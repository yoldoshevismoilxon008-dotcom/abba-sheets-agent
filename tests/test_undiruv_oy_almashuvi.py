"""Undiruv oy almashuvi va keyingi oyga oldindan qarash (29.09.2026).

Ega: «oktabr tabi to'g'rilandi, sentabrdan ortgan pul oktabrga yozilgan — bot
oktabrni ham tekshirsin». Qarorlar: oktabr to'lovlari 5 kun oldin eslatilsin;
Stirka sentabr qoldig'i ($364) oktabrga QO'SHILSIN; Maestro kids oktabrda $2 000 TO'LIQ.

Asosiy qo'riqchilar:
  · ko'chirilgan qarz ikki marta so'ralmaydi (imlo farqi bilan ham: «Bosimov shcool»);
  · oy oxirida ko'chgan sentabr qatori ESKI muddat bilan «muddat o'tdi» deb so'ralmaydi;
  · oktabrning ≤5 kunlik to'lovlari 29–30.09 da ko'rinadi;
  · noaniq holat (summa farqli, qarorsiz; ikki o'xshash nom; boshqa PM) — YASHIRILMAYDI (C5);
  · dekabr→yanvar: to'g'ri yil tabi, yilsiz sana to'g'ri yil bilan;
  · nusxa/shablon keyingi oy tabi joriy qarzni yashirmaydi.

pytest tests/test_undiruv_oy_almashuvi.py  yoki  python3 tests/test_undiruv_oy_almashuvi.py
Tarmoq/kredensial kerak emas: korinish() uchun _oy_oqi soxtalashtiriladi.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pm_push as pp   # noqa: E402
import undiruv as u    # noqa: E402

SEP29, SEP30, OKT01 = date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)
HDR = ["№", "Nomi", "Ma'sul shaxs", "LTV", "Summa", "Undirildi", "Aktive  Summary",
       "Lose summa", "Final data", "To'lov xolati", "Tasdiq"]


def _tab(*rows, ref=None, today=SEP29):
    vals = [[""] * 11, HDR] + [list(r) for r in rows] + [["Jami", "", "", "", "", "", "", "", "", "", ""]]
    return u.parse_rows(vals, today, ref)


# Haqiqiy 29.09 holatidan qisqartirilgan (sentabr/oktabr 2026)
SENT = _tab(
    ["1", "Kanzec", "Zubair", "36", "$0", "$2 000", "", "", "06.09", "✅ To'lov qilindi", "TRUE"],
    ["12", "Bazarway", "Islom", "1", "$1 800", "", "", "", "21.09", "", "FALSE"],
    ["13", "Stirka", "Zubair", "18", "$364", "$986", "", "", "21.09", "", "FALSE"],
    ["14", "Bosimov shcool", "Zubair", "3", "$2 500", "", "", "", "18.09", "", "FALSE"],
    ["15", "Maestro kids", "Zubair", "3", "$2 100", "", "", "", "25.09", "", "FALSE"],
    ["22", "Pruddy", "Zubair", "19", "$4 500", "", "", "", "30.09", "", "FALSE"],
    ["23", "Tanho", "Abdufattoh", "13", "$2 417", "$2 083", "", "", "30.09", "", "FALSE"],
    ["26", "Li auto", "Islom", "2", "", "", "", "$2 500", "06.09", "Mijoz yo'q bo'lib qoldi", "FALSE"],
    ["99", "Kechikkan", "Islom", "1", "$700", "", "", "", "20.09", "", "FALSE"],
    ref=date(2026, 9, 1))
OKT = _tab(
    ["1", "Kanzec", "Zubair", "37", "$2 000", "", "", "", "05.10", "", "FALSE"],
    ["9", "Stirkauz", "Zubair", "19", "$1 350", "", "", "", "20.10", "", "FALSE"],
    ["4", "Maestro kids", "Zubair", "4", "$2 000", "", "", "", "05.10", "", "FALSE"],
    ["10", "Bosimov School", "Zubair", "4,5", "$2 500", "", "", "", "18.10", "", "FALSE"],
    ["11", "Pruddy", "Zubair", "20", "$4 500", "", "", "", "05.10", "", "FALSE"],
    ["20", "Tanho", "Abdufattoh", "14", "$2 417", "", "", "", "05.10", "", "FALSE"],
    ["31", "Bazarway", "Islom", "2", "$1 800", "", "", "", "03.10", "", "FALSE"],
    ["14", "Mb city", "Abdufattoh", "14", "$1 600", "", "", "", "03.10", "", "FALSE"],
    ref=date(2026, 10, 1))
AVG = _tab(["1", "Baaztruck", "Azizxo'ja", "1", "$433", "", "", "", "05.08", "", "FALSE"],
           ["2", "Li auto", "Islom", "1", "$2 500", "", "", "", "06.08", "", "FALSE"],
           ref=date(2026, 8, 1))
QAROR = [
    {"loyiha": "Stirka", "yangi_tab": "Undiruv oktabr(2026)", "qaror": "qoshilsin",
     "otgan_qoldiq": 364, "yangi_summa": 1350, "sabab": "ega 29.09"},
    {"loyiha": "Maestro kids", "yangi_tab": "Undiruv oktabr(2026)", "qaror": "yangi_toliq",
     "otgan_qoldiq": 2100, "yangi_summa": 2000, "sabab": "ega 29.09"},
]
TABS = {("sentyabr", 2026): ("Undiruv sentabr(2026)", SENT),
        ("oktyabr", 2026): ("Undiruv oktabr(2026)", OKT),
        ("avgust", 2026): ("Undiruv avgust(2026)", AVG)}


_KORINISH = u.korinish     # asl funksiya — testlar u.korinish'ni almashtirganda rekursiya bo'lmasin


def _view(today, qlar=QAROR, tabs=None):
    tabs = TABS if tabs is None else tabs
    orig = u._oy_oqi
    u._VIEW_KESH.clear()

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi = soxta
    try:
        return _KORINISH(today, day=today.isoformat(), prefer_live=True, qlar=qlar)
    finally:
        u._oy_oqi = orig


def _by(rows):
    return {r["loyiha"]: r for r in rows}


# ------------------------------------------------------------ nom mosligi

def test_nom_ball_imlo_farqlari():
    assert u.nom_ball("Bosimov shcool", "Bosimov School") >= u.FUZZY_MIN
    assert u.nom_ball("Stirka", "Stirkauz") == 0.9            # prefiks
    assert u.nom_ball("Marvid textile", "Mavrid textil") >= u.FUZZY_MIN
    assert u.nom_ball("Mercedes benz", "Mercedes-benz") == 1.0
    assert u.nom_ball("YEC", "YEC gilam") < u.FUZZY_MIN      # 3 belgi — prefiks emas


def test_fuzzy_faqat_bir_xil_pm_bilan():
    prev = _tab(["1", "Bosimov shcool", "Zubair", "", "$2 500", "", "", "", "18.09", "", ""])
    cur = _tab(["1", "Bosimov School", "Islom", "", "$2 500", "", "", "", "18.10", "", ""])
    t = u.month_transition(prev, cur)
    assert not t["moved"] and len(t["real"]) == 1, "boshqa PM'ning qatoriga fuzzy bog'landi"


def test_ikki_oxshash_nomzod_noaniq():
    prev = _tab(["1", "Nexus", "Zubair", "", "$1 600", "", "", "", "10.09", "", ""])
    cur = _tab(["1", "Nexus A", "Zubair", "", "$1 600", "", "", "", "10.10", "", ""],
               ["2", "Nexus B", "Zubair", "", "$1 600", "", "", "", "10.10", "", ""])
    t = u.month_transition(prev, cur)
    assert not t["moved"] and t["noaniq"] and t["real"], t


# ------------------------------------------------------------ oy almashuvi (01.10)

def test_01_oktabr_hech_qarz_ikki_marta_sanalmaydi():
    t = u.month_transition(SENT, OKT, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    moved = {r["loyiha"] for r in t["moved"]}
    assert {"Bazarway", "Pruddy", "Tanho", "Bosimov shcool", "Maestro kids", "Stirka"} <= moved, moved
    assert {r["loyiha"] for r in t["real"]} == {"Kechikkan"}, "ko'chirilmagan qarz so'ralishda qolishi kerak"


def test_qaror_qoshilsin_stirka_1714():
    t = u.month_transition(SENT, OKT, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    st = _by(t["cur_rows"])["Stirkauz"]
    assert round(st["qoldiq"]) == 1714
    assert st["qoshimcha"] == {"summa": 364, "oy": "sentyabr", "asl": 1350, "jadvalda": False}
    assert round(_by(OKT)["Stirkauz"]["qoldiq"]) == 1350, "asl qator o'zgarib ketdi (nusxa emas)"


def test_qaror_yangi_toliq_maestro_2000():
    t = u.month_transition(SENT, OKT, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    assert round(_by(t["cur_rows"])["Maestro kids"]["qoldiq"]) == 2000
    assert "Maestro kids" not in {r["loyiha"] for r in t["real"]}


def test_qarorsiz_summa_farqli_yashirilmaydi():
    t = u.month_transition(SENT, OKT, "Undiruv oktabr(2026)", [], prev_oy="sentyabr")
    real = {r["loyiha"] for r in t["real"]}
    assert {"Maestro kids", "Stirka"} <= real, "qarorsiz farqli summa jim yashirildi"
    assert {r["loyiha"] for r in t["farqli"]} >= {"Maestro kids", "Stirka"}


def test_qoshilsin_jadvalga_kiritilsa_ikki_marta_qoshilmaydi():
    okt = [dict(r) for r in OKT]
    _by(okt)["Stirkauz"]["qoldiq"] = 1714                     # ega jadvalni tuzatdi
    t = u.month_transition(SENT, okt, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    st = _by(t["cur_rows"])["Stirkauz"]
    assert round(st["qoldiq"]) == 1714 and st["qoshimcha"]["jadvalda"], st
    stirka = next(r for r in t["moved"] if r["loyiha"] == "Stirka")
    assert stirka["_kochish"]["turi"] == "qaror_jadvalda"             # sentabr $364 bog'landi, ikki marta emas


def test_eskirgan_qaror_oddiy_qoidaga_qaytadi():
    okt = [dict(r) for r in OKT]
    _by(okt)["Maestro kids"]["qoldiq"] = 1900                # jadval boshqa qiymatga o'zgardi
    t = u.month_transition(SENT, okt, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    assert "Maestro kids" in {r["loyiha"] for r in t["real"]}
    assert any("eskirgan" in i for i in t["izoh"]), t["izoh"]


def test_carryover_filter_orqaga_moslik():
    real, closed, moved = u.carryover_filter(SENT, OKT)
    assert "Bosimov shcool" in {r["loyiha"] for r in moved}   # imlo farqi endi tanildi


# ------------------------------------------------------------ oy oxiri (29–30.09)

def test_oldinga_qarash_oynasi():
    assert u.oldinga_qarash_faolmi(date(2026, 9, 25))           # 5 kun qoldi
    assert not u.oldinga_qarash_faolmi(date(2026, 9, 24))
    assert u.oy_oxiriga_kun(SEP30) == 0
    assert u.oy_oxiriga_kun(date(2026, 2, 26)) == 2


def test_29_09_kochganlar_eski_muddat_bilan_soralmaydi():
    v = _view(SEP29)
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    matn = "\n".join(l for ls in per_pm.values() for l in ls)
    for nom in ("Bosimov shcool", "Stirka —", "Maestro kids — qoldiq $2 100", "Bazarway —"):
        assert f"MUDDAT O'TDI" not in matn or nom not in matn, (nom, matn)
    assert "🔴 MUDDAT O'TDI (9 kun): Kechikkan" in matn, "ko'chirilmagan sentabr qarzi yo'qolib qoldi"
    kochgan = {i["loyiha"] for i in st["keyingi_kochgan"]}
    assert {"Bazarway", "Bosimov shcool", "Maestro kids", "Stirka", "Pruddy", "Tanho"} <= kochgan


def test_29_09_oktabr_yaqin_tolovlar_eslatiladi():
    v = _view(SEP29)
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    matn = "\n".join(l for ls in per_pm.values() for l in ls)
    assert "Mb city (oktyabr) — qoldiq $1 600, muddat 03.10 (4 kun qoldi)" in matn, matn
    assert "Bazarway (oktyabr)" in matn
    assert "Pruddy (oktyabr)" not in matn                      # 05.10 — 6 kun, oynadan tashqari
    assert st["keyingi_n"] == 2 and st["keyingi_sum"] == 3400, st


def test_30_09_besh_kunlik_oyna():
    v = _view(SEP30)
    per_pm, st = pp.build_push(SEP30, v["rows"], v["prev"]["rows"], "avgust", view=v)
    matn = "\n".join(l for ls in per_pm.values() for l in ls)
    assert "Pruddy (oktyabr) — qoldiq $4 500, muddat 05.10 (5 kun qoldi)" in matn
    assert "Maestro kids (oktyabr) — qoldiq $2 000" in matn
    assert "Stirkauz (oktyabr)" not in matn                     # 20.10 — uzoq


def test_summary_va_push_bir_xil_qoida():
    orig = u.korinish
    u.korinish = lambda today=None, day=None, prefer_live=True, qlar=None, kesh=False: _view(SEP29)
    try:
        s = u.summary("2026-09-29", SEP29)
    finally:
        u.korinish = orig
    otgan = {i["loyiha"] for i in s["muddat_otgan"]}
    assert otgan == {"Kechikkan"}, otgan                          # ko'chganlar overdue emas
    assert {i["loyiha"] for i in s["keyingi"]["yaqin"]} == {"Mb city", "Bazarway"}
    assert s["yaqin_kun"] == pp.PUSH_DUE_DAYS == 5


def test_report_data_kochdi_holati():
    v = _view(SEP29)
    d = u.report_data(v["rows"], v["tab"], SEP29)
    z = next(p for p in d["pms"] if p["name"] == "Zubair")
    st = {i["loyiha"]: i["status"] for i in z["items"]}
    assert st["Bosimov shcool"] == "kochdi" and st["Maestro kids"] == "kochdi"
    assert z["n"] == 0, "ko'chgan qarz PM «undirilmagan» soniga qo'shildi"


def test_shablon_nusxa_joriy_qarzni_yashirmaydi():
    nusxa = _tab(["1", "Kechikkan", "Islom", "", "$700", "", "", "", "20.09", "", ""],
                 ref=date(2026, 10, 1))                         # eski muddat bilan nusxa
    tabs = dict(TABS)
    tabs[("oktyabr", 2026)] = ("Undiruv oktabr(2026)", nusxa)
    v = _view(SEP29, tabs=tabs)
    assert not _by(v["rows"])["Kechikkan"].get("keyingi_oyga"), "nusxa tab joriy qarzni yashirdi"


def test_keyingi_oy_tabi_yoq_jim_emas():
    tabs = {k: t for k, t in TABS.items() if k[0] != "oktyabr"}
    v = _view(SEP29, tabs=tabs)
    assert v["keyingi"] is not None and v["keyingi"]["tab"] is None
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    assert st["keyingi_bor"] and not st["keyingi_tab"]


def test_ketgan_mijoz_eski_qarzi_yopiladi():
    """Li auto: avgustda $2 500, sentabrda «Mijoz yo'q bo'lib qoldi» + Lose — endi yopilgan."""
    li = _by(SENT)["Li auto"]
    assert li["holat"] == "ketdi"
    t = u.month_transition(AVG, SENT, "Undiruv sentabr(2026)", [], prev_oy="avgust")
    assert "Li auto" in {r["loyiha"] for r in t["closed"]}
    assert "Baaztruck" in {r["loyiha"] for r in t["real"]}      # ko'chirilmagan — so'raladi


def test_qarzi_bor_lose_noaniq_soralaveradi():
    r = _tab(["1", "Oqsaroy", "Islom", "", "$1 600", "", "", "$1 600", "05.08", "Kutilmoqda", ""])[0]
    assert r["holat"] == "pending" and u.is_unpaid(r)


# ------------------------------------------------------------ yil almashuvi

def test_oy_ofset_yil_almashuvi():
    assert u.oy_ofset(date(2026, 12, 28), 1) == ("yanvar", 2027, date(2027, 1, 1))
    assert u.oy_ofset(date(2027, 1, 3), -1) == ("dekabr", 2026, date(2026, 12, 1))
    assert u.oy_ofset(date(2027, 1, 3), -2) == ("noyabr", 2026, date(2026, 11, 1))


def test_rank_keyingi_yil_tabi():
    titles = ["Undiruv yanvar", "Undiruv yanvar(2027)", "Undiruv dekabr", "Undiruv dekabr(2026)"]
    assert u.rank_month_tabs(titles, "yanvar", date(2026, 12, 28), year=2027, suffikssiz=False) == \
        ["Undiruv yanvar(2027)"]
    assert u.rank_month_tabs(titles, "dekabr", date(2027, 1, 3), year=2026, suffikssiz=False) == \
        ["Undiruv dekabr(2026)"]
    # qat'iy rejim: yil tabi yo'q bo'lsa suffikssiz ARXIV olinmaydi
    assert u.rank_month_tabs(["Undiruv oktabr"], "oktyabr", SEP29, year=2026, suffikssiz=False) == []


def test_yilsiz_sana_tab_oyiga_yaqin_yil():
    assert u.parse_due("05.01", date(2026, 12, 28), ref=date(2027, 1, 1)) == date(2027, 1, 5)
    assert u.parse_due("28.12", date(2027, 1, 3), ref=date(2026, 12, 1)) == date(2026, 12, 28)
    assert u.parse_due("05.10", SEP29) == date(2026, 10, 5)     # ref'siz — eski xulq


def test_find_tab_snapshot_boshqa_yilni_olmaydi():
    snap = {"ranges": {"'Undiruv sentabr(2025)'!A1:BZ1000": {}, "'Undiruv sentabr'!A1:BZ1000": {}}}
    assert u.find_tab(snap, date(2026, 9, 6), month="sentyabr") == "'Undiruv sentabr'!A1:BZ1000"
    assert u.find_tab(snap, date(2026, 9, 6), month="sentyabr", year=2026, qat_iy=True) is None


# ------------------------------------------------------------ mustaqil tekshiruv tuzatishlari (29.09 kech)

def _okt_bilan(*qatorlar, olib_tashla=()):
    okt = [r for r in OKT if r["loyiha"] not in olib_tashla] + _tab(*qatorlar, ref=date(2026, 10, 1))
    tabs = dict(TABS)
    tabs[("oktyabr", 2026)] = ("Undiruv oktabr(2026)", okt)
    return tabs


def _blok(v, today):
    orig = u.korinish
    u.korinish = lambda *a, **k: v
    try:
        return u.report_block(today.isoformat(), today)
    finally:
        u.korinish = orig


def test_kesh_faqat_kesh_true_bilan():
    """Bot/scheduler jarayonida (kesh=False) har chaqiruv qayta o'qiydi: ega sheet'ni
    tuzatib /pm_push force bersa, eski ma'lumot PM'ga ketmasin (C1/M7/D1/S1)."""
    oqildi = []
    orig = u._oy_oqi

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        oqildi.append(month)
        t = TABS.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi = soxta
    u._VIEW_KESH.clear()
    try:
        a = _KORINISH(OKT01, day=OKT01.isoformat())
        b = _KORINISH(OKT01, day=OKT01.isoformat())
        assert a is not b and len(oqildi) == 4, oqildi          # 2 chaqiruv × (joriy + o'tgan)
        c = _KORINISH(OKT01, day=OKT01.isoformat(), kesh=True)
        d = _KORINISH(OKT01, day=OKT01.isoformat(), kesh=True)
        assert c is d and len(oqildi) == 6, oqildi              # kesh=True — ikkinchisi keshdan
    finally:
        u._oy_oqi = orig
        u._VIEW_KESH.clear()


def test_qoshilsin_tolov_kelsa_ham_364_saqlanadi():
    """Stirkauz'ga to'lov yozilsa ham sentabr $364 yopilib ketmaydi (M2)."""
    for summa, undirildi, holat, kutil in (("$350", "$1 000", "", 714),
                                           ("$0", "$1 350", "✅ To'lov qilindi", 364)):
        okt = [r for r in OKT if r["loyiha"] != "Stirkauz"] + _tab(
            ["9", "Stirkauz", "Zubair", "19", summa, undirildi, "", "", "20.10", holat, ""],
            ref=date(2026, 10, 1))
        t = u.month_transition(SENT, okt, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
        st = _by(t["cur_rows"])["Stirkauz"]
        assert round(st["qoldiq"]) == kutil and u.is_unpaid(st), (summa, st)
        assert "Stirka" in {r["loyiha"] for r in t["moved"]}
        assert "Stirka" not in {r["loyiha"] for r in t["closed"]}, "to'lov qarorni yopib yubordi"
        assert "to'langan $" in pp._tafsil(st, "oktyabr")


def test_qoshilsin_noyabrda_saqlanadi():
    """Oktabr «o'tgan oy» bo'lganda ham qo'shilgan $364 yo'qolmaydi (D4) — lekin faqat sentabr
    tabi tekshirilib: u yerda $364 to'langan bo'lsa qayta so'ralmaydi (MN1/DN1)."""
    noy = _tab(["9", "Stirkauz", "Zubair", "20", "$1 350", "", "", "", "20.11", "", ""], ref=date(2026, 11, 1))
    tabs = {("sentyabr", 2026): ("Undiruv sentabr(2026)", SENT), ("oktyabr", 2026): ("Undiruv oktabr(2026)", OKT),
            ("noyabr", 2026): ("Undiruv noyabr(2026)", noy)}
    v = _view(date(2026, 11, 3), tabs=tabs)
    assert round(_by(v["prev"]["rows"])["Stirkauz"]["qoldiq"]) == 1714
    assert "Stirkauz" in {r["loyiha"] for r in v["prev"]["real"]}   # $1 714 ≠ $1 350 — alohida so'raladi
    assert any("jadvalga kiritilmagan" in n for n in v["notes"]), v["notes"]
    # sentabr qatori to'langan — $364 qo'shilmaydi, oktabr $1 350 = noyabr $1 350 → bir marta
    sent_tol = [dict(r) for r in SENT if r["loyiha"] != "Stirka"] + _tab(
        ["13", "Stirka", "Zubair", "18", "$0", "$1 350", "", "", "21.09", "✅ To'lov qilindi", ""], ref=date(2026, 9, 1))
    tabs[("sentyabr", 2026)] = ("Undiruv sentabr(2026)", sent_tol)
    v = _view(date(2026, 11, 3), tabs=tabs)
    assert round(_by(v["prev"]["rows"])["Stirkauz"]["qoldiq"]) == 1350
    assert "Stirkauz" not in {r["loyiha"] for r in v["prev"]["real"]}
    # sentabr tabi o'qilmasa — qo'llanmaydi, halol izoh (tekshirilmagan qo'shish yo'q)
    del tabs[("sentyabr", 2026)]
    v = _view(date(2026, 11, 3), tabs=tabs)
    assert round(_by(v["prev"]["rows"])["Stirkauz"]["qoldiq"]) == 1350
    assert any("tabi o'qilmadi" in n for n in v["notes"]), v["notes"]


