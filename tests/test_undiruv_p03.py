"""AUDIT.md P0-3: oy oxiri ko'chirish ro'yxati (undiruv_carry) — Bosimov holati (30.09 → 12.10).

30.09 da bot egaga «🔁 … Bosimov shcool → Bosimov School ($2 500 → 18.10)» dedi, lekin bu qaror
saqlanmadi: 01.10 da sentabr qatori $1 500 bo'lgani uchun u yana «summa farqli» bo'lib, Zubair'dan
har kuni «sentyabr qoldig'i $1 500» so'raldi; 09.10 dan oktabr qatori bo'shab $1 000 izsiz yo'qoldi.

Qo'riqchilar:
  · oy oxiri report.json'dagi ro'yxat M+1 da BIR MARTA muzlatiladi (qayta ishga tushirish,
    retention uni o'zgartirmaydi); buzuq/yo'q manba — bugungi xulq (so'raladi);
  · ro'yxatdagi qarzning o'tgan oy qatori ochiq qolsa — PM'dan so'ralmaydi, egaga har kuni
    «⚠️ Ikki tabda dublikat»; har qanday shubha (PM boshqa, summa oshgan, hamkor yo'q yoki
    ikkita) — so'raladi;
  · ko'chirilgan joriy qatorda Summa+Undirildi+Lose+Aktive kamaysa — «$N izohsiz»;
  · 1–10 kunlar o'tgan oy tabi kecha↔bugun qatorma-qator;
  · o'tgan oy «⚖️ summa farqli» 09:00 💰 blokiga ham chiqadi (09:30 jamlamada bir marta);
  · UNDIRUV_CARRY_OFF=1 — hammasi 69a8de7 xulqiga qaytadi.

Tarmoq kerak emas: jonli o'qish o'chiriladi, korinish() tmp snapshot'lardan o'qiydi.
"""
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import diff as diffmod          # noqa: E402
import pm_push as pp            # noqa: E402
import undiruv as u             # noqa: E402
import undiruv_carry as carry   # noqa: E402

HDR = ["№", "Nomi", "Ma'sul shaxs", "LTV", "Summa", "Undirildi", "Aktive  Summary",
       "Lose summa", "Final data", "To'lov xolati", "Tasdiq"]
TABLAR = {"avgust": "Undiruv avgust(2026)", "sentyabr": "Undiruv sentabr(2026)",
          "oktyabr": "Undiruv oktabr(2026)", "dekabr": "Undiruv dekabr(2026)",
          "yanvar": "Undiruv yanvar(2027)"}
QAROR = [
    {"loyiha": "Stirka", "yangi_tab": "Undiruv oktabr(2026)", "qaror": "qoshilsin",
     "otgan_qoldiq": 364, "yangi_summa": 1350, "sabab": "ega 29.09"},
    {"loyiha": "Maestro kids", "yangi_tab": "Undiruv oktabr(2026)", "qaror": "yangi_toliq",
     "otgan_qoldiq": 2100, "yangi_summa": 2000, "sabab": "ega 29.09"},
    {"loyiha": "Baaztruck", "tab": "Undiruv avgust(2026)", "qaror": "hisobdan_chiqarilsin",
     "qoldiq": 433, "sabab": "ega 29.09: kerak emas"},
]


def q(nom, pm, summa="", und="", muddat="", holat="", aktiv="", lose=""):
    return ["1", nom, pm, "", summa, und, aktiv, lose, muddat, holat, ""]


# Haqiqiy 30.09 holatidan (hisobotlar/2026-09-30.md:36-37)
SENT_30 = [
    q("Kanzec", "Zubair", "$0", "$2 000", "06.09", "✅ To'lov qilindi"),
    q("Bazarway", "Islom", "$1 800", "", "21.09"),
    q("Stirka", "Zubair", "$364", "$986", "21.09"),
    q("Bosimov shcool", "Zubair", "$2 500", "", "18.09"),
    q("Maestro kids", "Zubair", "$2 100", "", "25.09"),
    q("Pruddy", "Zubair", "$4 500", "", "30.09"),
    q("Tanho", "Abdufattoh", "$2 417", "$2 083", "30.09"),
]
OKT_30 = [
    q("Kanzec", "Zubair", "$2 000", "", "05.10"),
    q("Stirkauz", "Zubair", "$1 714", "", "20.10"),
    q("Maestro kids", "Zubair", "$2 000", "", "05.10"),
    q("Bosimov School", "Zubair", "$2 500", "", "18.10"),
    q("Pruddy", "Zubair", "$4 500", "", "05.10"),
    q("Tanho", "Abdufattoh", "$2 417", "", "05.10"),
    q("Bazarway", "Islom", "$1 800", "", "03.10"),
]
AVG_30 = [q("Baaztruck", "Azizxo'ja", "$433", "", "05.08")]

OKT01, OKT02, OKT09 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 9)
SEP30 = date(2026, 9, 30)


def _almashtir(rows, nom, yangi):
    """rows nusxasi: `nom` qatori `yangi` bilan (None — o'chiriladi)."""
    out = []
    for r in rows:
        if r[1] == nom:
            if yangi is not None:
                out.append(yangi)
        else:
            out.append(r)
    return out


BOS_A = q("Bosimov shcool", "Zubair", "$1 500", "$1 000", "18.09")    # sentabrda $1 000 undirilgan
BOS_B = q("Bosimov shcool", "Zubair", "$1 500", "", "18.09")          # faqat Summa tahrirlangan
SENT_A = _almashtir(SENT_30, "Bosimov shcool", BOS_A)
SENT_B = _almashtir(SENT_30, "Bosimov shcool", BOS_B)
OKT_LOSE = _almashtir(OKT_30, "Bosimov School",
                      q("Bosimov School", "Zubair", "", "", "18.10", "Puli yo'q", lose="$1 500"))


@pytest.fixture
def muhit(monkeypatch, tmp_path):
    """Kalit yoqilgan; snapshot'lar va carry — tmp; jonli o'qish yo'q (snapshot fallback);
    ega qarorlari — repo faylidan emas, QAROR dan. Real sana — barcha test oylaridan keyin
    (aks holda royxat «simulyatsiya» deb muzlatmaydi)."""
    monkeypatch.delenv("UNDIRUV_CARRY_OFF", raising=False)
    monkeypatch.delenv("UNDIRUV_KESH", raising=False)
    monkeypatch.setattr(carry, "_bugun", lambda: date(2027, 2, 1))
    monkeypatch.setattr(diffmod, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(u, "fetch_live_month", lambda *a, **k: (None, []))
    monkeypatch.setattr(u, "qarorlar", lambda: list(QAROR))
    monkeypatch.setattr(u, "qaror_xatolari", lambda: [])
    u._VIEW_KESH.clear()
    return tmp_path


def _snap(day, **tablar):
    d = diffmod.SNAPSHOTS / day
    d.mkdir(parents=True, exist_ok=True)
    ranges = {f"'{TABLAR[oy]}'!A1:BZ1000": {"values": [[""] * 11, HDR] + [list(r) for r in rows]
                                                      + [["Jami"] + [""] * 10]}
              for oy, rows in tablar.items()}
    (d / "smm.json").write_text(json.dumps({"id": "smm", "pm_kpi": False, "ranges": ranges},
                                           ensure_ascii=False), encoding="utf-8")


def _report(day, und):
    d = diffmod.SNAPSHOTS / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps({"date": day, "undiruv": und}, ensure_ascii=False),
                                   encoding="utf-8")


