"""Audit P0 — maxfiy ma'lumot oshkor bo'lmasin.

  P0-1  bot tokeni Telegram chatga va loglarga chiqmaydi:
        requests tarmoq xatosi matnida «/bot<TOKEN>/method» bor edi — u chatga
        (send_retry «⚠️ ... {str(e)}») va data/logs + Railway log oqimiga tushardi;
  P0-2  public repo'da biznes ma'lumoti yo'q: Sheet ID'lar/dashboard_id → config.local.yaml
        yoki CONFIG_LOCAL_B64; ega qarorlari → DATA_DIR (UNDIRUV_QAROR_B64); bot suhbat
        xotirasi git'dan olib tashlandi.

pytest tests/test_maxfiy.py  yoki  python3 tests/test_maxfiy.py
Tarmoq/kredensial kerak emas (requests soxtalashtiriladi).
"""
import base64
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests            # noqa: E402

import bot_listener as bl  # noqa: E402
import design              # noqa: E402
import fetch as fm         # noqa: E402
import maxfiy              # noqa: E402
import pm_push as pp       # noqa: E402
import send as sendmod     # noqa: E402
import supervisor as sv    # noqa: E402
import undiruv as u        # noqa: E402

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _tarmoq_xatosi(*_a, **_k):
    """requests'ning real xato matni shakli: URL — ya'ni bot tokeni — ichida."""
    raise requests.ConnectionError(
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with "
        f"url: /bot{TOKEN}/sendDocument (Caused by NameResolutionError('failed'))")


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


# ------------------------------------------------------------------ P0-1: redact

def test_redact_token_va_github():
    s = maxfiy.redact(f"url: /bot{TOKEN}/getUpdates; push https://x-access-token:{GH}@github.com/a/b; {GH}")
    assert TOKEN not in s and GH not in s and "/bot***/getUpdates" in s, s
    assert maxfiy.redact("Zubair 41,2 ball, $1 500") == "Zubair 41,2 ball, $1 500"   # oddiy matn buzilmaydi


def test_redact_env_qiymati():
    with _env(GH_TOKEN_VAULT="vault-secret-value-xyz", TELEGRAM_BOT_TOKEN=None):
        assert maxfiy.redact("token=vault-secret-value-xyz") == "token=***"


def test_xato_xabar_faqat_turi():
    e = requests.ConnectionError(f"url: /bot{TOKEN}/sendDocument")
    m = maxfiy.xato_xabar("⚠️ Tahlil bo'lmadi", e)
    assert TOKEN not in m and "ConnectionError" in m, m


# ------------------------------------------------------------------ P0-1: manbada

def _tekshir_xato(fn):
    try:
        fn()
    except requests.RequestException as e:              # chaqiruvchilar shu turni ushlaydi
        assert isinstance(e, requests.ConnectionError), type(e)
        assert TOKEN not in str(e) and "bot***" in str(e), str(e)
        assert e.__suppress_context__, "asl xato (URL bilan) traceback'ga chiqmasin"
        return
    raise AssertionError("xato ko'tarilmadi")


def test_send_tg_call_va_document_tokensiz_xato():
    with _soxta(requests, "post", _tarmoq_xatosi):
        _tekshir_xato(lambda: sendmod.tg_call(TOKEN, "sendMessage", {"chat_id": 1, "text": "x"}))
        _tekshir_xato(lambda: sendmod.tg_send(TOKEN, 1, "salom"))
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            _tekshir_xato(lambda: sendmod.tg_send_document(TOKEN, 1, f.name, "caption"))


def test_bot_api_tokensiz_xato():
    with _soxta(bl, "TOKEN", TOKEN), _soxta(requests, "post", _tarmoq_xatosi):
        _tekshir_xato(lambda: bl.api("getUpdates", {"offset": 1}))


def test_design_download_tokensiz_xato():
    with _soxta(requests, "get", _tarmoq_xatosi):
        _tekshir_xato(lambda: design.download(TOKEN, "file-id", "logo.png"))


