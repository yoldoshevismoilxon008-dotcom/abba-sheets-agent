#!/usr/bin/env python3
"""Telegram Q&A listener — sheet'lar bo'yicha aqlli savol-javob.

Imkoniyatlar:
  - FAQAT .env dagi TELEGRAM_CHAT_ID ga javob (boshqalar — log + jim ignore)
  - Suhbat xotirasi: oxirgi 10 savol-javob promptda ("o'shani", "davom et",
    "bunga javob bermading" ishlaydi); /yangi — kontekstni tozalash
  - Ikki rejim: oddiy savol — tez; murakkab (nega/solishtir/trend/ko'p oy) —
    chuqur tafakkur (effort=max) + tarixiy snapshotlar kontekstda
  - Savolga qarab kerakli sheet/tab'largina jonli o'qiladi (snapshot yozilmaydi)
  - KPI qoidalari va oxirgi audit natijasi doim kontekstda
  - Javob yuborish retry bilan (Mac uyqudan uyg'onganda tarmoq kech tiklanadi)

Buyruqlar: /hisobot, /audit, /yangi, /help; qolgan matn — savol.
Log: data/logs/bot-YYYY-MM-DD.log · launchd: com.abba.sheets-bot (KeepAlive)
"""
import json
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import requests

import analyze
import audit as auditmod
import design
import diff as diffmod
import fetch as fetchmod
import send as sendmod

DATA = BASE / "data"
LOGS = DATA / "logs"
STATE_FILE = DATA / "bot-state.json"
MEM_DIR = DATA / "bot-memory"
HIST_FILE = MEM_DIR / "history.jsonl"
OUTBOX = DATA / "bot-outbox.md"
LAST_AUDIT = DATA / "last-audit.md"
QA_PDF_DIR = DATA / "qa-pdf"
QA_PROMPT = BASE / "prompts" / "qa.md"
DAILY_PROMPT = BASE / "prompts" / "daily-report.md"

POLL_TIMEOUT = 50
MAX_CELL = 80
MAX_ROW = 400
MAX_TABS_PER_SHEET = 14
MAX_DATA_CHARS = 180_000
TABS_CACHE_TTL = 600
HISTORY_PAIRS = 10
SNAP_FRESH_HOURS = 6
EFFORT_BY_MODE = {"deep": "high", "max": "max"}  # fast — default effort

TOKEN = ""
CHAT_ID = ""

# Murakkab savol belgilari — chuqur rejim (ko'proq kontekst + max effort)
DEEP_WORDS = (
    "nega", "nimaga", "sabab", "solishtir", "taqqosla", "trend", "dinamika",
    "o'zgar", "nisbatan", "o'tgan", "avvalgi", "tahlil", "analiz", "batafsil",
    "prognoz", "xulosa", "umumiy", "natija", "yaxshilan", "yomonlash", "kecha",
)
# Avvalgi suhbatga murojaat belgilari — oldingi tanlovni qayta ishlatamiz
REF_WORDS = (
    "o'sha", "davom", "bunga javob", "avvalgi", "yana", "batafsil",
    "to'liqroq", "aniqrog", "javob bermading", "tushunmadim",
)
# Tarixiy snapshotlarga murojaat belgilari
HISTQ_WORDS = ("kecha", "o'tgan", "avval", "trend", "dinamika", "nisbatan", "tarix")
# Jonli o'qish talab qiluvchi so'zlar (aks holda yangi snapshot'dan o'qiladi)
LIVE_WORDS = ("hozir", "jonli", "shu payt", "ayni", "real vaqt", "o'zgardimi", "yangilandimi")
# Maksimal effort faqat eksplitsit so'ralganda
MAX_WORDS = ("chuqur tahlil", "to'liq tahlil", "to'liq audit", "maksimal tahlil", "chuqur o'rgan")
# Infografik PDF kutiladigan so'rov belgilari — kamida deep rejim (PDF-nomzod)
PDF_WORDS = ("taqdim", "ko'rsat", "hisobot", "reyting", "ro'yxat", "jadval", "pdf", "grafik")

# Javob format ko'rsatmalari (prompts/qa.md dagi {{FORMAT}} o'rniga qo'yiladi).
# fast: doim matn (tezlik muhim); deep/max: Claude data turiga qarab o'zi tanlaydi.
TEXT_FORMAT = (
    "Telegram formati: oddiy matn, **qalin**, • ro'yxat; jadval/kod blok/# ishlatma."
)
PDF_FORMAT = """AQLLI TANLOV — javob turiga qarab ikki formatdan birini tanla:

1) Javob RAQAMLI-JADVALLI bo'lsa — solishtirish, trend/dinamika, oylik natijalar,
   reyting yoki 3+ qatorli raqamli ro'yxat, KPI holat taqdimoti — javobni FAQAT
   bitta ```json ... ``` blok qilib qaytar (quyidagi tuzilma). U brendli
   infografik PDF'ga aylantirilib yuboriladi.
2) Aks holda — bitta faktli qisqa javob ("ha/yo'q", bitta raqam), aniqlashtirish
   savoli, sof matnli tushuntirish — ODDIY MATN qaytar: oddiy matn, **qalin**,
   • ro'yxat; jadval/kod blok/# ishlatma.

JSON tuzilmasi (title, summary, source majburiy; qolgan bloklardan faqat data
turiga mosini kirit — hammasini majburan to'ldirma):
{
 "title": "3-6 so'zli sarlavha (savol mohiyati)",
 "summary": "2-3 gapli asosiy xulosa — eng muhim natija, raqami bilan",
 "kpis": [{"label": "Iyul", "value": "41,2%", "sub": "12/29 ball", "color": "yellow"}],
 "table": {"title": "...", "columns": ["Oy", "Ideal", "Fakt", "%"], "rows": [["Yanvar", "30", "24", "80,0%"]]},
 "bars": {"title": "...", "unit": "%", "items": [{"label": "Zubair", "value": 41.2, "display": "41,2%", "note": "12/29", "color": "yellow"}]},
 "trend": {"title": "...", "labels": ["18.07", "19.07"], "series": [{"name": "Zubair", "points": [45.1, 47.2]}]},
 "warnings": ["anomaliya/ogohlantirish qatorlari (faqat haqiqatan bor bo'lsa)"],
 "insights": ["1-3 muhim kuzatuv"],
 "note": "chegara izohi (masalan: ro'yxat qisqartirilgani)",
 "source": "qaysi sheet/tab'lar, manba (snapshot SANA VAQT yoki jonli holat)"
}
Qoidalar:
- color ∈ green|yellow|orange|red|accent|muted. KPI foizga status rang (≥90 green,
  80-90 yellow, 70-80 orange, <70 red); oddiy solishtirishda color yozma (o'zi tanlanadi).
- "value" va "points" — float (nuqta bilan: 41.2); ko'rsatiladigan matnlar
  ("display", jadval hujayralari, kpis.value) — sheet ko'rinishida ("41,2%").
- Limitlar: kpis ≤4 · table ≤20 qator (ko'p bo'lsa eng muhimlarini kirit, note'da ayt)
  · bars ≤10 · trend faqat vaqt-dinamika so'ralganda, series ≤4.
- trend.points'da ma'lumot yo'q kunga null yoz. summary'da to'qima raqam bo'lmasin —
  hammasi DATA'dan."""

