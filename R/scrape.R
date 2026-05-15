# =============================================================================
# scrape.R: R wrapper around the Python reddit_scraper package
# =============================================================================
#
# Lets R users drive the scraper without touching Python directly. Calls into
# the installed Python package via reticulate.
#
# QUICK START
# -----------
#   source("R/scrape.R")
#   scrape("replika")                             # one subreddit
#   scrape(c("ChatGPT", "ClaudeAI"))              # sequential
#   scrape(c("ChatGPT", "ClaudeAI"), parallel=TRUE, max_jobs=3)  # parallel
#   status("replika")                             # print progress
#
# COMMAND LINE
# ------------
#   Rscript R/scrape.R --subreddit replika
#   Rscript R/scrape.R --status --subreddit replika
#
# CONFIGURATION (env vars, all optional)
# --------------------------------------
#   REDDIT_PYTHON_ENV   virtualenv name to use (default: "r-reddit")
#   REDDIT_BASE_DIR     output root (default: getwd())
#   REDDIT_CREDS_PATH   path to credentials/reddit_creds.R
#                       (default: credentials/reddit_creds.R under BASE_DIR)
#
# REQUIREMENTS
# ------------
#   R: reticulate, jsonlite, parallel
#   Python virtualenv with the reddit-scraper package installed:
#     reticulate::virtualenv_create("r-reddit")
#     reticulate::virtualenv_install("r-reddit", "reddit-scraper")
# =============================================================================

suppressPackageStartupMessages({
  library(reticulate)
  library(jsonlite)
  library(parallel)
})

PYTHON_ENV <- Sys.getenv("REDDIT_PYTHON_ENV", unset = "r-reddit")
BASE_DIR   <- Sys.getenv("REDDIT_BASE_DIR",   unset = getwd())
CREDS_PATH <- Sys.getenv(
  "REDDIT_CREDS_PATH",
  unset = file.path(BASE_DIR, "credentials", "reddit_creds.R")
)

.init_python <- function() {
  use_virtualenv(PYTHON_ENV, required = TRUE)
  import("reddit_scraper")
}

.load_creds <- function() {
  if (!file.exists(CREDS_PATH)) {
    stop(
      "Credentials not found at: ", CREDS_PATH,
      "\nCopy credentials/template.R to credentials/reddit_creds.R and fill it in."
    )
  }
  source(CREDS_PATH, local = TRUE)
  list(
    client_id     = get("REDDIT_CLIENT_ID"),
    client_secret = get("REDDIT_CLIENT_SECRET"),
    username      = get("REDDIT_USERNAME"),
    app_name      = get("REDDIT_APP_NAME")
  )
}

.checkpoint_path <- function(subreddit, base_dir = BASE_DIR) {
  file.path(base_dir, "data", "raw", tolower(subreddit), "checkpoint.json")
}

#' Print progress for one or more subreddits
#'
#' @param subreddits Character vector of subreddit names.
#' @param base_dir   Output root (defaults to env var or cwd).
#' @return Data frame with phase, posts, comments, stale_mins per subreddit.
status <- function(subreddits, base_dir = BASE_DIR) {
  rows <- lapply(subreddits, function(s) {
    cp <- .checkpoint_path(s, base_dir)
    if (!file.exists(cp)) {
      return(data.frame(
        subreddit = s, phase = "not started", posts = 0,
        comments = 0, stale_mins = NA_real_, stringsAsFactors = FALSE
      ))
    }
    d <- tryCatch(fromJSON(cp), error = function(e) NULL)
    if (is.null(d)) {
      return(data.frame(
        subreddit = s, phase = "error", posts = 0,
        comments = 0, stale_mins = NA_real_, stringsAsFactors = FALSE
      ))
    }
    stale <- as.numeric(difftime(
      Sys.time(),
      as.POSIXct(d$updated_at, format = "%Y-%m-%dT%H:%M:%S", tz = "UTC"),
      units = "mins"
    ))
    data.frame(
      subreddit  = s,
      phase      = d$phase,
      posts      = d$posts_discovered,
      comments   = d$total_comments_written,
      stale_mins = round(stale, 1),
      stringsAsFactors = FALSE
    )
  })
  df <- do.call(rbind, rows)
  print(df, row.names = FALSE)
  invisible(df)
}

.scrape_one <- function(subreddit, base_dir, creds_path, python_env) {
  library(reticulate)
  use_virtualenv(python_env, required = TRUE)
  rs <- import("reddit_scraper")
  source(creds_path, local = TRUE)
  dir.create(
    file.path(base_dir, "data", "raw", tolower(subreddit)),
    recursive = TRUE, showWarnings = FALSE
  )
  s <- rs$RedditScraper(
    client_id     = get("REDDIT_CLIENT_ID"),
    client_secret = get("REDDIT_CLIENT_SECRET"),
    username      = get("REDDIT_USERNAME"),
    app_name      = get("REDDIT_APP_NAME"),
    base_dir      = base_dir
  )
  s$scrape_subreddit(subreddit)
  invisible(NULL)
}

#' Scrape one or more subreddits
#'
#' Each subreddit is independent (separate CSVs and checkpoint). Safe to
#' interrupt and re-run; progress resumes from checkpoint.json.
#'
#' @param subreddits Character vector of subreddit names (no r/ prefix).
#' @param parallel   Logical. Run subreddits concurrently? macOS/Linux only.
#' @param max_jobs   Max concurrent workers when parallel=TRUE. Keep <= 3 to
#'                   respect Reddit API rate limits on a single account.
#' @param base_dir   Output root (defaults to env var or cwd).
scrape <- function(subreddits, parallel = FALSE, max_jobs = 3,
                   base_dir = BASE_DIR) {
  subreddits <- unique(trimws(subreddits))
  message(sprintf("Targets : %s", paste(subreddits, collapse = ", ")))
  message(sprintf(
    "Mode    : %s",
    if (parallel) sprintf("parallel (max_jobs=%d)", max_jobs) else "sequential"
  ))
  message(strrep("-", 50))

  worker <- function(sub) {
    message(sprintf("[%s] Starting r/%s", format(Sys.time(), "%H:%M:%S"), sub))
    tryCatch(
      .scrape_one(sub, base_dir, CREDS_PATH, PYTHON_ENV),
      error = function(e) message(sprintf(
        "[%s] ERROR r/%s: %s",
        format(Sys.time(), "%H:%M:%S"), sub, e$message
      ))
    )
    message(sprintf("[%s] Done r/%s", format(Sys.time(), "%H:%M:%S"), sub))
  }

  if (parallel && length(subreddits) > 1) {
    if (.Platform$OS.type == "windows") {
      message("WARNING: parallel=TRUE not supported on Windows. Running sequentially.")
      lapply(subreddits, worker)
    } else {
      n_cores <- min(max_jobs, length(subreddits), detectCores() - 1)
      message(sprintf("Launching %d parallel workers...", n_cores))
      mclapply(subreddits, worker, mc.cores = n_cores)
    }
  } else {
    lapply(subreddits, worker)
  }

  message(strrep("-", 50))
  message("Final status:")
  status(subreddits, base_dir)
  invisible(NULL)
}

if (!interactive()) {
  args <- commandArgs(trailingOnly = TRUE)
  get_arg <- function(flag, default = NULL) {
    i <- which(args == flag)
    if (length(i) && i < length(args)) args[i + 1] else default
  }

  sub <- get_arg("--subreddit")
  if (is.null(sub)) stop("Usage: Rscript scrape.R --subreddit <name> [--status]")

  if ("--status" %in% args) {
    status(sub)
  } else {
    scrape(sub)
  }
}
