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
TOTALS_SINCE = os.environ.get("TOTALS_SINCE", "2026-07-01")  # ดึงยอดวิวคลิปที่โพสต์หลังวันนี้


# ─── Analytics (batch) ───────────────────────────────────────────────
def get_analytics_service():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import google_api
    creds = google_api.get_credentials()
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=creds)


def ids_param(channel_id, is_cms=False):
    if CMS_ID and is_cms:
        return f"contentOwner=={CMS_ID}", {}
    return f"channel=={channel_id}", {}


# ช่องที่อยู่ใน CMS ThaiRath (ใช้ contentOwner) — นอกเหนือจากนี้ใช้ channel== ธรรมดา
CMS_CHANNEL_IDS = {
    "UCrFDdD-EE05N7gjwZho2wqw",  # ThaiRath News
    "UCtc9-CS_FIZ7GGrm8--wsrQ",  # ThaiRath Variety
}


def query_channel_product(service, channel_id, start, end, is_cms=False):
    ids, extra = ids_param(channel_id, is_cms)
    req = {
        "ids": ids,
        "startDate": start,
        "endDate": end,
        "metrics": ("views,estimatedMinutesWatched,estimatedRevenue,subscribersGained,"
                    "subscribersLost,averageViewDuration"),
        "dimensions": "youtubeProduct",
    }
    return service.reports().query(**req, **extra).execute()


def query_top_videos(service, channel_id, start, end, product, is_cms=False):
    ids, extra = ids_param(channel_id, is_cms)
    req = {
        "ids": ids,
        "startDate": start,
        "endDate": end,
        "metrics": "views,estimatedMinutesWatched",
        "dimensions": "video",
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
        is_cms = cid in CMS_CHANNEL_IDS
        try:
            resp = query_channel_product(service, cid, start, end, is_cms)
            for row in resp.get("rows", []):
                # column order ตาม metrics: product,views,wtm,rev,sg,sl,avd
                (product, views, wtm, rev, sg, sl, avd) = (
                    row[0], int(row[1]), int(row[2]), float(row[3]),
                    int(row[4]), int(row[5]), int(row[6]))
                # delay-safe: ข้ามวันที่ยังไม่มี data จริง
                if views == 0 and rev == 0:
                    continue
                rows_channel.append({
                    "date": day, "channel_id": cid, "channel": cname,
                    "product": product, "views": views,
                    "watch_time_min": wtm, "estimated_revenue": rev,
                    "subs_gained": sg, "subs_lost": sl,
                    "avg_view_dur": avd,
                })
        except Exception as e:
            print(f"⚠️ channel query {cname}: {e}")

        if TOP_N > 0:
            for product in ("CORE", "SHORTS"):
                try:
                    resp = query_top_videos(service, cid, start, end, product, is_cms)
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


MONTH_VID_ROWS = []


def collect_channel_totals():
    """Backfill: ดึงคลิปที่โพสต์หลัง TOTALS_SINCE ของแต่ละช่อง → บวก viewCount สะสม
    แยก CORE/SHORTS ตาม duration (<60s = short) → ได้ยอดสะสมช่องคร่าวๆ ย้อนหลังได้
    (ไม่พึ่ง Analytics CMS) รันครั้งเดียว พอ ไม่ใส่ loop
    มี delay + retry ป้องกัน API key โดน rate-limit 403"""
    MONTH_VID_ROWS.clear()
    if not API_KEY:
        print("⚠️ channel_totals ต้องมี YOUTUBE_API_KEY")
        return []
    import urllib.request, urllib.error, time
    from urllib.parse import urlencode
    rows = []
    now = datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S")
    for ch in CHANNELS:
        try:
            pid = _get_uploads_playlist(ch["id"])
            # ดึงคลิปล่าสุด แล้วกรองเอาแค่โพสต์หลัง TOTALS_SINCE
            vids = []          # (video_id, publishedAt)
            page = None
            page_no = 0
            scanned = 0
            while True:
                params = {"part": "contentDetails", "playlistId": pid,
                          "maxResults": 50, "key": API_KEY}
                if page:
                    params["pageToken"] = page
                purl = "https://www.googleapis.com/youtube/v3/playlistItems?" + urlencode(params)
                with urllib.request.urlopen(purl, timeout=20) as r:
                    pdata = json.loads(r.read())
                for it in pdata.get("items", []):
                    vid = it.get("contentDetails", {}).get("videoId")
                    pub = it.get("contentDetails", {}).get("videoPublishedAt", "")
                    if vid:
                        scanned += 1
                        if pub >= TOTALS_SINCE:
                            vids.append((vid, pub))
                page = pdata.get("nextPageToken")
                page_no += 1
                print(f"  … {ch['name']}: หน้า {page_no} สแกน {scanned} คลิป, หลัง {TOTALS_SINCE}: {len(vids)}", flush=True)
                if not page or (pdata.get("items") and pdata["items"][-1].get("contentDetails", {}).get("videoPublishedAt", "") < TOTALS_SINCE):
                    break
                time.sleep(0.5)   # นิ่มเครื่องระหว่างหน้า
            if not vids:
                continue
            # ดึง statistics + duration ทีละ 50 (videos.list) พร้อม retry ถ้า 403
            total_views = 0
            core_views = 0
            short_views = 0
            n_core = 0
            n_short = 0
            vid_pub = {v[0]: v[1] for v in vids}
            for i in range(0, len(vids), 50):
                batch = [v[0] for v in vids[i:i+50]]
                vurl = "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
                    "part": "contentDetails,statistics,snippet", "id": ",".join(batch),
                    "key": API_KEY})
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(vurl, timeout=20) as r:
                            vdata = json.loads(r.read())
                        break
                    except urllib.error.HTTPError as he:
                        if he.code == 403 and attempt < 2:
                            print(f"  ⏳ 403 rate-limit {ch['name']} หน่วง 60s (ลอง {attempt+1}/3)", flush=True)
                            time.sleep(60)
                        else:
                            raise
                for it in vdata.get("items", []):
                    vid = it["id"]
                    vc = int(it.get("statistics", {}).get("viewCount", 0))
                    dur = it.get("contentDetails", {}).get("duration", "")
                    is_short = dur.startswith("PT") and "M" not in dur.split("T")[1] and "0S" in dur
                    total_views += vc
                    if is_short:
                        short_views += vc; n_short += 1
                    else:
                        core_views += vc; n_core += 1
                    # เก็บ per-video สำหรับ Tab "Views เดือนล่าสุด"
                    MONTH_VID_ROWS.append({
                        "channel_id": ch["id"], "channel": ch["name"],
                        "video_id": vid,
                        "title": it.get("snippet", {}).get("title", "")[:100],
                        "view_count": vc,
                        "like_count": int(it.get("statistics", {}).get("likeCount", 0)),
                        "is_short_est": bool(is_short),
                        "published_at": vid_pub.get(vid, ""),
                        "since": TOTALS_SINCE,
                    })
            rows.append({
                "ts": now, "channel_id": ch["id"], "channel": ch["name"],
                "total_views": total_views,
                "core_views": core_views, "short_views": short_views,
                "n_core": n_core, "n_short": n_short,
                "n_videos": len(vids),
                "since": TOTALS_SINCE,
            })
            print(f"  ✓ {ch['name']}: {total_views:,} วิว จากคลิป {len(vids)} ตัว (โพสต์หลัง {TOTALS_SINCE})")
        except Exception as e:
            print(f"⚠️ channel_totals {ch['name']}: {e}")
        time.sleep(2)   # นิ่มเครื่องระหว่างช่อง ป้องกัน 403
    return rows