def test_buzuq_qaror_korinishni_yiqitmaydi():
    """Qo'lda buzilgan qaror — tashlanadi, egaga izoh; push yiqilmaydi (M6/S3)."""
    buzuq = [{"loyiha": "Stirka", "yangi_tab": "Undiruv oktabr(2026)", "qaror": "qoshilsin",
              "otgan_qoldiq": None, "yangi_summa": 1350},
             "Maestro kids",
             {"loyiha": "X", "qaror": "nomalum", "yangi_tab": "T", "otgan_qoldiq": 1, "yangi_summa": 1}]
    v = _view(OKT01, qlar=buzuq)
    assert v["tab"] and sum("noto'g'ri" in n for n in v["notes"]) == 3, v["notes"]
    pp.build_push(OKT01, v["rows"], v["prev"]["rows"], "sentyabr", view=v)


def test_repo_qaror_fayli_yaroqli():
    """Deploy bilan ketadigan undiruv_qaror.json — 2 ta yaroqli qaror, xatosiz (S6)."""
    u._QAROR_KESH.update(mtime=None, data=[], xato=[])
    q = u.qarorlar()
    assert {x["loyiha"] for x in q} == {"Stirka", "Maestro kids"} and not u.qaror_xatolari()


def test_oy_oxiri_keyingi_tabda_tolangan_alohida_belgi():
    """Oktabr qatori to'langan — sentabr qarzi «ko'chirilgan → muddat» emas, 🧹 (M1/C3/S9)."""
    tabs = _okt_bilan(["11", "Pruddy", "Zubair", "20", "$0", "$4 500", "", "", "05.10", "✅ To'lov qilindi", "TRUE"],
                      olib_tashla=("Pruddy",))
    v = _view(SEP29, tabs=tabs)
    assert _by(v["rows"])["Pruddy"]["keyingi_oyga"]["turi"] == "yopilgan"
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    assert "Pruddy" in {i["loyiha"] for i in st["keyingi_yopilgan"]}
    assert "Pruddy" not in {i["loyiha"] for i in st["keyingi_kochgan"]}
    d = u.report_data(v["rows"], v["tab"], SEP29, view=v)
    z = next(p for p in d["pms"] if p["name"] == "Zubair")
    assert {i["loyiha"]: i["status"] for i in z["items"]}["Pruddy"] == "yopildi"
    blok = _blok(v, SEP29)
    assert "🧹 Oktyabr tabida" in blok and "Pruddy" in blok.split("🧹 Oktyabr tabida")[1], blok


