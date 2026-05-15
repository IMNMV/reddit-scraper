# =============================================================================
# clean.R: optional cleaning + feature engineering for scraped CSVs
# =============================================================================
#
# Reads <base_dir>/data/raw/<subreddit>/{posts,comments}.csv and writes
#       <base_dir>/data/processed/<subreddit>/{posts_clean,comments_clean}.csv
#
# Adds derived columns useful for NLP / longitudinal work:
#   year, month, quarter, yearmonth, yearquarter, day_of_week, hour_utc
#   est_upvotes, est_downvotes (Reddit obfuscates raw vote counts; these are
#                               the standard estimates used in published work)
#   selftext_clean / body_clean (markdown and URL stripped for NLP)
#   is_deleted, is_removed, is_bot flags
#
# Usage:
#   source("R/clean.R")
#   clean("replika")
#   clean(c("ChatGPT", "ClaudeAI", "Anthropic", "OpenAI"))
#
# Vote estimation rationale:
#   Reddit's API no longer exposes raw up and down counts. Standard practice
#   in published NLP work is to estimate from score and upvote_ratio:
#       est_upvotes   = round(score / upvote_ratio)
#       est_downvotes = est_upvotes - score
#   For comments, upvote_ratio is not provided; ups equals score post-2014.
# =============================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(lubridate)
})

BASE_DIR <- Sys.getenv("REDDIT_BASE_DIR", unset = getwd())

raw_path <- function(subreddit, file, base_dir = BASE_DIR) {
  file.path(base_dir, "data", "raw", tolower(subreddit), file)
}

processed_path <- function(subreddit, file, base_dir = BASE_DIR) {
  p <- file.path(base_dir, "data", "processed", tolower(subreddit))
  dir.create(p, recursive = TRUE, showWarnings = FALSE)
  file.path(p, file)
}

log_msg <- function(...) message(format(Sys.time(), "%H:%M:%S"), " ", ...)

clean_posts <- function(df, subreddit) {
  log_msg("Cleaning posts: ", nrow(df), " rows")
  df <- df %>%
    distinct(post_id, .keep_all = TRUE) %>%
    mutate(
      is_deleted = author %in% c("[deleted]", "[removed]", "NA", NA),
      is_removed = selftext %in% c("[deleted]", "[removed]"),
      created_utc = as.numeric(created_utc),
      created_dt  = as.POSIXct(created_utc, origin = "1970-01-01", tz = "UTC"),
      year        = year(created_dt),
      month       = month(created_dt),
      quarter     = quarter(created_dt),
      yearmonth   = format(created_dt, "%Y-%m"),
      yearquarter = paste0(year, "-Q", quarter),
      day_of_week = wday(created_dt, label = TRUE, abbr = TRUE),
      hour_utc    = hour(created_dt),
      score        = as.numeric(score),
      upvote_ratio = as.numeric(upvote_ratio),
      est_upvotes = if_else(
        !is.na(upvote_ratio) & upvote_ratio > 0,
        round(score / upvote_ratio), NA_real_
      ),
      est_downvotes = if_else(
        !is.na(est_upvotes), est_upvotes - score, NA_real_
      ),
      controversy_ratio = if_else(
        !is.na(est_upvotes) & est_upvotes > 0,
        est_downvotes / est_upvotes, NA_real_
      ),
      has_body     = !is.na(selftext) & !selftext %in% c("", "[deleted]", "[removed]"),
      body_length  = nchar(if_else(has_body, selftext, "")),
      title_length = nchar(as.character(title)),
      selftext_clean = selftext %>%
        str_replace_all("https?://\\S+", " ") %>%
        str_replace_all("\\[([^\\]]+)\\]\\([^)]+\\)", "\\1") %>%
        str_replace_all("[*_~`#>|]", " ") %>%
        str_replace_all("&amp;|&lt;|&gt;|&nbsp;", " ") %>%
        str_squish(),
      is_bot = str_detect(
        tolower(as.character(author)),
        "bot$|automoderator|automod|reddit_bot|transcribers|repostsleuth"
      ),
      subreddit = tolower(subreddit)
    )
  log_msg(
    "After cleaning: ", nrow(df), " rows | ",
    sum(df$is_deleted, na.rm = TRUE), " deleted | ",
    sum(df$is_removed, na.rm = TRUE), " removed | ",
    sum(df$is_bot, na.rm = TRUE), " bots"
  )
  df
}

