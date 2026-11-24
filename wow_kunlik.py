#!/usr/bin/env python3
"""Kunlik reja (ertalab) va kunlik hisobot (kechqurun) → boshliq lichkasiga.
Bot nomi kodda yo'q — bot_nomi() uni Telegram'dan o'qiydi (24.11 dan «WALL-E»).

Oqim:
  • Ertalab 09:00, 10:00, 11:00, 12:00 — «Bugun qanday ishlar qilasiz?» (javob berilmaguncha).
  • Kechqurun 19:00, 20:00, 21:00 — «Bugun nimalar qildingiz?» (ertalabki reja bilan).
  • Javob — matn yoki ovoz (stt.py: whisper.cpp + o'zbekcha rubaistt). Bir nechta xabar
    bo'lishi mumkin: har biri joriy jadvalga qo'shiladi yoki uni tuzatadi
    («3-ni o'chir», «Livardi emas, Livarti»).
  • Claude jadval tuzadi (ma'lum loyiha va xodim nomlari bilan noto'g'ri eshitilgan nomlarni
    tuzatadi) → Sheets ko'rinishidagi PNG jadval (wow_jadval.py) egaga preview bo'lib keladi.
  • ✅ bosilganda — yoki qoralama AVTO_DAQ daqiqa jim tursa — jadval egasining shaxsiy
    akkauntidan (userbot_sender.send_photo) boshliq lichkasiga ketadi.

Holat: DATA/wow_kunlik/<YYYY-MM-DD>.json (kun bo'yicha), sozlama: DATA/wow_kunlik/sozlama.json.
Repo PUBLIC — boshliq kontakti kodda emas: «/boshliq @username Ism» buyrug'i bilan volume'ga.

Xabar oqimi (bot_listener): ushlaydimi(msg) → slot bo'lsa xabarni_ishlash(msg, slot);
«savol» qaytsa — odatiy Q&A. Inline tugmalar: callback(cq). Buyruqlar: buyruq(text, msg).
Rejalovchi (supervisor): sorov_job(slot) har soatda, avto_job() har daqiqada, boot() bir marta.
"""
import json
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
DIR = DATA / "wow_kunlik"
SNAPSHOTS = DATA / "snapshots"
PROMPT = BASE / "prompts" / "wow-kunlik.md"
TZ = "Asia/Tashkent"

from maxfiy import redact, safe_exc  # noqa: E402  (log'da token/sir yo'q)

SLOTLAR = {
    "ertalab": {"soatlar": (9, 10, 11, 12), "rejim": "reja", "sarlavha": "Kunlik reja"},
    "kechqurun": {"soatlar": (19, 20, 21), "rejim": "hisobot", "sarlavha": "Kunlik hisobot"},
}
AVTO_DAQ = 15                  # qoralama shuncha daqiqa jim tursa — avtomatik yuboriladi
ISHLANMOQDA_ESKI = 20 * 60     # s — osilib qolgan «ishlanmoqda» belgisi e'tiborsiz qoladi
MAX_QATOR = 30
MAX_YUBORISH = 6               # bir slotga bir kunda boshliqqa ko'pi bilan (qayta urinishlar bilan)
VOICE_MAX_SEC = 180
CLAUDE_TIMEOUT = 240
BUYRUQLAR = ("/kunlik", "/ertalab", "/kechqurun", "/dam", "/boshliq")
HAFTA = ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba")
HOLAT_BELGI = {"bajarildi": "✅", "jarayonda": "⏳", "bajarilmadi": "❌", "ertaga": "➡️", "": "▫️"}
# Tartib muhim (birinchi mos kelgani olinadi): inkor → qisman → keyinga → bajarildi.
# «qisman bajarildi» — jarayonda; «bajarilmadi» ichida «bajaril» bor — u oldin turadi.
_HOLAT_SINONIM = (
    ("bajarilmadi", "bajarilmadi"), ("qilinmadi", "bajarilmadi"), ("bo'lmadi", "bajarilmadi"),
    ("not done", "bajarilmadi"), ("❌", "bajarilmadi"),
    ("jarayonda", "jarayonda"), ("qisman", "jarayonda"), ("davom", "jarayonda"), ("⏳", "jarayonda"),
    ("ertaga", "ertaga"), ("qoldirildi", "ertaga"), ("ko'chirildi", "ertaga"), ("➡️", "ertaga"),
    ("bajarildi", "bajarildi"), ("bajarilgan", "bajarildi"), ("qilindi", "bajarildi"),
    ("tayyor", "bajarildi"), ("done", "bajarildi"), ("✅", "bajarildi"),
)
_KONTAKT_RE = re.compile(r"^(@[A-Za-z][A-Za-z0-9_]{3,31}|\+\d{9,15}|me)$")
_SANA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_LOCK = threading.RLock()


def log(msg):
    print(f"[wow] {redact(msg)}", flush=True)


def hozir():
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(TZ))


# ---------------- holat (kun fayli) va sozlama ----------------

def _bosh_slot():
    return {"holat": "yangi", "sorovlar": [], "pauza": False, "jadval": [], "kirishlar": [],
            "preview_mid": None, "xabarlar": [], "oxirgi": None, "ishlanmoqda": None,
            "yuborildi": None, "xato": None, "yuborish_soni": 0, "yangilangan": False}


def _bosh_kun(sana):
    return {"sana": sana, "faol": None, "dam": False,
            "ertalab": _bosh_slot(), "kechqurun": _bosh_slot()}


def _kun_fayl(sana):
    return DIR / f"{sana}.json"


