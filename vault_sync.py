#!/usr/bin/env python3
"""vault_sync.py — Obsidian "claude brain" vault → bilim bazasi (KB) sinxroni (B2.1).

FAQAT O'QISH yo'nalishi (Mac vault → GitHub private repo → Railway → kb).
Railway supervisor har 10 daqiqada run() chaqiradi.

Oqim (to'liq reconcile — vault kichik, content_hash tufayli arzon):
  1. VAULT_REPO'ni /data/vault ga shallow clone/pull (GH_TOKEN_VAULT bilan).
  2. Har .md faylni kb.ingest_file (source="vault", origin/vault_path=nisbiy yo'l,
     meta_min_chars=1500 — kichik faylga Claude metadata chaqirilmaydi).
     content_hash → o'zgarmagan fayl "unchanged" bo'lib o'tkazib yuboriladi.
  3. .kbignore (repo ildizi, gitignore sintaksis) papkalari NA kb'ga tushadi.
  4. kb'da bor, lekin vault'da endi yo'q fayllar → forget_origin (arxiv).

Xavfsizlik: run() HECH QACHON raise QILMAYDI — status dict qaytaradi, bot tirik qoladi.
Statuslar: disabled | no_kbignore | unconfigured | git_error | error | ok

Env:
  VAULT_REPO      — owner/nom (masalan yoldoshevismoilxon008-dotcom/claude-brain)
  GH_TOKEN_VAULT  — fine-grained PAT, faqat shu repo'ga Contents: Read
"""
import fnmatch
import json
import os
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
CLONE = DATA / "vault"
STATE = DATA / "vault_sync_state.json"

META_MIN = 1500              # bundan KICHIK faylga Claude metadata chaqirilmaydi
GIT_TIMEOUT = 300
# .kbignore'siz ham HAR DOIM chetlab o'tiladigan texnik papka/fayllar
ALWAYS_IGNORE = (".git", ".obsidian", ".trash")
# .kbignore hali sozlanmaganini bildiruvchi sentinel — mavjud bo'lsa sinxron o'chiq
UNCONFIGURED = "__UNCONFIGURED__"


def log(msg):
    print(f"[vault_sync] {msg}", flush=True)


# ---------------------------------------------------------------- .kbignore

def _kbignore_load(clone_dir):
    """.kbignore → pattern ro'yxati (izoh/bo'sh qatorlar tashlanadi).
    Fayl yo'q bo'lsa None qaytadi (chaqiruvchi 'no_kbignore' guard qiladi)."""
    f = Path(clone_dir) / ".kbignore"
    if not f.exists():
        return None
    pats = []
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            pats.append(s)
    return pats


def _kbignore_match(relpath, patterns):
    """relpath (root'ga nisbiy) .kbignore patternlariga mos keladimi.
    Qo'llab-quvvatlanadi: bare nom (har chuqurlikda), anchored yo'l,
    trailing '/' (papka), '*' glob, '!' inkor (keyingi mos bekor qiladi)."""
    rel = str(relpath).replace("\\", "/").lstrip("/")
    segs = rel.split("/")
    matched = False
    for pat in patterns:
        neg = pat.startswith("!")
        p = (pat[1:] if neg else pat).rstrip("/")
        if not p:
            continue
        if "/" in p.lstrip("/"):                 # anchored yo'l (a/b, /secret/x)
            p = p.lstrip("/")
            hit = (rel == p or rel.startswith(p + "/")
                   or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*"))
        else:                                    # bare nom — har chuqurlikdagi segment
            hit = any(fnmatch.fnmatch(seg, p) for seg in segs)
        if hit:
            matched = not neg
    return matched


def _always_ignore(rel):
    segs = rel.replace("\\", "/").split("/")
    return any(s in ALWAYS_IGNORE or s == ".DS_Store" for s in segs)


# ---------------------------------------------------------------- git

def _git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} → {r.stderr.strip()[:200]}")
    return r.stdout


