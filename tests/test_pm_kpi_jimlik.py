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


def _stale(root, today, watch=("Oktyabr",), dam=()):
    snap = json.loads((Path(root) / today / f"{SID}.json").read_text(encoding="utf-8"))
    return dmod.stale_info(SID, snap, [tab_range(t) for t in watch], today, snapshots=Path(root), dam=dam)


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
        assert dmod.stale_info(SID, snap, [tab_range("Oktyabr")], "2026-10-07", snapshots=Path(root), dam=()) == []
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
    asl_snap, asl_argv, asl_dam = dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari
    dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari = Path(root), ["diff.py", "--date", day], lambda: set()
    try:
        assert dmod.main() == 0
    finally:
        dmod.SNAPSHOTS, sys.argv, dmod.dam_kunlari = asl_snap, asl_argv, asl_dam
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


# ------------------------------------------------------- review regressiyalari

def test_fetch_yiqilgan_kun_zanjirni_uzmaydi():
    # 08.10 da shu sheet o'qilmagan (papkada faqat _meta.json) — bu o'zgarish emas
    root = _tmp()
    try:
        for d in _kunlar(1, 9):
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        (Path(root) / "2026-10-08" / f"{SID}.json").unlink()
        st = _stale(root, "2026-10-09")
        assert st[0]["since"] == "2026-10-01" and st[0]["kun"] == 7, st   # 01–08.10, 04 yakshanba
    finally:
        shutil.rmtree(root)


def test_pipeline_ishlamagan_kunlar_kalendar_boyicha_sanaladi():
    # 02–05.10 da umuman papka yo'q (09-18/19 kabi) — kun kalendar bo'yicha
    root = _tmp()
    try:
        for d in ["2026-10-01", "2026-10-06"]:
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        st = _stale(root, "2026-10-06")
        assert st[0]["since"] == "2026-10-01" and st[0]["kun"] == 4, st   # 01,02,03,05
    finally:
        shutil.rmtree(root)


def test_yakshanba_siljishi():
    # O'zgarish yakshanba snapshot'ida ko'rindi → chorshanba hali 2 ish kuni (⚠️ yo'q)
    root = _tmp()
    try:
        _yoz(root, "2026-10-03", {"Oktyabr": _vals("1")}, ["Oktyabr"])
        for d in _kunlar(4, 7):
            _yoz(root, d, {"Oktyabr": _vals("2")}, ["Oktyabr"])
        assert _stale(root, "2026-10-07") == []
        # Payshanba ko'ringan o'zgarish → yakshanba 3 ish kuni (08, 09, 10)
        for d in _kunlar(8, 11):
            _yoz(root, d, {"Oktyabr": _vals("3")}, ["Oktyabr"])
        assert _stale(root, "2026-10-11")[0]["kun"] == 3
    finally:
        shutil.rmtree(root)


def test_bayram_ish_kuni_emas():
    root = _tmp()
    try:
        for d in _kunlar(1, 5):
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        assert _stale(root, "2026-10-05", dam=())[0]["kun"] == 3
        assert _stale(root, "2026-10-05", dam={"2026-10-01"}) == []        # O'qituvchilar kuni
    finally:
        shutil.rmtree(root)


def test_uzoq_jimlikda_sana_siljimaydi():
    # 14 kunlik cheklov olib tashlandi: «since» oy boshida qoladi, kun o'sib boradi
    root = _tmp()
    try:
        for d in _kunlar(1, 21):
            _yoz(root, d, {"Oktyabr": _vals("29,0")}, ["Oktyabr"])
        st = _stale(root, "2026-10-21")
        assert st[0]["since"] == "2026-10-01" and st[0]["kun"] == 17, st  # 20 kun − 3 yakshanba
    finally:
        shutil.rmtree(root)


