#!/usr/bin/env python3
"""SMM "Undiruv <oy>" tabini parse qilib, kunlik hisobot uchun jamlaydi.

Tab tuzilmasi (header 2-qatorda): № | Nomi | Ma'sul shaxs | Summa (qoldiq) |
Undirildi | Aktive Summary | Final data (to'lov muddati, KK.OO) | To'lov xolati.
"Jami"/"Ehtimoli aktive" qatorlari jadval tugaganini bildiradi.

Sheet'ning o'z jami mantiqi: Kelishilgan = Σqoldiq + Σundirildi (Aktive Summary
alohida "ehtimoliy" pul sifatida yuritiladi — kelishilganga qo'shilmaydi).
"""
import difflib
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import diff as diffmod
import fetch as fetchmod

MONEY_RE = re.compile(r"[-\d.,]+")
DDMM_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})$")                 # 06.07 (yilsiz)
DDMMYYYY_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{2,4})$")  # 06.07.2026
ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")             # 2026-07-06
SERIAL_RE = re.compile(r"^\d+(?:\.\d+)?$")                        # 45874 (Sheets serial)
# «Muddat yaqin» chegarasi — BITTA qiymat (C3). Ilgari kunlik KPI bloki ≤4, PM push
# va ega PDF ≤5 kun ishlatardi: bir kunning o'zida ikki xil ro'yxat chiqardi
# (13.09: Bosimov va Orto life faqat push'da). Ega 29.09 da «5 kun oldin»ni tanladi.
PUSH_DUE_DAYS = 5
DUE_SOON_DAYS = PUSH_DUE_DAYS
# Google Sheets serial → sana (epoch 1899-12-30 = serial 0). Aqlli chegara
# (~1990..2089) — mayda sonlarni (masalan "5") sana deb o'qib yubormaslik uchun.
_SERIAL_EPOCH = date(1899, 12, 30)
_SERIAL_MIN, _SERIAL_MAX = 33000, 80000


def log(msg):
    print(f"[undiruv] {msg}", flush=True)


def money(v):
    """"$1 800" / "1 800,50" → float. Bo'sh/matn → 0."""
    s = str(v).replace("\xa0", "").replace(" ", "").replace(" ", "")
    m = MONEY_RE.search(s)
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return 0.0


def _safe_date(y, mm, dd):
    try:
        return date(y, mm, dd)
    except (ValueError, TypeError):
        return None


def _serial_to_date(n):
    """Google Sheets serial son → sana (epoch 1899-12-30). Chegaradan tashqari → None."""
    from datetime import timedelta
    try:
        d = int(round(float(n)))
    except (ValueError, TypeError):
        return None
    if not (_SERIAL_MIN <= d <= _SERIAL_MAX):
        return None
    return _SERIAL_EPOCH + timedelta(days=d)


# Yilsiz sana oynasi (tab oyining 1-kuniga nisbatan): muddat ko'pi bilan ~3 oy OLDINDA,
# ko'chirilib yurgan eski qarz esa ~10 oygacha ORQADA bo'lishi mumkin. Oyna kelajakka
# qisqa — noaniq sana «o'tgan» deb o'qiladi va qarz PM'dan so'raladi (yashirinmaydi).
_YILSIZ_ORQA, _YILSIZ_OLDIN = 305, 92


def _yilsiz_sana(dd, mm, today, ref=None):
    """Yilsiz DD.MM → sana. ref (tab oyining 1-kuni) berilsa — [ref−305 kun, ref+92 kun]
    oynasiga tushadigan yil (bir nechta bo'lsa ref'ga eng yaqini): dekabr tabidagi «05.01» →
    keyingi yil, yanvar tabidagi «28.12» → o'tgan yil, sentabr tabidagi eski «15.02» →
    shu yil fevrali (o'tgan — so'raladi), fevral tabidagi «15.09» → o'tgan yil sentabri.
    «Eng yaqin yil» (review D3/S11) va «faqat yil chegarasi» (review DN2) qoidalari eski
    qarzni kelajakka o'tkazib PM'dan yashirardi. Yaroqsiz sana (29.02 kabisa bo'lmagan
    yilda) boshqa yilga «tuzatilmaydi» — sanasiz bo'lib, PM'dan sana so'raladi.
    ref yo'q — joriy yil (eski xulq)."""
    if ref is None:
        return _safe_date(today.year, mm, dd)
    cands = []
    for k in (-1, 0, 1):
        d = _safe_date(ref.year + k, mm, dd)
        if d and -_YILSIZ_ORQA <= (d - ref).days <= _YILSIZ_OLDIN:
            cands.append(d)
    return min(cands, key=lambda d: abs((d - ref).days)) if cands else None


def parse_due(v, today, ref=None):
    """To'lov muddatini turli formatdan o'qiydi → date (yoki None):
      DD.MM / D.M (yilsiz → joriy yil; ref berilsa tab oyiga eng yaqin yil),
      DD.MM.YYYY, DD/MM/YYYY, ISO YYYY-MM-DD,
      Google Sheets serial son (int/float yoki toza raqamli satr, epoch 1899-12-30).
      Chetki bo'shliqlar va ',' ajratuvchi ("05,08") ham qabul qilinadi. Aniqlanmasa None.
      Yil ko'rsatilmagan bo'lsagina yil taxmin qilinadi (o'tgan/kelasi yil buzilmaydi)."""
    if v is None or isinstance(v, bool):
        return None
    # 1) haqiqiy serial son (valueRenderOption o'zgarsa yoki katak date-tipli bo'lmasa)
    if isinstance(v, (int, float)):
        return _serial_to_date(v)
    s = str(v).strip()
    if not s:
        return None
    s = s.replace(",", ".")              # "05,08" → "05.08"
    m = ISO_RE.match(s)                  # 2026-07-06
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = DDMMYYYY_RE.match(s)             # 06.07.2026 / 06/07/26
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 2000
        return _safe_date(yy, mm, dd)
    m = DDMM_RE.match(s)                 # 06.07 (yilsiz → joriy yil / tab oyiga eng yaqin)
    if m:
        return _yilsiz_sana(int(m.group(1)), int(m.group(2)), today, ref)
    if SERIAL_RE.match(s):              # "45874" (toza raqamli satr — serial)
        return _serial_to_date(s)
    return None


def _col(header, *needles):
    """Avval aniq (norm==needle), keyin substring moslik."""
    normed = [fetchmod.norm(h) for h in header]
    for nd in needles:
        for i, n in enumerate(normed):
            if n == nd:
                return i
        for i, n in enumerate(normed):
            if n and nd in n:
                return i
    return None


def _status(v):
    n = fetchmod.norm(v)
    if "qilindi" in n or "✅" in str(v):
        return "paid"
    if "pauza" in n or "⏸" in str(v):
        return "pauza"
    if "ketdi" in n or "⛔" in str(v):
        return "ketdi"
    return "pending"


STATUS_LABEL = {"paid": "Undirildi ✅", "pauza": "Pauza ⏸", "ketdi": "Ketdi ⛔",
                "pending": "Kutilmoqda"}


def is_unpaid(r):
    """YAGONA undirilmagan-filtr (summary, full_report, pm_push, PDF, dashboard
    — bitta manba): «Summa» (D, qolgan qarz) > 0 va holat «To'lov qilindi»/
    «Ketdi» emas (Pauza so'ralaveradi). «Aktive Summary» — OLDINDAN to'lagan
    obuna mijozlari puli, SO'RALMAYDI (is_active_only)."""
    return r["holat"] not in ("paid", "ketdi") and r["qoldiq"] > 0


def is_active_only(r):
    """Aktiv obuna qatori: Summa bo'sh/0, lekin Aktive Summary > 0 — pul
    so'ralmaydi, faqat ma'lumot (ega jamlamasi/PDF'dagi alohida blok)."""
    return r["holat"] not in ("paid", "ketdi") and r["qoldiq"] <= 0 and r["aktiv"] > 0


def _name_key(name):
    """Loyiha nomini solishtirish kaliti — bo'shliq/registr farqiga chidamli."""
    return " ".join(fetchmod.norm(name).split())


# ---- O'tgan oy → joriy oy (va joriy → keyingi) moslash -----------------------

FUZZY_MIN = 0.85
QAROR_FAYL = BASE / "undiruv_qaror.json"


def _ixcham(name):
    """Fuzzy moslik kaliti: faqat harf va raqam («Mercedes-benz» = «Mercedes benz»)."""
    return "".join(ch for ch in fetchmod.norm(name) if ch.isalnum())


def _raqamlar(name):
    """Nomdagi raqamlar ketma-ketligi («Chorvoq hills 2» → ('2',)) — filial/raqam farqi."""
    return tuple(re.findall(r"\d+", fetchmod.norm(name)))


