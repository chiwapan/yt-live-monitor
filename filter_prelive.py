import json, collections

path = '/opt/data/projects/yt-live-monitor/live_data.jsonl'
rows = [json.loads(l) for l in open(path)]

by_vid = collections.defaultdict(list)
for r in rows:
    by_vid[r['video_id']].append(r)

drop_vid_lead = {}
for vid, rs in by_vid.items():
    rs.sort(key=lambda r: r['ts'])
    lead_end = 0
    while lead_end < len(rs) and rs[lead_end]['viewers'] <= 20:
        lead_end += 1
    max_val_after = max((r['viewers'] for r in rs[lead_end:]), default=0) if lead_end < len(rs) else 0
    if lead_end >= 8 and max_val_after > 100:
        drop_vid_lead[vid] = lead_end

kept = []
dropped = 0
for r in rows:
    vid = r['video_id']
    if vid in drop_vid_lead:
        rs = sorted(by_vid[vid], key=lambda x: x['ts'])
        # count leading low rows already processed; simpler: rebuild preserved set
        pass

# Simpler: rebuild per-video, keep rows after the leading noise run
out = []
dropped_count = 0
for vid, rs in by_vid.items():
    rs.sort(key=lambda r: r['ts'])
    if vid in drop_vid_lead:
        lead = drop_vid_lead[vid]
        dropped_count += lead
        rs = rs[lead:]
    out.extend(rs)

out.sort(key=lambda r: (r['video_id'], r['ts']))
with open(path, 'w') as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"Done. Removed {dropped_count} pre-live noise rows. Old total was {len(rows)}, new total is {len(out)}.")
