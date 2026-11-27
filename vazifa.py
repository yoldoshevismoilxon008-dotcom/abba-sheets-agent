#!/usr/bin/env python3
"""Vazifa navbati — egasining «keyin qilaman» ishlari va savollari (27.11.2026).

Oqim:
  • Qo'shish: «/vazifa <matn>», yoki «/vazifa» → keyingi matn/ovoz (KUTISH_DAQ daqiqa), yoki
    istalgan xabarga «/vazifa» bilan reply (matn, caption, «🎤 Eshitdim: «…»», ovozli xabar yoki
    belgilangan iqtibos). Bitta xabardagi bir nechta ish Claude bilan alohida bandlarga ajraladi
    (FAQAT obuna — analyze.run_claude, effort low); Claude ishlamasa (yoki limit tugasa) —
    qatorlar bo'yicha oddiy bo'lish (⚠️ bilan).
  • So'rash: ertalabki reja so'rovi yuborilgach (wow_kunlik.sorov) — kuniga bir marta, ko'pi
    bilan KUNIGA ta ish, har biri alohida xabar: «Buni ham bugun qilasizmi?» [✅ Ha] [⏳ Keyinroq].
  • ✅ Ha — ish bugungi ertalabki rejaga qo'shiladi va reja odatdagidek boshliqqa ketadi:
      – qoralama ochiq bo'lsa — darhol qator bo'lib (yangi preview; avto-yuborish faqat egasi shu
        preview'ni ko'rgandan keyin — wow_kunlik «korildi» izi);
      – reja hali yozilmagan bo'lsa — egasi rejasini yozganda (xabardan reja chiqsa) qo'shiladi;
      – reja yuborilgan bo'lsa — FAQAT «🔁 Rejaga qo'shib qayta yuborish» tugmasi bilan
        («yangilangan» qoralama; o'zicha qayta yuborilmaydi; kechki so'rov boshlangan bo'lsa —
        qayta ochilmaydi, ish kechki hisobotga qo'shiladi).
  • ⏳ Keyinroq — navbatda qoladi, keyingi kunlarda yana so'raladi.
  • Kechki hisobot yuborilgach: «bajarildi» bo'lgani yopiladi, qolgani navbatga qaytadi; hisobot
    tuzatilib qayta yuborilsa yoki kech yuborilsa — qayta solishtiriladi (olingan kuni bo'yicha).
    Kechki hisobot bo'lmagan kun — ertasi navbatga qaytadi.
  • «/vazifalar» — ro'yxat (sahifalab): ✅ bajarildi · 🗑 o'chirish · ❓ hozir so'rash.

Holat: DATA/wow_kunlik/vazifalar.json (volume). Repo PUBLIC — ish matnlari faqat volume'da.
Qulf: wow_kunlik._LOCK — navbat va kun fayli birga o'zgaradi (bitta RLock — lock tartibi
muammosi yo'q). Qulf ostida Telegram/Claude chaqirilmaydi.
Tugmalar: «vz:<amal>:<id>[:<sahifa>]» (bot_listener.handle_callback → callback).
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

import kalitlar  # noqa: E402
import wow_kunlik as wk  # noqa: E402
from maxfiy import redact  # noqa: E402

PROMPT = BASE / "prompts" / "vazifa-ajrat.md"
BUYRUQLAR = ("/vazifa", "/vazifalar")
KUNIGA = 5               # ertalab ko'pi bilan shuncha ish so'raladi (qolgani keyingi kunlarga)
KUTISH_DAQ = 10          # «/vazifa» dan keyin keyingi xabar shuncha daqiqa kutiladi
MAX_BAND = 20            # bitta xabardan ko'pi bilan shuncha band
MAX_OCHIQ = 200          # navbatdagi ochiq ishlar chegarasi
MAX_YOPIQ = 300          # tarix (bajarildi/o'chirildi) — eng yangilari saqlanadi
SAHIFA = 8               # /vazifalar: bir sahifadagi tugmali bandlar
CLAUDE_TIMEOUT = 90      # s — effort low, qisqa matn; osilsa poll loop'ni uzoq bloklamasin
KORSAT_BELGI = 3000      # tasdiq xabaridagi ro'yxat chegarasi (Telegram matni ≤ 4096)
OCHIQ = ("navbatda", "bugun")
UZUN_OVOZ = "har qismini alohida /vazifa bilan yuboring"
_HOLAT_SOZ = {"dam": "bugun dam kuni", "otkazildi": "ertalabki reja o'tkazib yuborilgan"}


def log(msg):
    print(f"[vazifa] {redact(msg)}", flush=True)


# ---------------- holat (vazifalar.json) ----------------

def _fayl():
    return wk.DIR / "vazifalar.json"          # chaqiruv paytida — testlar DIR'ni almashtiradi


def _bosh(keyingi_id=1):
    return {"versiya": 1, "keyingi_id": keyingi_id, "sorov_kuni": None, "kutish": None,
            "items": []}


def _yukla():
    """Navbat (wow_kunlik._LOCK ICHIDA chaqiriladi). Fayl yo'q — bo'sh navbat. Buzuq JSON —
    chetga olinadi (o'chirilmaydi), yangi navbat ogohlantirish bilan DARHOL diskka yoziladi."""
    p = _fayl()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("items"), list):
            raise ValueError("tuzilma noto'g'ri")
    except FileNotFoundError:
        return _bosh()
    except ValueError as e:
        return _buzuqdan_tikla(p, e)
    for k, v in _bosh().items():
        d.setdefault(k, v)
    d["items"] = [it for it in d["items"] if isinstance(it, dict) and isinstance(it.get("id"), int)]
    return d


