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
         pm_col_present=True, holat="pending", undirildi=0, aktiv=0, status_raw="pending",
         lose=0, lose_col_present=True):
    return {
        "loyiha": loyiha, "pm": pm, "pm_missing": pm_missing,
        "pm_col_present": pm_col_present, "qoldiq": qoldiq, "qoldiq_raw": str(qoldiq),
        "undirildi": undirildi, "aktiv": aktiv, "kelishilgan": qoldiq + undirildi,
        "lose": lose, "lose_raw": str(lose) if lose else "",
        "lose_col_present": lose_col_present,
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


# ---------------------------------------------------- Lose summa (ketgan loyihalar)

def test_status_emoji_normalization():
    # «🚪 Ketdi» kabi emoji-prefiks, registr, chetki bo'shliq → «ketdi»
    for s in ("🚪 Ketdi", "Ketdi", "⛔ Ketdi", " KETDI ", "🚪  ketdi"):
        assert u._status(s) == "ketdi", s
    # «ketdi» bo'lmagan statuslar noto'g'ri tushib qolmasin
    assert u._status("Kutilmoqda") == "pending"
    assert u._status("To'lov qilindi ✅") == "paid"


def test_money_spaced_parsing():
    # «$1 600» — probel bilan yoziladi (oddiy probel + NBSP + ingichka probel)
    assert u.money("$1 600") == 1600.0
    assert u.money("$1\xa0600") == 1600.0          # NBSP
    assert u.money("1 800,50") == 1800.50          # vergul o'nlik
    assert u.money("") == 0.0 and u.money("—") == 0.0


# «Lose summa» sarlavhasini NOM bo'yicha o'qish (mavjud header-parsing) + «Summa»
# (qoldiq) bilan ADASHMASLIK + emoji-status + probelli pul — end-to-end parse_rows.
_LOSE_VALS = [
    ["№", "Nomi", "Ma'sul shaxs", "Summa", "Undirildi", "Aktive Summary",
     "Final data", "To'lov xolati", "Lose summa"],
    ["1", "Welle", "Zubair", "0", "0", "0", "", "🚪 Ketdi", "$1 800"],
    ["2", "Oqsaroy", "Islom", "1 600", "0", "0", "05.08", "Kutilmoqda", "$1 600"],
    ["3", "Savy", "Islom", "1 800", "0", "0", "06.08", "", "$1 800"],
    ["4", "Baaz", "Zubair", "1 266", "500", "0", "04.08", "", ""],
    ["Jami", "", "", "", "", "", "", "", ""],
]


def test_parse_rows_lose_column_by_name():
    rows = u.parse_rows(_LOSE_VALS, T)
    by = {r["loyiha"]: r for r in rows}
    # «Summa» (qoldiq) va «Lose summa» ALOHIDA o'qilsin — substring adashuvi yo'q
    assert by["Welle"]["qoldiq"] == 0 and by["Welle"]["lose"] == 1800
    assert by["Oqsaroy"]["qoldiq"] == 1600 and by["Oqsaroy"]["lose"] == 1600
    assert by["Baaz"]["lose"] == 0            # bo'sh «Lose summa» → 0
    assert by["Welle"]["holat"] == "ketdi"    # «🚪 Ketdi» → ketdi


def test_lose_summary_august_scenario():
    # Kutilyapti: ro'yxatda faqat Welle $1 800; Oqsaroy+Savy ogohlantirishda
    r = u.lose_summary(u.parse_rows(_LOSE_VALS, T))
    assert r["count"] == 1 and r["total"] == 1800
    assert r["items"] == [{"nomi": "Welle", "masul": "Zubair",
                           "summa": 1800, "flag": ""}]
    assert len(r["warnings"]) == 1
    assert "Oqsaroy, Savy" in r["warnings"][0] and "«Ketdi» emas" in r["warnings"][0]


def test_lose_ketdi_empty_summa_flag():
    # Status Ketdi, lekin «Lose summa» bo'sh → ro'yxatga «summa yozilmagan» flag
    # bilan (jamiga 0), BITTA jamlangan warn (warn devori emas)
    r = u.lose_summary([_row("Xyz", holat="ketdi", lose=0),
                        _row("Welle", holat="ketdi", lose=1800)])
    assert r["count"] == 2 and r["total"] == 1800        # bo'sh qator jamiga 0
    xyz = next(i for i in r["items"] if i["nomi"] == "Xyz")
    assert xyz["flag"] == "summa yozilmagan" and xyz["summa"] == 0
    assert len(r["warnings"]) == 1
    assert r["warnings"][0] == ("1 qatorda status «Ketdi», lekin «Lose summa» "
                                "yozilmagan: Xyz.")


def test_lose_mismatch_not_ketdi_excluded():
    # «Lose summa» > 0, status Ketdi EMAS → ro'yxat va jamiga KIRMAYDI, faqat warn
    r = u.lose_summary([_row("Oqsaroy", holat="pending", lose=1600),
                        _row("Savy", holat="paid", lose=1800)])
    assert r["items"] == [] and r["total"] == 0 and r["count"] == 0
    assert len(r["warnings"]) == 1
    assert r["warnings"][0].startswith("2 qatorda") and "Oqsaroy, Savy" in r["warnings"][0]


def test_lose_empty_state():
    # Ketdi qator umuman yo'q va mismatch ham yo'q → bo'sh, ogohlantirishsiz
    r = u.lose_summary([_row("A", holat="pending"), _row("B", holat="paid")])
    assert r == {"items": [], "total": 0, "count": 0, "warnings": []}


def test_report_data_delegates_to_lose_summary():
    # YAGONA manba: report_data["lose"] == lose_summary(rows) (mustaqil hisob yo'q)
    rows = u.parse_rows(_LOSE_VALS, T)
    d = u.report_data(rows, "Undiruv avgust(2026)", T, source="live")
    assert d["lose"] == u.lose_summary(rows)


# «Lose summa» ustuni YO'Q tab (eski oy / 2025 arxivi) — pm_col_present naqshi kabi
_NOLOSE_VALS = [
    ["№", "Nomi", "Ma'sul shaxs", "Summa", "Undirildi", "Aktive Summary",
     "Final data", "To'lov xolati"],                       # «Lose summa» YO'Q
    ["1", "EskiKetgan", "Zubair", "0", "0", "0", "", "🚪 Ketdi"],
    ["Jami", "", "", "", "", "", "", ""],
]


def test_lose_col_missing_hides_block():
    # Fix 1 (BLOKER): ustunsiz tabda ketdi qator bor bo'lsa ham blok yolg'on
    # gapirmasin — col_missing True, blok BUTUNLAY yashiriladi
    rows = u.parse_rows(_NOLOSE_VALS, T)
    assert rows[0]["lose_col_present"] is False
    r = u.lose_summary(rows)
    assert r == {"items": [], "total": 0, "count": 0, "warnings": [], "col_missing": True}
    # full_report — na blok sarlavhasi, na «ketgan loyiha yo'q» (ikkalasi ham yolg'on)
    txt = u.full_report(rows, "Undiruv iyul(2025)", T, source="live")
    assert "Yo'qotilgan loyihalar" not in txt and "ketgan loyiha yo" not in txt


def test_lose_empty_summa_aggregated():
    # Fix 2: 12 bo'sh-summali «Ketdi» qator → BITTA warn (12 satr emas), 8+«+4 ta»
    rows = [_row(f"P{i}", holat="ketdi", lose=0) for i in range(12)]
    r = u.lose_summary(rows)
    assert r["count"] == 12 and r["total"] == 0
    assert len(r["warnings"]) == 1
    # faqat 8 nom ko'rsatiladi, qolgan 4 tasi «+4 ta»ga yig'iladi
    assert r["warnings"][0] == ("12 qatorda status «Ketdi», lekin «Lose summa» "
                                "yozilmagan: P0, P1, P2, P3, P4, P5, P6, P7 +4 ta.")


def test_lose_mismatch_truncation():
    # Fix 2: 25 mismatch → bitta qisqa warn (8 nom + «+17 ta»), 315 belgi emas
    rows = [_row(f"M{i}", holat="pending", lose=1000) for i in range(25)]
    r = u.lose_summary(rows)
    assert r["items"] == [] and r["count"] == 0 and len(r["warnings"]) == 1
    w = r["warnings"][0]
    assert w.startswith("25 qatorda «Lose summa» bor") and "+17 ta" in w
    assert len(w) < 150


def test_lose_negative_value():
    # Fix 3: manfiy «Lose summa» → summa=0, flag «summa noto'g'ri», ALOHIDA warn
    # (sabab «bo'sh» EMAS); jamiga qo'shilmaydi
    r = u.lose_summary([_row("Neg", holat="ketdi", lose=-1800),
                        _row("Welle", holat="ketdi", lose=1800)])
    assert r["count"] == 2 and r["total"] == 1800
    neg = next(i for i in r["items"] if i["nomi"] == "Neg")
    assert neg["flag"] == "summa noto'g'ri" and neg["summa"] == 0
    assert any("manfiy" in w and "Neg" in w for w in r["warnings"])
    assert not any("yozilmagan" in w for w in r["warnings"])  # «bo'sh» warn'iga tushmasin


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
