"""Audit P1 xavfsizlik (S2–S4) testlari.

  S2  egasining chat'ida ham YUBORUVCHI tekshiriladi (TELEGRAM_OWNER_IDS; shaxsiy chatda
      chat egasi avtomatik) — guruhning har bir a'zosi buyruq bera olmaydi;
  S3  maxfiy tab (exclude_tabs) o'qilgan javob bot xotirasi va chat arxiviga yozilmaydi,
      PDF diskda qolmaydi;
  S4  claude -p toollarsiz va bo'sh papkada ishlaydi; promptlarda ishonchsiz ma'lumot
      bloki oldidan himoya ko'rsatmasi bor.

pytest tests/test_p1_xavfsizlik.py  yoki  python3 tests/test_p1_xavfsizlik.py
Tarmoq/kredensial kerak emas.
"""
import contextlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import analyze             # noqa: E402
import bot_listener as bl  # noqa: E402
import diff as diffmod     # noqa: E402
import fetch as fm         # noqa: E402
import pm_push             # noqa: E402
import send as sendmod     # noqa: E402

MAXFIY_TAB = "Mijozlarning ma'lumot bazasi"


@contextlib.contextmanager
def _soxta(obj, name, val):
    orig = getattr(obj, name)
    setattr(obj, name, val)
    try:
        yield
    finally:
        setattr(obj, name, orig)


@contextlib.contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------------------------ S2

def _upd(chat, sender, text="/help", **extra):
    msg = {"chat": {"id": chat}, "text": text, **extra}
    if sender is not None:
        msg["from"] = {"id": sender}
    return {"update_id": 1, "message": msg}


@contextlib.contextmanager
def _bot(chat_id, owners=None):
    sent = []
    bl._RUXSATSIZ_OGOH.clear()

    def portlash(*_a, **_k):
        raise AssertionError("ruxsatsiz buyruq bajarildi")

    with _soxta(bl, "CHAT_ID", str(chat_id)), _env(TELEGRAM_OWNER_IDS=owners), \
            _soxta(bl, "send_retry", lambda t, **k: sent.append(t) or True), \
            _soxta(pm_push, "run_daily", portlash), _soxta(pm_push, "set_contact", portlash), \
            _soxta(bl, "handle_voice", portlash), _soxta(bl, "handle_media", portlash):
        yield sent


def test_s2_shaxsiy_chat_egasi_avtomatik():
    with _bot(555) as sent:
        assert bl.handle_update(_upd(555, 555)) == "help"
    assert sent and sent[0] == bl.HELP


def test_s2_guruhda_owner_ids_yoq_bolsa_hech_kim_buyruq_bermaydi():
    with _bot(-100123) as sent:
        assert bl.owner_ids() == set()
        assert bl.handle_update(_upd(-100123, 777, "/pm_push force")) == "unauthorized"
        assert bl.handle_update(_upd(-100123, 777, "/pm_set zubair @x")) == "unauthorized"
        assert bl.handle_update(_upd(-100123, 777, "", voice={"file_id": "v"})) == "unauthorized"
    assert len(sent) == 1 and "777" in sent[0] and "TELEGRAM_OWNER_IDS" in sent[0], sent   # kuniga 1 marta


def test_s2_guruhda_faqat_egalar():
    with _bot(-100123, owners="777, 888") as sent:
        assert bl.handle_update(_upd(-100123, 777)) == "help"
        assert bl.handle_update(_upd(-100123, 888)) == "help"
        assert bl.handle_update(_upd(-100123, 999, "/pm_push force")) == "unauthorized"
        assert bl.handle_update(_upd(-100123, None, "/pm_push force")) == "unauthorized"  # from yo'q
    assert sum("Ruxsat yo'q" in t for t in sent) == 1, sent


def test_s2_owner_ids_shaxsiy_chatda_ham_ustun():
    with _bot(555, owners="777"):
        assert bl.owner_ids() == {"777"}
        assert bl.handle_update(_upd(555, 555)) == "unauthorized"


# ------------------------------------------------------------------ S3

def test_s3_maxfiy_javob_arxivlanmaydi():
    yozildi = []
    import chat_log

    with _soxta(bl, "remember", lambda q, a, sel=None: yozildi.append(("mem", a))), \
            _soxta(chat_log, "append_qa", lambda q, a: yozildi.append(("chat", a))):
        bl.arxivla("parollar?", "login: admin / parol: 123", {"sheets": ["SMM"], "maxfiy": [MAXFIY_TAB]})
        bl.arxivla("KPI?", "Zubair 82%", {"sheets": ["Z"]})
    assert yozildi == [("mem", bl.MAXFIY_JAVOB), ("chat", bl.MAXFIY_JAVOB),
                       ("mem", "Zubair 82%"), ("chat", "Zubair 82%")], yozildi


def _smm_cfg():
    return [{"id": "SMM", "name": "SMM proektlar", "pm_kpi": False, "aliases": ["smm"],
             "exclude_tabs": [MAXFIY_TAB]}]


