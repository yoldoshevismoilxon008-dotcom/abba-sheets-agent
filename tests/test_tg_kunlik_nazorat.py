"""AUDIT.md P0-2 — Mac'dagi TG kunlik monitoring zanjiri 6 kun ishlamagan, signal yo'q.

09-23, 10-01, 10-04..10-07 kunlari PDF ham, heartbeat ham yo'q edi; 🩺 «PDF ✓» esa faqat
Railway Chrome'ini tekshirgani uchun yashil turgan. Bu testlar arxivdagi HAQIQIY PDF
kunlarida Railway nazoratchisi (tg_kunlik.py) to'g'ri belgi va xabar berishini tekshiradi.

Ikki rejimda: `pytest tests/test_tg_kunlik_nazorat.py` YOKI `python3 tests/test_tg_kunlik_nazorat.py`.
Tarmoq/credentials kerak emas.
"""

import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze as an        # noqa: E402
import health               # noqa: E402
import tg_kunlik as tk      # noqa: E402

# abba-hisobotlar/tg-kunlik dagi haqiqiy PDF kunlari (09.10 holati)
ARXIV = {f"2026-09-{d:02d}" for d in list(range(10, 23)) + list(range(24, 31))} | \
        {"2026-10-02", "2026-10-03", "2026-10-08"}
HB = {"kunlar": [{"sana": "2026-10-08", "holat": "ok", "tugadi": "2026-10-08T08:52:44+05:00"}]}


def _h(day, pdf=ARXIV, hb=HB):
    d = date.fromisoformat(day)
    return d, tk.holat(d, {p for p in pdf if p <= day}, hb)


# ------------------------------------------------------- holat + 🩺 belgisi

def test_0510_ikki_kun_yoq_xato():
    d, h = _h("2026-10-05")
    assert tk.health_part(d, h) == ("✗", "oxirgi 03.10 — 2 kun oldin · 7 kunda 2 kun yo'q (01.10, 04.10)")


def test_0910_kecha_bor_bugun_kutilmoqda_boshliq_korinadi():
    d, h = _h("2026-10-09")
    assert tk.health_part(d, h) == ("⏳", "bugungisi hali yo'q, kecha ✓ · 7 kunda 4 kun yo'q "
                                          "(04.10, 05.10, 06.10, 07.10)")


def test_0810_bugun_kelgan_vaqt_bilan():
    d, h = _h("2026-10-08")
    sign, note = tk.health_part(d, h)
    assert sign == "✓" and note.startswith("bugun 08:52 · 7 kunda 5 kun yo'q (01.10, 04.10, 05.10, 06.10 …)"), note


def test_3009_pdf_kech_keladi_xato_emas():
    # 30.09 da PDF 09:49 da keldi — 09:00 dagi hisobotda bu ✗ emas, ⏳
    d, h = _h("2026-09-30", pdf=ARXIV - {"2026-09-30"})
    assert tk.health_part(d, h) == ("⏳", "bugungisi hali yo'q, kecha ✓ · 7 kunda 1 kun yo'q (23.09)")


def test_bugungi_zanjir_xato_holati():
    hb = {"kunlar": [{"sana": "2026-10-08", "holat": "xato", "tugadi": "2026-10-08T09:10:00+05:00"}]}
    d, h = _h("2026-10-08", hb=hb)
    assert tk.health_part(d, h)[0] == "✗"
    assert "«xato»" in tk.alert_text(d, h)


def test_zanjir_boshlanmagan():
    d = date(2026, 9, 1)
    h = tk.holat(d, set(), {})
    assert tk.health_part(d, h)[0] == "✓" and tk.alert_text(d, h) is None


# ------------------------------------------------------- 12:00 xabari

def test_0410_tushda_xabar():
    d, h = _h("2026-10-04")
    msg = tk.alert_text(d, h)
    assert msg.startswith("⚠️ TG kunlik monitoring: bugungi (04.10) PDF soat 12:00 gacha kelmadi. "
                          "Oxirgi PDF: 03.10 (1 kun oldin). Oxirgi 7 kunda yo'q: 01.10."), msg
    assert "Mac'ni tekshiring" in msg


def test_0810_bugun_bor_xabar_yoq():
    d, h = _h("2026-10-08")
    assert tk.alert_text(d, h) is None


# ------------------------------------------------------- GitHub API o'qish (tarmoqsiz)

