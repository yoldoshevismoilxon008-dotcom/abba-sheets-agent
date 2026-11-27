"""Telefon raqamini vault'ga ketadigan WALL-E matnlarida yashirish (maxfiylik skani, 27.11.2026).

09:00 hisobot (push_reports), chat arxivi (chat_log, push_chat, wow_kunlik._arxiv) va Mac'dagi
miya yig'uvchisi (deploy/mac-sync/miya: asos.redakt, walle) vault'ga — GitHub va WALL-E bilim
bazasiga — yozadi. Qoida TG audit (abba-tg-audit/maxfiylik.py) bilan bir xil va ikki nusxada
turadi: maxfiy.py (Railway) va miya/asos.py (Mac, alohida nusxalanadi). Bu fayl:
  - qoida namunalarini IKKALA nusxada tekshiradi (summa, sana, ID ga tegilmaydi);
  - ikki nusxa bir-biridan farqlanib qolmasligini qo'riqlaydi;
  - har qo'llash joyida yashirish yozishdan va kesishdan OLDIN ekanini tekshiradi.

Raqamlar soxta (0 lar bilan) — repo ommaviy, haqiqiy telefon testga yozilmaydi.
"""
import inspect
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy" / "mac-sync"))
import chat_log          # noqa: E402
import maxfiy            # noqa: E402
import push_chat         # noqa: E402
import push_reports      # noqa: E402
import wow_kunlik        # noqa: E402
from miya import asos, walle  # noqa: E402

B = maxfiy.TELEFON_BELGI
NUSXALAR = [pytest.param(maxfiy.telefon_yashir, id="maxfiy"),
            pytest.param(asos.telefon_yashir, id="miya-asos")]


def _raqamsiz(s):
    return not any(ch.isdigit() for ch in s)


# ---------------------------------------------------------------- qoida (ikkala nusxa)

@pytest.mark.parametrize("Y", NUSXALAR)
@pytest.mark.parametrize("s", [
    "+998 90 000 00 00", "+998900000000", "998900000000", "+998 (90) 000-00-00",
    "+998-90-000-00-00", "+998 90.000.00.00", "(90) 000-00-00", "90 000 00 00",
    "90-000-00-00", "90 000 0000", "90 0000000", "33 000 00 00", "71 000 00 00",
    # qavsdan keyin ajratuvchisiz — real xabarlarda yuzlab marta uchragan
    "(90)000-00-00", "(90)0000000", "(71)000-00-00",
    # NBSP + uzilmas tire, ikki bo'shliq, «+ 998»
    "+998 90 000‑00‑00", "+998 90 000 00  00", "+ 998 90 000 00 00",
])
def test_raqam_korinishlari_yashiriladi(Y, s):
    assert Y(f"aloqa: {s} rahmat") == f"aloqa: {B} rahmat", s


@pytest.mark.parametrize("Y", NUSXALAR)
@pytest.mark.parametrize("s, kutilgan", [
    # kalit so'zsiz yopishgan 9 raqam — lead oqishining asosiy shakli
    ("900000000", B),
    ("Mijoz 900000000 raqamini qoldirdi.", f"Mijoz {B} raqamini qoldirdi."),
    ("Chorsu 900000000\nYunusobod 910000000", f"Chorsu {B}\nYunusobod {B}"),
    # kalit so'zdan keyin
    ("tel: 900000000", f"tel: {B}"),
    ("📞 900000000", f"📞 {B}"),
    ("Номер: 990000000", f"Номер: {B}"),
    # gap oxiri, ro'yxat, vergulga yopishgan
    ("Telefon raqamini qoldirdi: 90-000-00-00.", f"Telefon raqamini qoldirdi: {B}."),
    ("90 000 00 00, 91 000 00 00", f"{B}, {B}"),
    ("Ali,90 000 00 00", f"Ali,{B}"),
    # boshqa davlatlar va bir nechta raqam
    ("+7 916 000 00 00", B),
    ("+44 20‑000 0000", B),
    ("+998 90 000 00 00 yoki 91 000 00 00", f"{B} yoki {B}"),
    # 09:00 hisobot jadvali katagidagi iqtibos (2026-10-10 dagi holat shakli)
    ("| Loyiha | Mijoz 900000000 ga qo'ng'iroq |", f"| Loyiha | Mijoz {B} ga qo'ng'iroq |"),
])
def test_shakllar(Y, s, kutilgan):
    assert Y(s) == kutilgan


@pytest.mark.parametrize("Y", NUSXALAR)
@pytest.mark.parametrize("s", [
    "Narxi 90 000 000 so'm", "1 500 000 so'm", "+170 000 000", "+1 500 000 000", "+500 000",
    "900000000 so'm to'landi", "Narxi: 900000000", "Jami 900000000", "ИНН: 200000000",
    "(id 900000000)", "Buyurtma №900000000", "docs/edit#gid=900000000",
    "https://zoom.us/j/90000000000?pwd=abc", "admin 900000000aa",
    "27.11.2026 15:30", "2026-11-27", "3.14159", "1,250,000", "99 500 so'm", "ID 1234567890123",
    # 09:00 hisobotdagi odatiy satrlar
    "Kelishilgan: $65 751 · undirildi $39 833 (60,6%)", "Qoldiq 12 500 000 so'm, muddat 05.12",
    "44/45 tab o'zgardi · 09:00 run", "▸ **Undiruv noyabr** — 3 ta MUDDAT O'TDI",
])
def test_summa_sana_va_id_ga_tegilmaydi(Y, s):
    assert Y(s) == s


