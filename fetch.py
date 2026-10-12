#!/usr/bin/env python3
"""Google Sheets'lardan ma'lumot olib, kunlik snapshot sifatida saqlaydi.

mode: all_tabs — har sheet'ning BARCHA tab'lari avtomatik discovery qilinadi
(1 ta metadata so'rov + 1 ta values batchGet — quota tejaladi). Snapshot'ga
hammasi yoziladi; kunlik diff uchun esa watch_tabs (default: auto — Main +
joriy oy tabi, "Iyul " oxiridagi bo'shliq kabi variantlarni ham o'zi taniydi)
ro'yxati snapshot ichida belgilab qo'yiladi. Shu tufayli oy almashganda
config'ni qo'lda yangilash kerak emas.

Har sheet uchun: data/snapshots/YYYY-MM-DD/<SHEET_ID>.json
Auth/quota xatosida sheet skip qilinadi (log bilan), qolganlari davom etadi.
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.yaml"
# DATA_DIR (Railway volume kabi) berilsa barcha state o'sha yerda yashaydi
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
SNAPSHOTS = DATA / "snapshots"


def _creds_path():
    p = os.environ.get("GOOGLE_SA_PATH", "").strip()
    if p:
        return Path(p)
    if os.environ.get("DATA_DIR"):
        return DATA / "credentials" / "service-account.json"
    return BASE / "credentials" / "service-account.json"


CREDS = _creds_path()

RETRY_CODES = {429, 500, 502, 503}
TAB_RANGE = "A1:BZ1000"  # har tab uchun o'qiladigan maksimal maydon

# O'zbek oy nomlari (tab nomlarida ishlatiladi) + keng tarqalgan imlo variantlari
MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
]
MONTH_ALIASES = {
    "sentabr": "sentyabr", "oktabr": "oktyabr",
    "yanvar": "yanvar", "fevral": "fevral", "mart": "mart", "aprel": "aprel",
    "may": "may", "iyun": "iyun", "iyul": "iyul", "avgust": "avgust",
    "sentyabr": "sentyabr", "oktyabr": "oktyabr", "noyabr": "noyabr", "dekabr": "dekabr",
}


def log(msg):
    print(f"[fetch] {msg}", flush=True)


def norm(s):
    """Taqqoslash uchun: unicode-normalize, lower, ortiqcha bo'shliqlarsiz."""
    s = unicodedata.normalize("NFKC", str(s))
    return " ".join(s.strip().lower().split())


def quote_tab(title):
    return "'" + title.replace("'", "''") + "'"


def tab_range(title):
    return f"{quote_tab(title)}!{TAB_RANGE}"


def tab_of_range(rng):
    """"'Iyul '!A1:BZ1000" → "Iyul " (range kalitidan tab nomini ajratadi)."""
    if rng.startswith("'"):
        end = rng.rfind("'!")
        if end > 0:
            return rng[1:end].replace("''", "'")
    return rng.split("!")[0]


def current_month_name(today=None):
    m = (today or date.today()).month
    return MONTHS[m - 1]


def expand_month(s, today=None):
    """Config'dagi "<oy>" placeholder'ini joriy oy nomiga yoyadi
    (masalan "Undiruv <oy>" → "Undiruv iyul"). Oy almashganda avtomatik."""
    return str(s).replace("<oy>", current_month_name(today))


_YEAR_RE = re.compile(r"20\d{2}")

# Suffikssiz «Undiruv <oy>» tablari — 2025-08…2026-07 ARXIVI. Shu oydan boshlab Undiruv oy
# tabi (JORIY oy ham) faqat yil suffiksi bilan olinadi. YAGONA MANBA: undiruv.py (💰 blok),
# kunlik diff watch'i, key_column va Q&A loyiha qidiruvi shu qiymatga qaraydi — aks holda
# bir yo'l «(2026)» tabini, boshqasi 2025 arxivini o'qiydi (AUDIT.md P0-1: 08-01..08-06 va
# 09-01 hisobotlarida pul bloki va diff yilsiz arxiv tabdan chiqqan).
QATIY_DAN = date(2026, 8, 1)