HELP = (
    "🤖 **Abba Sheets Q&A**\n"
    "Oddiy tilda savol yozing — PM KPI sheet'larining joriy holati asosida "
    "javob beraman. Suhbatni eslab qolaman: \"nega?\", \"o'shani batafsilroq\" "
    "kabi davom savollari ishlaydi. Raqamli-jadvalli javoblar (solishtirish, "
    "trend, oylik natijalar) infografik PDF bo'lib keladi.\n\n"
    "Misollar:\n"
    "• Zubairda Livardi loyihasi bormi?\n"
    "• Islomning oktabrdan iyungacha natijalari qanday?\n"
    "• Kechaga nisbatan nima o'zgardi?\n"
    "• Nega Bekzodning bali tushdi?\n\n"
    "Buyruqlar:\n"
    "/hisobot — kunlik hisobotni hozir yaratish\n"
    "/audit — data sifat auditi\n"
    "/dashboard — dashboard linki + oxirgi yangilanish\n"
    "/ack — tan olingan audit muammolari (/ack <kalit> [izoh] — qo'shish)\n"
    "/dizayn — PDF dizayni: presetlar, matnli o'zgartirish; rasm yuborsangiz — "
    "referens tahlili (caption'da \"logo\" bo'lsa — logo)\n"
    "/yangi — suhbat kontekstini tozalash (yangi mavzu)\n"
    "/help — shu yordam"
)


def log(msg):
    line = f"[{datetime.now().strftime('%F %T')}] {msg}"
    print(line, flush=True)
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / f"bot-{date.today().isoformat()}.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def init_env():
    global TOKEN, CHAT_ID
    analyze.load_env()
    import os

    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not TOKEN or not CHAT_ID:
        log("XATO: .env da TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID yo'q")
        sys.exit(1)


def api(method, payload=None, timeout=30):
    return requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}", json=payload or {}, timeout=timeout
    )


def send_long(md_text):
    html = sendmod.md_to_html(md_text)
    chunks = sendmod.split_chunks(html)
    for i, c in enumerate(chunks, 1):
        sendmod.tg_send(TOKEN, CHAT_ID, c)
        if i < len(chunks):
            time.sleep(0.4)


def send_retry(md_text, attempts=4):
    """Javobni retry bilan yuboradi (uyqudan keyin tarmoq kech tiklanadi).
    Umuman yuborilmasa — outbox'ga saqlaydi. True = yetkazildi."""
    for i in range(attempts):
        try:
            send_long(md_text)
            return True
        except Exception as e:
            log(f"yuborish xatosi ({i + 1}/{attempts}): {type(e).__name__}: {str(e)[:120]}")
            if i < attempts - 1:
                time.sleep(20 * (i + 1))
    try:
        OUTBOX.write_text(md_text + "\n", encoding="utf-8")
        log(f"XATO: javob yuborilmadi — {OUTBOX} ga saqlandi")
    except OSError:
        pass
    return False


def typing():
    try:
        api("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
    except requests.RequestException:
        pass


def send_status(text):
    """Progress xabari — keyin edit qilinadi. message_id qaytaradi (yoki None)."""
    try:
        r = api("sendMessage", {"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return r.json().get("result", {}).get("message_id")
    except requests.RequestException:
        pass
    return None


def edit_status(mid, text, html=False):
    if not mid:
        return False
    payload = {
        "chat_id": CHAT_ID, "message_id": mid, "text": text,
        "disable_web_page_preview": True,
    }
    if html:
        payload["parse_mode"] = "HTML"
    try:
        return api("editMessageText", payload).status_code == 200
    except requests.RequestException:
        return False


def delete_status(mid):
    """Progress xabarini o'chiradi (PDF yuborilgach ortda qolmasin)."""
    if not mid:
        return
    try:
        api("deleteMessage", {"chat_id": CHAT_ID, "message_id": mid})
    except requests.RequestException:
        pass


# ---------- getUpdates offset ----------

def load_last():
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8"))["last_update_id"])
    except Exception:
        return None


def save_last(uid):
    DATA.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_update_id": uid}), encoding="utf-8")


INFLIGHT = DATA / "bot-inflight.json"


def _write_inflight(upd, attempts=1):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        INFLIGHT.write_text(
            json.dumps({"update": upd, "attempts": attempts}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _clear_inflight():
    try:
        INFLIGHT.unlink()
    except OSError:
        pass


def recover_inflight():
    """Restart/crash paytida uzilgan xabarni tiklaydi (bir marta).
    Ikki urinishda ham uzilsa — tashlab, foydalanuvchiga xabar beradi."""
    if not INFLIGHT.exists():
        return
    try:
        st = json.loads(INFLIGHT.read_text(encoding="utf-8"))
    except Exception:
        _clear_inflight()
        return
    _clear_inflight()
    upd, att = st.get("update"), int(st.get("attempts", 1))
    if not upd:
        return
    preview = ((upd.get("message") or {}).get("text") or "")[:80]
    if att >= 2:
        log(f"inflight tashlab yuborildi (2 marta uzilgan): {preview!r}")
        send_retry(
            f"⚠️ «{preview}» so'rovingiz qayta ishlashda ikki marta uzildi — "
            f"iltimos qaytadan yozing.", attempts=2,
        )
        return
    log(f"restart paytida uzilgan so'rov tiklanmoqda (urinish {att + 1}): {preview!r}")
    _write_inflight(upd, attempts=att + 1)
    try:
        handle_update(upd)
    except Exception as e:
        log(f"XATO recover_inflight: {e}")
    finally:
        _clear_inflight()


def drop_backlog():
    try:
        r = api("getUpdates", {"offset": -1, "timeout": 0}).json()
        res = r.get("result", [])
        last = res[-1]["update_id"] if res else 0
    except Exception as e:
        log(f"backlog tekshirishda xato ({e}) — 0 dan boshlayman")
        last = 0
    save_last(last)
    log(f"birinchi ishga tushish: backlog o'tkazib yuborildi (last_update_id={last})")
    return last


# ---------- suhbat xotirasi ----------

def load_history(n=HISTORY_PAIRS):
    if not HIST_FILE.exists():
        return []
    recs = []
    for line in HIST_FILE.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(line))
        except ValueError:
            pass
    for i in range(len(recs) - 1, -1, -1):
        if recs[i].get("reset"):
            recs = recs[i + 1:]
            break
    return [r for r in recs if r.get("q")][-n:]


def remember(q, a, sel=None):
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().strftime("%F %T"), "q": str(q)[:400], "a": str(a)[:1200]}
        if sel:
            rec["sel"] = sel
        with open(HIST_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"xotira yozilmadi: {e}")


def reset_history():
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    with open(HIST_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"reset": True, "ts": datetime.now().strftime("%F %T")}) + "\n")


def history_block():
    h = load_history()
    if not h:
        return "(bo'sh — bu suhbatning birinchi savoli)"
    parts = []
    for r in h:
        parts.append(f"[{r['ts']}] SAVOL: {r['q']}\nJAVOB: {r['a']}")
    return "\n---\n".join(parts)


def prev_selection():
    for r in reversed(load_history()):
        if r.get("sel"):
            return r["sel"]
    return None


# ---------- Google Sheets ----------

_gc = None
_tabs_cache = {}


def gclient():
    global _gc
    if _gc is None:
        _gc = fetchmod.gclient()
    return _gc


_tls = threading.local()


def tgc():
    """Har thread uchun alohida gspread client (parallel fetch xavfsizligi)."""
    if getattr(_tls, "gc", None) is None:
        _tls.gc = fetchmod.gclient()
    return _tls.gc


def sheet_tabs(s):
    ent = _tabs_cache.get(s["id"])
    if ent and ent[0] > time.time():
        return ent[1], ent[2]
    sh, tabs = fetchmod.list_tabs(gclient(), s["id"])
    _tabs_cache[s["id"]] = (time.time() + TABS_CACHE_TTL, sh, tabs)
    return sh, tabs


def snapshot_days():
    if not diffmod.SNAPSHOTS.is_dir():
        return []
    return sorted(
        x.name
        for x in diffmod.SNAPSHOTS.iterdir()
        if x.is_dir()
        and len(x.name) == 10
        and any(f.name not in diffmod.SERVICE_FILES for f in x.glob("*.json"))
    )


def latest_day():
    days = snapshot_days()
    return days[-1] if days else None


# ---------- savol tasnifi va tanlash ----------

def _q_norm(text):
    return fetchmod.norm(text).replace("’", "'").replace("ʻ", "'").replace("`", "'")


def classify(q, months):
    """(mode, ref): mode ∈ fast|deep|max, ref — avvalgi suhbatga murojaatmi."""
    qn = _q_norm(q)
    ref = any(w in qn for w in REF_WORDS)
    if any(w in qn for w in MAX_WORDS):
        return "max", ref
    if (
        ref or len(months) >= 2 or len(q) > 140
        or any(w in qn for w in DEEP_WORDS) or any(w in qn for w in PDF_WORDS)
    ):
        return "deep", ref
    return "fast", ref


def needs_live(q):
    qn = _q_norm(q)
    return any(w in qn for w in LIVE_WORDS)


def snapshot_fresh(day):
    """Bugungi snapshot va 6 soatdan yangi bo'lsa — jonli fetch shart emas."""
    if day != date.today().isoformat():
        return False
    try:
        age_h = (time.time() - (diffmod.SNAPSHOTS / day).stat().st_mtime) / 3600
    except OSError:
        return False
    return age_h <= SNAP_FRESH_HOURS


def sheets_for_question(cfg, q, extra_names=None):
    qn = _q_norm(q).replace("'", "")
    sel = []
    for s in cfg:
        first = _q_norm(s.get("name", "")).split()[0].replace("'", "") if s.get("name") else ""
        if first and first in qn:
            sel.append(s)
    if extra_names:
        for s in cfg:
            if s.get("name") in extra_names and s not in sel:
                sel.append(s)
    return sel or list(cfg)


def months_in_question(q):
    qn = _q_norm(q)
    hits = []
    for word, canon in fetchmod.MONTH_ALIASES.items():
        pat = r"\bmay" if word == "may" else re.escape(word)
        m = re.search(pat, qn)
        if m and canon not in [c for _, c in hits]:
            hits.append((m.start(), canon))
    hits.sort()
    months = [c for _, c in hits]
    if len(months) == 2:
        a, b = fetchmod.MONTHS.index(months[0]), fetchmod.MONTHS.index(months[1])
        span, i = [], a
        while True:
            span.append(fetchmod.MONTHS[i])
            if i == b:
                break
            i = (i + 1) % 12
        months = span
    return months


def tabs_for_question(tabs, q, extra_tabs=None):
    chosen = list(fetchmod.detect_watch_tabs(tabs))
    for m in months_in_question(q):
        plain = [t for t in tabs if fetchmod.norm(t) == m]
        mgr = [t for t in tabs if m in fetchmod.norm(t) and "managerlar" in fetchmod.norm(t)]
        other = [t for t in tabs if m in fetchmod.norm(t) and t not in plain and t not in mgr]
        if plain:
            chosen.append(plain[-1])
        if mgr:
            chosen.append(mgr[-1])
        if other:
            chosen.append(other[-1])
    qn = _q_norm(q)
    for t in tabs:
        for word in fetchmod.norm(t).split():
            if len(word) >= 5 and word not in fetchmod.MONTHS and word in qn:
                chosen.append(t)
                break
    if extra_tabs:
        chosen += [t for t in extra_tabs if t in tabs]
    seen, out = set(), []
    for t in chosen:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:MAX_TABS_PER_SHEET]