def nom_ball(a, b):
    """Ikki loyiha nomining o'xshashligi 0..1. Aynan (ixcham) — 1.0; biri ikkinchisining
    boshi (≥4 belgi) — 0.9 («Stirka»/«Stirkauz», «Rivo»/«Rivo water», «FTTI univercity»/
    «FTTI»); aks holda difflib. Real juftlar (29.09, 17 ta bir PM'li — hammasi haqiqiy nom
    o'zgarishi, 5 tasi butun so'z qo'shilishi/tushishi): «Bosimov shcool»~«Bosimov School»
    0.92, «Marvid textile»~«Mavrid textil» 0.89. «YEC»~«YEC gilam» — 3 belgi, prefiks emas.
    Himoya (review M3): raqami farqli nomlar («Chorvoq hills 1»/«…2», «Mb city»/«Mb city 2»)
    — 0 (boshqa filial). Butun so'z farqi RAD ETILMAYDI (haqiqiy o'zgarishlarni uzib, qarzni
    ogohlantirishsiz ikki marta so'ratardi) — o'rniga «ko'chirildi» faqat summa AYNAN teng
    (yoki ega qarori) bo'lsa, «yopildi» esa faqat aynan nomda; egaga «A → B» ko'rsatiladi."""
    x, y = _ixcham(a), _ixcham(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if _raqamlar(a) != _raqamlar(b):
        return 0.0
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    if len(short) >= 4 and long_.startswith(short):
        return 0.9
    return difflib.SequenceMatcher(None, x, y).ratio()


def _pm_kalit(pm):
    return "".join(ch for ch in fetchmod.norm(pm or "") if ch.isalnum())


def _juftla(prev_rows, cur_rows, faqat):
    """O'tgan oy qatorlarini joriy oy qatorlariga 1:1 juftlaydi.
    Qaytadi: ({prev_i: cur_j}, noaniq_prev_i, fuzzy_prev_i).

      1) aynan _name_key — avval TO'LANMAGAN (`faqat`), keyin to'langan o'tgan qatorlar
         (to'langan dublikat qator to'lanmagan qarzning juftini «egallab», o'sha qarz
         ikki marta so'ralmasin — review M4); nomzodlar ichida avval shu PM, keyin summa
         teng qator. To'langan qator ham juft egallaydi — fuzzy uni boshqa qarzga bog'lamasin;
      2) fuzzy (≥FUZZY_MIN) — faqat `faqat` qatorlar, juftsiz joriy qatorlar orasida va
         FAQAT PM («Ma'sul shaxs») bir xil bo'lsa (PM bo'sh — fuzzy yo'q). Global: eng
         yuqori ball birinchi. NOANIQ (juftlanmaydi, qoldiq so'raladi, egaga ⚠️): bitta
         o'tgan qatorga ikki nomzod YOKI bitta joriy qatorga ikki o'tgan qator deyarli teng
         (<0.02) ball bersa — noto'g'ri «ko'chirilgan» real qarzni PM'dan jim yashirardi (C5)."""
    pair, used, by_key = {}, set(), {}
    for j, c in enumerate(cur_rows):
        by_key.setdefault(_name_key(c["loyiha"]), []).append(j)
    faqat_set = set(faqat)
    aniq = []                            # aynan nom juftlari — GLOBAL eng yaxshisi birinchi (MN9)
    for i, r in enumerate(prev_rows):
        for j in by_key.get(_name_key(r["loyiha"]), []):
            c = cur_rows[j]
            aniq.append(((i not in faqat_set,                        # to'lanmagan o'tgan qator oldin
                          _pm_kalit(c["pm"]) != _pm_kalit(r["pm"]),   # keyin shu PM
                          round(c["qoldiq"]) != round(r["qoldiq"]),   # keyin summa teng
                          i, j), i, j))
    for _kalit, i, j in sorted(aniq):
        if i in pair or j in used:
            continue
        pair[i] = j
        used.add(j)
    cands = []
    for i in faqat:
        if i in pair:
            continue
        r = prev_rows[i]
        pm = _pm_kalit(r["pm"])
        if not pm or r.get("pm_missing"):
            continue
        for j, c in enumerate(cur_rows):
            if j in used or _pm_kalit(c["pm"]) != pm:
                continue
            b = nom_ball(r["loyiha"], c["loyiha"])
            if b >= FUZZY_MIN:
                cands.append((b, i, j))
    noaniq = set()
    for k in (1, 2):                    # 1: o'tgan qator bo'yicha, 2: joriy qator bo'yicha
        guruh = {}
        for b, i, j in cands:
            guruh.setdefault(i if k == 1 else j, []).append((b, i))
        for lst in guruh.values():
            lst.sort(reverse=True)
            if len(lst) > 1 and lst[0][0] - lst[1][0] < 0.02:
                noaniq.update(i for b, i in lst if lst[0][0] - b < 0.02)
    fuzzy = set()
    for b, i, j in sorted(cands, key=lambda x: -x[0]):
        if i in noaniq or i in pair or j in used:
            continue
        pair[i] = j
        used.add(j)
        fuzzy.add(i)
    return pair, sorted(noaniq), fuzzy


# ---- Ega qarorlari (undiruv_qaror.json) --------------------------------------

_QAROR_TURLARI = ("qoshilsin", "yangi_toliq", "hisobdan_chiqarilsin")
_QAROR_KESH = {"mtime": None, "data": [], "xato": []}


def _qaror_son(v):
    """Qaror summasi → butun son yoki None (None/bool/raqamsiz matn — yaroqsiz)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(v)
    if isinstance(v, str) and re.search(r"\d", v):
        return round(money(v))
    return None


def qaror_tekshir(items):
    """Qarorlar ro'yxati → (yaroqlilar, xato_izohlari). Yaroqsiz yozuv (dict emas, loyiha/
    yangi_tab yo'q, qaror noma'lum, summa son emas) TASHLANADI va egaga izoh bo'ladi —
    bitta qo'lda buzilgan qaror butun undiruv ko'rinishini (09:00 KPI, 09:30 push,
    dashboard) yiqitmasin (review M6/S3)."""
    if not isinstance(items, list):
        return [], ["undiruv_qaror.json: «qarorlar» ro'yxat emas — ega qarorlarisiz ishlandi"]
    ok, xato = [], []
    for n, q in enumerate(items, 1):
        d = q if isinstance(q, dict) else {}
        nom = d.get("loyiha")
        nom_ok = isinstance(nom, str) and bool(nom.strip())
        if d.get("qaror") == "hisobdan_chiqarilsin":
            # {"loyiha", "tab" (qoldiq turgan o'tgan oy tabi), "qoldiq" (qiymat qo'riqchisi)}
            tab, qol = d.get("tab"), _qaror_son(d.get("qoldiq"))
            if nom_ok and isinstance(tab, str) and tab.strip() and qol is not None and qol > 0:
                ok.append(dict(d, qoldiq=qol))
                continue
        else:
            tab = d.get("yangi_tab")
            oq, ys = _qaror_son(d.get("otgan_qoldiq")), _qaror_son(d.get("yangi_summa"))
            if (nom_ok and isinstance(tab, str) and tab.strip() and d.get("qaror") in _QAROR_TURLARI
                    and oq is not None and ys is not None and oq > 0 and ys >= 0):
                ok.append(dict(d, otgan_qoldiq=oq, yangi_summa=ys))
                continue
        xato.append(f"undiruv_qaror.json: {n}-qaror ({nom if isinstance(nom, str) else str(q)[:30]}) "
                    f"noto'g'ri — e'tiborsiz qoldirildi")
    return ok, xato


def kechish_ajrat(real_rows, tab, qlar, oy=""):
    """«hisobdan_chiqarilsin» — ega o'tgan oy qoldig'ini so'ramaslikka qaror qilgan
    (29.09: «Baaztruck kerak emas»). FAQAT o'tgan oy qoldiqlariga (korinish prev.real)
    qo'llanadi — joriy oy jamlamasiga (Kelishilgan/Qoldiq, reconcile) tegmaydi.
    Qo'riqchi: tab va qoldiq AYNAN qarordagidek (o'zgargan bo'lsa — qo'llanmaydi, izoh).
    Qaytadi: (qolgan_real, hisobdan_chiqarilganlar, izohlar)."""
    qolgan, chiqdi, izoh = list(real_rows), [], []
    for q in qlar or []:
        if q.get("qaror") != "hisobdan_chiqarilsin" or not _tab_mos(q.get("tab"), tab):
            continue
        nom, qol = str(q.get("loyiha") or ""), _qaror_son(q.get("qoldiq"))
        mos = [r for r in qolgan if nom_ball(nom, r["loyiha"]) >= FUZZY_MIN]
        aynan = [r for r in mos if round(r["qoldiq"]) == qol]
        if not aynan:
            if mos:
                izoh.append(f"{nom}: hisobdan chiqarish qarori eskirgan (jadvalda endi "
                            f"{', '.join(_fmt_usd(r['qoldiq']) for r in mos)}, qarorda {_fmt_usd(qol or 0)}) "
                            f"— qo'llanmadi, qoldiq so'ralmoqda")
            continue
        r = aynan[0]
        qolgan = [x for x in qolgan if x is not r]
        chiqdi.append(r)
        izoh.append(f"Ega qarori: {r['loyiha']} ({r['pm']}, {oy + ' ' if oy else ''}qoldig'i "
                    f"{_fmt_usd(r['qoldiq'])}) hisobdan chiqarilgan — PM'dan so'ralmaydi")
    return qolgan, chiqdi, izoh


def qarorlar():
    """undiruv_qaror.json — egasining summa farqli ko'chirishlar bo'yicha qarorlari
    (qaror_tekshir'dan o'tganlari). Fayl yo'q — [] (log). Buzuq JSON yoki yaroqsiz yozuv
    — tashlanadi, sababi qaror_xatolari() orqali EGAGA ko'rsatiladi (jim emas)."""
    try:
        mt = QAROR_FAYL.stat().st_mtime
    except FileNotFoundError:
        if _QAROR_KESH["mtime"] != "yoq":
            log(f"{QAROR_FAYL.name} yo'q — ega qarorlarisiz ishlanadi")
            # Egaga ham (S6): deploy'da fayl tushib qolsa, qarorlari jim qo'llanmay qolmasin.
            # Qaror kerak bo'lmasa ham fayl turadi: {"qarorlar": []}
            _QAROR_KESH.update(mtime="yoq", data=[], xato=[
                "undiruv_qaror.json topilmadi — ega qarorlari qo'llanmadi (summa farqli ko'chishlar "
                "alohida so'ralmoqda)"])
        return []
    if _QAROR_KESH["mtime"] != mt:
        try:
            raw = json.loads(QAROR_FAYL.read_text(encoding="utf-8"))
            data, xato = qaror_tekshir(raw.get("qarorlar", []) if isinstance(raw, dict) else None)
        except Exception as e:                       # noqa: BLE001
            data, xato = [], [f"undiruv_qaror.json o'qilmadi ({type(e).__name__}) — ega qarorlarisiz ishlandi"]
        for x in xato:
            log("XATO: " + x)
        _QAROR_KESH.update(mtime=mt, data=data, xato=xato)
    return _QAROR_KESH["data"]


def qaror_xatolari():
    """Qarorlar faylidagi yaroqsiz yozuvlar / o'qish xatosi — egaga izoh satrlari."""
    qarorlar()
    return list(_QAROR_KESH.get("xato") or [])


def _tab_mos(a, b):
    return bool(a) and bool(b) and fetchmod.norm(a) == fetchmod.norm(b)


def _qaror_top(qlar, r, cur_tab):
    """Shu tab (yangi_tab) va shu loyiha uchun ega qarori (yo'q — None)."""
    for q in qlar or []:
        if not _tab_mos(q.get("yangi_tab"), cur_tab):
            continue
        if nom_ball(q.get("loyiha", ""), r["loyiha"]) >= FUZZY_MIN:
            return q
    return None


def qaror_qoll(rows, tab, qlar, otgan_oy, otgan_rows=None):
    """«qoshilsin» qarorlarini QAROR TABI (yangi_tab) qatorlariga qo'llaydi — tab qaysi
    rolda o'qilishidan qat'i nazar (joriy, keyingi yoki O'TGAN oy): noyabrda oktabr
    «o'tgan oy» bo'lganda ham qo'shilgan $364 yo'qolmasin (review D4).
    Qaytadi: (rows NUSXASI, izohlar).

    Qator — qaror loyihasiga eng mos nom (nom_ball ≥ FUZZY_MIN). Qo'riqchi — qatorning
    KELISHILGAN summasi (Summa + Undirildi): to'lov kelishi qarorni eskirtirmaydi (M2):
      = yangi_summa              → jadvalga hali kiritilmagan: otgan_qoldiq qo'shiladi
                                    (qoldiq ham, kelishilgan ham); to'langan deb yozilgan
                                    bo'lsa-yu qoldiq qolsa — holat «pending» (so'raladi);
      = yangi_summa + otgan      → jadvalga kiritilgan: o'zgarmaydi;
      boshqa                     → qaror eskirgan: o'zgarmaydi + izoh (oddiy qoida).
    Ikkala qo'llangan holatda `qoshimcha` = {summa, oy, asl, jadvalda} — month_transition
    o'tgan oy qatorini shu orqali «ko'chirilgan» deb taniydi (to'lov bo'lsa ham).
    otgan_rows — qarorning MANBA oyi (yangi_tabdan oldingi oy) qatorlari. Qo'llash uchun
    u yerda to'lanmagan qoldiq AYNAN otgan_qoldiq bo'lishi shart (to'langan/o'zgargan —
    qo'shilmaydi). otgan_rows=None (manba tab o'qilmadi) — qo'llanmaydi, egaga halol izoh:
    tekshirilmagan qo'shish to'langan qarzni qayta so'ratardi (review MN1/DN1/MN2/SN2).
    «Ketdi» qatorga qo'shilmaydi; bir qatorga takroriy qaror bir marta (SN5)."""
    out = [dict(r) for r in rows]
    izoh = []
    for q in qlar or []:
        if q.get("qaror") != "qoshilsin" or not _tab_mos(q.get("yangi_tab"), tab):
            continue
        oq, ys = _qaror_son(q.get("otgan_qoldiq")), _qaror_son(q.get("yangi_summa"))
        nom = str(q.get("loyiha") or "")
        if oq is None or ys is None or not nom:
            continue
        nomzod = sorted(((nom_ball(nom, r["loyiha"]), j) for j, r in enumerate(out)), reverse=True)
        if not nomzod or nomzod[0][0] < FUZZY_MIN:
            izoh.append(f"{nom}: ega qarori «{tab}» tabida mos qator topmadi — qo'llanmadi")
            continue
        c = out[nomzod[0][1]]
        if c.get("qoshimcha"):
            izoh.append(f"{nom}: takroriy qaror (undiruv_qaror.json'da ikki marta) — bir marta qo'llandi")
            continue
        kel = round(c["qoldiq"] + c["undirildi"])
        if kel == ys + oq:
            c["qoshimcha"] = {"summa": oq, "oy": otgan_oy, "asl": ys, "jadvalda": True}
            continue                             # jadval tuzatilgan — jim muvaffaqiyat, eslatma kerak emas
        if kel != ys:
            izoh.append(f"{nom}: ega qarori eskirgan («{c['loyiha']}» jadvalda {_fmt_usd(kel)}, qarorda "
                        f"{_fmt_usd(ys)}) — qo'llanmadi, oddiy qoida ishladi")
            continue
        if otgan_rows is None:
            izoh.append(f"{nom}: ega qarori bugun qo'llanmadi — {otgan_oy} tabi o'qilmadi, "
                        f"{otgan_oy} qoldig'i {_fmt_usd(oq)} tekshirib bo'lmadi")
            continue
        otg = [r for r in otgan_rows if is_unpaid(r) and nom_ball(nom, r["loyiha"]) >= FUZZY_MIN]
        if not any(round(r["qoldiq"]) == oq for r in otg):
            bor = ", ".join(_fmt_usd(r["qoldiq"]) for r in otg) or "yo'q/to'langan"
            izoh.append(f"{nom}: ega qarori eskirgan ({otgan_oy} qoldig'i endi {bor}, qarorda "
                        f"{_fmt_usd(oq)}) — {otgan_oy} qoldig'i qo'shilmadi, oddiy qoida ishladi")
            continue
        if c["holat"] == "ketdi":
            izoh.append(f"{nom}: «{c['loyiha']}» ketgan deb yozilgan — qaror qo'llanmadi; {otgan_oy} "
                        f"qoldig'i {_fmt_usd(oq)} alohida so'ralaveradi (u ham ketgan bo'lsa, {otgan_oy} "
                        f"tabida ham belgilang)")
            continue
        c["qoldiq"] += oq
        c["kelishilgan"] = c.get("kelishilgan", 0) + oq
        if c["holat"] == "paid" and c["qoldiq"] > 0:
            c["holat"] = "pending"               # yangi oy summasi to'langan, qo'shilgan qoldiq — yo'q
        c["qoshimcha"] = {"summa": oq, "oy": otgan_oy, "asl": ys, "jadvalda": False}
        izoh.append(f"{nom}: qaror jadvalga kiritilmagan — «{c['loyiha']}» jadvalda {_fmt_usd(ys)}, bot "
                    f"{otgan_oy} qoldig'i {_fmt_usd(oq)} bilan {_fmt_usd(ys + oq)} deb hisoblaydi. "
                    f"Jadvalda {_fmt_usd(ys + oq)} qilinsa, bu eslatma yo'qoladi")
    return out, izoh


