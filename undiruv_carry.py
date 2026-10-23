#!/usr/bin/env python3
"""Oy oxiri ko'chirish ro'yxati (carry) — AUDIT.md P0-3.

Muammo (30.09 → 12.10): 30.09 da bot egaga «🔁 … Bosimov shcool → Bosimov School ($2 500 →
18.10)» deb ko'rsatdi, lekin bu qaror HECH QAYERDA saqlanmadi (keyingi_oyga faqat xotirada,
undiruv.py korinish). 01.10 da month_transition hammasini qaytadan tenglik bilan tasnifladi:
sentabr qatori $1 500 ga o'zgargani uchun oktabr $2 500 bilan teng emas → farqli → Zubair'dan
har kuni «sentyabr qoldig'i $1 500» so'raldi (01.10–12.10); 09.10 dan oktabr qatori bo'shab
(Lose $1 500) $1 000 hech qayerda ko'rinmadi.

  royxat()          — o'tgan oy oxiridagi (look-ahead) OXIRGI report.json'dagi 🔁/🧹 ro'yxat —
                      ega aynan shuni ko'rgan, haqiqat manbai shu. M+1 oyda birinchi o'qishda
                      BIR MARTA DATA_DIR/undiruv_carry/<YYYY-MM>.json ga muzlatiladi (atomik,
                      faqat fayl yo'q bo'lsa): keyin `analyze.py --date <oy oxiri>` qayta
                      ishlatilsa ham (summary jonli-birinchi — ro'yxatni bugungi ma'lumot bilan
                      qayta yozardi), retention (run.sh, 40 kun) snapshot'ni o'chirsa ham o'zgarmaydi.
  tekshir()         — korinish() ichida: ro'yxatdagi qarzning o'tgan oy qatori hali ochiq va
                      L kunidagi o'sha joriy qator bilan juft — PM'dan IKKINCHI marta
                      so'ralmaydi, egaga har kuni «⚠️ Ikki tabda dublikat». Ko'chirilgan joriy
                      qatorda Summa+Undirildi+Lose+Aktive L kunidagidan kam — «$N izohsiz».
  otgan_tab_farqi() — 1–10 kunlar o'tgan oy tabi kecha↔bugun (snapshot↔snapshot) qatorma-qator.

XAVFSIZLIK QOIDASI: qarz PM'dan faqat ega har kuni ⚠️ satr olsa yashiriladi (💰 blok, PDF,
report_data, 09:30 jamlama — hammasi view.notes'dan). Har qanday shubha (manba yo'q/buzuq, juft
o'zgargan, PM boshqa, summa oshgan, hamkor qator yo'q, xato, UNDIRUV_CARRY_OFF=1) — bugungi
xulq: qarz so'raladi.
"""
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import diff as diffmod  # noqa: E402

# Railway volume holati — GIT'GA HECH QACHON (repo public, faylda mijoz nomi va summasi bor).
CARRY_DIR = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "undiruv_carry"
KUZATUV_KUN = 10          # o'tgan oy tabi shu kungacha qatorma-qator kuzatiladi (AUDIT 4)
VERSIYA = 1
_bugun = date.today       # REAL sana (testda almashtiriladi) — `--date` simulyatsiyasi muzlatmasin
# Eski (30.09) report.json'da joriy qator nomi faqat matnda: «A → B ($2 500 → 18.10)»,
# «A → B (sentyabr qoldig'i, $2 950, oktyabr tabida to'langan/ketgan …)»
_MATN_RE = re.compile(r"^(?P<nom>.*) \((?:[^()]*? qoldig'i, )?\$[^()]*\)$")


def _u():
    import undiruv           # kech import — undiruv bu modulni import qiladi (sikl yo'q)
    return undiruv


def log(msg):
    print(f"[undiruv_carry] {msg}", flush=True)


def ochiq():
    """Railway kill switch: UNDIRUV_CARRY_OFF=1 — P0-3 qo'shimchalarining HAMMASI o'chadi
    (dublikat/izohsiz, o'tgan tab kuzatuvi, 💰 dagi ⚖️/noaniq satrlari): 💰 blok, PDF, 09:30
    push va jamlama 69a8de7 bilan baytma-bayt bir xil (report.json'dagi yangi maydonlar —
    keyingi oy uchun ma'lumot — baribir yoziladi). Testlar ham shu bilan izolyatsiya
    qilinadi (tests/conftest.py)."""
    return os.environ.get("UNDIRUV_CARRY_OFF") != "1"