def test_yukla_faqat_pdf_kunlarini_oladi():
    asl = tk._get
    calls = []

    def fake(repo, token, path, raw=False):
        calls.append(path)
        if path == "tg-kunlik":
            return [{"name": "2026-10-08.pdf", "type": "file"}, {"name": "heartbeat.json", "type": "file"},
                    {"name": "state", "type": "dir"}, {"name": "eski.pdf", "type": "file"}]
        return '{"kunlar": [{"sana": "2026-10-08", "holat": "ok"}]}'
    tk._get = fake
    try:
        pdf, hb = tk.yukla("o/r", "t")
    finally:
        tk._get = asl
    assert pdf == {"2026-10-08"} and hb["kunlar"][0]["sana"] == "2026-10-08"
    assert calls == ["tg-kunlik", "tg-kunlik/heartbeat.json"]


def test_tekshir_sozlanmagan_va_xato():
    asl_env = {k: os.environ.pop(k, None) for k in ("REPORTS_REPO", "GH_TOKEN_REPORTS")}
    try:
        assert tk.tekshir(date(2026, 10, 8)) == (None, None)
        os.environ.update(REPORTS_REPO="o/r", GH_TOKEN_REPORTS="t")
        asl = tk.yukla
        tk.yukla = lambda: (_ for _ in ()).throw(RuntimeError("401 Unauthorized"))
        try:
            h, err = tk.tekshir(date(2026, 10, 8))
        finally:
            tk.yukla = asl
        assert h is None and "401" in err
    finally:
        for k in ("REPORTS_REPO", "GH_TOKEN_REPORTS"):
            os.environ.pop(k, None)
            if asl_env[k] is not None:
                os.environ[k] = asl_env[k]


# ------------------------------------------------------- 🩺 qatori

def _line_with(tekshir_res, now=datetime(2026, 10, 5, 9, 0)):
    asl = tk.tekshir
    tk.tekshir = lambda today=None: tekshir_res
    try:
        return health.health_line(now)
    finally:
        tk.tekshir = asl


def test_health_qatori_tg_kunlik_xato():
    _d, h = _h("2026-10-05")
    line = _line_with((h, None))
    assert "TG-kunlik ✗ (oxirgi 03.10 — 2 kun oldin" in line, line
    assert "PDF-render" in line and " PDF ✓" not in line          # eski chalg'ituvchi yorliq yo'q


def test_health_qatori_sozlanmagan_bolsa_tg_kunlik_yoq():
    assert "TG-kunlik" not in _line_with((None, None))


def test_health_qatori_tekshirib_bolmadi():
    assert "TG-kunlik ? (tekshirib bo'lmadi: 401" in _line_with((None, "401 Unauthorized"))


# ------------------------------------------------------- supervisor 12:00 job

def test_supervisor_tushda_egaga_bir_marta():
    import supervisor
    sent = []
    _d, h = _h("2026-10-04")
    asl_n, asl_t = supervisor._notify_owner_once_daily, tk.tekshir
    supervisor._notify_owner_once_daily = lambda msg, key="": sent.append((key, msg))
    tk.tekshir = lambda today=None: (h, None)
    try:
        supervisor.run_tg_kunlik_watch(today=date(2026, 10, 4))
        _d8, h8 = _h("2026-10-08")
        tk.tekshir = lambda today=None: (h8, None)
        supervisor.run_tg_kunlik_watch(today=date(2026, 10, 8))     # bugun bor — xabar yo'q
    finally:
        supervisor._notify_owner_once_daily, tk.tekshir = asl_n, asl_t
    assert len(sent) == 1 and sent[0][0] == "tg_kunlik" and "04.10" in sent[0][1], sent


# ------------------------------------------------------- hisobotlar orasidagi tanaffus

def test_hisobot_tanaffusi_izohi():
    d = {"date": "2026-09-20", "prev_date": "2026-09-17", "sheets": {}}
    assert an.baseline_gap_note(d) == ["ℹ️ Solishtirish 17.09 holatiga nisbatan — oraliqda 2 kun snapshot yo'q "
                                       "(18.09, 19.09); o'zgarishlar shu davr uchun jamlangan."]
    assert an.baseline_gap_note({"date": "2026-09-21", "prev_date": "2026-09-20", "sheets": {}}) == []
    assert an.baseline_gap_note({"date": "2026-09-21", "prev_date": None, "baseline": True, "sheets": {}}) == []
    assert any("18.09, 19.09" in n for n in an.deterministic_notes(d))


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
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
