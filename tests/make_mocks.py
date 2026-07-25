#!/usr/bin/env python3
"""Test uchun mock snapshotlar yaratadi (diff.py + analyze.py ni sinash uchun).

Yaratadi:
  data/snapshots/2026-07-14/  — baseline kun (2 sheet)
  data/snapshots/2026-07-15/  — o'zgarishlar bor kun (ball ↑/↓, deadline surilgan,
                                 yangi qator, o'chgan qator; Byudjet o'zgarmagan)
  data/snapshots/2026-07-16/  — 15-kun bilan aynan bir xil ("o'zgarish yo'q" holati)

Tozalash: rm -rf data/snapshots/2026-07-14 data/snapshots/2026-07-15 data/snapshots/2026-07-16
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SNAPSHOTS = BASE / "data" / "snapshots"

KPI_ID = "mock-kpi-sheet-001"
BUDGET_ID = "mock-budget-sheet-001"

KPI_HEADER = ["Xodim", "KPI ball", "Deadline", "Status", "Izoh"]
KPI_D1 = [
    KPI_HEADER,
    ["Aziza", "92", "2026-07-20", "Jarayonda", "Landing sahifa"],
    ["Bekzod", "78", "2026-07-18", "Jarayonda", "CRM integratsiya"],
    ["Davron", "85", "2026-07-25", "Jarayonda", "Hisobot moduli"],
    ["Gulnora", "88", "2026-07-19", "Tayyor", "Dizayn tizimi"],
]
KPI_D2 = [
    KPI_HEADER,
    ["Aziza", "95", "2026-07-20", "Jarayonda", "Landing sahifa"],
    ["Bekzod", "61", "2026-07-22", "Kechikkan", "CRM integratsiya"],
    ["Gulnora", "88", "2026-07-19", "Tayyor", "Dizayn tizimi"],
    ["Malika", "70", "2026-07-30", "Boshlandi", "Mobil ilova testi"],
]

BUDGET_HEADER = ["Modda", "Reja (mln)", "Fakt (mln)", "Farq"]
BUDGET = [
    BUDGET_HEADER,
    ["Marketing", "50", "42", "-8"],
    ["IT xizmatlar", "30", "31", "+1"],
    ["Ofis", "12", "12", "0"],
]


def snap(sheet_id, name, watch, rng, values, key_column=1):
    return {
        "id": sheet_id,
        "name": name,
        "watch": watch,
        "key_column": key_column,
        "fetched_at": "mock",
        "ranges": {rng: {"actual_range": rng, "values": values}},
    }


def write_day(day, snaps):
    d = SNAPSHOTS / day
    d.mkdir(parents=True, exist_ok=True)
    for s in snaps:
        (d / f"{s['id']}.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    (d / "_meta.json").write_text(
        json.dumps({"date": day, "ok": len(snaps), "errors": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"mock yozildi: {d}")


KPI_WATCH = "KPI ballari, deadline'lar, delay'lar — ball tushganlar va muddati o'tganlarni alohida ko'rsat."
BUDGET_WATCH = "Katta xarajat o'zgarishlari va rejadan oshishlar."

write_day("2026-07-14", [
    snap(KPI_ID, "KPI Tracker", KPI_WATCH, "Sheet1!A1:Z200", KPI_D1),
    snap(BUDGET_ID, "Byudjet", BUDGET_WATCH, "2026!A1:H100", BUDGET),
])
write_day("2026-07-15", [
    snap(KPI_ID, "KPI Tracker", KPI_WATCH, "Sheet1!A1:Z200", KPI_D2),
    snap(BUDGET_ID, "Byudjet", BUDGET_WATCH, "2026!A1:H100", BUDGET),
])
write_day("2026-07-16", [
    snap(KPI_ID, "KPI Tracker", KPI_WATCH, "Sheet1!A1:Z200", KPI_D2),
    snap(BUDGET_ID, "Byudjet", BUDGET_WATCH, "2026!A1:H100", BUDGET),
])