def _son(v):
    try:
        return round(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _usd(v):
    return _u()._fmt_usd(v)


def _dm(d):
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day:02d}.{d.month:02d}"


# ---- Qator qiymatlari (P0-5 ham shu yordamchilarni ishlatadi) -------------------

def qator_qiymat(r):
    """Qatorning SHEET'dagi pul qiymatlari — kunlar/tablar orasida solishtirish uchun.
    qaror_qoll jadvalga kiritilmagan «qoshilsin» qoldig'ini qoldiq'qa qo'shadi (u sheet'da
    yo'q) — ayiriladi, aks holda qaror qo'llangan kun «pul paydo bo'ldi» deb ko'rinardi."""
    if r is None:
        return None
    k = r.get("qoshimcha") or {}
    qo = _son(k.get("summa")) if k and not k.get("jadvalda") else 0
    raw = r.get("qoldiq_raw")
    return {"summa": _son(r.get("qoldiq")) - qo, "summa_raw": None if raw is None else str(raw),
            "undirildi": _son(r.get("undirildi")), "lose": _son(r.get("lose")),
            "aktiv": _son(r.get("aktiv"))}


def _B(x):
    return sum(_son(x.get(k)) for k in ("summa", "undirildi", "lose", "aktiv"))


def _pul(v, raw=None):
    """Summa katagi: bo'sh katak — «bo'sh» ($0 emas: ega sheet'da bo'sh katakni ko'radi)."""
    if v == 0 and raw is not None and not str(raw).strip():
        return "bo'sh"
    return _usd(v)


def qator_farqi(a, b):
    """a (oldin) → b (keyin), qator_qiymat shaklida. Qaytadi {qismlar, izohsiz}.
    Bu sheet'da Summa — QOLGAN qarz (undiruv.parse_rows, kelishilgan = Summa+Undirildi), pul
    faqat Summa → Undirildi/Lose/Aktive orasida ko'chadi: B = Summa+Undirildi+Lose+Aktive
    o'zgarmasligi kerak. izohsiz = B(a) − B(b) ≥ 1 — pul na undirildi, na lose, na aktivga
    yozilgan («Summa $2 500 → bo'sh, Lose +$1 500» → $1 000 izohsiz). AUDIT 2/5-qadamdagi
    «Summa'ni $2 500 ga qaytaring» formulasi bu sheet uchun noto'g'ri (qarzni qayta ochadi)."""
    q = []
    sa, sb = _son(a.get("summa")), _son(b.get("summa"))
    if sa != sb:
        q.append(f"Summa {_pul(sa, a.get('summa_raw'))} → {_pul(sb, b.get('summa_raw'))}")
    for key, nom in (("undirildi", "Undirildi"), ("lose", "Lose"), ("aktiv", "Aktive")):
        d = _son(b.get(key)) - _son(a.get(key))
        if d:
            q.append(f"{nom} {'+' if d > 0 else '−'}{_usd(abs(d))}")
    return {"qismlar": q, "izohsiz": _B(a) - _B(b)}


def _atomik_yoz(path, data):
    """tmp → hard link (bor bo'lsa — birinchi yozgan yutadi, «faqat yo'q bo'lsa») yoki,
    link qo'llanmaydigan FS'da, os.replace. Hech qachon yarim yozilgan fayl qolmaydi.
    tmp HAR CHAQIRUVGA alohida (mkstemp): supervisor jarayonida 09:30 push va bot handler
    oqimlari bir pid'da — umumiy «.{pid}.tmp» nomida B oqimi O_TRUNC bilan A link qilgan
    (endi e'lon qilingan) inode'ni bo'shatardi. Yozish xato bo'lsa ham tmp o'chiriladi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass                              # parallel jarayon muzlatib ulgurdi — o'shaniki qoladi
        except OSError:
            os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


# ---- Ro'yxat: oy oxiri report.json → bir martalik muzlatish ---------------------

def _fayl(oy_oxiri):
    return CARRY_DIR / f"{oy_oxiri.year:04d}-{oy_oxiri.month:02d}.json"


def _oxirgi_report(oy_oxiri):
    """Look-ahead faol kunlarda (oy oxiri, ≤PUSH_DUE_DAYS) oxirgidan orqaga: o'sha kun
    keyingi-oy bloki bor report.json. Qaytadi (kun|None, undiruv|None, xato|None).
    Fayl yo'q / undiruv yoki keyingi yo'q — o'sha kun ishlamagan, oldingi kunga o'tiladi.
    O'QILMAGAN fayl — to'xtaydi (eski kunga TUSHMAYDI: 26-dagi «ko'chdi» 30-dagi tasnifni
    yashirmasin). Birinchi topilgan (eng oxirgi) kun yutadi — ro'yxati bo'sh bo'lsa ham."""
    u = _u()
    d = oy_oxiri
    while u.oldinga_qarash_faolmi(d):
        p = diffmod.SNAPSHOTS / d.isoformat() / "report.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:               # noqa: BLE001 — buzuq fayl jim {} emas
                return d, None, e
            und = data.get("undiruv") if isinstance(data, dict) else None
            k = und.get("keyingi") if isinstance(und, dict) else None
            if isinstance(k, dict):
                return d, und, None
        d -= timedelta(days=1)
    return None, None, None


