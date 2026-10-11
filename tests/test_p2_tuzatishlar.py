"""Audit P2 tuzatishlari testlari (mustahkamlik va kichik xatolar).

  A  undiruv: money() vergul-minglik/manfiy/xato katak; sarlavhada bo'sh katak bo'lsa
     ham sarlavha topiladi, topilmasa egaga izoh; «Status bo'sh» konvensiya bo'lsa
     shovqin emas.
  B  KPI hisobot: oy tabi imlo/yil suffiksi va dublikat; audit oyi snapshot sanasidan;
     1% stavka qoida oralig'idan tashqarida «qoida yo'q» va son; rang yaxlitlanmagan
     %dan; yangi oy tabi kuni «o'zgarish yo'q» emas; diff har sheet'ning oxirgi
     snapshot'i bilan; Claude yiqilsa qayta urinish va diagnostika.

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
import analyze             # noqa: E402
import audit as auditmod   # noqa: E402
import dashboard           # noqa: E402
import diff as diffmod     # noqa: E402
import fetch as fm         # noqa: E402
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

# ---------------------------------------------------------------- B: KPI hisobot

OKT = date(2026, 10, 5)


def test_oy_tabi_imlo_yil_suffiksi_va_dublikat():
    assert fm.month_tab_of("Oktabr") == "oktyabr" and fm.month_tab_of("Oktyabr(2026)") == "oktyabr"
    assert fm.month_tab_of("oktyabr 2026") == "oktyabr" and fm.month_tab_of("Sentabr (2026)") == "sentyabr"
    assert fm.month_tab_of("Undiruv oktabr(2026)") is None and fm.month_tab_of("Main") is None
    # ilgari faqat aniq «Oktyabr» kuzatilardi — bular PM dashboarddan yo'qolardi
    assert fm.detect_watch_tabs(["Main", "Sentyabr", "Oktabr"], OKT) == ["Main", "Oktabr"]
    assert fm.detect_watch_tabs(["Main", "Oktyabr(2026)"], OKT) == ["Main", "Oktyabr(2026)"]
    # boshqa yil arxivi olinmaydi; joriy yil suffiksi yilsizdan ustun
    assert fm.pm_month_tabs(["Oktyabr(2025)", "Oktyabr", "Oktabr(2026)"], OKT) == ["Oktabr(2026)", "Oktyabr"]
    # eski konvensiya saqlanadi: bo'shliq bilan farqlanuvchi dublikatda OXIRGISI
    assert fm.detect_watch_tabs(["Main", "Oktyabr", "Oktyabr "], OKT)[1] == "Oktyabr "
    assert fm.month_tab_dup_note(["Main", "Oktyabr"], OKT) == ""
    n = fm.month_tab_dup_note(["Oktyabr", "Oktyabr "], OKT)
    assert n.startswith("joriy oyga 2 tab bor — «Oktyabr » o'qildi") and "«Oktyabr»" in n
    kc = fm.resolve_key_columns(["Main", "Oktabr"], {"main": "Loyihalar", "month": "Proekt nomi"}, OKT)
    assert kc[fm.tab_range("Oktabr")] == "Proekt nomi"


KPI_HDR = ["№", "Proekt nomi", "Ideal", "Proekt bali", "Kechga qolgan kun"]


def _pm_snap(tab="Oktabr(2026)", rows=(["1", "Alfa", "10", "9", "1"], ["2", "Beta", "10", "8", "0"]),
             tabs=None, sid="pm1"):
    rng, main = fm.tab_range(tab), fm.tab_range("Main")
    return {"id": sid, "name": "Ali PM", "pm_kpi": True, "tabs": tabs or ["Main", tab],
            "watch_ranges": [main, rng], "key_column": {main: "Loyihalar", rng: "Proekt nomi"},
            "fetched_at": "2026-10-05 09:00:00",
            "ranges": {main: {"values": [["Loyihalar"], ["Alfa"], ["Beta"]]},
                       rng: {"values": [KPI_HDR] + [list(r) for r in rows]}}}


def test_kpi_oy_tabi_variantida_ham_hisoblanadi():
    snap = _pm_snap()
    st = dashboard.sheet_stats(snap)
    assert st and st["tab"] == "Oktabr(2026)" and st["aktiv"] == 2 and st["fakt"] == 17.0
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": snap}, {})):
        assert analyze._day_stats("2026-10-05")["Ali PM"]["aktiv"] == 2
    f = []
    auditmod.audit_sheet(snap, f, OKT)
    assert not [x for x in f if x[4] == "oy-tab-yoq"]


def test_audit_joriy_oy_snapshot_sanasidan():
    snap = _pm_snap(tab="Sentabr")
    f = []
    auditmod.audit_sheet(snap, f, date(2026, 9, 20))
    assert not [x for x in f if x[4] == "oy-tab-yoq"]
    # eski (sentyabr) snapshot qayta tekshirilsa devor soati (oktyabr) ishlatilmaydi
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": snap}, {})):
        f, _src = auditmod.run_checks(from_snapshot="2026-09-20")
    assert not [x for x in f if x[4] == "oy-tab-yoq"]
    f = []
    auditmod.audit_sheet(snap, f, OKT)
    assert [x for x in f if x[4] == "oy-tab-yoq"]


def test_audit_oy_tabi_dublikati_ogohlantiradi():
    snap = _pm_snap(tab="Oktyabr ", tabs=["Main", "Oktyabr", "Oktyabr "])
    f = []
    auditmod.audit_sheet(snap, f, OKT)
    dup = [x for x in f if x[4] == "oy-tab-dublikat"]
    assert len(dup) == 1 and dup[0][2] == auditmod.WARN and dup[0][1] == "Oktyabr "
    assert "oy-tab-dublikat" in auditmod.KEY_LABELS


def test_bir_foiz_stavka_qoida_oraligi_va_son():
    assert dashboard.one_pct_rate(6) == 100_000 and dashboard.one_pct_rate(16) == 350_000
    assert dashboard.one_pct_rate(10) == 200_000
    assert dashboard.one_pct_rate(18) is None and dashboard.one_pct_rate(0) is None   # ilgari 350k / 100k

    def _kpi(aktiv):
        st = {"tab": "Oktyabr", "aktiv": aktiv, "ideal": 100.0, "fakt": 95.0, "delay": 0.0}
        with _soxta(diffmod, "load_day", lambda d: ({"pm1": _pm_snap()}, {})), \
                _soxta(auditmod, "run_checks", lambda from_snapshot=None: ([], "x")), \
                _soxta(dashboard, "build_undiruv", lambda d, n: None), \
                _soxta(dashboard, "sheet_stats", lambda s: st):
            kpi = dashboard.build("2026-10-05")["kpi"]
        return next(r for r in kpi if r and r[0] == "Ali PM")

    r = _kpi(18)
    assert r[2] == "qoida yo'q (n=18)" and r[4] == "—" and r[6] == "—" and r[8] == "—"
    r = _kpi(10)
    assert r[2] == 200_000 and isinstance(r[2], int)          # matn emas — #,##0 formati ishlaydi
    assert r[8] == round(25 * 200_000 + 10 * 200_000 + 5_000_000)


def test_rang_yaxlitlanmagan_foizdan():
    snap = _pm_snap(rows=[["1", "Alfa", "2500", "2249", "0"]])      # 89,96%
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": snap}, {})):
        st = analyze._day_stats("2026-10-05")["Ali PM"]
    assert st["pct"] == 90.0 and abs(st["pct_raw"] - 89.96) < 1e-9
    with tempfile.TemporaryDirectory() as td:
        with _soxta(analyze, "SNAPSHOTS", Path(td)), \
                _soxta(analyze, "_day_stats", lambda d: {"Ali PM": dict(st)}), \
                _soxta(auditmod, "run_checks", lambda from_snapshot=None: ([], "")), \
                _soxta(u, "summary", lambda d: None):
            data = analyze.build_report_json("2026-10-05", {"prev_date": None, "totals": {},
                                                            "sheets": {}}, "matn", insights=[])
    pm = data["pms"][0]
    assert pm["pct"] == 90.0 and pm["color"] == "yellow"        # ilgari «green»


def _diff(**range_flags):
    rng = {"stats": {"rows_now": 3, "rows_prev": 3, "added": 0, "removed": 0, "changed": 0},
           "header": KPI_HDR, "added": [], "removed": [], "changed": [], **range_flags}
    return {"baseline": False, "totals": {"added": 0, "removed": 0, "changed": 0},
            "fetch_errors": {}, "missing_today": {},
            "sheets": {"pm1": {"name": "Ali PM", "ranges": {"r": rng}}}}


def test_yangi_oy_tabi_kuni_ozgarish_yoq_emas():
    assert analyze.is_quiet(_diff())
    assert not analyze.is_quiet(_diff(baseline=True, new_range=True))   # 01.10: «Oktyabr» paydo bo'ldi
    assert not analyze.is_quiet(_diff(baseline=True))


def _yoz_snap(root, day, snap):
    d = root / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{snap['id']}.json").write_text(__import__("json").dumps(snap, ensure_ascii=False),
                                          encoding="utf-8")


def test_diff_bir_sheet_kecha_oqilmasa_oxirgi_snapshot_bilan():
    import json
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        a3 = _pm_snap(sid="pm1")
        b3 = _pm_snap(sid="pm2", rows=[["1", "Gamma", "10", "5", "0"]])
        b5 = _pm_snap(sid="pm2", rows=[["1", "Gamma", "10", "7", "0"]])
        _yoz_snap(root, "2026-10-03", a3)
        _yoz_snap(root, "2026-10-03", b3)
        _yoz_snap(root, "2026-10-04", a3)          # pm2 04.10 da o'qilmagan
        _yoz_snap(root, "2026-10-05", a3)
        _yoz_snap(root, "2026-10-05", b5)
        with _soxta(diffmod, "SNAPSHOTS", root), \
                _soxta(sys, "argv", ["diff.py", "--date", "2026-10-05"]):
            assert diffmod.main() == 0
        res = json.loads((root / "2026-10-05" / "diff.json").read_text(encoding="utf-8"))
    e = res["sheets"]["pm2"]
    assert res["prev_date"] == "2026-10-04"
    assert not e.get("baseline") and e["prev_date"] == "2026-10-03"     # ilgari baseline edi
    assert res["totals"]["changed"] == 1                                 # Gamma 5 → 7 yo'qolmadi
    assert "prev_date" not in res["sheets"]["pm1"]
    assert "2026-10-03 bilan solishtirildi" in analyze.fallback_report(res, "x")


def test_diff_dublikat_izohi_hisobotga_tushadi():
    d = _diff()
    d["sheets"]["pm1"]["watch_notes"] = ["joriy oyga 2 tab bor — «Oktyabr » o'qildi"]
    assert analyze.watch_missing_note(d) == ["⚠️ Ali PM: joriy oyga 2 tab bor — «Oktyabr » o'qildi"]


def test_claude_diagnostika():
    from types import SimpleNamespace as NS
    assert analyze.claude_diag(NS(stderr=" limit ", stdout="")) == "limit"
    assert analyze.claude_diag(NS(stderr="", stdout="Credit balance is too low")) == \
        "stdout: Credit balance is too low"                         # ilgari bo'sh sabab
    assert "bo'sh" in analyze.claude_diag(NS(stderr="", stdout=""))


def _analyze_main(claude_fn):
    """analyze.main() — tarmoqsiz: claude, KPI qoidalari, undiruv va JSON soxta."""
    import json
    calls = {"claude": 0, "insights": 0, "json": None}

    def _claude(prompt, **k):
        calls["claude"] += 1
        return claude_fn(calls["claude"])

    def _ins(report):
        calls["insights"] += 1
        return ["i"]

    def _json(day, diff, report, insights=None, **k):
        calls["json"] = insights
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "2026-10-05").mkdir()
        d = _diff()
        d["totals"]["changed"] = 1
        d["date"], d["prev_date"] = "2026-10-05", "2026-10-04"
        (root / "2026-10-05" / "diff.json").write_text(json.dumps(d), encoding="utf-8")
        with _soxta(analyze, "SNAPSHOTS", root), _soxta(analyze, "run_claude", _claude), \
                _soxta(analyze, "make_insights", _ins), _soxta(analyze, "build_report_json", _json), \
                _soxta(analyze, "kpi_block", lambda: ("", "")), _soxta(analyze, "load_env", lambda: None), \
                _soxta(analyze, "undiruv_block", lambda day: ""), _soxta(analyze, "CLAUDE_RETRY_WAIT", 0), \
                _soxta(sys, "argv", ["analyze.py", "--date", "2026-10-05"]):
            assert analyze.main() == 0
        calls["report"] = (root / "2026-10-05" / "report.md").read_text(encoding="utf-8")
    return calls


def test_claude_yiqilsa_qayta_urinadi():
    def _bir_marta_yiqil(n):
        if n == 1:
            raise RuntimeError("claude -p xato (kod 1): overloaded")
        return "AI hisobot"
    c = _analyze_main(_bir_marta_yiqil)
    assert c["claude"] == 2 and c["report"].startswith("AI hisobot") and c["insights"] == 1

    def _doim_yiqil(n):
        raise RuntimeError("claude -p xato (kod 1): stdout: Credit balance is too low")
    c = _analyze_main(_doim_yiqil)
    assert c["claude"] == 2 and "AI tahlil ishlamadi" in c["report"]
    assert "Credit balance is too low" in c["report"]
    assert c["insights"] == 0 and c["json"] == []                  # insights qayta yiqilmaydi

    import subprocess

    def _timeout(n):
        raise subprocess.TimeoutExpired("claude", 600)
    c = _analyze_main(_timeout)
    assert c["claude"] == 1 and "TimeoutExpired" in c["report"]   # timeout qayta kutilmaydi


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
