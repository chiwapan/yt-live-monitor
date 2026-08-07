#!/usr/bin/env python3
"""ตรวจสุขภาพ API key ทีละตัว — บอกว่า key ไหนใช้ได้/ตาย/เพราะอะไร

ใช้: python3 check_keys.py            # อ่าน key จาก .env
     python3 check_keys.py KEY1 KEY2  # ระบุเอง
1 call = 1 unit ต่อ key เท่านั้น
"""
import os
import re
import sys
import json
import urllib.request
import urllib.error

TEST_VIDEO = "dQw4w9WgXcQ"  # วิดีโอ public ที่ไม่มีวันหาย


def load_keys():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env) as f:
            txt = f.read()
    except FileNotFoundError:
        return []
    m = re.search(r"YOUTUBE_API_KEYS=([^\n]+)", txt)
    if m:
        return [k.strip() for k in m.group(1).split(",") if k.strip()]
    m = re.search(r"YOUTUBE_API_KEY=([^\n]+)", txt)
    return [m.group(1).strip()] if m else []


def check(k):
    url = ("https://www.googleapis.com/youtube/v3/videos"
           f"?part=snippet&id={TEST_VIDEO}&key={k}")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            json.loads(r.read())
        return "OK", "ใช้งานได้"
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            msg = body.get("error", {}).get("message", "")
            errs = body.get("error", {}).get("errors", [{}])
            reason = errs[0].get("reason", "?")
        except Exception:
            msg, reason = "", "?"
        return f"HTTP {e.code}", f"{reason}: {msg[:120]}"
    except Exception as e:
        return "ERR", str(e)[:120]


def main():
    keys = load_keys()
    if not keys:
        print("ไม่พบ API key")
        return 1
    print(f"ตรวจ {len(keys)} key\n")
    ok = 0
    for k in keys:
        status, detail = check(k)
        mark = "✅" if status == "OK" else "❌"
        if status == "OK":
            ok += 1
        print(f"{mark} {k[:12]}… [{status}] {detail}")
    print(f"\nสรุป: ใช้ได้ {ok}/{len(keys)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
