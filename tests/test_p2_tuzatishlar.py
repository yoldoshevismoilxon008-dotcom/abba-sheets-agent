"""Audit P2 tuzatishlari testlari (mustahkamlik va kichik xatolar).

  A  undiruv: money() vergul-minglik/manfiy/xato katak; sarlavhada bo'sh katak bo'lsa
     ham sarlavha topiladi, topilmasa egaga izoh; «Status bo'sh» konvensiya bo'lsa
     shovqin emas.

pytest tests/test_p2_tuzatishlar.py  yoki  python3 tests/test_p2_tuzatishlar.py
Tarmoq/kredensial kerak emas.
"""
import contextlib
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="p2-test-"))
import undiruv as u        # noqa: E402


@contextlib.contextmanager
def _soxta(obj, name, val):
    orig = getattr(obj, name)
    setattr(obj, name, val)
    try:
        yield
    finally:
        setattr(obj, name, orig)


# ---------------------------------------------------------------- A: undiruv

def test_money_vergul_minglik_va_xato_katak():
    assert u.money("$1,800") == 1800.0                 # ilgari 1,8
    assert u.money("$2,500.00") == 2500.0              # ilgari 0
    assert u.money("12,500,000") == 12500000.0
    assert u.money("2.500,00") == 2500.0
    assert u.money("1.800.000") == 1800000.0
    assert u.money("-$500") == -500.0                  # ilgari 0
    assert u.money("($500)") == -500.0                 # buxgalteriya manfiysi
    # eski xulq saqlanadi
    assert u.money("$1 600") == 1600.0 and u.money("1 800,50") == 1800.50
    assert u.money("0,5") == 0.5 and u.money("1.8") == 1.8
    assert u.money("") == 0.0 and u.money("—") == 0.0
    # xato katak: money 0 (hisob buzilmaydi), money_parse None (jim emas)
    assert u.money("#REF!") == 0.0 and u.money_parse("#REF!") is None
    assert u.money_parse("#N/A") is None and u.money_parse("kutilmoqda") is None
    assert u.money_parse("") == 0.0 and u.money_parse("—") == 0.0


HDR = ["№", "Ishlar nomi", "Ma'sul shaxs", "Summa", "Undirildi", "Final sana", "Xolati"]


def _vals(*rows, hdr=HDR):
    return [list(hdr)] + [list(r) for r in rows]


def test_bad_sum_qator_belgisi_va_jamlama():
    vals = _vals(["1", "Alfa", "Ali", "#REF!", "$0", "10.10", ""],
                 ["2", "Beta", "Ali", "$1,800", "$200", "10.10", ""],
                 ["3", "Gamma", "Vali", "$300", "matn", "10.10", ""])
    rows = u.parse_rows(vals, date(2026, 10, 5))
    by = {r["loyiha"]: r for r in rows}
    assert by["Alfa"]["bad_sum"] and by["Gamma"]["bad_sum"] and not by["Beta"]["bad_sum"]
    assert by["Beta"]["qoldiq"] == 1800 and by["Beta"]["kelishilgan"] == 2000
    t = u.totals(rows)
    assert t["bad_sum_n"] == 2
    assert "2 ta qatorda summa katagi son emas" in u.bad_sum_warn(t)
    assert u.bad_sum_warn(u.totals([by["Beta"]])) == ""


def test_sarlavhada_bosh_katak_malumot_qatori_sarlavha_bolmaydi():
    # Sarlavhada bo'sh kataklar bor, ma'lumot qatori to'laroq — eski detect_header
    # ma'lumot qatorini sarlavha deb olib, [] qaytarardi (blok jimgina yo'qolardi)
    hdr = ["", "Ishlar nomi", "", "Summa", "Undirildi", "", ""]
    vals = _vals(["1", "Alfa", "Ali", "$500", "$0", "10.10", "x"],
                 ["2", "Beta", "Vali", "$700", "$100", "12.10", "y"], hdr=hdr)
    import diff as diffmod
    assert diffmod.detect_header(vals) == 1          # eski qoida — noto'g'ri qator
    assert u.header_row(vals) == 0
    rows = u.parse_rows(vals, date(2026, 10, 5))
    assert [r["loyiha"] for r in rows] == ["Alfa", "Beta"]
    assert rows[1]["qoldiq"] == 700 and rows[1]["undirildi"] == 100