def qatiy_oy(oy_1):
    """Oy (1-kuni) uchun Undiruv tabi faqat yil suffiksi bilan qidirilsinmi."""
    return oy_1 >= QATIY_DAN


def _qatiy_tpl(tpl, today=None):
    """Shablon qat'iy rejimdami: faqat «Undiruv …» shabloni va QATIY_DAN dan keyingi oy.
    Boshqa oy-shablonlar (masalan «Hoji mini kpi <oy>») yil suffiksisiz nomlanadi —
    ularga bu qoida qo'llanmaydi."""
    today = today or date.today()
    return norm(tpl).startswith("undiruv") and qatiy_oy(date(today.year, today.month, 1))


def sheet_month_spelling(month):
    """Sheet'dagi oy imlosi: "sentyabr" → "sentabr", "oktyabr" → "oktabr", qolgani o'zi."""
    m = norm(month)
    for k, v in MONTH_ALIASES.items():
        if norm(v) == m and norm(k) != m:
            return norm(k)
    return m


def expected_month_tab(tpl, today=None):
    """"<oy>" shablonining kutilgan REAL nomi (ogohlantirish matni uchun):
    "Undiruv <oy>" 01.11.2026 da → "Undiruv noyabr(2026)"."""
    today = today or date.today()
    name = str(tpl).replace("<oy>", sheet_month_spelling(current_month_name(today)))
    return f"{name}({today.year})" if _qatiy_tpl(tpl, today) else name


def month_spellings(month):
    """Oy nomining barcha imlo variantlari (sentyabr↔sentabr, oktyabr↔oktabr)."""
    m = norm(month)
    sp = {m}
    for k, v in MONTH_ALIASES.items():
        nk, nv = norm(k), norm(v)
        if m in (nk, nv):
            sp.update({nk, nv})
    return sp


def resolve_month_template(tpl, tab_titles, today=None):
    """Config'dagi tab shabloni ("Undiruv <oy>") → REAL tab nomlari, eng mos
    birinchi. "<oy>" bo'lmasa — aniq tenglik (eski xatti-harakat).

    "<oy>" bo'lsa undiruv.rank_month_tabs bilan BIR XIL qoida:
      • imlo aliasi: "sentyabr" shabloni "Undiruv sentabr(2026)" ni ham topadi,
      • chegara: aynan teng / keyin " " / keyin "(" (startswith emas),
      • YIL QOIDASI: joriy yil suffiksi ustun; boshqa yil arxivi (2025/2024)
        hech qachon tanlanmaydi,
      • QAT'IY QOIDA (QATIY_DAN, faqat «Undiruv» shabloni): yilsiz tab — arxiv,
        hech qachon tanlanmaydi. Joriy yil tabi hali ochilmagan bo'lsa natija BO'SH
        va fetch_sheet uni meta["watch_missing"] ga yozadi (hisobotda ⚠️ qatori).

    Sabab (01.09.2026): current_month_name → "sentyabr", real tab esa
    "Undiruv sentabr(2026)" — aniq tenglik hech nimaga mos kelmagan va kunlik
    diff Undiruv tabini BUTUNLAY yo'qotgan. Avgustda esa aynan tenglik 2025
    arxivi "Undiruv avgust" ga tushib qolgan (jim xato)."""
    tpl = str(tpl)
    if "<oy>" not in tpl:
        n = norm(tpl)
        return [t for t in tab_titles if norm(t) == n]
    yr = str((today or date.today()).year)
    qatiy = _qatiy_tpl(tpl, today)
    cands = [norm(tpl.replace("<oy>", sp)) for sp in month_spellings(current_month_name(today))]
    scored = []
    for t in tab_titles:
        nt = norm(t)
        if not any(nt == c or nt.startswith(c + " ") or nt.startswith(c + "(") for c in cands):
            continue
        years = _YEAR_RE.findall(nt)
        if years and yr not in years:
            continue                       # boshqa yil arxivi — hech qachon
        if not years and qatiy:
            continue                       # yilsiz arxiv (2025-08…2026-07) — QATIY_DAN dan keyin hech qachon
        # Bir xil ustunlikda KANONIK nom birinchi («Undiruv oktabr(2026)», bo'shliqqa chidamli):
        # «… (2026) shablon» kabi nusxa tanlanmasin — undiruv.rank_month_tabs bilan aynan bir tartib
        ixcham = re.sub(r"\s+", "", nt)
        kanonik = any(ixcham in (re.sub(r"\s+", "", c) + f"({yr})", re.sub(r"\s+", "", c)) for c in cands)
        scored.append((0 if yr in years else 1, not kanonik, len(nt), nt, t))
    scored.sort(key=lambda x: x[:4])
    return [x[4] for x in scored]