def _eski_shakl(s):
    """P0-3 dan oldingi report.json (30.09 production): kitem'da cur_loyiha/manba_oy/eski/yangi yo'q."""
    s = json.loads(json.dumps(s, ensure_ascii=False))
    for tur in ("kochgan", "yopilgan"):
        for e in (s.get("keyingi") or {}).get(tur) or []:
            for key in ("cur_loyiha", "manba_oy", "eski", "yangi"):
                e.pop(key, None)
    return s


def _oy_oxiri(legacy=True, okt=OKT_30):
    """30.09: snapshot + o'sha kunning 09:00 report.json'i (production'dagi kabi)."""
    _snap("2026-09-30", avgust=AVG_30, sentyabr=SENT_30, oktyabr=okt)
    s = u.summary("2026-09-30", SEP30)
    _report("2026-09-30", _eski_shakl(s) if legacy else s)
    return s


def _kun(today, sent, okt=OKT_30):
    _snap(today.isoformat(), sentyabr=sent, oktyabr=okt)


def _view(today):
    u._VIEW_KESH.clear()
    return u.korinish(today, today.isoformat())


def _blok(today):
    u._VIEW_KESH.clear()
    return u.report_block(today.isoformat(), today)


def _push(today, prev_m="sentyabr"):
    v = _view(today)
    return pp.build_push(today, v["rows"], v["prev"]["rows"], prev_m, view=v)


def _pm(per_pm, pm):
    return "\n".join(per_pm.get(pm, []))


def _ochir(monkeypatch):
    monkeypatch.setenv("UNDIRUV_CARRY_OFF", "1")


def _carry_fayllar():
    return sorted(p.name for p in carry.CARRY_DIR.glob("*")) if carry.CARRY_DIR.exists() else []


DUB_0110 = ("⚠️ Ikki tabda dublikat: Bosimov shcool → Bosimov School (Zubair) — sentyabr $1 500 / "
            "oktyabr $2 500, 18.10 (30.09 da oktyabrga ko'chirilgan, sentyabr qoldig'i PM'dan "
            "so'ralmaydi; sentyabr tabida 30.09 dan beri: Summa $2 500 → $1 500, Undirildi +$1 000) — "
            "sentyabr tabidagi qatorni yoping")
ARXIV_0110 = ("⏰ Sentyabr qoldig'i (o'tgan oy tabidan, PM'dan so'ralmoqda): 1 ta, $1 500: "
              "Bosimov shcool (Zubair, $1 500, 18.09, 13 kun o'tdi)")


# ------------------------------------------------------------ T1: 30.09 o'zgarmaydi

def test_p03_3009_ozgarmas(muhit):
    s = _oy_oxiri(legacy=False)
    blok = _blok(SEP30)
    lines = blok.split("\n")
    assert ("📝 Ega qarori: Baaztruck (Azizxo'ja, avgust qoldig'i $433) hisobdan chiqarilgan — "
            "PM'dan so'ralmaydi") in lines, blok
    # hisobotlar/2026-09-30.md:37 — belgima-belgi
    assert ("🔁 Oktyabr tabiga ko'chirilgan (eski muddat bilan so'ralmaydi): 6 ta, $13 681: Bazarway "
            "($1 800 → 03.10), Stirka → Stirkauz ($364 → jami $1 714, 20.10 — ega qarori), Bosimov shcool "
            "→ Bosimov School ($2 500 → 18.10), Maestro kids ($2 100 → $2 000, 05.10 — ega qarori), Pruddy "
            "($4 500 → 05.10), Tanho ($2 417 → 05.10)") in lines, blok
    assert _carry_fayllar() == [], "30.09 da avgust uchun carry fayli yozilmasligi kerak"
    bos = next(i for i in s["keyingi"]["kochgan"] if i["loyiha"] == "Bosimov shcool")
    assert bos["cur_loyiha"] == "Bosimov School" and bos["manba_oy"] == "sentyabr"
    assert bos["eski"] == {"summa": 2500, "summa_raw": "$2 500", "undirildi": 0, "lose": 0, "aktiv": 0}
    assert bos["yangi"] == {"summa": 2500, "summa_raw": "$2 500", "undirildi": 0, "lose": 0, "aktiv": 0}
    json.dumps(s, ensure_ascii=False)                       # report.json'ga yoziladi


# ------------------------------------------------------------ T2/T3: 01.10 dublikat

def test_p03_0110_dublikat_tolov(muhit):
    _oy_oxiri()
    _kun(OKT01, SENT_A)
    blok = _blok(OKT01)
    assert DUB_0110 in blok.split("\n"), blok
    assert "⏰ Sentyabr qoldig'i: 0 ta — PM'dan so'ralmaydi (1 ta, $1 500 ikki tabda dublikat, ⚠️ yuqorida)" in blok
    assert "so'ralmoqda" not in blok and ARXIV_0110 not in blok, blok
    assert "Muddati o'tgan yoki yaqin qolgan undirilmagan loyiha yo'q ✅" not in blok
    per_pm, st = _push(OKT01)
    assert "Bosimov" not in _pm(per_pm, "Zubair") and st["overdue_carry_n"] == 0
    assert st["farqli"] == [] and st["noaniq"] == []
    rec = json.loads((carry.CARRY_DIR / "2026-09.json").read_text(encoding="utf-8"))
    assert rec["baza"] == "snapshot:2026-09-30" and rec["kun"] == "2026-09-30"
    assert rec["keyingi_tab"] == "Undiruv oktabr(2026)" and len(rec["items"]) == 6
    bos = next(e for e in rec["items"] if e["loyiha"] == "Bosimov shcool")
    assert bos["yangi_loyiha"] == "Bosimov School" and bos["eski"]["summa"] == 2500
    # ega PDF'i (09:30) ham so'ramaydi, ⚠️ satri esa bor
    v = _view(OKT01)
    d = u.report_data(v["rows"], v["tab"], OKT01, view=v)
    assert d["otgan"] is None and DUB_0110 in d["notes"]
    # kunlik PDF shabloni: 0 ta satri, «✅ yo'q» yo'q
    import render_pdf
    s = u.summary("2026-10-01", OKT01)
    html = render_pdf.build_html({"date": "2026-10-01", "totals": {}, "pms": [], "trend": [], "undiruv": s},
                                 logo_uri="")
    assert "ikki tabda dublikat, ⚠️ yuqorida" in html and "Ikki tabda dublikat: Bosimov shcool" in html
    assert "undirilmagan loyiha yo" not in html