def month_transition(prev_rows, cur_rows, cur_tab=None, qlar=None, prev_oy="", yangi_min=None,
                     prev_oqildi=True):
    """O'tgan oyning to'lanmagan qatorlarini joriy oy tabi bilan solishtiradi.

    Qaytadi dict:
      cur_rows — joriy qatorlar NUSXASI («qoshilsin» qarori qo'llangan — qaror_qoll);
      real     — hali so'raladigan o'tgan-oy qoldiqlari;
      closed   — joriyda to'langan/ketgan yoki undirildi>0 (o'tgan oy tabi tuzatilmagan).
                 FAQAT nomi aynan mos juftda — fuzzy juft (boshqa loyiha bo'lishi mumkin)
                 to'langan bo'lsa qarz yopilmaydi, so'raladi + noaniq (review M3);
      moved    — joriy oyga KO'CHIRILGAN: summa AYNAN teng yoki ega qarori bor. PM'dan
                 IKKINCHI marta so'ralmaydi (egasining konvensiyasi, 01.09 va 29.09:
                 yangi oy tabini ochganda to'lanmagan qoldiqni ko'chiradi). Ega qarori
                 to'lov tekshiruvidan OLDIN qaraladi — qo'shilgan qoldiq joriy qatorda
                 yashaydi, joriy qatorga to'lov kelsa ham o'tgan qator yopilib ketmaydi (M2);
      farqli   — joriyda bor, summa boshqa, qaror yo'q → real'da ham turadi (so'raladi) +
                 egaga «qaror kerak»;
      noaniq   — ikki o'xshash nomzod yoki fuzzy juft to'langan → real'da turadi;
                 `_noaniq` — egaga sabab;
      izoh     — qaror holati bo'yicha egaga satrlar (eskirgan/jadvalda/qo'llangan);
      juft     — {prev_i: cur_j} (keyingi bosqichda ishlatilmagan qatorlar uchun).
    moved/closed qatorlarida `_i` (prev indeksi) va `_kochish` (turi, cur nomi/summa/muddat).

    yangi_min — faqat KEYINGI oyga qarashda: joriy (keyingi oy) qatori muddati shu
    sanadan oldin bo'lmasa ko'chirish/yopilish qabul qilinmaydi. Ko'chirilgan qoldiq
    yangi oy muddatini oladi; nusxa/shablon tab (eski muddat yoki sanasiz) joriy
    qarzni yashirib qo'ymasin.
    prev_oqildi=False — o'tgan oy tabi o'qilmadi (prev_rows bo'sh): ega qarori «qoldiq
    to'langan» deb noto'g'ri eskirmasin, qo'llanmaydi + halol izoh."""
    q_ok, _xato = qaror_tekshir(list(qlar or []))
    cur, izoh = qaror_qoll(cur_rows, cur_tab, q_ok, prev_oy, otgan_rows=prev_rows if prev_oqildi else None)
    faqat = [i for i, r in enumerate(prev_rows) if is_unpaid(r)]
    pair, noaniq_i, fuzzy_i = _juftla(prev_rows, cur, faqat)
    out = {"cur_rows": cur, "real": [], "closed": [], "moved": [], "farqli": [], "noaniq": [],
           "izoh": izoh, "juft": pair}
    for i in faqat:
        r = prev_rows[i]
        j = pair.get(i)
        if j is None:
            out["real"].append(r)
            if i in noaniq_i:
                out["noaniq"].append(dict(r, _noaniq="ikki o'xshash nom"))
            continue
        c = cur[j]
        kel_c = round(c["qoldiq"] + c["undirildi"])
        meta = {"cur_loyiha": c["loyiha"], "cur_summa": round(c["qoldiq"]), "cur_kelishilgan": kel_c,
                "muddat": c["muddat"], "tab": cur_tab, "oy": prev_oy}
        yangi_ok = yangi_min is None or (c["muddat"] is not None and c["muddat"] >= yangi_min)
        rq, cq = round(r["qoldiq"]), round(c["qoldiq"])
        q = _qaror_top(q_ok, r, cur_tab)
        k = c.get("qoshimcha")
        turi = None
        if k and round(k.get("summa", -1)) == rq:
            turi = "qaror_jadvalda" if k.get("jadvalda") else "qaror_qoshildi"
        elif (q is not None and q.get("qaror") == "yangi_toliq" and rq == q["otgan_qoldiq"]
              and kel_c == q["yangi_summa"]):
            turi = "qaror_yangi_toliq"
        if turi:
            if yangi_ok:
                out["moved"].append(dict(r, _i=i, _kochish=dict(meta, turi=turi, sabab=q.get("sabab", "") if q else "")))
            else:
                out["real"].append(r)
            continue
        if c["holat"] in ("paid", "ketdi") or c["undirildi"] > 0:
            if i in fuzzy_i:
                out["real"].append(r)
                out["noaniq"].append(dict(r, _noaniq=f"nomi aynan mos emas: «{c['loyiha']}» "
                                                     f"{cur_tab or 'joriy tab'}da to'langan/ketgan"))
            elif yangi_ok:
                out["closed"].append(dict(r, _i=i, _kochish=dict(meta, turi="yopilgan")))
            else:
                out["real"].append(r)
            continue
        if not is_unpaid(c) or not yangi_ok:
            out["real"].append(r)
            continue
        if cq == rq:
            # summa aynan teng — ko'chirilgan (eskirgan qaror bo'lsa ham: aks holda bir xil
            # qarz ikki marta so'ralardi — review MN6/SN4)
            out["moved"].append(dict(r, _i=i, _kochish=dict(meta, turi="aynan")))
            continue
        out["real"].append(r)
        out["farqli"].append(dict(r, _i=i, _kochish=dict(meta, turi="farqli")))
        if q is not None and q.get("qaror") == "yangi_toliq":
            out["izoh"].append(f"{q.get('loyiha')}: ega qarori eskirgan (jadvalda endi {_fmt_usd(rq)} → "
                               f"{_fmt_usd(kel_c)}, qarorda {_fmt_usd(q['otgan_qoldiq'])} → "
                               f"{_fmt_usd(q['yangi_summa'])}) — o'tgan qoldiq ham so'ralmoqda")
    return out


def carryover_filter(prev_rows, cur_rows, cur_tab=None, qlar=None):
    """Orqaga moslik o'rovchisi: (haqiqiy_carryover, yopilganlar, ko'chirilganlar).
    To'liq tasnif (farqli/noaniq/izoh, qaror bo'yicha tuzatilgan joriy qatorlar) —
    month_transition. Ko'chirish endi imlo farqiga chidamli (PM himoyasi bilan) va
    summa farqli holatda egasining qarori (undiruv_qaror.json) hisobga olinadi."""
    t = month_transition(prev_rows, cur_rows, cur_tab, qlar)
    return t["real"], t["closed"], t["moved"]


def parse_rows(vals, today, ref=None):
    """Tab qiymatlari → [{loyiha, pm, qoldiq, undirildi, aktiv, kelishilgan,
    muddat: date|None, holat}]. Jami/summary qatorlari kirmaydi.
    ref — tab oyining 1-kuni: yilsiz «DD.MM» sanalar shu oyga eng yaqin yil bilan
    o'qiladi (yil almashuvi; berilmasa joriy yil — eski xulq)."""
    h = diffmod.detect_header(vals)
    header = [str(x) for x in (vals[h] if vals else [])]
    c_name = _col(header, "nomi")
    c_pm = _col(header, "shaxs")
    c_left = _col(header, "summa")
    c_paid = _col(header, "undirildi")
    c_active = _col(header, "aktive")
    c_due = _col(header, "final")
    c_status = _col(header, "xolati")
    # «Lose summa» — ketgan loyiha zarari. AYNAN shu nomni oldin qidiramiz, aks
    # holda «summa» substring'i «Lose summa»/«Aktive Summary»ga tushib ketardi
    # (c_left «Summa»ni aniq-tenglik bilan oladi — bu ustunga tegmaymiz).
    c_lose = _col(header, "lose summa", "lose")
    if c_name is None or c_paid is None:
        return []
    rows = []
    for row in vals[h + 1:]:
        get = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""
        first = fetchmod.norm(get(0))
        name = get(c_name)
        if first == "jami" or fetchmod.norm(name).startswith("ehtimoli"):
            break  # jadval tugadi — pastda yig'indi bloklari
        if not name:
            continue
        qoldiq, undirildi, aktiv = money(get(c_left)), money(get(c_paid)), money(get(c_active))
        # KONVENSIYA (2026-07-30, 27/27 paid qator isbotladi): «Summa» (D) =
        # QOLGAN QARZ, «Undirildi» (E) = shu paytgacha yig'ilgani, Bitim = D+E.
        # So'raladigan qoldiq = D (AYIRMASIZ). E'ni ayirish (eski qoldiq_net)
        # noto'g'ri edi — iyul'da har qatorni ikki marta ayirar edi.
        status_raw = get(c_status)
        lose = money(get(c_lose))
        holat = _status(status_raw)
        # QARZI YO'Q (Summa bo'sh/0), lekin «Lose summa» to'ldirilgan qator — ketgan.
        # Sheet «Lose pul»ni =SUM(H) bilan status matnidan QAT'I NAZAR sanaydi; 2026
        # tablarida status sabab bilan yoziladi («Mijoz yo'q bo'lib qoldi», «Puli
        # yo'q», «Sotuv etapidan o'tmagan»...) va _status ularni tanimasdi: 29.09 da
        # «Yo'qotilgan» bloki $3 500, sheet $19 400 edi; Li auto avgust qoldig'i
        # «54 kun o'tdi» deb PM'dan so'ralardi (sentabr qatori «ketgan» tanilmagani uchun).
        # Summa > 0 VA Lose > 0 (status «ketdi» emas) — NOANIQ: qarz so'ralaveradi va
        # lose_summary ogohlantiradi (avgust Oqsaroy/Savy holati, 09.08 qarori — C5).
        if lose > 0 and holat != "paid" and money(get(c_left)) <= 0:
            holat = "ketdi"
        pm_val = get(c_pm)  # c_pm=None (ustun yo'q) yoki katak bo'sh → ""
        rows.append({
            "loyiha": name,
            "pm": pm_val or "—",
            # PM aniqlanmagan qator PM'ga yo'naltirilmasin (jim "—" ga ketmasin);
            # pm_col_present: tabda umuman "Ma'sul shaxs" ustuni bormi (avgust yo'q)
            "pm_missing": not pm_val,
            "pm_col_present": c_pm is not None,
            "qoldiq": qoldiq,
            "qoldiq_raw": get(c_left),  # jamlamada "Summa son emas" hisobi uchun
            "undirildi": undirildi,
            "aktiv": aktiv,
            # «Lose summa» — ketgan (status «Ketdi») loyiha zarari. D/E qoldiq
            # mantiqidan MUSTAQIL alohida ustun; lose_summary() shundan o'qiydi.
            # lose_col_present: tabda umuman «Lose summa» ustuni bormi (eski oy
            # tablarida yo'q — lose_summary blokni butunlay yashiradi, pm_missing
            # naqshi kabi). Aks holda ustunsiz tabda «summa yozilmagan» yolg'oni.
            "lose": lose,
            "lose_raw": get(c_lose),
            "lose_col_present": c_lose is not None,
            # Kelishilgan = Summa(qoldiq) + Undirildi. Aktiv unga KIRMAYDI —
            # u oldindan to'langan obuna (alohida ma'lumot ustuni).
            "kelishilgan": qoldiq + undirildi,
            # Status katagi bo'sh (paid/ketdi belgilanmagan) — D>0 bo'lsa qarz
            # sanaladi (kam ko'rsatishdan xavfsizroq), lekin egaga ⚠️ belgi.
            "status_blank": not status_raw,
            "muddat": parse_due(get(c_due), today, ref),
            "muddat_raw": get(c_due),
            "holat": holat,
            "holat_matn": status_raw,
        })
    return rows


# ---- Oy-tab tanlash (mustahkam: imlo alias + yil suffiks + ambiguity) ----

# Egaga ko'rsatiladigan oxirgi tab-ogohlantirishi (ambiguity/fallback). run_daily
# fetch'dan keyin darrov consume_tab_note() bilan o'qib, jamlamaga qo'shadi.
_TAB_NOTE = ""


def consume_tab_note():
    global _TAB_NOTE
    n, _TAB_NOTE = _TAB_NOTE, ""
    return n


def _set_tab_note(n):
    global _TAB_NOTE
    _TAB_NOTE = n


def _month_spellings(month):
    """Oyning barcha imlo variantlari (sentyabr↔sentabr, oktyabr↔oktabr)."""
    m = fetchmod.norm(month)
    sp = {m}
    for k, v in getattr(fetchmod, "MONTH_ALIASES", {}).items():
        nk, nv = fetchmod.norm(k), fetchmod.norm(v)
        if m in (nk, nv):
            sp.update({nk, nv})
    return sp


def _tab_matches_month(norm_title, month):
    """norm_title 'undiruv <oy>' bilan boshlanadimi (bo'sh/'('/oxiri chegarada)."""
    for s in _month_spellings(month):
        p = f"undiruv {s}"
        if norm_title == p or norm_title.startswith(p + " ") or norm_title.startswith(p + "("):
            return True
    return False


