"""format_kb_source_block testlari (manba havolasi bug fix).

Telegram <a href> ichida faqat http/https/tg:// — obsidian:// rad etiladi (400) →
manba HAVOLA QILINMAYDI: yo'l <code> ichida, obsidian:// nusxalanadigan <code> qator.
.md — Moldova TLD → <code> tashqarisida avtolink bo'ladi, shuning uchun <code> shart.

pytest tests/test_send.py  yoki  python3 tests/test_send.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import send as sendmod   # noqa: E402


def test_source_no_anchor_and_code():
    ans, html = sendmod.format_kb_source_block(
        "Javob matni shu yerda.\nManba: bilim/PM-KPI-qoidalari.md", vault="claude-brain")
    assert "Javob matni shu yerda." in ans
    assert "Manba:" not in ans                                   # «Manba» qatori ajratildi
    assert "<a href" not in html and "<a " not in html           # HAVOLA umuman yo'q
    assert "<code>bilim/PM-KPI-qoidalari.md</code>" in html       # yo'l <code> ichida
    assert "obsidian://open?vault=claude-brain&amp;file=bilim%2FPM-KPI-qoidalari" in html
    # md_to_html'dan o'tsa ham <a> paydo bo'lmaydi (avtolinkka tushmaydi)
    assert "<a href" not in (sendmod.md_to_html(ans) + html)


def test_source_urlencode_space_and_uzbek_apostrophe():
    p = "bilim/PM KPI qoʻidalari.md"          # bo'shliq + o'zbek apostrofi ʻ (U+02BB)
    _, html = sendmod.format_kb_source_block(f"J.\nManba: {p}", vault="claude brain")
    file_part = html.split("&amp;file=")[1].split("</code>")[0]
    assert "%20" in file_part                 # bo'shliq → %20
    assert " " not in file_part               # file param'da xom bo'shliq yo'q
    assert "%CA%BB" in file_part              # ʻ (U+02BB) → %CA%BB
    assert "vault=claude%20brain" in html      # vault nomi (env'dan) ham kodlangan
    assert "<a href" not in html


def test_source_apostrophe_and_backtick_in_name():
    p = "kunlik/o'zbek`fayl.md"                # ' va ` — <code> buzilmasin (xom HTML)
    _, html = sendmod.format_kb_source_block(f"J.\nManba: {p}", vault="claude-brain")
    assert "<a href" not in html
    assert "%27" in html and "%60" in html     # ' → %27, ` → %60
    assert "<code>kunlik/o'zbek`fayl.md</code>" in html   # ko'rinishda xom yo'l


def test_source_max_three_plus_n():
    ans = "Javob.\nManbalar: bilim/a.md, bilim/b.md, bilim/c.md, bilim/d.md, bilim/e.md"
    _, html = sendmod.format_kb_source_block(ans, vault="v")
    assert html.count("obsidian://") == 3      # eng ko'pi 3 ta
    assert "+2 ta manba" in html


def test_source_without_md_extension():
    _, html = sendmod.format_kb_source_block(
        "J.\nManba: bilim/PM-KPI-qoidalari", vault="v")   # .md siz kelsa
    assert "<code>bilim/PM-KPI-qoidalari.md</code>" in html   # ko'rinishda .md qo'shiladi
    assert "file=bilim%2FPM-KPI-qoidalari" in html            # file .md siz


def test_nonpath_manba_kept_unchanged():
    # path-siz «Manba» (yuklangan hujjat nomi) — o'zgarmasdan javobda qoladi
    ans, html = sendmod.format_kb_source_block("Javob.\nManba: Yillik hisobot", vault="v")
    assert "Manba: Yillik hisobot" in ans
    assert html == ""


def test_no_manba_line():
    ans, html = sendmod.format_kb_source_block("Faqat javob, manba yo'q.", vault="v")
    assert html == "" and ans == "Faqat javob, manba yo'q."


def test_never_raises_on_bad_input():
    ans, html = sendmod.format_kb_source_block(None, vault="v")   # None → except → (ans,"")
    assert html == "" and ans is None


def test_bold_manba_marker_parsed():
    # model qalin qilib yozsa ham («**Manba:**») ajratiladi
    _, html = sendmod.format_kb_source_block("J.\n**Manba:** bilim/x.md", vault="v")
    assert "<code>bilim/x.md</code>" in html and "<a href" not in html


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
