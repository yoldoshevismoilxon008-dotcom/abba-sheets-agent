"""Kod loyihalari katalogi → vault `kod/<loyiha>.md` + `kod/INDEX.md`.

Har loyiha: maqsadi (README/CLAUDE.md), tili, git (remote, branch, oxirgi commitlar,
saqlanmagan o'zgarish bor-yo'qligi, worktree'lar), uni ishga tushiradigan launchd
vazifalari, GitHub Actions, miyadagi bog'liq yozuvlar va shu papkada ishlangan Claude
sessiyalari.

Barqarorlik: hajm va aniq «saqlanmagan fayllar soni» kabi tez o'zgaradigan raqamlar
yozilmaydi — yozuv faqat haqiqiy o'zgarishda (commit, yangi sessiya) yangilanadi.
Faqat o'qiydigan git buyruqlari ishlatiladi (fetch/pull YO'Q).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from . import asos

TURI = "kod-loyiha"
PAPKA = "kod"

_CHETLA = {"node_modules", "venv", ".venv", "__pycache__", ".git", "dist", "build", ".cache",
           ".pytest_cache", "raw", "data", "out", "voices", ".next", "site-packages"}
_TIL = {".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".sh": "Shell", ".html": "HTML", ".swift": "Swift",
        ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".gs": "Apps Script", ".sql": "SQL"}


def _git(papka: Path, *args, timeout: int = 20) -> str:
    try:
        r = subprocess.run(["git", "-C", str(papka), *args], capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                                 "GIT_OPTIONAL_LOCKS": "0"})
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _remote_toza(url: str) -> str:
    """Remote URL'dagi login/token olib tashlanadi."""
    url = re.sub(r"(https?://)[^/@\s]+@", r"\1", url or "")
    return asos.redakt(url)


def nomzodlar(home: Path | None = None) -> list:
    """Egasining kod papkalari: ~/Projects/*, uy papkasidagi git repolar, ~/.abba-*,
    ~/claude-mods/*. Vault'lar (claude-brain, Codex-brain) va Library chiqarib tashlanadi."""
    h = home or asos.HOME
    korilgan, natija = set(), []

    def qosh(p: Path):
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in korilgan or not p.is_dir():
            return
        korilgan.add(rp)
        natija.append(p)

    for p in sorted((h / "Projects").glob("*")) if (h / "Projects").is_dir() else []:
        if not p.name.startswith("."):
            qosh(p)
    for p in sorted(h.iterdir()):
        if p.name in ("Library", "Downloads", "Documents", "Desktop", "Movies", "Music", "Pictures",
                      "Public", "Applications", ".Trash", "claude-brain", "Codex-brain", "Projects",
                      "claude-mods"):
            continue
        if not p.is_dir() or p.is_symlink():
            continue
        if p.name.startswith(".abba-") or (p / ".git").exists() or p.name == ".palmier-mcp":
            qosh(p)
        elif not p.name.startswith("."):
            qosh(p)          # ish papkasi (kod yoki tayyor hujjatlar: pdf/xlsx/html)
    for p in sorted((h / "claude-mods").glob("*")) if (h / "claude-mods").is_dir() else []:
        qosh(p)
    return natija


def _birinchi_abzas(f: Path) -> str:
    try:
        matn = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if "create-next-app" in matn[:600]:
        return ""                       # Next.js shablon README — maqsad emas
    matn = re.sub(r"^---[\s\S]*?\n---\n", "", matn)
    for abzas in re.split(r"\n\s*\n", matn):
        a = abzas.strip()
        if not a or a.startswith(("#", "```", "<", "![", "|", "---", ">")):
            continue
        if re.match(r"^\*\*(Always|IMPORTANT|Note)\b", a):
            continue
        return asos.bir_qator(a, 400)
    return ""


def _maqsad(p: Path, vault: Path | None = None) -> str:
    """README → miyadagi loyiha yozuvi (natija/jarayon) → CLAUDE.md → package.json."""
    for nom in ("README.md", "BOT_README.md", "readme.md", "README.txt"):
        if (p / nom).exists():
            a = _birinchi_abzas(p / nom)
            if a:
                return a
    if vault is not None:
        asl = p.name.lstrip(".")
        for nom in dict.fromkeys((asl, asl.lower(), asl.replace("abba-", ""), "abba-" + asl.lower())):
            for f in ("natija.md", "jarayon.md", "holat.md"):
                if (vault / nom / f).exists():
                    a = _birinchi_abzas(vault / nom / f)
                    if a:
                        return a
    if (p / "CLAUDE.md").exists():
        a = _birinchi_abzas(p / "CLAUDE.md")
        if a:
            return a
    for nom in ("package.json", ".claude-plugin/plugin.json", "plugin.json"):
        try:
            d = json.loads((p / nom).read_text(encoding="utf-8"))
            if d.get("description"):
                return asos.bir_qator(d["description"], 400)
        except (OSError, ValueError):
            continue
    return ""


