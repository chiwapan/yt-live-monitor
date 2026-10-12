#!/usr/bin/env bash
# host_selfheal.sh — รันบน HOST ผ่าน cron */5 (ต้องเป็น root หรือ user ที่มีสิทธิ์ docker)
# หน้าที่: จับ "collector Up แต่ tick เงียบ" แล้ว docker restart ให้เอง (self-heal)
#
# ตรรกะ (ออกแบบ 12/10/69):
#   - วัด mtime ของ yt-live-daily-state.json ซึ่ง collector เขียน ทุก tick เสมอ
#     (แม้ไม่มี live stream — ต่างจาก live_data.jsonl ที่เงียบได้ตรงเวลา)
#   - เกณฑ์ 900 วิ = พลาด cold round 3 รอบติด = ค้างจริง ไม่ใช่ปกติ
#   - guard กัน restart storm: >=5 ครั้งใน 1 ชม → เลิกปลุก, log ไว้ (watchdog ฝั่ง
#     Hermes จะ alert เอง) — เพราะพังระดับโค้ด restart ไปก็ไร้ประโยชน์ ซ้ำเติม log
#   - กันปลุก container ที่เพิ่ง start (<200 วิ) — อาจกำลัง boot ปกติ
#   - ไม่แตะไฟล์ bind-mount ใดๆ เลย (stat อย่างเดียว) — ปลอดภัยกับ Docker mount rule
#
# Install (บน host, ครั้งเดียว):
#   crontab -l 2>/dev/null | grep -v host_selfheal > /tmp/ct
#   echo '*/5 * * * * bash /docker/hermes-agent-r6gh/data/projects/thairath/yt-live-monitor/host_selfheal.sh >/dev/null 2>&1' >> /tmp/ct
#   crontab /tmp/ct && rm /tmp/ct
set -u

REPO="${REPO:-/docker/hermes-agent-r6gh/data/projects/thairath/yt-live-monitor}"
CONTAINER="${CONTAINER:-yt-live-monitor-collector}"
STATE="$REPO/yt-live-daily-state.json"
LOG="${LOG:-/docker/hermes-agent-r6gh/data/logs/host-selfheal.log}"
DOCKBIN="${DOCKBIN:-/usr/bin/docker}"
STALE_SEC="${STALE_SEC:-900}"
MAX_RESTARTS_PER_HOUR="${MAX_RESTARTS_PER_HOUR:-5}"

mkdir -p "$(dirname "$LOG")"
ts=$(date -u '+%F %T')

if [ ! -e "$DOCKBIN" ]; then
  echo "$ts SKIP_NO_DOCKER $DOCKBIN" >> "$LOG"; exit 0   # sandbox/ที่อื่น — เงียบปลอดภัย
fi
if [ ! -f "$STATE" ]; then
  echo "$ts ERR_STATE_MISSING" >> "$LOG"; exit 0
fi

age=$(( $(date +%s) - $(stat -c %Y "$STATE") ))

running=$("$DOCKBIN" inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)
rc=$?
if [ $rc -ne 0 ]; then
  echo "$ts ERR_CONTAINER_ABSENT $CONTAINER" >> "$LOG"; exit 0
fi

if [ "$age" -lt "$STALE_SEC" ]; then
  exit 0   # FRESH — ไม่ log ทุก 5 นาที กันไฟล์บวม (ตรวจ freshness ได้จาก cron exit 0)
fi

# restart storm guard
H="$(date -u '+%F %H')"
recent=$(grep -c "^$H.*HEALED" "$LOG" 2>/dev/null || true)
recent=${recent:-0}
if [ "$recent" -ge "$MAX_RESTARTS_PER_HOUR" ]; then
  echo "$ts SKIP_STORM age=${age}s restarts_last_hour=$recent" >> "$LOG"
  exit 0
fi

# เพิ่ง start? ให้เวลา boot
started=$("$DOCKBIN" inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null)
sup=$(date -d "$started" +%s 2>/dev/null || echo 0)
if [ "$sup" -gt 0 ] && [ $(( $(date +%s) - sup )) -lt 200 ]; then
  echo "$ts SKIP_BOOTING age=${age}s" >> "$LOG"; exit 0
fi

if [ "$running" = "true" ]; then
  if "$DOCKBIN" restart "$CONTAINER" >>"$LOG" 2>&1; then
    echo "$ts HEALED restart age=${age}s" >> "$LOG"
  else
    echo "$ts FAIL_restart age=${age}s" >> "$LOG"
  fi
else
  if "$DOCKBIN" start "$CONTAINER" >>"$LOG" 2>&1; then
    echo "$ts HEALED start age=${age}s" >> "$LOG"
  else
    echo "$ts FAIL_start age=${age}s" >> "$LOG"
  fi
fi
