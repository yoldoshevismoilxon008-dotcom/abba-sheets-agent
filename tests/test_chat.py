"""B2.2 — chat arxivi (past vaznli kontekst, Claude'siz, 90-kun kesim) testlari.

pytest tests/test_chat.py  yoki  python3 tests/test_chat.py
"""
import os
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb                    # noqa: E402
import vault_sync as vs      # noqa: E402
import chat_log              # noqa: E402

_ORIG_INGEST = kb.ingest_file


def _fake_claude(prompt, effort="low"):
    return '{"title":"T","lang":"uz","tags":["x"],"summary":"s"}'


def _kbsetup():
    d = Path(tempfile.mkdtemp(prefix="chattest_"))
    kb.DATA = d
    kb.DB_PATH = d / "knowledge.db"
    kb._ask_claude = _fake_claude
    kb.ingest_file = _ORIG_INGEST
    kb.init_db()
    return d


# ---------------------------------------------------------------- source-map + 90-kun

def test_source_for():
    assert vs._source_for("chat/2026-08-12.md") == "chat"
    assert vs._source_for("bilim/x.md") == "vault"
    assert vs._source_for("kunlik/2026-08-12.md") == "vault"


def test_chat_indexable_90_days():
    today = date(2026, 8, 12)
    assert vs._chat_indexable("chat/2026-08-12.md", today)          # bugun
    assert vs._chat_indexable("chat/2026-06-01.md", today)          # 72 kun — kiradi
    assert not vs._chat_indexable("chat/2026-05-01.md", today)      # 103 kun — chiqadi
    assert not vs._chat_indexable("chat/2026-05-13.md", today)      # 91 kun — chiqadi
    assert vs._chat_indexable("chat/2026-05-14.md", today)          # 90 kun — kiradi (chegara)
    assert vs._chat_indexable("chat/izoh.md", today)                # sanasiz → True (yo'qotmaymiz)


# ---------------------------------------------------------------- kb: chat Claude'siz meta

def test_chat_never_calls_claude():
    _kbsetup()
    calls = {"n": 0}

    def counting(p, effort="low"):
        calls["n"] += 1
        return '{"title":"X","lang":"uz","tags":[],"summary":"s"}'

    kb._ask_claude = counting
    big = "# Suhbat\n\n" + ("Savol javob matni bo'lagi. " * 200)     # >1500 belgi
    r = kb.ingest_text(big, source="chat", origin="chat/2026-08-12.md",
                       vault_path="chat/2026-08-12.md", content_key=True, meta_min_chars=1500)
    assert calls["n"] == 0                            # chat → Claude UMUMAN chaqirilmadi
    assert r["title"] == "Suhbat arxivi — 2026-08-12"
    assert "suhbat" in r["tags"]


# ---------------------------------------------------------------- kb: chat reyting jarimasi

def test_chat_penalty_ranking():
    _kbsetup()
    body = "Undiruv qarz muddat ANIQSOZ qoidasi batafsil bayoni."
    kb.ingest_text(body, source="vault", origin="bilim/u.md",
                   vault_path="bilim/u.md", content_key=True)
    kb.ingest_text(body, source="chat", origin="chat/2026-08-12.md",
                   vault_path="chat/2026-08-12.md", content_key=True)
    res = kb.search("ANIQSOZ undiruv", k=8, use_rerank=False, use_expansion=False)
    srcs = [r["source"] for r in res]
    assert "vault" in srcs and "chat" in srcs
    assert srcs.index("vault") < srcs.index("chat")   # bir xil matn — jarima vault'ni yuqori qo'yadi


# ---------------------------------------------------------------- context_for: chat keyin, ≤2

