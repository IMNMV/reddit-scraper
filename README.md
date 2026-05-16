# a reddit scraper

Crash-safe Reddit scraper for academic NLP research. Pulls **full historical posts** via the Arctic Shift archive API (no 1,000-post Reddit listing cap) and **full comment trees** via PRAW (`replace_more(limit=None, threshold=0)`). Writes row-by-row to CSV with atomic checkpointing, so an interrupted run resumes from the last completed batch.

Validated on roughly 1.7 million posts and 3.6 million comments across r/replika, r/CharacterAI, r/MyBoyfriendIsAI, r/ChatGPT, r/ClaudeAI, r/Anthropic, and r/OpenAI.

Pure Python package with a CLI. R users can drive it directly via reticulate (see "Using from R" below).

## Why this exists

Pushshift, the standard tool for academic Reddit research, went down for outside-moderator use in 2023. Most public scrapers have not been updated since. Existing tools either wrap Arctic Shift at the API level, scrape Reddit's live/public listings, or require custom scripts. This package is designed as a reproducible academic data-collection pipeline: full historical post discovery via Arctic Shift, full comment-tree hydration via PRAW, row-wise CSV output, and atomic checkpointing for multi-day runs.

This package fills that gap. Key differentiators:

* Arctic Shift is the primary source for post discovery, with the Reddit listing API as fallback. Full subreddit history is reachable, not just the last 1,000 posts.
* Crash-safe by design. Every batch of rows is appended to disk immediately. Every checkpoint write is `tmp file -> os.rename()` so the checkpoint is never half-written. Restart at any time and pick up exactly where you left off.
* PRAW primary for comment hydration with Arctic Shift fallback per post. Full comment trees including collapsed and low-score comments.
* Generic shell wrapper for auto-restart on stalls (Arctic Shift occasionally times out on high-volume time windows; the right answer is to just restart).

## Install

Not yet on PyPI. Install directly from GitHub:

```bash
pip install git+https://github.com/IMNMV/reddit-scraper.git
```

Or clone and install in editable mode for local development:

```bash
git clone https://github.com/IMNMV/reddit-scraper.git
cd reddit-scraper
pip install -e .
```

## Credentials

Create a Reddit app at `https://www.reddit.com/prefs/apps`. App type: **script**. The scraper uses read-only `client_credentials` flow, so you do not need to provide your password.

You will get a `client_id` and `client_secret`. Together with your reddit username and a chosen app name, that is all you need.

Two ways to provide them:

1. **Environment variables** (works everywhere):

   ```bash
   export REDDIT_CLIENT_ID=...
   export REDDIT_CLIENT_SECRET=...
   export REDDIT_USERNAME=...
   export REDDIT_APP_NAME=...
   ```

2. **Python file** (CLI `--creds` flag): copy `credentials/template.py` to `credentials/reddit_creds.py` and fill it in.

The credentials file is in `.gitignore`. Do not commit it.

## Usage

### Python (library)

```python
from reddit_scraper import RedditScraper

scraper = RedditScraper(
    client_id="...",
    client_secret="...",
    username="...",
    app_name="...",
    base_dir=".",
)
scraper.scrape_subreddit("replika")
```

Output:

```
./data/raw/replika/posts.csv
./data/raw/replika/comments.csv
./data/raw/replika/checkpoint.json
```

### Python (CLI)

```bash
reddit-scraper replika --base-dir .
reddit-scraper ChatGPT --base-dir . --creds credentials/reddit_creds.py
reddit-scraper replika --base-dir . --status
```

### Using from R (via reticulate)

R users can drive the Python package directly. No R wrapper is needed.

One-time setup:

```r
install.packages("reticulate")
reticulate::virtualenv_create("r-reddit")
reticulate::virtualenv_install(
  "r-reddit",
  "git+https://github.com/IMNMV/reddit-scraper.git"
)
```

Then:

```r
library(reticulate)
use_virtualenv("r-reddit", required = TRUE)
rs <- import("reddit_scraper")

scraper <- rs$RedditScraper(
  client_id     = Sys.getenv("REDDIT_CLIENT_ID"),
  client_secret = Sys.getenv("REDDIT_CLIENT_SECRET"),
  username      = Sys.getenv("REDDIT_USERNAME"),
  app_name      = Sys.getenv("REDDIT_APP_NAME"),
  base_dir      = "."
)
scraper$scrape_subreddit("replika")
```

See `examples/r_example.R`. Reticulate-specific gotchas (passing integers, RStudio Server quirks) are documented in `docs/API_NOTES.md`.

### Auto-restart for long runs

