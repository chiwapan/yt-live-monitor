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


@app.route("/api/ping")
def api_ping():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


# ── Slot comparison: ข่าวเช้า / เที่ยง / เย็น / Primetime วันต่อวัน ──
SLOTS = [
    {"name": "Live ข่าวเช้า", "programs": [
        {"name": "เรื่องเล่าเช้านี้", "channel": "เรื่องเล่าเช้านี้", "kw": ["เรื่องเล่าเช้านี้"]},
        {"name": "สรยุทธ กรรมกรข่าว", "channel": "สรยุทธ กรรมกรข่าว", "kw": ["กรรมกรข่าว คุยนอกจอ"]},
        {"name": "ข่าวเวิร์คพอยท์ 23", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ฟลุ้ค"]},
        {"name": "ข่าวช่อง8", "channel": "ข่าวช่อง8", "kw": ["คุยข่าวเช้า"]},
        {"name": "ThaiRath News", "channel": "ThaiRath News", "kw": ["ข่าวเช้าหัวเขียว"]},
    ]},
    {"name": "ข่าวเย็น (16:00)", "programs": [
        {"name": "ข่าวเย็นไทยรัฐ", "channel": "ThaiRath News", "kw": ["ข่าวเย็นไทยรัฐ", "ไทยรัฐทันข่าว"]},
        {"name": "คุยข่าวเย็นช่อง8", "channel": "ข่าวช่อง8", "kw": ["คุยข่าวเย็น"]},
    ]},
    {"name": "Live ข่าวเที่ยง", "programs": [
        {"name": "ครอบครัวข่าว3", "channel": "ครอบครัวข่าว3", "kw": ["เที่ยงวันทันเหตุการณ์"]},
        {"name": "ThaiRath News", "channel": "ThaiRath News", "kw": ["ข่าวเที่ยงไทยรัฐ"]},
        {"name": "ข่าวช่อง8", "channel": "ข่าวช่อง8", "kw": ["ข่าวใหญ่ช่อง8"]},
        {"name": "ข่าวเวิร์คพอยท์ 23", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ข่าวเที่ยงเวิร์คพอยท์"]},
        {"name": "Ch7HDNews", "channel": "Ch7HDNews", "kw": ["ห้องข่าวภาคเที่ยง"]},
    ]},
    {"name": "Live ข่าวค่ำ", "programs": [
        {"name": "ข่าวช่อง8", "channel": "ข่าวช่อง8", "kw": ["ลุยชนข่าว"]},
        {"name": "ThaiRath News", "channel": "ThaiRath News", "kw": ["ไทยรัฐนิวส์โชว์"]},
        {"name": "Amarin TV", "channel": "Amarin TV", "kw": ["ทุบโต๊ะข่าว"]},
        {"name": "Ch7HDNews", "channel": "Ch7HDNews", "kw": ["ข่าวภาคค่ำ"]},
        {"name": "ข่าวเวิร์คพอยท์ 23", "channel": "ข่าวเวิร์คพอยท์ 23", "kw": ["ชงข่าวเขย่าจอ"]},
    ]},
    {"name": "รายการ Talk", "programs": [
        {"name": "Newsroom", "channel": "ThaiRath News", "kw": ["NEWSROOM"]},
        {"name": "เปิดปาก", "channel": "ThaiRath News", "kw": ["เปิดปาก"]},
        {"name": "ถกไม่เถียง", "channel": "terodigital", "kw": ["ถกไม่เถียง"]},
        {"name": "คนดังนั่งเคลียร์", "channel": "ช่อง8 Thai Ch8", "kw": ["คนดังนั่งเคลียร์"]},
    ]},
]


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
                    }
                if d.get("viewers", 0) > s["peak"]:
                    s["peak"] = d["viewers"]
                if dt < s["start"]:
                    s["start"] = dt
                if dt > s["end"]:
                    s["end"] = dt
    except FileNotFoundError:
        return jsonify({"slots": [], "last_ts": ""})

    result = []
    for slot in SLOTS:
        progs = []
        for prog in slot["programs"]:
            days = {}
            for s in streams.values():
                if s["channel"] != prog["channel"]:
                    continue
                if not any(k in s["title"] for k in prog["kw"]):
                    continue
                e = days.get(s["date"])
                if e is None:
                    days[s["date"]] = {
                        "peak": s["peak"],
                        "start": s["start"].strftime("%H:%M"),
                        "end": s["end"].strftime("%H:%M"),
                    }
                else:
                    e["peak"] = max(e["peak"], s["peak"])
                    if s["start"].strftime("%H:%M") < e["start"]:
                        e["start"] = s["start"].strftime("%H:%M")
                    if s["end"].strftime("%H:%M") > e["end"]:
                        e["end"] = s["end"].strftime("%H:%M")
            progs.append({
                "name": prog["name"],
                "channel": prog["channel"],
                "days": days,
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

    # "current" = stream มีข้อมูลใน 7 นาทีล่าสุดของเวลาจริง (cron เก็บทุก 5 นาที)
    # ใช้เวลาปัจจุบัน ไม่ใช่ last_dt — ไม่งั้นดูวันย้อนหลังทุกอย่างจะขึ้น LIVE
    now_naive_ict = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
    cutoff = now_naive_ict - timedelta(minutes=7)

    channels = {}
    for ch, vids in streams.items():
        ch_streams = []
        ch_peak = 0
        ch_current = 0
        for vid, points in vids.items():
            points.sort(key=lambda p: (p["dt"] or datetime.min))
            peak = max(p["viewers"] for p in points)
            peak_pt = next(p for p in points if p["viewers"] == peak)
            last_pt = points[-1]
            is_live = bool(last_pt["dt"] and last_pt["dt"] >= cutoff)
            if is_live:
                ch_current = max(ch_current, last_pt["viewers"])
            ch_peak = max(ch_peak, peak)
            meta = stream_meta.get(vid, {})
            ch_streams.append({
                "video_id": vid,
                "title": meta.get("title", vid),
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


@app.route("/")
def index():
    return redirect("/live-monitor")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8899"))
    app.run(host="0.0.0.0", port=port, threaded=True)