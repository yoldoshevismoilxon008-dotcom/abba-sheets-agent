#!/usr/bin/env python3
"""chat_log.py — bot suhbatini Obsidian vault uchun DATA/chat/YYYY-MM-DD.md ga yozadi (B2.2).

FAQAT yozadi (best-effort append). kb.ingest HECH QACHON chaqirmaydi — chat KB'ga faqat
vault_sync orqali (GitHub round-trip'dan keyin) tushadi; aks holda bir xil matn IKKI MARTA
tushardi. Yozish xatosi javobni HECH QACHON yiqitmaydi (try/except, faqat log).
"""
import os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
CHAT_DIR = DATA / "chat"
CHAT_MAX = 8000            # bitta yozuv (savol/javob) shu belgidan kesiladi — kunlik fayl shishmasin


def log(msg):
    print(f"[chat_log] {msg}", flush=True)


def _clip(s):
    s = (s or "").strip()
    return s if len(s) <= CHAT_MAX else s[:CHAT_MAX].rstrip() + " …(qisqartirildi)"


def _file_for(now):
    return CHAT_DIR / f"{now.strftime('%Y-%m-%d')}.md"


def _append(text, now):
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    path = _file_for(now)
    if not path.exists():                      # kun almashsa — yangi fayl + sarlavha
        path.write_text(f"# {now.strftime('%Y-%m-%d')} — Suhbat arxivi\n\n", encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:   # QAYTA YOZISH emas — append
        f.write(text)


def append_qa(question, answer, now=None):
    """Savol+javobni bugungi faylga qo'shadi. Best-effort — xato javobni yiqitmaydi.
    (Ovozli savolda transkript matni; PDF javobda caption/xulosa matni keladi — fayl emas.)"""
    try:
        now = now or datetime.now()
        t = now.strftime("%H:%M")
        q = _clip(question)                     # uzun yozuv faylni shishirtirmasin (~8000)
        a = _clip(answer)
        _append(f"## {t} · Savol\n{q}\n\n## {t} · Javob\n{a}\n\n---\n\n", now)
    except Exception as e:
        log(f"append_qa o'tkazildi: {type(e).__name__}: {str(e)[:120]}")


def append_cmd(label, now=None):
    """Buyruqni BITTA qator bilan yozadi (to'liq chiqishsiz — baza shovqinga to'lmasin)."""
    try:
        now = now or datetime.now()
        _append(f"- {now.strftime('%H:%M')} · {str(label).strip()}\n", now)
    except Exception as e:
        log(f"append_cmd o'tkazildi: {type(e).__name__}: {str(e)[:120]}")
