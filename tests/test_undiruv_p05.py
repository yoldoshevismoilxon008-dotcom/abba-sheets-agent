"""AUDIT.md P0-5: Kelishilgan izohsiz kamayishi — joriy oy tabi qatorma-qator kecha↔bugun (undiruv_izohsiz).

Qatorlar hisobotlar arxividan (abba-hisobotlar origin/main, 2026-07-30 … 2026-10-17) qayta tiklangan
sintetik snapshot'lar (raqamlar AUDIT/arxivda keltirilganlari). Tarmoq kerak emas: jonli o'qish
o'chiriladi, korinish()/summary() tmp snapshot'lardan o'qiydi. Holat fayli YO'Q — har chaqiruvda
zanjir snapshot'lardan quriladi (jarayon keshi bilan).
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import diff as diffmod            # noqa: E402
import fetch as fetchmod          # noqa: E402
import undiruv as u               # noqa: E402
import undiruv_carry as carry     # noqa: E402
import undiruv_izohsiz as iz      # noqa: E402

HDR = ["№", "Nomi", "Ma'sul shaxs", "LTV", "Summa", "Undirildi", "Aktive  Summary",
       "Lose summa", "Final data", "To'lov xolati", "Tasdiq"]
TABLAR = {"avgust": "Undiruv avgust(2026)", "sentyabr": "Undiruv sentabr(2026)",
          "oktyabr": "Undiruv oktabr(2026)", "noyabr": "Undiruv noyabr(2026)"}
FOOT = [["Jami"] + [""] * 10,
        ["", "Ehtimoli aktive", "$107 944"] + [""] * 8,
        ["", "$132 710", "", "", "$107 944", "", "$24 766", "", "", "", ""]]


def q(nom, pm, summa="", und="", muddat="", holat="", aktiv="", lose=""):
    return ["1", nom, pm, "", summa, und, aktiv, lose, muddat, holat, ""]


def _temiz():
    iz._QATOR_KESH.clear()
    iz._ZANJIR_KESH.clear()
    iz._SNAP_BIR.clear()
    iz._FAYL_KESH.clear()


@pytest.fixture
def muhit(monkeypatch, tmp_path):
    monkeypatch.delenv("UNDIRUV_IZOHSIZ_OFF", raising=False)
    monkeypatch.setenv("UNDIRUV_CARRY_OFF", "1")          # P0-3 o'chiq: P0-5 Tanho/Bosimov'ni o'zi ko'radi
    monkeypatch.delenv("UNDIRUV_KESH", raising=False)
    monkeypatch.setattr(carry, "_bugun", lambda: date(2027, 2, 1))
    monkeypatch.setattr(diffmod, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(u, "fetch_live_month", lambda *a, **k: (None, []))
    monkeypatch.setattr(u, "qarorlar", lambda: [])
    monkeypatch.setattr(u, "qaror_xatolari", lambda: [])
    u._VIEW_KESH.clear()
    _temiz()
    return tmp_path


def snap(day, ustun_siljishi=False, foot=None, sarlavha=None, qoshimcha=None, **tablar):
    d = diffmod.SNAPSHOTS / day
    d.mkdir(parents=True, exist_ok=True)
    ranges = {}
    for oy, rows in tablar.items():
        hdr, rr = list(sarlavha or HDR), [list(r) for r in rows]
        ft = [list(r) for r in (FOOT if foot is None else foot)]
        if ustun_siljishi:                       # «Izoh» ustuni Summa'dan oldin qo'shildi
            hdr = hdr[:4] + ["Izoh"] + hdr[4:]
            rr = [r[:4] + [""] + r[4:] for r in rr]
            ft = [r[:4] + [""] + r[4:] for r in ft]
        ranges[f"'{TABLAR[oy]}'!A1:BZ1000"] = {"values": [[""] * 11, hdr] + rr + ft}
    ranges.update(qoshimcha or {})
    (d / "smm.json").write_text(json.dumps({"id": "smm", "pm_kpi": False, "fetched_at": f"{day} 09:00:00",
                                            "ranges": ranges}, ensure_ascii=False), encoding="utf-8")
    _temiz()                                     # bir xil mtime/hajm bilan qayta yozilsa ham eski kesh qolmasin


def blok(day):
    u._VIEW_KESH.clear()
    out = u.report_block(day.isoformat(), day).split("\n")
    print("\n=== " + day.isoformat() + "\n" + "\n".join(out))
    return out


def bor(lines, prefix):
    return [x for x in lines if x.startswith(prefix)]


def pul(lines):
    return bor(lines, "Kelishilgan $")[0]


def izohsiz_satrlar(lines):
    return [x for x in lines if x.startswith(("⚠️ Izohsiz", "⚠️ Qator o'chirilgan", "✅ Izohsiz",
                                              "⚠️ Kelishilgan izohsiz"))]


def _okt(rows, nom, yangi):
    """rows nusxasi: `nom` qatori `yangi` bilan (None — o'chiriladi)."""
    out = []
    for r in rows:
        if r[1] == nom:
            if yangi is not None:
                out.append(yangi)
        else:
            out.append(r)
    return out


# ---------------------------------------------------------------- T1: 29.09 → 30.09 Marvid textile

S29 = [q("Marvid textile", "Abdufattoh", "$1 600", "$1 600", "30.09", "🟡 Qisman to'langan"),
       q("Tanho", "Abdufattoh", "$4 500", "", "30.09"),
       q("Pruddy", "Zubair", "$4 500", "", "30.09"),
       q("Kanzec", "Zubair", "", "$2 000", "06.09", "✅ To'lov qilindi")]
S30 = [q("Marvid textile", "Abdufattoh", "$0", "$1 600", "30.09", "✅ To'lov qilindi"),
       q("Tanho", "Abdufattoh", "$2 417", "$2 083", "30.09"),
       q("Pruddy", "Zubair", "$4 500", "", "30.09"),
       q("Kanzec", "Zubair", "", "$2 000", "06.09", "✅ To'lov qilindi")]
# Oktabr tabi 30.09 da ochiq (look-ahead): Marvid oktabr hisob-fakturasi — ko'chirish EMAS
O30 = [q("Marvid textile", "Abdufattoh", "$1 600", "", "30.10"),
       q("Icar24", "Islom", "$5 400", "", "05.10"),
       q("Tanho", "Abdufattoh", "$2 417", "", "05.10"),
       q("FTTI", "Islom", "$2 200", "", "10.10"),
       q("Trend snack", "Zubair", "$5 000", "", "10.10"),
       q("Geely", "Islom", "$2 950", "", "05.10")]
MARVID = ("⚠️ Izohsiz yo'qolish: Marvid textile (Abdufattoh) $1 600, muddat 30.09 — Summa $1 600 → $0 "
          "(29.09 → 30.09), holat «✅ To'lov qilindi», lekin pul Undirildi/Lose summa'ga yozilmagan; "
          "Undirildi yoki Lose summa'ga yozing")


def test_t1_marvid(muhit):
    snap("2026-08-31", sentyabr=S29)                     # oy asosi — 1-sanadan oldin
    snap("2026-09-29", sentyabr=S29, oktyabr=O30)
    snap("2026-09-30", sentyabr=S30, oktyabr=O30)
    L = blok(date(2026, 9, 30))
    assert izohsiz_satrlar(L) == [MARVID], L
    assert not any("Tanho" in x for x in izohsiz_satrlar(L))
    assert "ℹ️ Kelishilgan 29.09 → 30.09: $14 200 → $12 600 (−$1 600): izohsiz yo'qolish −$1 600" in L, L
    assert pul(L).endswith(" · lose $0 · izohsiz yo'qolgan $1 600 (oy boshidan) · lose va izohsiz hisobga "
                           "olinsa 40,0%"), pul(L)   # 5 683 / (12 600 + 0 + 1 600)


# ---------------------------------------------------------------- T2: 01.10 → 02.10 Icar24 (AI ishlamagan)

ICAR = {
    "o'chirilgan": None,
    "lose_yoq": q("Icar24", "Islom", "", "", "05.10"),
    "lose_bor": q("Icar24", "Islom", "", "", "05.10", "Puli yo'q", lose="$5 400"),
}


@pytest.mark.parametrize("variant", list(ICAR))
def test_t2_icar24(muhit, variant):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-01", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", ICAR[variant]))
    L = blok(date(2026, 10, 2))
    got = izohsiz_satrlar(L)
    if variant == "o'chirilgan":
        assert got == ["⚠️ Qator o'chirilgan: Icar24 (Islom) $5 400, muddat 05.10 — kecha Summa $5 400 "
                       "(01.10 → 02.10); qatorni qaytaring yoki Undirildi/Lose summa bilan yoping"], L
        assert " · izohsiz yo'qolgan $5 400 (oy boshidan)" in pul(L)
    elif variant == "lose_yoq":
        assert got == ["⚠️ Izohsiz yo'qolish: Icar24 (Islom) $5 400, muddat 05.10 — Summa $5 400 → bo'sh "
                       "(01.10 → 02.10); Undirildi yoki Lose summa'ga yozing"], L
    else:
        assert got == [], L
        assert "ℹ️ Kelishilgan 01.10 → 02.10: $19 567 → $14 167 (−$5 400): Lose'ga −$5 400" in L, L
        assert " · lose $5 400 · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


# ---------------------------------------------------------------- T3: 02.10 → 03.10 Tanho $917 (P0-3 o'chiq)

