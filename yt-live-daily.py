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
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import subprocess
from datetime import datetime, timezone, timedelta

# ─── Config (all from env) ───
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
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
]

ICT = timezone(timedelta(hours=7))
STATE_FILE = "/tmp/yt-live-daily-state.json"


def floor_5min(dt):
    """Floor datetime to nearest 5-minute mark (cron-aligned)."""
    new_min = (dt.minute // 5) * 5
    return dt.replace(minute=new_min, second=0, microsecond=0)


# ─── YouTube Data API (API key only, no OAuth needed for public data) ───

def yt_api(endpoint, params):
    """Call YouTube Data API v3 with API key."""
    params["key"] = API_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"⚠️ API error {e.code}: {e.reason}")
        return {}
    except Exception as e:
        print(f"⚠️ API error: {e}")
        return {}


# ─── RSS Discovery (0 quota) ───

def get_live_from_rss():
    """Check all channel RSS feeds for recent videos (0 quota cost)."""
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
]

def get_live_from_search():
    """Search API eventType=live per-channel (100 units/call) เฉพาะช่องหลัก.
    Search ระดับ global (regionCode=TH) คืน 0 เสมอ — ต้อง per-channel ถึง reliable.
    จำกัดช่องเพื่อประหยัด quota; เรียกทุก 2 ชม ผ่าน throttle ใน main."""
    wanted = {c["id"]: c["name"] for c in CHANNELS}
    hits = []
    for ch_id in SEARCH_CHANNEL_IDS:
        if ch_id not in wanted:
            continue
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
    """Check which videos are currently live using videos.list (1 unit/call)."""
    if not video_ids_list:
        return []

    channel_lookup = {v["video_id"]: v for v in video_ids_list}

    # Batch: YouTube API max 50 IDs per call
    all_items = []
    for i in range(0, len(video_ids_list), 50):
        batch = video_ids_list[i:i+50]
        ids_str = ",".join(v["video_id"] for v in batch)
        result = yt_api("videos", {
            "part": "snippet,liveStreamingDetails",
            "id": ids_str,
        })
        all_items.extend(result.get("items", []))

    # Load state to get last known viewers for fallback
    state = load_state()

    live_streams = []
    for item in all_items:
        live_details = item.get("liveStreamingDetails", {})
        snippet = item.get("snippet", {})
        vid = item["id"]

        concurrent = live_details.get("concurrentViewers")
        actual_end = live_details.get("actualEndTime")
        broadcast = snippet.get("liveBroadcastContent")

        # PREMIERE DETECTION: A YouTube Premiere also sets liveBroadcastContent="live"
        # during the event, but the Data API NEVER returns concurrentViewers for a
        # premiere (only for true live broadcasts). So if we've already polled this video
        # (it's in state) and it STILL has no concurrentViewers field → it's a Premiere,
        # not a real live. Flag & skip so premieres don't pollute the live ranking/summary
        # with fake 0-viewer rows.
        if (concurrent is None and broadcast == "live" and actual_end is None
                and vid in state.get("streams", {})):
            print(f"🎬 {vid}: Premiere — no concurrentViewers, not a real live. Skipped.")
            continue

        # If concurrentViewers is missing but stream is still live (no endTime),
        # use last known viewers from state as fallback
        if concurrent is None and actual_end is None and vid in state.get("streams", {}):
            last_viewers = state["streams"][vid].get("last_viewers")
            if last_viewers is not None:
                concurrent = last_viewers
                print(f"⚠️ {vid}: concurrentViewers missing, using fallback {last_viewers}")

        # NEW-LIVE GUARD: A brand-new live stream (not yet in state) may not have
        # concurrentViewers populated for the first 1-2 ticks after going live.
        # Record 0 so we don't drop the opening ticks; later ticks overwrite real values.
        if concurrent is None and broadcast == "live" and actual_end is None:
            concurrent = 0
            print(f"⚠️ {vid}: new live, concurrentViewers not ready yet — recording 0")

        if concurrent is not None:
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
    return live_streams


