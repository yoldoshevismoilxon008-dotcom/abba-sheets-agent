"""Audit P2 tuzatishlari testlari (mustahkamlik va kichik xatolar).

  A  undiruv: money() vergul-minglik/manfiy/xato katak; sarlavhada bo'sh katak bo'lsa
     ham sarlavha topiladi, topilmasa egaga izoh; «Status bo'sh» konvensiya bo'lsa
     shovqin emas.
  B  KPI hisobot: oy tabi imlo/yil suffiksi va dublikat; audit oyi snapshot sanasidan;
     1% stavka qoida oralig'idan tashqarida «qoida yo'q» va son; rang yaxlitlanmagan
     %dan; yangi oy tabi kuni «o'zgarish yo'q» emas; diff har sheet'ning oxirgi
     snapshot'i bilan; Claude yiqilsa qayta urinish va diagnostika.
  C  runtime: restart 09:00 dan keyin bo'lsa boot catch-up; 09:30 PM push pipeline
     tugashini kutadi; recover_inflight watchdog bilan (osilgan xabar pollingni
     bloklamaydi).
  D  xavfsizlik: PM onboarding so'rovlari chat_id bo'yicha (begona so'rov haqiqiysini
     almashtirmaydi, bir nechta bo'lsa /approve_<slot> <chat_id>, rate-limit); inbox
     fayl nomi kengaytmani saqlaydi va tozalanadi; GitHub token git argv'ida yo'q.
  E  testsiz kritik joylar: dashboard_writer.guard (PM sheet'lariga yozishni to'xtatadigan
     yagona himoya) va pm_push.run_daily muvaffaqiyatli yetkazish shoxi.

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


def test_sarlavha_izohi_kpi_bloki_va_dashboardga_chiqadi():
    izoh = "⚠️ «Undiruv Oktyabr(2026)» tabi sarlavhasida «Undirildi» ustuni topilmadi — qatorlar o'qilmadi"
    view = {"tab": "Undiruv Oktyabr(2026)", "rows": [], "source": "live", "oy": "oktyabr",
            "notes": [izoh], "prev": {"rows": [], "real": []}, "keyingi": None}
    with _soxta(u, "korinish", lambda *a, **k: view):
        s = u.summary("2026-10-05")
        assert s["topilmadi"] and s["tab"] == "Undiruv Oktyabr(2026)" and s["notes"] == [izoh]
        assert izoh in u.report_block("2026-10-05")                    # ilgari: "" (jim)
        rows = dashboard.build_undiruv("2026-10-05", "2026-10-05 09:00")
        assert rows and "sarlavhasi o'qilmadi" in rows[0][0] and any(izoh in r[0] for r in rows)
    bosh = dict(view, notes=["ℹ️ boshqa izoh"])                          # oddiy bo'sh tab — o'zgarmagan
    with _soxta(u, "korinish", lambda *a, **k: bosh):
        assert u.summary("2026-10-05") is None
        assert dashboard.build_undiruv("2026-10-05", "x") is None


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
    # boshqa yil arxivi olinmaydi; aniq yozilish birinchi (kuzatilayotgan tab almashmaydi),
    # variantlar — faqat aniq tab yo'q bo'lsa
    assert fm.pm_month_tabs(["Oktyabr(2025)", "Oktabr(2026)", "Oktabr", "Oktyabr"], OKT) == \
        ["Oktyabr", "Oktabr", "Oktabr(2026)"]
    assert fm.detect_watch_tabs(["Main", "Oktyabr", "Oktyabr (2026)"], OKT)[1] == "Oktyabr"
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


class _Oktyabr(date):
    """Devor soati — 2026-10-05 (test qaysi oyda ishga tushmasin, natija bir xil)."""
    @classmethod
    def today(cls):
        return cls(2026, 10, 5)


def test_audit_joriy_oy_snapshot_sanasidan():
    snap = _pm_snap(tab="Sentabr")
    f = []
    auditmod.audit_sheet(snap, f, date(2026, 9, 20))
    assert not [x for x in f if x[4] == "oy-tab-yoq"]
    # eski (sentyabr) snapshot qayta tekshirilsa devor soati (oktyabr) ishlatilmaydi
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": snap}, {})), _soxta(fm, "date", _Oktyabr):
        f, _src = auditmod.run_checks(from_snapshot="2026-09-20")
        assert not [x for x in f if x[4] == "oy-tab-yoq"]
        f = []
        auditmod.audit_sheet(snap, f)                       # sana berilmasa — devor soati
        assert [x for x in f if x[4] == "oy-tab-yoq"]
    f = []
    auditmod.audit_sheet(snap, f, OKT)
    assert [x for x in f if x[4] == "oy-tab-yoq"]


def test_audit_oy_tabi_dublikati_ogohlantiradi():
    snap = _pm_snap(tab="Oktyabr ", tabs=["Main", "Oktyabr", "Oktyabr "])
    f = []
    auditmod.audit_sheet(snap, f, OKT)
    dup = [x for x in f if x[4] == "oy-tab-dublikat"]
    assert len(dup) == 1 and dup[0][2] == auditmod.WARN and dup[0][1] == "Oktyabr "
    assert dup[0][3].startswith("Joriy oyga 2 tab bor — «Oktyabr » o'qildi")   # tab nomi harfi saqlanadi
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
    st = {"tab": "Oktyabr", "aktiv": 10, "ideal": 100.0, "fakt": 89.96, "delay": 0.0}
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": _pm_snap()}, {})), \
            _soxta(auditmod, "run_checks", lambda from_snapshot=None: ([], "x")), \
            _soxta(dashboard, "build_undiruv", lambda d, n: None), \
            _soxta(dashboard, "sheet_stats", lambda s: st):
        tabs = dashboard.build("2026-10-05")
    assert tabs["umumiy"][1][4] == 89.96 and tabs["trend"][0][5] == 89.96   # rang qoidasi <90 — sariq
    r = _kpi(10)
    assert r[2] == 200_000 and isinstance(r[2], int)          # matn emas — #,##0 formati ishlaydi
    assert r[8] == round(25 * 200_000 + 10 * 200_000 + 5_000_000)


def test_rang_yaxlitlanmagan_foizdan():
    snap = _pm_snap(rows=[["1", "Alfa", "125", "112,45", "0"]])     # 89,96%
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
    # report.json (PDF badge / caption) ham xuddi shu qoida bilan
    for d, kutilgan in ((_diff(), True), (_diff(baseline=True, new_range=True), False)):
        with tempfile.TemporaryDirectory() as td:
            with _soxta(analyze, "SNAPSHOTS", Path(td)), _soxta(analyze, "_day_stats", lambda day: {}), \
                    _soxta(auditmod, "run_checks", lambda from_snapshot=None: ([], "")), \
                    _soxta(u, "summary", lambda day: None):
                data = analyze.build_report_json("2026-10-05", d, "matn", insights=[])
        assert data["totals"]["quiet"] is kutilgan


def test_jim_tab_va_yangi_oy_tabi_yil_suffiksli_nomda_ham():
    """P2 «Oktyabr (2026)» ni kuzatadi (aniq «Oktyabr» yo'q kuni) — PR #5 ning jimlik ⚠️ si
    va «yangi oy tabi» yozuvi ham shu nomni tanisin."""
    import json
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for tab in ("Oktyabr (2026)", "Oktabr(2026)", "Oktyabr"):
            snap = _pm_snap(tab=tab)
            for d in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"):
                (root / d).mkdir(exist_ok=True)
                (root / d / "pm1.json").write_text(json.dumps(snap), encoding="utf-8")
            st = diffmod.stale_info("pm1", snap, snap["watch_ranges"], "2026-10-09",
                                    snapshots=root, dam=set())
            assert [x["tab"] for x in st] == [tab] and st[0]["kun"] >= diffmod.STALE_DAYS, (tab, st)
            r = {}
            diffmod.mark_watch_new(r, fm.tab_range(tab), {"watch_ranges": ["x"]}, "2026-10-01")
            assert r == {"watch_new": True, "watch_new_month": True}, tab


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
    izoh = "ℹ️ Ali PM: 04.10 da o'qilmagan — o'zgarishlar 03.10 holatiga nisbatan."
    assert analyze.sheet_gap_note(res) == [izoh]
    assert izoh in analyze.deterministic_notes(res)          # PDF/caption/fallback — bitta manba


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


# ---------------------------------------------------------------- C: runtime

def _tk(h, m, d=5):
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime(2026, 10, d, h, m, tzinfo=ZoneInfo("Asia/Tashkent"))


def test_catchup_oynasi():
    import supervisor as sv
    assert sv.catchup_kerak(_tk(10, 15), sv.DAILY_AT, "")
    assert sv.catchup_kerak(_tk(10, 15), sv.DAILY_AT, "2026-10-04")          # kechagi marker
    assert not sv.catchup_kerak(_tk(10, 15), sv.DAILY_AT, "2026-10-05")      # bugun bajarilgan
    assert not sv.catchup_kerak(_tk(8, 50), sv.DAILY_AT, "")                 # vaqti kelmagan
    assert not sv.catchup_kerak(_tk(12, 0), sv.DAILY_AT, "")                 # 3 soatlik oynadan tashqari
    assert sv.catchup_kerak(_tk(12, 20), sv.PM_PUSH_AT) and not sv.catchup_kerak(_tk(9, 20), sv.PM_PUSH_AT)


def test_boot_catchup_pipeline_keyin_pm_push():
    import supervisor as sv
    tartib = []
    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "daily_last_run.txt"
        with _soxta(sv, "DAILY_MARKER", marker), _soxta(sv, "_hozir", lambda: _tk(9, 40)), \
                _soxta(sv, "daily_job", lambda: tartib.append("daily")), \
                _soxta(sv, "pm_push_job", lambda: tartib.append("pm")):
            sv.boot_catchup()()
            assert tartib == ["daily", "pm"]
            marker.write_text("2026-10-05", encoding="utf-8")       # pipeline bugun bo'lgan
            tartib.clear()
            sv.boot_catchup()()
            assert tartib == ["pm"]
        # marker yo'q (birinchi deploy kuni / restart send'dan keyin), lekin run.sh log'ida
        # hisobot ketgani bor — pipeline QAYTA ishga tushmaydi (hisobot ikki marta ketmasin)
        marker.unlink()
        logs = Path(td) / "logs"
        logs.mkdir()
        tartib.clear()
        with _soxta(sv, "DATA", Path(td)), _soxta(sv, "DAILY_MARKER", marker), \
                _soxta(sv, "_hozir", lambda: _tk(9, 40)), \
                _soxta(sv, "daily_job", lambda: tartib.append("daily")), \
                _soxta(sv, "pm_push_job", lambda: tartib.append("pm")):
            (logs / "2026-10-05.log").write_text("[fetch] ...\n[send] yuborildi: 1/1\n", encoding="utf-8")
            sv.boot_catchup()()
            assert tartib == ["daily", "pm"]                     # faqat alert/matn — hisobot emas
            tartib.clear()
            (logs / "2026-10-05.log").write_text("[send] PDF hisobot yuborildi\n", encoding="utf-8")
            sv.boot_catchup()()
            assert tartib == ["pm"]
            tartib.clear()
            (logs / "2026-10-05.log").write_text("===== tugadi: 2026-10-05 09:12:00 =====\n",
                                                 encoding="utf-8")
            sv.boot_catchup()()
            assert tartib == ["pm"]
        with _soxta(sv, "DAILY_MARKER", marker), _soxta(sv, "_hozir", lambda: _tk(8, 30)):
            assert sv.boot_catchup() is None                          # hali 09:00 emas
        with _soxta(sv, "DAILY_MARKER", marker), _soxta(sv, "_hozir", lambda: _tk(15, 0)):
            assert sv.boot_catchup() is None                          # oyna o'tgan


def test_daily_job_marker_yozadi():
    import supervisor as sv
    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "sub" / "daily_last_run.txt"
        with _soxta(sv, "DAILY_MARKER", marker), _soxta(sv, "_hozir", lambda: _tk(9, 5)), \
                _soxta(sv, "run_daily", lambda: None):
            sv.daily_job()
        assert marker.read_text(encoding="utf-8") == "2026-10-05"


def test_pm_push_pipeline_tugashini_kutadi():
    import threading
    import supervisor as sv
    ketdi = threading.Event()
    with _soxta(sv, "run_pm_push", ketdi.set):
        sv._PIPELINE_LOCK.acquire()                  # pipeline ishlayapti
        try:
            th = threading.Thread(target=sv.pm_push_job, daemon=True)
            th.start()
            assert not ketdi.wait(0.3)               # push kutyapti
        finally:
            sv._PIPELINE_LOCK.release()
        assert ketdi.wait(3)                         # pipeline tugadi — push ketdi
        th.join(3)
    ketdi.clear()
    with _soxta(sv, "run_pm_push", ketdi.set), _soxta(sv, "PM_WAIT_SEC", 0.05):
        sv._PIPELINE_LOCK.acquire()
        try:
            sv.pm_push_job()                         # chek tugadi — baribir yuboriladi
        finally:
            sv._PIPELINE_LOCK.release()
    assert ketdi.is_set()


def test_recover_inflight_watchdog_bilan():
    import json
    import threading
    import time
    import bot_listener as bl
    qoyib_yubor = threading.Event()
    xabarlar = []

    def _osilgan(upd):
        qoyib_yubor.wait(5)

    upd = {"update_id": 7, "message": {"chat": {"id": 1}, "text": "savol"}}
    with tempfile.TemporaryDirectory() as td:
        inflight = Path(td) / "bot-inflight.json"
        inflight.write_text(json.dumps({"update": upd, "attempts": 1}), encoding="utf-8")
        with _soxta(bl, "INFLIGHT", inflight), _soxta(bl, "handle_update", _osilgan), \
                _soxta(bl, "HANDLE_TIMEOUT", 0.2), \
                _soxta(bl, "send_retry", lambda t, **k: xabarlar.append(t)):
            t0 = time.monotonic()
            bl.recover_inflight()
            dt = time.monotonic() - t0
        qoyib_yubor.set()
        assert dt < 2                                # ilgari handle_update tugashini kutardi
        assert not inflight.exists()
    assert any("timeout" in x for x in xabarlar)


# ---------------------------------------------------------------- D: xavfsizlik

@contextlib.contextmanager
def _pm_muhit():
    import pm_push
    yub, ega = [], []
    with tempfile.TemporaryDirectory() as td, \
            _soxta(pm_push, "CHATS_FILE", Path(td) / "pm_chats.json"), \
            _soxta(pm_push, "slots_from_config", lambda: {"ali": "Ali", "vali": "Vali"}), \
            _soxta(pm_push, "send_to", lambda c, t: yub.append((c, t))), \
            _soxta(pm_push, "send_owner", ega.append):
        yield pm_push, yub, ega


def _start(pm, chat_id, user, slot="ali"):
    return pm.handle_incoming(chat_id, {"text": f"/start pm_{slot}", "from": {"username": user}})


def test_pm_onboarding_begona_sorov_haqiqiysini_almashtirmaydi():
    with _pm_muhit() as (pm, yub, ega):
        assert _start(pm, 111, "ali_pm") == "pm-start"
        assert _start(pm, 666, "hujumchi") == "pm-start"
        assert "/approve_ali 666" in ega[-1] and "2 ta so'rov" in ega[-1]
        # ilgari: ikkinchi so'rov birinchisini almashtirar, /approve_ali uni ulardi
        r = pm.approve("ali")
        assert "2 ta so'rov" in r and "chat_id 111" in r and "chat_id 666" in r
        assert pm.load_chats()["slots"] == {}                       # hech kim ulanmadi
        assert pm.approve("ali", "111").startswith("✅ Ali ← @ali_pm (chat_id 111)")
        ch = pm.load_chats()
        assert ch["slots"]["ali"]["chat_id"] == 111 and "ali" not in ch["pending"]
        assert (666, "So'rov rad etildi.") in yub


def test_pm_onboarding_rate_limit_va_cheklov():
    with _pm_muhit() as (pm, yub, ega):
        _start(pm, 111, "a")
        assert _start(pm, 111, "a") == "pm-start-rate" and len(ega) == 1   # egaga spam yo'q
        for i in range(10):
            _start(pm, 1000 + i, f"u{i}")
        lst = pm.load_chats()["pending"]["ali"]
        assert len(lst) == pm.PENDING_MAX and lst[-1]["chat_id"] == 1009


def test_pm_onboarding_yagona_sorov_va_reject():
    with _pm_muhit() as (pm, yub, ega):
        _start(pm, 111, "ali_pm")
        assert pm.approve("ali", "999").startswith("chat_id 999")    # boshqa chat_id — ulanmaydi
        assert pm.reject("ali").startswith("❌ Ali so'rovi rad etildi (@ali_pm)")
        assert pm.approve("ali") == "Ali uchun kutilayotgan so'rov yo'q."
        _start(pm, 222, "v1", slot="vali")
        _start(pm, 333, "v2", slot="vali")
        assert "2 ta so'rov" in pm.reject("vali")
        assert pm.reject("vali", "333").startswith("❌")
        assert pm.approve("vali").startswith("✅ Vali ← @v1")       # bittasi qoldi — chat_id shart emas


def test_pm_eski_pending_formati_oqiladi():
    import json
    with _pm_muhit() as (pm, yub, ega):
        pm.CHATS_FILE.write_text(json.dumps(
            {"slots": {}, "pending": {"ali": {"chat_id": 5, "username": "@x"}}}), encoding="utf-8")
        assert pm.approve("ali").startswith("✅ Ali ← @x (chat_id 5)")


def test_bot_approve_buyrugi_chat_id_uzatadi():
    import bot_listener as bl
    import pm_push
    chaqiruv = []
    upd = {"update_id": 1, "message": {"chat": {"id": 4242}, "from": {"id": 4242},
                                       "text": "/approve_ali 666"}}
    with _soxta(bl, "CHAT_ID", "4242"), _soxta(bl, "send_retry", lambda *a, **k: True), \
            _soxta(pm_push, "approve", lambda s, c=None: chaqiruv.append(("a", s, c)) or "ok"), \
            _soxta(pm_push, "reject", lambda s, c=None: chaqiruv.append(("r", s, c)) or "ok"):
        assert bl.handle_update(upd) == "pm-approve"
        upd["message"]["text"] = "/reject_vali@abba_bot"
        assert bl.handle_update(upd) == "pm-reject"
    assert chaqiruv == [("a", "ali", "666"), ("r", "vali", None)]


def test_inbox_fayl_nomi_kengaytma_va_tozalash():
    import time
    import design
    uzun = "Hisobot " + "x" * 120 + ".pdf"
    n = design.safe_name(uzun)
    assert len(n) == 60 and n.endswith(".pdf")                   # ilgari kengaytma kesilardi
    assert design.safe_name("../../etc/passwd").count("/") == 0
    assert design.safe_name("") == "fayl" and design.safe_name(".env") == "env"
    assert design.safe_name("hisobot (yakuniy).docx") == "hisobot__yakuniy_.docx"
    with tempfile.TemporaryDirectory() as td:
        inbox = Path(td) / "inbox"
        inbox.mkdir()
        eski, yangi = inbox / "eski.pdf", inbox / "yangi.pdf"
        eski.write_text("x")
        yangi.write_text("y")
        t = time.time() - 8 * 86400
        os.utime(eski, (t, t))
        with _soxta(design, "INBOX", inbox):
            assert design.prune_inbox() == 1
        assert not eski.exists() and yangi.exists()


def test_git_token_argv_da_yoq():
    import subprocess
    import git_auth
    e = git_auth.env("TOK123", base={"PATH": os.environ.get("PATH", "")})
    r = subprocess.run(["git", "config", "--get", git_auth.HEADER_KEY], env=e,
                       capture_output=True, text=True)
    assert r.stdout.strip() == "AUTHORIZATION: basic eC1hY2Nlc3MtdG9rZW46VE9LMTIz"   # git o'qiydi
    assert git_auth.env("", base={"A": "1"}) == {"A": "1"}
    # mavjud GIT_CONFIG_* (masalan proxy sozlamasi) saqlanadi, token keyingi indeksga
    e = git_auth.env("T", base={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b",
                                "GIT_CONFIG_VALUE_0": "c"})
    assert e["GIT_CONFIG_COUNT"] == "2" and e["GIT_CONFIG_KEY_0"] == "a.b"
    assert e["GIT_CONFIG_KEY_1"] == git_auth.HEADER_KEY
    oldin = os.environ.get("GIT_CONFIG_COUNT")
    git_auth.env("T")
    assert os.environ.get("GIT_CONFIG_COUNT") == oldin           # os.environ o'zgarmaydi


def _argv_yozgich(log):
    from types import SimpleNamespace as NS

    def _sh(*cmd, **k):
        log.append((cmd, k.get("env")))
        if len(cmd) > 1 and cmd[1] == "clone":
            (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
        # «diff --cached --quiet» 1 → commit qilinadigan o'zgarish bor
        return NS(returncode=1 if "diff" in cmd else 0, stdout="", stderr="")
    return _sh


def test_push_reports_va_push_chat_tokenni_argv_ga_qoymaydi():
    import push_chat
    import push_reports
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "snap" / "2026-10-05").mkdir(parents=True)
        (root / "snap" / "2026-10-05" / "report.md").write_text("hisobot", encoding="utf-8")
        (root / "chat").mkdir()
        (root / "chat" / "2026-10-05.md").write_text("suhbat", encoding="utf-8")
        log = []
        with _soxta(os, "environ", {**os.environ, "REPORTS_REPO": "o/r", "GH_TOKEN_REPORTS": "SIRTOKEN"}), \
                _soxta(push_reports, "sh", _argv_yozgich(log)), \
                _soxta(push_reports, "CLONE", root / "rep"), _soxta(push_reports, "SNAPSHOTS", root / "snap"), \
                _soxta(push_chat, "sh", _argv_yozgich(log)), _soxta(push_chat, "CLONE", root / "ch"), \
                _soxta(push_chat, "CHAT_SRC", root / "chat"), _soxta(push_chat, "STATE", root / "st.json"):
            assert push_reports.main() == 0
            assert push_chat.main() == 0
    tarmoq = [(c, e) for c, e in log if any(x in c for x in ("clone", "pull", "push"))]
    assert len(tarmoq) >= 4
    assert not any("SIRTOKEN" in " ".join(map(str, c)) for c, _ in log)      # ps ko'rmaydi
    assert all(e and e.get("GIT_CONFIG_KEY_" + str(int(e["GIT_CONFIG_COUNT"]) - 1))
               == "http.https://github.com/.extraheader" for _, e in tarmoq)


# ---------------------------------------------------------------- E: testsiz kritik joylar

@contextlib.contextmanager
def _dw_muhit(did="DASH-ID"):
    import dashboard_writer as dw
    alert = []

    def _tarmoq():
        raise AssertionError("guard'dan oldin tarmoqqa chiqildi")
    with _soxta(dw.fetchmod, "load_full_config", lambda: {"dashboard_id": did}), \
            _soxta(dw, "_alert", alert.append), _soxta(dw, "rw_client", _tarmoq):
        yield dw, alert


def test_dashboard_writer_guard_faqat_dashboard_ga_ruxsat():
    with _dw_muhit() as (dw, alert):
        dw.guard("DASH-ID")
        dw.guard("  DASH-ID ")                                   # bo'shliq — o'sha id
        assert alert == []
        for begona in ("PM-SHEET-ID", "", "DASH-ID-2", "dash-id"):
            try:
                dw.guard(begona)
            except dw.WriteDeniedError:
                pass
            else:
                raise AssertionError(f"guard o'tkazib yubordi: {begona!r}")
        assert len(alert) == 4 and all("XAVFSIZLIK" in a for a in alert)
        # write_values ham guard'dan o'tadi — tarmoqqa (rw_client) yetib bormaydi
        try:
            dw.write_values("PM-SHEET-ID", "Umumiy", [["x"]])
        except dw.WriteDeniedError:
            pass
        else:
            raise AssertionError("write_values begona id'ga yozdi")
    with _dw_muhit(did="") as (dw, alert):
        for sid in ("", "PM-SHEET-ID"):                          # dashboard_id yo'q — hammasi yopiq
            try:
                dw.guard(sid)
            except dw.WriteDeniedError as e:
                assert "to'ldirilmagan" in str(e)
            else:
                raise AssertionError("dashboard_id bo'sh, lekin yozishga ruxsat berildi")


def test_dashboard_writer_ruxsat_etilgan_yozuv():
    import dashboard_writer as dw
    yozildi = []

    class _Ws:
        def clear(self):
            yozildi.append("clear")

        def update(self, values, range_name, value_input_option):
            yozildi.append((range_name, values))

    class _Sh:
        def __init__(self, key):
            self.key = key

    with _dw_muhit() as (dw, alert), \
            _soxta(dw, "rw_client", lambda: type("C", (), {"open_by_key": lambda self, k: _Sh(k)})()), \
            _soxta(dw, "_worksheet", lambda sh, t, rows=0, cols=0: (yozildi.append(sh.key), _Ws())[1]):
        dw.overwrite_tab("Umumiy", [["a", 1]])
    assert yozildi == ["DASH-ID", "clear", ("A1", [["a", 1]])]


@contextlib.contextmanager
def _pm_run_muhit(contacts, natija):
    """pm_push.run_daily — tarmoqsiz: ko'rinish, push matni, userbot va state soxta."""
    import pm_push
    import userbot_sender
    holat, ega, yuborilgan = {}, [], []
    view = {"tab": "Undiruv oktabr(2026)", "rows": [_row("Alfa"), _row("Beta")], "source": "live",
            "oy": "oktyabr",
            "prev": {"tab": None, "rows": [], "source": "none", "oy": "sentyabr", "real": [],
                     "closed": [], "moved": [], "farqli": [], "noaniq": [], "izoh": []},
            "keyingi": None, "notes": [], "data_source": "live"}
    stats = {"overdue_n": 1, "overdue_sum": 100, "aktiv_n": 0, "aktiv_sum": 0, "bad_sum": 0,
             "no_date": 0, "pauza": [], "status_blank": [], "unpaid_n": 2, "pm_missing": [],
             "pm_col_missing": False, "closed_carry": [], "moved_carry": [], "nodate_pm": {}}

    def _send(msgs):
        yuborilgan.extend(msgs)
        return [(slot, *natija.get(slot, (True, ""))) for slot, _c, _t in msgs]
    with _soxta(pm_push, "_load_state", lambda: dict(holat.get("s") or {})), \
            _soxta(pm_push, "_save_state", lambda d: holat.__setitem__("s", d)), \
            _soxta(u, "korinish", lambda today=None, day=None, prefer_live=True, qlar=None: view), \
            _soxta(pm_push, "build_push", lambda today, cur, prev, pm, view=None: (
                {"Ali": ["• Alfa — $100"], "Vali": ["• Beta — $200"]}, dict(stats))), \
            _soxta(pm_push, "load_contacts", lambda: contacts), \
            _soxta(pm_push, "slots_from_config", lambda: {"ali": "Ali", "vali": "Vali"}), \
            _soxta(pm_push, "send_owner", ega.append), \
            _soxta(pm_push, "owner_pdf", lambda *a, **k: True), \
            _soxta(userbot_sender, "send_messages", _send):
        yield pm_push, holat, ega, yuborilgan


def test_pm_push_run_daily_muvaffaqiyatli_yetkazish():
    with _pm_run_muhit({"ali": "@ali", "vali": "@vali"}, {}) as (pm, holat, ega, yub):
        st, summary = pm.run_daily(today=OKT)
        assert st == "sent"
        assert [(s, c) for s, c, _t in yub] == [("ali", "@ali"), ("vali", "@vali")]
        assert "• Alfa — $100" in yub[0][2] and "05.10.2026" in yub[0][2]
        assert "• Ali (@ali): 1 eslatma yuborildi ✅" in summary
        assert "• Vali (@vali): 1 eslatma yuborildi ✅" in summary
        assert holat["s"]["date"] == "2026-10-05" and holat["s"]["sent"] == {"ali": 1, "vali": 1}
        assert holat["s"]["failed"] == {} and holat["s"]["tab"] == "Undiruv oktabr(2026)"
        # o'sha kuni qayta (09:30 cron + catch-up) — ikkinchi marta yuborilmaydi
        assert pm.run_daily(today=OKT) == ("skip", "") and len(yub) == 2


def test_pm_push_run_daily_qisman_xato():
    with _pm_run_muhit({"ali": "@ali", "vali": "@vali"}, {"vali": (False, "PEER_FLOOD")}) \
            as (pm, holat, ega, yub):
        st, summary = pm.run_daily(today=OKT)
    assert st == "sent"
    assert "• Ali (@ali): 1 eslatma yuborildi ✅" in summary
    assert "• Vali (@vali): YUBORILMADI ❌ — PEER_FLOOD" in summary
    assert holat["s"]["sent"] == {"ali": 1} and holat["s"]["failed"] == {"vali": "PEER_FLOOD"}


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
