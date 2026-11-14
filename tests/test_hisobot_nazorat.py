"""deploy/railway/hisobot_nazorat.py — Railway'ning Mac'dagi tashqi nazorati (13.11 hodisasi).

Hammasi soxta sana va vaqtinchalik git klonida: jonli token ham, tarmoq ham yo'q.
Telegram — 127.0.0.1 dagi soxta server, macOS — argv'ni yozib oladigan soxta osascript.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKRIPT = ROOT / "deploy" / "railway" / "hisobot_nazorat.py"
_spec = importlib.util.spec_from_file_location("hisobot_nazorat", SKRIPT)
hn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hn)
TZ = hn.TZ


def T(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def _commit(repo, author, subject, when):
    iso = when.isoformat()
    env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL="a@x.local",
               GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL="a@x.local",
               GIT_AUTHOR_DATE=iso, GIT_COMMITTER_DATE=iso)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q",
                    "--allow-empty", "--no-verify", "-m", subject], env=env, check=True)


def _sinxron(repo, when):
    """reports-pull'ning muvaffaqiyatli pull'i: FETCH_HEAD vaqti = when."""
    fh = repo / ".git" / "FETCH_HEAD"
    fh.write_text("0000000000000000000000000000000000000000\t\tbranch 'main'\n")
    ts = when.timestamp()
    os.utime(fh, (ts, ts))


@pytest.fixture
def klon(tmp_path):
    repo = tmp_path / "klon"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _commit(repo, "abba-sheets-agent", "hisobot 2026-11-11", T("2026-11-11 09:00"))
    _commit(repo, "abba-sheets-agent", "chat 2026-11-11", T("2026-11-11 16:30"))
    _commit(repo, "abba-sheets-agent", "hisobot 2026-11-12", T("2026-11-12 09:01"))
    _commit(repo, "mac-tg-kunlik", "tg-kunlik 2026-11-13", T("2026-11-13 10:46"))
    _commit(repo, "mac-tg-kunlik", "hisobot 2026-11-13", T("2026-11-13 10:50"))  # boshqa muallif — hisob emas
    return repo


class Kanal:
    """Soxta kanal: xabarlarni yozib oladi, javoblar ro'yxatidan qaytaradi (bo'sh → ok)."""

    def __init__(self, *javoblar):
        self.xabarlar = []
        self.javoblar = list(javoblar)

    def __call__(self, xabar):
        self.xabarlar.append(xabar)
        return self.javoblar.pop(0) if self.javoblar else ("ok", None)


@pytest.fixture
def kanallar():
    return {"mac": Kanal(), "telegram": Kanal()}


def _run(klon, holat, kanallar, vaqt):
    return hn.ishga_tushir(T(vaqt), klon, holat, kanallar)


# ---- Asosiy qoida ----

def test_0930_gacha_hech_narsa(klon, tmp_path, kanallar):
    _sinxron(klon, T("2026-11-13 09:20"))
    holat = tmp_path / "holat.json"
    assert _run(klon, holat, kanallar, "2026-11-13 09:29") == "erta"
    assert not holat.exists()
    assert all(not k.xabarlar for k in kanallar.values())


def test_hisobot_bor_jim(klon, tmp_path, kanallar):
    _sinxron(klon, T("2026-11-12 09:31"))
    assert _run(klon, tmp_path / "h.json", kanallar, "2026-11-12 09:35") == "bor"
    assert all(not k.xabarlar for k in kanallar.values())


def test_yoq_kuniga_bir_marta_ikkala_kanalga(klon, tmp_path, kanallar):
    _sinxron(klon, T("2026-11-13 09:38"))
    holat = tmp_path / "h.json"
    assert _run(klon, holat, kanallar, "2026-11-13 09:40") == "yoq"
    for _ in range(5):                                   # keyingi 10 daqiqaliklar — takror yo'q
        assert _run(klon, holat, kanallar, "2026-11-13 10:30") == "yoq"
    assert len(kanallar["mac"].xabarlar) == 1
    assert len(kanallar["telegram"].xabarlar) == 1
    x = kanallar["telegram"].xabarlar[0]
    assert "13.11" in x["toliq"] and "hisobot 2026-11-13" in x["toliq"]
    assert "12.11 09:01 (1 kun oldin)" in x["toliq"]       # boshqa muallifning commit'i sanalmadi
    assert "12:00 gacha tiklansa" in x["toliq"]            # 09:40 — catch-up oynasi ichida
    assert "12.11 09:01" in x["qisqa"] and len(x["qisqa"]) < 200


def test_dam_olish_kunida_ham_tekshiriladi(klon, tmp_path, kanallar):
    assert T("2026-11-14 09:00").weekday() == 5           # shanba
    _sinxron(klon, T("2026-11-14 11:05"))
    assert _run(klon, tmp_path / "h.json", kanallar, "2026-11-14 11:10") == "yoq"
    x = kanallar["mac"].xabarlar[0]
    assert "14.11" in x["qisqa"] and "2 kun oldin" in x["qisqa"]
    assert "12:00 gacha tiklansa" in kanallar["telegram"].xabarlar[0]["toliq"]   # 11:10 — oyna ochiq


def test_catchup_otgan_bolsa_ertaga_deyiladi(klon, tmp_path, kanallar):
    _sinxron(klon, T("2026-11-13 13:00"))
    _run(klon, tmp_path / "h.json", kanallar, "2026-11-13 13:05")
    t = kanallar["telegram"].xabarlar[0]["toliq"]
    assert "ertaga 09:00" in t and "tiklansa, bugungi run" not in t


def test_kech_uygonish_eskirgan_klon_bilan_yolgon_ogohlantirish_yoq(klon, tmp_path, kanallar):
    """Mac 13:00 da uyg'ondi: klon hali tongdagi (07:10). Bu «tekshirib bo'lmadi» EMAS —
    reports-pull tortguncha kutiladi, keyin aniq qaror."""
    holat = tmp_path / "h.json"
    _sinxron(klon, T("2026-11-13 07:10"))
    assert _run(klon, holat, kanallar, "2026-11-13 13:00") == "kutish"
    assert all(not k.xabarlar for k in kanallar.values())
    _sinxron(klon, T("2026-11-13 13:01"))                 # reports-pull tortdi
    assert _run(klon, holat, kanallar, "2026-11-13 13:10") == "yoq"
    assert len(kanallar["mac"].xabarlar) == 1


def test_uzoq_tortilmasa_tekshirib_bolmadi_keyin_aniq_yoq(klon, tmp_path, kanallar):
    holat = tmp_path / "h.json"
    _sinxron(klon, T("2026-11-13 07:00"))
    t0 = T("2026-11-13 09:40")
    natijalar = [hn.ishga_tushir(t0 + timedelta(minutes=10 * i), klon, holat, kanallar)
                 for i in range(hn.ESKI_CHEGARA + 3)]
    assert natijalar[:hn.ESKI_CHEGARA - 1] == ["kutish"] * (hn.ESKI_CHEGARA - 1)
    assert natijalar[hn.ESKI_CHEGARA - 1] == "noma'lum"
    assert len(kanallar["mac"].xabarlar) == 1              # bir marta
    x = kanallar["telegram"].xabarlar[0]
    assert "tekshira olmadi" in x["toliq"] and "13.11 07:00 dan beri" in x["toliq"]
    _sinxron(klon, T("2026-11-13 12:30"))                 # tarmoq qaytdi — endi aniq
    assert _run(klon, holat, kanallar, "2026-11-13 12:35") == "yoq"
    assert len(kanallar["mac"].xabarlar) == 2              # yangi tur — alohida xabar
    assert "run bo'lmadi" in kanallar["mac"].xabarlar[1]["sarlavha"]


def test_yoq_aniqlangach_klon_eskirsa_ham_qaror_saqlanadi(klon, tmp_path, kanallar):
    holat = tmp_path / "h.json"
    _sinxron(klon, T("2026-11-13 09:38"))
    assert _run(klon, holat, kanallar, "2026-11-13 09:40") == "yoq"
    (klon / ".git" / "FETCH_HEAD").unlink()               # klon qayta olingan: sinxron vaqti yo'q
    t0 = T("2026-11-13 09:50")
    for i in range(hn.ESKI_CHEGARA + 1):
        assert hn.ishga_tushir(t0 + timedelta(minutes=10 * i), klon, holat, kanallar) == "yoq"
    assert len(kanallar["mac"].xabarlar) == 1              # «tekshirib bo'lmadi» chiqmaydi


def test_keyin_kelsa_tiklandi_faqat_yetgan_kanalga(klon, tmp_path):
    holat = tmp_path / "h.json"
    k = {"mac": Kanal(), "telegram": Kanal(("doimiy_xato", "HTTP 401 Unauthorized"))}
    _sinxron(klon, T("2026-11-13 09:38"))
    assert _run(klon, holat, k, "2026-11-13 09:40") == "yoq"
    _commit(klon, "abba-sheets-agent", "hisobot 2026-11-13", T("2026-11-13 10:05"))  # catch-up run
    _sinxron(klon, T("2026-11-13 10:08"))
    assert _run(klon, holat, k, "2026-11-13 10:10") == "bor"
    assert _run(klon, holat, k, "2026-11-13 10:20") == "bor"
    assert [x["sarlavha"] for x in k["mac"].xabarlar] == [
        "⚠️ ABBA hisobot: bugun run bo'lmadi", "✅ ABBA hisobot keldi"]
    assert "10:05" in k["mac"].xabarlar[1]["qisqa"]
    assert len(k["telegram"].xabarlar) == 1                # ogohlantirish yetmagan — tiklandi ham yo'q


def test_doimiy_xato_qayta_urinilmaydi_vaqtinchalik_3_marta(klon, tmp_path):
    holat = tmp_path / "h.json"
    k = {"mac": Kanal(*[("xato", "osascript kod 1")] * 5),
         "telegram": Kanal(("doimiy_xato", "HTTP 401 Unauthorized"))}
    _sinxron(klon, T("2026-11-13 09:38"))
    for i in range(6):
        _run(klon, holat, k, f"2026-11-13 1{i}:00")
    assert len(k["telegram"].xabarlar) == 1
    assert len(k["mac"].xabarlar) == hn.MAX_URINISH
    st = json.loads(holat.read_text(encoding="utf-8"))["ogoh"]["yoq"]
    assert st["telegram"]["holat"] == "doimiy_xato" and "401" in st["telegram"]["xato"]
    assert st["mac"]["urinish"] == hn.MAX_URINISH


def test_vaqtinchalik_xatodan_keyin_yetkaziladi(klon, tmp_path):
    holat = tmp_path / "h.json"
    k = {"telegram": Kanal(("xato", "URLError: timed out"))}
    _sinxron(klon, T("2026-11-13 09:38"))
    _run(klon, holat, k, "2026-11-13 09:40")
    _run(klon, holat, k, "2026-11-13 09:50")
    _run(klon, holat, k, "2026-11-13 10:00")
    assert len(k["telegram"].xabarlar) == 2                # 2-urinish ok → to'xtadi


def test_ertangi_kun_yangidan_boshlanadi(klon, tmp_path, kanallar):
    holat = tmp_path / "h.json"
    _sinxron(klon, T("2026-11-13 09:38"))
    _run(klon, holat, kanallar, "2026-11-13 09:40")
    _sinxron(klon, T("2026-11-14 09:31"))
    assert _run(klon, holat, kanallar, "2026-11-14 09:40") == "yoq"
    assert len(kanallar["mac"].xabarlar) == 2
    assert json.loads(holat.read_text(encoding="utf-8"))["sana"] == "2026-11-14"


def test_klon_yoq_bolsa_jim_qolmaydi(tmp_path, kanallar):
    holat = tmp_path / "h.json"
    t0 = T("2026-11-13 09:40")
    for i in range(hn.ESKI_CHEGARA):
        n = hn.ishga_tushir(t0 + timedelta(minutes=10 * i), tmp_path / "yoq-klon", holat, kanallar)
    assert n == "noma'lum"
    assert "klonni o'qib bo'lmadi" in kanallar["telegram"].xabarlar[0]["toliq"]


# ---- Kanallar ----

class _TgServer:
    def __init__(self, kod=200, javob=None):
        self.so_rovlar = []
        tashqi = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                tashqi.so_rovlar.append((self.path, parse_qs(self.rfile.read(n).decode())))
                body = json.dumps(javob if javob is not None else {"ok": kod == 200}).encode()
                self.send_response(kod)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def test_tg_yubor_soxta_serverga():
    s = _TgServer()
    try:
        assert hn.tg_yubor("123:SOXTA", "42", "salom «yo'q»", api=s.url) == ("ok", None)
    finally:
        s.close()
    path, form = s.so_rovlar[0]
    assert path == "/bot123:SOXTA/sendMessage"
    assert form["chat_id"] == ["42"] and form["text"] == ["salom «yo'q»"]


@pytest.mark.parametrize("kod,kutilgan", [(401, "doimiy_xato"), (400, "doimiy_xato"),
                                          (429, "xato"), (502, "xato")])
def test_tg_xato_turlari_token_yashirin(kod, kutilgan):
    s = _TgServer(kod, {"ok": False, "description": "bot123:SOXTA rad etildi"})
    try:
        holat, xato = hn.tg_yubor("123:SOXTA", "42", "x", api=s.url)
    finally:
        s.close()
    assert holat == kutilgan and str(kod) in xato
    assert "SOXTA" not in xato


def test_tg_tarmoq_xatosi_vaqtinchalik():
    holat, xato = hn.tg_yubor("123:SOXTA", "42", "x", api="http://127.0.0.1:9")
    assert holat == "xato" and "SOXTA" not in xato


def test_env_oqi(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# izoh\nexport TELEGRAM_BOT_TOKEN='1:ab=c'\nTELEGRAM_CHAT_ID=42 # egasi\n"
                 'BOSHQA="x y"\nbuzuq qator\n', encoding="utf-8")
    d = hn.env_oqi(f)
    assert d == {"TELEGRAM_BOT_TOKEN": "1:ab=c", "TELEGRAM_CHAT_ID": "42", "BOSHQA": "x y"}
    assert hn.env_oqi(tmp_path / "yoq") == {}


def test_token_yoq_bolsa_sababi_aytiladi(tmp_path):
    f = tmp_path / ".env"
    f.write_text("TELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    k = hn.yuboruvchilar("mac,telegram", f)
    assert set(k) == {"mac", "telegram"}
    holat, xato = k["telegram"]({"toliq": "x"})
    assert holat == "doimiy_xato" and "TELEGRAM_BOT_TOKEN" in xato


def test_mac_yubor_matn_argv_orqali(tmp_path, monkeypatch):
    """Apostrof va qo'shtirnoq AppleScript'ni buzmasin: matn argv'da alohida keladi."""
    yozuv = tmp_path / "argv.json"
    soxta = tmp_path / "osascript"
    soxta.write_text(f"#!{sys.executable}\nimport json, sys\n"
                     f"json.dump(sys.argv[1:], open({str(yozuv)!r}, 'w'))\n", encoding="utf-8")
    soxta.chmod(0o755)
    monkeypatch.setattr(hn, "OSASCRIPT", str(soxta))
    assert hn.mac_yubor({"sarlavha": "⚠️ run bo'lmadi", "qisqa": 'yo\'q "x"'}) == ("ok", None)
    argv = json.loads(yozuv.read_text())
    assert argv[-2:] == ["⚠️ run bo'lmadi", 'yo\'q "x"']
    assert "display notification (item 2 of argv)" in " ".join(argv)