def yukla(sana):
    """Kun holati (fayl yo'q/buzuq bo'lsa — bo'sh holat). Yetishmagan kalitlar to'ldiriladi."""
    try:
        d = json.loads(_kun_fayl(sana).read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError("dict emas")
    except (OSError, ValueError):
        return _bosh_kun(sana)
    for k, v in _bosh_kun(sana).items():
        d.setdefault(k, v)
    for slot in SLOTLAR:
        s = d.get(slot) if isinstance(d.get(slot), dict) else {}
        for k, v in _bosh_slot().items():
            s.setdefault(k, v)
        d[slot] = s
    return d


def _yoz(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)                       # atomik: yarim yozilgan fayl qolmaydi


def saqla(st):
    _yoz(_kun_fayl(st["sana"]), st)


def sozlama():
    try:
        d = json.loads((DIR / "sozlama.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sozlama_saqla(**kw):
    with _LOCK:
        d = sozlama()
        d.update(kw)
        _yoz(DIR / "sozlama.json", d)
        return d


def _avto_daq(sz=None):
    sz = sozlama() if sz is None else sz
    v = sz.get("avto_daq", AVTO_DAQ)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return AVTO_DAQ


def _yoqilgan(sz=None):
    sz = sozlama() if sz is None else sz
    return bool(sz.get("yoqilgan", True))


def _ga(soz):
    """O'zbekcha jo'nalish qo'shimchasi: «Anvar aka» → «Anvar akaga», «Bek» → «Bekka»."""
    s = str(soz or "").rstrip()
    if s[-1:].lower() == "k":
        return s + "ka"
    if s[-1:].lower() == "q":
        return s + "qa"
    return s + "ga"


def _kimga():
    nomi = (sozlama().get("boshliq_nomi") or "").strip()
    return _ga(nomi) if nomi else "boshliqqa"


def _bosh_harf(s):
    return s[:1].upper() + s[1:]


def _sana_yorliq(sana):
    d = datetime.strptime(sana, "%Y-%m-%d")
    return f"{d.strftime('%d.%m.%Y')}, {HAFTA[d.weekday()]}"


def _vaqt(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _ismni_eslab(msg):
    """Rasm sarlavhasidagi ism — egasining Telegram ismidan (bir marta; /kunlik ism bilan o'zgaradi)."""
    try:
        if sozlama().get("ism"):
            return
        f = (msg or {}).get("from") or {}
        ism = " ".join(x for x in (f.get("first_name"), f.get("last_name")) if x).strip()
        if ism:
            sozlama_saqla(ism=ism[:60])
    except Exception as e:                              # noqa: BLE001
        log(f"ism saqlanmadi: {e}")


# ---------------- Telegram (bot nomidan, egasining chati) ----------------

def _tg():
    return (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            os.environ.get("TELEGRAM_CHAT_ID", "").strip())


_NOM_KESH = {"t": 0.0, "nom": ""}
NOM_TTL = 600                  # s — nom o'zgarsa ko'pi bilan 10 daqiqada hamma joyga yetadi


def bot_nomi():
    """Botning Telegram'dagi joriy nomi (yordam sarlavhasi, /kunlik, jadval rasmidagi belgi).
    Nom FAQAT Telegram'da o'zgartiriladi — setMyName yoki BotFather → Edit Name; kod va deploy
    shart emas. Avval getMyName: getMe.first_name keshlanib eski nomni qaytarishi mumkin
    (24.11 da 7+ daqiqa shunday bo'ldi). Telegram javob bermasa — oxirgi ma'lum nom."""
    import time

    if _NOM_KESH["nom"] and time.monotonic() - _NOM_KESH["t"] < NOM_TTL:
        return _NOM_KESH["nom"]
    nom = ""
    if _tg()[0]:                            # tokensiz (testlar, lokal) — tarmoqqa chiqilmaydi
        for method in ("getMyName", "getMe"):
            res = _api(method, {})
            if isinstance(res, dict):
                nom = str(res.get("name") or res.get("first_name") or "").strip()
            if nom:
                break
    if nom:
        _NOM_KESH.update(t=time.monotonic(), nom=nom[:64])
    return _NOM_KESH["nom"] or "Bot"


def _api(method, payload):
    """JSON chaqiruv. Natija (result) yoki None — xato yiqitmaydi, faqat log."""
    import send as sendmod

    token, _ = _tg()
    try:
        r = sendmod.tg_call(token, method, payload)
    except Exception as e:                              # noqa: BLE001
        log(f"{method} xato: {type(e).__name__}: {str(e)[:150]}")
        return None
    if r.status_code != 200:
        log(f"{method} {r.status_code}: {r.text[:200]}")
        return None
    try:
        return r.json().get("result")
    except ValueError:
        return None


def _kb(*qatorlar):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in q] for q in qatorlar]}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def xabar(html, kb=None):
    _, chat = _tg()
    p = {"chat_id": chat, "text": html, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb:
        p["reply_markup"] = kb
    res = _api("sendMessage", p)
    return (res or {}).get("message_id") if isinstance(res, dict) else None


def rasm(png, caption_html, kb=None):
    """sendPhoto (multipart). message_id yoki None."""
    import requests

    token, chat = _tg()
    data = {"chat_id": chat, "caption": redact(caption_html)[:1024], "parse_mode": "HTML"}
    if kb:
        data["reply_markup"] = json.dumps(kb)
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data=data,
                          files={"photo": ("jadval.png", png, "image/png")}, timeout=120)
    except requests.RequestException as e:
        log(f"sendPhoto xato: {safe_exc(e)}")
        return None
    if r.status_code != 200:
        log(f"sendPhoto {r.status_code}: {r.text[:200]}")
        return None
    try:
        return r.json().get("result", {}).get("message_id")
    except ValueError:
        return None


def caption_tahrir(mid, html, kb=None):
    _, chat = _tg()
    return _api("editMessageCaption", {
        "chat_id": chat, "message_id": mid, "caption": html, "parse_mode": "HTML",
        "reply_markup": kb or {"inline_keyboard": []},
    }) is not None


def matn_tahrir(mid, html, kb=None):
    _, chat = _tg()
    return _api("editMessageText", {
        "chat_id": chat, "message_id": mid, "text": html, "parse_mode": "HTML",
        "disable_web_page_preview": True, "reply_markup": kb or {"inline_keyboard": []},
    }) is not None


def tahrir(mid, html, kb=None):
    """Rasmli xabar — caption, matnli (zaxira preview) — text tahriri."""
    return bool(mid) and (caption_tahrir(mid, html, kb) or matn_tahrir(mid, html, kb))


def tugmalarni_olib_tashla(mid):
    _, chat = _tg()
    _api("editMessageReplyMarkup", {"chat_id": chat, "message_id": mid,
                                    "reply_markup": {"inline_keyboard": []}})


def ochir(mid):
    _, chat = _tg()
    _api("deleteMessage", {"chat_id": chat, "message_id": mid})


def javob_cb(cb_id, text=""):
    _api("answerCallbackQuery", {"callback_query_id": cb_id, "text": str(text)[:190]})


# ---------------- ma'lum nomlar (ovozni tuzatish uchun) ----------------

def _loyiha_nomlari(rows):
    """«Smm main» qatorlari → loyiha nomlari (aktivlari oldin). Sarlavha qatori «Proektlar nomi»."""
    for i, row in enumerate(rows[:15]):
        cells = [str(c).strip().lower() for c in (row or [])]
        if "proektlar nomi" not in cells:
            continue
        j = cells.index("proektlar nomi")
        k = cells.index("ish xolati") if "ish xolati" in cells else None
        aktiv, qolgan = [], []
        for r in rows[i + 1:]:
            if len(r) <= j or not str(r[j]).strip():
                continue
            nom = str(r[j]).strip()
            holat = str(r[k]).strip().lower() if k is not None and len(r) > k else ""
            (aktiv if any(w in holat for w in ("aktiv", "ishla", "jarayon", "davom")) else qolgan)\
                .append(nom)
        return aktiv + qolgan
    return []


_NOMLAR_KESH = {"t": 0.0, "nomlar": []}
NOMLAR_TTL = 1800              # s — snapshot kuniga bir marta yangilanadi, har xabarda o'qilmasin


def malum_nomlar(limit=150):
    """Oxirgi snapshot'dagi «Smm main» loyiha nomlari + PM ismlari (sheet nomlaridan).
    Ovoz transkriptidagi noto'g'ri eshitilgan nomlarni Claude shu ro'yxat bo'yicha tuzatadi.
    Topilmasa — bo'sh ro'yxat (xato yiqitmaydi). Natija NOMLAR_TTL davomida keshlanadi."""
    import time

    if _NOMLAR_KESH["nomlar"] and time.monotonic() - _NOMLAR_KESH["t"] < NOMLAR_TTL:
        return _NOMLAR_KESH["nomlar"][:limit]
    nomlar = []
    try:
        kunlar = sorted(p for p in SNAPSHOTS.iterdir() if p.is_dir() and len(p.name) == 10)
    except OSError:
        kunlar = []
    for kun in reversed(kunlar[-3:]):
        for f in sorted(kun.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict):
                continue
            m = re.match(r"(.+?)\s+PM KPI", str(d.get("name") or ""))
            if m:
                nomlar.insert(0, m.group(1).strip())
            for key, rows in (d.get("ranges") or {}).items():
                if str(key).startswith("'Smm main'!") and isinstance(rows, list):
                    nomlar += _loyiha_nomlari(rows)
        if nomlar:
            break
    out, bor = [], set()
    for n in nomlar:
        k = n.lower()
        if n and k not in bor and len(n) <= 60:
            bor.add(k)
            out.append(n)
    if out:
        _NOMLAR_KESH.update(t=time.monotonic(), nomlar=out)
    return out[:limit]


# ---------------- Claude: jadval tuzish / tahrirlash ----------------

def _prompt(rejim, joriy, reja, nomlar, kiritma, tur, sana):
    qiymat = {
        "REJIM": rejim,
        "SANA": sana,
        "JORIY": json.dumps(joriy, ensure_ascii=False) if joriy else "(bo'sh)",
        "REJA": json.dumps(reja, ensure_ascii=False) if reja else "(yo'q)",
        "NOMLAR": ", ".join(nomlar) if nomlar else "(yo'q)",
        "TUR": "ovozli xabar transkripti" if tur == "ovoz" else "matn",
        "KIRITMA": kiritma,
    }
    shablon = PROMPT.read_text(encoding="utf-8")
    # bir o'tishda: foydalanuvchi matnidagi «{{...}}» qayta almashtirilmaydi
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: qiymat.get(m.group(1), m.group(0)), shablon)


