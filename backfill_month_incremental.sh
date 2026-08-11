#!/usr/bin/env bash
# backfill_month_incremental.sh — เติมคลิปใหม่เข้า views_month.jsonl แบบ增量
# แก้บั๊ก: endpoint /api/views-today ว่าง เพราะ views_month.jsonl หยุดอัปเดตตั้งแต่รัน totals ครั้งสุดท้าย
#   - snapshot (run_views_snapshot.sh) เขียนแค่ views_live.jsonl (ไม่มี published_at)
#   - views-today กรอง published_at จาก views_month.jsonl → วันใหม่เลย 0 ตัว
# วิธี: หา video_id ที่อยู่ใน views_live.jsonl แต่ยังไม่มีใน views_month.jsonl
#       ดึง publishedAt + statistics จริงจาก YouTube Data API (videos.list) แล้วต่อท้ายเข้า views_month.jsonl
# รัน: ทุกวันตอนเที่ยงคืน (หรือ manual) — ใช้ quota นิดเดียว (1 unit / 50 วิดีโอ)
set -uo pipefail
HERE="/opt/data/projects/yt-live-monitor"
cd "$HERE" || exit 1

if [ -f "$HERE/.env" ]; then
    export YOUTUBE_API_KEY=$(grep -E "^YOUTUBE_API_KEY=" "$HERE/.env" | head -1 | cut -d= -f2)
fi
export PYTHONIOENCODING=utf-8
/usr/bin/python3 "$HERE/backfill_month_incremental.py" 2>&1