def test_t3_tanho_va_izohlandi(muhit):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=O30)
    o3 = _okt(O30, "Tanho", q("Tanho", "Abdufattoh", "", "", "05.10", aktiv="$1 500"))
    snap("2026-10-03", oktyabr=o3)
    L = blok(date(2026, 10, 3))
    assert izohsiz_satrlar(L) == [
        "⚠️ Izohsiz yo'qolish: Tanho (Abdufattoh) $917, muddat 05.10 — Summa $2 417 → bo'sh, Aktive +$1 500 "
        "(02.10 → 03.10); Undirildi yoki Lose summa'ga yozing"], L
    # 04.10–08.10: har kuni ochiq ro'yxatda
    snap("2026-10-04", oktyabr=o3)
    L = blok(date(2026, 10, 4))
    assert ("⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $917: Tanho (Abdufattoh) $917, muddat 05.10, "
            "03.10 dan") in L, L
    # 09.10: Undirildi +$1 250 (10-09.md:14) — ✅, ortig'i $333 «oshgan»
    o9 = _okt(O30, "Tanho", q("Tanho", "Abdufattoh", "", "$1 250", "", "✅ To'lov qilindi", aktiv="$1 500"))
    snap("2026-10-09", oktyabr=o9)
    L = blok(date(2026, 10, 9))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Tanho (Abdufattoh) $917 — Undirildi +$1 250 "
                                  "(03.10 da ochilgan)"], L
    snap("2026-10-10", oktyabr=o9)
    assert izohsiz_satrlar(blok(date(2026, 10, 10))) == []


# ---------------------------------------------------------------- T4/T5: FTTI ✅, Trend snack takrorlanadi

def _ftti_trend():
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-05", oktyabr=O30)
    o6 = _okt(O30, "FTTI", q("FTTI", "Islom", "", "", "10.10"))
    snap("2026-10-06", oktyabr=o6)
    o7 = _okt(o6, "FTTI", q("FTTI", "Islom", "", "", "", "Puli yo'q", lose="$2 200"))   # Final data bo'shatildi
    o7 = _okt(o7, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10", "Vaqtinchalik pauzaga olindi"))
    return o6, o7


TREND = ("⚠️ Izohsiz yo'qolish: Trend snack (Zubair) $5 000, muddat 10.10 — Summa $5 000 → bo'sh (06.10 → 07.10), "
         "holat «Vaqtinchalik pauzaga olindi», lekin pul Undirildi/Lose summa'ga yozilmagan; Undirildi yoki "
         "Lose summa'ga yozing")


def test_t4_ftti_t5_trend(muhit):
    o6, o7 = _ftti_trend()
    L = blok(date(2026, 10, 6))
    assert izohsiz_satrlar(L) == [
        "⚠️ Izohsiz yo'qolish: FTTI (Islom) $2 200, muddat 10.10 — Summa $2 200 → bo'sh (05.10 → 06.10); "
        "Undirildi yoki Lose summa'ga yozing"], L
    snap("2026-10-07", oktyabr=o7)
    L = blok(date(2026, 10, 7))
    assert izohsiz_satrlar(L) == [
        TREND, "✅ Izohsiz yo'qolish izohlandi: FTTI (Islom) $2 200 — Lose +$2 200 (06.10 da ochilgan)"], L
    assert ("ℹ️ Kelishilgan 06.10 → 07.10: $17 367 → $12 367 (−$5 000): Lose'ga −$2 200, izohsiz yo'qolish "
            "−$5 000, ilgari yo'qolgan izohlandi +$2 200") in L, L
    snap("2026-10-08", oktyabr=o7)
    L = blok(date(2026, 10, 8))
    assert not any("FTTI" in x for x in izohsiz_satrlar(L)), L


def test_trend_takrorlanadi(muhit):
    _o6, o7 = _ftti_trend()
    snap("2026-10-07", oktyabr=o7)
    o10 = _okt(o7, "Trend snack", None)                  # 10.10: nol qator o'chirildi (10-10.md:17)
    for kun in range(8, 18):
        snap(f"2026-10-{kun:02d}", oktyabr=o7 if kun < 10 else o10)
    for kun in range(8, 18):
        L = blok(date(2026, 10, kun))
        tail = ", qator o'chirilgan" if kun >= 10 else ""
        assert izohsiz_satrlar(L) == [
            "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $5 000: Trend snack (Zubair) $5 000, muddat 10.10, "
            "07.10 dan" + tail], (kun, L)
        if kun == 10:
            assert not bor(L, "⚠️ Qator o'chirilgan"), L
            assert " · lose $2 200 · izohsiz yo'qolgan $5 000 (oy boshidan) · " in pul(L), pul(L)


# ---------------------------------------------------------------- T6: 25.09 → 26.09 Ifar baklava $800

def test_t6_ifar(muhit):
    s25 = [q("Ifar baklava", "Islom", "$1 800", "", "21.09"), q("Forza.uz", "Islom", "$6 000", "", "20.09"),
           q("Li auto", "Islom", "$2 500", "", "06.09"), q("Aventos", "Zubair", "$1 500", "", "22.09")]
    s26 = [q("Ifar baklava", "Islom", "", "$1 000", "21.09", "✅ To'lov qilindi"),
           q("Forza.uz", "Islom", "", "", "20.09", "Mijoz yo'q bo'lib qoldi", lose="$6 000"),
           q("Li auto", "Islom", "", "", "06.09", "Puli yo'q", lose="$2 500"),
           q("Aventos", "Zubair", "", "$1 500", "22.09", "✅ To'lov qilindi")]
    snap("2026-09-25", sentyabr=s25)
    snap("2026-09-26", sentyabr=s26)
    L = blok(date(2026, 9, 26))
    got = izohsiz_satrlar(L)
    assert len(got) == 1 and got[0].startswith("⚠️ Izohsiz yo'qolish: Ifar baklava (Islom) $800, muddat 21.09 — "
                                               "Summa $1 800 → bo'sh, Undirildi +$1 000 (25.09 → 26.09)"), L
    # pulning bir qismi yozilgan — «lekin qolgan $800», «lekin pul … yozilmagan» (o'zaro zid) EMAS
    assert got[0].endswith("holat «✅ To'lov qilindi», lekin qolgan $800 Undirildi/Lose summa'ga yozilmagan; "
                           "Undirildi yoki Lose summa'ga yozing"), got
    assert ("ℹ️ Kelishilgan 25.09 → 26.09: $11 800 → $2 500 (−$9 300): Lose'ga −$8 500, izohsiz yo'qolish "
            "−$800") in L, L
    assert " · izohsiz yo'qolgan $800 (25.09 dan)" in pul(L), pul(L)     # zanjir oy boshidan emas


# ---------------------------------------------------------------- T7: K − U = Q (±$1)

@pytest.mark.parametrize("gap,kerak", [(683, True), (1167, True), (1, False), (-1, False), (0, False)])
def test_t7_arifmetika(gap, kerak):
    w = u.reconcile_warn({"kelishilgan": 53083, "undirildi": 46633, "qoldiq": 6450 - gap, "reconcile_gap": gap})
    if kerak:
        assert w == (f"⚠️ Arifmetika mos emas, farq {u._fmt_usd(gap)}: kelishilgan−undirildi = $6 450, "
                     f"qoldiq = {u._fmt_usd(6450 - gap)} — sheet'da yopilgan (to'langan/ketgan) qatorda Summa "
                     f"qolgan bo'lishi mumkin, tekshiring."), w
    else:
        assert w == ""


T7_ROWS = [q("Baaz", "Azizxo'ja", "$333", "$1 767", "25.09", "✅ To'lov qilindi"),
           q("Stirkauz", "Zubair", "$350", "$1 000", "21.09", "✅ To'lov qilindi"),
           q("vgr", "Islom", "$2 000", "", "30.09")]


def test_t7_blok(muhit, monkeypatch):
    # 30.07 holati: to'langan deb belgilangan qatorda Summa qolgan (Baaz $333 + Stirkauz $350)
    monkeypatch.setenv("UNDIRUV_IZOHSIZ_OFF", "1")      # kalitdan qat'i nazar (shartsiz o'zgarish)
    snap("2026-09-30", sentyabr=T7_ROWS)
    L = blok(date(2026, 9, 30))
    i = L.index("⚠️ Arifmetika mos emas, farq $683: kelishilgan−undirildi = $2 683, qoldiq = $2 000 — sheet'da "
                "yopilgan (to'langan/ketgan) qatorda Summa qolgan bo'lishi mumkin, tekshiring.")
    assert L[i + 1].startswith("💰 **Undiruv"), L


def test_t7_bir_dollar_bosh_satr_yoq(muhit):
    """$1 farq — ogohlantirish ham, bo'sh satr ham yo'q (avval «if reconcile_gap» bo'sh satr qo'shardi)."""
    snap("2026-09-30", sentyabr=[q("vgr", "Islom", "$2 000.6", "$0.4", "30.09")])
    L = blok(date(2026, 9, 30))
    assert "" not in L and not bor(L, "⚠️ Arifmetika"), L


def test_pdf_reconcile(muhit, monkeypatch):
    import render_pdf
    monkeypatch.setenv("UNDIRUV_IZOHSIZ_OFF", "1")
    snap("2026-09-30", sentyabr=T7_ROWS)
    s = u.summary("2026-09-30", date(2026, 9, 30))
    html = render_pdf.build_html({"date": "2026-09-30", "totals": {}, "pms": [], "trend": [], "undiruv": s},
                                 logo_uri="")
    assert '<span class="overdue">⚠️ Arifmetika mos emas, farq $683: kelishilgan−undirildi = $2 683' in html
    # farq yo'q — HTML'da hech narsa qo'shilmaydi
    s2 = dict(s, reconcile_gap=0)
    html2 = render_pdf.build_html({"date": "2026-09-30", "totals": {}, "pms": [], "trend": [], "undiruv": s2},
                                  logo_uri="")
    assert "Arifmetika" not in html2 and "</h3>\n  <div class=\"u-kpis\">" in html2


# ---------------------------------------------------------------- R1–R3: regressiyalar

def test_r1_qayta_nomlash(muhit):
    a = [q("Stirka", "Zubair", "$364", "$986", "21.10"), q("Bosimov shcool", "Zubair", "$2 500", "", "18.10"),
         q("ABC servis", "Islom", "$700", "", "12.10")]
    b = [q("Stirkauz", "Zubair", "$364", "$986", "21.10"), q("Bosimov School", "Zubair", "$2 500", "", "18.10"),
         q("Zeta group", "Islom", "$700", "", "12.10")]
    snap("2026-09-30", oktyabr=a)
    snap("2026-10-01", oktyabr=b)
    L = blok(date(2026, 10, 1))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan"), L
    assert ("ℹ️ Qayta nomlangan (30.09 → 01.10): Stirka → Stirkauz (Zubair); Bosimov shcool → Bosimov School "
            "(Zubair); ABC servis → Zeta group (Islom)") in L, L
    # nomi o'zgargan qatorda keyin yo'qolish — yangi nom bilan
    c = [q("Stirkauz", "Zubair", "$1 350", "$1 350", "21.10"), q("Bosimov School", "Zubair", "", "", "18.10",
                                                                  lose="$1 500"),
         q("Zeta group", "Islom", "$700", "", "12.10")]
    snap("2026-10-09", oktyabr=c)
    L = blok(date(2026, 10, 9))
    assert izohsiz_satrlar(L) == [
        "⚠️ Izohsiz yo'qolish: Bosimov School (Zubair) $1 000, muddat 18.10 — Summa $2 500 → bo'sh, Lose +$1 500 "
        "(01.10 → 09.10); Undirildi yoki Lose summa'ga yozing"], L


def test_r2_jamlanma_qatorlari(muhit):
    rows = [q("Geely", "Islom", "$2 950", "", "05.10"),
            ["", "$7 536", "", "", "", "", "$7 536", "", "", "", ""],          # Jami'dan YUQORIDA, PM'siz
            ["", "Aktive Summary", "", "", "$1 000", "", "", "", "", "", ""]]
    rows2 = [q("Geely", "Islom", "$2 950", "", "05.10"),
             ["", "$2 654", "", "", "", "", "$2 654", "", "", "", ""],
             ["", "Aktive Summary", "", "", "$300", "", "", "", "", "", ""]]
    foot1 = [["Jami"] + [""] * 10, ["", "Ehtimoli aktive", "$100 744"] + [""] * 8,
             ["", "$121 610", "", "", "$100 744", "", "$20 866", "", "", "", ""]]
    foot2 = [["Jami"] + [""] * 10, ["", "Ehtimoli aktive", "$96 844"] + [""] * 8,
             ["", "$132 710", "", "", "$96 844", "", "$35 866", "", "", "", ""]]
    snap("2026-09-30", oktyabr=rows, foot=foot1)
    snap("2026-10-01", oktyabr=rows2, foot=foot2)
    L = blok(date(2026, 10, 1))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan"), L
    assert bor(L, "Kelishilgan $2 950 · undirildi $0"), L
    # PM'li qator (nomi son bo'lsa ham) tashlanmaydi
    assert [r["loyiha"] for r in u.parse_rows([HDR, q("777", "Islom", "$5")], date(2026, 10, 1))] == ["777"]


def test_r3_ustun_siljishi(muhit):
    smm_main = lambda n: {"'Smm main'!A1:BZ1000": {"values": [["Loyiha", "Narx"]]  # noqa: E731
                                                   + [[f"L{i}", f"${i * n}"] for i in range(40)]}}
    snap("2026-10-04", oktyabr=O30, qoshimcha=smm_main(1))
    snap("2026-10-05", ustun_siljishi=True, oktyabr=O30, qoshimcha=smm_main(7))
    L = blok(date(2026, 10, 5))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan") and not bor(L, "ℹ️ Qayta"), L


# ---------------------------------------------------------------- Ommaviy kun, ko'prik, bugungi snapshot yo'q

def test_ommaviy(muhit):
    a = [q(f"Loyiha {chr(65 + i)}", "Islom", "$1 000", "", "20.10") for i in range(10)]
    b = [q(f"Loyiha {chr(65 + i)}", "Islom", "", "", "20.10") for i in range(10)]
    snap("2026-09-30", oktyabr=a)
    snap("2026-10-04", oktyabr=a)
    snap("2026-10-05", oktyabr=b)
    L = blok(date(2026, 10, 5))
    got = izohsiz_satrlar(L)
    assert got == ["⚠️ Izohsiz yo'qolish (04.10 → 05.10): 10 qator bir kunda, jami $10 000 — tab almashgan yoki "
                   "ustun siljigan bo'lishi mumkin, sheet'ni tekshiring: Loyiha A (Islom) $1 000, Loyiha B (Islom) "
                   "$1 000, Loyiha C (Islom) $1 000, Loyiha D (Islom) $1 000, Loyiha E (Islom) $1 000, Loyiha F "
                   "(Islom) $1 000 +4"], L
    assert " · izohsiz yo'qolgan $10 000 (oy boshidan)" in pul(L), pul(L)
    snap("2026-10-06", oktyabr=a)
    L = blok(date(2026, 10, 6))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: 10 ta qator, $10 000 — Loyiha A (Islom), "
                                  "Loyiha B (Islom), Loyiha C (Islom), Loyiha D (Islom), Loyiha E (Islom), "
                                  "Loyiha F (Islom) +4"], L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


