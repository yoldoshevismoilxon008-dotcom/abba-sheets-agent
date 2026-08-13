"""B2.2 — chat arxivi (past vaznli kontekst, Claude'siz, 90-kun kesim) testlari.

pytest tests/test_chat.py  yoki  python3 tests/test_chat.py
"""
import os
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
