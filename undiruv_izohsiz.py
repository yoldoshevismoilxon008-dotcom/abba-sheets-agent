#!/usr/bin/env python3
"""Kelishilgan summa izohsiz kamayishi — joriy oy tabi qatorma-qator, kecha ↔ bugun (AUDIT.md P0-5).

Bu sheet'da «Summa» — QOLGAN qarz, kelishilgan = Summa + Undirildi. Pul faqat Summa → Undirildi /
Lose summa / Aktive Summary orasida ko'chadi: har qatorda B = Summa+Undirildi+Lose+Aktive o'zgarmasligi
kerak (undiruv_carry.qator_farqi). B kamaysa — pul na undirilgan, na lose'ga yozilgan: «⚠️ Izohsiz
yo'qolish». Qator o'chsa — «⚠️ Qator o'chirilgan». Keyin Undirildi/Lose/Aktive yozilsa, Summa aynan
qaytarilsa, qator jami yo'qolishdan oldingi jamiga qaytsa yoki holat «Ega qarori» bo'lsa — «✅ …
izohlandi»; aks holda oy oxirigacha har kuni ochiq ro'yxatda takrorlanadi.

HOLAT FAYLI YO'Q: oy hodisalari har summary() chaqiruvida joriy oy tabining SNAPSHOT'laridan
(DATA_DIR/snapshots/<kun>/<sheet>.json — jonli o'qish EMAS) qaytadan quriladi: asos — 1-sanadan
oldingi (≤ASOS_MAX_KUN kun) shu tab bor oxirgi snapshot, keyin har snapshot kuni juft-juft (zanjir).
Qatorma-qator satrlar snapshot'lardan deterministik, kod tuzatilsa tarix ham o'zi to'g'rilanadi.
O'tgan kunni ko'rish — faqat o'qiydigan CLI: `python undiruv_izohsiz.py --date D`. `analyze.py
--date D` EMAS: u 💰 K/U/lose va P0-3'ni jonli sheet'dan oladi, D hisobotini (report.md/json) qayta
yozadi va push_reports uni arxivga qayta push qiladi. Bir jarayonda kesh: qatorlar — fayl (mtime,
hajm) bo'yicha, zanjir — kunlar izi bo'yicha. run.sh retention 40 kun — oy asosi oy oxirigacha
o'chmaydi.

Faqat undiruv.summary() dan (09:00 hisobot, report.json/PDF, /hisobot) chaqiriladi — 09:30 push,
ega jamlamasi va dashboard qo'shimcha snapshot o'qimaydi. Kill switch: UNDIRUV_IZOHSIZ_OFF=1.
P0-3 (undiruv_carry) O'SHA KUNI hukm qilgan ko'chirilgan qatorlar (nom + PM) bu yerda takrorlanmaydi
(bir hodisa — bir ⚠️); P0-3 jim kunlari P0-5 ularni o'zi ko'rsatadi.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import diff as diffmod            # noqa: E402
import fetch as fetchmod          # noqa: E402
import undiruv_carry as carrymod  # noqa: E402

TOL = 1                 # $1 — sheet kasr sentlari (09-30: jami $39 803 / blok $39 802)
YANGI_CAP = 6           # bir kunda alohida satr bilan ko'rsatiladigan yangi/yopilgan hodisa
OCHIQ_CAP = 6           # «hali izohlanmagan» va guruh satrlaridagi nomlar
OMMAVIY_MIN = 8         # shuncha (va ≥ OMMAVIY_ULUSH) qator birdan pul yo'qotsa — bitta guruh satri
OMMAVIY_ULUSH = 0.25
ASOS_MAX_KUN = 7        # oy boshidagi asos snapshot'i shuncha kun orqadan qidiriladi
_QATOR_KESH_MAX = 80
_ZANJIR_KESH_MAX = 4
_QATOR_KESH = {}        # (fayl, mtime_ns, hajm, oy_1) → (tab, ixcham qatorlar) — o'zgartirilmaydi
_ZANJIR_KESH = {}       # (oy_1, D, sid, kunlar izi) → zanjir holati — ko'rsatish uni O'ZGARTIRMAYDI
_SNAP_BIR = {}          # oxirgi o'qilgan snapshot (bitta): kunning joriy va keyingi oy tabi bir o'qishda
_FAYL_KESH = {}         # kun izi → SMM fayli (config id fayli yo'q bo'lganda papka skani natijasi)


def ochiq():
    """UNDIRUV_IZOHSIZ_OFF=1 — P0-5 butunlay o'chadi (snapshot o'qilmaydi): 💰 blok, report.json va
    PDF bu modulsiz holat bilan baytma-bayt bir xil. P0-3 kaliti (UNDIRUV_CARRY_OFF) alohida."""
    return os.environ.get("UNDIRUV_IZOHSIZ_OFF") != "1"


def _u():
    import undiruv           # kech import — undiruv bu modulni import qiladi
    return undiruv


def log(msg):
    print(f"[undiruv_izohsiz] {msg}", flush=True)


_B = carrymod._B
_qv = carrymod.qator_qiymat
_NOL = {"summa": 0, "summa_raw": None, "undirildi": 0, "lose": 0, "aktiv": 0}


def _usd(v):
    return _u()._fmt_usd(v)


def _dm(d):
    return carrymod._dm(d)


def _son(v):
    return carrymod._son(v)


def _nk(r):
    u = _u()
    return u._name_key(r["loyiha"]), u._pm_kalit(r["pm"])


# ---- Snapshot o'qish -----------------------------------------------------------------------

def _kesh_qoy(d, k, v, cap):
    """Kichik FIFO kesh. Bot jarayonida summary() bir nechta oqimdan chaqirilishi mumkin — bir vaqtdagi
    o'zgarish xato bermasin (eng yomoni: kesh bir marta ortiq tozalanadi)."""
    try:
        while len(d) >= cap:
            d.pop(next(iter(d)), None)
    except RuntimeError:
        pass
    d[k] = v


def _stat_kalit(p):
    s = p.stat()
    return str(p), s.st_mtime_ns, s.st_size


def _snap_oqi(p):
    """JSON snapshot (yoki None). Faqat OXIRGI o'qilgani xotirada (3 MB × 40 kun saqlanmasin)."""
    try:
        k = _stat_kalit(p)
    except OSError:
        return None
    hit = _SNAP_BIR.get("v")                      # (kalit, snapshot) — bitta atomik o'qish
    if hit and hit[0] == k:
        return hit[1]
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                         # noqa: BLE001 — yarim yozilgan fayl
        log(f"{p.parent.name}/{p.name} o'qilmadi: {type(e).__name__}")
        s = None
    _SNAP_BIR["v"] = (k, s)
    return s