def test_yuboruvchilar_tokeni_logga_chiqmaydi(tmp_path, capsys):
    f = tmp_path / ".env"
    f.write_text("TELEGRAM_BOT_TOKEN=999:MAXFIY\nTELEGRAM_CHAT_ID=42\n", encoding="utf-8")
    hn.yuboruvchilar("telegram", f)
    hn.log("xato: https://api.telegram.org/bot999:MAXFIY/sendMessage")
    assert "MAXFIY" not in capsys.readouterr().out


# ---- Kod bilan moslik (D1: hujjat/nusxa koddan ajralmasin) ----

def test_supervisor_jadvali_bilan_mos():
    """Nazorat «run har kuni 09:00, catch-up 3 soat» deb hisoblaydi — supervisor o'zgarsa
    bu test yiqiladi va nazoratni ham yangilash kerakligi ko'rinadi."""
    src = (ROOT / "supervisor.py").read_text(encoding="utf-8")
    m = re.search(r"DAILY_AT, PM_PUSH_AT = \((\d+), (\d+)\)", src)
    g = re.search(r"CATCHUP_GRACE_H = (\d+)", src)
    assert m and g
    run = hn.RUN_VAQTI
    assert (run.hour, run.minute) == (int(m.group(1)), int(m.group(2)))
    tugash = datetime.combine(datetime(2026, 1, 1).date(), run) + timedelta(hours=int(g.group(1)))
    assert tugash.time() == hn.CATCHUP_TUGASH
    assert hn.MUDDAT > run
    assert "day_of_week" not in src                        # run har kuni — dam olish kunlari ham


def test_push_reports_commit_formati_bilan_mos():
    src = (ROOT / "push_reports.py").read_text(encoding="utf-8")
    assert f"user.name={hn.AUTHOR}" in src
    assert '"commit", "-q", "-m", f"hisobot {date.today().isoformat()}"' in src


# ---- CLI (launchd shunday chaqiradi) ----

def test_cli_soxta_sana_quruq(klon, tmp_path):
    _sinxron(klon, T("2026-11-13 09:38"))
    py = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
    r = subprocess.run([py, str(SKRIPT), "--klon", str(klon), "--holat", str(tmp_path / "h.json"),
                        "--env", str(tmp_path / "yoq.env"), "--hozir", "2026-11-13T09:40",
                        "--quruq"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "natija: yoq" in r.stdout
    assert "[quruq:mac] ⚠️ ABBA hisobot: bugun run bo'lmadi" in r.stdout
    assert "[quruq:telegram] ⚠️ abba-sheets-agent: bugungi (13.11)" in r.stdout
