"""Kechki «🧠 Miya xulosasi» — WALL-E orqali egaga bitta Telegram xabar.

Kuniga bir marta, belgilangan soatda (standart 21:30). Asosiy yig'ish har soatda ishlaydi, lekin
uning daqiqasi Mac uyg'ongan paytga qarab suriladi (masalan, har soatning 13-daqiqasi). Shuning
uchun `--xulosa on` launchd'ga alohida `com.abba.miya-xulosa` jadvalini qo'yadi, xulosa aynan
belgilangan soatda chiqadi. Jadval yo'qolsa ham, soatlik yig'ish o'sha soatdan keyingi birinchi
yurishda yuboradi. Mac uyquda bo'lsa — uyg'ongach, lekin faqat shu kun ichida (ertasi kuni
eskisi yuborilmaydi).

Xulosaga hali yozilmagan faol sessiyalar ham kiradi (sessiyalar.bugungi_faol — faqat o'qiladi).
Soatdan oldingi sinov (`--xulosa-yubor`) kechki xulosani bekor qilmaydi.

  python3 -m miya --xulosa on|off [--soat 21:30]   # state/xulosa.json + launchd jadvali
  python3 -m miya --xulosa-korish                  # matnni yubormasdan ko'rish
  python3 -m miya --xulosa-yubor                   # hozir yuborish (sinov)

Token va chat_id ~/abba-sheets-agent/.env dan (target hisoboti bilan bir xil); hech qayerga
yozilmaydi va logga chiqmaydi.
"""
from __future__ import annotations

import html
import json
import os
import plistlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from . import asos, sessiyalar

ENV = asos.HOME / "abba-sheets-agent" / ".env"
JADVAL = "com.abba.miya-xulosa"
PY = "/usr/bin/python3"


def sozlama() -> dict:
    d = asos.holat_oqi("xulosa")
    return {"yoqilgan": bool(d.get("yoqilgan")), "soat": d.get("soat") or "21:30",
            "oxirgi": d.get("oxirgi") or ""}


def sozla(yoqilgan: bool, soat: str | None = None) -> dict:
    d = asos.holat_oqi("xulosa")
    d["yoqilgan"] = yoqilgan
    if soat:      # «9:30» → «09:30»: kerakmi() vaqtni satr sifatida solishtiradi
        d["soat"] = datetime.strptime(soat.strip(), "%H:%M").strftime("%H:%M")
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


def tayyormi() -> bool:
    """.env da token va chat_id bormi (qiymatlarning o'zi hech qayerga chiqmaydi)."""
    e = _env()
    return bool(e.get("TELEGRAM_BOT_TOKEN") and e.get("TELEGRAM_CHAT_ID"))


# ---------------------------------------------------------------- launchd jadvali

def _joy() -> Path | None:
    """Yig'uvchi o'rnatilgan papka (launchd shu yerdan `python3 -m miya` qiladi). O'rnatilmagan
    bo'lsa None: jadval repo/worktree'ga bog'lanmasin — u o'chsa, jadval jimgina buziladi."""
    o = asos.HOME / ".abba-miya"
    return o if (o / "miya").is_dir() else None


def jadval_plist(soat: str, joy: Path) -> dict:
    """Xulosa soatida bitta to'liq yig'ish (kunning oxirgi sessiyalari ham kirsin), keyin xulosa.
    RunAtLoad yo'q: yoqilgan zahoti yuborib yubormasin."""
    s, d = (int(x) for x in soat.split(":"))
    return {
        "Label": JADVAL,
        "ProgramArguments": [PY, "-m", "miya"],
        "WorkingDirectory": str(joy),
        "EnvironmentVariables": {"PYTHONDONTWRITEBYTECODE": "1"},
        "StartCalendarInterval": {"Hour": s, "Minute": d},
        "Nice": 10,
        "LowPriorityIO": True,
        "StandardOutPath": str(joy / "launchd.log"),
        "StandardErrorPath": str(joy / "launchd.log"),
    }


def jadval_yangila(s: dict | None = None) -> str:
    """Sozlamaga moslab launchd jadvalini qo'yadi yoki olib tashlaydi."""
    s = s or sozlama()
    la = asos.HOME / "Library" / "LaunchAgents"
    p = la / f"{JADVAL}.plist"
    domen = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domen}/{JADVAL}"], capture_output=True)
    joy = _joy()
    if not s["yoqilgan"] or joy is None:
        p.unlink(missing_ok=True)
        if not s["yoqilgan"]:
            return "launchd jadvali yo'q (xulosa o'chiq)"
        return ("⚠️ yig'uvchi o'rnatilmagan (~/.abba-miya/miya yo'q) — avval "
                "`bash deploy/mac-sync/miya_install.sh`, jadval o'shanda qo'yiladi")
    la.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        plistlib.dump(jadval_plist(s["soat"], joy), f)
    xato = ""
    for _ in range(3):          # bootout'dan keyin launchd ba'zan bir zum band bo'ladi
        r = subprocess.run(["launchctl", "bootstrap", domen, str(p)], capture_output=True, text=True)
        if r.returncode == 0:
            return f"launchd {JADVAL}: har kuni {s['soat']} da"
        xato = (r.stderr or r.stdout).strip()
        time.sleep(1)
    asos.log(f"xulosa jadvali qo'yilmadi: {asos.bir_qator(xato, 200)}")
    return "⚠️ launchd jadvali qo'yilmadi (log) — xulosa soatlik yig'ish bilan chiqadi"