def test_kooprik(muhit):
    o4 = _okt(O30, "Geely", q("Geely", "Islom", "", "", "05.10"))
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=O30)
    snap("2026-10-04", oktyabr=o4)                       # 03.10 snapshot yo'q (run o'tkazib yuborildi)
    L = blok(date(2026, 10, 4))
    assert bor(L, "⚠️ Izohsiz yo'qolish: Geely (Islom) $2 950, muddat 05.10 — Summa $2 950 → bo'sh (02.10 → 04.10)"), L
    # 05.10: sarlavhada «Undirildi» yo'q — kun ko'prik bilan o'tkaziladi, «hamma qator o'chdi» EMAS
    snap("2026-10-05", oktyabr=o4, sarlavha=[("Undirilgan" if h == "Undirildi" else h) for h in HDR])
    snap("2026-10-06", oktyabr=o4)
    L = blok(date(2026, 10, 6))
    assert izohsiz_satrlar(L) == ["⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $2 950: Geely (Islom) $2 950, "
                                  "muddat 05.10, 04.10 dan"], L
    assert not [x for x in L if u.SARLAVHA_BELGI in x], L
    st = iz.zanjir(date(2026, 10, 1), "2026-10-06")
    assert st["kunlar"]["2026-10-05"] == {"otkazildi": "sarlavha o'qilmadi"}
    assert st["kunlar"]["2026-10-06"]["oldin"] == "2026-10-04"


def _jonli(monkeypatch, kun):
    """Jonli o'qish o'rniga `kun` snapshot'i (bugungi snapshot hali yo'q, /hisobot jonli o'qiydi)."""
    def f(month_name, today, year=None, qat_iy=False, ref=None):
        s = json.loads((diffmod.SNAPSHOTS / kun / "smm.json").read_text(encoding="utf-8"))
        rng = u.find_tab(s, today, month=month_name, year=year, qat_iy=qat_iy)
        if not rng:
            return None, []
        tab = fetchmod.tab_of_range(rng)
        return tab, u.parse_rows(s["ranges"][rng]["values"], today, ref, tab=tab)
    monkeypatch.setattr(u, "fetch_live_month", f)


def test_bugun_snapshot_yoq(muhit, monkeypatch):
    _o6, o7 = _ftti_trend()
    snap("2026-10-07", oktyabr=o7)
    snap("2026-10-17", oktyabr=o7)
    _jonli(monkeypatch, "2026-10-17")
    L = blok(date(2026, 10, 18))
    assert izohsiz_satrlar(L) == [
        "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $5 000: Trend snack (Zubair) $5 000, muddat 10.10, "
        "07.10 dan"], L
    assert "ℹ️ Izohsiz yo'qolish: 18.10 snapshot'i yo'q — 17.10 holati ko'rsatildi" in L, L
    assert not bor(L, "ℹ️ Kelishilgan") and not bor(L, "✅"), L
    assert " · izohsiz yo'qolgan $5 000 (oy boshidan, 17.10 snapshot)" in pul(L), pul(L)
    # /hisobot 09:00 dan oldin ikkinchi marta: bugungi papkada faqat report-live.json — baribir «snapshot'i yo'q»
    (diffmod.SNAPSHOTS / "2026-10-18").mkdir()
    (diffmod.SNAPSHOTS / "2026-10-18" / "report-live.json").write_text("{}", encoding="utf-8")
    assert "ℹ️ Izohsiz yo'qolish: 18.10 snapshot'i yo'q — 17.10 holati ko'rsatildi" in blok(date(2026, 10, 18))


def test_qayta_ishga_tushirish(muhit, monkeypatch):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-01", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", ICAR["lose_yoq"]))
    L02 = blok(date(2026, 10, 2))
    n = {"c": 0}
    asl = iz._tab_qatorlari

    def sanoq(*a, **k):
        n["c"] += 1
        return asl(*a, **k)
    monkeypatch.setattr(iz, "_tab_qatorlari", sanoq)
    assert blok(date(2026, 10, 2)) == L02
    assert n["c"] == 0                                   # ikkinchi chaqiruv — kesh (qayta parse yo'q)
    o4 = _okt(_okt(O30, "Icar24", ICAR["lose_yoq"]), "Geely", q("Geely", "Islom", "", "", "05.10"))
    for kun in ("2026-10-04", "2026-10-07", "2026-10-10"):
        snap(kun, oktyabr=o4)
    assert bor(blok(date(2026, 10, 10)), "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 2 ta, $8 350")
    # `analyze.py --date 2026-10-02` keyinroq — o'sha kunning chiqishi aynan qaytadi (deterministik)
    assert izohsiz_satrlar(blok(date(2026, 10, 2))) == izohsiz_satrlar(L02)
    assert pul(blok(date(2026, 10, 2))) == pul(L02)


