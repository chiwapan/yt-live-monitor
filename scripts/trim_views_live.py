#!/usr/bin/env python3
"""Trim views_live.jsonl to RETENTION_DAYS, archive dropped lines to backup_trim/.
In-place rewrite (truncate+write) to preserve inode — safe for Docker bind mounts.
Idempotent: exits fast if nothing older than cutoff."""
import json, gzip, os, sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "views_live.jsonl")
ARC_DIR = os.path.join(BASE, "backup_trim")
RETENTION_DAYS = 14

def main():
    if not os.path.exists(SRC):
        print("no file, nothing to do"); return 0
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    tmp = SRC + ".trimtmp"
    os.makedirs(ARC_DIR, exist_ok=True)
    arc_path = os.path.join(ARC_DIR, f"views_live_trim_{datetime.now():%Y%m%d}.jsonl.gz")

    kept = dropped = bad = 0
    with open(SRC) as fin, open(tmp, "w") as fout, gzip.open(arc_path, "wt") as arc_f:
        for line in fin:
            if not line.strip():
                continue
            try:
                ts = json.loads(line)["ts"]
            except Exception:
                bad += 1
                fout.write(line)  # keep unparseable lines rather than lose data
                kept += 1
                continue
            if ts >= cutoff:
                fout.write(line); kept += 1
            else:
                arc_f.write(line); dropped += 1

    if dropped == 0:
        os.remove(tmp)
        if os.path.getsize(arc_path) == 0:
            os.remove(arc_path)
        print(f"nothing older than {cutoff}; kept={kept} bad={bad}")
        return 0

    # in-place swap preserving inode
    with open(tmp) as fsrc, open(SRC, "r+") as fdst:
        fdst.seek(0); fdst.truncate()
        while True:
            chunk = fsrc.read(1024 * 1024)
            if not chunk:
                break
            fdst.write(chunk)
        fdst.flush(); os.fsync(fdst.fileno())
    os.remove(tmp)
    print(f"cutoff={cutoff} kept={kept} archived={dropped} bad={bad} new_size={os.path.getsize(SRC)/1e6:.1f}MB -> {arc_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