def days_for_question(q):
    """Tarixiy solishtirish uchun mos snapshot kunlari (bugungidan oldingilar)."""
    qn = _q_norm(q)
    if not any(w in qn for w in HISTQ_WORDS):
        return []
    today = date.today().isoformat()
    past = [d for d in snapshot_days() if d < today]
    if not past:
        return []
    picks = []
    if "kecha" in qn:
        picks.append(past[-1])
    if "hafta" in qn or "o'tgan" in qn:
        target = date.today() - timedelta(days=7)
        picks.append(min(past, key=lambda d: abs((date.fromisoformat(d) - target).days)))
    if "trend" in qn or "dinamika" in qn:
        picks += past[-5:]
    if not picks:
        picks.append(past[-1])
    seen, out = set(), []
    for d in picks:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out[:5]


# ---------- data kontekst ----------

def fmt_row(row, header):
    parts = []
    for i, v in enumerate(row):
        v = str(v).strip()
        if not v:
            continue
        h = str(header[i]).strip() if i < len(header) else f"{i + 1}-ustun"
        parts.append(f"{h}={v[:MAX_CELL]}")
    return "; ".join(parts)[:MAX_ROW] or "(bo'sh)"


def format_tab(tab, d):
    vals = d.get("values", [])
    h = diffmod.detect_header(vals)
    header = [str(x) for x in (vals[h] if vals else [])]
    rows = [
        (n, row)
        for n, row in enumerate(vals[h + 1:], start=h + 2)
        if any(str(c).strip() for c in row)
    ]
    L = [f"[{tab}] {len(rows)} qator. Ustunlar: {', '.join(x for x in header if x.strip())}"]
    for n, row in rows:
        L.append(f"{n}. {fmt_row(row, header)}")
    return "\n".join(L)


def select_from_snapshot(snap, q, extra_tabs):
    all_ranges = snap.get("ranges", {})
    by_tab = {fetchmod.tab_of_range(r): r for r in all_ranges}
    tabs = snap.get("tabs") or list(by_tab.keys())
    sel_tabs = [t for t in tabs_for_question(tabs, q, extra_tabs) if t in by_tab]
    ranges = {by_tab[t]: all_ranges[by_tab[t]] for t in sel_tabs}
    return tabs, sel_tabs, ranges


_agg_cache = {}


def sheet_aggregates(day, snap, exclude):
    """KONTEKST DIETASI: tanlanmagan tab'lar uchun faqat agregat qatorlar
    (snapshot'dan, keshlanadi). Raw dump taqiqlanadi."""
    key = (day, snap.get("id"))
    lines = _agg_cache.get(key)
    if lines is None:
        lines = []
        for rng, data in snap.get("ranges", {}).items():
            tab = fetchmod.tab_of_range(rng)
            vals = data.get("values", [])
            header, rows = auditmod.data_rows(vals)
            ci = auditmod.find_col(header, "ideal")
            cf = auditmod.find_col(header, "proekt bali")
            ck = auditmod.find_col(header, "kechga qolgan", "kech")
            if ci is None and cf is None:
                lines.append((tab, f"{tab}: {len(rows)} qator"))
                continue
            si = sum(auditmod._numval(auditmod.cell(r, ci)) or 0 for _, r in rows)
            sf = sum(auditmod._numval(auditmod.cell(r, cf)) or 0 for _, r in rows)
            dl = (
                sum(auditmod._numval(auditmod.cell(r, ck)) or 0 for _, r in rows)
                if ck is not None else 0
            )
            pct = f"{sf / si * 100:.1f}%" if si else "—"
            lines.append(
                (tab, f"{tab}: {len(rows)} qator | Σideal {si:.1f} | Σfakt {sf:.1f} | {pct} | kechikish {dl:.0f}")
            )
        _agg_cache[key] = lines
    return [txt for tab, txt in lines if tab not in exclude]


