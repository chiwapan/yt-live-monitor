#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedupe live_data.jsonl — เก็บแถวล่าสุดต่อ (ts, video_id, channel)

สาเหตุซ้ำ: collector เขียน append แบบ scan-then-write (ก่อน 13/9/69 ไม่มี lock)
→ 2 รันชนกันที่ slot เดียวกัน · แก้ต้นทางแล้วใน yt-live-daily.py (flock) แต่ต้อง
  rebuild container ถึงจะมีผล — ตัวนี้ใช้เป็น cron กันซ้ำระหว่างรอ rebuild

- silent-when-OK: ไม่มีแถวซ้ำ = ไม่พิมพ์ และ **ไม่เขียนไฟล์** (กัน race กับ collector)
- ใช้ lock เดียวกับ collector (live_data.jsonl.lock) → หลัง rebuild จะไม่ชนกันเลย
"""
import fcntl
import json
import os
import shutil
import sys
import time

PATH = "/opt/data/projects/yt-live-monitor/live_data.jsonl"
LOCK = PATH + ".lock"
BAK = "/opt/data/projects/yt-live-monitor/backup_dedupe_20260913/live_data.jsonl.bak"


def main(apply=False, quiet=True):
    lock_fh = open(LOCK, "a+")
    fcntl.flock(lock_fh, fcntl.LOCK_EX)
    try:
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

        if dup == 0 and bad == 0:
            return 0                  # เงียบ + ไม่แตะไฟล์

        if apply and dup:
            if not os.path.exists(BAK):
                os.makedirs(os.path.dirname(BAK), exist_ok=True)
                shutil.copy2(PATH, BAK)
            # ⛔ ห้ามใช้ tmp + os.replace เด็ดขาด: PATH เป็น Docker single-file bind mount
            #    (live_data.jsonl:/data/live_data.jsonl) — replace แล้ว container ยังชี้ inode เก่า
            #    → collector เขียนลงไฟล์ที่ไม่มีชื่อ (ข้อมูลหายจากมุม host) เกิดจริง 13/9/69 13:34
            #    (yt-live-daily.py เองก็เตือนเรื่องนี้ที่ STATE_FILE) → เขียนทับ in-place เท่านั้น
            with open(PATH, "w", encoding="utf-8") as f:
                for k in order:
                    f.write(keep[k] + "\n")

        if apply:
            print(f"🧹 dedupe live_data: ตัด {dup:,} แถวซ้ำ (เหลือ {len(order):,}) · JSON เสียหาย {bad}")
        else:
            print(f"(dry-run) พบ {dup:,} แถวซ้ำ · เสียหาย {bad} · เหลือ {len(order):,}")
        return 0
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))