def _tillar(p: Path, maks_fayl: int = 4000) -> list:
    c = Counter()
    n = 0
    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in _CHETLA and not d.startswith(".")]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _TIL:
                c[_TIL[ext]] += 1
            n += 1
            if n > maks_fayl:
                break
        if n > maks_fayl:
            break
    return [k for k, _ in c.most_common(3)]


def _launchd(p: Path) -> list:
    natija = []
    la = asos.HOME / "Library" / "LaunchAgents"
    for plist in sorted(la.glob("*.plist")) if la.is_dir() else []:
        try:
            matn = plist.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if str(p) + "/" in matn or f"<string>{p}</string>" in matn:
            natija.append(plist.stem)
    return natija


_HUJJAT = (".pdf", ".pptx", ".xlsx", ".docx", ".html", ".md", ".csv", ".mp4", ".key", ".numbers")


def _asosiy_fayllar(p: Path, maks: int = 15) -> list:
    """Papka ildizidagi tayyor ishlar (hujjat, jadval, taqdimot) — yangisi birinchi."""
    try:
        fayllar = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in _HUJJAT
                   and f.name not in ("README.md", "CLAUDE.md", "AGENTS.md")]
        fayllar.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [f.name for f in fayllar[:maks]]


def _actions(p: Path) -> list:
    wf = p / ".github" / "workflows"
    return sorted(f.name for f in wf.glob("*.y*ml")) if wf.is_dir() else []


def loyiha_ol(p: Path, vault: Path | None = None) -> dict:
    nom = p.name.lstrip(".")
    d = {"nom": nom, "kalit": asos.slug(nom, 60), "yol": asos.uy_yol(p), "abs": str(p),
         "maqsad": _maqsad(p, vault), "tillar": _tillar(p), "launchd": _launchd(p), "actions": _actions(p),
         "fayllar": _asosiy_fayllar(p), "git": None}
    if (p / ".git").exists():
        g = {"remote": _remote_toza(_git(p, "remote", "get-url", "origin")),
             "branch": _git(p, "branch", "--show-current"),
             "soni": _git(p, "rev-list", "--count", "HEAD"),
             "oxirgi": [], "toza": _git(p, "status", "--porcelain", "--untracked-files=no") == "",
             "worktree": []}
        log = _git(p, "log", "-8", "--date=format:%Y-%m-%d", "--pretty=format:%h\t%ad\t%s")
        for q in log.splitlines():
            qism = q.split("\t", 2)
            if len(qism) == 3:
                g["oxirgi"].append(qism)
        wt = _git(p, "worktree", "list", "--porcelain")
        joriy = {}
        for q in wt.splitlines() + [""]:
            if q.startswith("worktree "):
                joriy = {"yol": q[9:]}
            elif q.startswith("branch "):
                joriy["branch"] = q[7:].replace("refs/heads/", "")
            elif not q and joriy:
                if joriy.get("yol") and Path(joriy["yol"]) != p:
                    g["worktree"].append((asos.uy_yol(joriy["yol"]), joriy.get("branch", "")))
                joriy = {}
        d["git"] = g
    return d


def _boglik(vault: Path, loyihalar: list) -> dict:
    natija = {l["kalit"]: [] for l in loyihalar}
    naqshlar = {}
    for l in loyihalar:
        variantlar = {l["yol"], l["abs"]}
        if len(l["nom"]) >= 6:
            variantlar.add(l["nom"])
        naqshlar[l["kalit"]] = re.compile("|".join(
            r"(?<![\w-])" + re.escape(v) + r"(?![\w-])" for v in sorted(variantlar, key=len, reverse=True)))
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault).as_posix()
        if rel.startswith((".", "claude/", "kod/", "wall-e/", "tizim/", "chat/")) or "/hisobotlar/" in rel:
            continue
        if rel == "BOSH-SAHIFA.md" or rel.startswith("kunlik/"):
            continue        # kunliklar juda ko'p — loyiha yozuvlari (jarayon/natija/holat) yetarli
        try:
            matn = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k, rx in naqshlar.items():
            if rx.search(matn):
                natija[k].append(rel)
    return natija


def _sessiyalar(sessiya_holat: dict, nom: str) -> list:
    s = [v for v in (sessiya_holat or {}).values()
         if isinstance(v, dict) and v.get("rel") and v.get("loyiha") == nom]
    return sorted(s, key=lambda x: x.get("boshi") or "", reverse=True)


