"""Bitta bot — ikki servis: abba-hisobotlar/yordamchi shu botdan kartalar yuboradi, egasining «/y_…»
buyruqlari va «#Y12» kartalariga reply'larini o'z sessiyasi orqali o'qiydi. Sheets agenti ularga javob
bermasligi kerak (aks holda «Bunday buyruq yo'q» yoki savol javobi ketadi).

pytest tests/test_yordamchi_birga.py — tarmoq/kredensial kerak emas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot_listener as bl  # noqa: E402


def _upd(text, **extra):
    return {"update_id": 1, "message": {"chat": {"id": 555}, "from": {"id": 555}, "text": text, **extra}}


def _portlash(*_a, **_k):
    raise AssertionError("yordamchi xabariga Sheets agenti javob berdi")


def test_yordamchi_buyrugi_va_kartaga_reply_otkaziladi(monkeypatch):
    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    for nom in ("send_retry", "do_question", "handle_voice", "handle_media", "do_hisobot"):
        monkeypatch.setattr(bl, nom, _portlash)
    monkeypatch.setattr(bl.design, "load_pending", lambda: None)
    assert bl.handle_update(_upd("/y_ok12_3fa9")) == "yordamchi"
    assert bl.handle_update(_upd("/Y_NAVBAT")) == "yordamchi"
    assert bl.handle_update(_upd("qisqaroq qilib yoz", reply_to_message={"text": "🟡 Orient  #Y12\n✍️ Qoralama"})) \
        == "yordamchi"
    assert bl.handle_update(_upd("", voice={"file_id": "v"}, reply_to_message={"text": "✏️ Tahrir #Y7"})) \
        == "yordamchi"


def test_sheets_buyruq_va_savollari_oz_joyida():
    assert not bl.yordamchi_xabari({"text": "/yangi"})
    assert not bl.yordamchi_xabari({"text": "Zubairda Livardi loyihasi bormi?"})
    assert not bl.yordamchi_xabari({"text": "batafsil", "reply_to_message": {"text": "📊 Hisobot #12"}})
    assert not bl.yordamchi_xabari({"text": "/hisobot"})


def test_begona_yordamchi_buyrugi_ham_ruxsatsiz(monkeypatch):
    """Xavfsizlik tartibi o'zgarmaydi: egasi bo'lmagan odamning «/y_» xabari — ruxsatsiz oqimi."""
    monkeypatch.setattr(bl, "CHAT_ID", "-100123")
    monkeypatch.setenv("TELEGRAM_OWNER_IDS", "777")
    monkeypatch.setattr(bl, "send_retry", lambda *a, **k: True)
    bl._RUXSATSIZ_OGOH.clear()
    assert bl.handle_update({"update_id": 1, "message": {"chat": {"id": -100123}, "from": {"id": 999},
                                                         "text": "/y_ok1_ab"}}) == "unauthorized"