def test_p03_0110_summa_tahrir(muhit):
    _oy_oxiri()
    _kun(OKT01, SENT_B)
    blok = _blok(OKT01)
    dub = [x for x in blok.split("\n") if x.startswith("⚠️ Ikki tabda dublikat: Bosimov shcool")]
    assert dub and "Summa $2 500 → $1 500, $1 000 izohsiz" in dub[0], blok
    assert "so'ralmoqda" not in blok


# ------------------------------------------------------------ T4/T5: 09.10 izohsiz

def test_p03_0910_izohsiz(muhit):
    _oy_oxiri()
    _kun(OKT09, SENT_B, OKT_LOSE)
    blok = _blok(OKT09)
    assert ("⚠️ Bosimov School (Zubair, oktyabr): Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz "
            "(30.09 dan beri) — oktyabr qatorida Undirildi yoki Lose'ga yozing") in blok.split("\n"), blok
    assert "Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz" in blok       # AUDIT substring
    assert "sentyabr $1 500 / oktyabr bo'sh, Lose $1 500" in blok
    assert "⏰ Sentyabr qoldig'i: 0 ta" in blok
    assert "$1 500: Bosimov shcool (Zubair, $1 500, 18.09, 21 kun o'tdi)" not in blok
    per_pm, _st = _push(OKT09)
    assert "Bosimov" not in _pm(per_pm, "Zubair")
    v = _view(OKT09)
    assert v["prev"]["izohsiz"] == [{"loyiha": "Bosimov School", "pm": "Zubair", "summa": 1000}]


def test_p03_0910_sentyabrda_izohlangan(muhit):
    _oy_oxiri()
    _kun(OKT09, SENT_A, OKT_LOSE)
    blok = _blok(OKT09)
    assert ("ℹ️ Bosimov School (Zubair, oktyabr): Summa $2 500 → bo'sh, Lose +$1 500 (30.09 dan beri); "
            "qolgan $1 000 sentyabr tabida yozilgan (Undirildi +$1 000)") in blok.split("\n"), blok
    assert "$1 000 izohsiz" not in blok
    okt11 = date(2026, 10, 11)
    _kun(okt11, SENT_A, OKT_LOSE)
    blok = _blok(okt11)
    assert "sentyabr tabida yozilgan" not in blok and "$1 000 izohsiz" not in blok
    assert "⚠️ Ikki tabda dublikat: Bosimov shcool → Bosimov School (Zubair)" in blok


# ------------------------------------------------------------ T6/T7: ro'yxatda yo'q qarz so'raladi

def test_p03_carryda_yoq(muhit):
    _oy_oxiri()
    _kun(OKT01, SENT_A + [q("Kechikkan", "Azizxo'ja", "$433", "", "20.09")])
    blok = _blok(OKT01)
    assert ("⏰ Sentyabr qoldig'i (o'tgan oy tabidan, PM'dan so'ralmoqda): 1 ta, $433: Kechikkan "
            "(Azizxo'ja, $433, 20.09, 11 kun o'tdi)") in blok.split("\n"), blok
    per_pm, _st = _push(OKT01)
    assert "🔴 MUDDAT O'TDI (11 kun): Kechikkan (sentyabr qoldig'i) — qoldiq $433" in _pm(per_pm, "Azizxo'ja")
    assert "Bosimov" not in _pm(per_pm, "Zubair")


def _jamlama(monkeypatch, today):
    import userbot_sender
    for n, f in (("_load_state", lambda: {}), ("_save_state", lambda d: None),
                 ("load_contacts", lambda: {}), ("slots_from_config", lambda: {"zubair": "Zubair"}),
                 ("send_owner", lambda t: None), ("owner_pdf", lambda *a, **k: True)):
        monkeypatch.setattr(pp, n, f)
    monkeypatch.setattr(userbot_sender, "available", lambda: (True, ""))
    u._VIEW_KESH.clear()
    return pp.run_daily(today=today)[1]


def test_p03_0209_baaztruck(muhit, monkeypatch):
    """02.09 qayta ijrosi (avgust oxirida report.json yo'q — look-ahead hali chiqmagan edi):
    💰 blok va 09:30 ega jamlamasi kalit o'chiq holat bilan BAYTMA-BAYT bir xil."""
    sep02 = date(2026, 9, 2)
    avg = [q("Baaztruck", "Azizxo'ja", "$433", "", "05.08"), q("Geely", "Zubair", "$0", "$2 950", "05.08",
                                                             "✅ To'lov qilindi")]
    sent = [q("Rasulov", "Islom", "$2 200", "", "03.09"), q("Geely", "Zubair", "$2 950", "", "05.09"),
            q("Baaztruck", "Azizxo'ja", "$433", "", "05.09"), q("Kanzec", "Zubair", "$1 800", "", "06.09")]
    for day in ("2026-09-01", "2026-09-02"):                      # avgust tabi o'zgarmagan
        _snap(day, avgust=avg, sentyabr=sent)
    blok_on, jam_on = _blok(sep02), _jamlama(monkeypatch, sep02)
    assert _carry_fayllar() == [], "manba yo'q — hech narsa muzlatilmaydi"
    _ochir(monkeypatch)
    blok_off, jam_off = _blok(sep02), _jamlama(monkeypatch, sep02)
    assert blok_on == blok_off, (blok_on, blok_off)
    assert jam_on == jam_off, (jam_on, jam_off)
    soon = next(x for x in blok_on.split("\n") if x.startswith("🔜 Muddati ≤5 kun: "))
    assert "Baaztruck (Azizxo'ja, $433, 05.09)" in soon, blok_on


# ------------------------------------------------------------ T8/T9/T10: manba qoidalari

