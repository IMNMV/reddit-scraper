"""
reddit_scraper.scraper

Crash-safe, full-history Reddit scraper built for academic NLP research.

Two-phase pipeline per subreddit:

  Phase 1 (post discovery):  Arctic Shift API paginates the entire history
                             of the subreddit by created_utc cursor, bypassing
                             the ~1000-post Reddit listing cap. Falls back to
                             Reddit API listings (new/top/controversial/hot)
                             if Arctic Shift is unavailable.

  Phase 2 (comment hydration): For every post_id, PRAW fetches the full
                               comment tree via replace_more(limit=None,
                               threshold=0). Falls back to Arctic Shift
                               /api/comments/search per post on PRAW failure.

State is persisted to checkpoint.json after every batch. Writes are atomic
(tmp file then os.rename), so a crash never leaves an inconsistent file.
Re-running the same command resumes from the last completed batch.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import praw
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reddit_scraper")

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"
POSTS_PER_PAGE = 100
COMMENTS_PER_PAGE = 100
ARCTIC_SLEEP = 0.6
REDDIT_SLEEP = 1.1
MAX_RETRIES = 6
BACKOFF_BASE = 2.0

POST_COLS = [
    "post_id", "subreddit", "title", "selftext", "author", "author_flair",
    "score", "upvote_ratio", "num_comments", "url", "domain",
    "is_self", "is_video", "nsfw", "spoiler", "locked", "archived",
    "distinguished", "stickied", "flair_text", "flair_css_class",
    "created_utc", "created_dt", "scraped_utc",
    "gilded", "total_awards", "crosspost_parent", "permalink", "source",
]

COMMENT_COLS = [
    "comment_id", "post_id", "subreddit", "parent_id", "parent_type",
    "body", "author", "author_flair",
    "score", "ups", "controversiality",
    "depth", "is_submitter", "distinguished", "stickied",
    "edited", "gilded", "total_awards",
    "created_utc", "created_dt", "scraped_utc", "source",
]


def utc_now():
    return datetime.now(timezone.utc).timestamp()


def utc_to_dt(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return ""


def ensure_csv(path, cols):
    """Write header row if the CSV does not exist yet."""
    if not path.exists():
        pd.DataFrame(columns=cols).to_csv(path, index=False)


def append_rows(path, rows, cols):
    """Append a list of dicts to a CSV (header already written by ensure_csv)."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df[cols].to_csv(path, mode="a", index=False, header=False)


class Checkpoint:
    """
    Persists scraping state to disk after every batch.

    Writes atomically (tmp file then os.rename) so the file is never corrupted
    by a crash. Layout of checkpoint.json:

        subreddit, phase (posts|comments|done),
        last_post_utc            UTC cursor for Arctic Shift pagination resume
        posts_discovered         count of posts written so far
        posts_done_comments      list of post_ids whose comments are done
        total_posts_written, total_comments_written,
        started_at, updated_at   ISO-8601 timestamps
    """

    def __init__(self, path, subreddit):
        self.path = path
        if path.exists():
            with open(path) as f:
                self.data = json.load(f)
            log.info(
                "Resuming checkpoint: phase=%s posts=%d comments_done=%d",
                self.data.get("phase"),
                self.data.get("posts_discovered", 0),
                len(self.data.get("posts_done_comments", [])),
            )
        else:
            self.data = {
                "subreddit": subreddit,
                "phase": "posts",
                "last_post_utc": 0.0,
                "posts_discovered": 0,
                "posts_done_comments": [],
                "total_posts_written": 0,
                "total_comments_written": 0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": "",
            }
            self.save()

    def save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        tmp.replace(self.path)

    def mark_post_utc(self, utc):
        self.data["last_post_utc"] = utc
        self.save()

    def add_posts(self, n):
        self.data["posts_discovered"] += n
        self.data["total_posts_written"] += n
        self.save()

    def mark_comments_done(self, post_id, n):
        if post_id not in self.data["posts_done_comments"]:
            self.data["posts_done_comments"].append(post_id)
        self.data["total_comments_written"] += n
        self.save()

    def set_phase(self, phase):
        self.data["phase"] = phase
        self.save()

    @property
    def last_post_utc(self):
        return float(self.data.get("last_post_utc", 0.0))

    @property
    def phase(self):
        return self.data.get("phase", "posts")

    @property
    def posts_done_set(self):
        return set(self.data.get("posts_done_comments", []))


