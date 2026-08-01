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
    res = kb.archive(r["uid"])
    assert res["status"] == "ok" and res["n"] == 1
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


# --- review fixlari testlari ---

def test_timeout_fallback():
    """BLOCKER 1: Claude timeout (yoki har xato) → ingest va qidiruv fallback bilan ishlaydi."""
    import subprocess

    def timeout(prompt, effort="low"):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=30)

    setup_kb(fake=timeout)
    r = kb.ingest_text("# Hujjat\n\nMatn TIMEOUTSOZ ichida bor.",
                       source="telegram", origin="t.md")
    assert r["status"] == "new"                 # meta timeout → fayl nomi fallback
    assert r["title"]
    assert len(kb.search("TIMEOUTSOZ", use_rerank=False)) >= 1   # expansion timeout → tokenizatsiya


def test_unut_never_mass_archives():
    """BLOCKER 2: /unut % yoki umumiy substring butun bazani arxivlamaydi."""
    setup_kb()
    for i in range(3):
        kb.ingest_text(f"# Hujjat {i}\n\nBazaviy matn raqam {i}.",
                       source="telegram", origin=f"d{i}.md")
    assert kb.stats()["docs"] == 3
    # '%' — LIKE wildcard sifatida ishlamasin (escaped)
    res = kb.archive("%")
    assert res["status"] == "not_found"
    assert kb.stats()["docs"] == 3              # HECH BIRI arxivlanmadi
    # umumiy title substring (barchasi "Hujjat") → ambiguous, arxivlamaydi
    res = kb.archive("Hujjat")
    assert res["status"] == "ambiguous" and len(res["candidates"]) == 3
    assert kb.stats()["docs"] == 3              # baribir arxivlanmadi
    # aynan id bilan → faqat bittasi
    res = kb.archive(str(res["candidates"][0]["id"]))
    assert res["status"] == "ok"
    assert kb.stats()["docs"] == 2


def test_uid_collision_no_data_loss():
    """FIX 3: bir xil nomli ('report.md') ikki boshqa fayl birini o'chirmasin."""
    setup_kb()
    d = Path(tempfile.mkdtemp(prefix="kbcol_"))
    f = d / "report.md"
    f.write_text("# Hisobot A\n\nBirinchi hujjat CONTENTALPHA ichida.", encoding="utf-8")
    kb.ingest_file(f, source="telegram", origin="report.md")
    f.write_text("# Hisobot B\n\nIkkinchi butunlay boshqa CONTENTBETA hujjat.", encoding="utf-8")
    kb.ingest_file(f, source="telegram", origin="report.md")     # AYNAN bir xil origin
    assert kb.stats()["docs"] == 2                                # ikkalasi saqlandi
    assert len(kb.search("CONTENTALPHA", use_rerank=False)) >= 1  # birinchi O'CHMADI
    assert len(kb.search("CONTENTBETA", use_rerank=False)) >= 1
    # bir xil faylni qayta → unchanged (idempotent)
    f.write_text("# Hisobot B\n\nIkkinchi butunlay boshqa CONTENTBETA hujjat.", encoding="utf-8")
    assert kb.ingest_file(f, source="telegram", origin="report.md")["status"] == "unchanged"


def test_apostrophe_cross_match():
    """FIX 4: 'toʻlov' (U+02BB) va 'to'lov' (ASCII ') o'zaro mos kelsin."""
    setup_kb()
    kb.ingest_text("# Toʻlov tartibi\n\nMijoz toʻlovni oʻz vaqtida amalga oshirdi.",
                   source="telegram", origin="p.md")
    assert len(kb.search("to'lov", use_rerank=False)) >= 1        # ASCII ' → topadi
    assert len(kb.search("toʻlov", use_rerank=False)) >= 1        # U+02BB → topadi
    # teskari: ASCII bilan saqlab, U+02BB bilan qidirish
    kb.ingest_text("# Koʻrsatkich\n\nKPI koʻrsatkichlari hisoblanadi ANIQSOZ.",
                   source="telegram", origin="k.md")
    assert len(kb.search("ko'rsatkich", use_rerank=False)) >= 1


def test_rerank_dedupe():
    """FIX 6: Claude [0,0,0,1] qaytarsa natijada takroriy chunk bo'lmasin."""
    def fake(prompt, effort="low"):
        p = prompt.lower()
        if "kalit so" in p:
            raise RuntimeError("expansion->fallback")
        if "saralovchi" in p:
            return "[0, 0, 0, 1]"               # ataylab takrorli
        return FAKE_META

    setup_kb(fake=fake)
    # bir necha bo'lak "undiruv" so'zi bilan (rerank ishga tushishi uchun cands>k)
    doc = "\n\n".join(
        f"## Bo'lim {i}\n\nUndiruv qarz muddat to'lov haqida batafsil matn bo'lagi {i}."
        for i in range(6)
    )
    kb.ingest_text("# Katta\n\n" + doc, source="telegram", origin="r.md")
    res = kb.search("undiruv", k=2, use_rerank=True)
    ids = [r["chunk_id"] for r in res]
    assert len(ids) == len(set(ids))            # takror yo'q


def test_use_expansion_false_skips_claude():
    """FIX 7: fast rejim (use_expansion=False) Claude query-expansion'ni chaqirmasin."""
    setup_kb()
    kb.ingest_text("# Hujjat\n\nUndiruv qarz muddat matni bor.",
                   source="telegram", origin="u.md")
    seen = {"n": 0}
    orig = kb._expand_query
    kb._expand_query = lambda q: (seen.__setitem__("n", seen["n"] + 1), orig(q))[1]
    try:
        kb.search("undiruv", k=3, use_rerank=False, use_expansion=False)
        assert seen["n"] == 0                    # expansion CHAQIRILMADI
        kb.search("undiruv", k=3, use_rerank=False, use_expansion=True)
        assert seen["n"] == 1                    # endi chaqirildi
    finally:
        kb._expand_query = orig


def test_chunk_ceiling_and_warn():
    """FIX 5: MAX_CHUNKS'dan oshsa kesiladi va ogohlantirish qaytadi."""
    setup_kb()
    body = "\n\n".join(
        f"## Bo'lim {i}\n\n" + ("undiruv qarz matni bo'lagi. " * 8)   # ~230 belgi → alohida chunk
        for i in range(kb.MAX_CHUNKS + 100)
    )
    r = kb.ingest_text("# Katta hujjat\n\n" + body, source="telegram", origin="big.md")
    assert r["n_chunks"] == kb.MAX_CHUNKS
    assert "bo'lak" in (r.get("warn") or "")


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