def test_p03_eng_oxirgi_kun(muhit):
    s = _eski_shakl(_oy_oxiri())
    _report("2026-09-26", s)                                       # 26.09: Bosimov ko'chgan
    s30 = json.loads(json.dumps(s))
    s30["keyingi"]["kochgan"] = [i for i in s30["keyingi"]["kochgan"] if i["loyiha"] != "Bosimov shcool"]
    _report("2026-09-30", s30)                                     # 30.09 (oxirgi): Bosimov yo'q
    _kun(OKT01, SENT_A)
    blok = _blok(OKT01)
    assert "PM'dan so'ralmoqda): 1 ta, $1 500: Bosimov shcool (Zubair, $1 500, 18.09, 13 kun o'tdi)" in blok
    assert "Ikki tabda dublikat" not in blok
    rec = json.loads((carry.CARRY_DIR / "2026-09.json").read_text(encoding="utf-8"))
    assert rec["kun"] == "2026-09-30" and len(rec["items"]) == 5


def test_p03_buzuq_manba(muhit, monkeypatch):
    s = _eski_shakl(_oy_oxiri())
    _report("2026-09-29", s)
    (diffmod.SNAPSHOTS / "2026-09-30" / "report.json").write_text("{broken", encoding="utf-8")
    _kun(OKT01, SENT_A)
    blok = _blok(OKT01)
    assert ("⚠️ 30.09 report.json o'qilmadi (JSONDecodeError) — oy oxiri ko'chirish ro'yxati "
            "tekshirilmadi, sentyabr qoldiqlari odatdagidek so'ralmoqda") in blok.split("\n"), blok
    assert "Bosimov shcool (Zubair, $1 500, 18.09, 13 kun o'tdi)" in blok          # 29.09 ga tushmadi
    assert "Ikki tabda dublikat" not in blok and _carry_fayllar() == []
    # 25–30.09 da report.json umuman yo'q — carry qismi hech narsa qo'shmaydi, fayl yo'q
    for d in ("2026-09-29", "2026-09-30"):
        (diffmod.SNAPSHOTS / d / "report.json").unlink(missing_ok=True)
    blok_on = _blok(OKT01)
    v_on = _view(OKT01)
    assert _carry_fayllar() == []
    _ochir(monkeypatch)
    blok_off = _blok(OKT01)
    v_off = _view(OKT01)
    assert ARXIV_0110 in blok_off.split("\n")
    # P0-3 2/3-qismlari (o'tgan tab kuzatuvi ℹ️, ⚖️ farqli) — manbadan qat'i nazar; qolgani bir xil
    qosh = ("ℹ️ Sentyabr tabi", "⚠️ Sentyabr tabi", "⚖️ Summa farqli", "⚠️ Moslik noaniq")
    assert [x for x in blok_on.split("\n") if not x.startswith(qosh)] == blok_off.split("\n")
    assert v_on["notes"] == v_off["notes"]
    assert [r["loyiha"] for r in v_on["prev"]["real"]] == [r["loyiha"] for r in v_off["prev"]["real"]]


def test_p03_muzlatilgan(muhit):
    _oy_oxiri()
    _kun(OKT01, SENT_B)
    _view(OKT01)                                                    # 01.10: muzlatildi
    assert _carry_fayllar() == ["2026-09.json"]
    shutil.rmtree(diffmod.SNAPSHOTS / "2026-09-30")                 # retention (31.10) yoki qayta ishga tushirish
    _kun(OKT09, SENT_B, OKT_LOSE)
    blok = _blok(OKT09)
    assert "⚠️ Ikki tabda dublikat: Bosimov shcool → Bosimov School (Zubair)" in blok, blok
    assert "Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz (30.09 dan beri)" in blok
    # buzuq muzlatilgan fayl — qayta yozilmaydi, egaga ⚠️, qarz so'raladi
    (carry.CARRY_DIR / "2026-09.json").write_text("{broken", encoding="utf-8")
    blok = _blok(OKT09)
    assert ("⚠️ undiruv_carry/2026-09.json buzilgan (JSONDecodeError) — oy oxiri ko'chirish ro'yxati "
            "tekshirilmadi, sentyabr qoldiqlari odatdagidek so'ralmoqda (faylni o'chiring — 30.09 "
            "report.json'dan qayta tiklanadi)") in blok.split("\n"), blok
    assert "PM'dan so'ralmoqda): 1 ta, $1 500: Bosimov shcool" in blok
    assert (carry.CARRY_DIR / "2026-09.json").read_text(encoding="utf-8") == "{broken"


# ------------------------------------------------------------ T11/T12: qo'riqchilar

def test_p03_hamkor_yoq(muhit):
    _oy_oxiri()
    _kun(OKT01, SENT_A, _almashtir(OKT_30, "Bosimov School", None))
    blok = _blok(OKT01)
    assert ("⚠️ Bosimov shcool (Zubair): 30.09 da oktyabr tabiga «Bosimov School» bo'lib ko'chirilgan "
            "edi, endi u yerda topilmadi — sentyabr qoldig'i $1 500 qayta so'ralmoqda") in blok.split("\n"), blok
    per_pm, _st = _push(OKT01)
    assert "🔴 MUDDAT O'TDI (13 kun): Bosimov shcool (sentyabr qoldig'i) — qoldiq $1 500" in _pm(per_pm, "Zubair")


@pytest.mark.parametrize("sent,okt,kutil", [
    # sentabr qoldig'i L kunidagidan OSHGAN ($3 000 > $2 500) — boshqa qarz bo'lishi mumkin
    (_almashtir(SENT_30, "Bosimov shcool", q("Bosimov shcool", "Zubair", "$3 000", "", "18.09")), OKT_30,
     "Bosimov shcool (Zubair, $3 000, 18.09"),
    # sentabr qatorining PM'i boshqa — yozuvdagi qator emas
    (_almashtir(SENT_30, "Bosimov shcool", q("Bosimov shcool", "Islom", "$1 500", "", "18.09")), OKT_30,
     "Bosimov shcool (Islom, $1 500, 18.09"),
    # oktabrda shu PM'ning ikkinchi «Bosimov School» qatori — moslik noaniq
    (SENT_A, OKT_30 + [q("Bosimov School", "Zubair", "$500", "", "25.10")],
     "Bosimov shcool (Zubair, $1 500, 18.09"),
])
def test_p03_qoriqchilar(muhit, sent, okt, kutil):
    _oy_oxiri()
    _kun(OKT01, sent, okt)
    blok = _blok(OKT01)
    assert "Ikki tabda dublikat" not in blok, blok
    assert "PM'dan so'ralmoqda): 1 ta" in blok and kutil in blok, blok
    per_pm, st = _push(OKT01)
    assert st["overdue_carry_n"] == 1


def test_p03_1310_kontrfaktual(muhit):
    """Oktabr qatori $2 500 qolsa (write-off bo'lmasa) 13.10 dan Zubair $4 000 emas, $2 500 so'raladi."""
    _oy_oxiri()
    okt13 = date(2026, 10, 13)
    _kun(okt13, SENT_A)
    per_pm, _st = _push(okt13)
    z = _pm(per_pm, "Zubair")
    assert "⏳ Undiruv: Bosimov School — qoldiq $2 500, muddat 18.10 (5 kun qoldi)" in z, z
    assert "sentyabr qoldig'i" not in z, z


