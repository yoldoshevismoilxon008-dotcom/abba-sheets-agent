#!/usr/bin/env python3
"""BIR MARTALIK lokal login (Mac): eganing Telegram akkaunti uchun Telethon
StringSession yaratadi (~350 belgi — Railway env limitiga bemalol sig'adi).
Satr EKRANGA CHIQMAYDI — to'g'ridan clipboard'ga (pbcopy).

Ishlatish:
  venv/bin/python scripts/tg_login.py
  (TG_API_ID/TG_API_HASH env'da bo'lsa so'ralmaydi; my.telegram.org → API
   development tools'dan olinadi)

Hamma so'rovlar OCHIQ input (getpass YO'Q) — telefon, SMS kod, 2FA parol.
So'ng Railway → Variables → TG_SESSION_STRING = (paste).
"""
import os
import subprocess
import sys


def ask(prompt, env=None):
    v = os.environ.get(env, "").strip() if env else ""
    if v:
        print(f"{prompt}: (env'dan olindi)")
        return v
    return input(f"{prompt}: ").strip()


def main():
    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("XATO: telethon yo'q — avval: venv/bin/pip install telethon")
        return 1

    api_id = ask("TG_API_ID (my.telegram.org)", "TG_API_ID")
    api_hash = ask("TG_API_HASH", "TG_API_HASH")
    phone = ask("Telefon (masalan +99890...)")

    client = TelegramClient(StringSession(), int(api_id), api_hash,
                            device_model="abba-sheets-agent", system_version="railway")
    # Kod va 2FA parol — OCHIQ input (foydalanuvchi talabi: getpass yo'q)
    client.start(
        phone=lambda: phone,
        code_callback=lambda: input("Telegram'dan kelgan KOD: ").strip(),
        password=lambda: input("2FA parol (bo'lmasa Enter): ").strip(),
    )
    me = client.get_me()
    s = client.session.save()
    client.disconnect()
    print(f"\n✅ Login muvaffaqiyatli: {me.first_name} (@{me.username or '—'}, id {me.id})")
    try:
        subprocess.run(["pbcopy"], input=s.encode(), check=True)
        print(f"OK — StringSession clipboard'ga ko'chirildi ({len(s)} belgi)")
    except Exception as e:
        print(f"XATO: pbcopy ishlamadi ({e}) — satr ko'rsatilmadi (xavfsizlik).")
        return 1
    print("Endi: Railway → Variables: TG_SESSION_STRING = ⌘V, TG_API_ID, TG_API_HASH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