def _smm_fayl(kun, sid):
    """`kun` papkasidagi SMM (pm_kpi=false) snapshot fayli yoki None. Avval config'dagi id fayli
    (fetch.py <id>.json yozadi), topilmasa — papkadagi sheet fayllari (load_day kabi, SERVICE_FILES'siz)."""
    d = diffmod.SNAPSHOTS / kun
    if not d.is_dir():
        return None
    if sid and "/" not in sid and "\\" not in sid and not sid.startswith("."):
        p = d / f"{sid}.json"
        if p.is_file():
            return p
    izi = _kun_izi(kun)                            # skan natijasi fayllar izi bo'yicha keshlanadi (sekin yo'l)
    if izi in _FAYL_KESH:
        return _FAYL_KESH[izi]
    topildi = None
    for p in sorted(d.glob("*.json")):
        if p.name in diffmod.SERVICE_FILES:
            continue
        s = _snap_oqi(p)
        if isinstance(s, dict) and not s.get("pm_kpi", True):
            topildi = p
            break
    _kesh_qoy(_FAYL_KESH, izi, topildi, _QATOR_KESH_MAX)
    return topildi


def _ixcham_qator(r):
    """parse_rows qatori → ixcham shakl (_juftla va qator_qiymat shu shaklni qabul qiladi)."""
    u = _u()
    v = _qv(r)
    m = r.get("muddat")
    return {"loyiha": r["loyiha"], "pm": r["pm"], "pm_missing": bool(r.get("pm_missing")),
            "qoldiq": v["summa"], "qoldiq_raw": v["summa_raw"], "undirildi": v["undirildi"],
            "lose": v["lose"], "aktiv": v["aktiv"],
            "muddat_s": u._due_str(m) if m else (str(r.get("muddat_raw") or "").strip() or None),
            "muddat_iso": m.isoformat() if m else None,
            "holat": r.get("holat"), "holat_matn": r.get("holat_matn") or "", "hid": None}


def _tab_qatorlari(snap, kun, oy_1):
    u = _u()
    oy, yil = fetchmod.MONTHS[oy_1.month - 1], oy_1.year
    kd = date.fromisoformat(kun)
    rng = u.find_tab(snap, kd, month=oy, year=yil, qat_iy=u.qatiy_oy(oy_1))
    if not rng:
        return None, None
    tab = fetchmod.tab_of_range(rng)
    vals = (snap.get("ranges") or {}).get(rng, {}).get("values", [])
    if not any(str(c).strip() for r in vals for c in (r or [])):
        # Tab butunlay bo'sh (fetch Sheets'dagi bo'sh diapazonni `values: []` saqlaydi) — o'qilmagan kun
        # kabi ko'prik, «hamma qator o'chdi» EMAS. Sarlavhasi bor, qatorsiz tab — haqiqiy o'chirish (ommaviy)
        return tab, None
    iz = []                                      # mahalliy: umumiy undiruv._SARLAVHA_IZOH'ga tegilmaydi
    rows = u.parse_rows(vals, kd, oy_1, tab=tab, izoh=iz)
    if not rows and iz:
        return tab, None
    return tab, [_ixcham_qator(r) for r in rows]


def tab_qatorlari(kun, oy_1, sid=None):
    """(tab, ixcham qatorlar) — `oy_1` oyi tabi `kun` snapshot'idan; (None, None) — snapshot/tab yo'q,
    (tab, None) — sarlavha o'qilmadi (o'sha kun ko'prik bilan o'tkaziladi, «hamma qator o'chdi» EMAS).
    Natija fayl (mtime, hajm) bo'yicha keshlanadi — qaytgan ro'yxat O'ZGARTIRILMASIN."""
    p = _smm_fayl(kun, sid)
    if p is None:
        return None, None
    try:
        k = _stat_kalit(p) + (oy_1.isoformat(),)
    except OSError:
        return None, None
    if k in _QATOR_KESH:
        return _QATOR_KESH[k]
    snap = _snap_oqi(p)
    natija = _tab_qatorlari(snap, kun, oy_1) if isinstance(snap, dict) else (None, None)
    _kesh_qoy(_QATOR_KESH, k, natija, _QATOR_KESH_MAX)
    return natija


# ---- Moslash va bir kunlik qadam (toza funksiya) --------------------------------------------

def _kunlik_tenglik(r, c, i, j):
    """Kunlik juftlashda bir xil nomli (va PM) nomzodlar tartibi: pul (B) teng, muddat teng, sheet'dagi
    o'rni yaqin. Oy almashuvidagi «Summa teng» emas: qisman to'langan qator (Summa $2 000 → $1 000,
    Undirildi +$1 000) egizagi bilan («Tutti» $1 000) almashib, yolg'on ⚠️ berardi."""
    return (_B(_qv(r)) != _B(_qv(c)), r.get("muddat_s") != c.get("muddat_s"), abs(i - j))


def juftla(prev, cur):
    """(pair {i: j}, noaniq {i}, nomlar [(i, j)]). 1–2: undiruv._juftla (aynan nom — bir xil nomlilar
    _kunlik_tenglik bo'yicha; fuzzy ≥0.85 bir PM). 3 (AUDIT 1): qolganlar — PM, pul (B) va muddat aynan
    bir xil, ikki tomonlama yagona bo'lsa — qayta nomlangan (faqat ℹ️). nomlar — nomi (ixcham) farqli juftlar."""
    u = _u()
    pair, noaniq, _fz = u._juftla(prev, cur, list(range(len(prev))), tenglik=_kunlik_tenglik)
    noaniq = set(noaniq)
    used = set(pair.values())

    def imzo(r):
        return (u._pm_kalit(r["pm"]), _B(_qv(r)), r.get("muddat_s"))
    bp = [i for i in range(len(prev)) if i not in pair and i not in noaniq and not prev[i].get("pm_missing")]
    bc = [j for j in range(len(cur)) if j not in used and not cur[j].get("pm_missing")]
    sig_c = {}
    for j in bc:
        sig_c.setdefault(imzo(cur[j]), []).append(j)
    sig_p = {}
    for i in bp:
        sig_p.setdefault(imzo(prev[i]), []).append(i)
    for s, ii in sig_p.items():
        jj = sig_c.get(s) or []
        if len(ii) == 1 and len(jj) == 1 and s[0] and s[1] > TOL:
            pair[ii[0]] = jj[0]
    nomlar = [(i, j) for i, j in sorted(pair.items())
              if u._ixcham(prev[i]["loyiha"]) != u._ixcham(cur[j]["loyiha"])]
    return pair, noaniq, nomlar


def _izoh_miqdori(qa, qb, anchor):
    """Ochiq hodisali qatorda bugungi o'sish (−izohsiz) qanchasi izoh: Undirildi/Lose/Aktive o'sishi
    (Summa kamaygani ayirilgan); Summa o'sishi — faqat hodisadan oldingi Summa'ga AYNAN qaytsa (yangi
    hisob-faktura izoh emas). Qaytadi (izoh, o'sish)."""
    ds = qb["summa"] - qa["summa"]
    dula = sum(qb[k] - qa[k] for k in ("undirildi", "lose", "aktiv"))
    osish = ds + dula
    if osish <= TOL:
        return 0, osish
    if ds <= 0 or abs(qb["summa"] - anchor["summa"]) <= TOL:
        return osish, osish
    return max(0, min(osish, dula)), osish


def _ega(a, b):
    """Holat bugun «Ega qarori» bo'ldi (AUDIT 2: pul yozilmasa ham izoh). «Puli yo'q»/«Pauza» — yo'q."""
    n = lambda r: fetchmod.norm((r or {}).get("holat_matn") or "")  # noqa: E731
    return "ega qarori" in n(b) and "ega qarori" not in n(a)