# PM KPI oy tabi (AUDIT.md P0-4): 2026-09 dan PM'lar «<Oy> (<yil>)» tabini to'ldiradi
# («Oktyabr (2026) », «Sentyabr(2026)»), yilsiz «Oktyabr» esa 01.10 dan beri o'zgarmagan —
# diff 40 kun «o'zgarish yo'q» degan. Ega qarori (2026-10-12): rasmiy tab «<Oy> (<yil>)».
# Shu oydan boshlab yilsiz oy tabi PM KPI uchun kuzatilmaydi; undan oldingi oylar — eski qoida.
PM_QATIY_DAN = date(2026, 9, 1)
_PM_YILLIK_RE = re.compile(r"^(\w+)\s*\(\s*(20\d{2})\s*\)$")


def pm_qatiy(today=None):
    today = today or date.today()
    return date(today.year, today.month, 1) >= PM_QATIY_DAN


def pm_yillik_tablar(tab_titles, month, year=None):
    """«<oy> (<yil>)» shaklidagi tablar (imlo varianti va bo'shliq farqi qabul), yil
    o'sish tartibida. «Managerlar oktyabr kpi (2026)», «Oktyabr (2026) nusxa» kirmaydi."""
    spell = month_spellings(month)
    out = []
    for t in tab_titles:
        m = _PM_YILLIK_RE.match(norm(t))
        if m and m.group(1) in spell and (year is None or m.group(2) == str(year)):
            out.append((m.group(2), t))
    return [t for _y, t in sorted(out, key=lambda x: x[0])]


def pm_month_tab(tab_titles, today=None):
    """PM KPI joriy oy tabi yoki None. PM_QATIY_DAN dan: faqat «<Oy> (<joriy yil>)»;
    undan oldin — aynan oy nomi. Bir nechta mos bo'lsa tartibda OXIRGISI."""
    today = today or date.today()
    month = current_month_name(today)
    if pm_qatiy(today):
        c = pm_yillik_tablar(tab_titles, month, today.year)
    else:
        c = [t for t in tab_titles if norm(t) == month]
    return c[-1] if c else None


def expected_pm_month_tab(today=None):
    """Ogohlantirish matni uchun: 01.11.2026 → «Noyabr (2026)»."""
    today = today or date.today()
    month = current_month_name(today).capitalize()
    return f"{month} ({today.year})" if pm_qatiy(today) else month


def is_month_watch_tab(title):
    """Sanasiz: kuzatuvdagi tab PM KPI oy tabimi — yilsiz «Oktyabr» (2026-09 gacha) yoki
    «Oktyabr (2026)». Statistika (PDF kartalari, dashboard, Q&A agregati) eski va yangi
    snapshot'larda bir xil ishlashi uchun."""
    n = norm(title)
    if n in MONTH_ALIASES:
        return True
    m = _PM_YILLIK_RE.match(n)
    return bool(m and m.group(1) in MONTH_ALIASES)


def is_pm_month_tab(title, today=None):
    """Tab joriy oyning PM KPI tabimi (diff jimlik nazorati uchun): aynan oy nomi
    yoki «<oy> (<joriy yil>)» — kuzatuvdagi qaysi biri bo'lsa ham tanilsin."""
    today = today or date.today()
    month = current_month_name(today)
    return norm(title) in month_spellings(month) or bool(pm_yillik_tablar([title], month, today.year))


