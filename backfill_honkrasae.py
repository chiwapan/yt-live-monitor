#!/usr/bin/env python3
"""Backfill โหนกระแส 2026-08-07 จาก Playboard — insert จุดขาด + ลบ ghost
เขียนทับใน-place (ไฟล์เป็น bind mount; ห้าม os.replace)
ก่อนรัน: cp live_data.jsonl <backup>
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "live_data.jsonl")

# ── จุดที่จะเพิ่ม (ts, video_id, viewers) ──
ADD = [
    # HN-WTZiCuSA (โหนกระแส) — 12:40 จุดแรกขาด
    ("2026-08-07 12:40:00", "HN-WTZiCuSA", 122696),
    # lUfVGbAYtKE (ตามต่อ..เสียงปืน) — ช่องโหว่จาก outage
    ("2026-08-07 14:40:00", "lUfVGbAYtKE", 2994),
    ("2026-08-07 15:40:00", "lUfVGbAYtKE", 13758),
    ("2026-08-07 15:50:00", "lUfVGbAYtKE", 13874),
    ("2026-08-07 16:00:00", "lUfVGbAYtKE", 12559),
    # 6mN2zVhPPtg (เหตุกราดยิงเทพรินทร์) — 11:40 จุดแรกขาด
    ("2026-08-07 11:40:00", "6mN2zVhPPtg", 4991),
]
# ── แถวปลอม ghost ที่ต้องลบ (HN จบจริง 14:20 แต่ 18:15 มีแถว 336339 ค้าง) ──
REMOVE_TS = "2026-08-07 18:15:00"
REMOVE_VID = "HN-WTZiCuSA"

# ดึง template (title/url/actual_start/channel) จากแถวที่มีอยู่แล้วของ video นั้น
templates = {}
for line in open(PATH, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    templates.setdefault(d["video_id"], d)

rows = []
ghost_removed = added = 0
for line in open(PATH, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.strip():
        continue
    d = json.loads(line)
    if d.get("video_id") == REMOVE_VID and d.get("ts") == REMOVE_TS:
        ghost_removed += 1
        continue  # เอา ghost ออก
    rows.append((d["ts"], line))

# เติมจุดที่ขาด (ถ้ายังไม่มี)
existing = set()
for _, line in rows:
    d = json.loads(line)
    existing.add((d["ts"], d["video_id"]))

for ts, vid, viewers in ADD:
    if (ts, vid) in existing:
        print(f"  ข้าม (มีอยู่แล้ว): {ts} {vid}")
        continue
    t = templates.get(vid, {})
    newrow = {
        "ts": ts,
        "video_id": vid,
        "title": t.get("title", ""),
        "viewers": viewers,
        "channel": t.get("channel", "โหนกระแส"),
        "url": t.get("url", f"https://www.youtube.com/watch?v={vid}"),
        "actual_start": t.get("actual_start", ""),
    }
    rows.append((ts, json.dumps(newrow, ensure_ascii=False)))
    added += 1
    print(f"  + เพิ่ม {ts} {vid} = {viewers}")

# จัดเรียงตาม ts (stable — อันเดิมอยู่ก่อน) แล้วเขียนทับใน-place
rows.sort(key=lambda x: x[0])
with open(PATH, "w", encoding="utf-8") as f:
    for _, text in rows:
        f.write(text + "\n")

print(f"\nเพิ่ม {added} จุด, ลบ ghost {ghost_removed} แถว")