def _kochdi(a, d, keyingi, kun, b=None, band=None):
    """Oy oxiri (look-ahead kunlari): yo'qolgan pul keyingi oy tabidagi juft qatorga ko'chganmi.
    Qaytadi None — juft yo'q (oddiy hodisa); {…, "kochdi": True} — ko'chirilgan (izohsiz emas, X'ga
    kirmaydi); {…, "kochdi": False} — juft bor, lekin ko'chganiga dalil yo'q: hodisa ochiladi, satrda
    maslahat. Juft (month_transition «aynan» kabi): ikkala qator «To'lov qilindi» emas (to'lov
    Undirildi'ga yozilmagan — bu izohsiz, Marvid 30.09), juft TO'LANMAGAN, muddati keyingi oy 1-sanasidan
    oldin emas, B ≥ yo'qolgan pul. Dalil:
      · muddati hali kelmagan qator (muddat ≥ kun) — juft navbatdagi oylik to'lov emas (KEYINGI_SIKL_KUN)
        va B aynan teng (±$1; Pruddy 30.09 → 05.10) yoki juft shu juftda o'sgan;
      · muddati o'tgan / sanasiz qator — FAQAT juft shu juftda o'sgan bo'lsa (keyingi tab kecha yo'q edi,
        juft qator yangi yoki B ≥ yo'qolgan pulga oshdi). Keyingi tab odatda joriyning nusxasi (o'sha
        mijozning navbatdagi hisobi); sheet ko'chirilgan qarzda eski qatorni yopmaydi (sentabr Bosimov,
        Tanho oktabr bo'yi ochiq) — bo'shatilgan muddati o'tgan qarz hisobdan chiqarish bo'lishi mumkin.
    band — shu juftda ko'chish qabul qilingan juft qatorlar (bitta juft — bitta qator)."""
    if not keyingi or a.get("holat") == "paid" or (b is not None and b.get("holat") == "paid"):
        return None
    u = _u()
    band = set() if band is None else band
    rows = keyingi["rows"]
    j = u._juftla([a], rows, [0])[0].get(0)
    if j is None or j in band:
        return None
    c = rows[j]
    am, cm = a.get("muddat_iso"), c.get("muddat_iso")
    n1 = keyingi.get("oy_1")
    if not u.is_unpaid(c) or not cm or (n1 and cm < n1):
        return None                              # juft qarzni saqlamaydi / eski muddatli nusxa
    bc = _B(_qv(c))
    if bc < d - TOL:
        return None
    oldin_kelmagan = bool(am) and am >= kun
    if oldin_kelmagan and (date.fromisoformat(cm) - date.fromisoformat(am)).days >= u.KEYINGI_SIKL_KUN:
        return None                              # navbatdagi oylik to'lov (KN1)
    oldin = keyingi.get("oldin")                 # kun0 dagi keyingi tab qatorlari (None — tab yo'q edi)
    if oldin is None:
        osdi = True
    else:
        jo = u._juftla([c], oldin, [0], tenglik=_kunlik_tenglik)[0].get(0)   # o'sha qator kecha
        osdi = jo is None or bc - _B(_qv(oldin[jo])) >= d - TOL
    kochdi = osdi or (oldin_kelmagan and abs(bc - d) <= TOL)
    if kochdi:
        band.add(j)
    return {"loyiha": a["loyiha"], "pm": a["pm"], "summa": d, "juft": c["loyiha"], "juft_B": bc,
            "tab": keyingi["tab"], "kochdi": kochdi}


def _qator_tavsifi(qv, oldin=False):
    """Qatorning pul kataklari: «Summa $5 400, Undirildi $1 000» — o'chirilgan (oldin=True: qator
    qiymati) yoki qayta yozilgan qator uchun (nol ↔ qator farqidan, belgisiz)."""
    if oldin:
        qism = carrymod.qator_farqi(qv, _NOL)["qismlar"]
        return [p.split(" → ")[0] if p.startswith("Summa") else p.replace("−", "") for p in qism]
    qism = carrymod.qator_farqi(_NOL, qv)["qismlar"]
    return ["Summa " + p.split(" → ")[1] if p.startswith("Summa") else p.replace("+", "") for p in qism]


def _yangi_hodisa(st, kun, kun0, b, turi, d, qismlar, anchor, muddat=None):
    """Muddat — yo'qolishdan OLDINGI qator muddati (FTTI 06.10 → 07.10 da Final data bo'shatildi)."""
    st["n"] = st.get("n", 0) + 1
    ev = {"id": f"{kun}#{st['n']}", "turi": turi, "loyiha": b["loyiha"], "pm": b["pm"],
          "muddat": muddat or b.get("muddat_s"), "ochildi": kun, "oldin": kun0, "qismlar": qismlar,
          "summa": d, "qoldi": d, "anchor": anchor, "tarix": [[kun, d]], "izohlandi": None,
          "qator_yoq": kun if turi == "ochirilgan" else None}
    st["hodisalar"].append(ev)
    return ev


def _yop(ev, kun, qismlar, sabab):
    ev["qoldi"] = 0
    ev["tarix"].append([kun, 0])
    ev["izohlandi"] = {"kun": kun, "qismlar": qismlar, "sabab": sabab}