def test_oy_almashuvi(muhit):
    snap("2026-08-31", sentyabr=S29)
    snap("2026-09-29", sentyabr=S29, oktyabr=O30)
    snap("2026-09-30", sentyabr=S30, oktyabr=O30)
    assert izohsiz_satrlar(blok(date(2026, 9, 30))) == [MARVID]
    snap("2026-10-01", sentyabr=S30, oktyabr=O30)
    L = blok(date(2026, 10, 1))
    assert not [x for x in L if "Marvid" in x and "zohsiz" in x], L      # sentabr hodisasi oktabrda yo'q
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    assert iz.zanjir(date(2026, 10, 1), "2026-10-01")["asos_kun"] == "2026-09-30"


def test_oy_almashuvi_tab_1_sanada(muhit):
    snap("2026-09-30", sentyabr=S30)                     # oktabr tabi hali yo'q
    snap("2026-10-01", sentyabr=S30, oktyabr=O30)
    L = blok(date(2026, 10, 1))
    assert " · izohsiz yo'qolgan $0 (01.10 dan)" in pul(L), pul(L)
    snap("2026-10-02", sentyabr=S30, oktyabr=_okt(O30, "Icar24", None))
    L = blok(date(2026, 10, 2))
    assert bor(L, "⚠️ Qator o'chirilgan: Icar24 (Islom) $5 400, muddat 05.10 — kecha Summa $5 400 (01.10 → 02.10)")
    assert " · izohsiz yo'qolgan $5 400 (01.10 dan)" in pul(L), pul(L)


def test_oy_oxiri_kochirildi_va_ega_qarori(muhit):
    """30.09: Pruddy sentabr qatori bo'shatildi, oktabr tabida $4 500 (05.10) bor — ko'chirish (ℹ️);
    Kanzec 2 «Ega qarori» bilan yopildi — ℹ️; ikkalasi izohsiz emas va X'ga kirmaydi."""
    s29 = S29 + [q("Kanzec 2", "Zubair", "$900", "", "28.09")]
    s30 = _okt(_okt(S30 + [q("Kanzec 2", "Zubair", "$900", "", "28.09")], "Pruddy", q("Pruddy", "Zubair", "", "",
                                                                                     "30.09")),
               "Kanzec 2", q("Kanzec 2", "Zubair", "", "", "28.09", "Ega qarori"))
    okt = O30 + [q("Pruddy", "Zubair", "$4 500", "", "05.10")]
    snap("2026-08-31", sentyabr=s29)
    snap("2026-09-29", sentyabr=s29, oktyabr=okt)
    snap("2026-09-30", sentyabr=s30, oktyabr=okt)
    L = blok(date(2026, 9, 30))
    assert izohsiz_satrlar(L) == [MARVID], L
    assert ("ℹ️ Pruddy (Zubair): Summa $4 500 → bo'sh — «Undiruv oktabr(2026)» tabida «Pruddy» $4 500 bor "
            "(ko'chirilgan deb olindi, izohsiz emas)") in L, L
    assert "ℹ️ Kanzec 2 (Zubair): Summa $900 → bo'sh — holat «Ega qarori» (izohsiz deb olinmadi)" in L, L
    assert " · izohsiz yo'qolgan $1 600 (oy boshidan)" in pul(L), pul(L)


def test_oy_oxiri_kochish_ommaviy_emas(muhit):
    """30.09: 9 qator oktabr tabiga ko'chirildi (ℹ️) + Marvid izohsiz — ommaviy guruh satri EMAS,
    Marvid alohida to'liq satr bilan (ko'chgan qatorlar «tab almashgan» deb sanalmaydi)."""
    kop = [q(f"Mijoz {chr(65 + i)}", "Zubair", "$1 000", "", "30.09") for i in range(9)]
    s29, s30 = S29 + kop, S30 + [q(r[1], r[2], "", "", "30.09") for r in kop]
    okt = O30 + [q(r[1], r[2], "$1 000", "", "05.10") for r in kop]
    snap("2026-08-31", sentyabr=s29)
    snap("2026-09-29", sentyabr=s29, oktyabr=okt)
    snap("2026-09-30", sentyabr=s30, oktyabr=okt)
    L = blok(date(2026, 9, 30))
    assert izohsiz_satrlar(L) == [MARVID], L
    assert len([x for x in L if x.startswith("ℹ️ Mijoz") and "ko'chirilgan deb olindi" in x]) == 6, L
    assert ("ℹ️ Keyingi oy tabiga ko'chirilgan deb olindi: yana 3 ta, $3 000") in L, L


def test_ega_qarori_yopadi(muhit):
    o7 = _okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10"))
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-07", oktyabr=o7)
    assert izohsiz_satrlar(blok(date(2026, 10, 7)))[0].startswith("⚠️ Izohsiz yo'qolish: Trend snack")
    # «Puli yo'q» yoki «Pauza» — faqat holat, pul yozilmagan: hodisa ochiq qoladi
    snap("2026-10-08", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10", "Puli yo'q")))
    snap("2026-10-09", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10", "⏸ Pauza")))
    for kun in (8, 9):
        assert bor(blok(date(2026, 10, kun)), "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $5 000: Trend snack")
    snap("2026-10-10", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10", "Ega qarori")))
    L = blok(date(2026, 10, 10))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Trend snack (Zubair) $5 000 — holat «Ega qarori» "
                                  "(07.10 da ochilgan)"], L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


# ---------------------------------------------------------------- N1/N3/N5 va izoh qoidalari

def test_n1_agromash(muhit):
    a = O30 + [q("Agromashtexnika", "Azizxo'ja", "$5 000", "", "25.10")]
    b = O30 + [q("Agromashtexnika", "Azizxo'ja", "", "$4 500", "25.10", "✅ To'lov qilindi")]
    snap("2026-10-15", oktyabr=a)
    snap("2026-10-16", oktyabr=b)
    assert izohsiz_satrlar(blok(date(2026, 10, 16))) == [
        "⚠️ Izohsiz yo'qolish: Agromashtexnika (Azizxo'ja) $500, muddat 25.10 — Summa $5 000 → bo'sh, "
        "Undirildi +$4 500 (15.10 → 16.10), holat «✅ To'lov qilindi», lekin qolgan $500 Undirildi/Lose "
        "summa'ga yozilmagan; Undirildi yoki Lose summa'ga yozing"]


def test_n3_oshish_jim(muhit):
    a = O30 + [q("Asl Food", "Islom", "$1 700", "", "20.10")]
    b = O30 + [q("Asl Food", "Islom", "$2 850", "", "20.10"), q("Ansel", "Azizxo'ja", "$1 500", "", "15.10")]
    snap("2026-10-08", oktyabr=a)
    snap("2026-10-09", oktyabr=b)
    L = blok(date(2026, 10, 9))
    assert izohsiz_satrlar(L) == [], L
    assert "ℹ️ Kelishilgan 08.10 → 09.10: $21 267 → $23 917 (+$2 650): oshgan/yangi qator +$2 650" in L, L


def test_n5_faqat_muddat(muhit):
    a = O30 + [q("Ifar baklava", "Islom", "$1 800", "", "05.10")]
    b = O30 + [q("Ifar baklava", "Islom", "$1 800", "", "20.10")]
    snap("2026-10-11", oktyabr=a)
    snap("2026-10-12", oktyabr=b)
    L = blok(date(2026, 10, 12))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan") and not bor(L, "ℹ️ Qayta"), L
    assert not [x for x in L if "Ifar" in x and not x.startswith("  •")], L


def test_yangi_invoice_yopmaydi(muhit):
    snap("2026-10-06", oktyabr=O30)
    snap("2026-10-07", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10")))
    blok(date(2026, 10, 7))
    snap("2026-10-08", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "$6 000", "", "10.11")))
    L = blok(date(2026, 10, 8))
    assert not bor(L, "✅"), L
    assert bor(L, "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $5 000: Trend snack (Zubair) $5 000, "
                  "muddat 10.10, 07.10 dan"), L


def test_qisman_izohlandi(muhit):
    snap("2026-10-06", oktyabr=O30)
    snap("2026-10-07", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10")))
    blok(date(2026, 10, 7))
    snap("2026-10-08", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "$2 000", "10.10")))
    L = blok(date(2026, 10, 8))
    assert ("ℹ️ Qisman izohlandi: Trend snack (Zubair) — Undirildi +$2 000; $3 000 hali izohsiz (07.10 dan)") in L, L
    assert " · izohsiz yo'qolgan $3 000 (05.10 dan)" not in pul(L)
    assert " · izohsiz yo'qolgan $3 000 (06.10 dan)" in pul(L), pul(L)
    # yangi hisob-faktura (Summa $4 000) izoh EMAS — hodisa ochiq qoladi
    snap("2026-10-09", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "$4 000", "$2 000", "10.11")))
    L = blok(date(2026, 10, 9))
    assert bor(L, "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $3 000: Trend snack (Zubair) $3 000, muddat "
                  "10.10, 07.10 dan"), L


def test_qator_qaytarildi(muhit):
    """Icar24 qatori o'chirildi, ertasi kuni aynan qaytarildi — ✅ (qator qayta yozildi), X = 0."""
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", None))
    snap("2026-10-03", oktyabr=O30)
    L = blok(date(2026, 10, 3))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Icar24 (Islom) $5 400 — qator qayta yozildi, "
                                  "Summa $5 400 (02.10 da ochilgan)"], L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


def test_boshqa_qatorga_yozilgan(muhit):
    a = [q("Geely", "Islom", "$2 950", "", "05.10"), q("Mb city", "Islom", "$1 600", "", "05.10")]
    b = [q("Geely", "Islom", "", "", "05.10", "✅ To'lov qilindi"), q("Mb city", "Islom", "$1 600", "$2 950", "05.10")]
    snap("2026-10-04", oktyabr=a)
    snap("2026-10-05", oktyabr=b)
    got = izohsiz_satrlar(blok(date(2026, 10, 5)))
    assert len(got) == 1 and "; shu kuni Mb city: Undirildi +$2 950 — to'lov boshqa qatorga yozilgan bo'lishi mumkin" in got[0]


