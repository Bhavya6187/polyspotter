# Articlebot: chained articlebot → claude edit → publish workflow

**Date:** 2026-05-06
**Status:** Design
**Owner:** bhavya

## Problem

Today the article pipeline is two manual steps:

1. `python storybot/articlebot.py` — picks a story, researches it, drafts a
   ~600-word article and teaser tweet, writes a draft row to the `articles`
   table plus `storybot/articles/<run_id>.md` for review.
2. Human reads the .md, decides whether it's good, runs `python
   storybot/publish_article.py <run_id>`.

The user wants a third step inserted between draft and publish: **a Claude
Code editing pass** that critiques and improves the article and tweet
in-place, after which `publish_article.py` runs automatically. Single command;
walk away.

The naive way to wire this — a shell script that just chains the three —
breaks because the .md file is **not the source of truth** for what gets
published. Specifically:

- `publish_article.py` reads `tweet_text` from the Postgres `articles` table.
- The on-site article (rendered at `polyspotter.com/article/<date>/<slug>`)
  reads `body_markdown` from the same table.
- The .md file is a regenerated review artifact only — it contains the
  article body but **does not contain the tweet at all**.

So if Claude edits only the .md, the published tweet and on-site article
both come from the unchanged DB row. The edits don't take effect.

## Goals

- Single command runs the full chain: draft → Claude edit → publish.
- Claude edits a single human-readable file on disk, not the DB.
- Edits actually flow through to the published tweet and on-site article.
- Pre-publish validation still runs — Claude can't push an article that
  violates the existing rules (length bounds, banned phrases, missing
  polyspotter link, etc.).
- If any step fails (articlebot errors, Claude errors, validation fails),
  the pipeline aborts before posting a tweet.

## Non-goals

- Replacing the existing `publish_article.py` review-then-post model for
  manual runs — that path stays untouched.
- Re-running articlebot on validation failure. If sync fails validation, the
  workflow aborts and the human investigates.
- Editing anything other than headline, subhead, body, and tweet (cover
  chart, alert IDs, event slug all stay as-is).

## Design

Three components:

### 1. Add a tweet section to the .md file

Modify `_format_md_file` in `storybot/articlebot_storage.py` to include the
tweet as a delimited section. Layout becomes:

```
# {headline}

*{subhead}*

![cover](<run_id>.png)

{body}

---

## Tweet

{tweet_text}

---

run_id: {run_id} | event_slug: {slug} | alert_ids: [...]
posted_url: <fill in after publishing>
```

The tweet section is bracketed by horizontal-rule lines so it parses
deterministically — the body's own `## H2` sections (which the validator
already requires 3-4 of) live above the first `---`, and the metadata footer
lives below the second `---`. `## Tweet` is the only `## ` heading in the
"between rules" region.

Existing draft files in `storybot/articles/` won't have this section. The
sync script (component 2) handles that as an error case — it tells the user
to re-run articlebot. We don't backfill old drafts; this is a forward-only
change.

### 2. New `storybot/sync_article_from_md.py`

Parses `storybot/articles/<run_id>.md` and `UPDATE`s the matching `articles`
row's `headline`, `subhead`, `body_markdown`, `tweet_text`, and `word_count`.
Aborts with a non-zero exit if:

- The row doesn't exist or status != 'draft'.
- Any of the four fields can't be parsed from the .md.
- The reconstructed decision dict fails `validate_article_decision` (reused
  from `articlebot.py` — covers length bounds, banned phrases, polyspotter
  link, H2 count, tweet length).

Parsing approach (regex-based, no markdown library):

- **Headline** — first line matching `^# (.+)$`.
- **Subhead** — first line matching `^\*([^*].*)\*$`.
- **Body** — text from after subhead/cover line to the first `^---$`,
  stripped of leading/trailing blank lines.
- **Tweet** — text between `^## Tweet$` and the next `^---$`, stripped.

`cover_alt_text` and `alert_ids` are not in the .md — they stay as the DB
row's existing values. `event_slug` is in the metadata footer but isn't
something a human should be retconning, so we ignore the footer values and
use the DB's existing `event_slug` for validation.

