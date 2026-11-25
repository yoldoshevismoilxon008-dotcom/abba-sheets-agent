"""Claude imkoniyatlari katalogi → vault `claude/skillar/<nom>.md` + `claude/sozlamalar.md`.

Manbalar:
  - ~/.claude/skills/<nom>/SKILL.md                  — lokal skillar
  - ~/.claude/skills/synced/<akkaunt>/<nom>/SKILL.md — claude.ai'dan sinxron (manifest.json
    `source`: anthropic | anthropic-example | plugin)
  - o'rnatilgan plaginlarning skillari (installed_plugins.json)
  - sessiyalarda chaqirilgan, lekin diskda yo'q ichki skillar (Claude ilovasi bilan keladi)
  - sozlamalar: hook'lar, modlar, rejalashtirilgan vazifalar, MCP server NOMLARI (qiymatsiz)

Kelib chiqishi: "o'zimizniki" — nomida/tavsifida ABBA bor yoki claude.ai'dagi o'z plagini;
"Anthropic" — rasmiy; "tashqi" — boshqa muallif; "ichki" — ilova bilan keladi.
"""
from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from pathlib import Path

from . import asos

TURI = "skill"
PAPKA = "claude/skillar"


def kalit(nom: str) -> str:
    """Skill nomini yagona kalitga keltiradi: 'anthropic-skills:pdf' → 'pdf',
    'shartnoma-pdf:shartnoma-pdf' → 'shartnoma-pdf', 'telegram:access' → 'telegram-access'."""
    nom = (nom or "").strip().lstrip("/")
    if ":" in nom:
        plagin, sk = nom.split(":", 1)
        if plagin == sk or plagin == "anthropic-skills":
            nom = sk
        else:
            nom = f"{plagin}-{sk}"
    return asos.slug(nom, 60)


def _fayllar_royxati(papka: Path, maks: int = 40):
    natija = []
    try:
        for p in sorted(papka.rglob("*")):
            if p.is_file() and not any(x.startswith(".") for x in p.relative_to(papka).parts):
                natija.append(p)
    except OSError:
        pass
    return natija


def _skill_ol(skill_md: Path, kelib: str, qayerdan: str) -> dict | None:
    try:
        matn = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = asos.fm_oqi(matn)
    papka = skill_md.parent
    fayllar = _fayllar_royxati(papka)
    try:
        yangilangan = max(p.stat().st_mtime for p in fayllar) if fayllar else skill_md.stat().st_mtime
    except OSError:
        yangilangan = None
    nom = (fm.get("name") or papka.name).strip()
    tavsif = (fm.get("description") or "").strip()
    if kelib == "lokal":
        kelib = "o'zimizniki" if ("abba" in nom.lower() or "ABBA" in tavsif) else "tashqi"
    return {
        "kalit": kalit(nom), "nom": nom, "tavsif": tavsif, "kelib": kelib, "qayerdan": qayerdan,
        "joyi": asos.uy_yol(papka), "fayllar": [str(p.relative_to(papka)) for p in fayllar],
        "hajm": sum(p.stat().st_size for p in fayllar if p.exists()),
        "yangilangan": asos.vaqt_str(asos.ts_parse(yangilangan), True) if yangilangan else "",
    }


