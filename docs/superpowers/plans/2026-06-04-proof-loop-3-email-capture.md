# Proof Loop — Plan 3: Email Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture emails on the homepage — a `subscribers` table, a `POST /api/subscribe` endpoint, and an `EmailCapture` form in the scoreboard hero and at the foot of the feed.

**Architecture:** A new `subscribers` Postgres table (idempotent migration, mirrors the existing `_migrate_add_*` pattern). A `POST /api/subscribe` endpoint validates the email (regex), drops honeypot-flagged bot submissions silently, and idempotently upserts (`ON CONFLICT (email) DO NOTHING`); the DB write is a separate module-level function so it's unit-testable via monkeypatch (mirrors Plan 1's `_scoreboard_rows`). On the frontend, a `subscribeEmail()` client posts JSON, and an `EmailCapture` client component renders the form with idle/loading/done/error states plus a honeypot field.

**Tech Stack:** Python 3.13 + FastAPI + psycopg2 (backend); Next.js 15 / React 19 / Tailwind 4 (frontend). Backend tests via pytest (FastAPI TestClient + monkeypatch). **No frontend test harness** (only `next lint`, which is currently broken by a pre-existing eslint-9-vs-legacy-config issue) — verify the frontend with `npm run build`.

**Spec:** `docs/superpowers/specs/2026-06-04-homepage-proof-loop-design.md` (subsystem B, capture only).

**Explicitly OUT of scope (deferred):** the daily digest (`digest_worker.py`), the Resend send pipeline / `email_sender.py`, and the `GET /api/unsubscribe` endpoint (nothing sends mail yet, so there's nothing to unsubscribe from — the `unsubscribe_token` column is added now for forward-compat).

---

## File Structure

- **Modify** `backend/schema.sql` — add `subscribers` table DDL.
- **Modify** `backend/database.py` — register `_migrate_add_subscribers` in `init_db()`.
- **Modify** `backend/models.py` — add `SubscribeRequest`, `SubscribeResponse`.
- **Modify** `backend/app.py` — add `_save_subscriber()` + `POST /api/subscribe`.
- **Create** `backend/test_subscribe.py` — endpoint tests (monkeypatched DB write).
- **Modify** `frontend/src/lib/api.js` — add `subscribeEmail()`.
- **Create** `frontend/src/components/EmailCapture.jsx` — the form (client component).
- **Modify** `frontend/src/components/ScoreboardHero.jsx` — mount `EmailCapture` in both states.
- **Modify** `frontend/src/app/home-client.jsx` — mount a repeat `EmailCapture` at the foot of the feed.

---

## Task 1: `subscribers` table + migration

**Files:**
- Modify: `backend/schema.sql` (append)
- Modify: `backend/database.py` (`init_db` + new function)

- [ ] **Step 1: Append the table DDL to `backend/schema.sql`** (at the end of the file):

```sql
-- subscribers: homepage email captures. Idempotent on email. unsubscribe_token
-- is added now for forward-compat (no mail is sent yet). gen_random_uuid() is
-- built into Postgres 13+.
CREATE TABLE IF NOT EXISTS subscribers (
    id                SERIAL PRIMARY KEY,
    email             TEXT NOT NULL UNIQUE,
    source            TEXT,
    confirmed         BOOLEAN NOT NULL DEFAULT TRUE,
    unsubscribe_token UUID NOT NULL DEFAULT gen_random_uuid(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unsubscribed_at   TIMESTAMPTZ
);
```

- [ ] **Step 2: Add the migration function in `backend/database.py`** — after `_migrate_add_graded_calls`:

```python
def _migrate_add_subscribers(cur):
    """Create the subscribers table (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id                SERIAL PRIMARY KEY,
            email             TEXT NOT NULL UNIQUE,
            source            TEXT,
            confirmed         BOOLEAN NOT NULL DEFAULT TRUE,
            unsubscribe_token UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            unsubscribed_at   TIMESTAMPTZ
        )
    """)
```

- [ ] **Step 3: Call it from `init_db()`** — immediately after `_migrate_add_graded_calls(cur)`:

```python
            _migrate_add_subscribers(cur)
```

- [ ] **Step 4: Verify import**

Run: `cd backend && DATABASE_URL=postgres://x python -c "import database; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/schema.sql backend/database.py
git commit -m "feat(subscribe): add subscribers table + migration"
```

---

## Task 2: `POST /api/subscribe` endpoint + models

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/app.py`
- Create: `backend/test_subscribe.py`

- [ ] **Step 1: Add models to `backend/models.py`** (append; match the file's `BaseModel` style):

```python
class SubscribeRequest(BaseModel):
    email: str
    source: str | None = None
    hp: str | None = None   # honeypot — bots fill this; humans never see it


class SubscribeResponse(BaseModel):
    ok: bool
```

- [ ] **Step 2: Write the failing endpoint tests** — create `backend/test_subscribe.py`:

```python
from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


def _capture_saves(monkeypatch):
    """Replace the DB write with an in-memory recorder; returns the list."""
    saved = []
    monkeypatch.setattr(app_module, "_save_subscriber", lambda email, source: saved.append((email, source)))
    return saved


def test_subscribe_valid_email_saves(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "Person@Example.COM ", "source": "hero"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # normalized: trimmed + lowercased
    assert saved == [("person@example.com", "hero")]


def test_subscribe_invalid_email_rejected(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "not-an-email", "source": "hero"})
    assert resp.status_code == 400
    assert saved == []


def test_subscribe_honeypot_silently_accepted(monkeypatch):
    saved = _capture_saves(monkeypatch)
    resp = client.post("/api/subscribe", json={"email": "bot@example.com", "hp": "i am a bot"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert saved == []   # honeypot filled -> accepted silently, nothing saved
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest test_subscribe.py -v`
Expected: FAIL — 404 (route missing) or AttributeError on `_save_subscriber`.

- [ ] **Step 4: Implement in `backend/app.py`**

- Extend the existing `from models import (...)` block with `SubscribeRequest, SubscribeResponse`.
- Ensure `import re` and `HTTPException` are available at the top of `app.py` (FastAPI's `HTTPException` — check it's already imported; if not, add `from fastapi import HTTPException` consistent with the existing FastAPI imports). Confirm by reading the file before editing.
- Add near the other write endpoint (`ingest`):

```python
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _save_subscriber(email: str, source: str | None) -> None:
    """Idempotent insert of a subscriber. Separated out so tests can fake it."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO subscribers (email, source)
               VALUES (%s, %s)
               ON CONFLICT (email) DO NOTHING""",
            (email, source),
        )


@app.post("/api/subscribe", response_model=SubscribeResponse)
def subscribe(payload: SubscribeRequest):
    """Capture a homepage email signup. Honeypot-filtered, idempotent."""
    # A bot filled the hidden honeypot field — accept silently, save nothing.
    if payload.hp:
        return {"ok": True}
    email = (payload.email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    _save_subscriber(email, payload.source)
    return {"ok": True}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest test_subscribe.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/app.py backend/test_subscribe.py
git commit -m "feat(subscribe): POST /api/subscribe with validation + honeypot"
```

---

## Task 3: `subscribeEmail()` API client

**Files:**
- Modify: `frontend/src/lib/api.js`

The existing `request()` helper only does GET. Add a dedicated POST function.

- [ ] **Step 1: Add the function** (after `fetchScoreboard`):

```javascript
export function subscribeEmail({ email, source, hp } = {}) {
  const url = new URL("/api/subscribe", BASE_URL);
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, source, hp }),
  }).then(async (res) => {
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `API error: ${res.status}`);
    }
    return res.json();
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.js
git commit -m "feat(subscribe): subscribeEmail API client (POST)"
```

---

## Task 4: `EmailCapture` component

**Files:**
- Create: `frontend/src/components/EmailCapture.jsx`

- [ ] **Step 1: Create `frontend/src/components/EmailCapture.jsx`**

```jsx
"use client";