def test_nusxa_qator_eski_muddat_ikki_marta_soralmaydi():
    """Keyingi oy tabidagi JORIY oy sanali nusxa qator ikkinchi marta eslatilmaydi (D2/S2)."""
    tabs = _okt_bilan(["20", "Tanho", "Abdufattoh", "14", "$2 417", "", "", "", "30.09", "", ""],
                      olib_tashla=("Tanho",))
    v = _view(SEP29, tabs=tabs)
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    matn = "\n".join(per_pm.get("Abdufattoh", []))
    assert matn.count("Tanho") == 1, matn
    assert any("oyi muddatli" in n and "Tanho" in n for n in v["notes"]), v["notes"]


def test_otgan_oy_qoldigi_keyingi_tabga_yozilsa_bir_marta():
    """Ega avgust qoldig'ini (Baaztruck) oktabr tabiga yozsa — 30.09 da bir marta so'raladi (D6)."""
    v = _view(SEP30, tabs=_okt_bilan(["40", "Baaztruck", "Azizxo'ja", "2", "$433", "", "", "", "05.10", "", ""]))
    per_pm, st = pp.build_push(SEP30, v["rows"], v["prev"]["rows"], "avgust", view=v)
    matn = "\n".join(per_pm.get("Azizxo'ja", []))
    assert matn.count("Baaztruck") == 1 and "Baaztruck (oktyabr)" in matn, matn
    assert st["overdue_carry_n"] == 0
    assert not any("Baaztruck" in n for n in v["notes"]), v["notes"]


