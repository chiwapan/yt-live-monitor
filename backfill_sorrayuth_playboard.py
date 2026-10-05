#!/usr/bin/env python3
"""
backfill_sorrayuth_playboard.py — Backfill สรยุทธ กรรมกรข่าว concurrent viewers
ย้อนหลัง (default: 2026-07-04 .. 2026-08-02) ผ่าน Playboard chart ทีละวิดีโอ.

Pipeline:
  1. YouTube Data API search.list → ได้ video_id ของ live ย้อนหลัง (channelId สรยุทธ)
  2. เปิด playboard.co/en/video/<vid> → save HTML (ถ้าไม่โดน rate-limit)
  3. รัน backfill_playboard.py ingest ลง live_data.jsonl

ออกแบบให้รันบน HOST (ไม่ใช่ sandbox) — สมมติ host IP ไม่โดน Playboard บล็อก
ถ้าโดนบล็อก → พิมพ์ข้อความชัดเจนแล้วหยุด (ไม่ silently fail)

Usage (บน host):
  YT_LIVE_PRODUCTION=1 python3 backfill_sorrayuth_playboard.py
  YT_LIVE_PRODUCTION=1 python3 backfill_sorrayuth_playboard.py --start 2026-07-04 --end 2026-08-02
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import subprocess
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "live_data.jsonl")
PB_DIR = os.path.join(BASE, "playboard_cache")
os.makedirs(PB_DIR, exist_ok=True)

CHANNEL_ID = "UC4kPIfdCZrPqoQ94m6-eFsg"
CHANNEL_NAME = "สรยุทธ กรรมกรข่าว"
YEAR = "2026"

# โหลด API key จาก .env (เหมือน backfill_playboard.py)
def load_key():
    env = os.path.join(BASE, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("YOUTUBE_API_KEY="):
                return line.strip().split("=", 1)[1]
    return os.environ.get("YOUTUBE_API_KEY", "")

API_KEY = load_key() or os.environ.get("YOUTUBE_API_KEY", "")

def api_search(channel_id, published_after, published_before, page_token=""):
    """YouTube search.list — หา live วิดีโอในช่วงเวลา"""
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "eventType": "completed",
        "type": "video",
        "order": "date",
        "maxResults": 50,
        "publishedAfter": published_after,
        "publishedBefore": published_before,
        "key": API_KEY,
    }
    if page_token:
        params["pageToken"] = page_token
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  ! search API HTTP {e.code}: {e.read().decode()[:200]}")
        return {}
    except Exception as e:
        print(f"  ! search API error: {e}")
        return {}

def fetch_playboard(vid):
    """ดึง HTML หน้า playboard.co/en/video/<vid> → คืน path ถ้าสำเร็จ"""
    url = f"https://playboard.co/en/video/{vid}"
    path = os.path.join(PB_DIR, f"{vid}.html")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path  # cache แล้ว
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode("utf-8", "replace")
        if "Too many requests" in html or "Page not found" in html:
            print(f"  ! Playboard บล็อก/ไม่มีหน้าสำหรับ {vid}")
            return None
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path
    except urllib.error.HTTPError as e:
        print(f"  ! Playboard HTTP {e.code} for {vid}")
        return None
    except Exception as e:
        print(f"  ! Playboard error {vid}: {e}")
        return None

def main():
    if not API_KEY:
        print("❌ ไม่มี YOUTUBE_API_KEY — หยุด")
        sys.exit(1)
    if os.environ.get("YT_LIVE_PRODUCTION") != "1":
        print("🚧 SAFETY: ต้องรันด้วย YT_LIVE_PRODUCTION=1 (ป้องกันใช้ key จริงผิดที่)")
        sys.exit(1)

    # parse args
    start_s = "2026-07-04"
    end_s = "2026-08-02"
    if "--start" in sys.argv:
        start_s = sys.argv[sys.argv.index("--start") + 1]
    if "--end" in sys.argv:
        end_s = sys.argv[sys.argv.index("--end") + 1]
    start_dt = datetime.strptime(start_s, "%Y-%m-%d")
    end_dt = datetime.strptime(end_s, "%Y-%m-%d") + timedelta(days=1)

    print(f"🔍 Backfill สรยุทธ {CHANNEL_NAME}: {start_s} → {end_s}")

    # 1) หา video_id ย้อนหลัง
    vids = []
    page = ""
    after = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    before = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    while True:
        d = api_search(CHANNEL_ID, after, before, page)
        for it in d.get("items", []):
            vid = it["id"].get("videoId")
            pub = it["snippet"].get("publishedAt", "")
            title = it["snippet"].get("title", "")
            if vid:
                vids.append((vid, pub, title))
        nxt = d.get("nextPageToken")
        if not nxt:
            break
        page = nxt
        time.sleep(0.5)

    print(f"  ได้ video_id: {len(vids)} วิดีโอ")
    if not vids:
        print("❌ ไม่มีวิดีโอในช่วงนี้ — จบ")
        sys.exit(0)

    # 2) ดึง Playboard ทีละอัน
    ok = 0
    for vid, pub, title in vids:
        print(f"  ▶ {vid} | {pub[:10]} | {title[:40]}")
        p = fetch_playboard(vid)
        if p:
            ok += 1
        time.sleep(1.5)  # เบาๆ กัน rate-limit

    print(f"\n✅ ดึง Playboard สำเร็จ: {ok}/{len(vids)} วิดีโอ")
    if ok == 0:
        print("❌ Playboard บล็อกทั้งหมด — หยุด (ลองรันบน host IP อื่น หรือใช้ proxy)")
        sys.exit(1)

    # 3) รัน backfill_playboard.py ingest (channel override = สรยุทธ)
    print("\n🔄 รัน backfill_playboard.py ingest...")
    cmd = [
        sys.executable, os.path.join(BASE, "backfill_playboard.py"),
        "--scan-dir", PB_DIR,
        "--channel", CHANNEL_NAME,
        "--no-filter",
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        print(f"❌ backfill_playboard.py 失败: {e}")
        sys.exit(1)

    print("\n🎉 เสร็จ — ตรวจสอบด้วย: curl https://live.chiwapan.online/api/slot-compare")

if __name__ == "__main__":
    main()
