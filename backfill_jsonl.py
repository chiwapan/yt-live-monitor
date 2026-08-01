#!/usr/bin/env python3
"""One-time backfill: pull Raw tab from Google Sheets → local JSONL."""
import json, subprocess, os, sys

# Load .env
env = {}
env_path = os.path.join(os.path.dirname(__file__), ".env")
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

SHEET_ID = env["YT_SHEET_ID"]
GAPI = "/opt/data/skills/productivity/google-workspace/scripts/google_api.py"
PY = "/opt/hermes/.venv/bin/python3"
JSONL = os.path.join(os.path.dirname(__file__), "live_data.jsonl")

result = subprocess.run(
    [PY, GAPI, "sheets", "get", SHEET_ID, "Raw!A:F"],
    capture_output=True, text=True, timeout=30
)
rows = json.loads(result.stdout)
print(f"Raw rows from Sheets: {len(rows)}")

count = 0
with open(JSONL, "a") as f:
    for row in rows[1:]:
        if len(row) < 6:
            continue
        ts, vid, title, viewers, channel, url = row[:6]
        try:
            v = int(str(viewers).replace(",", ""))
        except:
            continue
        f.write(json.dumps({
            "ts": ts, "video_id": vid, "title": title[:100],
            "viewers": v, "channel": channel, "url": url, "actual_start": "",
        }, ensure_ascii=False) + "\n")
        count += 1

print(f"Backfilled {count} rows → {JSONL}")
