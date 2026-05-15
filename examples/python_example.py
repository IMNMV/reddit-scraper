"""
Minimal Python example.

Before running:
    pip install git+https://github.com/IMNMV/reddit-scraper.git
    (or, from a clone: pip install -e .)

Then set your credentials in environment variables, or edit the
RedditScraper(...) call below.
"""

import os
from reddit_scraper import RedditScraper

scraper = RedditScraper(
    client_id=os.environ["REDDIT_CLIENT_ID"],
    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
    username=os.environ["REDDIT_USERNAME"],
    app_name=os.environ["REDDIT_APP_NAME"],
    base_dir=".",
)

# Output lands at ./data/raw/replika/{posts,comments,checkpoint}.csv|json
scraper.scrape_subreddit("replika")