_YEAR_RE = re.compile(r"20\d{2}")
# Suffikssiz «Undiruv <oy>» tablari — 2025-08…2026-07 ARXIVI. Shu oydan boshlab har oy
# tabi (JORIY oy ham) faqat yil suffiksi bilan qidiriladi: 01.11 da «noyabr(2026)» hali
# ochilmagan bo'lsa, bot 2025 arxivini jimgina «joriy oy» deb o'qib, oktabr qarzlarini
# arxivdagi to'langan qatorlarga qarab yopib yubormasin (review M8/D5/S4).
QATIY_DAN = date(2026, 8, 1)


def qatiy_oy(oy_1):
    """Oy (1-kuni) uchun faqat yil suffiksli tab qidirilsinmi."""
    return oy_1 >= QATIY_DAN


def rank_month_tabs(titles, month, today=None, year=None, suffikssiz=True):
    """'undiruv <oy>' ga mos tab nomlari — eng mos birinchi. YIL QOIDASI:
      (a) joriy yil suffiksi ('(2026)') ENG USTUN,
      (b) suffikssiz aynan 'undiruv <oy>' — keyingi,
      (c) BOSHQA yil suffiksli (2025/2024 arxiv) — HECH QACHON (kandidat emas),
      (d) qolgan tenglikda eng ko'p undirilmagan — fetch_live_month hal qiladi.
    Sabab: 'Undiruv avgust' aynan tenglikka mos, lekin u 2025 arxivi bo'lishi mumkin —
    joriy yil suffiksli tab uni yutib o'tishi shart.

    year — MAQSAD oyning yili (berilmasa today.year): yanvarda o'tgan oy «dekabr(2026)»,
    dekabr oxirida keyingi oy «yanvar(2027)» — today.year bilan ular «boshqa yil
    arxivi» deb chetlanardi va suffikssiz arxiv jim o'qilardi.
    suffikssiz=False — faqat yil suffiksli tab (o'tgan/keyingi oy uchun: suffikssiz
    tablar 2025-08…2026-07 arxivi, keyingi oy o'rniga o'tgan yilniki o'qilmasin)."""
    today = today or date.today()
    yr = str(year or today.year)
    scored = []
    for t in titles:
        nt = fetchmod.norm(t)
        if not _tab_matches_month(nt, month):
            continue
        years = _YEAR_RE.findall(nt)
        if years and yr not in years:
            continue                        # boshqa yil arxivi — HECH QACHON tanlanmaydi
        if not years and not suffikssiz:
            continue                        # qat'iy rejim: faqat yil suffiksli tab
        prio = 0 if yr in years else 1      # (a) joriy-yil suffiksi → (b) suffikssiz
        # Bir xil ustunlikda KANONIK nom («undiruv oktabr(2026)», bo'shliqqa chidamli) birinchi:
        # «Undiruv oktabr (2026) shablon» kabi nusxa/shablon tab tanlanmasin (review D10)
        ixcham = re.sub(r"\s+", "", nt)
        kanonik = any(ixcham in (f"undiruv{s}({yr})", f"undiruv{s}") for s in _month_spellings(month))
        scored.append((prio, not kanonik, len(nt), nt, t))
    scored.sort(key=lambda x: x[:4])
    return [x[4] for x in scored]


def _latest_month_tab(titles, today):
    """Joriy oy tabi topilmaganda — mavjud eng so'nggi (≤ joriy oy) 'undiruv <oy>'
    tabi. Boshqa yil arxivlari (2025/…) chetlab o'tiladi (hech qachon fallback emas)."""
    today = today or date.today()
    yr, cur_idx = str(today.year), today.month
    best = None  # (idx, title)
    for t in titles:
        nt = fetchmod.norm(t)
        if not nt.startswith("undiruv "):
            continue
        years = _YEAR_RE.findall(nt)
        if years and yr not in years:
            continue                        # boshqa yil arxivi — fallback ham emas
        for idx, mon in enumerate(fetchmod.MONTHS, start=1):
            if _tab_matches_month(nt, mon):
                cand_idx = idx if idx <= cur_idx else idx - 12  # kelasi oy → o'tmishga
                if best is None or cand_idx > best[0]:
                    best = (cand_idx, t)
                break
    return best[1] if best else None


def find_tab(snap, today=None, month=None, year=None, qat_iy=False):
    """Snapshot'dagi "Undiruv <oy>" range kaliti (topilmasa None). month berilmasa
    joriy oy. Tanlash qoidasi jonli yo'l bilan BIR XIL (rank_month_tabs): boshqa yil
    arxivi hech qachon, yil suffiksi ustun, qat'iy rejimda suffikssiz ham yo'q."""
    month = month or fetchmod.current_month_name(today)
    by_title = {}
    for rng in snap.get("ranges", {}):
        by_title.setdefault(fetchmod.tab_of_range(rng), rng)
    ranked = rank_month_tabs(list(by_title), month, today, year=year, suffikssiz=not qat_iy)
    return by_title[ranked[0]] if ranked else None


def smm_sheet_id():
    """Undiruv manba sheet'i (pm_kpi=false) id'si — jonli o'qish uchun."""
    for s in fetchmod.load_config(include_qa_only=True):
        if not s.get("pm_kpi", True):
            return s["id"]
    return None


def fetch_live_month(month_name, today, year=None, qat_iy=False, ref=None):
    """JONLI: SMM sheet'dan "Undiruv <month_name>" tabini bevosita o'qiydi
    (readonly gspread). Qaytadi: (tab, rows) yoki (None, []). Xato — chaqiruvchi
    ushlaydi (snapshot fallback). consume_tab_note() bilan ega ogohlantirishini oladi.
    Mustahkam: imlo/yil-suffiks; >1 mos → yil+eng-ko'p-undirilmagan bo'yicha tanlaydi
    va ega uchun WARNING qoldiradi; joriy oy topilmasa — eng so'nggi oy tabi (fallback).
    qat_iy=True (o'tgan/keyingi oy) — faqat year suffiksli tab, FALLBACK YO'Q: aks holda
    «keyingi oy» o'rniga joriy oy tabi qaytib, qarz ikki karra sanalardi."""
    _set_tab_note("")
    sid = smm_sheet_id()
    if not sid:
        return None, []
    gc = fetchmod.gclient()
    sh = gc.open_by_key(sid)
    titles = [w.title for w in sh.worksheets()]

    def _read(tab):
        ranges = fetchmod.fetch_ranges(sh, [fetchmod.tab_range(tab)], "undiruv-live")
        vals = next(iter(ranges.values())).get("values", [])
        return parse_rows(vals, today, ref)

    matched = rank_month_tabs(titles, month_name, today, year=year, suffikssiz=not qat_iy)
    if not matched and qat_iy:
        return None, []
    if qat_iy and len(matched) > 1:
        # Qat'iy rejimda (yil suffiksli tablar) tanlov snapshot yo'li (find_tab) bilan
        # AYNAN bir xil: rank tartibi — kanonik nom birinchi. «Eng ko'p undirilmagan»
        # qoidasi shablon/nusxa tabni tanlab, joriy qarzni «ko'chirilgan» deb
        # yashirishi mumkin edi (review D10). Ortiqcha tab — egaga ogohlantirish.
        note = (f"⚠️ «{month_name}({year or today.year})» oyiga {len(matched)} tab bor — "
                f"«{matched[0]}» o'qildi; boshqalari e'tiborsiz: "
                + ", ".join(f"«{t}»" for t in matched[1:]) + " (nusxa bo'lsa o'chiring/nomini o'zgartiring)")
        log(note)
        _set_tab_note(note)
        return matched[0], _read(matched[0])
    if not matched:
        # Joriy oy tabi umuman yo'q — eng so'nggi mavjud oy tabiga tushamiz (WARNING)
        fb = _latest_month_tab(titles, today)
        if not fb:
            return None, []
        note = (f"⚠️ «Undiruv {month_name}» tabi topilmadi — vaqtincha eng so'nggi "
                f"«{fb}» tabidan o'qildi. Joriy oy tabini oching/nomlang.")
        log(note)
        _set_tab_note(note)
        return fb, _read(fb)
    if len(matched) == 1:
        return matched[0], _read(matched[0])
    # >1 mos: hammasini o'qib, (yil ustun, keyin eng ko'p undirilmagan) tanlaymiz
    cands = []
    for tab in matched:
        rows = _read(tab)
        cands.append((tab, rows, str(year or (today or date.today()).year) in fetchmod.norm(tab),
                      sum(1 for r in rows if is_unpaid(r))))
    cands.sort(key=lambda c: (not c[2], -c[3]))
    best = cands[0]
    others = "; ".join(f"«{c[0]}» ({c[3]} undirilmagan)" for c in cands[1:])
    # Yil-qoidasi arxivni allaqachon chetladi; bu — shaffoflik uchun ma'lumot
    # (egaga "o'chir" deb turtki EMAS — arxiv tab ataylab saqlanishi mumkin).
    note = (f"ℹ️ «{month_name}» oyiga {len(matched)} tab bor — joriy yil «{best[0]}» "
            f"tanlandi ({best[3]} undirilmagan). Boshqa: {others} (e'tiborsiz qoldirildi).")
    log(note)
    _set_tab_note(note)
    return best[0], best[1]


def oy_ofset(today, k):
    """(oy_nomi, yil, oyning_1_kuni) — k oy siljish (dekabr +1 → yanvar, yil +1)."""
    y, m = divmod(today.year * 12 + today.month - 1 + k, 12)
    return fetchmod.MONTHS[m], y, date(y, m + 1, 1)


def oy_oxiriga_kun(today):
    """Oyning oxirgi kunigacha qolgan kun (30.09 → 0, 25.09 → 5)."""
    return (oy_ofset(today, 1)[2] - timedelta(days=1) - today).days


def oldinga_qarash_faolmi(today):
    """Keyingi oy tabiga faqat oy OXIRIDA qaraladi (≤ PUSH_DUE_DAYS kun qolganda) —
    ega tanlovi (29.09): «5 kun oldin». Oy o'rtasida emas: erta ochilgan keyingi oy
    tabidagi oylik to'lov joriy qarz bilan teng bo'lsa, joriy qarz noto'g'ri
    «ko'chirilgan» bo'lib PM'dan yashirinardi."""
    return oy_oxiriga_kun(today) <= PUSH_DUE_DAYS


def _oy_oqi(month, year, ref, today, day, prefer_live, qat_iy, notes):
    """Bitta oy tabi: (tab, rows, source) — source ∈ live / snapshot / none / xato.
    Jonli-birinchi, xato/topilmasa snapshot. Jonli o'qish XATO berib, snapshot'da ham
    tab bo'lmasa — «xato» + egaga izoh: «tab hali yo'q» degan yolg'on o'rniga (A2, C4/S5)."""
    xato = ""
    if prefer_live:
        try:
            tab, rows = fetch_live_month(month, today, year=year, qat_iy=qat_iy, ref=ref)
            n = consume_tab_note()
            if n:
                notes.append(n)
            if tab is not None:
                return tab, rows, "live"
            log(f"jonli: «Undiruv {month}({year})» tabi topilmadi — snapshot fallback")
        except Exception as e:                   # noqa: BLE001
            xato = f"{type(e).__name__}: {str(e)[:80]}"
            log(f"jonli o'qish xato ({month} {year}): {type(e).__name__}: {str(e)[:120]} — snapshot fallback")
    for snap in diffmod.load_day(day)[0].values():
        if snap.get("pm_kpi", True):
            continue
        rng = find_tab(snap, today, month=month, year=year, qat_iy=qat_iy)
        if rng:
            vals = snap["ranges"][rng].get("values", [])
            return fetchmod.tab_of_range(rng), parse_rows(vals, today, ref), "snapshot"
    if xato:
        notes.append(f"⚠️ «Undiruv {month}({year})» tabi o'qilmadi (jonli xato: {xato}) — "
                     f"snapshot'da ham yo'q")
        return None, [], "xato"
    return None, [], "none"


# korinish() keshi — FAQAT kesh=True chaqiruvlar uchun (UNDIRUV_KESH=1: run.sh → analyze subprocess'ida
# report_block va report.json AYNAN bir ko'rinishdan chiqsin). Uzoq yashaydigan bot/
# scheduler jarayonida (09:30 push, /pm_push, /test_undiruv, dashboard) kesh YO'Q: ega
# sheet'ni tuzatib darrov qayta ishga tushirsa, eski ma'lumot «jonli» deb PM'ga ketmasin
# (review C1/M7/D1/S1). TTL analyze'dagi Claude chaqiruvi (≤600 s) oralig'ini qoplaydi.
_VIEW_KESH = {}
_VIEW_TTL = 1800