def qadam(st, kun0, kun, cur, keyingi=None):
    """Bir juft (kun0 qatorlari st['qatorlar'] → kun qatorlari cur). st joyida o'zgaradi (cur
    ro'yxati o'zi emas — nusxasi). Qaytadi kun yozuvi: hodisa id'lari, ℹ️ ma'lumot va Kelishilgan
    o'zgarishi bo'laklari. Ayniyat (har juftda, butun dollar): −ΔK = ΔLose + ΔAktive + izohsiz +
    o'chirilgan + ega + ko'chdi + noaniq − izohlandi − oshgan − yangi + yaxlit (qoldiq ≠ 0 — kod xatosi).
    Ommaviy kun (≥OMMAVIY_MIN qator birdan) — hodisalar BARIBIR ochiladi va X'ga kiradi (yashirilmaydi),
    faqat ko'rsatishda bitta guruh satri."""
    u = _u()
    prev = st["qatorlar"]
    cur = [dict(r, hid=None) for r in cur]
    hod = {e["id"]: e for e in st["hodisalar"]}

    def ochiq_hid(h):
        return h if h in hod and hod[h]["izohlandi"] is None else None
    pair, noaniq, nomlar = juftla(prev, cur)
    used = set(pair.values())
    t = dict.fromkeys(("izohsiz", "ochirilgan", "ega", "kochdi", "noaniq", "izohlandi",
                       "oshgan", "yangi", "yaxlit"), 0)
    ky = {"oldin": kun0, "yangi": [], "chuqur": [], "yopildi": [], "qisman": [], "kochdi": [],
          "ega": [], "noaniq": [], "noaniq_net": 0, "qator": {}, "ommaviy": None,
          "nomlar": [[prev[i]["loyiha"], cur[j]["loyiha"], cur[j]["pm"]] for i, j in nomlar]}
    yangi_ev, osishlar = [], []
    band = set()                                    # ko'chish qabul qilingan keyingi oy qatorlari

    def qayd(r, v):                                 # qator bo'yicha izohsiz(+)/izohlandi(−) — ko'rsatishda
        k = _nk(r)                                  # P0-3 hukm qilgan qatorlar (nom + PM) alohida bo'lak
        ky["qator"][k] = ky["qator"].get(k, 0) + v
    for i, j in sorted(pair.items()):
        a, b = prev[i], cur[j]
        qa, qb = _qv(a), _qv(b)
        f = carrymod.qator_farqi(qa, qb)
        d = f["izohsiz"]
        hid = ochiq_hid(a.get("hid"))
        ev = hod.get(hid) if hid else None
        b["hid"] = hid
        if ev is not None:                          # hodisa qatorni qayta nomlashda ham kuzatadi
            ev["loyiha"], ev["pm"] = b["loyiha"], b["pm"]
            ev["muddat"] = ev.get("muddat") or b.get("muddat_s")   # faqat bo'sh bo'lsa to'ldiriladi
        if d > TOL:
            if _ega(a, b):
                t["ega"] += d
                ky["ega"].append([b["loyiha"], b["pm"], f["qismlar"], d])
                if ev is not None:
                    _yop(ev, kun, f["qismlar"], "ega")
                    ky["yopildi"].append(hid)
                    b["hid"] = None
                continue
            k = _kochdi(a, d, keyingi, kun, b, band) if ev is None else None
            if k and k["kochdi"]:
                t["kochdi"] += d
                ky["kochdi"].append(dict(k, qismlar=f["qismlar"]))
                continue
            t["izohsiz"] += d
            qayd(b, d)
            if ev is not None:
                ev["summa"] += d
                ev["qoldi"] += d
                ev["tarix"].append([kun, ev["qoldi"]])
                ky["chuqur"].append([hid, d, f["qismlar"]])
            else:
                ev = _yangi_hodisa(st, kun, kun0, b, "izohsiz", d, f["qismlar"], qa, a.get("muddat_s"))
                if fetchmod.norm(b.get("holat_matn")) != fetchmod.norm(a.get("holat_matn")) and b.get("holat_matn"):
                    ev["holat_izoh"] = b["holat_matn"]
                    # pulning bir qismi Undirildi/Lose/Aktive'ga yozilgan (Agromash +$4 500) — «qolgan $X»
                    ev["qisman_yozilgan"] = sum(qb[x] - qa[x] for x in ("undirildi", "lose", "aktiv")) > TOL
                if k:
                    ev["keyingi"] = k                # keyingi oy tabida juft bor, lekin ko'chganiga dalil yo'q
                hod[ev["id"]] = ev
                b["hid"] = ev["id"]
                ky["yangi"].append(ev["id"])
                yangi_ev.append(ev)
        elif d < -TOL:
            if ev is not None:
                izoh, osish = _izoh_miqdori(qa, qb, ev["anchor"])
                if abs(_B(qb) - _B(ev["anchor"])) <= TOL:
                    # Qator jami yo'qolishdan oldingi jamiga qaytdi (Summa qisman + Undirildi; yoki bir necha
                    # qadamda) — to'liq izoh. Ilgari «oshgan» deb sanalgan o'sish shu yerda qaytadi (oshgan < 0)
                    izoh = ev["qoldi"]
                izoh = min(izoh, ev["qoldi"])
                t["izohlandi"] += izoh
                qayd(b, -izoh)
                t["oshgan"] += osish - izoh
                if izoh and ev["qoldi"] - izoh <= TOL:
                    _yop(ev, kun, f["qismlar"], "pul")
                    ky["yopildi"].append(hid)
                    b["hid"] = None
                elif izoh:
                    ev["qoldi"] -= izoh
                    ev["tarix"].append([kun, ev["qoldi"]])
                    ky["qisman"].append([hid, izoh, f["qismlar"]])
            else:
                t["oshgan"] += -d
                osishlar.append((-d, b, f["qismlar"]))
        else:
            t["yaxlit"] += d
            if ev is not None and _ega(a, b):
                _yop(ev, kun, [], "ega")
                ky["yopildi"].append(hid)
                b["hid"] = None
    yetim = dict(st.get("yetim") or {})
    nq_prev = []
    for i, a in enumerate(prev):
        if i in pair:
            continue
        qa = _qv(a)
        bv = _B(qa)
        hid = ochiq_hid(a.get("hid"))
        if hid:
            ev = hod[hid]
            ev["qator_yoq"] = ev.get("qator_yoq") or kun
            yetim[hid] = a
            if bv > TOL:                            # qolgan pul ham qator bilan ketdi
                t["ochirilgan"] += bv
                qayd(a, bv)
                ev["summa"] += bv
                ev["qoldi"] += bv
                ev["tarix"].append([kun, ev["qoldi"]])
                ky["chuqur"].append([hid, bv, ["qator o'chirildi"]])
            else:
                t["yaxlit"] += bv
            continue
        if bv <= TOL:
            t["yaxlit"] += bv                       # $0 qator o'chdi (10.10 kabi) — signal emas
            continue
        if i in noaniq:
            t["noaniq"] += bv
            nq_prev.append(i)
            continue
        k = _kochdi(a, bv, keyingi, kun, band=band)
        if k and k["kochdi"]:
            t["kochdi"] += bv
            ky["kochdi"].append(dict(k, qismlar=["qator o'chirildi"]))
            continue
        qism = _qator_tavsifi(qa, oldin=True)
        t["ochirilgan"] += bv
        qayd(a, bv)
        ev = _yangi_hodisa(st, kun, kun0, a, "ochirilgan", bv, qism, qa, a.get("muddat_s"))
        if k:
            ev["keyingi"] = k
        hod[ev["id"]] = ev
        yetim[ev["id"]] = a
        ky["yangi"].append(ev["id"])
        yangi_ev.append(ev)
    # Qo'shilgan qatorlar: o'chirilgan hodisa qatori qaytsa — qayta bog'lanadi. Kunlik juftlash qoidasi
    # bilan (juftla: aynan nom; fuzzy ≥ FUZZY_MIN shu PM; PM+pul+muddat) — «Icar24» → «Icar 24» ham;
    # o'xshash nomli bir nechta nomzod (noaniq) bog'lanmaydi
    bosh = [j for j in range(len(cur)) if j not in used]
    ys = [(h, a) for h, a in yetim.items() if ochiq_hid(h)]
    qayta = {}
    if ys and bosh:
        yp, _ynq, _yn = juftla([a for _h, a in ys], [cur[j] for j in bosh])
        qayta = {bosh[jj]: ys[ii][0] for ii, jj in yp.items()}
    yangi_j = []
    for j in bosh:
        b = cur[j]
        qb = _qv(b)
        bn = _B(qb)
        h = qayta.get(j)
        if h is not None:
            ev = hod[h]
            del yetim[h]
            ev["qator_yoq"] = None
            b["hid"] = h
            izoh, _o = _izoh_miqdori(_NOL, qb, ev["anchor"])
            if bn > TOL and abs(bn - _B(ev["anchor"])) <= TOL:
                izoh = ev["qoldi"]                  # yo'qolishdan oldingi jami bilan qaytdi
            izoh = min(izoh, ev["qoldi"])
            t["izohlandi"] += izoh
            qayd(b, -izoh)
            t["yangi"] += bn - izoh
            if izoh and ev["qoldi"] - izoh <= TOL:
                _yop(ev, kun, ["qator qayta yozildi"] + _qator_tavsifi(qb), "qator")
                ky["yopildi"].append(h)
                b["hid"] = None
            elif izoh:
                ev["qoldi"] -= izoh
                ev["tarix"].append([kun, ev["qoldi"]])
                ky["qisman"].append([h, izoh, ["qator qayta yozildi"]])
            continue
        t["yangi"] += bn
        yangi_j.append(j)
    for h in [h for h in yetim if not ochiq_hid(h)]:
        del yetim[h]
    st["yetim"] = yetim
    # Noaniq (o'xshash nomli bir nechta nomzod) yo'qolgan qatorlar — hodisa ochilmaydi, X'ga kirmaydi:
    # nomzod (shu PM, fuzzy ≥ FUZZY_MIN) yangi qatorlar puli ayiriladi; qolgani (net) > $1 bo'lsagina ⚠️
    if nq_prev:
        nomzod = set()
        for i in nq_prev:
            pk = u._pm_kalit(prev[i]["pm"])
            for j in yangi_j:
                if (pk and u._pm_kalit(cur[j]["pm"]) == pk
                        and u.nom_ball(prev[i]["loyiha"], cur[j]["loyiha"]) >= u.FUZZY_MIN):
                    nomzod.add(j)
        nb = sum(_B(_qv(cur[j])) for j in nomzod)
        t["yangi"] -= nb
        t["noaniq"] -= nb
        if t["noaniq"] < 0:                         # nomzodlar ko'proq — bu o'sish
            t["yangi"] += -t["noaniq"]
            t["noaniq"] = 0
        ky["noaniq"] = [[prev[i]["loyiha"], prev[i]["pm"], _B(_qv(prev[i]))] for i in nq_prev]
        ky["noaniq_net"] = t["noaniq"]
    # Ommaviy kun — faqat OCHILGAN hodisalar soni bo'yicha (oy oxirida keyingi tabga ko'chgan / «Ega
    # qarori» qatorlari sanalmaydi: aks holda haqiqiy yo'qolish guruh satriga yashirinardi)
    if len(yangi_ev) >= OMMAVIY_MIN and len(yangi_ev) >= OMMAVIY_ULUSH * max(1, len(prev)):
        ky["ommaviy"] = [len(yangi_ev), len(prev)]
    # Noto'g'ri qatorga yozilgan to'lov: shu juftda boshqa qatorda AYNAN shuncha (yagona) o'sish
    for ev in yangi_ev:
        mos = [(x, b, q) for x, b, q in osishlar if abs(x - ev["summa"]) <= TOL]
        if len(mos) == 1:
            ev["boshqa_qator"] = f"{mos[0][1]['loyiha']}: {', '.join(mos[0][2])}"
    K0 = sum(r["qoldiq"] + r["undirildi"] for r in prev)
    K1 = sum(r["qoldiq"] + r["undirildi"] for r in cur)
    L0, L1 = sum(r["lose"] for r in prev), sum(r["lose"] for r in cur)
    A0, A1 = sum(r["aktiv"] for r in prev), sum(r["aktiv"] for r in cur)
    rhs = ((L1 - L0) + (A1 - A0) + t["izohsiz"] + t["ochirilgan"] + t["ega"] + t["kochdi"] + t["noaniq"]
           - t["izohlandi"] - t["oshgan"] - t["yangi"] + t["yaxlit"])
    ky.update(K=[K0, K1], L=[L0, L1], A=[A0, A1], bolak=t, qoldiq=-(K1 - K0) - rhs)
    if ky["qoldiq"]:
        log(f"{kun}: ayniyat qoldig'i {ky['qoldiq']} — kod xatosi")
    st["qatorlar"] = cur
    st["qatorlar_kun"] = kun
    return ky


