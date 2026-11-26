"""Ikkinchi miya yig'uvchisi (deploy/mac-sync/miya) testlari.

pytest tests/test_miya.py — haqiqiy ~/.claude yoki ~/claude-brain'ga TEGMAYDI:
har test vaqtinchalik vault, ~/.claude va state papkasini quradi (MIYA_* env).
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy" / "mac-sync"))
from miya import asos, hublar, kod, sessiyalar, skillar, sorovlar, walle, xulosa  # noqa: E402


@pytest.fixture()
def muhit(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "kunlik").mkdir(parents=True)
    c = tmp_path / "claude"
    (c / "projects").mkdir(parents=True)
    monkeypatch.setenv("MIYA_VAULT", str(v))
    monkeypatch.setenv("MIYA_CLAUDE_DIR", str(c))
    monkeypatch.setenv("MIYA_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("MIYA_TG_AUDIT", str(tmp_path / "tg"))
    return {"vault": v, "claude": c, "tmp": tmp_path}


def _jsonl(p: Path, yozuvlar):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in yozuvlar) + "\n", encoding="utf-8")


def _sessiya(c: Path, sid="aaaaaaaa-1111-2222-3333-444444444444", papka="-Users-x-Projects-demo",
             cwd="/Users/x/Projects/demo", sirli=""):
    yozuv = [
        {"type": "custom-title", "customTitle": "Demo sessiya", "sessionId": sid},
        {"type": "user", "turnOrigin": "human", "origin": {"kind": "human"}, "timestamp": "2026-11-20T05:00:00.000Z",
         "cwd": cwd, "gitBranch": "main", "sessionId": sid,
         "message": {"role": "user", "content": "<system-reminder>ichki</system-reminder>Hisobot qil " + sirli}},
        {"type": "user", "isMeta": True, "timestamp": "2026-11-20T05:00:01Z", "cwd": cwd,
         "message": {"role": "user", "content": "skill matni — inson so'rovi emas"}},
        {"type": "assistant", "timestamp": "2026-11-20T05:01:00Z", "cwd": cwd,
         "message": {"model": "claude-opus-5-5", "content": [
             {"type": "text", "text": "Boshlayman"},
             {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "/Users/x/Projects/demo/a.py"}},
             {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "git commit -m 'x'"}},
             {"type": "tool_use", "id": "t3", "name": "Artifact", "input": {"action": "list"}},
             {"type": "tool_use", "id": "t4", "name": "Artifact", "input": {"file_path": "/tmp/p.html"}},
             {"type": "tool_use", "id": "t5", "name": "Skill", "input": {"skill": "anthropic-skills:pdf"}},
             {"type": "tool_use", "id": "t6", "name": "mcp__ccd_turn__wrap_up",
              "input": {"recap": "Hisobot tayyor, PDF yuborildi."}},
         ]}},
        {"type": "user", "timestamp": "2026-11-20T05:01:05Z", "cwd": cwd, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "[main 1a2b3c4] x\n 1 file changed"},
            {"type": "tool_result", "tool_use_id": "t3",
             "content": "- https://claude.ai/artifact/LISTONLY111 — boshqa sessiyaniki"},
            {"type": "tool_result", "tool_use_id": "t4", "content": "Published https://claude.ai/artifact/NASHR222"},
        ]}},
        {"type": "user", "isCompactSummary": True, "turnOrigin": "human", "timestamp": "2026-11-20T06:00:00Z",
         "cwd": cwd, "message": {"role": "user", "content": "This session is being continued from a previous conversation"}},
        {"type": "assistant", "timestamp": "2026-11-20T06:00:05Z", "cwd": cwd,
         "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your limit"}]}},
        {"type": "frame-link", "frameUrl": "https://claude.ai/artifact/FRAME333", "title": "Dashboard"},
        {"type": "cost-state", "totalCostUSD": 12.5, "totalLinesAdded": 10, "totalLinesRemoved": 2},
    ]
    _jsonl(c / "projects" / papka / f"{sid}.jsonl", yozuv)
    return sid


# ---------------------------------------------------------------- asos

def test_redakt_sirlar():
    tok = "1234567890:" + "A" * 35
    t = asos.redakt(f"token={tok} ghp_{'a' * 36} parol: Qwerty12345 AIza{'b' * 35} sk-ant-{'c' * 30}")
    assert tok not in t and "ghp_" not in t and "Qwerty12345" not in t and "AIza" not in t
    assert "sk-ant-c" not in t
    assert asos.redakt("token qo'yilgach rasmiy API o'tadi") == "token qo'yilgach rasmiy API o'tadi"


def test_redakt_qisqartirishdan_oldin():
    kalit = "sk-ant-" + "z" * 40
    assert "zzzz" not in asos.bir_qator(asos.redakt("x " * 10 + kalit), 40)


def test_slug_va_fayl_nomi():
    assert asos.slug("O'zbekcha G'alaba — Тест") == "ozbekcha-galaba-test"
    assert sessiyalar.fayl_nomi("a/b: c?.md…") == "a b c"


def test_frontmatter_oqish_yozish():
    fm = asos.frontmatter({"sarlavha": 'Qo\'shtirnoq "x" va: nuqta', "sana": "2026-11-20", "tags": ["a", "b"],
                           "son": 5, "bosh": ""})
    d = asos.fm_oqi(fm + "\n# x\n")
    assert d["sarlavha"] == 'Qo\'shtirnoq "x" va: nuqta' and d["sana"] == "2026-11-20" and d["son"] == "5"
    assert "bosh" not in d and asos.BELGI in fm
    blok = asos.fm_oqi("---\nname: s\ndescription: >\n  birinchi\n  ikkinchi\n---\n")
    assert blok["description"] == "birinchi ikkinchi"


# ---------------------------------------------------------------- yozuvchi

def test_yozuvchi_qolda_faylga_tegmaydi(muhit):
    v = muhit["vault"]
    (v / "claude").mkdir()
    (v / "claude" / "INDEX.md").write_text("# egasi yozgan\n", encoding="utf-8")
    y = asos.Yozuvchi(v)
    assert y.yoz("claude/INDEX.md", asos.frontmatter({"turi": "x"}) + "yangi\n") == "qolda"
    assert (v / "claude" / "INDEX.md").read_text(encoding="utf-8") == "# egasi yozgan\n"


def test_yozuvchi_ruxsat_va_barqarorlik(muhit):
    y = asos.Yozuvchi(muhit["vault"])
    with pytest.raises(ValueError):
        y.yoz("kunlik/2026-11-20.md", "x")
    with pytest.raises(ValueError):
        y.yoz("claude/../kunlik/x.md", "x")
    matn = asos.frontmatter({"turi": "t"}) + "# A\n" + asos.QOLDA_BLOK
    assert y.yoz("claude/a.md", matn) == "yangi"
    assert y.yoz("claude/a.md", matn) == "ozgarmagan"


def test_yozuvchi_izohni_saqlaydi(muhit):
    y = asos.Yozuvchi(muhit["vault"])
    y.yoz("claude/a.md", asos.frontmatter({"turi": "t"}) + "# A\n" + asos.QOLDA_BLOK)
    p = muhit["vault"] / "claude" / "a.md"
    p.write_text(p.read_text(encoding="utf-8") + "MENING IZOHIM\n", encoding="utf-8")
    assert y.yoz("claude/a.md", asos.frontmatter({"turi": "t"}) + "# B\n" + asos.QOLDA_BLOK) == "yangilandi"
    t = p.read_text(encoding="utf-8")
    assert "# B" in t and "MENING IZOHIM" in t and "# A" not in t


def test_quruq_rejim_yozmaydi(muhit):
    y = asos.Yozuvchi(muhit["vault"], quruq=True)
    assert y.yoz("claude/a.md", asos.frontmatter({"turi": "t"}) + "x") == "yangi"
    assert not (muhit["vault"] / "claude" / "a.md").exists()


# ---------------------------------------------------------------- sessiyalar

def test_sessiya_parse(muhit):
    sid = _sessiya(muhit["claude"], sirli="parol: Maxfiy123456")
    s = sessiyalar.sessiya_oqi(muhit["claude"] / "projects" / "-Users-x-Projects-demo" / f"{sid}.jsonl")
    assert s["sarlavha"] == "Demo sessiya"
    assert len(s["turlar"]) == 1                      # compact summary inson so'rovi emas
    assert s["turlar"][0]["recap"] == ["Hisobot tayyor, PDF yuborildi."]
    assert s["turlar"][0]["javob"] == "Boshlayman"     # <synthetic> limit xabari javob emas
    assert "system-reminder" not in s["turlar"][0]["sorov"]
    assert s["commitlar"] == [("1a2b3c4", "main", "x")]
    assert set(s["artifactlar"]) == {"https://claude.ai/artifact/NASHR222", "https://claude.ai/artifact/FRAME333"}
    assert s["skillar"]["anthropic-skills:pdf"] == 1
    assert s["loyiha"] == "demo"


def test_sessiya_yozuvi_va_idempotent(muhit, monkeypatch):
    monkeypatch.setattr(asos, "HOME", Path("/Users/x"))
    _sessiya(muhit["claude"], sirli="parol: Maxfiy123456")
    y = asos.Yozuvchi(muhit["vault"])
    assert sessiyalar.yigish(y)["hisob"] == {"faol": 1}      # hozirgina yozilgan — hali faol
    assert not (muhit["vault"] / "claude").exists()
    kech = __import__("time").time() + 3600
    r = sessiyalar.yigish(y, hozir=kech)
    assert r["hisob"] == {"yangi": 1}
    fayllar = list((muhit["vault"] / "claude" / "sessiyalar" / "2026-11").glob("*.md"))
    assert len(fayllar) == 1 and fayllar[0].name.startswith("2026-11-20 Demo sessiya")
    t = fayllar[0].read_text(encoding="utf-8")
    assert "Maxfiy123456" not in t and "[MAXFIY]" in t
    assert "LISTONLY111" not in t and "NASHR222" in t
    assert "`1a2b3c4`" in t and "Hisobot tayyor" in t
    # ikkinchi yurish: transkript o'zgarmagan → o'tkaziladi
    assert sessiyalar.yigish(asos.Yozuvchi(muhit["vault"]), hozir=kech)["hisob"] == {"o'tkazildi": 1}
    # holat yo'qolsa ham dublikat yaratilmaydi
    (Path(os.environ["MIYA_STATE"]) / "sessiyalar.json").unlink()
    assert sessiyalar.yigish(asos.Yozuvchi(muhit["vault"]), hozir=kech)["hisob"] == {"ozgarmagan": 1}
    assert len(list((muhit["vault"] / "claude" / "sessiyalar" / "2026-11").glob("*.md"))) == 1


def test_headless_papka_otkaziladi(muhit):
    _sessiya(muhit["claude"], papka="-private-var-folders-xx-T-claude-p-abc123")
    assert sessiyalar.transkriptlar(muhit["claude"]) == []


def test_loyiha_nomi(monkeypatch):
    monkeypatch.setattr(asos, "HOME", Path("/Users/x"))
    assert sessiyalar.loyiha_nomi("/Users/x/abba-sheets-agent/.claude/worktrees/w1") == "abba-sheets-agent"
    assert sessiyalar.loyiha_nomi("/Users/x/.abba-tg-audit") == "abba-tg-audit"
    assert sessiyalar.loyiha_nomi("/Users/x/Library/Application Support/Claude/scratch-workspaces/a/b") == "papkasiz"
    assert sessiyalar.loyiha_nomi("/Users/x") == "uy"


# ---------------------------------------------------------------- boshqa manbalar

def test_sorovlar_oylik(muhit):
    _jsonl(muhit["claude"] / "history.jsonl", [
        {"display": "birinchi so'rov", "project": "/Users/x", "timestamp": 1777353153384},
        {"display": "ikkinchi token=ghp_" + "a" * 36, "project": "/Users/x/p", "timestamp": 1780000000000},
    ])
    y = asos.Yozuvchi(muhit["vault"])
    r = sorovlar.yigish(y)
    assert sum(r["oylar"].values()) == 2
    hammasi = "".join(p.read_text(encoding="utf-8") for p in (muhit["vault"] / "claude" / "sorovlar").glob("*.md"))
    assert "birinchi so'rov" in hammasi and "ghp_aaaa" not in hammasi


def test_skill_kalit():
    assert skillar.kalit("anthropic-skills:pdf") == "pdf"
    assert skillar.kalit("shartnoma-pdf:shartnoma-pdf") == "shartnoma-pdf"
    assert skillar.kalit("telegram:access") == "telegram-access"


def test_skillar_katalogi(muhit):
    sk = muhit["claude"] / "skills" / "abba-demo"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: abba-demo\ndescription: ABBA uchun demo skill\n---\n# x\n", encoding="utf-8")
    y = asos.Yozuvchi(muhit["vault"])
    r = skillar.yigish(y, sessiya_holat={"s1": {"rel": "claude/sessiyalar/x.md", "sarlavha": "S",
                                                 "skillar": ["abba-demo", "dataviz"], "boshi": "2026-11-20"}})
    assert r["skillar"]["abba-demo"]["kelib"] == "o'zimizniki"
    assert r["skillar"]["dataviz"]["kelib"] == "ichki"
    t = (muhit["vault"] / "claude" / "skillar" / "abba-demo.md").read_text(encoding="utf-8")
    assert "[[claude/sessiyalar/x|S]]" in t


def test_walle_kun(muhit, monkeypatch):
    v = muhit["vault"]
    (v / "chat").mkdir()
    (v / "chat" / "2026-11-24.md").write_text(
        "# 2026-11-24 — Suhbat arxivi\n\n- 11:32 · WOW kunlik reja (2026-11-24) yuborildi: A ish; B ish\n"
        "- 19:19 · WOW kunlik hisobot (2026-11-24) yuborildi: ✅ A ish; ➡️ B ish\n"
        "## 12:36 · Savol\nundiruv qoldig'i qancha?\n\n## 12:36 · Javob\n$15 600\n", encoding="utf-8")
    (v / "abba-sheets-agent" / "hisobotlar").mkdir(parents=True)
    (v / "abba-sheets-agent" / "hisobotlar" / "2026-11-24.md").write_text(
        "# x\n\n▸ **PM-1 KPI**\n- 15 qator o'zgargan.\n", encoding="utf-8")
    kesh = Path(os.environ["MIYA_STATE"]) / "walle_target"
    kesh.mkdir(parents=True)
    (kesh / "2026-11-24.md").write_text("📈 **Target** — 24.11\nTarget: **+3 497** obunachi, 20 loyiha", encoding="utf-8")
    monkeypatch.setattr(walle, "KUNLAR_ORQAGA", 3)
    y = asos.Yozuvchi(v)
    walle.yigish(y, sessiya_holat={}, hozir=datetime(2026, 11, 25, 22, 0, tzinfo=asos.TZ))
    t = (v / "wall-e" / "kunlar" / "2026-11-24.md").read_text(encoding="utf-8")
    assert "**Ertalabki reja**" in t and "- ➡️ B ish" in t and "PM-1 KPI" in t
    assert "undiruv qoldig'i qancha?" in t
    fm = asos.fm_oqi(t)
    assert fm["target_obunachi"] == "3497" and fm["wow"] == "2"
    assert "[[wall-e/kunlar/2026-11-24\\|2026-11-24]]" in (v / "wall-e" / "INDEX.md").read_text(encoding="utf-8")


def test_kod_remote_tozalanadi():
    assert kod._remote_toza("https://user:ghp_" + "x" * 36 + "@github.com/a/b.git") == "https://github.com/a/b.git"


def test_xulosa_vaqti(muhit):
    xulosa.sozla(True, "21:30")
    assert not xulosa.kerakmi(datetime(2026, 11, 25, 20, 0, tzinfo=asos.TZ))
    assert xulosa.kerakmi(datetime(2026, 11, 25, 21, 31, tzinfo=asos.TZ))
    d = asos.holat_oqi("xulosa")
    d["oxirgi"] = "2026-11-25"
    asos.holat_yoz("xulosa", d)
    assert not xulosa.kerakmi(datetime(2026, 11, 25, 23, 0, tzinfo=asos.TZ))
    xulosa.sozla(False)
    assert not xulosa.kerakmi(datetime(2026, 11, 26, 22, 0, tzinfo=asos.TZ))


def test_xulosa_jadval_plist(tmp_path):
    import plistlib
    d = xulosa.jadval_plist("21:30", tmp_path)
    assert d["Label"] == "com.abba.miya-xulosa"
    assert d["StartCalendarInterval"] == {"Hour": 21, "Minute": 30}
    assert d["ProgramArguments"][-2:] == ["-m", "miya"]
    assert d["WorkingDirectory"] == str(tmp_path)
    assert "RunAtLoad" not in d          # yoqilgan zahoti yuborib yubormasin
    plistlib.loads(plistlib.dumps(d))      # yaroqli plist


def test_xulosa_soat_normallashadi(muhit):
    assert xulosa.sozla(True, "9:05")["soat"] == "09:05"     # kerakmi() satrlarni solishtiradi
    assert not xulosa.kerakmi(datetime(2026, 11, 27, 9, 4, tzinfo=asos.TZ))
    assert xulosa.kerakmi(datetime(2026, 11, 27, 9, 6, tzinfo=asos.TZ))
    with pytest.raises(ValueError):
        xulosa.sozla(True, "25:00")
    assert xulosa.sozlama()["soat"] == "09:05"


def test_xulosa_matn_bugungi_yozuvlar(muhit):
    v = muhit["vault"]
    bugun = datetime(2026, 11, 26, 15, 0, tzinfo=asos.TZ).timestamp()
    kecha = datetime(2026, 11, 25, 15, 0, tzinfo=asos.TZ).timestamp()

    def yoz(rel, ts):
        p = v / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        os.utime(p, (ts, ts))
    yoz("kunlik/2026-11-26.md", bugun)
    yoz("bilim/eski.md", kecha)
    yoz("claude/sessiyalar/2026-11/a.md", bugun)
    yoz("BOSH-SAHIFA.md", bugun)
    yoz(".obsidian/x.md", bugun)
    yoz("loyiha/ilovalar/x.md", bugun)
    m = xulosa.matn({}, v, "2026-11-26")
    assert "1 yozuv (+2 avto sahifa)" in m
    assert "kunlik/2026-11-26" in m and "bilim/eski" not in m and "ilovalar" not in m
    assert "obsidian://open?vault=vault&amp;file=BOSH-SAHIFA" in m
    for teg in ("b", "code"):               # Telegram HTML: hamma teg yopiq
        assert m.count(f"<{teg}>") == m.count(f"</{teg}>")


def test_xulosa_faol_sessiya_kiradi(muhit, monkeypatch):
    # xulosa soatidagi yig'ish 45 daqiqalik faol sessiyani yozmaydi — YUBORILGAN xulosa baribir uni ko'rsatsin
    yuborilgan = []
    monkeypatch.setattr(xulosa, "yubor", lambda t: yuborilgan.append(t) or True)
    xulosa.sozla(True, "21:30")
    sid = _sessiya(muhit["claude"])
    f = next((muhit["claude"] / "projects").rglob(f"{sid}.jsonl"))
    hozir = datetime(2026, 11, 20, 21, 30, tzinfo=asos.TZ)
    os.utime(f, (hozir.timestamp() - 600, hozir.timestamp() - 600))      # 10 daqiqa jim
    r = sessiyalar.yigish(asos.Yozuvchi(muhit["vault"]), hozir=hozir.timestamp())
    assert r["hisob"].get("faol") == 1 and sid not in r["holat"]
    assert xulosa.ishla(r["holat"], muhit["vault"], hozir=hozir) == "yuborildi"
    assert "1 sessiya" in yuborilgan[0] and "Demo sessiya" in yuborilgan[0]
    # kecha yozilgan (imzo eskirgan), bugun davom etgan sessiya ham kiradi
    eski = {sid: {"rel": "claude/sessiyalar/2026-11/x.md", "sarlavha": "Demo sessiya",
                  "sana": ["2026-11-19"], "imzo": [0, 0]}}
    assert "Demo sessiya" in xulosa.xabar(eski, muhit["vault"], "2026-11-20")
    assert sid not in asos.holat_oqi("sessiyalar")             # faqat o'qildi: holatga yozilmadi
    assert not list(muhit["vault"].rglob("claude/sessiyalar/*/*.md"))


def test_xulosa_sinov_kechkisini_bekor_qilmaydi(muhit, monkeypatch):
    yuborilgan = []
    monkeypatch.setattr(xulosa, "yubor", lambda t: yuborilgan.append(t) or True)
    xulosa.sozla(True, "21:30")

    def soat(h, m, kun=26):
        return datetime(2026, 11, kun, h, m, tzinfo=asos.TZ)
    assert xulosa.ishla({}, muhit["vault"], majburiy=True, hozir=soat(16, 0)) == "yuborildi"
    assert xulosa.sozlama()["oxirgi"] == ""                      # sinov kunni band qilmadi
    assert xulosa.ishla({}, muhit["vault"], hozir=soat(21, 30)) == "yuborildi"
    assert xulosa.sozlama()["oxirgi"] == "2026-11-26"
    assert xulosa.ishla({}, muhit["vault"], hozir=soat(22, 36)) == "kerak emas"
    assert len(yuborilgan) == 2
    # ertasi: 21:30 dagisi ketmadi, egasi 21:45 da qo'lda yubordi — soatlik yurish takrorlamasin
    assert xulosa.ishla({}, muhit["vault"], majburiy=True, hozir=soat(21, 45, 27)) == "yuborildi"
    assert xulosa.sozlama()["oxirgi"] == "2026-11-27"
    assert xulosa.ishla({}, muhit["vault"], hozir=soat(22, 13, 27)) == "kerak emas"
    assert len(yuborilgan) == 3


def test_xulosa_yubor_tarmoqni_kutadi(muhit, monkeypatch):
    import io
    import socket
    import types
    import urllib.error
    monkeypatch.setattr(xulosa, "_env", lambda: {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    kutishlar, urinish = [], []
    monkeypatch.setattr(xulosa, "time", types.SimpleNamespace(sleep=kutishlar.append))

    def ochuvchi(*xatolar):
        def urlopen(url, data=None, timeout=None):
            urinish.append(1)
            if len(urinish) <= len(xatolar):
                raise xatolar[len(urinish) - 1]
            return io.BytesIO(b'{"ok": true}')
        return urlopen

    # Mac uyg'ongan, Wi-Fi hali ulanmagan: so'rov ketmagan — kutib, qayta urinadi
    tarmoqsiz = urllib.error.URLError(OSError("tarmoq yo'q"))
    monkeypatch.setattr(xulosa.urllib.request, "urlopen", ochuvchi(tarmoqsiz, tarmoqsiz))
    assert xulosa.yubor("salom") is True and len(urinish) == 3 and kutishlar == [15.0, 15.0]
    # Telegram rad etdi yoki javob yo'lda uzildi (xabar yetgan bo'lishi mumkin) — qayta urinmaydi
    for xato in (urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"description": "x"}')),
                 socket.timeout("javob kelmadi"), ConnectionResetError()):
        urinish.clear()
        monkeypatch.setattr(xulosa.urllib.request, "urlopen", ochuvchi(xato))
        assert xulosa.yubor("salom") is False and len(urinish) == 1


def test_sessiya_sarlavhasi_redakt(muhit):
    tok = "ghp_" + "a" * 36
    uzun = "Q" * 30 + "x9" * 175          # uzun base64'simon sir — sarlavha 70 belgida kesiladi

    def sarlavha(n, sorov, nom=None):
        sid = f"bbbbbbbb-1111-2222-3333-44444444444{n}"
        p = muhit["claude"] / "projects" / "-Users-x-p" / f"{sid}.jsonl"
        yozuv = [{"type": "custom-title", "customTitle": nom, "sessionId": sid}] if nom else []
        yozuv.append({"type": "user", "turnOrigin": "human", "origin": {"kind": "human"}, "sessionId": sid,
                      "timestamp": "2026-11-20T05:00:00Z", "cwd": "/Users/x/p",
                      "message": {"role": "user", "content": sorov}})
        _jsonl(p, yozuv)
        return sessiyalar.sessiya_oqi(p)["sarlavha"]
    s1 = sarlavha(1, f"token {tok} bilan push qil")
    s2 = sarlavha(2, "salom", nom=f"Push {tok}")                       # qo'lda qo'yilgan sarlavha ham
    s3 = sarlavha(3, f"Bu sessiya stringini saqla: {uzun}")            # avval redakt, keyin kesish
    assert "[MAXFIY]" in s1 and tok not in s1
    assert "[MAXFIY]" in s2 and tok not in s2
    assert "[MAXFIY]" in s3 and uzun[:30] not in s3


def test_xulosa_jadval_ornatilmaganda_qoyilmaydi(tmp_path, monkeypatch):
    import plistlib
    import types
    monkeypatch.setattr(asos, "HOME", tmp_path)
    buyruqlar = []
    monkeypatch.setattr(xulosa, "subprocess", types.SimpleNamespace(
        run=lambda args, **k: buyruqlar.append(args) or types.SimpleNamespace(returncode=0, stderr="", stdout="")))
    plist = tmp_path / "Library" / "LaunchAgents" / "com.abba.miya-xulosa.plist"
    s = {"yoqilgan": True, "soat": "21:30"}
    assert "o'rnatilmagan" in xulosa.jadval_yangila(s)               # repo/worktree'ga bog'lanmaydi
    assert not plist.exists() and not any("bootstrap" in a for a in buyruqlar)
    (tmp_path / ".abba-miya" / "miya").mkdir(parents=True)
    assert "21:30" in xulosa.jadval_yangila(s)
    assert plistlib.loads(plist.read_bytes())["WorkingDirectory"] == str(tmp_path / ".abba-miya")
    assert "o'chiq" in xulosa.jadval_yangila({"yoqilgan": False, "soat": "21:30"}) and not plist.exists()


def test_main_soat_xulosasiz_xato(muhit):
    from miya import __main__ as kirish
    with pytest.raises(SystemExit) as e:
        kirish.main(["--soat", "21:30"])
    assert e.value.code == 2 and xulosa.sozlama()["yoqilgan"] is False


def test_main_xulosa_xatosi_logni_buzmaydi(muhit, monkeypatch):
    from miya import __main__ as kirish
    y = asos.Yozuvchi(muhit["vault"])
    monkeypatch.setattr(kirish, "yig", lambda **k: {"yozuvchi": y, "natijalar": {}, "xatolar": {}, "sh": {}})

    def portlash(*a, **k):
        raise RuntimeError("sinov")
    monkeypatch.setattr(xulosa, "ishla", portlash)
    assert kirish.main([]) == 0
    log = (muhit["tmp"] / "miya.log").read_text(encoding="utf-8")
    assert "xulosa=xato (RuntimeError)" in log and "xulosa XATO" in log


def test_main_xulosa_korish_faol_sessiyani_korsatadi(muhit, monkeypatch, capsys):
    from miya import __main__ as kirish
    sid = _sessiya(muhit["claude"])
    f = next((muhit["claude"] / "projects").rglob(f"{sid}.jsonl"))
    ts = datetime(2026, 11, 20, 21, 20, tzinfo=asos.TZ).timestamp()
    os.utime(f, (ts, ts))
    monkeypatch.setattr(asos, "bugun", lambda: "2026-11-20")
    assert kirish.main(["--xulosa-korish"]) == 0
    assert "Demo sessiya" in capsys.readouterr().out


def test_hublar_bosh_sahifa(muhit):
    y = asos.Yozuvchi(muhit["vault"])
    sh = {"s1": {"rel": "claude/sessiyalar/2026-11/a.md", "sarlavha": "A", "boshi": "2026-11-20 10:00",
                 "oxiri": "2026-11-20 11:00", "sana": ["2026-11-20"], "loyiha": "demo", "sorovlar": 2}}
    hublar.oy_indekslari(y, sh)
    hublar.baselar(y)
    hublar.bosh_sahifa(y, sh, {"sessiyalar": 1})
    t = (muhit["vault"] / "BOSH-SAHIFA.md").read_text(encoding="utf-8")
    assert "[[claude/sessiyalar/2026-11/a|A]]" in t and "![[tizim/Claude sessiyalari.base]]" in t
    base = (muhit["vault"] / "tizim" / "Claude sessiyalari.base").read_text(encoding="utf-8")
    assert base.startswith(asos.BELGI_BASE)


def test_jadvaldagi_havola_quvuri():
    m = "| [[kod/a|A]] | x |\n- [[kod/a|A]] ro'yxatda\n"
    r = asos.jadval_havolalari(m)
    assert r.splitlines()[0] == "| [[kod/a\\|A]] | x |"
    assert r.splitlines()[1] == "- [[kod/a|A]] ro'yxatda"
