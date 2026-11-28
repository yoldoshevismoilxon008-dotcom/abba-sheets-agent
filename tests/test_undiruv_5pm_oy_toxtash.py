"""5-PM slot (config «undiruv_pmlar»), userbot limiti va 1-dekabrdan o'tgan oy so'ralmasligi
(ega qarori 27.11.2026: «noyabr va dekabrni parallel berib, dekabrga o'tganda noyabr update'ini
so'rashni to'xtatsin»).

Qo'riqchilar:
  · KPI sheet'i yo'q PM ham slot oladi; sheet'dagi imlo aliasi shu slotga boradi, taxminiy
    (prefiks) moslik YO'Q;
  · ro'yxatda yo'q ism egaga ⚠️ + tayyor matn bilan chiqadi (ilgari noto'g'ri «/pm_set» deyilardi);
  · userbot bir chiqishda 8 tagacha yuboradi, ortig'i jim kesilmaydi — xato bo'lib qaytadi;
  · OTGAN_OY_TOXTASH_DAN dan o'tgan oy qoldig'i PM'ga ketmaydi (PDF/💰 blok ham ko'rsatmaydi),
    egaga oy boshida ℹ️, oy oxirida oldindan ⚠️; undan oldingi oylar — eski qoida.
Barcha nomlar SOXTA (repo ommaviy). Tarmoq/kredensial kerak emas: _oy_oqi soxtalashtiriladi.
"""
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fetch as fetchmod  # noqa: E402
import pm_push as pp      # noqa: E402
import undiruv as u       # noqa: E402
import userbot_sender as ub  # noqa: E402

HDR = ["№", "Nomi", "Ma'sul shaxs", "LTV", "Summa", "Undirildi", "Aktive  Summary",
       "Lose summa", "Final data", "To'lov xolati", "Tasdiq"]


def _tab(*rows, ref, today):
    vals = [[""] * 11, HDR] + [list(r) for r in rows] + [["Jami"] + [""] * 10]
    return u.parse_rows(vals, today, ref)


def _qator(nom, pm, summa, sana, holat=""):
    return ["1", nom, pm, "1", summa, "", "", "", sana, holat, "FALSE"]


def _view(today, tabs):
    """korinish() — soxta oy tablari bilan (qarorlarsiz)."""
    orig = u._oy_oqi
    u._VIEW_KESH.clear()

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi = soxta
    try:
        return u.korinish(today, day=today.isoformat(), prefer_live=True, qlar=[])
    finally:
        u._oy_oqi = orig


def _push(today, v):
    return pp.build_push(today, v["rows"], v["prev"]["rows"] or [], v["prev"]["oy"], view=v)


def _barcha_satrlar(per_pm):
    return [ln for lines in per_pm.values() for ln in lines]


# ------------------------------------------------------------ soxta oylar (2026)

def _noyabr(today):
    return ("Undiruv noyabr(2026)", _tab(
        _qator("Kochmagan qarz", "Alfa", "$900", "20.11"),           # dekabrda yo'q
        _qator("Teng loyiha", "Alfa", "$1 200", "25.11"),            # dekabrda xuddi shu summa
        _qator("Farqli loyiha", "Beta", "$500", "18.11"),            # dekabrda boshqa summa
        _qator("Oy oxiri", "Beta", "$1 000", "30.11"),               # 30.11 muddatli
        _qator("Tolangan", "Alfa", "$0", "10.11", "✅ To'lov qilindi"),
        ref=date(2026, 11, 1), today=today))


def _dekabr(today):
    return ("Undiruv dekabr(2026)", _tab(
        _qator("Teng loyiha", "Alfa", "$1 200", "05.12"),
        _qator("Farqli loyiha", "Beta", "$2 300", "09.12"),
        _qator("Dekabr yangi", "Alfa", "$1 500", "02.12"),
        _qator("Dekabr kech", "Beta", "$800", "20.12"),
        ref=date(2026, 12, 1), today=today))