Arctic Shift occasionally stalls on dense time windows. The scraper itself is crash-safe; the right strategy is just to restart on non-clean exit. A generic wrapper is included:

```bash
bash scripts/run_subreddit.sh replika .
bash scripts/run_subreddit.sh ChatGPT /Users/me/reddit-data
```

Logs land at `<base_dir>/logs/<subreddit>_runner.log`. The loop checks `checkpoint.json` after each exit and only stops when `phase == "done"`.

To run several subreddits at once in the background:

```bash
for s in ChatGPT ClaudeAI Anthropic OpenAI; do
  bash scripts/run_subreddit.sh "$s" . &
done
```

### Surviving laptop sleep and reboots

The scraper does **not** auto-resume when your computer wakes from sleep or boots back up. Background shell processes are killed when the system suspends or shuts down. Your data is safe (every batch is on disk, every checkpoint write is atomic), but you do need to re-run the launcher manually after the machine comes back. When you do, each subreddit picks up from its checkpoint within seconds.

To keep a Mac awake during long runs:

```bash
caffeinate -i &        # prevents sleep
# ... start your scrapers ...
pkill caffeinate       # release when done
```

Note that `caffeinate` only blocks idle sleep; closing the laptop lid still kills background processes regardless. For multi-day scrapes, keep the lid open or run on a desktop or server.

After a reboot, just re-run the same launch loop:

```bash
for s in ChatGPT ClaudeAI Anthropic OpenAI; do
  bash scripts/run_subreddit.sh "$s" . &
done
```

## What gets collected

Each subreddit produces three files under `<base_dir>/data/raw/<subreddit_lowercase>/`:

```
posts.csv         row-per-post,    29 columns
comments.csv     row-per-comment,  22 columns
checkpoint.json  atomic resume state
```

Full column reference is in `docs/SCHEMAS.md`. Quick summary below.

### posts.csv (29 columns)

| column | type | notes |
|---|---|---|
| post_id | str | Reddit base36 ID |
| subreddit | str | lowercased |
| title | str | |
| selftext | str | body text; empty for link posts |
| author | str | "[deleted]" if removed |
| author_flair | str | sparse from Arctic Shift, complete from PRAW |
| score | int | net votes (slightly fuzzed for new posts) |
| upvote_ratio | float | most reliable vote signal |
| num_comments | int | Reddit-reported count |
| url | str | post or link URL |
| domain | str | hostname of url |
| is_self | bool | True for text posts |
| is_video | bool | NA on some Arctic Shift rows |
| nsfw | bool | over_18 flag |
| spoiler | bool | |
| locked | bool | |
| archived | bool | Reddit archives after 6 months |
| distinguished | str | moderator / admin / "" |
| stickied | bool | |
| flair_text | str | link_flair_text |
| flair_css_class | str | sparse from Arctic Shift |
| created_utc | float | epoch seconds UTC |
| created_dt | str | human-readable UTC |
| scraped_utc | float | when row was collected |
| gilded | int | gold-award count |
| total_awards | int | NA on some older posts |
| crosspost_parent | str | parent post ID if crosspost |
| permalink | str | full Reddit URL |
| source | str | "arctic_shift" or "reddit_api" |

### comments.csv (22 columns)

| column | type | notes |
|---|---|---|
| comment_id | str | Reddit base36 ID |
| post_id | str | parent post ID |
| subreddit | str | |
| parent_id | str | t3_<post_id> or t1_<comment_id> |
| parent_type | str | "post" or "comment" |
| body | str | comment text |
| author | str | "[deleted]" if removed |
| author_flair | str | |
| score | int | net votes |
| ups | int | same as score post-2014 |
| controversiality | int | Reddit flag (0 or 1) |
| depth | int | 0 = top-level reply to the post |
| is_submitter | bool | True if commenter is OP |
| distinguished | str | |
| stickied | bool | |
| edited | bool | True if ever edited |
| gilded | int | |
| total_awards | int | |
| created_utc | float | |
| created_dt | str | |
| scraped_utc | float | |
| source | str | "reddit_api" or "arctic_shift" |

### checkpoint.json

Per-subreddit resume state. Tracks the current phase (`posts`, `comments`, or `done`), the UTC cursor for Arctic Shift pagination, the list of post IDs whose comments are already saved, and running totals. Written atomically (tmp file then rename) after every batch, so it is never half-written on crash.

### What is not collected

Reddit deliberately obfuscates raw upvote and downvote counts. The scraper preserves what the API returns (`score`, `upvote_ratio`, `ups`); raw up/down counts are not available from any Reddit source. The standard estimate used in published research is `est_upvotes = round(score / upvote_ratio)` and `est_downvotes = est_upvotes - score`.