def write_channel_totals(path, rows):
    if not rows:
        print("⚠️ channel_totals: ไม่มีข้อมูลรอบนี้ (อาจโดน 403 หมด) → ข้าม ไม่เขียนทับไฟล์เดิม")
        return
    # merge กับของเดิม (เขียนทับเฉพาะช่องที่ได้รอบนี้) → รันซ้ำทีละช่องไม่หาย
    existing = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    existing[r["channel_id"]] = r
                except Exception:
                    continue
    for r in rows:
        existing[r["channel_id"]] = r
    with open(path, "w") as f:
        for r in existing.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ channel_totals +{len(rows)} ช่อง (รวม {len(existing)} ในไฟล์) → {path}")


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

    if MODE == "totals":
        # backfill ครั้งเดียว: ยอดสะสมช่อง (ไม่พึ่ง CMS)
        if not API_KEY:
            print("⚠️ ต้องตั้ง YOUTUBE_API_KEY สำหรับ totals mode")
            sys.exit(1)
        rows = collect_channel_totals()
        base = os.path.dirname(VIEWS_LIVE_JSONL)
        write_channel_totals(os.path.join(base, "channel_totals.jsonl"), rows)
        write_month_videos(os.path.join(base, "views_month.jsonl"), MONTH_VID_ROWS)
        print("✅ channel_totals + views_month done")
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


def write_month_videos(path, rows):
    """เขียน/merge per-video ที่ดึงจาก backfill totals → สำหรับ Tab 'Views เดือนล่าสุด'"""
    if not rows:
        print("⚠️ month_videos: ไม่มีข้อมูลรอบนี้ → ข้าม ไม่ทับไฟล์เดิม")
        return
    seen = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    seen[r.get("video_id")] = r
                except Exception:
                    continue
    for r in rows:
        seen[r["video_id"]] = r
    with open(path, "w") as f:
        for r in seen.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ views_month +{len(rows)} คลิป (รวม {len(seen)} ในไฟล์) → {path}")


if __name__ == "__main__":
    main()
