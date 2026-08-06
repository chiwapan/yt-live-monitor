#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  Isolate YT Live Collector — ย้าย source ไป /docker/yt-live-collector
#  (นอก Hermes bind mount) → Hermes แตะไม่ได้ ไม่มีวันไปกระทบ
#
#  รันจาก HOST:  bash /docker/hermes-agent-r6gh/data/projects/yt-live-monitor/deploy_isolate_collector.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SRC=/docker/hermes-agent-r6gh/data/projects/yt-live-monitor
COL=/docker/yt-live-collector

echo "==> [1/8] สร้าง dir โดดเดี่ยว: $COL"
mkdir -p "$COL"

echo "==> [2/8] คัดลอก source ไปที่ Hermes เข้าไม่ถึง"
for f in yt-live-daily.py run_collector.py google_api.py _hermes_home.py token_sheets.json; do
  cp "$SRC/$f" "$COL/$f"
  echo "    ✓ $f"
done
cp "$SRC/.env" "$COL/.env"
echo "    ✓ .env"

echo "==> [3/8] บันทึกสถานะ data ก่อน (เพื่อ verify ว่าไม่หายหลัง migration)"
BEFORE_ROWS=$(wc -l < "$SRC/live_data.jsonl")
BEFORE_MTIME=$(stat -c %Y "$SRC/live_data.jsonl")
echo "    live_data.jsonl ก่อน: $BEFORE_ROWS rows, mtime=$(date -d @$BEFORE_MTIME +%H:%M:%S)"

echo "==> [4/8] เขียน Dockerfile + compose โดดเดี่ยว"
cat > "$COL/Dockerfile" <<'DOCK'
FROM python:3.13-slim
WORKDIR /app
COPY yt-live-daily.py .
COPY run_collector.py .
COPY google_api.py .
COPY _hermes_home.py .
COPY token_sheets.json .
ENV TZ=Asia/Bangkok \
    LIVE_JSONL=/data/live_data.jsonl \
    STATE_FILE=/data/yt-live-daily-state.json \
    GAPI_SCRIPT=/app/google_api.py \
    PYTHONUNBUFFERED=1
CMD ["python", "run_collector.py"]
DOCK

cat > "$COL/docker-compose.yml" <<'YML'
services:
  collector:
    build: .
    image: yt-live-collector:isolated
    container_name: yt-live-collector
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - LIVE_JSONL=/data/live_data.jsonl
      - STATE_FILE=/data/yt-live-daily-state.json
      - GAPI_SCRIPT=/app/google_api.py
    volumes:
      - /docker/hermes-agent-r6gh/data/projects/yt-live-monitor/live_data.jsonl:/data/live_data.jsonl
      - /docker/hermes-agent-r6gh/data/projects/yt-live-monitor/yt-live-daily-state.json:/data/yt-live-daily-state.json
    healthcheck:
      test: ["CMD", "python", "-c", "import os,time; s=os.path.getmtime('/data/live_data.jsonl'); raise SystemExit(1 if time.time()-s>420 else 0)"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
YML

echo "==> [5/8] บันทึกสถานะ data หลัง (เพื่อ verify ว่าไม่หายหลัง migration)"
AFTER_ROWS=$(wc -l < "$SRC/live_data.jsonl")
AFTER_MTIME=$(stat -c %Y "$SRC/live_data.jsonl")
echo "    live_data.jsonl หลัง: $AFTER_ROWS rows, mtime=$(date -d @$AFTER_MTIME +%H:%M:%S)"
echo "    → rows เพิ่ม: $((AFTER_ROWS - BEFORE_ROWS)) แถว (ควร > 0 เพราะ collector ยังเขียนต่อ)"

echo "==> [6/8] หยุด collector เก่า (ตัวใน main stack) ก่อนขึ้นตัวใหม่ — กัน 2 ตัวเขียนไฟล์พร้อมกัน"
docker stop yt-live-monitor-collector 2>/dev/null && echo "    ✓ หยุด yt-live-monitor-collector แล้ว" || echo "    ℹ️ ไม่พบ yt-live-monitor-collector (อาจถูกลบแล้ว)"

echo "==> [7/8] build + up collector โดดเดี่ยว"
cd "$COL"
docker compose up -d --build

echo "==> [8/8] recreate main stack (web+cloudflared) — เอา collector เก่าออกจาก main"
cd "$SRC"
docker compose -f docker-compose.hostinger.yml up -d --force-recreate web cloudflared

echo "==> Verify หลัง migration: data ต้องยังไหล"
sleep 300
VERIFY_ROWS=$(wc -l < "$SRC/live_data.jsonl")
echo "    live_data.jsonl หลัง migration 5 นาที: $VERIFY_ROWS rows (ก่อน: $BEFORE_ROWS)"
echo "    → rows เพิ่ม: $((VERIFY_ROWS - BEFORE_ROWS)) แถว"

echo "==> [Verify] ตรวจขั้นสุดท้าย"
echo "--- collector โดดเดี่ยว ---"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep yt-live-collector || true
echo "--- main stack (web+cloudflared) ---"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep yt-live-monitor || true
echo ""
echo "DONE — collector ตอนนี้ independent แล้ว (Hermes แตะ /docker/yt-live-collector ไม่ได้)"