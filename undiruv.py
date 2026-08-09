#!/usr/bin/env python3
"""SMM "Undiruv <oy>" tabini parse qilib, kunlik hisobot uchun jamlaydi.

Tab tuzilmasi (header 2-qatorda): № | Nomi | Ma'sul shaxs | Summa (qoldiq) |
Undirildi | Aktive Summary | Final data (to'lov muddati, KK.OO) | To'lov xolati.
"Jami"/"Ehtimoli aktive" qatorlari jadval tugaganini bildiradi.

Sheet'ning o'z jami mantiqi: Kelishilgan = Σqoldiq + Σundirildi (Aktive Summary
alohida "ehtimoliy" pul sifatida yuritiladi — kelishilganga qo'shilmaydi).
"""
import re
import sys
from datetime import date
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
DUE_SOON_DAYS = 4
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


def parse_due(v, today):
    """To'lov muddatini turli formatdan o'qiydi → date (yoki None):
      DD.MM / D.M (yilsiz → joriy yil), DD.MM.YYYY, DD/MM/YYYY, ISO YYYY-MM-DD,
      Google Sheets serial son (int/float yoki toza raqamli satr, epoch 1899-12-30).
      Chetki bo'shliqlar va ',' ajratuvchi ("05,08") ham qabul qilinadi. Aniqlanmasa None.
      Yil ko'rsatilmagan bo'lsagina joriy yil qo'yiladi (o'tgan/kelasi yil buzilmaydi)."""
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
    m = DDMM_RE.match(s)                 # 06.07 (yilsiz → joriy yil)
    if m:
        return _safe_date(today.year, int(m.group(2)), int(m.group(1)))
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


def carryover_filter(prev_rows, cur_rows):
    """O'tgan oy unpaid qatorlaridan JORIY OY tabida allaqachon yopilganlarini
    ajratadi (pul undirilgan, faqat o'tgan oy tabi tuzatilmagan — PM'ga talab
    KETMAYDI). Yopilgan deb hisoblanadi: joriy oyda shu nomli loyiha bor VA
    (holati To'lov qilindi/Ketdi YOKI Undirildi > 0).
    Qaytadi: (haqiqiy_carryover, joriy_oyda_yopilganlar)."""
    cur_by_name = {_name_key(r["loyiha"]): r for r in cur_rows}
    real, closed = [], []
    for r in prev_rows:
        if not is_unpaid(r):
            continue
        c = cur_by_name.get(_name_key(r["loyiha"]))
        if c and (c["holat"] in ("paid", "ketdi") or c["undirildi"] > 0):
            closed.append(r)
        else:
            real.append(r)
    return real, closed


def parse_rows(vals, today):
    """Tab qiymatlari → [{loyiha, pm, qoldiq, undirildi, aktiv, kelishilgan,
    muddat: date|None, holat}]. Jami/summary qatorlari kirmaydi."""
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
            "lose": money(get(c_lose)),
            "lose_raw": get(c_lose),
            # Kelishilgan = Summa(qoldiq) + Undirildi. Aktiv unga KIRMAYDI —
            # u oldindan to'langan obuna (alohida ma'lumot ustuni).
            "kelishilgan": qoldiq + undirildi,
            # Status katagi bo'sh (paid/ketdi belgilanmagan) — D>0 bo'lsa qarz
            # sanaladi (kam ko'rsatishdan xavfsizroq), lekin egaga ⚠️ belgi.
            "status_blank": not status_raw,
            "muddat": parse_due(get(c_due), today),
            "muddat_raw": get(c_due),
            "holat": _status(status_raw),
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


def rank_month_tabs(titles, month, today=None):
    """'undiruv <oy>' ga mos tab nomlari — eng mos birinchi. YIL QOIDASI:
      (a) joriy yil suffiksi ('(2026)') ENG USTUN,
      (b) suffikssiz aynan 'undiruv <oy>' — keyingi,
      (c) BOSHQA yil suffiksli (2025/2024 arxiv) — HECH QACHON (kandidat emas),
      (d) qolgan tenglikda eng ko'p undirilmagan — fetch_live_month hal qiladi.
    Sabab: 'Undiruv avgust' aynan tenglikka mos, lekin u 2025 arxivi bo'lishi mumkin —
    joriy yil suffiksli tab uni yutib o'tishi shart."""
    today = today or date.today()
    yr = str(today.year)
    scored = []
    for t in titles:
        nt = fetchmod.norm(t)
        if not _tab_matches_month(nt, month):
            continue
        years = _YEAR_RE.findall(nt)
        if years and yr not in years:
            continue                        # boshqa yil arxivi — HECH QACHON tanlanmaydi
        prio = 0 if yr in years else 1      # (a) joriy-yil suffiksi → (b) suffikssiz
        scored.append((prio, nt, t))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in scored]


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


