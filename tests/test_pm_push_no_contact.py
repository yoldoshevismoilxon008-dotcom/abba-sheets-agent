"""PM undiruv push — kontaktsizlik JIM YASHIRINMASIN (2026-09-07 tekshiruvidan).

Ilgari `if msgs and not dry_run` sababli, birorta PM kontakti sozlanmagan bo'lsa:
  1. userbot UMUMAN chaqirilmasdi — uning nosozligi hech qayerda ko'rinmasdi;
  2. jamlamada faqat PM-qatorlarida "kontakt yo'q" turardi, ya'ni push
     haqiqatda ketmagani bir qarashda bilinmasdi.
Bu testlar ikkala teshikni ham qo'riqlaydi.

pytest tests/test_pm_push_no_contact.py  yoki  python3 tests/test_pm_push_no_contact.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pm_push  # noqa: E402
import undiruv  # noqa: E402

TODAY = date(2026, 9, 7)

_ORIG = {n: getattr(pm_push, n) for n in
         ("_load_state", "_save_state", "_month_rows_src", "build_push",
          "load_contacts", "slots_from_config", "send_owner", "owner_pdf")}
_U_ORIG = {n: getattr(undiruv, n) for n in
           ("consume_tab_note", "snapshot_banner", "reconcile_warn", "totals", "is_unpaid")}

_STATS = {
    "overdue_n": 1, "overdue_sum": 100, "aktiv_n": 1, "aktiv_sum": 100,
    "bad_sum": 0, "no_date": 0, "pauza": 0, "status_blank": [], "unpaid_n": 1,
    "pm_missing": [], "pm_col_missing": False, "pm_col_tab": "Undiruv sentabr",
    "closed_carry": [], "moved_carry": [], "nodate_pm": {},
}


def _restore():
    for n, f in _ORIG.items():
        setattr(pm_push, n, f)
    for n, f in _U_ORIG.items():
        setattr(undiruv, n, f)


def _run(contacts, userbot=(True, "")):
    """run_daily'ni tashqi bog'liqliklarsiz yurgizadi. Qaytadi: (summary, egaga_ketgan)."""
    owner_msgs = []
    pm_push._load_state = lambda: {}
    pm_push._save_state = lambda d: None
    pm_push._month_rows_src = lambda m, t, d: ("Undiruv sentabr", [{"r": 1}], "live")
    pm_push.build_push = lambda today, cur, prev, pm: ({"Ali": ["• Loyiha A — $100"]}, dict(_STATS))
    pm_push.load_contacts = lambda: contacts
    pm_push.slots_from_config = lambda: {"ali": "Ali"}
    pm_push.send_owner = lambda t: owner_msgs.append(t)
    pm_push.owner_pdf = lambda *a, **k: True          # PDF ketdi deb hisoblanadi
    undiruv.consume_tab_note = lambda: ""
    undiruv.snapshot_banner = lambda *a, **k: ""
    undiruv.reconcile_warn = lambda *a, **k: ""
    undiruv.totals = lambda rows: {"qoldiq": 0, "kelishilgan": 0, "undirildi": 0, "pct": 0}
    undiruv.is_unpaid = lambda r: False

    import userbot_sender
    orig_av = userbot_sender.available
    userbot_sender.available = lambda: userbot
    try:
        _status, summary = pm_push.run_daily(today=TODAY)
        return summary, owner_msgs
    finally:
        userbot_sender.available = orig_av


# ------------------------------------------------ kontaktsizlik ko'rinadigan bo'lsin

def test_kontaktsizlik_jamlamada_ochiq_yoziladi():
    try:
        summary, _ = _run(contacts={})
    finally:
        _restore()
    assert "kontakt sozlanmagan" in summary, f"ogohlantirish yo'q:\n{summary}"
    assert "YUBORILMADI" in summary, f"push ketmagani aytilmagan:\n{summary}"
    assert "1 ta PM" in summary, f"PM soni ko'rsatilmagan:\n{summary}"


def test_kutayotgan_eslatmalar_soni_korsatiladi():
    try:
        summary, _ = _run(contacts={})
    finally:
        _restore()
    assert "1 eslatma kutmoqda" in summary, f"kutayotgan eslatma soni yo'q:\n{summary}"


def test_pm_set_korsatmasi_beriladi():
    try:
        summary, _ = _run(contacts={})
    finally:
        _restore()
    assert "/pm_set" in summary, f"tuzatish yo'li ko'rsatilmagan:\n{summary}"


# --------------------------------------- kontakt yo'q bo'lsa ham userbot tekshirilsin

def test_kontaktsizlikda_userbot_nosozligi_ham_korinadi():
    """Ilgari userbot umuman chaqirilmasdi — nosozlik kontaktsizlik ostida yashirinardi."""
    try:
        summary, _ = _run(contacts={}, userbot=(False, "TG_API_ID/TG_API_HASH env yo'q"))
    finally:
        _restore()
    assert "Userbot ham tayyor emas" in summary, f"userbot holati yo'q:\n{summary}"
    assert "TG_API_ID" in summary, f"aniq sabab ko'rsatilmagan:\n{summary}"


def test_userbot_soz_bolsa_ortiqcha_ogohlantirish_yoq():
    try:
        summary, _ = _run(contacts={}, userbot=(True, ""))
    finally:
        _restore()
    assert "kontakt sozlanmagan" in summary          # bu qolishi kerak
    assert "Userbot ham tayyor emas" not in summary, f"ortiqcha ogohlantirish:\n{summary}"


# ------------------------------------------------------- kontakt bor bo'lgan holat

def test_kontakt_sozlangan_bolsa_kontakt_ogohlantirishi_chiqmaydi():
    try:
        summary, _ = _run(contacts={"ali": "@ali"})
    finally:
        _restore()
    assert "kontakt sozlanmagan" not in summary, f"noo'rin ogohlantirish:\n{summary}"
    assert "Userbot ham tayyor emas" not in summary, f"noo'rin userbot xabari:\n{summary}"


def test_kontakt_bor_va_userbot_yiqilsa_eski_fallback_ishlaydi():
    """Kontakt bor → send_messages chaqiriladi; yiqilsa fallback_reason yo'li."""
    import userbot_sender

    def _boom(items):
        raise userbot_sender.SessionInvalid("session yaroqsiz")

    orig_send = userbot_sender.send_messages
    userbot_sender.send_messages = _boom
    try:
        summary, owner_msgs = _run(contacts={"ali": "@ali"})
    finally:
        userbot_sender.send_messages = orig_send
        _restore()
    assert "session yaroqsiz" in summary, f"userbot xatosi jamlamada yo'q:\n{summary}"
    assert "QO'LDA yuboring" in summary
    assert any("tayyor matn" in m for m in owner_msgs), "egaga tayyor matn yuborilmadi"


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
