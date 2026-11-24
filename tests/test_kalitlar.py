"""Egasining kalit so'zlari (kalitlar.py): vault'dagi lug'at → whisper --prompt va Claude prompti.

conftest FAYLLAR'ni tmp_path/kalit-sozlar.md ga yo'naltiradi. pytest tests/test_kalitlar.py —
tarmoq, model va Claude kerak emas.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kalitlar  # noqa: E402

NAMUNA = """# Kalit so'zlar

> Format: `- **Kalit** — ma'nosi` — bu iqtibos, kalit emas.
#teg-sarlavha-emas

## Odamlar
- **Anvar aka** — direktor
- Bekzod: dizayner
* **Sherzod aka:** montaj jamoasi rahbari
1. Dilshod – operator
- Ma'nosiz band
- Juda uzun gap bu kalit emas balki izoh uni whisper promptiga qo'shib bo'lmaydi chunki uzun — x

## Atamalar
- **kassachilar** — to'lov qabul qiluvchi xodimlar
- **kontent-reja** — oylik post rejasi

## Loyihalar
Loyiha nomlari main page'dan avtomatik olinadi.
"""


@pytest.fixture
def lugat():
    f = kalitlar.FAYLLAR[0]
    f.write_text(NAMUNA, encoding="utf-8")
    return f


def test_royxat_formatlar_va_bolimlar(lugat):
    r = kalitlar.royxat()
    assert [(b, k) for b, k, _ in r] == [
        ("Odamlar", "Anvar aka"), ("Odamlar", "Bekzod"), ("Odamlar", "Sherzod aka"),
        ("Odamlar", "Dilshod"), ("Atamalar", "kassachilar"), ("Atamalar", "kontent-reja")]
    assert r[0][2] == "direktor" and r[2][2] == "montaj jamoasi rahbari"
    assert r[3][2] == "operator"


def test_fayl_ozgarsa_qayta_oqiladi(lugat):
    assert len(kalitlar.royxat()) == 6
    lugat.write_text("## Odamlar\n- **Jasur** — kopirayter\n", encoding="utf-8")
    os.utime(lugat, ns=(10**18, 10**18))
    assert [k for _, k, _ in kalitlar.royxat()] == ["Jasur"]


def test_fayl_yoq_yoki_buzuq():
    assert kalitlar.royxat() == [] and kalitlar.whisper_royxati() == []
    assert kalitlar.prompt_matni() == "(yo'q)"
    kalitlar.FAYLLAR[0].write_bytes(b"## O\n- **X** \xff\xfe \x80\n")
    assert kalitlar.royxat() == []


def test_vault_nusxasi_uydagidan_oldin(tmp_path, monkeypatch):
    vault, uy = tmp_path / "vault.md", tmp_path / "uy.md"
    monkeypatch.setattr(kalitlar, "FAYLLAR", (vault, uy))
    uy.write_text("## O\n- **B** — b\n", encoding="utf-8")
    assert kalitlar.fayl() == uy
    vault.write_text("## O\n- **A** — a\n", encoding="utf-8")
    assert [k for _, k, _ in kalitlar.royxat()] == ["A"]


def test_whisper_royxati_uzunlik_chegarasi(lugat, monkeypatch):
    assert kalitlar.whisper_royxati() == ["Anvar aka", "Bekzod", "Sherzod aka", "Dilshod",
                                          "kassachilar", "kontent-reja"]
    monkeypatch.setattr(kalitlar, "WHISPER_MAX", 30)
    assert kalitlar.whisper_royxati() == ["Anvar aka", "Bekzod"]


def test_prompt_matni_bolimlar_bilan(lugat):
    t = kalitlar.prompt_matni()
    assert t.splitlines()[:2] == ["Odamlar:", "- Anvar aka — direktor"]
    assert "Atamalar:\n- kassachilar — to'lov qabul qiluvchi xodimlar" in t


def test_whisperga_kalit_sozlar_prompt_bolib_boradi(lugat, monkeypatch, tmp_path):
    import stt

    monkeypatch.setattr(stt, "stt_ready", lambda: (True, ""))
    monkeypatch.setattr(stt, "whisper_bin", lambda: "/bin/whisper-cli")
    monkeypatch.setenv("WHISPER_THREADS", "2")
    cmdlar = []

    def run(cmd, **kw):
        cmdlar.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"wav")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "salom\n", "")

    monkeypatch.setattr(stt.subprocess, "run", run)
    assert stt.transcribe(tmp_path / "v.ogg", sekund=3) == "salom"
    cmd = cmdlar[-1]
    assert cmd[cmd.index("--prompt") + 1] == ("Anvar aka, Bekzod, Sherzod aka, Dilshod, "
                                              "kassachilar, kontent-reja.")
    lugat.unlink()
    stt.transcribe(tmp_path / "v.ogg", sekund=3)
    assert "--prompt" not in cmdlar[-1]


def test_claude_promptida_lugat_va_main_page_nomlari(lugat):
    import wow_kunlik as wk

    p = wk._prompt("reja", [], None, ["Livardi", "Orzu"], "bekzot bilan livardi", "ovoz",
                   "2026-11-24")
    assert "- Anvar aka — direktor" in p and "Livardi, Orzu" in p
    assert "{{" not in p