def _oktabr(today):
    return ("Undiruv oktabr(2026)", _tab(
        _qator("Oktabr qoldiq", "Alfa", "$700", "15.10"),
        ref=date(2026, 10, 1), today=today))


def _tabs(today, *oylar):
    yasovchi = {"oktyabr": _oktabr, "noyabr": _noyabr, "dekabr": _dekabr}
    return {(oy, 2026): yasovchi[oy](today) for oy in oylar}


# ------------------------------------------------------------ slotlar va aliaslar

def _cfg(monkeypatch, pmlar, kpi=("Alfa", "Beta")):
    """Soxta config: KPI sheet'lari (ID'siz — slot ID'ga bog'liq emas) + «undiruv_pmlar»."""
    sheets = [{"name": f"{n} PM KPI"} for n in kpi] + [{"name": "SMM proektlar", "pm_kpi": False}]
    monkeypatch.setattr(fetchmod, "load_full_config", lambda: {"sheets": sheets, "undiruv_pmlar": pmlar})


@pytest.fixture
def soxta_pmlar(monkeypatch):
    """KPI sheet'lari: Alfa, Beta; config «undiruv_pmlar»: Yangipm (alias «Yangip»)."""
    _cfg(monkeypatch, [{"nom": "Yangipm", "aliases": ["Yangip"]}])


def test_undiruv_pmlar_buzuq_yozuvlar_yiqitmaydi(monkeypatch):
    _cfg(monkeypatch, [{"nom": "Yangipm", "aliases": ["Yangip", "", "  "]}, "Ikkinchi", {"nom": ""}, 5,
                       None, {"nom": "Uchinchi", "aliases": "Uchinch"}, {"aliases": ["Yetim"]}])
    assert pp._undiruv_pmlar() == [("Yangipm", ["Yangip"]), ("Ikkinchi", []),
                                   ("Uchinchi", ["Uchinch"])]


@pytest.mark.parametrize("buzuq", [5, True, "Furqat", {"nom": "Yangipm", "aliases": ["Yangip"]}])
def test_undiruv_pmlar_royxat_bolmasa_soxta_slot_yoq(monkeypatch, buzuq):
    """«- » unutilsa mapping, satr yozilsa — harf/kalitlardan soxta slot yasalmasin, yiqilmasin."""
    _cfg(monkeypatch, buzuq)
    assert pp._undiruv_pmlar() == []
    assert pp.slots_from_config() == {"alfa": "Alfa", "beta": "Beta"}


def test_config_oqilmasa_yiqilmaydi(monkeypatch):
    def boom():
        raise OSError("disk")
    monkeypatch.setattr(fetchmod, "load_full_config", boom)
    assert pp.slots_from_config() == {} and pp._alias_map() == {}


def test_kpi_sheetsiz_pm_slot_oladi_va_id_kerak_emas(soxta_pmlar):
    assert pp.slots_from_config() == {"alfa": "Alfa", "beta": "Beta", "yangipm": "Yangipm"}


def test_alias_aniq_moslik_prefiks_emas(soxta_pmlar):
    am = pp._alias_map()
    assert pp.pm_slot("Yangip", am) == "yangipm"
    assert pp.pm_slot("YANGIPM", am) == "yangipm"
    assert pp.pm_slot("Yangipmjon", am) == "yangipmjon"     # yangi odam — jim qo'shilmaydi
    assert pp.pm_slot("Alf", am) == "alf"


def test_alias_boshqa_pmni_egallamaydi(monkeypatch):
    """Config xatosi: alias mavjud PM nomiga teng yoki ikki PM'da — qo'llanmaydi, ⚠️ bilan."""
    _cfg(monkeypatch, [{"nom": "Yangipm", "aliases": ["Alfa", "Yangip", "Yangipm"]},
                       {"nom": "Ikkinchi", "aliases": ["yangip"]}])
    am, xato = pp._alias_tahlil()
    assert am == {}
    assert pp.pm_slot("Alfa", am) == "alfa"                 # Alfa'ning qarzi Alfa'da qoladi
    assert len(xato) == 2 and any("«Alfa»" in x for x in xato) and any("bir nechta" in x for x in xato)


