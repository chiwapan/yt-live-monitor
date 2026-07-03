#!/bin/bash
# YouTube Live Daily Monitor — shell wrapper for cron (no_agent=True)
# Sources env vars from .env if present, otherwise expects them set externally.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if it exists (optional, for manual runs)
[ -f "$SCRIPT_DIR/.env" ] && set -a && . "$SCRIPT_DIR/.env" && set +a

cd "$SCRIPT_DIR" || exit 1
exec /opt/hermes/.venv/bin/python3 yt-live-daily.py