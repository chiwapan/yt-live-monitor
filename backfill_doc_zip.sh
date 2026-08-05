#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./backfill_doc_zip.sh <doc_zip_path> --start "YYYY-MM-DD HH:MM:SS" [--channel "ข่าวช่อง8"] [--video-id xxx]
# Example:
#   ./backfill_doc_zip.sh /opt/data/cache/documents/doc_xxx.zip --start "2026-07-23 13:05:00" --channel "ข่าวช่อง8"

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <doc_zip_path> --start 'YYYY-MM-DD HH:MM:SS' [--channel NAME] [--video-id ID] [--title TITLE] [--output PATH] [--dry-run]"
  exit 1
fi

ZIP_PATH="$1"
shift

python3 /opt/data/projects/yt-live-monitor/backfill_zip.py "$ZIP_PATH" "$@"