# ---- Zanjir: oy asosidan D gacha (holatsiz, xotirada) ----------------------------------------

def _snap_kunlari():
    if not diffmod.SNAPSHOTS.is_dir():
        return []
    return sorted(x.name for x in diffmod.SNAPSHOTS.iterdir()
                  if x.is_dir() and len(x.name) == 10 and x.name[4] == "-" and x.name[7] == "-")


def _kun_izi(kun):
    """Kun papkasidagi sheet fayllari izi (nom, mtime, hajm) — zanjir keshi kaliti uchun (faqat stat)."""
    out = []
    for p in sorted((diffmod.SNAPSHOTS / kun).glob("*.json")):
        if p.name in diffmod.SERVICE_FILES:
            continue
        try:
            s = p.stat()
        except OSError:
            continue
        out.append((p.name, s.st_mtime_ns, s.st_size))
    return kun, tuple(out)


def _keyingi(kun, oy_1, sid, kun0=None):
    """Look-ahead kunlarida (oy oxiri) keyingi oy tabi qatorlari — o'sha snapshot'dan; oldin — o'sha
    tab juftning oldingi kuni (kun0) snapshot'ida (None — tab yo'q edi/o'qilmadi): _kochdi dalili."""
    u = _u()
    kd = date.fromisoformat(kun)
    if not (kd.year == oy_1.year and kd.month == oy_1.month and u.oldinga_qarash_faolmi(kd)):
        return None
    n1 = u.oy_ofset(oy_1, 1)[2]
    tab, rows = tab_qatorlari(kun, n1, sid)
    if not rows:
        return None
    oldin = tab_qatorlari(kun0, n1, sid)[1] if kun0 else None
    return {"tab": tab, "rows": rows, "oy_1": n1.isoformat(), "oldin": oldin}


def _holat(oy_1, d, tab, rows, dan):
    return {"oy": oy_1.isoformat()[:7], "tab": tab, "asos_kun": d, "qatorlar_kun": d,
            "oxirgi_kun": d, "qatorlar": [dict(r) for r in rows], "hodisalar": [], "kunlar": {},
            "yetim": {}, "n": 0, "dan": dan}


def _asos(oy_1, kunlar, sid):
    """Oy asosi: 1-sanadan oldingi (≤ASOS_MAX_KUN) shu tab bor oxirgi snapshot (dan=None — «oy
    boshidan»); yo'q bo'lsa — oydagi birinchi shunday kun (dan=o'sha kun, o'sha kuni juft yo'q)."""
    bosh = oy_1.isoformat()
    oldin = [d for d in kunlar if d < bosh and d >= (oy_1 - timedelta(days=ASOS_MAX_KUN)).isoformat()]
    for d in reversed(oldin):
        tab, rows = tab_qatorlari(d, oy_1, sid)
        if rows is not None:
            return _holat(oy_1, d, tab, rows, None)
    for d in kunlar:
        if d >= bosh:
            tab, rows = tab_qatorlari(d, oy_1, sid)
            if rows is not None:
                st = _holat(oy_1, d, tab, rows, d)
                st["kunlar"][d] = {"asos": True}
                return st
    return None


