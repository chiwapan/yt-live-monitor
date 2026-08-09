#!/usr/bin/env python3
# Cross-check baseline: YT views (from views_live.jsonl) for videos published >= 2026-08-01
# vs Fanpage Karma (which pulls every video published since Aug 1st)
# Strategy: get publishedAt from YT Data API (playlistItems of uploads playlist),
# filter >= Aug 1, then join with latest view_count from views_live.jsonl.

import json, os, time, urllib.parse, urllib.request, urllib.error
from collections import defaultdict

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    # try load from .env
    envp = "/opt/data/projects/yt-live-monitor/.env"
    if os.path.exists(envp):
        for line in open(envp):
            if line.startswith("YOUTUBE_API_KEY="):
                API_KEY = line.strip().split("=",1)[1]

assert API_KEY, "YOUTUBE_API_KEY not found"

# Channel IDs monitored (from views_monitor.html CH map)
CH_IDS = [
 'UCrFDdD-EE05N7gjwZho2wqw','UCtc9-CS_FIZ7GGrm8--wsrQ','UC6x41swVZP3rEmy-ODxLMFA',
 'UCzMoibQRslh_1bTuW0YXc6A','UCXm0bpjlfB0AF-ZdPhT0K1A','UC5wKpLWxAZBZrunls3mzwEw',
 'UCirZPTc9IoKM_DsA9aKbc4g','UC4kPIfdCZrPqoQ94m6-eFsg','UC3WyfUir0HD8sFI4AVAl6SQ',
 'UCDAl2WdfkIbzhRNESXi-3lw','UCXUVnTEsLZBim_WlWxBvEwA','UC2OtDM92rLjt4mm43ED1Q-w',
 'UCKXg1i42GPbDZDDBs-dzweg','UCnMyW2tEZDWWYq-6VIdrDVA','UCbJfg1BrJ5hJPlVqDUUv8lg',
 'UC5TOFhyb_LxL2VG_Zenhpzw','UCk1v3FzlMu3r34LYgoHpH2w','UCtBu8Wb2BUoduUXJS9Uss7Q',
 'UC7FCQJFK1sfwD_uobB45Xng','UCq2_AaNWBd0kxzR1HL2yhsw','UCqZ3is1Z4ck-I0ObYFw8OEQ',
 'UCQ2ABjf4gcrF0-zfDLQhWFQ','UC3S5gtXjd522gCtjOkYRUwg','UceF5sxjXSdWq80n3RA9gBpw',
 'UC37k-Kxlc7rDpHLZTNytNDw','UCygWbILDfBfPN6xR3mrHXHA','UCzheDCNyul0tRvvoGycjz6A',
 'UC7d3VlqC5LvvIraCNHBFtjw','UCxT3t-i3nX4uAbvXEsyWmsA','UCJ6PZBK3kOYKBLmvKwdI1gg',
 'UCqUBA96OsqMgSFvTwLXY9yw','UCv1QMOzm4RPDtm8-JchAkkw','UCDI9EEC4ZstO4v-Sg8vlfBQ',
 'UCOFvLl4bKwCIZg0r4EBQLug','UCMtFuOVbM_T43hYLnRA4MEA',
]
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
 'UCxT3t-i3nX4uAbvXEsysWmsA':'suthichai live','UCJ6PZBK3kOYKBLmvKwdI1gg':'NationTV Live',
 'UCqUBA96OsqMgSFvTwLXY9yw':'TNN','UCv1QMOzm4RPDtm8-JchAkkw':'SiroteTalk',
 'UCDI9EEC4ZstO4v-Sg8vlfBQ':'อาร์ท เอกรัฐ','UCOFvLl4bKwCIZg0r4EBQLug':'ThaiPBSNews',
 'UCMtFuOVbM_T43hYLnRA4MEA':'Ejan : อีจัน',
}

SINCE = "2026-08-01T00:00:00Z"
VIEWS_JSONL = "/opt/data/projects/yt-live-monitor/views_live.jsonl"

def api_get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"yt-xcheck/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"  403 quota/rate — wait 60s (attempt {attempt+1})")
                time.sleep(60)
            else:
                raise
    raise RuntimeError("API failed after retries")

# 1) latest view_count per video_id from snapshot
print("Loading views_live.jsonl ...")
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
print(f"  {len(latest_view)} unique videos in snapshot")

# 2) get uploads playlist per channel
print("Fetching uploads playlists ...")
uploads_map = {}
ids_csv = ",".join(CH_IDS)
url = f"https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id={ids_csv}&key={API_KEY}"
data = api_get(url)
for it in data.get("items",[]):
    cid = it["id"]
    up = it["contentDetails"]["relatedPlaylists"]["uploads"]
    uploads_map[cid] = up
    time.sleep(0.2)
print(f"  got {len(uploads_map)} uploads playlists")

# 3) playlistItems, collect video_id + publishedAt >= SINCE
print("Scanning playlistItems for videos published since Aug 1 ...")
published_since = {}  # video_id -> (cid, publishedAt)
for cid, pl in uploads_map.items():
    nextp = None
    while True:
        url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={pl}&key={API_KEY}"
        if nextp: url += f"&pageToken={nextp}"
        d = api_get(url)
        for it in d.get("items",[]):
            pub = it["contentDetails"]["videoPublishedAt"]
            if pub >= SINCE:
                vid = it["contentDetails"]["videoId"]
                published_since[vid] = (cid, pub)
        nextp = d.get("nextPageToken")
        time.sleep(0.5)
        if not nextp: break

print(f"  videos published since Aug 1: {len(published_since)}")

# 4) join with view_count, summarize per channel
ch_videos = defaultdict(list)
for vid,(cid,pub) in published_since.items():
    vw = latest_view.get(vid,{}).get('view_count',0)
    try: vw=int(vw)
    except: vw=0
    ch_videos[cid].append((vid,pub,vw))

print("\n" + "="*72)
print(f"{'ช่อง':<20}{'คลิป>=1ส.ค.':>12}{'รวมวิว(สะสม)':>18}")
print("="*72)
total_v=0; total_n=0
for cid in CH_IDS:
    vs = ch_videos.get(cid,[])
    n=len(vs); v=sum(x[2] for x in vs)
    total_v+=v; total_n+=n
    print(f"{CH_NAMES.get(cid,cid)[:20]:<20}{n:>12}{v:>18,}")
print("="*72)
print(f"{'รวมทั้งหมด':<20}{total_n:>12}{total_v:>18,}")
print("\nNote: 'รวมวิว(สะสม)' = sum of lifetime view_count of videos published since Aug 1.")
print("This matches Fanpage Karma's 'every video published since Aug 1st' scope.")
