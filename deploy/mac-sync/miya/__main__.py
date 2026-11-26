"""Ikkinchi miya yig'uvchisi — kirish nuqtasi.

  python3 -m miya                 # hammasi (launchd har soatda shuni chaqiradi)
  python3 -m miya --quruq         # diskka yozmasdan: nima o'zgarishini ko'rsatadi
  python3 -m miya --hammasi       # keshga qaramay hamma sessiya/kunni qayta yozish
  python3 -m miya --faqat sessiyalar,skillar
  python3 -m miya --obsidian-och  # vault'ni Obsidian'da ochish (ro'yxatda bo'lmasa qo'shiladi)
  python3 -m miya --xulosa on --soat 21:30   # kechki Telegram xulosasini yoqish (+ launchd jadvali)
  python3 -m miya --xulosa-korish # xulosa matnini yubormasdan ko'rish
  python3 -m miya --xulosa-yubor  # xulosani hozir yuborish (sinov)

Hech bir manba xatosi butun yig'ishni to'xtatmaydi: xato logga va tizim/miya-holati.md ga yoziladi.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from . import (artifactlar, asos, avtomatika, hublar, kod, obsidian, sessiyalar, skillar,
               sorovlar, walle, xulosa)

BOSQICHLAR = ("sessiyalar", "sorovlar", "skillar", "kod", "artifactlar", "walle", "avtomatika",
              "hublar", "obsidian")


def _holat_sahifa(yozuvchi: asos.Yozuvchi, natijalar: dict, xatolar: dict) -> None:
    fm = {"turi": "miya-holati", "tags": ["tizim"]}
    q = [asos.frontmatter(fm), "# Miya yig'uvchisi — holat\n",
         asos.avto_izoh("yig'uvchining o'z holati"), "",
         f"**Oxirgi yig'ish sanasi:** {asos.bugun()} · har soatda ishlaydi (launchd `com.abba.miya`).\n",
         "| Bo'lim | Natija |\n|---|---|"]
    for b in BOSQICHLAR:
        if b in xatolar:
            q.append(f"| {b} | ⚠️ {asos.bir_qator(xatolar[b], 160)} |")
        elif b in natijalar:
            q.append(f"| {b} | ✅ {asos.bir_qator(natijalar[b], 160)} |")
    q.append("")
    if yozuvchi.ogohlar:
        q.append("## Ogohlantirishlar\n")
        q.extend(f"- {asos.bir_qator(o, 200)}" for o in sorted(set(yozuvchi.ogohlar))[:20])
        q.append("")
    q.append("Kod: `~/.abba-miya/miya/` (manba: WALL-E repo, `deploy/mac-sync/miya/`). "
             "Log: `~/.abba-miya/miya.log`.\n")
    q.append(asos.QOLDA_BLOK)
    yozuvchi.yoz("tizim/miya-holati.md", "\n".join(q))


def yig(quruq: bool = False, hammasi: bool = False, faqat: set | None = None) -> dict:
    y = asos.Yozuvchi(quruq=quruq)
    natijalar, xatolar = {}, {}
    sh = asos.holat_oqi("sessiyalar")
    sorov_oylar, skill_soni, art_soni, kod_soni, loy_soni, oylar = {}, 0, 0, 0, 0, []
    urug = artifactlar.urug()
    nomlar = {u: a.get("sarlavha") for u, a in urug.items() if a.get("sarlavha")}

    def bosqich(nom, fn):
        if faqat and nom not in faqat:
            return None
        t = time.time()
        try:
            r = fn()
            natijalar[nom] = r if isinstance(r, str) else "ok"     # vaqt yozilmaydi: sahifa barqaror bo'lsin
            return r
        except Exception as e:
            xatolar[nom] = f"{type(e).__name__}: {e}"
            asos.log(f"{nom} XATO: {type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}")
            return None

    r = bosqich("sessiyalar", lambda: sessiyalar.yigish(y, hammasi=hammasi, artifact_nomlari=nomlar))
    if r:
        sh = r["holat"] if not quruq else {**sh, **r["holat"]}
        natijalar["sessiyalar"] = f"{sum(1 for v in sh.values() if isinstance(v, dict) and v.get('rel'))} sessiya"
    r = bosqich("sorovlar", lambda: sorovlar.yigish(y))
    if r:
        sorov_oylar = r["oylar"]
        natijalar["sorovlar"] = f"{sum(sorov_oylar.values())} so'rov, {len(sorov_oylar)} oy"
    r = bosqich("skillar", lambda: skillar.yigish(y, sh))
    if r:
        skill_soni = len(r["skillar"])
        natijalar["skillar"] = f"{skill_soni} skill"
    r = bosqich("kod", lambda: kod.yigish(y, sh))
    if r:
        kod_soni = len(r["loyihalar"])
        natijalar["kod"] = f"{kod_soni} loyiha"
    r = bosqich("artifactlar", lambda: artifactlar.yigish(y, sh))
    if r:
        art_soni = r["artifactlar"]
        natijalar["artifactlar"] = f"{art_soni} artifact"
    r = bosqich("walle", lambda: walle.yigish(y, sh, hammasi=hammasi))
    if r:
        natijalar["walle"] = f"{r['kunlar']} kun"
    bosqich("avtomatika", lambda: avtomatika.yigish(y))

    def _hub():
        nonlocal oylar, loy_soni
        oylar = hublar.oy_indekslari(y, sh)
        hublar.claude_index(y, sh, oylar, sorov_oylar, skill_soni, art_soni)
        loy_soni = hublar.loyihalar(y)
        hublar.baselar(y)
        n_sess = sum(1 for v in sh.values() if isinstance(v, dict) and v.get("rel"))
        hublar.bosh_sahifa(y, sh, {"sessiyalar": n_sess, "skillar": skill_soni, "kod": kod_soni,
                                   "artifactlar": art_soni, "loyihalar": loy_soni})
        return f"{len(oylar)} oy, {loy_soni} loyiha"
    bosqich("hublar", _hub)
    r = bosqich("obsidian", lambda: obsidian.sozla(y.vault, quruq=quruq))
    if r is not None:
        royxat = obsidian.royxatdami(y.vault)
        natijalar["obsidian"] = (("yaratildi: " + ", ".join(r) + "; ") if r else "") + \
            ("ilovada ro'yxatda" if royxat else "ilovada hali ochilmagan (--obsidian-och)")
    if not faqat:
        _holat_sahifa(y, natijalar, xatolar)
    return {"yozuvchi": y, "natijalar": natijalar, "xatolar": xatolar, "sh": sh}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="miya", description="Ikkinchi miya yig'uvchisi (WALL-E)")
    ap.add_argument("--quruq", action="store_true", help="diskka yozmasdan ko'rsatish")
    ap.add_argument("--hammasi", action="store_true", help="keshga qaramay hammasini qayta yozish")
    ap.add_argument("--faqat", help="vergul bilan: " + ",".join(BOSQICHLAR))
    ap.add_argument("--obsidian-och", action="store_true", help="vault'ni Obsidian'da ochish")
    ap.add_argument("--xulosa", choices=("on", "off"), help="kechki Telegram xulosasi")
    ap.add_argument("--soat", help="xulosa soati, HH:MM (standart 21:30)")
    ap.add_argument("--xulosa-yubor", action="store_true", help="xulosani hozir yuborish")
    ap.add_argument("--xulosa-korish", action="store_true", help="xulosa matnini yubormasdan ko'rish")
    a = ap.parse_args(argv)
    if a.soat and not a.xulosa:
        ap.error("--soat faqat --xulosa on|off bilan birga ishlaydi (masalan: --xulosa on --soat 21:30)")

    if a.xulosa:
        try:
            s = xulosa.sozla(a.xulosa == "on", a.soat)
        except ValueError:
            print(f"miya: soat HH:MM ko'rinishida bo'lsin (masalan 21:30), berilgani: {a.soat}")
            return 2
        print(f"xulosa: {'yoqilgan' if s['yoqilgan'] else 'o‘chiq'}, soat {s['soat']}")
        print(xulosa.jadval_yangila(s))
        if s["yoqilgan"] and not xulosa.tayyormi():
            print("⚠️ ~/abba-sheets-agent/.env da TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID yo'q — "
                  "xulosa yuborilmaydi")
        return 0
    if a.xulosa_korish:
        print(xulosa.xabar(asos.holat_oqi("sessiyalar"), asos.vault(), asos.bugun()))
        return 0
    if a.obsidian_och:
        obsidian.sozla()
        natija = obsidian.och()
        print({"ochildi": "Obsidian ochildi: ~/claude-brain (Bosh sahifa)",
               "ilova-ochiq": "Obsidian hozir ochiq — ro'yxatga qo'shish uchun uni yoping va qayta "
                              "ishga tushiring, yoki Obsidian'da: Open folder as vault → ~/claude-brain",
               }.get(natija, "Obsidian ochilmadi (log: ~/.abba-miya/miya.log)"))
        return 0 if natija == "ochildi" else 1

    faqat = {x.strip() for x in a.faqat.split(",")} if a.faqat else None
    try:
        with asos.Qulf():
            t = time.time()
            r = yig(quruq=a.quruq, hammasi=a.hammasi, faqat=faqat)
            y = r["yozuvchi"]
            xs = "-"
            if not a.quruq and not faqat:
                try:
                    xs = xulosa.ishla(r["sh"], y.vault, majburiy=a.xulosa_yubor)
                except Exception as e:      # xulosa xatosi yig'ish natijasini (log, holat) buzmasin
                    xs = f"xato ({type(e).__name__})"
                    asos.log(f"xulosa XATO: {type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}")
    except RuntimeError as e:
        print(f"miya: {e}")
        return 0
    qisqa = ", ".join(f"{k}={v}" for k, v in sorted(y.hisob.items()))
    xato = "; ".join(f"{k}: {v}" for k, v in r["xatolar"].items())
    asos.log(f"yig'ish {time.time() - t:.1f}s — {qisqa}; xulosa={xs}" + (f"; XATO {xato}" if xato else ""))
    print(f"{'QURUQ — ' if a.quruq else ''}{qisqa} ({time.time() - t:.1f}s); xulosa: {xs}")
    if a.quruq:
        for holat, rel in y.ozgargan:
            print(f"  {holat:10} {rel}")
    for k, v in r["xatolar"].items():
        print(f"  XATO {k}: {v}", file=sys.stderr)
    return 1 if r["xatolar"] else 0


if __name__ == "__main__":
    sys.exit(main())
