# YT Live Monitor — Thairath

Poll YouTube live concurrent viewers every 5 minutes → Google Sheets + local JSONL,
and serve a real-time dashboard at `/live-monitor`.

**Standalone since 2026-08-03** — แยกออกจาก Hermes dashboard แล้ว, deploy ไป Amazon ได้ทั้งก้อน

## Components (อัปเดต 2026-08-09 — ไม่มี docker แล้ว รันเป็น native process + Hermes cron)

| ส่วน | ไฟล์ | หน้าที่ | เรียกโดย |
|------|------|--------|---------|
| Poller (live concurrent) | `yt-live-daily.py` | ดึง concurrent viewers ทุก 5 นาที → Google Sheets + `live_data.jsonl` | Hermes cron `yt-live-daily.sh` (subprocess สั้นๆ ไม่ใช่ process เดินพื้นหลัง) |
| Poller (views snapshot) | `yt-views-collector.py` MODE=snapshot | ดึง view_count สด → `views_live.jsonl` | Hermes cron `run_views_snapshot.sh` (ทุกชม.) |
| Watchdog | `yt-live-watchdog.py` | เตือนเมื่อไฟล์ไม่ถูกเขียน | Hermes cron ทุก 2 นาที |
| **Frontend** (หน้า `/live-monitor`) | **Streamlit `thairath-reports/scripts/dashboard.py` (port 8501)** | อ่าน jsonl โชว์ Σ concurrent | process ถาวร (ไม่ใช่ `web/app.py`) |
| ทางเข้าโดเมน | cloudflared tunnel (pid 164483 ชี้ localhost:80 → CF ingress `/live-monitor`→8501) | `live.chiwapan.online` | process ถาวร |

⚠️ `web/app.py` (port 8889) คือเศษเก่า ไม่ได้ถูกเสิร์ฟแล้ว (8889/live-monitor ได้ 404) — ห้ามนำมาแก้ไขสับสน

## Run frontend locally (Streamlit 8501)

```bash
cd /opt/data/home/thairath-reports
/opt/hermes/.venv/bin/streamlit run scripts/dashboard.py --server.port 8501 --server.headless true --server.address 127.0.0.1
# หน้า /live-monitor อ่าน live_data.jsonl + views_live.jsonl
```

## Env vars

**Dashboard:** สืบทอดจาก `thairath-reports` (ไม่ได้ใช้ PORT/LIVE_JSONL ของ web/app.py)

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
