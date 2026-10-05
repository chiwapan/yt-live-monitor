#!/bin/bash
cd /opt/data/projects/yt-live-monitor/web
export PORT=8899
exec /opt/hermes/.venv/bin/python3 /opt/data/projects/yt-live-monitor/web/app.py
