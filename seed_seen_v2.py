import json
base = "/opt/data/projects/yt-live-monitor/"
# seed per-channel เป็น dict {cid: {vid: published_ts}} — เรียงตาม published ใหม่สุดก่อน
# ใช้ views_month (มี published_at จริง) เป็น source of truth
pub_of = {}  # vid -> published_at
with open(base + "views_month.jsonl") as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("video_id") and r.get("published_at"):
            pub_of[r["video_id"]] = r["published_at"]

with open(base + "views_live.jsonl") as f:
    rows = [json.loads(l) for l in f if l.strip()]
per_ch = {}
for r in rows:
    cid = r.get("channel_id")
    vid = r.get("video_id")
    if not cid or not vid: continue
    per_ch.setdefault(cid, {})
    ts = pub_of.get(vid, "2000-01-01T00:00:00Z")
    if vid not in per_ch[cid]:
        per_ch[cid][vid] = ts
    # นำ ts ใหม่สุด (ดูจาก published ใน month) — เก็บ ts ที่"ใหม่กว่า"
    else:
        cur = per_ch[cid][vid]
        if ts > cur:
            per_ch[cid][vid] = ts

with open(base + "snapshot_seen.json", "w", encoding="utf-8") as f:
    json.dump(per_ch, f, ensure_ascii=False)

# verify: ThaiRath มี 973, Zxyxt ts อะไร, เรียง new-first ตัวแรก 60 เป็นใคร
th = per_ch.get("UCrFDdD-EE05N7gjwZho2wqw", {})
print("Thairath seen:", len(th))
print("Zxyxt ts:", th.get("Zxyxt-7jz4o"))
sorted_th = sorted(th.items(), key=lambda kv: kv[1], reverse=True)
print("top5 recent ของ Thairath:")
for vid, ts in sorted_th[:5]:
    print("  ", vid, ts)
print("Zxyxt อยู่ใน recent-first 60 ตัวแรก:", "Zxyxt-7jz4o" in [v for v, _ in sorted_th[:60]])
print("chan count:", len(per_ch), "| total:", sum(len(v) for v in per_ch.values()))
print("saved OK")