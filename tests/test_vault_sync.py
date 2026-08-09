"""vault_sync.py testlari (B2.1).

Ikki rejim: pytest tests/test_vault_sync.py  yoki  python3 tests/test_vault_sync.py
Har test toza kb DB + temp "clone" katalog quradi; git ham, Claude ham chaqirilmaydi
(_ensure_clone va kb._ask_claude monkeypatch).
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb            # noqa: E402
import vault_sync as vs   # noqa: E402

_ORIG_INGEST = kb.ingest_file


def _fake_claude(prompt, effort="low"):
    return '{"title":"T","lang":"uz","tags":["v"],"summary":"s"}'


def setup(sentinel=False):
    """Toza kb DB + vault_sync temp yo'llari + git monkeypatch. clone katalogini qaytaradi."""
    d = Path(tempfile.mkdtemp(prefix="vstest_"))
    kb.DATA = d
    kb.DB_PATH = d / "knowledge.db"
    kb._ask_claude = _fake_claude
    kb.ingest_file = _ORIG_INGEST
    kb.init_db()
    vs.DATA = d
    vs.CLONE = d / "vault"
    vs.STATE = d / "vault_sync_state.json"
    clone = d / "vault"
    clone.mkdir(parents=True, exist_ok=True)
    vs._ensure_clone = lambda repo, token: clone
    os.environ["VAULT_REPO"] = "x/y"
    os.environ["GH_TOKEN_VAULT"] = "tok"
    return clone


def write(clone, rel, text):
    p = clone / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def kbignore(clone, *lines):
    (clone / ".kbignore").write_text(("\n".join(lines) + "\n") if lines else "\n",
                                     encoding="utf-8")


# ---------------------------------------------------------------- spec kesimlari

def test_unchanged_not_reingested():
    """(1) O'zgarmagan fayl ikkinchi sinxronda qayta ingest QILINMAYDI."""
    clone = setup()
    kbignore(clone)
    write(clone, "bilim/a.md", "# A\n\n" + "Batafsil undiruv matni. " * 200)  # >1500
    r1 = vs.run()
    assert r1["status"] == "ok"
    assert r1["counts"]["ingested"] == 1 and r1["counts"]["unchanged"] == 0
    r2 = vs.run()
    assert r2["counts"]["ingested"] == 0 and r2["counts"]["unchanged"] == 1


def test_kbignore_skips_folder():
    """(2) .kbignore papkasi kb'ga tushmaydi, skipped_dirs'ga tushadi."""
    clone = setup()
    kbignore(clone, "odam/")
    write(clone, "bilim/a.md", "# A\n\nMatn.")
    write(clone, "odam/profil.md", "# Profil\n\nMaxfiy shaxsiy ma'lumot.")
    r = vs.run()
    assert r["status"] == "ok"
    origins = kb.origins("vault")
    assert "bilim/a.md" in origins
    assert "odam/profil.md" not in origins
    assert "odam" in r["skipped_dirs"]


def test_deleted_file_archived():
    """(3) Vault'dan o'chirilgan fayl kb'da arxivlanadi."""
    clone = setup()
    kbignore(clone)
    write(clone, "kunlik/x.md", "# X\n\nMatn.")
    vs.run()
    assert "kunlik/x.md" in kb.origins("vault")
    (clone / "kunlik" / "x.md").unlink()
    r = vs.run()
    assert r["counts"]["archived"] == 1
    assert "kunlik/x.md" not in kb.origins("vault")


def test_git_failure_survives():
    """(4) git pull yiqilsa run() raise QILMAYDI — status qaytaradi (bot tirik)."""
    setup()

    def boom(repo, token):
        raise RuntimeError("network down")

    vs._ensure_clone = boom
    r = vs.run()
    assert r["status"] == "git_error"
    assert "network" in r["error"]


def test_first_ingest_resumable():
    """(5) Birinchi ingest o'rtada uzilsa, qayta yugurishda o'sha joydan davom etadi."""
    clone = setup()
    kbignore(clone)
    for i in range(5):
        write(clone, f"kunlik/f{i}.md", f"# F{i}\n\nMatn raqam {i}.")
    calls = {"n": 0}

    def flaky(path, **kw):
        calls["n"] += 1
        if calls["n"] == 3:                 # 3-faylda "uzilish"
            raise RuntimeError("uzildi")
        return _ORIG_INGEST(path, **kw)

    kb.ingest_file = flaky
    r1 = vs.run()
    assert r1["counts"]["errors"] == 1
    assert kb.stats()["docs"] == 4          # bittasi tushib qoldi
    kb.ingest_file = _ORIG_INGEST           # "qayta ishga tushdi"
    r2 = vs.run()
    assert r2["counts"]["errors"] == 0
    assert r2["counts"]["unchanged"] >= 4   # avval tushganlar qayta ingest bo'lmadi
    assert kb.stats()["docs"] == 5          # hammasi joyida


# ---------------------------------------------------------------- guard'lar / gate

def test_no_kbignore_blocks():
    """.kbignore repo'da yo'q → hech narsa ingest qilinmaydi (himoya)."""
    clone = setup()
    write(clone, "bilim/a.md", "# A\n\nMatn.")
    r = vs.run()
    assert r["status"] == "no_kbignore"
    assert kb.stats()["docs"] == 0


def test_unconfigured_blocks():
    """__UNCONFIGURED__ sentinel turgan ekan — sinxron o'chiq."""
    clone = setup()
    kbignore(clone, "__UNCONFIGURED__")
    write(clone, "bilim/a.md", "# A\n\nMatn.")
    r = vs.run()
    assert r["status"] == "unconfigured"
    assert kb.stats()["docs"] == 0


def test_disabled_without_env():
    """Env yo'q → disabled (Railway'da wiring bo'lmaganda xavfsiz no-op)."""
    setup()
    os.environ.pop("VAULT_REPO", None)
    os.environ.pop("GH_TOKEN_VAULT", None)
    assert vs.run()["status"] == "disabled"


def test_meta_gate_small_no_claude():
    """Narx-gate: <1500 belgi faylga Claude metadata chaqirilmaydi; katta faylga chaqiriladi."""
    clone = setup()
    kbignore(clone)
    calls = {"n": 0}

    def counting(prompt, effort="low"):
        calls["n"] += 1
        return '{"title":"T","lang":"uz","tags":[],"summary":"s"}'

    kb._ask_claude = counting
    write(clone, "bilim/small.md", "# Kichik\n\nQisqa eslatma.")            # <1500
    write(clone, "bilim/big.md", "# Katta\n\n" + "so'z bo'lagi matni " * 200)  # >1500
    vs.run()
    assert calls["n"] == 1


def test_kbignore_matcher():
    """.kbignore matcher: bare nom, anchored yo'l, glob, inkor."""
    pats = ["odam/", "kunlik/shaxsiy/", "*.private.md", "!kunlik/shaxsiy/keep.md"]
    assert vs._kbignore_match("odam/profil.md", pats)
    assert vs._kbignore_match("a/odam/x.md", pats)            # bare nom — har chuqurlikda
    assert vs._kbignore_match("kunlik/shaxsiy/note.md", pats)
    assert vs._kbignore_match("bilim/x.private.md", pats)
    assert not vs._kbignore_match("bilim/a.md", pats)
    assert not vs._kbignore_match("kunlik/2026-08-10.md", pats)
    assert not vs._kbignore_match("kunlik/shaxsiy/keep.md", pats)   # inkor bekor qildi
    assert vs._always_ignore(".obsidian/app.md")
    assert vs._always_ignore("bilim/.trash/old.md")
    assert not vs._always_ignore("bilim/a.md")


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
