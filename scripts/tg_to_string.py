#!/usr/bin/env python3
"""Mavjud fayl-session (scripts/undiruv_user.session) ni QAYTA LOGIN QILMASDAN
Telethon StringSession satriga o'giradi — Railway env limiti (32KB) muammosining
yechimi (~350 belgi). Satr EKRANGA CHIQMAYDI — to'g'ridan clipboard'ga (pbcopy).

Ishlatish:  venv/bin/python scripts/tg_to_string.py
So'ng Railway → Variables → TG_SESSION_STRING = (paste).
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SESSION_FILE = HERE / "undiruv_user.session"


def ask(prompt, env=None):
    v = os.environ.get(env, "").strip() if env else ""
    if v:
        print(f"{prompt}: (env'dan olindi)")
        return v
    return input(f"{prompt}: ").strip()


def main():
    try:
        from telethon.sessions import SQLiteSession, StringSession
    except ImportError:
        print("XATO: telethon yo'q — avval: venv/bin/pip install telethon")
        return 1
    if not SESSION_FILE.exists():
        print(f"XATO: {SESSION_FILE} topilmadi — avval scripts/tg_login.py bilan "
              "login qiling.")
        return 1
    # api_id/api_hash bu bosqichda shart emas (fayldan auth_key o'qiladi),
    # lekin muvofiqlik uchun so'raladi — Railway'ga baribir kerak bo'ladi
    ask("TG_API_ID (my.telegram.org)", "TG_API_ID")
    ask("TG_API_HASH", "TG_API_HASH")

    session = SQLiteSession(str(SESSION_FILE))
    s = StringSession.save(session)
    session.close()
    if not s or len(s) < 100:
        print("XATO: session satri chiqmadi (fayl buzuqmi?) — tg_login.py bilan "
              "qayta login qiling.")
        return 1
    try:
        subprocess.run(["pbcopy"], input=s.encode(), check=True)
    except Exception as e:
        print(f"XATO: pbcopy ishlamadi ({e}) — satr ko'rsatilmadi (xavfsizlik).")
        return 1
    print(f"OK — clipboard'ga ko'chirildi ({len(s)} belgi)")
    print("Endi: Railway → Variables → TG_SESSION_STRING = ⌘V (paste)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
