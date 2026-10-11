"""KPI va undiruv hisob-kitobi — audit P1 (K1–K8) tuzatishlari testlari.

  K1  qisman to'lov o'tgan oy qoldig'ini jimgina yopmaydi;
  K2  fuzzy juft + «ketdi»: Lose summa == o'tgan qoldiq bo'lsa yopiladi;
  K3  ideal bo'sh qatorning fakti foizni shishirmaydi (+ audit WARN);
  K4  Jami/nomsiz yig'indi qatori loyiha deb sanalmaydi;
  K5  o'ng tomondagi shablon katagi jadvalni kesmaydi;
  K6  diff: Jami bloki, nomsiz/son kalit va takror nomlar barqaror kalit oladi;
  K7  diff: ustun qo'shilsa qatorlar siljimaydi, sarlavha kalit ustuni bo'yicha topiladi;
  K8  oy boshida kunlik diff 2025 arxiv tabini «joriy oy» deb olmaydi.

pytest tests/test_kpi_hisob.py  yoki  python3 tests/test_kpi_hisob.py
Tarmoq/kredensial kerak emas.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze as an       # noqa: E402
import audit as au         # noqa: E402
import dashboard as db     # noqa: E402
import diff as df          # noqa: E402
import fetch as fm         # noqa: E402
import undiruv as u        # noqa: E402

# ------------------------------------------------------------------ yordamchilar

U_HDR = ["№", "Nomi", "Ma'sul shaxs", "LTV", "Summa", "Undirildi", "Aktive  Summary",
         "Lose summa", "Final data", "To'lov xolati", "Tasdiq"]


def _tab(*rows, ref=None, today=date(2026, 10, 9)):
    vals = [[""] * 11, U_HDR] + [list(r) for r in rows] + [["Jami"] + [""] * 10]
    return u.parse_rows(vals, today, ref)


PM_HDR = ["№", "Proekt nomi", "Kpi ideal bali", "Proekt bali", "Farq", "Kechga qolgan kunlar"]


def _pm(*rows, header=PM_HDR):
    return [list(header)] + [list(r) for r in rows]


def _snap(vals, tab="Oktyabr"):
    rng = fm.tab_range(tab)
    return {"name": "Test PM KPI", "watch_ranges": [rng], "ranges": {rng: {"values": vals}}}


def _names(rows):
    return [r["loyiha"] for r in rows]


# ------------------------------------------------------------------ K1

def test_k1_qisman_tolov_otgan_qoldiqni_jim_yopmaydi():
    """Sentyabr $1 500 qoldi; oktyabr qatori $2 000 yangi hisob, $500 to'landi — sentyabr
    qarzi «yopilgan» emas: so'raladi va egaga «qaror kerak» (to'lovdan oldingidek)."""
    prev = _tab(["1", "Levelmax", "Islom", "", "$1 500", "", "", "", "20.09", "", ""])
    oldin = u.month_transition(prev, _tab(["1", "Levelmax", "Islom", "", "$2 500", "", "", "", "20.10", "", ""]))
    keyin = u.month_transition(prev, _tab(["1", "Levelmax", "Islom", "", "$2 000", "$500", "", "", "20.10", "", ""]))
    for t in (oldin, keyin):
        assert not t["closed"], t["closed"]
        assert _names(t["real"]) == ["Levelmax"] and _names(t["farqli"]) == ["Levelmax"], t


def test_k1_qisman_tolov_kochirilgan_qarzni_yopadi():
    """Joriy qator AYNAN o'tgan qoldiq (kelishilgan $1 500 = qoldiq) va qisman to'landi —
    qarz joriy qatorda yashaydi, o'tgan qator yopiladi (ikki marta so'ralmaydi)."""
    prev = _tab(["1", "Levelmax", "Islom", "", "$1 500", "", "", "", "20.09", "", ""])
    t = u.month_transition(prev, _tab(["1", "Levelmax", "Islom", "", "$1 000", "$500", "", "", "20.10", "", ""]))
    assert _names(t["closed"]) == ["Levelmax"] and not t["real"], t


def test_k1_toliq_tolangan_status_bosh_yopadi():
    """Joriy qatorda qarz qolmagan (Summa $0, Undirildi bor), status yozilmagan —
    to'langan deb olinadi (qisman to'lov emas)."""
    prev = _tab(["1", "Levelmax", "Islom", "", "$1 500", "", "", "", "20.09", "", ""])
    t = u.month_transition(prev, _tab(["1", "Levelmax", "Islom", "", "$0", "$2 000", "", "", "20.10", "", ""]))
    assert _names(t["closed"]) == ["Levelmax"] and not t["real"], t


def test_k1_summa_teng_qisman_tolov_kochirilgan():
    """Qisman to'lovdan keyin ham qolgan summa o'tgan qoldiqqa teng bo'lsa — oddiy qoida
    («ko'chirilgan»), qarz ikki marta so'ralmaydi."""
    prev = _tab(["1", "Levelmax", "Islom", "", "$1 500", "", "", "", "20.09", "", ""])
    t = u.month_transition(prev, _tab(["1", "Levelmax", "Islom", "", "$1 500", "$500", "", "", "20.10", "", ""]))
    assert _names(t["moved"]) == ["Levelmax"] and not t["real"] and not t["closed"], t


# ------------------------------------------------------------------ K2

def test_k2_bosimov_lose_teng_yopiladi():
    """09.10 real holati: sentyabr «Bosimov shcool» $1 500; oktyabr «Bosimov School»
    Summa bo'sh, Lose $1 500, status sabab bilan — sentyabr qarzi PM'dan so'ralmaydi."""
    prev = _tab(["14", "Bosimov shcool", "Zubair", "", "$1 500", "", "", "", "18.09", "", ""])
    cur = _tab(["10", "Bosimov School", "Zubair", "", "", "", "", "$1 500", "18.10", "Puli yo'q", ""])
    assert cur[0]["holat"] == "ketdi"
    t = u.month_transition(prev, cur)
    assert _names(t["closed"]) == ["Bosimov shcool"] and not t["real"] and not t["noaniq"], t


def test_k2_lose_farqli_noaniq_qoladi():
    prev = _tab(["14", "Bosimov shcool", "Zubair", "", "$1 500", "", "", "", "18.09", "", ""])
    cur = _tab(["10", "Bosimov School", "Zubair", "", "", "", "", "$2 500", "18.10", "Puli yo'q", ""])
    t = u.month_transition(prev, cur)
    assert not t["closed"] and _names(t["real"]) == ["Bosimov shcool"] and t["noaniq"], t


# ------------------------------------------------------------------ K3

def test_k3_ideal_bosh_fakt_foizga_kirmaydi():
    vals = _pm(["1", "Kanzec", "", "23,2", "", ""], ["2", "Brend", "41,2", "20", "21,2", "2"])
    st = au.pm_stats(vals)
    assert st["aktiv"] == 1 and st["ideal"] == 41.2 and st["fakt"] == 20.0 and st["delay"] == 2.0, st
    assert st["ideal_bosh"] == ["Kanzec"], st
    s = db.sheet_stats(_snap(vals))
    assert s["fakt"] / s["ideal"] * 100 < 100, s            # avval 104,9% chiqardi


def test_k3_ref_xatoli_ideal_ham_chetlanadi():
    st = au.pm_stats(_pm(["1", "A", "#REF!", "30", "", ""], ["2", "B", "41,2", "35", "", ""]))
    assert st["aktiv"] == 1 and st["fakt"] == 35.0, st


def test_k3_audit_ideal_bosh_ogohlantiradi():
    f = []
    au.audit_month_tab("Test PM KPI", "Oktyabr", _pm(["1", "Kanzec", "", "23,2", "", ""],
                                                      ["2", "Brend", "41,2", "20", "", ""]), f)
    keys = [(x[2], x[4]) for x in f]
    assert (au.WARN, "ideal-bosh") in keys and "Kanzec" in f[0][3], f
    assert "ideal-bosh" in au.KEY_LABELS
    f = []
    au.audit_month_tab("Test PM KPI", "Oktyabr", _pm(["1", "A", "41,2", "30", "", ""]), f)
    assert not f, f


def test_k3_dashboard_va_pdf_bir_xil_hisob():
    """dashboard.sheet_stats va analyze._day_stats (PDF) bitta pm_stats'dan — farq qilmaydi."""
    vals = _pm(["1", "A", "41,2", "30", "", "1"], ["2", "Kanzec", "", "23,2", "", ""],
               ["3", "B", "41,2", "40", "", "0"], ["", "", "82,4", "93,2", "", "1"])
    snap = _snap(vals)
    orig = df.load_day
    df.load_day = lambda day: ({"sid": snap}, {})
    try:
        d = an._day_stats("2026-10-09")["Test PM KPI"]
    finally:
        df.load_day = orig
    s = db.sheet_stats(snap)
    assert (d["aktiv"], d["ideal"], d["fakt"]) == (s["aktiv"], round(s["ideal"], 1), round(s["fakt"], 1)) == (2, 82.4, 70.0), (d, s)
    assert d["pct"] == round(70 / 82.4 * 100, 1) and d["delay_days"] == 1.0, d


# ------------------------------------------------------------------ K4

def test_k4_nomsiz_jami_qatori_loyiha_emas():
    """Jami qatori loyihalardan keyin bo'sh qatorsiz — aktiv +1, ideal 2 baravar bo'lmaydi."""
    st = au.pm_stats(_pm(["1", "A", "41,2", "30", "", ""], ["2", "B", "41,2", "20", "", "2"],
                         ["", "", "82,4", "50", "", "2"]))
    assert (st["aktiv"], st["ideal"], st["fakt"], st["delay"]) == (2, 82.4, 50.0, 2.0), st
    assert db.one_pct_rate(st["aktiv"]) == 100_000


def test_k4_jami_yorliqli_qator_loyiha_emas():
    st = au.pm_stats(_pm(["1", "A", "41,2", "30", "", ""], ["", "Jami", "41,2", "30", "", ""]))
    assert (st["aktiv"], st["ideal"]) == (1, 41.2), st


def test_k4_nom_ustunisiz_jadvalda_katta_yigindi_chetlanadi():
    hdr = ["№", "Kpi ideal bali", "Proekt bali"]
    st = au.pm_stats(_pm(["1", "41,2", "30"], ["2", "41,2", "20"], ["", "164,8", "100"], header=hdr))
    assert (st["aktiv"], st["ideal"]) == (2, 82.4), st


def test_k4_audit_jami_qatorni_mainda_yoq_demaydi():
    names = au.audit_month_tab("T", "Oktyabr", _pm(["1", "A", "41,2", "30", "", ""],
                                                   ["", "Jami", "41,2", "30", "", ""]), [])
    assert names == {"a"}, names


# ------------------------------------------------------------------ K5

SHABLON_HDR = PM_HDR + ["", "", "May oyligi→ Abdullox", "Limit"]


def test_k5_ong_tomondagi_shablon_jadvalni_kesmaydi():
    assert au.table_width(SHABLON_HDR) == len(PM_HDR)
    vals = _pm(["1", "A", "41,2", "30", "", "", "", "", "Fix", "5 000 000"],
               ["2", "B", "41,2", "35", "", "", "", "", "May oyligi→ Abdullox", "limit"],
               ["3", "C", "41,2", "40", "", "", "", "", "", ""], header=SHABLON_HDR)
    st = au.pm_stats(vals)
    assert (st["aktiv"], round(st["ideal"], 1)) == (3, 123.6), st    # avval aktiv 1, ideal 41,2


def test_k5_jadval_ichidagi_marker_hali_ham_tugatadi():
    vals = _pm(["1", "A", "41,2", "30", "", ""], ["", "Kpi turi", "Joriy KPI", "Limit", "", ""],
               ["", "Ball", "70", "", "", ""])
    assert [r[1] for _, r in au.data_rows(vals)[1]] == ["A"]


def test_k5_jadval_tugab_ongda_blok_davom_etsa_tugatadi():
    vals = _pm(["1", "A", "41,2", "30", "", "", "", "", "", ""],
               ["", "", "", "", "", "", "", "", "Iyun oyligi→ X", "1"],
               ["9", "Shablon qatori", "41,2", "41,2", "", "", "", "", "", ""], header=SHABLON_HDR)
    assert [r[1] for _, r in au.data_rows(vals)[1]] == ["A"]


# ------------------------------------------------------------------ K6

def _undiruv_vals(rows, jami_nomi, jami_summa, keyin=()):
    return ([[""] * 6, ["№", "Nomi", "Ma'sul shaxs", "Summa", "Undirildi", "To'lov xolati"]]
            + [list(r) for r in rows]
            + [["Jami", jami_nomi, "", jami_summa, "", ""]] + [list(r) for r in keyin])


def test_k6_jami_bloki_soxta_yangi_ochgan_bermaydi():
    """09.10: Jami qatorining «Nomi» katagida summa ($121 610) — kalit bo'lib, har kuni
    «N yangi, N o'chgan» chiqardi. Endi pozitsion kalit — faqat qiymat o'zgarishi."""
    rows_old = [["1", "Tanho", "Abdufattoh", "$1 250", "", ""], ["2", "Asl Food", "Islom", "$1 700", "", ""]]
    rows_new = [["1", "Tanho", "Abdufattoh", "$0", "$1 250", "✅ To'lov qilindi"],
                ["2", "Asl Food", "Islom", "$2 850", "", ""]]
    old = _undiruv_vals(rows_old, "$121 610", "$88 144", keyin=[["", "58", "", "$7 600", "", ""]])
    new = _undiruv_vals(rows_new, "$121 900", "$82 994", keyin=[["", "59", "", "$12 900", "", ""]])
    r = df.diff_range(old, new, "Nomi")
    assert not r["added"] and not r["removed"], (r["added"], r["removed"])
    keys = {c["key"] for c in r["changed"]}
    assert keys == {"Tanho", "Asl Food", "(jami bloki +0)", "(jami bloki +1)"}, keys


def test_k6_son_kalit_jami_yorliqsiz_ham_barqaror():
    hdr = ["№", "Proektlar nomi", "Price"]
    old = [hdr, ["1", "Biboo snack", "$2 000"], ["", "58", "$97 704"]]
    new = [hdr, ["1", "Biboo snack", "$2 000"], ["", "59", "$95 704"]]
    r = df.diff_range(old, new, "Proektlar nomi")
    assert not r["added"] and not r["removed"] and len(r["changed"]) == 1, r


def test_k6_bosh_kalit_tepaga_qator_qoshilsa_qayta_kalitlanmaydi():
    hdr = ["№", "Nomi", "Summa"]
    old = [hdr, ["1", "A", "$1"], ["", "", "izoh"], ["2", "B", "$2"]]
    new = [hdr, ["0", "Yangi", "$5"], ["1", "A", "$1"], ["", "", "izoh"], ["2", "B", "$2"]]
    r = df.diff_range(old, new, "Nomi")
    assert [a["key"] for a in r["added"]] == ["Yangi"] and not r["removed"] and not r["changed"], r


def test_k6_takror_nom_tepaga_qoshilsa_eski_qator_ozgarmaydi():
    """07.10: «Biboo snack» tepasiga yana «Biboo snack» qo'shildi — avval eski qator
    «o'zgardi», o'zi «Biboo snack #2 yangi» deb chiqdi. Endi: 1 yangi, 0 o'zgargan."""
    hdr = ["№", "Proektlar nomi", "Ma'sul", "Price"]
    old = [hdr, ["1", "Biboo snack", "Islom", "$2 000"], ["2", "FTTI", "Zubair", "$1 500"]]
    new = [hdr, ["1", "Biboo snack", "Zubair", "$1 500"], ["2", "Biboo snack", "Islom", "$2 000"],
           ["3", "FTTI", "Zubair", "$1 500"]]
    r = df.diff_range(old, new, "Proektlar nomi")
    assert [a["key"] for a in r["added"]] == ["Biboo snack #2"], r["added"]
    assert a_row(r["added"][0]) == ["1", "Biboo snack", "Zubair", "$1 500"]
    assert not r["removed"], r["removed"]
    # eski qatorlar to'g'ri juftlangan: faqat tartib raqami (№) surildi, qiymatlar emas
    assert {c["key"] for c in r["changed"]} == {"Biboo snack", "FTTI"}, r["changed"]
    assert all(set(c["changes"]) == {"№"} for c in r["changed"]), r["changed"]


def a_row(item):
    return item["row"]


def test_k6_raqam_ustuni_kalit_bolsa_sonlar_haqiqiy_kalit():
    """Kalit «№» ustuni (key_column topilmay 1-ustunga qaytgan holat) — o'rtadagi qator
    o'chsa bitta «o'chgan», qolganlari zanjir bo'lib «o'zgardi» bo'lmaydi."""
    hdr = ["№", "Nomi", "Summa"]
    old = [hdr, ["1", "A", "$1"], ["2", "B", "$2"], ["3", "C", "$3"], ["4", "D", "$4"]]
    new = [hdr, ["1", "A", "$1"], ["3", "C", "$3"], ["4", "D", "$4"]]
    r = df.diff_range(old, new, 1)
    assert [x["key"] for x in r["removed"]] == ["2"] and not r["added"] and not r["changed"], r


def test_k6_row_map_orqaga_moslik():
    m = df.row_map([["1", "X"], ["2", "X"], ["3", "Y"]], 1)
    assert list(m) == ["X", "X #2", "Y"]


# ------------------------------------------------------------------ K7

def test_k7_ustun_qoshilsa_qatorlar_siljimaydi():
    """11.08: sarlavhaga «Proekt soni» qo'shildi — 72 yangi, 72 o'chgan chiqqan edi."""
    old = [["№", "Loyihalar", "Reyting", "Ball"],
           ["1", "Remax", "8", "41,2"], ["2", "Geely", "7", "35"]]
    new = [["№", "Proekt soni", "Loyihalar", "Reyting", "Ball"],
           ["1", "3", "Remax", "8", "41,2"], ["2", "3", "Geely", "7", "36"]]
    r = df.diff_range(old, new, "Loyihalar")
    assert not r["added"] and not r["removed"], r
    assert r["changed"] == [{"key": "Geely", "changes": {"Ball": {"old": "35", "new": "36"}}}], r["changed"]
    assert "header_changed" in r


def test_k7_joyida_qayta_nomlangan_ustun_solishtiriladi():
    old = [["№", "Nomi", "Summa"], ["1", "A", "$1"]]
    new = [["№", "Nomi", "Summa $"], ["1", "A", "$2"]]
    r = df.diff_range(old, new, "Nomi")
    assert r["changed"] == [{"key": "A", "changes": {"Summa $": {"old": "$1", "new": "$2"}}}], r


def test_k7_sarlavhada_bosh_katak_maalumot_qatori_sarlavha_bolmaydi():
    """08.10: sarlavhaning bitta katagi bo'sh — ko'proq to'ldirilgan ma'lumot qatori
    sarlavha bo'lib qolmasin (kalit ustuni nomi bo'yicha topiladi)."""
    vals = [["№", "Proektlar nomi", "", "Narx"], ["1", "A", "x", "$1"], ["2", "B", "y", "$2"]]
    assert df.detect_header(vals) == 1                      # eski usul — xato qator
    assert df.header_index(vals, "Proektlar nomi") == 0
    r = df.diff_range(vals, [list(x) for x in vals[:2]] + [["2", "B", "y", "$3"]], "Proektlar nomi")
    assert not r["added"] and not r["removed"] and [c["key"] for c in r["changed"]] == ["B"], r


# ------------------------------------------------------------------ K8

NOY01 = date(2026, 11, 1)


def test_k8_oy_boshida_arxiv_tab_olinmaydi():
    tabs = ["Undiruv noyabr", "Undiruv oktabr(2026)", "Smm main"]
    assert fm.resolve_month_template("Undiruv <oy>", tabs, NOY01) == []
    assert fm.resolve_key_columns(tabs, {"Undiruv <oy>": "Nomi"}, NOY01) == {}
    tabs.append("Undiruv noyabr(2026)")
    assert fm.resolve_month_template("Undiruv <oy>", tabs, NOY01) == ["Undiruv noyabr(2026)"]


def test_k8_fetch_va_undiruv_bir_xil_qoida():
    assert u.QATIY_DAN is fm.QATIY_DAN
    tabs = ["Undiruv noyabr", "Undiruv noyabr(2025)", "Undiruv dekabr", "Undiruv yanvar",
            "Undiruv iyul", "Undiruv oktabr(2026)", "Undiruv oktabr"]
    for d in (date(2026, 7, 10), date(2026, 10, 9), NOY01, date(2026, 12, 1), date(2027, 1, 1)):
        oy = fm.current_month_name(d)
        qatiy = u.qatiy_oy(date(d.year, d.month, 1))
        assert fm.resolve_month_template("Undiruv <oy>", tabs, d) == \
            u.rank_month_tabs(tabs, oy, d, suffikssiz=not qatiy), d


def _run_all():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for n, f in tests:
        try:
            f()
            passed += 1
            print(f"  ✓ {n}")
        except Exception as e:                   # noqa: BLE001
            failed += 1
            print(f"  ✗ {n} — {type(e).__name__}: {e}")
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
