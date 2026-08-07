#!/usr/bin/env python3
"""YouTube Live Daily Monitor — poll concurrent viewers, store in Google Sheets.

Design:
- RSS discovery: check channel RSS feed for live/upcoming videos (0 quota)
- videos.list: get concurrentViewers for known live streams (1 unit/call)
- Google Sheets: per-stream rows with timestamp + peak tracking
- Silent when no live streams (don't spam)
- no_agent=True cron: zero LLM tokens

Sheet structure:
  Tab "Raw": Timestamp | Video_ID | Title | Concurrent_Viewers | Channel | URL
  Tab "Daily_Summary": Date | Video_ID | Title | Peak_Viewers | Start_Time | End_Time | Duration_Min

Config (all via env vars — zero tokens in code):
  YOUTUBE_API_KEY   — required, YouTube Data API v3 key
  YT_SHEET_ID       — required, Google Sheet ID to write into
  GAPI_SCRIPT       — optional, path to google_api.py helper (see .env.example)
"""

import os
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import subprocess
from datetime import datetime, timezone, timedelta

# ─── Config (all from env) ───
# Multi-key rotation: ใช้ YOUTUBE_API_KEYS (comma-separated) ถ้าตั้งไว้, fallback YOUTUBE_API_KEY
# เดิมตัวเดียว. แต่ละ key อยู่คนละ Google Cloud project → quota แยกกัน.
# Purpose: live collector ต้องทำงาน 24 ชม. — ไม่จม 403 quotaExceeded จาก key เดียวโดนกินหมด
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
API_KEYS = [k.strip() for k in os.environ.get("YOUTUBE_API_KEYS", "").split(",") if k.strip()]
if not API_KEYS and API_KEY:
    API_KEYS = [API_KEY]
API_KEYS = list(dict.fromkeys(API_KEYS))  # dedupe รักษาลำดับ

# ⚠️ SAFETY — ป้องกัน dev/test เผา quota ของโปรดักชัน (อุบัติเหตุ 2026-08-07)
# รันเป็น "production collector" แท้ต้องผ่าน container entrypoint (run_collector.py)
# ซึ่ง set YT_LIVE_PRODUCTION=1. ถ้ารันจาก host เพื่องาน dev/test โดยไม่ได้ตั้งใจ
# (เช่น `python3 yt-live-daily.py` ตรงๆ) → บล็อก ไม่ยอมใช้ key จริงใน .env
# ต้องการรัน live ด้วย key จริงนอก container จริงๆ → YT_LIVE_PRODUCTION=1 python3 ...
_IS_DEV_RUN = os.environ.get("YT_LIVE_PRODUCTION", "") != "1"
# DEMO/TEST MODE — module global (document the decision, independent of env ที่ถูก mutate)
# บังคับเปิดเมื่อ dev โดน guard; เปิดเองได้ผ่าน YT_DEMO_MODE=1 (offline test)
DEMO_MODE = os.environ.get("YT_DEMO_MODE") == "1"
if _IS_DEV_RUN and API_KEYS and not os.environ.get("YT_LIVE_DEV_KEYS"):
    _probe_dev = os.environ.get("STATE_FILE", "")
    if not _probe_dev or "projects/yt-live-monitor" in _probe_dev:
        # ดูเหมือนจะรันจาก repo ของโปรดักชัน ไม่ใช่ config ทดสอบ
        # ห้ามใช้ key จริง — บอกให้ใช้อันทดสอบ mock แทน
        API_KEYS = ["YT_LIVE_TEST_KEY_ONLY"]  # key ปลอมชัดเจน ห้ามใช้จริง
        DEMO_MODE = True
        print("🚧 SAFETY: รัน dev/test (ไม่ผ่าน container) — ห้ามใช้ key จริง")
        print("   ใช้ key ปลอม + mock ไปก่อน ถ้าอยากรัน live จริงนอก container:")
        print("   YT_LIVE_PRODUCTION=1 python3 yt-live-daily.py  (ระวัง quota)")
SHEET_ID = os.environ.get("YT_SHEET_ID", "")
GAPI_SCRIPT = os.environ.get("GAPI_SCRIPT",
    "/opt/data/skills/productivity/google-workspace/scripts/google_api.py")

