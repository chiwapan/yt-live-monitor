#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedupe live_data.jsonl — เก็บแถวล่าสุดต่อ (ts, video_id, channel)
สาเหตุซ้ำ: collector เขียนด้วย append แบบ scan-then-write ไม่มี lock → 2 รันชนกันที่ slot เดียวกัน
รอบนี้: ล้างข้อมูลเก่า (atomic replace) · ส่วนต้นทางต้องแก้ที่ yt-live-daily.py + rebuild container
"""
import json, os, shutil, sys, time

PATH = "/opt/data/projects/yt-live-monitor/live_data.jsonl"
BAK = "/opt/data/projects/yt-live-monitor/backup_dedupe_20260913/live_data.jsonl.bak"

def main(apply=False):
    if os.path.exists(BAK):
        print("มี backup อยู่แล้ว:", BAK)
    else:
        os.makedirs(os.path.dirname(BAK), exist_ok=True)
        shutil.copy2(PATH, BAK)
        print("backup ->", BAK, os.path.getsize(BAK) // 1024, "KB")
    keep, order, dup, bad = {}, [], 0, 0
    with open(PATH, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
            except Exception:
                bad += 1
                continue
            k = (d.get("ts"), d.get("video_id"), d.get("channel"))
            if k in keep:
                dup += 1
            else:
                order.append(k)
            keep[k] = s           # ตัวหลังทับตัวหน้า = เก็บค่าล่าสุด
    print(f"แถวทั้งหมด(อ่านได้) {len(order)+dup:,} | ซ้ำ {dup:,} | เสียหาย {bad} | เหลือ {len(order):,}")
    if not apply:
        print("(dry-run — ใส่ --apply เพื่อเขียนจริง)")
        return
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for k in order:
            f.write(keep[k] + "\n")
    os.replace(tmp, PATH)
    print("เขียนทับแล้ว:", os.path.getsize(PATH) // 1024, "KB | mtime", time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(PATH))))

if __name__ == "__main__":
    main("--apply" in sys.argv)