def find_tab(snap, today=None, month=None):
    """Snapshot'dagi "Undiruv <oy>" range kaliti (topilmasa None). month berilmasa
    joriy oy. Mustahkam: imlo/yil-suffiks bo'yicha eng mosini oladi."""
    month = month or fetchmod.current_month_name(today)
    rng_by_norm = {rng: fetchmod.norm(fetchmod.tab_of_range(rng)) for rng in snap.get("ranges", {})}
    matched = [rng for rng, nt in rng_by_norm.items() if _tab_matches_month(nt, month)]
    if not matched:
        return None
    yr = str((today or date.today()).year)
    matched.sort(key=lambda rng: (yr not in rng_by_norm[rng], -len(rng_by_norm[rng]), rng_by_norm[rng]))
    return matched[0]


def smm_sheet_id():
    """Undiruv manba sheet'i (pm_kpi=false) id'si — jonli o'qish uchun."""
    for s in fetchmod.load_config(include_qa_only=True):
        if not s.get("pm_kpi", True):
            return s["id"]
    return None


def fetch_live_month(month_name, today):
    """JONLI: SMM sheet'dan "Undiruv <month_name>" tabini bevosita o'qiydi
    (readonly gspread). Qaytadi: (tab, rows) yoki (None, []). Xato — chaqiruvchi
    ushlaydi (snapshot fallback). consume_tab_note() bilan ega ogohlantirishini oladi.
    Mustahkam: imlo/yil-suffiks; >1 mos → yil+eng-ko'p-undirilmagan bo'yicha tanlaydi
    va ega uchun WARNING qoldiradi; joriy oy topilmasa — eng so'nggi oy tabi (fallback)."""
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
        return parse_rows(vals, today)

    matched = rank_month_tabs(titles, month_name, today)
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
        cands.append((tab, rows, str((today or date.today()).year) in fetchmod.norm(tab),
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


def load_rows(day=None, today=None, prefer_live=True):
    """Undiruv qatorlari. prefer_live=True (default): avval JONLI o'qiladi
    (production 09:00/09:30 uchun MAJBURIY jonli), xato bo'lsagina snapshot
    fallback. Qaytadi: (rows, tab, source) — source ∈ {'live','snapshot','none'}.
    day — snapshot fallback kuni (default: bugun)."""
    today = today or (date.fromisoformat(day) if day else date.today())
    month = fetchmod.current_month_name(today)
    if prefer_live:
        try:
            tab, rows = fetch_live_month(month, today)
            if tab is not None:
                return rows, tab, "live"
            log(f"jonli: «Undiruv {month}» tabi topilmadi — snapshot fallback")
        except Exception as e:
            log(f"jonli o'qish xato ({month}): {type(e).__name__}: {str(e)[:120]} — snapshot fallback")
    day = day or today.isoformat()
    for snap in diffmod.load_day(day)[0].values():
        if snap.get("pm_kpi", True):
            continue
        rng = find_tab(snap, today)
        if rng:
            vals = snap["ranges"][rng].get("values", [])
            return parse_rows(vals, today), fetchmod.tab_of_range(rng), "snapshot"
    return [], None, "none"


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
        "status_blank_n": sum(1 for r in rows if is_unpaid(r) and r.get("status_blank")),
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


def lose_summary(rows):
    """Ketgan loyihalar («To'lov xolati» normalizatsiyadan keyin «ketdi») YAGONA
    jamlamasi. Kunlik PDF (summary) va ega jamlamasi (report_data) IKKALASI shu
    funksiyani chaqiradi — ikki joyda mustaqil hisob-kitob YO'Q. Summa manbai —
    «Lose summa» ustuni (money() bilan parse; "$1 600" kabi probelli qiymatlar).
    D/E qoldiq mantiqi va PM push hisob-kitoblariga TEGMAYDI — alohida qatlam.

    Status aniqlash mavjud _status() orqali («🚪 Ketdi» kabi emoji-prefiks
    NFKC-norm + substring bilan «ketdi»ga tushadi — r["holat"] shuni saqlaydi).

    Qaytadi:
      items    — [{nomi, masul, summa, flag}] status «Ketdi» qatorlar (bo'sh
                 summali ham kiradi, flag bilan);
      total    — Σ summa (faqat summasi bor Ketdi qatorlar);
      count    — len(items) = ketgan loyihalar soni;
      warnings — (a) Ketdi, lekin «Lose summa» bo'sh (har qator uchun satr +
                 item flag'i «summa yozilmagan», jamiga 0);
                 (b) «Lose summa» > 0, lekin status «Ketdi» EMAS — bitta jamlangan
                 satr (ro'yxat va jamiga KIRMAYDI, faqat ogohlantirish)."""
    items, total, warnings = [], 0, []
    empty_names, mismatch = [], []
    for r in rows:
        lose = round(r.get("lose", 0) or 0)
        if r.get("holat") == "ketdi":
            if lose > 0:
                flag = ""
                total += lose
            else:
                flag = LOSE_FLAG_EMPTY
                empty_names.append(r.get("loyiha", "?"))
            items.append({
                "nomi": r.get("loyiha", "?"),
                "masul": r.get("pm", "—"),
                "summa": lose,
                "flag": flag,
            })
        elif lose > 0:
            mismatch.append(r.get("loyiha", "?"))
    for nm in empty_names:
        warnings.append(f"«{nm}» — status «Ketdi», lekin «Lose summa» yozilmagan "
                        "(jamiga 0 qo'shildi).")
    if mismatch:
        warnings.append(
            f"{len(mismatch)} qatorda «Lose summa» bor, status «Ketdi» emas: "
            f"{', '.join(mismatch)}.")
    return {"items": items, "total": total, "count": len(items), "warnings": warnings}


def summary(day, today=None, prefer_live=True):
    """report.json uchun 'undiruv' bloki. Ma'lumot bo'lmasa None.
    prefer_live: production'da JONLI o'qiladi (snapshot faqat fallback)."""
    today = today or date.fromisoformat(day)
    rows, tab, source = load_rows(day, today, prefer_live=prefer_live)
    if not rows:
        return None
    t = totals(rows)
    unpaid = is_unpaid

    def item(r):
        return {
            "pm": r["pm"], "loyiha": r["loyiha"],
            "summa": round(r["qoldiq"]),
            "muddat": _due_str(r["muddat"]),
            "kun": (today - r["muddat"]).days if r["muddat"] else None,
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
    if s["muddat_otgan"]:
        tot = sum(i["summa"] for i in s["muddat_otgan"])
        L.append(f"⏰ Muddati o'tgan, undirilmagan: {len(s['muddat_otgan'])} loyiha, {_fmt_usd(tot)}:")
        for pm, items in _group_pm(s["muddat_otgan"]).items():
            det = ", ".join(f"{i['loyiha']} ({_fmt_usd(i['summa'])}, {i['muddat']})" for i in items)
            L.append(f"  • {pm}: {det}")
    if s["muddat_yaqin"]:
        det = ", ".join(
            f"{i['loyiha']} ({i['pm']}, {_fmt_usd(i['summa'])}, {i['muddat']})"
            for i in s["muddat_yaqin"]
        )
        L.append(f"🔜 Muddati ≤{DUE_SOON_DAYS} kun: {det}")
    if not s["muddat_otgan"] and not s["muddat_yaqin"]:
        L.append("⏰ Muddati o'tgan yoki yaqin qolgan undirilmagan loyiha yo'q ✅")
    if s.get("status_blank_n"):
        L.append(f"⚠️ Status bo'sh (tasdiqlanmagan qarz): {s['status_blank_n']} ta qator")
    return "\n".join(L)


PUSH_DUE_DAYS = 5  # pm_push va PDF hisobotda "muddat yaqin" chegarasi


def report_data(rows, tab, today, source=""):
    """Undiruv hisobotining YAGONA hisob-kitob manbasi — full_report (matn),
    PDF (render_pdf.build_undiruv_html) va caption shu strukturadan quriladi.
    Item status: overdue / soon (≤PUSH_DUE_DAYS) / future / nodate."""
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
    }
    by_pm = {}
    for r in rows:
        by_pm.setdefault(r["pm"], []).append(r)
    aktiv_pms, aktiv_n, aktiv_sum = [], 0, 0
    for pm in sorted(by_pm, key=lambda p: -sum(x["qoldiq"] for x in by_pm[p] if is_unpaid(x))):
        items = []
        for r in sorted((r for r in by_pm[pm] if is_unpaid(r)),
                        key=lambda r: (r["muddat"] is None, r["muddat"] or today)):
            if r["muddat"] is None:
                status, kun = "nodate", None
            elif r["muddat"] < today:
                status, kun = "overdue", (today - r["muddat"]).days
            elif (r["muddat"] - today).days <= PUSH_DUE_DAYS:
                status, kun = "soon", (r["muddat"] - today).days
            else:
                status, kun = "future", (r["muddat"] - today).days
            items.append({
                "loyiha": r["loyiha"],
                "summa": round(r["qoldiq"]),
                "muddat": _due_str(r["muddat"]) if r["muddat"] else "—",
                "status": status,
                "kun": kun,
                "pauza": r["holat"] == "pauza",
                "status_blank": bool(r.get("status_blank")),
            })
        paid = [r for r in by_pm[pm] if r["holat"] == "paid"]
        data["pms"].append({
            "name": pm,
            "n": len(items),
            "sum": round(sum(i["summa"] for i in items)),
            "items": items,
            "paid_n": len(paid),
            "paid_sum": round(sum(r["undirildi"] for r in paid)),
        })
        # Aktiv obuna (oldindan to'langan) — pul so'ralmaydi, faqat ma'lumot
        act = [r for r in by_pm[pm] if is_active_only(r)]
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
    return data


STATUS_MARK = {"overdue": "⏰", "soon": "🔜", "future": "📅", "nodate": "📋"}


def full_report(rows, tab, today, source=""):
    """Dry-run MATN ko'rinishi (PDF fallback va CLI): filtr natijasining TO'LIQ
    ro'yxati PM kesimida, qisqartirishsiz. report_data'dan quriladi.
    Belgilar: ⏰ muddat o'tgan · 🔜 ≤5 kun · 📅 kelajak · 📋 sanasiz."""
    if not rows:
        return "🧪 Undiruv dry-run: qator topilmadi."
    d = report_data(rows, tab, today, source)
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
    for pm in d["pms"]:
        if not pm["n"] and not pm["paid_n"]:
            continue
        L.append(f"\n▸ **{pm['name']}** — undirilmagan {pm['n']} ta, {_fmt_usd(pm['sum'])}:")
        for i in pm["items"]:
            if i["status"] == "nodate":
                mud = "muddat yo'q"
            elif i["status"] == "overdue":
                mud = f"{i['muddat']} ({i['kun']} kun o'tdi)"
            elif i["status"] == "soon":
                mud = f"{i['muddat']} ({i['kun']} kun qoldi)"
            else:
                mud = i["muddat"]
            extra = " ⏸" if i["pauza"] else ""
            extra += " ⚠️status bo'sh" if i.get("status_blank") else ""
            L.append(f"  {STATUS_MARK[i['status']]} {i['loyiha']} — {_fmt_usd(i['summa'])}, {mud}{extra}")
        if pm["paid_n"]:
            L.append(f"  ✅ to'langan: {pm['paid_n']} ta, {_fmt_usd(pm['paid_sum'])}")
    if t.get("status_blank_n"):
        L.append(f"\n⚠️ Status bo'sh (tasdiqlanmagan qarz): {t['status_blank_n']} ta qator — "
                 "D>0 bo'lgani uchun qarz sanaldi; sheet'da holatni belgilash tavsiya etiladi.")
    lose = d.get("lose") or {}
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
    L = [
        title or f"📊 Undiruv ({d['oy']})" + (f" — {d['source']}" if d.get("source") else ""),
        f"JAMI: {_fmt_usd(t['kelishilgan'])} dan {_fmt_usd(t['undirildi'])} undirildi "
        f"({str(t['pct']).replace('.', ',')}%) · qoldiq {_fmt_usd(t['qoldiq'])}"
        + (f" · aktiv {_fmt_usd(t['aktiv'])}" if t["aktiv"] else ""),
    ]
    for pm in d["pms"]:
        if not pm["n"]:
            continue
        od = sum(1 for i in pm["items"] if i["status"] == "overdue")
        L.append(f"{pm['name']}: {pm['n']} ta undirilmagan, {_fmt_usd(pm['sum'])}"
                 + (f" · 🔴 {od} muddat o'tgan" if od else ""))
    lose = d.get("lose") or {}
    if lose.get("count"):
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
        rows, tab, source = load_rows(args.date)
        print(full_report(rows, tab or "?", date.fromisoformat(args.date),
                          source=source))
    else:
        print(report_block(args.date) or "(undiruv ma'lumoti topilmadi)")