def _buzuqdan_tikla(p, sabab):
    vaqt = wk.hozir()
    zaxira = p.with_name(f"{p.name}.buzuq-{vaqt.strftime('%Y%m%d-%H%M%S')}")
    p.replace(zaxira)                       # OSError — yuqoriga: buzuq fayl jim ustidan yozilmasin
    # eski xabarlardagi tugmalar (vz:<amal>:<id>) yangi ishlarga tegmasin — id'lar oldingi
    # oraliqdan katta (vaqt belgisi)
    d = _bosh(keyingi_id=int(vaqt.timestamp()))
    d["ogoh"] = (f"⚠️ Vazifalar fayli buzilgan edi — nusxasi saqlandi "
                 f"(<code>{wk.esc(zaxira.name)}</code>), navbat yangidan boshlandi.")
    _saqla(d)                               # ogohlantirish diskda — restart'da yo'qolmaydi
    log(f"XATO: vazifalar.json buzuq ({sabab}) — chetga olindi: {zaxira.name}")
    return d


def _saqla(d):
    """Atomik yozuv: vaqtinchalik fayl + fsync + os.replace (yarim yozilgan fayl qolmaydi)."""
    ochiq = [it for it in d["items"] if it.get("holat") in OCHIQ]
    yopiq = sorted((it for it in d["items"] if it.get("holat") not in OCHIQ),
                   key=lambda it: it.get("yopildi") or "", reverse=True)[:MAX_YOPIQ]
    d["items"] = sorted(ochiq + yopiq, key=lambda it: it["id"])
    p = _fayl()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ogoh_bilan(html):
    """Diskdagi ogohlantirish (buzuq fayl) bo'lsa — javob boshiga, bir marta."""
    with wk._LOCK:
        d = _yukla()
        og = d.pop("ogoh", None)
        if og:
            _saqla(d)
    if not og:
        return html
    return f"{og}\n\n{html}" if html else og


def _top(d, iid):
    for it in d["items"]:
        if it.get("id") == iid:
            return it
    return None


def _yangi(d, matn, tur, manba, src, toplam, now):
    i = int(d.get("keyingi_id") or 1)
    d["keyingi_id"] = i + 1
    return {"id": i, "matn": matn, "tur": tur, "holat": "navbatda", "manba": manba, "src": src,
            "toplam": toplam or i, "qoshildi": now.isoformat(timespec="seconds"),
            "keyin_soni": 0, "keyin_kuni": None, "soraldi": None, "sorov_mid": None,
            "sana": None, "olingan": None, "kechki": None, "yopildi": None}


def _bugungilar(d, sana):
    return [it for it in d["items"] if it.get("holat") == "bugun" and it.get("sana") == sana]


def _kechki_ochiqmi(sana):
    try:
        return wk.yukla(sana)["kechqurun"]["holat"] in ("qoralama", "xato", "yuborilmoqda")
    except Exception:                                   # noqa: BLE001
        return False


def _tikla(d, bugun):
    """O'tgan kunda «bugun» qilingan, lekin kechki hisobotda yopilmagan ishlar → navbatga.
    Kechagi kechki hisobot hali yuborilmagan (qoralama/xato) bo'lsa — o'sha ishlar kutadi:
    kech yuborilsa ham shu hisobot bilan yopiladi. Qaytadi: qaytgan ishlar soni."""
    kecha = (date.fromisoformat(bugun) - timedelta(days=1)).isoformat()
    n = 0
    for it in d["items"]:
        s = it.get("sana") or ""
        if it.get("holat") != "bugun" or s >= bugun:
            continue
        if s == kecha and _kechki_ochiqmi(s):
            continue
        it.update(holat="navbatda", sana=None)
        it["keyin_soni"] = int(it.get("keyin_soni") or 0) + 1
        n += 1
    return n


def _yukla_tik(sana):
    """(lock ichida) navbat + eskirgan «bugun»larni qaytarish (o'zgarsa — saqlanadi)."""
    d = _yukla()
    if _tikla(d, sana):
        _saqla(d)
    return d


def _yosh(iso, now):
    t = wk._vaqt(iso)
    if not t:
        return ""
    kun = (now.date() - t.date()).days
    if kun <= 0:
        return "bugun qo'shilgan"
    if kun == 1:
        return "kecha qo'shilgan"
    return f"{kun} kun oldin qo'shilgan"


def _qisqa(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _src(msg):
    """Xabar kaliti (chat:message_id) — restart'dagi qayta ishlov (recover_inflight) ikki marta
    qo'shmasin va «/vazifa» kutishi qayta ishlovda ham shu xabarni tanisin."""
    mid = (msg or {}).get("message_id")
    if mid is None:
        return None
    return f"{((msg or {}).get('chat') or {}).get('id')}:{mid}"


_ESHITDIM_RE = re.compile(r"^\s*🎤\s*Eshitdim:\s*«(.*)»\s*$", re.S)


def _reply_manbasi(msg):
    """«/vazifa» reply bo'lsa — (matn, manba, ovoz): belgilangan iqtibos → reply matni yoki
    caption («🎤 Eshitdim: «…»» o'ramisiz) → reply qilingan ovozli xabar (ovoz obyekti)."""
    q = str(((msg or {}).get("quote") or {}).get("text") or "").strip()
    if q:
        return q, "matn", None
    rep = (msg or {}).get("reply_to_message") or {}
    t = (rep.get("text") or rep.get("caption") or "").strip()
    m = _ESHITDIM_RE.match(t)
    if m:
        return m.group(1).strip(), "ovoz", None
    if t:
        return t, "matn", None
    return "", "ovoz", (rep.get("voice") or rep.get("audio") or None)


def _mos_qator(matn, jadval):
    """Jadvaldagi shu ishning qatori: avval aynan (normallashgan) teng, keyin YAGONA o'xshash.
    Bir nechta o'xshash (yoki teng, lekin holati har xil) bo'lsa — None: shubhada yopilmaydi."""
    n = wk._norm_matn(matn)
    aniq = [r for r in jadval or [] if wk._norm_matn(r.get("ish")) == n]
    if aniq:
        return aniq[0] if len({r.get("holat") for r in aniq}) == 1 else None
    oxshash = [r for r in jadval or [] if wk.matn_oxshash(matn, r.get("ish", ""))]
    return oxshash[0] if len(oxshash) == 1 else None


# ---------------- Claude: xabarni bandlarga ajratish (faqat obuna) ----------------

def _prompt(matn, manba):
    qiymat = {
        "NOMLAR": ", ".join(wk.malum_nomlar()) or "(yo'q)",
        "KALITLAR": kalitlar.prompt_matni(),
        "TUR": "ovozli xabar transkripti" if manba == "ovoz" else "matn",
        "KIRITMA": matn,
    }
    shablon = PROMPT.read_text(encoding="utf-8")
    # bir o'tishda: foydalanuvchi matnidagi «{{...}}» qayta almashtirilmaydi
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: qiymat.get(m.group(1), m.group(0)), shablon)