def korinish(today=None, day=None, prefer_live=True, qlar=None, kesh=False):
    """Undiruv «ko'rinishi» — YAGONA yig'uvchi (C3). Kunlik KPI bloki (summary/
    report_block), 09:30 PM push va ega PDF, /test_undiruv, /pm_push test va dashboard
    shu natijadan o'qiydi — bir ertalab turli joyda turli raqam chiqmasin.

    Qaytadi: {tab, rows, source, oy, prev{tab, rows, source, oy, real, closed, moved,
    farqli, noaniq, izoh}, keyingi{…}|None, notes, data_source}.
      rows — JORIY oy qatorlari: ega qarori bo'yicha qo'shilgan qoldiq bilan
             (`qoshimcha`) va oy oxirida keyingi oy tabiga ko'chgan/yopilganlari
             `keyingi_oyga` belgisi bilan (ular eski muddat bilan SO'RALMAYDI).
      prev.real — hali so'raladigan o'tgan oy qoldiqlari (oy oxirida keyingi oy tabiga
             yozilganlari ham `keyingi_oyga` belgisi oladi — ikki marta so'ralmaydi).
      keyingi — oy oxirida (oldinga_qarash_faolmi): keyingi oy tabi, muddati
             ≤PUSH_DUE_DAYS qolgan to'lanmaganlar (`yaqin`, faqat keyingi oy sanalari),
             ko'chgan/yopilganlar, eski (joriy oy) muddatli nusxa qatorlar, 1-sanadan
             kuzatuvdan tushadigan o'tgan oy qoldiqlari (`tushadi`).
      notes — EGAGA izohlar (tab topilmadi/o'qilmadi, qaror holati, ogohlantirishlar).
    Barcha oy tablari (joriy ham, QATIY_DAN dan) — qat'iy: yil suffiksli tab, arxiv yo'q.
    kesh=True — faqat 09:00 analyze juftligi uchun (yuqoridagi izohga qarang)."""
    today = today or (date.fromisoformat(day) if day else date.today())
    day = day or today.isoformat()
    kalit = (today.isoformat(), day, bool(prefer_live))
    if kesh and qlar is None:
        hit = _VIEW_KESH.get(kalit)
        if hit and time.time() - hit[0] < _VIEW_TTL:
            return hit[1]
    if qlar is None:
        q, notes = qarorlar(), qaror_xatolari()
    else:
        q, notes = qaror_tekshir(list(qlar))
    cur_m, cur_y, cur_1 = oy_ofset(today, 0)
    prev_m, prev_y, prev_1 = oy_ofset(today, -1)
    prev2_m, prev2_y, prev2_1 = oy_ofset(today, -2)
    next_m, next_y, next_1 = oy_ofset(today, 1)
    tab, rows, source = _oy_oqi(cur_m, cur_y, cur_1, today, day, prefer_live, qatiy_oy(cur_1), notes)
    ptab, prows, psrc = (None, [], "none")
    if tab is None:
        if source == "xato":
            notes.append(f"⚠️ Joriy oy tabi «Undiruv {cur_m}({cur_y})» o'qilmadi (xato) — undiruv "
                         f"tekshirilmadi; keyinroq /pm_push force yoki /test_undiruv bilan qayta urining")
        else:
            notes.append(f"⚠️ Joriy oy tabi «Undiruv {cur_m}({cur_y})» topilmadi — undiruv tekshirilmadi. "
                         f"Yangi oy tabini oching (nomi aynan: «Undiruv {cur_m}({cur_y})»)")
    else:
        ptab, prows, psrc = _oy_oqi(prev_m, prev_y, prev_1, today, day, prefer_live, True, notes)
        if ptab is None:
            notes.append(f"⚠️ O'tgan oy tabi «Undiruv {prev_m}({prev_y})» "
                         + ("o'qilmadi (xato)" if psrc == "xato" else "topilmadi")
                         + " — o'tgan oy qoldiqlari tekshirilmadi")
        elif any(x.get("qaror") == "qoshilsin" and _tab_mos(x.get("yangi_tab"), ptab) for x in q):
            # Qaror tabi «o'tgan oy»ga aylangan (noyabrda oktabr): qo'shilgan qoldiq saqlansin,
            # lekin FAQAT manba oyi (sentabr) tekshirilgan holda — u yerda qoldiq to'langan
            # bo'lsa qayta so'ralmasin (review MN1/DN1). Manba tab faqat shu holatda o'qiladi.
            p2tab, p2rows, _p2src = _oy_oqi(prev2_m, prev2_y, prev2_1, today, day, prefer_live, True, notes)
            prows, iz = qaror_qoll(prows, ptab, q, prev2_m, otgan_rows=p2rows if p2tab is not None else None)
            notes += iz
    t1 = month_transition(prows, rows, tab, q, prev_oy=prev_m, prev_oqildi=ptab is not None)
    # Ega hisobdan chiqargan o'tgan oy qoldiqlari — so'ralmaydi, «tushadi» ogohlantirishiga
    # ham kirmaydi (t3 dan OLDIN: t3 `_i` indekslari t1["real"] ga tayanadi)
    t1["real"], kechildi, iz = kechish_ajrat(t1["real"], ptab, q, prev_m)
    notes += iz
    if kechildi:
        kk = {(r["loyiha"], round(r["qoldiq"])) for r in kechildi}
        for key in ("farqli", "noaniq"):
            t1[key] = [r for r in t1[key] if (r["loyiha"], round(r["qoldiq"])) not in kk]
    joriy = t1["cur_rows"]
    for r in joriy:
        kq = r.get("qoshimcha")
        if kq and not kq.get("jadvalda"):
            # Jami farqi faqat qaror JORIY oy tabida qo'llanganda (review CN1)
            notes.append(f"📝 Jami farqi: «{r['loyiha']}» ega qarori bo'yicha +{_fmt_usd(kq['summa'])} "
                         f"({kq.get('oy')} qoldig'i) — bot jami/qoldiq sheet «Jami»sidan shuncha ko'p")
    keyingi = None
    if tab is not None and oldinga_qarash_faolmi(today):
        ntab, nrows, nsrc = _oy_oqi(next_m, next_y, next_1, today, day, prefer_live, True, notes)
        keyingi = {"tab": ntab, "oy": next_m, "source": nsrc, "rows": [], "yaqin": [],
                   "kochgan": [], "yopilgan": [], "farqli": [], "noaniq": [], "izoh": [],
                   "eski_muddat": [], "carry_kochgan": [], "tushadi": []}
        t3_juft = set()
        if ntab is not None:
            t2 = month_transition(joriy, nrows, ntab, q, prev_oy=cur_m, yangi_min=next_1)
            for m in t2["moved"] + t2["closed"]:
                # closed → turi «yopilgan»: keyingi oy tabida to'langan/ketgan deb yozilgan
                # (1-sanadagi 🧹 qoidasi bilan bir xil — so'ralmaydi, alohida belgi bilan)
                joriy[m["_i"]]["keyingi_oyga"] = dict(m["_kochish"], tab=ntab, oy=next_m, manba_oy=cur_m)
            # O'tgan oy (2 oy oldingi) qoldiqlari ham keyingi oy tabiga yozilgan bo'lishi
            # mumkin (ega Baaztruck'ni oktabrga ko'chirsa) — ikki marta so'ralmasin (D6)
            band = set(t2["juft"].values())
            bosh = [c for j, c in enumerate(t2["cur_rows"]) if j not in band]
            t3 = month_transition(t1["real"], bosh, ntab, [], prev_oy=prev_m, yangi_min=next_1)
            t3_juft = set(t3["juft"])
            for m in t3["moved"] + t3["closed"]:
                t1["real"][m["_i"]]["keyingi_oyga"] = dict(m["_kochish"], tab=ntab, oy=next_m, manba_oy=prev_m)
            yaqin, eski = [], []
            for r in t2["cur_rows"]:
                if not is_unpaid(r) or r["muddat"] is None:
                    continue
                if r["muddat"] < next_1:
                    # Keyingi oy tabida JORIY oy sanasi — nusxa/shablon qator: keyingi oy
                    # eslatmasiga olinmaydi (joriy qator o'zi so'raladi — D2/S2), egaga izoh
                    eski.append(r)
                elif (r["muddat"] - today).days <= PUSH_DUE_DAYS:
                    yaqin.append(r)
            yaqin.sort(key=lambda r: (r["muddat"], r["pm"]))
            # t3 farqli/noaniq ham egaga (2 oy oldingi qoldiq keyingi tabda boshqa summa bilan)
            yon = f"{prev_m} → {next_m}"
            keyingi.update(rows=t2["cur_rows"], yaqin=yaqin, kochgan=t2["moved"],
                           yopilgan=t2["closed"],
                           farqli=t2["farqli"] + [dict(r, _yonalish=yon) for r in t3["farqli"]],
                           noaniq=t2["noaniq"] + t3["noaniq"],
                           izoh=t2["izoh"], eski_muddat=eski, carry_kochgan=t3["moved"] + t3["closed"])
            if eski:
                notes.append(f"⚠️ «{ntab}» tabida {cur_m} oyi muddatli {len(eski)} qator: "
                             + ", ".join(f"{r['loyiha']} ({_due_str(r['muddat'])})" for r in eski[:6])
                             + (f" +{len(eski) - 6}" if len(eski) > 6 else "")
                             + f" — {next_m} eslatmasiga olinmadi (nusxa bo'lsa muddatini yangilang)")
        # 1-sanadan bot faqat bir oy orqaga qaraydi: keyingi oy tabida TOPILMAGAN o'tgan oy
        # qoldiqlari o'shanda kuzatuvdan TUSHADI — egaga oldindan aytiladi (D11/S13, A2).
        # Keyingi tabda boshqa summa bilan topilganlar (t3 juft) bu ro'yxatga kirmaydi.
        tushadi = [r for i, r in enumerate(t1["real"])
                   if is_unpaid(r) and not r.get("keyingi_oyga") and i not in t3_juft]
        keyingi["tushadi"] = tushadi
        if tushadi:
            nomlar = (", ".join(f"{r['loyiha']} ({r['pm']}, {_fmt_usd(r['qoldiq'])})" for r in tushadi[:6])
                      + (f" +{len(tushadi) - 6}" if len(tushadi) > 6 else ""))
            if ntab is not None:
                notes.append(f"⚠️ {prev_m.capitalize()} qoldig'i «{ntab}» tabida topilmadi — 1-{next_m}dan "
                             f"bot uni tekshirmaydi: {nomlar}. {next_m.capitalize()} tabiga ko'chiring "
                             f"yoki hisobdan chiqaring")
            else:
                holat = "o'qilmadi" if nsrc == "xato" else "hali yo'q"
                notes.append(f"⚠️ 1-{next_m}dan bot {prev_m} qoldig'ini tekshirmaydi ({next_m} tabi {holat}, "
                             f"tekshirib bo'lmadi): {nomlar}. {next_m.capitalize()} tabiga ko'chirilganiga "
                             f"ishonch hosil qiling yoki hisobdan chiqaring")
    srcs = [source, psrc] + ([keyingi["source"]] if keyingi else [])
    view = {
        "today": today, "day": day, "tab": tab, "rows": joriy, "source": source, "oy": cur_m,
        "yil": cur_y,
        "prev": {"tab": ptab, "rows": prows, "source": psrc, "oy": prev_m, "kechildi": kechildi,
                 **{k: t1[k] for k in ("real", "closed", "moved", "farqli", "noaniq", "izoh")}},
        "keyingi": keyingi,
        "notes": notes,
        "data_source": "snapshot" if "snapshot" in srcs else "live",
    }
    if kesh and qlar is None:
        now = time.time()
        for k in [k for k, v in _VIEW_KESH.items() if now - v[0] >= _VIEW_TTL]:
            del _VIEW_KESH[k]                   # eskirganlar tozalanadi (S12)
        _VIEW_KESH[kalit] = (now, view)
    return view


def load_rows(day=None, today=None, prefer_live=True):
    """Undiruv qatorlari — korinish() dan (YAGONA yig'uvchi). prefer_live=True
    (default): avval JONLI (production 09:00/09:30 uchun MAJBURIY), xato bo'lsagina
    snapshot. Qaytadi: (rows, tab, source) — source ∈ {'live','snapshot','none'}.
    rows — joriy oy, qaror bo'yicha tuzatilgan va `keyingi_oyga` belgilari bilan."""
    v = korinish(today, day, prefer_live)      # kesh YO'Q — har chaqiruv jonli o'qiydi
    return v["rows"], v["tab"], v["source"]


def snapshot_banner(source, snap_day=None):
    """source='snapshot' bo'lsa — qalin ogohlantirish banneri (PDF/Telegram
    boshiga). Jonli bo'lsa "" (banner yo'q)."""
    if source != "snapshot":
        return ""
    extra = f" ({snap_day})" if snap_day else ""
    return f"🧊 **SNAPSHOT — JONLI MA'LUMOT EMAS**{extra} · raqamlar eskirgan bo'lishi mumkin"


def _fmt_usd(v):
    return f"${v:,.0f}".replace(",", " ")


def _due_str(d):
    return f"{d.day:02d}.{d.month:02d}" if d else "—"


