#!/usr/bin/env python3
"""Komponent holati — kunlik hisobot pastiga bitta qator.

  health.py --line     → "🩺 bot listener ✓ (oxirgi getUpdates 08:59) · scheduler ✓ …"

Nega: 2026-09-09 da bot listener 08:59 dan 19:00 gacha (~10 soat) o'lik turdi,
lekin scheduler ishlagani uchun hisobotlar kelaverdi va nosozlik faqat tasodifan
sezildi. Bu qator bo'lganda hisobotning O'ZI aytardi.

Har bir komponent xatosi yutiladi — health hech qachon pipeline'ni yiqitmasin.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))

# Listener shu muddatdan uzoq jim tursa — nosoz deb belgilanadi.
# getUpdates long-poll 50s, heartbeat daqiqada bir yoziladi → 15 daqiqa keng zaxira.
LISTENER_STALE_MIN = 15


def _fmt_hhmm(dt):
    return dt.strftime("%H:%M")


def listener_status(now=None):
    """(ok, izoh) — bot-heartbeat.json asosida."""
    now = now or datetime.now()
    hb = DATA / "bot-heartbeat.json"
    if not hb.exists():
        return False, "heartbeat yo'q"
    try:
        d = json.loads(hb.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(d["iso"])
    except Exception as e:                       # noqa: BLE001
        return False, f"heartbeat o'qilmadi ({type(e).__name__})"
    age = now - ts
    if age > timedelta(minutes=LISTENER_STALE_MIN):
        mins = int(age.total_seconds() // 60)
        return False, f"oxirgi getUpdates {_fmt_hhmm(ts)} — {mins} daq JIM"
    return True, f"oxirgi getUpdates {_fmt_hhmm(ts)}"


def userbot_status():
    try:
        import userbot_sender

        ok, why = userbot_sender.available()
        return bool(ok), ("" if ok else str(why)[:60])
    except Exception as e:                       # noqa: BLE001
        return False, f"{type(e).__name__}"


def pdf_status():
    """Chrome topiladimi — PDF render'ning yagona tashqi sharti."""
    try:
        import render_pdf

        render_pdf.find_chrome()
        return True, ""
    except Exception as e:                       # noqa: BLE001
        return False, str(e)[:60]


def scheduler_status():
    """Bu kod kunlik pipeline ichida ishlayapti — demak scheduler ishga tushirgan."""
    return True, ""


def _mark(ok, note):
    s = "✓" if ok else "✗"
    return f"{s} ({note})" if note else s


def health_line(now=None):
    parts = []
    for name, fn in (("bot listener", lambda: listener_status(now)),
                     ("scheduler", scheduler_status),
                     ("userbot", userbot_status),
                     ("PDF", pdf_status)):
        try:
            ok, note = fn()
        except Exception as e:                   # noqa: BLE001
            ok, note = False, f"tekshirilmadi ({type(e).__name__})"
        parts.append(f"{name} {_mark(ok, note)}")
    return "🩺 " + " · ".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--line", action="store_true", help="bitta qator chiqar")
    ap.parse_args()
    print(health_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
