"""Bitta bot — ikki servis: abba-hisobotlar/yordamchi shu botdan kartalar yuboradi, egasining «/y_…»
buyruqlari va «🔖Y12» kartalariga matnli reply'larini o'z sessiyasi orqali o'qiydi. Sheets agenti ularga
javob bermasligi kerak (aks holda «Bunday buyruq yo'q» yoki savol javobi ketadi). Ovoz/rasm va boshqa
«/» buyruqlar — reply bo'lsa ham — Sheets agentiniki (yordamchi ularga tegmaydi, yo'qolmasin).

pytest tests/test_yordamchi_birga.py — tarmoq/kredensial kerak emas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot_listener as bl  # noqa: E402

KARTA = {"text": "🟡 Orient cavier  🔖Y12\n✍️ Qoralama: Assalomu alaykum"}


def _upd(text=None, **extra):
    msg = {"chat": {"id": 555}, "from": {"id": 555}, **extra}
    if text is not None:
        msg["text"] = text
    return {"update_id": 1, "message": msg}


def _portlash(*_a, **_k):
    raise AssertionError("yordamchi xabariga Sheets agenti javob berdi")


def _egasi(monkeypatch):
    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    monkeypatch.setattr(bl.design, "load_pending", lambda: None)


def test_yordamchi_buyrugi_va_kartaga_matnli_reply_otkaziladi(monkeypatch):
    _egasi(monkeypatch)
    for nom in ("send_retry", "do_question", "handle_voice", "handle_media", "do_hisobot"):
        monkeypatch.setattr(bl, nom, _portlash)
    assert bl.handle_update(_upd("/y_ok12_3fa9")) == "yordamchi"
    assert bl.handle_update(_upd("/Y_NAVBAT")) == "yordamchi"
    assert bl.handle_update(_upd("qisqaroq qilib yoz", reply_to_message=KARTA)) == "yordamchi"
    assert bl.handle_update(_upd("Ertaga 15:00 da", reply_to_message={"text": "✏️ Tahrir 🔖Y7: matnni yozing"})) \
        == "yordamchi"


def test_kartaga_ovoz_rasm_va_boshqa_buyruq_sheetsniki(monkeypatch):
    """Yordamchi ularga tegmaydi — Sheets ham tashlab yubormasin (aks holda xabar yo'qoladi)."""
    _egasi(monkeypatch)
    monkeypatch.setattr(bl, "handle_voice", lambda msg: "voice")
    monkeypatch.setattr(bl, "handle_media", lambda msg: "media")
    monkeypatch.setattr(bl, "do_hisobot", lambda: None)
    import chat_log
    monkeypatch.setattr(chat_log, "append_cmd", lambda *a: None)
    assert bl.handle_update(_upd(voice={"file_id": "v"}, reply_to_message=KARTA)) == "voice"
    assert bl.handle_update(_upd(caption="shu bo'yicha", photo=[{"file_id": "p"}], reply_to_message=KARTA)) == "media"
    assert bl.handle_update(_upd("/hisobot", reply_to_message=KARTA)) == "hisobot"


def test_sheets_buyruq_va_savollari_oz_joyida():
    assert not bl.yordamchi_xabari({"text": "/yangi"})
    assert not bl.yordamchi_xabari({"text": "Zubairda Livardi loyihasi bormi?"})
    assert not bl.yordamchi_xabari({"text": "batafsil", "reply_to_message": {"text": "📊 Hisobot #Y2026 #12"}})
    assert not bl.yordamchi_xabari({"text": "nega?", "reply_to_message": {"text": bl.HELP}})
    assert not bl.yordamchi_xabari({"text": "/hisobot"})


def test_begona_yordamchi_buyrugi_ham_ruxsatsiz(monkeypatch):
    """Xavfsizlik tartibi o'zgarmaydi: egasi bo'lmagan odamning «/y_» xabari — ruxsatsiz oqimi."""
    monkeypatch.setattr(bl, "CHAT_ID", "-100123")
    monkeypatch.setenv("TELEGRAM_OWNER_IDS", "777")
    monkeypatch.setattr(bl, "send_retry", lambda *a, **k: True)
    bl._RUXSATSIZ_OGOH.clear()
    assert bl.handle_update({"update_id": 1, "message": {"chat": {"id": -100123}, "from": {"id": 999},
                                                         "text": "/y_ok1_ab"}}) == "unauthorized"