def test_kochirilmagan_otgan_qoldiq_ogohlantiriladi():
    """1-oktyabrdan kuzatuvdan tushadigan avgust qoldig'i egaga OLDINDAN aytiladi (D11/S13)."""
    v = _view(SEP29)
    assert any("Baaztruck" in n and "1-oktyabrdan" in n for n in v["notes"]), v["notes"]
    assert [r["loyiha"] for r in v["keyingi"]["tushadi"]] == ["Baaztruck"]
    assert "Baaztruck" in _blok(v, SEP29)


def test_joriy_oy_tabi_yoq_arxivga_tushmaydi():
    """01.11: «noyabr(2026)» yo'q — 2025 arxivi o'qilmaydi, egaga aniq ogohlantirish (M8/D5/S4)."""
    assert u.qatiy_oy(date(2026, 11, 1)) and not u.qatiy_oy(date(2026, 7, 1))
    assert u.rank_month_tabs(["Undiruv noyabr"], "noyabr", date(2026, 11, 1), year=2026, suffikssiz=False) == []
    qat = []
    orig = u._oy_oqi

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        qat.append((month, qat_iy))
        t = TABS.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi = soxta
    try:
        v = _KORINISH(date(2026, 11, 2), day="2026-11-02", qlar=[])
    finally:
        u._oy_oqi = orig
    assert qat[0] == ("noyabr", True), qat                   # joriy oy ham qat'iy
    assert v["tab"] is None and any("topilmadi" in n for n in v["notes"])
    orig_k = u.korinish
    u.korinish = lambda *a, **k: v
    try:
        s = u.summary("2026-11-02", date(2026, 11, 2))
    finally:
        u.korinish = orig_k
    assert s["topilmadi"] and "topilmadi" in _blok(v, date(2026, 11, 2))