class _Sh:
    def worksheets(self):
        return [type("W", (), {"title": t})() for t in ("Smm main", MAXFIY_TAB)]


def _jonli_ranges(sh, ranges, name):
    return {r: {"values": [["Nomi", "Login", "Parol"], ["A", "a@x", "p1"]]} for r in ranges}


def test_s3_build_data_maxfiy_tabni_belgilaydi():
    """Snapshot yo'li (maxfiy tab jonli qo'shiladi) va to'liq jonli yo'l — ikkalasida ham."""
    q = "smm mijozlarning ma'lumot bazasi tabida A loyihasi bormi"
    snap = {"id": "SMM", "name": "SMM proektlar", "tabs": ["Smm main", MAXFIY_TAB],
            "excluded_tabs": [MAXFIY_TAB], "fetched_at": "2026-10-10T09:00",
            "watch_ranges": [fm.tab_range("Smm main")],
            "ranges": {fm.tab_range("Smm main"): {"values": [["Nomi"], ["A"]]}}}
    bl._tabs_cache.clear()
    with _soxta(fm, "load_config", lambda include_qa_only=False: _smm_cfg()), \
            _soxta(bl, "latest_day", lambda: "2026-10-10"), \
            _soxta(diffmod, "load_day", lambda d: ({"SMM": snap}, {})), \
            _soxta(bl, "tgc", lambda: type("G", (), {"open_by_key": lambda self, k: _Sh()})()), \
            _soxta(fm, "fetch_ranges", _jonli_ranges):
        for fresh in (True, False):
            with _soxta(bl, "snapshot_fresh", lambda d, f=fresh: f):
                _txt, sel, _src = bl.build_data(q)
            assert sel.get("maxfiy") == [MAXFIY_TAB], (fresh, sel)
        _txt, sel, _src = bl.build_data("smm main tabida nechta loyiha")
        assert not sel.get("maxfiy"), sel


def test_s3_maxfiy_pdf_diskda_qolmaydi():
    import render_pdf

    with tempfile.TemporaryDirectory() as d, _soxta(bl, "QA_PDF_DIR", Path(d)), \
            _soxta(render_pdf, "render_qa", lambda qa, pdf, **k: Path(pdf).write_bytes(b"%PDF")), \
            _soxta(sendmod, "tg_send_document", lambda *a, **k: None), \
            _soxta(bl, "delete_status", lambda mid: None):
        bl.send_qa_pdf({"title": "x"}, "q", None, saqlama=False)
        assert not list(Path(d).glob("*.pdf"))
        bl.send_qa_pdf({"title": "x"}, "q", None)
        assert len(list(Path(d).glob("*.pdf"))) == 1


# ------------------------------------------------------------------ S4

def _claude_chaqiruvi(**kw):
    seen = {}

    def run(cmd, **k):
        cwd = k.get("cwd")
        seen.update(cmd=cmd, cwd=cwd, bosh=(cwd is not None and os.listdir(cwd) == []))
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    with _soxta(analyze, "find_claude", lambda: "claude"), _soxta(analyze.subprocess, "run", run):
        assert analyze.run_claude("prompt", **kw) == "ok"
    return seen


def test_s4_claude_toollarsiz_va_bosh_papkada():
    s = _claude_chaqiruvi()
    cmd = s["cmd"]
    taqiq = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert {"Read", "Glob", "Grep", "Bash", "WebFetch", "Write"} <= set(taqiq), taqiq
    assert "--allowedTools" not in cmd
    assert s["bosh"] and Path(s["cwd"]).resolve() != ROOT and not Path(s["cwd"]).exists(), s


def test_s4_vision_faqat_read():
    s = _claude_chaqiruvi(allowed_tools=["Read"])
    cmd = s["cmd"]
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    taqiq = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert "Read" not in taqiq and "Bash" in taqiq and "WebFetch" in taqiq, taqiq
    assert s["cwd"] is None


def test_s4_promptlarda_ishonchsiz_blok_himoyasi():
    for fayl, joy in (("qa.md", "{{DATA}}"), ("qa.md", "{{KNOWLEDGE}}"),
                      ("daily-report.md", "{{CONTEXT}}"), ("audit.md", "{{FINDINGS}}"),
                      ("kb-meta.md", "{{TEXT}}"), ("kb-rerank.md", "{{CANDIDATES}}")):
        txt = (ROOT / "prompts" / fayl).read_text(encoding="utf-8")
        oldi = txt[:txt.index(joy)].splitlines()[-4:]
        assert any("ISHONCHSIZ" in x and "BAJARMA" in x for x in oldi), (fayl, joy)


def _run_all():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for n, f in tests:
        try:
            f()
            passed += 1
            print(f"  ✓ {n}")
        except Exception as e:                   # noqa: BLE001
            failed += 1
            print(f"  ✗ {n} — {type(e).__name__}: {e}")
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