def totals(rows):
    """YAGONA jamlama manbai — report_data, summary, dashboard uchtasi shundan
    o'qiydi (aks holda Telegram va Dashboard zid raqam ko'rsatadi).
      kelishilgan = Σ(D + E)                  — barcha qatorlar
      undirildi   = Σ E                        — barcha qatorlar
      qoldiq      = Σ D  (is_unpaid qatorlar)  — so'raladigan qarz (= D, ayirmasiz)
      aktiv       = Σ Aktive Summary
      pct         = undirildi / kelishilgan
      status_blank_n = status bo'sh, lekin qarz sanalgan qatorlar soni (⚠️)
    Paid qatorlarda D=0 bo'lgani uchun qoldiq = kelishilgan − undirildi bilan
    yopiladi (agar paid+D>0 anomaliya bo'lsa — o'sha farq ogohlantirish belgisi)."""
    kelishilgan = sum(r["qoldiq"] + r["undirildi"] for r in rows)
    undirildi = sum(r["undirildi"] for r in rows)
    qoldiq = sum(r["qoldiq"] for r in rows if is_unpaid(r))
    aktiv = sum(r["aktiv"] for r in rows)
    # RECONCILIATION GUARD: kelishilgan−undirildi = Σ D(barcha) qoldiq = Σ D
    # (unpaid); ular teng bo'lishi shart (paid qatorlarda D=0). Farq bo'lsa —
    # jim BUG (masalan paid+D>0 yoki qoldiq ta'rifi buzilgan). Crash EMAS —
    # gap saqlanadi, jamlama/PDF boshida ko'rinadigan ogohlantirish chiqadi.
    gap = round(kelishilgan) - round(undirildi) - round(qoldiq)
    return {
        "kelishilgan": round(kelishilgan),
        "undirildi": round(undirildi),
        "qoldiq": round(qoldiq),
        "aktiv": round(aktiv),
        "pct": round(undirildi / kelishilgan * 100, 1) if kelishilgan else 0.0,
        # keyingi oy tabiga ko'chgan/yopilgan qatorlar so'ralmaydi — «status bo'sh qarz» emas (C2)
        "status_blank_n": sum(1 for r in rows if is_unpaid(r) and r.get("status_blank")
                              and not r.get("keyingi_oyga")),
        "reconcile_gap": gap,
    }


def reconcile_warn(t):
    """Ogohlantirish satri yoki "" — raqamlar yopilmasa (jamlama/PDF boshiga)."""
    g = (t or {}).get("reconcile_gap") or 0
    if not g:
        return ""
    kel_und = t["kelishilgan"] - t["undirildi"]
    return (f"⚠️ Raqamlar yopilmadi: kelishilgan−undirildi = {_fmt_usd(kel_und)}, "
            f"ro'yxat = {_fmt_usd(t['qoldiq'])} (farq {_fmt_usd(g)}) — sheet'da "
            "yopilgan qatorda qoldiq qolgan bo'lishi mumkin, tekshiring.")


LOSE_FLAG_EMPTY = "summa yozilmagan"  # Ketdi, lekin «Lose summa» bo'sh (jamiga 0)
LOSE_FLAG_BAD = "summa noto'g'ri"     # Ketdi, lekin «Lose summa» manfiy (jamiga 0)
_LOSE_NAMES_CAP = 8                   # warn satrida ko'rsatiladigan maks nom


def _lose_names(names):
    """Nomlar ro'yxati → warn satri uchun qisqa CSV (8 tadan keyin «+N ta»)."""
    head = ", ".join(names[:_LOSE_NAMES_CAP])
    extra = len(names) - _LOSE_NAMES_CAP
    return head + (f" +{extra} ta" if extra > 0 else "")


def lose_summary(rows):
    """Ketgan loyihalar («To'lov xolati» normalizatsiyadan keyin «ketdi») YAGONA
    jamlamasi. Kunlik PDF (summary) va ega jamlamasi (report_data) IKKALASI shu
    funksiyani chaqiradi — ikki joyda mustaqil hisob-kitob YO'Q. Summa manbai —
    «Lose summa» ustuni (money() bilan parse; "$1 600" kabi probelli qiymatlar).
    D/E qoldiq mantiqi va PM push hisob-kitoblariga TEGMAYDI — alohida qatlam.

    Status aniqlash mavjud _status() orqali («🚪 Ketdi» kabi emoji-prefiks
    NFKC-norm + substring bilan «ketdi»ga tushadi — r["holat"] shuni saqlaydi).

    USTUN YO'Q (eski oy tablari): tabda «Lose summa» ustuni bo'lmasa
    (lose_col_present=False) — {..., "col_missing": True} qaytadi va chaqiruvchilar
    blokni BUTUNLAY chiqarmaydi (aks holda ustunsiz tab «summa yozilmagan» deb
    yolg'on gapiradi).

    Qaytadi:
      items    — [{nomi, masul, summa, flag}] status «Ketdi» qatorlar (bo'sh/manfiy
                 summali ham kiradi, flag bilan; summa 0);
      total    — Σ summa (faqat summasi to'g'ri (>0) Ketdi qatorlar);
      count    — len(items) = ketgan loyihalar soni;
      warnings — jamlangan satrlar (har biri 8 nomdan keyin «+N ta»):
                 (a) Ketdi, lekin «Lose summa» bo'sh — item flag «summa yozilmagan»;
                 (b) Ketdi, lekin «Lose summa» manfiy — item flag «summa noto'g'ri»;
                 (c) «Lose summa» > 0, lekin status «Ketdi» EMAS (ro'yxat/jamiga
                 KIRMAYDI, faqat ogohlantirish);
      col_missing — True bo'lsa ustun yo'q (blok yashiriladi)."""
    if rows and not rows[0].get("lose_col_present", True):
        return {"items": [], "total": 0, "count": 0, "warnings": [], "col_missing": True}
    items, total = [], 0
    empty_names, invalid_names, mismatch = [], [], []
    for r in rows:
        lose = round(r.get("lose", 0) or 0)
        if r.get("holat") == "ketdi":
            if lose > 0:
                flag, summa = "", lose
                total += lose
            elif lose < 0:                       # manfiy — sabab «bo'sh» emas
                flag, summa = LOSE_FLAG_BAD, 0
                invalid_names.append(r.get("loyiha", "?"))
            else:
                flag, summa = LOSE_FLAG_EMPTY, 0
                empty_names.append(r.get("loyiha", "?"))
            items.append({
                "nomi": r.get("loyiha", "?"),
                "masul": r.get("pm", "—"),
                "summa": summa,
                "flag": flag,
            })
        elif lose > 0:
            mismatch.append(r.get("loyiha", "?"))
    warnings = []
    if empty_names:
        warnings.append(f"{len(empty_names)} qatorda status «Ketdi», lekin «Lose "
                        f"summa» yozilmagan: {_lose_names(empty_names)}.")
    if invalid_names:
        warnings.append(f"{len(invalid_names)} qatorda «Lose summa» manfiy "
                        f"(noto'g'ri): {_lose_names(invalid_names)}.")
    if mismatch:
        warnings.append(f"{len(mismatch)} qatorda «Lose summa» bor, status «Ketdi» "
                        f"emas: {_lose_names(mismatch)}.")
    return {"items": items, "total": total, "count": len(items), "warnings": warnings}


def keyingi_tab_holati(k):
    """Oy oxirida keyingi oy tabi yo'q / o'qilmadi — bitta matn (KPI, shablon, PDF, push — C3)."""
    if not k or k.get("tab"):
        return []
    oy = str(k.get("oy") or "keyingi oy").capitalize()
    if k.get("source") == "xato":
        return [f"⚠️ {oy} (keyingi oy) tabi O'QILMADI (xato) — ko'chgan qarzlar eski muddat bilan "
                f"so'ralmoqda, keyingi oy to'lovlari ko'rinmaydi"]
    return [f"ℹ️ {oy} (keyingi oy) tabi hali yo'q — keyingi oy to'lovlari ko'rinmaydi"]


def izoh_satrlari(notes):
    """Egaga izohlar: belgisiz (qaror holati) satrlar «📝 » bilan — matn, PDF va push bir xil."""
    return [n if not n or n[:1] in "⚠📝ℹ🆕🔁🧹" else "📝 " + n for n in notes]


def kochish_matn(r):
    """Keyingi oy tabiga ko'chgan/yopilgan qarz — egaga BITTA ko'rinish (KPI bloki,
    shablon, 09:30 jamlama bir xil matn — C3): «Stirka → Stirkauz ($364 → jami $1 714,
    20.10 — ega qarori)», «Maestro kids ($2 100 → $2 000, 05.10 — ega qarori)»,
    «Bazarway ($1 800 → 03.10)», «Geely ($2 950, oktyabr tabida to'langan/ketgan)»."""
    k = r.get("keyingi_oyga") or r.get("_kochish") or {}
    nom = r["loyiha"]
    cn = k.get("cur_loyiha")
    if cn and _ixcham(cn) != _ixcham(nom):
        nom += f" → {cn}"
    rq, turi, mud = _fmt_usd(r["qoldiq"]), k.get("turi") or "", _due_str(k.get("muddat"))
    manba = f"{k['manba_oy']} qoldig'i, " if k.get("manba_oy") else ""
    if turi == "yopilgan":
        return f"{nom} ({manba}{rq}, {k.get('oy') or 'keyingi oy'} tabida to'langan/ketgan deb yozilgan)"
    if turi == "qaror_yangi_toliq":
        return f"{nom} ({rq} → {_fmt_usd(k.get('cur_summa', 0))}, {mud} — ega qarori)"
    if turi in ("qaror_qoshildi", "qaror_jadvalda"):
        # «jami» — kelishilgan (asl + qo'shilgan); to'lov bo'lsa qolgani alohida (review MN7)
        kel = k.get("cur_kelishilgan", k.get("cur_summa", 0))
        qol = k.get("cur_summa", kel)
        qism = f", qoldiq {_fmt_usd(qol)}" if round(qol) != round(kel) else ""
        return f"{nom} ({rq} → jami {_fmt_usd(kel)}{qism}, {mud} — ega qarori)"
    return f"{nom} ({rq} → {mud})"


def summary(day, today=None, prefer_live=True):
    """report.json uchun 'undiruv' bloki. Ma'lumot bo'lmasa None; joriy oy tabi
    topilmasa — {"topilmadi": True, ...} (09:00 hisobotida ogohlantirish, jim emas).
    prefer_live: production'da JONLI o'qiladi (snapshot faqat fallback).
    Kesh faqat UNDIRUV_KESH=1 bo'lsa (run.sh → analyze.py subprocess): 09:00 da report_block
    va report.json bitta ko'rinishdan. Bot jarayonidagi /hisobot har safar jonli (MN5/SN1)."""
    today = today or date.fromisoformat(day)
    v = korinish(today, day, prefer_live, kesh=os.environ.get("UNDIRUV_KESH") == "1")
    rows, tab, source = v["rows"], v["tab"], v["source"]
    if tab is None:
        return {"topilmadi": True, "oy": v["oy"], "tab": None, "source": source, "day": day,
                "notes": list(v.get("notes") or [])}
    if not rows:
        return None
    t = totals(rows)

    def unpaid(r):
        # Oy oxirida keyingi oyga ko'chgan/yopilgan qarz eski muddat bilan so'ralmaydi —
        # PM push va ega PDF bilan AYNAN bir xil qoida (C3).
        return is_unpaid(r) and not r.get("keyingi_oyga")

    def item(r):
        return {
            "pm": r["pm"], "loyiha": r["loyiha"],
            "summa": round(r["qoldiq"]),
            "muddat": _due_str(r["muddat"]),
            "kun": (today - r["muddat"]).days if r["muddat"] else None,
        }

    def kitem(r):
        kk = r["keyingi_oyga"]
        return {"loyiha": r["loyiha"], "pm": r["pm"], "summa": round(r["qoldiq"]),
                "yangi_summa": kk.get("cur_summa"), "yangi_muddat": _due_str(kk.get("muddat")),
                "turi": kk.get("turi"), "matn": kochish_matn(r)}

    pv = v["prev"]
    k = v.get("keyingi")
    keyingi = None
    if k:
        flag = [r for r in rows if r.get("keyingi_oyga")] + [r for r in pv["real"] if r.get("keyingi_oyga")]
        kochgan = [r for r in flag if r["keyingi_oyga"].get("turi") != "yopilgan"]
        yopilgan = [r for r in flag if r["keyingi_oyga"].get("turi") == "yopilgan"]
        keyingi = {
            "tab": k["tab"], "oy": k["oy"], "source": k.get("source"),
            "yaqin": [dict(item(r), kun=(r["muddat"] - today).days) for r in k["yaqin"]],
            "yaqin_sum": round(sum(r["qoldiq"] for r in k["yaqin"])),
            "kochgan": [kitem(r) for r in kochgan],
            "kochgan_sum": round(sum(r["qoldiq"] for r in kochgan)),
            "yopilgan": [kitem(r) for r in yopilgan],
            "yopilgan_sum": round(sum(r["qoldiq"] for r in yopilgan)),
        }

    overdue = sorted(
        (item(r) for r in rows if unpaid(r) and r["muddat"] and r["muddat"] < today),
        key=lambda x: -(x["kun"] or 0),
    )
    soon = sorted(
        (item(r) for r in rows
         if unpaid(r) and r["muddat"] and 0 <= (r["muddat"] - today).days <= DUE_SOON_DAYS),
        key=lambda x: x["muddat"],
    )
    # O'tgan oy qoldiqlari — 09:30 push ular bilan PM'ni so'raydi (build_push carry
    # qoidasi: muddat o'tgan yoki ≤5 kun yoki sanasiz). KPI bloki ham ko'rsatsin, aks
    # holda «muddati o'tgan yo'q ✅» deb yolg'on gapirardi (review C5).
    otgan = []
    for r in pv["real"]:
        if not is_unpaid(r) or r.get("keyingi_oyga"):
            continue
        if r["muddat"] is None or (r["muddat"] - today).days <= PUSH_DUE_DAYS:
            otgan.append(item(r))
    otgan.sort(key=lambda x: -(x["kun"] or 0))
    return {
        "oy": fetchmod.current_month_name(today),
        "tab": tab,
        "kelishilgan": t["kelishilgan"],
        "undirildi": t["undirildi"],
        "qoldiq": t["qoldiq"],
        "aktiv": t["aktiv"],
        "pct": t["pct"],
        "status_blank_n": t["status_blank_n"],
        "reconcile_gap": t["reconcile_gap"],
        "source": source,
        "day": day,
        "muddat_otgan": overdue,
        "muddat_yaqin": soon,
        "yaqin_kun": DUE_SOON_DAYS,
        # O'tgan oy tabidan hali so'ralayotgan qoldiqlar (09:30 push bilan bir xil to'plam)
        "otgan_oy": {"oy": pv["oy"], "tab": pv["tab"], "items": otgan,
                     "sum": round(sum(i["summa"] for i in otgan))},
        # Oy oxirida: keyingi oy tabi (muddati yaqinlar + unga ko'chgan/yopilgan qarzlar)
        "keyingi": keyingi,
        # Egaga izohlar: tab topilmadi/o'qilmadi, ega qarorlari, ogohlantirishlar (matn bloki
        # va PDF shablon AYNAN shu satrlarni chiqaradi — C3)
        "notes": izoh_satrlari(list(v.get("notes") or []) + list(pv.get("izoh") or [])
                               + list((k or {}).get("izoh") or [])),
        # Ketgan loyihalar — YAGONA manba (report_data ham aynan shuni chaqiradi)
        "lose": lose_summary(rows),
    }