def test_apostrof_variantlari_bitta_slot():
    keys = {pp._slot_key(n) for n in ("Azizxo'ja", "Azizxoʻja", "Azizxoʼja", "Azizxo’ja", "AZIZXO`JA")}
    assert keys == {"azizxoja"}


def test_alias_va_asl_nom_bitta_xabarga(soxta_pmlar):
    by_slot, slot_n, _nd = pp._slotga_yig({"Yangip": ["a"], "Yangipm": ["b"]}, {"Yangip": ["c"]},
                                          pp.slots_from_config())
    assert list(by_slot) == ["yangipm"]
    nom, satrlar = by_slot["yangipm"]
    assert nom == "Yangipm" and sorted(satrlar) == ["a", "b"] and slot_n["yangipm"] == 3


def test_pm_set_alias_bilan(monkeypatch, tmp_path, soxta_pmlar):
    monkeypatch.setattr(pp, "CONTACTS_FILE", tmp_path / "pm_contacts.json")
    assert "✅" in pp.set_contact("yangip", "@soxta_kontakt")
    assert json.loads((tmp_path / "pm_contacts.json").read_text()) == {"yangipm": "@soxta_kontakt"}
    assert "Noma'lum slot" in pp.set_contact("yangipmjon", "@boshqa")


def test_status_aliasni_va_config_xatosini_korsatadi(monkeypatch):
    _cfg(monkeypatch, [{"nom": "Yangipm", "aliases": ["Yangip", "Alfa"]}])
    monkeypatch.setattr(pp, "load_contacts", lambda: {})
    monkeypatch.setattr(pp, "_load_state", lambda: {})
    monkeypatch.setattr(ub, "available", lambda: (True, ""))
    t = pp.status_text()
    assert "• Yangipm (sheet'da: Yangip): kontakt yo'q — /pm_set yangipm @username" in t
    assert "«Alfa» aliasi boshqa PM nomi bilan bir xil" in t


def test_haqiqiy_config_undiruv_pmlar_toza():
    """Repo'dagi config.yaml: har yozuv o'qiladi, alias xatosi yo'q (ismlarsiz tekshiruv)."""
    cfg = fetchmod.load_full_config()
    raw = cfg.get("undiruv_pmlar") or []
    assert isinstance(raw, list) and len(pp._undiruv_pmlar(cfg)) == len(raw)
    am, xato = pp._alias_tahlil(cfg)
    assert xato == [] and len(am) == sum(len(al) for _n, al in pp._undiruv_pmlar(cfg))


# ------------------------------------------------------------ userbot limiti

def test_userbot_limit_5_pmdan_katta_va_ortigi_xato_qaytadi(monkeypatch):
    assert ub.MAX_SENDS >= 5
    yuborilgan = []

    class SoxtaClient:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            pass

        def is_user_authorized(self):
            return True

        def send_message(self, entity, text, link_preview=False):
            yuborilgan.append(entity)

        def disconnect(self):
            pass

    sync = types.ModuleType("telethon.sync")
    sync.TelegramClient = SoxtaClient
    monkeypatch.setitem(sys.modules, "telethon.sync", sync)
    monkeypatch.setattr(ub, "available", lambda: (True, ""))
    monkeypatch.setattr(ub, "_make_session", lambda: "soxta")
    monkeypatch.setenv("TG_API_ID", "1")
    monkeypatch.setenv("TG_API_HASH", "soxta")
    items = [(f"s{i}", f"@soxta{i}", "matn") for i in range(ub.MAX_SENDS + 2)]
    res = ub.send_messages(items, sleep_range=(0, 0))
    assert len(yuborilgan) == ub.MAX_SENDS
    assert [s for s, _ok, _e in res] == [s for s, _t, _m in items]     # hech biri yo'qolmadi
    assert all(ok for _s, ok, _e in res[:ub.MAX_SENDS])
    assert [ok for _s, ok, _e in res[ub.MAX_SENDS:]] == [False, False]
    assert all("limit" in e for _s, _ok, e in res[ub.MAX_SENDS:])


