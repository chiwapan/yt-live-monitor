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


# --- Cache for /api/live-data (2026-08-31) ---
# keyed by mtime of live_data.jsonl — invalidate เมื่อไฟล์ append ใหม่ (cronทุก 5นาที)
_live_data_cache: dict = {"mtime": 0, "data": None}


@app.route("/api/ping")
def api_ping():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


# ── Slot comparison: ข่าวเช้า / เที่ยง / เย็น / Primetime วันต่อวัน ──
SLOTS = [
    {"name": "Live ข่าวเช้า", "programs": [
        {"name": "เรื่องเล่าเช้านี้ · เรื่องเล่าเช้านี้", "channel": "เรื่องเล่าเช้านี้", "kw": ["เรื่องเล่าเช้านี้", "เรื่องเล่าหน้าหนึ่ง", "เรื่องเล่าเสาร์-อาทิตย์"]},
        {"name": "Workpoint 23 · ข่าวเช้าเวิร์คพอยท์", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ข่าวเวิร์คพอยท์", "ข่าวเช้า"]},
        {"name": "ข่าวช่อง8 · คุยข่าวเช้า", "channel": "ข่าวช่อง8", "kw": ["คุยข่าวเช้า"]},
        {"name": "ThaiRath News", "channel": "ThaiRath News", "kw": ["ข่าวเช้าหัวเขียว", "ห้องข่าวหัวเขียว"], "window": ["06:35", "08:30"]},
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
    {"name": "Live Talk (08:30-09:00) vs กรรมกรข่าว", "programs": [
        {"name": "ไทยรัฐ · Live Talk ออนไลน์ (08:30-09:00)", "channel": "ThaiRath News", "kw": ["ข่าวเช้าหัวเขียว", "ห้องข่าวหัวเขียว"], "window": ["08:30", "09:00"], "weekdays": [0, 1, 2, 3]},
        {"name": "สรยุทธ · กรรมกรข่าว คุยนอกจอ", "channel": "สรยุทธ กรรมกรข่าว", "kw": ["กรรมกรข่าว คุยนอกจอ"], "window": ["08:30", "09:00"]},
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
                # weekday filter: จับเฉพาะบางวันในสัปดาห์ (เช่น Live Talk ไทยรัฐ Mon-Thu เท่านั้น)
                # s["end"] เป็น datetime → .weekday() Mon=0 ... Sun=6
                if prog.get("weekdays") and s["end"].weekday() not in prog["weekdays"]:
                    continue
                # track วิดีโอล่าสุด (end หลังสุด) ของโปรแกรมนี้ → ใช้ title เป็นชื่อแสดง
                if latest_end is None or s["end"] > latest_end:
                    latest_end = s["end"]
                    latest_title = s["title"]
                # time window: จับเฉพาะช่วงเวลา (เช่น Live Talk 09:00-09:30) ถ้าตั้ง "window"
                # หัวใจ: normalize ชั่วโมงเป็น 2 หลักก่อน string-compare (รองรับ '8:30' ไม่ pad จาก Sheets)
                if prog.get("window"):
                    w0, w1 = prog["window"]
                    def _hhmm(ts):
                        hh, mm, *_ = ts.split(" ")[1].split(":")
                        return f"{int(hh):02d}:{mm}"
                    pts = [tv for tv in s["points"] if w0 <= _hhmm(tv[0]) <= w1]
                    if not pts:
                        continue
                    eff = {
                        "peak": max(v for _, v in pts),
                        "start": min(p[0] for p in pts).split(" ")[1][:5],
                        "end": max(p[0] for p in pts).split(" ")[1][:5],
                        "points": pts,
                    }
                else:
                    eff = {"peak": s["peak"], "start": s["start"].strftime("%H:%M"),
                           "end": s["end"].strftime("%H:%M"), "points": s["points"]}
                e = days.get(s["date"])
                if e is None:
                    e = days[s["date"]] = {
                        "peak": eff["peak"],
                        "start": eff["start"],
                        "end": eff["end"],
                        "curve": {},
                    }
                else:
                    e["peak"] = max(e["peak"], eff["peak"])
                    if eff["start"] < e["start"]:
                        e["start"] = eff["start"]
                    if eff["end"] > e["end"]:
                        e["end"] = eff["end"]
                # per-day concurrent curve: sum viewers ของทุก stream ที่ match ตาม HH:MM
                for tv in eff["points"]:
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
    ?date=YYYY-MM-DD  : คืนแค่วันที่ระบุ (หน้า overview/เลือกวัน)
    ?recent_days=N   : คืน N วันล่สุด (เดิม = all ถ้าใส่ 0 หรือไม่ใส่)
                       default=0 (backward compatible); frontendเปิดครั้งแรกใช้ 7
                       ลด 6MB → ~600KB เมื่อเปิด live-monitor (เดิม fetch full)

    Optimization (2026-08-31 #3): cached_load() เก็บ parsed data + mtime
    ลดเวลา 1.4-3.7s → 0.1s หลัง request แรก (jsonl append ทุก 5 นาทีเท่านั้น)
    """
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

    # Cache: ใช้ mtime เป็น key ล้างเมื่อไฟล์เปลี่ยน
    # ต้องประกาศ global ที่จุดเริ่มต้น —เพราะมี _live_data_cache = {...} assignment
    # ใน cache-miss block ทำให้ Python mark เป็น local; ถ้าไม่ declare ก่อน
    # จะ UnboundLocalError ตอน read
    global _live_data_cache
    try:
        file_mtime = os.path.getmtime(LIVE_JSONL)
    except OSError:
        return jsonify({"channels": {}, "last_ts": "", "total_samples": 0, "dates": []})

    if _live_data_cache["mtime"] != file_mtime or _live_data_cache["data"] is None:
        # Cache miss — full reload + group ครั้งเดียว
        cached = {
            "streams": defaultdict(lambda: defaultdict(list)),
            "stream_meta": {},
            "last_dt": None,
            "available_dates": set(),
            "raw_rows": [],  # เก็บ raw (channel, video_id, ts_dt, ts_str) ไว้ — filter ภายหลังได้
        }
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
                        cached["available_dates"].add(dt.strftime("%Y-%m-%d"))
                    ch = d.get("channel", "Unknown")
                    vid = d.get("video_id", "")
                    cached["raw_rows"].append({
                        "ts": ts,
                        "dt": dt,
                        "ch": ch,
                        "vid": vid,
                        "viewers": d.get("viewers", 0),
                        "title": d.get("title", ""),
                        "url": d.get("url", ""),
                        "actual_start": d.get("actual_start", ""),
                    })
                    if dt and (cached["last_dt"] is None or dt > cached["last_dt"]):
                        cached["last_dt"] = dt
        except FileNotFoundError:
            return jsonify({"channels": {}, "last_ts": "", "total_samples": 0, "dates": []})

        _live_data_cache = {"mtime": file_mtime, "data": cached}
    cached = _live_data_cache["data"]

    date_filter = request.args.get("date", "")
    recent_days = int(request.args.get("recent_days", default="0") or "0")
    # คำนวณ recent_dates_set (cached — ถ้าเปลี่ยน recent_days ก็คำนวณใหม่)
    if date_filter:
        recent_dates_set = {date_filter}
    elif recent_days > 0:
        sorted_dates = sorted(cached["available_dates"], reverse=True)
        recent_dates_set = set(sorted_dates[:recent_days])
    else:
        recent_dates_set = None  # all

    # Single-pass filter จาก cached raw_rows
    streams = defaultdict(lambda: defaultdict(list))
    stream_meta = {}
    total = 0
    for r in cached["raw_rows"]:
        if recent_dates_set is not None:
            day = r["ts"].split(" ")[0] if r["ts"] else ""
            if day not in recent_dates_set:
                continue
        total += 1
        streams[r["ch"]][r["vid"]].append({
            "ts": r["ts"], "dt": r["dt"], "viewers": r["viewers"]
        })
        stream_meta[r["vid"]] = {
            "title": r["title"],
            "channel": r["ch"],
            "url": r["url"],
            "actual_start": r["actual_start"],
        }

    last_dt = cached["last_dt"]
    available_dates = cached["available_dates"]

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
            # ── Aggregate optimization (2026-08-31) ──
            # When called without ?date filter (default view, first-load),
            # frontend shows channel cards + leaderboards — does NOT need
            # every 5-minute point of every historical stream. Aggregate
            # points to 1-per-hour for non-live streams to cut payload
            # ~70% (4MB → 1MB). Live streams keep every point so chart
            # animates correctly. When ?date is specified, user is doing
            # drilldown → keep full resolution.
            if not date_filter and not is_live:
                agg_points = []
                cur_hour = None
                cur_peak_v = 0
                cur_peak_ts = ""
                for p in points:
                    h = p["ts"][:13]  # 'YYYY-MM-DD HH'
                    if h != cur_hour:
                        if cur_hour is not None:
                            agg_points.append({"ts": cur_peak_ts, "viewers": cur_peak_v})
                        cur_hour = h
                        cur_peak_v = p["viewers"]
                        cur_peak_ts = p["ts"]
                    else:
                        if p["viewers"] > cur_peak_v:
                            cur_peak_v = p["viewers"]
                            cur_peak_ts = p["ts"]
                if cur_hour is not None:
                    agg_points.append({"ts": cur_peak_ts, "viewers": cur_peak_v})
                points_out = agg_points
            else:
                points_out = [{"ts": p["ts"], "viewers": p["viewers"]} for p in points]
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
                "points": points_out,
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


_views_month_cache = {"mtime": 0, "batch": None}


def _load_views_month():
    """Load VIEWS_MONTH_JSONL + snapshot for latest views. Cached by mtime."""
    global _views_month_cache
    month_path = os.environ.get("VIEWS_MONTH_JSONL", "/data/views_month.jsonl")
    try:
        m = os.path.getmtime(month_path) if os.path.exists(month_path) else 0
    except OSError:
        m = 0
    if _views_month_cache["mtime"] == m and _views_month_cache["batch"] is not None:
        return _views_month_cache["batch"]
    # ใช้ helper _read_jsonl (module-level) แทน local read_jsonl — ลดซ้ำซ้อน
    vids = _read_jsonl(os.environ.get("VIEWS_MONTH_JSONL", "/data/views_month.jsonl"))
    # คำนวณ latest month + video info เดียวกัน
    months = sorted({v.get("published_at", "")[:7] for v in vids if v.get("published_at")})
    latest_month = months[-1] if months else ""
    # ยอดวิวล่าสุด: scan snapshot 1 pass
    live_vc = {}
    live_raw = _read_jsonl(VIEWS_LIVE_JSONL)
    for r in live_raw:
        vid = r.get("video_id")
        if vid:
            live_vc[vid] = r.get("viewers", 0)
    # เก็บ processed batch
    result = {"month": latest_month, "videos": vids, "live_vc": live_vc}
    _views_month_cache = {"mtime": m, "batch": result}
    return result


@app.route("/api/views-month")
def api_views_month():
    """คลิปที่โพสต์ในเดือนล่าสุด (ตาม published_at ใน views_month.jsonl)
    + ยอดวิวสะสมล่าสุด (จาก snapshot views_live.jsonl ถ้ามี video_id นี้)
    ได้ทุกช่องรวมคู่แข่ง (พึ่ง Data API ไม่ใช่ CMS)"""
    result = _load_views_month()
    vids = result["videos"]
    latest_month = result["month"]
    if not vids:
        return jsonify({"month": "", "videos": [], "note": "ยังไม่มี views_month.jsonl — รัน MODE=totals ก่อน"})

    # ยอดวิวสดล่าสุดของแต่ละ video_id จาก snapshot
    live_vc = {}
    for r in _read_jsonl(VIEWS_LIVE_JSONL):
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
    # ใช้ snapshot ล่าสุดเป็นข้อมูล "วันล่าสุด" (ไม่ใช้ published_at filter)
    # ก่อนหน้าใช้ published_at == today → คืน 0 ถ้าไม่มีวิดีโอโพสต์ใหม่ตรงวันที่ snapshot
    # ตอนนี้ใช้ snapshot (live_data.jsonl) → คืนวิดีโอล่าสุดที่มีข้อมูล concurrent
    # ลดความสับสนระหว่าง "วันที่ snapshot" กับ "วันที่ publish" ของ CMS
    # วันที่ "วันนี้" ตาม Asia/Bangkok (UTC+7) — ใช้เป็น label วันที่ snapshot
    from datetime import timezone as _tz, timedelta as _td
    today = datetime.now(_tz(_td(hours=7))).strftime("%Y-%m-%d")
    live_raw = _read_jsonl(VIEWS_LIVE_JSONL)
    # รวบรวม video ล่าสุด (max view_count จาก snapshot)
    latest_vids = {}
    for r in live_raw:
        vid = r.get("video_id")
        if not vid:
            continue
        ts = r.get("ts", "")
        # views_live.jsonl ใช้ 'view_count' (ไม่ใช่ 'viewers')
        vc = int(r.get("view_count", 0))
        # เก็บล่าสุด (last snapshot per video)
        if vid not in latest_vids or ts > latest_vids[vid].get("ts", ""):
            latest_vids[vid] = {"ts": ts, "viewers": vc,
                                "channel_id": r.get("channel_id", ""),  # UCxxxxx
                                "channel": r.get("channel", ""),          # ชื่อช่อง
                                "title": r.get("title", ""),
                                "url": r.get("url", "")}

    # อ่าน meta จาก VIEWS_JSONL (มี title_raw, product, is_short_est) — ไม่กรองด้วยวันที่
    meta_vids = {}
    # VIEWS_JSONL ใช้ env หรือ default /data/views_data.jsonl (local path ใน container)
    for r in _read_jsonl(os.environ.get("VIEWS_DATA_JSONL", "/data/views_data.jsonl")):
        vid = r.get("video_id")
        if vid:
            meta_vids[vid] = r

    videos = []
    for vid, info in sorted(latest_vids.items(), key=lambda x: -x[1]["viewers"]):
        meta = meta_vids.get(vid, {})
        # channel_id = UCxxxxx (YouTube ID) — จาก snapshot ก่อน, fallback จาก meta
        ch_id = info.get("channel_id") or meta.get("channel_id", "")
        ch_name = info.get("channel") or meta.get("channel", "")
        title = info.get("title", "")
        ct = clean_video_title(title) if title else title
        videos.append({
            "channel_id": ch_id,            # ต้องเป็น UCxxxxx
            "channel": ch_name,              # ชื่อช่อง (แสดงผล)
            "video_id": vid,
            "title": ct or title,
            "title_raw": meta.get("title_raw", title),
            "view_count": info.get("viewers", 0),
            "is_short": bool(meta.get("is_short_est")),
            "published_at": meta.get("published_at", ""),
        })
    # จำกัดไว้ที่ 20 รายการล่าสุด (ลด payload)
    videos = videos[:20]
    return jsonify({
        "date": today,
        "total_videos": len(videos),
        "videos": videos,
        "note": f"คลิปที่โพสต์วันนี้ ({today}) + ยอดวิวล่าสุด",
    })


# --- views-data cache (2026-08-31) ---
# mtime-based cache เพื่อลด response time 8-21s → <0.1s หลัง request แรก
# ไฟล์ views_data.jsonl + views_live.jsonl append ทุก 5 นาที — mtime change → invalidate
_views_data_cache = {"mtime": 0, "batch": None, "last_live": ""}


def _read_jsonl(path):
    """Read JSONL file safely."""
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        pass
    return out


def _load_views_batch():
    """Load batch + last_live from jsonl files. Cached by mtime."""
    global _views_data_cache
    try:
        m1 = os.path.getmtime(VIEWS_JSONL) if os.path.exists(VIEWS_JSONL) else 0
    except OSError:
        m1 = 0
    try:
        m2 = os.path.getmtime(VIEWS_LIVE_JSONL) if os.path.exists(VIEWS_LIVE_JSONL) else 0
    except OSError:
        m2 = 0
    combined = (m1, m2)
    if _views_data_cache["mtime"] == combined and _views_data_cache["batch"] is not None:
        return _views_data_cache["batch"], _views_data_cache["last_live"]
    live = _read_jsonl(VIEWS_LIVE_JSONL)
    batch = _read_jsonl(VIEWS_JSONL)
    if not batch and live:
        batch = compute_daily_from_snapshot(live)
    last_live = live[-1]["ts"] if live else ""
    _views_data_cache = {"mtime": combined, "batch": batch, "last_live": last_live}
    return batch, last_live


@app.route("/api/views-data")
def api_views_data():
    """อ่าน views_data.jsonl (batch รายวันจาก Analytics ถ้ามี) + views_live.jsonl (snapshot สด)
    ถ้าไม่มี batch (CMS บล็อก) → คำนวณรายวันจาก snapshot history แทน (ไม่ต้อง CMS)"""
    batch, last_live = _load_views_batch()
    last_batch = batch[-1]["date"] if batch else ""

    # Optimization (2026-08-31): ตัด fields ที่ frontend ไม่ใช้จริง
    # (grep frontend ใช้แค่: video_id, channel_id, channel, title, title_raw, view_count, views, date, is_short, product)
    # ตัด: estimated_revenue, subs_gained, subs_lost, avg_view_dur, watch_time_min
    # batch ที่มาจาก compute_daily_from_snapshot ตัดไปแล้วตอนสร้าง แต่ batch จาก views_data.jsonl ต้อง filter ตอนนี้
    # ประหยัย: 51MB → ~30MB
    KEEP_BATCH_FIELDS = {"date", "channel_id", "channel", "video_id", "title", "title_raw",
                          "view_count", "views", "is_short", "product"}
    if batch and batch[0].keys() - KEEP_BATCH_FIELDS:
        batch = [{k: v for k, v in row.items() if k in KEEP_BATCH_FIELDS} for row in batch]

    # --- Optimization (2026-08-31 #2): server-side date filter ---
    # Frontend (views_monitor.html) ใช้ batch แค่เพื่อหา "วันล่าสุด" + delta กับวันก่อนหน้า
    # ส่งแค่วันล่าสุดหรือ 1-2 วันจก่อน → 44MB → ~2MB (95%)
    # param ?days=N (default 3: วันนี้ + เมื่อวาน + ก่อนเมื่อวานเผื่อให้มี prev)
    days = request.args.get("days", default=3, type=int)
    if days > 0 and batch:
        all_dates = sorted({r.get("date", "") for r in batch if r.get("date")})
        # ใช้ N วันสุดท้ายจาก available dates (ไม่ใช่วันละ format เหมือนกัน)
        cutoff_dates = set(all_dates[-days:]) if len(all_dates) > days else set(all_dates)
        batch = [r for r in batch if r.get("date", "") in cutoff_dates]
        last_batch = max(cutoff_dates) if cutoff_dates else last_batch

    # IMPORTANT: อย่าส่ง raw `live` array เต็ม (180K+ แถว ≈ 114MB) เข้าเบราว์เซอร์ —
    # frontend ใช้แค่ RAW.batch (daily) + last_live timestamp
    return jsonify({
        "batch": batch,
        "last_live": last_live,
        "last_batch": last_batch,
        "channels": None,
    })


def compute_daily_from_snapshot(live):
    """คำนวณยอดวิวรายวันจาก snapshot history (view_count สะสมทุกชั่วโมง)
    รายวัน[date][video] = view_count สุดท้ายของวัน − baseline
    baseline: วิวสุดท้ายของวันก่อนหน้า ถ้ามี; ถ้าไม่มี (วิดีโอวันแรกของ monitor)
              ใช้วิว snapshot แรกของวันนั้นเป็น baseline แทน 0
    → ไม่นับวิวสะสมทั้งคลิปที่มาก่อนเริ่มเก็บ (กัน daily พอง 39M ที่เจอ 13-08)"""
    from collections import defaultdict
    # รวบรวม (video_id, date) -> (ts แรก, vc แรก, ts สุดท้าย, vc สุดท้าย)
    by_vid_date = defaultdict(dict)  # vid -> date -> [first_ts, first_vc, last_ts, last_vc]
    meta = {}  # vid -> (channel_id, channel, title, is_short)
    for r in live:
        vid = r.get("video_id")
        if not vid:
            continue
        d = r["ts"][:10]
        ts = r["ts"]
        vc = int(r.get("view_count", 0))
        e = by_vid_date[vid].get(d)
        if e is None:
            by_vid_date[vid][d] = [ts, vc, ts, vc]
        else:
            if ts < e[0]:
                e[0], e[1] = ts, vc
            if ts > e[2]:
                e[2], e[3] = ts, vc
        meta[vid] = (r.get("channel_id"), r.get("channel"), r.get("title"), r.get("is_short_est"))

    # วันทั้งหมดเรียงลำดับ (global) — ใช้อ้างอิงวันก่อนหน้าของวิดีโอ
    all_dates = sorted({d for vid in by_vid_date for d in by_vid_date[vid]})
    prev_date = {}
    for i, d in enumerate(all_dates):
        prev_date[d] = all_dates[i-1] if i > 0 else None

    rows = []
    for vid, dmap in by_vid_date.items():
        cid, cname, title, is_short = meta[vid]
        for d in (dmap):
            last_ts, last_vc = dmap[d][2], dmap[d][3]
            first_vc = dmap[d][1]
            pd = prev_date[d]
            # baseline เลือก: วิวสุดท้ายวันก่อน (ถ้ามี) > มิฉะนั้น วิวแรกของวัน (วันแรกของ monitor)
            if pd and pd in dmap:
                base = dmap[pd][3]  # วิวสุดท้ายวันก่อน
            else:
                base = first_vc     # วันแรกของ monitor → ใช้จุดแรกของวันแทน 0
            daily = max(0, last_vc - base)
            rows.append({
                "date": d, "channel_id": cid, "channel": cname,
                "video_id": vid, "title": title or "",
                "product": "SHORTS" if is_short else "CORE",
                "views": daily,
            })
    return rows


@app.route("/")
def index():
    return redirect("/live-monitor")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8899"))
    app.run(host="0.0.0.0", port=port, threaded=True)