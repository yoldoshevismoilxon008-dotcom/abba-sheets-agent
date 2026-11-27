"""kb.purge_archived (/kb_tozala) — arxivdagi eski vault/chat versiyalarini butunlay o'chirish.

forget_old_versions faqat archived=1 qo'yadi: vault'da keyin yashirilgan telefon raqami eski
versiyada SQLite faylida qolardi (maxfiylik skani, 27.11.2026). Bu testlar o'chirishdan keyin
eski matn baza faylida (va WAL'da) baytlar darajasida ham qolmasligini, faol hujjatlar va
Telegram'dan yuklanganlar tegilmasligini tekshiradi. Raqamlar soxta (0 lar bilan).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb                # noqa: E402
import vault_sync as vs  # noqa: E402

ESKI = "EskiVersiyaQZX"       # faqat eski (arxivlanadigan) versiyada uchraydi
TG = "TelegramEslatmaQZX"     # /unut bilan arxivlangan Telegram hujjatida


@pytest.fixture()
def baza(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "DATA", tmp_path)
    monkeypatch.setattr(kb, "DB_PATH", tmp_path / "knowledge.db")
    monkeypatch.setattr(kb, "_ask_claude",
                        lambda p, effort="low": '{"title":"T","lang":"uz","tags":["x"],"summary":"s"}')
    # macOS SQLite'da secure_delete sukut bo'yicha 2 (o'chgan baytni o'zi tozalaydi), Railway'dagi
    # Debian'da odatda 0. Sinov aldamasin: sukut 0 — himoya faqat purge'ning o'zidan kelsin.
    asl_connect = kb._connect

    def _connect_sukut_ochiq():
        c = asl_connect()
        c.execute("PRAGMA secure_delete=OFF")
        return c

    monkeypatch.setattr(kb, "_connect", _connect_sukut_ochiq)
    kb.init_db()
    eski = kb.ingest_text(f"# Hisobot\n\n{ESKI}: Ali +998 90 000 00 00 ga qo'ng'iroq qilsin.",
                          source="vault", origin="abba-sheets-agent/hisobotlar/2026-10-10.md",
                          content_key=True)
    yangi = kb.ingest_text("# Hisobot\n\nYangiVersiya: Ali [telefon] ga qo'ng'iroq qilsin.",
                           source="vault", origin="abba-sheets-agent/hisobotlar/2026-10-10.md",
                           content_key=True)
    assert kb.forget_old_versions("vault", "abba-sheets-agent/hisobotlar/2026-10-10.md",
                                  yangi["uid"]) == 1
    tg = kb.ingest_text(f"{TG} — eslab qol", source="telegram", origin="eslatma: x", content_key=True)
    assert kb.archive(tg["uid"])["status"] == "ok"
    return {"eski": eski, "yangi": yangi, "tg": tg}


def _baytlar():
    p = kb.DB_PATH
    wal = p.with_name(p.name + "-wal")
    return (p.read_bytes() + (wal.read_bytes() if wal.exists() else b"")).lower()


def _soni(uid):
    conn = kb._connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM docs WHERE uid=?", (uid,)).fetchone()[0]
    finally:
        conn.close()


def test_sinov_rejimi_hech_narsa_ochirmaydi(baza):
    r = kb.purge_archived(dry_run=True)
    assert (r["docs"], r["telefonli"], r["by_source"]) == (1, 1, {"vault": 1})
    assert r["chunks"] >= 1 and r["bytes_keyin"] is None
    assert _soni(baza["eski"]["uid"]) == 1
    assert ESKI.lower().encode() in _baytlar()


def test_eski_matn_baza_faylidan_butunlay_ketadi(baza):
    assert ESKI.lower().encode() in _baytlar()            # oldin: arxivda bo'lsa ham faylda turibdi
    r = kb.purge_archived(dry_run=False)
    assert (r["docs"], r["telefonli"]) == (1, 1)
    assert _soni(baza["eski"]["uid"]) == 0
    b = _baytlar()
    assert ESKI.lower().encode() not in b                 # matn ham, FTS termi ham
    assert b"000 00 00" not in b
    # Telegram hujjati (/unut — «qaytarish mumkin») va faol hujjat tegilmaydi
    assert _soni(baza["tg"]["uid"]) == 1 and TG.lower().encode() in b
    topildi = kb.search("YangiVersiya", use_rerank=False, use_expansion=False)
    assert [x["origin"] for x in topildi] == ["abba-sheets-agent/hisobotlar/2026-10-10.md"]
    assert kb.search(ESKI, use_rerank=False, use_expansion=False) == []
    assert kb.purge_archived(dry_run=False)["docs"] == 0  # takror — o'chiradigan narsa yo'q


def test_faol_hujjatdagi_telefon_korsatiladi(baza):
    kb.ingest_text("Namuna: (90)000-00-00", source="vault", origin="bilim/namuna.md", content_key=True)
    r = kb.purge_archived(dry_run=True)
    assert r["faol_telefonli"] == ["bilim/namuna.md"]     # faqat origin — raqam emas


def test_origin_filtri(baza):
    assert kb.purge_archived(origins=["boshqa/fayl.md"], dry_run=False)["docs"] == 0
    assert kb.purge_archived(origins=[], dry_run=False)["docs"] == 0
    assert _soni(baza["eski"]["uid"]) == 1
    r = kb.purge_archived(origins=["abba-sheets-agent/hisobotlar/2026-10-10.md"], dry_run=False)
    assert r["docs"] == 1 and _soni(baza["eski"]["uid"]) == 0


def test_sinxron_ishlayotganda_tozalanmaydi(baza):
    assert vs._LOCK.acquire(blocking=False)
    try:
        assert vs.purge_archived(dry_run=False) == {"status": "busy"}
    finally:
        vs._LOCK.release()
    assert _soni(baza["eski"]["uid"]) == 1
    r = vs.purge_archived(dry_run=False)
    assert r["status"] == "ok" and r["docs"] == 1