@pytest.mark.parametrize("Y", NUSXALAR)
def test_bosh_qiymat_va_takror_yashirish(Y):
    assert Y("") == ""
    assert Y(None) is None
    bir = Y("raqam 900000000 va +998 90 000 00 00")
    assert Y(bir) == bir            # idempotent: [telefon] qayta tegilmaydi


# ---------------------------------------------------------------- ikki nusxa farqlanmasin

_NAQSHLAR = ("_UZ", "_XALQARO", "_MAHALLIY", "_YOPISHGAN", "_PUL_KEYIN", "_PUL_OLDIN",
             "_ID_OLDIN", "_KALIT_SOZ")


def test_miya_nusxasi_maxfiy_bilan_bir_xil():
    """miya/asos.py ~/.abba-miya ga alohida nusxalanadi va maxfiy.py ni import qila olmaydi.
    Qoida ikki joyda — biri o'zgarib, ikkinchisi eskicha qolsa, shu test yiqiladi."""
    for nom in ("TELEFON_BELGI", "_KOD", "_KORINMAS", "_A"):
        assert getattr(asos, nom) == getattr(maxfiy, nom), nom
    for nom in _NAQSHLAR:
        a, m = getattr(asos, nom), getattr(maxfiy, nom)
        assert (a.pattern, a.flags) == (m.pattern, m.flags), nom
    for nom in ("_xalqaro", "_yopishgan", "telefon_yashir"):
        assert inspect.getsource(getattr(asos, nom)) == inspect.getsource(getattr(maxfiy, nom)), nom


# ---------------------------------------------------------------- 09:00 hisobot → repo

def _push_reports_muhit(tmp_path, monkeypatch):
    snaps, out = tmp_path / "snapshots", tmp_path / "clone" / "hisobotlar"
    out.mkdir(parents=True)
    monkeypatch.setattr(push_reports, "SNAPSHOTS", snaps)
    return snaps, out


def test_push_reports_hisobotni_yozishdan_oldin_yashiradi(tmp_path, monkeypatch):
    snaps, out = _push_reports_muhit(tmp_path, monkeypatch)
    (snaps / "2026-11-27").mkdir(parents=True)
    rep = snaps / "2026-11-27" / "report.md"
    asl = "▸ **Undiruv**\n- Ali: 900000000 ga qo'ng'iroq · qoldiq 12 500 000 so'm\n"
    rep.write_text(asl, encoding="utf-8")

    assert push_reports._hisobotlarni_yoz(out) == 1
    yozilgan = (out / "2026-11-27.md").read_text(encoding="utf-8")
    assert "900000000" not in yozilgan and B in yozilgan
    assert "12 500 000 so'm" in yozilgan                   # summa o'z joyida
    assert rep.read_text(encoding="utf-8") == asl          # snapshot (egasiniki) o'zgarmaydi
    assert push_reports._hisobotlarni_yoz(out) == 0        # ikkinchi yurish — o'zgarish yo'q


def test_push_reports_snapshoti_ochgan_eski_hisobot_ham_maskalanadi(tmp_path, monkeypatch):
    """Snapshot'lar 30 kun saqlanadi (run.sh). 2026-10-10 kabi eski hisobot repo'da qoladi va
    snapshot bo'lmagani uchun boshqa qayta yozilmasdi — joyida maskalanishi kerak."""
    snaps, out = _push_reports_muhit(tmp_path, monkeypatch)
    eski = out / "2026-10-10.md"
    eski.write_text("# 2026-10-10 — Sheets kunlik hisobot\n\n| Ali | 900000000 |\n", encoding="utf-8")
    toza = out / "2026-10-11.md"
    toza.write_text("# 2026-10-11 — Sheets kunlik hisobot\n\nQoldiq 1 500 000 so'm\n", encoding="utf-8")
    toza_vaqt = toza.stat().st_mtime_ns

    assert push_reports._hisobotlarni_yoz(out) == 1
    assert eski.read_text(encoding="utf-8").endswith(f"| Ali | {B} |\n")
    assert toza.stat().st_mtime_ns == toza_vaqt            # telefonsiz faylga tegilmaydi
    assert push_reports._hisobotlarni_yoz(out) == 0


# ---------------------------------------------------------------- chat arxivi