# ------------------------------------------------------------ 1-dekabrdan o'tgan oy so'ralmaydi

def test_qoida_sanasi():
    assert u.otgan_oy_soraladimi(date(2026, 11, 1))
    assert not u.otgan_oy_soraladimi(date(2026, 12, 1))
    assert not u.otgan_oy_soraladimi(date(2027, 1, 1))


def test_1_dekabrda_noyabr_pmga_ketmaydi():
    kun = date(2026, 12, 1)
    v = _view(kun, _tabs(kun, "noyabr", "dekabr"))
    assert v["prev"]["soraladi"] is False and v["prev"]["real"] == []
    assert not v["prev"]["farqli"] and not v["prev"]["noaniq"]
    toxt = {r["loyiha"] for r in v["prev"]["toxtatildi"]}
    assert "Kochmagan qarz" in toxt and "Teng loyiha" not in toxt     # teng summa — ko'chgan
    per_pm, st = _push(kun, v)
    satrlar = _barcha_satrlar(per_pm)
    assert not any("qoldig'i" in s or "Kochmagan" in s for s in satrlar), satrlar
    assert st["overdue_carry_n"] == 0
    assert any("Dekabr yangi" in s for s in satrlar)                   # dekabr so'raladi
    izoh = " ".join(v["notes"])
    assert "ℹ️ 1-dekabrdan noyabr qoldiqlari PM'lardan so'ralmaydi" in izoh
    assert "Kochmagan qarz" in izoh


def test_oy_boshidan_keyin_ogohlantirish_shovqin_qilmaydi():
    kun = date(2026, 12, 7)
    v = _view(kun, _tabs(kun, "noyabr", "dekabr"))
    assert v["prev"]["real"] == []
    assert not any("qoldiqlari PM'lardan so'ralmaydi" in n for n in v["notes"])


def test_egaga_hisobotlar_ham_otgan_oyni_korsatmaydi():
    """C3: 💰 blok (summary) va PDF (report_data) ham PM push bilan bir xil to'plamdan."""
    kun = date(2026, 12, 3)
    v = _view(kun, _tabs(kun, "noyabr", "dekabr"))
    d = u.report_data(v["rows"], v["tab"], kun, view=v)
    assert not any(i.get("status") == "otgan" for p in d["pms"] for i in p.get("items", []))
    assert u.farqli_satrlari(v["prev"], v["oy"]) == []


def test_noyabrda_oktabr_qoldigi_eski_qoida_bilan_soraladi():
    kun = date(2026, 11, 2)
    v = _view(kun, _tabs(kun, "oktyabr", "noyabr"))
    assert v["prev"]["soraladi"] is True
    per_pm, st = _push(kun, v)
    assert any("Oktabr qoldiq (oktyabr qoldig'i)" in s for s in _barcha_satrlar(per_pm))
    assert st["overdue_carry_n"] == 1


