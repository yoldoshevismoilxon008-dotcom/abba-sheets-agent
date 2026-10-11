"""AUDIT.md P0-1 — Undiruv oy tabi: barcha yo'llar bitta qat'iy qoida bilan.

01.08–06.08 va 01.09.2026 hisobotlarida pul bloki va SMM diff yilsiz «Undiruv <oy>»
(2025 arxivi) tabidan o'qigan. 💰 blok keyin tuzatilgan (undiruv.QATIY_DAN), lekin
kunlik diff watch'i (fetch.resolve_month_template), key_column va Q&A loyiha
qidiruvi hali yilsiz tabga tushardi. Bu testlar haqiqiy arxiv kunlarida hamma yo'l
bir xil tabni tanlashini va tab yo'q kuni hisobotga ⚠️ chiqishini tekshiradi.

Ikki rejimda: `pytest tests/test_undiruv_tab_qatiy.py` YOKI `python3 tests/test_undiruv_tab_qatiy.py`.
Tarmoq/credentials kerak emas.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze as an          # noqa: E402
import bot_listener as bl     # noqa: E402
import fetch as fmod          # noqa: E402
import undiruv as u           # noqa: E402

T = "Undiruv <oy>"
AUG04 = date(2026, 8, 4)
SEP01 = date(2026, 9, 1)
OKT01 = date(2026, 10, 1)
NOV01 = date(2026, 11, 1)
SAVOL = "Livardi loyihasi qayerda?"


# ------------------------------------------------------- yagona manba

def test_qatiy_dan_yagona_manba():
    assert u.QATIY_DAN == fmod.QATIY_DAN == date(2026, 8, 1)
    assert fmod.qatiy_oy(date(2026, 8, 1)) and not fmod.qatiy_oy(date(2026, 7, 1))


# ------------------------------------------------------- kunlik diff watch'i

def test_watch_0804_ikkalasi_bor_2026_tanlanadi():
    # 04.08: «Undiruv avgust(2026)» bor edi, hisobot esa yilsiz tabdan o'qigan
    tabs = ["Undiruv iyul", "Undiruv avgust", "Undiruv avgust(2026)", "Smm main"]
    assert fmod.resolve_month_template(T, tabs, AUG04) == ["Undiruv avgust(2026)"]


def test_watch_0901_joriy_yil_tabi_yoq_arxiv_tanlanmaydi():
    # 01.09: «Undiruv sentabr(2026)» hali ochilmagan, yilsiz «Undiruv sentabr» — 2025 arxivi
    tabs = ["Undiruv avgust", "Undiruv avgust(2026)", "Undiruv sentabr", "Smm main"]
    assert fmod.resolve_month_template(T, tabs, SEP01) == []


def test_watch_1001_imlo_aliasi():
    tabs = ["Undiruv oktabr", "Undiruv sentabr(2026)", "Undiruv oktabr(2026)"]
    assert fmod.resolve_month_template(T, tabs, OKT01) == ["Undiruv oktabr(2026)"]


def test_watch_1101_noyabr_arxivi_tanlanmaydi():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main"]
    assert fmod.resolve_month_template(T, tabs, NOV01) == []


def test_qatiydan_oldin_yilsiz_tab_ishlaydi():
    assert fmod.resolve_month_template(T, ["Undiruv iyul"], date(2026, 7, 20)) == ["Undiruv iyul"]


def test_boshqa_shablon_qatiy_emas():
    # «Hoji mini kpi <oy>» yil suffiksisiz nomlanadi — qat'iy qoida unga tegmaydi
    assert fmod.resolve_month_template("Hoji mini kpi <oy>", ["Hoji mini kpi sentabr"], SEP01) == \
        ["Hoji mini kpi sentabr"]


def test_kutilgan_tab_nomi():
    assert fmod.expected_month_tab(T, NOV01) == "Undiruv noyabr(2026)"
    assert fmod.expected_month_tab(T, SEP01) == "Undiruv sentabr(2026)"   # sheet imlosi
    assert fmod.expected_month_tab(T, OKT01) == "Undiruv oktabr(2026)"
    assert fmod.expected_month_tab(T, date(2026, 7, 20)) == "Undiruv iyul"
    assert fmod.expected_month_tab("Hoji mini kpi <oy>", SEP01) == "Hoji mini kpi sentabr"


# ------------------------------------------------------- key_column

def test_key_column_arxiv_tabga_berilmaydi():
    kc = {T: "Nomi", "Smm main": "Loyiha"}
    out = fmod.resolve_key_columns(["Undiruv noyabr", "Smm main"], kc, NOV01)
    assert fmod.tab_range("Undiruv noyabr") not in out
    assert out[fmod.tab_range("Smm main")] == "Loyiha"
    out = fmod.resolve_key_columns(["Undiruv noyabr", "Undiruv noyabr(2026)"], kc, NOV01)
    assert out == {fmod.tab_range("Undiruv noyabr(2026)"): "Nomi"}


def test_key_column_qatiydan_oldin_saqlanadi():
    out = fmod.resolve_key_columns(["Undiruv iyul"], {T: "Nomi"}, date(2026, 7, 20))
    assert out == {fmod.tab_range("Undiruv iyul"): "Nomi"}


# ------------------------------------------------------- fetch_sheet → watch_missing

def _fetch_sheet(tabs, today):
    asl = fmod.list_tabs, fmod.fetch_ranges
    fmod.list_tabs = lambda gc, sid: (None, list(tabs))
    fmod.fetch_ranges = lambda sh, ranges, label: {r: {"values": []} for r in ranges}
    try:
        s = {"name": "SMM proektlar", "id": "x", "watch_tabs": [T, "Smm main"],
             "key_column": {T: "Nomi"}}
        return fmod.fetch_sheet(None, s, today)[1]
    finally:
        fmod.list_tabs, fmod.fetch_ranges = asl


def test_fetch_sheet_tab_yoq_kuni_watch_missing():
    meta = _fetch_sheet(["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main"], NOV01)
    assert meta["watch_missing"] == ["Undiruv noyabr(2026)"]
    assert meta["watch_ranges"] == [fmod.tab_range("Smm main")]


def test_fetch_sheet_tab_bor_kuni_ogoh_yoq():
    meta = _fetch_sheet(["Undiruv oktabr", "Undiruv oktabr(2026)", "Smm main"], OKT01)
    assert meta["watch_missing"] == []
    assert meta["watch_ranges"] == [fmod.tab_range("Undiruv oktabr(2026)"), fmod.tab_range("Smm main")]


# ------------------------------------------------------- hisobot (analyze)

DIFF = {"date": "2026-11-01", "prev_date": "2026-10-31", "sheets": {
    "x": {"name": "SMM proektlar", "watch": "", "ranges": {},
          "watch_missing": ["Undiruv noyabr(2026)"]},
    "y": {"name": "Zubair PM KPI", "watch": "", "ranges": {}},
}}


def test_hisobotga_ogoh_qatori():
    notes = an.watch_missing_note(DIFF)
    assert len(notes) == 1
    assert notes[0].startswith("⚠️ SMM proektlar: «Undiruv noyabr(2026)» tabi topilmadi")


def test_ai_kontekstiga_diqqat():
    assert "DIQQAT: kuzatiladigan «Undiruv noyabr(2026)» tabi sheet'da yo'q" in an.build_context(DIFF)


def test_ogoh_yoq_kuni_jim():
    assert an.watch_missing_note({"sheets": {"x": {"name": "SMM", "ranges": {}}}}) == []


# ------------------------------------------------------- Q&A loyiha qidiruvi

def test_qa_1101_arxiv_emas_otgan_oy_tabi():
    tabs = ["Undiruv noyabr", "Undiruv oktabr", "Undiruv oktabr(2026)", "Smm main"]
    assert bl.project_lookup_tabs(tabs, SAVOL, today=NOV01) == ["Undiruv oktabr(2026)"]


def test_qa_joriy_va_otgan_oy():
    tabs = ["Undiruv sentabr", "Undiruv sentabr(2026)", "Undiruv oktabr(2026)", "Smm main"]
    assert bl.project_lookup_tabs(tabs, SAVOL, today=date(2026, 10, 11)) == \
        ["Undiruv oktabr(2026)", "Undiruv sentabr(2026)"]


def test_qa_yil_almashuvi():
    tabs = ["Undiruv dekabr", "Undiruv dekabr(2026)", "Undiruv yanvar(2027)"]
    assert bl.project_lookup_tabs(tabs, SAVOL, today=date(2027, 1, 5)) == \
        ["Undiruv yanvar(2027)", "Undiruv dekabr(2026)"]


def test_qa_loyiha_savoli_emas():
    assert bl.project_lookup_tabs(["Undiruv oktabr(2026)"], "Bugun nechta xabar keldi?", today=OKT01) == []


# ------------------------------------------------------- yagona tartib (kanonik nom birinchi)

def test_diff_watch_va_pul_bloki_bir_tabni_tanlaydi():
    for tabs in (["Undiruv oktabr(2026) shablon", "Undiruv oktabr(2026)"],
                 ["Undiruv oktabr (2026)", "Undiruv oktabr(2026) nusxa"],
                 ["Undiruv oktabr(2026)", "Undiruv oktabr(2026)  "]):
        a = fmod.resolve_month_template(T, tabs, OKT01)[0]
        b = u.rank_month_tabs(tabs, "oktyabr", OKT01, year=2026, suffikssiz=False)[0]
        assert a == b, (tabs, a, b)


def test_resolve_watch_tabs_yagona():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main", "Pm proektlar After"]
    assert fmod.resolve_watch_tabs([T, "Smm main", "Pm proektlar After"], tabs, NOV01) == \
        (["Smm main", "Pm proektlar After"], ["Undiruv noyabr(2026)"])
    assert fmod.resolve_watch_tabs("auto", ["Main", "Oktyabr"], OKT01) == (["Main", "Oktyabr"], [])


# ------------------------------------------------------- undiruv.month_tab

def test_month_tab_yillar():
    tabs = ["Undiruv dekabr", "Undiruv noyabr", "Undiruv oktabr", "Undiruv oktabr(2026)"]
    assert u.month_tab(tabs, "oktyabr", date(2026, 10, 11)) == ("Undiruv oktabr(2026)", 2026)
    assert u.month_tab(tabs, "dekabr", date(2026, 10, 11)) == ("Undiruv dekabr", 2025)   # 2025 arxivi — to'g'ri tab
    assert u.month_tab(tabs, "noyabr", NOV01) == (None, 2026)                            # arxiv emas
    # oy oxirida kelasi oy tabi oldindan ochilgan — o'sha, o'tgan yil arxivi emas
    assert u.month_tab(tabs, "oktabr", date(2026, 9, 29)) == ("Undiruv oktabr(2026)", 2026)
    assert u.month_tab(["Undiruv dekabr(2026)"], "dekabr", date(2027, 1, 5)) == ("Undiruv dekabr(2026)", 2026)


# ------------------------------------------------------- Q&A «undiruv» oy guruhi

def test_qa_guruh_1101_arxiv_emas():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main", "Pm proektlar After"]
    sel, notes = bl.tabs_for_question(tabs, "undiruv qancha?", today=NOV01)
    assert "Undiruv noyabr" not in sel
    assert "Undiruv oktabr(2026)" in sel
    assert any("«Undiruv noyabr(2026)»" in n and "arxiv" in n for n in notes), notes


def test_qa_guruh_bugun_faqat_2026():
    tabs = ["Undiruv sentabr", "Undiruv oktabr", "Undiruv sentabr(2026)", "Undiruv oktabr(2026)", "Smm main"]
    sel, _ = bl.tabs_for_question(tabs, "undiruv qancha?", today=date(2026, 10, 11))
    assert [t for t in sel if t.startswith("Undiruv")] == ["Undiruv oktabr(2026)"]


def test_qa_guruh_arxiv_aniq_sorovda_ochiq():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)"]
    sel, notes = bl.tabs_for_question(tabs, "2025 noyabr undiruv arxivi", today=NOV01)
    assert "Undiruv noyabr" in sel
    assert any("arxiv" in n for n in notes)


# ------------------------------------------------------- /hisobot (jonli oraliq diff)

class _Kun(date):
    KUN = NOV01

    @classmethod
    def today(cls):
        return cls.KUN


def _hisobot(kun, tabs, old_ranges):
    """do_hisobot'ni tarmoqsiz ishga tushiradi: (yuborilgan xabarlar, o'qilgan range'lar)."""
    sent, read = [], []
    vals = {"values": [["Nomi", "Summa"], ["Remax", "$5 000"]]}
    snap = {"id": "smm", "name": "SMM proektlar", "ranges": {r: dict(vals) for r in old_ranges}}
    cfg = [{"id": "smm", "name": "SMM proektlar", "watch_tabs": [T, "Smm main"],
            "key_column": {T: "Nomi"}}]

    def fetch_ranges(sh, ranges, label):
        read.extend(ranges)
        return {r: dict(vals) for r in ranges}

    patches = [(bl, "typing", lambda *a, **k: None), (bl, "send_retry", lambda m, **k: sent.append(m)),
               (bl, "remember", lambda *a, **k: None), (bl, "latest_day", lambda: "2026-10-31"),
               (bl, "sheet_tabs", lambda s: (None, list(tabs))), (bl, "date", _Kun),
               (bl.diffmod, "load_day", lambda d: ({"smm": snap}, {})),
               (bl.fetchmod, "load_config", lambda **k: cfg), (bl.fetchmod, "fetch_ranges", fetch_ranges)]
    asl = [(o, n, getattr(o, n)) for o, n, _ in patches]
    _Kun.KUN = kun
    try:
        for o, n, v in patches:
            setattr(o, n, v)
        bl.do_hisobot()
    finally:
        for o, n, v in asl:
            setattr(o, n, v)
    return sent, [fmod.tab_of_range(r) for r in read]