import { useState } from "react";
import { subscribeEmail } from "../lib/api";

// Email signup form. `source` tags where the signup came from (e.g. "hero",
// "footer"). Includes an off-screen honeypot field to deter bots.
export default function EmailCapture({ source = "home" }) {
  const [email, setEmail] = useState("");
  const [hp, setHp] = useState(""); // honeypot — must stay empty for humans
  const [status, setStatus] = useState("idle"); // idle | loading | done | error
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    if (status === "loading") return;
    setStatus("loading");
    setError("");
    try {
      await subscribeEmail({ email, source, hp });
      setStatus("done");
      setEmail("");
    } catch (err) {
      setStatus("error");
      setError(err?.message || "Something went wrong — try again.");
    }
  }

  if (status === "done") {
    return (
      <p className="text-sm" style={{ color: "var(--bullish)" }}>
        ✓ You&rsquo;re on the list — we&rsquo;ll send the smart-money brief.
      </p>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2 sm:flex-row sm:items-center"
    >
      {/* Honeypot: visually hidden, off-screen; bots fill it, humans don't. */}
      <input
        type="text"
        name="company"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={hp}
        onChange={(e) => setHp(e.target.value)}
        style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
      />
      <input
        type="email"
        required
        placeholder="you@email.com"
        aria-label="Email address"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm"
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border)",
          color: "var(--text-primary)",
        }}
      />
      <button
        type="submit"
        disabled={status === "loading"}
        className="rounded-lg px-4 py-2 text-sm font-bold transition-opacity disabled:opacity-50"
        style={{ background: "var(--accent)", color: "var(--surface-0)" }}
      >
        {status === "loading" ? "Joining…" : "Get the brief"}
      </button>
      {status === "error" && (
        <span className="text-xs" style={{ color: "var(--bearish)" }} role="alert">
          {error}
        </span>
      )}
    </form>
  );
}
```

- [ ] **Step 2: Lint/build sanity** (lint is broken pre-existing; rely on build later)

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build completes (component is imported nowhere yet — that's fine, it compiles standalone once imported in Task 5).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EmailCapture.jsx
git commit -m "feat(subscribe): EmailCapture form component"
```