def _claude(prompt):
    import analyze

    return analyze.run_claude(prompt, effort="low", timeout=CLAUDE_TIMEOUT)


def tekshir(d):
    """Claude JSON'i → [{"matn", "tur"}] (tur: ish | savol)."""
    if not isinstance(d, dict):
        raise ValueError("JSON obyekt emas")
    out = []
    for b in d.get("bandlar") or []:
        if isinstance(b, str):
            b = {"matn": b}
        if not isinstance(b, dict):
            continue
        m = wk._toza(b.get("matn"), 300)
        if not m:
            continue
        tur = "savol" if str(b.get("tur") or "").strip().lower() == "savol" else "ish"
        out.append({"matn": m, "tur": tur})
    return out[:MAX_BAND]


def ajrat(matn, manba="matn"):
    """Claude → (bandlar, izoh). Xatoda exception (chaqiruvchi zaxiraga o'tadi)."""
    d = wk.json_ol(_claude(_prompt(matn, manba)))
    return tekshir(d), wk._toza(d.get("izoh"), 300)


def _zaxira(matn):
    """Claude ishlamasa: qatorlar/raqamlar/«;» bo'yicha (oxiri «?» — savol)."""
    return [{"matn": q, "tur": "savol" if q.rstrip().endswith("?") else "ish"}
            for q in wk.oddiy_bolish(matn)][:MAX_BAND]


# ---------------- qo'shish ----------------

def _tahrir_yoki_yubor(mid, html, kb=None):
    if not (mid and wk.matn_tahrir(mid, html, kb)):
        return wk.xabar(html, kb)
    return mid


def _src_bormi(src):
    with wk._LOCK:
        return any(it.get("src") == src for it in _yukla()["items"])


def _kutishni_yop(src=None):
    """«/vazifa» kutishini yopadi: src berilsa — faqat shu xabar olgan kutishni."""
    with wk._LOCK:
        d = _yukla()
        k = d.get("kutish")
        if k and (src is None or (isinstance(k, dict) and k.get("src") == src)):
            d["kutish"] = None
            _saqla(d)
            return True
    return False


def _qisqa_royxat(matnlar, n=5):
    t = "; ".join(f"«{wk.esc(_qisqa(m, 120))}»" for m in matnlar[:n])
    return t + (f" va yana {len(matnlar) - n} ta" if len(matnlar) > n else "")


def _band_qatorlari(items):
    """Tasdiq xabaridagi ro'yxat — KORSAT_BELGI dan oshsa «… yana N ta» (↩️ tugmasi yetsin)."""
    L, n = [], 0
    for i, it in enumerate(items, 1):
        q = f"{i}. {'❓ ' if it['tur'] == 'savol' else ''}{wk.esc(_qisqa(it['matn'], 200))}"
        if n + len(q) > KORSAT_BELGI:
            L.append(f"… yana {len(items) - i + 1} ta — /vazifalar")
            break
        L.append(q)
        n += len(q) + 1
    return L