def diskdagi_skillar(claude: Path | None = None) -> "OrderedDict[str, dict]":
    c = claude or asos.claude_dir()
    natija: "OrderedDict[str, dict]" = OrderedDict()

    # 1) lokal
    sk = c / "skills"
    if sk.is_dir():
        for d in sorted(sk.iterdir()):
            if d.is_dir() and d.name != "synced" and (d / "SKILL.md").exists():
                s = _skill_ol(d / "SKILL.md", "lokal", "~/.claude/skills")
                if s:
                    natija[s["kalit"]] = s

    # 2) claude.ai sinxron (manifest: source)
    for akk in sorted((sk / "synced").glob("*")) if (sk / "synced").is_dir() else []:
        manbalar = {}
        try:
            m = json.loads((akk / "manifest.json").read_text(encoding="utf-8"))
            for x in m.get("skills", []):
                manbalar[x.get("name")] = x.get("source") or ""
        except (OSError, ValueError):
            pass
        for d in sorted(akk.iterdir()) if akk.is_dir() else []:
            if not (d / "SKILL.md").exists():
                continue
            src = manbalar.get(d.name, "")
            kelib = ("o'zimizniki" if src == "plugin" else
                     "Anthropic" if src.startswith("anthropic") else "tashqi")
            s = _skill_ol(d / "SKILL.md", kelib, "claude.ai (sinxron)")
            if s and s["kalit"] not in natija:
                natija[s["kalit"]] = s

    # 3) o'rnatilgan plaginlar
    try:
        ip = json.loads((c / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        for pid, versiyalar in (ip.get("plugins") or {}).items():
            for v in versiyalar or []:
                ip_yol = Path(v.get("installPath") or "")
                for md in sorted(ip_yol.glob("skills/*/SKILL.md")):
                    s = _skill_ol(md, "tashqi", f"plagin {pid}")
                    if s:
                        plagin = pid.split("@", 1)[0]
                        s["kalit"] = kalit(f"{plagin}:{s['nom']}")
                        natija.setdefault(s["kalit"], s)
    except (OSError, ValueError):
        pass
    return natija


def _boglik_yozuvlar(vault: Path, kalitlar: dict) -> dict:
    """Har skill nomi qaysi qo'lda yozilgan vault yozuvlarida tilga olingan."""
    natija = {k: [] for k in kalitlar}
    naqsh = {k: re.compile(r"(?<![\w-])" + re.escape(v["nom"]) + r"(?![\w-])") for k, v in kalitlar.items()
             if len(v["nom"]) >= 4}
    for p in sorted(vault.rglob("*.md")):
        rel = p.relative_to(vault).as_posix()
        if rel.startswith((".", "claude/", "kod/", "wall-e/", "tizim/", "chat/")) or rel == "BOSH-SAHIFA.md":
            continue
        if "/hisobotlar/" in rel:
            continue
        try:
            matn = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k, rx in naqsh.items():
            if rx.search(matn):
                natija[k].append(rel)
    return natija


def _ishlatilish(sessiya_holat: dict) -> dict:
    natija: dict = {}
    for sid, v in (sessiya_holat or {}).items():
        if not isinstance(v, dict) or not v.get("rel"):
            continue
        for sk in v.get("skillar") or []:
            natija.setdefault(kalit(sk), []).append(v)
    for k in natija:
        natija[k].sort(key=lambda x: x.get("boshi") or "", reverse=True)
    return natija


def skill_matni(s: dict, ishlatilgan: list, boglik: list) -> str:
    fm = {
        "turi": TURI, "nomi": s["nom"], "kelib_chiqishi": s["kelib"], "qayerdan": s["qayerdan"],
        "joyi": s.get("joyi") or "", "yangilangan": s.get("yangilangan") or "",
        "fayllar": len(s.get("fayllar") or []), "ishlatilgan": len(ishlatilgan),
        "tags": ["claude/skill"],
    }
    q = [asos.frontmatter(fm), f"# {s['nom']}\n", asos.avto_izoh("Claude skill katalogi"), ""]
    if s.get("tavsif"):
        q.append("> " + asos.bir_qator(asos.redakt(s["tavsif"]), 1200) + "\n")
    meta = [f"**Kelib chiqishi:** {s['kelib']}", f"**Manba:** {s['qayerdan']}"]
    if s.get("joyi"):
        meta.append(f"**Joyi:** `{s['joyi']}`")
    if s.get("yangilangan"):
        meta.append(f"**Yangilangan:** {s['yangilangan']}")
    q.append(" · ".join(meta) + "\n")
    if s.get("fayllar"):
        q.append(f"## Tarkibi ({len(s['fayllar'])} fayl, {s.get('hajm', 0) // 1024} KB)\n")
        for f in s["fayllar"][:30]:
            q.append(f"- `{f}`")
        if len(s["fayllar"]) > 30:
            q.append(f"- … yana {len(s['fayllar']) - 30} ta")
        q.append("")
    if ishlatilgan:
        q.append(f"## Qayerda ishlatilgan ({len(ishlatilgan)} sessiya)\n")
        for v in ishlatilgan[:25]:
            q.append(f"- {asos.wikilink(v['rel'], v.get('sarlavha') or 'sessiya')} — {v.get('boshi', '')[:10]}")
        q.append("")
    if boglik:
        q.append("## Miyadagi bog'liq yozuvlar\n")
        q.append(" · ".join(asos.wikilink(r) for r in boglik[:20]) + "\n")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


# ---------------------------------------------------------------- sozlamalar

def _hooklar(c: Path) -> list:
    natija = []
    try:
        st = json.loads((c / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return natija
    for hodisa, guruhlar in (st.get("hooks") or {}).items():
        for g in guruhlar or []:
            for h in g.get("hooks") or []:
                cmd = str(h.get("command") or "")
                m = re.search(r"([\w.-]+\.(?:sh|py|js))", cmd)
                skript = m.group(1) if m else cmd[:60]
                izoh = ""
                yol = re.search(r"\$HOME/([^\"' ]+)", cmd)
                if yol:
                    p = asos.HOME / yol.group(1)
                    try:
                        for q in p.read_text(encoding="utf-8").splitlines()[1:6]:
                            if q.startswith("#") and len(q) > 3:
                                izoh = q.lstrip("# ").strip()
                                break
                    except OSError:
                        pass
                natija.append((hodisa, skript, izoh))
    return natija


def _modlar() -> list:
    natija = []
    for d in sorted((asos.HOME / "claude-mods").glob("*")) if (asos.HOME / "claude-mods").is_dir() else []:
        if not d.is_dir():
            continue
        tavsif = ""
        for f in (d / ".claude-plugin" / "plugin.json", d / "plugin.json", d / "package.json"):
            try:
                tavsif = json.loads(f.read_text(encoding="utf-8")).get("description") or ""
                if tavsif:
                    break
            except (OSError, ValueError):
                continue
        natija.append((d.name, asos.uy_yol(d), tavsif))
    return natija


def _rejalashtirilgan(c: Path) -> list:
    natija = []
    for d in sorted((c / "scheduled-tasks").glob("*")) if (c / "scheduled-tasks").is_dir() else []:
        md = d / "SKILL.md"
        if not md.exists():
            continue
        try:
            fm = asos.fm_oqi(md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            fm = {}
        natija.append((d.name, fm.get("description") or ""))
    return natija


def _mcp_nomlari() -> list:
    """Faqat server NOMI va turi — env, header, token hech qachon o'qilmaydi/yozilmaydi."""
    natija = []
    try:
        cj = json.loads((asos.HOME / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return natija
    for nom, cfg in (cj.get("mcpServers") or {}).items():
        tur = (cfg or {}).get("type") or ("stdio" if (cfg or {}).get("command") else "?")
        natija.append((nom, tur, "foydalanuvchi"))
    for proj, pc in (cj.get("projects") or {}).items():
        for nom, cfg in ((pc or {}).get("mcpServers") or {}).items():
            tur = (cfg or {}).get("type") or ("stdio" if (cfg or {}).get("command") else "?")
            natija.append((nom, tur, f"loyiha {asos.uy_yol(proj)}"))
    return natija


def sozlamalar_matni(skillar: dict) -> str:
    c = asos.claude_dir()
    fm = {"turi": "claude-sozlamalar", "tags": ["claude/sozlama"]}
    q = [asos.frontmatter(fm), "# Claude sozlamalari va vositalari\n",
         asos.avto_izoh("hook, mod, rejalashtirilgan vazifa va MCP ro'yxati"), ""]
    kelib = Counter(s["kelib"] for s in skillar.values())
    q.append("## Skillar\n")
    q.append(f"Jami **{len(skillar)}** ta: " + ", ".join(f"{k} — {v}" for k, v in kelib.most_common())
             + ". To'liq ro'yxat: " + asos.wikilink("claude/skillar/INDEX", "Skillar katalogi") + ".\n")
    h = _hooklar(c)
    if h:
        q.append("## Hook'lar (`~/.claude/settings.json`)\n")
        q.append("| Hodisa | Skript | Vazifasi |\n|---|---|---|")
        for hodisa, skript, izoh in h:
            q.append(f"| {hodisa} | `{skript}` | {asos.bir_qator(izoh, 160)} |")
        q.append("")
    m = _modlar()
    if m:
        q.append("## Modlar (`~/claude-mods`)\n")
        for nom, yol, tavsif in m:
            q.append(f"- **{nom}** — `{yol}`" + (f" — {asos.bir_qator(tavsif, 200)}" if tavsif else ""))
        q.append("")
    r = _rejalashtirilgan(c)
    if r:
        q.append("## Claude ilovasidagi rejalashtirilgan vazifalar\n")
        for nom, tavsif in r:
            q.append(f"- **{nom}** — {asos.bir_qator(asos.redakt(tavsif), 200)}")
        q.append("")
    mcp = _mcp_nomlari()
    if mcp:
        q.append("## MCP serverlar (faqat nomlari)\n")
        for nom, tur, qamrov in mcp:
            q.append(f"- `{nom}` — {tur}, {qamrov}")
        q.append("")
    q.append("## Ko'rsatmalar fayllari\n")
    for p in (c / "CLAUDE.md", asos.HOME / "AGENTS.md"):
        if p.exists():
            q.append(f"- `{asos.uy_yol(p)}`")
    q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def index_matni(skillar: dict, ishlatilish: dict) -> str:
    fm = {"turi": "skill-index", "skillar": len(skillar), "tags": ["claude/skill"]}
    q = [asos.frontmatter(fm), "# Skillar katalogi\n", asos.avto_izoh("barcha Claude skillari"), ""]
    tartib = ["o'zimizniki", "Anthropic", "tashqi", "ichki"]
    guruh: dict = {}
    for s in skillar.values():
        guruh.setdefault(s["kelib"], []).append(s)
    for g in sorted(guruh, key=lambda x: tartib.index(x) if x in tartib else 99):
        q.append(f"## {g.capitalize() if g[0].islower() else g} ({len(guruh[g])})\n")
        q.append("| Skill | Ishlatilgan | Yangilangan | Tavsif |\n|---|---|---|---|")
        for s in sorted(guruh[g], key=lambda x: (-len(ishlatilish.get(x["kalit"], [])), x["nom"])):
            q.append(f"| {asos.wikilink(PAPKA + '/' + s['kalit'], s['nom'])} | "
                     f"{len(ishlatilish.get(s['kalit'], []))} | {s.get('yangilangan', '')} | "
                     f"{asos.bir_qator(s.get('tavsif', ''), 140)} |")
        q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def yigish(yozuvchi: asos.Yozuvchi, sessiya_holat: dict | None = None) -> dict:
    skillar = diskdagi_skillar()
    ishl = _ishlatilish(sessiya_holat or asos.holat_oqi("sessiyalar"))
    for k, sesslar in ishl.items():          # diskda yo'q, lekin ishlatilgan → ichki skill
        if k not in skillar:
            skillar[k] = {"kalit": k, "nom": k, "tavsif": "", "kelib": "ichki",
                          "qayerdan": "Claude ilovasi bilan keladi", "fayllar": [], "joyi": ""}
    boglik = _boglik_yozuvlar(yozuvchi.vault, skillar)
    for k, s in skillar.items():
        yozuvchi.yoz(f"{PAPKA}/{k}.md", skill_matni(s, ishl.get(k, []), boglik.get(k, [])))
    yozuvchi.yoz(f"{PAPKA}/INDEX.md", index_matni(skillar, ishl))
    yozuvchi.yoz("claude/sozlamalar.md", sozlamalar_matni(skillar))
    return {"skillar": skillar, "ishlatilish": ishl}
