#!/usr/bin/env bash
# run_full_refresh.sh — เติม seen file ครอบคลุมคลิปทั้งเดือน + รัน snapshot รอบใหญ่
# แก้บั๊กวิวค้าง/ไม่ตรงยูทูบ (ทุกลlive ทุกช่อง)
set -uo pipefail
HERE="/opt/data/projects/yt-live-monitor"
cd "$HERE" || exit 1

if [ -f "$HERE/.env" ]; then
    export YOUTUBE_API_KEY=$(grep -E "^YOUTUBE_API_KEY=" "$HERE/.env" | head -1 | cut -d= -f2)
fi
export SEEN_PAGES=10

echo "=== Step 1: build seen from playlists (all channels, whole month) ==="
/usr/bin/python3 "$HERE/build_seen_from_playlist.py" 2>&1 | tail -45

echo ""
echo "=== Step 2: full snapshot to refresh ALL channels' view counts ==="
export MODE=snapshot
export VIEWS_LIVE_JSONL="$HERE/views_live.jsonl"
export SNAPSHOT_TOP=15
/usr/bin/python3 "$HERE/yt-views-collector.py" 2>&1 | tail -5

echo "=== Done at $(date) ==="