---

## Task 5: Mount EmailCapture in the hero and the feed footer

**Files:**
- Modify: `frontend/src/components/ScoreboardHero.jsx`
- Modify: `frontend/src/app/home-client.jsx`

- [ ] **Step 1: Add the import + capture block to `ScoreboardHero.jsx`**

At the top of `frontend/src/components/ScoreboardHero.jsx`, add the import:

```jsx
import EmailCapture from "./EmailCapture";
```

In the **cold-start** return (the `if (!window || gradedCount < MIN_GRADED)` branch), add the capture block right before the closing `</section>`, after the existing `<p>...</p>`:

```jsx
        <div className="mt-4 max-w-md">
          <EmailCapture source="hero" />
        </div>
```

In the **populated** return, add the same block right before the closing `</section>`, after the value-prop `<p>...</p>`:

```jsx
      <div className="mt-5 max-w-md">
        <p className="mb-2 text-xs" style={{ color: "var(--text-muted)" }}>
          Get the daily smart-money brief:
        </p>
        <EmailCapture source="hero" />
      </div>
```

- [ ] **Step 2: Add a footer capture to `home-client.jsx`**

In `frontend/src/app/home-client.jsx`, add the import near the other component imports:

```javascript
import EmailCapture from "../components/EmailCapture";
```

Then, in the returned JSX, immediately after the `</nav>` that closes the Pagination block and BEFORE `<EngagementToast />`, insert:

```jsx
      {/* Repeat email capture at the foot of the feed */}
      <section
        aria-label="Email signup"
        className="mt-8 rounded-2xl p-6 text-center"
        style={{ background: "var(--surface-card)", border: "1px solid var(--border)" }}
      >
        <p className="mb-3 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          Get the sharpest Polymarket bets in your inbox every morning.
        </p>
        <div className="mx-auto max-w-md">
          <EmailCapture source="footer" />
        </div>
      </section>
```

- [ ] **Step 3: Build (full verification)**

Run: `cd frontend && npm run build 2>&1 | tail -8`
Expected: build completes; no unused-import errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ScoreboardHero.jsx frontend/src/app/home-client.jsx
git commit -m "feat(subscribe): mount EmailCapture in hero + feed footer"
```

---

## Manual verification (after Task 5)

```bash
cd frontend && NEXT_PUBLIC_API_URL=https://api.polyspotter.com npm run dev
# open http://localhost:3000
```
- The hero shows an email field + "Get the brief" button (in both cold-start and populated states).
- A second capture block sits at the foot of the feed.
- Submitting a valid email shows the "✓ You're on the list" confirmation; an invalid email shows the inline error.

(Backend must be deployed with the `subscribers` migration for real submissions to persist; the endpoint returns 400 on malformed emails and 200 on success.)

---

## Self-Review Notes

- **Spec coverage (subsystem B, capture only):** `subscribers` table (Task 1) ✓; `POST /api/subscribe` with email validation + honeypot + idempotent upsert (Task 2) ✓; `subscribeEmail()` client (Task 3) ✓; `EmailCapture` form with states (Task 4) ✓; mounted in hero + feed footer (Task 5) ✓. **Deferred (stated):** digest, Resend pipeline, `/api/unsubscribe`.
- **No placeholders:** every step has complete, runnable code.
- **Type/shape consistency:** `_save_subscriber(email, source)` is the monkeypatch seam used by the tests; the `subscribers` columns match between `schema.sql`, the migration, and the INSERT; `SubscribeRequest` fields (`email`, `source`, `hp`) match what `subscribeEmail()` posts and what the endpoint reads.
- **Testing:** backend endpoint covered by 3 TestClient tests (valid normalized save, invalid 400, honeypot silent). Frontend has no test harness; verified via `npm run build`.

## Deferred to later

- Daily digest (`backend/digest_worker.py`) reusing articlebot content + scoreboard + receipts, sent via Resend (`backend/email_sender.py`), with `GET /api/unsubscribe`.