def qoshish(matn, manba="matn", src=None, now=None):
    """Matn → bandlar → navbat; natija egaga. Qaytadi: natija kodi."""
    now = now or wk.hozir()
    matn = str(matn or "").strip()
    if not matn:
        wk.xabar("Matn bo'sh — ishni yozing: <code>/vazifa &lt;ish&gt;</code>")
        return "vazifa-bosh"
    if src and _src_bormi(src):                 # restart'dagi qayta ishlov — ikki marta qo'shilmaydi
        _kutishni_yop(src)
        wk.xabar(_ogoh_bilan("ℹ️ Bu xabar navbatga allaqachon qo'shilgan — /vazifalar"))
        return "vazifa-takror"
    jarayon = wk.xabar("✍️ Navbatga yozyapman…")
    ai_xato, izoh = None, ""
    try:
        bandlar, izoh = ajrat(matn, manba)
    except Exception as e:                              # noqa: BLE001
        ai_xato = f"{type(e).__name__}: {str(e)[:300]}"
        log(f"AI ajratish xatosi — zaxira bo'lish: {ai_xato}")
        bandlar = _zaxira(matn)
    if not bandlar:
        _tahrir_yoki_yubor(jarayon, "Bu xabardan ish yoki savol topilmadi — aniqroq yozib "
                                    "ko'ring (masalan: <code>/vazifa &lt;loyiha&gt; TZ yozish</code>).")
        return "vazifa-topilmadi"
    with wk._LOCK:
        d = _yukla()
        k = d.get("kutish")
        if src and isinstance(k, dict) and k.get("src") == src:
            d["kutish"] = None                  # kutish ishlar saqlanadigan bo'limda yopiladi
        takror = bool(src) and any(it.get("src") == src for it in d["items"])
        yangi, bor, sigmadi = [], [], []
        if not takror:
            ochiq = [it for it in d["items"] if it.get("holat") in OCHIQ]
            for b in bandlar:
                if any(wk.matn_oxshash(b["matn"], it["matn"]) for it in ochiq + yangi):
                    bor.append(b["matn"])
                    continue
                if len(ochiq) + len(yangi) >= MAX_OCHIQ:
                    sigmadi.append(b["matn"])
                    continue
                it = _yangi(d, b["matn"], b["tur"], manba, src, yangi[0]["id"] if yangi else None,
                            now)
                d["items"].append(it)
                yangi.append(it)
        _saqla(d)
        jami = sum(1 for it in d["items"] if it.get("holat") == "navbatda")
    if takror:
        _tahrir_yoki_yubor(jarayon, "ℹ️ Bu xabar navbatga allaqachon qo'shilgan — /vazifalar")
        return "vazifa-takror"
    L = []
    if yangi:
        L.append(f"📌 <b>Navbatga qo'shildi</b> · {len(yangi)} ta")
        L += _band_qatorlari(yangi)
    if bor:
        L.append(("\n" if L else "") + "ℹ️ Navbatda allaqachon bor: " + _qisqa_royxat(bor))
    if sigmadi:
        L.append(f"⚠️ Navbat to'la ({MAX_OCHIQ} ta) — qo'shilmadi: {_qisqa_royxat(sigmadi)}. "
                 "Eskilarini /vazifalar da yoping.")
    if izoh:
        L.append(f"ℹ️ {wk.esc(izoh)}")
    if ai_xato:
        import analyze

        limit = analyze.limit_matni(ai_xato)
        L.append("⚠️ " + (f"{wk.esc(limit)} — " if limit else "Claude hozir ishlamadi — ")
                 + "xabar qatorlar bo'yicha bo'lindi. Noto'g'ri bo'lsa ↩️ bosib, qayta yozing.")
    if yangi:
        L.append(f"\nErtalab reja so'rovi bilan «buni ham bugun qilasizmi?» deb so'rayman. "
                 f"Navbatda jami: {jami} ta · /vazifalar")
    kb = wk._kb([("↩️ Bekor qilish", f"vz:qaytar:{yangi[0]['id']}")]) if yangi else None
    _tahrir_yoki_yubor(jarayon, _ogoh_bilan("\n".join(L)), kb)
    if yangi:
        log(f"navbatga {len(yangi)} ta ({manba}{', AI zaxira' if ai_xato else ''})")
        _arxiv("Vazifa navbatga: " + "; ".join(it["matn"] for it in yangi))
    return "vazifa-qoshildi" if yangi else "vazifa-bor"


def _arxiv(qator):
    """Ikkinchi miyaga (chat arxivi → vault) bitta qator — best-effort."""
    try:
        import chat_log

        chat_log.append_cmd(f"📌 {qator}"[:1500])
    except Exception:                                   # noqa: BLE001
        pass


# ---------------- «/vazifa» kutishi ----------------

def _wow_xabari(mid, now):
    """Bu message_id kunlik reja so'rovi/preview'imi (aniq reply — kunlik oqimniki)."""
    try:
        st = wk.yukla(now.date().isoformat())
        return any(mid in (st[sl].get("xabarlar") or []) for sl in wk.SLOTLAR)
    except Exception:                                   # noqa: BLE001
        return False


def ushlaydimi(msg, now=None):
    """«/vazifa» dan keyingi xabar (matn yoki ovoz) navbatga tushadimi? Buyruqlar — hech qachon.
    Shu xabar kutishni allaqachon olgan yoki navbatga tushgan bo'lsa (restart'dagi qayta ishlov) —
    muddatdan qat'i nazar ha: xabar kunlik rejaga yoki Q&A'ga sirpanib ketmasin."""
    text = (msg.get("text") or "").strip()
    if text.startswith("/"):
        return False
    if not (text or msg.get("voice") or msg.get("audio")):
        return False
    now = now or wk.hozir()
    src = _src(msg)
    with wk._LOCK:
        d = _yukla()
    k = d.get("kutish") if isinstance(d.get("kutish"), dict) else {}
    if src and (k.get("src") == src or any(it.get("src") == src for it in d["items"])):
        return True
    gacha = wk._vaqt(k.get("gacha"))
    if not (gacha and now < gacha):
        return False
    rep = (msg.get("reply_to_message") or {}).get("message_id")
    return not (rep and _wow_xabari(rep, now))


def kutish_bekor():
    """Kutishni yopadi (boshqa buyruq, yangi kunlik so'rov). Qaytadi: yopildimi."""
    return _kutishni_yop()


def boshqa_buyruq(text):
    """bot_listener: «/vazifa» dan boshqa har qanday buyruq — «/vazifa» kutishi bekor."""
    cmd = (str(text or "").strip().split() or [""])[0].lower().split("@")[0]
    if cmd != "/vazifa":
        _kutishni_yop()


def xabarni_ishlash(msg, now=None):
    """«/vazifa» dan keyingi matn/ovoz → navbat. Kutish shu xabarga belgilanadi va faqat ishlar
    saqlanganda yopiladi (qayta ishlovda ham navbatga qaytadi). Ovoz o'qilmasa — kutish qoladi."""
    now = now or wk.hozir()
    src = _src(msg)
    if src:
        with wk._LOCK:
            d = _yukla()
            k = d.get("kutish")
            if isinstance(k, dict) and k.get("src") != src:
                k["src"] = src
                _saqla(d)
    v = msg.get("voice") or msg.get("audio")
    if v:
        r = wk._ovozdan_matn(v, uzun=UZUN_OVOZ)
        if not r:
            return "vazifa-ovoz-xato"
        matn, manba = r[0], "ovoz"
    else:
        matn, manba = (msg.get("text") or "").strip(), "matn"
    return qoshish(matn, manba, src, now)


# ---------------- ertalabki so'rov ----------------