# ------------------------------------------------------------ T14: Tanho $917 (AUDIT P0-5 bilan kesishadi)

def test_p03_tanho_917(muhit):
    _oy_oxiri()
    okt03 = date(2026, 10, 3)
    okt = _almashtir(OKT_30, "Tanho", q("Tanho", "Abdufattoh", "", "", "05.10", aktiv="$1 500"))
    _kun(okt03, SENT_30, okt)
    blok = _blok(okt03)
    assert ("⚠️ Tanho (Abdufattoh, oktyabr): Summa $2 417 → bo'sh, Aktive +$1 500, $917 izohsiz "
            "(30.09 dan beri) — oktyabr qatorida Undirildi yoki Lose'ga yozing") in blok.split("\n"), blok
    # sentabr tabida Tanho yopilgan (Undirildi +$2 417) VA oktabrda Aktive $1 500 — $3 917 / $2 417
    # qarz: ikki tabda yozilgan, $917 hali izohsiz (≥ qoidasi uni ℹ️ deb yashirardi)
    sent = _almashtir(SENT_30, "Tanho", q("Tanho", "Abdufattoh", "", "$4 500", "30.09"))
    _kun(okt03, sent, okt)
    blok = _blok(okt03)
    assert ("⚠️ Tanho (Abdufattoh, oktyabr): Summa $2 417 → bo'sh, Aktive +$1 500, $917 izohsiz (30.09 dan "
            "beri); sentyabr tabida ham Undirildi +$2 417 — bir qarz ikki tabda yozilgan, ikkalasini "
            "solishtiring") in blok.split("\n"), blok
    assert "sentyabr tabida yozilgan" not in blok
    # sentabrda AYNAN yetishmagan $917 yozilgan — izohlangan (ℹ️)
    sent = _almashtir(SENT_30, "Tanho", q("Tanho", "Abdufattoh", "$1 500", "$3 000", "30.09"))
    _kun(okt03, sent, okt)
    blok = _blok(okt03)
    assert "$917 izohsiz" not in blok, blok
    assert ("ℹ️ Tanho (Abdufattoh, oktyabr): Summa $2 417 → bo'sh, Aktive +$1 500 (30.09 dan beri); "
            "qolgan $917 sentyabr tabida yozilgan (Undirildi +$917)") in blok.split("\n"), blok


# ------------------------------------------------------------ T15: kill switch

@pytest.mark.parametrize("today,sent,okt", [(OKT01, SENT_A, OKT_30), (OKT01, SENT_B, OKT_30),
                                           (OKT09, SENT_B, OKT_LOSE), (OKT09, SENT_A, OKT_LOSE)])
def test_p03_kalit(muhit, monkeypatch, today, sent, okt):
    """UNDIRUV_CARRY_OFF=1 — 69a8de7 xulqi: Bosimov so'raladi (arxiv satri), yangi satr yo'q, fayl yo'q."""
    _ochir(monkeypatch)
    _oy_oxiri()
    _kun(today, sent, okt)
    blok = _blok(today)
    kun = (today - date(2026, 9, 18)).days
    assert (f"⏰ Sentyabr qoldig'i (o'tgan oy tabidan, PM'dan so'ralmoqda): 1 ta, $1 500: Bosimov shcool "
            f"(Zubair, $1 500, 18.09, {kun} kun o'tdi)") in blok.split("\n"), blok
    for yangi in ("dublikat", "izohsiz", "Sentyabr tabi", "⚖️", "Moslik noaniq", "report.json"):
        assert yangi not in blok, (yangi, blok)
    assert _carry_fayllar() == []
    v = _view(today)
    assert v["prev"]["dublikat"] == [] and "Bosimov shcool" in [r["loyiha"] for r in v["prev"]["real"]]
    per_pm, _st = _push(today)
    assert f"🔴 MUDDAT O'TDI ({kun} kun): Bosimov shcool (sentyabr qoldig'i) — qoldiq $1 500" in _pm(per_pm, "Zubair")


# ------------------------------------------------------------ T16: o'tgan oy tabi kecha↔bugun (1–10 kun)

def test_p03_otgan_tab(muhit):
    _oy_oxiri()
    ekstra_01 = [q("Mb city", "Abdufattoh", "", "$1 600", "03.09", "✅ To'lov qilindi"),
                 q("Orto life", "Islom", "$900", "", "28.09")]
    _kun(OKT01, SENT_A + ekstra_01)
    sent02 = _almashtir(SENT_A, "Bazarway", q("Bazarway", "Islom", "", "", "21.09"))
    sent02 = _almashtir(sent02, "Tanho", q("Tanho", "Abdufattoh", "", "$4 500", "30.09"))
    sent02 = _almashtir(sent02, "Bosimov shcool", q("Bosimov shcool", "Zubair", "$1 400", "$1 000", "18.09"))
    sent02 += [q("Mb city", "Abdufattoh", "", "", "03.09", "✅ To'lov qilindi")]      # Orto life o'chirildi
    _kun(OKT02, sent02)
    lines = _blok(OKT02).split("\n")
    assert ("ℹ️ Sentyabr tabi o'zgardi (01.10 → 02.10): Bazarway (Islom): Summa $1 800 → bo'sh — "
            "ko'chirilgan qarz yopildi; Tanho (Abdufattoh): Summa $2 417 → bo'sh, Undirildi +$2 417") in lines, lines
    assert "⚠️ Sentyabr tabi (01.10 → 02.10): Mb city (Abdufattoh): Undirildi −$1 600, $1 600 izohsiz" in lines
    assert "⚠️ Sentyabr tabi (01.10 → 02.10): qator o'chirilgan — Orto life (Islom) Summa $900" in lines
    assert not [x for x in lines if "Sentyabr tabi" in x and "Bosimov" in x], "dublikat satri takrorlandi"
    assert any(x.startswith("⚠️ Ikki tabda dublikat: Bosimov shcool") for x in lines)
    # 09:30 push / dashboard yo'li (view.notes) — qo'shimcha snapshot o'qimaydi
    assert not [n for n in _view(OKT02)["notes"] if "Sentyabr tabi" in n]
    # 11-kundan kuzatilmaydi
    okt10, okt11 = date(2026, 10, 10), date(2026, 10, 11)
    _kun(okt10, SENT_A + ekstra_01)
    _kun(okt11, sent02)
    assert not [x for x in _blok(okt11).split("\n") if "Sentyabr tabi" in x]


# ------------------------------------------------------------ T17: ⚖️ farqli 💰 blokida

