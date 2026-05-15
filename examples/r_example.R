# Using reddit-scraper from R via reticulate
#
# This package is Python-only, but the R reticulate library can drive it
# directly with no separate R wrapper required.
#
# One-time setup:
#   install.packages("reticulate")
#   reticulate::virtualenv_create("r-reddit")
#   reticulate::virtualenv_install("r-reddit", "reddit-scraper")
#
# Then:

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

# Output lands at ./data/raw/replika/{posts,comments,checkpoint}.csv|json
scraper$scrape_subreddit("replika")
