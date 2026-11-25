"""Kechki «🧠 Miya xulosasi» — WALL-E orqali egaga bitta Telegram xabar.

Kuniga bir marta, belgilangan soatdan keyingi birinchi yig'ishda (standart 21:30). Mac
uyquda bo'lsa — uyg'ongach, lekin faqat shu kun ichida (ertasi kuni eskisi yuborilmaydi).
Yoqish/o'chirish: `python3 -m miya --xulosa on|off [--soat 21:30]` → state/xulosa.json.
Token va chat_id ~/abba-sheets-agent/.env dan (target hisoboti bilan bir xil); hech qayerga
yozilmaydi va logga chiqmaydi.
"""
from __future__ import annotations

import html
import json
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from . import asos

ENV = asos.HOME / "abba-sheets-agent" / ".env"


def sozlama() -> dict:
    d = asos.holat_oqi("xulosa")
    return {"yoqilgan": bool(d.get("yoqilgan")), "soat": d.get("soat") or "21:30",
            "oxirgi": d.get("oxirgi") or ""}


def sozla(yoqilgan: bool, soat: str | None = None) -> dict:
    d = asos.holat_oqi("xulosa")
    d["yoqilgan"] = yoqilgan
    if soat:
        datetime.strptime(soat, "%H:%M")
        d["soat"] = soat
    asos.holat_yoz("xulosa", d)
    return sozlama()


def _env() -> dict:
    natija = {}
    try:
        for q in ENV.read_text(encoding="utf-8").splitlines():
            q = q.strip()
            if q and not q.startswith("#") and "=" in q:
                k, v = q.split("=", 1)
                natija[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return natija


def matn(sh: dict, hisob: dict, vault: Path, kun: str) -> str:
    e = html.escape
    sesslar = [v for v in sh.values() if isinstance(v, dict) and v.get("rel") and kun in (v.get("sana") or [])]
    q = [f"🧠 <b>Ikkinchi miya — {kun[8:10]}.{kun[5:7]}</b>", ""]
    if sesslar:
        commit = sum(int(v.get("commitlar") or 0) for v in sesslar)
        art = sum(len(v.get("artifactlar") or []) for v in sesslar)
        q.append(f"💬 <b>Claude:</b> {len(sesslar)} sessiya"
                 + (f", {commit} commit" if commit else "") + (f", {art} artifact" if art else ""))
        for v in sesslar[:6]:
            q.append(f"  • {e(asos.qisqart(v.get('sarlavha') or 'sessiya', 70))}")
    else:
        q.append("💬 <b>Claude:</b> bugun sessiya yo'q")
    kun_fayl = vault / "wall-e" / "kunlar" / f"{kun}.md"
    if kun_fayl.exists():
        fm = asos.fm_oqi(kun_fayl.read_text(encoding="utf-8"))
        qism = []
        qism.append("09:00 hisobot ✅" if fm.get("hisobot") == "true" else "09:00 hisobot yo'q")
        wow = int(fm.get("wow") or 0)
        qism.append({0: "reja/hisobot yo'q", 1: "reja ✅", 2: "reja ✅ hisobot ✅"}.get(wow, f"WOW {wow}"))
        if fm.get("chat_xabarlar") not in (None, "", "0"):
            qism.append(f"{fm['chat_xabarlar']} savol")
        q.append("🤖 <b>WALL-E:</b> " + " · ".join(qism))
    yangi = hisob.get("yangi", 0)
    yang = hisob.get("yangilandi", 0)
    q.append(f"📥 <b>Miya:</b> {yangi} yangi, {yang} yangilangan yozuv")
    q.append("")
    q.append("Obsidian'da: <code>obsidian://open?path=" + e(urllib.parse.quote(str(vault / "BOSH-SAHIFA.md"))) + "</code>")
    return "\n".join(q)


def yubor(text: str) -> bool:
    env = _env()
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        asos.log("xulosa: TELEGRAM_BOT_TOKEN/CHAT_ID yo'q — yuborilmadi")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                    timeout=40) as r:
            ok = json.loads(r.read().decode("utf-8", "replace")).get("ok") is True
    except Exception as ex:      # tarmoq xatosi — keyingi yig'ishda qayta urinadi
        asos.log(f"xulosa: yuborilmadi ({type(ex).__name__})")
        return False
    return ok


def kerakmi(hozir: datetime | None = None) -> bool:
    s = sozlama()
    if not s["yoqilgan"]:
        return False
    hozir = hozir or datetime.now(asos.TZ)
    kun = hozir.strftime("%Y-%m-%d")
    if s["oxirgi"] == kun:
        return False
    return hozir.strftime("%H:%M") >= s["soat"]


def ishla(sh: dict, hisob: dict, vault: Path, majburiy: bool = False) -> str:
    """Kerak bo'lsa yuboradi. Qaytadi: 'yuborildi' | 'kerak emas' | 'xato'."""
    hozir = datetime.now(asos.TZ)
    if not majburiy and not kerakmi(hozir):
        return "kerak emas"
    kun = hozir.strftime("%Y-%m-%d")
    if yubor(matn(sh, hisob, vault, kun)):
        d = asos.holat_oqi("xulosa")
        d["oxirgi"] = kun
        asos.holat_yoz("xulosa", d)
        return "yuborildi"
    return "xato"
