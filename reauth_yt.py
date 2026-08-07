#!/usr/bin/env python3
"""Re-auth ย้อน YouTube Analytics — 2 ขั้นตอน (no stdin blocking, headless-safe).

ขั้น 1: python reauth_yt.py url        → พิมพ์ OAuth URL + บันทึก PKCE state ลง /tmp/reauth_yt_state.json
ขั้น 2: python reauth_yt.py code CODE  → แลก code ด้วย state ที่บันทึกไว้ → write token

เพราะ background process ไม่อาจรอ input() → ต้องแยกสร้างลิงก์ กับ แลก code เป็นคนละ process
"""
import sys, json
from pathlib import Path

TOKEN_PATH = Path("/opt/data/google_token.json")
CLIENT_SECRET_PATH = Path("/opt/data/google_client_secret.json")
STATE_PATH = Path("/tmp/reauth_yt_state.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def make_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    flow.redirect_uri = "http://localhost:1"  # OOB ถูก deprecate แล้ว → ใช้ localhost
    return flow


def step_url():
    flow = make_flow()
    url, state = flow.authorization_url(prompt="consent", access_type="offline",
                                        include_granted_scopes="true")
    # บันทึก verifier + state ไว้สำหรับขั้นแลก code
    STATE_PATH.write_text(json.dumps({
        "code_verifier": flow.code_verifier,
        "state": state,
        "client_config": flow.client_config,
    }))
    print(url)


def step_code(code):
    from google_auth_oauthlib.flow import InstalledAppFlow
    st = json.loads(STATE_PATH.read_text())
    from google_auth_oauthlib.flow import InstalledAppFlow
    # โหลดจาก client_secret file ตรงๆ ไม่ใช้ st["client_config"] (เก็บ format ผิด)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), SCOPES, code_verifier=st["code_verifier"])
    flow.redirect_uri = "http://localhost:1"
    # Google ส่ง granted_scopes เดิมรวมกลับมา (adwords/analytics/webmasters ฯลฯ)
    # oauthlib ถือว่า scope เปลี่ยน = warning → เปลี่ยนเป็น error
    # แก้: แลก token ด้วย raw HTTP ไม่ผ่าน oauthlib validation
    import requests
    client_secret = json.loads(CLIENT_SECRET_PATH.read_text())["installed"]
    resp = requests.post(client_secret["token_uri"], data={
        "code": code.strip(),
        "client_id": client_secret["client_id"],
        "client_secret": client_secret["client_secret"],
        "redirect_uri": "http://localhost:1",
        "grant_type": "authorization_code",
        "code_verifier": st["code_verifier"],
    })
    if resp.status_code != 200:
        print("❌ token exchange failed:", resp.text)
        return
    token_data = resp.json()
    payload = {
        "token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": client_secret["token_uri"],
        "client_id": client_secret["client_id"],
        "client_secret": client_secret["client_secret"],
        "scopes": token_data.get("scope", "").split(),
        "type": "authorized_user",
    }
    if not payload.get("refresh_token"):
        try:
            old = json.loads(TOKEN_PATH.read_text())
            if old.get("refresh_token") and old.get("client_id") == payload.get("client_id"):
                payload["refresh_token"] = old["refresh_token"]
                print("ℹ️ reuse refresh_token เดิม (client เดียวกัน)")
        except Exception:
            pass
    TOKEN_PATH.write_text(json.dumps(payload, indent=2))
    print("✅ TOKEN ใหม่เขียนแล้ว:", TOKEN_PATH)
    print("   scopes:", len(payload.get("scopes", [])), "ตัว")
    has_yt = any("yt-analytics" in s for s in payload.get("scopes", []))
    has_rf = bool(payload.get("refresh_token"))
    print("   yt-analytics.readonly:", has_yt)
    print("   refresh_token:", has_rf)
    if has_yt and has_rf:
        print("READY")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "url":
        step_url()
    elif len(sys.argv) >= 3 and sys.argv[1] == "code":
        step_code(sys.argv[2])
    else:
        print("usage: reauth_yt.py url | reauth_yt.py code <CODE>")
        sys.exit(1)