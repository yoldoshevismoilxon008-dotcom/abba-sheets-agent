"""/miya buyrug'i (miya_buyruq.py) — vault ko'zgusidagi kun yozuvidan Telegram xulosasi."""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import miya_buyruq as mb  # noqa: E402

TZ = ZoneInfo("Asia/Tashkent")
KUN = """---
turi: wall-e-kun
sana: 2026-11-24
manba: miya-avto
---

# WALL-E — 2026-11-24 (seshanba)

> [!info] Avtomatik yozuv

## 🗓️ Kunlik reja va hisobot

**Ertalabki reja** (11:32, boshliqqa yuborildi):
- A ish & <b>teg</b>
- B ish

## 📊 09:00 Sheets hisoboti

- **PM-1 KPI** — 15 qator o'zgargan.

## 🎯 Target va organik obunachilar (ertasi kuni 18:30 hisoboti)

📈 **Target va organik obunachilar — 24.11.2026**
Target: **+3 497** obunachi, 20 loyiha

## 💬 WALL-E bilan suhbat (3 savol)

- 12:36 — undiruv qoldig'i?

## 💻 Shu kuni Claude bilan (1)

- [[claude/sessiyalar/2026-11/2026-11-24 Demo|Demo sessiya]] — papkasiz

## ✍️ Izohlarim
<!-- miya:qo'lda -->
SHAXSIY IZOH
"""


def _klon(tmp_path):
    k = tmp_path / "vault"
    (k / "wall-e" / "kunlar").mkdir(parents=True)
    (k / "wall-e" / "kunlar" / "2026-11-24.md").write_text(KUN, encoding="utf-8")
    return k


def test_sana_ol():
    b = date(2026, 11, 25)
    assert mb.sana_ol([], b) == b
    assert mb.sana_ol(["kecha"], b) == date(2026, 11, 24)
    assert mb.sana_ol(["24.11"], b) == date(2026, 11, 24)
    assert mb.sana_ol(["2026-11-24"], b) == date(2026, 11, 24)
    assert mb.sana_ol(["31.12"], date(2027, 1, 5)) == date(2026, 12, 31)
    assert mb.sana_ol(["31.02"], b) is None
    assert mb.sana_ol(["salom"], b) is None


def test_bizniki_emas():
    assert mb.javob("/miyasiz") is None and mb.javob("/hisobot") is None and mb.javob("") is None


def test_kun_xulosasi(tmp_path):
    k = _klon(tmp_path)
    t = mb.javob("/miya kecha", now=datetime(2026, 11, 25, 10, 0, tzinfo=TZ), klon=k)
    assert "Ikkinchi miya — 24.11.2026" in t
    assert "<b>Ertalabki reja</b>" in t and "A ish &amp; &lt;b&gt;teg&lt;/b&gt;" in t
    assert "<b>PM-1 KPI</b>" in t and "+3 497" in t
    assert "3 savol" in t and "Demo sessiya" in t and "[[" not in t
    assert "SHAXSIY IZOH" not in t                     # egasining izohi chiqmaydi
    assert "obsidian://open?vault=claude-brain" in t and len(t) <= mb.MAKS + 40


def test_yozuv_yoq(tmp_path):
    k = _klon(tmp_path)
    t = mb.javob("/miya", now=datetime(2026, 11, 25, 10, 0, tzinfo=TZ), klon=k)
    assert "hali kelmagan" in t
    t = mb.javob("/miya 01.10", now=datetime(2026, 11, 25, 10, 0, tzinfo=TZ), klon=k)
    assert "yozuv yo'q" in t
    t = mb.javob("/miya", now=datetime(2026, 11, 25, 10, 0, tzinfo=TZ), klon=tmp_path / "bosh")
    assert "/vault_stat" in t


def test_notogri_argument(tmp_path):
    assert "Foydalanish" in mb.javob("/miya ertaga-emas", klon=_klon(tmp_path))