def build_data(q, extra_sel=None, force_live=False):
    """Savolga mos sheet/tab'lar. SNAPSHOT-FIRST: bugungi snapshot yangi bo'lsa
    undan o'qiladi; jonli fetch faqat so'ralganda/eskirganda — PARALLEL.
    Qaytaradi: (matn, sel, manba)."""
    cfg = fetchmod.load_config()
    extra_names = (extra_sel or {}).get("sheets")
    sel_sheets = sheets_for_question(cfg, q, extra_names)
    latest = latest_day()
    snap_sheets = diffmod.load_day(latest)[0] if latest else {}
    use_snap = (not force_live) and bool(snap_sheets) and snapshot_fresh(latest)

    def fetch_live(s):
        name = s.get("name", s["id"])
        sh = tgc().open_by_key(s["id"])
        ent = _tabs_cache.get(s["id"])
        if ent and ent[0] > time.time():
            tabs = ent[2]
        else:
            tabs = [w.title for w in sh.worksheets()]
            _tabs_cache[s["id"]] = (time.time() + TABS_CACHE_TTL, sh, tabs)
        extra_tabs = (extra_sel or {}).get("tabs", {}).get(name)
        sel_tabs = tabs_for_question(tabs, q, extra_tabs)
        ranges = fetchmod.fetch_ranges(sh, [fetchmod.tab_range(t) for t in sel_tabs], name)
        return tabs, sel_tabs, ranges

    results = {}
    if use_snap:
        for s in sel_sheets:
            snap = snap_sheets.get(s["id"])
            if not snap:
                results[s["id"]] = None
                continue
            extra_tabs = (extra_sel or {}).get("tabs", {}).get(s.get("name"))
            tabs, sel_tabs, ranges = select_from_snapshot(snap, q, extra_tabs)
            results[s["id"]] = (sel_tabs, ranges, f"snapshot: {snap.get('fetched_at', latest)}")
    else:
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(sel_sheets)))) as ex:
            futs = {ex.submit(fetch_live, s): s for s in sel_sheets}
            for fut, s in futs.items():
                name = s.get("name", s["id"])
                try:
                    _tabs, sel_tabs, ranges = fut.result()
                    results[s["id"]] = (sel_tabs, ranges, "jonli holat")
                except Exception as e:
                    log(f"fetch xato '{name}': {type(e).__name__}: {str(e)[:120]} — snapshot fallback")
                    snap = snap_sheets.get(s["id"])
                    if snap:
                        extra_tabs = (extra_sel or {}).get("tabs", {}).get(name)
                        _tabs, sel_tabs, ranges = select_from_snapshot(snap, q, extra_tabs)
                        results[s["id"]] = (
                            sel_tabs, ranges, f"oxirgi snapshot: {latest} — jonli o'qib bo'lmadi"
                        )
                    else:
                        results[s["id"]] = None

    parts, total = [], 0
    sel = {"sheets": [], "tabs": {}}
    for s in sel_sheets:
        name = s.get("name", s["id"])
        r = results.get(s["id"])
        if r is None:
            parts.append(f"\n=== SHEET: {name} — O'QIB BO'LMADI (zaxira snapshot ham yo'q) ===")
            continue
        sel_tabs, ranges, tag = r
        block = [
            f"\n=== SHEET: {name} (manba: {tag}) ===\n"
            f"Raw kiritilgan tab'lar: {', '.join(sel_tabs) or '—'}"
        ]
        for rng in ranges:
            block.append(format_tab(fetchmod.tab_of_range(rng), ranges[rng]))
        snap = snap_sheets.get(s["id"])
        if snap:
            agg = sheet_aggregates(latest, snap, set(sel_tabs))
            if agg:
                block.append("BOSHQA TAB'LAR (faqat agregat):\n" + "\n".join(agg))
        text = "\n".join(block)
        if total + len(text) > MAX_DATA_CHARS:
            parts.append(f"\n=== SHEET: {name} — KONTEKST LIMITI TUFAYLI QISQARTIRILDI ===")
            break
        parts.append(text)
        total += len(text)
        sel["sheets"].append(name)
        sel["tabs"][name] = sel_tabs
    return "\n".join(parts), sel, ("snapshot" if use_snap else "live")


def month_aggregate(snap):
    """Snapshot'dagi joriy oy watch tabidan (Σideal, Σfakt) hisoblaydi."""
    for rng in snap.get("watch_ranges", []):
        tab = fetchmod.tab_of_range(rng)
        if fetchmod.norm(tab) in fetchmod.MONTHS:
            vals = snap.get("ranges", {}).get(rng, {}).get("values", [])
            header, rows = auditmod.data_rows(vals)
            ci = auditmod.find_col(header, "ideal")
            cf = auditmod.find_col(header, "proekt bali")
            si = sum(auditmod._numval(auditmod.cell(r, ci)) or 0 for _, r in rows)
            sf = sum(auditmod._numval(auditmod.cell(r, cf)) or 0 for _, r in rows)
            return tab, si, sf
    return None, 0, 0


def build_history_data(q, sel_names, budget):
    """Tarixiy snapshotlar: mos kunlarning watch tab'lari + kunlik agregatlar."""
    days = days_for_question(q)
    if not days:
        return ""
    today = date.today().isoformat()
    all_past = [d for d in snapshot_days() if d < today]
    parts, total = [], 0

    agg = []
    for d in all_past[-10:]:
        for snap in diffmod.load_day(d)[0].values():
            if sel_names and snap.get("name") not in sel_names:
                continue
            tab, si, sf = month_aggregate(snap)
            if tab and si:
                agg.append(
                    f"{d} | {snap.get('name')} [{tab}] | Σideal {si:.1f} | Σfakt {sf:.1f} | {sf / si * 100:.1f}%"
                )
    if agg:
        parts.append("KUNLIK AGREGATLAR (barcha mavjud kunlar):\n" + "\n".join(agg))

    for d in days:
        for snap in diffmod.load_day(d)[0].values():
            if sel_names and snap.get("name") not in sel_names:
                continue
            block = [f"\n=== TARIXIY SNAPSHOT {d}: {snap.get('name')} ==="]
            for rng in snap.get("watch_ranges", []):
                data = snap.get("ranges", {}).get(rng)
                if data:
                    block.append(format_tab(fetchmod.tab_of_range(rng), data))
            text = "\n".join(block)
            if total + len(text) > budget:
                parts.append(f"\n(tarixiy kontekst limiti — {d} qisman)")
                return "\n".join(parts)
            parts.append(text)
            total += len(text)
    return "\n".join(parts)


def audit_block():
    if not LAST_AUDIT.exists():
        return "(hali audit o'tkazilmagan)"
    try:
        return LAST_AUDIT.read_text(encoding="utf-8")[:1500]
    except OSError:
        return "(audit o'qib bo'lmadi)"


# ---------- Q&A infografik PDF ----------

def parse_qa_answer(ans):
    """Claude javobidan QA-JSON blokini ajratadi. Topilmasa/buzuq bo'lsa None
    (javob oddiy matn sifatida yuboriladi)."""
    m = re.search(r"```json\s*(.*?)```", ans, re.S)
    raw = m.group(1).strip() if m else None
    if raw is None:
        t = ans.strip()
        if t.startswith("{") and t.endswith("}"):
            raw = t
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError as e:
        log(f"QA-JSON parse bo'lmadi ({e}) — matn sifatida yuboriladi")
        return None
    if not (isinstance(d, dict) and (d.get("summary") or d.get("title"))):
        return None
    return d


