# reddit-scraper

Crash-safe Reddit scraper for academic NLP research. Pulls **full historical posts** via the Arctic Shift archive API (no 1,000-post Reddit listing cap) and **full comment trees** via PRAW (`replace_more(limit=None, threshold=0)`). Writes row-by-row to CSV with atomic checkpointing, so an interrupted run resumes from the last completed batch.

Built and battle-tested on roughly 1.7 million posts and 3.6 million comments across r/replika, r/CharacterAI, r/MyBoyfriendIsAI, r/ChatGPT, r/ClaudeAI, r/Anthropic, and r/OpenAI.

Ships with both a **Python** package + CLI and an **R** wrapper that calls into the Python module via reticulate.

## Why this exists

Pushshift, the standard tool for academic Reddit research, went down for outside-moderator use in 2023. Most public scrapers have not been updated since. Arctic Shift is the current archive replacement, but almost nothing wraps it for end users, especially nothing R-first or research-grade.

This package fills that gap. Key differentiators:

* Arctic Shift is the primary source for post discovery, with the Reddit listing API as fallback. Full subreddit history is reachable, not just the last 1,000 posts.
* Crash-safe by design. Every batch of rows is appended to disk immediately. Every checkpoint write is `tmp file -> os.rename()` so the checkpoint is never half-written. Restart at any time and pick up exactly where you left off.
* PRAW primary for comment hydration with Arctic Shift fallback per post. Full comment trees including collapsed and low-score comments.
* Generic shell wrapper for auto-restart on stalls (Arctic Shift occasionally times out on high-volume time windows; the right answer is to just restart).
* R interface so researchers who live in R do not have to learn reticulate plumbing.

## Install

### Python

```bash
pip install reddit-scraper
```

Or from source:

```bash
git clone https://github.com/IMNMV/reddit-scraper.git
cd reddit-scraper
pip install -e .
```

### R

```r
install.packages(c("reticulate", "jsonlite", "dplyr", "readr",
                   "stringr", "lubridate"))
reticulate::virtualenv_create("r-reddit")
reticulate::virtualenv_install("r-reddit", "reddit-scraper")
```

Then in your project: `source("R/scrape.R")` (copy `R/scrape.R` and `R/clean.R` from this repo into your project, or work from a clone).

## Credentials

Create a Reddit app at `https://www.reddit.com/prefs/apps`. App type: **script**. The scraper uses read-only `client_credentials` flow, so you do not need to provide your password.

You will get a `client_id` and `client_secret`. Together with your reddit username and a chosen app name, that is all you need.

Three ways to provide them:

1. **Environment variables** (works everywhere):

   ```bash
   export REDDIT_CLIENT_ID=...
   export REDDIT_CLIENT_SECRET=...
   export REDDIT_USERNAME=...
   export REDDIT_APP_NAME=...
   ```

2. **Python file** (CLI `--creds` flag): copy `credentials/template.py` to `credentials/reddit_creds.py` and fill it in.

3. **R file** (auto-loaded by `R/scrape.R`): copy `credentials/template.R` to `credentials/reddit_creds.R` and fill it in.

Both credential files are in `.gitignore`. Do not commit them.

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

### R

```r
source("R/scrape.R")

# one subreddit
scrape("replika")

# sequential
scrape(c("ChatGPT", "ClaudeAI", "Anthropic", "OpenAI"))

# parallel (macOS / Linux only; keep max_jobs <= 3 to stay within Reddit limits)
scrape(c("ChatGPT", "ClaudeAI", "Anthropic", "OpenAI"),
       parallel = TRUE, max_jobs = 3)

# progress
status(c("replika", "ChatGPT", "ClaudeAI"))
```

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

### Optional: clean + feature engineer

`R/clean.R` reads the raw CSVs and writes a cleaned, feature-engineered version with time variables (`year`, `yearmonth`, `yearquarter`, `day_of_week`, `hour_utc`), estimated vote counts (`est_upvotes`, `est_downvotes`, `controversy_ratio`), text fields scrubbed for NLP (`selftext_clean`, `body_clean`), and quality flags (`is_deleted`, `is_removed`, `is_bot`).

```r
source("R/clean.R")
clean(c("replika", "ChatGPT", "ClaudeAI"))
# writes ./data/processed/<subreddit>/posts_clean.csv + comments_clean.csv
```

## For AI agents

If you are an AI agent driving this package on behalf of a user, here is the short version. Everything below is enough to run a full scrape end to end without reading any other file.

**One-time setup (run once per machine):**

```bash
pip install reddit-scraper
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

**Programmatic use from R:**

```r
source("R/scrape.R")
scrape("replika")
```

**Output schemas:** see `docs/SCHEMAS.md`. The raw posts file has 29 columns, the raw comments file has 22 columns. Both are appended row by row; the file is always valid CSV.

**Things to know before debugging:**

* Arctic Shift rejects `after=0` with HTTP 400. The scraper omits `after` on first page already. If you write a custom client, do the same.
* Arctic Shift stalls intermittently on dense time windows. This is expected. Restarting resumes within seconds.
* PRAW's `replace_more(limit=None, threshold=0)` is the only correct way to get complete comment trees including collapsed ones. Do not interrupt it mid-call.
* Reddit obfuscates raw vote counts. The scraper preserves what the API returns (`score`, `upvote_ratio`, `ups`); `R/clean.R` produces standard estimated counts.
* Closing a laptop lid kills background shell processes regardless of `caffeinate`. For multi-day scrapes, either keep the lid open with `caffeinate -i &` or run on a server.

**See also:** `docs/API_NOTES.md` for the full list of API gotchas; `docs/SCHEMAS.md` for column definitions.

## Project layout

```
src/reddit_scraper/        Python package
  scraper.py               core RedditScraper class + Arctic Shift + checkpoint
  cli.py                   command-line entry point (installed as reddit-scraper)
R/
  scrape.R                 R wrapper around the Python module
  clean.R                  optional cleaning + feature engineering
scripts/
  run_subreddit.sh         generic auto-restart wrapper
credentials/
  template.R, template.py  copy and fill in; never commit reddit_creds.*
examples/                  minimal runnable examples
docs/
  SCHEMAS.md               CSV column reference
  API_NOTES.md             Arctic Shift + PRAW gotchas
```

## Citing

If you use this in academic work, see `CITATION.cff` or cite as:

> Vitali, N. (2026). reddit-scraper: crash-safe full-history Reddit scraper (v0.1.0) [Software]. https://github.com/IMNMV/reddit-scraper

## License

MIT. See `LICENSE`.