def test_hisobot_1101_arxiv_kuzatilmaydi_ogoh_chiqadi():
    sent, read = _hisobot(NOV01, ["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main"],
                          [fmod.tab_range("Smm main")])
    assert read == ["Smm main"]
    assert "«Undiruv noyabr(2026)» tabi topilmadi" in sent[-1]


def test_hisobot_1105_2026_tab_kuzatiladi():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)", "Undiruv noyabr(2026)", "Smm main"]
    sent, read = _hisobot(date(2026, 11, 5), tabs,
                          [fmod.tab_range("Undiruv noyabr(2026)"), fmod.tab_range("Smm main")])
    assert read == ["Undiruv noyabr(2026)", "Smm main"]
    assert "topilmadi" not in sent[-1]


def test_hisobot_bugun_oktabr_imlo():
    # «oktyabr» (current_month_name) va «oktabr» (sheet) — avval /hisobot Undiruv tabini umuman ko'rmasdi
    tabs = ["Undiruv oktabr", "Undiruv oktabr(2026)", "Smm main"]
    _sent, read = _hisobot(date(2026, 10, 11), tabs,
                           [fmod.tab_range("Undiruv oktabr(2026)"), fmod.tab_range("Smm main")])
    assert read == ["Undiruv oktabr(2026)", "Smm main"]


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
