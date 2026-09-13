#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ทดสอบ append_local_jsonl หลังใส่ flock + key รวม channel
จำลอง: รัน 1 เขียน 2 สตรีม → รัน 2 ที่ ts เดียวกัน (ซ้ำ) ต้องถูก skip
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime

SRC = "/opt/data/projects/yt-live-monitor/yt-live-daily.py"
tmp = tempfile.mkdtemp()
jsonl = os.path.join(tmp, "live_data.jsonl")

spec = importlib.util.spec_from_file_location("yld", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["yld"] = m
spec.loader.exec_module(m)
m.JSONL_FILE = jsonl

now = datetime(2026, 9, 13, 13, 30, 0)
s1 = {"video_id": "AAA", "title": "live A", "concurrent_viewers": 100, "channel_name": "ch1", "url": "u1"}
s2 = {"video_id": "BBB", "title": "live B", "concurrent_viewers": 200, "channel_name": "ch2", "url": "u2"}

m.append_local_jsonl([s1, s2], now)          # เขียน 2 แถว
m.append_local_jsonl([s1, s2], now)          # ts เดียวกัน -> ต้อง skip ทั้งคู่
s3 = {"video_id": "AAA", "title": "live A", "concurrent_viewers": 150, "channel_name": "ch3", "url": "u3"}
m.append_local_jsonl([s3], now)              # ช่องอื่น (channel ต่าง) -> ต้องเขียนได้

rows = [json.loads(l) for l in open(jsonl) if l.strip()]
keys = [(r["video_id"], r["channel"]) for r in rows]
print("แถว:", len(rows), keys)
ok = (len(rows) == 3 and len(set(keys)) == 3)
print("ผลทดสอบ:", "PASS" if ok else "FAIL", "(คาด 3 แถวไม่ซ้ำ)")

# เขียนต่าง ts -> ต้องเขียนใหม่ได้
m.append_local_jsonl([s1], datetime(2026, 9, 13, 13, 35, 0))
rows2 = [json.loads(l) for l in open(jsonl) if l.strip()]
print("หลัง ts ใหม่:", len(rows2), "แถว ->", "PASS" if len(rows2) == 4 else "FAIL")
sys.exit(0 if (ok and len(rows2) == 4) else 1)
