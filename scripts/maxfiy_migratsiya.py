#!/usr/bin/env python3
"""Maxfiy ma'lumotni public repo'dan chiqarish migratsiyasi (audit P0-2) — BIR MARTALIK.

Git tarixidagi eski commit'dan (Sheet ID'lar config.yaml'da, undiruv_qaror.json repo'da
bo'lgan holat) quyidagilarni yasaydi:
  config.local.yaml   — {dashboard_id, sheet_ids: {sheet nomi: id}} (.gitignore'da)
  undiruv_qaror.json  — ega qarorlari (.gitignore'da)
va Railway Variables uchun base64 qiymatlarni chiqaradi:
  CONFIG_LOCAL_B64, UNDIRUV_QAROR_B64

Ishlatish (Mac, loyiha papkasida):
  python3 scripts/maxfiy_migratsiya.py               # eski commit avtomatik topiladi
  python3 scripts/maxfiy_migratsiya.py --ref 15a590a # aniq commit
  python3 scripts/maxfiy_migratsiya.py --force       # mavjud fayllarni qayta yozish
  python3 scripts/maxfiy_migratsiya.py --no-b64      # base64 chiqarmasin

Diqqat: chiqqan base64 — maxfiy qiymat. Uni faqat Railway Variables'ga qo'ying, chatga
yoki repo'ga yozmang.
"""
import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent


def git(*args):
    r = subprocess.run(["git", "-C", str(BASE), *args], capture_output=True, text=True)
    return r.returncode, r.stdout


def show(ref, path):
    code, out = git("show", f"{ref}:{path}")
    return out if code == 0 else None


def eski_ref():
    """undiruv_qaror.json hali repo'da bo'lgan oxirgi commit (o'chirgan commit'ning ota-onasi)."""
    if show("HEAD", "undiruv_qaror.json") is not None:
        return "HEAD"
    code, out = git("rev-list", "-n", "1", "HEAD", "--", "undiruv_qaror.json")
    sha = out.strip()
    return f"{sha}^" if code == 0 and sha else None


def overlay_from(cfg_text):
    cfg = yaml.safe_load(cfg_text) or {}
    ids = {s["name"]: str(s["id"]) for s in cfg.get("sheets") or []
           if s.get("name") and s.get("id")}
    out = {"sheet_ids": ids}
    if cfg.get("dashboard_id"):
        out["dashboard_id"] = str(cfg["dashboard_id"])
    return out


def yoz(path, text, force):
    if path.exists() and not force:
        print(f"  • {path.name}: allaqachon bor — tegilmadi (--force bilan qayta yoziladi)")
        return path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    print(f"  ✓ {path.name} yozildi")
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", help="maxfiy ma'lumot hali repo'da bo'lgan commit (default: avtomatik)")
    ap.add_argument("--force", action="store_true", help="mavjud fayllarni qayta yozish")
    ap.add_argument("--no-b64", action="store_true", help="Railway uchun base64 chiqarmaslik")
    a = ap.parse_args()

    ref = a.ref or eski_ref()
    if not ref:
        print("XATO: eski commit topilmadi — --ref bilan bering (masalan: --ref 15a590a)")
        return 1
    cfg_text, qaror_text = show(ref, "config.yaml"), show(ref, "undiruv_qaror.json")
    if cfg_text is None:
        print(f"XATO: {ref} da config.yaml yo'q")
        return 1
    ov = overlay_from(cfg_text)
    if not ov["sheet_ids"]:
        print(f"XATO: {ref} dagi config.yaml'da Sheet ID yo'q — boshqa --ref bering")
        return 1
    print(f"Manba commit: {ref} — {len(ov['sheet_ids'])} ta sheet ID"
          + (", dashboard_id bor" if ov.get("dashboard_id") else ""))

    cl = yoz(BASE / "config.local.yaml",
             "# Maxfiy: Google Sheet ID'lar (git'da EMAS). fetch._overlay o'qiydi.\n"
             + yaml.safe_dump(ov, allow_unicode=True, sort_keys=False), a.force)
    qj = None
    if qaror_text is not None:
        json.loads(qaror_text)                       # buzuq bo'lsa — shu yerda to'xtaydi
        qj = yoz(BASE / "undiruv_qaror.json", qaror_text, a.force)
    else:
        print(f"  • {ref} da undiruv_qaror.json yo'q — o'tkazildi")

    if not a.no_b64:
        print("\nRailway → service → Variables (har biri BITTA qator; maxfiy — hech qayerga yozmang):")
        print("CONFIG_LOCAL_B64=" + base64.b64encode(cl.encode("utf-8")).decode())
        if qj is not None:
            print("UNDIRUV_QAROR_B64=" + base64.b64encode(qj.encode("utf-8")).decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