def test_p03_farqli_kpi_blokida(muhit, monkeypatch):
    _oy_oxiri()
    _kun(OKT01, SENT_A + [q("Mixmobile", "Zubair", "$1 200", "", "25.09")],
         OKT_30 + [q("Mixmobile", "Zubair", "$1 500", "", "05.10")])
    satr = ("⚖️ Summa farqli — ko'chirilgan deb OLINMADI, o'tgan qoldiq ham so'ralmoqda (qaror kerak): "
            "Mixmobile (Zubair, sentyabr → oktyabr: $1 200 → $1 500)")
    blok = _blok(OKT01)
    assert satr in blok.split("\n"), blok
    assert "Mixmobile (Zubair, $1 200, 25.09, 6 kun o'tdi)" in blok              # so'ralaveradi
    jam = _jamlama(monkeypatch, OKT01)
    assert jam.count("⚖️ Summa farqli") == 1 and satr in jam, jam
    assert jam.count("Ikki tabda dublikat: Bosimov shcool") == 1, jam


# ------------------------------------------------------------ qo'shimcha: S6/S7, yordamchilar

def test_p03_xato_eski_xulq(muhit, monkeypatch):
    """tekshir() yiqilsa — korinish yiqilmaydi, qarz so'raladi, egaga ⚠️ (S6)."""
    _oy_oxiri()
    _kun(OKT01, SENT_A)

    def yiqil(*a, **k):
        raise RuntimeError("sinov")
    monkeypatch.setattr(carry, "tekshir", yiqil)
    blok = _blok(OKT01)
    assert ("⚠️ Oy oxiri ko'chirish ro'yxati tekshirilmadi (RuntimeError) — sentyabr qoldiqlari odatdagidek "
            "so'ralmoqda") in blok.split("\n"), blok
    assert ARXIV_0110 in blok.split("\n")


def test_p03_oy_oxiri_kuzatuvdan_tushadi(muhit):
    """26–31.10 (look-ahead): dublikat satri 1-noyabrdan sentabr tabi kuzatilmasligini aytadi (S7);
    «tushadi» ogohlantirishi uni takrorlamaydi."""
    _oy_oxiri()
    okt27 = date(2026, 10, 27)
    _kun(okt27, SENT_A)
    lines = _blok(okt27).split("\n")
    dub = [x for x in lines if x.startswith("⚠️ Ikki tabda dublikat: Bosimov shcool")]
    assert dub and dub[0].endswith(" — sentyabr tabidagi qatorni yoping — 1-noyabrdan bot sentyabr tabini "
                                   "kuzatmaydi"), lines
    assert not [x for x in lines if "1-noyabrdan bot sentyabr qoldig'ini tekshirmaydi" in x], lines


