#!/usr/bin/env python3
"""PM undiruv eslatmalarini EGANING shaxsiy Telegram akkauntidan yuborish
(Telethon userbot) — ega ongli ravishda tanlagan yetkazish kanali.

QAT'IY CHEKLOVLAR:
  - FAQAT send_message. Boshqa hech qanday akkaunt-aksiya yo'q (o'qish, join,
    delete, kontakt qo'shish — hech narsa).
  - Bitta chiqishda maks MAX_SENDS xabar; xabarlar orasi 4-6s (flood-safety).
  - Session: /data/undiruv_user.session — TG_SESSION_B64 env'dan startup'da
    yoziladi (fayl bo'lsa TEGILMAYDI). Login LOKAL scripts/tg_login.py bilan.
"""
import base64
import os
import random
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
SESSION = DATA / "undiruv_user.session"

MAX_SENDS = 4          # kuniga maksimal chiqish xabari (4 PM)
SLEEP_RANGE = (4, 6)   # xabarlar orasidagi pauza, soniya


def log(msg):
    print(f"[userbot] {msg}", flush=True)


class SessionInvalid(RuntimeError):
    """Session yo'q/yaroqsiz (ega hamma qurilmani logout qilgan bo'lishi mumkin)."""


def ensure_session():
    """TG_SESSION_B64 env → /data/undiruv_user.session (fayl bo'lsa tegilmaydi)."""
    if SESSION.exists() and SESSION.stat().st_size > 0:
        return True
    b64 = os.environ.get("TG_SESSION_B64", "").strip()
    if not b64:
        return False
    try:
        raw = base64.b64decode(b64)
        SESSION.parent.mkdir(parents=True, exist_ok=True)
        SESSION.write_bytes(raw)
        os.chmod(SESSION, 0o600)
        log(f"session yozildi: {SESSION} ({len(raw)} b)")
        return True
    except Exception as e:
        log(f"XATO: TG_SESSION_B64 o'qilmadi: {e}")
        return False


def available():
    """(True, "") yoki (False, sabab) — yuborishdan oldin tekshiruv."""
    try:
        import telethon  # noqa: F401
    except ImportError:
        return False, "telethon o'rnatilmagan"
    if not (os.environ.get("TG_API_ID") and os.environ.get("TG_API_HASH")):
        return False, "TG_API_ID/TG_API_HASH env yo'q"
    if not ensure_session():
        return False, "session yo'q (TG_SESSION_B64 berilmagan) — scripts/tg_login.py bilan yarating"
    return True, ""


def send_messages(items, sleep_range=SLEEP_RANGE):
    """items: [(slot, kontakt, matn)] — kontakt: @username / +telefon / "me"
    (Saved Messages, test). Qaytadi: [(slot, ok, xato_matni)].
    SessionInvalid — auth yaroqsiz bo'lsa (chaqiruvchi fallback'ka o'tadi)."""
    ok0, why = available()
    if not ok0:
        raise SessionInvalid(why)
    if len(items) > MAX_SENDS:
        log(f"OGOHLANTIRISH: {len(items)} xabar so'raldi — faqat {MAX_SENDS} tasi yuboriladi")
        items = items[:MAX_SENDS]

    from telethon.sync import TelegramClient

    results = []
    client = TelegramClient(
        str(SESSION), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"],
        device_model="abba-sheets-agent", system_version="railway",
    )
    try:
        client.connect()
        if not client.is_user_authorized():
            raise SessionInvalid(
                "session yaroqsiz (akkauntdan chiqarilgan?) — tg_login.py bilan qayta yarating"
            )
        for i, (slot, to, text) in enumerate(items):
            try:
                entity = "me" if to == "me" else str(to).strip()
                client.send_message(entity, text, link_preview=False)
                results.append((slot, True, ""))
                log(f"yuborildi: {slot} → {entity if entity == 'me' else entity[:4] + '…'}")
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:150]}"
                results.append((slot, False, err))
                log(f"XATO: {slot} yuborilmadi — {err}")
            if i + 1 < len(items):
                time.sleep(random.uniform(*sleep_range))
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    return results


if __name__ == "__main__":
    ok, why = available()
    print(f"available: {ok} {why}")
    if ok and "--test-saved" in sys.argv:
        print(send_messages([("test", "me", "abba-sheets-agent: userbot sinov xabari ✅")]))