def _ensure_clone(repo, token):
    """Shallow clone yoki pull → CLONE. Pull yiqilsa qayta klon. Monkeypatch qulay."""
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    CLONE.parent.mkdir(parents=True, exist_ok=True)
    if not (CLONE / ".git").is_dir():
        _git("clone", "--depth", "1", url, str(CLONE))
    else:
        _git("-C", str(CLONE), "remote", "set-url", "origin", url)
        try:
            _git("-C", str(CLONE), "pull", "--rebase", "-q")
        except RuntimeError as e:
            log(f"pull yiqildi ({e}) — qayta klon")
            shutil.rmtree(CLONE, ignore_errors=True)
            _git("clone", "--depth", "1", url, str(CLONE))
    return CLONE


# ---------------------------------------------------------------- state

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
        log(f"state saqlanmadi: {e}")


# ---------------------------------------------------------------- reconcile

def _reconcile(clone):
    """clone ichidagi barcha .md ni kb bilan solishtiradi (idempotent, resumable).
    Qaytadi status dict."""
    import kb

    clone = Path(clone)
    patterns = _kbignore_load(clone)
    if patterns is None:
        log(".kbignore yo'q — sinxron o'tkazildi (himoya guard)")
        return {"status": "no_kbignore"}
    if UNCONFIGURED in patterns:
        log(f".kbignore sozlanmagan ({UNCONFIGURED} bor) — sinxron o'chiq")
        return {"status": "unconfigured"}

    md_files = sorted(p for p in clone.rglob("*.md") if p.is_file())
    total = len(md_files)
    ingested = unchanged = errors = 0
    skipped_dirs = set()
    present = set()          # joriy vault fayllari (origin) — o'chirilganini aniqlash uchun

    for i, p in enumerate(md_files, 1):
        rel = p.relative_to(clone).as_posix()
        if _always_ignore(rel) or _kbignore_match(rel, patterns):
            skipped_dirs.add(rel.split("/", 1)[0])
            continue
        present.add(rel)
        try:
            r = kb.ingest_file(p, source="vault", origin=rel, vault_path=rel,
                               meta_min_chars=META_MIN)
            if r.get("status") == "unchanged":
                unchanged += 1
            else:
                ingested += 1
        except Exception as e:
            errors += 1
            log(f"ingest xato ({rel}): {str(e)[:120]}")
        if i % 50 == 0:
            log(f"progress {i}/{total} (yangi={ingested}, o'zgarmagan={unchanged})")

    # kb'da bor, vault'da endi yo'q → arxivlash
    archived = 0
    for origin in kb.origins("vault"):
        if origin not in present:
            archived += kb.forget_origin("vault", origin)

    st = {
        "status": "ok",
        "last_success_ts": kb._now(),
        "last_error": None,
        "counts": {"files": total, "ingested": ingested, "unchanged": unchanged,
                   "archived": archived, "errors": errors},
        "skipped_dirs": sorted(skipped_dirs),
    }
    _save_state(st)
    log(f"sinxron OK: {st['counts']} skip={st['skipped_dirs']}")
    return st


def run():
    """To'liq sinxron. HECH QACHON raise QILMAYDI — status dict qaytaradi."""
    repo = os.environ.get("VAULT_REPO", "").strip()
    token = os.environ.get("GH_TOKEN_VAULT", "").strip()
    if not repo or not token:
        return {"status": "disabled"}
    try:
        clone = _ensure_clone(repo, token)
    except Exception as e:
        msg = str(e)[:200]
        st = _load_state()
        st["last_error"] = f"git: {msg}"
        _save_state(st)
        log(f"git xato: {msg}")
        return {"status": "git_error", "error": msg}
    try:
        return _reconcile(clone)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        st = _load_state()
        st["last_error"] = msg
        _save_state(st)
        log(f"XATO reconcile: {msg}")
        return {"status": "error", "error": msg}


def stat():
    """/vault_stat uchun — state + kb vault kesimi."""
    st = _load_state()
    vault_docs = chunks = None
    try:
        import kb

        sc = kb.source_counts("vault")
        vault_docs, chunks = sc["docs"], sc["chunks"]
    except Exception as e:
        log(f"stat kb xato: {e}")
    return {
        "vault_docs": vault_docs,
        "chunks": chunks,
        "last_success_ts": st.get("last_success_ts"),
        "counts": st.get("counts") or {},
        "skipped_dirs": st.get("skipped_dirs") or [],
        "last_error": st.get("last_error"),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
