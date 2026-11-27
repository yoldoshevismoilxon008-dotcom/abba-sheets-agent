#!/usr/bin/env python3
"""Kunlik hisobotlarni ikkinchi private repo'ga push qiladi (Railway'dan).

supervisor.run_daily() pipeline'dan keyin chaqiradi. Env:
  REPORTS_REPO      — owner/nom (masalan ismoilxon/abba-hisobotlar)
  GH_TOKEN_REPORTS  — fine-grained PAT, faqat shu repo'ga Contents: Read+Write

Klon DATA_DIR/hisobotlar-repo da yashaydi (volume). Idempotent: mavjud va
o'zgarmagan fayllar push qilinmaydi. Format export_obsidian.py bilan bir xil —
Mac'dagi vault_pull to'g'ridan-to'g'ri vault'ga ko'chiradi.

Repo'ga yozilgan hisobot vault'ga (GitHub) va WALL-E bilim bazasiga tushadi, shuning
uchun telefon raqamlari yozishdan OLDIN yashiriladi (maxfiy.telefon_yashir). Snapshot
o'zi (DATA/snapshots) va egaga ketgan hisobot o'zgarmaydi.
"""
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
SNAPSHOTS = DATA / "snapshots"
CLONE = DATA / "hisobotlar-repo"


from maxfiy import redact, telefon_yashir  # noqa: E402  (log'da sir yo'q; repo'da telefon yo'q)


def log(msg):
    print(f"[push_reports] {redact(msg)}", flush=True)


_TOKEN_RE = re.compile(r"x-access-token:[^@]*@")


def _san(msg):
    """git stderr'da token'li URL bo'lishi mumkin — log'ga chiqishdan oldin tozalanadi."""
    s = _TOKEN_RE.sub("x-access-token:***@", str(msg))
    tok = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    return s.replace(tok, "***") if tok else s


def sh(*cmd, cwd=None, env=None):
    r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=180, env=env)
    if r.returncode != 0:
        raise RuntimeError(_san(f"{' '.join(cmd[:4])} → {r.stderr.strip()[:250]}"))
    return r.stdout


def _hisobotlarni_yoz(out):
    """SNAPSHOTS/<sana>/report.md → out/<sana>.md, telefon raqamlari yashirilgan holda.
    Snapshot'i retention'da (30 kun, run.sh) o'chib ketgan eski hisobotlar repo'da
    boshqa qayta yozilmaydi — ular ham shu yerda joyida maskalanadi (idempotent:
    telefon yo'q faylga tegilmaydi). Qaytadi: o'zgargan fayllar soni."""
    changed = 0
    manbali = set()
    if SNAPSHOTS.is_dir():
        for d in sorted(SNAPSHOTS.iterdir()):
            rep = d / "report.md"
            if not (d.is_dir() and len(d.name) == 10 and rep.exists()):
                continue
            body = telefon_yashir(
                f"# {d.name} — Sheets kunlik hisobot\n\n{rep.read_text(encoding='utf-8').strip()}\n")
            dst = out / f"{d.name}.md"
            manbali.add(dst.name)
            if not dst.exists() or dst.read_text(encoding="utf-8") != body:
                dst.write_text(body, encoding="utf-8")
                changed += 1
    for dst in sorted(out.glob("*.md")):
        if dst.name in manbali:
            continue
        try:
            eski = dst.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log(f"{dst.name} o'qilmadi — telefon tekshirilmadi: {type(e).__name__}")
            continue
        yangi = telefon_yashir(eski)
        if yangi != eski:
            dst.write_text(yangi, encoding="utf-8")
            changed += 1
    return changed


def main():
    repo = os.environ.get("REPORTS_REPO", "").strip()
    token = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    if not repo or not token:
        log("REPORTS_REPO / GH_TOKEN_REPORTS yo'q — o'tkazildi")
        return 0
    # Token na DISKDA, na git ARGV'ida (ps): URL tokensiz, token GIT_CONFIG_* env'da (git_auth)
    import git_auth

    clean = git_auth.url(repo)
    genv = git_auth.env(token)

    if not (CLONE / ".git").is_dir():
        sh("git", "clone", "--depth", "1", clean, str(CLONE), env=genv)
        sh("git", "-C", str(CLONE), "remote", "set-url", "origin", clean)   # tokensiz origin
    else:
        sh("git", "-C", str(CLONE), "remote", "set-url", "origin", clean)   # eski tokenli bo'lsa tozala
        try:
            sh("git", "-C", str(CLONE), "pull", "--rebase", "-q", clean, env=genv)
        except RuntimeError as e:
            log(f"pull yiqildi ({_san(str(e))}) — klon yangidan olinadi")
            shutil.rmtree(CLONE, ignore_errors=True)
            sh("git", "clone", "--depth", "1", clean, str(CLONE), env=genv)
            sh("git", "-C", str(CLONE), "remote", "set-url", "origin", clean)

    out = CLONE / "hisobotlar"
    out.mkdir(exist_ok=True)
    changed = _hisobotlarni_yoz(out)
    if not changed:
        log("yangi/o'zgargan hisobot yo'q")
        return 0
    sh("git", "-C", str(CLONE), "add", "-A")
    sh(
        "git", "-C", str(CLONE),
        "-c", "user.name=abba-sheets-agent", "-c", "user.email=agent@abba.local",
        "commit", "-q", "-m", f"hisobot {date.today().isoformat()}",
    )
    sh("git", "-C", str(CLONE), "push", "-q", clean, "HEAD", env=genv)
    log(f"{changed} hisobot push qilindi → {repo}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"XATO: {type(e).__name__}: {_san(str(e))}")
        sys.exit(1)
