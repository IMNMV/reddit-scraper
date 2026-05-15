"""
reddit_scraper.cli

Command-line entry point. Installed as `reddit-scraper` by pyproject.toml.

Usage:
    reddit-scraper <subreddit> [--base-dir PATH] [--creds PATH]
    reddit-scraper --status <subreddit> [--base-dir PATH]
    reddit-scraper --help

Credentials are loaded from (in order):
    1. CLI flags --client-id / --client-secret / --username / --app-name
    2. --creds PATH (Python file defining REDDIT_CLIENT_ID etc.)
    3. Environment variables REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
       REDDIT_USERNAME, REDDIT_APP_NAME
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .scraper import RedditScraper


def load_creds_file(path):
    """Load REDDIT_* variables from a Python file."""
    ns = {}
    with open(path) as f:
        exec(compile(f.read(), str(path), "exec"), ns)
    return {
        "client_id": ns.get("REDDIT_CLIENT_ID"),
        "client_secret": ns.get("REDDIT_CLIENT_SECRET"),
        "username": ns.get("REDDIT_USERNAME"),
        "app_name": ns.get("REDDIT_APP_NAME"),
    }


def resolve_creds(args):
    creds = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "username": args.username,
        "app_name": args.app_name,
    }
    if args.creds and Path(args.creds).exists():
        file_creds = load_creds_file(args.creds)
        for k, v in file_creds.items():
            if creds[k] is None and v is not None:
                creds[k] = v
    env_map = {
        "client_id": "REDDIT_CLIENT_ID",
        "client_secret": "REDDIT_CLIENT_SECRET",
        "username": "REDDIT_USERNAME",
        "app_name": "REDDIT_APP_NAME",
    }
    for k, env in env_map.items():
        if creds[k] is None:
            creds[k] = os.environ.get(env)
    missing = [k for k, v in creds.items() if not v]
    if missing:
        sys.exit(
            f"Missing credentials: {', '.join(missing)}. "
            "Pass via flags, --creds FILE, or env vars."
        )
    return creds


def cmd_status(args):
    cp = Path(args.base_dir) / "data" / "raw" / args.subreddit.lower() / "checkpoint.json"
    if not cp.exists():
        print(f"No checkpoint at {cp}")
        sys.exit(1)
    with open(cp) as f:
        d = json.load(f)
    posts_done = len(d.get("posts_done_comments", []))
    total = d.get("posts_discovered", 0)
    pct = (100 * posts_done / total) if total else 0
    print(f"Subreddit : r/{d['subreddit']}")
    print(f"Phase     : {d['phase']}")
    print(f"Posts     : {total:,}")
    print(f"Comments  : {d.get('total_comments_written', 0):,}")
    print(f"Phase 2   : {posts_done:,}/{total:,} posts ({pct:.1f}%)")
    print(f"Updated   : {d.get('updated_at', '')}")


def cmd_scrape(args):
    creds = resolve_creds(args)
    scraper = RedditScraper(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        username=creds["username"],
        app_name=creds["app_name"],
        base_dir=args.base_dir,
    )
    scraper.scrape_subreddit(args.subreddit)


def build_parser():
    p = argparse.ArgumentParser(
        prog="reddit-scraper",
        description=(
            "Crash-safe Reddit scraper. Full history via Arctic Shift, "
            "full comment trees via PRAW. Resume by re-running the same command."
        ),
    )
    p.add_argument("subreddit", help="Subreddit name without the r/ prefix")
    p.add_argument(
        "--base-dir",
        default=".",
        help="Output root. Data lands at <base-dir>/data/raw/<subreddit>/. Default: cwd",
    )
    p.add_argument("--creds", help="Path to a Python creds file (see credentials/template.py)")
    p.add_argument("--client-id")
    p.add_argument("--client-secret")
    p.add_argument("--username")
    p.add_argument("--app-name")
    p.add_argument("--status", action="store_true", help="Print progress and exit")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.status:
        cmd_status(args)
    else:
        cmd_scrape(args)


if __name__ == "__main__":
    main()