def test_chatga_ketadigan_matn_redakt_qilinadi():
    sent = []

    class _R:
        status_code = 200

        def json(self):
            return {"result": {"message_id": 1}}

    def _post(url, json=None, **_k):
        sent.append(json)
        return _R()

    with _soxta(bl, "TOKEN", TOKEN), _soxta(requests, "post", _post):
        bl.api("sendMessage", {"chat_id": 1, "text": f"xato: /bot{TOKEN}/x"})   # send_status/edit_status yo'li
        sendmod.tg_send(TOKEN, 1, f"xato: /bot{TOKEN}/x")
        with _env(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_CHAT_ID="1"):
            pp.send_to(1, f"xato: /bot{TOKEN}/x")
    assert len(sent) == 3 and all(TOKEN not in str(p) for p in sent), sent


def test_log_tokensiz():
    with tempfile.TemporaryDirectory() as d, _soxta(bl, "LOGS", Path(d)):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bl.log(f"tarmoq xatosi: /bot{TOKEN}/getUpdates")
            sendmod.log(f"/bot{TOKEN}/sendMessage")
            pp.log(f"/bot{TOKEN}/sendMessage")
        fayl = "".join(p.read_text(encoding="utf-8") for p in Path(d).glob("*.log"))
    assert TOKEN not in buf.getvalue() and TOKEN not in fayl and "bot***" in fayl, (buf.getvalue(), fayl)


def test_bot_listener_xatoni_chatga_matn_bilan_yubormaydi():
    """Regressiya qo'riqchisi: chatga xato matni (str(e)) to'g'ridan-to'g'ri ketmasin."""
    src = (ROOT / "bot_listener.py").read_text(encoding="utf-8")
    bad = re.findall(r"(?:send_retry|edit_status)\([^\n]*\{str\(e\)\[:1[25]0\]\}", src)
    assert not bad, bad


# ------------------------------------------------------------------ P0-2: Sheet ID'lar

def test_config_yaml_da_sheet_id_yoq():
    txt = (ROOT / "config.yaml").read_text(encoding="utf-8")
    ids = re.findall(r'(?:id|dashboard_id):\s*"([A-Za-z0-9_-]{20,})"', txt)
    assert not ids, f"public config.yaml'da Sheet ID: {ids}"
    assert "parol" not in txt.lower()


def _ov_yaml():
    return ('dashboard_id: "DASH-ID-1234567890"\n'
            'sheet_ids:\n  "Zubair PM KPI": "ZUBAIR-ID-123456789"\n  "SMM proektlar": "SMM-ID-1234567890"\n')


def test_overlay_env_dan():
    b64 = base64.b64encode(_ov_yaml().encode()).decode()
    with tempfile.TemporaryDirectory() as d, _soxta(fm, "DATA", Path(d)), _env(CONFIG_LOCAL_B64=b64):
        cfg = {s["name"]: s["id"] for s in fm.load_config(include_qa_only=True)}
        assert cfg == {"Zubair PM KPI": "ZUBAIR-ID-123456789", "SMM proektlar": "SMM-ID-1234567890"}, cfg
        assert fm.load_full_config()["dashboard_id"] == "DASH-ID-1234567890"


def test_overlay_data_fayldan_va_yoq_bolsa_bosh():
    with tempfile.TemporaryDirectory() as d, _soxta(fm, "DATA", Path(d)), _env(CONFIG_LOCAL_B64=None):
        lokal = ROOT / fm.CONFIG_LOCAL
        if lokal.exists():                     # dasturchi Mac'ida — bu holatni tekshirib bo'lmaydi
            return
        assert fm.load_config(include_qa_only=True) == [] and not fm.load_full_config().get("dashboard_id")
        (Path(d) / fm.CONFIG_LOCAL).write_text(_ov_yaml(), encoding="utf-8")
        ids = {s["name"]: s["id"] for s in fm.load_config()}
        assert ids == {"Zubair PM KPI": "ZUBAIR-ID-123456789", "SMM proektlar": "SMM-ID-1234567890"}, ids


def test_supervisor_id_yoq_bolsa_egaga_ogohlantiradi():
    xabarlar = []
    with _soxta(sv, "_notify_owner_once_daily", lambda m, key="": xabarlar.append((key, m))), \
            _soxta(fm, "load_config", lambda include_qa_only=False: []):
        assert sv.boot_config_check() is False
    assert xabarlar and xabarlar[0][0] == "config_ids" and "CONFIG_LOCAL_B64" in xabarlar[0][1], xabarlar
    with _soxta(fm, "load_config", lambda include_qa_only=False: [{"id": "x", "name": "y"}]), \
            _soxta(fm, "overlay_holati", lambda: ([], [], True)), \
            _soxta(u, "qaror_fayl", lambda: ROOT / "config.yaml"):          # mavjud fayl
        assert sv.boot_config_check() is True