def test_context_for_chat_after_vault_and_capped():
    _kbsetup()
    kb.ingest_text("# Vault\n\nVault MAVZUSOZ hujjati matni.", source="vault",
                   origin="bilim/v.md", vault_path="bilim/v.md", content_key=True)
    for i in range(3):
        kb.ingest_text(f"## 1{i}:00 · Javob\nChat MAVZUSOZ javob {i}.", source="chat",
                       origin=f"chat/2026-08-1{i}.md", vault_path=f"chat/2026-08-1{i}.md",
                       content_key=True)
    ctx = kb.context_for("MAVZUSOZ", use_rerank=False, use_expansion=False)
    assert "[O'TGAN SUHBAT" in ctx                             # chat alohida sarlavha
    assert ctx.index("Vault MAVZUSOZ") < ctx.index("[O'TGAN SUHBAT")   # vault CHAT'dan avval
    assert ctx.count("Chat MAVZUSOZ") <= 2                     # ko'pi 2 chat bo'lagi


# ---------------------------------------------------------------- vault_sync integratsiya

def _vssetup():
    d = _kbsetup()
    vs.DATA = d
    vs.CLONE = d / "vault"
    vs.STATE = d / "st.json"
    vs._LOCK = threading.Lock()
    clone = d / "vault"
    clone.mkdir(parents=True, exist_ok=True)
    vs._ensure_clone = lambda repo, token: clone
    os.environ["VAULT_REPO"] = "x/y"
    os.environ["GH_TOKEN_VAULT"] = "tok"
    (clone / ".kbignore").write_text("\n", encoding="utf-8")
    return clone


def _write(clone, rel, text="matn"):
    p = clone / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# H\n\n{text} UNIKALSOZ", encoding="utf-8")
    return p


def test_vault_sync_chat_source_mapping():
    clone = _vssetup()
    _write(clone, "bilim/a.md")
    _write(clone, f"chat/{date.today().isoformat()}.md")
    r = vs.run()
    assert r["status"] == "ok"
    assert "bilim/a.md" in kb.origins("vault")          # bilim/ → vault
    assert f"chat/{date.today().isoformat()}.md" in kb.origins("chat")   # chat/ → chat
    assert kb.origins("chat") and "chat" not in [o.split("/")[0] for o in kb.origins("vault")]


def test_old_chat_archived_vault_untouched():
    """fix#4 — ATAYLAB: 90 kundan eski chat arxivlanadi; vault hujjatlari HECH tegilmaydi."""
    clone = _vssetup()
    _write(clone, "bilim/keep.md")
    old = (date.today() - timedelta(days=200)).isoformat()
    _write(clone, f"chat/{old}.md")
    # eski chat AVVAL (young paytida) ingest qilingan edi — simulyatsiya:
    kb.ingest_text("## eski\nmatn", source="chat", origin=f"chat/{old}.md",
                   vault_path=f"chat/{old}.md", content_key=True)
    assert f"chat/{old}.md" in kb.origins("chat")
    r = vs.run()
    assert f"chat/{old}.md" not in kb.origins("chat")   # eski chat ARXIVLANDI
    assert r["counts"]["aged_chat"] >= 1
    assert r["counts"]["archived"] == 1                  # FAQAT eski chat (vault emas)
    assert "bilim/keep.md" in kb.origins("vault")        # vault hujjati tegilmadi


def test_empty_chat_folder():
    clone = _vssetup()
    _write(clone, "bilim/a.md")
    r = vs.run()
    assert r["status"] == "ok"
    assert kb.origins("chat") == []                      # chat papkasi yo'q — muammosiz
    assert "bilim/a.md" in kb.origins("vault")


# ---------------------------------------------------------------- chat_log

def _chatsetup():
    d = Path(tempfile.mkdtemp(prefix="cltest_"))
    chat_log.DATA = d
    chat_log.CHAT_DIR = d / "chat"
    return d