def zanjir(oy_1, D):
    """`oy_1` oyi hodisalari D (snapshot kuni, 'YYYY-MM-DD') gacha — asosdan boshlab har snapshot
    juftida qadam(). None — oyda (va asos oynasida) shu tab bor snapshot yo'q. Sarlavhasi o'qilmagan
    yoki tabsiz kun ko'prik bilan o'tkaziladi (keyingi juft o'sha kundan oldingisiga). Kesh: kunlar
    izi (fayl mtime/hajm) o'zgarmasa — qayta o'qilmaydi. Qaytgan holat ko'rsatishda O'ZGARTIRILMAYDI."""
    kunlar = _snap_kunlari()
    try:
        sid = _u().smm_sheet_id()
    except Exception:                              # noqa: BLE001 — config o'qilmasa skan
        sid = None
    bosh_q = (oy_1 - timedelta(days=ASOS_MAX_KUN)).isoformat()
    oraliq = [d for d in kunlar if bosh_q <= d <= D]
    kalit = (oy_1.isoformat(), D, sid, tuple(_kun_izi(d) for d in oraliq))
    if kalit in _ZANJIR_KESH:
        return _ZANJIR_KESH[kalit]
    try:
        st = _asos(oy_1, oraliq, sid)
        if st is not None:
            bosh = oy_1.isoformat()
            for d in [d for d in oraliq if d > st["oxirgi_kun"] and d >= bosh]:
                if _smm_fayl(d, sid) is None:
                    continue                       # SMM fayli yo'q (faqat report-live.json va h.k.) — kun yo'q
                tab, rows = tab_qatorlari(d, oy_1, sid)
                if rows is None:
                    st["kunlar"][d] = {"otkazildi": "tab yo'q" if tab is None else "sarlavha o'qilmadi"}
                    continue
                st["kunlar"][d] = qadam(st, st["qatorlar_kun"], d, rows,
                                        _keyingi(d, oy_1, sid, st["qatorlar_kun"]))
                st["oxirgi_kun"] = d
                st["tab"] = tab or st.get("tab")
    finally:
        _SNAP_BIR.clear()
    _kesh_qoy(_ZANJIR_KESH, kalit, st, _ZANJIR_KESH_MAX)
    return st


# ---- Ko'rsatish (st O'ZGARTIRILMAYDI — keshda) ------------------------------------------------

def _qoldi_holat(ev, A):
    """Hodisa A kuni holatida: (ochiqmi, qoldi)."""
    q = 0
    for k, v in ev["tarix"]:
        if k <= A:
            q = v
    yop = ev.get("izohlandi")
    return (ev["ochildi"] <= A and q > TOL and not (yop and yop["kun"] <= A)), q


def _muddat(ev):
    return f"muddat {ev['muddat']}" if ev.get("muddat") and ev["muddat"] != "—" else "muddat yo'q"


def _davr(ky, kun):
    return f"{_dm(ky['oldin'])} → {_dm(kun)}"


def _ev_satr(ev, ky, kun):
    nomi = f"{ev['loyiha']} ({ev['pm']}) {_usd(ev['summa'])}, {_muddat(ev)}"
    k = ev.get("keyingi")
    juft = f"«{k['tab']}» tabida «{k['juft']}» {_usd(k['juft_B'])} bor, lekin unga bu pul qo'shilmagan" if k else ""
    if ev["turi"] == "ochirilgan":
        s = (f"⚠️ Qator o'chirilgan: {nomi} — kecha {', '.join(ev['qismlar'])} ({_davr(ky, kun)}); "
             f"qatorni qaytaring yoki Undirildi/Lose summa bilan yoping")
        if juft:
            s += f"; {juft} — ko'chirilgan bo'lsa qatorni qaytarib holatini «Ega qarori» qiling"
    else:
        s = f"⚠️ Izohsiz yo'qolish: {nomi} — {', '.join(ev['qismlar'])} ({_davr(ky, kun)})"
        if ev.get("holat_izoh"):
            s += (f", holat «{ev['holat_izoh']}», lekin "
                  + (f"qolgan {_usd(ev['summa'])}" if ev.get("qisman_yozilgan") else "pul")
                  + " Undirildi/Lose summa'ga yozilmagan")
        if ev.get("boshqa_qator"):
            s += f"; shu kuni {ev['boshqa_qator']} — to'lov boshqa qatorga yozilgan bo'lishi mumkin"
        s += "; Undirildi yoki Lose summa'ga yozing"
        if juft:
            s += f"; {juft} — ko'chirilgan bo'lsa holatini «Ega qarori» qiling"
    return s


def _nomlar(evs, pul=True):
    det = ", ".join(f"{e['loyiha']} ({e['pm']})" + (f" {_usd(e['summa'])}" if pul else "")
                    for e in evs[:OCHIQ_CAP])
    return det + (f" +{len(evs) - OCHIQ_CAP}" if len(evs) > OCHIQ_CAP else "")


def takror_satr(ochiq_ev):
    """«⚠️ Izohsiz yo'qolish — hali izohlanmagan» — ochiq hodisalar (oy oxirigacha har kuni)."""
    if not ochiq_ev:
        return ""
    eski = sorted(ochiq_ev, key=lambda x: (x[0]["ochildi"], x[0]["loyiha"]))
    det = "; ".join(f"{ev['loyiha']} ({ev['pm']}) {_usd(q)}, {_muddat(ev)}, {_dm(ev['ochildi'])} dan"
                    + (", qator o'chirilgan" if ev.get("qator_yoq") else "")
                    for ev, q in eski[:OCHIQ_CAP])
    more = f" +{len(eski) - OCHIQ_CAP}" if len(eski) > OCHIQ_CAP else ""
    return (f"⚠️ Izohsiz yo'qolish — hali izohlanmagan: {len(eski)} ta, "
            f"{_usd(sum(q for _e, q in eski))}: {det}{more}")


def ochiq_hodisalar(st, A, skip=frozenset()):
    out = []
    for ev in st["hodisalar"]:
        o, q = _qoldi_holat(ev, A)
        if o and _nk(ev) not in skip:
            out.append((ev, q))
    return out