def test_supervisor_qisman_muammolarni_aytadi():
    """Sheet nomi o'zgarsa / ID kaliti ortiqcha / dashboard_id yo'q / qarorlar fayli yo'q —
    hammasi egaga bitta ⚠️ da (jim tushib qolmasin — review)."""
    xabarlar = []
    with _soxta(sv, "_notify_owner_once_daily", lambda m, key="": xabarlar.append((key, m))), \
            _soxta(fm, "load_config", lambda include_qa_only=False: [{"id": "x", "name": "y"}]), \
            _soxta(fm, "overlay_holati", lambda: (["Islom PM KPI"], ["Islom PM KPl"], False)), \
            _soxta(u, "qaror_fayl", lambda: ROOT / "yoq-fayl.json"):
        assert sv.boot_config_check() is False
    (key, m), = xabarlar
    assert key == "config_holat" and "Islom PM KPI" in m and "dashboard_id" in m and "undiruv_qaror" in m, m


def test_overlay_nom_apostrof_va_holat():
    ov = ('sheet_ids:\n  "azizxo’ja pm kpi": "AZIZ-ID-1234567890"\n  "Eski nom": "OLD-ID-1234567890"\n')
    with tempfile.TemporaryDirectory() as d, _soxta(fm, "DATA", Path(d)), \
            _env(CONFIG_LOCAL_B64=base64.b64encode(ov.encode()).decode()):
        ids = {x["name"]: x["id"] for x in fm.load_config(include_qa_only=True)}
        assert ids == {"Azizxo'ja PM KPI": "AZIZ-ID-1234567890"}, ids
        idsiz, ortiqcha, dash = fm.overlay_holati()
        assert "Zubair PM KPI" in idsiz and "Azizxo'ja PM KPI" not in idsiz, idsiz
        assert ortiqcha == ["Eski nom"] and dash is False, (ortiqcha, dash)


def test_migratsiya_eski_configdan_overlay():
    sys.path.insert(0, str(ROOT / "scripts"))
    import maxfiy_migratsiya as mg

    ov = mg.overlay_from('dashboard_id: "D1"\nsheets:\n  - id: "A1"\n    name: "Zubair PM KPI"\n'
                         '  - id: ""\n    name: "Bosh"\n')
    assert ov == {"sheet_ids": {"Zubair PM KPI": "A1"}, "dashboard_id": "D1"}, ov


def test_kesilgan_xato_matnida_ham_token_yoq():
    """Review: xato matni log'dan OLDIN 120 belgida kesilsa tokenning yarmi qolardi
    (pm_push._tg, sendVoice). Real requests xato shaklida (URL 87-belgidan) tekshiriladi."""
    sir = TOKEN.split(":", 1)[1]
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as d, _soxta(bl, "LOGS", Path(d)), _soxta(bl, "TOKEN", TOKEN), \
            _soxta(requests, "post", _tarmoq_xatosi), _soxta(pp, "_owner", lambda: (TOKEN, "1")), \
            _soxta(pp.time, "sleep", lambda *_: None), contextlib.redirect_stdout(buf):
        pp._tg("sendMessage", {"chat_id": 1, "text": "x"}, attempts=1)
        with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
            bl.send_voice_file(f.name)
        fayl = "".join(x.read_text(encoding="utf-8") for x in Path(d).glob("*.log"))
    out = buf.getvalue() + fayl
    bo_lak = [sir[i:i + 8] for i in range(0, len(sir) - 7)]
    assert "bot***" in out and not any(b in out for b in bo_lak), out
    for n in range(80, 140):                         # har qanday kesish nuqtasida
        assert not any(b in maxfiy.redact(f"url: /bot{TOKEN}/x"[:n]) for b in bo_lak), n