def _group_pm(items):
    by = {}
    for it in items:
        g = by.setdefault(it["pm"], [])
        g.append(it)
    return by


def report_block(day, today=None):
    """report.md oxiriga qo'shiladigan matn bloki (Telegram matn-fallback va
    Obsidian arxiv uchun). Ma'lumot bo'lmasa bo'sh satr."""
    s = summary(day, today)
    if not s:
        return ""
    if s.get("topilmadi"):
        return "\n".join([f"💰 **Undiruv ({s['oy']})**"] + list(s.get("notes") or []))
    L = []
    banner = snapshot_banner(s.get("source"), s.get("day"))
    if banner:
        L.append(banner)
    if s.get("reconcile_gap"):
        L.append(reconcile_warn(s))
    L += [
        f"💰 **Undiruv ({s['oy']})** — {s['tab']}",
        f"Kelishilgan {_fmt_usd(s['kelishilgan'])} · undirildi {_fmt_usd(s['undirildi'])} "
        f"({str(s['pct']).replace('.', ',')}%) · qoldiq {_fmt_usd(s['qoldiq'])}"
        + (f" · 💳 aktiv obuna {_fmt_usd(s['aktiv'])} (so'ralmaydi)" if s["aktiv"] else ""),
    ]
    L += izoh_satrlari(s.get("notes") or [])
    if s["muddat_otgan"]:
        tot = sum(i["summa"] for i in s["muddat_otgan"])
        L.append(f"⏰ Muddati o'tgan, undirilmagan: {len(s['muddat_otgan'])} loyiha, {_fmt_usd(tot)}:")
        for pm, items in _group_pm(s["muddat_otgan"]).items():
            det = ", ".join(f"{i['loyiha']} ({_fmt_usd(i['summa'])}, {i['muddat']})" for i in items)
            L.append(f"  • {pm}: {det}")
    oo = s.get("otgan_oy") or {}
    if oo.get("items"):
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, {_fmt_usd(i['summa'])}, {i['muddat']}"
                        + (f", {i['kun']} kun o'tdi" if (i.get("kun") or 0) > 0 else "") + ")"
                        for i in oo["items"][:8])
        more = f" +{len(oo['items']) - 8}" if len(oo["items"]) > 8 else ""
        oy_nomi = (oo.get("oy") or "o'tgan oy").capitalize()
        L.append(f"⏰ {oy_nomi} qoldig'i (o'tgan oy tabidan, PM'dan so'ralmoqda): "
                 f"{len(oo['items'])} ta, {_fmt_usd(oo['sum'])}: {det}{more}")
    if s["muddat_yaqin"]:
        det = ", ".join(
            f"{i['loyiha']} ({i['pm']}, {_fmt_usd(i['summa'])}, {i['muddat']})"
            for i in s["muddat_yaqin"]
        )
        L.append(f"🔜 Muddati ≤{DUE_SOON_DAYS} kun: {det}")
    k = s.get("keyingi")
    if k and k.get("kochgan"):
        det = ", ".join(i["matn"] for i in k["kochgan"][:8])
        more = f" +{len(k['kochgan']) - 8}" if len(k["kochgan"]) > 8 else ""
        L.append(f"🔁 {k['oy'].capitalize()} tabiga ko'chirilgan (eski muddat bilan so'ralmaydi): "
                 f"{len(k['kochgan'])} ta, {_fmt_usd(k['kochgan_sum'])}: {det}{more}")
    if k and k.get("yopilgan"):
        det = ", ".join(i["matn"] for i in k["yopilgan"][:8])
        L.append(f"🧹 {k['oy'].capitalize()} tabida to'langan/ketgan deb yozilgan, {s['oy']} tabida ochiq "
                 f"(so'ralmaydi — {s['oy']} tabini tuzating): {len(k['yopilgan'])} ta, "
                 f"{_fmt_usd(k['yopilgan_sum'])}: {det}")
    if k and k.get("yaqin"):
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, {_fmt_usd(i['summa'])}, {i['muddat']})" for i in k["yaqin"][:10])
        more = f" +{len(k['yaqin']) - 10}" if len(k["yaqin"]) > 10 else ""
        L.append(f"📅 {k['oy'].capitalize()} (keyingi oy) — muddati ≤{DUE_SOON_DAYS} kun: "
                 f"{len(k['yaqin'])} ta, {_fmt_usd(k['yaqin_sum'])}: {det}{more}")
    elif k is not None and not k.get("tab"):
        if k.get("source") == "xato":
            L.append(f"⚠️ {k['oy'].capitalize()} (keyingi oy) tabi O'QILMADI (xato) — ko'chgan qarzlar "
                     f"eski muddat bilan so'ralmoqda, keyingi oy to'lovlari ko'rinmaydi")
        else:
            L.append(f"ℹ️ {k['oy'].capitalize()} (keyingi oy) tabi hali yo'q — oy oxiri, "
                     f"keyingi oy to'lovlari ko'rinmaydi")
    if (not s["muddat_otgan"] and not s["muddat_yaqin"] and not (k and k.get("yaqin"))
            and not oo.get("items")):
        L.append("⏰ Muddati o'tgan yoki yaqin qolgan undirilmagan loyiha yo'q ✅")
    if s.get("status_blank_n"):
        L.append(f"⚠️ Status bo'sh (tasdiqlanmagan qarz): {s['status_blank_n']} ta qator")
    return "\n".join(L)


# PUSH_DUE_DAYS — fayl boshida (bitta manba; DUE_SOON_DAYS shu qiymatning o'zi).


def _row_status(r, today):
    if r["muddat"] is None:
        return "nodate", None
    if r["muddat"] < today:
        return "overdue", (today - r["muddat"]).days
    if (r["muddat"] - today).days <= PUSH_DUE_DAYS:
        return "soon", (r["muddat"] - today).days
    return "future", (r["muddat"] - today).days


def report_data(rows, tab, today, source="", view=None):
    """Undiruv hisobotining YAGONA hisob-kitob manbasi — full_report (matn),
    PDF (render_pdf.build_undiruv_html) va caption shu strukturadan quriladi.
    Item status: overdue / soon (≤PUSH_DUE_DAYS) / future / nodate — joriy oy;
    kochdi (keyingi oy tabiga ko'chgan) / yopildi (keyingi oy tabida to'langan/ketgan) —
    so'ralmaydi; view berilsa yana: otgan (o'tgan oy tabidan so'ralayotgan qoldiq) va
    keyingi (keyingi oy, muddati ≤PUSH_DUE_DAYS) — 09:30 push AYNAN shularni PM'ga
    yuboradi, shuning uchun ega PDF'i ham ko'rsatadi (review M5/C2: «qarz yo'q» deb,
    PM'larga eslatma ketayotganda). pm n/sum — faqat JORIY oy tabidan so'raladiganlar."""
    data = {
        "tab": tab,
        "oy": (fetchmod.norm(tab).split() or ["?"])[-1],
        "source": source,
        "totals": totals(rows),
        "counts": {
            "jami": len(rows),
            **{k: sum(1 for r in rows if r["holat"] == k) for k in ("paid", "ketdi", "pauza")},
        },
        # Ketgan loyihalar — YAGONA manba (summary() ham aynan shuni chaqiradi)
        "lose": lose_summary(rows),
        "pms": [],
        "keyingi": None,
        "otgan": None,
        "notes": izoh_satrlari(list((view or {}).get("notes") or [])
                               + list(((view or {}).get("prev") or {}).get("izoh") or [])
                               + list(((view or {}).get("keyingi") or {}).get("izoh") or [])
                               + keyingi_tab_holati((view or {}).get("keyingi"))),
    }
    by_pm, extra = {}, {}
    for r in rows:
        by_pm.setdefault(r["pm"], []).append(r)
    k = (view or {}).get("keyingi")
    pv = (view or {}).get("prev") or {}
    if view is not None:
        for r in pv.get("real") or []:
            if not is_unpaid(r) or r.get("keyingi_oyga"):
                continue
            st, kun = _row_status(r, today)
            if st == "future":
                continue                         # build_push ham so'ramaydi (muddati uzoq)
            extra.setdefault(r["pm"], []).append({
                "loyiha": r["loyiha"], "summa": round(r["qoldiq"]),
                "muddat": _due_str(r["muddat"]) if r["muddat"] else "—",
                "status": "otgan", "kun": kun, "otgan_status": st, "otgan_oy": pv.get("oy"),
                "pauza": r["holat"] == "pauza", "status_blank": bool(r.get("status_blank"))})
        if k:
            for r in k.get("yaqin") or []:
                extra.setdefault(r["pm"], []).append({
                    "loyiha": r["loyiha"], "summa": round(r["qoldiq"]), "muddat": _due_str(r["muddat"]),
                    "status": "keyingi", "kun": (r["muddat"] - today).days, "keyingi_oy": k.get("oy"),
                    "pauza": r["holat"] == "pauza", "status_blank": bool(r.get("status_blank")),
                    "qoshimcha": r.get("qoshimcha")})
    aktiv_pms, aktiv_n, aktiv_sum = [], 0, 0
    tartib = sorted(by_pm, key=lambda p: -sum(x["qoldiq"] for x in by_pm[p] if is_unpaid(x)))
    tartib += [p for p in extra if p not in by_pm]
    for pm in tartib:
        items = []
        for r in sorted((r for r in by_pm.get(pm, []) if is_unpaid(r)),
                        key=lambda r: (r["muddat"] is None, r["muddat"] or today)):
            kk = r.get("keyingi_oyga")
            if kk:
                # Oy oxirida keyingi oy tabiga ko'chgan/yopilgan — eski muddat bilan so'ralmaydi
                status, kun = ("yopildi" if kk.get("turi") == "yopilgan" else "kochdi"), None
            else:
                status, kun = _row_status(r, today)
            items.append({
                "loyiha": r["loyiha"],
                "summa": round(r["qoldiq"]),
                "muddat": _due_str(r["muddat"]) if r["muddat"] else "—",
                "status": status,
                "kun": kun,
                "pauza": r["holat"] == "pauza",
                "status_blank": bool(r.get("status_blank")),
                "kochdi": ({"oy": kk.get("oy"), "muddat": _due_str(kk.get("muddat")),
                            "turi": kk.get("turi"), "matn": kochish_matn(r),
                            "cur_loyiha": (kk.get("cur_loyiha")
                                           if _ixcham(kk.get("cur_loyiha") or "") != _ixcham(r["loyiha"]) else None),
                            "manba_oy": kk.get("manba_oy")} if kk else None),
                "qoshimcha": r.get("qoshimcha"),
            })
        items += extra.get(pm, [])
        paid = [r for r in by_pm.get(pm, []) if r["holat"] == "paid"]
        hisob = [i for i in items if i["status"] in ("overdue", "soon", "future", "nodate")]
        koch = [i for i in items if i["status"] in ("kochdi", "yopildi")]
        kyn = [i for i in items if i["status"] == "keyingi"]
        otg = [i for i in items if i["status"] == "otgan"]
        data["pms"].append({
            "name": pm,
            "n": len(hisob),
            "sum": round(sum(i["summa"] for i in hisob)),
            "items": items,
            "paid_n": len(paid),
            "paid_sum": round(sum(r["undirildi"] for r in paid)),
            "kochdi_n": len(koch), "kochdi_sum": round(sum(i["summa"] for i in koch)),
            "keyingi_n": len(kyn), "keyingi_sum": round(sum(i["summa"] for i in kyn)),
            "otgan_n": len(otg), "otgan_sum": round(sum(i["summa"] for i in otg)),
        })
        # Aktiv obuna (oldindan to'langan) — pul so'ralmaydi, faqat ma'lumot
        act = [r for r in by_pm.get(pm, []) if is_active_only(r)]
        if act:
            aktiv_pms.append({
                "name": pm,
                "n": len(act),
                "sum": round(sum(r["aktiv"] for r in act)),
                "loyihalar": [r["loyiha"] for r in act],
            })
            aktiv_n += len(act)
            aktiv_sum += round(sum(r["aktiv"] for r in act))
    data["aktiv_obuna"] = {"n": aktiv_n, "sum": aktiv_sum, "pms": aktiv_pms}
    ps = data["pms"]
    if view is not None:
        on = sum(p["otgan_n"] for p in ps)
        data["otgan"] = {"oy": pv.get("oy"), "tab": pv.get("tab"), "n": on,
                         "sum": sum(p["otgan_sum"] for p in ps)} if on else None
    if k:
        data["keyingi"] = {
            "oy": k.get("oy"), "tab": k.get("tab"), "source": k.get("source"),
            "n": sum(p["keyingi_n"] for p in ps), "sum": sum(p["keyingi_sum"] for p in ps),
            "kochdi_n": sum(1 for p in ps for i in p["items"] if i["status"] == "kochdi"),
            "kochdi_sum": sum(i["summa"] for p in ps for i in p["items"] if i["status"] == "kochdi"),
            "yopildi_n": sum(1 for p in ps for i in p["items"] if i["status"] == "yopildi"),
            "yopildi_sum": sum(i["summa"] for p in ps for i in p["items"] if i["status"] == "yopildi"),
        }
    return data