def test_oqish_xatosi_hali_yoq_deb_aytilmaydi():
    """Keyingi oy tabi o'qilmasa — «hali yo'q» yolg'oni emas, «o'qilmadi (xato)» (C4/S5)."""
    orig_f, orig_l = u.fetch_live_month, u.diffmod.load_day

    def portla(*a, **k):
        raise TimeoutError("sheets javob bermadi")
    u.fetch_live_month = portla
    u.diffmod.load_day = lambda day: ({}, None)
    notes = []
    try:
        res = u._oy_oqi("oktyabr", 2026, date(2026, 10, 1), SEP29, "2026-09-29", True, True, notes)
    finally:
        u.fetch_live_month, u.diffmod.load_day = orig_f, orig_l
    assert res == (None, [], "xato") and "o'qilmadi" in notes[0], (res, notes)
    orig = u._oy_oqi

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes_):
        if month == "oktyabr":
            notes_.append("⚠️ «Undiruv oktyabr(2026)» tabi o'qilmadi (jonli xato: TimeoutError)")
            return None, [], "xato"
        t = TABS.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi = soxta
    try:
        v = _KORINISH(SEP29, day="2026-09-29", qlar=QAROR)
    finally:
        u._oy_oqi = orig
    blok = _blok(v, SEP29)
    assert "O'QILMADI" in blok and "hali yo'q" not in blok, blok
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    assert st["keyingi_source"] == "xato"


