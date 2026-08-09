#!/usr/bin/env python3
# FAST cross-check: YT views (views_live.jsonl) for videos published >= 2026-08-01
# vs Fanpage Karma (every video published since Aug 1st).
# Fast path: take video_ids already in snapshot -> videos.list batch (50/call) -> publishedAt.
# ~58 API calls instead of scanning every uploads playlist page.

import json, os, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    for line in open("/opt/data/projects/yt-live-monitor/.env"):
        if line.startswith("YOUTUBE_API_KEY="):
            API_KEY = line.strip().split("=",1)[1]
assert API_KEY, "YOUTUBE_API_KEY not found"

CH_NAMES = {
 'UCrFDdD-EE05N7gjwZho2wqw':'ThaiRath News','UCtc9-CS_FIZ7GGrm8--wsrQ':'ThaiRath Variety',
 'UC6x41swVZP3rEmy-ODxLMFA':'ข่าวช่อง8','UCzMoibQRslh_1bTuW0YXc6A':'Amarin TV',
 'UCXm0bpjlfB0AF-ZdPhT0K1A':'โหนกระแส','UC5wKpLWxAZBZrunls3mzwEw':'เรื่องเล่าเช้านี้',
 'UCirZPTc9IoKM_DsA9aKbc4g':'ครอบครัวข่าว3','UC4kPIfdCZrPqoQ94m6-eFsg':'สรยุทธ กรรมกรข่าว',
 'UC3WyfUir0HD8sFI4AVAl6SQ':'ข่าวเวิร์คพอยท์ 23','UCDAl2WdfkIbzhRNESXi-3lw':'Dailynews Online',
 'UCXUVnTEsLZBim_WlWxBvEwA':'Ch7HD','UC2OtDM92rLjt4mm43ED1Q-w':'Ch7HDNews',
 'UCKXg1i42GPbDZDDBs-dzweg':'TERO ENTERTAINMENT','UCnMyW2tEZDWWYq-6VIdrDVA':'Phutta Talk',
 'UCbJfg1BrJ5hJPlVqDUUv8lg':'sondhitalk','UC5TOFhyb_LxL2VG_Zenhpzw':'Thai PBS',
 'UCk1v3FzlMu3r34LYgoHpH2w':'THE STANDARD','UCtBu8Wb2BUoduUXJS9Uss7Q':'ช่อง8 Thai Ch8',
 'UC7FCQJFK1sfwD_uobB45Xng':'PPTV HD 36','UCq2_AaNWBd0kxzR1HL2yhsw':'terodigital',
 'UCqZ3is1Z4ck-I0ObYFw8OEQ':'ข่าวช่องวัน','UCQ2ABjf4gcrF0-zfDLQhWFQ':'TODAY',
 'UC3S5gtXjd522gCtjOkYRUwg':'matichon tv','UceF5sxjXSdWq80n3RA9gBpw':'TOP NEWS LIVE',
 'UC37k-Kxlc7rDpHLZTNytNDw':'Thairath Sport','UCygWbILDfBfPN6xR3mrHXHA':'News1',
 'UCzheDCNyul0tRvvoGycjz6A':'Jomquan','UC7d3VlqC5LvvIraCNHBFtjw':'แนวหน้าออนไลน์',
 'UCxT3t-i3nX4uAbvXEsyWmsA':'suthichai live','UCJ6PZBK3kOYKBLmvKwdI1gg':'NationTV Live',
 'UCqUBA96OsqMgSFvTwLXY9yw':'TNN','UCv1QMOzm4RPDtm8-JchAkkw':'SiroteTalk',
 'UCDI9EEC4ZstO4v-Sg8vlfBQ':'อาร์ท เอกรัฐ','UCOFvLl4bKwCIZg0r4EBQLug':'ThaiPBSNews',
 'UCMtFuOVbM_T43hYLnRA4MEA':'Ejan : อีจัน',
}
SINCE = "2026-08-01T00:00:00Z"
VIEWS_JSONL = "/opt/data/projects/yt-live-monitor/views_live.jsonl"

def api_get(url):
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"yt-xcheck-fast/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print("  403 — wait 60s"); time.sleep(60)
            else:
                raise
    raise RuntimeError("API failed")

# 1) latest view_count per video_id
print("Load snapshot ...")
latest_view = {}
with open(VIEWS_JSONL) as f:
    for line in f:
        line=line.strip()
        if not line: continue
        r=json.loads(line)
        vid=r.get('video_id','')
        if not vid: continue
        if vid not in latest_view or r.get('ts','') > latest_view[vid].get('ts',''):
            latest_view[vid]=r
print(f"  {len(latest_view)} unique videos")

# 2) videos.list batch -> publishedAt
vids = list(latest_view.keys())
print(f"Fetching publishedAt for {len(vids)} videos (batch 50) ...")
pub_map = {}  # vid -> publishedAt
for i in range(0, len(vids), 50):
    batch = vids[i:i+50]
    url = "https://www.googleapis.com/youtube/v3/videos?part=snippet&id=" + ",".join(batch) + "&key=" + API_KEY
    d = api_get(url)
    for it in d.get("items",[]):
        vid = it["id"]
        pub = it["snippet"].get("publishedAt","")
        pub_map[vid] = pub
    time.sleep(0.3)
print(f"  got publishedAt for {len(pub_map)} videos")

# 3) filter >= SINCE, summarize per channel
ch_videos = defaultdict(list)
for vid, pub in pub_map.items():
    if pub >= SINCE:
        r = latest_view.get(vid,{})
        cid = r.get('channel_id','')
        try: vw = int(r.get('view_count',0))
        except: vw = 0
        ch_videos[cid].append((vid, pub, vw))

print("\n" + "="*72)
print(f"{'ช่อง':<20}{'คลิป>=1ส.ค.':>12}{'รวมวิว(สะสม)':>18}")
print("="*72)
total_v=0; total_n=0
for cid in CH_NAMES:
    vs = ch_videos.get(cid,[])
    n=len(vs); v=sum(x[2] for x in vs)
    total_v+=v; total_n+=n
    print(f"{CH_NAMES[cid][:20]:<20}{n:>12}{v:>18,}")
print("="*72)
print(f"{'รวมทั้งหมด':<20}{total_n:>12}{total_v:>18,}")
print("\nScope: sum of lifetime view_count of videos published since Aug 1 (matches Karma).")
