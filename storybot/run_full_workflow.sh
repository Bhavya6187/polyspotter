#!/usr/bin/env bash
# Chained articlebot → claude edit → sync → publish workflow.
#
# 1. Runs `python storybot/articlebot.py` to produce a draft.
# 2. If a draft was produced (skip path produces no draft and exits the
#    workflow cleanly), invokes `claude -p` to edit the .md in-place.
# 3. Runs `python storybot/sync_article_from_md.py <run_id>` to push the
#    edits into Postgres (validates with articlebot's own validator).
# 4. Runs `python storybot/publish_article.py <run_id>` to post the tweet
#    and flip the row to 'published'.
#
# Any non-zero exit in steps 1, 3, or 4 aborts via set -e + pipefail
# before a tweet is posted. Step 2 (`claude -p`) failure also aborts —
# the draft is left in DB as 'draft' so the user can investigate, fix,
# and re-run sync + publish manually.
set -euo pipefail

# Always run from project root so `@storybot/...` mentions in the prompt
# resolve correctly inside Claude.
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
source venv/bin/activate

echo "[workflow] running articlebot.py"
output=$(python storybot/articlebot.py 2>&1 | tee /dev/tty)

# `[articlebot] draft run_id=<hex>` is printed only on the post path.
# A clean skip (no draft today) produces no such line and we exit 0 below.
# An articlebot error returns non-zero and set -e already aborted before
# this point — we never reach the grep on the error path.
run_id=$(echo "$output" \
    | grep -oP '\[articlebot\] draft run_id=\K[a-f0-9]+' || true)

if [[ -z "$run_id" ]]; then
    echo "[workflow] no draft produced (articlebot skipped or errored). Stopping."
    exit 0
fi

echo "[workflow] draft run_id=$run_id — invoking claude to edit"

prompt="Review and edit the articlebot draft with run_id=$run_id. The draft is at @storybot/articles/$run_id.md (article body, headline, subhead, and teaser tweet — all editable). The full agent transcript with every tool output the bot used as source data is at @storybot/live_runs/articlebot_$run_id.json — open it whenever you need to verify a number cited in the article.

Make your edits directly to the .md and improve both the article and the tweet. After your edits the workflow runs @storybot/sync_article_from_md.py, which re-runs articlebot's validator and aborts the publish if anything fails — so fix these before finishing:

1. FACT FIDELITY (most common failure). Every win-loss tuple in the body (any 'X-Y' or 'X–Y' shape where X+Y ≥ 10, e.g. '83-15', '577-331') must be reachable in the transcript's function_call_output items or the alerts payload. The bot has a known habit of inventing wallet records. If you can't verify a tuple in the transcript, either replace it with the actual numbers from there or rewrite the line to drop the specific stat. The same caution applies to dollar amounts, ROI %, and profit figures cited as wallet attributes.

2. OPENING. The first paragraph (everything before the first ## H2) must contain at least one concrete number token — a dollar amount, win-loss tuple, percentage, or cents price. Don't open with generic scene-setting.

3. HEADLINE vs SUBHEAD. The subhead must add new context, not restate the headline (Jaccard similarity on content words is checked).

4. STRUCTURE. Body must keep its 2–3 ## H2 sections, stay within the word-count band already set by the bot, and contain at least one polyspotter.com link.

Refer to validate_article_decision in @storybot/articlebot.py for the exact rules if anything is unclear. I want to run @storybot/publish_article.py with this id directly after you finish, so the article must be in a publishable state."

claude -p "$prompt" --dangerously-skip-permissions

echo "[workflow] syncing edited .md back to Postgres"
python storybot/sync_article_from_md.py "$run_id"

echo "[workflow] publishing"
python storybot/publish_article.py "$run_id"

echo "[workflow] done. run_id=$run_id"
