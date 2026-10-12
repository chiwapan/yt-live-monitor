#!/usr/bin/env python3
"""
build_thaipbs_programs.py — ถอด "ชื่อรายการ" ของไทยพีบีเอสลงไฟล์ jsonl ให้ทุก consumer ใช้ร่วมกัน

ผลลัพธ์ (2 ไฟล์, dir เดียวกับ live_data.jsonl):
  1. thaipbs_video_programs.jsonl  → ต่อบันทึก: video_id + ts_first/last + peak/avg + program + title
  2. thaipbs_programs.jsonl        → aggregate ต่อรายการ: ตอน/วันที่, mean, median, p90, peak, ช่วงวันที่

เขียนไฟล์ใหม่เสมอ (atomic tmp+rename ใช้ได้ เพราะ 2 ไฟล์นี้ NOT bind-mounted ใน Docker)
⚠️ ห้ามใช้ script นี้แตะ live_data.jsonl (เป็น Docker single-file bind mount — ดู AGENTS.md)

matching: keyword scan ทั้ง title (ไม่ใช่แค่ segment แรก) เพราะไทยพีบีเอสวางชื่อรายการท้าย title
  e.g. "🔴 [Live] <พาดหัว> | ตอบโจทย์ | 4 ส.ค. 69"

rerun: เมื่อมีข้อมูลใหม่ → python3 build_thaipbs_programs.py
"""
import os, re, json, statistics, collections
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "live_data.jsonl")
OUT_MAP = os.path.join(HERE, "thaipbs_video_programs.jsonl")
OUT_AGG = os.path.join(HERE, "thaipbs_programs.jsonl")

CHANNELS = {"Thai PBS", "ThaiPBSNews"}

# (program_name, keywords) — เรียงจาก specificity สูงไปต่ำ, match แบบ substring (lowercased)
# แก้/เพิ่มรายการที่นี่จุดเดียว แล้ว rerun → 2 ไฟล์อัปเดตตาม
PROGRAMS = [
    ("วันใหม่ไทยพีบีเอส",          ["วันใหม่"]),
    ("ชั่วโมงข่าวเสาร์-อาทิตย์",    ["ชั่วโมงข่าว"]),
    ("ข่าวเที่ยง",                ["ข่าวเที่ยง"]),
    ("ข่าวค่ำ",                   ["ข่าวค่ำ"]),
    ("ข่าวดึก",                   ["ข่าวดึก"]),
    ("ข่าวเจาะย่อโลก",             ["ข่าวเจาะย่อโลก"]),
    ("คุยให้คิด",                 ["คุยให้คิด"]),
    ("ตอบโจทย์",                  ["ตอบโจทย์"]),
    ("สมมุติว่า",                  ["สมมุติว่า"]),
    ("มุมการเมือง",                ["มุมการเมือง"]),
    ("จับตาสถานการณ์",             ["จับตาสถานการณ์"]),
    ("จับตารอบทิศ",                ["จับตารอบทิศ"]),
    ("ประจักษ์จับประเด็น",          ["ประจักษ์"]),
    ("ตรงประเด็น",                 ["ตรงประเด็น"]),
    ("ทุกทิศทั่วไทย",               ["ทุกทิศทั่วไทย"]),
    ("เสิร์ฟติดข่าว",               ["เสิร์ฟติดข่าว"]),
    ("คนสู้โรค Daily",             ["คนสู้โรค"]),
    ("สปอร์ตออนไลน์",              ["สปอร์ตออนไลน์"]),
    ("ทันโลกกับThaiPBS",           ["ทันโลก"]),
    ("ทันข่าว",                   ["ทันข่าว"]),
    ("Turning Point จุดเปลี่ยน",    ["turning point"]),
    ("สถานีประชาชน",               ["สถานีประชาชน"]),
    ("ไม่ตกข่าว",                  ["ไม่ตกข่าว"]),
    ("ไลฟ์วันนี้",                 ["ไลฟ์วันนี้"]),
    ("Policy Forum",              ["policy forum"]),
    ("Policy Easy นโยบายเข้าใจได้", ["policy easy"]),
    ("สาระดีสาระTalk",             ["สาระดี"]),
    ("ฟังเสียงประเทศไทย",           ["ฟังเสียงประเทศไทย"]),
    ("เสียงเปลี่ยนเมือง",           ["เสียงเปลี่ยนเมือง"]),
    ("VIPAvROOM",                 ["vipavroom"]),
    ("ยกพลคนน้ำพริก",              ["ยกพลคนน้ำพริก"]),
    ("วงแชร์",                    ["วงแชร์"]),
    ("ป็อปดีโคตร",                 ["ป็อปดีโคตร", "pop-d"]),
    ("นอกสำนวน",                  ["นอกสำนวน"]),
    ("หนูน้อยจ้าวเวหา",            ["หนูน้อยจ้าวเวหา"]),
    ("ศึกเรือยาวชิงจ้าวสายน้ำ",     ["เรือยาว"]),
    ("ศึกเรือเกยหาด",              ["เรือเกยหาด"]),
    ("ปั่นสู่ฝัน คนวัยมันส์",       ["ปั่นสู่ฝัน"]),
    ("WorldSkills Shanghai 2026",  ["worldskills"]),
    ("วิ่งเลย Running Day",        ["running day", "วิ่งเลย"]),
    ("กมธ.ว่าไง",                  ["กมธ. ว่าไง", "กมธ.ว่าไง"]),
    ("รายการพิเศษ",                ["รายการพิเศษ"]),
]
PREFIX_RE = re.compile(r"^[🔴🟠⚪🟡🔵\s\[\]]+")
CANDIDATE = [n for n, k in PROGRAMS]