def test_fuzzy_himoyalari():
    """Raqam/alohida so'z farqi, to'langan fuzzy juft, ikki nomzodli joriy qator (M3)."""
    assert u.nom_ball("Chorvoq hills 1", "Chorvoq hills 2") == 0.0
    assert u.nom_ball("Mb city", "Mb city 2") == 0.0
    assert u.nom_ball("Stirka", "Stirkauz") == 0.9 and u.nom_ball("Baaz", "Baaztruck") == 0.9
    assert u.nom_ball("Rivo", "Rivo water") == 0.9          # real: butun so'z qo'shilgan nom o'zgarishi
    # fuzzy juft «ko'chirildi» bo'lsa egaga ikkala nom ko'rsatiladi (tekshirish mumkin bo'lsin)
    t = u.month_transition(_tab(["1", "Rivo", "Azizxo'ja", "", "$1 800", "", "", "", "20.09", "", ""]),
                           _tab(["1", "Rivo water", "Azizxo'ja", "", "$1 800", "", "", "", "04.10", "", ""]))
    assert u.kochish_matn(t["moved"][0]).startswith("Rivo → Rivo water"), t
    prev = _tab(["1", "Bosimov shcool", "Zubair", "", "$2 500", "", "", "", "18.09", "", ""])
    cur = _tab(["1", "Bosimov School", "Zubair", "", "$0", "$2 500", "", "", "18.10", "✅ To'lov qilindi", ""])
    t = u.month_transition(prev, cur)
    assert not t["closed"] and [r["loyiha"] for r in t["real"]] == ["Bosimov shcool"] and t["noaniq"], t
    prev = _tab(["1", "Nexus school", "Zubair", "", "$1 600", "", "", "", "10.09", "", ""],
                ["2", "Nexus schol", "Zubair", "", "$1 600", "", "", "", "10.09", "", ""])
    cur = _tab(["1", "Nexus schooll", "Zubair", "", "$1 600", "", "", "", "10.10", "", ""])
    t = u.month_transition(prev, cur)
    assert not t["moved"] and len(t["real"]) == 2 and len(t["noaniq"]) == 2, t