def _hamkor(rows, nom, pmlar):
    """Joriy tabdagi hamkor qator — aniq (_ixcham) nom bo'yicha. PM faqat bir xil nomli qatorlar
    bir nechta bo'lsa ajratadi (pmlar tartibida: L kunidagi hamkor PM'i, keyin o'tgan oy PM'i):
    _juftla aniq nomni PM'dan qat'i nazar juftlaydi, oy almashganda PM o'zgaradi (30.09: «Mono
    electric: Muharram → Asadbek») — o'tgan oy PM'i bilan izlash «topilmadi» deb yolg'on ⚠️
    berib, izohsiz tekshiruvini o'tkazib yuborardi. Qaytadi (qator|None — yo'q/noaniq, nomli soni)."""
    u = _u()
    ck = u._ixcham(nom)
    cc = [c for c in rows if u._ixcham(c["loyiha"]) == ck]
    n = len(cc)
    for pk in map(u._pm_kalit, pmlar):
        if len(cc) <= 1:
            break
        cc = [c for c in cc if pk and u._pm_kalit(c["pm"]) == pk] or cc
    return (cc[0] if len(cc) == 1 else None), n


def _matndan_nom(e):
    """Eski yozuv (cur_loyiha yo'q): joriy qator nomi matndan, aks holda loyiha o'zi."""
    nom = str(e.get("loyiha") or "")
    m = _MATN_RE.match(str(e.get("matn") or ""))
    if m and m.group("nom").startswith(nom + " → "):
        return m.group("nom")[len(nom) + 3:]
    return nom


def _legacy_baza(items, kun, today, manba_tab, keyingi_tab):
    """Eski (30.09) yozuvda L kunidagi qiymatlar yo'q — o'sha kun snapshot'idan BIR MARTA
    (muzlatishda) olinadi. Moslik: aniq nom + PM, yagona qator, Summa report.json'dagi bilan
    AYNAN teng (report.json jonli o'qishdan, snapshot 09:00 fetch'dan — orada tahrir bo'lsa
    asos noma'lum qoladi: izohsiz tekshiruvi aynan turida 0/0/0 ga tushadi, qaror_* da jim)."""
    u = _u()
    pm_, py, p1 = u.oy_ofset(today, -1)
    cm, cy, c1 = u.oy_ofset(today, 0)
    d = kun.isoformat()
    try:
        ptab, prow, _s = u._oy_oqi(pm_, py, p1, kun, d, False, u.qatiy_oy(p1), [])
        ctab, crow, _s = u._oy_oqi(cm, cy, c1, kun, d, False, True, [])
    except Exception as e:                       # noqa: BLE001
        log(f"{d} snapshot'idan asos olinmadi: {type(e).__name__}: {e}")
        return f"xato:{type(e).__name__}"
    if not u._tab_mos(ptab, manba_tab):
        prow = []
    if not u._tab_mos(ctab, keyingi_tab):
        crow = []
    if not prow and not crow:
        return "yoq"
    for e in items:
        nk, pk = u._name_key(e["loyiha"]), u._pm_kalit(e.get("pm"))
        rr = [r for r in prow if u._name_key(r["loyiha"]) == nk and u._pm_kalit(r["pm"]) == pk]
        if len(rr) == 1 and round(rr[0]["qoldiq"]) == e["summa"]:
            e["eski"] = qator_qiymat(rr[0])
        c, _n = _hamkor(crow, e.get("yangi_loyiha") or e["loyiha"], (e.get("yangi_pm"), e.get("pm")))
        if (c is not None and e.get("yangi_summa") is not None
                and round(c["qoldiq"]) == _son(e["yangi_summa"])):
            e["yangi"] = qator_qiymat(c)
    return f"snapshot:{d}"