def qa_json_to_text(qa):
    """QA-JSON → Telegram matni (PDF yiqilsa javob hech qachon yo'qolmasin;
    xotira uchun ham shu matn saqlanadi)."""
    L = []
    t = str(qa.get("title") or "").strip()
    if t:
        L.append(f"**{t}**")
    s = str(qa.get("summary") or "").strip()
    if s:
        L.append(s)
    for k in qa.get("kpis") or []:
        if isinstance(k, dict):
            line = f"• {k.get('label', '')}: {k.get('value', '')}"
            if k.get("sub"):
                line += f" ({k['sub']})"
            L.append(line)
    tb = qa.get("table")
    if isinstance(tb, dict) and isinstance(tb.get("rows"), list):
        if tb.get("title"):
            L.append(f"\n**{tb['title']}**")
        cols = tb.get("columns") or []
        if cols:
            L.append(" | ".join(str(c) for c in cols))
        for r in tb["rows"][:24]:
            if isinstance(r, list):
                L.append(" | ".join(str(c) for c in r))
    b = qa.get("bars")
    if isinstance(b, dict):
        if b.get("title"):
            L.append(f"\n**{b['title']}**")
        for it in (b.get("items") or [])[:12]:
            if isinstance(it, dict):
                disp = it.get("display") or it.get("value")
                note = f" ({it['note']})" if it.get("note") else ""
                L.append(f"• {it.get('label', '?')}: {disp}{note}")
    for w in qa.get("warnings") or []:
        L.append(f"⚠️ {w}")
    for i in qa.get("insights") or []:
        L.append(f"💡 {i}")
    if qa.get("note"):
        L.append(f"ℹ️ {qa['note']}")
    if qa.get("source"):
        L.append(f"Manba: {qa['source']}")
    return "\n".join(L)


def build_qa_caption(qa):
    """sendDocument caption: sarlavha + asosiy xulosa + PDF'ga ishora (≤1024)."""
    lines = [f"📊 {str(qa.get('title') or 'Savol-javob').strip()}"]
    s = str(qa.get("summary") or "").strip()
    if s:
        lines.append(s)
    w = qa.get("warnings") or []
    if w:
        lines.append(f"⚠️ {len(w)} ogohlantirish — PDF ichida")
    lines.append("📎 Batafsil jadval va grafiklar PDF ichida")
    return "\n".join(lines)[:1024]


def _prune_qa_pdfs(days=7):
    """Eski QA PDF/HTML fayllarini tozalaydi (papka o'sib ketmasin)."""
    try:
        cutoff = time.time() - days * 86400
        for p in list(QA_PDF_DIR.glob("*.pdf")) + list(QA_PDF_DIR.glob("*.html")):
            if p.stat().st_mtime < cutoff:
                p.unlink()
    except OSError:
        pass


def send_qa_pdf(qa, q, mid, filename=None):
    """QA-JSON → infografik PDF → sendDocument. Muvaffaqiyatda progress xabari
    o'chiriladi. Xatoda exception — chaqiruvchi matnga fallback qiladi."""
    import render_pdf

    QA_PDF_DIR.mkdir(parents=True, exist_ok=True)
    _prune_qa_pdfs()
    now = datetime.now()
    qa = dict(qa)
    qa.setdefault("question", q)
    qa["asked_at"] = now.strftime("%Y-%m-%d %H:%M")
    pdf = QA_PDF_DIR / f"qa-{now.strftime('%Y%m%d-%H%M%S')}.pdf"
    render_pdf.render_qa(qa, pdf)
    sendmod.tg_send_document(
        TOKEN, CHAT_ID, str(pdf), build_qa_caption(qa),
        filename=filename or f"KPI-javob-{now.strftime('%Y-%m-%d')}.pdf",
    )
    delete_status(mid)


def audit_qa_data(findings, source, today, ai_lines):
    """Audit natijalari (deterministik) → QA-PDF strukturasi. Claude shart emas."""
    fresh, acked = auditmod.split_acked(findings)
    crit = [f for f in fresh if f[2] == auditmod.CRIT]
    warn = [f for f in fresh if f[2] == auditmod.WARN]
    if not findings:
        summary = "Hammasi toza — muammo topilmadi ✅"
    elif not fresh:
        summary = "Yangi muammo yo'q — barcha topilmalar avvaldan tan olingan."
    else:
        summary = f"Yangi topilmalar: {len(crit)} kritik, {len(warn)} ogohlantirish."
    qa = {
        "title": "Data audit",
        "summary": summary,
        "kpis": [
            {"label": "Kritik", "value": str(len(crit)), "color": "red" if crit else "green"},
            {"label": "Ogohlantirish", "value": str(len(warn)), "color": "yellow" if warn else "green"},
            {"label": "Tan olingan", "value": str(len(acked)), "color": "muted",
             "sub": "kritik ro'yxatdan chiqarilgan"},
        ],
        "source": source,
    }
    rows = [
        ["🔴" if lvl == auditmod.CRIT else "🟡", sheet, tab, msg]
        for sheet, tab, lvl, msg, _k in sorted(fresh, key=lambda f: 0 if f[2] == auditmod.CRIT else 1)
    ]
    if rows:
        qa["table"] = {"title": "Yangi topilmalar", "columns": ["", "Sheet", "Tab", "Muammo"],
                       "rows": rows}
    notes = []
    if len(rows) > 24:
        notes.append(f"Jadvalda 24/{len(rows)} topilma — to'lig'i: /audit matn arxivida.")
    if acked:
        groups = {}
        for (sheet, _t, _l, _m, key), _e in acked:
            groups.setdefault(key, set()).add(sheet)
        ack_txt = " · ".join(
            f"{auditmod.KEY_LABELS.get(k, k)} ({len(s)} sheet)" for k, s in groups.items()
        )
        notes.append(f"🤝 Tan olingan: {ack_txt} — ro'yxat: /ack")
    if notes:
        qa["note"] = " ".join(notes)
    if ai_lines:
        qa["insights"] = ai_lines
    return qa


# ---------- savol / buyruqlar ----------

