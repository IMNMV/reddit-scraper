# Output schemas

Every subreddit produces three files under `<base_dir>/data/raw/<subreddit_lowercase>/`:

```
posts.csv         row-per-post,  29 columns
comments.csv      row-per-comment, 22 columns
checkpoint.json   atomic progress + cursor state
```

`R/clean.R` optionally produces `data/processed/<subreddit>/posts_clean.csv` (46 cols) and `comments_clean.csv` (37 cols) with derived time, vote, and NLP fields.

## posts.csv (29 columns)

| column | type | notes |
|---|---|---|
| post_id | str | Reddit base36 ID, no prefix |
| subreddit | str | lowercased |
| title | str | |
| selftext | str | body; empty string for link posts |
| author | str | "[deleted]" if removed |
| author_flair | str | sparse from Arctic Shift |
| score | int | net votes (slightly fuzzed on recent posts) |
| upvote_ratio | float | most reliable vote signal |
| num_comments | int | Reddit-reported count |
| url | str | |
| domain | str | |
| is_self | bool | True for text posts |
| is_video | bool | NA on some Arctic Shift rows |
| nsfw | bool | over_18 field |
| spoiler | bool | |
| locked | bool | |
| archived | bool | Reddit archives after 6 months |
| distinguished | str | moderator/admin/empty |
| stickied | bool | |
| flair_text | str | link_flair_text |
| flair_css_class | str | sparse from Arctic Shift |
| created_utc | float | epoch seconds UTC |
| created_dt | str | human-readable UTC datetime |
| scraped_utc | float | when this row was collected |
| gilded | int | gold award count |
| total_awards | int | NA on some older posts |
| crosspost_parent | str | parent post ID if crosspost |
| permalink | str | full Reddit URL |
| source | str | "arctic_shift" or "reddit_api" |

## comments.csv (22 columns)

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
| depth | int | 0 = top-level reply to post |
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

## checkpoint.json

```json
{
  "subreddit": "replika",
  "phase": "comments",
  "last_post_utc": 1716000000.0,
  "posts_discovered": 157420,
  "posts_done_comments": ["abc123", "def456", ...],
  "total_posts_written": 157420,
  "total_comments_written": 739522,
  "started_at": "2026-04-01T12:00:00+00:00",
  "updated_at": "2026-05-15T09:31:04+00:00"
}
```

`phase` is one of `posts`, `comments`, `done`. Writes are atomic (tmp file then rename), so the file is never half-written on crash.

## Notes on vote data

Reddit no longer exposes raw up and down counts. The standard estimate used in published research is:

```
est_upvotes   = round(score / upvote_ratio)
est_downvotes = est_upvotes - score
```

`R/clean.R` adds these columns automatically. For comments, `upvote_ratio` is not provided; `ups` equals `score` post-2014, so `est_upvotes` falls back to `ups`.

## Notes on deleted content

`author = "[deleted]"` or `selftext in ["[deleted]", "[removed]"]` indicates removal. Arctic Shift captures more deleted content than the live Reddit API because it archives before deletion happens.
