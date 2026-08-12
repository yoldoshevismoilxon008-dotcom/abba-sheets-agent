"""Bot chiqishlari — fayl yo'li / origin / vault_path / title HAR DOIM <code> ichida
(Telegram .md/.io/.co ni domen deb avtolink qilmasin) va qo'sh-escape (&amp;amp;) bo'lmasin.

handle_update dispatch'ini haqiqiy chaqirib, send_retry/edit_status chiqishini ushlaydi.
pytest tests/test_bot_output.py  yoki  python3 tests/test_bot_output.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot_listener as bl   # noqa: E402
import kb                    # noqa: E402
import vault_sync as vs      # noqa: E402
import design                # noqa: E402
import send as sendmod       # noqa: E402

# Monkeypatch qilinadigan funksiyalarning ASLI — har testdan keyin tiklanadi
# (aks holda global override boshqa test fayllariga oqadi — izolatsiya buziladi).
_KB_ORIG = {n: getattr(kb, n)
            for n in ("stats", "list_docs", "search", "archive", "ingest_text", "ingest_file")}
_VS_ORIG = {n: getattr(vs, n) for n in ("run", "stat")}
_SEND_TG = sendmod.tg_send

# Telegram HTML parse_mode ruxsat etadigan teglar (boshqa <...> → «Unsupported start tag»)
_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
                 "code", "pre", "a", "blockquote", "span", "tg-spoiler", "tg-emoji"}


def _bad_tags(html):
    """is_html matndagi RUXSATSIZ `<...>` ro'yxati (Telegram teg deb rad etadi).
    Satr MAZMUNINI emas — parser qoidasini tekshiradi: «/bilim <so'rov>» → tag nomi
    'so' → ruxsatsiz. Escape qilingan &lt; &gt; (haqiqiy < > emas) hisobga olinmaydi."""
    bad = []
    for m in re.finditer(r"<([^>]*)>", html):
        inner = m.group(1).strip()
        raw = inner[1:].strip() if inner.startswith("/") else inner
        nm = re.match(r"[a-zA-Z][a-zA-Z0-9-]*", raw)
        if (nm.group(0).lower() if nm else "") not in _ALLOWED_TAGS:
            bad.append(m.group(0))
    return bad


def _restore():
    for n, f in _KB_ORIG.items():
        setattr(kb, n, f)
    for n, f in _VS_ORIG.items():
        setattr(vs, n, f)
    sendmod.tg_send = _SEND_TG


class Cap:
    def __init__(self):
        self.sent = []

    def send_retry(self, text, attempts=4, is_html=False):
        self.sent.append({"text": text, "is_html": is_html})
        return True

    def edit_status(self, mid, text, html=False):
        self.sent.append({"text": text, "is_html": html})
        return True


def _run(text):
    cap = Cap()
    bl.TOKEN, bl.CHAT_ID = "x", "1"
    bl.send_retry = cap.send_retry
    bl.edit_status = cap.edit_status
    bl.send_status = lambda t: 1
    design.load_pending = lambda: None
    try:
        bl.handle_update({"message": {"chat": {"id": 1}, "text": text}})
    finally:
        _restore()      # kb.*/vs.* asllarini tikla — keyingi test fayliga oqmasin
    return cap.sent


def _assert_safe(entry):
    """is_html=True; qo'sh-escape yo'q; RUXSATSIZ teg yo'q; HAR «...md» yo'li <code> ichida."""
    t = entry["text"]
    assert entry["is_html"] is True, f"is_html emas: {t[:100]!r}"
    assert "&amp;amp;" not in t, f"qo'sh-escape: {t[:150]!r}"
    bad = _bad_tags(t)
    assert not bad, f"ruxsatsiz HTML teg (Telegram rad etadi): {bad} — {t!r}"
    for m in re.finditer(r"[^\s<>]+\.md\b", t):
        i = t.rfind("<code>", 0, m.start())
        j = t.find("</code>", m.start())
        assert i != -1 and j != -1 and i < m.start() < j, \
            f"«{m.group(0)}» <code> TASHQARISIDA: {t!r}"


def test_bilim_stat_origin_in_code():
    kb.stats = lambda: {
        "docs": 48, "docs_archived": 0, "chunks": 202, "bytes_db": 1 << 20,
        "by_source": {"vault": 48},
        "last_ingest": {"origin": "uchrashuv-bot/natija.md", "status": "new", "ts": "2026-08-10"},
    }
    e = _run("/bilim_stat")[-1]
    assert "<code>uchrashuv-bot/natija.md</code>" in e["text"]
    _assert_safe(e)


def test_bilim_list_title_in_code():
    kb.list_docs = lambda limit=20, tag=None: [
        {"id": 1, "title": "natija.md", "tags": ["x"], "created_at": "2026-08-10"},
    ]
    e = _run("/bilim")[-1]
    assert "<code>natija.md</code>" in e["text"]
    _assert_safe(e)


def test_bilim_search_title_in_code():
    kb.search = lambda q, k=5, use_rerank=True: [
        {"title": "qoidalar.md", "heading": "", "text": "matn bo'lagi"},
    ]
    e = _run("/bilim qoida")[-1]
    assert "<code>qoidalar.md</code>" in e["text"]
    _assert_safe(e)


def test_unut_title_in_code():
    kb.archive = lambda a: {"status": "ok", "title": "eslatma.md", "id": 3}
    e = _run("/unut 3")[-1]
    assert "<code>eslatma.md</code>" in e["text"]
    _assert_safe(e)


def test_eslab_qol_title_in_code():
    kb.ingest_text = lambda *a, **k: {
        "status": "new", "title": "katalog.md", "n_chunks": 2, "tags": ["a"], "warn": "",
    }
    e = _run("/eslab_qol bu yetarlicha uzun matn")[-1]
    assert "<code>katalog.md</code>" in e["text"]
    _assert_safe(e)


def test_vault_stat_paths_in_code():
    vs.stat = lambda: {
        "vault_docs": 48, "chunks": 202, "last_success_ts": "2026-08-10T15:24:24",
        "counts": {"ingested": 0, "unchanged": 48, "archived": 0, "errors": 0},
        "skipped_dirs": ["ilovalar", "odam"],
        "last_error": "fetch bilim/x.md yiqildi",
    }
    e = _run("/vault_stat")[-1]
    assert "<code>ilovalar</code>" in e["text"] and "<code>odam</code>" in e["text"]
    _assert_safe(e)


def test_title_with_special_chars_single_escape():
    kb.archive = lambda a: {"status": "ok", "title": "a & b <x>.md", "id": 9}
    e = _run("/unut a")[-1]
    assert "<code>a &amp; b &lt;x&gt;.md</code>" in e["text"]
    assert "&amp;amp;" not in e["text"]
    _assert_safe(e)


def test_supervisor_notify_path_in_code():
    import os
    import tempfile
    import send as sendmod
    import supervisor

    supervisor.DATA = Path(tempfile.mkdtemp(prefix="supntest_"))
    os.environ["TELEGRAM_BOT_TOKEN"] = "x"
    os.environ["TELEGRAM_CHAT_ID"] = "1"
    captured = []
    sendmod.tg_send = lambda token, chat, msg: captured.append(msg)
    vs.run = lambda: {"status": "git_error", "error": "fetch bilim/PM-KPI-qoidalari.md yiqildi"}
    try:
        supervisor.run_vault_sync()
    finally:
        _restore()      # tg_send / vs.run asllarini tikla
    assert captured, "notify yuborilmadi"
    msg = captured[0]
    assert "<code>" in msg and "&amp;amp;" not in msg
    assert ".md" not in msg.split("<code>")[0]    # .md faqat <code> ichida


def test_bilim_list_help_line_no_bad_tags():
    """BLOCKER regressiya: /bilim ro'yxati yordam qatori «<so'rov>/<id>» — is_html'da
    escape bo'lishi SHART (aks holda Telegram butun xabarni rad etadi)."""
    kb.list_docs = lambda limit=20, tag=None: [
        {"id": 1, "title": "a", "tags": [], "created_at": "2026-08-10"}]
    e = _run("/bilim")[-1]
    assert e["is_html"] is True
    assert _bad_tags(e["text"]) == [], f"ruxsatsiz teg: {_bad_tags(e['text'])}"
    assert "&lt;so'rov&gt;" in e["text"] and "<so'rov>" not in e["text"]


def test_kb_document_upload_title_in_code():
    """Hujjat yuklash tasdiqi (handle_kb_document) — title <code>, ruxsatsiz teg yo'q."""
    kb.ingest_file = lambda *a, **k: {"status": "new", "title": "hisobot.md",
                                      "n_chunks": 3, "tags": ["a"], "warn": "", "summary": "xul"}
    cap = Cap()
    bl.send_status = lambda t: 1
    bl.edit_status = cap.edit_status
    try:
        bl.handle_kb_document("/tmp/x.pdf", "x.pdf", "")
    finally:
        _restore()
    e = cap.sent[-1]
    assert "<code>hisobot.md</code>" in e["text"]
    _assert_safe(e)


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
