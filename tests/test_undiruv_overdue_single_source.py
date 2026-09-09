"""Undiruv PDF: «muddat o'tgan» raqami BITTA manbadan (09.09.2026 tekshiruvi).

Bug: PDF ichida ikki mustaqil hisob bor edi —
  • badge/PM-kartochkalari : undiruv.report_data(cur_rows) → pms[*].items[status=overdue]
  • «Push jamlamasi» bloki : pm_push.build_push(cur_rows + prev_real)
build_push o'tgan oy carryover'ini ham bir hisobga qo'shgani uchun bitta hujjatda
zid raqam chiqardi (07.09 real ma'lumotida: badge 5/$10 083, jamlama 6/$10 444).

Endi: build_push joriy oyni `overdue_*`, carryover'ni `overdue_carry_*` da alohida
sanaydi; PDF badge esa raqamni build_push'dan oladi va o'zi qayta hisoblamaydi.

pytest tests/test_undiruv_overdue_single_source.py
  yoki  python3 tests/test_undiruv_overdue_single_source.py
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pm_push as pp   # noqa: E402
import undiruv as u    # noqa: E402
import render_pdf      # noqa: E402

T = date(2026, 9, 9)
CUR_TAB = "Undiruv sentabr(2026)"


def _row(loyiha, qoldiq=1000, muddat=None, pm="Zubair", pm_missing=False,
         pm_col_present=True, holat="pending", undirildi=0, aktiv=0, status_raw="pending",
         lose=0, lose_col_present=True):
    return {
        "loyiha": loyiha, "pm": pm, "pm_missing": pm_missing,
        "pm_col_present": pm_col_present, "qoldiq": qoldiq, "qoldiq_raw": str(qoldiq),
        "undirildi": undirildi, "aktiv": aktiv, "kelishilgan": qoldiq + undirildi,
        "lose": lose, "lose_raw": str(lose) if lose else "",
        "lose_col_present": lose_col_present,
        "status_blank": not status_raw, "muddat": muddat, "muddat_raw": "", "holat": holat,
    }


def _scenario():
    """Ikki tab: joriy oyda 1 ta muddat o'tgan, o'tgan oyda 2 ta ko'chgan qarz."""
    cur = [_row("Li auto", qoldiq=2500, muddat=date(2026, 9, 1), pm="Zubair")]
    prev = [
        _row("Alfa", qoldiq=500, muddat=date(2026, 8, 10), pm="Islom"),
        _row("Beta", qoldiq=294, muddat=date(2026, 8, 20), pm="Islom"),
    ]
    return cur, prev


def _badge_counts(cur_rows):
    """PDF badge/kartochkalari qaysi to'plamdan sanaydi."""
    d = u.report_data(cur_rows, CUR_TAB, T, source="live")
    n = s = 0
    for pm in d.get("pms", []):
        for i in pm.get("items", []):
            if i.get("status") == "overdue":
                n += 1
                s += i.get("summa", 0)
    return d, n, s


# ------------------------------------------------- ikki tab → bitta raqam

def test_ikki_tab_bolganda_ikkala_blok_bir_xil_raqam():
    cur, prev = _scenario()
    _per, stats = pp.build_push(T, cur, prev, "avgust")
    _d, badge_n, badge_s = _badge_counts(cur)
    assert (badge_n, badge_s) == (stats["overdue_n"], stats["overdue_sum"]), (
        f"zid raqam: badge {badge_n}/{badge_s} vs jamlama "
        f"{stats['overdue_n']}/{stats['overdue_sum']}")


def test_carryover_asosiy_hisobga_qoshilmaydi():
    """Regressiya qo'riqchisi: ilgari overdue_n = 1 + 2 = 3 bo'lib ketardi."""
    cur, prev = _scenario()
    _per, stats = pp.build_push(T, cur, prev, "avgust")
    assert stats["overdue_n"] == 1, f"joriy oy 1 ta bo'lishi kerak, keldi {stats['overdue_n']}"
    assert stats["overdue_sum"] == 2500
    assert stats["overdue_carry_n"] == 2, "carryover alohida sanalmadi"
    assert stats["overdue_carry_sum"] == 794


def test_carryover_yoq_bolsa_hisob_ozgarmaydi():
    cur, _prev = _scenario()
    _per, stats = pp.build_push(T, cur, [], "avgust")
    assert (stats["overdue_n"], stats["overdue_sum"]) == (1, 2500)
    assert stats["overdue_carry_n"] == 0 and stats["overdue_carry_sum"] == 0


# ------------------------------------------------- PDF badge chaqiruvchidan oladi

def test_pdf_badge_build_push_raqamini_oladi():
    cur, prev = _scenario()
    _per, stats = pp.build_push(T, cur, prev, "avgust")
    d, _bn, _bs = _badge_counts(cur)
    d = dict(d, overdue_n=stats["overdue_n"], overdue_sum=stats["overdue_sum"])
    html = render_pdf.build_undiruv_html(d, theme=render_pdf.DEFAULT_THEME)
    m = re.search(r"muddat o'tgan\s*(\d+)\s*·\s*\$?\s*([\d\s]+)<", html)
    assert m, "badge HTML'da topilmadi"
    assert int(m.group(1)) == stats["overdue_n"] == 1
    assert m.group(2).replace(" ", "").strip() == "2500"


def test_pdf_badge_berilmasa_ozi_hisoblaydi():
    """Orqaga moslik: overdue_n berilmagan chaqiruvlar (bot /undiruv) buzilmasin."""
    cur, _prev = _scenario()
    d, badge_n, _bs = _badge_counts(cur)
    assert "overdue_n" not in d
    html = render_pdf.build_undiruv_html(d, theme=render_pdf.DEFAULT_THEME)
    m = re.search(r"muddat o'tgan\s*(\d+)\s*·", html)
    assert m and int(m.group(1)) == badge_n == 1


# ------------------------------------------------- jamlama matni

def test_jamlamada_carryover_alohida_korsatiladi():
    cur, prev = _scenario()
    _per, stats = pp.build_push(T, cur, prev, "avgust")
    line = f"⏰ Muddat o'tganlar: {stats['overdue_n']} ta, jami ${stats['overdue_sum']:,.0f}"
    if stats.get("overdue_carry_n"):
        line += f" · + avgust qoldig'i: {stats['overdue_carry_n']} ta"
    assert "1 ta" in line and "+ avgust qoldig'i: 2 ta" in line, line


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
