#!/usr/bin/env python3
"""YT Live Monitor — standalone dashboard (extracted from Hermes dashboard 2026-08-03).

Routes:
  /                → redirect to /live-monitor
  /live-monitor    → dashboard HTML
  /api/live-data   → JSON grouped by channel/stream (for Chart.js)
  /api/slot-compare → Peak viewers per program per day
  /api/ping        → health check

Config (env):
  PORT        — default 8899
  LIVE_JSONL  — path to live_data.jsonl (default: ../live_data.jsonl relative to repo root)
"""
import os
import re
import json
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request, redirect

app = Flask(__name__, static_folder='.')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # no cache

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_JSONL = os.environ.get(
    "LIVE_JSONL",
    os.path.join(HERE, "..", "live_data.jsonl"),
)
VIEWS_JSONL = os.environ.get(
    "VIEWS_JSONL",
    os.path.join(HERE, "..", "views_data.jsonl"),
)
VIEWS_LIVE_JSONL = os.environ.get(
    "VIEWS_LIVE_JSONL",
    os.path.join(HERE, "..", "views_live.jsonl"),
)


@app.route("/api/ping")
def api_ping():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


# ── Slot comparison: ข่าวเช้า / เที่ยง / เย็น / Primetime วันต่อวัน ──
SLOTS = [
    {"name": "Live ข่าวเช้า", "programs": [
        {"name": "เรื่องเล่าเช้านี้ · เรื่องเล่าเช้านี้", "channel": "เรื่องเล่าเช้านี้", "kw": ["เรื่องเล่าเช้านี้", "เรื่องเล่าหน้าหนึ่ง", "เรื่องเล่าเสาร์-อาทิตย์"]},
        {"name": "Workpoint 23 · ข่าวเช้าเวิร์คพอยท์", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ข่าวเวิร์คพอยท์", "ข่าวเช้า"]},
        {"name": "ข่าวช่อง8 · คุยข่าวเช้า", "channel": "ข่าวช่อง8", "kw": ["คุยข่าวเช้า"]},
        {"name": "ThaiRath News", "channel": "ThaiRath News", "kw": ["ข่าวเช้าหัวเขียว", "ห้องข่าวหัวเขียว"]},
        {"name": "Ch7HD · เช้านี้ที่หมอชิต", "channel": "Ch7HDNews", "kw": ["เช้านี้ที่หมอชิต", "สนามข่าว"]},
        {"name": "Thai PBS · วันใหม่ไทยพีบีเอส", "channel": "Thai PBS", "kw": ["วันใหม่"]},
    ]},
    {"name": "ข่าวเย็น (16:00)", "programs": [
        {"name": "ThaiRath News · ข่าวเย็นไทยรัฐ", "channel": "ThaiRath News", "kw": ["ข่าวเย็นไทยรัฐ", "ไทยรัฐทันข่าว"]},
        {"name": "ข่าวช่อง8 · คุยข่าวเย็น", "channel": "ข่าวช่อง8", "kw": ["คุยข่าวเย็น"]},
        {"name": "Workpoint 23 · ชงข่าวเขย่าจอ", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ชงข่าวเขย่าจอ", "ชงข่าว เขย่าLIVE"]},
    ]},
    {"name": "Live ข่าวเที่ยง", "programs": [
        {"name": "ครอบครัวข่าว3 · เที่ยงวันทันเหตุการณ์", "channel": "ครอบครัวข่าว3", "kw": ["เที่ยงวันทันเหตุการณ์"]},
        {"name": "แนวหน้าออนไลน์ · แนวหน้าข่าวเที่ยง", "channel": "แนวหน้าออนไลน์", "kw": ["แนวหน้าข่าวเที่ยง"]},
        {"name": "ThaiRath News · ข่าวเที่ยงไทยรัฐ", "channel": "ThaiRath News", "kw": ["ข่าวเที่ยงไทยรัฐ"]},
        {"name": "ข่าวช่อง8 · ข่าวใหญ่ช่อง8", "channel": "ข่าวช่อง8", "kw": ["ข่าวใหญ่ช่อง8"]},
        {"name": "Workpoint 23 · ข่าวเที่ยงเวิร์คพอยท์", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ข่าวเที่ยงเวิร์คพอยท์"]},
        {"name": "Ch7HD · ห้องข่าวภาคเที่ยง", "channel": "Ch7HDNews", "kw": ["ห้องข่าวภาคเที่ยง"]},
    ]},
    {"name": "Live ข่าวค่ำ", "programs": [
        {"name": "ข่าวช่อง8 · ลุยชนข่าว", "channel": "ข่าวช่อง8", "kw": ["ลุยชนข่าว"]},
        {"name": "ThaiRath News · ไทยรัฐนิวส์โชว์", "channel": "ThaiRath News", "kw": ["ไทยรัฐนิวส์โชว์"]},
        {"name": "Amarin TV · ทุบโต๊ะข่าว", "channel": "Amarin TV", "kw": ["ทุบโต๊ะข่าว"]},
        {"name": "TOP NEWS LIVE · ข่าวภาคค่ำ", "channel": "TOP NEWS LIVE", "kw": ["Live ภาคค่ำ"]},
    ]},
    {"name": "Live Report", "programs": [
        {"name": "PPTV HD 36 · Live Report", "channel": "PPTV HD 36", "kw": ["Live Report"]},
        {"name": "ThaiRath News · สดไทยรัฐ", "channel": "ThaiRath News", "kw": ["สดไทยรัฐ"]},
        {"name": "ข่าวช่อง8 · สดสด", "channel": "ข่าวช่อง8", "kw": ["สดสด"]},
        {"name": "Amarin TV · สดอมรินทร์", "channel": "Amarin TV", "kw": ["สดอมรินทร์"]},
        {"name": "โหนกระแส · Live", "channel": "โหนกระแส", "kw": ["Live "]},
    ]},
    {"name": "รายการ Talk", "programs": [
        {"name": "ThaiRath News · NEWSROOM", "channel": "ThaiRath News", "kw": ["NEWSROOM", "นิวส์รูม"]},
        {"name": "ThaiRath News · เปิดปาก", "channel": "ThaiRath News", "kw": ["เปิดปาก"]},
        {"name": "terodigital · ถกไม่เถียง", "channel": "terodigital", "kw": ["ถกไม่เถียง"]},
        {"name": "ช่อง8 Thai Ch8 · คนดังนั่งเคลียร์", "channel": "ช่อง8 Thai Ch8", "kw": ["คนดังนั่งเคลียร์"]},
    ]},
]


def clean_video_title(title):
    """ตัด prefix (LIVE/ถ่ายทอดสด) และ suffix (| เดท) เหลือชื่อหลักของโปรแกรม"""
    if not title:
        return title
    t = title.strip()
    # ถอดคำ prefix LIVE หลายรูปแบบ + ถ่ายทอดสด
    t = re.sub(r"(?i)^\s*(🔴)?\s*LIVE+!*\s*[:：]?\s*", "", t)
    t = re.sub(r"(?i)^🔴\s*\[?Live\]?\s*[:：]?\s*", "", t)
    t = re.sub(r"^(ถ่ายทอดสด|ถ่ายทอดสด LIVE)\s*[:：]?\s*", "", t)
    # ตัด "| เดท" (อังกฤษ) หรือ "วันที่ X ..." (ไทย)
    if "|" in t:
        t = t.split("|")[0].strip()
    t = re.sub(r"\s*[|｜].*$", "", t)
    t = re.sub(r"\s*[-–]?\s*วันที่?\s*\d{1,2}\s*(เดือน|มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|[ก-ฮ]{1,8})\s*\d{2,4}.*$", "", t)
    t = re.sub(r"\s*\|\s*\d{1,2}\s*\w*\.?\s*(ก.ค.|ส.ค.|ก.ย.|ต.ค.|พ.ย.|ธ.ค.|ม.ค.|ก.พ.|มี.ค.|เม.ย.|พ.ค.|มิ.ย.|ก.ค.).*$", "", t)
    t = t.strip(" :#[]()")
    return t or title


@app.route("/api/slot-compare")
def api_slot_compare():
    """Peak viewers per program per day — วันต่อวัน สำหรับเทียบข่าวแต่ละช่วงเวลา"""
    def parse_ts(ts):
        if not ts:
            return None
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                date_part, time_part = ts.split(" ", 1)
                y, m, d = date_part.split("-")
                hh, mm, ss = time_part.split(":")
                return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss))
            except Exception:
                return None

    # stream key (ch, vid) → {title, channel, date, peak}
    streams = {}
    try:
        with open(LIVE_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                dt = parse_ts(d.get("ts", ""))
                if not dt:
                    continue
                key = (d.get("channel", "Unknown"), d.get("video_id", ""))
                s = streams.get(key)
                if s is None:
                    s = streams[key] = {
                        "title": d.get("title", ""),
                        "channel": key[0],
                        "date": dt.strftime("%Y-%m-%d"),
                        "peak": 0,
                        "start": dt,
                        "end": dt,
                        "points": [],
                    }
                v = d.get("viewers")
                v = v if isinstance(v, (int, float)) else 0
                if v > s["peak"]:
                    s["peak"] = v
                if dt < s["start"]:
                    s["start"] = dt
                if dt > s["end"]:
                    s["end"] = dt
                s["points"].append((d["ts"], v))

        # PREMIERE FILTER: a premiere never has live concurrentViewers, so its captured
        # rows are all 0 → peak==0. Drop them so premieres never show in slot comparison.
        streams = {k: s for k, s in streams.items() if s["peak"] > 0}
    except FileNotFoundError:
        return jsonify({"slots": [], "last_ts": ""})

    result = []
    for slot in SLOTS:
        progs = []
        for prog in slot["programs"]:
            days = {}
            latest_title = None
            latest_end = None
            for (ch_key, vid_key), s in streams.items():
                # Live Report / หมวดที่ match ตาม video ID ตรงๆ (เหตุการณ์เดียว ต่างช่อง)
                if prog.get("vids"):
                    if vid_key not in prog["vids"]:
                        continue
                else:
                    if s["channel"] != prog["channel"]:
                        continue
                    if not any(k in s["title"] for k in prog["kw"]):
                        continue
                # track วิดีโอล่าสุด (end หลังสุด) ของโปรแกรมนี้ → ใช้ title เป็นชื่อแสดง
                if latest_end is None or s["end"] > latest_end:
                    latest_end = s["end"]
                    latest_title = s["title"]
                e = days.get(s["date"])
                if e is None:
                    e = days[s["date"]] = {
                        "peak": s["peak"],
                        "start": s["start"].strftime("%H:%M"),
                        "end": s["end"].strftime("%H:%M"),
                        "curve": {},
                    }
                else:
                    e["peak"] = max(e["peak"], s["peak"])
                    if s["start"].strftime("%H:%M") < e["start"]:
                        e["start"] = s["start"].strftime("%H:%M")
                    if s["end"].strftime("%H:%M") > e["end"]:
                        e["end"] = s["end"].strftime("%H:%M")
                # per-day concurrent curve: sum viewers ของทุก stream ที่ match ตาม HH:MM
                for tv in s["points"]:
                    hhmm = tv[0].split(" ")[1][:5]
                    e["curve"][hhmm] = e["curve"].get(hhmm, 0) + tv[1]
            progs.append({
                "name": prog["name"],
                "live_title": clean_video_title(latest_title) if latest_title else prog["name"],
                "channel": prog["channel"],
                "kw": prog.get("kw", []),
                "vids": prog.get("vids", []),
                "days": {d: {**v, "curve": sorted([[k, c] for k, c in v["curve"].items()])}
                         for d, v in days.items()},
            })
        result.append({"name": slot["name"], "programs": progs})

    return jsonify({"slots": result})


@app.route("/api/live-data")
def api_live_data():
    """Read JSONL, group by channel → stream, return for Chart.js.
    ?date=YYYY-MM-DD filters to one day (local ts). Omit = all data."""
    from collections import defaultdict

    def parse_ts(ts):
        """Parse 'YYYY-MM-DD H:M:S' or 'YYYY-MM-DD HH:MM:SS' → datetime.
        ทนทั้ง zero-pad และไม่ pad (ข้อมูล backfill จาก Sheets ไม่ pad ชั่วโมง)."""
        if not ts:
            return None
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                date_part, time_part = ts.split(" ", 1)
                y, m, d = date_part.split("-")
                hh, mm, ss = time_part.split(":")
                return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss))
            except Exception:
                return None

    date_filter = request.args.get("date", "")
    streams = defaultdict(lambda: defaultdict(list))  # channel → video_id → [points]
    stream_meta = {}  # video_id → {title, channel, url, actual_start}
    last_dt = None
    total = 0
    available_dates = set()

    try:
        with open(LIVE_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts = d.get("ts", "")
                dt = parse_ts(ts)
                if dt:
                    available_dates.add(dt.strftime("%Y-%m-%d"))
                if date_filter:
                    if not dt or dt.strftime("%Y-%m-%d") != date_filter:
                        continue
                total += 1
                ch = d.get("channel", "Unknown")
                vid = d.get("video_id", "")
                streams[ch][vid].append({"ts": ts, "dt": dt, "viewers": d["viewers"]})
                stream_meta[vid] = {
                    "title": d.get("title", ""),
                    "channel": ch,
                    "url": d.get("url", ""),
                    "actual_start": d.get("actual_start", ""),
                }
                if dt and (last_dt is None or dt > last_dt):
                    last_dt = dt

    except FileNotFoundError:
        return jsonify({"channels": {}, "last_ts": "", "total_samples": 0, "dates": []})

    # "current" = stream มีข้อมูลใน 12 นาทีล่าสุดของเวลาจริง (cron เก็บทุก 5 นาที)
    # margin 12นาที > round 5นาที กัน false 0 LIVE ตอน collector delay
    now_naive_ict = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
    cutoff = now_naive_ict - timedelta(minutes=12)

    channels = {}
    for ch, vids in streams.items():
        ch_streams = []
        ch_peak = 0
        ch_current = 0
        for vid, points in vids.items():
            points.sort(key=lambda p: (p["dt"] or datetime.min))
            peak = max(p["viewers"] for p in points)
            # PREMIERE FILTER: a premiere never has live concurrentViewers → all
            # captured rows are 0 → peak==0. Skip so premieres never render on the
            # dashboard (defense-in-depth; collector already skips them).
            if peak == 0:
                total -= len(points)
                continue
            peak_pt = next(p for p in points if p["viewers"] == peak)
            last_pt = points[-1]
            is_live = bool(last_pt["dt"] and last_pt["dt"] >= cutoff)
            if is_live:
                ch_current = max(ch_current, last_pt["viewers"])
            ch_peak = max(ch_peak, peak)
            meta = stream_meta.get(vid, {})
            raw_title = meta.get("title", vid)
            ch_streams.append({
                "video_id": vid,
                "title": raw_title,
                "url": meta.get("url", ""),
                "actual_start": meta.get("actual_start", ""),
                "peak": peak,
                "peak_ts": peak_pt["ts"],
                "start_ts": points[0]["ts"],
                "end_ts": last_pt["ts"],
                "is_live": is_live,
                "points": [{"ts": p["ts"], "viewers": p["viewers"]} for p in points],
            })
        # Sort: live first, then by peak desc
        ch_streams.sort(key=lambda s: (not s["is_live"], -s["peak"]))
        channels[ch] = {
            "streams": ch_streams,
            "peak": ch_peak,
            "current": ch_current,
        }

    return jsonify({
        "channels": channels,
        "last_ts": last_dt.strftime("%Y-%m-%d %H:%M:%S") if last_dt else "",
        "total_samples": total,
        "date": date_filter,
        "dates": sorted(available_dates, reverse=True),
    })


@app.route("/live-monitor")
def live_monitor():
    try:
        with open(os.path.join(HERE, "live_monitor.html")) as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        return f"Dashboard error: {e}", 500


@app.route("/views-monitor")
def views_monitor():
    try:
        with open(os.path.join(HERE, "views_monitor.html")) as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        return f"Dashboard error: {e}", 500


@app.route("/api/views-month")
def api_views_month():
    """คลิปที่โพสต์ในเดือนล่าสุด (ตาม published_at ใน views_month.jsonl)
    + ยอดวิวสะสมล่าสุด (จาก snapshot views_live.jsonl ถ้ามี video_id นี้)
    ได้ทุกช่องรวมคู่แข่ง (พึ่ง Data API ไม่ใช่ CMS)"""
    import re as _re
    month_path = os.environ.get("VIEWS_MONTH_JSONL", "/data/views_month.jsonl")
    live_path = VIEWS_LIVE_JSONL

    def read_jsonl(path):
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    vids = read_jsonl(month_path)
    if not vids:
        return jsonify({"month": "", "videos": [], "note": "ยังไม่มี views_month.jsonl — รัน MODE=totals ก่อน"})

    # หาเดือนล่าสุดจาก published_at (รูปแบบ 2026-08-10T...)
    months = sorted({v.get("published_at", "")[:7] for v in vids if v.get("published_at")})
    if not months:
        return jsonify({"month": "", "videos": [], "note": "ไม่มี published_at ในข้อมูล"})
    latest_month = months[-1]

    # ยอดวิวสดล่าสุดของแต่ละ video_id จาก snapshot
    live_vc = {}
    for r in read_jsonl(live_path):
        vid = r.get("video_id")
        if not vid:
            continue
        ts = r.get("ts", "")
        if vid not in live_vc or ts > live_vc[vid][0]:
            live_vc[vid] = (ts, int(r.get("view_count", 0)))

    videos = []
    for v in vids:
        if v.get("published_at", "")[:7] != latest_month:
            continue
        vid = v.get("video_id", "")
        # ใช้ยอดสดล่าสุด ถ้ามี ไม่ใช่ยอดตอน backfill (สดกว่า)
        vc = live_vc.get(vid, ("", v.get("view_count", 0)))
        vc = vc[1] if isinstance(vc, tuple) else vc
        title = v.get("title", "")
        # ถอด prefix/suffix ให้อ่านง่าย
        ct = clean_video_title(title) if title else title
        videos.append({
            "channel_id": v.get("channel_id", ""),
            "channel": v.get("channel", ""),
            "video_id": vid,
            "title": ct or title,
            "title_raw": title,
            "view_count": int(vc),
            "like_count": int(v.get("like_count", 0)),
            "is_short": bool(v.get("is_short_est")),
            "published_at": v.get("published_at", ""),
        })
    videos.sort(key=lambda x: -x["view_count"])
    return jsonify({
        "month": latest_month,
        "total_videos": len(videos),
        "videos": videos,
        "note": f"คลิปที่โพสต์เดือน {latest_month} + ยอดวิวล่าสด",
    })



@app.route("/api/views-today")
def api_views_today():
    """วิดีโอที่ published วันนี้ (calendar today = Asia/Bangkok) + ยอดวิวล่าสุด
    ต่างจาก views-month: กรองเป็นวัน ไม่ใช่เดือน — มุมมอง 'วันล่าสุด' ต้องเป็นวิดีโอของวันนี้เท่านั้น"""
    from datetime import timezone as _tz, timedelta as _td
    month_path = os.environ.get("VIEWS_MONTH_JSONL", "/data/views_month.jsonl")
    live_path = VIEWS_LIVE_JSONL

    def read_jsonl(path):
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    vids = read_jsonl(month_path)
    if not vids:
        return jsonify({"date": "", "total_videos": 0, "videos": [], "note": "ยังไม่มี views_month.jsonl — รัน MODE=totals ก่อน"})

    # วันที่ "วันนี้" ตาม Asia/Bangkok (UTC+7)
    today = datetime.now(_tz(_td(hours=7))).strftime("%Y-%m-%d")

    # ยอดวิวสดล่าสุดของแต่ละ video_id จาก snapshot
    live_vc = {}
    for r in read_jsonl(live_path):
        vid = r.get("video_id")
        if not vid:
            continue
        ts = r.get("ts", "")
        if vid not in live_vc or ts > live_vc[vid][0]:
            live_vc[vid] = (ts, int(r.get("view_count", 0)))

    videos = []
    for v in vids:
        # กรองด้วย published_at == วันนี้ (แปลง 2026-08-10T... → 2026-08-10)
        pub = v.get("published_at", "")[:10]
        if pub != today:
            continue
        vid = v.get("video_id", "")
        vc = live_vc.get(vid, ("", v.get("view_count", 0)))
        vc = vc[1] if isinstance(vc, tuple) else vc
        title = v.get("title", "")
        ct = clean_video_title(title) if title else title
        videos.append({
            "channel_id": v.get("channel_id", ""),
            "channel": v.get("channel", ""),
            "video_id": vid,
            "title": ct or title,
            "title_raw": title,
            "view_count": int(vc),
            "like_count": int(v.get("like_count", 0)),
            "is_short": bool(v.get("is_short_est")),
            "published_at": v.get("published_at", ""),
        })
    videos.sort(key=lambda x: -x["view_count"])
    return jsonify({
        "date": today,
        "total_videos": len(videos),
        "videos": videos,
        "note": f"คลิปที่โพสต์วันนี้ ({today}) + ยอดวิวล่าสุด",
    })


@app.route("/api/views-data")
def api_views_data():
    """อ่าน views_data.jsonl (batch รายวันจาก Analytics ถ้ามี) + views_live.jsonl (snapshot สด)
    ถ้าไม่มี batch (CMS บล็อก) → คำนวณรายวันจาก snapshot history แทน (ไม่ต้อง CMS)"""
    def read_jsonl(path):
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    batch = read_jsonl(VIEWS_JSONL)
    live = read_jsonl(VIEWS_LIVE_JSONL)
    last_live = live[-1]["ts"] if live else ""
    last_batch = batch[-1]["date"] if batch else ""

    # ถ้าไม่มี batch จริง (CMS บล็อก) → สังเคราะห์รายวันจาก snapshot history
    if not batch and live:
        batch = compute_daily_from_snapshot(live)

    return jsonify({
        "batch": batch,          # channel-level + per-video (มี date, product)
        "live": live,            # snapshot สด (ts, video_id, view_count, is_short_est)
        "last_live": last_live,
        "last_batch": last_batch,
        "channels": None,
    })


def compute_daily_from_snapshot(live):
    """คำนวณยอดวิวรายวันจาก snapshot history (view_count สะสมทุกชั่วโมง)
    รายวัน[date][video] = view_count สุดท้ายของวัน − view_count สุดท้ายของวันก่อนหน้า
    ถ้าไม่มีวันก่อน → เทียบกับ 0 (วิดีโอเพิ่งโพสต์)"""
    from collections import defaultdict
    # รวบรวม (video_id, date) -> (ts สุดท้าย, view_count สุดท้าย)
    by_vid_date = defaultdict(dict)  # vid -> date -> (ts, vc)
    meta = {}  # vid -> (channel_id, channel, title, is_short)
    for r in live:
        vid = r.get("video_id")
        if not vid:
            continue
        d = r["ts"][:10]
        ts = r["ts"]
        vc = int(r.get("view_count", 0))
        cur = by_vid_date[vid].get(d)
        if cur is None or ts > cur[0]:
            by_vid_date[vid][d] = (ts, vc)
        meta[vid] = (r.get("channel_id"), r.get("channel"), r.get("title"), r.get("is_short_est"))

    # วันทั้งหมดเรียงลำดับ
    all_dates = sorted({d for vid in by_vid_date for d in by_vid_date[vid]})
    # วันก่อนหน้าของแต่ละวัน
    prev_date = {}
    for i, d in enumerate(all_dates):
        prev_date[d] = all_dates[i-1] if i > 0 else None

    rows = []
    for vid, dmap in by_vid_date.items():
        cid, cname, title, is_short = meta[vid]
        for d in dmap:
            vc_today = dmap[d][1]
            pd = prev_date[d]
            vc_prev = 0
            if pd and pd in dmap:
                vc_prev = dmap[pd][1]
            elif pd:
                # หา vc วันก่อนจากวันไหนก็ได้ที่ < d (เอาแค่ก่อนสุด)
                earlier = [dd for dd in dmap if dd < d]
                if earlier:
                    vc_prev = dmap[max(earlier)][1]
            daily = max(0, vc_today - vc_prev)
            rows.append({
                "date": d, "channel_id": cid, "channel": cname,
                "video_id": vid, "title": title or "",
                "product": "SHORTS" if is_short else "CORE",
                "views": daily,
                "estimated_revenue": 0.0, "subs_gained": 0, "subs_lost": 0,
                "avg_view_dur": 0, "watch_time_min": 0,
            })
    return rows


@app.route("/")
def index():
    return redirect("/live-monitor")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8899"))
    app.run(host="0.0.0.0", port=port, threaded=True)