def test_aniq_juftlash_tolanmagan_qator_birinchi():
    """To'langan dublikat qator to'lanmagan qarzning juftini egallamaydi (M4)."""
    prev = _tab(["1", "Pruddy", "Zubair", "", "$0", "$2 000", "", "", "05.09", "✅ To'lov qilindi", ""],
                ["2", "Pruddy", "Zubair", "", "$4 500", "", "", "", "30.09", "", ""])
    cur = _tab(["1", "Pruddy", "Zubair", "", "$4 500", "", "", "", "05.10", "", ""])
    t = u.month_transition(prev, cur)
    assert [r["loyiha"] for r in t["moved"]] == ["Pruddy"] and not t["real"], t


def test_yilsiz_sana_oynasi_otmishga_moyil():
    """Tab oyiga nisbatan [−305, +92] kun oynasi: eski qarz o'tmishda qoladi (D3/S11/DN2)."""
    assert u.parse_due("15.02", SEP29, ref=date(2026, 9, 1)) == date(2026, 2, 15)   # eski qarz — o'tgan
    assert u.parse_due("05.1", date(2026, 10, 3), ref=date(2026, 10, 1)) == date(2026, 1, 5)
    assert u.parse_due("29.02", date(2027, 2, 3), ref=date(2027, 2, 1)) is None      # yil «tuzatilmaydi»
    assert u.parse_due("05.01", date(2026, 12, 28), ref=date(2026, 12, 1)) == date(2027, 1, 5)
    assert u.parse_due("28.12", date(2027, 1, 3), ref=date(2027, 1, 1)) == date(2026, 12, 28)
    # yil boshidagi tablarda ko'chirilib yurgan o'tgan yil qarzi kelajakka o'tmaydi (DN2)
    assert u.parse_due("05.08", date(2027, 1, 10), ref=date(2027, 1, 1)) == date(2026, 8, 5)
    assert u.parse_due("20.10", date(2027, 2, 3), ref=date(2027, 2, 1)) == date(2026, 10, 20)
    assert u.parse_due("15.12", date(2027, 3, 3), ref=date(2027, 3, 1)) == date(2026, 12, 15)
    assert u.parse_due("03.10", SEP29, ref=date(2026, 10, 1)) == date(2026, 10, 3)   # keyingi oy tabi


def test_ega_pdf_malumoti_keyingi_oy_va_otgan_qoldiq():
    """30.09: ega PDF'i PM'larga ketayotgan oktabr eslatmalari va avgust qoldig'ini ko'rsatadi,
    «qarz yo'q» demaydi (M5/C2/S10)."""
    v = _view(SEP30)
    d = u.report_data(v["rows"], v["tab"], SEP30, view=v)
    per_pm, st = pp.build_push(SEP30, v["rows"], v["prev"]["rows"], "avgust", view=v)
    assert d["keyingi"]["n"] == st["keyingi_n"] and d["keyingi"]["sum"] == st["keyingi_sum"]
    assert d["otgan"]["n"] == st["overdue_carry_n"] == 1                  # Baaztruck
    az = next(p for p in d["pms"] if p["name"] == "Azizxo'ja")
    assert az["n"] == 0 and "avgust qoldig'i" in u.pm_qoshimcha_matn(az)
    import render_pdf
    html = render_pdf.build_undiruv_html(d, logo_uri="")
    assert "dolzarb qarz yo'q" not in html and "oktyabr ≤5 kun" in html
    cap = u.pdf_caption(d)
    assert "📅 Oktyabr (keyingi oy)" in cap and "shundan oktyabr tabida" in cap, cap


def test_jamlama_eslatildi_demaydi():
    """Kontakt yo'q (hech narsa yuborilmagan) kun jamlama «PM'larga eslatildi» demaydi (M10/C6/S7)."""
    v = _view(SEP30)
    saqla = {n: getattr(pp, n) for n in ("_load_state", "_save_state", "load_contacts",
                                         "slots_from_config", "send_owner", "owner_pdf")}
    orig_k, egaga = u.korinish, []
    import userbot_sender
    orig_av = userbot_sender.available
    pp._load_state, pp._save_state = (lambda: {}), (lambda d: None)
    pp.load_contacts, pp.slots_from_config = (lambda: {}), (lambda: {"zubair": "Zubair"})
    pp.send_owner, pp.owner_pdf = (lambda t: egaga.append(t)), (lambda *a, **k: True)
    u.korinish = lambda *a, **k: v
    userbot_sender.available = lambda: (True, "")
    try:
        _st, jamlama = pp.run_daily(today=SEP30)
    finally:
        for n, f in saqla.items():
            setattr(pp, n, f)
        u.korinish = orig_k
        userbot_sender.available = orig_av
    assert "PM'larga eslatildi" not in jamlama and "PM xabarlariga qo'shildi" in jamlama, jamlama