CHANNELS = [
    {"id": "UCrFDdD-EE05N7gjwZho2wqw", "name": "ThaiRath News"},
    {"id": "UCtc9-CS_FIZ7GGrm8--wsrQ", "name": "ThaiRath Variety"},
    {"id": "UC6x41swVZP3rEmy-ODxLMFA", "name": "ข่าวช่อง8"},
    {"id": "UCzMoibQRslh_1bTuW0YXc6A", "name": "Amarin TV"},
    {"id": "UCXm0bpjlfB0AF-ZdPhT0K1A", "name": "โหนกระแส"},
    {"id": "UC5wKpLWxAZBZrunls3mzwEw", "name": "เรื่องเล่าเช้านี้"},
    {"id": "UCirZPTc9IoKM_DsA9aKbc4g", "name": "ครอบครัวข่าว3"},
    {"id": "UC4kPIfdCZrPqoQ94m6-eFsg", "name": "สรยุทธ กรรมกรข่าว"},
    {"id": "UC3WyfUir0HD8sFI4AVAl6SQ", "name": "ข่าวเวิร์คพอยท์ 23"},
    {"id": "UCDAl2WdfkIbzhRNESXi-3lw", "name": "Dailynews Online"},
    {"id": "UCXUVnTEsLZBim_WlWxBvEwA", "name": "Ch7HD"},
    {"id": "UC2OtDM92rLjt4mm43ED1Q-w", "name": "Ch7HDNews"},
    {"id": "UCKXg1i42GPbDZDDBs-dzweg", "name": "TERO ENTERTAINMENT"},
    {"id": "UCnMyW2tEZDWWYq-6VIdrDVA", "name": "Phutta Talk"},
    {"id": "UCbJfg1BrJ5hJPlVqDUUv8lg", "name": "sondhitalk"},
    {"id": "UC5TOFhyb_LxL2VG_Zenhpzw", "name": "Thai PBS"},
    {"id": "UCk1v3FzlMu3r34LYgoHpH2w", "name": "THE STANDARD"},
    {"id": "UCtBu8Wb2BUoduUXJS9Uss7Q", "name": "ช่อง8 Thai Ch8"},
    {"id": "UC7FCQJFK1sfwD_uobB45Xng", "name": "PPTV HD 36"},
    {"id": "UCq2_AaNWBd0kxzR1HL2yhsw", "name": "terodigital"},
    {"id": "UCqZ3is1Z4ck-I0ObYFw8OEQ", "name": "ข่าวช่องวัน"},
    {"id": "UCQ2ABjf4gcrF0-zfDLQhWFQ", "name": "TODAY"},
    {"id": "UC3S5gtXjd522gCtjOkYRUwg", "name": "matichon tv"},
    {"id": "UCeF5sxjXSdWq80n3RA9gBpw", "name": "TOP NEWS LIVE"},
    {"id": "UC37k-Kxlc7rDpHLZTNytNDw", "name": "Thairath Sport"},
    {"id": "UCygWbILDfBfPN6xR3mrHXHA", "name": "News1"},
    {"id": "UCzheDCNyul0tRvvoGycjz6A", "name": "Jomquan"},
    {"id": "UC7d3VlqC5LvvIraCNHBFtjw", "name": "แนวหน้าออนไลน์"},
    {"id": "UCxT3t-i3nX4uAbvXEsyWmsA", "name": "suthichai live"},
    {"id": "UCJ6PZBK3kOYKBLmvKwdI1gg", "name": "NationTV Live"},
    {"id": "UCqUBA96OsqMgSFvTwLXY9yw", "name": "TNN"},
    {"id": "UCv1QMOzm4RPDtm8-JchAkkw", "name": "SiroteTalk"},
    {"id": "UCDI9EEC4ZstO4v-Sg8vlfBQ", "name": "อาร์ท เอกรัฐ"},
    {"id": "UCOFvLl4bKwCIZg0r4EBQLug", "name": "ThaiPBSNews"},
    {"id": "UCMtFuOVbM_T43hYLnRA4MEA", "name": "Ejan : อีจัน"},
]

ICT = timezone(timedelta(hours=7))
STATE_FILE = os.environ.get("STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-live-daily-state.json"))


def floor_5min(dt):
    """Floor datetime to nearest 5-minute mark (cron-aligned)."""
    new_min = (dt.minute // 5) * 5
    return dt.replace(minute=new_min, second=0, microsecond=0)


# ─── YouTube Data API (API key only, no OAuth needed for public data) ───

# ─── Key health tracking (แยกไฟล์จาก STATE_FILE — เขียนถี่, ไฟล์เล็ก, ไม่ race กับ state 90KB) ───
#
# ปัญหาเดิม (2026-08-07): key ที่ quota หมดยังถูกเรียกซ้ำทุก call → log ท่วม + เสียเวลา +
# batch ที่โชคร้ายเจอ 429 ถูกทิ้งทั้งก้อน (live คนดูหลักหมื่นหายไปเฉยๆ)
#
# แก้ถาวร: จำสุขภาพราย key
#   - 403 quotaExceeded  → dead ถึงเที่ยงคืน Pacific (YouTube reset quota ตอนนั้น)
#   - 429 / rateLimit    → dead 120 วินาที (ชั่วคราว)
#   - นับ units ที่ใช้ต่อ key ต่อวัน → ใช้ตัดสินว่าเหลือ budget พอทำ search (100 units) ไหม
KEY_HEALTH_FILE = os.environ.get("KEY_HEALTH_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-key-health.json"))
DAILY_QUOTA_PER_KEY = int(os.environ.get("DAILY_QUOTA_PER_KEY", "10000"))
# กัน budget ไว้ให้ videos.list (งานหลัก) เสมอ — ห้าม search กินจนหมด
POLL_RESERVE_UNITS = int(os.environ.get("POLL_RESERVE_UNITS", "1500"))
PT = timezone(timedelta(hours=-8))  # Pacific (quota reset boundary)

# In-memory cache ต่อ 1 tick (1 process run)
# Persist: เก็บใน STATE_FILE (bind-mounted ใน Docker → รอด container restart)
# ไม่เขียนไฟล์แยกทุก API call เพราะ /data ผูก bind mount เป็นรายไฟล์
# ไฟล์ใหม่ใน container จะหายเมื่อ restart
_HEALTH_CACHE = None


def _quota_day():
    """วันของ quota window ตามเวลา Pacific (YouTube reset เที่ยงคืน PT)."""
    return datetime.now(PT).strftime("%Y-%m-%d")


def _load_health():
    """โหลด key health จาก STATE_FILE (bind mount → persist ข้าม container restart)."""
    global _HEALTH_CACHE
    if _HEALTH_CACHE is not None:
        return _HEALTH_CACHE
    h = {}
    try:
        with open(STATE_FILE) as f:
            h = json.load(f).get("_key_health", {}) or {}
    except Exception:
        h = {}
    if h.get("day") != _quota_day():
        h = {"day": _quota_day(), "keys": {}, "idx": 0}
    h.setdefault("keys", {})
    h.setdefault("idx", 0)
    _HEALTH_CACHE = h
    return h


def _save_health(h):
    """อัปเดต cache ในหน่วยความจำเท่านั้น — flush ลงดิสก์ตอน save_state() ปลาย tick.

    ทำไมไม่เขียนไฟล์ทุกครั้ง:
      - STATE_FILE ~90KB เขียนทุก API call = I/O เปล่า
      - STATE_FILE เป็น Docker bind-mount ไฟล์เดี่ยว → os.replace() พัง (EBUSY)
        ต้องเขียนทับ in-place เท่านั้น (save_state ทำอยู่แล้ว)
    """
    global _HEALTH_CACHE
    _HEALTH_CACHE = h


def any_key_alive():
    """ยังมี key ไหนใช้ได้ไหม — ใช้ตัดวงจรก่อนยิง API ที่รู้อยู่แล้วว่าพัง."""
    h = _load_health()
    return any(_key_alive(h, k) for k in API_KEYS)