def month_tab_dup_note(tab_titles, today=None):
    """Joriy oyga bittadan ko'p PM KPI tabi (pm_month_tab qoidasi bo'yicha) bo'lsa egaga
    izoh, aks holda "". Ilgari jim tartibda oxirgisi olinardi (P2). 2026-09 dan faqat
    «<Oy> (<yil>)» tablari sanaladi — yilsiz eski «Oktyabr» yonida turishi normal."""
    today = today or date.today()
    month = current_month_name(today)
    c = (pm_yillik_tablar(tab_titles, month, today.year) if pm_qatiy(today)
         else [t for t in tab_titles if norm(t) == month])
    if len(c) < 2:
        return ""
    return (f"joriy oyga {len(c)} tab bor — «{c[-1]}» o'qildi; boshqalari e'tiborsiz: "
            + ", ".join(f"«{t}»" for t in c[:-1]) + " (nusxa bo'lsa o'chiring/nomini o'zgartiring)")


def detect_watch_tabs(tab_titles, today=None):
    """Main + joriy oy tabini (pm_month_tab) topadi.
    Main yo'q bo'lsa — vaqtinchalik manba sifatida "...ishlash muddati" tabi
    olinadi (deadline/muddat ma'lumotlari uchun); Main qaytsa avtomatik tiklanadi."""
    watch = []
    main = next((t for t in tab_titles if norm(t) == "main"), None)
    if main:
        watch.append(main)
    else:
        fb = next((t for t in tab_titles if "ishlash muddati" in norm(t)), None)
        if fb:
            watch.append(fb)
    month_tab = pm_month_tab(tab_titles, today)
    if month_tab:
        watch.append(month_tab)
    return watch


def resolve_watch_tabs(watch_cfg, tab_titles, today=None):
    """Config watch_tabs → (real tab nomlari, topilmagan oy tablari ro'yxati).

    YAGONA yechuvchi: kunlik fetch_sheet, /hisobot (jonli oraliq diff) va Q&A jonli
    fallback'i shu funksiyadan foydalanadi — aks holda bir yo'l «(2026)» tabini, boshqasi
    yilsiz arxivni kuzatadi (AUDIT.md P0-1). "auto" → detect_watch_tabs. "<oy>" shabloni
    faqat ENG MOS bitta tabga bog'lanadi; topilmasa kutilgan nomi (expected_month_tab)
    ikkinchi ro'yxatga tushadi — hisobotda ⚠️ qatori shundan chiqadi."""
    if watch_cfg in (None, "auto"):
        # PM KPI oy tabi yo'q bo'lsa yilsiz tabga qaytilmaydi — ⚠️ qatori chiqadi
        missing = ([expected_pm_month_tab(today)]
                   if pm_qatiy(today) and not pm_month_tab(tab_titles, today) else [])
        return detect_watch_tabs(tab_titles, today), missing
    resolved, missing = [], []
    for w in watch_cfg:
        hits = resolve_month_template(w, tab_titles, today)
        if "<oy>" in str(w):
            hits = hits[:1]                # oy shabloni — faqat ENG MOS tab
            if not hits:
                missing.append(expected_month_tab(w, today))
        for t in hits:
            if t not in resolved:
                resolved.append(t)
    return resolved, missing


def resolve_key_columns(tab_titles, key_cfg, today=None):
    """Config'dagi semantik key_column ({main: X, month: Y, "<tab>": Z} yoki
    skalyar) ni real range kalitlariga yoyadi: {range_key: kalit}."""
    if not isinstance(key_cfg, dict):
        return key_cfg or 1
    cur_month_tab = pm_month_tab(tab_titles, today)
    main_exists = any(norm(t) == "main" for t in tab_titles)
    fallback_tab = (
        None if main_exists
        else next((t for t in tab_titles if "ishlash muddati" in norm(t)), None)
    )
    # "<oy>" kalitlari faqat pastdagi resolve_month_template orqali bog'lanadi: aynan
    # expand_month ("Undiruv noyabr") yilsiz ARXIV tabiga kalit berib qo'ymasin.
    by_name = {norm(expand_month(k, today)): v for k, v in key_cfg.items() if "<oy>" not in str(k)}
    # "<oy>" shabloni imlo/yil qoidasi bilan REAL tab nomiga bog'lanadi
    # (aks holda "Undiruv sentyabr" kaliti "Undiruv sentabr(2026)" ga tushmaydi
    #  va key_column 1-ustunga qaytib, diff soxta "yangi qator" beradi).
    for k, v in key_cfg.items():
        if "<oy>" in str(k):
            for t in resolve_month_template(k, tab_titles, today)[:1]:
                by_name[norm(t)] = v
    out = {}
    for t in tab_titles:
        n = norm(t)
        val = None
        if n in by_name:
            val = by_name[n]
        elif n == "main" and "main" in by_name:
            val = by_name["main"]
        elif t == fallback_tab and "main" in by_name:
            val = by_name["main"]  # muddatlar tabida ham kalit "Loyihalar"
        elif t == cur_month_tab and "month" in by_name:
            val = by_name["month"]
        if val is not None:
            out[tab_range(t)] = val
    return out