The script reuses `validate_article_decision` by constructing a synthetic
`decision` dict from the parsed .md plus the existing DB row's
`alert_ids` / `event_slug`. This keeps validation logic in one place.

### 3. New `storybot/run_full_workflow.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."   # project root, so @storybot/... resolves
source venv/bin/activate

# 1. Draft
output=$(python storybot/articlebot.py 2>&1 | tee /dev/tty)

# 2. Extract run_id (only printed on successful draft, not skip/error)
run_id=$(echo "$output" \
    | grep -oP '\[articlebot\] draft run_id=\K[a-f0-9]+' || true)

if [[ -z "$run_id" ]]; then
    echo "[workflow] articlebot did not produce a draft (skipped or errored). Stopping."
    exit 0
fi

echo "[workflow] draft run_id=$run_id — invoking claude to edit"

# 3. Claude editing pass (literal user prompt, run_id substituted in)
prompt="can you look at $run_id run of the @storybot/articlebot.py in folder @storybot/articles/ and tell me if there are any improvements we can make to the article there. make your edits to the article directly and improve both the article and the tweet. I want to be able to run @storybot/publish_article.py with this id directly after you are done with your edits"

claude -p "$prompt" --dangerously-skip-permissions

# 4. Sync edited .md back to DB (validates; aborts on failure)
python storybot/sync_article_from_md.py "$run_id"

# 5. Publish
python storybot/publish_article.py "$run_id"
```

Key choices:

- **`set -euo pipefail`** — any non-zero in the chain aborts before the
  publish step. We never tweet a half-broken article.
- **`tee /dev/tty`** while capturing — user sees articlebot's live progress;
  we still get the stdout to grep.
- **`--dangerously-skip-permissions`** — required for non-interactive Edit.
  Acceptable here because the prompt is fixed by us, not user-supplied, and
  the working directory is the user's own polybot checkout.
- **Skip path is exit 0, not 1** — articlebot legitimately skipping (no
  story worth running today) is a normal outcome, not a workflow failure.
- **`@`-mentions in the prompt** — preserved verbatim from the user's
  request; Claude Code resolves them in `-p` mode the same as interactive.

## Error handling

| Failure | Outcome |
|---|---|
| articlebot exits 1 (validation, agent error, etc.) | `pipefail` aborts. No claude, no publish. |
| articlebot exits 0 with skip (no draft line in stdout) | Workflow logs "no draft" and exits 0. |
| `claude -p` errors | `set -e` aborts. Draft is left in DB as `draft`; user can investigate, re-run sync+publish manually, or delete. |
| Claude's edits fail validation in sync step | Sync script exits 1, `set -e` aborts. Same recovery as above. |
| publish_article.py errors | Existing behavior unchanged — exits 1, draft stays as `draft` in DB. |

In all error paths the .md file on disk reflects whatever Claude last wrote;
the DB row reflects either the original articlebot draft (if sync didn't
run) or the synced version (if sync ran but publish failed).

## Files touched

- `storybot/articlebot_storage.py` — extend `_format_md_file` to include the
  `## Tweet` section bracketed by `---` rules.
- `storybot/sync_article_from_md.py` — **new**, ~80 lines.
- `storybot/run_full_workflow.sh` — **new**, ~25 lines, `chmod +x`.
- `storybot/articlebot.py` — no change. `validate_article_decision` stays
  where it is; sync imports it.

## Tests

- `test/test_articlebot_storage.py` (extend if it exists, otherwise add) —
  `_format_md_file` round-trips through the sync parser cleanly.
- `test/test_sync_article_from_md.py` (new) — happy path, missing tweet
  section, malformed headline, validation failure (e.g. body too short),
  draft-not-found, status != 'draft'.

The shell script and the live `claude -p` call are not unit-tested; manual
end-to-end on a dry run.

## Out of scope

- Backfilling the tweet section into existing draft .md files in
  `storybot/articles/`. Old drafts won't have it; sync will reject them with
  a clear error. The user re-runs articlebot for a fresh draft.
- Letting Claude edit cover_alt_text, alert_ids, or the cover chart spec.
  Those stay in the DB row from articlebot's original output.
- Adding a "review and confirm" step before publish_article runs. The user
  explicitly chose fully automatic.