def test_noaniq_net(muhit):
    a = O30 + [q("Asl Food", "Islom", "$1 700", "", "20.10")]
    teng = O30 + [q("Asl Food uz", "Islom", "$1 000", "", "20.10"), q("Asl Food tj", "Islom", "$700", "", "20.10")]
    kam = O30 + [q("Asl Food uz", "Islom", "$500", "", "20.10"), q("Asl Food tj", "Islom", "$500", "", "20.10")]
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-08", oktyabr=a)
    snap("2026-10-09", oktyabr=teng)
    L = blok(date(2026, 10, 9))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan 08.10"), L
    snap("2026-10-09", oktyabr=kam)
    L = blok(date(2026, 10, 9))
    assert izohsiz_satrlar(L) == ["⚠️ Kelishilgan izohsiz kamaydi: $700 (08.10 → 09.10) — qator aniq moslanmadi: "
                                  "Asl Food (Islom) $1 700 (o'xshash nomli qatorlar bor); nomini aniq yozing"], L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    snap("2026-10-10", oktyabr=kam)
    assert izohsiz_satrlar(blok(date(2026, 10, 10))) == []                   # takrorlanmaydi


# ---------------------------------------------------------------- P0-3 bilan: bir hodisa — bir ⚠️

import test_undiruv_p03 as p03     # noqa: E402  (P0-3 fixture'lari: 30.09 report.json, SENT_A/B, OKT_LOSE)


@pytest.fixture
def ikkalasi(muhit, monkeypatch):
    monkeypatch.delenv("UNDIRUV_CARRY_OFF", raising=False)
    monkeypatch.setattr(u, "qarorlar", lambda: list(p03.QAROR))
    return muhit


def _p03_kun(today, sent, okt=p03.OKT_30):
    p03._kun(today, sent, okt)
    _temiz()


def test_p03_tanho_bir_marta(ikkalasi):
    p03._oy_oxiri()
    okt03 = date(2026, 10, 3)
    okt = p03._almashtir(p03.OKT_30, "Tanho", p03.q("Tanho", "Abdufattoh", "", "", "05.10", aktiv="$1 500"))
    _p03_kun(okt03, p03.SENT_30, okt)
    L = blok(okt03)
    assert len([x for x in L if "Tanho" in x and "$917" in x]) == 1, L          # faqat P0-3 satri
    assert bor(L, "⚠️ Tanho (Abdufattoh, oktyabr): Summa $2 417 → bo'sh, Aktive +$1 500, $917 izohsiz"), L
    assert not bor(L, "⚠️ Izohsiz yo'qolish: Tanho"), L
    assert ("ℹ️ Kelishilgan 30.09 → 03.10: $16 931 → $14 514 (−$2 417): Aktive'ga −$1 500, ko'chirilgan qarz "
            "(yuqoridagi satr) −$917") in L, L
    assert " · izohsiz yo'qolgan $917 (oy boshidan)" in pul(L), pul(L)


@pytest.mark.parametrize("sent,x", [(p03.SENT_A, 0), (p03.SENT_B, 1000)])
def test_p03_bosimov_bir_marta(ikkalasi, sent, x):
    """SENT_A: $1 000 sentabr tabida undirilgan — P0-3 ℹ️ (izohlangan), P0-5 ham jim; SENT_B — P0-3 ⚠️ bitta."""
    p03._oy_oxiri()
    _p03_kun(p03.OKT01, sent)
    blok(p03.OKT01)
    _p03_kun(p03.OKT09, sent, p03.OKT_LOSE)
    L = blok(p03.OKT09)
    assert not bor(L, "⚠️ Izohsiz yo'qolish: Bosimov") and not bor(L, "⚠️ Izohsiz yo'qolish — hali"), L
    izohsiz_p03 = [y for y in L if y.startswith("⚠️ Bosimov School (Zubair, oktyabr): Summa $2 500 → bo'sh, "
                                                 "Lose +$1 500, $1 000 izohsiz")]
    assert len(izohsiz_p03) == (1 if x else 0), L
    assert ("ℹ️ Kelishilgan 01.10 → 09.10: $16 931 → $14 431 (−$2 500): Lose'ga −$1 500, ko'chirilgan qarz "
            "(yuqoridagi satr) −$1 000") in L, L
    assert f" · izohsiz yo'qolgan {u._fmt_usd(x)} (oy boshidan)" in pul(L), pul(L)


def test_p03_kelishilgan_bolaklari(ikkalasi):
    """Bir juftda P0-3 qatorlaridan biri yo'qotdi (Bosimov $1 000), boshqasi izohlandi (Tanho $917) —
    ℹ️ Kelishilgan bo'laklari alohida (sof −$83 emas). Tanho bugun P0-3 uchun joyida (jim) — P0-3 03.10 da
    aytgan $917 ning yopilishi P0-5 ✅ satri bilan (ikkinchi ⚠️ emas)."""
    p03._oy_oxiri()
    okt3 = p03._almashtir(p03.OKT_30, "Tanho", p03.q("Tanho", "Abdufattoh", "", "", "05.10", aktiv="$1 500"))
    _p03_kun(date(2026, 10, 3), p03.SENT_B, okt3)
    okt9 = p03._almashtir(p03.OKT_LOSE, "Tanho", p03.q("Tanho", "Abdufattoh", "", "$1 250", "", "✅ To'lov qilindi",
                                                       aktiv="$1 500"))
    _p03_kun(p03.OKT09, p03.SENT_B, okt9)
    L = blok(p03.OKT09)
    assert ("ℹ️ Kelishilgan 03.10 → 09.10: $14 514 → $13 264 (−$1 250): Lose'ga −$1 500, ko'chirilgan qarz "
            "(yuqoridagi satr) −$1 000, ilgari yo'qolgan izohlandi +$917, oshgan/yangi qator +$333") in L, L
    assert bor(L, "✅") == ["✅ Izohsiz yo'qolish izohlandi: Tanho (Abdufattoh) $917 — Undirildi +$1 250 "
                           "(03.10 da ochilgan)"], L
    assert not bor(L, "⚠️ Izohsiz"), L
    assert " · izohsiz yo'qolgan $1 000 (oy boshidan)" in pul(L), pul(L)


def test_p05_carry_off_bosimov(muhit):
    """CARRY o'chiq — P0-5 Bosimov'ning $1 000 ini o'zi ko'rsatadi (09.10)."""
    p03._oy_oxiri()
    _p03_kun(p03.OKT01, p03.SENT_B)
    _p03_kun(p03.OKT09, p03.SENT_B, p03.OKT_LOSE)
    L = blok(p03.OKT09)
    assert bor(L, "⚠️ Izohsiz yo'qolish: Bosimov School (Zubair) $1 000, muddat 18.10 — Summa $2 500 → bo'sh, "
                  "Lose +$1 500 (01.10 → 09.10), holat «Puli yo'q», lekin qolgan $1 000 Undirildi/Lose summa'ga "
                  "yozilmagan; Undirildi yoki Lose summa'ga yozing"), L
    assert " · izohsiz yo'qolgan $1 000 (oy boshidan)" in pul(L), pul(L)


def test_p03_topilmadi_skip(ikkalasi):
    """Ko'chirilgan oktabr qatori o'chirildi, sentabr qatori ochiq — P0-3 o'tgan qoldiqni qayta so'raydi;
    P0-5 «Qator o'chirilgan: Bosimov School» demaydi va X'ga qo'shmaydi."""
    p03._oy_oxiri()
    _p03_kun(p03.OKT01, p03.SENT_B, p03._almashtir(p03.OKT_30, "Bosimov School", None))
    L = blok(p03.OKT01)
    assert [x for x in L if "endi u yerda topilmadi" in x and "qayta so'ralmoqda" in x], L
    assert not bor(L, "⚠️ Qator o'chirilgan: Bosimov"), L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


# ---------------------------------------------------------------- Xato, kalit, raqamlar, caption/PDF

def test_xato(muhit, monkeypatch):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", None))

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(iz, "hisobot", boom)
    L = blok(date(2026, 10, 2))
    assert "⚠️ Izohsiz yo'qolish tekshiruvi ishlamadi (RuntimeError) — qatorma-qator tekshirilmadi" in L, L
    assert pul(L).endswith("· qoldiq $14 167"), pul(L)
    s = u.summary("2026-10-02", date(2026, 10, 2))
    assert "izohsiz" not in s and "lose_jami" not in s


def test_kalit_ochiq_baytma_bayt(muhit, monkeypatch):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", None))
    n = {"c": 0}
    asl = iz.tab_qatorlari

    def sanoq(*a, **k):
        n["c"] += 1
        return asl(*a, **k)
    monkeypatch.setattr(iz, "tab_qatorlari", sanoq)
    monkeypatch.setenv("UNDIRUV_IZOHSIZ_OFF", "1")
    L = blok(date(2026, 10, 2))
    assert not [x for x in L if "zohsiz" in x or "Qator o'chirilgan" in x or "ℹ️ Kelishilgan" in x
                or " · lose $" in x], L
    s = u.summary("2026-10-02", date(2026, 10, 2))
    assert "izohsiz" not in s and "lose_jami" not in s
    assert n["c"] == 0
    # kalit yoqilgan, aytadigan gap yo'q (o'zgarishsiz juft) — faqat 💰 qo'shimchasi farq qiladi
    snap("2026-10-03", oktyabr=O30)
    snap("2026-10-04", oktyabr=O30)
    off = blok(date(2026, 10, 4))
    monkeypatch.delenv("UNDIRUV_IZOHSIZ_OFF")
    on = blok(date(2026, 10, 4))
    assert len(on) == len(off) and [a for a, b in zip(on, off) if a != b] == [pul(on)], (on, off)
    assert pul(on) == pul(off) + iz.pul_qatori(u.summary("2026-10-04", date(2026, 10, 4)))


