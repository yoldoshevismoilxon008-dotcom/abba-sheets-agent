"""Markaziy sahifalar (hub) — vault bo'ylab navigatsiya:

  BOSH-SAHIFA.md                  — bosh dashboard (Obsidian'da birinchi ochiladi)
  claude/INDEX.md                 — Claude ishlari: oylar, loyihalar, so'nggi sessiyalar
  claude/sessiyalar/YYYY-MM.md    — oy bo'yicha sessiyalar (kunlarga bo'lingan)
  tizim/loyihalar.md              — barcha loyihalar va ularning xulosalari (natija.md)
  tizim/*.base                    — Obsidian Bases jadvallari (faqat Obsidian uchun; git'ga
                                    tushmaydi — .kbignore'da *.base)

Barqarorlik: soat/daqiqa yozilmaydi — sahifa faqat yangi ma'lumot kelganda o'zgaradi.
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from pathlib import Path

from . import asos

# loyiha papkasi emas: bular tizim yoki umumiy bo'limlar
_TIZIM_PAPKALAR = {"kunlik", "bilim", "odam", "chat", "claude", "kod", "wall-e", "tizim"}


def _sessiyalar(sh: dict) -> list:
    s = [v for v in sh.values() if isinstance(v, dict) and v.get("rel")]
    return sorted(s, key=lambda x: (x.get("oxiri") or x.get("boshi") or "", x["rel"]), reverse=True)


def _sess_qator(v: dict) -> str:
    qism = [v.get("loyiha") or ""]
    if v.get("sorovlar"):
        qism.append(f"{v['sorovlar']} so'rov")
    if v.get("commitlar"):
        qism.append(f"{v['commitlar']} commit")
    if v.get("artifactlar"):
        qism.append(f"{len(v['artifactlar'])} artifact")
    return f"{asos.wikilink(v['rel'], v.get('sarlavha') or 'sessiya')} — " + " · ".join(x for x in qism if x)


def oy_indekslari(yozuvchi: asos.Yozuvchi, sh: dict) -> list:
    oylar: "OrderedDict[str, list]" = OrderedDict()
    for v in sorted(_sessiyalar(sh), key=lambda x: x.get("boshi") or ""):
        oylar.setdefault((v.get("boshi") or "nomalum")[:7], []).append(v)
    for oy, ro in oylar.items():
        kunlar: "OrderedDict[str, list]" = OrderedDict()
        for v in ro:
            kunlar.setdefault((v.get("boshi") or "")[:10], []).append(v)
        fm = {"turi": "claude-oy", "oy": oy, "sessiyalar": len(ro), "tags": ["claude/sessiya"]}
        q = [asos.frontmatter(fm), f"# Claude sessiyalari — {oy}\n", asos.avto_izoh("oy bo'yicha sessiyalar"), "",
             f"{len(ro)} ta sessiya. Shu oydagi terminal so'rovlari: "
             + asos.wikilink(f"claude/sorovlar/{oy}", f"{oy} so'rovlari") + ".\n"]
        for kun, vs in sorted(kunlar.items(), reverse=True):
            kl = asos.wikilink(f"kunlik/{kun}", kun) if (yozuvchi.vault / "kunlik" / f"{kun}.md").exists() else kun
            q.append(f"## {kl}\n")
            q.extend(f"- {_sess_qator(v)}" for v in vs)
            q.append("")
        q.append(asos.QOLDA_BLOK)
        yozuvchi.yoz(f"claude/sessiyalar/{oy}.md", "\n".join(q))
    return list(oylar)


def claude_index(yozuvchi: asos.Yozuvchi, sh: dict, oylar: list, sorov_oylar: dict,
                 skill_soni: int, art_soni: int) -> None:
    ss = _sessiyalar(sh)
    loy = Counter(v.get("loyiha") or "?" for v in ss)
    narx = sum(float(v["narx_usd"]) for v in ss if isinstance(v.get("narx_usd"), (int, float)))
    fm = {"turi": "claude-index", "sessiyalar": len(ss), "skillar": skill_soni, "artifactlar": art_soni,
          "tags": ["claude"]}
    q = [asos.frontmatter(fm), "# Claude bilan qilingan ishlar\n", asos.avto_izoh("Claude ishlari markazi"), "",
         f"- **Sessiyalar:** {len(ss)} ta (transkriptdan) · **Skillar:** "
         + asos.wikilink("claude/skillar/INDEX", f"{skill_soni} ta")
         + " · **Artifactlar:** " + asos.wikilink("claude/artifactlar", f"{art_soni} ta")
         + " · **Sozlamalar:** " + asos.wikilink("claude/sozlamalar", "hook, mod, MCP"),
         f"- **Sessiyalar hajmi:** API narxi bo'yicha ${narx:,.0f} (obunada alohida to'lanmaydi — "
         "ishning og'irligini solishtirish uchun)",
         "- Claude transkriptlari diskda ~30 kun saqlanadi (qayta ochilgan sessiyalar qoladi); "
         "yig'uvchi har soatda ularni shu yerga ko'chiradi — manba o'chsa ham yozuv qoladi. "
         "Faol sessiya 45 daqiqa jim turgach yoziladi.\n"]
    q.append("## Oylar\n")
    q.append("| Oy | Sessiyalar | Terminal so'rovlari |\n|---|---|---|")
    hamma_oy = sorted(set(oylar) | set(sorov_oylar), reverse=True)
    for oy in hamma_oy:
        s_n = sum(1 for v in ss if (v.get("boshi") or "")[:7] == oy)
        s_l = asos.wikilink(f"claude/sessiyalar/{oy}", str(s_n)) if s_n else "—"
        r_l = asos.wikilink(f"claude/sorovlar/{oy}", str(sorov_oylar[oy])) if oy in sorov_oylar else "—"
        q.append(f"| {oy} | {s_l} | {r_l} |")
    q.append("")
    if loy:
        q.append("## Loyihalar bo'yicha\n")
        for nom, n in loy.most_common():
            nl = nom if nom in ("papkasiz", "uy", "vaqtinchalik", "nomalum") else asos.wikilink(f"kod/{asos.slug(nom, 60)}", nom)
            q.append(f"- {nl} — {n} sessiya")
        q.append("")
    q.append("## So'nggi sessiyalar\n")
    q.extend(f"- {(v.get('oxiri') or '')[:10]} · {_sess_qator(v)}" for v in ss[:20])
    q.append("")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("claude/INDEX.md", "\n".join(q))


def _birinchi_abzas(p: Path, n: int = 260) -> str:
    try:
        matn = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    matn = re.sub(r"^---[\s\S]*?\n---\n", "", matn)
    for abzas in re.split(r"\n\s*\n", matn):
        a = abzas.strip()
        if not a or a.startswith(("#", "```", "|", "---", "![")):
            continue
        a = re.sub(r"^>\s*", "", a, flags=re.M)
        return asos.bir_qator(a, n)
    return ""


def loyihalar(yozuvchi: asos.Yozuvchi) -> int:
    """Qo'lda yuritiladigan loyiha papkalari va ularning xulosasi (natija → holat → jarayon)."""
    v = yozuvchi.vault
    royxat = []
    for d in sorted(v.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in _TIZIM_PAPKALAR:
            continue
        mdlar = sorted(d.glob("*.md"))
        if not mdlar:
            continue
        asosiy = next((d / f for f in ("natija.md", "holat.md", "jarayon.md") if (d / f).exists()), mdlar[0])
        rel = asosiy.relative_to(v).as_posix()
        royxat.append((d.name, rel, _birinchi_abzas(asosiy), len(list(d.rglob("*.md")))))
    fm = {"turi": "loyihalar-index", "loyihalar": len(royxat), "tags": ["loyiha"]}
    q = [asos.frontmatter(fm), "# Loyihalar va xulosalar\n",
         asos.avto_izoh("har loyihaning asosiy yozuvi (natija → holat → jarayon) va birinchi xulosasi"), "",
         "| Loyiha | Xulosa | Yozuvlar |\n|---|---|---|"]
    for nom, rel, xulosa, n in royxat:
        q.append(f"| {asos.wikilink(rel, nom)} | {asos.redakt(xulosa) or '—'} | {n} |")
    q.append("")
    bilim = sorted((v / "bilim").glob("*.md")) if (v / "bilim").is_dir() else []
    if bilim:
        q.append(f"## Bilim yozuvlari ({len(bilim)})\n")
        for b in bilim:
            q.append(f"- {asos.wikilink('bilim/' + b.stem, b.stem)} — {asos.redakt(_birinchi_abzas(b, 160))}")
        q.append("")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("tizim/loyihalar.md", "\n".join(q))
    return len(royxat)


_BASELAR = {
    "tizim/Claude sessiyalari.base": """filters:
  and:
    - 'turi == "claude-sessiya"'
views:
  - type: table
    name: Barcha sessiyalar
    order:
      - file.name
      - sana
      - loyiha
      - sorovlar
      - commitlar
      - artifactlar
      - narx_usd
    sort:
      - property: sana
        direction: DESC
  - type: table
    name: Loyiha bo'yicha
    groupBy:
      property: loyiha
      direction: ASC
    order:
      - file.name
      - sana
      - sorovlar
      - commitlar
    sort:
      - property: sana
        direction: DESC
""",
    "tizim/Skillar.base": """filters:
  and:
    - 'turi == "skill"'
views:
  - type: table
    name: Skillar
    groupBy:
      property: kelib_chiqishi
      direction: ASC
    order:
      - file.name
      - ishlatilgan
      - yangilangan
      - qayerdan
    sort:
      - property: ishlatilgan
        direction: DESC
""",
    "tizim/Kod loyihalari.base": """filters:
  and:
    - 'turi == "kod-loyiha"'
views:
  - type: table
    name: Kod
    order:
      - file.name
      - oxirgi_commit
      - branch
      - sessiyalar
      - toza
      - yol
    sort:
      - property: oxirgi_commit
        direction: DESC
""",
    "tizim/WALL-E kunlari.base": """filters:
  and:
    - 'turi == "wall-e-kun"'
views:
  - type: table
    name: Kunlar
    order:
      - file.name
      - sana
      - hisobot
      - chat_xabarlar
      - target_obunachi
    sort:
      - property: sana
        direction: DESC
""",
}


def baselar(yozuvchi: asos.Yozuvchi) -> None:
    for rel, yaml in _BASELAR.items():
        yozuvchi.yoz(rel, asos.BELGI_BASE + " — miya yig'uvchisi yaratgan; Obsidian'da o'zgartirsangiz, "
                     "yig'uvchi bu faylga boshqa tegmaydi\n" + yaml)


def bosh_sahifa(yozuvchi: asos.Yozuvchi, sh: dict, raqamlar: dict) -> None:
    v = yozuvchi.vault
    bugun = asos.bugun()
    ss = _sessiyalar(sh)
    bugungi = [x for x in ss if bugun in (x.get("sana") or [])]
    kunliklar = sorted(p.stem for p in (v / "kunlik").glob("*.md")) if (v / "kunlik").is_dir() else []
    bilim_n = len(list((v / "bilim").glob("*.md"))) if (v / "bilim").is_dir() else 0
    fm = {"turi": "bosh-sahifa", "tags": ["miya"]}
    q = [asos.frontmatter(fm), "# 🧠 Ikkinchi miya — Bosh sahifa\n",
         asos.avto_izoh("markaziy dashboard; har soatda yangilanadi"), ""]
    q.append(f"## 📅 Bugun — {bugun}\n")
    if (v / "kunlik" / f"{bugun}.md").exists():
        q.append(f"- 📓 Kunlik yozuv: {asos.wikilink('kunlik/' + bugun, bugun)}")
    if (v / "wall-e" / "kunlar" / f"{bugun}.md").exists():
        q.append(f"- 🤖 WALL-E kuni: {asos.wikilink('wall-e/kunlar/' + bugun, bugun)}")
    if bugungi:
        q.append(f"- 💬 Bugungi Claude sessiyalari ({len(bugungi)}):")
        q.extend(f"  - {_sess_qator(x)}" for x in bugungi[:12])
    else:
        q.append("- 💬 Bugun hali Claude sessiyasi yozilmagan.")
    q.append("")
    q.append("## 🗂️ Bo'limlar\n")
    q.append("| Bo'lim | Nima bor |\n|---|---|")
    q.append(f"| {asos.wikilink('INDEX', '📌 INDEX')} | Asosiy indeks: loyihalar, bilim, ochiq iplar (qo'lda yuritiladi) |")
    q.append(f"| {asos.wikilink('claude/INDEX', '💬 Claude ishlari')} | {raqamlar.get('sessiyalar', 0)} sessiya, "
             f"so'rovlar tarixi, {raqamlar.get('artifactlar', 0)} artifact |")
    q.append(f"| {asos.wikilink('claude/skillar/INDEX', '🧩 Skillar')} | {raqamlar.get('skillar', 0)} ta skill va sozlamalar |")
    q.append(f"| {asos.wikilink('kod/INDEX', '💻 Kod')} | {raqamlar.get('kod', 0)} ta loyiha papkasi |")
    q.append(f"| {asos.wikilink('wall-e/INDEX', '🤖 WALL-E')} | bot hisobotlari, suhbatlar, target va kunlik ishlar |")
    q.append(f"| {asos.wikilink('tizim/loyihalar', '🎯 Loyihalar va xulosalar')} | {raqamlar.get('loyihalar', 0)} ta loyiha, {bilim_n} ta bilim yozuvi |")
    q.append(f"| {asos.wikilink('tizim/avtomatika', '⚙️ Avtomatika')} | Mac va Railway'dagi barcha rejalashtirilgan ishlar |")
    q.append(f"| {asos.wikilink('odam/profil', '👤 Profil')} | asosiy kontekst |")
    q.append("")
    q.append("## 💬 So'nggi Claude sessiyalari\n")
    q.extend(f"- {(x.get('oxiri') or '')[:10]} · {_sess_qator(x)}" for x in ss[:10])
    q.append("")
    q.append("## 📊 Obsidian jadvallari\n")
    q.append("![[tizim/Claude sessiyalari.base]]\n")
    q.append("Boshqa jadvallar: " + " · ".join(asos.wikilink(r[:-5] + ".base", Path(r).stem) for r in _BASELAR) + "\n")
    q.append("## 🔢 Raqamlarda\n")
    if kunliklar:
        q.append(f"- Kunlik yozuvlar: **{len(kunliklar)}** ({kunliklar[0]} → {kunliklar[-1]})")
    q.append(f"- Bilim: **{bilim_n}** · Loyihalar: **{raqamlar.get('loyihalar', 0)}** · "
             f"Claude sessiyalari: **{raqamlar.get('sessiyalar', 0)}** · Skillar: **{raqamlar.get('skillar', 0)}** · "
             f"Kod: **{raqamlar.get('kod', 0)}** · Artifactlar: **{raqamlar.get('artifactlar', 0)}**")
    q.append("")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("BOSH-SAHIFA.md", "\n".join(q))
