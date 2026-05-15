#!/bin/bash
# =============================================================================
# run_subreddit.sh: generic auto-restart wrapper for a single subreddit
# =============================================================================
#
# The Arctic Shift API occasionally stalls or times out on high-volume time
# windows. The scraper itself is crash-safe (checkpoint after every batch),
# so the right strategy is simply to restart it on any non-clean exit. This
# script does exactly that.
#
# Usage:
#   bash scripts/run_subreddit.sh <subreddit> [base_dir]
#
# Examples:
#   bash scripts/run_subreddit.sh replika
#   bash scripts/run_subreddit.sh ChatGPT /Users/me/reddit-data
#
# Environment:
#   PYTHON       python interpreter to use (default: python3)
#   SLEEP_SECS   seconds between restarts on non-clean exit (default: 5)
#   LOGFILE      override log file path
# =============================================================================

set -u

SUBREDDIT="${1:-}"
BASE_DIR="${2:-$(pwd)}"
PYTHON="${PYTHON:-python3}"
SLEEP_SECS="${SLEEP_SECS:-5}"

if [ -z "$SUBREDDIT" ]; then
  echo "Usage: bash run_subreddit.sh <subreddit> [base_dir]" >&2
  exit 1
fi

SUB_LOWER=$(echo "$SUBREDDIT" | tr '[:upper:]' '[:lower:]')
LOGFILE="${LOGFILE:-$BASE_DIR/logs/${SUB_LOWER}_runner.log}"
CHECKPOINT="$BASE_DIR/data/raw/$SUB_LOWER/checkpoint.json"
mkdir -p "$(dirname "$LOGFILE")"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOGFILE"; }

log "=== r/$SUBREDDIT runner started ==="
log "base_dir   : $BASE_DIR"
log "checkpoint : $CHECKPOINT"
log "logfile    : $LOGFILE"

while true; do
  log "Launching scrape: r/$SUBREDDIT"
  "$PYTHON" -m reddit_scraper.cli "$SUBREDDIT" --base-dir "$BASE_DIR" >> "$LOGFILE" 2>&1
  EXIT=$?
  log "Process exited (code $EXIT)"

  if [ ! -f "$CHECKPOINT" ]; then
    log "No checkpoint found yet. Restarting in ${SLEEP_SECS}s..."
    sleep "$SLEEP_SECS"
    continue
  fi

  PHASE=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['phase'])" "$CHECKPOINT" 2>/dev/null)
  if [ "$PHASE" = "done" ]; then
    log "r/$SUBREDDIT COMPLETE. Exiting."
    break
  fi

  log "Not done (phase=$PHASE). Restarting in ${SLEEP_SECS}s..."
  sleep "$SLEEP_SECS"
done