def test_pul_qatori_raqamlar():
    s = {"kelishilgan": 96844, "undirildi": 13850, "lose_jami": 12900,
         "izohsiz": {"x": 6000, "dan": None, "kun": "2026-10-09", "eski": False}}
    assert iz.pul_qatori(s) == (" · lose $12 900 · izohsiz yo'qolgan $6 000 (oy boshidan) · lose va izohsiz "
                                "hisobga olinsa 12,0%")       # 10-09
    s = {"kelishilgan": 85344, "undirildi": 38764, "lose_jami": 25700,
         "izohsiz": {"x": 6500, "dan": None, "kun": "2026-10-17", "eski": False}}
    assert iz.pul_qatori(s) == (" · lose $25 700 · izohsiz yo'qolgan $6 500 (oy boshidan) · lose va izohsiz "
                                "hisobga olinsa 33,0%")       # 10-17
    s = {"kelishilgan": 85344, "undirildi": 38764, "lose_jami": 0,
         "izohsiz": {"x": 0, "dan": "2026-10-05", "kun": "2026-10-16", "eski": True}}
    assert iz.pul_qatori(s) == " · lose $0 · izohsiz yo'qolgan $0 (05.10 dan, 16.10 snapshot)"
    assert iz.pul_qatori({"kelishilgan": 1, "undirildi": 1}) == ""
    s = {"kelishilgan": 100, "undirildi": 50, "izohsiz": {"x": 0, "dan": None, "kun": None, "eski": False}}
    assert iz.pul_qatori(s) == " · izohsiz yo'qolgan $0 (qatorma-qator tekshirilmadi)"   # Lose ustuni yo'q


def test_caption_va_pdf(muhit):
    import render_pdf
    import send
    o7 = _ftti_trend()[1]
    snap("2026-10-07", oktyabr=o7)
    s = u.summary("2026-10-07", date(2026, 10, 7))
    assert s["izohsiz"]["x"] == 5000 and s["lose_jami"] == 2200
    cap = send.build_caption({"date": "2026-10-07", "undiruv": s})
    assert " · ⚠️ izohsiz $5 000" in cap, cap
    cap0 = send.build_caption({"date": "2026-10-07", "undiruv": dict(s, izohsiz=dict(s["izohsiz"], x=0))})
    assert "izohsiz" not in cap0, cap0
    html = render_pdf.build_html({"date": "2026-10-07", "totals": {}, "pms": [], "trend": [], "undiruv": s},
                                 logo_uri="")
    assert ('<div class="l">Lose · izohsiz</div><div class="v" style="font-size:12px;"><span class="muted">'
            '$2 200</span> · <span class="c-red">$5 000</span>') in html, html
    p2 = iz.ikkinchi_foiz(s)
    # 2-foiz va X yorlig'i PDF'da ham izohli (yalang'och «/ 33,0%» emas)
    assert p2 and f">lose+izohsiz bilan {p2}%</div>" in html and f"/ {p2}%" not in html, html
    assert ">izohsiz oy boshidan</div>" in html, html
    # tekshirilmagan oy — X «—» ($0 emas) va «qatorma-qator tekshirilmadi»
    s1 = dict(s, izohsiz=dict(s["izohsiz"], kun=None, x=0))
    html1 = render_pdf.build_html({"date": "2026-10-07", "totals": {}, "pms": [], "trend": [], "undiruv": s1},
                                  logo_uri="")
    assert '<span class="muted">—</span></div><div class="l"' in html1 and ">izohsiz qatorma-qator tekshirilmadi<" in html1
    # kalit o'chiq (izohsiz maydoni yo'q) — tile ham, 2-foiz ham yo'q
    s0 = {k: v for k, v in s.items() if k not in ("izohsiz", "lose_jami")}
    html0 = render_pdf.build_html({"date": "2026-10-07", "totals": {}, "pms": [], "trend": [], "undiruv": s0},
                                  logo_uri="")
    assert "Lose · izohsiz" not in html0 and "lose+izohsiz bilan" not in html0
    assert "izohsiz" not in send.build_caption({"date": "2026-10-07", "undiruv": s0})


# ---------------------------------------------------------------- Review tuzatishlari (P0-5 review)

def _p03_tanho_917():
    """Ko'chirilgan Tanho: 03.10 Summa $2 417 → bo'sh, Aktive +$1 500 — P0-3 ⚠️ $917 (P0-5 jim)."""
    p03._oy_oxiri()
    okt3 = p03._almashtir(p03.OKT_30, "Tanho", p03.q("Tanho", "Abdufattoh", "", "", "05.10", aktiv="$1 500"))
    _p03_kun(date(2026, 10, 3), p03.SENT_30, okt3)
    L = blok(date(2026, 10, 3))
    assert bor(L, "⚠️ Tanho (Abdufattoh, oktyabr): Summa $2 417 → bo'sh, Aktive +$1 500, $917 izohsiz"), L
    assert not bor(L, "⚠️ Izohsiz yo'qolish: Tanho"), L


@pytest.mark.parametrize("carry_off", [False, True])
def test_p03_jim_kunda_p05_korsatadi_tanho(ikkalasi, monkeypatch, carry_off):
    """15.10: shu qatorga oktabr hisob-fakturasi Summa $4 500 yozildi — P0-3 asosga nisbatan «joyida»
    (jim), yangi hisob esa izoh EMAS: $917 ochiq qoladi va X'da — P0-3 kalitidan qat'i nazar bir xil."""
    _p03_tanho_917()
    if carry_off:
        monkeypatch.setenv("UNDIRUV_CARRY_OFF", "1")
    okt15 = p03._almashtir(p03.OKT_30, "Tanho", p03.q("Tanho", "Abdufattoh", "$4 500", "", "05.11", aktiv="$1 500"))
    _p03_kun(date(2026, 10, 15), p03.SENT_30, okt15)
    L = blok(date(2026, 10, 15))
    assert bor(L, "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $917: Tanho (Abdufattoh) $917, muddat 05.10, "
                  "03.10 dan"), L
    assert not bor(L, "⚠️ Tanho"), L
    assert " · izohsiz yo'qolgan $917 (oy boshidan)" in pul(L), pul(L)


def test_p03_ortiqchadan_keyingi_yoqolish(ikkalasi):
    """Tanho ✅ dan keyin (A $1 500 + U $1 250 = asosdan $333 ortiq) 12.10 Aktive $1 500 → $1 200 —
    P0-3 kumulyativ (jim), P0-5 ⚠️ $300 beradi (ilgari ikkalasi ham jim edi)."""
    _p03_tanho_917()
    t9 = p03.q("Tanho", "Abdufattoh", "", "$1 250", "", "✅ To'lov qilindi", aktiv="$1 500")
    _p03_kun(p03.OKT09, p03.SENT_30, p03._almashtir(p03.OKT_30, "Tanho", t9))
    assert bor(blok(p03.OKT09), "✅ Izohsiz yo'qolish izohlandi: Tanho (Abdufattoh) $917")
    t12 = p03.q("Tanho", "Abdufattoh", "", "$1 250", "", "✅ To'lov qilindi", aktiv="$1 200")
    _p03_kun(date(2026, 10, 12), p03.SENT_30, p03._almashtir(p03.OKT_30, "Tanho", t12))
    L = blok(date(2026, 10, 12))
    assert bor(L, "⚠️ Izohsiz yo'qolish") == ["⚠️ Izohsiz yo'qolish: Tanho (Abdufattoh) $300, muddat yo'q — Aktive −$300 "
                                              "(09.10 → 12.10); Undirildi yoki Lose summa'ga yozing"], L
    assert " · izohsiz yo'qolgan $300 (oy boshidan)" in pul(L), pul(L)


def test_p03_pruddy_oshgan_keyin_yoqoldi(ikkalasi):
    """Ko'chirilgan Pruddy $4 500: 05.10 Summa $9 000 (oktabr hisobi qo'shildi), 09.10 Summa $4 500 (U/L yo'q).
    P0-3 asosga nisbatan joyida (jim) — P0-5 ⚠️ $4 500, ℹ️ satri «ko'chirilgan qarz (yuqoridagi satr)» demaydi."""
    p03._oy_oxiri()
    _p03_kun(date(2026, 10, 5), p03.SENT_30,
             p03._almashtir(p03.OKT_30, "Pruddy", p03.q("Pruddy", "Zubair", "$9 000", "", "05.11")))
    blok(date(2026, 10, 5))
    _p03_kun(p03.OKT09, p03.SENT_30,
             p03._almashtir(p03.OKT_30, "Pruddy", p03.q("Pruddy", "Zubair", "$4 500", "", "05.11")))
    L = blok(p03.OKT09)
    assert bor(L, "⚠️ Izohsiz yo'qolish: Pruddy (Zubair) $4 500, muddat 05.11 — Summa $9 000 → $4 500 "
                  "(05.10 → 09.10)"), L
    assert " · izohsiz yo'qolgan $4 500 (oy boshidan)" in pul(L), pul(L)
    k = bor(L, "ℹ️ Kelishilgan 05.10 → 09.10")
    assert k and "izohsiz yo'qolish −$4 500" in k[0] and "yuqoridagi satr" not in k[0], L