def _sorov_html(it, i, n, qolgan, now):
    savol = it.get("tur") == "savol"
    bosh = f"{'❓' if savol else '📌'} <b>Navbatdan</b>" + (f" ({i}/{n})" if n > 1 else "")
    yosh = _yosh(it.get("qoshildi"), now)
    L = [bosh + (f" · {yosh}" if yosh else ""), f"«{wk.esc(it['matn'])}»"]
    k = int(it.get("keyin_soni") or 0)
    if k:
        L.append(f"<i>⏳ {k} marta keyinga qoldirilgan</i>")
    L.append("Buni bugun hal qilasizmi?" if savol else "Buni ham bugun qilasizmi?")
    if qolgan:
        L.append(f"\n<i>Navbatda yana {qolgan} ta bor — /vazifalar</i>")
    return "\n".join(L)


def _sorov_kb(iid):
    return wk._kb([("✅ Ha", f"vz:ha:{iid}"), ("⏳ Keyinroq", f"vz:keyin:{iid}")])


def ertalabki_sorov(sana=None, now=None, qolda=False):
    """Ertalabki reja so'rovi yuborilgach (wow_kunlik.sorov) — navbatdagi ishlarni so'raydi.
    Kuniga bir marta (kun belgisi yuborishdan OLDIN — restart/deploy'da takror so'ralmaydi; har
    ish esa faqat xabari yetib borgach «so'raldi» bo'ladi). qolda=True — /vazifalar «❓ Hozir
    so'rash»: bugun so'ralganlari ham. Qaytadi: so'ralgan ishlar soni."""
    now = now or wk.hozir()
    sana = sana or now.date().isoformat()
    with wk._LOCK:
        d = _yukla_tik(sana)
        if not qolda and d.get("sorov_kuni") == sana:
            return 0
        nav = [it for it in d["items"] if it.get("holat") == "navbatda"
               and (qolda or it.get("soraldi") != sana)]
        nav.sort(key=lambda it: (it.get("soraldi") or "", it.get("qoshildi") or "", it["id"]))
        sora = nav[:KUNIGA]
        qolgan = len(nav) - len(sora)
        if not qolda:
            d["sorov_kuni"] = sana
            _saqla(d)
        royxat = [dict(it) for it in sora]
        ogoh = bool(d.get("ogoh"))
    if ogoh:
        wk.xabar(_ogoh_bilan(""))
    n = len(royxat)
    for i, it in enumerate(royxat, 1):
        mid = wk.xabar(_sorov_html(it, i, n, qolgan if i == n else 0, now), _sorov_kb(it["id"]))
        if not mid:
            continue                            # yetmadi — «so'ralmagan» bo'lib qoladi
        eski = it.get("sorov_mid")
        if eski and eski != mid:
            wk.tugmalarni_olib_tashla(eski)     # avvalgi so'rov xabarida tugma qolmasin
        with wk._LOCK:
            d = _yukla()
            x = _top(d, it["id"])
            if x:
                x["sorov_mid"] = mid
                x["soraldi"] = sana
                _saqla(d)
    if n:
        log(f"ertalab: {n} ta ish so'raldi{f' (yana {qolgan} ta navbatda)' if qolgan else ''}"
            f"{' — qo‘lda' if qolda else ''}")
    return n


# ---------------- reja bilan bog'lanish (wow_kunlik chaqiradi) ----------------

def rejaga_kutayotganlar(sana):
    """Bugun «Ha» deyilgan ishlar matni — egasi rejasini yozganda jadvalga qo'shiladi."""
    with wk._LOCK:
        return [it["matn"] for it in _bugungilar(_yukla(), sana)]


def kechki_eslatma(sana, reja):
    """Kechki so'rov va hisobot uchun: bugun «Ha» deyilgan, lekin ertalabki rejada yo'q ishlar."""
    with wk._LOCK:
        bugun = _bugungilar(_yukla(), sana)
    return [it["matn"] for it in bugun if not _mos_qator(it["matn"], reja)]


def kechki_yakun(sana, jadval, now=None, xabar_yubor=True):
    """Kechki hisobot yuborilgach: shu kun olingan ishlar (olingan == sana) hisobot bo'yicha
    yopiladi yoki navbatga qaytadi. Tuzatilib qayta yuborilgan yoki kech yuborilgan hisobot ham
    qayta solishtiriladi; egasi /vazifalar da qo'lda yopgani tegilmaydi. Topilmagan yoki shubhali
    ish hech qachon «bajarildi» bo'lmaydi. Takror chaqiruv (boot, replay) holatni ikkinchi marta
    o'zgartirmaydi. Qaytadi: (yopildi, qaytdi)."""
    now = now or wk.hozir()
    with wk._LOCK:
        d = _yukla()
        b = q = 0
        for it in d["items"]:
            if it.get("olingan") != sana or it.get("holat") not in ("navbatda", "bugun", "bajarildi"):
                continue
            r = _mos_qator(it["matn"], jadval)
            bajarildi = bool(r) and r.get("holat") == "bajarildi"
            h = it.get("holat")
            if bajarildi and h != "bajarildi":
                it.update(holat="bajarildi", sana=None, kechki=sana,
                          yopildi=now.isoformat(timespec="seconds"))
                b += 1
            elif not bajarildi and h == "bugun":
                it.update(holat="navbatda", sana=None)
                it["keyin_soni"] = int(it.get("keyin_soni") or 0) + 1
                q += 1
            elif not bajarildi and h == "bajarildi" and it.get("kechki") == sana:
                it.update(holat="navbatda", kechki=None, yopildi=None)   # tuzatilgan hisobot
                q += 1
        if b or q:
            _saqla(d)
    if (b or q) and xabar_yubor:
        qism = ([f"{b} ta bajarildi ✅"] if b else []) + \
               ([f"{q} tasi navbatga qaytdi ⏳ — keyingi kunlarda yana so'rayman"] if q else [])
        wk.xabar(f"📌 <b>Vazifa navbati:</b> {', '.join(qism)} · /vazifalar")
        _arxiv(f"Vazifa navbati ({sana}): {b} ta bajarildi, {q} tasi navbatga qaytdi")
    return b, q


