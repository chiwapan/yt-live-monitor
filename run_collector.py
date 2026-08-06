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

INTERVAL = 300  # 5 min

def tick():
    print(f"[{datetime.now(ICT).strftime('%Y-%m-%d %H:%M:%S')} ICT] collector tick", flush=True)
    try:
        # ไฟล์ชื่อ yt-live-daily.py (hyphen) → import เป็น module ปกติไม่ได้ ต้องโหลดผ่าน path
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("yt_live_daily", os.path.join(here, "yt-live-daily.py"))
        ym = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ym)
        ym.main()
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc()

def main():
    print("yt-live-monitor collector started (every 5 min)", flush=True)
    while True:
        try:
            tick()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()