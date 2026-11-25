"""Claude CLI so'rovlar tarixi → vault `claude/sorovlar/YYYY-MM.md`.

Manba: ~/.claude/history.jsonl — terminaldagi Claude Code'ga yozilgan har so'rov
(display, project, sessionId, timestamp). Sessiya transkriptlari ~10 kunda o'chib
ketadi, bu fayl esa aprel 2026 dan beri saqlanib qolgan: eski ishlar tarixini shu tiklaydi.
Joylangan matnlar (pastedContents) yozilmaydi — faqat so'rovning o'zi, maxfiy qiymatlar yashirilgan.
"""
from __future__ import annotations

import json
from collections import OrderedDict

from . import asos

TURI = "claude-sorovlar"
PAPKA = "claude/sorovlar"


def oqi(claude=None) -> "OrderedDict[str, list]":
    """Oy → [(vaqt, loyiha, matn)], vaqt bo'yicha tartiblangan."""
    p = (claude or asos.claude_dir()) / "history.jsonl"
    oylar: "OrderedDict[str, list]" = OrderedDict()
    try:
        fh = open(p, encoding="utf-8", errors="replace")
    except OSError:
        return oylar
    yozuvlar = []
    with fh:
        for q in fh:
            try:
                d = json.loads(q)
            except ValueError:
                continue
            t = asos.ts_parse(d.get("timestamp"))
            matn = (d.get("display") or "").strip()
            if not t or not matn:
                continue
            yozuvlar.append((t, d.get("project") or "", matn))
    yozuvlar.sort(key=lambda x: x[0])
    for t, proj, matn in yozuvlar:
        oylar.setdefault(asos.vaqt_str(t, True)[:7], []).append((t, proj, matn))
    return oylar


def oy_matni(oy: str, yozuvlar: list) -> str:
    kunlar: "OrderedDict[str, list]" = OrderedDict()
    for t, proj, matn in yozuvlar:
        kunlar.setdefault(asos.vaqt_str(t, True), []).append((t, proj, matn))
    fm = {"turi": TURI, "oy": oy, "sorovlar": len(yozuvlar), "kunlar": len(kunlar),
          "tags": ["claude/sorov"]}
    q = [asos.frontmatter(fm), f"# Claude so'rovlari — {oy}\n",
         asos.avto_izoh("terminaldagi Claude Code so'rovlari tarixi (~/.claude/history.jsonl)"), "",
         f"{len(yozuvlar)} ta so'rov, {len(kunlar)} kun. Sessiya yozuvlari: "
         + asos.wikilink(f"claude/sessiyalar/{oy}", f"{oy} sessiyalari") + ".\n"]
    for kun, ro in kunlar.items():
        q.append(f"## {kun}\n")
        for t, proj, matn in ro:
            joy = asos.uy_yol(proj) if proj else ""
            joy_s = f" `{joy}`" if joy and joy != "~" else ""
            q.append(f"- **{asos.mahalliy(t).strftime('%H:%M')}**{joy_s} — "
                     f"{asos.bir_qator(asos.redakt(matn), 300)}")
        q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def yigish(yozuvchi: asos.Yozuvchi) -> dict:
    oylar = oqi()
    for oy, yoz in oylar.items():
        yozuvchi.yoz(f"{PAPKA}/{oy}.md", oy_matni(oy, yoz))
    return {"oylar": {k: len(v) for k, v in oylar.items()}}