def holat_qatori(now=None):
    """/kunlik holati uchun bitta qator (ogohlantirish bo'lsa — u ham)."""
    now = now or wk.hozir()
    with wk._LOCK:
        d = _yukla_tik(now.date().isoformat())
    nav = sum(1 for it in d["items"] if it.get("holat") == "navbatda")
    t = f"📌 Vazifa navbati: {nav} ta — /vazifalar"
    return (d["ogoh"] + "\n" + t) if d.get("ogoh") else t


# ---------------- /vazifalar ro'yxati ----------------

def royxat(now=None, sahifa=0):
    """(html, kb) — ochiq ishlar (bugunga olinganlar oldin), sahifalab."""
    now = now or wk.hozir()
    sana = now.date().isoformat()
    with wk._LOCK:
        d = _yukla_tik(sana)
    ochiq = [it for it in d["items"] if it.get("holat") in OCHIQ]
    ochiq.sort(key=lambda it: (it.get("holat") != "bugun", it.get("qoshildi") or "", it["id"]))
    nav = sum(1 for it in ochiq if it.get("holat") == "navbatda")
    L = [f"📌 <b>Vazifa navbati</b> · {nav} ta navbatda"]
    if not ochiq:
        L.append("\nNavbat bo'sh. Qo'shish: <code>/vazifa &lt;ish&gt;</code> — yoki /vazifa "
                 "yuborib, keyin ovoz yoki matn.")
        return "\n".join(L), None
    sahifalar = (len(ochiq) + SAHIFA - 1) // SAHIFA
    sahifa = max(0, min(int(sahifa or 0), sahifalar - 1))
    bosh = sahifa * SAHIFA
    qator = []
    for i, it in enumerate(ochiq[bosh:bosh + SAHIFA], bosh + 1):
        teg = []
        if it.get("holat") == "bugun":
            teg.append("📅 bugunga olingan" if it.get("sana") == sana else "📅 olingan")
        else:
            teg.append(_yosh(it.get("qoshildi"), now))
            if it.get("keyin_soni"):
                teg.append(f"⏳ {it['keyin_soni']}")
        teg = [t for t in teg if t]
        L.append(f"{i}. {'❓ ' if it.get('tur') == 'savol' else ''}{wk.esc(_qisqa(it['matn'], 200))}"
                 + (f" <i>· {' · '.join(teg)}</i>" if teg else ""))
        qator.append([(f"✅ {i}", f"vz:bajardi:{it['id']}:{sahifa}"),
                      (f"🗑 {i}", f"vz:ochir:{it['id']}:{sahifa}")])
    if sahifalar > 1:
        L.append(f"\nSahifa {sahifa + 1}/{sahifalar}")
        yol = []
        if sahifa > 0:
            yol.append(("⬅️ Oldingi", f"vz:sahifa:{sahifa - 1}"))
        if sahifa < sahifalar - 1:
            yol.append(("Keyingi ➡️", f"vz:sahifa:{sahifa + 1}"))
        qator.append(yol)
    L.append(f"\n✅ — bajarildi · 🗑 — o'chirish. Ertalab reja so'rovi bilan kuniga {KUNIGA} "
             "tagacha so'rayman.")
    if nav:
        qator.append([("❓ Hozir so'rash", "vz:sora:0")])
    return "\n".join(L), wk._kb(*qator)


# ---------------- inline tugmalar ----------------

def _yangila_xabar(mid, html, kb=None):
    if mid:
        wk.matn_tahrir(mid, html, kb)
    else:
        wk.xabar(html, kb)


def callback(cq, now=None):
    """«vz:<amal>:<id>[:<sahifa>]» tugmalari. Qaytadi: natija satri yoki None (bizniki emas).
    Yuboruvchi (egasi) tekshiruvi — bot_listener'da. Qayta bosish (va restart'dagi qayta ishlov)
    holatni ikkinchi marta o'zgartirmaydi."""
    data = str(cq.get("data") or "")
    if not data.startswith("vz:"):
        return None
    q = data.split(":")
    amal = q[1] if len(q) > 1 else ""
    try:
        iid = int(q[2]) if len(q) > 2 else -1
        sahifa = int(q[3]) if len(q) > 3 else 0
    except ValueError:
        iid, sahifa = -1, 0
    cid = cq.get("id")
    mid = (cq.get("message") or {}).get("message_id")
    now = now or wk.hozir()
    if amal == "sora":
        wk.javob_cb(cid, "So'rayapman…")
        n = ertalabki_sorov(now=now, qolda=True)
        if not n:
            wk.xabar("Navbatda so'raladigan ish yo'q — /vazifalar")
        return f"vz-sora-{n}"
    if amal == "sahifa" and iid >= 0:
        wk.javob_cb(cid)
        html, kb = royxat(now, iid)
        _yangila_xabar(mid, html, kb)
        return "vz-sahifa"
    f = {"ha": _ha, "keyin": _keyin, "qayta": _qayta, "qaytar": _qaytar,
         "bajardi": _yop, "ochir": _yop}.get(amal)
    if not f or iid <= 0:
        wk.javob_cb(cid, "Eskirgan tugma")
        return "vz-cb-noma'lum"
    return f(cid, mid, iid, now, amal, sahifa)


def _eskirgan(cid, mid):
    wk.javob_cb(cid, "Eskirgan tugma")
    if mid:
        wk.tugmalarni_olib_tashla(mid)
    return "vz-eskirgan"


def _kechki_boshlangan(sana):
    return wk.yukla(sana)["kechqurun"]["holat"] != "yangi"


