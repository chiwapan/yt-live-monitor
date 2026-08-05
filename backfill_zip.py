#!/usr/bin/env python3
"""Backfill live_data.jsonl from YouTube Studio CSV zip.
Usage: python3 backfill_zip.py <zip_path> [--channel NAME] [--video-id ID] [--start "YYYY-MM-DD HH:MM:SS"]

Auto-detects channel from title keywords if not specified.
"""
import sys, os, csv, json, zipfile, io
from datetime import datetime, timedelta

JSONL = "/opt/data/projects/yt-live-monitor/live_data.jsonl"

CHANNEL_KEYWORDS = {
    "ThaiRath News": ["ไทยรัฐ", "thairath"],
    "ข่าวช่อง8": ["ช่อง8", "channel8", "ch8"],
    "Amarin TV": ["amarin", "อมรินทร์", "ทุบโต๊ะ"],
}

def detect_channel(title):
    t = title.lower()
    for ch, kws in CHANNEL_KEYWORDS.items():
        if any(k in t for k in kws):
            return ch
    return None

def parse_zip(zip_path):
    """Extract liveViewership CSV from zip, return rows.
    Reads CSV directly from zip entry (avoids filesystem filename-length limits
    that break extractall on long Thai titles)."""
    with zipfile.ZipFile(zip_path) as z:
        viewers_files = [n for n in z.namelist() if "liveViewership" in n]
        if not viewers_files:
            print("ERROR: no liveViewership CSV found in zip")
            sys.exit(1)
        with z.open(viewers_files[0]) as f:
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("zip_path")
    p.add_argument("--channel", default=None)
    p.add_argument("--video-id", default=None)
    p.add_argument("--start", default=None, help="Stream start time ICT: YYYY-MM-DD HH:MM:SS")
    args = p.parse_args()

    rows = parse_zip(args.zip_path)
    if not rows:
        print("ERROR: CSV empty"); sys.exit(1)

    # Get title from filename
    with zipfile.ZipFile(args.zip_path) as z:
        names = z.namelist()
    title_file = [n for n in names if "liveViewership" in n]
    title = title_file[0].replace("liveViewership_", "").replace(".csv", "").strip() if title_file else "Unknown"

    channel = args.channel or detect_channel(title)
    if not channel:
        print(f"ERROR: cannot detect channel from '{title}'. Use --channel")
        sys.exit(1)

    # Parse start time
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    else:
        print("ERROR: need --start 'YYYY-MM-DD HH:MM:SS' (stream start time ICT)")
        sys.exit(1)

    video_id = args.video_id or "unknown"

    # Load existing timestamps for dedup
    existing = set()
    if os.path.exists(JSONL):
        for line in open(JSONL):
            if not line.strip(): continue
            r = json.loads(line)
            if r.get("video_id") == video_id:
                existing.add(r["ts"])

    # Build new rows
    new_rows = []
    for row in rows:
        pos = int(row["Livestream position (seconds)"])
        viewers = int(row["Live concurrent viewers"])
        ts = start + timedelta(seconds=pos)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        if ts_str in existing:
            continue
        new_rows.append({
            "ts": ts_str,
            "video_id": video_id,
            "channel": channel,
            "title": title,
            "viewers": viewers,
            "source": "yt-studio-csv"
        })

    # Append
    with open(JSONL, "a") as f:
        for r in new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Summary
    all_pts = []
    for line in open(JSONL):
        if not line.strip(): continue
        r = json.loads(line)
        if r.get("video_id") == video_id and r["ts"].startswith(start.strftime("%Y-%m-%d")):
            all_pts.append(r)
    all_pts.sort(key=lambda r: r["ts"])
    peak = max(r["viewers"] for r in all_pts) if all_pts else 0
    print(f"✅ {channel} | {title[:50]}")
    print(f"   +{len(new_rows)} new (total {len(all_pts)}) | {all_pts[0]['ts'][11:16]}→{all_pts[-1]['ts'][11:16]} | peak {peak:,}")

if __name__ == "__main__":
    main()