def _key_alive(h, k):
    info = h["keys"].get(k, {})
    return time.time() >= info.get("dead_until", 0)


def _mark_key(h, k, *, dead_for=None, dead_today=False, units=0):
    info = h["keys"].setdefault(k, {})
    info["units"] = info.get("units", 0) + units
    if dead_today:
        # ตายจนกว่าจะข้ามวัน quota (เที่ยงคืน PT)
        nxt = (datetime.now(PT) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        info["dead_until"] = nxt.timestamp()
        info["reason"] = "quotaExceeded"
    elif dead_for:
        info["dead_until"] = time.time() + dead_for
        info["reason"] = "rateLimit"


def quota_budget_left():
    """หน่วย quota ที่ยังพอใช้ได้รวมทุก key (ประมาณจากที่นับไว้)."""
    h = _load_health()
    total = 0
    for k in API_KEYS:
        if not _key_alive(h, k):
            continue
        total += max(0, DAILY_QUOTA_PER_KEY - h["keys"].get(k, {}).get("units", 0))
    return total


def key_health_report():
    h = _load_health()
    out = []
    for k in API_KEYS:
        info = h["keys"].get(k, {})
        used = info.get("units", 0)
        alive = _key_alive(h, k)
        state = "ok" if alive else f"dead({info.get('reason','?')})"
        out.append(f"{k[:8]}…={used}u/{state}")
    return " | ".join(out)


# quota cost ต่อ endpoint (YouTube Data API v3)
_UNIT_COST = {"videos": 1, "search": 100, "channels": 1, "playlistItems": 1}


def yt_api(endpoint, params, _cost=None):
    """Call YouTube Data API v3 พร้อม key rotation + health tracking + retry.

    หลักการ (แก้ถาวร 2026-08-07):
      1. ข้าม key ที่รู้อยู่แล้วว่าตาย (quota หมด / rate-limited) — ไม่เสียเวลายิงซ้ำ
      2. transient error (429, 403 rateLimit, network, 5xx) → rotate + retry key อื่น
         ทุกตัว ห้าม return {} ทิ้ง batch เด็ดขาด
      3. วนครบทุก key แล้วยังไม่ได้ → พัก 2 วิ แล้ววนอีกรอบ (สูงสุด 2 รอบ)
         เพราะ 429 เป็นของชั่วคราว มักหายใน 1-2 วินาที
      4. นับ units ที่ใช้จริงต่อ key → ใช้ตัดสิน budget ของ search layer
    """
    # 🧪 DEMO/TEST MODE — ตรวจก่อน !API_KEYS ปิด (demo mock ไม่ต้องใช้ key)
    # บังคับตอนรัน dev กันเผา quota โปรดักชัน (อุบัติเหตุ 2026-08-07)
    if DEMO_MODE:
        if endpoint == "videos":
            ids = [i for i in params.get("id", "").split(",") if i]
            items = []
            n = 0
            for vid in ids[:3]:  # จำกัด สุ่ม 3 ตัวพอให้ test ผ่าน
                n += 1
                items.append({
                    "kind": "youtube#video",
                    "id": vid,
                    "snippet": {"title": f"demo live {n}", "liveBroadcastContent": "live",
                                "channelTitle": "demo"},
                    "liveStreamingDetails": {"concurrentViewers": str(100 * n),
                                             "actualStartTime": "2026-08-07T00:00:00Z"},
                })
            # ปิด 1 รายการ (มี actualEndTime) เพื่อ test จบจริง
            if items:
                items[0]["liveStreamingDetails"] = {"actualEndTime": "2026-08-07T12:00:00Z"}
            return {"kind": "youtube#videoListResponse", "items": items}
        if endpoint == "search":
            return {"kind": "youtube#searchListResponse", "items": []}
        return {}

    if not API_KEYS:
        params["key"] = ""
        return {}

    cost = _cost if _cost is not None else _UNIT_COST.get(endpoint, 1)
    h = _load_health()
    n = len(API_KEYS)
    start = int(h.get("idx", 0)) % n
    dirty = False

    # ตัดวงจรก่อน: ทุก key ตายอยู่แล้ว → ไม่ต้องยิง ไม่ต้อง sleep
    if not any(_key_alive(h, k) for k in API_KEYS):
        return {}

    for rnd in range(2):  # 2 passes — pass 2 ให้โอกาส key ที่เพิ่งโดน 429 ชั่วคราว
        for attempt in range(n):
            idx = (start + attempt) % n
            k = API_KEYS[idx]
            if not _key_alive(h, k):
                continue
            params["key"] = k
            url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{urllib.parse.urlencode(params)}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
                    data = json.loads(resp.read())
                _mark_key(h, k, units=cost)
                h["idx"] = (idx + 1) % n
                _save_health(h)
                return data
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode()[:500]
                except Exception:
                    pass
                dirty = True
                if e.code == 403 and "quotaExceeded" in body:
                    _mark_key(h, k, dead_today=True, units=cost)
                    print(f"⛔ key {k[:8]}… quota หมดวันนี้ → ปิดจนถึงเที่ยงคืน PT")
                elif e.code == 429 or (e.code == 403 and "ateLimit" in body):
                    # 45 วิ — สั้นกว่า tick interval (5 นาที) เพื่อให้ฟื้นทัน tick หน้า
                    _mark_key(h, k, dead_for=45, units=cost)
                    print(f"⚠️ key {k[:8]}… rate-limited ({e.code}) → พัก 45 วิ")
                elif 500 <= e.code < 600:
                    _mark_key(h, k, dead_for=30)
                    print(f"⚠️ YouTube {e.code} (key {k[:8]}…) → retry key อื่น")
                else:
                    # error จริงจากคำขอ — เปลี่ยน key ก็ไม่ช่วย
                    if e.code in (400, 401) and "API key not valid" in body:
                        # key ผิด/ถูกเพิกถอน → ตายทั้งวัน อย่าเสียเวลายิงซ้ำ
                        _mark_key(h, k, dead_today=True)
                        _save_health(h)
                        print(f"⛔ key {k[:8]}… ใช้ไม่ได้ (invalid key) → ปิดถาวรวันนี้")
                        continue
                    _save_health(h)
                    print(f"⚠️ API error {e.code} (key {k[:8]}…): {e.reason} {body[:120]}")
                    return {}
            except Exception as e:
                dirty = True
                _mark_key(h, k, dead_for=20)
                print(f"⚠️ network error (key {k[:8]}…): {e} → retry key อื่น")
        if rnd == 0:
            time.sleep(2)

    if dirty:
        _save_health(h)
    print(f"⛔ ทุก key ใช้ไม่ได้ในรอบนี้ [{endpoint}] — {key_health_report()}")
    return {}


# ─── RSS Discovery (0 quota) ───

def get_live_from_rss():
    """Check all channel RSS feeds for recent videos (0 quota cost)."""
    # 🧪 DEMO MODE — offline ไม่ยิง network (RSS จริง 0 quota แต่ dev ควรให้ปลอดภัย/เร็ว)
    if DEMO_MODE:
        return [
            {"video_id": f"demo{r:02d}", "title": f"demo live {r}", "channel_id": "",
             "channel_name": "demo"}
            for r in range(3)
        ]
    all_videos = []
    for ch in CHANNELS:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"
        try:
            req = urllib.request.Request(rss_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
        except Exception as e:
            print(f"⚠️ RSS error for {ch['name']}: {e}")
            continue

        root = ET.fromstring(xml_data)
        ns_atom = "http://www.w3.org/2005/Atom"
        ns_yt = "http://www.youtube.com/xml/schemas/2015"

        for entry in root.findall(f"{{{ns_atom}}}entry"):
            video_id_el = entry.find(f"{{{ns_yt}}}videoId")
            title_el = entry.find(f"{{{ns_atom}}}title")
            if video_id_el is not None and title_el is not None:
                all_videos.append({
                    "video_id": video_id_el.text,
                    "title": title_el.text,
                    "channel_id": ch["id"],
                    "channel_name": ch["name"],
                })

    return all_videos


# ─── Live-Search Layer (กัน live หลุดจาก RSS — per-channel เฉพาะช่องหลัก, throttle) ───

# ช่องที่ต้อง monitor live จริง (RSS 15 อัน อาจเบียด live ที่ scheduled ไว้หลุด)
# คัดจากช่องที่ user ต้องการดู live เปรียบเทียบจริง — จำกัดเพื่อประหยัด quota
SEARCH_CHANNEL_IDS = [
    "UCrFDdD-EE05N7gjwZho2wqw",  # ThaiRath News
    "UCtc9-CS_FIZ7GGrm8--wsrQ",  # ThaiRath Variety
    "UC6x41swVZP3rEmy-ODxLMFA",  # ข่าวช่อง8
    "UCtBu8Wb2BUoduUXJS9Uss7Q",  # ช่อง8 Thai Ch8
    "UCq2_AaNWBd0kxzR1HL2yhsw",  # terodigital
    "UC7FCQJFK1sfwD_uobB45Xng",  # PPTV HD 36
    "UCk1v3FzlMu3r34LYgoHpH2w",  # THE STANDARD
    "UCMtFuOVbM_T43hYLnRA4MEA",  # Ejan : อีจัน
]

def get_live_from_search():
    """Search API eventType=live per-channel (100 units/call) เฉพาะช่องหลัก.
    Search ระดับ global (regionCode=TH) คืน 0 เสมอ — ต้อง per-channel ถึง reliable.
    จำกัดช่องเพื่อประหยัด quota; เรียกทุก 2 ชม ผ่าน throttle ใน main."""
    wanted = {c["id"]: c["name"] for c in CHANNELS}
    hits = []
    for n_done, ch_id in enumerate(SEARCH_CHANNEL_IDS):
        if ch_id not in wanted:
            continue
        if not any_key_alive():
            print(f"  ⛔ หยุด live-search — key หมดกลางคัน (ทำไป {n_done} ช่อง)")
            break
        if n_done:
            time.sleep(1.0)  # search หนัก — เว้นจังหวะกัน 429 จาก QPS
        result = yt_api("search", {
            "part": "snippet",
            "channelId": ch_id,
            "eventType": "live",
            "type": "video",
            "maxResults": 10,
        })
        for item in result.get("items", []):
            vid = item["id"].get("videoId")
            if vid:
                hits.append({
                    "video_id": vid,
                    "title": item["snippet"].get("title", ""),
                    "channel_id": ch_id,
                    "channel_name": wanted[ch_id],
                })
    return hits


def check_if_live(video_ids_list):
    """Check which videos are currently live using videos.list (1 unit/call).

    ป้องกันข้อมูลหาย (แก้ถาวร 2026-08-07):
      - เรียง video ตาม last_viewers มาก→น้อย ก่อนแบ่ง batch
        → ถ้า quota ตายกลางคัน live ตัวใหญ่ (คนดูหลักหมื่น) ถูกเก็บไปแล้ว
      - ถ้า batch ไหน fail → retry ทีละตัวเฉพาะ stream ตัวใหญ่ (>500 คนดู)
        1 unit/ตัว ถูกมาก คุ้มกว่าปล่อยข้อมูล peak หาย
    """
    if not video_ids_list:
        return []

    state = load_state()
    _streams = state.get("streams", {})

    def _last_v(v):
        return _streams.get(v["video_id"], {}).get("last_viewers", 0) or 0

    # ตัวใหญ่ก่อนเสมอ — quota ตายกลางคันก็ยังได้ข้อมูลที่สำคัญที่สุด
    video_ids_list = sorted(video_ids_list, key=_last_v, reverse=True)

    # Batch: YouTube API max 50 IDs per call
    all_items = []
    failed_ids = []
    for i in range(0, len(video_ids_list), 50):
        batch = video_ids_list[i:i+50]
        if i:
            time.sleep(0.3)  # กันยิงรัวจน YouTube ตอบ 429
        ids_str = ",".join(v["video_id"] for v in batch)
        result = yt_api("videos", {
            "part": "snippet,liveStreamingDetails",
            "id": ids_str,
        })
        if not result:
            failed_ids.extend(batch)
            continue
        all_items.extend(result.get("items", []))

    # Rescue pass: batch พังแต่ stream ตัวใหญ่ห้ามหาย → ยิงทีละตัว (1 unit)
    # แต่ถ้าทุก key ตายอยู่แล้ว การยิงต่อไม่มีทางสำเร็จ — เสียเวลา + log ท่วม
    rescue = [v for v in failed_ids if _last_v(v) >= 500]
    if rescue and not any_key_alive():
        print(f"⛔ ข้าม rescue {len(rescue)} stream — ทุก key ตายอยู่ ({key_health_report()})")
        rescue = []
    if rescue:
        print(f"🛟 rescue: batch fail — ยิงทีละตัว {len(rescue)} stream ใหญ่")
        for v in rescue:
            if not any_key_alive():
                print(f"  ⛔ key หมดกลางคัน — หยุด rescue (เหลือ {len(rescue) - rescue.index(v)} ตัว)")
                break
            r = yt_api("videos", {
                "part": "snippet,liveStreamingDetails",
                "id": v["video_id"],
            })
            if r.get("items"):
                all_items.extend(r["items"])
            else:
                print(f"  ✖ rescue fail: {v['video_id']} ({_last_v(v)} viewers ล่าสุด)")
    if failed_ids and not rescue:
        print(f"⚠️ {len(failed_ids)} video ไม่ถูก poll รอบนี้ (batch fail, ไม่มีตัวใหญ่)")

    channel_lookup = {v["video_id"]: v for v in video_ids_list}
    live_streams = []
    # เก็บว่า API ยืนยันตัวไหน "จบจริง" (มี actualEndTime) — ใช้มาร์ก ended แบบมั่นใจ
    confirmed_ended = set()
    for item in all_items:
        live_details = item.get("liveStreamingDetails", {})
        snippet = item.get("snippet", {})
        vid = item["id"]

        concurrent = live_details.get("concurrentViewers")
        actual_end = live_details.get("actualEndTime")
        broadcast = snippet.get("liveBroadcastContent")

        if actual_end:
            # จบจริงแล้ว — YouTube บางทียังคืน concurrentViewers เก่าค้างอยู่หลังจบ
            # ทำให้ ghost stream กลับมา live ตลอด (บั๊ก HN-WTZiCuSA). จบแล้ว = ไม่เป็น live
            confirmed_ended.add(vid)
            continue

        # PREMIERE / NON-LIVE DETECTION:
        # A YouTube Premiere sets liveBroadcastContent="live" during the event, but the
        # Data API NEVER returns concurrentViewers for a premiere (only real live
        # broadcasts have that field, even "0"). So concurrentViewers absent + still
        # "live" + not ended ⇒ premiere, or a brand-new unconfirmed live.
        #   - Already polled with real viewers (last_viewers > 0) ⇒ it's a real live;
        #     hold the last known value while its viewer count briefly blanks.
        #   - Otherwise (premiere, or new live with no viewers yet) ⇒ skip ENTIRELY.
        #     Do NOT record 0 and do NOT add to state — premieres have no live viewers
        #     and would pollute the ranking/summary/dashboard with fake rows. A real
        #     live is picked up next tick once concurrentViewers appears.
        if concurrent is None and broadcast == "live" and actual_end is None:
            last = state.get("streams", {}).get(vid, {}).get("last_viewers")
            if last and last > 0:
                concurrent = last
                print(f"⚠️ {vid}: concurrentViewers missing, holding last known {last}")
            else:
                print(f"🎬 {vid}: Premiere (no concurrentViewers) — not a real live. Skipped.")
                continue

        if concurrent is not None:
            title = snippet.get("title", "")
            # FULL / REPLAY / PREMIERE FILTER:
            # YouTube sometimes returns concurrentViewers>0 for a full-replay or
            # premiere-styled VOD that is NOT a real live broadcast. These pollute
            # the ranking/summary/dashboard with fake rows. Drop them by title pattern.
            _JUNK = ("FULL", "REPLAY", "PREMIERE", "Premiere", "Replay", "full", "replay", "premiere")
            if any(j in title for j in _JUNK):
                print(f"🗑️ {vid}: non-live VOD ('{title[:40]}') — skipped.")
                continue
            ch_info = channel_lookup.get(vid, {"channel_name": "Unknown", "channel_id": ""})
            live_streams.append({
                "video_id": vid,
                "title": snippet.get("title", ""),
                "concurrent_viewers": int(concurrent),
                "actual_start": live_details.get("actualStartTime", ""),
                "scheduled_start": live_details.get("scheduledStartTime", ""),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "channel_name": ch_info["channel_name"],
                "channel_id": ch_info["channel_id"],
            })

    live_streams.sort(key=lambda x: x["concurrent_viewers"], reverse=True)
    # api_ok = รอบนี้เก็บข้อมูลได้ครบไหม
    # ต้องเป็น False ถ้ามี batch ไหนพัง — ไม่งั้น stream ใน batch ที่พังจะโดนนับ missed
    # ทั้งที่เราแค่ "มองไม่เห็น" ไม่ใช่ "มันหายไปจริง"
    unrecovered = {v["video_id"] for v in failed_ids} - {i["id"] for i in all_items}
    api_ok = not unrecovered
    if unrecovered:
        print(f"⚠️ api_ok=False — {len(unrecovered)} stream มองไม่เห็นรอบนี้ (ไม่นับเป็น missed)")
    return live_streams, confirmed_ended, api_ok


# ─── State Management (peak tracking) ───

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"streams": {}, "last_daily_summary": ""}


def save_state(state):
    """เขียน state ลงดิสก์ + flush key health เข้าไปด้วย.

    เขียนทับ in-place (ไม่ใช้ tmp+rename) เพราะ STATE_FILE เป็น Docker
    bind-mount ไฟล์เดี่ยว — os.replace() จะพังด้วย EBUSY
    """
    if _HEALTH_CACHE is not None:
        state["_key_health"] = _HEALTH_CACHE
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_stream_state(state, live_streams, cron_now, api_ok=True, confirmed_ended=None):
    """Update peak viewers for each tracked stream.

    การมาร์ก ended (แก้ถาวร 2026-08-07):
      บั๊กเดิม — poll พลาดเพราะ 429/quota → หายจาก current_ids → ครบ 10 นาที
      ระบบมาร์ก ended:True → ตัดออกจาก polling **ถาวร** ทั้งที่ยัง live อยู่
      (x37jys4xbDw คนดู 12,800 ถูกตัดทิ้งตอน 16:40)

    กติกาใหม่:
      1. ended ทันที เฉพาะเมื่อ API ยืนยัน actualEndTime (confirmed_ended) — แม่นยำ 100%
      2. ถ้าแค่ "ไม่เจอ" → ต้อง api_ok (รอบนั้น API ทำงานปกติ) และหายติดกัน
         >= MISS_TICKS_TO_END ticks ถึงจะมาร์ก — รอบที่ API พังไม่นับเป็น miss
      3. stream ที่เคย ended แล้วโผล่มา live อีก → ปลุกคืน (ended=False)
    """
    now_str = cron_now.strftime("%Y-%m-%d %H:%M:%S")
    current_ids = {s["video_id"] for s in live_streams}
    confirmed_ended = confirmed_ended or set()
    MISS_TICKS_TO_END = 6  # 6 tick × 5 นาที = 30 นาที ของการหายจริง

    for stream in live_streams:
        vid = stream["video_id"]
        if vid not in state["streams"]:
            state["streams"][vid] = {
                "title": stream["title"],
                "channel": stream["channel_name"],
                "url": stream["url"],
                "peak_viewers": stream["concurrent_viewers"],
                "first_seen": now_str,
                "actual_start": stream.get("actual_start", ""),
                "last_viewers": stream["concurrent_viewers"],
                "last_seen": now_str,
                "samples": [stream["concurrent_viewers"]],
            }
        else:
            existing = state["streams"][vid]
            if stream["concurrent_viewers"] > existing["peak_viewers"]:
                existing["peak_viewers"] = stream["concurrent_viewers"]
            existing["last_viewers"] = stream["concurrent_viewers"]
            existing["last_seen"] = now_str
            existing["samples"].append(stream["concurrent_viewers"])
            if len(existing["samples"]) > 300:
                existing["samples"] = existing["samples"][-300:]
            # ปลุกคืน: เคยถูกมาร์ก ended ผิดๆ แต่ยัง live จริง
            if existing.get("ended"):
                print(f"🔁 resurrect: {vid} ({existing.get('title','')[:40]}) ยัง live อยู่ — ยกเลิก ended")
                existing["ended"] = False
                existing.pop("end_time", None)
        state["streams"][vid]["missed"] = 0

    # Mark ended
    for vid in list(state["streams"].keys()):
        if vid in current_ids:
            continue
        existing = state["streams"][vid]
        if existing.get("ended"):
            continue
        if vid in confirmed_ended:
            existing["ended"] = True
            existing["end_time"] = existing.get("last_seen", now_str)
            print(f"🏁 {vid} จบจริง (API ยืนยัน actualEndTime)")
            existing["ended_confirmed"] = True
            continue
        if not api_ok:
            # รอบนี้ API พัง — ไม่นับเป็นการหาย ห้ามมาร์ก ended
            continue
        existing["missed"] = existing.get("missed", 0) + 1
        if existing["missed"] >= MISS_TICKS_TO_END:
            existing["ended"] = True
            existing["end_time"] = existing.get("last_seen", now_str)

    return state


# ─── Daily Summary ───

def generate_daily_summary(state, cron_now):
    """Generate daily summary rows + peak summary for ended streams (once per day).
    Returns (summary_rows, peak_rows).
    """
    today = cron_now.strftime("%Y-%m-%d")
    if state["last_daily_summary"] == today:
        return [], []

    rows = []
    peak_rows = []
    for vid, s in state["streams"].items():
        if not s.get("ended"):
            continue

        duration_min = ""
        if s.get("actual_start") and s.get("end_time"):
            try:
                start = datetime.fromisoformat(s["actual_start"].replace("Z", "+00:00"))
                end = datetime.strptime(s["end_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ICT)
                duration_min = int((end - start).total_seconds() / 60)
            except Exception:
                pass

        samples = s.get("samples", [])
        avg_viewers = sum(samples) / max(len(samples), 1)

        # Daily_Summary tab: tech format with video ID + duration
        rows.append([
            today,
            vid,
            s.get("title", "")[:100],
            s["peak_viewers"],
            int(avg_viewers),
            s.get("actual_start", "")[:19],
            s.get("end_time", ""),
            duration_min,
            s.get("url", ""),
        ])

        # Peak_Viewers tab: clean summary — no video ID, easier to read
        # Use first_seen (when we detected viewers) instead of actual_start (YouTube stream start time)
        peak_rows.append([
            today,
            s.get("title", "")[:80],
            s.get("channel", ""),
            s["peak_viewers"],
            int(avg_viewers),
            s.get("first_seen", "")[:19],
            s.get("end_time", ""),
            s.get("url", ""),
        ])

    return rows, peak_rows


# ─── Google Sheets ───

def sheets_append(tab_name, rows):
    """Append rows to a Google Sheets tab via GAPI script."""
    if not rows:
        return
    if not SHEET_ID:
        return  # Sheets ไม่ใช้แล้ว — JSONL เป็น database หลัก

    values_json = json.dumps(rows)
    col = "F" if tab_name == "Raw" else ("H" if tab_name == "Peak_Viewers" else "I")
    range_str = f"{tab_name}!A:{col}"

    cmd = [sys.executable, GAPI_SCRIPT, "sheets", "append",
           SHEET_ID, range_str, "--values", values_json]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"⚠️ Sheets append failed: {result.stderr.strip()}")
        else:
            print(f"✅ Appended {len(rows)} rows to {tab_name}")
    except Exception as e:
        print(f"⚠️ Sheets append error: {e}")


def sheets_update(tab_name, range_str, values):
    """Update specific cells in Google Sheets."""
    if not SHEET_ID:
        return  # Sheets ไม่ใช้แล้ว — JSONL เป็น database หลัก
    values_json = json.dumps(values)
    cmd = [sys.executable, GAPI_SCRIPT, "sheets", "update",
           SHEET_ID, f"{tab_name}!{range_str}", "--values", values_json]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"⚠️ Sheets update failed: {result.stderr.strip()}")
        else:
            print(f"✅ Updated {tab_name}!{range_str}")
    except Exception as e:
        print(f"⚠️ Sheets update error: {e}")


def sheets_sort_by_start_time(tab_name, time_col_index=5):
    """Sort tab by Start_Time column (parse datetime, not string sort)."""
    if not SHEET_ID:
        return  # Sheets ไม่ใช้แล้ว — JSONL เป็น database หลัก
    range_str = f"{tab_name}!A:H"
    cmd = [sys.executable, GAPI_SCRIPT, "sheets", "get", SHEET_ID, range_str]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"⚠️ Sheets get failed: {result.stderr.strip()}")
            return
        
        rows = json.loads(result.stdout)
        if len(rows) <= 1:
            return
        
        header = rows[0]
        data = rows[1:]
        
        # Parse Start_Time for sorting
        def parse_start(row):
            if len(row) <= time_col_index:
                return datetime.min
            ts = row[time_col_index].strip()
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']:
                try:
                    return datetime.strptime(ts, fmt)
                except:
                    pass
            return datetime.min
        
        data.sort(key=parse_start)
        sorted_rows = [header] + data
        
        values_json = json.dumps(sorted_rows, ensure_ascii=False)
        cmd2 = [sys.executable, GAPI_SCRIPT, "sheets", "update",
                SHEET_ID, f"{tab_name}!A:H", "--values", values_json]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
        if result2.returncode != 0:
            print(f"⚠️ Sort update failed: {result2.stderr.strip()}")
        else:
            print(f"✅ Sorted {tab_name} by Start_Time")
    except Exception as e:
        print(f"⚠️ Sort error: {e}")