def test_push_chat_eski_va_manbasiz_fayllar_maskalanadi(tmp_path, monkeypatch):
    src, clone = tmp_path / "chat", tmp_path / "chat-repo"
    src.mkdir()
    (clone / "chat").mkdir(parents=True)
    monkeypatch.setattr(push_chat, "CHAT_SRC", src)
    monkeypatch.setattr(push_chat, "CLONE", clone)
    asl = "## 10:00 · Savol\nMijoz raqami 90 000 00 00\n"
    (src / "2026-11-20.md").write_text(asl, encoding="utf-8")          # chat_log'dan oldingi yozuv
    (clone / "chat" / "2026-08-01.md").write_text("tel: 900000000\n", encoding="utf-8")  # manbasiz

    assert push_chat._sync_files() == 2
    assert (clone / "chat" / "2026-11-20.md").read_text(encoding="utf-8") == \
        f"## 10:00 · Savol\nMijoz raqami {B}\n"
    assert (clone / "chat" / "2026-08-01.md").read_text(encoding="utf-8") == f"tel: {B}\n"
    assert (src / "2026-11-20.md").read_text(encoding="utf-8") == asl   # volume nusxasi o'zgarmaydi
    assert push_chat._sync_files() == 0


@pytest.fixture()
def chat_papka(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_log, "CHAT_DIR", tmp_path / "chat")
    return tmp_path / "chat"


def test_chat_log_savol_javob_va_buyruq_maskalanadi(chat_papka):
    now = datetime(2026, 11, 27, 10, 0)
    chat_log.append_qa("Ali'ning raqami +998 90 000 00 00, yozib qo'y", "Yozdim: 900000000.", now=now)
    chat_log.append_cmd("WOW kunlik reja (2026-11-27) yuborildi: Mijoz 90 000 00 00 bilan", now=now)
    matn = (chat_papka / "2026-11-27.md").read_text(encoding="utf-8")
    assert "000 00 00" not in matn and "900000000" not in matn
    assert matn.count(B) == 3
    assert "WOW kunlik reja (2026-11-27) yuborildi" in matn            # walle._WOW shakli buzilmaydi


def test_chat_log_kesish_chegarasida_raqam_yarmi_qolmaydi(chat_papka):
    """Yashirish _clip'dan KEYIN bo'lsa, CHAT_MAX chegarasida «+998 9» ochiq qolardi."""
    javob = "x" * (chat_log.CHAT_MAX - 8) + " +998 90 000 00 00 tamom"
    chat_log.append_qa("savol", javob, now=datetime(2026, 11, 27, 10, 0))
    matn = (chat_papka / "2026-11-27.md").read_text(encoding="utf-8")
    dum = matn.split("x" * 100)[-1]
    assert "qisqartirildi" in dum and _raqamsiz(dum), dum


def test_wow_arxiv_1500_chegarasida_raqam_yarmi_qolmaydi(monkeypatch):
    yozildi = []
    monkeypatch.setattr(chat_log, "append_cmd", lambda s, now=None: yozildi.append(s))
    sana = "2026-11-27"
    bosh = f"WOW {wow_kunlik.SLOTLAR['ertalab']['sarlavha'].lower()} ({sana}) yuborildi: "
    ish = "x" * (1500 - len(bosh) - 6) + " +998 90 000 00 00"   # raqam 1500-belgida kesiladi
    wow_kunlik._arxiv(sana, "ertalab", [{"ish": ish}])
    assert len(yozildi) == 1
    assert yozildi[0].startswith(bosh) and _raqamsiz(yozildi[0][len(bosh):]), yozildi[0][-30:]


# ---------------------------------------------------------------- miya yig'uvchisi (Mac)

def test_redakt_toliq_qoida_va_tartib():
    t = asos.redakt("tel 900000000, (90)000-00-00; summa 90 000 000 so'm; 2026-11-27")
    assert t == f"tel {B}, {B}; summa 90 000 000 so'm; 2026-11-27"
    # email telefondan oldin: raqamli manzil butunligicha [email] bo'ladi
    assert asos.redakt("yozing: ali998900000000@mail.uz") == "yozing: [email]"
    # sir telefondan oldin: bot tokeni «[telefon]:…» bo'lib, dumi ochiq qolmasin
    token = "9" + "0" * 8 + ":" + "A" * 35
    t = asos.redakt(f"token {token}")
    assert "AAAA" not in t and "[MAXFIY]" in t
    # karta (Luhn) avvalgidek
    assert asos.redakt("karta 0000 0000 0000 0000") == "karta [karta]"


def test_walle_0900_bandi_redakt_qilinadi(tmp_path):
    """walle 09:00 Sheets hisobotidan bo'lim sarlavhasi va birinchi qatorni oladi — u
    hisobot jadvalidan iqtibos bo'lishi mumkin. Avval bu band redakt'dan o'tmasdi."""
    kun = "2026-11-27"
    p = tmp_path / "abba-sheets-agent" / "hisobotlar" / f"{kun}.md"
    p.parent.mkdir(parents=True)
    p.write_text("▸ **Undiruv 900000000**\n- Ali: 90 000 00 00 ga qo'ng'iroq qilsin\n", encoding="utf-8")
    chat = {"bor": False, "savollar": [("10:00", "Mijoz 900000000 yozdi")], "buyruqlar": [], "wow": []}
    matn = walle.kun_matni(tmp_path, kun, chat, walle.hisobot_oqi(tmp_path, kun), {}, None, [])
    assert "900000000" not in matn and "000 00 00" not in matn
    assert matn.count(B) == 3
