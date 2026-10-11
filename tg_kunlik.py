#!/usr/bin/env python3
"""TG kunlik monitoring (Mac zanjiri) nazorati — Railway tomonidan, Mac'dan TASHQARIDA.

AUDIT.md (abba-hisobotlar) P0-2: Mac zanjiri 09-23, 10-01, 10-04..10-07 kunlari umuman
ishlamagan — PDF ham, heartbeat yozuvi ham yo'q. heartbeat.json faqat muvaffaqiyatli
kunni yozadi, shuning uchun yo'qolgan kun hech qanday signal bermagan; hisobotdagi
🩺 «PDF ✓» esa faqat Railway'ning o'z Chrome'ini tekshirardi (Mac PDF'ini emas).

Bu modul REPORTS_REPO (abba-hisobotlar) dagi tg-kunlik/ ni GitHub API orqali O'QIYDI
(klonsiz — push_reports/push_chat klonlari bilan to'qnashmasin). Kun «bor» = PDF bor YOKI
heartbeat'da holati «ok» — PDF'lar git'dan olib tashlansa ham nazorat ishlayveradi;
TG_BOSH dan keyin ikkalasi ham bo'lmasa — ✗ (yashil «boshlanmagan» emas).
  • holat()        — sof funksiya: bugun/kecha bormi, oxirgi kun, oynadagi bo'shliqlar;
  • health_part()  — 🩺 qatori uchun «TG-kunlik ✓/⏳/✗» (health.py);
  • alert_text()   — 12:00 da bugungi natija hali yo'q bo'lsa egaga xabar (supervisor.py).
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

OYNA = 7          # bo'shliqlar shuncha oxirgi kun ichida qidiriladi (bugun kirmaydi)
TIMEOUT = 15
TG_BOSH = date(2026, 9, 10)   # birinchi PDF kuni: shundan keyin ma'lumot yo'qligi — ✗
API = "https://api.github.com/repos/{repo}/{path}"
_PDF_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.pdf$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def log(msg):
    # stdout emas: health.py --line chiqishi report.md ga yoziladi
    print(f"[tg_kunlik] {msg}", file=sys.stderr, flush=True)


def _dm(iso):
    return f"{iso[8:10]}.{iso[5:7]}"


def sozlangan():
    return bool(os.environ.get("REPORTS_REPO", "").strip() and os.environ.get("GH_TOKEN_REPORTS", "").strip())


def _get(repo, token, path, raw=False):
    import requests

    headers = {
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
    }
    r = requests.get(API.format(repo=repo, path=path), headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text if raw else r.json()


def _pdf_kunlar(repo, token):
    """tg-kunlik/ dagi PDF kunlari. contents/ papka ro'yxati 1000 faylda jim kesiladi,
    shuning uchun git tree (papka sha'si orqali) o'qiladi; u ham kesilsa — xato."""
    root = _get(repo, token, "contents")
    sha = next((it.get("sha") for it in root if isinstance(it, dict)
                and it.get("name") == "tg-kunlik" and it.get("type") == "dir"), None) \
        if isinstance(root, list) else None
    if not sha:
        return set()
    tree = _get(repo, token, f"git/trees/{sha}")
    if tree.get("truncated"):
        raise RuntimeError("tg-kunlik git tree kesilgan — ro'yxat to'liq emas")
    pdf = set()
    for it in tree.get("tree") or []:
        m = _PDF_RE.match(str(it.get("path", "")))
        if m and it.get("type") == "blob":
            pdf.add(m.group(1))
    return pdf


def yukla(repo=None, token=None):
    """(pdf_kunlar: set[ISO], heartbeat: dict) — tg-kunlik/ dagi PDF'lar va heartbeat.json."""
    repo = repo or os.environ.get("REPORTS_REPO", "").strip()
    token = token or os.environ.get("GH_TOKEN_REPORTS", "").strip()
    pdf = _pdf_kunlar(repo, token)
    try:
        hb = json.loads(_get(repo, token, "contents/tg-kunlik/heartbeat.json", raw=True))
    except Exception as e:                       # noqa: BLE001
        if not pdf:
            raise                                # na PDF, na heartbeat — «?», yashil emas
        log(f"heartbeat o'qilmadi: {type(e).__name__}")
        hb = {}
    return pdf, hb if isinstance(hb, dict) else {}


def holat(today, pdf_kunlar, heartbeat=None):
    """Sof funksiya. today — date. Kun «bor» = PDF bor YOKI heartbeat holati «ok». Qaytadi dict:
    boshlanmagan, bugun, kecha, oxirgi (ISO|None — TG_BOSH dan beri hech narsa yo'q),
    yoq (oynadagi yo'q kunlar, ISO), vaqt (bugungi heartbeat 'tugadi' HH:MM|None),
    hb_xato (bugungi heartbeat holati ≠ ok)."""
    hb = {k["sana"]: k for k in ((heartbeat or {}).get("kunlar") or [])
          if isinstance(k, dict) and _ISO_RE.match(str(k.get("sana", "")))}
    t = today.isoformat()
    bor = {d for d in set(pdf_kunlar) | {s for s, k in hb.items() if k.get("holat") == "ok"} if d <= t}
    if not bor and today < TG_BOSH:
        return {"boshlanmagan": True}
    kunlar = sorted(bor)
    birinchi = min(TG_BOSH, date.fromisoformat(kunlar[0])) if kunlar else TG_BOSH
    oyna = [today - timedelta(days=i) for i in range(1, OYNA + 1)]
    yoq = sorted(d.isoformat() for d in oyna if d >= birinchi and d.isoformat() not in bor)
    kecha = (today - timedelta(days=1)).isoformat()
    hb_bugun = hb.get(t) or {}
    tugadi = str(hb_bugun.get("tugadi") or "")
    return {
        "boshlanmagan": False,
        "bugun": t in bor,
        "kecha": kecha in bor or date.fromisoformat(kecha) < birinchi,
        "oxirgi": kunlar[-1] if kunlar else None,
        "yoq": yoq,
        "vaqt": tugadi[11:16] if len(tugadi) >= 16 else None,
        "hb_xato": bool(hb_bugun) and hb_bugun.get("holat") not in (None, "ok"),
        "hb_holat": hb_bugun.get("holat"),
    }


def _yoq_izoh(h):
    if not h.get("yoq"):
        return ""
    return f" · {OYNA} kunda {len(h['yoq'])} kun yo'q ({', '.join(_dm(d) for d in h['yoq'][:4])}" + \
        (" …" if len(h["yoq"]) > 4 else "") + ")"


def health_part(today, h):
    """(belgi, izoh): belgi ∈ {'✓', '⏳', '✗'}."""
    if h.get("boshlanmagan"):
        return "✓", "zanjir hali boshlanmagan"
    if h.get("hb_xato"):
        return "✗", f"bugungi zanjir holati: {h.get('hb_holat')}" + _yoq_izoh(h)
    if h.get("bugun"):
        return "✓", ("bugun " + h["vaqt"] if h.get("vaqt") else "bugun") + _yoq_izoh(h)
    if h.get("kecha"):
        return "⏳", "bugungisi hali yo'q, kecha ✓" + _yoq_izoh(h)
    if not h.get("oxirgi"):
        return "✗", f"{_dm(TG_BOSH.isoformat())} dan beri PDF ham, heartbeat ham yo'q"
    gap = (today - date.fromisoformat(h["oxirgi"])).days
    return "✗", f"oxirgi {_dm(h['oxirgi'])} — {gap} kun oldin" + _yoq_izoh(h)


def alert_text(today, h):
    """12:00 tekshiruvi: bugungi natija (PDF/heartbeat) yo'q bo'lsa egaga matn, aks holda None."""
    if h.get("boshlanmagan") or (h.get("bugun") and not h.get("hb_xato")):
        return None
    if h.get("hb_xato"):
        return (f"⚠️ TG kunlik monitoring ({_dm(today.isoformat())}): zanjir holati «{h.get('hb_holat')}». "
                "Mac log'ini tekshiring.")
    if h.get("oxirgi"):
        gap = (today - date.fromisoformat(h["oxirgi"])).days
        oxirgi = f"Oxirgisi: {_dm(h['oxirgi'])} ({gap} kun oldin)."
    else:
        oxirgi = f"{_dm(TG_BOSH.isoformat())} dan beri PDF ham, heartbeat ham topilmadi."
    yoq = ", ".join(_dm(d) for d in h.get("yoq", []))
    return (
        f"⚠️ TG kunlik monitoring: bugungi ({_dm(today.isoformat())}) natija (PDF/heartbeat) soat 12:00 "
        f"gacha kelmadi. {oxirgi}"
        + (f" Oxirgi {OYNA} kunda yo'q: {yoq}." if yoq else "")
        + " Mac'ni tekshiring: uyquda/o'chiq, launchd job, internet yoki git push."
    )


def tekshir(today=None):
    """health/supervisor uchun: (holat dict | None, xato matni | None). Sozlanmagan → (None, None)."""
    if not sozlangan():
        return None, None
    today = today or date.today()
    try:
        pdf, hb = yukla()
    except Exception as e:                       # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:80]}"
    return holat(today, pdf, hb), None


def main():
    h, err = tekshir()
    if err:
        print(f"tekshirib bo'lmadi: {err}")
        return 1
    if h is None:
        print("REPORTS_REPO / GH_TOKEN_REPORTS yo'q — o'tkazildi")
        return 0
    print(health_part(date.today(), h))
    print(alert_text(date.today(), h) or "ogohlantirish yo'q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
