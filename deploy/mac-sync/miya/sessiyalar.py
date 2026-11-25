"""Claude sessiyalari → vault `claude/sessiyalar/YYYY-MM/<sana> <sarlavha>.md`.

Manba: ~/.claude/projects/<papka>/<sessiya-id>.jsonl (Claude Code va desktop ilovaning
Code yorlig'i). Har sessiyaga bitta yozuv: sarlavha, so'rovlar va natijalar (wrap_up
recap yoki oxirgi javob), miyaga yozilgan yozuvlar (wikilink), artifactlar, commitlar,
fayllar, vositalar, narx.

Muhim:
  - Tool NATIJALARI yozuvga kirmaydi (sirlar asosan o'sha yerda). Faqat Artifact va
    `git commit` natijasidan havola/SHA olinadi.
  - Artifact havolasi faqat `frame-link` yozuvidan va Artifact tool natijasidan olinadi:
    boshqa tool natijalarida (masalan INDEX.md o'qilganda) eski havolalar ko'p uchraydi.
  - Subagent/workflow transkriptlari alohida yozuv bo'lmaydi — sessiya ichida soni.
  - Headless `claude -p` papkalari (launchd avtomatikasi) o'tkazib yuboriladi.
  - Transkriptlar ~10 kundan keyin o'chib ketadi: yozuv bir marta yaratilgach, manba
    yo'qolsa ham vault'da qoladi (yig'uvchi hech narsani o'chirmaydi).
"""
from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from pathlib import Path

from . import asos

TURI = "claude-sessiya"
PAPKA = "claude/sessiyalar"

