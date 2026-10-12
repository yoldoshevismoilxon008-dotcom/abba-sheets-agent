"""AUDIT.md P0-4 ildiz sababi — PM KPI diff noto'g'ri oy tabini kuzatgan.

2026-10-12 hisoboti (P0-4 jimlik ⚠️ qatori) ko'rsatdi: 4 PM'da yilsiz «Oktyabr» 01.10 dan
beri o'zgarmagan, PM'lar esa «Oktyabr (2026)» ni to'ldirmoqda. Ega qarori (2026-10-12):
rasmiy tab «<Oy> (<yil>)». Bu testlar shu yagona qoidani (fetch.pm_month_tab) kunlik diff,
key_column, jimlik nazorati, audit va Q&A yo'llarida tekshiradi. Tab nomlari — 10-12
hisobotidagi haqiqiy nomlar (oxiridagi bo'shliqlar bilan).

Ikki rejimda: `pytest tests/test_pm_kpi_oy_tab.py` YOKI `python3 tests/test_pm_kpi_oy_tab.py`.
"""

import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze as an          # noqa: E402
import audit                  # noqa: E402
import bot_listener as bl     # noqa: E402
import dashboard             # noqa: E402
import diff as dmod           # noqa: E402
import fetch as fmod          # noqa: E402
from fetch import tab_range   # noqa: E402

OKT12 = date(2026, 10, 12)
ZUBAIR = ["Loyihalarning ishlash muddati", "Oktyabr", "Sentyabr", "Oktyabr (2026) ", "Sentyabr (2026)",
          "Managerlar oktyabr kpi (2026)   ", "Managerlar sentyabr kpi (2026)  "]
ABDUFATTOH = ["Main", "Avgust (2026)", "Sentyabr(2026)", "Oktyabr", "Oktyabr (2026) ",
              "Managerlar oktyabr kpi  (2026)", "Managerlar sentyabr kpi  (2026)"]
ISLOM = ["Main", "Oktyabr", "Sentyabr (2026)", "Managerlar sentyabr kpi (2026)"]


# ------------------------------------------------------- tab tanlash

def test_zubair_yillik_tab_kuzatiladi():
    assert fmod.pm_month_tab(ZUBAIR, OKT12) == "Oktyabr (2026) "
    assert fmod.resolve_watch_tabs("auto", ZUBAIR, OKT12) == \
        (["Loyihalarning ishlash muddati", "Oktyabr (2026) "], [])


def test_abdufattoh_boshliqsiz_va_bir_nechta_oy():
    assert fmod.resolve_watch_tabs("auto", ABDUFATTOH, OKT12) == (["Main", "Oktyabr (2026) "], [])
    assert fmod.pm_month_tab(ABDUFATTOH, date(2026, 9, 15)) == "Sentyabr(2026)"


def test_tab_yoq_bolsa_yilsizga_qaytilmaydi_va_ogohlantiradi():
    watch, missing = fmod.resolve_watch_tabs("auto", ISLOM, OKT12)
    assert watch == ["Main"] and missing == ["Oktyabr (2026)"]
    notes = an.watch_missing_note({"sheets": {"isl": {"name": "Islom PM KPI", "watch_missing": missing}}})
    assert notes and notes[0].startswith("⚠️ Islom PM KPI: «Oktyabr (2026)» tabi topilmadi"), notes


def test_oy_almashuvi_noyabr():
    nov = date(2026, 11, 1)
    assert fmod.resolve_watch_tabs("auto", ["Main", "Oktyabr (2026)"], nov) == (["Main"], ["Noyabr (2026)"])
    assert fmod.resolve_watch_tabs("auto", ["Main", "Oktyabr (2026)", "Noyabr (2026)"], nov) == \
        (["Main", "Noyabr (2026)"], [])


def test_boshqa_yil_nusxa_va_manager_tabi_tanlanmaydi():
    for tabs in (["Oktyabr (2025)"], ["Oktyabr (2026) nusxa"], ["Managerlar oktyabr kpi (2026)"],
                 ["Oktyabr 2026"], ["Oktyabr"]):
        assert fmod.pm_month_tab(tabs, OKT12) is None, tabs


def test_imlo_va_bosh_joy_farqlari():
    assert fmod.pm_month_tab(["Oktabr (2026)"], OKT12) == "Oktabr (2026)"
    assert fmod.pm_month_tab(["oktyabr( 2026 )"], OKT12) == "oktyabr( 2026 )"
    assert fmod.pm_month_tab(["Sentabr(2026)"], date(2026, 9, 2)) == "Sentabr(2026)"


