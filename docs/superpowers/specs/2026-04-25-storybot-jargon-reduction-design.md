# Storybot — Jargon Reduction for Mixed Audience

**Date:** 2026-04-25
**Status:** Approved, pending implementation plan
**Affects:** [storybot/storybot.py](../../../storybot/storybot.py) — `SYSTEM_PROMPT` only

## Goal

Make storybot threads readable by a mixed audience — a casual reader can follow without a glossary, a sharp reader doesn't feel talked down to. Today the prompt actively *teaches* trader/desk slang ("clip", "trimming", "lifted", "wall", "the sharp", "P&L wallet", "stacked", "hit BUY"), so dry-run output reads like an internal trading-floor chat. The voice instruction, the rewrite-table, and the ban list all currently pull in the same wrong direction; they need to be re-aligned to pull in the new direction together.

Reference reader: someone who follows the news, isn't a trader, and shouldn't need to google to follow a tweet. Stylistic North Star: mainstream finance Twitter (Matt Levine, Joe Weisenthal) — punchy, confident, occasionally playful, but always self-explanatory on first read.

## Non-goals

- No changes to detection strategies, query/compressor pipeline, picker prompt, validators, posting code, or backend.
- No change to thread structure (3-5 tweets, hook/body/payoff, reply chain).
- No change to character cap (280) or URL counting (`TWEET_URL_CHARS = 23`).
- No change to fact-fidelity rules.
- No new prediction-market explainer paragraphs in every tweet — this is not "audience C" (true layman). The reader is assumed to know what a bet is.
- No prompt restructuring beyond the three coordinated edits below.

## Audience target

Audience D from brainstorming: **mixed**. A layman can follow; a sharp reader doesn't feel talked down to. This is the hardest target — pure layman would be easier (just over-explain everything) and pure sharp would be easier (write desk slang). The mixed target requires *one* frame per concept per thread, then drop it.

## The three coordinated edits

All three edits live in `SYSTEM_PROMPT` in [storybot/storybot.py](../../../storybot/storybot.py). They MUST be made together — each one alone leaves the prompt internally inconsistent (e.g. banning "stacked" while the rewrite-table still demonstrates "stacked $34k" as the ✅ answer).

### Edit 1 — Voice line rewrite