def _yozuv(und, kun, today):
    u = _u()
    prev_m = u.oy_ofset(today, -1)[0]
    k = und["keyingi"]
    items = []
    if k.get("tab"):                              # keyingi tab yo'q edi — ega ko'chish ko'rmagan
        for tur in ("kochgan", "yopilgan"):
            for e in k.get(tur) or []:
                if not isinstance(e, dict) or not e.get("loyiha"):
                    continue
                if e.get("manba_oy") not in (None, prev_m):
                    continue                     # 2 oy oldingi qoldiq (t3) — boshqa tab
                items.append({
                    "loyiha": e["loyiha"], "pm": e.get("pm"), "turi": e.get("turi"),
                    "summa": _son(e.get("summa")), "yangi_summa": e.get("yangi_summa"),
                    "yangi_loyiha": e.get("cur_loyiha") or _matndan_nom(e),
                    "yangi_pm": e.get("cur_pm"), "yangi_muddat": e.get("yangi_muddat"),
                    "eski": e.get("eski") if isinstance(e.get("eski"), dict) else None,
                    "yangi": e.get("yangi") if isinstance(e.get("yangi"), dict) else None,
                    "legacy": "eski" not in e})
    rec = {"versiya": VERSIYA, "manba_oy": und.get("oy"), "manba_tab": und.get("tab"),
           "keyingi_tab": k.get("tab"), "kun": kun.isoformat(), "manba": "report.json",
           "muzlatildi": _bugun().isoformat(), "items": items}
    eski = [e for e in items if e["legacy"]]
    if eski:
        rec["baza"] = _legacy_baza(eski, kun, today, und.get("tab"), k.get("tab"))
    return rec


def royxat(today):
    """O'tgan oy oxirida egaga «🔁 ko'chirilgan / 🧹 yopilgan» deb ko'rsatilgan qarzlar —
    muzlatilgan yozuv. Qaytadi (yozuv|None, egaga_izohlar).
      · fayl bor — o'qiladi; buzuq bo'lsa QAYTA YOZILMAYDI (S5, qarzlar so'raladi);
      · fayl yo'q — oy oxiri report.json'dan quriladi va BIR MARTA yoziladi;
      · manba topilmadi — hech narsa yozilmaydi (bo'sh ro'yxat abadiy muzlamasin);
      · REAL sana hali oy oxiridan o'tmagan (`pm_push.py --dry-run --date 2026-11-01` 28.10 da)
        — faqat xotirada: aks holda 28.10 ro'yxati muzlab, 29–31.10 dagi oxirgi ko'rinish
        (T8: oxirgi kun yutadi) abadiy e'tiborsiz qolardi."""
    if not ochiq():
        return None, []
    u = _u()
    oxiri = today.replace(day=1) - timedelta(days=1)
    prev_m = u.oy_ofset(today, -1)[0]
    path = _fayl(oxiri)
    if path.exists():
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if not (isinstance(rec, dict) and rec.get("versiya") == VERSIYA
                    and isinstance(rec.get("items"), list)
                    and all(isinstance(e, dict) for e in rec["items"])):
                raise ValueError("tuzilma noto'g'ri")
            date.fromisoformat(rec.get("kun"))
            return rec, []
        except Exception as e:                   # noqa: BLE001
            log(f"{path} buzilgan: {type(e).__name__}: {e}")
            return None, [f"⚠️ undiruv_carry/{path.name} buzilgan ({type(e).__name__}) — oy oxiri "
                          f"ko'chirish ro'yxati tekshirilmadi, {prev_m} qoldiqlari odatdagidek "
                          f"so'ralmoqda (faylni o'chiring — {_dm(oxiri)} report.json'dan qayta tiklanadi)"]
    kun, und, xato = _oxirgi_report(oxiri)
    if xato is not None:
        log(f"{kun} report.json o'qilmadi: {type(xato).__name__}: {xato}")
        return None, [f"⚠️ {_dm(kun)} report.json o'qilmadi ({type(xato).__name__}) — oy oxiri "
                      f"ko'chirish ro'yxati tekshirilmadi, {prev_m} qoldiqlari odatdagidek so'ralmoqda"]
    if kun is None:
        return None, []
    rec = _yozuv(und, kun, today)
    if _bugun() <= oxiri:
        log(f"{path.name} muzlatilmadi: simulyatsiya ({today}), real sana {_bugun()} — faqat xotirada")
        return rec, []
    try:
        _atomik_yoz(path, rec)
        log(f"{path.name} muzlatildi: {kun} report.json, {len(rec['items'])} ta yozuv")
    except OSError as e:
        log(f"{path} yozilmadi ({type(e).__name__}: {e}) — bugun xotiradan ishlatildi")
    return rec, []


