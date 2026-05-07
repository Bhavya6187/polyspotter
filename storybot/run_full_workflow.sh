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

prompt="can you look at $run_id run of the @storybot/articlebot.py in folder @storybot/articles/ and tell me if there are any improvements we can make to the article there. make your edits to the article directly and improve both the article and the tweet. I want to be able to run @storybot/publish_article.py with this id directly after you are done with your edits"

claude -p "$prompt" --dangerously-skip-permissions

echo "[workflow] syncing edited .md back to Postgres"
python storybot/sync_article_from_md.py "$run_id"

echo "[workflow] publishing"
python storybot/publish_article.py "$run_id"

echo "[workflow] done. run_id=$run_id"