def loyiha_matni(l: dict, boglik: list, sesslar: list) -> str:
    g = l.get("git") or {}
    oxirgi_sana = g.get("oxirgi", [[None, ""]])[0][1] if g.get("oxirgi") else ""
    fm = {
        "turi": TURI, "nomi": l["nom"], "yol": l["yol"], "tillar": l["tillar"],
        "remote": g.get("remote") or "", "branch": g.get("branch") or "",
        "commitlar": int(g["soni"]) if g.get("soni", "").isdigit() else None,
        "oxirgi_commit": oxirgi_sana, "toza": g.get("toza") if g else None,
        "launchd": l["launchd"], "sessiyalar": len(sesslar), "tags": ["kod"],
    }
    q = [asos.frontmatter(fm), f"# {l['nom']}\n", asos.avto_izoh("kod loyihasi katalogi"), ""]
    if l["maqsad"]:
        q.append("> " + asos.redakt(l["maqsad"]) + "\n")
    meta = [f"**Joyi:** `{l['yol']}`"]
    if l["tillar"]:
        meta.append("**Til:** " + ", ".join(l["tillar"]))
    if g.get("remote"):
        meta.append(f"**Remote:** `{g['remote']}`")
    q.append(" · ".join(meta) + "\n")
    if g:
        q.append("## Git\n")
        q.append(f"- **Branch:** `{g.get('branch') or '—'}` · **Commitlar:** {g.get('soni') or '—'} · "
                 f"**Holat:** {'toza' if g.get('toza') else 'saqlanmagan (commit qilinmagan) o‘zgarishlar bor'}")
        if g.get("worktree"):
            q.append("- **Worktree'lar:** " + ", ".join(f"`{b or y}`" for y, b in g["worktree"]))
        if g.get("oxirgi"):
            q.append("\n**Oxirgi commitlar:**\n")
            for sha, sana, xabar in g["oxirgi"]:
                q.append(f"- `{sha}` {sana} — {asos.bir_qator(asos.redakt(xabar), 140)}")
        q.append("")
    if l.get("fayllar"):
        q.append("## Asosiy fayllar\n")
        q.extend(f"- `{f}`" for f in l["fayllar"])
        q.append("")
    if l["launchd"] or l["actions"]:
        q.append("## Avtomatika\n")
        for j in l["launchd"]:
            q.append(f"- launchd: `{j}` → {asos.wikilink('tizim/avtomatika', 'avtomatika')}")
        for a in l["actions"]:
            q.append(f"- GitHub Actions: `{a}`")
        q.append("")
    if sesslar:
        q.append(f"## Claude sessiyalari ({len(sesslar)})\n")
        for v in sesslar[:15]:
            q.append(f"- {asos.wikilink(v['rel'], v.get('sarlavha') or 'sessiya')} — {(v.get('boshi') or '')[:10]}")
        q.append("")
    if boglik:
        q.append("## Miyadagi bog'liq yozuvlar\n")
        q.append(" · ".join(asos.wikilink(r) for r in boglik[:25]) + "\n")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def index_matni(loyihalar: list, sesslar: dict) -> str:
    fm = {"turi": "kod-index", "loyihalar": len(loyihalar), "tags": ["kod"]}
    q = [asos.frontmatter(fm), "# Kod loyihalari\n", asos.avto_izoh("Mac'dagi barcha kod papkalari"), ""]
    q.append("| Loyiha | Maqsadi | Oxirgi commit | Sessiyalar | Avtomatika |\n|---|---|---|---|---|")
    for l in sorted(loyihalar, key=lambda x: ((x.get("git") or {}).get("oxirgi") or [["", ""]])[0][1],
                    reverse=True):
        g = l.get("git") or {}
        sana = g["oxirgi"][0][1] if g.get("oxirgi") else "—"
        q.append(f"| {asos.wikilink(PAPKA + '/' + l['kalit'], l['nom'])} | {asos.bir_qator(l['maqsad'], 110)} | "
                 f"{sana} | {len(sesslar.get(l['nom'], []))} | {', '.join(l['launchd']) or '—'} |")
    q.append("")
    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


def yigish(yozuvchi: asos.Yozuvchi, sessiya_holat: dict | None = None) -> dict:
    sh = sessiya_holat or asos.holat_oqi("sessiyalar")
    loyihalar, band = [], set()
    for p in nomzodlar():
        try:
            l = loyiha_ol(p, yozuvchi.vault)
        except Exception as e:
            asos.log(f"kod: {p.name} o'qilmadi: {type(e).__name__}: {e}")
            continue
        if l["kalit"] in band:      # masalan ~/Projects/x va ~/.x — ikkalasi ham 'x'
            ota = "mac" if p.parent == asos.HOME else (p.parent.name.lstrip(".") or "mac")
            l["kalit"] = asos.slug(f"{l['nom']}-{ota}", 60)
            l["nom"] = f"{l['nom']} ({asos.uy_yol(p.parent)})"
        band.add(l["kalit"])
        loyihalar.append(l)
    boglik = _boglik(yozuvchi.vault, loyihalar)
    sesslar = {l["nom"]: _sessiyalar(sh, l["nom"]) for l in loyihalar}
    for l in loyihalar:
        yozuvchi.yoz(f"{PAPKA}/{l['kalit']}.md", loyiha_matni(l, boglik.get(l["kalit"], []), sesslar[l["nom"]]))
    yozuvchi.yoz(f"{PAPKA}/INDEX.md", index_matni(loyihalar, sesslar))
    return {"loyihalar": loyihalar}