def test_oy_oxirida_parallel_va_oldindan_ogohlantirish():
    kun = date(2026, 11, 29)
    v = _view(kun, _tabs(kun, "oktyabr", "noyabr", "dekabr"))
    per_pm, _st = _push(kun, v)
    satrlar = _barcha_satrlar(per_pm)
    assert any("Oy oxiri" in s for s in satrlar)                        # noyabr (30.11)
    assert any("Dekabr yangi (dekabr)" in s for s in satrlar)            # dekabr (02.12)
    assert not any("Dekabr kech" in s for s in satrlar)                  # 20.12 — hali erta
    ogoh = [n for n in v["notes"] if n.startswith("⚠️ 1-dekabrdan noyabr tabi PM'lardan so'ralmaydi")]
    assert len(ogoh) == 1, v["notes"]
    oldindan = {r["loyiha"] for r in v["keyingi"]["joriy_toxtaydi"]}
    assert {"Kochmagan qarz", "Farqli loyiha", "Oy oxiri"} <= oldindan
    assert "Teng loyiha" not in oldindan and "Tolangan" not in oldindan
    # Oldindan aytilgan ro'yxat 1-dekabrdagi «to'xtatildi» ni to'liq qamraydi (o'sha ma'lumotda)
    d1 = date(2026, 12, 1)
    v1 = _view(d1, {("noyabr", 2026): _noyabr(kun), ("dekabr", 2026): _dekabr(d1)})
    assert oldindan >= {r["loyiha"] for r in v1["prev"]["toxtatildi"]}


def test_navbatdagi_oylik_tolov_oldindan_aytiladi():
    """Noyabr invoysi to'lanmagan, dekabr tabida faqat keyingi oyning xuddi shu summasi (30.12):
    1-dekabr qoidasi (KN1) uni «ko'chgan» deb oladi — noyabr qarzi jim yo'qolmasin, oldindan ⚠️."""
    kun = date(2026, 11, 27)
    tabs = {("noyabr", 2026): ("Undiruv noyabr(2026)", _tab(
                _qator("Oylik mijoz", "Alfa", "$1 200", "30.11"), ref=date(2026, 11, 1), today=kun)),
            ("dekabr", 2026): ("Undiruv dekabr(2026)", _tab(
                _qator("Oylik mijoz", "Alfa", "$1 200", "30.12"), ref=date(2026, 12, 1), today=kun))}
    v = _view(kun, tabs)
    assert [r["loyiha"] for r in v["keyingi"]["joriy_toxtaydi"]] == ["Oylik mijoz"]
    assert any("Oylik mijoz (Alfa, $1 200)" in n and "keyingi oylik to'lov" in n for n in v["notes"])
    per_pm, _st = _push(kun, v)
    assert any("Oylik mijoz — qoldiq $1 200" in s for s in _barcha_satrlar(per_pm))   # hali so'raladi


def test_keyingi_tab_oqilmasa_tabini_oching_demaydi():
    kun = date(2026, 11, 28)
    orig = u._oy_oqi
    tabs = _tabs(kun, "noyabr")

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        if month == "dekabr":
            return None, [], "xato"
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi, u._VIEW_KESH = soxta, {}
    try:
        v = u.korinish(kun, day=kun.isoformat(), prefer_live=True, qlar=[])
    finally:
        u._oy_oqi = orig
    ogoh = [n for n in v["notes"] if n.startswith("⚠️ 1-dekabrdan noyabr tabi")]
    assert len(ogoh) == 1 and "o'qilmadi (xato)" in ogoh[0] and "tabini oching" not in ogoh[0], ogoh


def test_carry_toxtagan_oyda_qayta_soralmoqda_demaydi(monkeypatch):
    """P0-3: oy oxirida ko'chgan deb ko'rsatilgan qarz dekabr tabida yo'qolsa — egaga rost gap."""
    import undiruv_carry as carry
    kun = date(2026, 12, 3)
    prows = _tab(_qator("Kochgan qarz", "Alfa", "$900", "20.11"), ref=date(2026, 11, 1), today=kun)
    cur = _tab(_qator("Boshqa loyiha", "Alfa", "$500", "05.12"), ref=date(2026, 12, 1), today=kun)
    rec = {"versiya": carry.VERSIYA, "kun": "2026-11-30", "keyingi_tab": "Undiruv dekabr(2026)",
           "manba_tab": "Undiruv noyabr(2026)",
           "items": [{"loyiha": "Kochgan qarz", "pm": "Alfa", "turi": "aynan", "summa": 900,
                      "yangi_loyiha": "Kochgan qarz"}]}
    monkeypatch.setattr(carry, "royxat", lambda today, soraladi=True: (rec, []))
    for soraladi, kutilgan, yoq in ((True, "qayta so'ralmoqda", "PM'lardan so'ralmaydi"),
                                    (False, "PM'lardan so'ralmaydi", "qayta so'ralmoqda")):
        t1 = {"cur_rows": cur, "real": list(prows), "juft": {}, "farqli": [], "noaniq": [],
              "closed": [], "moved": []}
        out = carry.tekshir(t1, prows, "Undiruv dekabr(2026)", "noyabr", "dekabr", kun,
                            ptab="Undiruv noyabr(2026)", soraladi=soraladi)
        matn = " ".join(out["notes"])
        assert "Kochgan qarz (Alfa)" in matn and kutilgan in matn and yoq not in matn, matn