class ArcticShiftClient:
    """
    Wraps the Arctic Shift public API for full-history post and comment
    retrieval. No authentication required. Paginates via UTC timestamp cursor
    so every post from subreddit inception to present is reachable.

    If the API becomes unavailable, sets `ArcticShiftClient.available = False`
    so callers can fall back to the Reddit API listing endpoint.
    """

    available = True

    def __init__(self, user_agent="reddit_scraper/0.1"):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _get(self, endpoint, params):
        url = ARCTIC_BASE + "/" + endpoint
        for attempt in range(MAX_RETRIES):
            try:
                # (connect_timeout, read_timeout): fail fast on hung connections
                r = self.session.get(url, params=params, timeout=(10, 45))
                r.raise_for_status()
                remaining = r.headers.get("X-RateLimit-Remaining")
                if remaining is not None and float(remaining) < 5:
                    reset = float(r.headers.get("X-RateLimit-Reset", 10))
                    log.warning(
                        "Arctic Shift rate limit low (%s remaining), sleeping %.1fs",
                        remaining, reset,
                    )
                    time.sleep(reset)
                else:
                    time.sleep(ARCTIC_SLEEP)
                return r.json()
            except Exception as e:
                wait = BACKOFF_BASE ** attempt
                log.warning("Arctic Shift error: %s, retry in %.1fs", e, wait)
                time.sleep(wait)
        raise RuntimeError("Arctic Shift exhausted retries")

    def fetch_posts_page(self, subreddit, after_utc):
        # NOTE: omit "after" on first page. The API rejects after=0 with HTTP 400.
        try:
            params = {
                "subreddit": subreddit,
                "limit": POSTS_PER_PAGE,
                "sort": "asc",
            }
            if after_utc and float(after_utc) > 0:
                params["after"] = int(after_utc)
            data = self._get("posts/search", params)
            return data.get("data", [])
        except Exception as e:
            log.error("Arctic Shift posts failed: %s", e)
            ArcticShiftClient.available = False
            return []

    def fetch_comments_search(self, post_id, after_utc=0):
        """
        Paginate through all comments for a post via /api/comments/search.
        Used as fallback when PRAW fails. Paginates via created_utc cursor.
        """
        link_id = "t3_" + post_id.replace("t3_", "")
        all_comments, after = [], int(after_utc)
        while True:
            params = {
                "link_id": link_id,
                "limit": COMMENTS_PER_PAGE,
                "sort": "asc",
            }
            if after and float(after) > 0:
                params["after"] = int(after)
            try:
                data = self._get("comments/search", params)
                batch = data.get("data", [])
            except Exception as e:
                log.error("Arctic Shift comments/search failed for %s: %s", post_id, e)
                break
            if not batch:
                break
            all_comments.extend(batch)
            if len(batch) < COMMENTS_PER_PAGE:
                break
            after = int(float(batch[-1].get("created_utc", after)))
        return all_comments

    def fetch_all_comments(self, post_id):
        return self.fetch_comments_search(post_id)


def parse_arctic_post(raw, subreddit):
    utc = float(raw.get("created_utc", 0))
    return {
        "post_id": raw.get("id", ""),
        "subreddit": subreddit,
        "title": raw.get("title", ""),
        "selftext": raw.get("selftext", ""),
        "author": raw.get("author", ""),
        "author_flair": raw.get("author_flair_text", ""),
        "score": raw.get("score", ""),
        "upvote_ratio": raw.get("upvote_ratio", ""),
        "num_comments": raw.get("num_comments", ""),
        "url": raw.get("url", ""),
        "domain": raw.get("domain", ""),
        "is_self": raw.get("is_self", ""),
        "is_video": raw.get("is_video", ""),
        "nsfw": raw.get("over_18", ""),
        "spoiler": raw.get("spoiler", ""),
        "locked": raw.get("locked", ""),
        "archived": raw.get("archived", ""),
        "distinguished": raw.get("distinguished", ""),
        "stickied": raw.get("stickied", ""),
        "flair_text": raw.get("link_flair_text", ""),
        "flair_css_class": raw.get("link_flair_css_class", ""),
        "created_utc": utc,
        "created_dt": utc_to_dt(utc),
        "scraped_utc": utc_now(),
        "gilded": raw.get("gilded", ""),
        "total_awards": raw.get("total_awards_received", ""),
        "crosspost_parent": raw.get("crosspost_parent", ""),
        "permalink": raw.get("permalink", ""),
        "source": "arctic_shift",
    }