def test_pm_push_id_yoq_bolsa_eski_snapshotdan_yubormaydi():
    """Review: CONFIG_LOCAL_B64 o'rnatilmagan kuni 09:30 push muzlagan eski snapshot'dan
    PM'larga qarz eslatmasi yubormasin — egaga sabab aytilsin."""
    yuborildi = []
    view = {"tab": None, "rows": [], "source": "none", "notes": [], "prev": {"rows": []}}
    with tempfile.TemporaryDirectory() as d, _soxta(pp, "STATE_FILE", Path(d) / "st.json"), \
            _soxta(u, "korinish", lambda *a, **k: dict(view)), _soxta(u, "smm_sheet_id", lambda: None), \
            _soxta(pp, "send_owner", lambda t: yuborildi.append(t)), \
            _soxta(pp, "send_to", lambda *a: yuborildi.append(a)):
        holat, msg = pp.run_daily(today=__import__("datetime").date(2026, 10, 12))
    assert holat == "no-config" and "CONFIG_LOCAL_B64" in msg, (holat, msg)
    assert yuborildi == [msg], yuborildi                                  # faqat egaga


# ------------------------------------------------------------------ P0-2: ega qarorlari

def test_qaror_fayli_data_dan_keyin_lokal():
    with tempfile.TemporaryDirectory() as d, _soxta(u, "DATA", Path(d)), _soxta(u, "QAROR_FAYL", None):
        lokal = ROOT / "undiruv_qaror.json"
        kutil = lokal if lokal.exists() else Path(d) / "undiruv_qaror.json"
        assert u.qaror_fayl() == kutil
        (Path(d) / "undiruv_qaror.json").write_text('{"qarorlar": []}', encoding="utf-8")
        assert u.qaror_fayl() == Path(d) / "undiruv_qaror.json"          # volume ustun


def test_supervisor_env_dan_qaror_fayli():
    data = b'{"qarorlar": []}'
    with tempfile.TemporaryDirectory() as d, _soxta(sv, "DATA", Path(d)), \
            _env(UNDIRUV_QAROR_B64=base64.b64encode(data).decode(), GOOGLE_SA_JSON=None):
        sv.boot_secrets()
        p = Path(d) / "undiruv_qaror.json"
        assert p.read_bytes() == data and (p.stat().st_mode & 0o777) == 0o600


def test_qaror_env_buzilsa_yoki_ochirilsa_eski_qaror_qollanmaydi():
    """Review: buzuq yoki o'chirilgan UNDIRUV_QAROR_B64 — avval env'dan yozilgan fayl
    jim qo'llanaverib qolmasin (.stale ga olinadi, egaga ⚠️). Qo'lda qo'yilgan fayl tegilmaydi."""
    good = base64.b64encode(b'{"qarorlar": [{"loyiha": "A"}]}').decode()
    xabarlar = []
    with tempfile.TemporaryDirectory() as d, _soxta(sv, "DATA", Path(d)), \
            _soxta(sv, "_notify_owner_once_daily", lambda m, key="": xabarlar.append(key)):
        f = Path(d) / "undiruv_qaror.json"
        with _env(UNDIRUV_QAROR_B64=good):
            assert sv.boot_qarorlar() and f.exists()
        with _env(UNDIRUV_QAROR_B64=good[:-2]):                       # nusxalashda kesilgan
            assert sv.boot_qarorlar() is False
        assert not f.exists() and (Path(d) / "undiruv_qaror.json.stale").exists() and xabarlar == ["undiruv_qaror"]
        with _env(UNDIRUV_QAROR_B64=good):
            assert sv.boot_qarorlar() and f.exists()
        with _env(UNDIRUV_QAROR_B64=None):                            # o'chirildi
            sv.boot_qarorlar()
        assert not f.exists() and len(xabarlar) == 2
        f.write_text('{"qarorlar": []}', encoding="utf-8")            # qo'lda (VPS/Mac)
        with _env(UNDIRUV_QAROR_B64=None):
            sv.boot_qarorlar()
        assert f.exists() and len(xabarlar) == 2


def test_git_da_maxfiy_fayl_yoq():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True)
    if r.returncode != 0:
        return                                  # git checkout emas (masalan Docker image)
    files = set(r.stdout.split())
    bad = {"undiruv_qaror.json", "config.local.yaml"} & files
    bad |= {f for f in files if f.startswith("seed/bot-memory/")}
    assert not bad, bad


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