def test_qatiy_dan_oldin_eski_qoida_ozgarmagan():
    avg = date(2026, 8, 15)
    assert fmod.resolve_watch_tabs("auto", ["Main", "Avgust", "Avgust (2026)"], avg) == (["Main", "Avgust"], [])
    assert fmod.resolve_watch_tabs("auto", ["Main"], avg) == (["Main"], [])


def test_key_column_yillik_tabga_boglanadi():
    kc = fmod.resolve_key_columns(ZUBAIR, {"main": "Loyihalar", "month": "Proekt nomi"}, OKT12)
    assert kc[tab_range("Oktyabr (2026) ")] == "Proekt nomi"
    assert tab_range("Oktyabr") not in kc
    assert kc[tab_range("Loyihalarning ishlash muddati")] == "Loyihalar"


# ------------------------------------------------------- jimlik nazorati va oy almashuvi

HDR = ["Proekt nomi", "Kpi ideal bali", "Proekt bali", "Kechga qolgan kunlar"]


def _vals(ball):
    return [HDR, ["Kanzec", "41,2", str(ball), "2"], ["Mix Mobile", "50,0", "43,0", "0"]]


def _yoz(root, day, tabs, watch):
    d = Path(root) / day
    d.mkdir(parents=True, exist_ok=True)
    snap = {"id": "zub", "name": "Zubair PM KPI", "watch": "", "pm_kpi": True, "track_other_tabs": True,
            "key_column": {tab_range(t): "Proekt nomi" for t in tabs},
            "watch_ranges": [tab_range(t) for t in watch],
            "ranges": {tab_range(t): {"values": v} for t, v in tabs.items()}}
    (d / "zub.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    (d / "_meta.json").write_text(json.dumps({"date": day, "ok": 1, "errors": {}}), encoding="utf-8")
    return snap


def _diff(root, day):
    asl = dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari
    dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari = Path(root), ["diff.py", "--date", day], lambda: set()
    try:
        assert dmod.main() == 0
    finally:
        dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari = asl
    return json.loads((Path(root) / day / "diff.json").read_text(encoding="utf-8"))


def test_jimlik_yillik_tabni_taniydi():
    root = tempfile.mkdtemp(prefix="pm-oy-")
    try:
        for i in range(1, 9):
            snap = _yoz(root, f"2026-10-{i:02d}", {"Oktyabr (2026) ": _vals("29,0"), "Oktyabr": _vals(f"{30 + i},0")},
                        ["Oktyabr (2026) "])
        st = dmod.stale_info("zub", snap, [tab_range("Oktyabr (2026) ")], "2026-10-08",
                             snapshots=Path(root), dam=())
        assert len(st) == 1 and st[0]["tab"] == "Oktyabr (2026) " and st[0]["other_changed"] == ["Oktyabr"], st
    finally:
        shutil.rmtree(root)


def test_otish_kuni_yangi_oy_tabi_deb_elon_qilinadi():
    r = {}
    dmod.mark_watch_new(r, tab_range("Oktyabr (2026) "), {"watch_ranges": [tab_range("Oktyabr")]}, "2026-10-13")
    assert r == {"watch_new": True, "watch_new_month": True}, r


def test_statistika_yillik_tabdan_olinadi():
    """Review: PDF PM kartalari, caption %, dashboard va Q&A agregati yilsiz nomni kutib
    yangi tabni tashlab yuborardi (_day_stats → {}). Eski snapshot'lar ham ishlashi kerak."""
    root = tempfile.mkdtemp(prefix="pm-oy-")
    asl = dmod.SNAPSHOTS
    try:
        dmod.SNAPSHOTS = Path(root)
        yangi = _yoz(root, "2026-10-13", {"Oktyabr (2026) ": _vals("29,0"), "Oktyabr": _vals("1,0")},
                     ["Oktyabr (2026) "])
        eski = _yoz(root, "2026-10-12", {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        for snap in (yangi, eski):
            assert dashboard.sheet_stats(snap)["fakt"] == 72.0, snap["watch_ranges"]
            assert bl.month_aggregate(snap)[1:] == (91.2, 72.0)
        st = an._day_stats("2026-10-13")["Zubair PM KPI"]
        assert st["pct"] == 78.9 and st["aktiv"] == 2, st
        assert an._day_stats("2026-10-12")["Zubair PM KPI"]["pct"] == 78.9
    finally:
        dmod.SNAPSHOTS = asl
        shutil.rmtree(root)


def test_oy_ortasida_paydo_bolgan_tab_elon_qilinadi():
    root = tempfile.mkdtemp(prefix="pm-oy-")
    try:
        _yoz(root, "2026-10-14", {"Oktyabr": _vals("29,0")}, [])
        _yoz(root, "2026-10-15", {"Oktyabr": _vals("29,0"), "Oktyabr (2026)": _vals("30,0")}, ["Oktyabr (2026)"])
        notes = an.deterministic_notes(_diff(root, "2026-10-15"))
        assert "ℹ️ Zubair PM KPI: «Oktyabr (2026)» tabi paydo bo'ldi va kuzatuvga olindi (2 qator) — " \
               "o'zgarishlar ertadan ko'rinadi." in notes, notes
    finally:
        shutil.rmtree(root)


def test_bosh_watch_hamma_tabni_diff_qilmaydi():
    """Kuzatiladigan tab topilmagan kun (watch_ranges=[]) — hamma tab diff'ga tushmasin, yilsiz
    «Oktyabr» jimlik ⚠️ bermasin; faqat «topilmadi» ⚠️ qoladi."""
    root = tempfile.mkdtemp(prefix="pm-oy-")
    try:
        for i in range(1, 9):
            _yoz(root, f"2026-10-{i:02d}", {"Oktyabr": _vals("29,0"), "Sentyabr": _vals(f"{i},0")}, [])
        d = _diff(root, "2026-10-08")
        assert d["sheets"]["zub"]["ranges"] == {}, d["sheets"]["zub"]["ranges"].keys()
        assert not any("o'zgarmagan" in n for n in an.deterministic_notes(d))
    finally:
        shutil.rmtree(root)


# ------------------------------------------------------- audit va Q&A

def test_audit_yillik_tabni_tekshiradi():
    snap = {"name": "Islom PM KPI", "pm_kpi": True, "tabs": ISLOM,
            "ranges": {tab_range(t): {"values": [["x"]]} for t in ISLOM}}
    f = []
    audit.audit_sheet(snap, f, today=OKT12)
    assert ("Islom PM KPI", "—", audit.CRIT, "Joriy oy tabi «Oktyabr (2026)» topilmadi", "oy-tab-yoq") in f, f


def test_qa_rasmiy_oy_tabini_yuklaydi():
    tabs, _ = bl.tabs_for_question(ZUBAIR, "Zubairning loyihalari qanday?", today=OKT12)
    assert "Oktyabr (2026) " in tabs and "Oktyabr" not in tabs, tabs
    tabs, _ = bl.tabs_for_question(ZUBAIR, "sentyabr kpi ballari", today=OKT12)
    assert "Sentyabr (2026)" in tabs and "Sentyabr" not in tabs, tabs
    # guruh prefiksi («managerlar … kpi») mos kelgan yo'l — `other` qo'shilmaydi, rasmiy tab baribir bor
    tabs, _ = bl.tabs_for_question(ZUBAIR, "managerlar sentyabr kpi", today=OKT12)
    assert "Sentyabr (2026)" in tabs, tabs
    tabs, _ = bl.tabs_for_question(ABDUFATTOH, "managerlar avgust kpi", today=OKT12)
    assert "Avgust (2026)" in tabs, tabs
    tabs, _ = bl.tabs_for_question(ZUBAIR, "oktyabr ballari", today=OKT12)
    assert "Oktyabr (2026) " in tabs and "Oktyabr" not in tabs, tabs


def test_qa_rasmiy_tab_yoq_bolsa_izoh_beradi():
    tabs, notes = bl.tabs_for_question(ISLOM, "Islomning oktyabr ballari", today=OKT12)
    assert "Oktyabr" in tabs and any("«Oktyabr (2026)» tabi yo'q" in n and "rasmiy" in n for n in notes), notes
    tabs, notes = bl.tabs_for_question(ZUBAIR, "oktyabr arxiv ballari", today=OKT12)
    assert "Oktyabr" in tabs, tabs                                     # «arxiv» so'ralsa yilsiz ham ochiq
    assert bl.savol_oyi("dekabr", date(2027, 1, 5)) == date(2026, 12, 1)


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
