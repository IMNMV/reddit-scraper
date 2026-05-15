# Minimal R example.
#
# One-time setup:
#   install.packages(c("reticulate", "jsonlite", "dplyr", "readr",
#                      "stringr", "lubridate"))
#   reticulate::virtualenv_create("r-reddit")
#   reticulate::virtualenv_install("r-reddit", "reddit-scraper")
#
# Then copy credentials/template.R to credentials/reddit_creds.R
# and fill in your four Reddit API values.

source("R/scrape.R")

# One subreddit
scrape("replika")

# Several in parallel (macOS / Linux only; keep max_jobs <= 3)
scrape(c("ChatGPT", "ClaudeAI", "Anthropic"), parallel = TRUE, max_jobs = 3)

# Check progress later
status(c("replika", "ChatGPT", "ClaudeAI", "Anthropic"))

# Optional: clean and feature-engineer after scraping finishes
source("R/clean.R")
clean(c("replika", "ChatGPT", "ClaudeAI", "Anthropic"))
