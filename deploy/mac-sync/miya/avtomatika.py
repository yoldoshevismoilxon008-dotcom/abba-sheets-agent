"""Avtomatika xaritasi → vault `tizim/avtomatika.md`.

Mac: ~/Library/LaunchAgents/com.abba.*.plist (+ diktovka) — jadval, skript, log, yuklanganmi,
oxirgi chiqish kodi (`launchctl list`). Railway (WALL-E): supervisor.py dagi jadval — bu yerda
qo'lda yuritiladigan ro'yxat (kamdan-kam o'zgaradi; o'zgarsa shu faylni yangilang).
Claude ilovasidagi rejalashtirilgan vazifalar — claude/sozlamalar.md da.
"""
from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from . import asos

# WALL-E (Railway, supervisor.py, TZ Asia/Tashkent). Manba: origin/main supervisor.py.
RAILWAY = [
    ("09:00", "Kunlik pipeline", "Sheets fetch → diff → tahlil → PDF → Telegram → hisobotlar repo → Dashboard"),
    ("09:30", "PM undiruv eslatmalari", "egasining akkauntidan PM'larga (userbot)"),
    ("09:00–12:00, har soat", "WOW ertalabki so'rov", "kunlik reja so'raladi (ovoz yoki matn)"),
    ("19:00–21:00, har soat", "WOW kechki so'rov", "kunlik hisobot so'raladi"),
    ("har daqiqa", "WOW avto-yuborish", "15 daqiqa jim turgan qoralama boshliqqa ketadi"),
    ("12:00", "TG kunlik nazorati", "Mac'dagi TG hisobot kelganini tekshiradi"),
    ("har 10 daqiqa", "Vault → bilim bazasi", "claude-brain repo'dan o'zgargan .md lar KB'ga (vault_sync)"),
    ("har 10 daqiqa", "Chat arxivi", "Q&A suhbatlari → abba-hisobotlar repo → Mac vault'ga (chat/)"),
    ("ishga tushganda", "Catch-up", "o'tib ketgan 09:00 / so'rovlar qayta bajariladi"),
]


def _jadval(d: dict) -> str:
    if d.get("StartCalendarInterval"):
        sci = d["StartCalendarInterval"]
        sci = sci if isinstance(sci, list) else [sci]
        qism = []
        for x in sci:
            hafta = x.get("Weekday")
            vaqt = f"{x.get('Hour', 0):02d}:{x.get('Minute', 0):02d}"
            if hafta is not None:
                vaqt += f" (hafta kuni {hafta})"
            qism.append(vaqt)
        tartib = sorted(set(qism))
        return ", ".join(tartib[:6]) + (f" … (+{len(tartib) - 6})" if len(tartib) > 6 else "")
    if d.get("StartInterval"):
        s = int(d["StartInterval"])
        return f"har {s // 60} daqiqa" if s < 3600 else f"har {s // 3600} soat"
    if d.get("KeepAlive"):
        return "doim ishlaydi (KeepAlive)"
    if d.get("RunAtLoad"):
        return "yuklanganda bir marta"
    return "—"


def _skript(d: dict) -> str:
    args = d.get("ProgramArguments") or []
    for a in reversed(args):
        if any(a.endswith(e) for e in (".py", ".sh", ".js")):
            return asos.uy_yol(a)
    return asos.uy_yol(args[-1]) if args else "—"


def _launchctl() -> dict:
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    natija = {}
    for q in r.stdout.splitlines()[1:]:
        qism = q.split("\t")
        if len(qism) == 3:
            natija[qism[2]] = {"pid": qism[0], "holat": qism[1]}
    return natija


def mac_vazifalar() -> list:
    la = asos.HOME / "Library" / "LaunchAgents"
    yuklangan = _launchctl()
    natija = []
    for p in sorted(la.glob("*.plist")) if la.is_dir() else []:
        if not (p.name.startswith("com.abba.") or p.name.startswith("com.rubaistt.") or "miya" in p.name):
            continue
        try:
            with open(p, "rb") as f:
                d = plistlib.load(f)
        except Exception:
            continue
        label = d.get("Label") or p.stem
        y = yuklangan.get(label)
        natija.append({
            "label": label, "jadval": _jadval(d), "skript": _skript(d),
            "log": asos.uy_yol(d.get("StandardOutPath") or "") or "—",
            "yuklangan": bool(y), "chiqish": (y or {}).get("holat", ""),
        })
    return natija


def yigish(yozuvchi: asos.Yozuvchi) -> dict:
    mac = mac_vazifalar()
    fm = {"turi": "avtomatika", "mac_vazifalar": len(mac), "railway_vazifalar": len(RAILWAY),
          "tags": ["tizim"]}
    q = [asos.frontmatter(fm), "# ⚙️ Avtomatika — hamma rejalashtirilgan ishlar\n",
         asos.avto_izoh("Mac launchd va Railway jadvali"), ""]
    q.append("## Mac (launchd)\n")
    q.append("Mac uyquda bo'lsa vazifa uyg'onganda ishlaydi. O'chiq qatorlar — zaxira (rollback) nusxalar.\n")
    q.append("| Vazifa | Jadval | Skript | Holat |\n|---|---|---|---|")
    for v in mac:
        if not v["yuklangan"]:
            holat = "o'chiq"
        elif v["chiqish"] in ("0", "-", ""):
            holat = "✅ yuklangan"
        else:
            holat = f"⚠️ oxirgi chiqish kodi {v['chiqish']}"
        q.append(f"| `{v['label']}` | {v['jadval']} | `{v['skript']}` | {holat} |")
    q.append("")
    q.append("## Railway — WALL-E (supervisor.py, Toshkent vaqti)\n")
    q.append("| Vaqt | Vazifa | Nima qiladi |\n|---|---|---|")
    q.extend(f"| {a} | {b} | {c} |" for a, b, c in RAILWAY)
    q.append("")
    q.append("Bog'liq: " + " · ".join([asos.wikilink("abba-sheets-agent/holat", "WALL-E holati"),
                                       asos.wikilink("tg-kunlik-monitoring/jarayon", "TG monitoring"),
                                       asos.wikilink("claude/sozlamalar", "Claude vazifalari"),
                                       asos.wikilink("kod/INDEX", "kod")]) + "\n")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("tizim/avtomatika.md", "\n".join(q))
    return {"mac": len(mac)}
