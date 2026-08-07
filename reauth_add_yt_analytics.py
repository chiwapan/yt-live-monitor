#!/usr/bin/env python3
"""Re-auth Google token ให้มี scope yt-analytics.readonly (manual flow, ไม่ต้อง browser บนเครื่อง).

รัน → พิมพ์ลิงก์ → เปิดลิงก์ใน browser (เครื่องไหนก็ได้) → รับ code → วางกลับ → token ใหม่
"""
import sys, json
from pathlib import Path

TOKEN_PATH = Path("/opt/data/google_token.json")
CLIENT_SECRET_PATH = Path("/opt/data/google_client_secret.json")

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

def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("⚠️ ต้องรันด้วย python ที่มี google_auth_oauthlib")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"  # manual code (out-of-band)

    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline",
                                         include_granted_scopes="true")
    print("=" * 70)
    print("1. เปิดลิงก์นี้ใน browser (เครื่องไหนก็ได้ ที่ login Google account ของช่อง):")
    print(auth_url)
    print("=" * 70)
    print("2. รับ permission (Advanced → Allow) แล้ว Google จะให้ code")
    code = input("3. วาง authorization code ที่นี่ แล้วกด Enter: ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    payload = json.loads(creds.to_json())
    # ถ้าไม่มี refresh_token ใช้ของเดิม (ถ้าเลข client เดียวกัน)
    if not payload.get("refresh_token"):
        try:
            old = json.loads(TOKEN_PATH.read_text())
            if old.get("refresh_token") and old.get("client_id") == payload.get("client_id"):
                payload["refresh_token"] = old["refresh_token"]
                print("ℹ️ reuse refresh_token เดิม (client เดียวกัน)")
        except Exception:
            pass

    TOKEN_PATH.write_text(json.dumps(payload, indent=2))
    print("\n✅ TOKEN ใหม่เขียนแล้ว:", TOKEN_PATH)
    print("   scopes:", len(payload.get("scopes", [])), "ตัว")
    print("   มี refresh_token:", bool(payload.get("refresh_token")))
    print("   มี yt-analytics.readonly:", any("yt-analytics" in s for s in payload.get("scopes", [])))

if __name__ == "__main__":
    main()