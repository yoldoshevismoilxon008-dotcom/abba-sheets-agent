"""Umumiy test izolyatsiyasi.

undiruv_carry (AUDIT P0-3) korinish()/summary() ichida DATA_DIR'dagi oy oxiri report.json va
snapshot'larni o'qiydi hamda DATA_DIR/undiruv_carry/<YYYY-MM>.json ni muzlatadi. Lokal
data/snapshots bo'lsa, mavjud testlar natijasi o'sha ma'lumotga bog'lanib qolmasin va test
repo ichiga holat fayli yozmasin: har test uchun kill switch yoqiladi (xulq 69a8de7 bilan
bir xil) va CARRY_DIR vaqtinchalik papkaga yo'naltiriladi. P0-3 testlari
(test_undiruv_p03.py) kalitni o'zi o'chiradi va SNAPSHOTS'ni ham tmp'ga yo'naltiradi.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import undiruv_carry  # noqa: E402


@pytest.fixture(autouse=True)
def _undiruv_carry_izolyatsiya(monkeypatch, tmp_path):
    monkeypatch.setenv("UNDIRUV_CARRY_OFF", "1")
    monkeypatch.setattr(undiruv_carry, "CARRY_DIR", tmp_path / "carry")