def _ha(cid, mid, iid, now, amal, sahifa=0):
    sana = now.date().isoformat()
    with wk._LOCK:                                      # qulf ostida faqat holat — Telegram keyin
        d = _yukla_tik(sana)
        it = _top(d, iid)
        if not it or it.get("holat") not in OCHIQ:
            natija = "eskirgan"
        elif it.get("holat") == "bugun" and it.get("sana") == sana:
            natija = "takror"
        else:
            natija = wk.qator_qosh(sana, "ertalab", [it["matn"]])
            if natija == "yuborildi" and _kechki_boshlangan(sana):
                natija = "kechki"
            if natija in ("qoshildi", "bor", "yangi", "kutilmoqda", "yuborildi", "kechki"):
                it.update(holat="bugun", sana=sana, olingan=sana)
            it["soraldi"] = sana
            _saqla(d)
        matn = it["matn"] if it else ""
    if natija == "eskirgan":
        return _eskirgan(cid, mid)
    m = f"«{wk.esc(matn)}»"
    izoh = f"Navbatdan qo'shildi: {matn}"[:200]
    if natija == "takror":
        wk.javob_cb(cid, "Allaqachon qabul qilingan")
        if wk.preview_eskirgan(sana, "ertalab"):       # uzilishdan keyin preview yetmagan bo'lsa
            wk.preview_yubor(sana, "ertalab", izoh=izoh)
        return "vz-ha-takror"
    if natija == "qoshildi":
        wk.javob_cb(cid, "Rejaga qo'shildi")
        _yangila_xabar(mid, f"✅ {m} — bugungi rejaga qo'shildi (yangi preview pastda).")
        wk.preview_yubor(sana, "ertalab", izoh=izoh)
    elif natija == "bor":
        wk.javob_cb(cid, "Rejada bor")
        _yangila_xabar(mid, f"✅ {m} — bugungi rejada allaqachon bor.")
        if wk.preview_eskirgan(sana, "ertalab"):
            wk.preview_yubor(sana, "ertalab")
    elif natija in ("yangi", "kutilmoqda"):
        wk.javob_cb(cid, "Qabul qilindi")
        _yangila_xabar(mid, f"✅ {m} — qabul qilindi. Rejangizni yozganingizda jadvalga "
                            "qo'shaman.")
    elif natija == "yuborildi":
        wk.javob_cb(cid, "Qabul qilindi")
        _yangila_xabar(mid, f"✅ {m} — qabul qilindi.\nℹ️ Bugungi reja {wk.esc(wk._kimga())} "
                            "allaqachon yuborilgan. Yangilangan rejani yuborish uchun:",
                       wk._kb([("🔁 Rejaga qo'shib qayta yuborish", f"vz:qayta:{iid}")]))
    elif natija == "kechki":
        wk.javob_cb(cid, "Qabul qilindi")
        _yangila_xabar(mid, f"✅ {m} — qabul qilindi. Ertalabki reja yuborilgan, kechki so'rov "
                            "boshlangan — bu ishni kechki hisobotda so'rayman.")
    elif natija == "yuborilmoqda":
        wk.javob_cb(cid, "Reja hozir yuborilyapti — birozdan so'ng qayta bosing")
        return "vz-ha-yuborilmoqda"
    elif natija == "toliq":
        wk.javob_cb(cid, "Rejada joy yo'q")
        _yangila_xabar(mid, f"⚠️ {m} — rejada joy qolmadi ({wk.MAX_QATOR} qator). Navbatda "
                            "qoldi, keyingi kunlarda yana so'rayman.")
    else:                                               # dam | otkazildi | boshqa
        wk.javob_cb(cid, "Bugungi reja yopiq")
        _yangila_xabar(mid, f"ℹ️ {m} — {wk.esc(_HOLAT_SOZ.get(natija, 'bugungi reja yopiq'))}. "
                            "Navbatda qoldi, keyingi kunlarda yana so'rayman.")
    log(f"ha #{iid} → {natija}")
    return f"vz-ha-{natija}"


def _keyin(cid, mid, iid, now, amal, sahifa=0):
    sana = now.date().isoformat()
    with wk._LOCK:
        d = _yukla_tik(sana)
        it = _top(d, iid)
        if not it or it.get("holat") not in OCHIQ:
            natija = "eskirgan"
        elif it.get("holat") == "bugun":
            natija = "bugun"
        else:
            natija = "keyin"
            if it.get("keyin_kuni") != sana:            # qayta bosish ikki marta sanalmasin
                it["keyin_soni"] = int(it.get("keyin_soni") or 0) + 1
                it["keyin_kuni"] = sana
            it["soraldi"] = sana
            _saqla(d)
        matn = it["matn"] if it else ""
    if natija == "eskirgan":
        return _eskirgan(cid, mid)
    if natija == "bugun":
        wk.javob_cb(cid, "Bu ish bugunga olingan")
        return "vz-keyin-bugun"
    wk.javob_cb(cid, "Mayli — keyinroq yana so'rayman")
    _yangila_xabar(mid, f"⏳ «{wk.esc(matn)}» — keyinroqqa qoldirildi. Navbatda turadi, keyingi "
                        "kunlarda yana so'rayman.")
    return "vz-keyin"


