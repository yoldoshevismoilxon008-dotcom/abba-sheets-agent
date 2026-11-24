"""WOW ai — kunlik reja (ertalab) va hisobot (kechqurun) → boshliqqa.

Tarmoq, Claude, STT va userbot soxta: Telegram chaqiruvlari yoziladi, soat qo'lda suriladi.
pytest tests/test_wow_kunlik.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wow_kunlik as wk  # noqa: E402

TZ = ZoneInfo("Asia/Tashkent")


class Soxta:
    """Telegram (bot) + userbot + Claude soxtalari."""

    def __init__(self):
        self.mid = 100
        self.calls = []          # (method, payload)
        self.rasmlar = []        # (caption, png)
        self.yuborildi = []      # userbot: (to, path_name, caption, png)
        self.userbot_xato = None
        self.claude = None       # dict natija yoki Exception
        self.claude_args = []

    def keyingi(self):
        self.mid += 1
        return self.mid

    def api(self, method, payload):
        self.calls.append((method, payload))
        if method == "sendMessage":
            return {"message_id": self.keyingi()}
        return True

    def rasm(self, png, caption, kb=None):
        self.rasmlar.append((caption, png, kb))
        return self.keyingi()

    def send_photo(self, to, path, caption=""):
        if self.userbot_xato:
            raise self.userbot_xato
        self.yuborildi.append((to, Path(path).name, caption, Path(path).read_bytes()))

    def jadval_yangila(self, slot, joriy, kiritma, tur, reja=None, nomlar=None, sana=""):
        self.claude_args.append({"slot": slot, "joriy": joriy, "kiritma": kiritma, "tur": tur,
                                 "reja": reja})
        if isinstance(self.claude, Exception):
            raise self.claude
        return wk.tekshir(self.claude, slot)

    def matnlar(self, method="sendMessage"):
        return [p.get("text") or p.get("caption") or "" for m, p in self.calls if m == method]


@pytest.fixture
def s(monkeypatch, tmp_path):
    sx = Soxta()
    monkeypatch.setattr(wk, "DIR", tmp_path / "wow")
    monkeypatch.setattr(wk, "SNAPSHOTS", tmp_path / "snap")
    monkeypatch.setattr(wk, "_api", sx.api)
    monkeypatch.setattr(wk, "rasm", sx.rasm)
    monkeypatch.setattr(wk, "jadval_yangila", sx.jadval_yangila)
    monkeypatch.setattr(wk, "malum_nomlar", lambda limit=150: ["Livardi", "Orzu"])
    import userbot_sender

    monkeypatch.setattr(userbot_sender, "send_photo", sx.send_photo)
    import chat_log

    monkeypatch.setattr(chat_log, "append_cmd", lambda *a, **k: None)
    sx.vaqt = datetime(2026, 11, 23, 9, 0, tzinfo=TZ)
    monkeypatch.setattr(wk, "hozir", lambda: sx.vaqt)
    return sx


def _msg(text=None, **extra):
    m = {"chat": {"id": 555}, "from": {"id": 555, "first_name": "Ismoilxon"}, **extra}
    if text is not None:
        m["text"] = text
    return m


def _cq(data, mid=999):
    return {"id": "cb1", "data": data, "from": {"id": 555},
            "message": {"message_id": mid, "chat": {"id": 555}}}


def _st(s):
    return wk.yukla(s.vaqt.date().isoformat())


SANA = "2026-11-23"
REJA = {"savol": False, "jadval": [
    {"ish": "Livardi: kontent-reja tasdiqlash", "izoh": "11:00 gacha"},
    {"ish": "Orzu: reels TZ berish"},
    {"ish": "Undiruv: 3 mijozga qo'ng'iroq"}], "izoh": ""}


def _qoralama(s, text="1. Livardi reja 2. Orzu TZ 3. undiruv"):
    s.claude = REJA
    assert wk.sorov("ertalab") == "sent"
    assert wk.ushlaydimi(_msg(text)) == "ertalab"
    return wk.xabarni_ishlash(_msg(text), "ertalab")


# ---------------- so'rov va ushlash ----------------

def test_ertalab_sorov_keyin_matn_ushlanadi_buyruq_va_rasm_yoq(s):
    assert wk.sorov("ertalab") == "sent"
    st = _st(s)
    assert st["faol"] == "ertalab" and st["ertalab"]["holat"] == "kutilmoqda"
    assert "Xayrli tong" in s.matnlar()[0]
    assert wk.ushlaydimi(_msg("bugun Livardi bilan ishlayman")) == "ertalab"
    assert wk.ushlaydimi(_msg(voice={"file_id": "v", "duration": 20})) == "ertalab"
    assert wk.ushlaydimi(_msg("/hisobot")) is None
    assert wk.ushlaydimi(_msg(photo=[{"file_id": "p"}])) is None


def test_soralmagan_kunda_hech_narsa_ushlanmaydi(s):
    assert wk.ushlaydimi(_msg("Zubairda Livardi bormi?")) is None


def test_keyinroq_ushlamaydi_lekin_sorovga_reply_ushlanadi(s):
    wk.sorov("ertalab")
    ask_mid = _st(s)["ertalab"]["xabarlar"][0]
    assert wk.callback(_cq(f"wow:keyin:{SANA}:ertalab", ask_mid)) == "wow-keyin"
    assert wk.ushlaydimi(_msg("savol: undiruv qancha?")) is None
    assert wk.ushlaydimi(_msg("Livardi reja", reply_to_message={"message_id": ask_mid})) \
        == "ertalab"
    # keyingi soatdagi eslatma pauzani yechadi
    s.vaqt = s.vaqt.replace(hour=10)
    assert wk.sorov("ertalab") == "sent"
    assert "hali yozilmadi" in s.matnlar()[-1]
    assert wk.ushlaydimi(_msg("Livardi reja")) == "ertalab"


def test_oxirgi_eslatma_belgisi(s):
    for soat in (9, 10, 11, 12):
        s.vaqt = s.vaqt.replace(hour=soat)
        assert wk.sorov("ertalab") == "sent"
    assert "oxirgi eslatma" in s.matnlar()[-1]
    assert _st(s)["ertalab"]["sorovlar"] == ["09:00", "10:00", "11:00", "12:00"]


# ---------------- qoralama ----------------

def test_matndan_qoralama_va_preview_tugmalari(s):
    assert _qoralama(s) == ("ok", "1. Livardi reja 2. Orzu TZ 3. undiruv")
    st = _st(s)
    assert st["ertalab"]["holat"] == "qoralama"
    assert [r["ish"] for r in st["ertalab"]["jadval"]][0] == "Livardi: kontent-reja tasdiqlash"
    assert st["ertalab"]["jadval"][0]["holat"] == ""          # reja rejimida holat yo'q
    caption, png, kb = s.rasmlar[-1]
    assert png.startswith(b"\x89PNG")
    assert "qoralama" in caption and "Qabul qiluvchi belgilanmagan" in caption
    datalar = [b["callback_data"] for q in kb["inline_keyboard"] for b in q]
    assert datalar == [f"wow:ok:{SANA}:ertalab", f"wow:bekor:{SANA}:ertalab"]
    assert s.claude_args[0]["tur"] == "matn" and s.claude_args[0]["joriy"] == []


def test_ikkinchi_xabar_joriy_jadval_bilan_va_eski_preview_ochadi(s):
    _qoralama(s)
    eski = _st(s)["ertalab"]["preview_mid"]
    s.claude = {"savol": False, "jadval": REJA["jadval"][:2], "izoh": "3-band o'chirildi"}
    assert wk.ushlaydimi(_msg("3-ni o'chir")) == "ertalab"
    assert wk.xabarni_ishlash(_msg("3-ni o'chir"), "ertalab")[0] == "ok"
    assert len(s.claude_args[1]["joriy"]) == 3                 # Claude joriy jadvalni ko'rdi
    assert len(_st(s)["ertalab"]["jadval"]) == 2
    assert ("deleteMessage", {"chat_id": "", "message_id": eski}) in \
        [(m, {**p, "chat_id": ""}) for m, p in s.calls if m == "deleteMessage"]
    assert "3-band o'chirildi" in s.rasmlar[-1][0]


def test_savol_qa_ga_qaytadi_holat_ozgarmaydi(s):
    wk.sorov("ertalab")
    s.claude = {"savol": True, "jadval": []}
    assert wk.xabarni_ishlash(_msg("Zubairda Livardi bormi?"), "ertalab") == \
        ("savol", "Zubairda Livardi bormi?")
    st = _st(s)
    assert st["ertalab"]["holat"] == "kutilmoqda" and st["ertalab"]["ishlanmoqda"] is None
    assert not s.rasmlar


def test_ai_ishlamasa_oddiy_bolinadi_va_ogohlantiriladi(s):
    wk.sorov("ertalab")
    s.claude = RuntimeError("claude -p xato")
    r = wk.xabarni_ishlash(_msg("1. Livardi reja\n2) Orzu TZ\n- undiruv; Hoji KPI"), "ertalab")
    assert r[0] == "ok"
    assert [x["ish"] for x in _st(s)["ertalab"]["jadval"]] == \
        ["Livardi reja", "Orzu TZ", "undiruv", "Hoji KPI"]
    assert "AI hozir ishlamadi" in s.rasmlar[-1][0]


def test_ish_topilmasa_qoralama_ochilmaydi(s):
    wk.sorov("ertalab")
    s.claude = {"savol": False, "jadval": []}
    assert wk.xabarni_ishlash(_msg("salom"), "ertalab")[0] == "bosh"
    assert _st(s)["ertalab"]["holat"] == "kutilmoqda"
    assert "ish topilmadi" in s.matnlar()[-1]


# ---------------- yuborish ----------------

def test_boshliq_belgilash_va_yuborish(s):
    assert wk.buyruq("/boshliq @test_boss Anvar aka", _msg()) == "wow-boshliq"
    _qoralama(s)
    assert "Anvar akaga ketadi" in s.rasmlar[-1][0]
    assert "15 daqiqa" in s.rasmlar[-1][0]
    mid = _st(s)["ertalab"]["preview_mid"]
    s.vaqt = s.vaqt.replace(minute=7)
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab", mid)) == "wow-ok-yuborildi"
    (to, nom, caption, png), = s.yuborildi
    assert to == "@test_boss" and nom == f"reja-{SANA}.png" and png.startswith(b"\x89PNG")
    assert caption.startswith("Kunlik reja — 23.11.2026, dushanba")
    assert "1. Livardi: kontent-reja tasdiqlash (11:00 gacha)" in caption
    st = _st(s)
    assert st["ertalab"]["holat"] == "yuborildi" and st["ertalab"]["yuborildi"] == "09:07"
    assert st["faol"] is None
    tahrir = [p for m, p in s.calls if m == "editMessageCaption"][-1]
    assert tahrir["message_id"] == mid and "Anvar akaga yuborildi" in tahrir["caption"]
    # yuborilgandan keyin xabarlar odatiy Q&A'ga ketadi
    assert wk.ushlaydimi(_msg("Zubairda Livardi bormi?")) is None


def test_ikki_marta_bosilsa_bir_marta_ketadi(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    _qoralama(s)
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab")) == "wow-ok-yuborildi"
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab")) == "wow-ok-yuborildi"
    assert len(s.yuborildi) == 1


def test_boshliq_yoq_bolsa_yuborilmaydi(s):
    _qoralama(s)
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab")) == "wow-ok-boshliq-yoq"
    assert not s.yuborildi and _st(s)["ertalab"]["holat"] == "qoralama"
    assert "/boshliq @username" in s.matnlar()[-1]


def test_userbot_xatosi_rasm_egaga_va_qayta_urinish(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    _qoralama(s)
    s.userbot_xato = RuntimeError("FloodWait")
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab")) == "wow-ok-xato"
    st = _st(s)
    assert st["ertalab"]["holat"] == "xato" and "FloodWait" in st["ertalab"]["xato"]
    caption, _png, kb = s.rasmlar[-1]
    assert "Anvar akaga yuborilmadi" in caption
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"wow:qayta:{SANA}:ertalab"
    s.userbot_xato = None
    assert wk.callback(_cq(f"wow:qayta:{SANA}:ertalab")) == "wow-qayta-yuborildi"
    assert _st(s)["ertalab"]["holat"] == "yuborildi" and len(s.yuborildi) == 1


def test_avto_yuborish_jimlikdan_keyin(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    _qoralama(s)
    s.vaqt = s.vaqt + timedelta(minutes=14)
    assert wk.avto_job(now=s.vaqt) == []
    s.vaqt = s.vaqt + timedelta(minutes=2)
    assert wk.avto_job(now=s.vaqt) == [(SANA, "ertalab", "yuborildi")]
    assert len(s.yuborildi) == 1
    assert "(avtomatik)" in [p for m, p in s.calls if m == "editMessageCaption"][-1]["caption"]


def test_avto_yangi_xabar_ishlanayotganda_va_ochiq_bolsa_kutadi(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    _qoralama(s)
    with wk._LOCK:
        st = _st(s)
        st["ertalab"]["ishlanmoqda"] = (s.vaqt + timedelta(minutes=15)).isoformat()
        wk.saqla(st)
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=16)) == []
    wk.buyruq("/kunlik avto off")
    st = _st(s)
    st["ertalab"]["ishlanmoqda"] = None
    wk.saqla(st)
    assert wk.avto_job(now=s.vaqt + timedelta(hours=2)) == []
    assert not s.yuborildi


def test_avto_boshliqsiz_ishlamaydi(s):
    _qoralama(s)
    assert wk.avto_job(now=s.vaqt + timedelta(hours=1)) == []


def test_boshliq_keyin_belgilansa_eski_qoralama_darhol_ketmaydi(s):
    _qoralama(s)
    s.vaqt = s.vaqt + timedelta(minutes=40)                  # qoralama 40 daqiqa oldin tuzilgan
    wk.buyruq("/boshliq @test_boss Anvar aka")
    assert "15 daqiqadan keyin avtomatik" in s.matnlar()[-1]
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=1)) == []
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=15)) == [(SANA, "ertalab", "yuborildi")]


def test_kechki_qoralama_yarim_tundan_keyin_ham_ketadi(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    s.vaqt = datetime(2026, 11, 23, 23, 55, tzinfo=TZ)
    s.claude = {"savol": False, "jadval": [{"ish": "Hisobot", "holat": "bajarildi"}]}
    wk.sorov("kechqurun", qolda=True)
    wk.xabarni_ishlash(_msg("hisobot qildim"), "kechqurun")
    keyin = datetime(2026, 11, 24, 0, 11, tzinfo=TZ)
    assert wk.avto_job(now=keyin) == [(SANA, "kechqurun", "yuborildi")]


# ---------------- kechqurun ----------------

def _ertalab_yuborilgan(s):
    wk.buyruq("/boshliq @test_boss Anvar aka")
    _qoralama(s)
    wk.callback(_cq(f"wow:ok:{SANA}:ertalab"))
    s.vaqt = s.vaqt.replace(hour=19)


def test_kechki_sorovda_reja_va_hammasi_tugmasi(s):
    _ertalab_yuborilgan(s)
    assert wk.sorov("kechqurun") == "sent"
    matn = s.matnlar()[-1]
    assert "Ertalabki rejangiz" in matn and "1. Livardi: kontent-reja tasdiqlash" in matn
    kb = [p for m, p in s.calls if m == "sendMessage"][-1]["reply_markup"]
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"wow:hammasi:{SANA}:kechqurun"
    assert wk.callback(_cq(f"wow:hammasi:{SANA}:kechqurun")) == "wow-hammasi"
    st = _st(s)
    assert st["kechqurun"]["holat"] == "qoralama"
    assert {r["holat"] for r in st["kechqurun"]["jadval"]} == {"bajarildi"}
    assert "Kunlik hisobot" in s.rasmlar[-1][0]


def test_kechki_javob_reja_bilan_claudega_boradi(s):
    _ertalab_yuborilgan(s)
    wk.sorov("kechqurun")
    s.claude = {"savol": False, "jadval": [
        {"ish": "Livardi: kontent-reja tasdiqlash", "holat": "✅"},
        {"ish": "Orzu: reels TZ berish", "holat": "qisman bajarildi"},
        {"ish": "Undiruv: 3 mijozga qo'ng'iroq", "holat": "Bajarilmadi"},
        {"ish": "Yangi mijoz bilan uchrashuv", "holat": "bajarildi"}]}
    assert wk.xabarni_ishlash(_msg("Livardi bo'ldi, Orzu qisman..."), "kechqurun")[0] == "ok"
    assert len(s.claude_args[-1]["reja"]) == 3
    holatlar = [r["holat"] for r in _st(s)["kechqurun"]["jadval"]]
    assert holatlar == ["bajarildi", "jarayonda", "bajarilmadi", "bajarildi"]
    assert wk.callback(_cq(f"wow:ok:{SANA}:kechqurun")) == "wow-ok-yuborildi"
    caption = s.yuborildi[-1][2]
    assert caption.startswith("Kunlik hisobot — 23.11.2026, dushanba\nBajarildi: 2 · Jarayonda: 1")
    assert "2. ⏳ Orzu: reels TZ berish" in caption


def test_ertalab_javobsiz_qolsa_kechqurun_otkazildi(s):
    wk.sorov("ertalab")
    s.vaqt = s.vaqt.replace(hour=19)
    assert wk.sorov("kechqurun") == "sent"
    st = _st(s)
    assert st["ertalab"]["holat"] == "otkazildi" and st["faol"] == "kechqurun"
    assert "Qilgan ishlaringizni" in s.matnlar()[-1]


def test_yuborilgandan_keyin_soatlik_sorov_jim(s):
    _ertalab_yuborilgan(s)
    n = len(s.calls)
    s.vaqt = s.vaqt.replace(hour=10)
    assert wk.sorov("ertalab") == "done"
    assert len(s.calls) == n


# ---------------- dam, buyruqlar, qayta ----------------

def test_dam_tugmasi_va_qolda_boshlash(s):
    wk.sorov("ertalab")
    assert wk.callback(_cq(f"wow:dam:{SANA}:ertalab")) == "wow-dam"
    st = _st(s)
    assert st["dam"] and st["ertalab"]["holat"] == "dam" and st["kechqurun"]["holat"] == "dam"
    s.vaqt = s.vaqt.replace(hour=19)
    assert wk.sorov("kechqurun") == "off"
    assert wk.ushlaydimi(_msg("Livardi")) is None
    assert wk.buyruq("/kechqurun") == "wow-kechqurun-sent"        # qo'lda — dam bo'lsa ham
    assert wk.ushlaydimi(_msg("Livardi")) == "kechqurun"


def test_qayta_ochish_yangilangan_versiya(s):
    _ertalab_yuborilgan(s)
    s.vaqt = s.vaqt.replace(hour=14)
    assert wk.buyruq("/ertalab") == "wow-ertalab-done"
    assert "Yangilash: /ertalab qayta" in s.matnlar()[-1]
    assert wk.buyruq("/ertalab qayta") == "wow-ertalab-qayta"
    st = _st(s)
    assert st["ertalab"]["holat"] == "qoralama" and st["ertalab"]["yangilangan"]
    assert wk.callback(_cq(f"wow:ok:{SANA}:ertalab")) == "wow-ok-yuborildi"
    assert s.yuborildi[-1][2].startswith("Kunlik reja (yangilangan) — ")


def test_buyruqlar_parse(s):
    assert wk.buyruq("/dashboard") is None
    assert wk.buyruq("/hisobot") is None
    assert wk.buyruq("/boshliq anvar") == "wow-boshliq-xato"
    assert wk.buyruq("/boshliq me") == "wow-boshliq"
    assert wk.sozlama()["boshliq"] == "me" and wk.sozlama()["boshliq_nomi"] == "Saved Messages"
    assert wk.buyruq("/kunlik avto off") == "wow-avto" and wk.sozlama()["avto_daq"] == 0
    assert wk.buyruq("/kunlik avto 5") == "wow-avto" and wk.sozlama()["avto_daq"] == 5
    assert wk.buyruq("/kunlik off") == "wow-yoqish" and wk.sozlama()["yoqilgan"] is False
    assert wk.sorov("ertalab") == "off"
    assert wk.buyruq("/kunlik on") == "wow-yoqish"
    assert wk.buyruq("/kunlik@AbbaSheetsMonitorBot") == "wow-holat"
    assert "kunlik reja va hisobot" in s.matnlar()[-1]
    assert wk.buyruq("/kunlik", _msg()) == "wow-holat"
    assert wk.sozlama()["ism"] == "Ismoilxon"


def test_eski_yoki_buzuq_tugma(s):
    assert wk.callback(_cq("wow:ok:bad:ertalab")) == "wow-cb-yaroqsiz"
    assert wk.callback(_cq(f"wow:ok:{SANA}:tushlik")) == "wow-cb-yaroqsiz"
    assert wk.callback({"id": "x", "data": "boshqa:1"}) is None


def test_bekor_qoralamani_tozalaydi_ushlash_davom_etadi(s):
    _qoralama(s)
    assert wk.callback(_cq(f"wow:bekor:{SANA}:ertalab")) == "wow-bekor"
    st = _st(s)
    assert st["ertalab"]["holat"] == "kutilmoqda" and st["ertalab"]["jadval"] == []
    assert wk.ushlaydimi(_msg("yangi reja")) == "ertalab"


# ---------------- ovoz ----------------

def test_ovoz_transkript_jadvalga(s, monkeypatch):
    import design
    import stt

    monkeypatch.setattr(stt, "stt_ready", lambda: (True, ""))
    monkeypatch.setattr(stt, "transcribe", lambda p: "bugun livardi reja keyin gili tezet")

    def _dl(token, file_id, name):
        p = wk.DIR / "v.ogg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"ogg")
        return p

    monkeypatch.setattr(design, "download", _dl)
    wk.sorov("ertalab")
    s.claude = REJA
    r = wk.xabarni_ishlash(_msg(voice={"file_id": "v", "duration": 30}), "ertalab")
    assert r == ("ok", "bugun livardi reja keyin gili tezet")
    assert s.claude_args[-1]["tur"] == "ovoz"
    assert any("Eshitdim" in (p.get("text") or "") for m, p in s.calls if m == "editMessageText")
    assert not (wk.DIR / "v.ogg").exists()                      # ovoz fayli o'chirildi
    assert _st(s)["ertalab"]["kirishlar"][-1]["tur"] == "ovoz"


def test_ovoz_stt_tayyor_emas(s, monkeypatch):
    import stt

    monkeypatch.setattr(stt, "stt_ready", lambda: (False, "model yo'q"))
    wk.sorov("ertalab")
    assert wk.xabarni_ishlash(_msg(voice={"file_id": "v", "duration": 30}), "ertalab") == ("xato", "")
    assert "matn bilan yozing" in s.matnlar()[-1]
    assert _st(s)["ertalab"]["holat"] == "kutilmoqda"


def test_ovoz_juda_uzun(s):
    wk.sorov("ertalab")
    assert wk.xabarni_ishlash(_msg(voice={"file_id": "v", "duration": 400}), "ertalab")[0] == "xato"
    assert "bo'lib yuboring" in s.matnlar()[-1]


# ---------------- boot ----------------

def test_boot_uzilgan_yuborish_va_otib_ketgan_sorov(s):
    st = wk.yukla(SANA)
    st["kechqurun"]["holat"] = "yuborilmoqda"
    wk.saqla(st)
    s.vaqt = s.vaqt.replace(hour=10, minute=20)
    assert wk.boot(now=s.vaqt) == "sent"
    st = _st(s)
    assert st["kechqurun"]["holat"] == "xato" and st["ertalab"]["holat"] == "kutilmoqda"
    # ikkinchi restart — takror so'ramaydi
    assert wk.boot(now=s.vaqt) is None


def test_boot_tushda_sorov_yoq(s):
    s.vaqt = s.vaqt.replace(hour=15)
    assert wk.boot(now=s.vaqt) is None
    assert not s.calls


# ---------------- sof funksiyalar ----------------

def test_json_ol_va_tekshir():
    raw = '```json\n{"savol": false, "jadval": ["Livardi", {"ish": "  Orzu  TZ ", "holat": "✅"},' \
          ' {"ish": ""}, 5]}\n```'
    d = wk.tekshir(wk.json_ol(raw), "kechqurun")
    assert d["jadval"] == [{"ish": "Livardi", "izoh": "", "holat": ""},
                           {"ish": "Orzu TZ", "izoh": "", "holat": "bajarildi"}]
    assert wk.tekshir({"jadval": [{"ish": "x", "holat": "bajarildi"}]}, "ertalab")["jadval"][0][
        "holat"] == ""
    assert len(wk.tekshir({"jadval": [f"ish {i}" for i in range(50)]}, "ertalab")["jadval"]) == 30
    with pytest.raises(ValueError):
        wk.json_ol("JSON yo'q")


@pytest.mark.parametrize("kirish,kutilgan", [
    ("Bajarilmadi", "bajarilmadi"), ("bajarildi", "bajarildi"), ("✅", "bajarildi"),
    ("qisman bajarildi", "jarayonda"), ("Ertaga qoldirildi", "ertaga"), ("", ""),
    ("noma'lum", ""), ("bo‘lmadi", "bajarilmadi"),
])
def test_holat_norm(kirish, kutilgan):
    assert wk.holat_norm(kirish) == kutilgan


def test_ga_qoshimchasi():
    assert wk._ga("Anvar aka") == "Anvar akaga"
    assert wk._ga("Bek") == "Bekka"
    assert wk._ga("Farrux") == "Farruxga"
    assert wk._ga("O'rtoq") == "O'rtoqqa"


def test_prompt_bir_otishda_foydalanuvchi_matni_almashtirilmaydi():
    p = wk._prompt("reja", [], [], ["Livardi"], "matnda {{NOMLAR}} bor", "matn", SANA)
    assert "matnda {{NOMLAR}} bor" in p and "Livardi" in p and "{{KIRITMA}}" not in p


def test_boshliq_caption_1024_dan_oshmaydi():
    jadval = [{"ish": f"Juda uzun vazifa nomi raqam {i} " + "x" * 60, "izoh": "izoh",
               "holat": "bajarildi"} for i in range(30)]
    c = wk.boshliq_caption(SANA, "kechqurun", jadval)
    assert len(c) <= 1024 and c.endswith("to'liq ro'yxat rasmda")


def test_malum_nomlar_snapshotdan(tmp_path, monkeypatch):
    monkeypatch.setattr(wk, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(wk, "_NOMLAR_KESH", {"t": 0.0, "nomlar": []})
    kun = tmp_path / "2026-11-22"
    kun.mkdir()
    (kun / "a.json").write_text(json.dumps({"name": "SMM proektlar", "ranges": {
        "'Smm main'!A1:BZ1000": [["", ""], ["Proektlar nomi", "Ish xolati"],
                                 ["Eski loyiha", "Yakunlangan"], ["Livardi", "Aktiv"],
                                 ["livardi", "aktiv"], ["", ""]]}}), encoding="utf-8")
    (kun / "b.json").write_text(json.dumps({"name": "Zubair PM KPI", "ranges": {}}),
                                encoding="utf-8")
    assert wk.malum_nomlar() == ["Zubair", "Livardi", "Eski loyiha"]


def test_jadval_png_uzun_soz_va_izohsiz():
    import wow_jadval

    png = wow_jadval.chiz("Kunlik reja", "Ismoilxon · 23.11.2026, dushanba",
                          [{"ish": "a" * 400, "izoh": "", "holat": ""},
                           {"ish": "Oʻzbekcha gʻ, qo‘ng‘iroq, Приём — кириллица", "izoh": ""}])
    assert png.startswith(b"\x89PNG") and len(png) > 1000
    assert wow_jadval.xulosa_matn([{"holat": "bajarildi"}, {"holat": ""}], True) == \
        "Bajarildi: 1 · Holati aytilmagan: 1 · Jami: 2"


# ---------------- bot_listener bilan birga ----------------

def test_bot_listener_kunlik_xabar_va_savol(s, monkeypatch):
    import bot_listener as bl

    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    monkeypatch.setattr(bl.design, "load_pending", lambda: None)
    savollar = []
    monkeypatch.setattr(bl, "do_question", lambda q: savollar.append(q))
    wk.sorov("ertalab")
    s.claude = REJA
    assert bl.handle_update({"update_id": 1, "message": _msg("Livardi reja, Orzu TZ")}) == "wow-ok"
    assert not savollar
    s.claude = {"savol": True, "jadval": []}
    assert bl.handle_update({"update_id": 2, "message": _msg("undiruv qancha?")}) == "wow-savol"
    assert savollar == ["undiruv qancha?"]


def test_bot_listener_callback_faqat_egasidan(s, monkeypatch):
    import bot_listener as bl

    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    monkeypatch.setattr(bl, "api", lambda *a, **k: None)
    chaqirildi = []
    monkeypatch.setattr(wk, "callback", lambda cq: chaqirildi.append(cq) or "wow-ok-x")
    begona = {"id": "c", "data": f"wow:ok:{SANA}:ertalab", "from": {"id": 999},
              "message": {"message_id": 1, "chat": {"id": 555}}}
    assert bl.handle_update({"update_id": 3, "callback_query": begona}) == "cb-ignored"
    boshqa_chat = {**begona, "from": {"id": 555}, "message": {"message_id": 1, "chat": {"id": 7}}}
    assert bl.handle_update({"update_id": 4, "callback_query": boshqa_chat}) == "cb-ignored"
    assert not chaqirildi
    egasi = {**begona, "from": {"id": 555}}
    assert bl.handle_update({"update_id": 5, "callback_query": egasi}) == "wow-ok-x"


def test_bot_listener_wow_buyruqlari(s, monkeypatch):
    import bot_listener as bl
    import chat_log

    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    monkeypatch.setattr(bl.design, "load_pending", lambda: None)
    monkeypatch.setattr(chat_log, "append_cmd", lambda *a: None)
    assert bl.handle_update({"update_id": 6, "message": _msg("/kunlik")}) == "wow-holat"
    assert bl.handle_update({"update_id": 7, "message": _msg("/ertalab")}) == "wow-ertalab-sent"
    assert "WOW ai" in bl.HELP and "/kunlik" in bl.HELP
