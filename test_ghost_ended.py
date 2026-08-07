#!/usr/bin/env python3
"""Regression — ยืนยันว่าวิดีโอที่จบแล้ว (มี actualEndTime) ไม่ถูกนับเป็น live
แม้ YouTube จะคืน concurrentViewers เก่าค้าง (ghost stream, บั๊ก HN-WTZiCuSA 2026-08-07)

รันแบบ offline (demo mode) — ไม่แตะ key จริง ไม่แตะ network
"""
import os
import sys
import json
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "yt-live-daily.py")

# ห้าม key จริงรั่วเข้าเด็ดขาด
for k in ("YOUTUBE_API_KEY", "YOUTUBE_API_KEYS", "YT_LIVE_PRODUCTION"):
    os.environ.pop(k, None)
os.environ["YT_DEMO_MODE"] = "1"  # บังคับ offline (แม้ไม่มี key)

spec = importlib.util.spec_from_file_location("yt_live_m", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
# ทดสอบ offline แท้ — แทรก response ล่วงหน้า
assert m.DEMO_MODE, "ต้องเป็น demo mode (ไม่แตะ network)"

# ── กรณี: วิดีโอจบแล้ว (actualEndTime) แต่ YouTube ยังคืน concurrentViewers ค้าง ──
_GHOST = {
    "kind": "youtube#videoListResponse",
    "items": [{
        "kind": "youtube#video",
        "id": "GHOST_ENDED",
        "snippet": {"title": "บางอย่าง (จบแล้ว)", "liveBroadcastContent": "none"},
        "liveStreamingDetails": {
            "concurrentViewers": "999999",          # ยอดค้างเก่า
            "actualStartTime": "2026-08-07T08:00:00Z",
            "actualEndTime": "2026-08-07T09:00:00Z",  # จบแล้วจริง
        },
    }],
}
_LIVE = {
    "kind": "youtube#videoListResponse",
    "items": [{
        "kind": "youtube#video",
        "id": "REAL_LIVE",
        "snippet": {"title": "สดเดี๋ยวนี้", "liveBroadcastContent": "live"},
        "liveStreamingDetails": {
            "concurrentViewers": "5000",
            "actualStartTime": "2026-08-07T09:30:00Z",
        },
    }],
}


class _Fake:
    pass


# stub yt_api: GHOST_ENDED ให้ทั้ง concurrent+actualEnd; REAL_LIVE ให้ live จริง
_orig_yt_api = m.yt_api
_calls = []


def _fake_yt_api(endpoint, params, _cost=None):
    _calls.append(params["id"])
    items = []
    for vid in params.get("id", "").split(","):
        if vid == "GHOST_ENDED":
            items.append(_GHOST["items"][0])
        elif vid == "REAL_LIVE":
            items.append(_LIVE["items"][0])
    if items:
        return {"kind": "youtube#videoListResponse", "items": items}
    return {}


m.yt_api = _fake_yt_api

state = {"streams": {
    "GHOST_ENDED": {"title": "x", "channel": "c", "url": "u", "last_viewers": 999999,
                    "last_seen": "2026-08-07 10:00:00", "peak_viewers": 999999},
    "REAL_LIVE": {"title": "y", "channel": "c", "url": "u", "last_viewers": 1,
                  "last_seen": "2026-08-07 10:00:00", "peak_viewers": 1},
}}

# save state แบบปลอมลง tmp
d = tempfile.mkdtemp()
sf = os.path.join(d, "state.json")
json.dump(state, open(sf, "w"))
m.STATE_FILE = sf

vids = [{"video_id": "GHOST_ENDED", "title": "x", "channel_id": "", "channel_name": "c"},
        {"video_id": "REAL_LIVE", "title": "y", "channel_id": "", "channel_name": "c"}]

live, confirmed, api_ok = m.check_if_live(vids)
live_ids = {s["video_id"] for s in live}

assert "GHOST_ENDED" not in live_ids, f"Ghost จบแล้ว ยังติด live! {live_ids}"
assert "GHOST_ENDED" in confirmed, "ghost ควรถูกยืนยันว่าจบ"
assert "REAL_LIVE" in live_ids, "live จริงต้องติด"
print(f"✓ ghost (จบแล้ว) ไม่ติด live, เข้า confirmed_ended; live จริงติด: {live_ids}")
print("✓ ทุกเคสผ่าน")

# คืน yt_api เดิม
m.yt_api = _orig_yt_api
print("\nALL PASS ✅")