def test_pm_push_test_ism_variantlari_birlashadi():
    """/pm_push test ham run_daily kabi PM ismi variantlarini bitta xabarga yig'adi (C8/S8)."""
    by_slot, slot_n, _nd = pp._slotga_yig({"Azizxo'ja": ["a"], "Azizxo’ja": ["b"]}, {})
    assert list(by_slot) == ["azizxoja"] and by_slot["azizxoja"][1] == ["a", "b"] and slot_n["azizxoja"] == 2


def test_qaror_izohi_oy_nomi_bilan():
    """Oy oxirida Maestro qarori: «o'tgan oy» emas, «sentyabr»; 🔁 ro'yxatida so'raladigan summa (C7)."""
    v = _view(SEP29)
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    q = [x for x in st["qaror_qollangan"] if x.startswith("Maestro kids")]
    assert q and "sentyabr $2 100 alohida so'ralmaydi" in q[0] and "o'tgan oy" not in q[0], q
    km = [i["matn"] for i in st["keyingi_kochgan"] if i["loyiha"] == "Maestro kids"]
    assert km == ["Maestro kids ($2 100 → $2 000, 05.10 — ega qarori)"], km


# ------------------------------------------------------------ ikkinchi qayta tekshiruv (29.09 tun)

def test_eskirgan_yangi_toliq_teng_summa_bir_marta():
    """Qaror eskirgan, lekin summalar AYNAN teng — ko'chirilgan, ikki marta so'ralmaydi (MN6/SN4)."""
    okt = [dict(r) for r in OKT]
    _by(okt)["Maestro kids"]["qoldiq"] = 2100                   # jadval $2 100 ga o'zgardi
    t = u.month_transition(SENT, okt, "Undiruv oktabr(2026)", QAROR, prev_oy="sentyabr")
    assert "Maestro kids" in {r["loyiha"] for r in t["moved"]}
    assert "Maestro kids" not in {r["loyiha"] for r in t["real"]}


def test_aniq_nom_global_juftlash():
    """Boshqa PM'ning bir xil nomli qatori yagona joriy qatorni «egallab» olmaydi (MN9)."""
    prev = _tab(["1", "Tanho", "Islom", "", "$2 417", "", "", "", "20.09", "", ""],
                ["2", "Tanho", "Abdufattoh", "", "$2 417", "", "", "", "20.09", "", ""])
    cur = _tab(["1", "Tanho", "Abdufattoh", "", "$2 417", "", "", "", "05.10", "", ""])
    t = u.month_transition(prev, cur)
    assert [r["pm"] for r in t["moved"]] == ["Abdufattoh"] and [r["pm"] for r in t["real"]] == ["Islom"], t


def test_otgan_tab_oqilmasa_qaror_eskirgan_demaydi():
    """O'tgan oy tabi o'qilmadi — qaror «to'langan» deb eskirmaydi, halol izoh (MN2/DN4/SN2)."""
    tabs = {k: t for k, t in TABS.items() if k[0] != "sentyabr"}
    v = _view(OKT01, tabs=tabs)
    iz = " ".join(v["notes"] + v["prev"]["izoh"])
    assert "eskirgan" not in iz and "o'qilmadi" in iz, iz
    assert round(_by(v["rows"])["Stirkauz"]["qoldiq"]) == 1350


def test_jami_farqi_izohi_faqat_joriy_oyda():
    """«Jami farqi» izohi faqat qaror joriy oy tabida qo'llanganda (CN1)."""
    assert any("Jami farqi" in n for n in _view(OKT01)["notes"])
    assert not any("Jami farqi" in n for n in _view(SEP29)["notes"])


def test_pmsiz_keyingi_oy_qatori_sanoqqa_kirmaydi():
    """PM'siz keyingi oy qatori PM xabariga tushmaydi va «qo'shildi» sanog'iga kirmaydi (C6)."""
    tabs = _okt_bilan(["14", "Mb city", "", "14", "$1 600", "", "", "", "03.10", "", ""], olib_tashla=("Mb city",))
    v = _view(SEP29, tabs=tabs)
    per_pm, st = pp.build_push(SEP29, v["rows"], v["prev"]["rows"], "avgust", view=v)
    assert st["keyingi_n"] == 1 and st["keyingi_sum"] == 1800, st        # faqat Bazarway
    assert any(i["loyiha"] == "Mb city" for i in st["pm_missing"])


def test_takroriy_qaror_bir_marta():
    """undiruv_qaror.json'da ikki marta yozilgan qaror bir marta qo'llanadi (SN5)."""
    t = u.month_transition(SENT, OKT, "Undiruv oktabr(2026)", QAROR + [QAROR[0]], prev_oy="sentyabr")
    assert round(_by(t["cur_rows"])["Stirkauz"]["qoldiq"]) == 1714
    assert any("takroriy" in i for i in t["izoh"]), t["izoh"]


def test_kanonik_tab_birinchi():
    """Shablon/nusxa tab kanonik oy tabidan oldin tanlanmaydi (D10)."""
    titles = ["Undiruv oktabr (2026) shablon", "Undiruv oktabr(2026)"]
    assert u.rank_month_tabs(titles, "oktyabr", SEP29, year=2026, suffikssiz=False)[0] == "Undiruv oktabr(2026)"


def test_status_bosh_kochganlarni_sanamaydi():
    """Keyingi oyga ko'chgan qatorlar «status bo'sh qarz» sanog'iga kirmaydi (C2)."""
    v = _view(SEP29)
    assert u.totals(v["rows"])["status_blank_n"] == 1                  # faqat Kechikkan (so'raladigan)


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