def kun_satrlari(st, A, skip=frozenset()):
    """`A` kuni (zanjirning oxirgi jufti) uchun egaga satrlar va A holatidagi ochiq hodisalar.
    skip — P0-3 bugun hukm qilgan qatorlar (nom, PM) — ularning ⚠️/ℹ️ satri P0-3'da."""
    ky = st["kunlar"].get(A) or {}
    hod = {e["id"]: e for e in st["hodisalar"]}

    def korin(ev):
        return _nk(ev) not in skip
    L = []
    ochiq_ev = ochiq_hodisalar(st, A, skip)
    if "K" not in ky:
        return L, ochiq_ev
    yangi = [hod[h] for h in ky.get("yangi", []) if h in hod and korin(hod[h])]
    if ky.get("ommaviy") and yangi:
        L.append(f"⚠️ Izohsiz yo'qolish ({_davr(ky, A)}): {len(yangi)} qator bir kunda, jami "
                 f"{_usd(sum(e['summa'] for e in yangi))} — tab almashgan yoki ustun siljigan bo'lishi "
                 f"mumkin, sheet'ni tekshiring: {_nomlar(yangi)}")
    else:
        for ev in yangi[:YANGI_CAP]:
            L.append(_ev_satr(ev, ky, A))
        if len(yangi) > YANGI_CAP:
            L.append(f"⚠️ Izohsiz yo'qolish: yana {len(yangi) - YANGI_CAP} ta qator, "
                     f"{_usd(sum(e['summa'] for e in yangi[YANGI_CAP:]))} — sheet'da tekshiring")
    chuqur = [(hod[h], d, qism) for h, d, qism in ky.get("chuqur", []) if h in hod and korin(hod[h])]
    for ev, d, qism in chuqur[:YANGI_CAP]:
        L.append(f"⚠️ Izohsiz yo'qolish oshdi: {ev['loyiha']} ({ev['pm']}) +{_usd(d)} — "
                 f"{', '.join(qism)} ({_davr(ky, A)}); jami {_usd(_qoldi_holat(ev, A)[1])} "
                 f"({_dm(ev['ochildi'])} dan)")
    if len(chuqur) > YANGI_CAP:
        L.append(f"⚠️ Izohsiz yo'qolish oshdi: yana {len(chuqur) - YANGI_CAP} ta qator, "
                 f"+{_usd(sum(d for _e, d, _q in chuqur[YANGI_CAP:]))} — sheet'da tekshiring")
    yop_ev = [hod[h] for h in ky.get("yopildi", []) if h in hod and korin(hod[h])]
    if len(yop_ev) > YANGI_CAP:
        L.append(f"✅ Izohsiz yo'qolish izohlandi: {len(yop_ev)} ta qator, "
                 f"{_usd(sum(e['summa'] for e in yop_ev))} — {_nomlar(yop_ev, pul=False)}")
    else:
        for ev in yop_ev:
            yop = ev["izohlandi"] or {}
            sabab = ("holat «Ega qarori»" if yop.get("sabab") == "ega"
                     else ", ".join(yop.get("qismlar") or []))
            L.append(f"✅ Izohsiz yo'qolish izohlandi: {ev['loyiha']} ({ev['pm']}) {_usd(ev['summa'])} — "
                     f"{sabab} ({_dm(ev['ochildi'])} da ochilgan)")
    qisman = [(hod[h], qism) for h, _iz, qism in ky.get("qisman", []) if h in hod and korin(hod[h])]
    for ev, qism in qisman[:YANGI_CAP]:
        L.append(f"ℹ️ Qisman izohlandi: {ev['loyiha']} ({ev['pm']}) — {', '.join(qism)}; "
                 f"{_usd(_qoldi_holat(ev, A)[1])} hali izohsiz ({_dm(ev['ochildi'])} dan)")
    if len(qisman) > YANGI_CAP:
        L.append(f"ℹ️ Qisman izohlandi: yana {len(qisman) - YANGI_CAP} ta qator")
    t = takror_satr([(ev, q) for ev, q in ochiq_ev if ev["ochildi"] < A])
    if t:
        L.append(t)
    if ky.get("nomlar"):
        L.append(f"ℹ️ Qayta nomlangan ({_davr(ky, A)}): "
                 + "; ".join(f"{a} → {b} ({pm})" for a, b, pm in ky["nomlar"][:8])
                 + (f" +{len(ky['nomlar']) - 8}" if len(ky["nomlar"]) > 8 else ""))
    kochdi = ky.get("kochdi") or []
    for k in kochdi[:YANGI_CAP]:
        L.append(f"ℹ️ {k['loyiha']} ({k['pm']}): {', '.join(k['qismlar'])} — «{k['tab']}» tabida "
                 f"«{k['juft']}» {_usd(k['juft_B'])} bor (ko'chirilgan deb olindi, izohsiz emas)")
    if len(kochdi) > YANGI_CAP:
        L.append(f"ℹ️ Keyingi oy tabiga ko'chirilgan deb olindi: yana {len(kochdi) - YANGI_CAP} ta, "
                 f"{_usd(sum(k['summa'] for k in kochdi[YANGI_CAP:]))}")
    ega = ky.get("ega") or []
    for nom, pm, qism, _d in ega[:YANGI_CAP]:
        L.append(f"ℹ️ {nom} ({pm}): {', '.join(qism)} — holat «Ega qarori» (izohsiz deb olinmadi)")
    if len(ega) > YANGI_CAP:
        L.append(f"ℹ️ Holat «Ega qarori» (izohsiz deb olinmadi): yana {len(ega) - YANGI_CAP} ta, "
                 f"{_usd(sum(e[3] for e in ega[YANGI_CAP:]))}")
    b = ky["bolak"]
    dk = ky["K"][1] - ky["K"][0]
    net = ky.get("noaniq_net") or 0
    if net > TOL:
        det = ", ".join(f"{n} ({pm}) {_usd(bv)}" for n, pm, bv in ky["noaniq"][:OCHIQ_CAP])
        L.append(f"⚠️ Kelishilgan izohsiz kamaydi: {_usd(net)} ({_davr(ky, A)}) — qator aniq moslanmadi: "
                 f"{det} (o'xshash nomli qatorlar bor); nomini aniq yozing")
    elif abs(dk) > TOL:
        dl, da = ky["L"][1] - ky["L"][0], ky["A"][1] - ky["A"][0]
        # P0-3 egalik qilgan (ko'chirilgan) qatorlardagi yo'qolish — alohida bo'lak: hukmi yuqoridagi P0-3
        # satrida (bir qatorning yo'qolishi va boshqasining izohi bir-biriga qo'shib yuborilmaydi)
        p03_q = sum(v for k, v in (ky.get("qator") or {}).items() if tuple(k) in skip and v > 0)
        # Yo'qolishdan oldingi jamiga qaytgan qator: avval «oshgan» deb sanalgan o'sish izohga o'tdi
        # (oshgan < 0) — manfiy «oshgan» o'rniga izohlandi bo'lagidan ayiriladi (bugungi K o'zgarishi)
        osh, izl = b["oshgan"] + b["yangi"], b["izohlandi"]
        if osh < 0:
            izl, osh = izl + osh, 0
        qism = [("Lose'ga", -dl), ("Aktive'ga", -da),
                ("izohsiz yo'qolish", -(b["izohsiz"] + b["ochirilgan"] - p03_q)),
                ("ko'chirilgan qarz (yuqoridagi satr)", -p03_q), ("ega qarori", -b["ega"]),
                ("keyingi oyga ko'chdi", -b["kochdi"]), ("aniqlanmagan", -b["noaniq"]),
                ("ilgari yo'qolgan izohlandi", izl),
                ("oshgan/yangi qator", osh)]
        det = ", ".join(f"{n} {'+' if v > 0 else '−'}{_usd(abs(v))}" for n, v in qism if abs(v) > TOL)
        L.append(f"ℹ️ Kelishilgan {_davr(ky, A)}: {_usd(ky['K'][0])} → {_usd(ky['K'][1])} "
                 f"({'+' if dk > 0 else '−'}{_usd(abs(dk))})" + (f": {det}" if det else ""))
    return L, ochiq_ev


def _imzo(r):
    """Qatorning sheet'dagi holati (jonli ↔ snapshot solishtirish uchun)."""
    u = _u()
    q = _qv(r)
    return (u._name_key(r["loyiha"]), u._pm_kalit(r["pm"]), round(q["summa"]), round(q["undirildi"]),
            round(q["lose"]), round(q["aktiv"]), fetchmod.norm(r.get("holat_matn") or ""))


