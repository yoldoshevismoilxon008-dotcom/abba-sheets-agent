"""undiruv/pm_push — oy-tab tanlash, parse_due, no-date bo'limi testlari.

Ikki rejimda: `pytest tests/test_undiruv_push.py` YOKI `python3 tests/test_undiruv_push.py`.
Hammasi pure funksiyalar — tarmoq/credentials kerak emas.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import undiruv as u   # noqa: E402
import pm_push as pp  # noqa: E402

T = date(2026, 8, 6)


# ---------------------------------------------------------------- oy-tab tanlash

def test_rank_current_year_beats_suffixless():
    # 'Undiruv avgust' = 2025 arxivi (suffikssiz), '(2026)' = joriy — (2026) ustun
    r = u.rank_month_tabs(["Undiruv avgust", "Undiruv avgust(2026)"], "avgust", T)
    assert r[0] == "Undiruv avgust(2026)"


def test_rank_suffixless_beats_other_year():
    # ['(2025)', suffikssiz] → 2025 arxiv chiqariladi, suffikssiz tanlanadi
    r = u.rank_month_tabs(["Undiruv sentabr(2025)", "Undiruv sentabr"], "sentyabr", T)
    assert r == ["Undiruv sentabr"]


def test_rank_only_other_year_excluded():
    # faqat boshqa-yil arxivi → HECH QANDAY kandidat (egaga "topilmadi" ketadi)
    assert u.rank_month_tabs(["Undiruv avgust(2025)"], "avgust", T) == []
    assert u.rank_month_tabs(["Undiruv avgust(2024)", "Undiruv avgust(2025)"], "avgust", T) == []


def test_rank_alias_sentabr():
    # sentyabr↔sentabr imlo aliasi (1-sentabr avtomatik ishlashi uchun)
    sep = date(2026, 9, 6)
    assert u.rank_month_tabs(["Undiruv sentabr"], "sentyabr", sep) == ["Undiruv sentabr"]


def test_rank_no_cross_month():
    # "undiruv may" "mart"ga mos kelmasin (chegara aniq)
    assert u.rank_month_tabs(["Undiruv may", "Undiruv mart"], "mart", T) == ["Undiruv mart"]


def test_latest_tab_skips_archive():
    assert u._latest_month_tab(["Undiruv avgust(2025)"], T) is None
    assert u._latest_month_tab(["Undiruv avgust(2025)", "Undiruv iyul(2026)"], T) == "Undiruv iyul(2026)"


# ---------------------------------------------------------------- parse_due

def test_parse_due_formats():
    assert u.parse_due("05.08", T) == date(2026, 8, 5)
    assert u.parse_due("5.8", T) == date(2026, 8, 5)
    assert u.parse_due(" 05.08 ", T) == date(2026, 8, 5)      # bo'shliqli
    assert u.parse_due("05,08", T) == date(2026, 8, 5)        # vergulli
    assert u.parse_due("05.08.2025", T) == date(2025, 8, 5)   # yil bilan
    assert u.parse_due("05/08/2025", T) == date(2025, 8, 5)
    assert u.parse_due("2026-08-05", T) == date(2026, 8, 5)   # ISO
    assert u.parse_due(45874, T) == date(2025, 8, 5)          # serial (int)
    assert u.parse_due(45874.0, T) == date(2025, 8, 5)        # serial (float)
    assert u.parse_due("45874", T) == date(2025, 8, 5)        # serial (satr)


def test_parse_due_invalid():
    for bad in ("", "  ", "abc", "0", "5", "32.08", "2026-13-01", None, True):
        assert u.parse_due(bad, T) is None, bad


# ---------------------------------------------------------------- build_push no-date

def _row(loyiha, qoldiq=1000, muddat=None, pm="Zubair", pm_missing=False,
         pm_col_present=True, holat="pending", undirildi=0, aktiv=0, status_raw="pending"):
    return {
        "loyiha": loyiha, "pm": pm, "pm_missing": pm_missing,
        "pm_col_present": pm_col_present, "qoldiq": qoldiq, "qoldiq_raw": str(qoldiq),
        "undirildi": undirildi, "aktiv": aktiv, "kelishilgan": qoldiq + undirildi,
        "status_blank": not status_raw, "muddat": muddat, "muddat_raw": "", "holat": holat,
    }


def test_nodate_row_goes_to_pm_section():
    rows = [
        _row("Alfa", qoldiq=1000, muddat=None, pm="Zubair"),           # muddatsiz + PM
        _row("Beta", qoldiq=2000, muddat=date(2026, 8, 5), pm="Islom"),  # muddat o'tgan
    ]
    per_pm, stats = pp.build_push(T, rows, [], "iyul")
    assert stats["no_date"] == 1
    assert "Zubair" in stats["nodate_pm"] and stats["nodate_pm"]["Zubair"]
    assert "Alfa" in stats["nodate_pm"]["Zubair"][0]
    assert "Islom" in per_pm                          # muddatli → oddiy bo'lim
    assert "Zubair" not in per_pm                      # faqat muddatsiz → per_pm'da yo'q


def test_nodate_pm_missing_goes_to_owner():
    rows = [_row("Gamma", qoldiq=1500, muddat=None, pm="—",
                 pm_missing=True, pm_col_present=False)]
    per_pm, stats = pp.build_push(T, rows, [], "iyul")
    assert not stats["nodate_pm"]                       # PM'ga ketmadi
    assert any("Gamma" in x["line"] for x in stats["pm_missing"])   # egaga


def test_qoldiq_is_D_no_subtraction():
    # qoldiq = Summa(D) AYIRMASIZ — undirildi ayrilmaydi (1266, 766 emas)
    rows = [_row("Baaz", qoldiq=1266, undirildi=500, muddat=date(2026, 8, 4), pm="Zubair")]
    per_pm, _ = pp.build_push(T, rows, [], "iyul")
    line = per_pm["Zubair"][0]
    assert "1 266" in line and "766" not in line


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
