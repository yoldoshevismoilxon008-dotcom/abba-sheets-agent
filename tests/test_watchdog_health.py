"""Osilishga qarshi himoya: watchdog, Sheets timeout, komponent holati.

2026-09-09 hodisasi: handle_update polling loop ICHIDA chaqirilardi — u osilib
qolgach getUpdates boshqa chaqirilmadi, bot 08:59 dan 19:00 gacha (~10 soat) jim
qoldi, jarayon esa scheduler tufayli tirik ko'rindi va hisobotlar kelaverdi.
Nosozlik faqat tasodifan sezildi.

Uch qatlam qo'riqlanadi:
  1. handle_with_watchdog — osilgan xabar loop'ni to'xtatmasin;
  2. Sheets chaqiruvida majburiy timeout (asosiy osilish nomzodi edi);
  3. health.py — kunlik hisobotda listener jimligi DARHOL ko'rinsin.

pytest tests/test_watchdog_health.py  yoki  python3 tests/test_watchdog_health.py
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot_listener as bl   # noqa: E402
import fetch as fetchmod    # noqa: E402
import health               # noqa: E402

_ORIG = {
    "handle_update": bl.handle_update,
    "send_retry": bl.send_retry,
    "log": bl.log,
}


def _restore():
    for k, v in _ORIG.items():
        setattr(bl, k, v)


def _quiet():
    """Telegram'ga chiqmasin, log shovqin qilmasin; yuborilganlarni ushlaydi."""
    sent = []
    bl.send_retry = lambda text, **kw: sent.append(text)
    bl.log = lambda *a, **k: None
    return sent


# ------------------------------------------------------------ 1) watchdog

def test_normal_xabar_ok_qaytaradi():
    _quiet()
    seen = []
    bl.handle_update = lambda upd: seen.append(upd["update_id"])
    try:
        assert bl.handle_with_watchdog({"update_id": 1}, timeout=5) == "ok"
        assert seen == [1]
    finally:
        _restore()


def test_osilgan_xabar_timeout_beradi_va_loop_davom_etadi():
    """ASOSIY regressiya: osilgan handle_update butun botni to'xtatmasin."""
    sent = _quiet()
    bl.handle_update = lambda upd: time.sleep(30)      # osilgan xabar taqlidi
    try:
        t0 = time.monotonic()
        res = bl.handle_with_watchdog({"update_id": 42}, timeout=1)
        dur = time.monotonic() - t0
    finally:
        _restore()
    assert res == "timeout", res
    assert dur < 5, f"watchdog kutib qoldi ({dur:.1f}s) — chek ishlamadi"
    assert sent and "42" in sent[0] and "timeout" in sent[0].lower(), sent


def test_timeout_xabarida_chek_qiymati_korsatiladi():
    sent = _quiet()
    bl.handle_update = lambda upd: time.sleep(30)
    try:
        bl.handle_with_watchdog({"update_id": 7}, timeout=1)
    finally:
        _restore()
    assert "1s" in sent[0], sent


def test_xato_yutiladi_va_error_qaytadi():
    sent = _quiet()

    def _boom(upd):
        raise ValueError("sinov xatosi")

    bl.handle_update = _boom
    try:
        assert bl.handle_with_watchdog({"update_id": 3}, timeout=5) == "error"
    finally:
        _restore()
    assert sent, "xatoda foydalanuvchiga xabar ketmadi"


def test_watchdog_thread_daemon_boladi():
    """Osilgan thread jarayon chiqishini ushlab qolmasin."""
    _quiet()
    box = {}
    bl.handle_update = lambda upd: box.setdefault(
        "daemon", __import__("threading").current_thread().daemon) or time.sleep(2)
    try:
        bl.handle_with_watchdog({"update_id": 9}, timeout=1)
    finally:
        _restore()
    assert box.get("daemon") is True


def test_handle_timeout_konstanta_bor():
    assert isinstance(bl.HANDLE_TIMEOUT, (int, float)) and bl.HANDLE_TIMEOUT > 0


# ------------------------------------------------------------ 2) Sheets timeout

def test_gclient_timeout_ornatadi():
    """gspread client CHEKSIZ kutmasin — set_timeout chaqirilishi shart."""
    import gspread
    from google.oauth2 import service_account

    calls = {}

    class _FakeGC:
        def set_timeout(self, t):
            calls["timeout"] = t

    orig_auth = gspread.authorize
    orig_creds = service_account.Credentials.from_service_account_file
    gspread.authorize = lambda creds: _FakeGC()
    service_account.Credentials.from_service_account_file = lambda *a, **k: object()
    try:
        fetchmod.gclient()
    finally:
        gspread.authorize = orig_auth
        service_account.Credentials.from_service_account_file = orig_creds
    assert "timeout" in calls, "set_timeout chaqirilmadi — Sheets cheksiz kutishi mumkin"
    assert calls["timeout"] == fetchmod.SHEETS_TIMEOUT


