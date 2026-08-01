"""kb.py testlari (B1).

Ikki rejimda ishlaydi:
  - pytest:            pytest tests/test_kb.py
  - pytestsiz (skript): python3 tests/test_kb.py

Har test o'z alohida (vaqtinchalik) DB'sini quradi va Claude'ni monkeypatch qiladi —
subprocess (claude -p) chaqirilmaydi.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb  # noqa: E402


# ---------------------------------------------------------------- yordamchilar

FAKE_META = (
    '{"title":"Test hujjat","lang":"uz","tags":["test","kb"],'
    '"summary":"Qisqa mazmun."}'
)


def fake_claude(prompt, effort="low"):
    """Metadata → JSON; query-expansion → fallback ishlasin (haqiqiy so'zlar);
    re-rank → indekslar."""
    p = prompt.lower()
    if "kalit so" in p:                       # query expansion
        raise RuntimeError("expansion -> fallback (haqiqiy so'zlar)")
    if "saralovchi" in p or "re-rank" in p:   # re-rank
        return "[0, 1, 2, 3, 4, 5, 6, 7]"
    return FAKE_META                          # metadata


def setup_kb(fake=fake_claude):
    """Har test uchun toza DB + Claude monkeypatch."""
    d = Path(tempfile.mkdtemp(prefix="kbtest_"))
    kb.DATA = d
    kb.DB_PATH = d / "knowledge.db"
    kb._ask_claude = fake
    kb.init_db()
    return d


# ---------------------------------------------------------------- testlar

def test_init_idempotent():
    setup_kb()
    kb.init_db()
    kb.init_db()                              # ikki marta — xatosiz
    conn = kb._connect()
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert ver == kb.SCHEMA_VERSION
    assert kb.stats()["docs"] == 0


def test_ingest_new_then_unchanged():
    setup_kb()
    doc = "# Undiruv\n\n" + ("Mijozdan qarz undiriladi. " * 20)
    r1 = kb.ingest_text(doc, source="telegram", origin="u.md")
    assert r1["status"] == "new" and r1["n_chunks"] >= 1
    r2 = kb.ingest_text(doc, source="telegram", origin="u.md")
    assert r2["status"] == "unchanged"
    assert r2["n_chunks"] == r1["n_chunks"]
    assert kb.stats()["docs"] == 1            # dublikat yaratilmadi


def test_updated_removes_old_chunks():
    setup_kb()
    kb.ingest_text("# Hujjat\n\n" + ("ESKIMATN birlamchi tarkib. " * 10),
                   source="telegram", origin="u.md")
    assert len(kb.search("ESKIMATN", use_rerank=False)) >= 1
    r = kb.ingest_text("# Hujjat\n\n" + ("YANGIMATN boshqa tarkib. " * 10),
                       source="telegram", origin="u.md")
    assert r["status"] == "updated"
    # eski chunk FTS'dan butunlay o'chgan bo'lishi kerak
    assert len(kb.search("ESKIMATN", use_rerank=False)) == 0
    assert len(kb.search("YANGIMATN", use_rerank=False)) >= 1
    assert kb.stats()["docs"] == 1


def test_fts_prefix_uzbek():
    setup_kb()
    kb.ingest_text("# Qoidalar\n\nUndiruv qoidalari va muddatlari haqida batafsil.",
                   source="telegram", origin="q.md")
    # o'zak (prefix) inflected shaklni topadi: 'qoida' -> 'qoidalari'
    assert len(kb.search("qoida", use_rerank=False)) >= 1
    assert len(kb.search("muddat", use_rerank=False)) >= 1
    assert len(kb.search("undiruv", use_rerank=False)) >= 1


def test_context_for_budget():
    setup_kb()
    big = "# Katta\n\n" + ("Undiruv qarz muddat to'lov hisobot. " * 500)
    kb.ingest_text(big, source="telegram", origin="big.md")
    ctx = kb.context_for("undiruv qarz", budget_chars=1000, use_rerank=False)
    assert 0 < len(ctx) <= 1000
    assert ctx.startswith("[BILIM BAZASI")


def test_ingest_survives_claude_failure():
    def boom(prompt, effort="low"):
        raise RuntimeError("claude yo'q")
    setup_kb(fake=boom)                        # HAR chaqiruv yiqiladi
    r = kb.ingest_text("# Fayl sarlavhasi\n\nBirlamchi matn UNIKALSOZ.",
                       source="telegram", origin="hujjat.md")
    assert r["status"] == "new"
    assert r["title"]                          # fallback title (fayl nomidan) bor
    # qidiruv ham fallback query-expansion bilan ishlaydi
    assert len(kb.search("UNIKALSOZ", use_rerank=False)) >= 1


def test_archive_hides_doc():
    setup_kb()
    r = kb.ingest_text("# Arxiv\n\nArxiv testi matni ARXIVSOZ.",
                       source="telegram", origin="a.md")
    assert len(kb.list_docs()) == 1
    assert kb.archive(r["uid"]) is True
    assert len(kb.list_docs()) == 0            # ro'yxatdan yashiriladi
    assert len(kb.search("ARXIVSOZ", use_rerank=False)) == 0   # archived=0 filtri


def test_chunking_splits_large():
    setup_kb()
    # >3000 belgi (paragraf chegaralari bilan) -> bir nechta chunk
    body = "\n\n".join(f"Paragraf {i}: undiruv qarz matni bo'lagi." for i in range(200))
    r = kb.ingest_text("# Katta bo'lim\n\n" + body, source="telegram", origin="k.md")
    assert r["n_chunks"] >= 2


def test_list_docs_tag_filter():
    setup_kb()
    kb.ingest_text("# Teg testi\n\nBazaviy matn.", source="telegram", origin="t.md",
                   tags=["undiruv", "maxsus"])
    assert len(kb.list_docs(tag="maxsus")) == 1
    assert len(kb.list_docs(tag="yoqteg")) == 0


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
