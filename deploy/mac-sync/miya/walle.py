"""WALL-E kunlik ma'lumotlari → vault `wall-e/kunlar/YYYY-MM-DD.md` + `wall-e/INDEX.md`.

Bir kunlik yozuv WALL-E o'sha kuni qilgan hamma narsani bitta joyga bog'laydi:
  - kunlik reja va hisobot (WOW) — chat arxividagi «WOW kunlik … yuborildi» qatorlari;
  - 09:00 Sheets hisoboti — `abba-sheets-agent/hisobotlar/<sana>.md` (bo'lim sarlavhalari);
  - Q&A suhbatlar — `chat/<sana>.md` (savollar ro'yxati);
  - TG kunlik PDF — `tg-kunlik-monitoring/hisobotlar/<sana>.pdf`;
  - target va organik obunachilar (18:30) — `target_hisobot.py --sinov --yigmasdan`
    (faqat o'qiydi: Telegram'ga yubormaydi, guruhlardan yig'maydi); natija keshda saqlanadi;
  - Instagram o'lchovi — `~/.abba-tg-audit/state/ig_obunachi/<sana>.json`;
  - o'sha kuni Claude bilan qilingan sessiyalar.

Ma'lumotning o'zi allaqachon vault'da bo'lsa (hisobot, chat) — bu yerda faqat qisqa ko'rinish
va havola: bilim bazasida takror ko'paymasin.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from . import asos

TURI = "wall-e-kun"
PAPKA = "wall-e/kunlar"
KUNLAR_ORQAGA = 7          # har yurishda oxirgi N kun qayta tekshiriladi
_HAFTA = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
_WOW = re.compile(r"^- (\d{2}:\d{2}) · WOW kunlik (reja|hisobot) \((\d{4}-\d{2}-\d{2})\) yuborildi: (.+)$")


def tg_audit() -> Path:
    return Path(os.environ.get("MIYA_TG_AUDIT") or asos.HOME / ".abba-tg-audit")


# ---------------------------------------------------------------- manbalar

def chat_oqi(vault: Path, kun: str) -> dict:
    p = vault / "chat" / f"{kun}.md"
    natija = {"bor": p.exists(), "savollar": [], "buyruqlar": [], "wow": []}
    if not p.exists():
        return natija
    try:
        qatorlar = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return natija
    for i, q in enumerate(qatorlar):
        m = _WOW.match(q)
        if m:
            natija["wow"].append({"vaqt": m.group(1), "tur": m.group(2), "sana": m.group(3),
                                  "bandlar": [b.strip() for b in m.group(4).split(";") if b.strip()]})
            continue
        m = re.match(r"^## (\d{2}:\d{2}) · Savol\s*$", q)
        if m:
            matn = ""
            for k in qatorlar[i + 1:i + 6]:
                if k.startswith("## "):
                    break
                if k.strip():
                    matn = k.strip()
                    break
            natija["savollar"].append((m.group(1), matn))
            continue
        m = re.match(r"^- (\d{2}:\d{2}) · (/\S+)", q)
        if m:
            natija["buyruqlar"].append((m.group(1), m.group(2)))
    return natija


def hisobot_oqi(vault: Path, kun: str) -> dict:
    p = vault / "abba-sheets-agent" / "hisobotlar" / f"{kun}.md"
    natija = {"bor": p.exists(), "bolimlar": []}
    if not p.exists():
        return natija
    try:
        matn = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return natija
    for m in re.finditer(r"^▸ \*\*(.+?)\*\*\s*\n((?:- .*\n?){0,1})", matn, flags=re.M):
        birinchi = m.group(2).strip()[2:] if m.group(2).strip().startswith("- ") else ""
        natija["bolimlar"].append((m.group(1).strip(), birinchi))
    return natija


def ig_oqi(kun: str) -> dict:
    p = tg_audit() / "state" / "ig_obunachi" / f"{kun}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ob = d.get("obunachi") if isinstance(d, dict) else None
    if not isinstance(ob, dict):
        return {}
    sonlar = [v for v in ob.values() if isinstance(v, (int, float))]
    return {"akkauntlar": len(sonlar), "jami": int(sum(sonlar)), "manba": d.get("manba") or ""}


def _tg_html_md(matn: str) -> str:
    t = matn or ""
    t = re.sub(r"</?b>", "**", t)
    t = re.sub(r"</?i>", "_", t)
    t = re.sub(r"</?code>", "`", t)
    t = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"[\2](\1)", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


def target_oqi(kun: str, hozir: datetime) -> str | None:
    """`kun` uchun target hisobotining matni. Hisobot kun+1 18:30 da tuziladi, shuning uchun
    undan oldin None. Kesh: state/walle_target/<kun>.md (bir marta hisoblanadi)."""
    kesh = asos.state_dir() / "walle_target" / f"{kun}.md"
    if kesh.exists():
        try:
            return kesh.read_text(encoding="utf-8") or None
        except OSError:
            return None
    d = date.fromisoformat(kun)
    tayyor = datetime(d.year, d.month, d.day, 18, 45, tzinfo=asos.TZ) + timedelta(days=1)
    if hozir < tayyor or d.weekday() == 6:        # yakshanba — target hisobotlari deyarli yo'q
        return None
    skript = tg_audit() / "target_hisobot.py"
    if not skript.exists():
        return None
    try:
        r = subprocess.run(["/usr/bin/python3", str(skript), "--sinov", "--yigmasdan", "--sana", kun],
                           capture_output=True, text=True, timeout=180, cwd=str(tg_audit()))
    except (OSError, subprocess.SubprocessError) as e:
        asos.log(f"walle: target {kun} olinmadi: {type(e).__name__}")
        return None
    if r.returncode != 0 or not r.stdout.strip():
        asos.log(f"walle: target {kun} — chiqish {r.returncode}")
        return None
    toza = "\n".join(q for q in r.stdout.splitlines()
                     if not re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[target\]", q))
    md = asos.redakt(_tg_html_md(toza))
    kesh.parent.mkdir(parents=True, exist_ok=True)
    kesh.write_text(md, encoding="utf-8")
    return md


def _target_jami(md: str) -> int | None:
    t = (md or "").replace("**", "")
    m = re.search(r"(?im)^target:\s*\+\s*([\d \u00a0\u202f]{1,12})\s*obunachi", t)
    if not m:
        m = re.search(r"\+\s*([\d \u00a0\u202f]{2,12})\s*obunachi", t)
    if not m:
        return None
    try:
        return int(re.sub(r"\D", "", m.group(1)))
    except ValueError:
        return None


# ---------------------------------------------------------------- yozuv

def kun_matni(vault: Path, kun: str, chat: dict, hisob: dict, ig: dict, target: str | None,
              sesslar: list) -> str:
    d = date.fromisoformat(kun)
    pdf = vault / "tg-kunlik-monitoring" / "hisobotlar" / f"{kun}.pdf"
    fm = {
        "turi": TURI, "sana": kun, "hisobot": hisob["bor"], "chat_xabarlar": len(chat["savollar"]),
        "wow": len(chat["wow"]), "tg_pdf": pdf.exists(), "ig_akkauntlar": ig.get("akkauntlar"),
        "target_obunachi": _target_jami(target) if target else None,
        "claude_sessiyalar": len(sesslar), "tags": ["wall-e"],
    }
    q = [asos.frontmatter(fm), f"# WALL-E — {kun} ({_HAFTA[d.weekday()]})\n",
         asos.avto_izoh("WALL-E kunlik yig'indisi"), ""]
    boglar = []
    if (vault / "kunlik" / f"{kun}.md").exists():
        boglar.append(asos.wikilink(f"kunlik/{kun}", "Kunlik yozuv"))
    if chat["bor"]:
        boglar.append(asos.wikilink(f"chat/{kun}", "Suhbat arxivi"))
    if hisob["bor"]:
        boglar.append(asos.wikilink(f"abba-sheets-agent/hisobotlar/{kun}", "09:00 hisobot"))
    if pdf.exists():
        boglar.append(f"[[tg-kunlik-monitoring/hisobotlar/{kun}.pdf|TG kunlik PDF]]")
    if boglar:
        q.append("**Manbalar:** " + " · ".join(boglar) + "\n")

    if chat["wow"]:
        q.append("## 🗓️ Kunlik reja va hisobot\n")
        for w in chat["wow"]:
            sarl = "Ertalabki reja" if w["tur"] == "reja" else "Kechki hisobot"
            q.append(f"**{sarl}** ({w['vaqt']}, boshliqqa yuborildi):")
            q.extend(f"- {asos.bir_qator(asos.redakt(b), 200)}" for b in w["bandlar"])
            q.append("")

    if hisob["bolimlar"]:
        q.append("## 📊 09:00 Sheets hisoboti\n")
        for sar, birinchi in hisob["bolimlar"][:12]:
            q.append(f"- **{asos.bir_qator(sar, 80)}**" + (f" — {asos.bir_qator(birinchi, 220)}" if birinchi else ""))
        q.append("")

    if target:
        q.append("## 🎯 Target va organik obunachilar (ertasi kuni 18:30 hisoboti)\n")
        q.append(target.strip() + "\n")
    if ig:
        q.append("## 📈 Instagram o'lchovi\n")
        q.append(f"- {ig['akkauntlar']} ta akkaunt o'lchandi, jami {format(ig['jami'], ',').replace(',', ' ')} obunachi"
                 + (f" (manba: {ig['manba']})" if ig.get("manba") else "") + "\n")

    if chat["savollar"] or chat["buyruqlar"]:
        q.append(f"## 💬 WALL-E bilan suhbat ({len(chat['savollar'])} savol)\n")
        for vaqt, matn in chat["savollar"][:25]:
            q.append(f"- {vaqt} — {asos.bir_qator(asos.redakt(matn), 160)}")
        if chat["buyruqlar"]:
            q.append("- Buyruqlar: " + ", ".join(f"`{b}`" for _, b in chat["buyruqlar"][:15]))
        q.append("")

    if sesslar:
        q.append(f"## 💻 Shu kuni Claude bilan ({len(sesslar)})\n")
        for v in sesslar:
            q.append(f"- {asos.wikilink(v['rel'], v.get('sarlavha') or 'sessiya')} — {v.get('loyiha') or ''}")
        q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def index_matni(kunlar: list) -> str:
    fm = {"turi": "wall-e-index", "kunlar": len(kunlar), "tags": ["wall-e"]}
    q = [asos.frontmatter(fm), "# 🤖 WALL-E — ikkinchi miyaning ijrochisi\n",
         asos.avto_izoh("WALL-E bo'limi markazi"), "",
         "WALL-E (Telegram bot, Railway) har kuni ishlaydi: 09:00 Sheets hisoboti, kunlik reja va "
         "hisobot (WOW), Q&A, 18:30 target hisoboti. Mac tomonida TG monitoring va Instagram o'lchovi. "
         "Bu bo'lim ularning hammasini kunma-kun bitta joyga bog'laydi; bot esa vault'ni bilim "
         "bazasi sifatida o'qiydi (har 10 daqiqada sinxron).\n",
         "**Asosiy yozuvlar:** " + " · ".join([
             asos.wikilink("abba-sheets-agent/holat", "joriy holat"),
             asos.wikilink("abba-sheets-agent/natija", "tavsif"),
             asos.wikilink("abba-sheets-agent/kalit-sozlar", "kalit so'zlar"),
             asos.wikilink("tg-kunlik-monitoring/jarayon", "TG monitoring"),
             asos.wikilink("tizim/avtomatika", "avtomatika")]) + "\n",
         "## Kunlar\n",
         "| Sana | Reja/hisobot | 09:00 | Suhbat | Target | TG PDF |\n|---|---|---|---|---|---|"]
    for k in kunlar[:60]:
        q.append(f"| {asos.wikilink(PAPKA + '/' + k['sana'], k['sana'])} | {k['wow'] or '—'} | "
                 f"{'✅' if k['hisobot'] else '—'} | {k['chat'] or '—'} | "
                 f"{k['target'] if k['target'] is not None else '—'} | {'✅' if k['pdf'] else '—'} |")
    q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def yigish(yozuvchi: asos.Yozuvchi, sessiya_holat: dict | None = None, hammasi: bool = False,
           hozir: datetime | None = None) -> dict:
    v = yozuvchi.vault
    sh = sessiya_holat if sessiya_holat is not None else asos.holat_oqi("sessiyalar")
    hozir = hozir or datetime.now(asos.TZ)
    bugun = hozir.date()
    if hammasi:
        sanalar = set()
        for papka, ext in (("chat", ".md"), ("abba-sheets-agent/hisobotlar", ".md"),
                           ("tg-kunlik-monitoring/hisobotlar", ".pdf")):
            for p in (v / papka).glob(f"20??-??-??{ext}") if (v / papka).is_dir() else []:
                sanalar.add(p.stem)
        kunlar = sorted(sanalar)
    else:
        kunlar = [(bugun - timedelta(days=i)).isoformat() for i in range(KUNLAR_ORQAGA)][::-1]
    natija = []
    for kun in kunlar:
        chat = chat_oqi(v, kun)
        hisob = hisobot_oqi(v, kun)
        ig = ig_oqi(kun)
        target = target_oqi(kun, hozir) if not hammasi or kun >= (bugun - timedelta(days=14)).isoformat() else None
        sesslar = sorted((x for x in sh.values() if isinstance(x, dict) and x.get("rel") and kun in (x.get("sana") or [])),
                         key=lambda x: (x.get("boshi") or "", x["rel"]))
        pdf = (v / "tg-kunlik-monitoring" / "hisobotlar" / f"{kun}.pdf").exists()
        if not (chat["bor"] or hisob["bor"] or ig or target or pdf):
            continue
        yozuvchi.yoz(f"{PAPKA}/{kun}.md", kun_matni(v, kun, chat, hisob, ig, target, sesslar))
    # index — vault'dagi barcha kun yozuvlari bo'yicha
    for p in sorted((v / PAPKA).glob("20??-??-??.md"), reverse=True) if (v / PAPKA).is_dir() else []:
        try:
            fm = asos.fm_oqi(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        natija.append({"sana": p.stem, "wow": fm.get("wow") if fm.get("wow") not in ("0", 0) else "",
                       "hisobot": fm.get("hisobot") == "true",
                       "chat": fm.get("chat_xabarlar") if fm.get("chat_xabarlar") not in ("0", 0) else "",
                       "target": fm.get("target_obunachi"), "pdf": fm.get("tg_pdf") == "true"})
    if not yozuvchi.quruq or natija:
        yozuvchi.yoz("wall-e/INDEX.md", index_matni(natija))
    return {"kunlar": len(natija)}
