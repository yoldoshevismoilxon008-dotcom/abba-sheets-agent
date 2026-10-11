"""AUDIT.md P0-4 — PM KPI diff'i 01.09–09.10 da 37 hisobotda «o'zgarish yo'q" degan.

Diff qatorlarni to'liq solishtiradi — ma'lumot haqiqatan o'zgarmagan yoki PM boshqa
tabni (masalan «Sentyabr (2026)» agregati) to'ldirgan. Ikkalasida ham jimlik hech
qanday signal bermagan. Bu testlar: joriy oy tabi ≥3 ish kuni o'zgarmasa ⚠️ chiqadi,
boshqa tablar o'zgargani nomma-nom ko'rsatiladi, oy almashuvida yangi tab belgilanadi.

Ikki rejimda: `pytest tests/test_pm_kpi_jimlik.py` YOKI `python3 tests/test_pm_kpi_jimlik.py`.
Tarmoq/credentials kerak emas.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze as an      # noqa: E402
import diff as dmod       # noqa: E402
from fetch import tab_range  # noqa: E402

SID = "zub"
HDR = ["Proekt nomi", "Proekt bali"]


def _vals(ball):
    return [HDR, ["Kanzec", str(ball)], ["Mix Mobile", "43,0"]]


def _yoz(root, day, tabs, watch, pm_kpi=True):
    """tabs: {tab: values}; watch: tab nomlari."""
    d = Path(root) / day
    d.mkdir(parents=True, exist_ok=True)
    snap = {"id": SID, "name": "Zubair PM KPI", "watch": "", "pm_kpi": pm_kpi, "track_other_tabs": True,
            "key_column": {tab_range(t): "Proekt nomi" for t in tabs},
            "watch_ranges": [tab_range(t) for t in watch],
            "ranges": {tab_range(t): {"values": v} for t, v in tabs.items()}}
    (d / f"{SID}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    (d / "_meta.json").write_text(json.dumps({"date": day, "ok": 1, "errors": {}}), encoding="utf-8")
    return snap


def _kunlar(a, b):
    return [f"2026-10-{d:02d}" for d in range(a, b + 1)]


def _stale(root, today, watch=("Oktyabr",)):
    snap = json.loads((Path(root) / today / f"{SID}.json").read_text(encoding="utf-8"))
    return dmod.stale_info(SID, snap, [tab_range(t) for t in watch], today, snapshots=Path(root))


def _tmp():
    return tempfile.mkdtemp(prefix="p0-4-")


# ------------------------------------------------------- stale_info

def test_jim_tab_boshqa_tab_ozgargan():
    # Oktyabr 01.10 dan bir xil; PM esa «Oktyabr (2026)» agregatini to'ldiryapti
    root = _tmp()
    try:
        for i, d in enumerate(_kunlar(1, 7)):
            _yoz(root, d, {"Oktyabr": _vals("29,0"), "Oktyabr (2026)": _vals(f"{30 + i},0")}, ["Oktyabr"])
        st = _stale(root, "2026-10-07")
        assert st == [{"tab": "Oktyabr", "kun": 5, "since": "2026-10-01",
                       "other_changed": ["Oktyabr (2026)"], "other_total": 1}], st   # 04.10 yakshanba
    finally:
        shutil.rmtree(root)


def test_butun_sheet_jim():
    root = _tmp()
    try:
        for d in _kunlar(1, 7):
            _yoz(root, d, {"Oktyabr": _vals("29,0"), "Main": _vals("1")}, ["Oktyabr"])
        st = _stale(root, "2026-10-07")
        assert st[0]["kun"] == 5 and st[0]["other_changed"] == []
    finally:
        shutil.rmtree(root)


def test_kecha_ozgargan_jim_emas():
    root = _tmp()
    try:
        for d in _kunlar(1, 6):
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        _yoz(root, "2026-10-07", {"Oktyabr": _vals("31,0")}, ["Oktyabr"])
        assert _stale(root, "2026-10-07") == []
    finally:
        shutil.rmtree(root)


def test_chegara_3_ish_kuni():
    root = _tmp()
    try:
        for d in _kunlar(1, 5):
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        assert _stale(root, "2026-10-03") == []                 # 2 ish kuni — hali erta
        assert _stale(root, "2026-10-05")[0]["kun"] == 3        # 02, 03, 05 (04 — yakshanba)
    finally:
        shutil.rmtree(root)


def test_oy_boshida_otgan_oy_kunlari_sanalmaydi():
    # «Oktyabr» 28.09 da oldindan ochilgan, o'zgarmagan — 02.10 da hali ⚠️ emas
    root = _tmp()
    try:
        for d in ["2026-09-28", "2026-09-29", "2026-09-30"] + _kunlar(1, 2):
            _yoz(root, d, {"Oktyabr": _vals("29,0"), "Sentyabr": _vals("1")}, ["Oktyabr"])
        assert _stale(root, "2026-10-02") == []
    finally:
        shutil.rmtree(root)


def test_smm_sheet_tekshirilmaydi():
    root = _tmp()
    try:
        for d in _kunlar(1, 7):
            snap = _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"], pm_kpi=False)
        assert dmod.stale_info(SID, snap, [tab_range("Oktyabr")], "2026-10-07", snapshots=Path(root)) == []
    finally:
        shutil.rmtree(root)


def test_faqat_joriy_oy_tabi():
    # «Loyihalarning ishlash muddati» kam o'zgaradi — u jimlik nazoratiga kirmaydi
    root = _tmp()
    try:
        for d in _kunlar(1, 7):
            _yoz(root, d, {"Loyihalarning ishlash muddati": _vals("1")}, ["Loyihalarning ishlash muddati"])
        assert _stale(root, "2026-10-07", watch=("Loyihalarning ishlash muddati",)) == []
    finally:
        shutil.rmtree(root)


# ------------------------------------------------------- diff.main → analyze (uchidan-uchiga)

def _diff(root, day):
    asl_snap, asl_argv = dmod.SNAPSHOTS, sys.argv
    dmod.SNAPSHOTS, sys.argv = Path(root), ["diff.py", "--date", day]
    try:
        assert dmod.main() == 0
    finally:
        dmod.SNAPSHOTS, sys.argv = asl_snap, asl_argv
    return json.loads((Path(root) / day / "diff.json").read_text(encoding="utf-8"))


def test_uchidan_uchiga_jimlik_va_oy_almashuvi():
    root = _tmp()
    try:
        _yoz(root, "2026-09-30", {"Sentyabr": _vals("1"), "Oktyabr": _vals("29,0"),
                                  "Oktyabr (2026)": _vals("30,0")}, ["Sentyabr"])
        for i, d in enumerate(_kunlar(1, 7)):
            _yoz(root, d, {"Sentyabr": _vals("1"), "Oktyabr": _vals("29,0"),
                           "Oktyabr (2026)": _vals(f"{31 + i},0")}, ["Oktyabr"])

        d1 = _diff(root, "2026-10-01")             # oy almashuvi
        notes = an.deterministic_notes(d1)
        assert notes == ["ℹ️ Zubair PM KPI: «Oktyabr» kuzatuvga yangi oy tabi sifatida olindi (2 qator) — "
                         "o'zgarishlar uning kechagi holatiga nisbatan."], notes

        for d in _kunlar(2, 6):
            _diff(root, d)
        d7 = _diff(root, "2026-10-07")
        assert d7["totals"]["changed"] == 0                         # diff o'zi «o'zgarish yo'q» deydi…
        notes = an.deterministic_notes(d7)
        assert notes == ["⚠️ Zubair PM KPI: «Oktyabr» tabi 01.10 dan beri o'zgarmagan (5 ish kuni), lekin shu "
                         "davrda «Oktyabr (2026)» o'zgargan — kunlik diff noto'g'ri tabni kuzatayotgan bo'lishi "
                         "mumkin; PM qaysi tabni to'ldirishini tekshiring."], notes   # …lekin jimlik ko'rinadi
        assert "DIQQAT: «Oktyabr» tabi 01.10 dan beri o'zgarmagan" in an.build_context(d7)
        assert any("Oktyabr (2026)" in n for n in an.other_tabs_note(d7))   # track_other_tabs ham
    finally:
        shutil.rmtree(root)


def test_config_pm_sheetlari_boshqa_tablarni_kuzatadi():
    import fetch
    pm = [s for s in fetch.load_config() if s.get("pm_kpi", True)]
    assert len(pm) == 4 and all(s.get("track_other_tabs") for s in pm)


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