def test_p03_yordamchilar(tmp_path):
    assert carry._matndan_nom({"loyiha": "Bosimov shcool",
                               "matn": "Bosimov shcool → Bosimov School ($2 500 → 18.10)"}) == "Bosimov School"
    assert carry._matndan_nom({"loyiha": "Geely (Uz)", "matn": "Geely (Uz) → Geely Uz (sentyabr qoldig'i, "
                               "$2 950, oktyabr tabida to'langan/ketgan deb yozilgan)"}) == "Geely Uz"
    assert carry._matndan_nom({"loyiha": "Pruddy", "matn": "Pruddy ($4 500 → 05.10)"}) == "Pruddy"
    f = carry.qator_farqi({"summa": 2500, "summa_raw": "$2 500", "undirildi": 0, "lose": 0, "aktiv": 0},
                          {"summa": 0, "summa_raw": "", "undirildi": 0, "lose": 1500, "aktiv": 0})
    assert f == {"qismlar": ["Summa $2 500 → bo'sh", "Lose +$1 500"], "izohsiz": 1000}
    # qaror qo'shgan (jadvalda yo'q) qoldiq sheet qiymatiga kirmaydi
    r = {"qoldiq": 1714, "qoldiq_raw": "$1 350", "undirildi": 0, "lose": 0, "aktiv": 0,
         "qoshimcha": {"summa": 364, "jadvalda": False}}
    assert carry.qator_qiymat(r)["summa"] == 1350
    # muzlatish — faqat fayl yo'q bo'lsa (birinchi yozgan yutadi), yarim fayl qolmaydi
    p = tmp_path / "x" / "2026-09.json"
    carry._atomik_yoz(p, {"a": 1})
    carry._atomik_yoz(p, {"a": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert [x.name for x in p.parent.iterdir()] == ["2026-09.json"]


def test_p03_yangi_shakl_yil_almashuvi(muhit):
    """31.12 dan boshlab report.json o'zi to'liq (eski/yangi qiymatlar bilan) — snapshot o'qilmaydi;
    dekabr → yanvar(2027) yil almashuvida fayl nomi va tablar to'g'ri."""
    dek31, yan05 = date(2026, 12, 31), date(2027, 1, 5)
    _snap("2026-12-31", dekabr=[q("Bosimov shcool", "Zubair", "$2 500", "", "18.12")],
          yanvar=[q("Bosimov School", "Zubair", "$2 500", "", "18.01")])
    _report("2026-12-31", u.summary("2026-12-31", dek31))
    _snap("2027-01-05", dekabr=[q("Bosimov shcool", "Zubair", "$1 500", "$1 000", "18.12")],
          yanvar=[q("Bosimov School", "Zubair", "$2 500", "", "18.01")])
    (diffmod.SNAPSHOTS / "2026-12-31" / "smm.json").unlink()      # asos faqat report.json'dan
    blok = _blok(yan05)
    assert ("⚠️ Ikki tabda dublikat: Bosimov shcool → Bosimov School (Zubair) — dekabr $1 500 / yanvar "
            "$2 500, 18.01 (31.12 da yanvarga ko'chirilgan, dekabr qoldig'i PM'dan so'ralmaydi; dekabr "
            "tabida 31.12 dan beri: Summa $2 500 → $1 500, Undirildi +$1 000) — dekabr tabidagi qatorni "
            "yoping") in blok.split("\n"), blok
    rec = json.loads((carry.CARRY_DIR / "2026-12.json").read_text(encoding="utf-8"))
    assert "baza" not in rec and rec["items"][0]["legacy"] is False and rec["items"][0]["eski"]["summa"] == 2500
    per_pm, st = _push(yan05, "dekabr")
    assert "Bosimov shcool" not in _pm(per_pm, "Zubair") and st["overdue_carry_n"] == 0


# ------------------------------------------------------------ review: eskirgan ega qarori dublikat emas

# 30.09 da oktabr Stirkauz $1 350 — «qoshilsin» $364 ni bot xotirada qo'shgan (qaror_qoshildi):
# oktabr qatori sentabr qarzini SHEET'da saqlamaydi
OKT_QOSH = _almashtir(OKT_30, "Stirkauz", q("Stirkauz", "Zubair", "$1 350", "", "20.10"))


@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("sent,okt,qoldiq", [
    (SENT_A, _almashtir(OKT_QOSH, "Stirkauz", q("Stirkauz", "Zubair", "$1 400", "", "20.10")), "$364"),
    (_almashtir(SENT_A, "Stirka", q("Stirka", "Zubair", "$164", "$1 186", "21.09")), OKT_QOSH, "$164"),
    (SENT_A, _almashtir(OKT_QOSH, "Stirkauz", q("Stirkauz", "Zubair", "", "", "20.10", "Mijoz ketdi",
                                                lose="$1 350")), "$364"),
], ids=["narx", "sent_qisman", "ketdi"])
def test_p03_eskirgan_qaror_qoshildi(muhit, legacy, sent, okt, qoldiq):
    """Qaror eskirsa undiruv.py qoidasi («📝 … eskirgan», o'tgan qoldiq so'raladi) yutadi —
    «⚠️ Ikki tabda dublikat … yoping» qarzni hisobdan chiqartirardi ($364 oktabr qatorida yo'q)."""
    _oy_oxiri(legacy, okt=OKT_QOSH)
    _kun(OKT01, sent, okt)
    blok = _blok(OKT01)
    assert "Ikki tabda dublikat: Stirka" not in blok, blok
    per_pm, _st = _push(OKT01)
    assert f"🔴 MUDDAT O'TDI (10 kun): Stirka (sentyabr qoldig'i) — qoldiq {qoldiq}" in _pm(per_pm, "Zubair")
    assert u._name_key("Stirka") not in _view(OKT01)["prev"]["carry_kochgan"]


def test_p03_eskirgan_qaror_yangi_toliq(muhit):
    """Maestro kids «yangi_toliq» ($2 100 → $2 000) eskirgan (oktabr $2 500) — sentabr $2 100 so'raladi."""
    _oy_oxiri(legacy=False)
    _kun(OKT01, SENT_A, _almashtir(OKT_30, "Maestro kids", q("Maestro kids", "Zubair", "$2 500", "", "05.10")))
    blok = _blok(OKT01)
    assert "Ikki tabda dublikat: Maestro" not in blok and "Maestro kids: ega qarori eskirgan" in blok, blok
    per_pm, _st = _push(OKT01)
    assert "🔴 MUDDAT O'TDI (6 kun): Maestro kids (sentyabr qoldig'i) — qoldiq $2 100" in _pm(per_pm, "Zubair")


def test_p03_qaror_jadvalda_dublikat(muhit):
    """qaror_jadvalda (oktabr Stirkauz $1 714 = $1 350 + $364 — sheet'da) qaror eskirsa ham dublikat."""
    _oy_oxiri()
    _kun(OKT01, SENT_A, _almashtir(OKT_30, "Stirkauz", q("Stirkauz", "Zubair", "$1 800", "", "20.10")))
    blok = _blok(OKT01)
    assert "⚠️ Ikki tabda dublikat: Stirka → Stirkauz (Zubair) — sentyabr $364 / oktyabr $1 800, 20.10" in blok, blok
    per_pm, _st = _push(OKT01)
    assert "Stirka (sentyabr" not in _pm(per_pm, "Zubair")


# ------------------------------------------------------------ review: hamkor qatorning PM'i oy almashganda o'zgargan

@pytest.mark.parametrize("legacy", [True, False])
def test_p03_hamkor_pm_ozgargan(muhit, legacy):
    """30.09 sentabr Pruddy (Zubair) ↔ oktabr Pruddy (Asadbek) aynan juft: hamkor PM bo'yicha
    izlanmaydi — «topilmadi» yolg'on ⚠️ yo'q, oktabr qatori bo'shasa «$4 500 izohsiz» chiqadi."""
    okt = _almashtir(OKT_30, "Pruddy", q("Pruddy", "Asadbek", "$4 500", "", "05.10"))
    s = _oy_oxiri(legacy, okt=okt)
    assert next(i for i in s["keyingi"]["kochgan"] if i["loyiha"] == "Pruddy")["cur_pm"] == "Asadbek"
    bosh = _almashtir(okt, "Pruddy", q("Pruddy", "Asadbek", "", "", "05.10"))
    _kun(OKT01, _almashtir(SENT_A, "Pruddy", q("Pruddy", "Zubair", "$4 000", "$500", "30.09")), bosh)
    blok = _blok(OKT01)
    assert "topilmadi" not in blok, blok
    assert ("⚠️ Pruddy (Asadbek, oktyabr): Summa $4 500 → bo'sh, $4 500 izohsiz (30.09 dan beri) — "
            "oktyabr qatorida Undirildi yoki Lose'ga yozing") in blok.split("\n"), blok
    # sentabr «✅ To'lov qilindi» (Undirildi'siz), oktabr nusxasi bo'shatilgan — $4 500 ikki tabdan jim yo'qolardi
    _kun(OKT09, _almashtir(SENT_A, "Pruddy", q("Pruddy", "Zubair", "$4 500", "", "30.09", "✅ To'lov qilindi")), bosh)
    assert "Pruddy (Asadbek, oktyabr): Summa $4 500 → bo'sh, $4 500 izohsiz" in _blok(OKT09)


# ------------------------------------------------------------ review: o'tgan tab kuzatuvi — joriy tabdagi qarz ⚠️ emas

def test_p03_otgan_tab_kochirildi(muhit, monkeypatch):
    _oy_oxiri()
    orto = q("Orto life", "Islom", "$900", "", "28.09")
    orto0 = q("Orto life", "Islom", "", "", "28.09")
    okt_orto = OKT_30 + [q("Orto life", "Islom", "$900", "", "10.10")]
    # L dan keyin ko'chirish: 02.10 sentabr bo'shatildi, oktabrga qo'shildi
    _kun(OKT01, SENT_A + [orto])
    _kun(OKT02, SENT_A + [orto0], okt_orto)
    blok = _blok(OKT02)
    assert "Orto life (Islom): Summa $900 → bo'sh — oktyabr tabida: Orto life, $900, 10.10" in blok, blok
    assert "$900 izohsiz" not in blok
    # ikki qadam: 02.10 nusxa (sentabr ochiq), 03.10 sentabr bo'shatildi
    okt03 = date(2026, 10, 3)
    _kun(OKT02, SENT_A + [orto], okt_orto)
    _kun(okt03, SENT_A + [orto0], okt_orto)
    blok = _blok(okt03)
    assert "Orto life (Islom): Summa $900 → bo'sh — oktyabr tabida" in blok and "$900 izohsiz" not in blok, blok
    # 🧹 tuzatildi: Remax oktabrda to'langan, ega sentabr Summa'ni bo'shatdi
    remax = q("Remax", "Zubair", "$5 000", "", "25.09")
    okt_remax = OKT_30 + [q("Remax", "Zubair", "", "$5 000", "05.10", "✅ To'lov qilindi")]
    _kun(OKT02, SENT_A + [remax], okt_remax)
    _kun(okt03, SENT_A + [q("Remax", "Zubair", "", "", "25.09")], okt_remax)
    blok = _blok(okt03)
    assert "Remax (Zubair): Summa $5 000 → bo'sh — oktyabr tabida: Remax, to'langan" in blok, blok
    assert "$5 000 izohsiz" not in blok
    # dublikat satri «sentabr tabidagi qatorni yoping» dedi — qator o'chirildi
    _kun(OKT01, SENT_A)
    _kun(OKT02, _almashtir(SENT_A, "Bosimov shcool", None))
    blok = _blok(OKT02)
    assert "Bosimov shcool (Zubair): qator o'chirildi, Summa $1 500 — ko'chirilgan qarz" in blok, blok
    assert "qator o'chirilgan — Bosimov" not in blok


def test_p03_otgan_tab_cheklov(muhit):
    _oy_oxiri()
    ekstra = [q(f"Loyiha {n}", "Islom", "$100", "", "20.09") for n in range(10)]
    _kun(OKT01, SENT_A + ekstra)
    _kun(OKT02, SENT_A)
    lines = [x for x in _blok(OKT02).split("\n") if x.startswith("⚠️ Sentyabr tabi")]
    assert len(lines) == 9 and lines[-1] == "⚠️ Sentyabr tabi (01.10 → 02.10): yana 2 ta qator — sheet'da tekshiring"


# ------------------------------------------------------------ review: ikki tabda yozilgan pul «izohlangan» emas

def test_p03_ikki_tabda_yozilgan(muhit, monkeypatch):
    """Sentabr nusxasi oktabrdek yopilsa (Lose $1 500 ikkala tabda) — $3 000 / $2 500 qarz:
    $1 000 izohsiz yashirinmaydi (09:00 blok va 09:30 jamlama)."""
    _oy_oxiri()
    okt13, okt14 = date(2026, 10, 13), date(2026, 10, 14)
    _kun(okt13, SENT_B, OKT_LOSE)
    assert "Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz (30.09 dan beri) — oktyabr" in _blok(okt13)
    sent = _almashtir(SENT_B, "Bosimov shcool", q("Bosimov shcool", "Zubair", "", "", "18.09", "Puli yo'q",
                                                  lose="$1 500"))
    satr = ("⚠️ Bosimov School (Zubair, oktyabr): Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz (30.09 dan "
            "beri); sentyabr tabida ham Lose +$1 500 — bir qarz ikki tabda yozilgan, ikkalasini solishtiring")
    for d in (okt14, OKT09):
        _kun(d, sent, OKT_LOSE)
        blok = _blok(d)
        assert satr in blok.split("\n") and "sentyabr tabida yozilgan" not in blok, blok
    assert satr in _jamlama(monkeypatch, okt14)
    # to'lov ikkala tabda: oktabr Undirildi $1 500, sentabr nusxasi ham to'langan $1 500
    paid = _almashtir(OKT_30, "Bosimov School", q("Bosimov School", "Zubair", "", "$1 500", "18.10", "✅ To'lov qilindi"))
    _kun(okt14, _almashtir(SENT_B, "Bosimov shcool", q("Bosimov shcool", "Zubair", "", "$1 500", "18.09",
                                                       "✅ To'lov qilindi")), paid)
    assert ("Undirildi +$1 500, $1 000 izohsiz (30.09 dan beri); sentyabr tabida ham Undirildi +$1 500 — bir "
            "qarz ikki tabda yozilgan") in _blok(okt14)


# ------------------------------------------------------------ review: `--date` simulyatsiyasi muzlatmaydi

def test_p03_simulyatsiya_muzlatmaydi(muhit, monkeypatch):
    """28.09 da `pm_push.py --dry-run --date 2026-10-01`: ro'yxat xotirada quriladi, fayl YOZILMAYDI —
    aks holda 28.09 ro'yxati abadiy muzlab, 30.09 dagi oxirgi ko'rinish (T8) e'tiborsiz qolardi."""
    s = _eski_shakl(_oy_oxiri())
    (diffmod.SNAPSHOTS / "2026-09-30" / "report.json").unlink()
    _report("2026-09-28", s)
    monkeypatch.setattr(carry, "_bugun", lambda: date(2026, 9, 28))
    rec, _iz = carry.royxat(OKT01)
    assert rec["kun"] == "2026-09-28" and _carry_fayllar() == []
    s30 = json.loads(json.dumps(s))
    s30["keyingi"]["kochgan"] = [i for i in s30["keyingi"]["kochgan"] if i["loyiha"] != "Bosimov shcool"]
    _report("2026-09-30", s30)
    monkeypatch.setattr(carry, "_bugun", lambda: date(2026, 10, 1))
    rec, _iz = carry.royxat(OKT01)
    assert rec["kun"] == "2026-09-30" and rec["muzlatildi"] == "2026-10-01" and _carry_fayllar() == ["2026-09.json"]
    assert "Bosimov shcool" not in [e["loyiha"] for e in rec["items"]]


# ------------------------------------------------------------ review: bir jarayondagi oqimlar bitta tmp'ni bo'lishmaydi

def test_p03_atomik_yoz_oqimlar(tmp_path, monkeypatch):
    """09:30 push va bot handler oqimi (bitta pid) bir vaqtda muzlatsa: B ning tmp'i A e'lon qilgan
    faylni bo'shatmaydi va qayta yozmaydi; yozish xato bo'lsa tmp qolmaydi."""
    p = tmp_path / "x" / "2026-09.json"
    asl = os.link
    korildi = []

    def link(src, dst):
        asl(src, dst)
        if not korildi:                     # A link qildi, tmp'ni hali o'chirmadi — shu payt B
            korildi.append(1)
            carry._atomik_yoz(p, {"b": 2})
            korildi.append(json.loads(p.read_text(encoding="utf-8")))
    monkeypatch.setattr(carry.os, "link", link)
    carry._atomik_yoz(p, {"a": 1})
    assert korildi[1] == {"a": 1} and json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert [x.name for x in p.parent.iterdir()] == ["2026-09.json"]
    with pytest.raises(TypeError):
        carry._atomik_yoz(tmp_path / "y" / "2026-09.json", {"x": object()})
    assert list((tmp_path / "y").iterdir()) == []