Private, quarantined, and banned subreddits are not accessible to read-only `client_credentials` auth. Deleted post bodies appear as `"[deleted]"` or `"[removed]"`; Arctic Shift sometimes captures the pre-deletion text because it archives at posting time, the live Reddit API does not.

## For AI agents

If you are an AI agent driving this package on behalf of a user, here is the short version. Everything below is enough to run a full scrape end to end without reading any other file.

**One-time setup (run once per machine):**

```bash
pip install git+https://github.com/IMNMV/reddit-scraper.git
```

The user needs a Reddit script app at `https://www.reddit.com/prefs/apps`. Ask them for `client_id`, `client_secret`, their reddit `username`, and any string for `app_name`. Export them as environment variables:

```bash
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USERNAME=...
export REDDIT_APP_NAME=...
```

**Run a scrape:**

```bash
reddit-scraper <subreddit> --base-dir <output_root>
```

Output lands at `<output_root>/data/raw/<subreddit_lowercase>/{posts.csv,comments.csv,checkpoint.json}`. Re-running the same command resumes from `checkpoint.json`. No deduplication or manual cleanup needed.

**Check progress:**

```bash
reddit-scraper <subreddit> --base-dir <output_root> --status
```

Prints phase (`posts` / `comments` / `done`), post count, comment count, and percent complete.

**Run unattended for hours or days:**

```bash
bash scripts/run_subreddit.sh <subreddit> <output_root>
```

This wraps the CLI in a `while true` loop that restarts on any non-clean exit and only stops when `checkpoint.json` reports `phase == "done"`. Logs to `<output_root>/logs/<subreddit>_runner.log`. Run multiple in parallel with `&`.

**Programmatic use from Python:**

```python
from reddit_scraper import RedditScraper
scraper = RedditScraper(
    client_id=os.environ["REDDIT_CLIENT_ID"],
    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
    username=os.environ["REDDIT_USERNAME"],
    app_name=os.environ["REDDIT_APP_NAME"],
    base_dir=".",
)
scraper.scrape_subreddit("replika")
```

**Programmatic use from R (via reticulate):**

```r
library(reticulate)
use_virtualenv("r-reddit", required = TRUE)
rs <- import("reddit_scraper")
s <- rs$RedditScraper(
  client_id = Sys.getenv("REDDIT_CLIENT_ID"),
  client_secret = Sys.getenv("REDDIT_CLIENT_SECRET"),
  username = Sys.getenv("REDDIT_USERNAME"),
  app_name = Sys.getenv("REDDIT_APP_NAME"),
  base_dir = "."
)
s$scrape_subreddit("replika")
```

**Output schemas:** see `docs/SCHEMAS.md`. The raw posts file has 29 columns, the raw comments file has 22 columns. Both are appended row by row; the file is always valid CSV.

**Things to know before debugging:**

* Arctic Shift rejects `after=0` with HTTP 400. The scraper omits `after` on first page already. If you write a custom client, do the same.
* Arctic Shift stalls intermittently on dense time windows. This is expected. Restarting resumes within seconds.
* PRAW's `replace_more(limit=None, threshold=0)` is the only correct way to get complete comment trees including collapsed ones. Do not interrupt it mid-call.
* Reddit obfuscates raw vote counts. The scraper preserves what the API returns (`score`, `upvote_ratio`, `ups`). The standard estimate used in published research is `est_upvotes = round(score / upvote_ratio)` and `est_downvotes = est_upvotes - score`; see `docs/SCHEMAS.md`.
* Closing a laptop lid kills background shell processes regardless of `caffeinate`. For multi-day scrapes, either keep the lid open with `caffeinate -i &` or run on a server.

**See also:** `docs/API_NOTES.md` for the full list of API gotchas; `docs/SCHEMAS.md` for column definitions.

## Project layout

```
src/reddit_scraper/        Python package
  scraper.py               core RedditScraper class + Arctic Shift + checkpoint
  cli.py                   command-line entry point (installed as reddit-scraper)
scripts/
  run_subreddit.sh         generic auto-restart wrapper
credentials/
  template.py              copy to reddit_creds.py and fill in; never commit
examples/
  python_example.py        minimal Python example
  r_example.R              minimal R-via-reticulate example
docs/
  SCHEMAS.md               CSV column reference
  API_NOTES.md             Arctic Shift + PRAW gotchas
```

## Citing

If you use this in academic work, see `CITATION.cff` or cite as:

> Vitali, N. (2026). A Reddit scraper for academic research (v0.1.0) [Software]. https://github.com/IMNMV/reddit-scraper

## License

MIT. See `LICENSE`.
