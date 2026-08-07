#!/usr/bin/env python3
"""YouTube Views Collector — เก็บยอดวิวรายวัน แยก Video (CORE) / Short (SHORTS).
แยกจาก live monitor เด็ดขาด:
- Live monitor   = realtime poll concurrent viewers (Data API, API key, ทุก 5 นาที)
- Views collector = batch รายวัน (Analytics API v2, OAuth) + snapshot สด (Data API)

ทำไมไม่ใช้ Data API อย่างเดียว:
- videos.list คืนแค่ viewCount สะสมตลอดชีพ ไม่มีมิติเวลา ไม่มี Shorts flag
- Analytics API มี dimension `youtubeProduct` = CORE (long-form) vs SHORTS → แยกสะอาด

สองโหมด (เลือกด้วย env MODE):
  MODE=batch     (default) → Analytics API ดึงรายวัน แยก CORE/SHORTS, delay-safe + upsert
  MODE=snapshot  → Data API ดึง viewCount สดทันที ของ top video ทุกช่อง (คล้าย social listening)
                    ได้ตัวเลขสดแบบเรียลไทม์ แต่ไม่มีมิติ Shorts แยก

Data model (JSONL):
  Batch (views_data.jsonl):
    Channel-level (1 row/ช่อง/วัน/product):
      {"date","channel_id","channel","product":"CORE|SHORTS","views","watch_time_min",
       "estimated_revenue","subs_gained","subs_lost","avg_view_dur","impressions","ctr"}
    Per-video (top N/ช่อง/วัน/product) — เปิดเมื่อ TOP_N>0:
      {"date","channel_id","channel","product","video_id","title","views","watch_time_min"}
  Snapshot (views_live.jsonl) — ตัวเลขสดทันที:
      {"ts","channel_id","channel","video_id","title","view_count","like_count","is_short_est"}

Config (env):
  MODE                 batch | snapshot (default batch)
  VIEWS_JSONL          path batch JSONL (default /data/views_data.jsonl)
  VIEWS_LIVE_JSONL     path snapshot JSONL (default /data/views_live.jsonl)
  VIEWS_SHEET_ID       Sheet ID
  GAPI_SCRIPT          path google_api.py (ต้องมี scope yt-analytics.readonly)
  CMS_ID               contentOwner ID (จาก memory: 6tGFEVDsxneJqsVjifQvEA)
  TOP_N                top/N ช่อง/วัน (0 = ข้าม per-video)
  VIEWS_LOOKBACK_DAYS  จำนวนวันย้อนหลังดึงต่อรอบ batch (default 2 — delay-safe)
  YOUTUBE_API_KEY      API key สำหรับ snapshot mode
  SNAPSHOT_TOP         จำนวนวิดีโอ/ช่อง ที่ดึง snapshot (default 15)

Delay-safe (batch):
  - ดึงย้อนหลัง LOOKBACK วัน (default 2) เพื่อให้ data วันล่าสุดที่อาจยังหน่วงมาครบ
  - ข้ามวันที่ views==0 และ revenue==0 (ยังไม่มี data จริง)
  - dedupe ตาม date+channel+product+video_id แล้ว upsert ทับของเก่า (กัน double)
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))

CHANNELS = [
    {'id': 'UCrFDdD-EE05N7gjwZho2wqw', 'name': 'ThaiRath News'},
    {'id': 'UCtc9-CS_FIZ7GGrm8--wsrQ', 'name': 'ThaiRath Variety'},
    {'id': 'UC6x41swVZP3rEmy-ODxLMFA', 'name': 'ข่าวช่อง8'},
    {'id': 'UCzMoibQRslh_1bTuW0YXc6A', 'name': 'Amarin TV'},
    {'id': 'UCXm0bpjlfB0AF-ZdPhT0K1A', 'name': 'โหนกระแส'},
    {'id': 'UC5wKpLWxAZBZrunls3mzwEw', 'name': 'เรื่องเล่าเช้านี้'},
    {'id': 'UCirZPTc9IoKM_DsA9aKbc4g', 'name': 'ครอบครัวข่าว3'},
    {'id': 'UC4kPIfdCZrPqoQ94m6-eFsg', 'name': 'สรยุทธ กรรมกรข่าว'},
    {'id': 'UC3WyfUir0HD8sFI4AVAl6SQ', 'name': 'ข่าวเวิร์คพอยท์ 23'},
    {'id': 'UCDAl2WdfkIbzhRNESXi-3lw', 'name': 'Dailynews Online'},
    {'id': 'UCXUVnTEsLZBim_WlWxBvEwA', 'name': 'Ch7HD'},
    {'id': 'UC2OtDM92rLjt4mm43ED1Q-w', 'name': 'Ch7HDNews'},
    {'id': 'UCKXg1i42GPbDZDDBs-dzweg', 'name': 'TERO ENTERTAINMENT'},
    {'id': 'UCnMyW2tEZDWWYq-6VIdrDVA', 'name': 'Phutta Talk'},
    {'id': 'UCbJfg1BrJ5hJPlVqDUUv8lg', 'name': 'sondhitalk'},
    {'id': 'UC5TOFhyb_LxL2VG_Zenhpzw', 'name': 'Thai PBS'},
    {'id': 'UCk1v3FzlMu3r34LYgoHpH2w', 'name': 'THE STANDARD'},
    {'id': 'UCtBu8Wb2BUoduUXJS9Uss7Q', 'name': 'ช่อง8 Thai Ch8'},
    {'id': 'UC7FCQJFK1sfwD_uobB45Xng', 'name': 'PPTV HD 36'},
    {'id': 'UCq2_AaNWBd0kxzR1HL2yhsw', 'name': 'terodigital'},
    {'id': 'UCqZ3is1Z4ck-I0ObYFw8OEQ', 'name': 'ข่าวช่องวัน'},
    {'id': 'UCQ2ABjf4gcrF0-zfDLQhWFQ', 'name': 'TODAY'},
    {'id': 'UC3S5gtXjd522gCtjOkYRUwg', 'name': 'matichon tv'},
    {'id': 'UCeF5sxjXSdWq80n3RA9gBpw', 'name': 'TOP NEWS LIVE'},
    {'id': 'UC37k-Kxlc7rDpHLZTNytNDw', 'name': 'Thairath Sport'},
    {'id': 'UCygWbILDfBfPN6xR3mrHXHA', 'name': 'News1'},
    {'id': 'UCzheDCNyul0tRvvoGycjz6A', 'name': 'Jomquan'},
    {'id': 'UC7d3VlqC5LvvIraCNHBFtjw', 'name': 'แนวหน้าออนไลน์'},
    {'id': 'UCxT3t-i3nX4uAbvXEsyWmsA', 'name': 'suthichai live'},
    {'id': 'UCJ6PZBK3kOYKBLmvKwdI1gg', 'name': 'NationTV Live'},
    {'id': 'UCqUBA96OsqMgSFvTwLXY9yw', 'name': 'TNN'},
    {'id': 'UCv1QMOzm4RPDtm8-JchAkkw', 'name': 'SiroteTalk'},
    {'id': 'UCDI9EEC4ZstO4v-Sg8vlfBQ', 'name': 'อาร์ท เอกรัฐ'},
    {'id': 'UCOFvLl4bKwCIZg0r4EBQLug', 'name': 'ThaiPBSNews'},
    {'id': 'UCMtFuOVbM_T43hYLnRA4MEA', 'name': 'Ejan : อีจัน'},
]
MODE = os.environ.get("MODE", "batch")
VIEWS_JSONL = os.environ.get("VIEWS_JSONL", "/data/views_data.jsonl")
VIEWS_LIVE_JSONL = os.environ.get("VIEWS_LIVE_JSONL", "/data/views_live.jsonl")
SHEET_ID = os.environ.get("VIEWS_SHEET_ID", "")
GAPI_SCRIPT = os.environ.get("GAPI_SCRIPT",
    "/opt/data/skills/productivity/google-workspace/scripts/google_api.py")
CMS_ID = os.environ.get("CMS_ID", "6tGFEVDsxneJqsVjifQvEA")  # default CMS ThaiRath
TOP_N = int(os.environ.get("TOP_N", "20"))
LOOKBACK = int(os.environ.get("VIEWS_LOOKBACK_DAYS", "2"))
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SNAPSHOT_TOP = int(os.environ.get("SNAPSHOT_TOP", "15"))


# ─── Analytics (batch) ───────────────────────────────────────────────
def get_analytics_service():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import google_api
    creds = google_api.get_credentials()
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=creds)


def ids_param(channel_id):
    if CMS_ID:
        return f"contentOwner=={CMS_ID}", {"onBehalfOfContentOwner": CMS_ID}
    return f"channel=={channel_id}", {}


def query_channel_product(service, channel_id, start, end):
    ids, extra = ids_param(channel_id)
    req = {
        "ids": ids,
        "startDate": start,
        "endDate": end,
        "metrics": ("views,watchTimeMinutes,estimatedRevenue,subscribersGained,"
                    "subscribersLost,averageViewDuration,impressions,impressionsClickThroughRate"),
        "dimensions": "youtubeProduct",
    }
    # onBehalfOfContentOwner เป็น system parameter → ส่งเป็น kwarg ตรงๆ ไม่ใช่ใน body dict
    return service.reports().query(**req, **extra).execute()


def query_top_videos(service, channel_id, start, end, product):
    ids, extra = ids_param(channel_id)
    req = {
        "ids": ids,
        "startDate": start,
        "endDate": end,
        "metrics": "views,watchTimeMinutes",
        "dimensions": "video",
        "filters": f"youtubeProduct=={product}",
        "sort": "-views",
        "maxResults": TOP_N,
    }
    return service.reports().query(**req, **extra).execute()


def collect_day(service, day):
    start = day
    end = day
    rows_channel = []
    rows_video = []

    for ch in CHANNELS:
        cid, cname = ch["id"], ch["name"]
        try:
            resp = query_channel_product(service, cid, start, end)
            for row in resp.get("rows", []):
                # column order ตาม metrics ข้างบน
                (product, views, wtm, rev, sg, sl, avd, imp, ctr) = (
                    row[0], int(row[1]), int(row[2]), float(row[3]),
                    int(row[4]), int(row[5]), int(row[6]),
                    int(row[7] or 0), float(row[8] or 0))
                # delay-safe: ข้ามวันที่ยังไม่มี data จริง
                if views == 0 and rev == 0:
                    continue
                rows_channel.append({
                    "date": day, "channel_id": cid, "channel": cname,
                    "product": product, "views": views,
                    "watch_time_min": wtm, "estimated_revenue": rev,
                    "subs_gained": sg, "subs_lost": sl,
                    "avg_view_dur": avd, "impressions": imp, "ctr": ctr,
                })
        except Exception as e:
            print(f"⚠️ channel query {cname}: {e}")

        if TOP_N > 0:
            for product in ("CORE", "SHORTS"):
                try:
                    resp = query_top_videos(service, cid, start, end, product)
                    for row in resp.get("rows", []):
                        vid, views, wtm = row[0], int(row[1]), int(row[2])
                        rows_video.append({
                            "date": day, "channel_id": cid, "channel": cname,
                            "product": product, "video_id": vid,
                            "title": "", "views": views, "watch_time_min": wtm,
                        })
                except Exception as e:
                    print(f"⚠️ video query {cname}/{product}: {e}")

    return rows_channel, rows_video


def enrich_titles(rows_video):
    if not API_KEY or not rows_video:
        return
    from urllib.parse import urlencode
    import urllib.request
    vid_map = {r["video_id"]: r for r in rows_video}
    ids = list(vid_map.keys())
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        url = "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
            "part": "snippet", "id": ",".join(batch), "key": API_KEY})
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            for it in data.get("items", []):
                vid = it["id"]
                if vid in vid_map:
                    vid_map[vid]["title"] = it["snippet"].get("title", "")[:100]
        except Exception as e:
            print(f"⚠️ title enrich: {e}")


# ─── Data API (snapshot สด) ──────────────────────────────────────────
# ใช้ playlist uploads (playlistItems.list = 1 unit) แทน search.list (100 unit)
# → รันได้ทุกชั่วโมงโดยไม่ทะลุ quota 10,000 units/วัน
_UPLOADS_CACHE = {}  # channel_id -> uploads playlist id (cache ใน process)

def _get_uploads_playlist(channel_id):
    if channel_id in _UPLOADS_CACHE:
        return _UPLOADS_CACHE[channel_id]
    from urllib.parse import urlencode
    import urllib.request
    url = "https://www.googleapis.com/youtube/v3/channels?" + urlencode({
        "part": "contentDetails", "id": channel_id, "key": API_KEY})
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    pid = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    _UPLOADS_CACHE[channel_id] = pid
    return pid


def collect_snapshot():
    """ดึง viewCount สดทันที ของ top video ทุกช่อง → คล้าย social listening
    ทำงานทุกชั่วโมงได้ เพราะใช้ playlistItems (1 unit) + videos.list (~1-3 unit)
    """
    if not API_KEY:
        print("⚠️ snapshot mode ต้องมี YOUTUBE_API_KEY")
        return []
    import urllib.request
    from urllib.parse import urlencode
    rows = []
    now = datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S")
    for ch in CHANNELS:
        try:
            pid = _get_uploads_playlist(ch["id"])
            # ดึง video ID ล่าสุดจาก uploads playlist (1 unit)
            purl = "https://www.googleapis.com/youtube/v3/playlistItems?" + urlencode({
                "part": "contentDetails", "playlistId": pid,
                "maxResults": SNAPSHOT_TOP, "key": API_KEY})
            with urllib.request.urlopen(purl, timeout=15) as r:
                pdata = json.loads(r.read())
            vids = [it["contentDetails"]["videoId"] for it in pdata.get("items", [])]
            if not vids:
                continue
            # ดึง statistics สด (~1-3 unit)
            vurl = "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
                "part": "snippet,statistics,contentDetails", "id": ",".join(vids),
                "key": API_KEY})
            with urllib.request.urlopen(vurl, timeout=15) as r:
                vdata = json.loads(r.read())
            for it in vdata.get("items", []):
                dur = it.get("contentDetails", {}).get("duration", "")
                vc = int(it.get("statistics", {}).get("viewCount", 0))
                lc = int(it.get("statistics", {}).get("likeCount", 0))
                # ประมาณ short จาก duration (<60s) — heuristic ไม่ใช่ fact จาก API
                is_short = dur.startswith("PT") and "M" not in dur.split("T")[1] and "0S" in dur
                rows.append({
                    "ts": now, "channel_id": ch["id"], "channel": ch["name"],
                    "video_id": it["id"],
                    "title": it.get("snippet", {}).get("title", "")[:100],
                    "view_count": vc, "like_count": lc,
                    "is_short_est": bool(is_short),
                })
        except Exception as e:
            print(f"⚠️ snapshot {ch['name']}: {e}")
    return rows


# ─── JSONL + dedupe ─────────────────────────────────────────────────
def load_existing(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            key = (r.get("date"), r.get("channel_id"), r.get("product"),
                   r.get("video_id", ""))
            out[key] = r
    return out


def upsert_jsonl(path, rows):
    if not rows:
        return
    existing = load_existing(path)
    added = 0
    for r in rows:
        key = (r.get("date"), r.get("channel_id"), r.get("product"),
               r.get("video_id", ""))
        if key in existing:
            # update ของเก่า (เช่น data วันนั้นมาเต็มทีหลัง)
            existing[key].update(r)
        else:
            existing[key] = r
            added += 1
    with open(path, "w") as f:
        for r in existing.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ {path}: +{added} ใหม่, upsert {len(rows)-added} วันที่มีอยู่")


def append_snapshot(path, rows):
    if not rows:
        return
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ snapshot +{len(rows)} rows → {path}")


def sheets_append(tab, rows):
    if not rows or not SHEET_ID:
        return
    values = [list(r.values()) for r in rows]
    cmd = [sys.executable, GAPI_SCRIPT, "sheets", "append",
           SHEET_ID, f"{tab}!A:H", "--values", json.dumps(values)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            print(f"⚠️ Sheets {tab}: {res.stderr.strip()}")
        else:
            print(f"✅ Sheets +{len(rows)} rows → {tab}")
    except Exception as e:
        print(f"⚠️ Sheets {tab}: {e}")


# ─── Main ────────────────────────────────────────────────────────────
def main():
    if MODE == "snapshot":
        if not API_KEY:
            print("⚠️ ต้องตั้ง YOUTUBE_API_KEY สำหรับ snapshot mode")
            sys.exit(1)
        rows = collect_snapshot()
        append_snapshot(VIEWS_LIVE_JSONL, rows)
        if SHEET_ID:
            sheets_append("Views_Live", rows)
        print("✅ snapshot done")
        return

    # MODE = batch
    if not SHEET_ID and not os.environ.get("VIEWS_JSONL"):
        print("⚠️ ต้องตั้ง VIEWS_SHEET_ID หรือ VIEWS_JSONL")
        sys.exit(1)

    today = datetime.now(ICT).date()
    # delay-safe: ดึงย้อนหลัง LOOKBACK วัน (default 2) → วันล่าสุดที่หน่วงมาครบ
    days = [(today - timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(1, LOOKBACK + 1)]

    service = get_analytics_service()
    for day in days:
        print(f"📊 Collecting {day} ...")
        rows_ch, rows_vid = collect_day(service, day)
        if rows_vid:
            enrich_titles(rows_vid)
        # dedupe + upsert ทับวันที่ซ้ำ
        upsert_jsonl(VIEWS_JSONL, rows_ch + rows_vid)
        if SHEET_ID:
            sheets_append("Views_Daily", rows_ch)
            if rows_vid:
                sheets_append("Views_Video", rows_vid)

    print("✅ Views collector (batch) done")


if __name__ == "__main__":
    main()
