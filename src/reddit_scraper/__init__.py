"""
reddit_scraper: crash-safe, full-history Reddit scraper.

Exports:
    RedditScraper      main entry point
    ArcticShiftClient  low-level Arctic Shift wrapper (advanced use)
    Checkpoint         atomic per-subreddit progress file (advanced use)
    POST_COLS          column schema for posts.csv
    COMMENT_COLS       column schema for comments.csv
"""

from .scraper import (
    RedditScraper,
    ArcticShiftClient,
    Checkpoint,
    POST_COLS,
    COMMENT_COLS,
)

__version__ = "0.1.0"
__all__ = [
    "RedditScraper",
    "ArcticShiftClient",
    "Checkpoint",
    "POST_COLS",
    "COMMENT_COLS",
    "__version__",
]
