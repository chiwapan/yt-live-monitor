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


def check_if_live(video_ids_list):
    """Check which videos are currently live using videos.list (1 unit/call)."""
    if not video_ids_list:
        return []

    channel_lookup = {v["video_id"]: v for v in video_ids_list}
    ids_str = ",".join(v["video_id"] for v in video_ids_list)

    result = yt_api("videos", {
        "part": "snippet,liveStreamingDetails",
        "id": ids_str,
    })

    live_streams = []
    for item in result.get("items", []):
        live_details = item.get("liveStreamingDetails", {})
        snippet = item.get("snippet", {})
        vid = item["id"]

        concurrent = live_details.get("concurrentViewers")
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
        peak_rows.append([
            today,
            s.get("title", "")[:80],
            s.get("channel", ""),
            s["peak_viewers"],
            int(avg_viewers),
            s.get("actual_start", "")[:19],
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