def test_kuzatilayotgan_muddat_tabi_noto_g_ri_tab_deb_ko_rsatilmaydi():
    root = _tmp()
    try:
        for i, d in enumerate(_kunlar(1, 7)):
            _yoz(root, d, {"Oktyabr": _vals("29,0"), "Loyihalarning ishlash muddati": _vals(str(i))},
                 ["Loyihalarning ishlash muddati", "Oktyabr"])
        st = _stale(root, "2026-10-07", watch=("Loyihalarning ishlash muddati", "Oktyabr"))
        assert st[0]["other_changed"] == []
        note = an.stale_note({"sheets": {"x": {"name": "Zubair PM KPI", "ranges": {}, "stale": st}}})[0]
        assert "kuzatuvdan tashqari tablar ham o'zgarmagan" in note and "noto'g'ri tab" not in note
    finally:
        shutil.rmtree(root)


def test_oy_tabi_bolmagan_yangi_watch_neytral_matn():
    d = {"sheets": {"x": {"name": "Zubair PM KPI", "ranges": {
        tab_range("Loyihalarning ishlash muddati"): {"watch_new": True, "watch_new_month": False,
                                                    "stats": {"rows_now": 18}}}}}}
    note = an.watch_new_note(d)[0]
    assert "oy tabi" not in note and "kuzatuvga olindi" in note


def test_oy_almashuvi_ai_kontekst_va_fallback():
    root = _tmp()
    try:
        _yoz(root, "2026-09-30", {"Sentyabr": _vals("1"), "Oktyabr": _vals("29,0")}, ["Sentyabr"])
        _yoz(root, "2026-10-01", {"Sentyabr": _vals("1"), "Oktyabr": _vals("29,0")}, ["Oktyabr"])
        d1 = _diff(root, "2026-10-01")
        ctx, fb = an.build_context(d1), an.fallback_report(d1, "test")
        assert "kuzatuvga YANGI olingan tab" in ctx and "qatorlar 2 → 2" not in ctx
        assert "kuzatuvga yangi olindi — 2 qator" in fb and "(2 → 2 qator)" not in fb
    finally:
        shutil.rmtree(root)


# ------------------------------------------------------- PDF va caption (asosiy yetkazish yo'li)

W = ("⚠️ Zubair PM KPI: «Oktyabr» tabi 01.10 dan beri o'zgarmagan (5 ish kuni), lekin shu davrda "
     "«Oktyabr (2026)» o'zgargan — kunlik diff noto'g'ri tabni kuzatayotgan bo'lishi mumkin; PM qaysi "
     "tabni to'ldirishini tekshiring.")


def test_caption_jim_kunda_ogohlantirish():
    import send
    cap = send.build_caption({"date": "2026-10-07", "totals": {"quiet": True}, "warnings": [W]})
    assert "⚠️ Kuzatuv: 1 ta ogohlantirish" in cap and "😴" not in cap
    assert "«Oktyabr» tabi 01.10 dan beri o'zgarmagan" in cap and len(cap) <= 1024
    assert "😴 O'zgarish yo'q" in send.build_caption({"date": "2026-10-07", "totals": {"quiet": True}})


def test_pdf_html_ogohlantirish_bloki():
    import render_pdf
    data = {"date": "2026-10-07", "totals": {"quiet": True}, "pms": [], "trend": [],
            "warnings": [W] * 6}
    html = render_pdf.build_html(data, logo_uri="")
    assert "Kuzatuv ogohlantirishlari" in html and "Kuzatuv ogohlantirishi" in html
    assert "o&#39;zgarmagan" in html or "o'zgarmagan" in html
    assert "+3 ta ogohlantirish" in html                           # 3 qatordan ortig'i qisqartiriladi
    assert "😴 O&#39;zgarish yo&#39;q" not in html and "😴 O'zgarish yo'q" not in html
    assert render_pdf.validate_report_data(data) is data           # warnings — list turi qabul qilinadi
    try:
        render_pdf.validate_report_data(dict(data, warnings="matn"))
        raise AssertionError("warnings=str rad etilishi kerak edi")
    except ValueError:
        pass


