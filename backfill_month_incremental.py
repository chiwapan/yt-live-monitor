#!/usr/bin/env python3
# backfill_month_incremental.py
# เติมคลิปใหม่ (ที่มีใน views_live.jsonl แต่ยังไม่มีใน views_month.jsonl) เข้า views_month.jsonl
# ดึง publishedAt + viewCount + likeCount + duration จริงจาก YouTube Data API v3 (videos.list)
# แล้ว merge ลง views_month.jsonl (เขียนทับเฉพาะ video_id ที่เพิ่มเข้ามา — ไม่แตะของเก่า)
import os, json, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "views_live.jsonl")
MONTH = os.path.join(HERE, "views_month.jsonl")
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

def read_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
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

def load_month_map(path):
    m = {}
    for r in read_jsonl(path):
        vid = r.get("video_id")
        if vid:
            m[vid] = r
    return m

def fetch_video_meta(vids):
    """คืน dict video_id -> (publishedAt, viewCount, likeCount, is_short) จาก videos.list"""
    if not vids:
        return {}
    res = {}
    # แบ่งเป็นชุดละ 50
    for i in range(0, len(vids), 50):
        batch = vids[i:i+50]
        url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "key": API_KEY,
        })
        data = None
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
                else:
                    print(f"  ⚠️ HTTP {e.code}: {e}")
                    break
            except Exception as e:
                print(f"  ⚠️ network {e} (try {attempt+1}/3)")
                time.sleep(5)
                continue
        if not data:
            print("  ❌ ดึง videos.list ไม่สำเร็จหลัง retry")
            return res
        for it in data.get("items", []):
            vid = it.get("id")
            sn = it.get("snippet", {})
            st = it.get("statistics", {})
            cd = it.get("contentDetails", {})
            dur = cd.get("duration", "")
            is_short = dur.startswith("PT") and "M" not in dur.split("T")[1] and dur.endswith("S") and dur != "PT0S"
            res[vid] = {
                "published_at": sn.get("publishedAt", ""),
                "view_count": int(st.get("viewCount", 0)),
                "like_count": int(st.get("likeCount", 0)),
                "is_short_est": bool(is_short),
            }
        time.sleep(0.5)  # หน่วงกัน rate-limit
    return res

def main():
    if not API_KEY:
        print("❌ ไม่พบ YOUTUBE_API_KEY — export ก่อนรัน")
        sys.exit(1)

    live = read_jsonl(LIVE)
    month_map = load_month_map(MONTH)
    print(f"📂 views_live.jsonl: {len(live)} แถว | views_month.jsonl: {len(month_map)} วิดีโอ")

    # หา video_id ใหม่ (มีใน live แต่ไม่มีใน month)
    new_ids = []
    seen = set()
    for r in live:
        vid = r.get("video_id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        if vid not in month_map:
            new_ids.append(vid)

    print(f"🔎 วิดีโอใหม่ที่ยังไม่มีใน views_month.jsonl: {len(new_ids)} ตัว")
    if not new_ids:
        print("✅ ไม่มีอะไรต้องเติม — จบ")
        return

    meta = fetch_video_meta(new_ids)
    added = 0
    # หาชื่อช่อง/title จาก live (แถวล่าสุด) เป็น fallback
    live_meta = {}
    for r in live:
        vid = r.get("video_id")
        if vid and vid not in live_meta:
            live_meta[vid] = r

    out_rows = list(month_map.values())
    for vid in new_ids:
        m = meta.get(vid)
        if not m or not m.get("published_at"):
            # ข้ามถ้าดึง publishedAt ไม่ได้ (อาจคลิปถูกลบ/rivate)
            continue
        lm = live_meta.get(vid, {})
        out_rows.append({
            "channel_id": lm.get("channel_id", ""),
            "channel": lm.get("channel", ""),
            "video_id": vid,
            "title": lm.get("title", ""),
            "view_count": m["view_count"],
            "like_count": m["like_count"],
            "is_short_est": m["is_short_est"],
            "published_at": m["published_at"],
            "since": datetime.now(ICT).strftime("%Y-%m-%d"),
        })
        added += 1

    if added == 0:
        print("⚠️ ดึง metadata ไม่ได้เลย (คลิปอาจหาย/ปิด) — ไม่เขียนทับไฟล์")
        return

    # เขียนทับแบบเติมเข้า (รักษาของเก่า)
    with open(MONTH, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ เติม {added} วิดีโอใหม่เข้า views_month.jsonl (รวม {len(out_rows)} วิดีโอ)")

if __name__ == "__main__":
    main()