def parse_praw_post(sub, subreddit):
    utc = float(sub.created_utc)
    return {
        "post_id": sub.id,
        "subreddit": subreddit,
        "title": sub.title,
        "selftext": sub.selftext,
        "author": str(sub.author) if sub.author else "[deleted]",
        "author_flair": sub.author_flair_text or "",
        "score": sub.score,
        "upvote_ratio": sub.upvote_ratio,
        "num_comments": sub.num_comments,
        "url": sub.url,
        "domain": sub.domain,
        "is_self": sub.is_self,
        "is_video": sub.is_video,
        "nsfw": sub.over_18,
        "spoiler": sub.spoiler,
        "locked": sub.locked,
        "archived": sub.archived,
        "distinguished": sub.distinguished or "",
        "stickied": sub.stickied,
        "flair_text": sub.link_flair_text or "",
        "flair_css_class": sub.link_flair_css_class or "",
        "created_utc": utc,
        "created_dt": utc_to_dt(utc),
        "scraped_utc": utc_now(),
        "gilded": sub.gilded,
        "total_awards": sub.total_awards_received,
        "crosspost_parent": getattr(sub, "crosspost_parent", ""),
        "permalink": "https://reddit.com" + sub.permalink,
        "source": "reddit_api",
    }


def parse_praw_comment(c, post_id, subreddit, depth):
    utc = float(c.created_utc) if hasattr(c, "created_utc") else 0
    pid = c.parent_id or ""
    return {
        "comment_id": c.id,
        "post_id": post_id,
        "subreddit": subreddit,
        "parent_id": pid,
        "parent_type": "post" if pid.startswith("t3_") else "comment",
        "body": c.body,
        "author": str(c.author) if c.author else "[deleted]",
        "author_flair": c.author_flair_text or "",
        "score": c.score,
        "ups": c.ups,
        "controversiality": c.controversiality,
        "depth": depth,
        "is_submitter": c.is_submitter,
        "distinguished": c.distinguished or "",
        "stickied": c.stickied,
        "edited": bool(c.edited),
        "gilded": c.gilded,
        "total_awards": c.total_awards_received,
        "created_utc": utc,
        "created_dt": utc_to_dt(utc),
        "scraped_utc": utc_now(),
        "source": "reddit_api",
    }


def parse_arctic_comment(raw, post_id, subreddit):
    utc = float(raw.get("created_utc", 0))
    pid = raw.get("parent_id", "")
    return {
        "comment_id": raw.get("id", ""),
        "post_id": post_id,
        "subreddit": subreddit,
        "parent_id": pid,
        "parent_type": "post" if str(pid).startswith("t3_") else "comment",
        "body": raw.get("body", ""),
        "author": raw.get("author", ""),
        "author_flair": raw.get("author_flair_text", ""),
        "score": raw.get("score", ""),
        "ups": raw.get("ups", ""),
        "controversiality": raw.get("controversiality", ""),
        "depth": raw.get("depth", ""),
        "is_submitter": raw.get("is_submitter", ""),
        "distinguished": raw.get("distinguished", ""),
        "stickied": raw.get("stickied", ""),
        "edited": bool(raw.get("edited", False)),
        "gilded": raw.get("gilded", ""),
        "total_awards": raw.get("total_awards_received", ""),
        "created_utc": utc,
        "created_dt": utc_to_dt(utc),
        "scraped_utc": utc_now(),
        "source": "arctic_shift",
    }


def flatten_praw_tree(comments, post_id, subreddit, depth=0):
    """Recursively flatten a PRAW comment forest into a list of row dicts."""
    rows = []
    for c in comments:
        if isinstance(c, praw.models.MoreComments):
            continue
        rows.append(parse_praw_comment(c, post_id, subreddit, depth))
        if hasattr(c, "replies") and c.replies:
            rows.extend(flatten_praw_tree(c.replies, post_id, subreddit, depth + 1))
    return rows


