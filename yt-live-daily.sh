#!/bin/bash
# YouTube Live Daily Monitor — shell wrapper for cron (no_agent=True)
# Sources env vars from .env if present, otherwise expects them set externally.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if it exists (optional, for manual runs)
[ -f "$SCRIPT_DIR/.env" ] && set -a && . "$SCRIPT_DIR/.env" && set +a

cd "$SCRIPT_DIR" || exit 1
# ⚠️ production: wrapper นี้ถูกเรียกโดย cron ที่ตั้งใจให้รันจริง → ผ่าน guard
# (แยกจาก dev/test ที่รัน yt-live-daily.py ตรงๆ มือ จะโดนบล็อกไม่ให้ใช้ key จริง)
export YT_LIVE_PRODUCTION=1
exec /opt/hermes/.venv/bin/python3 yt-live-daily.py