def test_qoidadan_oldingi_oy_oxirida_yangi_ogohlantirish_yoq():
    kun = date(2026, 10, 28)
    tabs = {("oktyabr", 2026): ("Undiruv oktabr(2026)", _tab(
        _qator("Oktabr ochiq", "Alfa", "$700", "30.10"), ref=date(2026, 10, 1), today=kun)),
        ("noyabr", 2026): ("Undiruv noyabr(2026)", _tab(
            _qator("Noyabr yangi", "Alfa", "$900", "01.11"), ref=date(2026, 11, 1), today=kun))}
    v = _view(kun, tabs)
    assert not any("tabi PM'lardan so'ralmaydi" in n for n in v["notes"]), v["notes"]
    assert v["keyingi"]["joriy_toxtaydi"] == []


def test_toxtagan_oyda_eskirgan_qaror_izohi_soralmoqda_demaydi():
    rows = _tab(_qator("Qaror loyiha", "Alfa", "$900", "20.11"), ref=date(2026, 11, 1),
                today=date(2026, 12, 2))
    q = [{"loyiha": "Qaror loyiha", "tab": "Undiruv noyabr(2026)", "qaror": "hisobdan_chiqarilsin",
          "qoldiq": 400}]
    _r, _ch, izoh = u.kechish_ajrat(rows, "Undiruv noyabr(2026)", q, "noyabr", soraladi=False)
    assert izoh and not any("so'ralmoqda" in i for i in izoh), izoh
    _r, _ch, izoh = u.kechish_ajrat(rows, "Undiruv noyabr(2026)", q, "noyabr")
    assert any("so'ralmoqda" in i for i in izoh)


# ------------------------------------------------------------ run_daily: uchidan-uchiga

