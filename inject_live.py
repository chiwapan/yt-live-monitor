#!/usr/bin/env python3
"""Inject a known live video_id into state+jsonl directly via videos.list
(1 unit) — bypasses RSS (which is often 404/500) and Search API (which hits
429 under quota pressure). Use when a known live is missing from the dashboard.

Usage:
  python inject_live.py <video_id> <channel_name> <channel_id>
"""
import sys, os
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib.util
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("yt_live_daily", os.path.join(here, "yt-live-daily.py"))
ym = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ym)

def main():
    if len(sys.argv) < 4:
        print("usage: python inject_live.py <video_id> <channel_name> <channel_id>")
        sys.exit(1)
    vid, ch_name, ch_id = sys.argv[1], sys.argv[2], sys.argv[3]

    if not os.environ.get("GAPI_SCRIPT"):
        os.environ["GAPI_SCRIPT"] = os.path.join(here, "google_api.py")

    fake = [{"video_id": vid, "title": "", "channel_id": ch_id, "channel_name": ch_name}]
    streams = ym.check_if_live(fake)
    print(f"check_if_live({vid}) -> {len(streams)} stream(s)")
    if not streams:
        print("✗ not a live stream (or API 429 / ended). nothing injected.")
        return
    st = ym.load_state()
    now = datetime.now(ICT)
    ym.update_stream_state(st, streams, now)
    ym.append_local_jsonl(streams, now)
    ym.save_state(st)
    s = streams[0]
    print(f"✓ INJECTED: {s['channel_name']} | {s['title']} | {s['concurrent_viewers']:,} viewers")

if __name__ == "__main__":
    main()