def load_config(include_qa_only=False):
    """Sheets ro'yxati. qa_only sheet'lar faqat include_qa_only=True bo'lganda
    qaytadi (Q&A bot) — kunlik pipeline/diff/audit ularni ko'rmaydi."""
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    valid = []
    for s in cfg.get("sheets") or []:
        sheet_id = str(s.get("id") or "")
        if not sheet_id or "SHU_YERGA" in sheet_id or "SHEET_ID" in sheet_id:
            log(f"skip: '{s.get('name', '?')}' — id hali to'ldirilmagan")
            continue
        if s.get("qa_only") and not include_qa_only:
            continue
        valid.append(s)
    return valid


def load_full_config():
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def status_of(exc):
    resp = getattr(exc, "response", None)
    if resp is not None and hasattr(resp, "status_code"):
        return resp.status_code
    return getattr(exc, "code", 0) or 0


def _with_retry(fn, label):
    import gspread

    for attempt in (1, 2):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            code = status_of(e)
            if attempt == 1 and code in RETRY_CODES:
                log(f"{label}: HTTP {code} — 20s kutib qayta urinaman")
                time.sleep(20)
                continue
            raise


def list_tabs(gc, sheet_id):
    """Tab nomlari (sheet'dagi tartibda). 1 ta metadata so'rov."""
    sh = _with_retry(lambda: gc.open_by_key(sheet_id), sheet_id)
    return sh, [w.title for w in _with_retry(sh.worksheets, sheet_id)]


def fetch_ranges(sh, ranges, label):
    """Berilgan range'larni bitta batchGet bilan o'qiydi."""
    resp = _with_retry(lambda: sh.values_batch_get(ranges), label)
    out = {}
    for req, vr in zip(ranges, resp.get("valueRanges", [])):
        out[req] = {
            "actual_range": vr.get("range", req),
            "values": vr.get("values", []),
        }
    return out


def fetch_sheet(gc, s, today=None):
    """Bitta sheet: barcha tab'lar (mode: all_tabs) yoki legacy ranges ro'yxati.
    Qaytaradi: (ranges_dict, meta) — meta: tabs, watch_ranges, key_column."""
    name = s.get("name", s["id"])
    if s.get("mode", "all_tabs") == "all_tabs" and not s.get("ranges"):
        sh, tabs = list_tabs(gc, s["id"])
        # exclude_tabs: bu tab'lar API'dan O'QILMAYDI ham — snapshot/diff/git
        # arxiviga tushmaydi (maxfiy ma'lumot, masalan parollar). Nomi esa
        # meta.tabs ro'yxatida qoladi — Q&A bot mavjudligini bilib, kerak
        # bo'lsa jonli o'qiy oladi.
        excluded_norm = {norm(x) for x in (s.get("exclude_tabs") or [])}
        excluded = [t for t in tabs if norm(t) in excluded_norm]
        fetch_tabs = [t for t in tabs if norm(t) not in excluded_norm]
        ranges = [tab_range(t) for t in fetch_tabs]
        data = fetch_ranges(sh, ranges, name)
        watch_titles, missing = resolve_watch_tabs(s.get("watch_tabs", "auto"), fetch_tabs, today)
        meta = {
            "tabs": tabs,
            "excluded_tabs": excluded,
            "watch_ranges": [tab_range(t) for t in watch_titles],
            "key_column": resolve_key_columns(fetch_tabs, s.get("key_column", 1), today),
            "watch_missing": missing,
        }
        if s.get("watch_tabs", "auto") in (None, "auto") and s.get("pm_kpi", True):
            dup = month_tab_dup_note(fetch_tabs, today)
            if dup:
                meta["watch_notes"] = [dup]
                log(f"'{name}': DIQQAT — {dup}")
        for m in missing:
            log(f"'{name}': DIQQAT — «{m}» tabi topilmadi, bugun u kuzatilmaydi "
                "(yilsiz eski tab arxiv sifatida ataylab o'qilmaydi)")
        if not watch_titles:
            log(f"'{name}': DIQQAT — watch tab topilmadi (Main/joriy oy yo'q)")
        return data, meta
    # legacy: qo'lda berilgan ranges
    sh = _with_retry(lambda: gc.open_by_key(s["id"]), name)
    ranges = s.get("ranges") or ["A1:Z1000"]
    data = fetch_ranges(sh, ranges, name)
    meta = {"tabs": [], "excluded_tabs": [], "watch_ranges": list(ranges),
            "key_column": s.get("key_column", 1)}
    return data, meta