def setup_sheet_tabs():
    """Ensure tabs exist with headers."""
    if not SHEET_ID:
        return  # Sheets ไม่ใช้แล้ว — JSONL เป็น database หลัก
    sheets_update("Raw", "A1:F1",
                  [["Timestamp", "Video_ID", "Title", "Concurrent_Viewers", "Channel", "URL"]])
    sheets_update("Daily_Summary", "A1:I1",
                  [["Date", "Video_ID", "Title", "Peak_Viewers", "Avg_Viewers",
                     "Start_Time", "End_Time", "Duration_Min", "URL"]])
    sheets_update("Peak_Viewers", "A1:H1",
                  [["Date", "Program", "Channel", "Peak_Viewers", "Avg_Viewers",
                     "Start_Time", "End_Time", "URL"]])


# ─── Local JSONL store (for dashboard) ───
JSONL_FILE = os.environ.get("LIVE_JSONL",
    "/opt/data/projects/yt-live-monitor/live_data.jsonl")

def append_local_jsonl(live_streams, now):
    """Append live samples to local JSONL — dashboard reads this directly.

    Dedupe (แก้ 2026-08-07): ถ้า tick ปกติกับ manual/grace run ชนกันที่ ts เดียวกัน
    จะได้แถวซ้ำ video_id+ts → dashboard นับซ้ำ. อ่านท้ายไฟล์มาเช็กก่อนเขียน
    (อ่านแค่ 256KB สุดท้าย = ~15 ticks พอครอบคลุมการชนกันในรอบเดียวกัน)
    """
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    seen = set()
    try:
        with open(JSONL_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - 262144)
            f.seek(start)
            chunk = f.read().decode("utf-8", "ignore").split("\n")
            # ตัดบรรทัดแรกทิ้งเฉพาะตอน seek ข้ามมาจริง (อาจเป็นบรรทัดขาดครึ่ง)
            if start > 0:
                chunk = chunk[1:]
            for line in chunk:
                if not line.strip() or ts not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("ts") == ts:
                    seen.add(d.get("video_id"))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ dedupe scan error: {e}")

    try:
        with open(JSONL_FILE, "a") as f:
            skipped = 0
            for s in live_streams:
                if s["video_id"] in seen:
                    skipped += 1
                    continue
                f.write(json.dumps({
                    "ts": ts,
                    "video_id": s["video_id"],
                    "title": s["title"][:100],
                    "viewers": s["concurrent_viewers"],
                    "channel": s["channel_name"],
                    "url": s["url"],
                    "actual_start": s.get("actual_start", ""),
                }, ensure_ascii=False) + "\n")
        if skipped:
            print(f"⏭️ dedupe: ข้าม {skipped} แถวซ้ำที่ ts {ts}")
    except Exception as e:
        print(f"⚠️ JSONL write error: {e}")