**Location:** [storybot/storybot.py:861-864](../../../storybot/storybot.py#L861-L864) — the bullet beginning `- Voice:` inside the "Hard style rules" block.

**Current text:**

> Voice: crypto-twitter / betting-twitter — the way a sharp trader would text a friend about what they just saw. Confident, punchy, a little playful when warranted. NOT Wall Street research, NOT a press release, NOT an internal analyst log line. Same voice across every tweet.

**Replace with:**

> Voice: smart financial-twitter — Matt Levine writing about Polymarket, not a desk trader Slack. Confident, punchy, a little playful when warranted. The reader is a curious adult who follows the news but does NOT speak desk slang — they should never need a glossary to follow you. NOT Wall Street research, NOT a press release, NOT an internal analyst log line, and NOT trader-chat shorthand ("clip," "lifted," "trimming," "wall," "the sharp"). Same voice across every tweet.

**Why this carries the most weight:** the rewrite-table examples and the ban list inherit their tone from this paragraph. If the voice line still says "sharp trader texting a friend," the model will route around any specific banned phrase by inventing a synonym. Replacing the framing reader (the "friend") with a curious adult who doesn't speak desk slang changes the search space, not just the filter.

### Edit 2 — Add first-use unpack rule

**Location:** insert as a new bullet inside "Hard style rules", immediately after the existing "NO internal-tool jargon" bullet (the one ending around [storybot/storybot.py:885](../../../storybot/storybot.py#L885) with `"deployed capital" → "spent" / "bought" / "stacked"` — note: that final replacement ALSO needs updating, see Edit 3).

**Insert:**

> - **First-use unpack.** The first time a thread leans on a piece of insider machinery — a bet line, an order-book artifact, a track-record shorthand — give the reader a half-second of frame. After that, drop the framing and use the short form. The thread shouldn't *teach*, but it shouldn't make a casual reader google either.
>
>   When to unpack:
>   - **Bet lines** (sports totals, spreads, etc.). First mention names what the bet IS in plain English, then the shorthand can take over.
>     - ❌ "piled $75k into Red Sox/Orioles Under 7.5 near first pitch"
>     - ✅ "piled $75k into Under 7.5 — i.e. betting the Red Sox and Orioles combine for fewer than 8 runs — right before first pitch"
>     - Subsequent tweets in the same thread: "the Under" is fine.
>   - **Track-record shorthand**. "29-4" is opaque on its own.
>     - ❌ "A 29-4 wallet up $4.4M"
>     - ✅ "An account that's hit 29 of its last 33 bets and is up $4.4M"
>     - Subsequent: "that wallet" / "the same account."
>   - **Order-book artifacts** (walls, depth, fills). First mention names what's actually sitting on the book.
>     - ❌ "a big wall at 57¢"
>     - ✅ "a big stack of sell orders parked at 57¢" (or: "a chunk of resting offers at 57¢")
>     - Subsequent: "that 57¢ level" / "the wall" once the reader has the picture.
>   - **Polymarket prices**. The reader doesn't need a probability lecture, but the *first* time a price carries the story, gesture at what it means. Once is enough.
>     - ❌ "bought Over at 47¢"
>     - ✅ "bought Over at 47¢ (the market was giving it a coin-flip)" — or pair the price with its implied read in the surrounding sentence.
>     - Subsequent: "47¢," "44¢," "the mid-50s" — terse is fine.
>
>   What this is NOT:
>   - NOT a license to add an explainer sentence to every tweet. One frame per concept, per thread.
>   - NOT a parenthetical glossary on every term. If a term is self-explanatory in context ("first pitch," "$118k bet," "won 80% of his bets"), don't unpack it.
>   - NOT an excuse to inflate tweet count. Same 3-5 cap. If unpacking pushes a tweet over 280 chars, cut a number, not the unpack.

**Trade-off explicitly accepted:** unpacks cost characters. A tweet that today reads "A 29-4 wallet up $4.4M kept hammering Red Sox/Orioles Under" (96 chars) becomes ~150 chars after unpacking. That fits inside 280, but the model will need to spend its number-budget more carefully. The "if unpacking pushes a tweet over 280, cut a number, not the unpack" rule makes the priority unambiguous.

### Edit 3 — Expanded ban list + refreshed rewrite table

**Location:** [storybot/storybot.py:886-911](../../../storybot/storybot.py#L886-L911) — the "Analyst-speak is also BANNED" block plus the "Rewrite table" block.

**3a. Append to the analyst-speak ban list** (insert after the current `"positioning" → "betting" / "buying"` line at [storybot/storybot.py:895](../../../storybot/storybot.py#L895)):

```
    "the sharp" / "sharp on the other side"  → name the wallet by what makes it notable ("the +$2M wallet", "the 29-4 account") OR just "another account"
    "trimming" / "trimmed"                   → "selling some of their position" / "cutting their bet"
    "lifted" / "getting lifted"              → "kept getting bought" / "buyers kept hitting it"
    "clip" (as in "$49k clip")               → "$49k bet" / "$49k buy"
    "P&L wallet" / "$2M P&L wallet"          → "an account up $2M" / "a wallet up $2M lifetime"
    "leaning on a number"                    → "betting heavily that the line is wrong" / show the conviction via a fact
    "stacked" / "stacked in" / "stacking"    → "bought" / "bet" / "piled in"
    "hit BUY" / "hit the bid"                → "bought" / "sold" — say which side in plain English
    "round-tripped"                          → "went up and came back" / "ripped and faded"
    "the book" / "depth on the book"         → "the orders sitting on the market" / "what's offered"
```

**3b. Fix two existing entries whose right-hand sides suggest now-banned phrases.** Edit 3a bans `"stacked"` and `"stacked in"`, but two existing entries currently recommend those exact phrases as replacements. Both must be updated to keep the prompt internally consistent.

- At [storybot/storybot.py:885](../../../storybot/storybot.py#L885) (in the "internal-tool jargon" block):
  - **Current:** `"deployed capital"         → "spent" / "bought" / "stacked"`
  - **Replace with:** `"deployed capital"         → "spent" / "bought"`
- At [storybot/storybot.py:889](../../../storybot/storybot.py#L889) (in the "analyst-speak" block):
  - **Current:** `"coordinated burst" / "pile-in"     → "all bought at once" / "stacked in"`
  - **Replace with:** `"coordinated burst" / "pile-in"     → "all bought at once" / "all hit it within minutes"`

**3c. Replace the rewrite table** ([storybot/storybot.py:896-911](../../../storybot/storybot.py#L896-L911)) — the existing four ❌/✅ pairs ✅-side currently demonstrates the desk-slang voice we're now banning ("stacked $34k", "hit BUY", "Boston was 40.5¢"). Replace with six pairs that demonstrate the new voice:

```
- Rewrite table — internalize the voice shift:
    ❌ "12 buys from 8 wallets for $33.9k, mostly at 54-59¢"
    ✅ "Eight different accounts bought into the Yankees in the first 18 minutes — about $34k total, all paying somewhere in the mid-50s."

    ❌ "Price picked a winner fast. Boston was 40.5¢ 1 min after first
        pitch and 61.5¢ by minute 35."
    ✅ "Then the market made up its mind. Boston went from the low-40s
        to the low-60s in about half an hour — the kind of move you usually
        only see after a real event."

    ❌ "A coordinated 8-wallet push bought $33.9k of Yankees into a
        major pregame volume spike."
    ✅ "Before first pitch, eight separate accounts all bet on the Yankees
        within minutes of each other — $34k in, basically nobody on the
        other side. The volume on this market 9x'd in the same window."

    ❌ "That wallet's lifetime record is just 597-513 and down $5.8k."
    ✅ "And that account? It's basically been a coin flip across more than
        a thousand bets — and down about $6k overall."

    ❌ "A 29-4 wallet up $4.4M kept hammering the Under."
    ✅ "An account that's hit 29 of its last 33 bets — up $4.4M lifetime —
        kept hammering the Under."

    ❌ "Meanwhile the other sharp wasn't random. A $2.0M P&L wallet bought
        Over at 47¢ — then sold some at 44¢ as the Under kept getting lifted."
    ✅ "On the other side: not a random buyer either. An account up $2M
        lifetime bought Over at 47¢ — then sold some of it at 44¢ about
        half an hour later, as buyers kept lifting the Under."
```

**Why six pairs not four:** the last two pairs are calibration anchors drawn directly from the dry-run output that triggered this work. They map the *exact* recurring failure modes ("29-4 wallet", "P&L wallet", "the other sharp", "lifted") to fixed forms. The model gets to learn from its own past mistakes.

## What stays the same

- Thread shape (hook → body → payoff, 3-5 tweets, reply chain).
- 280-char cap, URL counting, banned-CTA list ("in bio", "full breakdown", etc.), banned-internal-jargon list, number-budget (max 3 per tweet, ~10 per thread), emoji budget, hashtag budget.
- Fact-fidelity rules and "when to skip" rules.
- Output JSON schema (`decision`, `reason`, `tweets`, `alert_ids`).
- Picker prompt, validator (`validate_decision`), banned-CTA list (`_BANNED_TWEET_PHRASES`), posting flow, dedup, transcript logging.

## Verification plan

The change is prompt-only. Verification is empirical:

1. **Diff check.** Confirm the only file touched is [storybot/storybot.py](../../../storybot/storybot.py), and the only change is inside `SYSTEM_PROMPT` (no logic, no validators, no I/O changes).
2. **Lint / syntax check.** Run `python -m py_compile storybot/storybot.py` from the project root — the prompt is an f-string with `{TWEET_MAX_CHARS}`/`{TWEET_URL_CHARS}` interpolations, so a stray `{` or `}` from the new copy would crash compilation.
3. **Dry-run, same alerts as before.** Run `STORYBOT_DRY_RUN=true python storybot.py` at least twice and inspect the output threads against this checklist:
   - No occurrences of the new banned phrases ("clip", "trimming", "lifted", "the sharp", "stacked", "P&L wallet", "wall", "leaning on a number", "hit BUY", "round-tripped", "the book") in the tweets.
   - First mention of any sports bet line is unpacked in plain English at least once per thread.
   - First mention of a track-record shorthand (e.g. "29-4") is unpacked at least once per thread.
   - Tweets remain ≤ 280 chars (existing validator already enforces this — but check that unpacking didn't push the model into truncation).
   - Voice still feels punchy, not explainer-blog. Subjective; eyeball it.
4. **Regression check.** Confirm validators still pass (no banned-CTA phrases, polyspotter URL in final tweet, 3-5 tweets, no URLs in tweets 1..N-1).

There is no automated test for "does this read like a layman can follow it" — that's an inherent limitation of prompt work and is accepted as part of the trade-off. If dry-runs after the change still show heavy jargon, the implementation plan should include a follow-up loop, not a "ship it" step.

## Trade-offs explicitly accepted

- **Tweets get longer.** Unpacks cost characters. The model will spend its number-budget more carefully. Acceptable.
- **Some authentic crypto-Twitter flavor is lost.** "Stacked" is genuinely native to that register; banning it costs a small amount of authenticity in exchange for accessibility. Audience D requires this trade. Re-evaluate if dry-runs feel sterile.
- **No automated assertion that "a layman can follow."** Prompt changes don't have unit tests. Verification is dry-run inspection.
- **The model may overcorrect** in early dry-runs by adding explainer sentences to every tweet. The "What this is NOT" sub-block in Edit 2 is the guard; if dry-runs still over-explain, tighten that block.

## Open questions

None at the time of writing. The "keep or kill 'stacked'" question was resolved during brainstorming: kill it.

## Implementation order

The three edits are coordinated and must be applied together in a single commit. Edit 3b (fixing the `"deployed capital"` line) is a knock-on of Edit 3a — making 3a without 3b leaves the prompt internally inconsistent (it would ban "stacked" while still suggesting it as a replacement two lines up). The implementation plan should treat all three edits as one atomic change, then run the verification checklist.