# ─── State Management (peak tracking) ───

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"streams": {}, "last_daily_summary": ""}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_stream_state(state, live_streams, cron_now):
    """Update peak viewers for each tracked stream."""
    now_str = cron_now.strftime("%Y-%m-%d %H:%M:%S")
    current_ids = {s["video_id"] for s in live_streams}

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

    # Mark ended streams (>10 min since last seen)
    for vid in list(state["streams"].keys()):
        if vid not in current_ids:
            existing = state["streams"][vid]
            last_seen = datetime.strptime(existing["last_seen"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ICT)
            elapsed = (cron_now - last_seen).total_seconds()
            if elapsed > 600:
                existing["ended"] = True
                existing["end_time"] = existing["last_seen"]

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
    sheets_update("Raw", "A1:F1",
                  [["Timestamp", "Video_ID", "Title", "Concurrent_Viewers", "Channel", "URL"]])
    sheets_update("Daily_Summary", "A1:I1",
                  [["Date", "Video_ID", "Title", "Peak_Viewers", "Avg_Viewers",
                     "Start_Time", "End_Time", "Duration_Min", "URL"]])
    sheets_update("Peak_Viewers", "A1:H1",
                  [["Date", "Program", "Channel", "Peak_Viewers", "Avg_Viewers",
                     "Start_Time", "End_Time", "URL"]])


# ─── Local JSONL store (for dashboard) ───
JSONL_FILE = "/opt/data/projects/yt-live-monitor/live_data.jsonl"

def append_local_jsonl(live_streams, now):
    """Append live samples to local JSONL — dashboard reads this directly."""
    try:
        with open(JSONL_FILE, "a") as f:
            for s in live_streams:
                f.write(json.dumps({
                    "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "video_id": s["video_id"],
                    "title": s["title"][:100],
                    "viewers": s["concurrent_viewers"],
                    "channel": s["channel_name"],
                    "url": s["url"],
                    "actual_start": s.get("actual_start", ""),
                }, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ JSONL write error: {e}")


# ─── Main ───

def main():
    if not API_KEY:
        print("⚠️ YOUTUBE_API_KEY not set")
        sys.exit(1)
    if not SHEET_ID:
        print("⚠️ YT_SHEET_ID not set")
        sys.exit(1)

    now = floor_5min(datetime.now(ICT))
    print(f"🔍 YT Live Monitor — {now.strftime('%Y-%m-%d %H:%M:%S')} ICT")

    # 1. Discover from RSS
    rss_videos = get_live_from_rss()
    print(f"📡 RSS: found {len(rss_videos)} recent videos")

    # 1a. Live-Search layer — กัน live หลุดจาก RSS top-15 (ช่องที่ upload ถี่มาก)
    #     Search API = 100 units/call หนักมาก → จำกัดให้รันทุก 15 นาที (ทุก 3 tick)
    state_pre = load_state()
    last_search = state_pre.get("last_live_search_ts", "")
    do_search = False
    if last_search:
        try:
            from datetime import datetime as _dt
            last_dt = _dt.strptime(last_search, "%Y-%m-%d %H:%M:%S")
            do_search = (now - last_dt).total_seconds() >= 7200  # 2 ชม (6 ช่อง × 100 = 600 units/ครั้ง)
        except Exception:
            do_search = True
    else:
        do_search = True

    if do_search:
        # per-channel search เฉพาะ 6 ช่องหลัก (100 units/ช่อง) throttle 2 ชม
        search_videos = get_live_from_search()
        print(f"🔎 live-search: found {len(search_videos)} live ในช่องหลัก")
        rss_ids = {v["video_id"] for v in rss_videos}
        added = 0
        for v in search_videos:
            if v["video_id"] not in rss_ids:
                rss_videos.append(v)
                added += 1
        if added:
            print(f"  ⊕ merged {added} live(s) ที่ RSS ไม่เจอ")
        state_pre["last_live_search_ts"] = now.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state_pre)  # persist throttle immediately (main reloads state later)
    else:
        print(f"  ⏳ live-search skip (รันครั้งล่าสุด {last_search})")

    # 1b. รวม stream จาก state ที่ยังไม่ ended (กันหลุดจาก RSS — RSS คืนแค่ ~15 ตัว)
    rss_ids = {v["video_id"] for v in rss_videos}
    ch_lookup = {c["id"]: c["name"] for c in CHANNELS}
    for vid, s in state_pre.get("streams", {}).items():
        if vid in rss_ids or s.get("ended"):
            continue
        # หา channel_id จาก name
        ch_id = next((c["id"] for c in CHANNELS if c["name"] == s.get("channel")), "")
        rss_videos.append({
            "video_id": vid,
            "title": s.get("title", ""),
            "channel_id": ch_id,
            "channel_name": s.get("channel", "Unknown"),
        })
        print(f"📌 state-persist: {vid} ({s.get('title','')[:40]}) — not in RSS, still polling")

    # 2. Check which are live
    live_streams = check_if_live(rss_videos)

    if not live_streams:
        print("ℹ️ No live streams right now — silent exit")
        state = load_state()
        update_stream_state(state, [], now)
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
    update_stream_state(state, live_streams, now)

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