def _qayta(cid, mid, iid, now, amal, sahifa=0):
    """Reja yuborilgandan keyin «Ha» — egasi aniq bosganda yuborilgan rejani «yangilangan»
    qoralama qilib ochadi va ishni qo'shadi (✅ yoki avto-yuborish bilan ketadi). Kechki so'rov
    boshlangan bo'lsa — ochilmaydi (ish kechki hisobotga qo'shiladi)."""
    sana = now.date().isoformat()
    with wk._LOCK:
        d = _yukla()
        it = _top(d, iid)
        if not it or it.get("holat") != "bugun" or it.get("sana") != sana:
            natija, matn = "eskirgan", ""
        else:
            matn = it["matn"]
            natija = "kechki" if _kechki_boshlangan(sana) else \
                wk.qator_qosh(sana, "ertalab", [matn], qayta_och=True)
    if natija == "eskirgan":
        return _eskirgan(cid, mid)
    m = f"«{wk.esc(matn)}»"
    if natija == "qoshildi":
        wk.javob_cb(cid, "Reja qayta ochildi")
        _yangila_xabar(mid, f"🔁 {m} — reja yangilandi, preview pastda. Tekshirib ✅ bosing.")
        wk.preview_yubor(sana, "ertalab", izoh=f"Navbatdan qo'shildi: {matn}"[:200])
    elif natija == "bor":
        wk.javob_cb(cid, "Rejada bor")
        _yangila_xabar(mid, f"✅ {m} — bugungi rejada allaqachon bor, qayta yuborish shart emas.")
    elif natija == "kechki":
        wk.javob_cb(cid, "Kechki so'rov boshlangan")
        _yangila_xabar(mid, f"ℹ️ {m} — kechki so'rov boshlangan, ertalabki reja endi qayta "
                            "yuborilmaydi. Bu ishni kechki hisobotda so'rayman.")
    elif natija == "toliq":
        wk.javob_cb(cid, "Rejada joy yo'q")
        _yangila_xabar(mid, f"⚠️ {m} — rejada joy qolmadi ({wk.MAX_QATOR} qator), reja ochilmadi.")
    else:
        wk.javob_cb(cid, "Hozir qo'shib bo'lmaydi")
        _yangila_xabar(mid, f"ℹ️ {m} — reja hozir ochilmadi. Ish bugunga olingan qoladi.")
    return f"vz-qayta-{natija}"


def _qaytar(cid, mid, iid, now, amal, sahifa=0):
    """«↩️ Bekor qilish» — shu xabardan qo'shilgan (navbatdagi) ishlar o'chadi."""
    with wk._LOCK:
        d = _yukla()
        it = _top(d, iid)
        n = -1
        if it:
            toplam = it.get("toplam") or it["id"]
            n = 0
            for x in d["items"]:
                if (x.get("toplam") or x["id"]) == toplam and x.get("holat") == "navbatda":
                    x.update(holat="ochirildi", yopildi=now.isoformat(timespec="seconds"))
                    n += 1
            if n:
                _saqla(d)
    if n < 0:
        return _eskirgan(cid, mid)
    wk.javob_cb(cid, "Bekor qilindi" if n else "O'zgarish yo'q")
    _yangila_xabar(mid, f"↩️ Bekor qilindi — {n} ta ish navbatdan olib tashlandi." if n else
                   "ℹ️ Bu ishlar navbatda emas (bajarilgan, bugunga olingan yoki o'chirilgan).")
    return f"vz-qaytar-{n}"


def _yop(cid, mid, iid, now, amal, sahifa=0):
    """/vazifalar dagi ✅ (bajarildi) va 🗑 (o'chirish) — ro'yxat o'sha sahifada yangilanadi.
    Qo'lda yopilgan ish kechki hisobot solishtiruvidan chiqadi (olingan tozalanadi)."""
    holat = "bajarildi" if amal == "bajardi" else "ochirildi"
    with wk._LOCK:
        d = _yukla()
        it = _top(d, iid)
        ok = bool(it) and it.get("holat") in OCHIQ
        if ok:
            it.update(holat=holat, yopildi=now.isoformat(timespec="seconds"), olingan=None,
                      sana=None)
            _saqla(d)
            matn = it["matn"]
    wk.javob_cb(cid, ("Bajarildi ✅" if holat == "bajarildi" else "O'chirildi") if ok else
                "Bu ish allaqachon yopilgan")
    html, kb = royxat(now, sahifa)
    _yangila_xabar(mid, html, kb)
    if ok:
        _arxiv(f"Vazifa {'bajarildi' if holat == 'bajarildi' else 'o‘chirildi'}: {matn}")
    return f"vz-{amal}" if ok else f"vz-{amal}-yopiq"


# ---------------- buyruqlar ----------------

def buyruq(text, msg=None, now=None):
    """/vazifa va /vazifalar. Bizniki bo'lmasa — None; aks holda natija kodi (javob yuborilgan)."""
    parts = str(text or "").strip().split(None, 1)
    if not parts:
        return None
    cmd = parts[0].lower().split("@")[0]
    if cmd not in BUYRUQLAR:                           # aniq so'z: /vazifalar ≠ /vazifa
        return None
    arg = parts[1].strip() if len(parts) > 1 else ""
    now = now or wk.hozir()
    if cmd == "/vazifalar":
        html, kb = royxat(now)
        wk.xabar(_ogoh_bilan(html), kb)
        return "vazifa-royxat"
    if arg.lower() in ("bekor", "stop"):
        _kutishni_yop()
        wk.xabar("Mayli — kutish bekor qilindi.")
        return "vazifa-kutish-bekor"
    if arg:
        _kutishni_yop()                         # oldingi «/vazifa» kutishi keyingi javobni olmasin
        return qoshish(arg, "matn", _src(msg), now)
    rep, manba, ovoz = _reply_manbasi(msg)
    if rep or ovoz:
        _kutishni_yop()
    if rep:
        return qoshish(rep, manba, _src(msg), now)
    if ovoz:
        r = wk._ovozdan_matn(ovoz, uzun=UZUN_OVOZ)
        if not r:
            return "vazifa-ovoz-xato"
        return qoshish(r[0], "ovoz", _src(msg), now)
    with wk._LOCK:
        d = _yukla()
        d["kutish"] = {"gacha": (now + timedelta(minutes=KUTISH_DAQ)).isoformat(timespec="seconds"),
                       "src": None}
        _saqla(d)
    wk.xabar(_ogoh_bilan(
        f"📝 Ishlaringizni yozing yoki ovoz yuboring — keyingi xabaringiz navbatga tushadi "
        f"({KUTISH_DAQ} daqiqa). Bir xabarda bir nechta ish bo'lsa — o'zim ajrataman.\n"
        "Bekor qilish: <code>/vazifa bekor</code>"))
    return "vazifa-kutish"


if __name__ == "__main__":                              # lokal ko'rish: python3 vazifa.py
    for it in _yukla()["items"]:
        print(it.get("id"), it.get("holat"), it.get("matn"))