def test_sheets_timeout_env_bilan_ozgaradi(monkeypatch=None):
    import os
    old = os.environ.get("SHEETS_TIMEOUT")
    try:
        os.environ["SHEETS_TIMEOUT"] = "5,30"
        assert fetchmod._sheets_timeout() == (5.0, 30.0)
        os.environ["SHEETS_TIMEOUT"] = "45"
        assert fetchmod._sheets_timeout() == 45.0
    finally:
        if old is None:
            os.environ.pop("SHEETS_TIMEOUT", None)
        else:
            os.environ["SHEETS_TIMEOUT"] = old


def test_notogri_env_defaultga_qaytadi():
    import os
    old = os.environ.get("SHEETS_TIMEOUT")
    try:
        os.environ["SHEETS_TIMEOUT"] = "salom"
        assert fetchmod._sheets_timeout() == fetchmod.SHEETS_TIMEOUT
    finally:
        if old is None:
            os.environ.pop("SHEETS_TIMEOUT", None)
        else:
            os.environ["SHEETS_TIMEOUT"] = old


# ------------------------------------------------------------ 3) health qatori

def _write_hb(tmp, when):
    (tmp / "bot-heartbeat.json").write_text(
        json.dumps({"ts": when.timestamp(), "iso": when.isoformat(timespec="seconds")}),
        encoding="utf-8")


def _with_data(tmp):
    health.DATA = tmp


def test_yangi_heartbeat_ok():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    orig = health.DATA
    try:
        _with_data(tmp)
        now = datetime.now()
        _write_hb(tmp, now - timedelta(minutes=1))
        ok, note = health.listener_status(now)
        assert ok and "oxirgi getUpdates" in note, note
    finally:
        health.DATA = orig


def test_eski_heartbeat_jim_deb_belgilanadi():
    """10 soatlik o'lim aynan shu holat — hisobotda ✗ bo'lib chiqsin."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    orig = health.DATA
    try:
        _with_data(tmp)
        now = datetime.now()
        _write_hb(tmp, now - timedelta(hours=10))
        ok, note = health.listener_status(now)
        assert not ok, "10 soatlik jimlik sezilmadi"
        assert "JIM" in note and "600" in note, note
    finally:
        health.DATA = orig


def test_heartbeat_yoq_bolsa_nosoz():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    orig = health.DATA
    try:
        _with_data(tmp)
        ok, note = health.listener_status(datetime.now())
        assert not ok and "yo'q" in note
    finally:
        health.DATA = orig


def test_health_line_hamma_komponentni_qamraydi():
    line = health.health_line()
    for name in ("bot listener", "scheduler", "userbot", "PDF"):
        assert name in line, f"«{name}» qatorda yo'q: {line}"


def test_komponent_xatosi_health_ni_yiqitmaydi():
    orig = health.userbot_status
    try:
        health.userbot_status = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        line = health.health_line()
        assert "userbot" in line and "✗" in line
    finally:
        health.userbot_status = orig


def test_bot_listener_heartbeat_yozadi():
    """Listener tomonidagi yozuv: touch_heartbeat faylni yaratadi."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    orig_data, orig_hb = bl.DATA, bl.HEARTBEAT
    try:
        bl.DATA = tmp
        bl.HEARTBEAT = tmp / "bot-heartbeat.json"
        bl._hb_last[0] = 0.0
        bl.touch_heartbeat(force=True)
        d = json.loads(bl.HEARTBEAT.read_text(encoding="utf-8"))
        assert "iso" in d and "ts" in d
    finally:
        bl.DATA, bl.HEARTBEAT = orig_data, orig_hb


def test_heartbeat_throttle_ishlaydi():
    """Har getUpdates'da diskka yozilmasin (50s poll → daqiqada bir marta)."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    orig_data, orig_hb = bl.DATA, bl.HEARTBEAT
    try:
        bl.DATA = tmp
        bl.HEARTBEAT = tmp / "bot-heartbeat.json"
        bl._hb_last[0] = 0.0
        bl.touch_heartbeat(force=True)
        first = bl.HEARTBEAT.read_text(encoding="utf-8")
        time.sleep(0.05)
        bl.touch_heartbeat()                 # throttle: yozmasligi kerak
        assert bl.HEARTBEAT.read_text(encoding="utf-8") == first
    finally:
        bl.DATA, bl.HEARTBEAT = orig_data, orig_hb


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
