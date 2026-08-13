import json, collections
base = "/opt/data/projects/yt-live-monitor/"
per_ch = collections.defaultdict(set)
with open(base + "views_live.jsonl") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        cid = r.get("channel_id")
        vid = r.get("video_id")
        if cid and vid:
            per_ch[cid].add(vid)

out = {k: sorted(v) for k, v in per_ch.items()}
with open(base + "snapshot_seen.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

zid = "Zxyxt-7jz4o"
hits = {k for k, v in out.items() if zid in v}
print("chan count:", len(out), "| total vids:", sum(len(v) for v in out.values()))
print("Zxyxt in seed channels:", hits)
print("saved OK")