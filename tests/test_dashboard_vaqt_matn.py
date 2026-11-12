"""Dashboard: surilib turadigan jadvaldagi «Yangilangan» vaqti MATN bo'lib yozilsin.

Bug (12.11): KPI tabida «Yangilangan» vaqti «Aktiv» ustuniga, PM soniga qarab surilib
turadigan qatorga yozilardi. USER_ENTERED uni sana deb tanib, katakka sana formatini
qo'yardi; ws.clear() formatni o'chirmaydi. Keyinroq shu katakka tushgan Aktiv=10 soni
«1900-01-09 0:00» bo'lib ko'rindi. Endi vaqt «'» bilan (matn) yoziladi, sonlar esa son
bo'lib qoladi. Umumiy'dagi «Yangilangan» o'z ustunida — u sana bo'lib qoladi.

pytest tests/test_dashboard_vaqt_matn.py  yoki  python3 tests/test_dashboard_vaqt_matn.py
Tarmoq/kredensial kerak emas.
"""
import contextlib
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="vaqt-matn-test-"))
import audit as auditmod   # noqa: E402
import dashboard           # noqa: E402
import diff as diffmod     # noqa: E402
import undiruv as u        # noqa: E402

VAQT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
HDR = ["№", "Ishlar nomi", "Ma'sul shaxs", "Summa", "Undirildi", "Final sana", "Xolati"]


@contextlib.contextmanager
def _soxta(obj, name, val):
    orig = getattr(obj, name)
    setattr(obj, name, val)
    try:
        yield
    finally:
        setattr(obj, name, orig)


def _yangilangan(rows):
    found = [r for r in rows if r and r[0] == "Yangilangan"]
    assert len(found) == 1, found
    return found[0][1]


def test_matn_vaqt_apostrof_bilan():
    assert dashboard.matn_vaqt("2026-11-12 09:00") == "'2026-11-12 09:00"


def test_kpi_yangilangan_matn_aktiv_esa_son():
    st = {"tab": "Noyabr (2026)", "aktiv": 10, "ideal": 100.0, "fakt": 80.0, "delay": 0.0}
    snap = {"name": "Islom PM KPI", "pm_kpi": True}
    with _soxta(diffmod, "load_day", lambda d: ({"pm1": snap}, {})), \
            _soxta(auditmod, "run_checks", lambda from_snapshot=None: ([], "x")), \
            _soxta(dashboard, "build_undiruv", lambda d, n: None), \
            _soxta(dashboard, "sheet_stats", lambda s: st):
        tabs = dashboard.build("2026-11-12")

    kpi = tabs["kpi"]
    vaqt = _yangilangan(kpi)
    assert vaqt.startswith("'") and VAQT.match(vaqt[1:]), vaqt     # matn — sana formati qo'yilmaydi
    pm = next(r for r in kpi if r and r[0] == "Islom PM KPI")
    assert pm[1] == 10 and isinstance(pm[1], int)                  # Aktiv son bo'lib qoladi
    # Umumiy'da «Yangilangan» qat'iy ustun — u yerda sana bo'lib qoladi
    umumiy_vaqt = tabs["umumiy"][1][7]
    assert not umumiy_vaqt.startswith("'") and VAQT.match(umumiy_vaqt), umumiy_vaqt


def test_undiruv_yangilangan_matn_qatorlar_bilan():
    rows = u.parse_rows([HDR, ["1", "Alfa", "Ali", "$500", "$0", "20.11.2026", ""]],
                        date(2026, 11, 12))
    view = {"tab": "Undiruv noyabr(2026)", "rows": rows, "source": "live", "oy": "noyabr",
            "notes": [], "prev": {"rows": [], "real": []}, "keyingi": None}
    with _soxta(u, "korinish", lambda *a, **k: view):
        out = dashboard.build_undiruv("2026-11-12", "2026-11-12 09:00")
    assert out and _yangilangan(out) == "'2026-11-12 09:00"
    alfa = next(r for r in out if r and r[1] == "Alfa")
    assert alfa[2] == 500 and isinstance(alfa[2], int)              # pul ustuni son bo'lib qoladi


def test_undiruv_yangilangan_matn_tab_yoq_kuni():
    view = {"tab": None, "rows": [], "source": "live", "oy": "noyabr", "notes": [],
            "prev": {"rows": [], "real": []}, "keyingi": None}
    with _soxta(u, "korinish", lambda *a, **k: view):
        out = dashboard.build_undiruv("2026-11-12", "2026-11-12 09:00")
    assert out and _yangilangan(out) == "'2026-11-12 09:00"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