clean_comments <- function(df, subreddit) {
  log_msg("Cleaning comments: ", nrow(df), " rows")
  df <- df %>%
    distinct(comment_id, .keep_all = TRUE) %>%
    mutate(
      is_deleted = author %in% c("[deleted]", "[removed]", "NA", NA),
      is_removed = body   %in% c("[deleted]", "[removed]"),
      created_utc = as.numeric(created_utc),
      created_dt  = as.POSIXct(created_utc, origin = "1970-01-01", tz = "UTC"),
      year        = year(created_dt),
      month       = month(created_dt),
      quarter     = quarter(created_dt),
      yearmonth   = format(created_dt, "%Y-%m"),
      yearquarter = paste0(year, "-Q", quarter),
      day_of_week = wday(created_dt, label = TRUE, abbr = TRUE),
      hour_utc    = hour(created_dt),
      score            = as.numeric(score),
      ups              = as.numeric(ups),
      controversiality = as.numeric(controversiality),
      est_upvotes      = ups,
      est_downvotes    = if_else(!is.na(ups) & !is.na(score), ups - score, NA_real_),
      is_controversial = controversiality == 1,
      body_length = nchar(as.character(body)),
      body_clean  = body %>%
        str_replace_all("https?://\\S+", " ") %>%
        str_replace_all("\\[([^\\]]+)\\]\\([^)]+\\)", "\\1") %>%
        str_replace_all("[*_~`#>|]", " ") %>%
        str_replace_all("&amp;|&lt;|&gt;|&nbsp;", " ") %>%
        str_squish(),
      is_bot = str_detect(
        tolower(as.character(author)),
        "bot$|automoderator|automod|reddit_bot|transcribers|repostsleuth"
      ),
      subreddit = tolower(subreddit)
    )
  log_msg(
    "After cleaning: ", nrow(df), " rows | ",
    sum(df$is_deleted, na.rm = TRUE), " deleted | ",
    sum(df$is_removed, na.rm = TRUE), " removed | ",
    sum(df$is_bot, na.rm = TRUE), " bots | ",
    sum(df$is_controversial, na.rm = TRUE), " controversial"
  )
  df
}

#' Clean raw scraped data for one or more subreddits
#'
#' @param subreddits Character vector of subreddit names.
#' @param base_dir   Output root (defaults to env var or cwd).
clean <- function(subreddits, base_dir = BASE_DIR) {
  for (sub in subreddits) {
    log_msg("=== Processing r/", sub, " ===")

    posts_raw <- raw_path(sub, "posts.csv", base_dir)
    if (file.exists(posts_raw)) {
      log_msg("Reading posts...")
      posts <- read_csv(posts_raw, col_types = cols(.default = "c"), show_col_types = FALSE)
      posts <- clean_posts(posts, sub)
      out   <- processed_path(sub, "posts_clean.csv", base_dir)
      write_csv(posts, out)
      log_msg("Posts saved: ", out)
    } else {
      log_msg("No posts.csv for r/", sub)
    }

    comments_raw <- raw_path(sub, "comments.csv", base_dir)
    if (file.exists(comments_raw)) {
      log_msg("Reading comments...")
      comments <- read_csv(comments_raw, col_types = cols(.default = "c"), show_col_types = FALSE)
      comments <- clean_comments(comments, sub)
      out      <- processed_path(sub, "comments_clean.csv", base_dir)
      write_csv(comments, out)
      log_msg("Comments saved: ", out)
    } else {
      log_msg("No comments.csv for r/", sub, " (may still be scraping)")
    }
  }
  log_msg("All done.")
}