_YOZISH_TOOLLARI = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_ART_URL = re.compile(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+")
_COMMIT_NATIJA = re.compile(r"\[([\w./+-]+)(?: \(root-commit\))? ([0-9a-f]{7,40})\] ([^\n]+)")
_WF_NOMI = re.compile(r"""\bname\s*:\s*['"]([^'"]{1,80})['"]""")
_FAYL_NOMI_TAQIQ = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')


# ---------------------------------------------------------------- yordamchilar

def _matn_bloklari(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        qism = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                qism.append(b.get("text") or "")
        return "\n".join(qism)
    return ""


def _tool_natija_matni(b) -> str:
    c = b.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def tozala_sorov(matn: str) -> str:
    """Inson so'rovidan texnik o'ramlarni olib tashlaydi."""
    t = matn or ""
    t = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>", " ", t)
    t = re.sub(r"<pasted_content[^>]*>([\s\S]*?)</pasted_content[^>]*>",
               lambda m: f" [joylangan matn, {len(m.group(1).strip())} belgi] ", t)
    t = re.sub(r"<!--\s*reply \d+\s*-->", " ", t)
    m = re.search(r"<command-name>/?([^<]+)</command-name>", t)
    buyruq = f"/{m.group(1).strip()} " if m else ""
    args = re.search(r"<command-args>([\s\S]*?)</command-args>", t)
    t = re.sub(r"<command-(?:message|name|args)>[\s\S]*?</command-(?:message|name|args)>", " ", t)
    t = re.sub(r"<skill-format>[\s\S]*?</skill-format>", " ", t)
    t = re.sub(r"<[a-z_-]+-event>[\s\S]*?</[a-z_-]+-event>", " ", t)
    t = re.sub(r"\[Image[^\]]*\]", " [rasm] ", t)
    t = (buyruq + (args.group(1).strip() + " " if args else "") + t).strip()
    t = t.replace(str(asos.HOME) + "/", "~/").replace(str(asos.HOME), "~")
    return re.sub(r"\s+", " ", t).strip()


def _javob_qisqa(matn: str, n: int) -> str:
    """Markdown javobni bir abzasga: sarlavha belgilari va jadval chiziqlari olinadi."""
    t = re.sub(r"```[\s\S]*?```", " [kod] ", matn or "")
    t = re.sub(r"^\s*#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*\|?[-:| ]{3,}\|?\s*$", " ", t, flags=re.M)
    t = t.replace("**", "")
    return asos.bir_qator(t, n)


def loyiha_nomi(cwd: str) -> str:
    """cwd → loyiha nomi (kod/ yozuvi nomi bilan bir xil qoidada)."""
    if not cwd:
        return "nomalum"
    if "/scratch-workspaces/" in cwd:
        return "papkasiz"
    if cwd.startswith("/private/") or cwd.startswith("/tmp/"):
        return "vaqtinchalik"
    if "/.claude/worktrees/" in cwd:
        cwd = cwd.split("/.claude/worktrees/", 1)[0]
    h = str(asos.HOME)
    if cwd == h:
        return "uy"
    if cwd.startswith(h + "/"):
        qism = cwd[len(h) + 1:].split("/")
        if qism[0] == "Projects" and len(qism) > 1:
            return qism[1].lstrip(".")
        return qism[0].lstrip(".")
    return Path(cwd).name or "nomalum"


def fayl_nomi(sarlavha: str, maks: int = 70) -> str:
    """Obsidian'da o'qiladigan fayl nomi (unicode, bo'shliq bilan), taqiqlangan belgisiz."""
    s = (sarlavha or "").replace(str(asos.HOME), "~").rstrip("…").strip()
    s = re.sub(r"\.md\b", "", s)
    s = _FAYL_NOMI_TAQIQ.sub(" ", s.replace("…", " "))
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > maks:
        s = s[:maks].rsplit(" ", 1)[0].strip(" .") or s[:maks]
    return s or "Nomsiz sessiya"


# ---------------------------------------------------------------- o'qish

def sessiya_oqi(yol: Path) -> dict | None:
    """Bitta transkriptni o'qib, yozuv uchun tuzilma qaytaradi. Inson so'rovi yo'q → None."""
    sid = yol.stem
    s = {
        "id": sid, "sarlavha": None, "agent_nomi": None, "boshi": None, "oxiri": None,
        "cwd": Counter(), "branch": Counter(), "turlar": [], "fayllar": OrderedDict(),
        "commitlar": [], "artifactlar": OrderedDict(), "skillar": Counter(),
        "workflowlar": [], "agentlar": 0, "toollar": Counter(), "modellar": Counter(),
        "narx": None, "reja": None, "entry": Counter(), "ai_sarlavha": None,
    }
    kutilgan = {}          # tool_use_id → (nom, input)
    joriy = None

    try:
        fh = open(yol, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for qator in fh:
            try:
                d = json.loads(qator)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            t = d.get("type")
            if t == "custom-title" and d.get("customTitle"):
                s["sarlavha"] = str(d["customTitle"]).strip()
                continue
            if t == "agent-name" and d.get("agentName"):
                s["agent_nomi"] = str(d["agentName"]).strip()
                continue
            if t == "ai-title" and (d.get("aiTitle") or d.get("title")):
                s["ai_sarlavha"] = str(d.get("aiTitle") or d.get("title")).strip()
                continue
            if t == "frame-link":
                url = d.get("frameUrl") or ""
                if _ART_URL.fullmatch(url):
                    s["artifactlar"][url] = d.get("title") or s["artifactlar"].get(url)
                continue
            if t == "cost-state":
                s["narx"] = d
                continue
            if t not in ("user", "assistant") or d.get("isSidechain"):
                continue
            if d.get("sessionId") and d["sessionId"] != sid:
                continue        # fork: ota sessiyadan ko'chirilgan tarix — u o'z yozuvida bor

            ts = asos.ts_parse(d.get("timestamp"))
            if ts:
                s["boshi"] = s["boshi"] or ts
                s["oxiri"] = ts
            if d.get("cwd"):
                s["cwd"][d["cwd"]] += 1
            if d.get("gitBranch") and d["gitBranch"] != "HEAD":
                s["branch"][d["gitBranch"]] += 1
            if d.get("entrypoint"):
                s["entry"][d["entrypoint"]] += 1
            msg = d.get("message") or {}
            content = msg.get("content")

            if t == "user":
                origin = d.get("origin") or {}
                inson = (d.get("turnOrigin") == "human" or origin.get("kind") == "human")
                if inson and not d.get("isMeta") and not d.get("isCompactSummary"):
                    matn = tozala_sorov(_matn_bloklari(content))
                    if matn:
                        joriy = {"vaqt": ts, "sorov": matn, "recap": [], "javob": "", "savol": ""}
                        s["turlar"].append(joriy)
                        continue
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_result":
                            continue
                        nom, inp = kutilgan.pop(b.get("tool_use_id"), (None, None))
                        if nom == "Artifact" and (inp or {}).get("action", "publish") == "publish":
                            # faqat nashr: list/read natijasida boshqa artifactlar havolasi ham bo'ladi
                            for url in _ART_URL.findall(_tool_natija_matni(b))[:3]:
                                s["artifactlar"].setdefault(url, None)
                        elif nom == "Bash" and "git commit" in str((inp or {}).get("command") or ""):
                            natija_matni = _tool_natija_matni(b)
                            topildi = _COMMIT_NATIJA.findall(natija_matni)
                            for br, sha, xabar in topildi:
                                s["commitlar"].append((sha[:7], br, xabar.strip()))
                            if not topildi:   # `git commit -q && git log --oneline -1` ko'rinishi
                                m = re.search(r"(?m)^([0-9a-f]{7,12}) (\S.{2,200})$", natija_matni)
                                if m:
                                    s["commitlar"].append((m.group(1)[:7], "", m.group(2).strip()))
                continue

            # assistant
            model = msg.get("model")
            sintetik = bool(model) and str(model).startswith("<")
            if model and not sintetik:
                s["modellar"][model] += 1
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text" and joriy is not None and not sintetik and (b.get("text") or "").strip():
                    joriy["javob"] = b["text"]
                elif bt == "tool_use":
                    nom = b.get("name") or "?"
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    s["toollar"][nom] += 1
                    if nom in _YOZISH_TOOLLARI:
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if fp:
                            s["fayllar"].setdefault(fp, set()).add(nom)
                    elif nom == "mcp__ccd_turn__wrap_up":
                        if joriy is not None and inp.get("recap"):
                            joriy["recap"].append(str(inp["recap"]))
                        if joriy is not None and inp.get("ask"):
                            joriy["savol"] = str(inp["ask"])
                    elif nom == "mcp__ccd_turn__update_plan" and isinstance(inp.get("items"), list):
                        s["reja"] = inp["items"]
                    elif nom == "Skill" and inp.get("skill"):
                        s["skillar"][str(inp["skill"])] += 1
                    elif nom == "Workflow":
                        m = _WF_NOMI.search(str(inp.get("script") or ""))
                        sp = str(inp.get("scriptPath") or "")
                        sp_nom = re.sub(r"-wf_[0-9a-z-]+$", "", Path(sp).stem) if sp else ""
                        s["workflowlar"].append(m.group(1) if m else (inp.get("name") or sp_nom or "workflow"))
                    elif nom == "Agent":
                        s["agentlar"] += 1
                    if nom in ("Artifact", "Bash"):
                        kutilgan[b.get("id")] = (nom, inp)

    if not s["turlar"]:
        return None
    sub = yol.parent / sid / "subagents"
    s["subagent_soni"] = sum(1 for _ in sub.rglob("*.jsonl")) if sub.is_dir() else 0
    s["asosiy_cwd"] = s["cwd"].most_common(1)[0][0] if s["cwd"] else ""
    s["loyiha"] = loyiha_nomi(s["asosiy_cwd"])
    if not s["sarlavha"]:
        s["sarlavha"] = (s.get("ai_sarlavha") or s["agent_nomi"]
                         or asos.qisqart(s["turlar"][0]["sorov"], 70))
    return s


# ---------------------------------------------------------------- yozuv

def _sanalar(s) -> list:
    sanalar = []
    for t in s["turlar"]:
        k = asos.vaqt_str(t["vaqt"], sana_faqat=True)
        if k and k not in sanalar:
            sanalar.append(k)
    return sanalar


def _vault_ichida(fp: str, vault: Path) -> str | None:
    v = str(vault)
    if fp.startswith(v + "/") and fp.endswith(".md"):
        return fp[len(v) + 1:]
    return None


_SHOVQIN_YOL = ("/private/", "/tmp/", "/var/folders/")


def _foydali_fayl(fp: str) -> bool:
    """Vaqtinchalik (scratchpad) va Claude ichki xotira fayllari ro'yxatga kirmaydi."""
    if any(fp.startswith(p) for p in _SHOVQIN_YOL):
        return False
    if "/.claude/projects/" in fp and "/memory/" in fp:
        return False
    return True


MAKS_TUR = 30


def yozuv_matni(s: dict, rel: str, vault: Path, artifact_nomlari: dict | None = None) -> str:
    artifact_nomlari = artifact_nomlari or {}
    sanalar = _sanalar(s)
    narx = s.get("narx") or {}
    narx_usd = narx.get("totalCostUSD")
    modellar = [m for m, _ in s["modellar"].most_common()]
    vault_yozuvlar = []
    kod_fayllar = []
    for fp in s["fayllar"]:
        r = _vault_ichida(fp, vault)
        if r:
            if r != rel:
                vault_yozuvlar.append(r)
        elif _foydali_fayl(fp):
            kod_fayllar.append(fp)

    fm = {
        "turi": TURI,
        "sarlavha": s["sarlavha"],
        "sana": sanalar[0] if sanalar else asos.vaqt_str(s["boshi"], True),
        "boshlandi": asos.vaqt_str(s["boshi"]),
        "oxirgi_faollik": asos.vaqt_str(s["oxiri"]),
        "loyiha": s["loyiha"],
        "papka": (asos.uy_yol(s["asosiy_cwd"]) if s["loyiha"] not in ("papkasiz", "vaqtinchalik") else "")
                 if s["asosiy_cwd"] else "",
        "branch": s["branch"].most_common(1)[0][0] if s["branch"] else "",
        "sorovlar": len(s["turlar"]),
        "fayllar": len(kod_fayllar) + len(vault_yozuvlar),
        "commitlar": len(s["commitlar"]),
        "artifactlar": len(s["artifactlar"]),
        "agentlar": s.get("subagent_soni", 0) or s["agentlar"],
        "narx_usd": round(float(narx_usd), 2) if isinstance(narx_usd, (int, float)) else None,
        "modellar": modellar,
        "skillar": [k for k, _ in s["skillar"].most_common()],
        "sessiya_id": s["id"],
        "tags": ["claude/sessiya", f"loyiha/{asos.slug(s['loyiha'], 40)}"],
    }
    q = [asos.frontmatter(fm), f"# {asos.redakt(s['sarlavha'])}\n", asos.avto_izoh("Claude sessiyasi"), ""]

    kunlik_link = []
    for k in sanalar:
        if (vault / "kunlik" / f"{k}.md").exists():
            kunlik_link.append(asos.wikilink(f"kunlik/{k}", k))
    bosh = [f"**Vaqt:** {asos.vaqt_str(s['boshi'])} → {asos.vaqt_str(s['oxiri'])}",
            f"**Loyiha:** {asos.wikilink('kod/' + s['loyiha'], s['loyiha'])}"
            if s["loyiha"] not in ("papkasiz", "vaqtinchalik", "nomalum", "uy") else f"**Loyiha:** {s['loyiha']}"]
    if kunlik_link:
        bosh.append("**Kunlik:** " + ", ".join(kunlik_link))
    q.append(" · ".join(bosh) + "\n")

    # so'rovlar
    q.append(f"## So'rovlar va natijalar ({len(s['turlar'])})\n")
    turlar = list(enumerate(s["turlar"], 1))
    if len(turlar) > MAKS_TUR:
        kesildi = len(turlar) - MAKS_TUR
        turlar = turlar[:5] + [None] + turlar[-(MAKS_TUR - 5):]
    else:
        kesildi = 0
    for el in turlar:
        if el is None:
            q.append(f"_… o'rtadagi {kesildi} ta so'rov qisqartirildi._\n")
            continue
        i, t = el
        q.append(f"### {i}. {asos.vaqt_str(t['vaqt'])}")
        q.append(f"- **So'rov:** {asos.bir_qator(asos.redakt(t['sorov']), 400)}")
        if t["recap"]:
            q.append(f"- **Natija:** {asos.bir_qator(asos.redakt(t['recap'][-1]), 600)}")
        elif t["javob"]:
            q.append(f"- **Javob:** {_javob_qisqa(asos.redakt(t['javob']), 600)}")
        if t["savol"]:
            q.append(f"- **Ochiq savol:** {asos.bir_qator(asos.redakt(t['savol']), 200)}")
        q.append("")

    if vault_yozuvlar:
        q.append("## Miyaga yozilganlar\n")
        q.append(" · ".join(asos.wikilink(r) for r in vault_yozuvlar[:40]) + "\n")

    if s["artifactlar"]:
        q.append("## Artifactlar\n")
        for url, nom in s["artifactlar"].items():
            nom = nom or artifact_nomlari.get(url) or url.rsplit("/", 1)[-1]
            q.append(f"- [{asos.bir_qator(nom, 100)}]({url})")
        q.append("")

    if s["commitlar"]:
        q.append("## Commitlar\n")
        korilgan = set()
        for sha, br, xabar in s["commitlar"]:
            if sha in korilgan:
                continue
            korilgan.add(sha)
            q.append(f"- `{sha}` ({br}) — {asos.bir_qator(asos.redakt(xabar), 150)}")
        q.append("")

    if kod_fayllar:
        q.append(f"## Fayllar ({len(kod_fayllar)})\n")
        for fp in kod_fayllar[:25]:
            amallar = "/".join(sorted(s["fayllar"][fp]))
            q.append(f"- `{asos.uy_yol(fp)}` — {amallar}")
        if len(kod_fayllar) > 25:
            q.append(f"- … yana {len(kod_fayllar) - 25} ta")
        q.append("")

    vositalar = []
    if s["workflowlar"]:
        wf = Counter(s["workflowlar"])
        vositalar.append("**Workflow:** " + ", ".join(f"{k}" + (f" ×{v}" if v > 1 else "") for k, v in wf.items()))
    if s["skillar"]:
        vositalar.append("**Skill:** " + ", ".join(
            asos.wikilink(f"claude/skillar/{asos.slug(k, 60)}", k) for k, _ in s["skillar"].most_common()))
    if s["agentlar"] or s.get("subagent_soni"):
        vositalar.append(f"**Agentlar:** {s.get('subagent_soni', 0) or s['agentlar']} ta (subagent va workflow agentlari)")
    top = ", ".join(f"{k} {v}" for k, v in s["toollar"].most_common(8)
                    if not k.startswith("mcp__ccd_turn__"))
    if top:
        vositalar.append("**Eng ko'p ishlatilgan:** " + top)
    if narx:
        qism = []
        if isinstance(narx_usd, (int, float)):
            qism.append(f"${narx_usd:,.2f} (API narxi bo'yicha hisob)")
        if narx.get("totalLinesAdded") is not None:
            qism.append(f"+{narx.get('totalLinesAdded')} / −{narx.get('totalLinesRemoved', 0)} qator")
        if qism:
            vositalar.append("**Hajm:** " + " · ".join(qism))
    if modellar:
        vositalar.append("**Model:** " + ", ".join(modellar))
    if vositalar:
        q.append("## Vositalar\n")
        q.extend(f"- {v}" for v in vositalar)
        q.append("")

    q.append(asos.QOLDA_BLOK)
    return "\n".join(q)


# ---------------------------------------------------------------- yig'ish

def _fayl_sid(p: Path) -> str | None:
    """Mavjud yozuvning sessiya_id'si (holat fayli yo'qolsa ham dublikat bo'lmasin)."""
    try:
        with open(p, encoding="utf-8") as f:
            for _ in range(40):
                q = f.readline()
                if not q:
                    break
                if q.startswith("sessiya_id:"):
                    return q.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def transkriptlar(claude: Path | None = None):
    """Yuqori darajadagi sessiya transkriptlari (subagent va headless -p chiqarilgan)."""
    root = (claude or asos.claude_dir()) / "projects"
    if not root.is_dir():
        return []
    eng_yangi = {}      # sessiya ko'chirilganda (relocated) bir id ikki papkada bo'lishi mumkin
    for papka in sorted(root.iterdir()):
        if not papka.is_dir():
            continue
        n = papka.name
        if "-claude-p-" in n or n.startswith("-private-var-folders-"):
            continue        # launchd'dagi headless `claude -p` — avtomatika, ish sessiyasi emas
        for f in papka.glob("*.jsonl"):
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if f.stem not in eng_yangi or mt > eng_yangi[f.stem][0]:
                eng_yangi[f.stem] = (mt, f)
    return [f for _, f in sorted(eng_yangi.values(), key=lambda x: str(x[1]))]


def yigish(yozuvchi: asos.Yozuvchi, hammasi: bool = False, artifact_nomlari: dict | None = None) -> dict:
    """Yangi/o'zgargan sessiyalarni yozadi. Qaytadi: {sessiyalar: [meta...], hisob}."""
    holat = asos.holat_oqi("sessiyalar")
    vault = yozuvchi.vault
    band = {v.get("rel") for v in holat.values() if isinstance(v, dict)}
    hisob = Counter()
    for f in transkriptlar():
        try:
            st = f.stat()
        except OSError:
            continue
        sid = f.stem
        eski = holat.get(sid) or {}
        imzo = [int(st.st_mtime), st.st_size]
        if not hammasi and eski.get("imzo") == imzo and eski.get("rel"):
            hisob["o'tkazildi"] += 1
            continue
        try:
            s = sessiya_oqi(f)
        except Exception as e:  # bitta buzuq transkript butun yig'ishni to'xtatmasin
            asos.log(f"sessiya o'qish xato {sid[:8]}: {type(e).__name__}: {e}")
            hisob["xato"] += 1
            continue
        if not s:
            holat[sid] = {"imzo": imzo, "rel": None}
            hisob["bo'sh"] += 1
            continue
        rel = eski.get("rel")
        if not rel:
            oy = asos.vaqt_str(s["boshi"], True)[:7] or "nomalum"
            asos_nom = f"{asos.vaqt_str(s['boshi'], True)} {fayl_nomi(asos.redakt(s['sarlavha']))}"
            rel = f"{PAPKA}/{oy}/{asos_nom}.md"
            if (rel in band or (vault / rel).exists()) and _fayl_sid(vault / rel) != sid:
                rel = f"{PAPKA}/{oy}/{asos_nom} ({sid[:6]}).md"
            band.add(rel)
        natija = yozuvchi.yoz(rel, yozuv_matni(s, rel, vault, artifact_nomlari))
        hisob[natija] += 1
        holat[sid] = {
            "imzo": imzo, "rel": rel, "sarlavha": s["sarlavha"], "loyiha": s["loyiha"],
            "boshi": asos.vaqt_str(s["boshi"]), "oxiri": asos.vaqt_str(s["oxiri"]),
            "sana": _sanalar(s), "sorovlar": len(s["turlar"]), "commitlar": len(s["commitlar"]),
            "artifactlar": [[u, n or (artifact_nomlari or {}).get(u)] for u, n in s["artifactlar"].items()],
            "skillar": list(s["skillar"].keys()), "fayllar": len(s["fayllar"]),
            "narx_usd": (s.get("narx") or {}).get("totalCostUSD"),
            "vault_yozuvlar": [r for r in (_vault_ichida(fp, vault) for fp in s["fayllar"]) if r],
        }
    if not yozuvchi.quruq:
        asos.holat_yoz("sessiyalar", holat)
    return {"holat": holat, "hisob": dict(hisob)}
