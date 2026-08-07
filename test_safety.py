#!/usr/bin/env python3
"""Regression test — ยืนยันว่า:
  1. dev run (bare) ถูกบล็อกไม่ให้ใช้ key จริง (YT_DEMO_MODE, key ปลอม)
  2. main() ใน demo mode วิ่งจบ offline ไม่ยิง network ไม่เขียน state โปรดักชัน
  3. production (YT_LIVE_PRODUCTION=1) ใช้ key จริงจาก .env
ใช้อัปเดต regressions ทุกครั้งที่แก้ collector logic.
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "yt-live-daily.py")


def load(env):
    # จำลองสภาพแวดล้อมใหม่ — ดร็อป env ก่อนทุกครั้ง
    saved = {}
    for k in list(os.environ):
        if k.startswith("YT_") or k in ("STATE_FILE", "LIVE_JSONL", "YOUTUBE_API_KEYS", "YOUTUBE_API_KEY"):
            saved[k] = os.environ.pop(k)
    for k, v in env.items():
        os.environ[k] = v
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("yt_live_m", SRC)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        # คืน env เดิม
        for k in list(os.environ):
            if k.startswith("YT_") or k in ("STATE_FILE", "LIVE_JSONL", "YOUTUBE_API_KEYS", "YOUTUBE_API_KEY"):
                os.environ.pop(k, None)
        os.environ.update(saved)


def test_dev_blocked():
    """dev run บน repo โปรดักชัน + มี key ใน env → ต้องโดน guard ไม่ให้ใช้ key จริง"""
    # จำลอง: มี key ดูเหมือนจริงใน env, ไม่ตั้ง YT_LIVE_PRODUCTION, STATE_FILE = repo prod
    m = load({"YOUTUBE_API_KEYS": "AIzaSyFAKE_TESTKEY_1234567890"})
    assert m.API_KEYS == ["YT_LIVE_TEST_KEY_ONLY"], f"dev ไม่บล็อก: {m.API_KEYS}"
    assert m.DEMO_MODE is True, "DEMO_MODE ไม่เปิด"
    # ยืนยันว่าไม่ใช้ key ปลอมที่ใส่เข้าไป (guide ต้องแทนที่ key จริง)
    assert m.API_KEYS != ["AIzaSyFAKE_TESTKEY_1234567890"], "key ปลอมรั่วเข้า!"
    print("✓ dev run ถูกบล็อกไม่ใช้ key จริง")


def test_prod_uses_real_keys():
    """production (YT_LIVE_PRODUCTION=1) ต้องใช้ key ที่ให้ไว้ ไม่แทนที่ (ต่างจาก dev)"""
    m = load({
        "YT_LIVE_PRODUCTION": "1",
        "YOUTUBE_API_KEYS": "AIzaSyREAL_PRODKEY_1234567890",
    })
    assert m.API_KEYS == ["AIzaSyREAL_PRODKEY_1234567890"], f"production แทนที่ key ผิด: {m.API_KEYS}"
    assert m.DEMO_MODE is False, "production ต้องไม่เปิด demo"
    print("✓ production ใช้ key ที่ให้ไว้ ไม่โดนแทนที่ ไม่เปิด demo")


def test_main_demo_offline():
    """main() ใน demo mode วิ่งจบ offline — เขียน tmp state/jsonl, ไม่แตะ network"""
    d = tempfile.mkdtemp()
    env = {
        "STATE_FILE": os.path.join(d, "state.json"),
        "LIVE_JSONL": os.path.join(d, "live.jsonl"),
        "YT_DEMO_MODE": "1",  # บังคับ offline — ห้ามแตะ network/key จริง เด็ดขาด
    }
    m = load(env)
    assert m.DEMO_MODE is True, "demo mode ต้องเปิดในการทดสอบ offline"
    m.main()
    assert os.path.exists(env["STATE_FILE"]), "main() ไม่เขียน state"
    assert os.path.exists(env["LIVE_JSONL"]), "main() ไม่เขียน live.jsonl"
    n = sum(1 for _ in open(env["LIVE_JSONL"]) if _.strip())
    print(f"✓ main() demo วิ่งจบ offline (state+jsonl เขียน, demo rows={n})")


if __name__ == "__main__":
    test_dev_blocked()
    test_prod_uses_real_keys()
    test_main_demo_offline()
    print("\nALL PASS ✅")