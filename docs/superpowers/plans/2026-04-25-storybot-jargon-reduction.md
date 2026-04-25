# Storybot Jargon Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply three coordinated edits to `SYSTEM_PROMPT` in `storybot/storybot.py` so storybot threads read clearly to a casual reader without losing punch for a sharp one — implementing the design in [docs/superpowers/specs/2026-04-25-storybot-jargon-reduction-design.md](../specs/2026-04-25-storybot-jargon-reduction-design.md).

**Architecture:** Prompt-only change. Six sequential `Edit` operations on a single file (`storybot/storybot.py`), all inside the `SYSTEM_PROMPT` f-string in the "Hard style rules" block (lines ~847-911 in the pre-edit file). All six edits land in one atomic commit because the prompt would be internally inconsistent at any intermediate state (e.g. banning "stacked" while another bullet still recommends it). Verification is empirical: `py_compile` for syntax, then `STORYBOT_DRY_RUN=true python storybot.py` inspection against a checklist.

**Tech Stack:** Python 3.13, no test framework involvement (prompt content has no unit-testable behavior — verification is dry-run inspection per the spec's verification plan).

**Note on TDD:** This plan deviates from the standard write-test-first pattern because the change is prompt content, not code with behavior. There is no programmatic assertion that captures "the model uses less jargon." The discipline here is: edit, syntax-check, dry-run, eyeball against checklist, iterate if needed, commit.

**Note on workspace:** The current `git status` shows an unrelated modified file (`storybot/twitter_simple.py`). The edits in this plan only touch `storybot/storybot.py`, so they don't conflict at the file level — but the executor MUST stage `storybot/storybot.py` by name (not `git add .`) when committing, to keep the unrelated change out of the commit.

---

## File Structure

Single file modified:
- **Modify:** `storybot/storybot.py` — exactly one block (`SYSTEM_PROMPT` "Hard style rules") changed by six independent `Edit` operations, in file-top-to-bottom order so that anchors used later in the plan don't shift relative to earlier edits.

No new files. No test files. No other source files touched.

---

### Task 1: Apply Edit 1 — Voice line rewrite

**Files:**
- Modify: `storybot/storybot.py` (the `- Voice:` bullet currently at lines 861-864)

- [ ] **Step 1: Read the target file location**

Run:

```
Read storybot/storybot.py offset=861 limit=4
```

Expected: the four lines beginning `- Voice: crypto-twitter / betting-twitter — the way a sharp trader …`. Confirm the text matches the `old_string` in the next step before applying. If it doesn't match (e.g. someone reformatted), STOP and reconcile.

- [ ] **Step 2: Apply the Edit**

Use the `Edit` tool with these EXACT strings (preserving the leading hyphen, two-space continuation indent, and the unicode em-dash `—`):

`old_string`:

```
- Voice: crypto-twitter / betting-twitter — the way a sharp trader
  would text a friend about what they just saw. Confident, punchy, a
  little playful when warranted. NOT Wall Street research, NOT a press
  release, NOT an internal analyst log line. Same voice across every tweet.
```

`new_string`:

```
- Voice: smart financial-twitter — Matt Levine writing about
  Polymarket, not a desk trader Slack. Confident, punchy, a little
  playful when warranted. The reader is a curious adult who follows
  the news but does NOT speak desk slang — they should never need a
  glossary to follow you. NOT Wall Street research, NOT a press
  release, NOT an internal analyst log line, and NOT trader-chat
  shorthand ("clip," "lifted," "trimming," "wall," "the sharp"). Same
  voice across every tweet.
```

- [ ] **Step 3: No commit yet**

The six edits are coordinated and commit together at Task 9. Do NOT run `git commit` here.

---

### Task 2: Apply Edit 3b part 1 — Update "deployed capital" replacement

The original line suggests `"stacked"` as a replacement, but Task 5 (Edit 3a) bans `"stacked"`. This edit fixes the inconsistency. Done before Task 3 (the `Edit 2` insertion) because Task 3's anchor uses this line as part of its `old_string` — so Task 2 must run first to make Task 3's anchor accurate.

**Files:**
- Modify: `storybot/storybot.py` (the `"deployed capital"` line currently at line 885)

- [ ] **Step 1: Apply the Edit**

`old_string` (note the eight spaces between `"deployed capital"` and the arrow — copy them exactly):

```
    "deployed capital"        → "spent" / "bought" / "stacked"
```

`new_string`:

```
    "deployed capital"        → "spent" / "bought"
```

- [ ] **Step 2: No commit yet**

---

### Task 3: Apply Edit 2 — Insert "first-use unpack" rule

Inserts a new bullet between the "internal-tool jargon" bullet (which ends with the `"deployed capital"` line just updated by Task 2) and the "Analyst-speak is also BANNED" bullet (which begins the next block).

**Files:**
- Modify: `storybot/storybot.py` (insertion between current lines 885 and 886)

- [ ] **Step 1: Apply the Edit**

`old_string` (this is two adjacent existing lines — the post-Task-2 `"deployed capital"` line plus the `Analyst-speak` line that follows it):

```
    "deployed capital"        → "spent" / "bought"
- Analyst-speak is also BANNED. These phrases sound like a research
```

`new_string` (inserts the new bullet between them; preserves the f-string interpolation `{TWEET_MAX_CHARS}`):

```
    "deployed capital"        → "spent" / "bought"
- First-use unpack. The first time a thread leans on a piece of
  insider machinery — a bet line, an order-book artifact, a
  track-record shorthand — give the reader a half-second of frame.
  After that, drop the framing and use the short form. The thread
  shouldn't *teach*, but it shouldn't make a casual reader google
  either.

  When to unpack:
  - Bet lines (sports totals, spreads, etc.). First mention names
    what the bet IS in plain English; the shorthand can take over after.
      ❌ "piled $75k into Red Sox/Orioles Under 7.5 near first pitch"
      ✅ "piled $75k into Under 7.5 — i.e. betting the Red Sox and
          Orioles combine for fewer than 8 runs — right before first pitch"
      Subsequent tweets in the same thread: "the Under" is fine.
  - Track-record shorthand. "29-4" is opaque on its own.
      ❌ "A 29-4 wallet up $4.4M"
      ✅ "An account that's hit 29 of its last 33 bets and is up $4.4M"
      Subsequent: "that wallet" / "the same account."
  - Order-book artifacts (walls, depth, fills). First mention names
    what's actually sitting on the book.
      ❌ "a big wall at 57¢"
      ✅ "a big stack of sell orders parked at 57¢" (or: "a chunk of
          resting offers at 57¢")
      Subsequent: "that 57¢ level" / "the wall" once the reader has
      the picture.
  - Polymarket prices. The reader doesn't need a probability lecture,
    but the *first* time a price carries the story, gesture at what
    it means. Once is enough.
      ❌ "bought Over at 47¢"
      ✅ "bought Over at 47¢ (the market was giving it a coin-flip)"
          — or pair the price with its implied read in the surrounding
          sentence.
      Subsequent: "47¢," "44¢," "the mid-50s" — terse is fine.

  What this is NOT:
  - NOT a license to add an explainer sentence to every tweet. One
    frame per concept, per thread.
  - NOT a parenthetical glossary on every term. If a term is
    self-explanatory in context ("first pitch," "$118k bet," "won 80%
    of his bets"), don't unpack it.
  - NOT an excuse to inflate tweet count. Same 3-5 cap. If unpacking
    pushes a tweet over {TWEET_MAX_CHARS} chars, cut a number, not
    the unpack.
- Analyst-speak is also BANNED. These phrases sound like a research
```

- [ ] **Step 2: Sanity-check the f-string interpolation**

The new copy contains exactly ONE pair of curly braces: `{TWEET_MAX_CHARS}`. Confirm visually that no other `{` or `}` snuck in (apostrophes inside ❌/✅ examples are fine; only braces matter for f-strings).

- [ ] **Step 3: No commit yet**

---

### Task 4: Apply Edit 3b part 2 — Update "pile-in" replacement

Same pattern as Task 2: an existing line suggests `"stacked in"` as a replacement, but Task 5 bans it. Fix.

**Files:**
- Modify: `storybot/storybot.py` (the `"coordinated burst" / "pile-in"` line, currently at line 889 in the pre-edit file)

- [ ] **Step 1: Apply the Edit**

`old_string` (note the five spaces between `"pile-in"` and the arrow):

```
    "coordinated burst" / "pile-in"     → "all bought at once" / "stacked in"
```

`new_string`:

```
    "coordinated burst" / "pile-in"     → "all bought at once" / "all hit it within minutes"
```

- [ ] **Step 2: No commit yet**

---

### Task 5: Apply Edit 3a — Append to ban list

Appends ten new entries to the end of the "Analyst-speak is also BANNED" block. The anchor is the existing last line of that block (`"positioning"`) plus the first line of the next block (`- Rewrite table`).

**Files:**
- Modify: `storybot/storybot.py` (insertion between the `"positioning"` line and `- Rewrite table`)

- [ ] **Step 1: Apply the Edit**

`old_string`:

```
    "positioning"                       → "betting" / "buying"
- Rewrite table — internalize the voice shift:
```

`new_string`:

```
    "positioning"                       → "betting" / "buying"
    "the sharp" / "sharp on the other side"  → name the wallet by what makes it notable ("the +$2M wallet", "the 29-4 account") OR just "another account"
    "trimming" / "trimmed"                   → "selling some of their position" / "cutting their bet"
    "lifted" / "getting lifted"              → "kept getting bought" / "buyers kept paying up for it"
    "clip" (as in "$49k clip")               → "$49k bet" / "$49k buy"
    "P&L wallet" / "$2M P&L wallet"          → "an account up $2M" / "a wallet up $2M lifetime"
    "leaning on a number"                    → "betting heavily that the line is wrong" / show the conviction via a fact
    "stacked" / "stacked in" / "stacking"    → "bought" / "bet"
    "hit BUY" / "hit the bid"                → "bought" / "sold" — say which side in plain English
    "round-tripped"                          → "went up and came back" / "ripped and faded"
    "the book" / "depth on the book"         → "the orders sitting on the market" / "what's offered"
- Rewrite table — internalize the voice shift:
```

Two intentional refinements vs. the spec text, both same direction:
- `"lifted"` replacement: spec offered `"kept getting bought" / "buyers kept hitting it"`. Plan uses `"kept getting bought" / "buyers kept paying up for it"` because "hitting it" is itself borderline trader slang.
- `"stacked"` replacement: spec offered `"bought" / "bet" / "piled in"`. Plan drops `"piled in"` because the same prompt block bans `"pile-in"` (noun) as analyst-speak; offering its verb cousin as a recommended replacement is internally confusing.

- [ ] **Step 2: No commit yet**

---

### Task 6: Apply Edit 3c — Replace rewrite table

Replaces the four ❌/✅ pairs with six new pairs that demonstrate the new voice. The current ✅ examples actively model phrases now banned by Task 5 (e.g. `"stacked $34k"`, `"hit BUY"`) — they MUST be replaced, not augmented.

**Files:**
- Modify: `storybot/storybot.py` (the rewrite table, currently lines 896-911)

- [ ] **Step 1: Apply the Edit**

`old_string` (this is the entire current rewrite table; preserve the blank lines between pairs and the 8-space continuation indent):

```
- Rewrite table — internalize the voice shift:
    ❌ "12 buys from 8 wallets for $33.9k, mostly at 54-59¢"
    ✅ "8 wallets stacked $34k on Yankees in the first 18 min — mostly around 55¢"

    ❌ "Price picked a winner fast. Boston was 40.5¢ 1 min after first
        pitch and 61.5¢ by minute 35."
    ✅ "Then it just flipped. Boston went from the low-40s to the low-60s
        in half an hour."

    ❌ "A coordinated 8-wallet push bought $33.9k of Yankees into a
        major pregame volume spike."
    ✅ "Before first pitch, 8 different wallets all hit BUY on the
        Yankees. $34k in, nobody on the other side."

    ❌ "That wallet's lifetime record is just 597-513 and down $5.8k."
    ✅ "And that wallet? Barely above .500 lifetime, down $5.8k."
```

`new_string`:

```
- Rewrite table — internalize the voice shift:
    ❌ "12 buys from 8 wallets for $33.9k, mostly at 54-59¢"
    ✅ "Eight different accounts bought into the Yankees in the first 18
        minutes — about $34k total, all paying somewhere in the mid-50s."

    ❌ "Price picked a winner fast. Boston was 40.5¢ 1 min after first
        pitch and 61.5¢ by minute 35."
    ✅ "Then the market made up its mind. Boston went from the low-40s
        to the low-60s in about half an hour — the kind of move you
        usually only see after a real event."

    ❌ "A coordinated 8-wallet push bought $33.9k of Yankees into a
        major pregame volume spike."
    ✅ "Before first pitch, eight separate accounts all bet on the
        Yankees within minutes of each other — $34k in, basically
        nobody on the other side. The volume on this market 9x'd in
        the same window."

    ❌ "That wallet's lifetime record is just 597-513 and down $5.8k."
    ✅ "And that account? It's basically been a coin flip across more
        than a thousand bets — and down about $6k overall."

    ❌ "A 29-4 wallet up $4.4M kept hammering the Under."
    ✅ "An account that's hit 29 of its last 33 bets — up $4.4M
        lifetime — kept hammering the Under."

    ❌ "Meanwhile the other sharp wasn't random. A $2.0M P&L wallet bought
        Over at 47¢ — then sold some at 44¢ as the Under kept getting lifted."
    ✅ "On the other side: not a random buyer either. An account up $2M
        lifetime bought Over at 47¢ — then sold some of it at 44¢ about
        half an hour later, as buyers kept lifting the Under."
```

- [ ] **Step 2: No commit yet**

---

### Task 7: Verify the prompt parses

Now that all six edits are applied, confirm the file still compiles. The prompt is an f-string with `{TWEET_MAX_CHARS}` and `{TWEET_URL_CHARS}` interpolations, so any stray `{` or `}` introduced by the new copy would crash compilation here.

**Files:**
- Read-only: `storybot/storybot.py`

- [ ] **Step 1: Run py_compile**

Run from the project root:

```bash
python -m py_compile storybot/storybot.py
```

Expected: silent success (exit 0, no output).

If it fails with a `SyntaxError` mentioning curly braces in an f-string, find the offending entry in the new ban list or rewrite table and escape any literal brace as `{{` / `}}`. Then re-run until clean.

- [ ] **Step 2: Visual sanity-check the modified block**

Run:

```
Read storybot/storybot.py offset=860 limit=120
```

Skim for: voice line is the new one; first-use unpack bullet is present and well-formed; ban list contains the ten new entries; rewrite table has six pairs. If anything looks malformed (e.g. a stray blank line, broken indent, or two bullets accidentally fused), fix with another `Edit` before proceeding.

---

### Task 8: Dry-run inspection

The empirical verification step. The change has no unit test that captures "fewer jargon"; the only way to confirm it works is to run the bot in dry-run mode and read the output threads against the spec's checklist.

**Files:**
- Read-only: `storybot/storybot.py`, `storybot/dry_runs/*.json`

- [ ] **Step 1: Run dry-run #1**

Run from the project root with the venv activated:

```bash
source venv/bin/activate
cd storybot && STORYBOT_DRY_RUN=true python storybot.py
```

Expected: a `posted` event at the end with `tweet_count` of 3-5 and tweet bodies printed to stdout. A skip is also acceptable — that means the picker didn't find a story; just re-run later or seed manually.

- [ ] **Step 2: Run dry-run #2**

Same command again. We want at least two output threads to spot-check, because LLM output varies run-to-run and a single sample can mask drift.

- [ ] **Step 3: Inspect each thread against this checklist**

For each thread (read directly from stdout, or open the saved transcript at `storybot/dry_runs/<run_id>.json`):

1. **No banned phrases.** Scan the tweet bodies for any of: `clip`, `trimming`, `trimmed`, `lifted` (in the trader-chat sense — "buyers kept lifting" stays banned, but a literal description is OK), `the sharp`, `sharp on the other side`, `stacked`, `stacked in`, `P&L wallet`, `wall` (as a synonym for "stack of sell orders"), `leaning on a number`, `hit BUY`, `hit the bid`, `round-tripped`, `the book`, `depth on the book`. If any appear, the prompt change didn't take — go back to Step 3 of Task 1 and re-verify the edits landed.

2. **First-use unpack visible.** If the thread mentions a sports bet line (e.g. "Under 7.5"), at least ONE tweet in the thread frames it in plain English. If the thread mentions a track-record shorthand (e.g. "29-4"), it's unpacked at least once. (Subsequent terse mentions are expected and fine.)

3. **No length violations.** The validator already enforces ≤ 280 chars per tweet (`storybot/storybot.py:1385-1387`), so this should be impossible to violate at runtime — but visually confirm the threads don't read like the model truncated mid-sentence.

4. **Voice still feels punchy.** Subjective. The threads should still read like financial-Twitter, not a Wikipedia entry. If they read as over-explainerish, the "What this is NOT" guards in the first-use unpack rule probably need tightening (re-edit Task 3 before committing).

5. **Validators pass.** No banned-CTA phrases ("in bio", "full breakdown", "link below", "link in bio") in any tweet. The final tweet contains a `polyspotter.com` URL. No URLs in tweets 1..N-1. No `@mentions`. (All of these are enforced by `validate_decision()` at runtime — if a dry-run completes successfully with `decision=post`, validators passed by definition.)

- [ ] **Step 4: Decide go / no-go**

If both dry-runs pass the checklist, proceed to Task 9.

If either dry-run fails the checklist, do NOT commit. Use this failure-to-task mapping to know which edit to revisit:

| Failure mode | Likely culprit edit | What to tighten |
|---|---|---|
| Banned phrase from the new ban list still appears in tweets (e.g. "clip," "stacked," "the sharp") | Task 5 | Either the ban list entry didn't land — re-Read the file and confirm — or the phrase needs an inline mention in Task 1's voice line so it's flagged earlier in the prompt. |
| Tweet uses an insider term without unpacking (e.g. raw "Under 7.5" with no plain-English frame in any tweet of the thread) | Task 3 | The "When to unpack" sub-bullets aren't strong enough. Promote one sub-bullet's example into the body of Task 1's voice line as a positive ✅ example. |
| Tweets over-explain — every tweet has a parenthetical glossary, voice reads as "explainer blog" not "punchy" | Task 3 | The "What this is NOT" sub-block is the guard. Tighten its first item — make "ONE frame per concept, per thread" a hard rule with a specific count (e.g. "no more than 2 unpacks across the whole thread"). |
| Rewrite-table examples themselves still demonstrate banned phrasing | Task 6 | Re-Read lines around the rewrite table; confirm the old four pairs were fully replaced, not appended-to. The tell: more than 6 ❌/✅ pairs in the rendered prompt. |
| `py_compile` fails with `KeyError` or `ValueError` mentioning braces | Task 3 | A literal `{` or `}` snuck into the new copy and is being treated as an f-string interpolation. Find the offending character and double it (`{{` / `}}`). |

After tightening, re-run both dry-runs (Steps 1-3) before re-attempting commit at Task 9.

---

### Task 9: Commit

**Files:**
- Stage: `storybot/storybot.py` (NOTHING ELSE — there is an unrelated dirty file `storybot/twitter_simple.py` that must NOT be included)

- [ ] **Step 1: Confirm only `storybot.py` is staged**

Run:

```bash
git add storybot/storybot.py
git status --short
```

Expected output should show `M  storybot/storybot.py` (staged) and ` M storybot/twitter_simple.py` (unstaged, unrelated). If `twitter_simple.py` shows as staged, run `git reset HEAD storybot/twitter_simple.py` to unstage it.

- [ ] **Step 2: Commit with a heredoc message**

Run:

```bash
git commit -m "$(cat <<'EOF'
storybot: rewrite voice + add first-use unpack rule + extend ban list

Re-aligns SYSTEM_PROMPT so threads read clearly to a casual reader without
losing punch for a sharp one. Three coordinated edits, all in the "Hard
style rules" block:

- Voice line: "sharp trader texting a friend" -> "smart financial-twitter,
  Matt Levine writing about Polymarket." Reader is a curious adult who
  follows the news and shouldn't need a glossary.
- First-use unpack rule: bet lines, track-record shorthand, order-book
  artifacts, and prices get framed in plain English on first mention,
  then can drop to short form for the rest of the thread.
- Ban list: adds trader-chat shorthand ("clip", "lifted", "trimming",
  "the sharp", "stacked", "P&L wallet", "leaning on a number",
  "hit BUY", "round-tripped", "the book"). Two existing entries that
  recommended now-banned replacements ("deployed capital -> stacked",
  "pile-in -> stacked in") updated. Rewrite-table examples replaced
  end-to-end so the demonstrations match the new voice.

Spec: docs/superpowers/specs/2026-04-25-storybot-jargon-reduction-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Confirm clean**

Run:

```bash
git log --oneline -3
git status --short
```

Expected: the new commit at the top of the log. `git status --short` should still show the unrelated `M storybot/twitter_simple.py` untouched.

- [ ] **Step 4: Done**

The implementation is complete. Future hourly runs of storybot will use the new prompt. If real-mode output drifts back toward jargon, the spec's "implementation order" section explicitly anticipates a follow-up tightening loop — that's a separate task, not part of this plan.