class RedditScraper:
    """
    Main scraper. Instantiate once, then call scrape_subreddit(name) per target.

    All state lives in checkpoint.json inside the per-subreddit raw data
    directory (base_dir/data/raw/<subreddit>/). Safe to interrupt and re-run
    at any time.

    Parameters
    ----------
    client_id, client_secret, username, app_name : str
        Reddit API credentials. Create a script-type app at
        https://www.reddit.com/prefs/apps. App type "script" with read-only
        client_credentials flow (no password needed).
    base_dir : str or Path
        Where data is written. Output paths are:
            <base_dir>/data/raw/<subreddit>/posts.csv
            <base_dir>/data/raw/<subreddit>/comments.csv
            <base_dir>/data/raw/<subreddit>/checkpoint.json
    user_agent : str, optional
        Custom user agent. Defaults to "script:<app_name>:v1.0 (by /u/<username>)".
    """

    def __init__(
        self,
        client_id,
        client_secret,
        username,
        app_name,
        base_dir,
        user_agent=None,
    ):
        self.base_dir = Path(base_dir)
        self.arctic = ArcticShiftClient()
        ua = user_agent or f"script:{app_name}:v1.0 (by /u/{username})"
        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=ua,
        )
        self.reddit.read_only = True
        log.info("RedditScraper ready (PRAW read-only)")

    def _paths(self, subreddit):
        raw = self.base_dir / "data" / "raw" / subreddit.lower()
        raw.mkdir(parents=True, exist_ok=True)
        return {
            "posts": raw / "posts.csv",
            "comments": raw / "comments.csv",
            "checkpoint": raw / "checkpoint.json",
        }

    def _phase1_arctic(self, subreddit, paths, ckpt):
        """Page through all historical posts via Arctic Shift."""
        log.info(
            "[%s] Phase 1 (Arctic Shift): resuming from UTC %.0f (%s)",
            subreddit, ckpt.last_post_utc, utc_to_dt(ckpt.last_post_utc),
        )
        ensure_csv(paths["posts"], POST_COLS)
        after_utc, page, total = ckpt.last_post_utc, 0, 0

        while True:
            page += 1
            batch = self.arctic.fetch_posts_page(subreddit, after_utc)

            if not batch:
                if not ArcticShiftClient.available:
                    log.warning(
                        "Arctic Shift unavailable, falling back to Reddit API"
                    )
                    self._phase1_reddit_api(subreddit, paths, ckpt)
                    return
                log.info("[%s] No more posts from Arctic Shift, phase 1 done", subreddit)
                break

            rows = [parse_arctic_post(p, subreddit) for p in batch]
            append_rows(paths["posts"], rows, POST_COLS)
            last_utc = float(batch[-1].get("created_utc", after_utc))
            after_utc = last_utc
            total += len(rows)
            ckpt.add_posts(len(rows))
            ckpt.mark_post_utc(after_utc)

            log.info(
                "[%s] page %5d | batch %4d | total %9d | up to %s",
                subreddit, page, len(rows), total, utc_to_dt(after_utc),
            )

            if len(batch) < POSTS_PER_PAGE:
                break

        log.info("[%s] Phase 1 done: %d posts written.", subreddit, total)

    def _phase1_reddit_api(self, subreddit, paths, ckpt):
        """
        Fallback when Arctic Shift is unavailable. Cycles through
        new/top/controversial/hot listings to maximise coverage. The Reddit
        listing endpoint caps at ~1000 posts per category, so total reach
        is far smaller than Arctic Shift.
        """
        log.info("[%s] Phase 1 fallback: Reddit API listing", subreddit)
        ensure_csv(paths["posts"], POST_COLS)
        seen = set()
        if paths["posts"].stat().st_size > 100:
            try:
                seen = set(
                    pd.read_csv(paths["posts"], usecols=["post_id"])["post_id"].astype(str)
                )
                log.info("[%s] Loaded %d existing post IDs", subreddit, len(seen))
            except Exception:
                pass

        sub = self.reddit.subreddit(subreddit)
        listings = [
            ("new", sub.new(limit=None)),
            ("top_all", sub.top(time_filter="all", limit=None)),
            ("controversial", sub.controversial(time_filter="all", limit=None)),
            ("hot", sub.hot(limit=None)),
        ]
        for name, listing in listings:
            n = 0
            log.info("[%s] Listing: %s", subreddit, name)
            try:
                for s in listing:
                    if str(s.id) in seen:
                        continue
                    append_rows(paths["posts"], [parse_praw_post(s, subreddit)], POST_COLS)
                    seen.add(s.id)
                    ckpt.add_posts(1)
                    n += 1
                    time.sleep(REDDIT_SLEEP)
            except Exception as e:
                log.warning("[%s] Listing %s error: %s", subreddit, name, e)
            log.info("[%s] %s: %d new posts", subreddit, name, n)

    def _phase2(self, subreddit, paths, ckpt):
        """Fetch full comment tree for every post in posts.csv."""
        log.info("[%s] Phase 2: comment hydration", subreddit)
        ensure_csv(paths["comments"], COMMENT_COLS)

        try:
            all_ids = (
                pd.read_csv(paths["posts"], usecols=["post_id"])["post_id"]
                .dropna()
                .astype(str)
                .tolist()
            )
        except Exception as e:
            log.error("Cannot read posts.csv: %s", e)
            return

        done = ckpt.posts_done_set
        remaining = [pid for pid in all_ids if pid not in done]
        log.info(
            "[%s] %d total posts | %d done | %d remaining",
            subreddit, len(all_ids), len(done), len(remaining),
        )

        for i, post_id in enumerate(remaining, 1):
            comments = self._comments_for_post(post_id, subreddit)
            append_rows(paths["comments"], comments, COMMENT_COLS)
            ckpt.mark_comments_done(post_id, len(comments))
            if i % 250 == 0 or i == len(remaining):
                log.info(
                    "[%s] comments: %d/%d posts | last batch %d | total written %d",
                    subreddit, i, len(remaining), len(comments),
                    ckpt.data["total_comments_written"],
                )

    def _comments_for_post(self, post_id, subreddit):
        """
        Fetch the full comment tree for one post.

        Primary: PRAW with replace_more(limit=None, threshold=0) expands
        every MoreComments object recursively, giving complete trees
        including collapsed/low-score comments.

        Fallback: Arctic Shift /api/comments/search if PRAW raises.
        """
        try:
            submission = self.reddit.submission(id=post_id)
            submission.comments.replace_more(limit=None, threshold=0)
            rows = flatten_praw_tree(submission.comments, post_id, subreddit)
            time.sleep(REDDIT_SLEEP)
            return rows
        except praw.exceptions.PRAWException as e:
            log.warning("PRAW failed for %s: %s, trying Arctic Shift", post_id, e)
        except Exception as e:
            log.warning("PRAW error %s: %s, trying Arctic Shift", post_id, e)
        try:
            raw = self.arctic.fetch_all_comments(post_id)
            return [parse_arctic_comment(c, post_id, subreddit) for c in raw]
        except Exception as e:
            log.error("Both sources failed for %s: %s", post_id, e)
            return []

    def scrape_subreddit(self, subreddit):
        """
        Run the full pipeline for one subreddit. Safe to interrupt and re-run.

        Parameters
        ----------
        subreddit : str
            Subreddit name without the r/ prefix. Case-insensitive.
        """
        subreddit = subreddit.strip().lower()
        log.info("=" * 60)
        log.info("Scraping: r/%s", subreddit)
        log.info("=" * 60)

        paths = self._paths(subreddit)
        ckpt = Checkpoint(paths["checkpoint"], subreddit)

        if ckpt.phase == "posts":
            self._phase1_arctic(subreddit, paths, ckpt)
            ckpt.set_phase("comments")

        if ckpt.phase == "comments":
            self._phase2(subreddit, paths, ckpt)
            ckpt.set_phase("done")

        log.info("[%s] ALL DONE", subreddit)
        log.info("  Posts    : %d", ckpt.data["total_posts_written"])
        log.info("  Comments : %d", ckpt.data["total_comments_written"])
        log.info("  Posts CSV: %s", paths["posts"])
        log.info("  Cmts CSV : %s", paths["comments"])
        log.info("=" * 60)
