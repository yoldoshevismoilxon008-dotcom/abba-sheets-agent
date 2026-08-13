#!/usr/bin/env python3
"""push_chat.py — DATA/chat/*.md ni REPORTS_REPO 'chat/' papkasiga push qiladi (B2.2).

push_reports.py naqshi. ALOHIDA klon (DATA/chat-repo) — 09:00 hisobotlar push bilan bir
ishchi katalogda poyga bo'lmasin (push_reports.py TEGILMAYDI). Best-effort: supervisor'ni
yiqitmaydi. Ikki job bitta REPORTS_REPO ga yozadi (chat/ vs hisobotlar/ — turli fayllar) →
non-fast-forward bo'lsa push oldidan `pull --rebase` + BIR marta qayta urinish; baribir
yiqilsa jim log (keyingi sikl o'zi tuzatadi).

Env: REPORTS_REPO (owner/nom) + GH_TOKEN_REPORTS (fine-grained PAT, Contents R+W).
"""
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
CHAT_SRC = DATA / "chat"
CLONE = DATA / "chat-repo"
_TOKEN_RE = re.compile(r"x-access-token:[^@]*@")


def log(msg):
    print(f"[push_chat] {msg}", flush=True)


def _san(msg):
    """git stderr'da token'li URL bo'lishi mumkin — log'ga chiqishdan oldin tozalanadi."""
    s = _TOKEN_RE.sub("x-access-token:***@", str(msg))
    tok = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    return s.replace(tok, "***") if tok else s


def sh(*cmd, check=True):
    r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(_san(f"{' '.join(cmd[:4])} → {r.stderr.strip()[:200]}"))
    return r


def _sync_files():
    """DATA/chat/*.md → clone/chat/ (append-fayllar to'liq nusxa). O'zgargan fayllar soni."""
    out = CLONE / "chat"
    out.mkdir(exist_ok=True)
    changed = 0
    if CHAT_SRC.is_dir():
        for src in sorted(CHAT_SRC.glob("*.md")):
            body = src.read_text(encoding="utf-8")
            dst = out / src.name
            if not dst.exists() or dst.read_text(encoding="utf-8") != body:
                dst.write_text(body, encoding="utf-8")
                changed += 1
    return changed


def _push_with_retry():
    """push; non-ff bo'lsa `pull --rebase` + BIR marta qayta. Muvaffaqiyat → True."""
    for attempt in (1, 2):
        if sh("git", "-C", str(CLONE), "push", "-q", check=False).returncode == 0:
            return True
        if attempt == 1:
            log("push rad etildi (non-ff?) — pull --rebase + qayta urinish")
            if sh("git", "-C", str(CLONE), "pull", "--rebase", "-q", check=False).returncode != 0:
                sh("git", "-C", str(CLONE), "rebase", "--abort", check=False)
                break
    return False


def main():
    repo = os.environ.get("REPORTS_REPO", "").strip()
    token = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    if not repo or not token:
        log("REPORTS_REPO / GH_TOKEN_REPORTS yo'q — o'tkazildi")
        return 0
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    try:
        if not (CLONE / ".git").is_dir():
            sh("git", "clone", "--depth", "1", url, str(CLONE))
        else:
            sh("git", "-C", str(CLONE), "remote", "set-url", "origin", url)
            sh("git", "-C", str(CLONE), "pull", "--rebase", "-q", check=False)  # boshda ham yangila
        if _sync_files() == 0:
            log("yangi/o'zgargan chat yo'q")
            return 0
        sh("git", "-C", str(CLONE), "add", "-A")
        if sh("git", "-C", str(CLONE), "diff", "--cached", "--quiet", check=False).returncode == 0:
            log("commit qilinadigan o'zgarish yo'q")
            return 0
        sh("git", "-C", str(CLONE),
           "-c", "user.name=abba-sheets-agent", "-c", "user.email=agent@abba.local",
           "commit", "-q", "-m", f"chat {date.today().isoformat()}")
        log("chat push qilindi" if _push_with_retry()
            else "push yiqildi — keyingi siklda qayta urinadi (jim)")
    except Exception as e:
        log(f"XATO: {type(e).__name__}: {_san(str(e))}")  # best-effort — supervisor'ni yiqitmaydi
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
