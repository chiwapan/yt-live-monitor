#!/bin/bash
export PORT=8889
cd /opt/data/projects/yt-live-monitor/web
exec /opt/hermes/.venv/bin/python3 /opt/data/projects/yt-live-monitor/web/app.py