def do_question(q):
    t0 = time.monotonic()
    typing()
    months = months_in_question(q)
    mode, ref = classify(q, months)
    # Qisqa davom-savollar ("nega?", "batafsilroq") — tarix bo'lsa referensial
    if mode == "fast" and len(q) <= 25 and load_history():
        mode, ref = "deep", True
    labels = {
        "fast": "⏳ Tekshiryapman...",
        "deep": "📖 Ma'lumot o'qilyapti... (chuqur rejim)",
        "max": "📖 Ma'lumot o'qilyapti... (maksimal tahlil)",
    }
    mid = send_status(labels[mode])

    extra_sel = prev_selection() if ref else None
    data_text, sel, src = build_data(q, extra_sel, force_live=needs_live(q))
    t_fetch = time.monotonic()
    hist_data = ""
    if mode != "fast":
        hist_data = build_history_data(q, sel["sheets"], MAX_DATA_CHARS - len(data_text))
        edit_status(mid, f"🧠 Tahlil qilinyapti... ({'chuqur' if mode == 'deep' else 'maksimal'} rejim)")
    typing()
    kpi_rules, kpi_mode = analyze.kpi_block()
    prompt = (
        QA_PROMPT.read_text(encoding="utf-8")
        .replace("{{DATE}}", date.today().isoformat())
        .replace("{{QUESTION}}", q)
        .replace("{{HISTORY}}", history_block())
        .replace("{{AUDIT}}", audit_block())
        .replace("{{KPI_RULES}}", kpi_rules)
        .replace("{{KPI_MODE}}", kpi_mode)
        .replace("{{HISTORY_DATA}}", hist_data or "(tarixiy ma'lumot talab qilinmadi)")
        .replace("{{FORMAT}}", PDF_FORMAT if mode != "fast" else TEXT_FORMAT)
        .replace("{{DATA}}", data_text)
    )
    try:
        ans = analyze.run_claude(prompt, effort=EFFORT_BY_MODE.get(mode))
    except Exception as e:
        log(f"claude xato: {e}")
        if not edit_status(mid, "⚠️ Tahlil ishlamadi, keyinroq urinib ko'ring."):
            send_retry("⚠️ Tahlil ishlamadi, keyinroq urinib ko'ring.")
        remember(q, "(tahlil xatosi — javob berilmadi)", sel)
        return
    t_claude = time.monotonic()
    # PDF yo'li: deep/max javobda QA-JSON blok bo'lsa — infografik hujjat
    pdf_sent = False
    qa = parse_qa_answer(ans) if mode != "fast" else None
    if qa:
        if qa.get("source") is None and src == "snapshot":
            qa["source"] = f"snapshot {latest_day() or ''}".strip()
        edit_status(mid, "📄 PDF tayyorlanmoqda...")
        try:
            send_qa_pdf(qa, q, mid)
            pdf_sent = True
            ans = qa_json_to_text(qa)  # xotira uchun matn ekvivalenti
        except Exception as e:
            log(f"QA PDF bo'lmadi ({type(e).__name__}: {str(e)[:150]}) — matn fallback")
            ans = qa_json_to_text(qa)
    if pdf_sent:
        ok = True
    else:
        # Bitta bo'lakli javob — progress xabarining o'zini javobga aylantiramiz
        chunks = sendmod.split_chunks(sendmod.md_to_html(ans))
        if mid and len(chunks) == 1 and edit_status(mid, chunks[0], html=True):
            ok = True
        else:
            if mid:
                edit_status(mid, "📄 Javob:")
            ok = send_retry(ans)
    remember(q, ans if ok else "(javob yuborilmadi — tarmoq xatosi)", sel)
    log(f"javob {'yuborildi' if ok else 'YUBORILMADI'} ({'PDF' if pdf_sent else 'matn'}, {len(ans)} belgi)")
    log(
        f"META: mode={mode} ref={int(ref)} src={src} pdf={int(pdf_sent)} "
        f"fetch_ms={int((t_fetch - t0) * 1000)} claude_ms={int((t_claude - t_fetch) * 1000)} "
        f"ctx={len(data_text)} hist={len(hist_data)} ans={len(ans)}"
    )


def do_audit():
    typing()
    mid = send_status("⏳ Data audit boshlandi (sheet'lar jonli o'qilmoqda)...")
    typing()
    today = date.today().isoformat()
    try:
        findings, source = auditmod.run_checks(None)
    except Exception as e:
        log(f"audit xato: {e}")
        if not edit_status(mid, f"⚠️ Audit ishlamadi: {str(e)[:150]}"):
            send_retry(f"⚠️ Audit ishlamadi: {str(e)[:150]}")
        return
    det, crit = auditmod.render(findings, source, today)
    auditmod.save_last(det)
    ai_summary = None
    if findings:
        try:
            ai_summary = auditmod.claude_summary(det, today)
        except Exception as e:
            log(f"audit claude xato: {e}")
    # Infografik PDF (deterministik struktura); yiqilsa — to'liq matn fallback
    pdf_sent = False
    try:
        ai_lines = (
            [l.strip("•-# ").strip() for l in ai_summary.splitlines() if l.strip()][:4]
            if ai_summary else []
        )
        qa = audit_qa_data(findings, source, today, ai_lines)
        send_qa_pdf(qa, "/audit", mid, filename=f"Data-audit-{today}.pdf")
        pdf_sent = True
    except Exception as e:
        log(f"/audit PDF bo'lmadi ({type(e).__name__}: {str(e)[:150]}) — matn rejimi")
    if pdf_sent:
        ok = True
    else:
        if ai_summary:
            det += "\n\n💡 **Xulosa va takliflar (AI):**\n" + ai_summary
        elif findings:
            det += "\n\n(AI xulosa ishlamadi — deterministik natijalar bilan cheklandi)"
        ok = send_retry(det)
    remember("/audit", det[:600] if ok else "(audit natijasi yuborilmadi)")
    log(
        f"/audit {'yuborildi' if ok else 'YUBORILMADI'} "
        f"({'PDF' if pdf_sent else 'matn'}, {len(findings)} topilma, {len(crit)} kritik)"
    )


def do_hisobot():
    typing()
    send_retry("⏳ Hisobot tayyorlanmoqda...", attempts=2)
    typing()
    latest = latest_day()
    if latest is None:
        send_retry("Hali birorta snapshot yo'q — avval kunlik 09:00 ishga tushishini kuting.")
        return
    old_sheets = diffmod.load_day(latest)[0]
    cfg = fetchmod.load_config()
    today = date.today().isoformat()

    result = {
        "date": today,
        "prev_date": latest,
        "baseline": False,
        "fetch_errors": {},
        "missing_today": {},
        "sheets": {},
        "totals": {"sheets": 0, "added": 0, "removed": 0, "changed": 0, "header_changed": 0},
    }
    for s in cfg:
        name = s.get("name", s["id"])
        try:
            sh, tabs = sheet_tabs(s)
            watch_titles = fetchmod.detect_watch_tabs(tabs)
            ranges_keys = [fetchmod.tab_range(t) for t in watch_titles]
            live = fetchmod.fetch_ranges(sh, ranges_keys, name) if ranges_keys else {}
            kc_map = fetchmod.resolve_key_columns(tabs, s.get("key_column", 1))
        except Exception as e:
            result["fetch_errors"][s["id"]] = {
                "name": name, "error": f"{type(e).__name__}: {str(e)[:200]}"
            }
            continue
        entry = {"name": name, "watch": s.get("watch", ""), "ranges": {}}
        old_snap = old_sheets.get(s["id"])
        if old_snap is None:
            entry["baseline"] = True
        for rng, d in live.items():
            vals = d.get("values", [])
            kc = kc_map.get(rng, 1) if isinstance(kc_map, dict) else kc_map
            old_rng = (old_snap or {}).get("ranges", {}).get(rng)
            if old_snap is None or old_rng is None:
                r = diffmod.baseline_range(vals)
                if old_snap is not None:
                    r["new_range"] = True
            else:
                r = diffmod.diff_range(old_rng.get("values", []), vals, kc)
            entry["ranges"][rng] = r
            st = r["stats"]
            for k in ("added", "removed", "changed"):
                result["totals"][k] += st.get(k, 0)
            if "header_changed" in r:
                result["totals"]["header_changed"] += 1
        result["sheets"][s["id"]] = entry
    result["totals"]["sheets"] = len(result["sheets"])

    t = result["totals"]
    quiet = (
        t["added"] == t["removed"] == t["changed"] == 0
        and t["header_changed"] == 0
        and not result["fetch_errors"]
        and not any(s.get("baseline") for s in result["sheets"].values())
    )
    if quiet:
        msg = (
            f"📊 O'zgarish yo'q: hozirgi jonli holat {latest} snapshot'idan farq qilmayapti "
            f"({t['sheets']} sheet tekshirildi)."
        )
        send_retry(msg)
        remember("/hisobot", msg)
        log(f"/hisobot: o'zgarish yo'q ({latest} ga nisbatan) — claude chaqirilmadi")
        return

    mode = (
        f"Bu oraliq (on-demand) hisobot: oxirgi saqlangan snapshot ({latest}) va HOZIRGI "
        f"jonli holat orasidagi o'zgarishlarni tahlil qil."
    )
    context = analyze.build_context(result)
    kpi_rules, kpi_mode = analyze.kpi_block()
    prompt = (
        DAILY_PROMPT.read_text(encoding="utf-8")
        .replace("{{DATE}}", today)
        .replace("{{PREV_DATE}}", latest)
        .replace("{{MODE}}", mode)
        .replace("{{KPI_RULES}}", kpi_rules)
        .replace("{{KPI_MODE}}", kpi_mode)
        .replace("{{CONTEXT}}", context)
    )
    log(f"/hisobot: claude -p (kontekst {len(context)} belgi)")
    try:
        ans = analyze.run_claude(prompt)
    except Exception as e:
        log(f"claude xato: {e}")
        ans = analyze.fallback_report(result, str(e))
    # PDF ko'rinishida urinamiz; yiqilsa — matn (hisobot hech qachon yo'qolmasin)
    ok = False
    try:
        import render_pdf

        jdata = analyze.build_report_json(today, result, ans, insights=[], out_name="report-live.json")
        pdf_path = diffmod.SNAPSHOTS / today / "report-live.pdf"
        render_pdf.render(jdata, pdf_path)
        sendmod.tg_send_document(
            TOKEN, CHAT_ID, str(pdf_path),
            sendmod.build_caption(jdata, title="oraliq hisobot (jonli holat)"),
            filename=f"KPI-hisobot-{today}-live.pdf",
        )
        ok = True
        log("/hisobot PDF yuborildi")
    except Exception as e:
        log(f"/hisobot PDF bo'lmadi ({type(e).__name__}: {str(e)[:120]}) — matn rejimi")
        ok = send_retry(ans)
    remember("/hisobot", ans[:600] if ok else "(hisobot yuborilmadi)")
    log(f"/hisobot {'yuborildi' if ok else 'YUBORILMADI'} ({len(ans)} belgi)")