def test_chat_log_format_cmd_and_daychange():
    _chatsetup()
    d1 = datetime(2026, 8, 12, 16, 42)
    d2 = datetime(2026, 8, 13, 9, 5)
    chat_log.append_qa("Savol matni", "Javob matni", now=d1)
    chat_log.append_cmd("/bilim_stat", now=d1)
    chat_log.append_qa("Ertangi savol", "Javob2", now=d2)
    f1 = (chat_log.CHAT_DIR / "2026-08-12.md").read_text(encoding="utf-8")
    assert "# 2026-08-12 — Suhbat arxivi" in f1
    assert "## 16:42 · Savol\nSavol matni" in f1 and "## 16:42 · Javob\nJavob matni" in f1
    assert "- 16:42 · /bilim_stat" in f1                       # buyruq — BIR qator
    assert (chat_log.CHAT_DIR / "2026-08-13.md").exists()      # kun almashdi → yangi fayl


def test_chat_log_append_error_swallowed():
    """Append xatosi javobni to'xtatmaydi — best-effort (istisno yutiladi)."""
    chat_log.CHAT_DIR = Path("/proc/nope-xyz-b22/chat")        # yozib bo'lmaydi
    chat_log.append_qa("q", "a", now=datetime(2026, 8, 12, 1, 1))   # raise QILMAYDI
    chat_log.append_cmd("/x", now=datetime(2026, 8, 12, 1, 1))      # raise QILMAYDI


# ---------------------------------------------------------------- push_chat (haqiqiy git)

def _gitc(repo, msg):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", msg], check=True)


def test_push_chat_sync_and_nonff_retry():
    """fix#2: DATA/chat → clone/chat sync; push non-ff bo'lsa pull --rebase + qayta urinish."""
    import push_chat as pc
    base = Path(tempfile.mkdtemp(prefix="pctest_"))
    bare, seed = base / "reports.git", base / "seed"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
    (seed / "README.md").write_text("init", encoding="utf-8")
    _gitc(seed, "init")
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD"], check=True)

    pc.CLONE = base / "chat-repo"
    subprocess.run(["git", "clone", "-q", str(bare), str(pc.CLONE)], check=True)
    pc.CHAT_SRC = base / "chatsrc"
    pc.CHAT_SRC.mkdir()
    (pc.CHAT_SRC / "2026-08-12.md").write_text("# chat\nsavol", encoding="utf-8")

    assert pc._sync_files() == 1                        # DATA/chat → clone/chat/
    assert (pc.CLONE / "chat" / "2026-08-12.md").exists()
    _gitc(pc.CLONE, "chat")

    # non-ff: remote seed orqali oldinga ketadi (boshqa fayl — hisobotlar/)
    (seed / "hisobotlar.md").write_text("rep", encoding="utf-8")
    _gitc(seed, "rep")
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD"], check=True)

    assert pc._push_with_retry(str(bare)) is True        # push rad → pull --rebase → qayta → OK
    subprocess.run(["git", "-C", str(seed), "pull", "-q", "--rebase"], check=True)
    assert (seed / "chat" / "2026-08-12.md").exists()   # chat remote'ga yetdi
    assert (seed / "hisobotlar.md").exists()            # hisobotlar ham saqlandi (rebase)


# ---------------------------------------------------------------- fix#1: jim yiqilish → notify

def test_push_chat_failstreak_and_sanitize():
    """Ketma-ket yiqilishlar sanaladi; last_error token'siz (sanitize)."""
    import push_chat as pc
    pc.STATE = Path(tempfile.mkdtemp(prefix="pcst_")) / "st.json"
    os.environ["GH_TOKEN_REPORTS"] = "SECRETTOK"
    for i in range(1, 7):
        assert pc._mark_fail(
            "fatal: https://x-access-token:SECRETTOK@github.com/x/y.git 403") == i
    s = pc.stat()
    assert s["fail_streak"] == 6
    assert "SECRETTOK" not in s["last_error"] and "***" in s["last_error"]
    pc._mark_ok()
    s2 = pc.stat()
    assert s2["fail_streak"] == 0 and s2["last_error"] is None and s2["last_success_ts"]
    os.environ.pop("GH_TOKEN_REPORTS", None)


