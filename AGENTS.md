# AGENTS.md — YT Live Monitor / Views Monitor

โปรเจกต์นี้รันเป็น **Docker container บน host** และมีบทเรียน "วนหลายชั่วโมง" ที่ต้องไม่ซ้ำ อ่านทั้งหมดก่อนแก้โค้ด

## 🚨 กติกาเหล็ก (อ่านก่อนแก้โค้ด — จากบทเรียน 2026-08-10)

1. **ALWAYS rebuild container → แล้ว verify ผ่าน URL จริง** หลังแก้โค้ดทุกครั้งเท่านั้น:
   ```bash
   cd /docker/hermes-agent-r6gh/data/projects/yt-live-monitor
   docker compose -f docker-compose.hostinger.yml build web
   docker compose -f docker-compose.hostinger.yml up -d web
   ```
   แก้ไฟล์ใน `/opt/data/projects/yt-live-monitor/` อย่างเดียว **ไม่เห็นผล** จนกว่า user จะ rebuild container

2. **verify ผ่าน public URL เท่านั้น** — `curl https://live.chiwapan.online/api/...`
   อย่า verify แค่ `localhost:8899` — ถ้าไม่ rebuild, public = โค้ดเก่า, localhost ≠ public

3. **อย่าไล่ process ผี / อย่าเปลี่ยน port** — มี `service-watchdog.sh` restart ตัวเก่าแทรกเสมอ
   อย่าเดาว่า "ใครตอบ" — curl public จริงเสมอ

4. **ชื่อรายการ (แก้ 2026-08-10):**
   - slot-compare คืน `name` (ชื่อช่อง คงที่จาก `SLOTS` config) + `live_title` (title วิดีโอล่าสุด clean แล้ว)
   - หน้า: **แนวโน้ม Peak / ตาราง** ใช้ `name` (ชื่อช่อง), **Concurrent รายวัน** ใช้ `live_title` (title จริง)
   - หัวเขียวรวมได้ 1 รายการ เพราะ `kw: ["ข่าวเช้าหัวเขียว", "ห้องข่าวหัวเขียว"]` (2 keywords 1 program)

5. **อัปโหลด GitHub เสมอ** หลังแก้: `chiwapan/yt-live-monitor` branch `master` (source อยู่ `/opt/data/projects/yt-live-monitor/web/`)

## สถาปัตยกรรม
- Live monitor: container `yt-live-monitor-web` (Flask `web/app.py`) port 8899 ผ่าน cloudflared named tunnel → `live.chiwapan.online`
- Views collector: `yt-views-collector.py` MODE=snapshot → `views_live.jsonl` (cron)
- Bind mount: sandbox `/opt/data` ↔ host `/docker/hermes-agent-r6gh/data`
- Frontend ไม่ hardcode ชื่อ — อ่านจาก `/api/slot-compare` และ `/api/live-data` ทั้งหมด

## ไฟล์สำคัญ
- `web/app.py` — backend API (SLOTS config, clean_video_title, slot-compare, live-data)
- `web/live_monitor.html` — หน้า dashboard (Chart.js)
- `live_data.jsonl` — ข้อมูล concurrent viewers หลัก
- `docker-compose.hostinger.yml` — deployment บน host

## อย่า
- อย่าแก้ `web/app.py` แล้วลืม rebuild+verify public
- อย่าเอา process/port มาเดา — มี watchdog แทรกแซง
- อย่าลบ `clean_video_title()` — ใช้กับ title วิดีโอเพื่อ strip prefix/suffix
- อย่าเปลี่ยนชื่อ `name` เป็น title จริง (name ต้องเป็นชื่อช่องคงที่ — dayCompare ใช้ live_title แทน)

ดู skill `yt-live-monitor-views` สำหรับรายละเอียด + history of bugs ด้วยเสมอ

## ⛔ บทเรียน 2026-09-13 (สำคัญ — เคยทำให้ข้อมูล live หยุดเขียนจริง)
- `live_data.jsonl` เป็น **Docker single-file bind mount** → **ห้ามใช้ tmp + os.replace()** เด็ดขาด
  (container จะยังชี้ inode เก่า → collector เขียนลงไฟล์ที่ไม่มีชื่อบน host = ข้อมูลหายจากมุม host, API ค้าง)
- เกิดจริง: dedupe script ใช้ os.replace 13:34 ICT → collector เขียนต่อไม่ถึง host จนถึง 15:50 (137 นาที) · watchdog alert ถูกต้อง
- ทางแก้: เขียนทับ **in-place** (open(path,"w")) เท่านั้น · ไฟล์ระดับ Docker bind-mount ทุกตัว (STATE_FILE ก็เตือนไว้แล้วที่ yt-live-daily.py)
- ตรวจหลังแก้: `ls -la live_data.jsonl` mtime ต้องขยับทุก ~5 นาที
