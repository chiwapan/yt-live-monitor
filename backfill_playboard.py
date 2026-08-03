#!/usr/bin/env python3
"""
backfill_playboard.py — Idempotent Playboard HTML -> live_data.jsonl backfill

Usage:
    python3 backfill_playboard.py <html_file> [html_file2 ...]
    python3 backfill_playboard.py --scan-dir /opt/data/cache/documents

Extracts the hidden a11y table from Playboard chart HTML, resolves title +
actualStartTime via YouTube API (needs YOUTUBE_API_KEY in .env), and appends
rows to live_data.jsonl with full dedup. Safe to re-run any number of times.

Time cells come in two shapes:
    "HH:MM"              -> date must come from API actualStartTime or title
    "MM.DD / HH:MM"      -> date embedded in cell (ICT, year 2026/2569)
"""
import json, os, re, sys, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "live_data.jsonl")
CHANNEL = "ข่าวช่อง8"
YEAR = "2026"  # พ.ศ. 2569

def load_key():
    env = os.path.join(BASE, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("YOUTUBE_API_KEY="):
                return line.strip().split("=", 1)[1]
    return os.environ.get("YOUTUBE_API_KEY", "")

API_KEY = load_key()

def api_video(vid):
    """Return (title, actualStartTime) or (None, None) if not found."""
    url = ("https://www.googleapis.com/youtube/v3/videos"
           f"?part=liveStreamingDetails,snippet&id={vid}&key={API_KEY}")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.load(r)
        items = d.get("items", [])
        if not items:
            return None, None
        title = items[0]["snippet"]["title"]
        start = items[0].get("liveStreamingDetails", {}).get("actualStartTime", "")
        return title, start
    except Exception as e:
        print(f"  ! API error for {vid}: {e}", file=sys.stderr)
        return None, None

def parse_html(path):
    """Return (video_id, [(ts_time, viewers), ...]) or None."""
    html = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r'playboard\.co/en/video/([A-Za-z0-9_-]{6,})', html)
    if not m:
        return None
    vid = m.group(1)
    # hidden a11y table rows
    rows = re.findall(r'<tr><td>([^<]+)</td><td>([^<]*)</td>', html)
    data = []
    for cell, val in rows:
        cell, val = cell.strip(), val.strip().replace(",", "")
        if not val or not re.match(r'^\d+$', val):
            continue
        # shape 1: "MM.DD / HH:MM"
        m2 = re.match(r'(\d{2})\.(\d{2})\s*/\s*(\d{2}):(\d{2})', cell)
        if m2:
            mo, dd, hh, mi = m2.groups()
            data.append((f"{YEAR}-{mo}-{dd} {hh}:{mi}:00", int(val)))
            continue
        # shape 2: "HH:MM"
        m3 = re.match(r'(\d{2}):(\d{2})', cell)
        if m3:
            data.append((f"{m3.group(1)}:{m3.group(2)}", int(val)))
    return (vid, data) if data else None

def date_from_title(title):
    """Try '16 กรกฎาคม 2569' / '16-07-69' patterns -> '2026-07-16'."""
    th_months = {"มกราคม":"01","กุมภาพันธ์":"02","มีนาคม":"03","เมษายน":"04",
                 "พฤษภาคม":"05","มิถุนายน":"06","กรกฎาคม":"07","สิงหาคม":"08",
                 "กันยายน":"09","ตุลาคม":"10","พฤศจิกายน":"11","ธันวาคม":"12"}
    m = re.search(r'(\d{1,2})\s*(' + '|'.join(th_months) + r')', title)
    if m:
        return f"{YEAR}-{th_months[m.group(2)]}-{int(m.group(1)):02d}"
    m = re.search(r'(\d{2})-(\d{2})-(\d{2})', title)
    if m:
        dd, mo, yy = m.groups()
        # พ.ศ. 2 หลัก (เช่น 69 = 2569) → ค.ศ. = พ.ศ. - 543
        return f"{2500 + int(yy) - 543:04d}-{mo}-{dd}"
    return None

def load_existing():
    existing = {}  # (video_id, ts) -> True
    if not os.path.exists(DATA):
        return existing
    with open(DATA) as f:
        for line in f:
            try:
                j = json.loads(line)
                existing[(j.get("video_id"), j.get("ts"))] = True
            except Exception:
                pass
    return existing

def ingest(path, existing):
    parsed = parse_html(path)
    if not parsed:
        print(f"SKIP {os.path.basename(path)} — ไม่เจอ Playboard chart/table")
        return 0
    vid, data = parsed
    title, start = api_video(vid)
    if title is None:
        print(f"SKIP {vid} — API ไม่พบวิดีโอ (ลบ/private) และไม่มี fallback title")
        return 0
    # resolve date for HH:MM-only rows
    need_date = any(len(ts) <= 5 for ts, _ in data)
    day = None
    if need_date:
        if start:
            # actualStartTime is UTC; chart is ICT (+7)
            from datetime import datetime, timedelta
            dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=7)
            day = dt.strftime("%Y-%m-%d")
        else:
            day = date_from_title(title)
        if not day:
            print(f"SKIP {vid} — หาวันที่ไม่ได้ (ไม่มี actualStartTime / date ใน title)")
            return 0
    url = f"https://www.youtube.com/watch?v={vid}"
    added = 0
    with open(DATA, "a") as f:
        for ts, v in data:
            if len(ts) <= 5:  # HH:MM
                ts = f"{day} {ts}:00"
            if (vid, ts) in existing:
                continue
            f.write(json.dumps({"ts": ts, "video_id": vid, "title": title,
                                "viewers": v, "channel": CHANNEL, "url": url,
                                "actual_start": start or ""}, ensure_ascii=False) + "\n")
            existing[(vid, ts)] = True
            added += 1
    peak = max(v for _, v in data)
    print(f"{'OK  ' if added else 'DUP '}{vid}  +{added:>2} rows (peak {peak:,})  {title[:45]}")
    return added

def main():
    args = sys.argv[1:]
    files = []
    if "--scan-dir" in args:
        d = args[args.index("--scan-dir") + 1] if len(args) > args.index("--scan-dir") + 1 else "/opt/data/cache/documents"
        files = sorted(os.path.join(d, f) for f in os.listdir(d)
                       if f.endswith(".txt") or f.endswith(".html"))
    else:
        files = args
    if not files:
        print(__doc__); sys.exit(1)
    existing = load_existing()
    total = sum(ingest(p, existing) for p in files)
    print(f"\nรวม: +{total} rows")

if __name__ == "__main__":
    main()
