# YT Live Monitor — Thairath

Poll YouTube live concurrent viewers every 5 minutes → Google Sheets + local JSONL,
and serve a real-time dashboard at `/live-monitor`.

**Standalone since 2026-08-03** — แยกออกจาก Hermes dashboard แล้ว, deploy ไป Amazon ได้ทั้งก้อน

## Components

| ส่วน | ไฟล์ | หน้าที่ |
|------|------|--------|
| Poller | `yt-live-daily.py` | ดึง concurrent viewers ทุก 5 นาที → Google Sheets + `live_data.jsonl` |
| Dashboard | `web/app.py` | Flask app: `/live-monitor`, `/api/live-data`, `/api/ping` |
| Backfill | `backfill_*.py` | เติมข้อมูลย้อนหลังจาก Playboard / Studio CSV |

## Run dashboard locally

```bash
pip install -r requirements.txt
cd web && python3 app.py
# PORT (default 8899), LIVE_JSONL (default ../live_data.jsonl)
```

## Docker

```bash
docker build -t yt-live-monitor .
docker run -d -p 8899:8899 -v /path/to/data:/data yt-live-monitor
# mount live_data.jsonl ที่ /data/live_data.jsonl
```

## Env vars

**Dashboard:** `PORT`, `LIVE_JSONL`

**Poller:** `YOUTUBE_API_KEY` (required), `YT_SHEET_ID` (required),
`GAPI_SCRIPT` (path to google_api.py helper — default points to Hermes skill dir)

## Deploy to Amazon (แนวทาง)

Dashboard (เบาสุด):
1. **Lightsail $3.5/mo** — `docker compose up -d`, ใช้ domain เดิมหรือใหม่ผ่าน Cloudflare DNS
2. **App Runner** — ต่อ GitHub repo auto-deploy, scale-to-zero ได้, มี health check ในตัว

Poller (ถ้าจะย้ายด้วย):
- ต้อง copy `google_api.py` helper เข้า repo ก่อน (ตอนนี้ชี้ไปที่ Hermes skill dir)
- หรือตัด Sheets ออก ให้เขียนแค่ JSONL → dashboard-only ก็ได้

Data flow บนเครื่อง Hermes ปัจจุบัน:
- cron `*/5` รัน `yt-live-daily.sh` → append `live_data.jsonl`
- `web/app.py` อ่าน JSONL → render ที่ `live.chiwapan.online/live-monitor`

## Channels monitored

ดู `CHANNELS` ใน `yt-live-daily.py` (ThaiRath News/Variety, ช่อง8, ฯลฯ)

## How it works (poller)

1. **RSS discovery** (0 quota) — fetches each channel's RSS feed for recent uploads
2. **videos.list** (1 unit/call) — batch checks up to 50 videos for `liveStreamingDetails.concurrentViewers`
3. **Google Sheets** — appends to `Raw` tab, writes daily summaries to `Daily_Summary`
4. **State file** (`/tmp/yt-live-daily-state.json`) — tracks peak viewers across polls
5. **no_agent=True cron** — runs as a shell script, zero LLM tokens