def test_run_daily_alias_pm_yuboriladi_notanish_egaga(monkeypatch, soxta_pmlar):
    kun = date(2026, 12, 3)
    tabs = _tabs(kun, "noyabr", "dekabr")
    dek = tabs[("dekabr", 2026)]
    tabs[("dekabr", 2026)] = (dek[0], dek[1] + _tab(
        _qator("Yangi loyiha", "Yangip", "$1 500", "04.12"),
        _qator("Begona loyiha", "Notanish", "$700", "03.12"),
        ref=date(2026, 12, 1), today=kun))

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    monkeypatch.setattr(u, "_oy_oqi", soxta)
    monkeypatch.setattr(u, "qarorlar", lambda: [])
    monkeypatch.setattr(u, "qaror_xatolari", lambda: [])
    u._VIEW_KESH.clear()
    egaga, holat, ketdi = [], {}, []
    monkeypatch.setattr(pp, "_load_state", lambda: {})
    monkeypatch.setattr(pp, "_save_state", lambda d: holat.update(d))
    monkeypatch.setattr(pp, "load_contacts", lambda: {"alfa": "@soxta_alfa", "beta": "@soxta_beta",
                                                      "yangipm": "@soxta_yangi"})
    monkeypatch.setattr(pp, "send_owner", lambda t: egaga.append(t))
    monkeypatch.setattr(pp, "owner_pdf", lambda *a, **k: False)     # matn jamlamasi egaga ketsin

    def yubor(items):
        ketdi.extend(items)
        return [(slot, True, "") for slot, _to, _t in items]
    monkeypatch.setattr(ub, "send_messages", yubor)

    status, summary = pp.run_daily(today=kun)
    assert status == "sent"
    kimga = {to: t for _s, to, t in ketdi}
    assert set(kimga) == {"@soxta_alfa", "@soxta_yangi"}               # Beta'da ≤5 kunlik yo'q
    assert "• Beta: bugun eslatma yo'q" in summary
    assert "Yangi loyiha" in kimga["@soxta_yangi"]
    assert "Dekabr yangi" in kimga["@soxta_alfa"]
    assert not any("Kochmagan" in t or "qoldig'i" in t for t in kimga.values())
    assert "PM ro'yxatida yo'q ism: «Notanish» — 1 eslatma" in summary
    assert "kontakt sozlanmagan" not in summary                        # noto'g'ri /pm_set yo'li yo'q
    assert "• Yangipm (@soxta_yangi): 1 eslatma yuborildi ✅" in summary
    assert "ℹ️ 1-dekabrdan noyabr qoldiqlari PM'lardan so'ralmaydi" in summary
    tayyor = [m for m in egaga if m.startswith("📋 PM ro'yxatida yo'q ism uchun tayyor matn")]
    assert len(tayyor) == 1 and "«Notanish»:" in tayyor[0] and "Begona loyiha" in tayyor[0]
    assert holat["nomalum"] == ["Notanish"] and "notanish" not in holat["sent"]


def _e2e(monkeypatch, kun, qoshimcha, contacts):
    """run_daily / test_to_saved uchun soxta muhit: dekabr tabiga qo'shimcha qatorlar."""
    tabs = _tabs(kun, "noyabr", "dekabr")
    dek = tabs[("dekabr", 2026)]
    tabs[("dekabr", 2026)] = (dek[0], dek[1] + _tab(*qoshimcha, ref=date(2026, 12, 1), today=kun))

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    monkeypatch.setattr(u, "_oy_oqi", soxta)
    monkeypatch.setattr(u, "qarorlar", lambda: [])
    monkeypatch.setattr(u, "qaror_xatolari", lambda: [])
    u._VIEW_KESH.clear()
    egaga, holat, ketdi = [], {}, []
    monkeypatch.setattr(pp, "_load_state", lambda: {})
    monkeypatch.setattr(pp, "_save_state", lambda d: holat.update(d))
    monkeypatch.setattr(pp, "load_contacts", lambda: dict(contacts))
    monkeypatch.setattr(pp, "send_owner", lambda t: egaga.append(t))
    monkeypatch.setattr(pp, "owner_pdf", lambda *a, **k: False)

    def yubor(items):
        ketdi.extend(items)
        return [(slot, True, "") for slot, _to, _t in items]
    monkeypatch.setattr(ub, "send_messages", yubor)
    return egaga, holat, ketdi


def test_configda_yoq_lekin_kontakti_bor_pm_baribir_oladi(monkeypatch, soxta_pmlar):
    """Overlay/config'dan PM tushib qolsa ham (eski xulq) kontakt bo'lsa eslatma ketadi."""
    kun = date(2026, 12, 3)
    egaga, holat, ketdi = _e2e(monkeypatch, kun, [_qator("Gamma loyiha", "Gamma", "$600", "04.12")],
                               {"alfa": "@soxta_alfa", "gamma": "@soxta_gamma"})
    _st, summary = pp.run_daily(today=kun)
    assert any(to == "@soxta_gamma" and "Gamma loyiha" in t for _s, to, t in ketdi)
    assert "• Gamma (@soxta_gamma): 1 eslatma yuborildi ✅" in summary
    assert "PM ro'yxatida yo'q ism" not in summary and holat["nomalum"] == []