def test_sarlavha_topilmasa_egaga_izoh():
    u.consume_tab_note()
    hdr = ["№", "", "Ma'sul shaxs", "Summa", "Undirildi", "Final sana", "Xolati"]
    vals = _vals(["1", "Alfa", "Ali", "$500", "$0", "10.10", ""], hdr=hdr)
    assert u.parse_rows(vals, date(2026, 10, 5), tab="Undiruv Oktyabr") == []
    n = u.consume_tab_note()
    assert "Undiruv Oktyabr" in n and "«Ishlar nomi»" in n and "«Undirildi»" not in n
    assert u.consume_tab_note() == ""                # bir marta iste'mol qilinadi
    # bo'sh tab (hali to'ldirilmagan) — izoh yo'q
    assert u.parse_rows([], date(2026, 10, 5), tab="X") == [] and u.consume_tab_note() == ""


def test_snapshot_yolida_sarlavha_izohi_notes_ga_tushadi():
    hdr = ["№", "", "Ma'sul shaxs", "Summa", "Undirildi"]
    snap = {"pm_kpi": False, "ranges": {"'Undiruv Oktyabr'!A1:Z": {"values": _vals(
        ["1", "Alfa", "Ali", "$500", "$0"], hdr=hdr)}}}
    notes = []
    with _soxta(u.diffmod, "load_day", lambda day: ({"smm": snap}, {})), \
            _soxta(u, "find_tab", lambda s, t, **k: "'Undiruv Oktyabr'!A1:Z"):
        tab, rows, src = u._oy_oqi("oktyabr", 2026, date(2026, 10, 1), date(2026, 10, 5),
                                   "2026-10-05", False, False, notes)
    assert (tab, rows, src) == ("Undiruv Oktyabr", [], "snapshot")
    assert any("«Ishlar nomi» ustuni" in n for n in notes)
    assert not any("«Undirildi»" in n for n in notes)   # sarlavha qatori to'g'ri topildi


def _row(name, status="", qoldiq=500.0):
    return {"loyiha": name, "pm": "Ali", "pm_missing": False, "pm_col_present": True,
            "qoldiq": qoldiq, "qoldiq_raw": str(qoldiq), "undirildi": 0.0, "aktiv": 0.0,
            "lose": 0.0, "lose_raw": "", "lose_col_present": False, "kelishilgan": qoldiq,
            "status_blank": not status, "muddat": date(2026, 10, 20), "muddat_raw": "20.10",
            "holat": "paid" if status == "✅" else "", "holat_matn": status, "bad_sum": False}


def test_status_bosh_konvensiya_bolsa_shovqin_emas():
    # Oy boshida hamma undirilmagan qator statusi bo'sh — bu sheet konvensiyasi
    hammasi = [_row(f"L{i}") for i in range(10)]
    t = u.totals(hammasi)
    assert t["status_blank_n"] == 10 and t["unpaid_n"] == 10
    assert u.status_blank_warn(t) == ""
    d = u.report_data(hammasi, "Undiruv Oktyabr", date(2026, 10, 5))
    assert not any(i["status_blank"] for p in d["pms"] for i in p["items"])
    assert "Status bo'sh" not in u.full_report(hammasi, "Undiruv Oktyabr", date(2026, 10, 5))
    # Qisman bo'sh — haqiqiy anomaliya: ogohlantirish va qator belgisi qoladi
    qisman = [_row(f"L{i}", status="⏳ jarayonda") for i in range(8)] + [_row("X"), _row("Y")]
    for r in qisman[:8]:
        r["holat"] = ""
    t = u.totals(qisman)
    assert t["status_blank_n"] == 2 and t["unpaid_n"] == 10
    assert u.status_blank_warn(t) == "⚠️ Status bo'sh (tasdiqlanmagan qarz): 2/10 ta qator"
    d = u.report_data(qisman, "Undiruv Oktyabr", date(2026, 10, 5))
    assert sum(i["status_blank"] for p in d["pms"] for i in p["items"]) == 2


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
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