def handle_media(msg):
    """Rasm/hujjat qabul qilish (FAQAT egasidan — chaqiruvchi tekshirgan).
    Caption'da "logo" → logo-draft; boshqa rasm → dizayn referensi (vision)."""
    doc, photos = msg.get("document"), msg.get("photo")
    caption = (msg.get("caption") or "").strip()
    if doc:
        name = doc.get("file_name") or "fayl"
        mime = doc.get("mime_type") or ""
        size = doc.get("file_size") or 0
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if not (mime.startswith("image/") or ext in design.LOGO_EXTS):
            send_retry("Faqat rasm fayllari qabul qilinadi (PNG/JPG/SVG/WebP).", attempts=2)
            return "media-reject"
        file_id = doc["file_id"]
    else:
        biggest = photos[-1]
        file_id = biggest["file_id"]
        size = biggest.get("file_size") or 0
        name = "photo.jpg"
    if size and size > design.MAX_FILE:
        send_retry("Fayl juda katta — limit 10MB.", attempts=2)
        return "media-reject"
    try:
        path = design.download(TOKEN, file_id, name)
    except Exception as e:
        log(f"media yuklab olinmadi: {e}")
        send_retry("⚠️ Faylni yuklab olib bo'lmadi, qayta urinib ko'ring.", attempts=2)
        return "media-error"
    log(f"media qabul qilindi: {path.name} ({size or '?'} bayt, caption={caption!r})")

    if "logo" in caption.lower():
        design.set_logo_draft(path)
        send_retry("🖼 Logo qabul qilindi — preview tayyorlanmoqda...", attempts=2)
        typing()
        try:
            pv = design.make_preview(use_logo_draft=True)
            sendmod.tg_send_document(
                TOKEN, CHAT_ID, str(pv),
                "🖼 Logo qo'shildi — preview yuqorida.\n«tasdiq» / «bekor» / «batafsil»",
                filename="preview-logo.pdf",
            )
            design.save_pending({"type": "logo"})
        except Exception as e:
            log(f"logo preview xato: {e}")
            send_retry(f"⚠️ Preview chiqmadi: {str(e)[:120]}", attempts=2)
            design.discard_logo_draft()
        return "logo-draft"

    send_retry("🎨 Referens qabul qilindi — palitra va uslub tahlil qilinmoqda (1-2 daqiqa)...", attempts=2)
    typing()
    try:
        theme, issues = design.analyze_reference(path)
        design.save_draft(theme)  # to'liq tahlil draft'da qoladi (matnli tuzatishlar uchun)
        if issues:
            log(f"referens: default qolgan kalitlar: {', '.join(issues)}")
        pv = design.make_preview(theme_name="draft")
        sendmod.tg_send_document(
            TOKEN, CHAT_ID, str(pv),
            "🎨 Referens tahlil qilindi — preview yuqorida.\n«tasdiq» / «bekor» / «batafsil»",
            filename="preview-referens.pdf",
        )
        design.save_pending({"type": "theme"})
    except Exception as e:
        log(f"referens tahlili xato: {type(e).__name__}: {e}")
        send_retry(f"⚠️ Tahlil bo'lmadi: {str(e)[:150]}", attempts=2)
    return "reference"


def apply_pending(p, low):
    """«tasdiq»/«bekor»/«batafsil» — kutilayotgan dizayn o'zgarishiga munosabat."""
    if low in ("batafsil", "tafsilot", "details"):
        send_retry(design.pending_details(p), attempts=2)
        return "design-detail"  # pending saqlanadi — hali tasdiq/bekor kutilyapti
    ok_words = ("tasdiq", "ha", "ok", "tasdiqlayman")
    no_words = ("bekor", "yo'q", "yoq", "cancel")
    if low not in ok_words + no_words:
        return None
    design.clear_pending()
    t = p.get("type")
    if low in no_words:
        if t == "logo":
            design.discard_logo_draft()
        send_retry("❌ Bekor qilindi — hech narsa o'zgarmadi.", attempts=2)
        return "design-cancel"
    if t == "logo":
        design.apply_logo_draft()
        design.git_commit_brand("dizayn: yangi logo tasdiqlandi")
        send_retry("✅ Logo tasdiqlandi — ertangi 09:00 hisobotidan boshlab chiqadi.", attempts=2)
        return "design-apply"
    if t == "theme":
        import shutil as _sh

        _sh.copy(design.THEMES / "draft.yaml", design.THEMES / "custom.yaml")
        design.set_active("custom")
        design.git_commit_brand("dizayn: referens/so'rovdan custom theme tasdiqlandi")
        send_retry("✅ Yangi dizayn tasdiqlandi (theme: custom) — ertangi 09:00 dan amalda. /dizayn bilan istalgan payt almashtirish mumkin.", attempts=2)
        return "design-apply"
    if t == "switch":
        design.set_active(p.get("name", "default"))
        design.git_commit_brand(f"dizayn: theme '{p.get('name')}' ga almashtirildi")
        send_retry(f"✅ Theme almashdi: {p.get('name')} — ertangi 09:00 dan amalda.", attempts=2)
        return "design-apply"
    return "design-cancel"


