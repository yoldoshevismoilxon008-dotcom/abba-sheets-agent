"""/miya — ikkinchi miyadan kun ko'rinishi (WALL-E buyrug'i, 2026-11-25).

  /miya            — bugun
  /miya kecha      — kecha
  /miya 24.11      — yoki 2026-11-24

Manba: vault ko'zgusi (vault_sync.CLONE = /data/vault, har 10 daqiqada yangilanadi).
Mac'dagi miya yig'uvchisi (deploy/mac-sync/miya) har kunga `wall-e/kunlar/<sana>.md`
yozadi: kunlik reja va hisobot, 09:00 hisobot, target, Instagram, suhbatlar va shu kungi
Claude sessiyalari. Bu buyruq o'sha yozuvni Telegram uchun qisqartiradi.

Claude chaqirilmaydi — javob bir zumda, kvota sarflanmaydi. Yozuv Mac → GitHub → Railway
yo'li bilan keladi: Mac uyquda bo'lsa kechikishi mumkin, javobda shu aytiladi.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
BUYRUQ = "/miya"
MAKS = 3800                      # Telegram 4096 chegarasidan pastda
VAULT_NOMI = "claude-brain"      # Obsidian'dagi vault nomi (papka nomi)


def _klon() -> Path:
    import vault_sync
    return Path(vault_sync.CLONE)


def sana_ol(args, bugun: date):
    """Argumentdan sana: bo'sh/bugun, kecha, YYYY-MM-DD, DD.MM[.YYYY]. Tushunilmasa None."""
    if not args:
        return bugun
    a = str(args[0]).strip().lower()
    if a in ("bugun", "today"):
        return bugun
    if a in ("kecha", "yesterday"):
        return bugun - timedelta(days=1)
    try:
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", a)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", a)
        if m:
            yil = int(m.group(3)) if m.group(3) else bugun.year
            if yil < 100:
                yil += 2000
            d = date(yil, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and d > bugun:          # «31.12» yanvarda — o'tgan yil
                d = date(yil - 1, d.month, d.day)
            return d
    except ValueError:
        return None
    return None


def _inline(matn: str) -> str:
    """Bir qator markdown → Telegram HTML (escape + bold + havolalar)."""
    t = matn
    t = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda m: m.group(2), t)
    t = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1).rsplit("/", 1)[-1], t)
    havolalar = []

    def _h(m):
        havolalar.append((m.group(1), m.group(2)))
        return f"\x00{len(havolalar) - 1}\x00"
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _h, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    for i, (nom, url) in enumerate(havolalar):
        t = t.replace(f"\x00{i}\x00", f'<a href="{html.escape(url)}">{html.escape(nom, quote=False)}</a>')
    return t


def _bolimlar(md: str) -> dict:
    md = re.sub(r"^---\n[\s\S]*?\n---\n", "", md)
    md = md.split("<!-- miya:qo'lda -->", 1)[0]
    natija, joriy = {}, None
    for q in md.splitlines():
        if q.startswith("## "):
            joriy = q[3:].strip()
            natija[joriy] = []
        elif joriy is not None and q.strip() and not q.startswith(">"):
            natija[joriy].append(q.rstrip())
    return natija


def _top(bolimlar: dict, kalit: str):
    for k, v in bolimlar.items():
        if kalit.lower() in k.lower():
            return k, v
    return None, []


def kun_matni(sana: date, klon: Path | None = None, bugun: date | None = None) -> str:
    klon = Path(klon or _klon())
    bugun = bugun or datetime.now(TZ).date()
    kun = sana.isoformat()
    sarlavha = f"🧠 <b>Ikkinchi miya — {sana:%d.%m.%Y}</b>"
    p = klon / "wall-e" / "kunlar" / f"{kun}.md"
    if not p.exists():
        if not (klon / "wall-e").exists():
            return (f"{sarlavha}\n\nMiya yig'uvchisi hali ishga tushmagan yoki vault sinxroni "
                    "kelmagan. Holat: /vault_stat")
        sabab = ("bugungi yozuv Mac'dan hali kelmagan (Mac uyquda bo'lsa kechikadi; "
                 "yig'uvchi har soatda ishlaydi)" if sana >= bugun - timedelta(days=1)
                 else "bu kun uchun yozuv yo'q")
        return f"{sarlavha}\n\n{sabab}. Boshqa kun: <code>/miya kecha</code> yoki <code>/miya 24.11</code>"
    try:
        b = _bolimlar(p.read_text(encoding="utf-8"))
    except OSError:
        return f"{sarlavha}\n\n⚠️ Yozuvni o'qib bo'lmadi."
    q = [sarlavha, ""]
    _, reja = _top(b, "reja va hisobot")
    if reja:
        q.append("🗓️ <b>Reja va hisobot</b>")
        q.extend(_inline(x) for x in reja[:24])
        q.append("")
    _, h09 = _top(b, "09:00")
    if h09:
        q.append("📊 <b>09:00 hisobot</b>")
        q.extend(_inline(x if len(x) <= 180 else x[:177] + "…") for x in h09[:6])
        q.append("")
    _, tg = _top(b, "Target")
    if tg:
        q.append("🎯 <b>Target</b>")
        q.extend(_inline(x) for x in tg[:3])
        q.append("")
    _, ig = _top(b, "Instagram")
    if ig:
        q.append("📈 " + _inline(ig[0].lstrip("- ")))
    sarl, suh = _top(b, "suhbat")
    if sarl:
        m = re.search(r"\((\d+) savol\)", sarl)
        q.append(f"💬 WALL-E bilan: {m.group(1) if m else len(suh)} savol")
    _, cl = _top(b, "Claude bilan")
    if cl:
        q.append(f"💻 <b>Claude bilan ({len(cl)})</b>")
        q.extend(_inline(x) for x in cl[:8])
    q.append("")
    q.append(f"Obsidian: <code>obsidian://open?vault={VAULT_NOMI}&amp;file=wall-e%2Fkunlar%2F{kun}</code>")
    matn = "\n".join(q).strip()
    if len(matn) > MAKS:
        matn = matn[:MAKS].rsplit("\n", 1)[0] + "\n…"
    # kesilgan qatorda yopilmagan teg qolmasin
    for teg in ("b", "code", "a"):
        ochiq = len(re.findall(rf"<{teg}[ >]", matn))
        yopiq = len(re.findall(rf"</{teg}>", matn))
        matn += f"</{teg}>" * max(0, ochiq - yopiq)
    return matn


def javob(text: str, now: datetime | None = None, klon: Path | None = None):
    """Buyruq bizniki bo'lmasa None; aks holda Telegram HTML matni."""
    parts = str(text or "").strip().split()
    if not parts or parts[0].lower().split("@")[0] != BUYRUQ:
        return None
    bugun = (now or datetime.now(TZ)).date()
    sana = sana_ol(parts[1:], bugun)
    if sana is None:
        return ("Foydalanish: <code>/miya</code> (bugun) · <code>/miya kecha</code> · "
                "<code>/miya 24.11</code> · <code>/miya 2026-11-24</code>")
    return kun_matni(sana, klon=klon, bugun=bugun)