def jonli_farq(v, st):
    """Jonli o'qilgan joriy tab (ko'rinish v) zanjirning oxirgi snapshot qatorlaridan farq qiladimi —
    snapshot olingandan keyin sheet tahrirlangan (/hisobot). 09:00 run'da ular bir xil."""
    if v.get("source") != "live":
        return False
    return Counter(map(_imzo, v.get("rows") or [])) != Counter(map(_imzo, st["qatorlar"]))


def hisobot(today, day, v):
    """summary() uchun: {notes, x, dan, kun, eski[, jonli_farq, lose_snap]}. x — joriy oy ochiq izohsiz
    summasi (P0-3 bugun hukm qilgan qatorlar o'rniga P0-3 summasi, bir marta); dan — zanjir 1-sanadan
    keyin boshlangan kun (None — oy boshidan); kun — ko'rsatilgan snapshot kuni (None — tekshirilmadi);
    eski — kun ≠ day. jonli_farq — 💰 K/U/lose jonli sheet'dan, P0-5 esa bugungi snapshot'dan va ular
    farq qiladi (snapshot'dan keyingi tahrir): satr va belgi shuni aytadi, 2-foizda Lose — snapshot'niki
    (lose_snap; bir pul L'da ham, X'da ham sanalmasin)."""
    u = _u()
    pv = v.get("prev") or {}
    carry = carrymod.ochiq()
    p03 = list(pv.get("izohsiz") or []) if carry else []
    skip = ({tuple(x) for x in pv.get("carry_hamkor") or ()}
            | {(u._name_key(x["loyiha"]), u._pm_kalit(x["pm"])) for x in p03}) if carry else set()
    x03 = sum(_son(x.get("summa")) for x in p03)
    out = {"notes": [], "x": x03, "dan": None, "kun": None, "eski": False}
    st = zanjir(date(today.year, today.month, 1), day)
    if st is None:
        out["notes"].append(f"ℹ️ Izohsiz yo'qolish tekshirilmadi: «{v.get('tab') or 'joriy oy'}» tabi "
                            f"snapshot'larda yo'q")
        return out
    A = st["oxirgi_kun"]
    skip = frozenset(skip)
    if A == day:
        L, ochiq_ev = kun_satrlari(st, A, skip=skip)
        if jonli_farq(v, st):
            out["jonli_farq"] = True
            out["lose_snap"] = round(sum(max(0, r["lose"]) for r in st["qatorlar"]))
            L.insert(0, f"ℹ️ Izohsiz yo'qolish: {_dm(A)} 09:00 snapshot holati — undan keyingi sheet "
                        f"tuzatishlari ertangi hisobotda ko'rinadi")
    else:
        # Bugungi juft yo'q (snapshot hali olinmagan yoki tab o'qilmadi) — oxirgi holat: faqat ochiq ro'yxat
        ochiq_ev = ochiq_hodisalar(st, A, skip)
        sabab = ("snapshot'ida tab o'qilmadi" if (st["kunlar"].get(day) or {}).get("otkazildi")
                 else "snapshot'i yo'q")
        L = [f"ℹ️ Izohsiz yo'qolish: {_dm(day)} {sabab} — {_dm(A)} holati ko'rsatildi"]
        t = takror_satr(ochiq_ev)
        if t:
            L.append(t)
    out["notes"] = L
    out["x"] = x03 + sum(q for _ev, q in ochiq_ev)
    out.update(dan=st.get("dan"), kun=A, eski=A != day)
    return out


def ikkinchi_foiz(s):
    """Ikkinchi foiz: undirildi / (Kelishilgan + Lose + izohsiz), bir kasr xonasi bilan ('33,0') yoki
    None (izohsiz maydoni yo'q yoki lose ham, izohsiz ham 0 — birinchi foizning o'zi)."""
    iz = s.get("izohsiz")
    if not iz:
        return None
    lose = iz["lose_snap"] if iz.get("jonli_farq") and iz.get("lose_snap") is not None else s.get("lose_jami")
    lose, x = lose or 0, iz.get("x") or 0
    maxraj = (s.get("kelishilgan") or 0) + lose + x
    if not (lose or x) or not maxraj:
        return None
    return str(round((s.get("undirildi") or 0) / maxraj * 100, 1)).replace(".", ",")


def belgi(iz):
    """X yorlig'i: «oy boshidan» / «05.10 dan» (+ «, 16.10 snapshot» yoki «, 09:00 snapshot») yoki
    «qatorma-qator tekshirilmadi» — 💰 qatori va PDF bir xil."""
    if iz.get("kun") is None:
        return "qatorma-qator tekshirilmadi"
    b = f"{_dm(iz['dan'])} dan" if iz.get("dan") else "oy boshidan"
    if iz.get("eski"):
        b += f", {_dm(iz['kun'])} snapshot"
    elif iz.get("jonli_farq"):
        b += ", 09:00 snapshot"
    return b


def pul_qatori(s):
    """💰 qatoriga qo'shimcha (AUDIT 4): « · lose $L · izohsiz yo'qolgan $X (oy boshidan) · lose va
    izohsiz hisobga olinsa P%». s — summary() natijasi (kelishilgan, undirildi, lose_jami, izohsiz).
    izohsiz yo'q (kalit o'chiq yoki tekshiruv xato) — "" (💰 qatori o'zgarmaydi)."""
    iz = s.get("izohsiz")
    if not iz:
        return ""
    out = f" · lose {_usd(s['lose_jami'])}" if s.get("lose_jami") is not None else ""
    out += f" · izohsiz yo'qolgan {_usd(iz.get('x') or 0)} ({belgi(iz)})"
    p = ikkinchi_foiz(s)
    if p is not None:
        out += f" · lose va izohsiz hisobga olinsa {p}%"
    return out


def main():
    ap = argparse.ArgumentParser(description="P0-5: izohsiz yo'qolish — snapshot'lardan ko'rish (faqat "
                                             "o'qiydi, hech qanday fayl yozmaydi; Railway operatori uchun)")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    today = date.fromisoformat(a.date)
    # Faqat o'qish: P0-3 royxat() ham muzlatmasin (real sana «oy oxiridan oldin» — xotirada)
    carrymod._bugun = lambda: date(1970, 1, 1)
    v = _u().korinish(today, a.date, prefer_live=False)
    out = hisobot(today, a.date, v)
    print("\n".join(out["notes"]) or "(izohsiz yo'qolish yo'q)")
    if carrymod.ochiq():                           # X'ga kirgan P0-3 (ko'chirilgan qator) summalari
        for x in (v.get("prev") or {}).get("izohsiz") or []:
            print(f"P0-3: {x['loyiha']} ({x['pm']}) {_usd(_son(x.get('summa')))} izohsiz")
    print(f"izohsiz yo'qolgan: {_usd(out['x'])} ({_dm(out['dan']) + ' dan' if out['dan'] else 'oy boshidan'}); "
          f"oxirgi snapshot: {out['kun'] or '—'}")


if __name__ == "__main__":
    main()