def do_dizayn(arg):
    presets = design.theme_list()
    if not arg:
        send_retry(
            f"🎨 Joriy theme: **{design.active_name()}**\n"
            f"Presetlar: {', '.join(presets) or '—'}\n\n"
            "• /dizayn <nom> — almashtirish (preview + tasdiq)\n"
            "• /dizayn <so'rov> — matnli o'zgartirish (\"sarlavhani to'q ko'k qil\")\n"
            "• Rasm yuboring — referens tahlili; caption'da \"logo\" bo'lsa — logo",
            attempts=2,
        )
        return "dizayn-list"
    name = arg.strip().lower()
    if name in presets:
        send_retry(f"⏳ «{name}» preview tayyorlanmoqda...", attempts=2)
        typing()
        try:
            pv = design.make_preview(theme_name=name)
            sendmod.tg_send_document(
                TOKEN, CHAT_ID, str(pv),
                f"🎨 «{name}» — preview yuqorida.\n«tasdiq» / «bekor» / «batafsil»",
                filename=f"preview-{name}.pdf",
            )
            design.save_pending({"type": "switch", "name": name})
        except Exception as e:
            log(f"preview xato: {e}")
            send_retry(f"⚠️ Preview chiqmadi: {str(e)[:120]}", attempts=2)
        return "dizayn-switch"
    # matnli dizayn so'rovi
    send_retry("🎨 So'rov theme'ga tarjima qilinmoqda...", attempts=2)
    typing()
    try:
        theme, issues = design.instruction_to_draft(arg)
        design.save_draft(theme)
        if issues:
            log(f"dizayn so'rovi: default qolgan kalitlar: {', '.join(issues)}")
        pv = design.make_preview(theme_name="draft")
        sendmod.tg_send_document(
            TOKEN, CHAT_ID, str(pv),
            "🎨 O'zgartirish tayyor — preview yuqorida.\n«tasdiq» / «bekor» / «batafsil»",
            filename="preview-draft.pdf",
        )
        design.save_pending({"type": "theme"})
    except Exception as e:
        log(f"dizayn so'rovi xato: {e}")
        send_retry(f"⚠️ Bo'lmadi: {str(e)[:150]}", attempts=2)
    return "dizayn-edit"


def handle_update(upd):
    msg = upd.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    if chat is None:
        kinds = ", ".join(k for k in upd if k != "update_id") or "nomalum"
        log(f"skip: message emas ({kinds})")
        return "skip"
    # XAVFSIZLIK: faqat egasining chat'i. Boshqasiga JAVOB YO'Q, faqat log.
    if str(chat) != str(CHAT_ID):
        text_preview = (msg.get("text") or msg.get("caption") or "")[:60]
        log(f"IGNORE: begona chat_id={chat} (matn: {text_preview!r})")
        return "ignored"
    if msg.get("document") or msg.get("photo"):
        return handle_media(msg)
    text = (msg.get("text") or "").strip()
    if not text:
        send_retry("Faqat matn yoki rasm qabul qilaman.", attempts=2)
        return "non-text"
    # Kutilayotgan dizayn tasdig'i bo'lsa — «tasdiq»/«bekor» so'zlarini ushlaymiz
    p = design.load_pending()
    if p:
        r = apply_pending(p, text.lower().strip())
        if r:
            log(f"SAVOL ({chat}): {text[:60]!r} → {r}")
            return r
        design.save_pending(p)  # boshqa matn — pending qolsin
    log(f"SAVOL ({chat}): {text[:200]!r}")
    low = text.lower()
    if low.startswith("/help") or low.startswith("/start"):
        send_retry(HELP, attempts=2)
        return "help"
    if low.startswith("/yangi"):
        reset_history()
        send_retry("🧹 Suhbat konteksti tozalandi — yangi mavzudan boshlaymiz.", attempts=2)
        return "reset"
    if low.startswith("/hisobot"):
        do_hisobot()
        return "hisobot"
    if low.startswith("/audit"):
        do_audit()
        return "audit"
    if low.startswith("/ack"):
        arg = text[4:].strip()
        if not arg:
            entries = auditmod.load_acked()
            L = ["🤝 **Tan olingan muammolar:**"]
            if entries:
                for e in entries:
                    sc = f" [{e['sheet']}]" if e.get("sheet") else ""
                    nt = f" — {e['note']}" if e.get("note") else ""
                    L.append(f"• {e['key']}{sc} ({e.get('date', '?')}){nt}")
            else:
                L.append("(hozircha bo'sh)")
            L.append("\nQo'shish: /ack <kalit> [izoh]")
            L.append("Kalitlar: " + ", ".join(auditmod.KEY_LABELS))
            send_retry("\n".join(L), attempts=2)
            return "ack-list"
        p = arg.split(None, 1)
        key, note = p[0].strip().lower(), (p[1].strip() if len(p) > 1 else "")
        if key not in auditmod.KEY_LABELS:
            send_retry(
                f"Noma'lum kalit: {key}\nKalitlar: " + ", ".join(auditmod.KEY_LABELS),
                attempts=2,
            )
            return "ack-bad"
        if auditmod.add_ack(key, note):
            log(f"/ack qo'shildi: {key} ({note!r})")
            send_retry(
                f"✅ Tan olindi: {auditmod.KEY_LABELS[key]} ({key}). Endi hisobotlarda "
                f"qisqa qatorda ko'rinadi, kritik sifatida takrorlanmaydi.",
                attempts=2,
            )
        else:
            send_retry(f"«{key}» allaqachon tan olingan.", attempts=2)
        return "ack-add"
    if low.startswith("/dizayn"):
        return do_dizayn(text[len("/dizayn"):].strip())
    if low.startswith("/dashboard"):
        import dashboard_writer as dw

        url = dw.dashboard_url()
        if url:
            send_retry(f"📊 Dashboard: {url}\nOxirgi yangilanish: {dw.last_updated()}", attempts=2)
        else:
            send_retry("Dashboard hali ulanmagan — config.yaml ga dashboard_id kiritilishi kerak.", attempts=2)
        return "dashboard"
    if text.startswith("/"):
        send_retry("Bunday buyruq yo'q. " + HELP, attempts=2)
        return "unknown-cmd"
    do_question(text)
    return "answered"


def main():
    init_env()
    log(f"listener boshlandi (chat_id={CHAT_ID}, poll={POLL_TIMEOUT}s)")
    recover_inflight()
    last = load_last()
    if last is None:
        last = drop_backlog()
    while True:
        try:
            r = api(
                "getUpdates",
                {"offset": last + 1, "timeout": POLL_TIMEOUT},
                timeout=POLL_TIMEOUT + 15,
            )
            if r.status_code == 409:
                log("409 conflict: boshqa getUpdates iste'molchisi bor — 15s")
                time.sleep(15)
                continue
            if r.status_code != 200:
                log(f"getUpdates HTTP {r.status_code}: {r.text[:200]} — 10s kutaman")
                time.sleep(10)
                continue
            for upd in r.json().get("result", []):
                # Avval offset saqlanadi — xabar hech qachon ikki marta ishlanmaydi.
                # Inflight fayli esa restart/kill'da uzilgan xabarni tiklash uchun.
                last = upd["update_id"]
                save_last(last)
                _write_inflight(upd)
                try:
                    handle_update(upd)
                except Exception as e:
                    log(f"XATO handle_update: {e}\n{traceback.format_exc()[:800]}")
                    try:
                        send_retry("⚠️ Xatolik yuz berdi — keyinroq urinib ko'ring.", attempts=2)
                    except Exception:
                        pass
                finally:
                    _clear_inflight()
        except requests.RequestException as e:
            log(f"tarmoq xatosi: {type(e).__name__}: {str(e)[:150]} — 10s kutaman")
            time.sleep(10)


if __name__ == "__main__":
    main()
