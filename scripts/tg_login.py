#!/usr/bin/env python3
"""BIR MARTALIK lokal login (Mac): eganing Telegram akkaunti uchun Telethon
session yaratadi — keyin base64 qilib Railway'ga TG_SESSION_B64 qilib qo'yiladi.

Ishlatish:
  venv/bin/python scripts/tg_login.py
  (TG_API_ID/TG_API_HASH env'da bo'lsa so'ralmaydi; my.telegram.org → API
   development tools'dan olinadi)

Hamma so'rovlar OCHIQ input (getpass YO'Q) — telefon, SMS kod, 2FA parol.
Session fayl: shu papkada undiruv_user.session
"""
import base64
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SESSION = HERE / "undiruv_user.session"


def ask(prompt, env=None):
    v = os.environ.get(env, "").strip() if env else ""
    if v:
        print(f"{prompt}: (env'dan olindi)")
        return v
    return input(f"{prompt}: ").strip()


def main():
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        print("XATO: telethon yo'q — avval: venv/bin/pip install telethon")
        return 1

    api_id = ask("TG_API_ID (my.telegram.org)", "TG_API_ID")
    api_hash = ask("TG_API_HASH", "TG_API_HASH")
    phone = ask("Telefon (masalan +99890...)")

    client = TelegramClient(str(SESSION), int(api_id), api_hash,
                            device_model="abba-sheets-agent", system_version="railway")
    # Kod va 2FA parol — OCHIQ input (foydalanuvchi talabi: getpass yo'q)
    client.start(
        phone=lambda: phone,
        code_callback=lambda: input("Telegram'dan kelgan KOD: ").strip(),
        password=lambda: input("2FA parol (bo'lmasa Enter): ").strip(),
    )
    me = client.get_me()
    client.disconnect()
    print(f"\n✅ Session yaratildi: {SESSION}")
    print(f"   Akkaunt: {me.first_name} (@{me.username or '—'}, id {me.id})")
    print("\nKEYINGI QADAM — session'ni base64 qilib clipboard'ga oling:\n")
    print(f"  base64 -i {SESSION} | pbcopy\n")
    print("So'ng Railway → Variables: TG_SESSION_B64 = (paste), TG_API_ID, TG_API_HASH.")
    print(f"(b64 hajmi ≈ {len(base64.b64encode(SESSION.read_bytes())) // 1024} KB — bitta env sig'adi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
