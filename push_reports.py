#!/usr/bin/env python3
"""Kunlik hisobotlarni ikkinchi private repo'ga push qiladi (Railway'dan).

supervisor.run_daily() pipeline'dan keyin chaqiradi. Env:
  REPORTS_REPO      — owner/nom (masalan ismoilxon/abba-hisobotlar)
  GH_TOKEN_REPORTS  — fine-grained PAT, faqat shu repo'ga Contents: Read+Write

Klon DATA_DIR/hisobotlar-repo da yashaydi (volume). Idempotent: mavjud va
o'zgarmagan fayllar push qilinmaydi. Format export_obsidian.py bilan bir xil —
Mac'dagi vault_pull to'g'ridan-to'g'ri vault'ga ko'chiradi.
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
SNAPSHOTS = DATA / "snapshots"
CLONE = DATA / "hisobotlar-repo"


def log(msg):
    print(f"[push_reports] {msg}", flush=True)


def sh(*cmd, cwd=None):
    r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} → {r.stderr.strip()[:250]}")
    return r.stdout


def main():
    repo = os.environ.get("REPORTS_REPO", "").strip()
    token = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    if not repo or not token:
        log("REPORTS_REPO / GH_TOKEN_REPORTS yo'q — o'tkazildi")
        return 0
    url = f"https://x-access-token:{token}@github.com/{repo}.git"

    if not (CLONE / ".git").is_dir():
        sh("git", "clone", "--depth", "1", url, str(CLONE))
    else:
        sh("git", "-C", str(CLONE), "remote", "set-url", "origin", url)
        try:
            sh("git", "-C", str(CLONE), "pull", "--rebase", "-q")
        except RuntimeError as e:
            log(f"pull yiqildi ({e}) — klon yangidan olinadi")
            shutil.rmtree(CLONE, ignore_errors=True)
            sh("git", "clone", "--depth", "1", url, str(CLONE))

    out = CLONE / "hisobotlar"
    out.mkdir(exist_ok=True)
    changed = 0
    if SNAPSHOTS.is_dir():
        for d in sorted(SNAPSHOTS.iterdir()):
            rep = d / "report.md"
            if not (d.is_dir() and len(d.name) == 10 and rep.exists()):
                continue
            body = f"# {d.name} — Sheets kunlik hisobot\n\n{rep.read_text(encoding='utf-8').strip()}\n"
            dst = out / f"{d.name}.md"
            if not dst.exists() or dst.read_text(encoding="utf-8") != body:
                dst.write_text(body, encoding="utf-8")
                changed += 1
    if not changed:
        log("yangi/o'zgargan hisobot yo'q")
        return 0
    sh("git", "-C", str(CLONE), "add", "-A")
    sh(
        "git", "-C", str(CLONE),
        "-c", "user.name=abba-sheets-agent", "-c", "user.email=agent@abba.local",
        "commit", "-q", "-m", f"hisobot {date.today().isoformat()}",
    )
    sh("git", "-C", str(CLONE), "push", "-q")
    log(f"{changed} hisobot push qilindi → {repo}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"XATO: {type(e).__name__}: {e}")
        sys.exit(1)
