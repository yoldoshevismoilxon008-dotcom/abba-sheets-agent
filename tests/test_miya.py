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
    assert "[[wall-e/kunlar/2026-11-24|2026-11-24]]" in (v / "wall-e" / "INDEX.md").read_text(encoding="utf-8")


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