# ---------------------------------------------------------------- matn

def bugungi_yozuvlar(vault: Path, kun: str) -> dict:
    """`kun` (Toshkent vaqti) da o'zgargan .md yozuvlar: yig'uvchining avto sahifalari soni va
    qolganlari (kunlik, bilim, loyihalar — Claude, egasi yoki boshqa avtomatika yozgan), yangisi oldin."""
    avto, boshqa = 0, []
    for ildiz, papkalar, fayllar in os.walk(vault):
        papkalar[:] = [x for x in papkalar if not x.startswith(".") and x != "ilovalar"]
        for f in fayllar:
            if not f.endswith(".md"):
                continue
            p = Path(ildiz) / f
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if datetime.fromtimestamp(mt, asos.TZ).strftime("%Y-%m-%d") != kun:
                continue
            rel = p.relative_to(vault).as_posix()
            if any(rel == j or (j.endswith("/") and rel.startswith(j)) for j in asos.AVTO_JOYLAR):
                avto += 1
            else:
                boshqa.append((mt, rel[:-3]))
    return {"avto": avto, "boshqa": [r for _, r in sorted(boshqa, reverse=True)]}


def matn(sh: dict, vault: Path, kun: str) -> str:
    e = html.escape
    sesslar = [v for v in sh.values() if isinstance(v, dict) and (v.get("rel") or v.get("faol"))
               and kun in (v.get("sana") or [])]
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
    b = bugungi_yozuvlar(vault, kun)
    if b["boshqa"] or b["avto"]:
        q.append(f"📥 <b>Miyaga bugun:</b> {len(b['boshqa'])} yozuv"
                 + (f" (+{b['avto']} avto sahifa)" if b["avto"] else ""))
        q.extend(f"  • {e(r)}" for r in b["boshqa"][:5])
        if len(b["boshqa"]) > 5:
            q.append(f"  • … yana {len(b['boshqa']) - 5} ta")
    else:
        q.append("📥 <b>Miyaga bugun:</b> yangi yozuv yo'q")
    q.append("")
    q.append("Obsidian'da: <code>obsidian://open?vault=" + e(urllib.parse.quote(vault.name))
             + "&amp;file=BOSH-SAHIFA</code>")
    return "\n".join(q)


def xabar(sh: dict, vault: Path, kun: str) -> str:
    """Yuboriladigan matn: holat + hali yozilmagan bugungi faol sessiyalar."""
    return matn(sessiyalar.bugungi_faol(sh, kun), vault, kun)


def yubor(text: str, urinish: int = 4, kutish: float = 15.0) -> bool:
    env = _env()
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        asos.log("xulosa: TELEGRAM_BOT_TOKEN/CHAT_ID yo'q — yuborilmadi")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    for i in range(urinish):
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                        timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "replace")).get("ok") is True
        except urllib.error.HTTPError as ex:     # Telegram rad etdi — sababi logga (URL'da token bor, u yozilmaydi)
            try:
                sabab = json.loads(ex.read().decode("utf-8", "replace")).get("description") or ""
            except Exception:
                sabab = ""
            asos.log(f"xulosa: Telegram rad etdi ({ex.code}: {asos.bir_qator(sabab, 160)})")
            return False
        except urllib.error.URLError as ex:      # so'rov ketmadi: DNS/tarmoq hali yo'q (Mac endi uyg'ongan)
            if i + 1 < urinish:
                time.sleep(kutish)
                continue
            asos.log(f"xulosa: yuborilmadi — tarmoq yo'q ({type(ex.reason).__name__})")
            return False
        except Exception as ex:      # javob kelmadi — keyingi yig'ishda qayta urinadi
            asos.log(f"xulosa: yuborilmadi ({type(ex).__name__})")
            return False
    return False


def kerakmi(hozir: datetime | None = None) -> bool:
    s = sozlama()
    if not s["yoqilgan"]:
        return False
    hozir = hozir or datetime.now(asos.TZ)
    kun = hozir.strftime("%Y-%m-%d")
    if s["oxirgi"] == kun:
        return False
    return hozir.strftime("%H:%M") >= s["soat"]


def ishla(sh: dict, vault: Path, majburiy: bool = False, hozir: datetime | None = None) -> str:
    """Kerak bo'lsa yuboradi. Qaytadi: 'yuborildi' | 'kerak emas' | 'xato'.
    Kun faqat rejadagi yuborishda belgilanadi: soatdan oldingi sinov (--xulosa-yubor) kechki
    xulosani bekor qilmaydi, soatdan keyingi qo'lda yuborish esa soatlik yurishda takrorlanmaydi."""
    hozir = hozir or datetime.now(asos.TZ)
    rejali = kerakmi(hozir)          # soat o'tgan va bugun hali yuborilmagan
    if not majburiy and not rejali:
        return "kerak emas"
    kun = hozir.strftime("%Y-%m-%d")
    if yubor(xabar(sh, vault, kun)):
        if rejali:
            d = asos.holat_oqi("xulosa")
            d["oxirgi"] = kun
            asos.holat_yoz("xulosa", d)
        return "yuborildi"
    return "xato"
