#!/usr/bin/env python3
"""fix_channel_attribution.py
ล้าง mislabel channel ใน views_live.jsonl + views_month.jsonl:
สาเหตุ = collect_snapshot ใช้ seen global → วิดีโอเดียวถูก append ทุกช่อง
วิธีแก้: ดึง channelId จริงของทุก video จาก videos.list(snippet.channelId)
แล้วคืน channel_id/channel ใหม่อย่างถูกต้อง + ทิ้งแถวซ้ำ (vid, ts) ที่เหลือช่องเดียวจริง
"""
import os, json, sys, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "views_live.jsonl")
MONTH = os.path.join(HERE, "views_month.jsonl")
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# ชื่อช่องสั้นตามที่ dashboard ใช้ (จาก CHANNELS config)
CHANNEL_NAME = {}  # channel_id -> ชื่อไทย

def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

def fetch_real_channels(vid_to_scan):
    """vid list -> {vid: (channel_id, channel_title)} จาก videos.list"""
    res = {}
    ids = list(vid_to_scan)
    print(f"  ดึง channelID จริงของ {len(ids)} วิดีโอ...")
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
            "part": "snippet", "id": ",".join(batch), "key": API_KEY})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    print(f"  ⚠️ 403 quota — หน่วง 60s (try {attempt+1}/3)")
                    time.sleep(60)
                    continue
                print(f"  ⚠️ HTTP {e.code}: {e}")
                data = None
                break
            except Exception as e:
                print(f"  ⚠️ net {e} (try {attempt+1}/3)")
                time.sleep(5)
                data = None
                continue
        if not data:
            print("  ❌ ดึงไม่สำเร็จ หยุด")
            return res
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            res[it["id"]] = (sn.get("channelId", ""), sn.get("channelTitle", ""))
        time.sleep(0.3)
    return res

def main():
    if not API_KEY:
        print("❌ ไม่มี YOUTUBE_API_KEY")
        sys.exit(1)

    live = read_jsonl(LIVE)
    month = read_jsonl(MONTH)

    # 1) รวบรวมทุก video ต้องใช้ channel mapping
    all_vids = set()
    for r in live:
        if r.get("video_id"):
            all_vids.add(r["video_id"])
    for r in month:
        if r.get("video_id"):
            all_vids.add(r["video_id"])
    print(f"live rows={len(live)} | month rows={len(month)} | unique vids={len(all_vids)}")

    # 2) เอา channelID จริงจาก API (เฉพาะตัวที่จำเป็น)
    real = fetch_real_channels(all_vids)
    print(f"  ได้ channel จริง {len(real)}/{len(all_vids)}")

    # 3) ล้าง live: คืน channel จริง + ทิ้งแถวซ้ำ (vid,ts) เหลือแถวเดียว (เอาอันที่ channel trotz)
    known = {r["video_id"]: r for r in month if r.get("video_id")}  # fallback metadata
    fixed_live = {}
    dropped = 0
    for r in live:
        vid = r.get("video_id")
        ts = r.get("ts")
        if not vid or not ts:
            continue
        info = real.get(vid)
        if info and info[0]:
            cid, ch = info
            r["channel_id"] = cid
            r["channel"] = ch
        # dedupe (vid,ts): keep first (ยังไม่ใช้ค่านี้แทน view_count ตอนนี้)
        key = (vid, ts)
        if key in fixed_live:
            dropped += 1
            continue
        fixed_live[key] = r
    live_out = list(fixed_live.values())
    print(f"  live: {len(live)} → {len(live_out)} rows (ทิ้งซ้ำ {dropped})")

    # 4) ล้าง month: คืน channel จริง
    fixed_month = []
    for r in month:
        vid = r.get("video_id")
        info = real.get(vid)
        if info and info[0]:
            r["channel_id"], r["channel"] = info
        fixed_month.append(r)
    print(f"  month: {len(month)} → {len(fixed_month)} rows (channel แก้แล้ว)")

    # 5) เขียนกลับ
    with open(LIVE, "w", encoding="utf-8") as f:
        for r in live_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(MONTH, "w", encoding="utf-8") as f:
        for r in fixed_month:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("✅ เขียนกลับครบ")

if __name__ == "__main__":
    main()