# ─── Main ───

def main():
    if not API_KEYS and not DEMO_MODE:
        print("⚠️ YOUTUBE_API_KEY / YOUTUBE_API_KEYS not set")
        sys.exit(1)
    # SHEET_ID ไม่บังคับแล้ว — ถ้าไม่ตั้ง = ไม่ export Sheets (JSONL เป็น database หลัก)
    # sheets_append/update มี guard ข้ามเองอยู่แล้ว

    now = floor_5min(datetime.now(ICT))
    print(f"🔍 YT Live Monitor — {now.strftime('%Y-%m-%d %H:%M:%S')} ICT")
    print(f"🔑 keys: {key_health_report()} (budget เหลือ ~{quota_budget_left()}u)")

    # 1. Discover from RSS
    rss_videos = get_live_from_rss()
    print(f"📡 RSS: found {len(rss_videos)} recent videos")

    # 1a. Live-Search layer — ตัดสินใจตอนนี้ แต่ "รันทีหลัง" (หลัง polling เสร็จ)
    #     เหตุผล (แก้ 2026-08-07): search = 100 units/ช่อง ยิงก่อน polling ทำให้ key
    #     โดน rate-limit ตั้งแต่ยังไม่ได้เก็บข้อมูลเลย → งานหลักพังเพราะงานเสริม
    #     ลำดับที่ถูก: เก็บข้อมูล (งานหลัก, 1 unit/batch) ก่อนเสมอ แล้วค่อย discover
    state_pre = load_state()
    last_search = state_pre.get("last_live_search_ts", "")
    do_search = False
    if last_search:
        try:
            from datetime import datetime as _dt
            last_dt = _dt.strptime(last_search, "%Y-%m-%d %H:%M:%S")
            do_search = (now - last_dt).total_seconds() >= 7200  # 2 ชม
        except Exception:
            do_search = True
    else:
        do_search = True
    if not do_search and last_search:
        print(f"  ⏳ live-search skip (รันครั้งล่าสุด {last_search})")

    # 1b. รวม stream จาก state ที่ยังไม่ ended (กันหลุดจาก RSS — RSS คืนแค่ ~15 ตัว)
    rss_ids = {v["video_id"] for v in rss_videos}
    ch_lookup = {c["id"]: c["name"] for c in CHANNELS}
    for vid, s in state_pre.get("streams", {}).items():
        if vid in rss_ids:
            continue
        # ended ที่ API ยืนยันแล้ว → เลิก poll จริง
        # ended จาก miss-count → poll ต่ออีก 2 ชม (grace) เผื่อมาร์กผิดจาก quota
        if s.get("ended"):
            if s.get("ended_confirmed"):
                continue
            try:
                et = datetime.strptime(s.get("end_time", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ICT)
                if (now - et).total_seconds() > 7200:
                    continue
            except Exception:
                continue
            print(f"🩺 grace-poll: {vid} ({s.get('title','')[:35]}) — ended แบบไม่ยืนยัน ตรวจซ้ำ")
        # หา channel_id จาก name
        ch_id = next((c["id"] for c in CHANNELS if c["name"] == s.get("channel")), "")
        rss_videos.append({
            "video_id": vid,
            "title": s.get("title", ""),
            "channel_id": ch_id,
            "channel_name": s.get("channel", "Unknown"),
        })
        print(f"📌 state-persist: {vid} ({s.get('title','')[:40]}) — not in RSS, still polling")

    # 2. Check which are live — งานหลัก ทำก่อนเสมอ (1 unit/50 videos)
    live_streams, confirmed_ended, api_ok = check_if_live(rss_videos)

    # 2b. Live-Search layer — รันหลัง polling เสร็จ (100 units/ช่อง)
    #     ต้องมาหลัง เพราะถ้ามาก่อนแล้วโดน rate-limit งานหลักจะไม่ได้ทำเลย
    if do_search:
        need = len(SEARCH_CHANNEL_IDS) * 100
        left = quota_budget_left()
        if not any_key_alive():
            print("  ⛽ skip live-search — ไม่มี key ที่ใช้ได้ตอนนี้")
        elif left < need + POLL_RESERVE_UNITS:
            print(f"  ⛽ skip live-search — quota เหลือ {left}u ต้องกัน {POLL_RESERVE_UNITS}u ให้ polling")
        else:
            search_videos = get_live_from_search()
            print(f"🔎 live-search: found {len(search_videos)} live ในช่องหลัก")
            known = {v["video_id"] for v in rss_videos}
            new = [v for v in search_videos if v["video_id"] not in known]
            if new:
                print(f"  ⊕ พบ {len(new)} live ที่ RSS ไม่เจอ — poll เพิ่ม")
                extra, extra_ended, extra_ok = check_if_live(new)
                live_streams.extend(extra)
                confirmed_ended |= extra_ended
                api_ok = api_ok and extra_ok
                live_streams.sort(key=lambda x: x["concurrent_viewers"], reverse=True)
            state_pre["last_live_search_ts"] = now.strftime("%Y-%m-%d %H:%M:%S")
            save_state(state_pre)

    if not live_streams:
        print("ℹ️ No live streams right now — silent exit")
        state = load_state()
        update_stream_state(state, [], now, api_ok=api_ok, confirmed_ended=confirmed_ended)
        summary_rows, peak_rows = generate_daily_summary(state, now)
        if summary_rows:
            setup_sheet_tabs()
            sheets_append("Daily_Summary", summary_rows)
            sheets_append("Peak_Viewers", peak_rows)
            sheets_sort_by_start_time("Peak_Viewers")
            sheets_sort_by_start_time("Daily_Summary")
            state["streams"] = {vid: s for vid, s in state["streams"].items()
                                if not s.get("ended")}
            state["last_daily_summary"] = now.strftime("%Y-%m-%d")
        save_state(state)
        return

    total = sum(s["concurrent_viewers"] for s in live_streams)
    print(f"🔴 {len(live_streams)} live, {total:,} total viewers")
    for s in live_streams:
        print(f"  • {s['title'][:80]} — {s['concurrent_viewers']:,} viewers ({s['channel_name']})")

    # 3. Update state
    state = load_state()
    update_stream_state(state, live_streams, now, api_ok=api_ok, confirmed_ended=confirmed_ended)

    # 4. Append raw data
    raw_rows = []
    for s in live_streams:
        raw_rows.append([
            now.strftime("%Y-%m-%d %H:%M:%S"),
            s["video_id"],
            s["title"][:100],
            s["concurrent_viewers"],
            s["channel_name"],
            s["url"],
        ])
    sheets_append("Raw", raw_rows)

    # 4b. Append to local JSONL for dashboard (fast, no API needed)
    append_local_jsonl(live_streams, now)

    # 5. Daily summary if streams ended
    summary_rows, peak_rows = generate_daily_summary(state, now)
    if summary_rows:
        # Ensure Peak_Viewers tab exists (headers written once)
        setup_sheet_tabs()
        sheets_append("Daily_Summary", summary_rows)
        sheets_append("Peak_Viewers", peak_rows)
        sheets_sort_by_start_time("Peak_Viewers")
        sheets_sort_by_start_time("Daily_Summary")
        state["streams"] = {vid: s for vid, s in state["streams"].items()
                            if not s.get("ended")}
        state["last_daily_summary"] = now.strftime("%Y-%m-%d")

    # 6. Save
    save_state(state)


if __name__ == "__main__":
    main()
