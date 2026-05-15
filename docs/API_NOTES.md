# Arctic Shift and PRAW: gotchas worth knowing

These are issues discovered during real production scraping of multi-million-post subreddits. Most are not documented elsewhere.

## Arctic Shift

Base URL: `https://arctic-shift.photon-reddit.com/api`. No authentication required. Free academic service maintained by the Photon Reddit team. Status page: `https://status.arctic-shift.photon-reddit.com`.

### `after=0` returns HTTP 400

The API rejects epoch zero as the pagination cursor. On the first page, omit the `after` parameter entirely:

```python
# wrong
params = {"subreddit": "replika", "limit": 100, "sort": "asc", "after": 0}

# correct
params = {"subreddit": "replika", "limit": 100, "sort": "asc"}
if after_utc > 0:
    params["after"] = int(after_utc)
```

### Stalls on dense time windows

The API consistently times out on high-volume periods. Observed stalls at roughly every 7,000 posts during continuous pagination. The scraper handles this with a 6-attempt exponential backoff, and the `scripts/run_subreddit.sh` wrapper restarts the entire process on any non-clean exit. After a restart, the checkpoint resumes from the last successful batch within seconds.

### Use `sort=asc`, not the old format

`sort=asc` works. Older docs suggesting `sort=created_utc&order=asc` cause 400 errors.

### Rate limit headers

The API exposes `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers. Observed budget is roughly 2,000 requests per 31-second window. The scraper sleeps for the full reset window if `remaining < 5`.

### Request timeouts

Use `timeout=(10, 45)` (connect, read). This fails fast on hung connections so the retry loop can kick in.

### Response shape

Always wrap in `.get("data", [])`. Some error responses omit the `data` key entirely.

## PRAW

### Use `replace_more(limit=None, threshold=0)` for complete trees

```python
submission.comments.replace_more(limit=None, threshold=0)
```

* `limit=None` expands every `MoreComments` continuation object recursively.
* `threshold=0` includes collapsed and low-score comments.

This is slow on threads with 10,000+ comments. PRAW handles rate limiting internally during `replace_more`. Do not interrupt mid-call.

### Listing cap

Reddit caps each listing endpoint (`new`, `top`, `hot`, `controversial`) at roughly 1,000 posts. Arctic Shift bypasses this by paginating through the archive, which is why post discovery uses Arctic Shift as primary and PRAW listings only as fallback.

### Vote obfuscation

Reddit deliberately obfuscates raw up and down counts. The fields you actually get back:

* `score` is the net (slightly fuzzed for posts under 36 hours old).
* `upvote_ratio` is the cleanest signal on posts.
* `ups` equals `score` for comments post-2014.
* `downs` is always 0; Reddit stopped populating it years ago.

The standard estimate in published Reddit research is `round(score / upvote_ratio)` for upvotes; see `docs/SCHEMAS.md` for the full formula.

### Deleted content

* Deleted body: `selftext` is `"[deleted]"` or `"[removed]"`.
* Deleted author: `submission.author is None`, stored as `"[deleted]"`.
* Arctic Shift captures more deleted content than PRAW because it archives at posting time.

## reticulate (R wrapper specific)

If you drive the Python module from R via reticulate, these bite:

* `py_run_string()` output is not captured in async R jobs. Use `import("reddit_scraper")` plus the `$` operator instead.
* Private Python methods need backticks in R: `scraper$\`_comments_for_post\`(id, sub)`.
* Pass integers explicitly: `as.integer(utc)` or `1234L`. Floats get coerced unpredictably.
* `callr::r_bg()` silently fails in some RStudio environments. The shell-script restart approach is more reliable.
* `reticulate::source_python()` must be re-run in every new R session.
* Very long Python code strings passed through `py_run_string()` can trigger HTTP 500 from RStudio Server. Write to a `.py` file with `writeLines()` and `source_python()` it instead.
