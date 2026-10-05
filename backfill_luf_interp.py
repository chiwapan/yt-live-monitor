#!/usr/bin/env python3
"""เติมจุดครึ่งชั่วโมงของ lUfVGbAYtKE ที่ Playboard 10-min bucket ไม่มี
Interpolate เส้นตรง ระหว่าง anchor ค่าจริงสองข้าง — เฉพาะจุดที่ขาด ไม่ทับของเดิม
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_data.jsonl")
VID = "lUfVGbAYtKE"

# จุดที่จะเติม: (ts, viewers_interpolated)
FILL = {
    "2026-08-07 15:25:00": 11422,  # กลาง 15:20(11154)~15:30(11689)
    "2026-08-07 15:35:00": 12724,  # กลาง 15:30(11689)~15:40(13758)
    "2026-08-07 15:45:00": 13816,  # กลาง 15:40(13758)~15:50(13874)
    "2026-08-07 15:55:00": 13217,  # กลาง 15:50(13874)~16:00(12559)
    "2026-08-07 16:05:00": 11506,  # กลาง 16:00(12559)~16:10(10453)
}

rows = []
templates = {}
existing = set()
for line in open(PATH, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.strip():
        continue
    d = json.loads(line)
    rows.append((d["ts"], line))
    templates.setdefault(d["video_id"], d)
    existing.add((d["ts"], d["video_id"]))

added = 0
for ts, viewers in FILL.items():
    if (ts, VID) in existing:
        print(f"  ข้าม (มีอยู่แล้ว): {ts}")
        continue
    t = templates.get(VID, {})
    row = {
        "ts": ts,
        "video_id": VID,
        "title": t.get("title", ""),
        "viewers": viewers,
        "channel": t.get("channel", "โหนกระแส"),
        "url": t.get("url", ""),
        "actual_start": t.get("actual_start", ""),
    }
    rows.append((ts, json.dumps(row, ensure_ascii=False)))
    added += 1
    print(f"  + เติม {ts} = {viewers} (interpolated)")

rows.sort(key=lambda x: x[0])
with open(PATH, "w", encoding="utf-8") as f:
    for _, text in rows:
        f.write(text + "\n")
print(f"\nเติม {added} จุด")