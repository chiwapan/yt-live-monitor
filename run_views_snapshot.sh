#!/usr/bin/env bash
# Views snapshot (yt-views-collector MODE=snapshot) — รันทุกชั่วโมง ผ่าน cron no_agent
# โหลด key จาก .env ของโปรเจกต์โดยตรง (deterministic, ไม่พึ่ง env ของ cron shell)
# NOTE: ไม่กระทบ live collector (คนละ script/service)
set -uo pipefail
HERE="/opt/data/projects/yt-live-monitor"
cd "$HERE"

# โหลด .env (เฉพาะ YOUTUBE_API_KEY ที่ views snapshot ต้องการ)
if [ -f "$HERE/.env" ]; then
    export YOUTUBE_API_KEY=$(grep -E "^YOUTUBE_API_KEY=" "$HERE/.env" | head -1 | cut -d= -f2)
fi

export MODE=snapshot
export VIEWS_LIVE_JSONL=/opt/data/projects/yt-live-monitor/views_live.jsonl
export SNAPSHOT_TOP=15

/usr/bin/python3 "$HERE/yt-views-collector.py" 2>&1