# ---- korinish() ichidagi tekshiruv ------------------------------------------------

def _hozir(c):
    """Joriy (hamkor) qator holati — dublikat satri uchun."""
    u = _u()
    s = _pul(round(c["qoldiq"]), c.get("qoldiq_raw"))
    if c["holat"] == "paid":
        return "to'langan"
    if c["holat"] == "ketdi":
        return f"{s}, Lose {_usd(c.get('lose') or 0)}"
    if u.is_unpaid(c):
        return s + (f", {u._due_str(c['muddat'])}" if c.get("muddat") else "")
    if u.is_active_only(c):
        return f"{s}, Aktive {_usd(c['aktiv'])}"
    return s


def tekshir(t1, prows, tab, prev_m, cur_m, today, ptab=None):
    """korinish() ichida, t1 + kechish_ajrat'dan keyin, look-ahead (t3 `_i`) dan OLDIN.
    Qaytadi {dublikat: [o'tgan oy qatorlari], izohsiz: [{loyiha, pm, summa}], notes,
    skip: {name_key} (dublikat — o'tgan tab kuzatuvi takrorlamasin), kochgan: {name_key},
    hamkor: {(name_key, pm_kalit)} — JORIY tab qatorlari, ularni P0-3 BUGUN hukm qildi: izohsiz ⚠️, o'tgan
    tab izohlagan (ℹ️/jim) yoki «topilmadi». P0-5 (undiruv_izohsiz) faqat shu kunlari ularni takrorlamaydi;
    P0-3 jim kunlari (asosga nisbatan joyida — ustiga yangi hisob tushgan bo'lsa ham) P0-5 o'zi ko'rsatadi.
    PM bilan: shu nomli boshqa PM qatori (yangi mijoz/hisob) P0-5'dan yashirinmaydi}.
    Oxirgi qadamgacha toza; oxirida t1 real/farqli/noaniq kechish_ajrat kabi qayta bog'lanadi.

    DUBLIKAT (PM'dan so'ralmaydi, egaga ⚠️) — HAMMASI bajarilsa: o'tgan oy qatori yozuv bilan
    aniq nom + PM bo'yicha yagona; bugun t1 real'da (so'ralmoqchi); ko'chish turi joriy qator
    qarzni sheet'da saqlaydigan (aynan/yopilgan/qaror_jadvalda); hamkor joriy qator (L kunidagi
    nom, _hamkor) yagona va _juftla bugun ham aynan shu qatorni juftlagan; qoldiq L kunidagidan
    OSHMAGAN. Hamkor nomi yo'q — ⚠️ va so'raladi. Boshqa har holat — bugungi xulq.
    IZOHSIZ — hamkor qator L kunidagi asosga nisbatan (o'tgan qator qaysi tasnifda bo'lishidan
    qat'i nazar: PR #1 K2 uni yopsa ham $1 000 ko'rinadi)."""
    u = _u()
    out = {"dublikat": [], "izohsiz": [], "notes": [], "skip": set(), "kochgan": set(), "hamkor": set()}
    rec, iz = royxat(today)
    out["notes"] += iz
    if not rec or tab is None or not u._tab_mos(rec.get("keyingi_tab"), tab):
        return out
    # O'tgan oy tabi boshqa (nusxa/qayta nomlangan) — o'tgan qatorlarga ishonilmaydi: dublikat yo'q
    prev_ok = ptab is not None and (not rec.get("manba_tab") or u._tab_mos(rec["manba_tab"], ptab))
    sana = _dm(rec["kun"])
    cur = t1["cur_rows"]
    real_id = {id(r) for r in t1["real"]}
    idx = {id(r): i for i, r in enumerate(prows)}
    faol = u.oldinga_qarash_faolmi(today)
    next_m = u.oy_ofset(today, 1)[0]
    olib, notes, izohsiz = {}, [], []
    for e in rec["items"]:
        nom0 = str(e.get("loyiha") or "")
        nk, pk = u._name_key(nom0), u._pm_kalit(e.get("pm"))
        if not nk:
            continue
        turi = str(e.get("turi") or "")
        if turi != "qaror_qoshildi":             # qarz sheet'da ko'chmagan (bot xotirada qo'shgan)
            out["kochgan"].add(nk)
        if not pk:
            continue                             # PM'siz yozuv — aniq moslab bo'lmaydi
        rr = ([r for r in prows if u._name_key(r["loyiha"]) == nk and u._pm_kalit(r["pm"]) == pk]
              if prev_ok else [])
        r = rr[0] if len(rr) == 1 else None
        yn = e.get("yangi_loyiha") or nom0
        c, n_nom = _hamkor(cur, yn, (e.get("yangi_pm"), e.get("pm")))
        eski = e.get("eski") if isinstance(e.get("eski"), dict) else None
        if r is not None and id(r) in real_id and u.is_unpaid(r):
            j = t1["juft"].get(idx[id(r)])
            if not n_nom:
                notes.append(f"⚠️ {r['loyiha']} ({r['pm']}): {sana} da {cur_m} tabiga «{yn}» bo'lib "
                             f"ko'chirilgan edi, endi u yerda topilmadi — {prev_m} qoldig'i "
                             f"{_usd(r['qoldiq'])} qayta so'ralmoqda")
                # P0-5: qarz o'tgan tabdan qayta so'raladi — joriy nusxa o'chgani «yo'qolish» emas
                # (qator yo'q — L kunidagi joriy PM'i va o'tgan oy PM'i bilan)
                for p_ in {e.get("yangi_pm"), e.get("pm")}:
                    out["hamkor"].add((u._name_key(yn), u._pm_kalit(p_)))
            # Faqat joriy qator qarzni SHEET'da o'zi saqlasa. qaror_qoshildi ($364 bot xotirada
            # qo'shgan) / qaror_yangi_toliq — qaror amal qilsa month_transition r'ni real'dan
            # o'zi oladi; bu yerga faqat qaror ESKIRGANDA keladi — undiruv.py qoidasi («📝 …
            # eskirgan», o'tgan qoldiq so'raladi) yutishi kerak, «dublikat, yoping» qarzni
            # hisobdan chiqartirardi.
            elif (turi in ("aynan", "yopilgan", "qaror_jadvalda") and c is not None and j is not None
                    and cur[j] is c and round(r["qoldiq"]) <= _son(e.get("summa"))):
                rq = round(r["qoldiq"])
                nom = r["loyiha"] + (f" → {c['loyiha']}" if u._ixcham(c["loyiha"]) != u._ixcham(r["loyiha"]) else "")
                es = _son(e.get("summa"))
                oldin = f" ({sana} da {_usd(es)})" if eski is None and es != rq else ""
                if turi.startswith("qaror"):
                    belgi = f"{sana} ega qarori bilan {cur_m}ga ko'chirilgan"
                elif turi == "yopilgan":
                    belgi = f"{sana} da {cur_m} tabida to'langan/ketgan deb yozilgan"
                else:
                    belgi = f"{sana} da {cur_m}ga ko'chirilgan"
                tafsil = ""
                if eski is not None:
                    pf = qator_farqi(eski, qator_qiymat(r))
                    if pf["qismlar"]:
                        tafsil = (f"; {prev_m} tabida {sana} dan beri: {', '.join(pf['qismlar'])}"
                                  + (f", {_usd(pf['izohsiz'])} izohsiz" if pf["izohsiz"] >= 1 else ""))
                s = (f"⚠️ Ikki tabda dublikat: {nom} ({r['pm']}) — {prev_m} {_usd(rq)}{oldin} / "
                     f"{cur_m} {_hozir(c)} ({belgi}, {prev_m} qoldig'i PM'dan so'ralmaydi{tafsil}) — "
                     f"{prev_m} tabidagi qatorni yoping")
                if faol:                         # 1-sanadan bot faqat bir oy orqaga qaraydi
                    s += f" — 1-{next_m}dan bot {prev_m} tabini kuzatmaydi"
                notes.append(s)
                olib[id(r)] = r
        if c is None:
            continue
        base = e.get("yangi") if isinstance(e.get("yangi"), dict) else None
        if base is None:
            if not (e.get("legacy") and e.get("turi") == "aynan"):
                continue                         # asos noma'lum (eski qaror_* yozuvi) — jim
            # «aynan» ko'chishda joriy qator to'lanmagan, Undirildi 0 edi (month_transition)
            ys = e.get("yangi_summa")
            base = {"summa": _son(e.get("summa") if ys is None else ys), "summa_raw": None,
                    "undirildi": 0, "lose": 0, "aktiv": 0}
        f = qator_farqi(base, qator_qiymat(c))
        if f["izohsiz"] < 1:
            continue                             # P0-3 jim — P0-5 bu qatorni o'zi kuzatadi (hamkor EMAS)
        # P0-5: bugun bu qatorni P0-3 hukm qiladi (o'tgan tab izohlagan $1 000 ham, ⚠️ $917 ham) —
        # undiruv_izohsiz takrorlamaydi. Faqat hukm kuni: asos kumulyativ, keyingi o'sish eski
        # yo'qolishni «yopib» qo'yardi — P0-3 jim bo'lgan kun P0-5 ning o'z ⚠️/✅ i ko'rinadi
        out["hamkor"].add((u._name_key(c["loyiha"]), u._pm_kalit(c["pm"])))
        nomi = f"{c['loyiha']} ({c['pm']}, {cur_m})"
        x, qism = None, []
        if r is not None and eski is not None:
            hozir = qator_qiymat(r)
            x = (hozir["undirildi"] - _son(eski.get("undirildi"))) + (hozir["lose"] - _son(eski.get("lose")))
            qism = [p for p in qator_farqi(eski, hozir)["qismlar"] if p.startswith(("Undirildi", "Lose"))]
        # Izohlangan — o'tgan oy tabida AYNAN yetishmagan pul yozilgan (x == izohsiz; ustiga faqat
        # ko'chishda kamaytirilgan qism: qaror yangi_toliq Maestro $2 100 → $2 000, aynan'da 0).
        # Ko'prog'i — bir qarz ikki tabda yozilgan: sentabr nusxasi oktabrdek «Puli yo'q, Lose
        # $1 500» bilan yopilsa $3 000 / $2 500 qarz, $1 000 yana jim yo'qolardi (AUDIT P0-3).
        if x is not None and f["izohsiz"] <= x <= f["izohsiz"] + max(0, _son(eski.get("summa")) - _B(base)):
            # 1–10 kunlar ℹ️, keyin jim (dublikat satri o'sha kontekstni ko'rsatib turadi)
            if today.day <= KUZATUV_KUN:
                notes.append(f"ℹ️ {nomi}: {', '.join(f['qismlar'])} ({sana} dan beri); qolgan "
                             f"{_usd(f['izohsiz'])} {prev_m} tabida yozilgan ({', '.join(qism)})")
            continue
        if x is not None and x > f["izohsiz"]:
            notes.append(f"⚠️ {nomi}: {', '.join(f['qismlar'])}, {_usd(f['izohsiz'])} izohsiz "
                         f"({sana} dan beri); {prev_m} tabida ham {', '.join(qism)} — bir qarz ikki "
                         f"tabda yozilgan, ikkalasini solishtiring")
        else:
            notes.append(f"⚠️ {nomi}: {', '.join(f['qismlar'])}, {_usd(f['izohsiz'])} izohsiz "
                         f"({sana} dan beri) — {cur_m} qatorida Undirildi yoki Lose'ga yozing")
        izohsiz.append({"loyiha": c["loyiha"], "pm": c["pm"], "summa": f["izohsiz"]})
    out["notes"] += notes
    out["izohsiz"] = izohsiz
    if olib:
        t1["real"] = [x for x in t1["real"] if id(x) not in olib]
        kk = {(x["loyiha"], x["pm"], round(x["qoldiq"])) for x in olib.values()}
        for key in ("farqli", "noaniq"):
            t1[key] = [x for x in t1[key] if (x["loyiha"], x["pm"], round(x["qoldiq"])) not in kk]
        out["dublikat"] = list(olib.values())
        out["skip"] = {u._name_key(x["loyiha"]) for x in olib.values()}
    return out


