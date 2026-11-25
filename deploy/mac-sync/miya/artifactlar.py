"""claude.ai artifactlari katalogi → vault `claude/artifactlar.md`.

Manbalar:
  1) sessiya transkriptlari (frame-link yozuvi va Artifact tool natijasi) — avtomatik;
  2) `state/artifactlar_urug.json` — claude.ai ro'yxatidan bir martalik urug' (sarlavha,
     turi, sana). Lokal skript claude.ai'ga kira olmaydi, shuning uchun eski artifactlar
     shu urug'dan keladi; yangilari transkriptlardan qo'shiladi.
"""
from __future__ import annotations

from collections import OrderedDict

from . import asos

TURI = "artifact-katalog"


def urug() -> "OrderedDict[str, dict]":
    d = asos.holat_oqi("artifactlar_urug")
    natija: "OrderedDict[str, dict]" = OrderedDict()
    for x in d.get("artifactlar", []) if isinstance(d, dict) else []:
        if x.get("url"):
            natija[x["url"]] = dict(x)
    return natija


def yigish(yozuvchi: asos.Yozuvchi, sessiya_holat: dict | None = None) -> dict:
    sh = sessiya_holat or asos.holat_oqi("sessiyalar")
    katalog = urug()
    for v in sorted((x for x in sh.values() if isinstance(x, dict) and x.get("rel")),
                    key=lambda x: (x.get("boshi") or "", x["rel"])):
        for url, nom in v.get("artifactlar") or []:
            a = katalog.setdefault(url, {"url": url})
            if nom and not a.get("sarlavha"):
                a["sarlavha"] = nom
            a.setdefault("sessiyalar", [])
            if v["rel"] not in [s[0] for s in a["sessiyalar"]]:
                a["sessiyalar"].append([v["rel"], v.get("sarlavha") or ""])
            sana = (v.get("oxiri") or "")[:10]
            if sana and sana > (a.get("sana") or ""):
                a["sana"] = sana
    royxat = sorted(katalog.values(), key=lambda a: a.get("sana") or "", reverse=True)
    fm = {"turi": TURI, "artifactlar": len(royxat), "tags": ["claude/artifact"]}
    q = [asos.frontmatter(fm), "# claude.ai artifactlari\n",
         asos.avto_izoh("dashboard, taqdimot, hujjat va sahifalar ro'yxati"), "",
         f"Jami **{len(royxat)}** ta. Havolalar shaxsiy (faqat egasi ko'radi, ulashilmagan bo'lsa).\n",
         "| Sana | Nomi | Turi | Sessiya |\n|---|---|---|---|"]
    for a in royxat:
        nom = asos.bir_qator(a.get("sarlavha") or a["url"].rsplit("/", 1)[-1], 90)
        sess = a.get("sessiyalar") or []
        sess_s = " ".join(asos.wikilink(r, "↗") for r, _ in sess[:3]) or "—"
        q.append(f"| {a.get('sana') or '—'} | [{nom}]({a['url']}) | {a.get('turi') or '—'} | {sess_s} |")
    q.append("")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("claude/artifactlar.md", "\n".join(q))
    return {"artifactlar": len(royxat)}
