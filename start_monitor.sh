#!/bin/bash
# Launcher for YT Live Monitor (port 8899) — keeps it alive independent of Hermes terminal session
cd /opt/data/projects/yt-live-monitor/web
export PORT=8899
exec /opt/hermes/.venv/bin/python3 app.py >> /tmp/dashboard_8899.log 2>&1
