#!/usr/bin/env python3
"""Run YT live collector every 5 min inside the container (no cron needed).
Mimics the Hermes cron job 974d21a00439 (every 5 min) but self-contained.
"""
import os, sys, time, subprocess, traceback
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# google_api helper lives in the repo for the container
if not os.environ.get("GAPI_SCRIPT"):
    os.environ["GAPI_SCRIPT"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_api.py")

INTERVAL = int(os.environ.get("COLLECTOR_INTERVAL", "60"))  # hot tick ทุก 1 นาที (was 300)
COLD_EVERY = int(os.environ.get("COLD_EVERY", "5"))        # main() เต็มรอบ ทุก N นาที

def tick():
    print(f"[{datetime.now(ICT).strftime('%Y-%m-%d %H:%M:%S')} ICT] collector tick", flush=True)
    # ⚠️ SAFETY: บอก yt-live-daily.py ว่าตอนนี้คือ "production collector" จริง
    # ตัว yt-live-daily.py ใช้ค่านี้ตัดสินว่าจะยอมใช้ key จริงใน .env หรือไม่
    # ถ้ารันจาก host (ไม่ได้ผ่าน container entrypoint นี้) → มันจะไม่แตะ key จริง/env
    # กันกรณี dev/test ไปเผา quota ของโปรดักชัน (อุบัติเหตุ 2026-08-07)
    os.environ["YT_LIVE_PRODUCTION"] = "1"
    try:
        # ไฟล์ชื่อ yt-live-daily.py (hyphen) → import เป็น module ปกติไม่ได้ ต้องโหลดผ่าน path
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("yt_live_daily", os.path.join(here, "yt-live-daily.py"))
        ym = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ym)
        return ym
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc()
    return None

def main():
    print(f"yt-live-monitor collector started — hot_tick every {INTERVAL}s, "
          f"full cold round every {COLD_EVERY} min (two-tier)", flush=True)
    ym = tick()
    if ym is None:
        return
    minute_i = 0
    while True:
        try:
            time.sleep(INTERVAL)
            minute_i += 1
            if minute_i % COLD_EVERY == 0:
                ym.main()          # cold round: RSS + discover + ทั้งหมด (5 นาที)
            else:
                ym.hot_tick()      # hot pass: เฉพาะ stream ≥ HOT_THRESHOLD (1 นาที)
        except Exception:
            traceback.print_exc()

if __name__ == "__main__":
    main()