def test_alias_xatosi_jamlamada_korinadi(monkeypatch):
    _cfg(monkeypatch, [{"nom": "Yangipm", "aliases": ["Alfa"]}])
    kun = date(2026, 12, 3)
    _egaga, _holat, ketdi = _e2e(monkeypatch, kun, [], {"alfa": "@soxta_alfa"})
    _st, summary = pp.run_daily(today=kun)
    assert "⚠️ config «undiruv_pmlar»: «Alfa» aliasi boshqa PM nomi bilan bir xil" in summary
    assert {to for _s, to, _t in ketdi} == {"@soxta_alfa"}           # Alfa o'z xabarini oldi


def test_nomalum_ismlar_bitta_qisqartirilgan_xabarda(monkeypatch, soxta_pmlar):
    kun = date(2026, 12, 3)
    qatorlar = [_qator(f"Begona {i} " + "x" * 60, f"Notanish{i}", "$500", "04.12") for i in range(40)]
    egaga, holat, _ketdi = _e2e(monkeypatch, kun, qatorlar, {"alfa": "@soxta_alfa"})
    _st, summary = pp.run_daily(today=kun)
    tayyor = [m for m in egaga if m.startswith("📋 PM ro'yxatida yo'q ism uchun tayyor matn")]
    assert len(tayyor) == 1 and len(tayyor[0]) <= pp.NOMALUM_MAX and "qisqartirildi" in tayyor[0]
    assert len(holat["nomalum"]) == 40


def test_pm_push_test_haqiqiy_pushda_ketmaydiganini_belgilaydi(monkeypatch, soxta_pmlar):
    kun = date(2026, 12, 3)
    _egaga, _holat, ketdi = _e2e(monkeypatch, kun, [
        _qator("Yangi loyiha", "Yangip", "$1 500", "04.12"),
        _qator("Begona loyiha", "Notanish", "$700", "03.12")], {"alfa": "@soxta_alfa"})
    pp.test_to_saved(today=kun)
    sarlavha = {s: t.splitlines()[0] for s, to, t in ketdi}
    assert all(to == "me" for _s, to, _t in ketdi)
    assert sarlavha["alfa"] == "🧪 [SINOV — Alfa ko'radigan xabar]"
    assert "kontakt yo'q (/pm_set yangipm)" in sarlavha["yangipm"]
    assert "PM ro'yxatida yo'q" in sarlavha["notanish"]


def test_oldindan_royxat_1_sana_tasnifi_va_qarorga_tayanadi():
    """Sanasiz ko'chgan qator (1-sanada «ko'chgan») va hisobdan chiqarilgan qarz ro'yxatga kirmaydi."""
    kun = date(2026, 11, 28)
    tabs = {("noyabr", 2026): ("Undiruv noyabr(2026)", _tab(
                _qator("Sanasiz kochgan", "Alfa", "$2 500", "15.11"),
                _qator("Chiqarilgan", "Beta", "$400", "10.11"),
                _qator("Qolgan", "Beta", "$300", "12.11"), ref=date(2026, 11, 1), today=kun)),
            ("dekabr", 2026): ("Undiruv dekabr(2026)", _tab(
                _qator("Sanasiz kochgan", "Alfa", "$2 500", ""), ref=date(2026, 12, 1), today=kun))}
    qaror = [{"loyiha": "Chiqarilgan", "tab": "Undiruv noyabr(2026)", "qaror": "hisobdan_chiqarilsin",
              "qoldiq": 400, "sabab": "soxta"}]
    orig = u._oy_oqi

    def soxta(month, year, ref, today_, day, prefer_live, qat_iy, notes):
        t = tabs.get((month, year))
        return (t[0], [dict(r) for r in t[1]], "live") if t else (None, [], "none")
    u._oy_oqi, u._VIEW_KESH = soxta, {}
    try:
        v = u.korinish(kun, day=kun.isoformat(), prefer_live=True, qlar=qaror)
    finally:
        u._oy_oqi = orig
    assert [r["loyiha"] for r in v["keyingi"]["joriy_toxtaydi"]] == ["Qolgan"]
