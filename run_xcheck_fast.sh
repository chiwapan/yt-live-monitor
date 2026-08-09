#!/usr/bin/env bash
cd /opt/data/projects/yt-live-monitor
export YOUTUBE_API_KEY=$(grep -E "^YOUTUBE_API_KEY=" .env | head -1 | cut -d= -f2)
exec /opt/hermes/.venv/bin/python3 xcheck_karma_fast.py