def test_p03_bir_xil_nom_boshqa_pm(ikkalasi):
    """Ko'chirilgan «Bosimov School» (Zubair, P0-3 ⚠️ $1 000) yonida 05.10 da alohida «Bosimov School»
    (Islom) $3 000 qo'shildi; 09.10 Islom qatori bo'shadi — P0-5 uni ko'rsatadi (skip nom + PM bo'yicha)."""
    p03._oy_oxiri()
    _p03_kun(p03.OKT01, p03.SENT_B)
    blok(p03.OKT01)
    _p03_kun(date(2026, 10, 5), p03.SENT_B, p03.OKT_30 + [p03.q("Bosimov School", "Islom", "$3 000", "", "25.10")])
    blok(date(2026, 10, 5))
    _p03_kun(p03.OKT09, p03.SENT_B, p03.OKT_LOSE + [p03.q("Bosimov School", "Islom", "", "", "25.10")])
    L = blok(p03.OKT09)
    assert len(bor(L, "⚠️ Bosimov School (Zubair, oktyabr): Summa $2 500 → bo'sh, Lose +$1 500, $1 000 izohsiz")) == 1, L
    assert bor(L, "⚠️ Izohsiz yo'qolish") == [
        "⚠️ Izohsiz yo'qolish: Bosimov School (Islom) $3 000, muddat 25.10 — Summa $3 000 → bo'sh (05.10 → 09.10); "
        "Undirildi yoki Lose summa'ga yozing"], L
    assert " · izohsiz yo'qolgan $4 000 (oy boshidan)" in pul(L), pul(L)      # P0-3 $1 000 + P0-5 $3 000
    assert ("ℹ️ Kelishilgan 05.10 → 09.10: $19 931 → $14 431 (−$5 500): Lose'ga −$1 500, izohsiz yo'qolish "
            "−$3 000, ko'chirilgan qarz (yuqoridagi satr) −$1 000") in L, L


def test_qisman_qaytish_tolov_bilan(muhit):
    """07.10 Trend snack Summa $5 000 → bo'sh; 08.10 ega tuzatdi: Summa $3 000 + Undirildi $2 000 (qator jami
    yo'qolishdan oldingi $5 000) — ✅, X = 0 (ilgari $3 000 oy oxirigacha ochiq qolardi)."""
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-07", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10")))
    blok(date(2026, 10, 7))
    snap("2026-10-08", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "$3 000", "$2 000", "10.10")))
    L = blok(date(2026, 10, 8))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Trend snack (Zubair) $5 000 — Summa bo'sh → $3 000, "
                                  "Undirildi +$2 000 (07.10 da ochilgan)"], L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    snap("2026-10-12", oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", "$0", "$5 000", "10.10",
                                                          "✅ To'lov qilindi")))
    assert izohsiz_satrlar(blok(date(2026, 10, 12))) == []


def test_ikki_bosqichli_qaytish(muhit):
    """5 000 → 3 000 → 1 000 → 3 000 → 5 000: qator aynan asl holiga qaytdi — oxirgi kuni ✅, X = 0,
    ℹ️ Kelishilgan'da manfiy «oshgan» bo'lagi yo'q."""
    snap("2026-09-30", oktyabr=O30)
    for kun, sm in (("2026-10-07", "$3 000"), ("2026-10-08", "$1 000"), ("2026-10-09", "$3 000"),
                    ("2026-10-10", "$5 000")):
        snap(kun, oktyabr=_okt(O30, "Trend snack", q("Trend snack", "Zubair", sm, "", "10.10")))
        L = blok(date.fromisoformat(kun))
    assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Trend snack (Zubair) $4 000 — Summa $3 000 → $5 000 "
                                  "(07.10 da ochilgan)"], L
    assert "ℹ️ Kelishilgan 09.10 → 10.10: $17 567 → $19 567 (+$2 000): ilgari yo'qolgan izohlandi +$2 000" in L, L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    st = iz.zanjir(date(2026, 10, 1), "2026-10-10")
    assert all(not k.get("qoldiq") for k in st["kunlar"].values() if "K" in k)      # ayniyat har juftda


@pytest.mark.parametrize("yangi,bogla", [
    (q("Icar 24", "Islom", "$5 400", "", "05.10"), True),              # imlo (bo'shliq) farqi
    (q("Icar24.uz", "Islom", "$5 400", "", "05.10"), True),            # fuzzy ≥ 0.85, shu PM
    (q("ICAR24", "Zubair", "$5 400", "", "05.10"), True),              # aynan nom, PM almashgan
    (q("Zeta group", "Islom", "$3 000", "", "20.10"), False),          # boshqa qator (nom, pul, muddat)
])
def test_qayta_yozildi_moslash(muhit, yangi, bogla):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", None))
    assert bor(blok(date(2026, 10, 2)), "⚠️ Qator o'chirilgan: Icar24 (Islom) $5 400")
    snap("2026-10-03", oktyabr=O30[:1] + [yangi] + O30[2:])
    L = blok(date(2026, 10, 3))
    if bogla:
        assert izohsiz_satrlar(L) == ["✅ Izohsiz yo'qolish izohlandi: Icar24 (Islom) $5 400 — qator qayta yozildi, "
                                      "Summa $5 400 (02.10 da ochilgan)"], L
        assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    else:
        assert bor(L, "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 1 ta, $5 400: Icar24 (Islom)"), L
        assert " · izohsiz yo'qolgan $5 400 (oy boshidan)" in pul(L), pul(L)


def test_qayta_yozildi_noaniq(muhit):
    """Ikki o'xshash o'chirilgan qator, bitta yangi «Asl Food» — qaysiniki noma'lum: bog'lanmaydi."""
    a = O30 + [q("Asl Food uz", "Islom", "$1 000", "", "20.10"), q("Asl Food tj", "Islom", "$700", "", "20.10")]
    snap("2026-09-30", oktyabr=a)
    snap("2026-10-02", oktyabr=O30)
    blok(date(2026, 10, 2))
    snap("2026-10-03", oktyabr=O30 + [q("Asl Food", "Islom", "$1 200", "", "25.10")])
    L = blok(date(2026, 10, 3))
    assert not bor(L, "✅"), L
    assert bor(L, "⚠️ Izohsiz yo'qolish — hali izohlanmagan: 2 ta, $1 700"), L


def _bosh_tab(day):
    p = diffmod.SNAPSHOTS / day / "smm.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    for k in s["ranges"]:
        s["ranges"][k]["values"] = []                    # fetch.py: Sheets bo'sh diapazonda «values» bermaydi
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    _temiz()


@pytest.mark.parametrize("qosh", [[], [q("Geely", "Islom", "$1 000", "", "25.10")]])
def test_bosh_tab_kooprik(muhit, qosh):
    """05.10 snapshot'ida tab butunlay bo'sh (values: []) — ko'prik (sarlavha o'qilmagan kun kabi):
    05.10 da «hamma qator o'chdi» emas, 06.10 da «✅ qator qayta yozildi» ham yo'q, X = 0 (bir xil nom+PM'li
    qatorlar bilan ham)."""
    rows = O30 + qosh
    snap("2026-09-30", oktyabr=rows)
    snap("2026-10-04", oktyabr=rows)
    snap("2026-10-05", oktyabr=rows)
    _bosh_tab("2026-10-05")
    snap("2026-10-06", oktyabr=rows)
    L = blok(date(2026, 10, 6))
    assert izohsiz_satrlar(L) == [] and not bor(L, "ℹ️ Kelishilgan"), L
    assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)
    st = iz.zanjir(date(2026, 10, 1), "2026-10-06")
    assert st["kunlar"]["2026-10-05"] == {"otkazildi": "sarlavha o'qilmadi"}
    assert st["kunlar"]["2026-10-06"]["oldin"] == "2026-10-04"
    # Sarlavhasi bor, qatorsiz tab — ko'prik EMAS (haqiqiy ommaviy o'chirish: hodisalar ochiladi)
    snap("2026-10-07", oktyabr=[])
    assert iz.tab_qatorlari("2026-10-07", date(2026, 10, 1))[1] == []


def test_sarlavha_izohi_umumiy_royxatga_tegmaydi(muhit, monkeypatch):
    """Tarixiy snapshot'ning buzuq sarlavhasi umumiy undiruv._SARLAVHA_IZOH'ni o'zgartirmaydi (bot oqimlari
    uni bir vaqtda tozalaydi/o'qiydi) va kun (tab, None) — ko'prik."""
    snap("2026-10-05", oktyabr=O30, sarlavha=[("Undirilgan" if h == "Undirildi" else h) for h in HDR])

    class Kuzat(list):                           # umumiy ro'yxatga har qanday yozish — qayd (oxirgi holat emas:
        yozuv = []                               # nusxa+tiklash ham boshqa oqim uchun oraliq holatni o'zgartiradi)

        def append(self, x):
            self.yozuv.append(("append", x))
            super().append(x)

        def __setitem__(self, k, v):
            self.yozuv.append(("setitem", k))
            super().__setitem__(k, v)

        def clear(self):
            self.yozuv.append(("clear",))
            super().clear()
    belgi = Kuzat(["⚠️ boshqa oqim izohi"])
    monkeypatch.setattr(u, "_SARLAVHA_IZOH", belgi)
    tab, rows = iz.tab_qatorlari("2026-10-05", date(2026, 10, 1))
    assert (tab, rows) == ("Undiruv oktabr(2026)", None)
    assert u._SARLAVHA_IZOH is belgi and list(belgi) == ["⚠️ boshqa oqim izohi"] and Kuzat.yozuv == []


def test_bir_xil_nomli_qatorlar_kunlik_juftlash(muhit):
    """Bir PM'ning ikki «Tutti» qatori: birinchisiga to'g'ri qisman to'lov (Summa $2 000 → $1 000, Undirildi
    +$1 000) — egizak $1 000 qator bilan almashmaydi: ⚠️ yo'q, X = 0."""
    a = O30 + [q("Tutti", "Abdufattoh", "$2 000", "", "10.10"), q("Tutti", "Abdufattoh", "$1 000", "", "25.10")]
    b = O30 + [q("Tutti", "Abdufattoh", "$1 000", "$1 000", "10.10", "🟡 Qisman to'langan"),
               q("Tutti", "Abdufattoh", "$1 000", "", "25.10")]
    snap("2026-09-30", oktyabr=a)
    snap("2026-10-01", oktyabr=a)
    snap("2026-10-02", oktyabr=b)
    for kun in (2, 3):
        if kun == 3:
            snap("2026-10-03", oktyabr=b)
        L = blok(date(2026, 10, kun))
        assert izohsiz_satrlar(L) == [], L
        assert " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), pul(L)


