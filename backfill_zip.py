#!/usr/bin/env python3
"""Backfill live_data.jsonl from YouTube Studio CSV zip.

Usage:
  python3 backfill_zip.py <zip_path> --start "YYYY-MM-DD HH:MM:SS" [--channel NAME] [--video-id ID]
  python3 backfill_zip.py <zip_path> --start "YYYY-MM-DD HH:MM:SS" --dry-run

Notes:
- Reads liveViewership CSV directly from zip (no extract needed)
- Dedup key = (video_id, ts)
- If --video-id is omitted, generates deterministic synthetic ID from title+start
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta

DEFAULT_JSONL = "/opt/data/projects/yt-live-monitor/live_data.jsonl"

CHANNEL_KEYWORDS = {
    "ThaiRath News": ["ไทยรัฐ", "thairath"],
    "ข่าวช่อง8": ["ช่อง8", "channel8", "ch8"],
    "Amarin TV": ["amarin", "อมรินทร์", "ทุบโต๊ะ"],
}


def detect_channel(title: str):
    t = title.lower()
    for ch, kws in CHANNEL_KEYWORDS.items():
        if any(k in t for k in kws):
            return ch
    return None


def find_viewership_entry(zip_path: str):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    candidates = [n for n in names if "liveViewership" in n and n.lower().endswith(".csv")]
    if not candidates:
        return None
    return candidates[0]


def extract_title_from_entry(entry_name: str):
    title = entry_name
    title = re.sub(r"^.*liveViewership_", "", title)
    title = re.sub(r"\.csv$", "", title, flags=re.IGNORECASE)
    return title.strip() or "Unknown"


def parse_zip_rows(zip_path: str, entry_name: str):
    with zipfile.ZipFile(zip_path) as z:
        with z.open(entry_name) as f:
            return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def parse_int(v, default=0):
    try:
        return int(str(v).strip().replace(",", ""))
    except Exception:
        return default


def synthetic_video_id(title: str, start_str: str):
    key = f"{title}|{start_str}".encode("utf-8", errors="ignore")
    return "studio_" + hashlib.sha1(key).hexdigest()[:16]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("zip_path")
    p.add_argument("--start", required=False, default=None, help="Stream start time ICT: YYYY-MM-DD HH:MM:SS (optional; if omitted, infer date from title and use 00:00:00)")
    p.add_argument("--channel", default=None)
    p.add_argument("--video-id", default=None)
    p.add_argument("--title", default=None, help="Override title")
    p.add_argument("--output", default=DEFAULT_JSONL, help="JSONL path (default: live_data.jsonl)")
    p.add_argument("--dry-run", action="store_true", help="Parse + summarize only (no write)")
    args = p.parse_args()

    if not os.path.exists(args.zip_path):
        print(f"ERROR: zip not found: {args.zip_path}")
        sys.exit(1)

    start = None
    if args.start:
        try:
            start = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print("ERROR: --start must be format YYYY-MM-DD HH:MM:SS")
            sys.exit(1)

    entry = find_viewership_entry(args.zip_path)
    if not entry:
        print("ERROR: no liveViewership CSV found in zip")
        sys.exit(1)

    rows = parse_zip_rows(args.zip_path, entry)
    if not rows:
        print("ERROR: liveViewership CSV is empty")
        sys.exit(1)

    title = args.title or extract_title_from_entry(entry)
    channel = args.channel or detect_channel(title)
    if not channel:
        print(f"ERROR: cannot detect channel from title: {title!r}. Use --channel")
        sys.exit(1)

    if start is None:
        m = re.search(r"\|\s*(\d{1,2})\s*ก\.ค\.\s*69", title)
        if not m:
            print("ERROR: --start not provided and cannot infer date from title")
            sys.exit(1)
        day = int(m.group(1))
        start = datetime(2026, 7, day, 0, 0, 0)

    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    video_id = args.video_id or synthetic_video_id(title, start_str)

    # Load existing (video_id, ts) for dedupe
    existing = set()
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    if r.get("video_id") and r.get("ts"):
                        existing.add((r["video_id"], r["ts"]))
                except Exception:
                    continue

    new_rows = []
    for row in rows:
        pos = parse_int(row.get("Livestream position (seconds)"))
        viewers = parse_int(row.get("Live concurrent viewers"))
        ts = start + timedelta(seconds=pos)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        key = (video_id, ts_str)
        if key in existing:
            continue
        new_rows.append(
            {
                "ts": ts_str,
                "video_id": video_id,
                "channel": channel,
                "title": title,
                "viewers": viewers,
                "source": "yt-studio-csv",
            }
        )

    if not args.dry_run:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "a", encoding="utf-8") as f:
            for r in new_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Build summary on this batch + existing same video_id/day
    day_prefix = start.strftime("%Y-%m-%d")
    all_pts = []
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("video_id") == video_id and str(r.get("ts", "")).startswith(day_prefix):
                    all_pts.append(r)
    else:
        all_pts = new_rows[:]

    all_pts.sort(key=lambda r: r.get("ts", ""))
    peak = max((parse_int(r.get("viewers", 0)) for r in all_pts), default=0)

    mode = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"✅ [{mode}] {channel}")
    print(f"   video_id: {video_id}")
    print(f"   title: {title[:120]}")
    print(f"   output: {args.output}")
    if new_rows:
        print(
            f"   +{len(new_rows)} rows | {new_rows[0]['ts'][11:16]}→{new_rows[-1]['ts'][11:16]} | peak {peak:,}"
        )
    else:
        print("   +0 rows (all deduped)")


if __name__ == "__main__":
    main()
