"""Vazifa navbati (vazifa.py): qo'shish, ertalabki so'rov, ✅ Ha / ⏳ Keyinroq, kunlik reja bilan
bog'lanish, kechki yakun, /vazifalar va «faqat obuna» (analyze.claude_env).

Tarmoq, Claude, STT va userbot soxta; nomlar — joy egalari (repo public).
pytest tests/test_vazifa.py
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyze  # noqa: E402
import vazifa as vz  # noqa: E402
import wow_kunlik as wk  # noqa: E402

TZ = ZoneInfo("Asia/Tashkent")
SANA = "2026-11-30"


class Crash(BaseException):
    """Jarayon uzilishi (deploy/restart) — except Exception ushlamaydi."""


class Soxta:
    """Telegram (bot) + userbot + Claude (kunlik jadval va navbat) soxtalari."""

    def __init__(self):
        self.mid = 100
        self.calls = []          # (method, payload)
        self.rasmlar = []        # (caption, kb)
        self.yuborildi = []      # userbot: (to, caption)
        self.wow_claude = None   # kunlik jadval: dict | callable(joriy, kiritma) | Exception
        self.wow_args = []
        self.ajrat = None        # navbat Claude'i: JSON matn | BaseException
        self.ajrat_prompt = []
        self.arxiv = []
        self.xato_matn = None    # shu bo'lak bor sendMessage yetib bormaydi (None)

    def keyingi(self):
        self.mid += 1
        return self.mid

    def api(self, method, payload):
        self.calls.append((method, payload))
        if method == "sendMessage":
            if self.xato_matn and self.xato_matn in (payload.get("text") or ""):
                return None
            return {"message_id": self.keyingi()}
        return True

    def rasm(self, png, caption, kb=None):
        self.rasmlar.append((caption, kb))
        return self.keyingi()

    def send_photo(self, to, path, caption=""):
        self.yuborildi.append((to, caption))

    def jadval_yangila(self, slot, joriy, kiritma, tur, reja=None, nomlar=None, sana=""):
        self.wow_args.append({"slot": slot, "joriy": [dict(r) for r in joriy], "kiritma": kiritma,
                              "reja": [dict(r) for r in reja or []]})
        natija = self.wow_claude
        if isinstance(natija, BaseException):
            raise natija
        if callable(natija):
            natija = natija(joriy, kiritma)
        return wk.tekshir(natija, slot)

    def claude(self, prompt):
        self.ajrat_prompt.append(prompt)
        if isinstance(self.ajrat, BaseException):
            raise self.ajrat
        return self.ajrat

    def matnlar(self, method="sendMessage"):
        return [p.get("text") or p.get("caption") or "" for m, p in self.calls if m == method]

    def tahrirlar(self):
        return [p for m, p in self.calls if m == "editMessageText"]

    def tugmalar(self, calls=None):
        out = []
        for m, p in (self.calls if calls is None else calls):
            for qator in (p.get("reply_markup") or {}).get("inline_keyboard") or []:
                out += [b["callback_data"] for b in qator]
        return out


@pytest.fixture
def s(monkeypatch, tmp_path):
    sx = Soxta()
    monkeypatch.setattr(wk, "DIR", tmp_path / "wow")
    monkeypatch.setattr(wk, "SNAPSHOTS", tmp_path / "snap")
    monkeypatch.setattr(wk, "_api", sx.api)
    monkeypatch.setattr(wk, "rasm", sx.rasm)
    monkeypatch.setattr(wk, "rasm_png", lambda *a, **k: b"\x89PNG-soxta")
    monkeypatch.setattr(wk, "jadval_yangila", sx.jadval_yangila)
    monkeypatch.setattr(wk, "malum_nomlar", lambda limit=150: ["Alfa", "Beta"])
    monkeypatch.setattr(vz, "_claude", sx.claude)
    import chat_log
    import userbot_sender

    monkeypatch.setattr(userbot_sender, "send_photo", sx.send_photo)
    monkeypatch.setattr(chat_log, "append_cmd", lambda label, now=None: sx.arxiv.append(label))
    sx.vaqt = datetime(2026, 11, 30, 9, 0, tzinfo=TZ)
    monkeypatch.setattr(wk, "hozir", lambda: sx.vaqt)
    monkeypatch.setattr(wk, "_NOM_KESH", {"t": 0.0, "nom": ""})
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)     # bot_nomi() tarmoqqa chiqmasin
    sx.tmp = tmp_path
    return sx


def _bl(monkeypatch, s):
    """bot_listener: egasi chati, log va javoblar tmp/soxta (repo ichiga yozilmasin)."""
    import bot_listener as bl

    monkeypatch.setattr(bl, "CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_OWNER_IDS", raising=False)
    monkeypatch.setattr(bl.design, "load_pending", lambda: None)
    monkeypatch.setattr(bl, "LOGS", s.tmp / "logs")
    monkeypatch.setattr(bl, "api", lambda *a, **k: None)
    s.bl_javob = []
    monkeypatch.setattr(bl, "send_retry", lambda t, **k: s.bl_javob.append(t) or True)
    return bl


def _msg(text=None, mid=None, **extra):
    m = {"chat": {"id": 555}, "from": {"id": 555, "first_name": "Sinov"}, **extra}
    if mid is not None:
        m["message_id"] = mid
    if text is not None:
        m["text"] = text
    return m


def _cq(data, mid=999):
    return {"id": "cb1", "data": data, "from": {"id": 555},
            "message": {"message_id": mid, "chat": {"id": 555}}}


def _bandlar(*matnlar, izoh=""):
    return json.dumps({"bandlar": [{"matn": m, "tur": "savol" if m.endswith("?") else "ish"}
                                   for m in matnlar], "izoh": izoh}, ensure_ascii=False)


def _yukla():
    with wk._LOCK:
        return vz._yukla()


def _items(holat=None):
    return [it for it in _yukla()["items"] if holat is None or it["holat"] == holat]


def _bir(matn):
    return next(it for it in _yukla()["items"] if it["matn"] == matn)


def _qosh(s, *matnlar, mid=None):
    s.ajrat = _bandlar(*matnlar)
    return vz.buyruq("/vazifa " + "; ".join(matnlar), _msg(mid=mid))


def _boshliq():
    wk.sozlama_saqla(boshliq="me", boshliq_nomi="Saved Messages")


def _rejani_yoz(s, jadval, slot="ertalab"):
    s.wow_claude = {"savol": False, "jadval": [r if isinstance(r, dict) else {"ish": r}
                                               for r in jadval]}
    assert wk.xabarni_ishlash(_msg("reja"), slot)[0] == "ok"


def _qatorlar(slot="ertalab", sana=SANA):
    return [r["ish"] for r in wk.yukla(sana)[slot]["jadval"]]


def _ha(iid, mid=999):
    return vz.callback(_cq(f"vz:ha:{iid}", mid=mid))


# ---------------- qo'shish ----------------

def test_vazifa_matni_bandlarga_ajraladi_va_izoh_korsatiladi(s):
    s.ajrat = _bandlar("Alfa: TZ yozish", "Beta: narx kerakmi?", izoh="2-banddagi nom noaniq")
    assert vz.buyruq("/vazifa alfa tz yozish, beta narxi kerakmi", _msg(mid=11)) == "vazifa-qoshildi"
    its = _items("navbatda")
    assert [(i["matn"], i["tur"]) for i in its] == [("Alfa: TZ yozish", "ish"),
                                                    ("Beta: narx kerakmi?", "savol")]
    assert its[1]["toplam"] == its[0]["id"] and its[0]["src"] == "555:11"
    p = s.ajrat_prompt[-1]
    assert "alfa tz yozish, beta narxi kerakmi" in p and "Alfa, Beta" in p and "ISHONCHSIZ" in p
    t = s.tahrirlar()[-1]                                     # «yozyapman…» xabari natijaga aylandi
    assert "Navbatga qo'shildi" in t["text"] and "2 ta" in t["text"]
    assert "ℹ️ 2-banddagi nom noaniq" in t["text"]
    assert t["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"vz:qaytar:{its[0]['id']}"
    assert s.arxiv and "Alfa: TZ yozish" in s.arxiv[-1]       # ikkinchi miyaga bir qator


def test_takror_xabar_va_bir_xil_ish_qoshilmaydi(s):
    _qosh(s, "Alfa: TZ yozish", mid=12)
    assert vz.buyruq("/vazifa Alfa TZ yozish", _msg(mid=12)) == "vazifa-takror"   # restart replay
    assert vz.buyruq("/vazifa Alfa TZ yozish", _msg(mid=13)) == "vazifa-bor"      # yana bir marta
    assert len(_items()) == 1 and "allaqachon bor" in s.tahrirlar()[-1]["text"]
    s.ajrat = _bandlar("Alfa: 1-post", "Alfa: 2-post", "Beta: TZ yozish")         # boshqa ishlar
    assert vz.buyruq("/vazifa x", _msg(mid=14)) == "vazifa-qoshildi"
    assert len(_items()) == 4


def test_claude_ishlamasa_zaxira_va_limit_aytiladi(s):
    s.ajrat = RuntimeError("claude -p xato (kod 1): You've hit your weekly limit · resets Nov 28 at 7pm")
    assert vz.buyruq("/vazifa Alfa TZ\nBeta narx kerakmi?", _msg(mid=14)) == "vazifa-qoshildi"
    assert [(i["matn"], i["tur"]) for i in _items()] == [("Alfa TZ", "ish"),
                                                         ("Beta narx kerakmi?", "savol")]
    t = s.tahrirlar()[-1]["text"]
    assert "obuna limiti tugagan" in t and "Nov 28 at 7pm" in t


def test_uzun_tasdiq_telegram_chegarasidan_oshmaydi(s):
    s.ajrat = RuntimeError("tarmoq")
    uzun = "\n".join(f"Ish {i}: " + "a" * 180 for i in range(20))
    assert vz.buyruq("/vazifa " + uzun, _msg(mid=15)) == "vazifa-qoshildi"
    t = s.tahrirlar()[-1]
    assert len(_items()) == 20 and len(t["text"]) < 4096 and "… yana" in t["text"]
    assert t["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("vz:qaytar:")


def test_ish_topilmasa_hech_narsa_yozilmaydi(s):
    s.ajrat = _bandlar()
    assert vz.buyruq("/vazifa salom", _msg(mid=16)) == "vazifa-topilmadi"
    assert not _items()


# ---------------- «/vazifa» kutishi ----------------

def test_kutish_keyingi_xabar_kunlik_oynada_ham_navbatga(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    wk.sorov("ertalab")                         # kunlik so'rov ochiq — matn odatda rejaga tushardi
    assert bl.handle_update({"update_id": 1, "message": _msg("/vazifa", mid=20)}) == "vazifa-kutish"
    s.ajrat = _bandlar("Alfa: dizayn")
    assert bl.handle_update({"update_id": 2, "message": _msg("alfa dizayn", mid=21)}) == \
        "vazifa-qoshildi"
    assert [i["matn"] for i in _items()] == ["Alfa: dizayn"] and not s.wow_args
    s.wow_claude = {"savol": False, "jadval": [{"ish": "Beta: post"}]}   # kutish bir martalik
    assert bl.handle_update({"update_id": 3, "message": _msg("beta post", mid=22)}) == "wow-ok"


def test_kutish_xabari_restartda_qayta_ishlansa_navbatga_qaytadi(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    wk.sorov("ertalab")
    bl.handle_update({"update_id": 1, "message": _msg("/vazifa", mid=20)})
    upd = {"update_id": 2, "message": _msg("alfa dizayn", mid=21)}
    s.ajrat = Crash()                           # Claude kutilayotganda deploy/restart
    with pytest.raises(Crash):
        bl.handle_update(upd)
    s.ajrat = _bandlar("Alfa: dizayn")
    assert bl.handle_update(upd) == "vazifa-qoshildi"         # recover_inflight — yana navbatga
    assert bl.handle_update(upd) == "vazifa-takror"           # saqlangandan keyin — takrorsiz
    assert not s.wow_args and [i["matn"] for i in _items()] == ["Alfa: dizayn"]


def test_kutish_xatosi_boshqa_oqimga_sirpanmaydi(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    wk.sorov("ertalab")
    vz.buyruq("/vazifa", _msg(mid=30))
    monkeypatch.setattr(vz, "qoshish", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    assert bl.handle_update({"update_id": 3, "message": _msg("alfa", mid=31)}) == "vazifa-xato"
    assert not s.wow_args and "Navbatga yozib bo'lmadi" in s.bl_javob[-1]


def test_kutish_muddati_bekor_va_boshqa_buyruq(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    assert vz.buyruq("/vazifa", _msg(mid=40)) == "vazifa-kutish"
    assert vz.ushlaydimi(_msg("alfa")) and not vz.ushlaydimi(_msg("/vazifalar"))
    s.vaqt += timedelta(minutes=vz.KUTISH_DAQ + 1)
    assert not vz.ushlaydimi(_msg("alfa"))
    vz.buyruq("/vazifa", _msg(mid=41))
    assert vz.buyruq("/vazifa bekor", _msg(mid=42)) == "vazifa-kutish-bekor"
    assert not vz.ushlaydimi(_msg("alfa"))
    vz.buyruq("/vazifa", _msg(mid=43))                         # boshqa buyruq — kutish bekor
    bl.handle_update({"update_id": 4, "message": _msg("/kunlik", mid=44)})
    assert not vz.ushlaydimi(_msg("alfa"))
    vz.buyruq("/vazifa", _msg(mid=45))                         # matnli /vazifa — kutish bekor
    _qosh(s, "Alfa: TZ", mid=46)
    assert not vz.ushlaydimi(_msg("beta post"))
    vz.buyruq("/vazifa", _msg(mid=47))                         # yangi kunlik so'rov — bekor
    wk.sorov("ertalab")
    assert not vz.ushlaydimi(_msg("beta post"))


def test_kutish_kunlik_preview_ga_reply_ni_olmaydi(s):
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    preview = wk.yukla(SANA)["ertalab"]["preview_mid"]
    vz.buyruq("/vazifa", _msg(mid=50))
    assert not vz.ushlaydimi(_msg("2-ni o'chir", reply_to_message={"message_id": preview}))
    assert vz.ushlaydimi(_msg("gamma video"))


def test_kutish_ovoz_va_ovoz_oqilmasa_kutish_qoladi(s, monkeypatch):
    vz.buyruq("/vazifa", _msg(mid=33))
    ovoz = {"file_id": "f", "duration": 5}
    olindi = []
    monkeypatch.setattr(wk, "_ovozdan_matn", lambda v, **k: olindi.append(k) or None)
    assert vz.xabarni_ishlash(_msg(voice=ovoz, mid=34)) == "vazifa-ovoz-xato"
    assert "/vazifa" in olindi[-1]["uzun"]                     # uzun ovoz maslahati navbatniki
    assert vz.ushlaydimi(_msg(voice=ovoz, mid=35))             # qayta yuborsa bo'ladi
    monkeypatch.setattr(wk, "_ovozdan_matn", lambda v, **k: ("alfa tezet yozish", 77))
    s.ajrat = _bandlar("Alfa: TZ yozish")
    assert vz.xabarni_ishlash(_msg(voice=ovoz, mid=35)) == "vazifa-qoshildi"
    assert _items()[0]["manba"] == "ovoz" and "ovozli xabar transkripti" in s.ajrat_prompt[-1]
    assert not vz.ushlaydimi(_msg("alfa", mid=36))


def test_reply_eshitdim_ovoz_va_iqtibos(s, monkeypatch):
    s.ajrat = _bandlar("Alfa: TZ yozish")
    rep = {"message_id": 40, "text": "🎤 Eshitdim: «alfa tezet yozish»"}
    assert vz.buyruq("/vazifa", _msg(mid=41, reply_to_message=rep)) == "vazifa-qoshildi"
    p = s.ajrat_prompt[-1]
    assert "alfa tezet yozish" in p and "Eshitdim" not in p and "ovozli xabar transkripti" in p
    monkeypatch.setattr(wk, "_ovozdan_matn", lambda v, **k: ("beta post qilish", 78))
    s.ajrat = _bandlar("Beta: post")                         # ovozli xabarga reply — matnga o'giriladi
    assert vz.buyruq("/vazifa", _msg(mid=42, reply_to_message={"message_id": 9,
                                                               "voice": {"file_id": "v"}})) == \
        "vazifa-qoshildi"
    assert "beta post qilish" in s.ajrat_prompt[-1]
    s.ajrat = _bandlar("Gamma: video")                       # iqtibos — faqat belgilangan qism
    assert vz.buyruq("/vazifa", _msg(mid=43, quote={"text": "gamma video"},
                                     reply_to_message={"message_id": 10,
                                                       "text": "uzun javob. gamma video. boshqa"})) \
        == "vazifa-qoshildi"
    assert "gamma video" in s.ajrat_prompt[-1] and "uzun javob" not in s.ajrat_prompt[-1]


# ---------------- ertalabki so'rov ----------------

def test_ertalab_har_ish_alohida_kuniga_bir_marta(s):
    for i, m in enumerate(["Alfa: TZ", "Beta: post", "Gamma: video", "Delta: KP", "Eta: brif",
                           "Zeta: dogovor"]):
        _qosh(s, m, mid=50 + i)
    s.calls.clear()
    assert wk.sorov("ertalab") == "sent"
    matnlar = s.matnlar()
    assert "Bugun qanday ishlar qilasiz?" in matnlar[0]
    sorovlar = [t for t in matnlar if "Buni ham bugun qilasizmi?" in t]
    assert len(sorovlar) == vz.KUNIGA == 5
    assert "«Alfa: TZ»" in sorovlar[0] and "Navbatda yana 1 ta bor" in sorovlar[-1]
    data = s.tugmalar()
    assert {d.split(":")[1] for d in data if d.startswith("vz:")} == {"ha", "keyin"}
    assert all(len(d.encode()) <= 64 for d in data)
    s.calls.clear()
    s.vaqt = s.vaqt.replace(hour=10)                  # soatlik eslatma — navbat qayta so'ralmaydi
    wk.sorov("ertalab")
    assert not [t for t in s.matnlar() if "Buni ham" in t]


def test_soraldi_faqat_xabar_yetib_borsa(s):
    for i, m in enumerate(["Alfa: TZ", "Beta: post", "Gamma: video"]):
        _qosh(s, m, mid=60 + i)
    s.xato_matn = "«Beta: post»"
    wk.sorov("ertalab")
    assert _bir("Alfa: TZ")["soraldi"] == SANA and _bir("Gamma: video")["soraldi"] == SANA
    assert _bir("Beta: post")["soraldi"] is None      # ertaga birinchi bo'lib so'raladi


def test_ochiq_kunlik_va_dam_kuni_sorovsiz(s):
    _qosh(s, "Alfa: TZ", mid=60)
    wk.sozlama_saqla(yoqilgan=False)
    assert wk.sorov("ertalab") == "off"
    wk.sozlama_saqla(yoqilgan=True)
    with wk._LOCK:
        st = wk.yukla(SANA)
        st["dam"] = True
        wk.saqla(st)
    assert wk.sorov("ertalab") == "off"
    assert wk.sorov("kechqurun") == "off"
    assert not [t for t in s.matnlar() if "Buni ham" in t]


# ---------------- ✅ Ha ----------------

def test_ha_reja_yozilmagan_egasi_yozganda_qoshiladi(s):
    _qosh(s, "Alfa: TZ yozish", mid=70)
    wk.sorov("ertalab")
    iid = _items()[0]["id"]
    assert _ha(iid, mid=500) == "vz-ha-kutilmoqda"
    assert _items("bugun")[0]["sana"] == SANA and _items("bugun")[0]["olingan"] == SANA
    assert not s.rasmlar
    assert _ha(iid, mid=500) == "vz-ha-takror"                 # qayta bosish
    _rejani_yoz(s, ["Beta: post"])
    assert s.wow_args[-1]["joriy"] == []                       # Claude'ga berilmaydi
    assert _qatorlar() == ["Beta: post", "Alfa: TZ yozish"]
    assert "Navbatdan 1 ta ish qo'shildi" in s.rasmlar[-1][0]


def test_ha_dan_keyin_reja_bolmagan_xabar_qoralama_ochmaydi(s):
    _qosh(s, "Alfa: TZ yozish", mid=71)
    _boshliq()
    wk.sorov("ertalab")
    _ha(_items()[0]["id"])
    s.wow_claude = {"savol": False, "jadval": []}              # «hozir yozaman», «ok»
    assert wk.xabarni_ishlash(_msg("hozir yozaman"), "ertalab")[0] == "bosh"
    sl = wk.yukla(SANA)["ertalab"]
    assert sl["holat"] == "kutilmoqda" and not sl["jadval"]
    assert wk.avto_job(now=s.vaqt + timedelta(hours=1)) == []


def test_ha_qoralama_ochiq_qator_qoshiladi_va_sanoq_qaytadan(s):
    _qosh(s, "Alfa: TZ yozish", mid=80)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    oldin = len(s.rasmlar)
    s.vaqt += timedelta(minutes=10)
    assert _ha(_items()[0]["id"]) == "vz-ha-qoshildi"
    assert _qatorlar() == ["Beta: post", "Alfa: TZ yozish"]
    assert len(s.rasmlar) == oldin + 1 and "Navbatdan qo'shildi" in s.rasmlar[-1][0]
    # eski sanoq bo'yicha (+16 daqiqa) ketmaydi — egasi yangi rasmni ko'rib ulgursin
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=6)) == []
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=15)) == [(SANA, "ertalab", "yuborildi")]
    assert "Alfa: TZ yozish" in s.yuborildi[-1][1]


def test_ha_restartda_preview_qayta_yuboriladi(s, monkeypatch):
    _qosh(s, "Alfa: TZ yozish", mid=81)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    iid = _items()[0]["id"]
    asl, sanoq = wk.preview_yubor, {"n": 0}

    def preview(*a, **k):
        sanoq["n"] += 1
        if sanoq["n"] == 1:
            raise Crash()                                       # holat saqlandi, preview yetmadi
        return asl(*a, **k)

    monkeypatch.setattr(wk, "preview_yubor", preview)
    with pytest.raises(Crash):
        _ha(iid)
    assert wk.preview_eskirgan(SANA, "ertalab")
    n = len(s.rasmlar)
    assert _ha(iid) == "vz-ha-takror"                           # recover_inflight
    assert len(s.rasmlar) == n + 1 and not wk.preview_eskirgan(SANA, "ertalab")


def test_avto_korilmagan_jadvalni_yubormaydi_avval_preview(s):
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    with wk._LOCK:                                              # preview'siz o'zgarish (uzilish)
        assert wk.qator_qosh(SANA, "ertalab", ["Gamma: video"]) == "qoshildi"
    n = len(s.rasmlar)
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=16)) == [(SANA, "ertalab", "korilmagan")]
    assert not s.yuborildi and len(s.rasmlar) == n + 1
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=30)) == []        # sanoq qaytadan
    assert wk.avto_job(now=s.vaqt + timedelta(minutes=31)) == [(SANA, "ertalab", "yuborildi")]
    assert "Gamma: video" in s.yuborildi[-1][1]


def test_ha_reja_yuborilgan_faqat_tugma_bilan_qayta_ochiladi(s):
    _qosh(s, "Alfa: TZ yozish", mid=90)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    assert wk.yubor(SANA, "ertalab") == "yuborildi"
    n = len(s.yuborildi)
    iid = _items()[0]["id"]
    assert _ha(iid, mid=501) == "vz-ha-yuborildi"
    assert len(s.yuborildi) == n and _qatorlar() == ["Beta: post"]          # o'zicha yuborilmadi
    t = s.tahrirlar()[-1]
    assert t["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"vz:qayta:{iid}"
    assert vz.callback(_cq(f"vz:qayta:{iid}", mid=501)) == "vz-qayta-qoshildi"
    sl = wk.yukla(SANA)["ertalab"]
    assert sl["holat"] == "qoralama" and sl["yangilangan"] and sl["yuborish_soni"] == 0
    assert _qatorlar() == ["Beta: post", "Alfa: TZ yozish"] and len(s.yuborildi) == n
    assert vz.callback(_cq(f"vz:qayta:{iid}", mid=501)) == "vz-qayta-bor"   # qayta bosish — takrorsiz
    assert _qatorlar() == ["Beta: post", "Alfa: TZ yozish"]


def test_yuborilgan_rejada_bor_ish_uchun_qayta_yuborish_taklif_qilinmaydi(s):
    _qosh(s, "Alfa: TZ yozish", mid=91)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Alfa: TZ yozish", "Beta: post"])
    wk.yubor(SANA, "ertalab")
    s.calls.clear()
    assert _ha(_items()[0]["id"]) == "vz-ha-bor"
    assert not [d for d in s.tugmalar() if d.startswith("vz:qayta")]
    assert wk.yukla(SANA)["ertalab"]["holat"] == "yuborildi"


def test_toliq_yuborilgan_reja_qayta_ochilmaydi(s):
    _qosh(s, "Alfa: TZ", mid=92)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, [f"Beta: ish {i}" for i in range(wk.MAX_QATOR)])
    wk.yubor(SANA, "ertalab")
    assert _ha(_items()[0]["id"]) == "vz-ha-toliq"
    assert _items()[0]["holat"] == "navbatda" and wk.yukla(SANA)["ertalab"]["holat"] == "yuborildi"


def test_kechki_sorov_boshlangach_qayta_yuborish_ertalabni_ochmaydi(s):
    _qosh(s, "Alfa: TZ yozish", mid=93)
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    wk.yubor(SANA, "ertalab")
    iid = _items()[0]["id"]
    assert _ha(iid) == "vz-ha-yuborildi"
    s.vaqt = s.vaqt.replace(hour=19)
    wk.sorov("kechqurun")
    assert vz.callback(_cq(f"vz:qayta:{iid}")) == "vz-qayta-kechki"
    st = wk.yukla(SANA)
    assert st["faol"] == "kechqurun" and st["ertalab"]["holat"] == "yuborildi"
    with wk._LOCK:                                              # himoya qatlami ham: faol o'zgarmaydi
        assert wk.qator_qosh(SANA, "ertalab", ["Gamma: video"], qayta_och=True) == "qoshildi"
    assert wk.yukla(SANA)["faol"] == "kechqurun"


def test_ha_dam_kuni_navbatda_qoladi(s):
    _qosh(s, "Alfa: TZ", mid=95)
    wk.sorov("ertalab")
    wk.buyruq("/dam")
    assert _ha(_items()[0]["id"]) == "vz-ha-dam"
    assert _items()[0]["holat"] == "navbatda" and "bugun dam kuni" in s.tahrirlar()[-1]["text"]


def test_ha_jadval_toliq_bolsa_navbatda_qoladi(s):
    _qosh(s, "Alfa: TZ", mid=96)
    wk.sorov("ertalab")
    _rejani_yoz(s, [f"Beta: ish {i}" for i in range(wk.MAX_QATOR)])
    assert _ha(_items()[0]["id"]) == "vz-ha-toliq"
    assert _items()[0]["holat"] == "navbatda" and len(_qatorlar()) == wk.MAX_QATOR


# ---------------- ⏳ Keyinroq va keyingi kun ----------------

def test_keyinroq_navbatda_qoladi_keyingi_kun_yana_soraladi(s):
    _qosh(s, "Alfa: TZ", mid=100)
    wk.sorov("ertalab")
    iid = _items()[0]["id"]
    assert vz.callback(_cq(f"vz:keyin:{iid}")) == "vz-keyin"
    assert vz.callback(_cq(f"vz:keyin:{iid}")) == "vz-keyin"              # qayta bosish
    it = _items()[0]
    assert it["holat"] == "navbatda" and it["keyin_soni"] == 1
    assert "keyingi kunlarda yana so'rayman" in s.tahrirlar()[-1]["text"]
    s.calls.clear()
    s.vaqt += timedelta(days=1)
    wk.sorov("ertalab")
    assert [t for t in s.matnlar() if "Buni ham" in t and "1 marta keyinga" in t]
    assert any(m == "editMessageReplyMarkup" for m, _ in s.calls)        # kechagi tugma olindi


def test_kechki_hisobot_bolmasa_ertalab_navbatga_qaytadi(s):
    _qosh(s, "Alfa: TZ", mid=101)
    wk.sorov("ertalab")
    _ha(_items()[0]["id"])
    s.vaqt += timedelta(days=1)
    s.calls.clear()
    wk.sorov("ertalab")
    it = _items()[0]
    assert it["holat"] == "navbatda" and it["keyin_soni"] == 1
    assert it["soraldi"] == "2026-12-01" and [t for t in s.matnlar() if "Buni ham" in t]


def test_royxatda_ham_eskirgan_bugun_qaytadi(s):
    wk.buyruq("/kunlik off")                                      # ertalabki so'rov yo'q kunlar
    _qosh(s, "Alfa: TZ", mid=102)
    assert vz.callback(_cq("vz:sora:0")) == "vz-sora-1"
    assert _ha(_items()[0]["id"]) == "vz-ha-yangi"
    s.vaqt += timedelta(days=2)
    html, kb = vz.royxat()
    assert "1 ta navbatda" in html
    assert "vz:sora:0" in [b["callback_data"] for q in kb["inline_keyboard"] for b in q]


# ---------------- kechqurun ----------------

def _kunni_boshla(s, *navbat, reja=("Beta: post",), mid=110):
    s.ajrat = _bandlar(*navbat)
    vz.buyruq("/vazifa x", _msg(mid=mid))
    _boshliq()
    wk.sorov("ertalab")
    for it in _items():
        _ha(it["id"])
    _rejani_yoz(s, list(reja))
    assert wk.yubor(SANA, "ertalab") == "yuborildi"
    s.vaqt = s.vaqt.replace(hour=19)
    wk.sorov("kechqurun")


def test_kechki_hisobot_bajarilganini_yopadi_qolganini_qaytaradi(s):
    _kunni_boshla(s, "Alfa: TZ yozish", "Gamma: video")
    _rejani_yoz(s, [{"ish": "Beta: post", "holat": "bajarildi"},
                    {"ish": "Alfa: TZ yozish", "holat": "bajarildi"},
                    {"ish": "Gamma: video", "holat": "ertaga"}], slot="kechqurun")
    assert wk.yubor(SANA, "kechqurun") == "yuborildi"
    holat = {i["matn"]: (i["holat"], i["keyin_soni"]) for i in _items()}
    assert holat == {"Alfa: TZ yozish": ("bajarildi", 0), "Gamma: video": ("navbatda", 1)}
    t = s.matnlar()[-1]
    assert "1 ta bajarildi" in t and "1 tasi navbatga qaytdi" in t


def test_kechki_hisobot_tuzatilib_qayta_yuborilsa_qayta_solishtiriladi(s):
    _kunni_boshla(s, "Alfa: TZ yozish", "Gamma: video")
    _rejani_yoz(s, [{"ish": "Beta: post", "holat": "bajarildi"},
                    {"ish": "Alfa: TZ yozish", "holat": "bajarildi"},
                    {"ish": "Gamma: video", "holat": "ertaga"}], slot="kechqurun")
    wk.yubor(SANA, "kechqurun")
    assert wk.buyruq("/kechqurun qayta") == "wow-kechqurun-qayta"
    _rejani_yoz(s, [{"ish": "Beta: post", "holat": "bajarildi"},
                    {"ish": "Alfa: TZ yozish", "holat": "bajarilmadi"},
                    {"ish": "Gamma: video", "holat": "bajarildi"}], slot="kechqurun")
    assert wk.yubor(SANA, "kechqurun") == "yuborildi"
    holat = {i["matn"]: (i["holat"], i["keyin_soni"]) for i in _items()}
    assert holat == {"Alfa: TZ yozish": ("navbatda", 0), "Gamma: video": ("bajarildi", 1)}
    assert vz.kechki_yakun(SANA, wk.yukla(SANA)["kechqurun"]["jadval"]) == (0, 0)  # boot — takrorsiz


def test_kechki_hisobot_ertasi_kech_yuborilsa_ham_yopiladi(s):
    s.ajrat = _bandlar("Alfa: TZ yozish")
    vz.buyruq("/vazifa x", _msg(mid=120))
    _boshliq()
    wk.buyruq("/kunlik avto off")
    wk.sorov("ertalab")
    _ha(_items()[0]["id"])
    _rejani_yoz(s, ["Beta: post"])
    wk.yubor(SANA, "ertalab")
    s.vaqt = s.vaqt.replace(hour=19)
    wk.sorov("kechqurun")
    _rejani_yoz(s, [{"ish": "Beta: post", "holat": "bajarildi"},
                    {"ish": "Alfa: TZ yozish", "holat": "bajarildi"}], slot="kechqurun")
    s.vaqt = datetime(2026, 12, 1, 9, 0, tzinfo=TZ)              # kechki qoralama yuborilmay qoldi
    s.calls.clear()
    wk.sorov("ertalab")
    assert _items()[0]["holat"] == "bugun" and not [t for t in s.matnlar() if "Buni ham" in t]
    assert wk.callback(_cq(f"wow:ok:{SANA}:kechqurun")) == "wow-ok-yuborildi"
    assert _items()[0]["holat"] == "bajarildi"


def test_kechki_hammasi_tugmasi_navbat_ishini_ham_qamraydi(s):
    s.ajrat = _bandlar("Alfa: TZ yozish")
    vz.buyruq("/vazifa x", _msg(mid=130))
    _boshliq()
    wk.sorov("ertalab")
    _rejani_yoz(s, ["Beta: post"])
    wk.yubor(SANA, "ertalab")
    assert _ha(_items()[0]["id"]) == "vz-ha-yuborildi"         # 🔁 bosilmadi — rejada yo'q
    s.vaqt = s.vaqt.replace(hour=19)
    s.calls.clear()
    wk.sorov("kechqurun")
    assert "Navbatdan bugunga olganlaringiz" in s.matnlar()[0]
    assert f"wow:hammasi:{SANA}:kechqurun" in s.tugmalar()
    assert wk.callback(_cq(f"wow:hammasi:{SANA}:kechqurun")) == "wow-hammasi"
    sl = wk.yukla(SANA)["kechqurun"]["jadval"]
    assert [(r["ish"], r["holat"]) for r in sl] == [("Beta: post", "bajarildi"),
                                                    ("Alfa: TZ yozish", "bajarildi")]
    wk.yubor(SANA, "kechqurun")
    assert _items()[0]["holat"] == "bajarildi"


def test_kechki_claude_ga_navbat_ishi_reja_bilan_beriladi(s):
    s.ajrat = _bandlar("Alfa: TZ yozish")
    vz.buyruq("/vazifa x", _msg(mid=131))
    wk.sorov("ertalab")
    _ha(_items()[0]["id"])                                     # reja umuman yozilmadi
    s.vaqt = s.vaqt.replace(hour=19)
    wk.sorov("kechqurun")
    _rejani_yoz(s, [{"ish": "Alfa: TZ yozish", "holat": "bajarildi"}], slot="kechqurun")
    assert [r["ish"] for r in s.wow_args[-1]["reja"]] == ["Alfa: TZ yozish"]


def test_kechki_yakun_oxshash_qatorni_yopmaydi(s):
    s.ajrat = _bandlar("Alfa: 2-post")
    vz.buyruq("/vazifa x", _msg(mid=132))
    wk.sorov("ertalab")
    _ha(_items()[0]["id"])
    jadval = [{"ish": "Alfa: 1-post", "holat": "bajarildi"},
              {"ish": "Alfa: 2-post", "holat": "jarayonda"}]
    assert vz.kechki_yakun(SANA, jadval, xabar_yubor=False) == (0, 1)
    assert _items()[0]["holat"] == "navbatda"


# ---------------- /vazifalar va boshqa tugmalar ----------------

def test_royxat_bajarildi_ochirish_va_hozir_sorash(s):
    s.ajrat = _bandlar("Alfa: TZ", "Beta: post")
    vz.buyruq("/vazifa x", _msg(mid=140))
    a, b = [i["id"] for i in _items()]
    assert vz.buyruq("/vazifalar", _msg()) == "vazifa-royxat"
    assert "2 ta navbatda" in s.matnlar()[-1]
    data = s.tugmalar()
    assert {f"vz:bajardi:{a}:0", f"vz:ochir:{b}:0", "vz:sora:0"} <= set(data)
    assert vz.callback(_cq("vz:sora:0")) == "vz-sora-2"
    assert vz.callback(_cq(f"vz:bajardi:{a}:0", mid=700)) == "vz-bajardi"
    assert s.tahrirlar()[-1]["message_id"] == 700 and "1 ta navbatda" in s.tahrirlar()[-1]["text"]
    assert vz.callback(_cq(f"vz:bajardi:{a}:0", mid=700)) == "vz-bajardi-yopiq"
    assert vz.callback(_cq(f"vz:ochir:{b}:0", mid=700)) == "vz-ochir"
    assert "Navbat bo'sh" in s.tahrirlar()[-1]["text"]
    assert _ha(a) == "vz-eskirgan"


def test_royxat_sahifalanadi(s):
    for i in range(12):
        _qosh(s, f"Ish {chr(65 + i)}", mid=200 + i)
    vz.buyruq("/vazifalar", _msg())
    t = s.matnlar()[-1]
    assert "Sahifa 1/2" in t and "Ish H" in t and "Ish I" not in t
    assert "vz:sahifa:1" in s.tugmalar()
    assert vz.callback(_cq("vz:sahifa:1", mid=800)) == "vz-sahifa"
    t2 = s.tahrirlar()[-1]["text"]
    assert "Ish L" in t2 and "Ish A" not in t2 and "Sahifa 2/2" in t2
    eng_yangi = _bir("Ish L")["id"]
    assert vz.callback(_cq(f"vz:ochir:{eng_yangi}:1", mid=800)) == "vz-ochir"
    assert "Sahifa 2/2" in s.tahrirlar()[-1]["text"]                        # o'sha sahifada qoladi


def test_qaytar_shu_xabardagi_ishlarni_ochiradi(s):
    s.ajrat = _bandlar("Alfa: TZ", "Beta: post")
    vz.buyruq("/vazifa x", _msg(mid=150))
    _qosh(s, "Gamma: video", mid=151)
    birinchi = _items()[0]["id"]
    assert vz.callback(_cq(f"vz:qaytar:{birinchi}")) == "vz-qaytar-2"
    assert [i["matn"] for i in _items("navbatda")] == ["Gamma: video"]
    assert vz.callback(_cq(f"vz:qaytar:{birinchi}")) == "vz-qaytar-0"


def test_eskirgan_va_begona_tugmalar(s):
    assert _ha(999) == "vz-eskirgan"
    assert vz.callback(_cq("vz:xyz:1")) == "vz-cb-noma'lum"
    assert vz.callback(_cq("vz:ha:abc")) == "vz-cb-noma'lum"
    assert vz.callback(_cq(f"wow:ok:{SANA}:ertalab")) is None


def test_buzuq_fayl_oqishda_chetga_olinadi_ogohlantirish_diskda(s):
    _qosh(s, "Alfa: TZ", mid=160)
    eski_id = _items()[0]["id"]
    p = wk.DIR / "vazifalar.json"
    p.write_text("{buzuq", encoding="utf-8")
    assert not vz.ushlaydimi(_msg("undiruv qancha?", mid=161))       # aloqasiz xabar — o'qish yo'li
    assert len(list(wk.DIR.glob("vazifalar.json.buzuq-*"))) == 1
    assert "buzilgan" in json.loads(p.read_text(encoding="utf-8"))["ogoh"]
    assert "buzilgan" in wk.holat_matni()
    vz.buyruq("/vazifalar", _msg())
    assert "Vazifalar fayli buzilgan" in s.matnlar()[-1]
    vz.buyruq("/vazifalar", _msg())
    assert "buzilgan" not in s.matnlar()[-1]                          # bir marta aytiladi
    _qosh(s, "Beta: post", mid=162)
    assert _items()[0]["id"] > 10 ** 9 and _items()[0]["id"] != eski_id     # eski tugmalar tegmaydi


def test_kunlik_holatida_navbat_soni(s):
    _qosh(s, "Alfa: TZ", mid=170)
    t = wk.holat_matni()
    assert "Vazifa navbati: 1 ta" in t and "/vazifalar" in t


# ---------------- bot_listener bilan birga ----------------

def test_bot_listener_buyruq_tugma_va_yordam(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    s.ajrat = _bandlar("Alfa: TZ")
    assert bl.handle_update({"update_id": 1, "message": _msg("/vazifa Alfa TZ", mid=180)}) == \
        "vazifa-qoshildi"
    assert bl.handle_update({"update_id": 2, "message": _msg("/vazifalar", mid=181)}) == \
        "vazifa-royxat"
    assert bl.handle_update({"update_id": 3, "message": _msg("/vazifalar@WallEBot", mid=182)}) == \
        "vazifa-royxat"
    iid = _items()[0]["id"]
    begona = {"id": "c", "data": f"vz:ochir:{iid}", "from": {"id": 999},
              "message": {"message_id": 1, "chat": {"id": 555}}}
    assert bl.handle_update({"update_id": 4, "callback_query": begona}) == "cb-ignored"
    assert _items("navbatda")
    assert bl.handle_update({"update_id": 5, "callback_query": {**begona, "from": {"id": 555}}}) \
        == "vz-ochir"
    assert "/vazifa" in bl.HELP and "/vazifalar" in bl.HELP and "/claude" in bl.HELP


def test_bot_listener_claude_holati_faqat_nomlar(s, monkeypatch):
    bl = _bl(monkeypatch, s)
    monkeypatch.setattr(analyze, "auth_usuli", lambda timeout=15: "oauth_token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-SIRLI")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-SIRLI")
    yuborilgan = []
    monkeypatch.setattr(bl, "send_retry", lambda t, **k: yuborilgan.append((t, k)) or True)
    assert bl.handle_update({"update_id": 6, "message": _msg("/claude", mid=190)}) == "claude-holat"
    t, k = yuborilgan[-1]
    assert k.get("is_html") and "Obuna tokeni" in t and "<code>ANTHROPIC_API_KEY</code>" in t
    assert "SIRLI" not in t and "obuna tokeni ✅" in t


# ---------------- faqat obuna: claude -p muhiti ----------------

def test_run_claude_api_kalit_va_proxyni_bermaydi(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_UNIX_SOCKET",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_MANTLE",
              "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
              "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_SIMPLE"):
        monkeypatch.setenv(k, "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-y")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    seen = {}

    def run(cmd, **k):
        seen.update(k, cmd=cmd)
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(analyze, "find_claude", lambda: "claude")
    monkeypatch.setattr(analyze.subprocess, "run", run)
    monkeypatch.setattr(analyze, "_CLI_YORDAM", {"txt": "--tools <t>\n--setting-sources <s>\n"})
    assert analyze.run_claude("p") == "ok"
    env = seen["env"]
    assert not [k for k in env if analyze.api_billing_mi(k)], [k for k in env if k.startswith("ANTH")]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-y" and env["CLAUDE_CODE_EFFORT_LEVEL"] == "low"
    assert env.get("PATH") == os.environ.get("PATH")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--setting-sources") + 1] == "project"     # user settings (apiKeyHelper) yo'q
    h = analyze.obuna_holati()
    assert h["token"] and {"ANTHROPIC_API_KEY", "ANTHROPIC_UNIX_SOCKET",
                           "CLAUDE_CODE_USE_ANTHROPIC_AWS"} <= set(h["bloklangan"])
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in h["bloklangan"]
    assert "sk-ant" not in analyze.obuna_qisqa() and "bloklandi" in analyze.obuna_qisqa()


def test_limit_matni():
    assert analyze.limit_matni("You've hit your session limit · resets 3:45pm") == \
        "Claude obuna limiti tugagan (tiklanadi: 3:45pm)"
    assert analyze.limit_matni("Credit balance is too low") is None
    assert analyze.limit_matni("") is None


def test_matn_oxshash_qatiy():
    ha = [("Alfa: TZ yozish", "alfa — tz yozish"), ("Alfa: TZ yozish", "Alfa: TZ yozish."),
          ("Alfa: TZ yozish", "ALFA: tz  yozish"), ("Alfa: post va video", "Alfa: video va post")]
    yoq = [("Alfa: TZ yozish", "Beta: TZ yozish"), ("Alfa: post", "Alfa: video"),
           ("Alfa: 1-post dizayni", "Alfa: 2-post dizayni"), ("3 ta reels", "5 ta reels"),
           ("Alfa: oktyabr hisoboti", "Alfa: noyabr hisoboti"), ("TZ yozish", "Beta: TZ yozish"),
           ("Alfa: shartnoma", "Alfa: shartnomani bekor qilish"),
           ("Alfa: TZ yozish va mijozga yuborish", "Alfa: TZ yozish"),
           ("Alfa: KP yuborish", "Alfa: KP yozish"), ("Alfa: dogovor tuzish", "Alfa: dogovor yuborish"),
           ("Alfa: kontent-reja tayyorlash", "Gamma: kontent-reja tayyorlash"),
           ("Alfa: TZ yozish", "Alfa: TZ yozish (soat 15)"), ("", "Alfa")]
    assert all(wk.matn_oxshash(a, b) for a, b in ha), [p for p in ha if not wk.matn_oxshash(*p)]
    assert not any(wk.matn_oxshash(a, b) for a, b in yoq), [p for p in yoq if wk.matn_oxshash(*p)]
    assert not wk.matn_oxshash("Alfa: 2 marta qo'ng'iroq", "Alfa: 2 mart qo'ng'iroq")   # «marta» oy emas