# ---- O'tgan oy tabi: kecha ↔ bugun (1–10 kunlar, AUDIT 4) --------------------------

def otgan_tab_farqi(today, day, skip=(), kochgan=(), cur_rows=()):
    """O'tgan oy tabi diff.py'da kuzatilmaydi (faqat «1/47 tab o'zgargan» — 01.10, 02.10):
    sentabr Bosimov $2 500 → $1 500 qaysi ustundan bo'lgani hech qayerda ko'rinmadi. 1–10
    kunlar snapshot↔snapshot (qayta ishga tushirsa ham bir xil) qatorma-qator:
      · qator Summa → 0 (izohsiz ≤ eski Summa) yoki o'chirilgan — ko'chirilgan (L kunidagi
        yozuvda) yoki BUGUNGI joriy tabda bor (_juftla jufti to'langan/ketgan yoki pulni
        saqlaydi) — ℹ️: ega qarzni L dan keyin ko'chirgan, 🧹/dublikat ko'rsatmasiga ko'ra
        o'tgan tabni yopgan. Bular faqat yozuvga qarab ⚠️ «izohsiz» bo'lardi (bot o'z
        ko'rsatmasi bajarilganda «pul yo'qoldi» derdi);
      · qolgan izohsiz ≥ $1 — ⚠️ alohida satr (eng ko'pi 8 ta); o'chirilgan qator (Summa > 0) — ⚠️;
      · qolgan pul o'zgarishlari — bitta ℹ️ satrga.
    skip — dublikat satrida allaqachon ko'rsatilganlar; cur_rows — bugungi joriy oy qatorlari
    (korinish rows). Faqat summary() dan (09:00 hisobot, /hisobot) chaqiriladi — 09:30 push va
    dashboard qo'shimcha snapshot o'qimaydi."""
    if not ochiq() or today.day > KUZATUV_KUN or not (diffmod.SNAPSHOTS / day).is_dir():
        return []
    d_y = diffmod.prev_day(day)
    if d_y is None:
        return []
    u = _u()
    pm_, py, p1 = u.oy_ofset(today, -1)
    tab_y, ry, _s = u._oy_oqi(pm_, py, p1, today, d_y, False, True, [])
    tab_t, rt, _s = u._oy_oqi(pm_, py, p1, today, day, False, True, [])
    if tab_y is None or tab_t is None or not u._tab_mos(tab_y, tab_t):
        return []
    pair, _noaniq, _fuzzy = u._juftla(ry, rt, list(range(len(ry))))
    cur_rows = list(cur_rows)
    hpair = u._juftla(ry, cur_rows, list(range(len(ry))))[0] if cur_rows else {}
    cur_m = u.oy_ofset(today, 0)[0]
    oy, yon = pm_.capitalize(), f"{_dm(d_y)} → {_dm(day)}"
    info, warn = [], []

    def hamkor(i, summa):
        j = hpair.get(i)
        c = cur_rows[j] if j is not None else None
        if c is not None and (c["holat"] in ("paid", "ketdi") or _B(qator_qiymat(c)) >= summa):
            return f"{cur_m} tabida: {c['loyiha']}, {_hozir(c)}"
        return None

    for i, a in enumerate(ry):
        nk = u._name_key(a["loyiha"])
        if nk in skip:
            continue
        j = pair.get(i)
        if j is None:
            if round(a["qoldiq"]) > 0:
                h = "ko'chirilgan qarz" if nk in kochgan else hamkor(i, round(a["qoldiq"]))
                if h:
                    info.append(f"{a['loyiha']} ({a['pm']}): qator o'chirildi, Summa {_usd(a['qoldiq'])} — {h}")
                else:
                    warn.append(f"⚠️ {oy} tabi ({yon}): qator o'chirilgan — {a['loyiha']} ({a['pm']}) "
                                f"Summa {_usd(a['qoldiq'])}")
            continue
        b = rt[j]
        qa, qb = qator_qiymat(a), qator_qiymat(b)
        f = qator_farqi(qa, qb)
        if not f["qismlar"]:
            continue
        nomi = f"{b['loyiha']} ({b['pm']})"
        h = None
        if f["izohsiz"] >= 1 and qb["summa"] == 0 and f["izohsiz"] <= qa["summa"]:
            h = "ko'chirilgan qarz yopildi" if nk in kochgan else hamkor(i, f["izohsiz"])
        if h:
            info.append(f"{nomi}: {', '.join(f['qismlar'])} — {h}")
        elif f["izohsiz"] >= 1:
            warn.append(f"⚠️ {oy} tabi ({yon}): {nomi}: {', '.join(f['qismlar'])}, "
                        f"{_usd(f['izohsiz'])} izohsiz")
        else:
            info.append(f"{nomi}: {', '.join(f['qismlar'])}")
    if len(warn) > 8:
        warn = warn[:8] + [f"⚠️ {oy} tabi ({yon}): yana {len(warn) - 8} ta qator — sheet'da tekshiring"]
    if info:
        warn.insert(0, f"ℹ️ {oy} tabi o'zgardi ({yon}): " + "; ".join(info[:8])
                    + (f" +{len(info) - 8}" if len(info) > 8 else ""))
    return warn