def test_supervisor_notifies_on_chat_failstreak():
    """6 ketma-ket yiqilishdan keyin egaga xabar; yo'l <code> ichida (token/avtolink yo'q)."""
    import send as sendmod
    import supervisor
    import push_chat as pc
    supervisor.DATA = Path(tempfile.mkdtemp(prefix="supchat_"))
    os.environ["TELEGRAM_BOT_TOKEN"] = "x"
    os.environ["TELEGRAM_CHAT_ID"] = "1"
    captured = []
    o_tg, o_main, o_stat = sendmod.tg_send, pc.main, pc.stat
    sendmod.tg_send = lambda token, chat, msg: captured.append(msg)
    pc.main = lambda: 1
    pc.stat = lambda: {"last_success_ts": None, "last_error": "fetch bilim/x.md yiqildi",
                       "fail_streak": 6}
    try:
        supervisor.run_push_chat()
    finally:
        sendmod.tg_send, pc.main, pc.stat = o_tg, o_main, o_stat
    assert captured, "notify yuborilmadi"
    msg = captured[0]
    assert "6 marta" in msg and "<code>" in msg
    assert ".md" not in msg.split("<code>")[0]           # .md faqat <code> ichida


# ---------------------------------------------------------------- fix#2: token diskda emas

def _rec_git(calls):
    from types import SimpleNamespace

    def rec(*cmd, check=True, cwd=None):
        calls.append(" ".join(str(c) for c in cmd))
        if "clone" in cmd:
            (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
        rc = 1 if "diff" in cmd else 0                   # diff --cached --quiet → o'zgarish bor
        return SimpleNamespace(returncode=rc, stdout="", stderr="")
    return rec


def _assert_token_not_in_config(calls, token):
    seturl = [c for c in calls if "set-url" in c]
    assert seturl, "set-url chaqirilmadi"
    assert "https://github.com/owner/repo.git" in seturl[0]      # TOKENSIZ URL config'ga
    assert not any("set-url" in c and token in c for c in calls)  # set-url'da HECH token yo'q
    pushes = [c for c in calls if " push " in c]
    assert any(token in c and c.strip().endswith("HEAD") for c in pushes)  # push token argument bilan


def test_push_chat_token_not_in_config():
    import push_chat as pc
    base = Path(tempfile.mkdtemp(prefix="pctok_"))
    pc.CLONE, pc.STATE = base / "clone", base / "st.json"
    pc.CHAT_SRC = base / "src"
    pc.CHAT_SRC.mkdir()
    (pc.CHAT_SRC / "2026-08-12.md").write_text("x", encoding="utf-8")
    os.environ["REPORTS_REPO"], os.environ["GH_TOKEN_REPORTS"] = "owner/repo", "SECRETTOK"
    calls, o_sh = [], pc.sh
    pc.sh = _rec_git(calls)
    try:
        pc.main()
    finally:
        pc.sh = o_sh
    _assert_token_not_in_config(calls, "SECRETTOK")


def test_push_reports_token_not_in_config():
    import push_reports as pr
    base = Path(tempfile.mkdtemp(prefix="prtok_"))
    pr.CLONE, pr.SNAPSHOTS = base / "clone", base / "snaps"
    snap = pr.SNAPSHOTS / "2026-08-12"
    snap.mkdir(parents=True)
    (snap / "report.md").write_text("hisobot matni", encoding="utf-8")
    os.environ["REPORTS_REPO"], os.environ["GH_TOKEN_REPORTS"] = "owner/repo", "SECRETTOK"
    calls, o_sh = [], pr.sh
    pr.sh = _rec_git(calls)
    try:
        pr.main()
    finally:
        pr.sh = o_sh
    _assert_token_not_in_config(calls, "SECRETTOK")


# ---------------------------------------------------------------- fix#4: chat_log clip

def test_chat_log_clip_long_answer():
    _chatsetup()
    chat_log.append_qa("q", "A" * 20000, now=datetime(2026, 8, 12, 1, 1))
    f = (chat_log.CHAT_DIR / "2026-08-12.md").read_text(encoding="utf-8")
    assert "…(qisqartirildi)" in f
    assert len(f) < 20000                                # to'liq 20000 tushmadi — kesildi


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
