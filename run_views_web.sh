#!/usr/bin/env bash
# Run YT Views Monitor web (app.py) on port 8899
# Reads views_live.jsonl + live_data.jsonl directly (no CMS needed)
cd /opt/data/projects/yt-live-monitor/web
export PORT=8899
export VIEWS_LIVE_JSONL=/opt/data/projects/yt-live-monitor/views_live.jsonl
export LIVE_JSONL=/opt/data/projects/yt-live-monitor/live_data.jsonl
exec /opt/hermes/.venv/bin/python3 app.py
