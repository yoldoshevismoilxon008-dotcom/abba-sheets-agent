#!/usr/bin/env python3
"""Google Sheets'ga YOZISH uchun yagona modul — qat'iy allowlist bilan.

XAVFSIZLIK MODELI:
  - O'qish (fetch.py va h.k.) — faqat spreadsheets.readonly scope, yozolmaydi.
  - Yozish — FAQAT shu modul orqali va FAQAT config.yaml dagi dashboard_id ga.
  - Boshqa har qanday spreadsheet_id ga yozish urinishi: WriteDeniedError +
    log + Telegram alert. Guard tarmoq chaqiruvidan OLDIN ishlaydi.

SA huquqlari: PM sheet'larda Viewer, dashboard'da Editor — shu qoida buzilmasin.
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import analyze
import fetch as fetchmod
import send as sendmod

SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]


class WriteDeniedError(RuntimeError):
    pass


def log(msg):
    print(f"[dashboard_writer] {msg}", flush=True)


def _alert(msg):
    """Allowlist buzilishida Telegram'ga xabar (test'da monkeypatch qilinadi)."""
    try:
        import os

        analyze.load_env()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if token and chat:
            sendmod.tg_send(token, chat, sendmod.md_to_html(msg))
    except Exception as e:
        log(f"alert yuborilmadi: {e}")


def dashboard_id():
    cfg = fetchmod.load_full_config()
    return str(cfg.get("dashboard_id") or "").strip()


def guard(spreadsheet_id):
    """Yozishdan oldin MAJBURIY tekshiruv. Faqat dashboard_id o'tadi."""
    did = dashboard_id()
    if not did:
        raise WriteDeniedError(
            "dashboard_id config.yaml da to'ldirilmagan — yozish o'chiq"
        )
    if str(spreadsheet_id).strip() != did:
        msg = (
            f"🚨 XAVFSIZLIK: allowlist'dan tashqari sheet'ga YOZISH urinishi "
            f"bloklandi! id={str(spreadsheet_id)[:50]!r} (ruxsat: faqat dashboard). "
            f"Kod tekshirilsin."
        )
        log(msg)
        _alert(msg)
        raise WriteDeniedError(f"yozish taqiqlangan: {spreadsheet_id!r} allowlist'da emas")


_rw = None


def rw_client():
    global _rw
    if _rw is None:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(str(fetchmod.CREDS), scopes=SCOPES_RW)
        _rw = gspread.authorize(creds)
    return _rw


def _worksheet(sh, title, rows=200, cols=26):
    import gspread

    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def write_values(spreadsheet_id, tab_title, values, overwrite=True):
    """Umumiy yozuv nuqtasi — HAR DOIM guard'dan o'tadi."""
    guard(spreadsheet_id)
    sh = rw_client().open_by_key(spreadsheet_id)
    ws = _worksheet(sh, tab_title, rows=max(200, len(values) + 20),
                    cols=max(12, max((len(r) for r in values), default=12) + 2))
    if overwrite:
        ws.clear()
    ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    log(f"yozildi: [{tab_title}] {len(values)} qator")


def overwrite_tab(tab_title, values):
    write_values(dashboard_id(), tab_title, values, overwrite=True)


def append_rows_idempotent(tab_title, header, rows, key_idx=(0, 1)):
    """Append — (key_idx ustunlari bo'yicha) mavjud qatorlarni takrorlamaydi."""
    did = dashboard_id()
    guard(did)
    sh = rw_client().open_by_key(did)
    ws = _worksheet(sh, tab_title, rows=1000, cols=len(header) + 2)
    existing = ws.get_values()
    if not existing or [c.strip() for c in existing[0][:len(header)]] != header:
        ws.clear()
        ws.update(values=[header], range_name="A1", value_input_option="USER_ENTERED")
        existing = [header]
    seen = {tuple(str(r[i]).strip() for i in key_idx if i < len(r)) for r in existing[1:]}
    fresh = [r for r in rows if tuple(str(r[i]).strip() for i in key_idx) not in seen]
    if fresh:
        ws.append_rows(fresh, value_input_option="USER_ENTERED")
    log(f"append [{tab_title}]: +{len(fresh)} yangi ({len(rows) - len(fresh)} allaqachon bor)")
    return len(fresh)


def dashboard_url():
    did = dashboard_id()
    return f"https://docs.google.com/spreadsheets/d/{did}" if did else ""


_LAST = BASE / "data" / "dashboard-state.json"


def save_state():
    import json

    _LAST.parent.mkdir(parents=True, exist_ok=True)
    _LAST.write_text(
        json.dumps({"updated": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8"
    )


def last_updated():
    import json

    try:
        return json.loads(_LAST.read_text(encoding="utf-8")).get("updated", "—")
    except Exception:
        return "—"
