#!/usr/bin/env python3
"""push_chat.py — DATA/chat/*.md ni REPORTS_REPO 'chat/' papkasiga push qiladi (B2.2).

push_reports.py naqshi. ALOHIDA klon (DATA/chat-repo) — 09:00 hisobotlar push bilan bir
ishchi katalogda poyga bo'lmasin (push_reports.py TEGILMAYDI). Best-effort: supervisor'ni
yiqitmaydi. Ikki job bitta REPORTS_REPO ga yozadi (chat/ vs hisobotlar/ — turli fayllar) →
non-fast-forward bo'lsa push oldidan `pull --rebase` + BIR marta qayta urinish.

Jim doimiy yiqilish ko'rinmas qolmasin: ketma-ket yiqilishlar state faylida sanaladi;
NOTIFY_AFTER dan oshsa supervisor egaga xabar beradi (stat() orqali).
Token DISKDA saqlanmaydi: origin TOKENSIZ URL, tarmoq amallariga token argument bilan.

Env: REPORTS_REPO (owner/nom) + GH_TOKEN_REPORTS (fine-grained PAT, Contents R+W).
"""
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
CHAT_SRC = DATA / "chat"
CLONE = DATA / "chat-repo"
STATE = DATA / "push_chat_state.json"
NOTIFY_AFTER = 6            # shuncha KETMA-KET yiqilishdan (~1 soat) keyin egaga xabar
_TOKEN_RE = re.compile(r"x-access-token:[^@]*@")


def log(msg):
    print(f"[push_chat] {msg}", flush=True)


def _san(msg):
    """git stderr'da token'li URL bo'lishi mumkin — chiqishdan oldin tozalanadi."""
    s = _TOKEN_RE.sub("x-access-token:***@", str(msg))
    tok = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    return s.replace(tok, "***") if tok else s


def _urls(repo, token):
    """(auth_url, clean_url) — token'li (klon/pull/push) va TOKENSIZ (config'da qoladi)."""
    return (f"https://x-access-token:{token}@github.com/{repo}.git",
            f"https://github.com/{repo}.git")


def sh(*cmd, check=True):
    r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(_san(f"{' '.join(cmd[:4])} → {r.stderr.strip()[:200]}"))
    return r


# ---------------------------------------------------------------- state (jim yiqilishni ko'rish)

def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"state saqlanmadi: {_san(str(e))}")


def _mark_ok():
    st = _load_state()
    st.update(last_success_ts=datetime.now().isoformat(timespec="seconds"),
              last_error=None, fail_streak=0)
    _save_state(st)


def _mark_fail(err):
    st = _load_state()
    st["last_error"] = _san(str(err))[:300]
    st["fail_streak"] = int(st.get("fail_streak") or 0) + 1
    _save_state(st)
    return st["fail_streak"]


def stat():
    """/vault_stat va supervisor uchun chat push holati (last_error sanitize'dan o'tgan)."""
    st = _load_state()
    return {"last_success_ts": st.get("last_success_ts"),
            "last_error": _san(st["last_error"]) if st.get("last_error") else None,
            "fail_streak": int(st.get("fail_streak") or 0)}


# ---------------------------------------------------------------- push

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


def _push_with_retry(auth):
    """push (TOKENLI URL argument — config'ga yozilmaydi); non-ff bo'lsa `pull --rebase` + 1 retry."""
    for attempt in (1, 2):
        if sh("git", "-C", str(CLONE), "push", "-q", auth, "HEAD", check=False).returncode == 0:
            return True
        if attempt == 1:
            log("push rad etildi (non-ff?) — pull --rebase + qayta urinish")
            if sh("git", "-C", str(CLONE), "pull", "--rebase", "-q", auth, check=False).returncode != 0:
                sh("git", "-C", str(CLONE), "rebase", "--abort", check=False)
                break
    return False


def main():
    repo = os.environ.get("REPORTS_REPO", "").strip()
    token = os.environ.get("GH_TOKEN_REPORTS", "").strip()
    if not repo or not token:
        log("REPORTS_REPO / GH_TOKEN_REPORTS yo'q — o'tkazildi")
        return 0
    auth, clean = _urls(repo, token)
    try:
        if not (CLONE / ".git").is_dir():
            sh("git", "clone", "--depth", "1", auth, str(CLONE))
            sh("git", "-C", str(CLONE), "remote", "set-url", "origin", clean)  # token diskda qolmasin
        else:
            sh("git", "-C", str(CLONE), "remote", "set-url", "origin", clean)  # eski tokenli bo'lsa tozala
            sh("git", "-C", str(CLONE), "pull", "--rebase", "-q", auth, check=False)
        if _sync_files() == 0:
            log("yangi/o'zgargan chat yo'q")
            _mark_ok()                         # mexanizm ishladi — jim yiqilish EMAS
            return 0
        sh("git", "-C", str(CLONE), "add", "-A")
        if sh("git", "-C", str(CLONE), "diff", "--cached", "--quiet", check=False).returncode == 0:
            log("commit qilinadigan o'zgarish yo'q")
            _mark_ok()
            return 0
        sh("git", "-C", str(CLONE),
           "-c", "user.name=abba-sheets-agent", "-c", "user.email=agent@abba.local",
           "commit", "-q", "-m", f"chat {date.today().isoformat()}")
        if _push_with_retry(auth):
            log("chat push qilindi")
            _mark_ok()
        else:
            n = _mark_fail("push yiqildi (non-ff/tarmoq?) — retry ham o'tmadi")
            log(f"push yiqildi ({n}-marta ketma-ket) — keyingi sikl qayta urinadi")
            return 1
    except Exception as e:
        n = _mark_fail(e)
        log(f"XATO ({n}-marta ketma-ket): {type(e).__name__}: {_san(str(e))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
