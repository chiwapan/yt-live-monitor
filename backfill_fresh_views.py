#!/usr/bin/env python3
# backfill_fresh_views.py — ดึงวิวจริงจาก YouTube API มาทุกวิดีโอใน views_month.jsonl
# แก้ปัญหาวิวค้าง: คลิปที่หลุดจาก top-15 ของ uploads playlist จะไม่ถูก snapshot เก็บ → วิวค้าง
# วิธี: อ่านทุก video_id จาก views_month.jsonl → videos.list (แบ่ง 50/รอบ) → อัปเดต view_count/like_count
#       เข้า month file + เขียน snapshot ใหม่ (ts=now) เข้า views_live.jsonl  ให้ dashboard ใช้ค่าล่าสุด
# รัน: MODE ครั้งเดียว (one-shot) ใช้ quota ~1 unit/50 วิดีโอ
import os, sys, json, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
HERE = os.path.dirname(os.path.abspath(__file__))
MONTH = os.path.join(HERE, "views_month.jsonl")
LIVE = os.path.join(HERE, "views_live.jsonl")
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
BATCH = 50

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

def fetch_meta(vids):
    """video_id -> dict(published_at, view_count, like_count, is_short_est) แบ่ง 50/รอบ"""
    res = {}
    for i in range(0, len(vids), BATCH):
        batch = vids[i:i+BATCH]
        url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
            "part": "snippet,statistics,contentDetails", "id": ",".join(batch), "key": API_KEY})
        data = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    print(f"  ⚠️ 403 quota — หน่วง 60s (try {attempt+1}/3)"); time.sleep(60); continue
                print(f"  ⚠️ HTTP {e.code}: {e}"); break
            except Exception as e:
                print(f"  ⚠️ network {e} (try {attempt+1}/3)"); time.sleep(5); continue
        if not data:
            print("  ❌ batch ล้มเหลว — หยุด"); return res
        for it in data.get("items", []):
            vid = it.get("id")
            sn = it.get("snippet", {}); st = it.get("statistics", {}); cd = it.get("contentDetails", {})
            dur = cd.get("duration", "")
            is_short = dur.startswith("PT") and "M" not in dur.split("T")[1] and dur.endswith("S") and dur != "PT0S"
            res[vid] = {
                "title": sn.get("title", "")[:100],
                "view_count": int(st.get("viewCount", 0)),
                "like_count": int(st.get("likeCount", 0)),
                "is_short_est": bool(is_short),
            }
        time.sleep(0.5)
        print(f"  batched {min(i+BATCH,len(vids))}/{len(vids)} ({len(res)} got)")
    return res

def main():
    if not API_KEY:
        print("❌ ไม่มี YOUTUBE_API_KEY"); sys.exit(1)

    month = read_jsonl(MONTH)
    if not month:
        print("❌ views_month.jsonl ว่าง"); sys.exit(1)
    month_map = {}
    for r in month:
        if r.get("video_id"):
            month_map[r["video_id"]] = r
    print(f"📂 views_month.jsonl: {len(month_map)} วิดีโอ")

    # ดึงวิวจริงทุก video_id
    all_ids = list(month_map.keys())
    print(f"🔎 ดึงวิวจริงจาก YouTube: {len(all_ids)} วิดีโอ กลุ่มละ {BATCH}")
    meta = fetch_meta(all_ids)
    print(f"✅ ได้ metadata {len(meta)}/{len(all_ids)}")

    if not meta:
        print("❌ ดึงไม่ได้เลย — ไม่เขียนทับ"); sys.exit(1)

    # อัปเดต month file (view_count/like_count/is_short_est ให้ตรงจริง)
    for vid, m in meta.items():
        r = month_map.get(vid)
        if r:
            r["view_count"] = m["view_count"]
            r["like_count"] = m["like_count"]
            r["is_short_est"] = m["is_short_est"]
            if m.get("title"): r["title"] = m["title"]

    with open(MONTH, "w", encoding="utf-8") as f:
        for r in month_map.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ อัปเดต view_count ใน {MONTH} ({len(month_map)} rows)")

    # เขียน snapshot ใหม่ (ts=now) ลง views_live.jsonl เพื่อ dashboard ใช้ค่าล่าสุด
    now = datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    with open(LIVE, "a", encoding="utf-8") as f:
        for vid, r in month_map.items():
            m = meta.get(vid)
            if not m:
                continue
            f.write(json.dumps({
                "ts": now,
                "channel_id": r.get("channel_id", ""),
                "channel": r.get("channel", ""),
                "video_id": vid,
                "title": m.get("title") or r.get("title", ""),
                "view_count": m["view_count"],
                "like_count": m["like_count"],
                "is_short_est": m["is_short_est"],
            }, ensure_ascii=False) + "\n")
            added += 1
    print(f"✅ เขียน snapshot ใหม่ {added} แถว เข้า {LIVE}")

if __name__ == "__main__":
    main()
