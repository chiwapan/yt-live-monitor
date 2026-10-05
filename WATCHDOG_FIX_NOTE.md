# Watchdog False-Positive Fix (note — 2026-08-08)

## อาการ
Cron `a1520922b464` (YT live watchdog) แจ้งเตือน "ไฟล์ไม่ถูกเขียน N นาที" ทั้งที่ความจริงคือ **ไม่มี live** (state `live count: 0`)

## Root cause
สคริปต์ watchdog เช็คแค่ mtime ของ `live_data.jsonl` ไม่ได้เปิด `yt-live-daily-state.json` ดู `live count`
→ แจ้งเตือนผิดตอนช่วงไม่มี live (ไฟล์หยุดเขียนเป็นปกติ)

## ตรวจสอบจริง (17:04 ICT)
- `live_data.jsonl` mtime 16:56 (ค้างจากรอบสุดท้าย collector รัน)
- state `live count: 0` → ไม่มี live active
- ไม่มี collector process รัน (ถูก kill ไป)
- เว็บโชว์ "TOP NEWS LIVE 88 ผู้ชม" = ข้อมูลค้างจากไฟล์เก่า ไม่ใช่ realtime

## Fix ที่ต้องทำ (รอ rootan เสร็จค่อยมาแก้)
แก้ logic watchdog:
```
if live_count == 0:
    ไม่เตือน (ไม่มี live = ไฟล์หยุดเขียนปกติ)
elif live_count > 0 and file_stale > threshold:
    เตือน (collector ตายตอนมี live)
```
อย่าลบ cron — แค่แก้เงื่อนไขเตือน
