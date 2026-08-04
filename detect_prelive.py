import json, collections, datetime

path = '/opt/data/projects/yt-live-monitor/live_data.jsonl'
rows = [json.loads(l) for l in open(path)]

by_vid = collections.defaultdict(list)
for r in rows:
    by_vid[r['video_id']].append(r)

def parse(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

affected = {}
total_drop = 0
for vid, rs in by_vid.items():
    rs.sort(key=lambda r: r['ts'])
    lead_end = 0
    while lead_end < len(rs) and rs[lead_end]['viewers'] <= 20:
        lead_end += 1
    max_val_after = max((r['viewers'] for r in rs[lead_end:]), default=0) if lead_end < len(rs) else 0
    if lead_end >= 8 and max_val_after > 100:
        affected[vid] = (lead_end, len(rs), max_val_after)
        total_drop += lead_end

print("Affected videos (vid: (leading rows to drop, total rows, real peak)):")
for vid,(d,t,p) in sorted(affected.items(), key=lambda x:-x[1][2]):
    titles = set(r['title'] for r in by_vid[vid])
    print(f"  {vid}: drop {d}/{t} rows, real peak {p} | {list(titles)[0][:60]}")
print("\nTotal rows to drop:", total_drop)
print("Total affected videos:", len(affected))