def json_ol(raw):
    s = str(raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("javobda JSON topilmadi")
    return json.loads(s[i:j + 1])


_APOSTROF = str.maketrans({c: "'" for c in "ʻʼ‘’`´"})   # o‘ / oʻ / o’ — hammasi o'


def holat_norm(h):
    t = str(h or "").strip().lower().translate(_APOSTROF)
    if not t:
        return ""
    for kalit, qiymat in _HOLAT_SINONIM:
        if t == kalit:
            return qiymat
    for kalit, qiymat in _HOLAT_SINONIM:
        if kalit in t:
            return qiymat
    return ""


def _toza(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def tekshir(d, slot):
    """Claude JSON'ini tekshiradi va me'yorlaydi: {"savol", "jadval", "izoh"}."""
    if not isinstance(d, dict):
        raise ValueError("JSON obyekt emas")
    hisobot = SLOTLAR[slot]["rejim"] == "hisobot"
    jadval = []
    for r in d.get("jadval") or []:
        if isinstance(r, str):
            r = {"ish": r}
        if not isinstance(r, dict):
            continue
        ish = _toza(r.get("ish"), 300)
        if not ish:
            continue
        jadval.append({"ish": ish, "izoh": _toza(r.get("izoh"), 200),
                       "holat": holat_norm(r.get("holat")) if hisobot else ""})
    return {"savol": bool(d.get("savol")), "jadval": jadval[:MAX_QATOR],
            "izoh": _toza(d.get("izoh"), 300)}


def jadval_yangila(slot, joriy, kiritma, tur, reja=None, nomlar=None, sana=""):
    """Claude → yangilangan to'liq jadval. Xatoda exception (chaqiruvchi zaxiraga o'tadi)."""
    import analyze

    prompt = _prompt(SLOTLAR[slot]["rejim"], joriy, reja, nomlar or [], kiritma, tur, sana)
    raw = analyze.run_claude(prompt, effort="medium", timeout=CLAUDE_TIMEOUT)
    return tekshir(json_ol(raw), slot)


_BANDLASH_RE = re.compile(r"^\s*(?:[-•*▪▫·]+|\d{1,2}\s*[.)\-:])\s*")


def oddiy_bolish(matn):
    """Zaxira (Claude ishlamasa): qatorlar/raqamlar/«;» bo'yicha bandlarga bo'lish."""
    qismlar = []
    for q in re.split(r"\n+|;\s*", str(matn or "")):
        q = _BANDLASH_RE.sub("", q).strip()
        if q:
            qismlar.append(q[:300])
    return qismlar


def _zaxira_jadval(slot, joriy, reja, matn):
    """Claude ishlamaganda: joriy jadval (kechqurun bo'sh bo'lsa — reja, holati bo'sh) +
    xabardagi yangi bandlar. Tahrir buyruqlarini tushunmaydi — preview'da ogohlantiriladi."""
    hisobot = SLOTLAR[slot]["rejim"] == "hisobot"
    asos = [dict(r) for r in joriy] or ([{"ish": r.get("ish", ""), "izoh": r.get("izoh", ""),
                                          "holat": ""} for r in reja] if hisobot else [])
    bor = {r["ish"].lower() for r in asos}
    for q in oddiy_bolish(matn):
        if q.lower() not in bor:
            asos.append({"ish": q, "izoh": "", "holat": ""})
            bor.add(q.lower())
    return asos[:MAX_QATOR]


# ---------------- rasm va matnlar ----------------

def rasm_png(sana, slot, jadval, yangilangan=False):
    import wow_jadval

    ism = (sozlama().get("ism") or "").strip()
    ost = (f"{ism} · " if ism else "") + _sana_yorliq(sana)
    sarlavha = SLOTLAR[slot]["sarlavha"] + (" (yangilangan)" if yangilangan else "")
    return wow_jadval.chiz(sarlavha, ost, jadval, hisobot=(slot == "kechqurun"),
                           belgi=bot_nomi())


def boshliq_caption(sana, slot, jadval, yangilangan=False):
    """Boshliqqa ketadigan rasm izohi — oddiy matn (qidirsa va nusxalasa bo'lsin), ≤1024."""
    import wow_jadval

    bosh = f"{SLOTLAR[slot]['sarlavha']}{' (yangilangan)' if yangilangan else ''} — " \
           f"{_sana_yorliq(sana)}"
    if slot == "kechqurun":
        bosh += "\n" + wow_jadval.xulosa_matn(jadval, True)
    qatorlar = []
    for i, r in enumerate(jadval, 1):
        q = f"{i}. "
        if slot == "kechqurun":
            q += HOLAT_BELGI.get(r.get("holat") or "", "▫️") + " "
        q += r["ish"] + (f" ({r['izoh']})" if r.get("izoh") else "")
        qatorlar.append(q)
    matn = bosh + "\n\n" + "\n".join(qatorlar)
    if len(matn) <= 1000:
        return matn
    qism = bosh + "\n\n"
    for n, q in enumerate(qatorlar):
        oxiri = f"\n… yana {len(qatorlar) - n} ta — to'liq ro'yxat rasmda"
        if len(qism) + len(q) + 1 + len(oxiri) > 1000:
            return qism.rstrip("\n") + oxiri
        qism += q + "\n"
    return qism.rstrip("\n")


def _preview_caption(sana, slot, s, izoh="", ai_xato=None):
    jadval = s["jadval"]
    sz = sozlama()
    nom = SLOTLAR[slot]["sarlavha"]
    son = f"{len(jadval)} ta {'vazifa' if slot == 'ertalab' else 'band'}"
    L = [f"📋 <b>{nom} — qoralama</b> · {son}"]
    if izoh:
        L.append(f"ℹ️ {esc(izoh)}")
    if ai_xato:
        L.append("⚠️ AI hozir ishlamadi — xabar oddiy bo'lib qo'shildi. Tekshiring yoki "
                 "❌ bosib keyinroq qayta yozing.")
    if sz.get("boshliq"):
        L.append(f"Shu rasm {esc(_kimga())} ketadi.")
    else:
        L.append("⚠️ Qabul qiluvchi belgilanmagan: <code>/boshliq @username Ism</code> — "
                 "keyin ✅ bosing.")
    L.append("✏️ Tuzatish yoki qo'shish — shunchaki yozing yoki ovoz yuboring "
             "(«3-ni o'chir», «yana: …»).")
    daq = _avto_daq(sz)
    if daq and sz.get("boshliq"):
        L.append(f"⏳ {daq} daqiqa ichida o'zgarish bo'lmasa — avtomatik yuboriladi.")
    return "\n".join(L)


def _matn_jadval(jadval, slot):
    """Rasm yuborilmasa — zaxira: jadvalning matnli ko'rinishi (HTML)."""
    L = []
    for i, r in enumerate(jadval, 1):
        belgi = HOLAT_BELGI.get(r.get("holat") or "", "▫️") + " " if slot == "kechqurun" else ""
        L.append(f"{i}. {belgi}{esc(r['ish'])}" + (f" — <i>{esc(r['izoh'])}</i>"
                                                    if r.get("izoh") else ""))
    return "\n".join(L)


def preview_yubor(sana, slot, izoh="", ai_xato=None):
    """Joriy qoralamani rasm + tugmalar bilan egaga yuboradi; eski preview o'chiriladi."""
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        jadval = list(s["jadval"])
        eski = s.get("preview_mid")
        caption = _preview_caption(sana, slot, s, izoh, ai_xato)
        yangilangan = bool(s.get("yangilangan"))
    kb = _kb([("✅ Yuborish", f"wow:ok:{sana}:{slot}"), ("❌ Bekor", f"wow:bekor:{sana}:{slot}")])
    mid = None
    try:
        mid = rasm(rasm_png(sana, slot, jadval, yangilangan), caption, kb)
    except Exception as e:                              # noqa: BLE001
        log(f"preview rasmi chizilmadi: {type(e).__name__}: {str(e)[:150]}")
    if not mid:
        mid = xabar(_matn_jadval(jadval, slot) + "\n\n" + caption, kb)
    if mid:
        with _LOCK:
            st = yukla(sana)
            s = st[slot]
            s["preview_mid"] = mid
            s["xabarlar"] = (s["xabarlar"] + [mid])[-40:]
            saqla(st)
        if eski and eski != mid:
            ochir(eski)
    return mid


# ---------------- so'rov (ertalab / kechqurun) ----------------

def _sorov_matni(slot, st, n, soat_hozir=9):
    """n — shu slotda oldin yuborilgan so'rovlar soni (0 — birinchi savol matni)."""
    soat = SLOTLAR[slot]["soatlar"]
    oxirgi = n + 1 >= len(soat)
    if slot == "ertalab":
        if n == 0:
            salom = "☀️ <b>Xayrli tong!</b> " if soat_hozir < 12 else "📝 "
            return (f"{salom}Bugun qanday ishlar qilasiz?\n\n"
                    "Rejangizni ovozli xabar yoki matn bilan yozing — jadval qilib, "
                    f"{esc(_kimga())} yuboraman.")
        return (f"⏰ Bugungi reja hali yozilmadi{' (oxirgi eslatma)' if oxirgi else ''}. "
                "Ovoz yoki matn bilan yuboring.")
    reja = st["ertalab"]["jadval"]
    if n == 0:
        L = ["🌙 <b>Kun yakuni.</b> Bugun nimalar qildingiz?"]
        if reja:
            L.append("\nErtalabki rejangiz:")
            L += [f"{i}. {esc(r['ish'])}" for i, r in enumerate(reja, 1)]
            L.append("\nQaysilari bajarildi, qaysilari qoldi, yana nima qildingiz — "
                     "ovoz yoki matn bilan ayting.")
        else:
            L.append("\nQilgan ishlaringizni ovoz yoki matn bilan yozing.")
        return "\n".join(L)
    return (f"⏰ Bugungi hisobot hali yozilmadi{' (oxirgi eslatma)' if oxirgi else ''}. "
            "Nimalar qildingiz — ovoz yoki matn bilan yuboring.")


def sorov(slot, qolda=False, now=None):
    """So'rov yoki eslatma yuboradi. qolda=True — /ertalab, /kechqurun buyrug'i (soat va «dam»
    e'tiborsiz). Qaytadi: holat kodi (sent | off | done | qoralama | xato | send-fail)."""
    now = now or hozir()
    sana = now.date().isoformat()
    sz = sozlama()
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        if not qolda and (not _yoqilgan(sz) or st.get("dam")):
            return "off"
        if s["holat"] in ("yuborildi", "yuborilmoqda"):
            return "done"
        if s["holat"] in ("qoralama", "xato"):
            st["faol"] = slot
            saqla(st)
            holat = s["holat"]
        else:
            holat = None
            if qolda:
                st["dam"] = False
            if slot == "kechqurun" and st["ertalab"]["holat"] in ("yangi", "kutilmoqda"):
                st["ertalab"]["holat"] = "otkazildi"
            n = len(s["sorovlar"])
            matn = _sorov_matni(slot, st, 0 if qolda else n, now.hour)
            st["faol"] = slot
            s["holat"] = "kutilmoqda"
            s["pauza"] = False
            s["sorovlar"].append(now.strftime("%H:%M"))
            saqla(st)                      # yuborishdan OLDIN — javob darhol kelsa ham ushlansin
    if holat == "qoralama":
        if qolda:
            preview_yubor(sana, slot)
        else:
            xabar(f"📋 {SLOTLAR[slot]['sarlavha']} qoralamasi tayyor — ✅ bosing yoki tuzating.")
        return "qoralama"
    if holat == "xato":
        xabar(f"⚠️ {SLOTLAR[slot]['sarlavha']} {esc(_kimga())} yetib bormadi.",
              _kb([("🔁 Qayta urinish", f"wow:qayta:{sana}:{slot}")]))
        return "xato"
    tugma = [("⏭ Keyinroq", f"wow:keyin:{sana}:{slot}"), ("🏖 Bugun dam", f"wow:dam:{sana}:{slot}")]
    qator = [tugma]
    if slot == "kechqurun" and st["ertalab"]["jadval"]:
        qator.insert(0, [("✅ Rejadagi hammasi bajarildi", f"wow:hammasi:{sana}:{slot}")])
    mid = xabar(matn, _kb(*qator))
    if mid:
        with _LOCK:
            st = yukla(sana)
            st[slot]["xabarlar"] = (st[slot]["xabarlar"] + [mid])[-40:]
            saqla(st)
    log(f"so'rov: {slot} #{n + 1} ({'qo‘lda' if qolda else 'jadval'}) → {'ok' if mid else 'XATO'}")
    return "sent" if mid else "send-fail"


def sorov_job(slot):
    """Rejalovchi (har soatda): xato rejalovchini yiqitmasin."""
    try:
        return sorov(slot)
    except Exception as e:                              # noqa: BLE001
        log(f"XATO sorov_job({slot}): {type(e).__name__}: {e}")
        return "error"


# ---------------- xabarni qabul qilish ----------------

def ushlaydimi(msg, now=None):
    """Bu xabar kunlik reja/hisobot oqimiga tegishlimi? → slot nomi yoki None.
    Buyruqlar, rasm/hujjatlar — hech qachon. Matn/ovoz — so'rov yuborilib javob kutilayotganda
    («⏭ Keyinroq» bosilmagan bo'lsa), qoralama ochiq bo'lsa yoki so'rov/preview'ga reply bo'lsa."""
    text = (msg.get("text") or "").strip()
    if text.startswith("/"):
        return None
    if not (text or msg.get("voice") or msg.get("audio")):
        return None
    now = now or hozir()
    with _LOCK:
        st = yukla(now.date().isoformat())
    rep = (msg.get("reply_to_message") or {}).get("message_id")
    if rep:
        for slot in SLOTLAR:
            s = st[slot]
            if rep in s.get("xabarlar", []) and s["holat"] in ("kutilmoqda", "qoralama"):
                return slot
    slot = st.get("faol")
    if slot not in SLOTLAR or st.get("dam"):
        return None
    s = st[slot]
    if s["holat"] == "qoralama":
        return slot
    if s["holat"] == "kutilmoqda" and not s.get("pauza"):
        return slot
    return None


def _ovozdan_matn(v):
    """Ovoz → matn. (matn, status_mid) yoki None (sabab egaga aytilgan)."""
    import stt

    if int(v.get("duration") or 0) > VOICE_MAX_SEC:
        xabar(f"🎤 Ovozli xabar {VOICE_MAX_SEC // 60} daqiqadan oshmasin — bo'lib yuboring "
              "(har biri jadvalga qo'shiladi).")
        return None
    ok, why = stt.stt_ready()
    if not ok:
        log(f"STT tayyor emas: {why}")
        xabar("🎤 Ovozni matnga aylantirish hozir ishlamayapti — matn bilan yozing "
              "(holat: /stt_status).")
        return None
    mid = xabar("🎤 Eshityapman...")
    path = None
    try:
        import design

        token, _ = _tg()
        path = design.download(token, v["file_id"], "kunlik.ogg")
        matn = stt.transcribe(path)
    except Exception as e:                              # noqa: BLE001
        log(f"STT xato: {type(e).__name__}: {str(e)[:200]}")
        t = "🎤 Ovozni tushunib bo'lmadi — qayta yuboring yoki matn bilan yozing."
        if not (mid and matn_tahrir(mid, t)):
            xabar(t)
        return None
    finally:
        if path:
            Path(path).unlink(missing_ok=True)
    if not matn:
        t = "🎤 Hech narsa eshitilmadi — aniqroq qayta yozib ko'ring yoki matn yozing."
        if not (mid and matn_tahrir(mid, t)):
            xabar(t)
        return None
    t = f"🎤 Eshitdim: «{esc(matn)}»"
    if not (mid and matn_tahrir(mid, t)):
        mid = xabar(t)
    return matn, mid


def xabarni_ishlash(msg, slot, now=None):
    """Kunlik oqimdagi matn/ovoz → jadval → preview. Qaytadi: (natija, matn):
    "ok" | "savol" (odatiy Q&A'ga) | "bosh" (ish topilmadi) | "xato" (ovoz o'qilmadi)."""
    now = now or hozir()
    sana = now.date().isoformat()
    _ismni_eslab(msg)
    v = msg.get("voice") or msg.get("audio")
    if v:
        r = _ovozdan_matn(v)
        if not r:
            return "xato", ""
        matn, tur = r[0], "ovoz"
    else:
        matn, tur = (msg.get("text") or "").strip(), "matn"
    # Claude 10–90 s o'ylashi mumkin — egasi bot ishlayotganini ko'rib tursin; preview kelgach
    # (yoki savol/xato bo'lsa) bu xabar o'chiriladi
    jarayon_mid = xabar("✍️ Jadval tuzyapman…")
    try:
        return _jadvalga(sana, slot, matn, tur, now)
    finally:
        if jarayon_mid:
            ochir(jarayon_mid)


def _jadvalga(sana, slot, matn, tur, now):
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        s["ishlanmoqda"] = hozir().isoformat(timespec="seconds")
        s["oxirgi"] = s["ishlanmoqda"]
        joriy = [dict(r) for r in s["jadval"]]
        reja = [dict(r) for r in st["ertalab"]["jadval"]] if slot == "kechqurun" else []
        saqla(st)
    ai_xato = None
    try:
        natija = jadval_yangila(slot, joriy, matn, tur, reja, malum_nomlar(), sana)
    except Exception as e:                              # noqa: BLE001
        ai_xato = f"{type(e).__name__}: {str(e)[:160]}"
        log(f"AI jadval xatosi — zaxira bo'lish: {ai_xato}")
        natija = {"savol": False, "jadval": _zaxira_jadval(slot, joriy, reja, matn), "izoh": ""}
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        s["ishlanmoqda"] = None
        if natija["savol"] or not natija["jadval"]:
            saqla(st)
            if natija["savol"]:
                log(f"{slot}: xabar savol deb topildi — Q&A'ga")
                return "savol", matn
            xabar("Bu xabardan ish topilmadi — ishlaringizni sanab yozing yoki ovoz yuboring.")
            return "bosh", matn
        if s["holat"] in ("yuborildi", "yuborilmoqda"):
            saqla(st)
            xabar(f"{SLOTLAR[slot]['sarlavha']} allaqachon yuborilgan. Yangilangan versiya: "
                  f"/{slot} qayta")
            return "ok", matn
        s["jadval"] = natija["jadval"]
        s["kirishlar"] = (s["kirishlar"] + [{"vaqt": now.strftime("%H:%M"), "tur": tur,
                                             "matn": matn[:2000]}])[-20:]
        s["holat"] = "qoralama"
        s["oxirgi"] = hozir().isoformat(timespec="seconds")   # avto-yuborish sanog'i shundan
        st["faol"] = slot
        saqla(st)
    preview_yubor(sana, slot, natija.get("izoh") or "", ai_xato)
    log(f"{slot}: qoralama yangilandi ({len(natija['jadval'])} qator, {tur}"
        f"{', AI zaxira' if ai_xato else ''})")
    return "ok", matn


# ---------------- boshliqqa yuborish ----------------

def _arxiv(sana, slot, jadval):
    """Obsidian chat arxiviga bitta qator (best-effort) — ikkinchi miyaga ham tushsin."""
    try:
        import chat_log

        bandlar = "; ".join(
            (f"{HOLAT_BELGI.get(r.get('holat') or '', '')} " if slot == "kechqurun" else "")
            + r["ish"] for r in jadval)
        chat_log.append_cmd(f"WOW {SLOTLAR[slot]['sarlavha'].lower()} ({sana}) yuborildi: "
                            f"{bandlar}"[:1500])
    except Exception:                                   # noqa: BLE001
        pass


def yubor(sana, slot, sabab="qo'lda"):
    """Qoralamani egasining akkauntidan boshliqqa yuboradi. Ikki marta yuborilmaydi:
    holat lock ostida «yuborilmoqda»ga o'tadi. Qaytadi: yuborildi | xato | boshliq-yoq |
    limit | bosh | <boshqa holat>."""
    boshliq = (sozlama().get("boshliq") or "").strip()
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        if s["holat"] not in ("qoralama", "xato"):
            return s["holat"]
        if not s["jadval"]:
            return "bosh"
        if not boshliq:
            return "boshliq-yoq"
        if s["yuborish_soni"] >= MAX_YUBORISH:
            return "limit"
        s["holat"] = "yuborilmoqda"
        s["yuborish_soni"] += 1
        jadval = [dict(r) for r in s["jadval"]]
        preview_mid = s.get("preview_mid")
        yangilangan = bool(s.get("yangilangan"))
        saqla(st)
    xato = None
    png = None
    try:
        png = rasm_png(sana, slot, jadval, yangilangan)
        import userbot_sender

        with tempfile.TemporaryDirectory(prefix="wow-") as td:
            p = Path(td) / f"{'reja' if slot == 'ertalab' else 'hisobot'}-{sana}.png"
            p.write_bytes(png)
            userbot_sender.send_photo(boshliq, p, boshliq_caption(sana, slot, jadval, yangilangan))
    except Exception as e:                              # noqa: BLE001
        xato = f"{type(e).__name__}: {str(e)[:200]}"
    vaqt = hozir().strftime("%H:%M")
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        if xato:
            s["holat"], s["xato"] = "xato", xato
        else:
            s["holat"], s["yuborildi"], s["xato"] = "yuborildi", vaqt, None
            if st.get("faol") == slot:
                st["faol"] = None
        saqla(st)
    kimga = _kimga()
    if xato:
        log(f"{slot}: boshliqqa yuborilmadi ({sabab}): {xato}")
        kb = _kb([("🔁 Qayta urinish", f"wow:qayta:{sana}:{slot}")])
        t = (f"⚠️ <b>{esc(_bosh_harf(kimga))} yuborilmadi</b>: {esc(xato)}\n"
             "Rasmni o'zingiz forward qiling yoki qayta urinib ko'ring.")
        if not (png and rasm(png, t, kb)):
            xabar(t, kb)
        tahrir(preview_mid, "⚠️ Yuborilmadi — pastdagi xabarga qarang.")
        return "xato"
    log(f"{slot}: boshliqqa yuborildi ({sabab}, {len(jadval)} qator)")
    t = f"✅ <b>{esc(_bosh_harf(kimga))} yuborildi</b> · {vaqt}" + \
        (" (avtomatik)" if sabab == "avto" else "")
    if not tahrir(preview_mid, t):
        xabar(t)
    _arxiv(sana, slot, jadval)
    return "yuborildi"


def avto_job(now=None):
    """Har daqiqada: AVTO_DAQ daqiqa jim turgan qoralamani yuboradi (bugungi va kechagi —
    kechki qoralama yarim tundan o'tib qolsa ham)."""
    try:
        now = now or hozir()
        sz = sozlama()
        daq = _avto_daq(sz)
        if not daq or not sz.get("boshliq") or not _yoqilgan(sz):
            return []
        yuborildi = []
        for kun in (now.date().isoformat(), (now.date() - timedelta(days=1)).isoformat()):
            if not _kun_fayl(kun).exists():
                continue
            with _LOCK:
                st = yukla(kun)
            for slot in SLOTLAR:
                s = st[slot]
                if s["holat"] != "qoralama":
                    continue
                ish = _vaqt(s.get("ishlanmoqda"))
                if ish and (now - ish).total_seconds() < ISHLANMOQDA_ESKI:
                    continue                        # yangi xabar ishlanyapti — kutamiz
                oxirgi = _vaqt(s.get("oxirgi"))
                if oxirgi and now - oxirgi >= timedelta(minutes=daq):
                    yuborildi.append((kun, slot, yubor(kun, slot, sabab="avto")))
        return yuborildi
    except Exception as e:                              # noqa: BLE001
        log(f"XATO avto_job: {type(e).__name__}: {e}")
        return []


def boot(now=None):
    """Supervisor startup'da bir marta: uzilib qolgan «yuborilmoqda» → «xato» (qayta urinish
    tugmasi bilan), bugungi so'rov restart/deploy tufayli o'tib ketgan bo'lsa — hozir so'rash."""
    try:
        now = now or hozir()
        sana = now.date().isoformat()
        with _LOCK:
            st = yukla(sana)
            ozgardi = False
            for slot in SLOTLAR:
                if st[slot]["holat"] == "yuborilmoqda":
                    st[slot]["holat"], st[slot]["xato"] = "xato", "yuborish jarayoni uzildi (restart)"
                    ozgardi = True
            if ozgardi:
                saqla(st)
        if not _yoqilgan() or st.get("dam"):
            return None
        for slot, cfg in SLOTLAR.items():
            if cfg["soatlar"][0] <= now.hour <= cfg["soatlar"][-1] and st[slot]["holat"] == "yangi":
                log(f"boot catch-up: {slot} so'rovi o'tib ketgan — hozir so'rayman")
                return sorov(slot, now=now)
        return None
    except Exception as e:                              # noqa: BLE001
        log(f"XATO wow boot: {type(e).__name__}: {e}")
        return None


# ---------------- inline tugmalar ----------------

def callback(cq):
    """«wow:<amal>:<sana>:<slot>» tugmalari. Qaytadi: natija satri yoki None (bizniki emas).
    Yuboruvchi (egasi) tekshiruvi — bot_listener'da."""
    data = str(cq.get("data") or "")
    if not data.startswith("wow:"):
        return None
    qism = data.split(":")
    amal = qism[1] if len(qism) > 1 else ""
    sana = qism[2] if len(qism) > 2 else ""
    slot = qism[3] if len(qism) > 3 else ""
    cid = cq.get("id")
    mid = (cq.get("message") or {}).get("message_id")
    if not _SANA_RE.match(sana) or slot not in SLOTLAR:
        javob_cb(cid, "Eskirgan tugma")
        return "wow-cb-yaroqsiz"
    bugun = hozir().date().isoformat()
    if amal in ("ok", "qayta"):
        javob_cb(cid, "Yuborilmoqda…")
        r = yubor(sana, slot)
        if r == "boshliq-yoq":
            xabar("⚠️ Avval qabul qiluvchini belgilang: <code>/boshliq @username Ism</code>\n"
                  "Sinash uchun o'zingizga: <code>/boshliq me</code>")
        elif r == "limit":
            xabar(f"⚠️ Bugun bu jadval {MAX_YUBORISH} marta yuborishga urinildi — limit. "
                  "Rasmni qo'lda forward qiling.")
        elif r == "yuborildi" and amal == "ok":
            pass
        elif r not in ("yuborildi", "xato"):
            xabar(f"ℹ️ Bu jadval hozir yuborib bo'lmaydi (holat: {esc(r)}).")
        return f"wow-{amal}-{r}"
    if amal == "bekor":
        with _LOCK:
            st = yukla(sana)
            s = st[slot]
            ok = s["holat"] in ("qoralama", "xato") and sana == bugun
            if ok:
                s.update(jadval=[], kirishlar=[], holat="kutilmoqda", pauza=False,
                         preview_mid=None, yangilangan=False)
                st["faol"] = slot
                saqla(st)
        if not ok:
            javob_cb(cid, "Bu qoralama endi o'zgartirilmaydi")
            return "wow-bekor-otkazildi"
        javob_cb(cid, "Qoralama o'chirildi")
        tahrir(mid, "❌ Bekor qilindi. Qaytadan yozing yoki ovoz yuboring.")
        return "wow-bekor"
    if amal == "keyin":
        with _LOCK:
            st = yukla(sana)
            if st[slot]["holat"] == "kutilmoqda":
                st[slot]["pauza"] = True
                saqla(st)
        javob_cb(cid, "Mayli — keyingi eslatmagacha jim turaman")
        if mid:
            tugmalarni_olib_tashla(mid)
        return "wow-keyin"
    if amal == "dam":
        with _LOCK:
            st = yukla(sana)
            st["dam"] = True
            for sl in SLOTLAR:
                if st[sl]["holat"] in ("yangi", "kutilmoqda"):
                    st[sl]["holat"] = "dam"
            st["faol"] = None
            saqla(st)
        javob_cb(cid, "Yaxshi dam oling! Bugun boshqa so'ramayman")
        if mid:
            tugmalarni_olib_tashla(mid)
        return "wow-dam"
    if amal == "hammasi":
        with _LOCK:
            st = yukla(sana)
            reja, s = st["ertalab"]["jadval"], st["kechqurun"]
            ok = bool(reja) and slot == "kechqurun" and s["holat"] in ("kutilmoqda", "qoralama")
            if ok:
                s["jadval"] = [{"ish": r["ish"], "izoh": r.get("izoh", ""), "holat": "bajarildi"}
                               for r in reja]
                s["holat"] = "qoralama"
                s["oxirgi"] = hozir().isoformat(timespec="seconds")
                st["faol"] = "kechqurun"
                saqla(st)
        if not ok:
            javob_cb(cid, "Eskirgan tugma")
            return "wow-hammasi-otkazildi"
        javob_cb(cid, "Jadval tayyor — tekshirib ✅ bosing")
        if mid:
            tugmalarni_olib_tashla(mid)
        preview_yubor(sana, "kechqurun")
        return "wow-hammasi"
    javob_cb(cid)
    return "wow-cb-noma'lum"


# ---------------- buyruqlar ----------------

_HOLAT_MATN = {
    "kutilmoqda": "❓ javob kutilmoqda",
    "qoralama": "📝 qoralama tayyor — ✅ bosing",
    "yuborilmoqda": "📤 yuborilmoqda…",
    "otkazildi": "— javob berilmadi",
    "dam": "🏖 dam",
}


def _slot_holat_matn(slot, s, now):
    h = s["holat"]
    soat = SLOTLAR[slot]["soatlar"]
    if h == "yangi":
        return f"⏳ {soat[0]:02d}:00 da so'rayman" if now.hour < soat[0] else "— so'ralmagan"
    if h == "yuborildi":
        return f"✅ yuborildi {s.get('yuborildi') or ''} · {len(s['jadval'])} qator"
    if h == "xato":
        return f"⚠️ yuborilmadi: {esc((s.get('xato') or '')[:120])}"
    t = _HOLAT_MATN.get(h, h)
    if h == "kutilmoqda" and s["sorovlar"]:
        t += f" (so'raldi: {', '.join(s['sorovlar'])}{'; ⏭ keyinroq' if s.get('pauza') else ''})"
    if h == "qoralama":
        t += f" ({len(s['jadval'])} qator)"
    return t


def holat_matni(now=None):
    now = now or hozir()
    sana = now.date().isoformat()
    sz = sozlama()
    st = yukla(sana)
    bosh = sz.get("boshliq")
    nomi = sz.get("boshliq_nomi") or ""
    daq = _avto_daq(sz)
    L = [f"🗓 <b>{esc(bot_nomi())} — kunlik reja va hisobot</b>",
         f"Bugun: {_sana_yorliq(sana)}" + (" · 🏖 dam" if st.get("dam") else ""),
         f"• Ertalab (09–12, har soat): {_slot_holat_matn('ertalab', st['ertalab'], now)}",
         f"• Kechqurun (19–21, har soat): {_slot_holat_matn('kechqurun', st['kechqurun'], now)}",
         "",
         "Qabul qiluvchi: " + (f"{esc(nomi) + ' · ' if nomi else ''}<code>{esc(bosh)}</code> — "
                               "sizning akkauntingizdan, lichkaga" if bosh else
                               "⚠️ belgilanmagan — <code>/boshliq @username Ism</code>"),
         "Avto-yuborish: " + (f"qoralama {daq} daqiqa jim tursa" if daq else "o'chiq (faqat ✅)"),
         "Holat: " + ("yoqilgan ✅" if _yoqilgan(sz) else "o'chiq (/kunlik on)"),
         "",
         "Buyruqlar:",
         "/ertalab — rejani hozir yozish · /kechqurun — hisobotni hozir yozish",
         "/ertalab qayta · /kechqurun qayta — yuborilganini yangilab qayta yuborish",
         "/dam — bugun so'ramaslik",
         "/boshliq @username Ism — qabul qiluvchi (sinov: <code>/boshliq me</code>)",
         "/kunlik avto 15 | avto off · /kunlik off | on"]
    return "\n".join(L)


def _qayta_ochish(slot, now):
    """Yuborilgan jadvalni qayta ochadi (tahrir → «yangilangan» bo'lib qayta yuboriladi)."""
    sana = now.date().isoformat()
    with _LOCK:
        st = yukla(sana)
        s = st[slot]
        if s["holat"] != "yuborildi" or not s["jadval"]:
            return False
        s.update(holat="qoralama", yangilangan=True, yuborish_soni=0,
                 oxirgi=hozir().isoformat(timespec="seconds"))
        st["faol"] = slot
        saqla(st)
    preview_yubor(sana, slot)
    return True


def buyruq(text, msg=None, now=None):
    """WOW kunlik buyruqlari. Bizniki bo'lmasa — None; aks holda natija kodi (javob yuborilgan)."""
    parts = str(text or "").strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().split("@")[0]
    if cmd not in BUYRUQLAR:
        return None
    args = parts[1:]
    now = now or hozir()
    if msg:
        _ismni_eslab(msg)
    if cmd == "/boshliq":
        if not args:
            sz = sozlama()
            xabar("Qabul qiluvchi: " + (f"{esc(sz.get('boshliq_nomi') or '')} "
                                       f"<code>{esc(sz['boshliq'])}</code>" if sz.get("boshliq")
                                       else "belgilanmagan")
                  + "\nO'rnatish: <code>/boshliq @username Ism</code> (masalan, "
                    "<code>/boshliq @username Anvar aka</code>). Sinov: <code>/boshliq me</code>")
            return "wow-boshliq-korsat"
        kontakt = args[0] if args[0].lower() != "me" else "me"
        if not _KONTAKT_RE.match(kontakt):
            xabar("⚠️ Format: <code>/boshliq @username Ism</code> yoki <code>/boshliq +998…</code>"
                  " (sinov uchun <code>/boshliq me</code> — Saved Messages)")
            return "wow-boshliq-xato"
        nomi = " ".join(args[1:]).strip()[:40] or ("Saved Messages" if kontakt == "me" else "")
        sozlama_saqla(boshliq=kontakt, boshliq_nomi=nomi)
        # Ochiq qoralamalar: avto-yuborish sanog'i shu daqiqadan qayta boshlanadi — qabul qiluvchi
        # endi belgilangani uchun eski qoralama tekshiruvsiz darhol ketib qolmasin
        ochiq = 0
        with _LOCK:
            st = yukla(now.date().isoformat())
            for sl in SLOTLAR:
                if st[sl]["holat"] == "qoralama":
                    st[sl]["oxirgi"] = hozir().isoformat(timespec="seconds")
                    ochiq += 1
            if ochiq:
                saqla(st)
        t = (f"✅ Qabul qiluvchi: {esc(nomi) + ' · ' if nomi else ''}<code>{esc(kontakt)}</code>\n"
             "✅ bosilganda (yoki avto-yuborishda) jadval sizning akkauntingizdan unga lichkada ketadi.")
        daq = _avto_daq()
        if ochiq and daq:
            t += f"\n⏳ Ochiq qoralama ✅ bosilmasa {daq} daqiqadan keyin avtomatik ketadi."
        try:
            import userbot_sender

            ok, why = userbot_sender.available()
            if not ok:
                t += f"\n⚠️ Userbot hozir tayyor emas: {esc(why)} — yuborishda xato beradi."
        except Exception:                               # noqa: BLE001
            pass
        xabar(t)
        return "wow-boshliq"
    if cmd == "/kunlik":
        a = [x.lower() for x in args]
        if a[:1] == ["avto"]:
            v = a[1] if len(a) > 1 else ""
            if v in ("off", "0", "ochir", "o'chir"):
                sozlama_saqla(avto_daq=0)
                xabar("⏳ Avto-yuborish o'chirildi — jadval faqat ✅ bosilganda ketadi.")
            elif v.isdigit() and 1 <= int(v) <= 240:
                sozlama_saqla(avto_daq=int(v))
                xabar(f"⏳ Avto-yuborish: qoralama {int(v)} daqiqa jim tursa.")
            else:
                xabar("Format: <code>/kunlik avto 15</code> (1–240 daqiqa) yoki "
                      "<code>/kunlik avto off</code>")
            return "wow-avto"
        if a[:1] in (["on"], ["off"]):
            sozlama_saqla(yoqilgan=(a[0] == "on"))
            xabar("✅ Kunlik so'rovlar yoqildi." if a[0] == "on" else
                  "⏸ Kunlik so'rovlar o'chirildi (qo'lda: /ertalab, /kechqurun ishlaydi).")
            return "wow-yoqish"
        if a[:1] == ["ism"] and len(args) > 1:
            sozlama_saqla(ism=" ".join(args[1:])[:60])
            xabar(f"✅ Jadval sarlavhasidagi ism: {esc(' '.join(args[1:])[:60])}")
            return "wow-ism"
        xabar(holat_matni(now))
        return "wow-holat"
    if cmd == "/dam":
        sana = now.date().isoformat()
        with _LOCK:
            st = yukla(sana)
            st["dam"] = True
            for sl in SLOTLAR:
                if st[sl]["holat"] in ("yangi", "kutilmoqda"):
                    st[sl]["holat"] = "dam"
            st["faol"] = None
            saqla(st)
        xabar("🏖 Bugun so'ramayman. Yaxshi dam oling! (Qo'lda: /ertalab, /kechqurun)")
        return "wow-dam"
    slot = "ertalab" if cmd == "/ertalab" else "kechqurun"
    if args[:1] and args[0].lower() == "qayta":
        if _qayta_ochish(slot, now):
            return f"wow-{slot}-qayta"
        xabar(f"ℹ️ Bugungi {SLOTLAR[slot]['sarlavha'].lower()} hali yuborilmagan — "
              f"/{slot} bilan yozing.")
        return f"wow-{slot}-qayta-yoq"
    with _LOCK:
        st = yukla(now.date().isoformat())
        if st[slot]["holat"] in ("dam", "otkazildi"):
            st[slot]["holat"] = "yangi"         # qo'lda qayta boshlash
            saqla(st)
    r = sorov(slot, qolda=True, now=now)
    if r == "done":
        s = yukla(now.date().isoformat())[slot]
        xabar(f"✅ Bugungi {SLOTLAR[slot]['sarlavha'].lower()} {s.get('yuborildi') or ''} da "
              f"yuborilgan. Yangilash: /{slot} qayta")
    return f"wow-{slot}-{r}"
