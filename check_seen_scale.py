import json, collections
base = "/opt/data/projects/yt-live-monitor/"
seen = json.load(open(base + "snapshot_seen.json"))
print("type:", type(seen).__name__)
for cid, vids in seen.items():
    print(cid, ":", len(vids), "vids")
    if "Zxyxt-7jz4o" in vids:
        print("   >>> Zxyxt อยู่ช่องนี้ ตำแหน่ง (sorted):", sorted(vids).index("Zxyxt-7jz4o"))
        print("   >>> ลำดับใน set (ไม่เรียง): ไม่มีความหมาย แต่บ่งว่า cap 60 จะพลาด")