def detect(title: str):
    t = (title or "").lower()
    for name, kws in PROGRAMS:
        if any(k in t for k in kws):
            return name
    return None

def prog_from_segments(title: str):
    """name = segment ท้าย (ก่อน trailing date) ถ้าตรงกับรายการที่รู้จัก, ไม่งั้น None
    ใช้เก็บ program_name แบบ human-readable ลง jsonl (ไม่ต้อง guess ใหม่ทุก consumer)"""
    segs = [s.strip() for s in PREFIX_RE.sub("", title or "").split("|") if s.strip()]
    def is_date(x):
        x = x.strip()
        return bool(re.fullmatch(r"(วันที่\s*)?\d{1,2}\s*[ก-๙]{0,4}\.?\s*\d{2,4}", x)
                   or re.fullmatch(r"(25)?\d{2}", x)
                   or re.fullmatch(r"\d{1,2}[/\.]\d{1,2}([/\.]\d{2,4})?", x))
    while segs and is_date(segs[-1]):
        segs = segs[:-1]
    if len(segs) >= 2:
        c = re.sub(r'^[\[\s]*(Live|LIVE|live|สด!?)[\]\s:!\-]*', "", segs[-1]).strip()
        c = re.sub(r"\s*\d{1,2}\s*[ก-๙]{0,4}\.?\s*\d{2,4}.*$", "", c).strip()
        low = c.lower()
        for name, kws in PROGRAMS:
            if any(k in low for k in kws):
                return name
    return None

def p90(vals):
    if not vals:
        return 0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]

def main():
    if not os.path.exists(DATA):
        raise SystemExit(f"not found: {DATA}")
    vids = {}
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("channel") not in CHANNELS:
                continue
            vid = d.get("video_id")
            v = d.get("viewers")
            if not vid or v is None:
                continue
            a = vids.setdefault(vid, {"titles": collections.Counter(), "vals": [], "ts": [],
                                      "ch": d.get("channel", ""), "url": d.get("url", "")})
            a["titles"][d.get("title", "")] += 1
            a["vals"].append(int(v))
            a["ts"].append(d.get("ts", ""))

    per_video = []
    for vid, a in vids.items():
        titles = [t for t, _ in a["titles"].most_common()]
        prog = None
        for t in titles:                      # union ทุก title variant กันชื่อโผล่แค่บาง snapshot
            prog = detect(t)
            if prog:
                break
        seg = None
        for t in titles:
            seg = prog_from_segments(t)
            if seg:
                break
        title = a["titles"].most_common(1)[0][0]
        per_video.append({
            "video_id": vid,
            "channel": a["ch"],
            "program": prog or "one_off_special",
            "program_from_title": seg or "",
            "title": title,
            "url": a["url"],
            "ts_first": min(a["ts"]),
            "ts_last": max(a["ts"]),
            "samples": len(a["vals"]),
            "avg_concurrent": round(statistics.mean(a["vals"]), 1),
            "median_concurrent": statistics.median(a["vals"]),
            "peak_concurrent": max(a["vals"]),
        })

    per_video.sort(key=lambda r: r["ts_first"])
    tmp = OUT_MAP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in per_video:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT_MAP)

    g = collections.defaultdict(list)
    for r in per_video:
        g[r["program"]].append(r)
    agg = []
    for p, items in g.items():
        vavgs = [i["avg_concurrent"] for i in items]
        peaks = [i["peak_concurrent"] for i in items]
        allv = []
        agg.append({
            "program": p,
            "episodes": len(items),
            "air_days": len({i["ts_first"][:10] for i in items}),
            "avg_concurrent_mean": round(statistics.mean(vavgs), 1),
            "avg_concurrent_median": round(statistics.median(vavgs), 1),
            "avg_concurrent_p90": round(p90(vavgs), 1),
            "peak_concurrent_max": max(peaks),
            "samples_total": sum(i["samples"] for i in items),
            "first_air": min(i["ts_first"] for i in items)[:10],
            "last_air": max(i["ts_first"] for i in items)[:10],
            "recurring": len(items) >= 5,
        })
    agg.sort(key=lambda x: -x["avg_concurrent_mean"])
    tmp = OUT_AGG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": {
            "source": "live_data.jsonl", "channels": sorted(CHANNELS),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "videos_total": len(per_video), "programs_defined": len(PROGRAMS),
            "note": "avg_concurrent_mean = ค่าเฉลี่ยของ avg_concurrent ต่อตอน (ไม่ใช่น้ำหนักด้วย duration)",
        }}, ensure_ascii=False) + "\n")
        for r in agg:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT_AGG)

    named = sum(1 for r in per_video if r["program"] != "one_off_special")
    print(f"videos: {len(per_video)} | tagged: {named} | one_off: {len(per_video)-named}")
    print(f"programs in agg: {len(agg)} (recurring: {sum(1 for a in agg if a['recurring'])})")
    print(f"wrote {OUT_MAP} ({os.path.getsize(OUT_MAP):,} B)")
    print(f"wrote {OUT_AGG} ({os.path.getsize(OUT_AGG):,} B)")

if __name__ == "__main__":
    main()
