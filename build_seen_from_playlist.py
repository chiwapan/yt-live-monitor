#!/usr/bin/env python3
# build_seen_from_playlist.py
# สร้าง snapshot_seen.json ครอบคลุมคลิปทั้งเดือนของทุกช่อง
# โดยดึง uploads playlist ย้อนหลังหลายหน้า (ไม่ใช่แค่ 15) → ใส่ลง seen file
# ใช้ครั้งเดียวก่อนรัน collector รอบใหญ่ เพื่อแก้บั๊ก "วิวค้าง/ไม่ตรงยูทูบ"
# หมายเหตุ: เปลือง quota ~1 unit/หน้า/ช่อง (10 หน้า x 35 ช่อง = 350 units) — อยู่ใน quota 10k/วัน
import os, json, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("YOUTUBE_API_KEY", "")
if not KEY:
    # โหลดจาก .env ถ้าไม่ได้ export มา
    try:
        with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("YOUTUBE_API_KEY="):
                    KEY = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass

# load CHANNELS from collector config (read source, no exec)
import re as _re
_coll_src = open(os.path.join(HERE, "yt-views-collector.py"), encoding="utf-8").read()
_m = _re.search(r'CHANNELS\s*=\s*\[(.*?)\]', _coll_src, _re.S)
CHANNELS = []
if _m:
    for mid in _re.findall(r"\{[^}]*'id':\s*'(UC[A-Za-z0-9_-]{22})'[^}]*'name':\s*'([^']*)'[^}]*\}", _m.group(1)):
        CHANNELS.append({"id": mid[0], "name": mid[1]})

SEEN_PATH = os.environ.get("SNAPSHOT_SEEN_JSONL", os.path.join(HERE, "snapshot_seen.json"))
PAGES = int(os.environ.get("SEEN_PAGES", "10"))  # หน้าละ 50 = 500 คลิป/ช่อง

def get_uploads_pid(channel_id):
    url = "https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode({
        "part": "contentDetails", "id": channel_id, "key": KEY})
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read())
    return d["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

def fetch_playlist_vids(pid, pages):
    out = []
    page = None
    for _ in range(pages):
        params = {"part": "contentDetails", "playlistId": pid, "maxResults": 50, "key": KEY}
        if page: params["pageToken"] = page
        url = "https://www.googleapis.com/youtube/v3/playlistItems?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print("  ⚠️ 403 quota — หน่วง 60s"); time.sleep(60); continue
            else: raise
        for it in d.get("items", []):
            out.append(it["contentDetails"]["videoId"])
        page = d.get("nextPageToken")
        if not page: break
        time.sleep(0.3)
    return out

def main():
    if not KEY:
        print("❌ ต้องตั้ง YOUTUBE_API_KEY"); return
    # load existing seen (ถ้ามี)
    seen = set()
    if os.path.exists(SEEN_PATH):
        try: seen = set(json.load(open(SEEN_PATH, encoding="utf-8")))
        except: seen = set()
    print(f"📂 seen ก่อน: {len(seen)} วิดีโอ")
    for ch in CHANNELS:
        try:
            pid = get_uploads_pid(ch["id"])
            vids = fetch_playlist_vids(pid, PAGES)
            before = len(seen)
            seen.update(vids)
            print(f"  ✅ {ch['name']}: +{len(seen)-before} (ดึง {len(vids)} จาก playlist)")
        except Exception as e:
            print(f"  ⚠️ {ch['name']}: {e}")
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False)
    print(f"💾 บันทึก {len(seen)} วิดีโอ → {SEEN_PATH}")

if __name__ == "__main__":
    main()
