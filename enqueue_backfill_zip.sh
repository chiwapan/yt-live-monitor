#!/usr/bin/env bash
set -euo pipefail

# Usage:
# ./enqueue_backfill_zip.sh <zip_path> "YYYY-MM-DD HH:MM:SS" "channel" [video_id] [title_override]

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <zip_path> <start_ts> <channel> [video_id] [title_override]"
  exit 1
fi

QUEUE_FILE="/opt/data/projects/yt-live-monitor/backfill_queue.tsv"
ZIP_PATH="$1"
START_TS="$2"
CHANNEL="$3"
VIDEO_ID="${4:-}"
TITLE_OVERRIDE="${5:-}"

mkdir -p "$(dirname "$QUEUE_FILE")"

# tab-separated: zip_path  start_ts  channel  video_id  title_override
printf '%s\t%s\t%s\t%s\t%s\n' "$ZIP_PATH" "$START_TS" "$CHANNEL" "$VIDEO_ID" "$TITLE_OVERRIDE" >> "$QUEUE_FILE"

echo "queued: $ZIP_PATH"