NOY = {"Trend snack": q("Trend snack", "Zubair", "$5 000", "", "10.11"),
       "FTTI": q("FTTI", "Islom", "$6 000", "", "15.11")}


def _oy_oxiri_kochish(noy27, noy28, okt28):
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-27", oktyabr=O30, noyabr=noy27)
    snap("2026-10-28", oktyabr=okt28, noyabr=noy28)
    return blok(date(2026, 10, 28))


def test_oy_oxiri_muddati_otgan_kochmagan(muhit):
    """28.10 (look-ahead): muddati o'tgan Trend snack $5 000 va FTTI $2 200 (10.10) bo'shatildi, Undirildi/
    Lose yo'q. Noyabr tabidagi «Trend snack $5 000» va «FTTI $6 000» 27.10 dan beri o'zgarmagan (navbatdagi
    hisob) — ko'chganiga dalil yo'q: ⚠️ + maslahat, X'ga kiradi (ilgari «ko'chirilgan deb olindi», X = 0)."""
    noy = list(NOY.values())
    okt = _okt(_okt(O30, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10")),
               "FTTI", q("FTTI", "Islom", "", "", "10.10"))
    L = _oy_oxiri_kochish(noy, noy, okt)
    assert not [x for x in L if "ko'chirilgan deb olindi" in x], L
    assert bor(L, "⚠️ Izohsiz yo'qolish") == [
        "⚠️ Izohsiz yo'qolish: FTTI (Islom) $2 200, muddat 10.10 — Summa $2 200 → bo'sh (27.10 → 28.10); Undirildi "
        "yoki Lose summa'ga yozing; «Undiruv noyabr(2026)» tabida «FTTI» $6 000 bor, lekin unga bu pul qo'shilmagan "
        "— ko'chirilgan bo'lsa holatini «Ega qarori» qiling",
        "⚠️ Izohsiz yo'qolish: Trend snack (Zubair) $5 000, muddat 10.10 — Summa $5 000 → bo'sh (27.10 → 28.10); "
        "Undirildi yoki Lose summa'ga yozing; «Undiruv noyabr(2026)» tabida «Trend snack» $5 000 bor, lekin unga bu "
        "pul qo'shilmagan — ko'chirilgan bo'lsa holatini «Ega qarori» qiling"], L
    assert " · izohsiz yo'qolgan $7 200 (oy boshidan)" in pul(L), pul(L)


def test_oy_oxiri_kochdi_dalil_bilan(muhit):
    """Xuddi shu kuni noyabr FTTI qatori $3 800 → $6 000 o'sdi (qarz qo'shildi) — ℹ️ ko'chirilgan, X = 0."""
    noy27 = [NOY["Trend snack"], q("FTTI", "Islom", "$3 800", "", "15.11")]
    okt = _okt(O30, "FTTI", q("FTTI", "Islom", "", "", "10.10"))
    L = _oy_oxiri_kochish(noy27, list(NOY.values()), okt)
    assert ("ℹ️ FTTI (Islom): Summa $2 200 → bo'sh — «Undiruv noyabr(2026)» tabida «FTTI» $6 000 bor (ko'chirilgan "
            "deb olindi, izohsiz emas)") in L, L
    assert izohsiz_satrlar(L) == [] and " · izohsiz yo'qolgan $0 (oy boshidan)" in pul(L), L


def test_oy_oxiri_muddati_kelmagan_kattaroq_juft(muhit):
    """Muddati hali kelmagan (30.10) qator bo'shatildi; noyabrdagi juft kattaroq ($3 000 ≠ $1 800) va
    o'zgarmagan — ko'chish emas (⚠️); teng summali juft (Pruddy kabi) — ko'chirilgan."""
    o = O30 + [q("Welle", "Islom", "$1 800", "", "30.10"), q("Ansel", "Azizxo'ja", "$900", "", "30.10")]
    noy = [q("Welle", "Islom", "$3 000", "", "05.11"), q("Ansel", "Azizxo'ja", "$900", "", "05.11")]
    okt = _okt(_okt(o, "Welle", q("Welle", "Islom", "", "", "30.10")), "Ansel", q("Ansel", "Azizxo'ja", "", "", "30.10"))
    snap("2026-09-30", oktyabr=o)
    snap("2026-10-27", oktyabr=o, noyabr=noy)
    snap("2026-10-28", oktyabr=okt, noyabr=noy)
    L = blok(date(2026, 10, 28))
    got = bor(L, "⚠️ Izohsiz yo'qolish")
    assert len(got) == 1 and got[0].startswith("⚠️ Izohsiz yo'qolish: Welle (Islom) $1 800, muddat 30.10 — "), L
    assert got[0].endswith("«Undiruv noyabr(2026)» tabida «Welle» $3 000 bor, lekin unga bu pul qo'shilmagan — "
                           "ko'chirilgan bo'lsa holatini «Ega qarori» qiling"), got
    assert " · izohsiz yo'qolgan $1 800 (oy boshidan)" in pul(L), pul(L)
    assert ("ℹ️ Ansel (Azizxo'ja): Summa $900 → bo'sh — «Undiruv noyabr(2026)» tabida «Ansel» $900 bor (ko'chirilgan "
            "deb olindi, izohsiz emas)") in L, L


def test_t6_ifar_keyingi_tab_ochiq(muhit):
    """AUDIT T6, oktabr tabi 25.09 da allaqachon ochiq («Ifar baklava $1 800, 05.10» — o'zgarmagan): $800
    baribir izohsiz (ilgari «ko'chirilgan deb olindi», X = 0)."""
    okt = [q("Ifar baklava", "Islom", "$1 800", "", "05.10")]
    s25 = [q("Ifar baklava", "Islom", "$1 800", "", "21.09")]
    s26 = [q("Ifar baklava", "Islom", "", "$1 000", "21.09", "🟡 Qisman to'langan")]
    snap("2026-09-25", sentyabr=s25, oktyabr=okt)
    snap("2026-09-26", sentyabr=s26, oktyabr=okt)
    L = blok(date(2026, 9, 26))
    got = izohsiz_satrlar(L)
    assert len(got) == 1 and got[0].startswith("⚠️ Izohsiz yo'qolish: Ifar baklava (Islom) $800, muddat 21.09 — "), L
    assert "«Undiruv oktabr(2026)» tabida «Ifar baklava» $1 800 bor, lekin unga bu pul qo'shilmagan" in got[0], got
    assert " · izohsiz yo'qolgan $800 (25.09 dan)" in pul(L), pul(L)


def test_jonli_tahrir_belgisi(muhit, monkeypatch):
    """/hisobot: 09:00 snapshot'dan keyin ega Trend snack'ga Lose $5 000 yozdi. 💰 K/U/lose jonli, P0-5
    snapshot'dan — satr va yorliq shuni aytadi, 2-foizda Lose snapshot'niki (pul L va X'da ikki marta emas)."""
    import send
    _o6, o7 = _ftti_trend()
    snap("2026-10-07", oktyabr=o7)
    snap("_jonli", oktyabr=_okt(o7, "Trend snack", q("Trend snack", "Zubair", "", "", "10.10", "Puli yo'q",
                                                     lose="$5 000")))
    _jonli(monkeypatch, "2026-10-07")                    # jonli = snapshot (09:00 run) — belgi yo'q
    L0 = blok(date(2026, 10, 7))
    assert not bor(L0, "ℹ️ Izohsiz yo'qolish: 07.10 09:00") and "09:00" not in pul(L0), L0
    assert "jonli_farq" not in u.summary("2026-10-07", date(2026, 10, 7))["izohsiz"]
    _jonli(monkeypatch, "_jonli")
    L = blok(date(2026, 10, 7))
    assert ("ℹ️ Izohsiz yo'qolish: 07.10 09:00 snapshot holati — undan keyingi sheet tuzatishlari ertangi "
            "hisobotda ko'rinadi") in L, L
    assert " · lose $7 200 · izohsiz yo'qolgan $5 000 (oy boshidan, 09:00 snapshot)" in pul(L), pul(L)
    s = u.summary("2026-10-07", date(2026, 10, 7))
    assert s["izohsiz"]["jonli_farq"] is True and s["izohsiz"]["lose_snap"] == 2200 and s["lose_jami"] == 7200
    s = dict(s, undirildi=1000)
    assert iz.ikkinchi_foiz(s) == str(round(1000 / (s["kelishilgan"] + 2200 + 5000) * 100, 1)).replace(".", ",")
    assert " · ⚠️ izohsiz $5 000 (09:00)" in send.build_caption({"date": "2026-10-07", "undiruv": s})


def test_cli_faqat_oqiydi(muhit, monkeypatch, capsys):
    """O'tgan kunni ko'rish — undiruv_izohsiz CLI (RAILWAY.md): hech qanday fayl yozmaydi."""
    snap("2026-09-30", oktyabr=O30)
    snap("2026-10-02", oktyabr=_okt(O30, "Icar24", None))
    oldin = sorted((p, p.stat().st_mtime_ns) for p in diffmod.SNAPSHOTS.rglob("*"))
    monkeypatch.setattr(carry, "_bugun", carry._bugun)  # main() uni almashtiradi — test oxirida tiklansin
    monkeypatch.setattr(sys, "argv", ["undiruv_izohsiz.py", "--date", "2026-10-02"])
    iz.main()
    out = capsys.readouterr().out
    assert "⚠️ Qator o'chirilgan: Icar24 (Islom) $5 400" in out and "izohsiz yo'qolgan: $5 400 (oy boshidan)" in out
    assert sorted((p, p.stat().st_mtime_ns) for p in diffmod.SNAPSHOTS.rglob("*")) == oldin