def test_uchidan_uchiga_report_json_va_caption():
    """fetch→diff→analyze (subprocess, DATA_DIR) → report.json warnings → caption."""
    import os
    import subprocess
    import send
    root = _tmp()
    try:
        for i, d in enumerate(_kunlar(1, 7)):
            _yoz(root, d, {"Oktyabr": _vals("29,0"), "Oktyabr (2026)": _vals(f"{31 + i},0")}, ["Oktyabr"])
        # DATA_DIR/snapshots tuzilmasi
        data_dir = Path(tempfile.mkdtemp(prefix="p0-4-data-"))
        shutil.move(root, str(data_dir / "snapshots"))
        env = dict(os.environ, DATA_DIR=str(data_dir))
        repo = Path(__file__).resolve().parent.parent
        for d in _kunlar(2, 7):
            subprocess.run([sys.executable, "diff.py", "--date", d], cwd=repo, env=env, check=True,
                           capture_output=True, timeout=120)
        subprocess.run([sys.executable, "analyze.py", "--date", "2026-10-07"], cwd=repo, env=env,
                       check=True, capture_output=True, timeout=300)
        rj = json.loads((data_dir / "snapshots" / "2026-10-07" / "report.json").read_text(encoding="utf-8"))
        # config.yaml'dagi dam_kunlari: 01.10 — O'qituvchilar kuni → 4 ish kuni
        assert any("«Oktyabr» tabi 01.10 dan beri o'zgarmagan (4 ish kuni)" in w for w in rj["warnings"]), rj["warnings"]
        assert rj["insights"] == [] and rj["totals"]["quiet"] is True
        assert "⚠️ Kuzatuv: 1 ta ogohlantirish" in send.build_caption(rj)
        md = (data_dir / "snapshots" / "2026-10-07" / "report.md").read_text(encoding="utf-8")
        assert "⚠️ Zubair PM KPI: «Oktyabr» tabi" in md
        shutil.rmtree(data_dir)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- /hisobot

def test_hisobot_jimlikni_korsatadi():
    from datetime import date
    import bot_listener as bl

    class _Kun(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 8)

    root = _tmp()
    try:
        for i, d in enumerate(_kunlar(1, 7)):
            snap = _yoz(root, d, {"Oktyabr": _vals("29,0"), "Oktyabr (2026)": _vals(f"{31 + i},0")}, ["Oktyabr"])
        sent = []
        cfg = [{"id": SID, "name": "Zubair PM KPI", "watch_tabs": "auto", "key_column": {"month": "Proekt nomi"}}]
        patches = [(bl, "typing", lambda *a, **k: None), (bl, "send_retry", lambda m, **k: sent.append(m)),
                   (bl, "remember", lambda *a, **k: None), (bl, "latest_day", lambda: "2026-10-07"),
                   (bl, "sheet_tabs", lambda s: (None, ["Oktyabr", "Oktyabr (2026)"])), (bl, "date", _Kun),
                   (bl.diffmod, "load_day", lambda d: ({SID: snap}, {})), (bl.diffmod, "SNAPSHOTS", Path(root)),
                   (bl.diffmod, "dam_kunlari", lambda: set()),
                   (bl.fetchmod, "load_config", lambda **k: cfg),
                   (bl.fetchmod, "fetch_ranges", lambda sh, rs, lb: {r: {"values": _vals("29,0")} for r in rs})]
        asl = [(o, n, getattr(o, n)) for o, n, _ in patches]
        try:
            for o, n, v in patches:
                setattr(o, n, v)
            bl.do_hisobot()
        finally:
            for o, n, v in asl:
                setattr(o, n, v)
        assert "⚠️ Zubair PM KPI: «Oktyabr» tabi 01.10 dan beri o'zgarmagan (6 ish kuni)" in sent[-1], sent[-1]
        assert "«Oktyabr (2026)» o'zgargan" in sent[-1]
    finally:
        shutil.rmtree(root)


def test_config_pm_sheetlari_boshqa_tablarni_kuzatadi():
    import fetch
    # config.yaml tuzilmasi (ID'lar config.local.yaml / CONFIG_LOCAL_B64 da — P0-1;
    # load_config ID'siz sheet'ni o'tkazib yuboradi, shuning uchun to'liq config o'qiladi)
    pm = [s for s in fetch.load_full_config().get("sheets", [])
          if s.get("pm_kpi", True) and not s.get("qa_only")]
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