STATUS_MARK = {"overdue": "⏰", "soon": "🔜", "future": "📅", "nodate": "📋", "kochdi": "🔁",
               "yopildi": "🧹", "keyingi": "📅", "otgan": "⏰"}


def item_holat_matn(i):
    """PDF/matn uchun item holati (render_pdf va full_report — bitta manba)."""
    st, kun = i.get("status"), i.get("kun")
    if st == "overdue":
        return f"{kun} kun o'tdi"
    if st == "soon":
        return "bugun oxirgi kun" if kun == 0 else f"{kun} kun qoldi"
    if st == "future":
        return f"{kun} kun"
    if st == "kochdi":
        k = i.get("kochdi") or {}
        yangi = f" → {k['cur_loyiha']}" if k.get("cur_loyiha") else ""      # fuzzy bog'lanish ko'rinsin (CN6)
        qaror = ", ega qarori" if str(k.get("turi") or "").startswith("qaror") else ""
        return f"{k.get('oy') or 'keyingi oy'} tabiga ko'chdi{yangi} ({k.get('muddat', '—')}{qaror})"
    if st == "yopildi":
        k = i.get("kochdi") or {}
        return f"{k.get('oy') or 'keyingi oy'} tabida to'langan/ketgan — {k.get('manba_oy') or 'joriy'} tabini tuzating"
    if st == "keyingi":
        q = "bugun oxirgi kun" if kun == 0 else f"{kun} kun qoldi"
        return f"{i.get('keyingi_oy') or 'keyingi oy'}: {q}"
    if st == "otgan":
        oy = i.get("otgan_oy") or "o'tgan oy"
        if i.get("otgan_status") == "overdue":
            return f"{oy} qoldig'i · {kun} kun o'tdi"
        if i.get("otgan_status") == "soon":
            return f"{oy} qoldig'i · {kun} kun qoldi"
        return f"{oy} qoldig'i · sana yo'q"
    return "sana yo'q"


def pm_qoshimcha_matn(pm):
    """PM sarlavhasiga: joriy oydan tashqari so'ralayotgan/ko'chgan qarzlar
    («· ⏰ avgust qoldig'i 1 ta $433 · 📅 oktyabr ≤5 kun 2 ta $3 400 · 🔁 ko'chgan 3 ta $9 464»)."""
    p = []
    if pm.get("otgan_n"):
        oy = next((i.get("otgan_oy") for i in pm["items"] if i["status"] == "otgan"), None) or "o'tgan oy"
        p.append(f"⏰ {oy} qoldig'i {pm['otgan_n']} ta {_fmt_usd(pm['otgan_sum'])}")
    if pm.get("keyingi_n"):
        oy = next((i.get("keyingi_oy") for i in pm["items"] if i["status"] == "keyingi"), None) or "keyingi oy"
        p.append(f"📅 {oy} ≤{PUSH_DUE_DAYS} kun {pm['keyingi_n']} ta {_fmt_usd(pm['keyingi_sum'])}")
    koch = [i for i in pm.get("items", []) if i["status"] == "kochdi"]
    yop = [i for i in pm.get("items", []) if i["status"] == "yopildi"]
    if koch:
        p.append(f"🔁 keyingi oy tabida {len(koch)} ta {_fmt_usd(sum(i['summa'] for i in koch))}")
    if yop:                                   # 🧹 alohida — «ko'chdi» bilan aralashmasin (CN9d)
        p.append(f"🧹 keyingi oy tabida yopilgan {len(yop)} ta {_fmt_usd(sum(i['summa'] for i in yop))}")
    return "".join(" · " + x for x in p)


def full_report(rows, tab, today, source="", view=None):
    """Dry-run MATN ko'rinishi (PDF fallback va CLI): filtr natijasining TO'LIQ
    ro'yxati PM kesimida, qisqartirishsiz. report_data'dan quriladi.
    Belgilar: ⏰ muddat o'tgan · 🔜 ≤5 kun · 📅 kelajak/keyingi oy · 📋 sanasiz ·
    🔁 keyingi oyga ko'chdi · 🧹 keyingi oy tabida yopilgan."""
    if not rows:
        return "🧪 Undiruv dry-run: qator topilmadi."
    d = report_data(rows, tab, today, source, view=view)
    t, c = d["totals"], d["counts"]
    L = []
    if t.get("reconcile_gap"):
        L.append(reconcile_warn(t))
    L += [
        f"🧪 **Undiruv dry-run — {tab}**" + (f" ({source})" if source else ""),
        "Filtr: undirilmagan = «Summa» (shu oy qoldig'i) > 0 va holati «To'lov "
        "qilindi»/«Ketdi» EMAS. Aktiv obuna (oldindan to'langan) so'ralmaydi — "
        "alohida blokda. Muddat — «Final data» (KK.OO).",
        "",
        f"JAMI: kelishilgan {_fmt_usd(t['kelishilgan'])} · undirildi {_fmt_usd(t['undirildi'])} "
        f"({str(t['pct']).replace('.', ',')}%) · qoldiq {_fmt_usd(t['qoldiq'])} · aktiv {_fmt_usd(t['aktiv'])}",
        f"Loyihalar: {c['jami']} ta · ✅ to'langan {c['paid']} · ⛔ ketgan {c['ketdi']} "
        f"· ⏸ pauza {c['pauza']}",
    ]
    L += izoh_satrlari(d.get("notes") or [])
    for pm in d["pms"]:
        if not pm["items"] and not pm["paid_n"]:
            continue
        L.append(f"\n▸ **{pm['name']}** — undirilmagan {pm['n']} ta, {_fmt_usd(pm['sum'])}"
                 f"{pm_qoshimcha_matn(pm)}:")
        for i in pm["items"]:
            if i["status"] == "nodate":
                mud = "muddat yo'q"
            elif i["status"] == "future":
                mud = i["muddat"]
            elif i["status"] in ("kochdi", "yopildi"):
                mud = item_holat_matn(i)
            else:
                mud = f"{i['muddat']} ({item_holat_matn(i)})"
            extra = " ⏸" if i["pauza"] else ""
            extra += " ⚠️status bo'sh" if i.get("status_blank") else ""
            L.append(f"  {STATUS_MARK[i['status']]} {i['loyiha']} — {_fmt_usd(i['summa'])}, {mud}{extra}")
        if pm["paid_n"]:
            L.append(f"  ✅ to'langan: {pm['paid_n']} ta, {_fmt_usd(pm['paid_sum'])}")
    if t.get("status_blank_n"):
        L.append(f"\n⚠️ Status bo'sh (tasdiqlanmagan qarz): {t['status_blank_n']} ta qator — "
                 "D>0 bo'lgani uchun qarz sanaldi; sheet'da holatni belgilash tavsiya etiladi.")
    lose = d.get("lose") or {}
    if not lose.get("col_missing"):        # ustun yo'q → blokni butunlay chiqarmaymiz
        if lose.get("count"):
            L.append(f"\n🚪 **Yo'qotilgan loyihalar (ketgan): {lose['count']} ta, "
                     f"{_fmt_usd(lose['total'])}**")
            for it in lose["items"]:
                summa = it["flag"] or _fmt_usd(it["summa"])
                L.append(f"  • {it['nomi']} ({it['masul']}) — {summa}")
        else:
            L.append("\n🚪 **Yo'qotilgan loyihalar:** bu oyda ketgan loyiha yo'q ✅")
        for w in lose.get("warnings", []):
            L.append(f"  ⚠️ {w}")
    ao = d.get("aktiv_obuna") or {}
    if ao.get("n"):
        L.append(f"\n💳 **Aktiv obuna (oldindan to'langan — so'ralmaydi):** "
                 f"{ao['n']} loyiha, {_fmt_usd(ao['sum'])}")
        for p in ao["pms"]:
            L.append(f"  • {p['name']}: {p['n']} ta, {_fmt_usd(p['sum'])} — "
                     f"{', '.join(p['loyihalar'][:8])}"
                     + (f" +{p['n'] - 8}" if p["n"] > 8 else ""))
    return "\n".join(L)


def pdf_caption(d, title=None):
    """PDF hujjat caption'i (≤1024): JAMI + har PM bir qator."""
    t, c = d["totals"], d["counts"]
    k = d.get("keyingi") or {}
    kochdi = ""
    if k.get("kochdi_n") or k.get("yopildi_n"):
        # Qoldiq ichida keyingi oy tabiga ko'chgan/yopilganlar ham bor — eski muddat bilan
        # so'ralmaydi; ega bir hujjatda ikki raqamni solishtira olsin (review S10)
        kochdi = (f" (shundan {k.get('oy') or 'keyingi oy'} tabida: "
                  f"{_fmt_usd(k.get('kochdi_sum', 0) + k.get('yopildi_sum', 0))})")
    L = [
        title or f"📊 Undiruv ({d['oy']})" + (f" — {d['source']}" if d.get("source") else ""),
        f"JAMI: {_fmt_usd(t['kelishilgan'])} dan {_fmt_usd(t['undirildi'])} undirildi "
        f"({str(t['pct']).replace('.', ',')}%) · qoldiq {_fmt_usd(t['qoldiq'])}{kochdi}"
        + (f" · aktiv {_fmt_usd(t['aktiv'])}" if t["aktiv"] else ""),
    ]
    if k.get("n"):
        L.append(f"📅 {str(k.get('oy') or 'keyingi oy').capitalize()} (keyingi oy) ≤{PUSH_DUE_DAYS} kun: "
                 f"{k['n']} ta, {_fmt_usd(k['sum'])}")
    o = d.get("otgan") or {}
    if o.get("n"):
        oy_nomi = (o.get("oy") or "o'tgan oy").capitalize()
        L.append(f"⏰ {oy_nomi} qoldig'i: {o['n']} ta, {_fmt_usd(o['sum'])}")
    for pm in d["pms"]:
        qo = pm_qoshimcha_matn(pm)
        if not pm["n"] and not qo:
            continue
        od = sum(1 for i in pm["items"] if i["status"] == "overdue")
        L.append(f"{pm['name']}: {pm['n']} ta undirilmagan, {_fmt_usd(pm['sum'])}"
                 + (f" · 🔴 {od} muddat o'tgan" if od else "") + qo)
    lose = d.get("lose") or {}
    if lose.get("count") and not lose.get("col_missing"):
        L.append(f"🚪 Ketgan: {lose['count']} loyiha, {_fmt_usd(lose['total'])} yo'qotildi")
    ao = d.get("aktiv_obuna") or {}
    if ao.get("n"):
        L.append(f"💳 Aktiv obuna: {ao['n']} loyiha, {_fmt_usd(ao['sum'])} (so'ralmaydi)")
    L.append("📎 Batafsil PDF ichida")
    return "\n".join(L)[:1024]


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--json", action="store_true", help="summary'ni JSON ko'rinishida chiqarish")
    ap.add_argument("--full", action="store_true", help="dry-run: to'liq ro'yxat PM kesimida")
    args = ap.parse_args()
    if args.json:
        print(json.dumps(summary(args.date), ensure_ascii=False, indent=1))
    elif args.full:
        _v = korinish(date.fromisoformat(args.date), args.date)
        print(full_report(_v["rows"], _v["tab"] or "?", date.fromisoformat(args.date),
                          source=_v["source"], view=_v))
    else:
        print(report_block(args.date) or "(undiruv ma'lumoti topilmadi)")