# (connect, read) — Sheets chaqiruvi CHEKSIZ kutmasin. Busiz osilgan so'rov
# bot'ning polling loop'ini butunlay to'xtatib qo'yishi mumkin (2026-09-09:
# 08:59 → 19:00, ~10 soat jimlik). SHEETS_TIMEOUT env bilan o'zgartiriladi.
SHEETS_TIMEOUT = (10, 60)


def _sheets_timeout():
    raw = os.environ.get("SHEETS_TIMEOUT", "").strip()
    if not raw:
        return SHEETS_TIMEOUT
    try:
        parts = [float(x) for x in raw.split(",")]
        return (parts[0], parts[1]) if len(parts) == 2 else float(parts[0])
    except (ValueError, IndexError):
        log(f"SHEETS_TIMEOUT noto'g'ri ({raw!r}) — default {SHEETS_TIMEOUT}")
        return SHEETS_TIMEOUT


def gclient():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        str(CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    gc.set_timeout(_sheets_timeout())
    return gc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: bugun)")
    args = ap.parse_args()
    run_day = date.fromisoformat(args.date)

    sheets = load_config()
    if not sheets:
        log("XATO: config.yaml da birorta ham to'ldirilgan sheet yo'q")
        return 1
    if not CREDS.exists():
        log(f"XATO: {CREDS} topilmadi — README'dagi Google Cloud qadamiga qarang")
        return 1

    gc = gclient()
    day_dir = SNAPSHOTS / args.date
    day_dir.mkdir(parents=True, exist_ok=True)

    ok, errors = 0, {}
    for s in sheets:
        name = s.get("name", s["id"])
        try:
            ranges, meta = fetch_sheet(gc, s, run_day)
            snap = {
                "id": s["id"],
                "name": name,
                "watch": s.get("watch", ""),
                # pm_kpi=False — PM KPI formatida emas (audit/dashboard-PM
                # statistikasi bu sheet'ni chetlab o'tadi)
                "pm_kpi": s.get("pm_kpi", True),
                "track_other_tabs": bool(s.get("track_other_tabs")),
                "key_column": meta["key_column"],
                "tabs": meta["tabs"],
                "excluded_tabs": meta.get("excluded_tabs", []),
                "watch_ranges": meta["watch_ranges"],
                "watch_missing": meta.get("watch_missing", []),
                "watch_notes": meta.get("watch_notes", []),
                "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ranges": ranges,
            }
            (day_dir / f"{s['id']}.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            rows = sum(len(r["values"]) for r in ranges.values())
            wt = ", ".join(tab_of_range(r) for r in meta["watch_ranges"]) or "—"
            log(f"OK: '{name}' — {len(ranges)} tab, {rows} qator (watch: {wt})")
            ok += 1
        except Exception as e:
            log(f"XATO: '{name}' o'qilmadi — {type(e).__name__}: {str(e)[:300]}")
            errors[s["id"]] = {"name": name, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    meta = {"date": args.date, "ok": ok, "errors": errors}
    (day_dir / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    if ok == 0:
        log("XATO: birorta ham sheet o'qilmadi")
        return 1
    log(f"tayyor: {ok}/{len(sheets)} sheet saqlandi → {day_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
