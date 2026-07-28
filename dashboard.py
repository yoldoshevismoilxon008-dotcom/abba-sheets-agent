#!/usr/bin/env python3
"""Dashboard sheet'ini to'ldiradi (kunlik run oxirida yoki qo'lda).

Tab'lar (SARLAVHALAR BARQAROR — foydalanuvchi grafiklarni qo'lda quradi,
tuzilmani o'zgartirmang!):
  Umumiy — har PM bo'yicha joriy holat (overwrite)
  Trend  — kunlik qatorlar, (Sana, PM) bo'yicha idempotent append
  Audit  — oxirgi audit topilmalari (overwrite)
  KPI    — qoidalar holati, stavkalar, oy yakuni prognozi (overwrite)

Ishlatish:
  dashboard.py [--date YYYY-MM-DD] [--dry-run]
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import audit as auditmod
import diff as diffmod
import fetch as fetchmod

# ⚠️ BARQAROR SARLAVHALAR — o'zgartirish foydalanuvchi grafiklarini buzadi
HEADERS_UMUMIY = ["PM", "Aktiv loyihalar", "Jami ideal", "Jami fakt",
                  "Bajarilish %", "Kechikish kunlari", "Kritik audit", "Yangilangan"]
HEADERS_TREND = ["Sana", "PM", "Aktiv", "Jami ideal", "Jami fakt",
                 "Bajarilish %", "Kechikish", "Kritik"]
HEADERS_AUDIT = ["Sheet", "Tab", "Daraja", "Topilma", "Sana"]
HEADERS_UNDIRUV = ["PM", "Loyiha", "Kelishilgan $", "Undirildi $", "Qoldiq $",
                   "To'lov muddati", "Holat"]


def log(msg):
    print(f"[dashboard] {msg}", flush=True)


def num(x, nd=1):
    return round(x, nd) if isinstance(x, float) else x


def sheet_stats(snap):
    """Snapshot'dagi joriy oy watch tabidan PM statistikasi."""
    for rng in snap.get("watch_ranges", []):
        tab = fetchmod.tab_of_range(rng)
        if fetchmod.norm(tab) not in fetchmod.MONTHS:
            continue
        vals = snap.get("ranges", {}).get(rng, {}).get("values", [])
        header, rows = auditmod.data_rows(vals)
        ci = auditmod.find_col(header, "ideal")
        cf = auditmod.find_col(header, "proekt bali")
        ck = auditmod.find_col(header, "kechga qolgan", "kech")
        aktiv, si, sf, delay = 0, 0.0, 0.0, 0.0
        for _, row in rows:
            vi = auditmod._numval(auditmod.cell(row, ci)) or 0.0
            vf = auditmod._numval(auditmod.cell(row, cf)) or 0.0
            vd = auditmod._numval(auditmod.cell(row, ck)) or 0.0
            if vi > 0:
                aktiv += 1
            si += vi
            sf += vf
            delay += vd
        return {"tab": tab, "aktiv": aktiv, "ideal": si, "fakt": sf, "delay": delay}
    return None


def one_pct_rate(n):
    """1% qiymati: 100k + (n−6)×25k, n [6..16] oralig'iga qisiladi (qoidadagi jadval)."""
    n = max(6, min(16, n))
    return 100_000 + (n - 6) * 25_000


def build(day):
    sheets = diffmod.load_day(day)[0]
    if not sheets:
        raise RuntimeError(f"{day} uchun snapshot yo'q")
    findings, _ = auditmod.run_checks(from_snapshot=day)
    fresh, acked = auditmod.split_acked(findings)
    crit_count = {}
    for sheet, _tab, lvl, _msg, _key in fresh:
        if lvl == auditmod.CRIT:
            crit_count[sheet] = crit_count.get(sheet, 0) + 1

    now = time.strftime("%Y-%m-%d %H:%M")
    umumiy = [list(HEADERS_UMUMIY)]
    trend_rows = []
    kpi_prog = []
    for snap in sorted(sheets.values(), key=lambda s: s.get("name", "")):
        if not snap.get("pm_kpi", True):
            continue  # SMM kabi sheet'lar PM statistikasiga kirmaydi
        name = snap.get("name", "?")
        st = sheet_stats(snap)
        crit = crit_count.get(name, 0)
        if not st:
            umumiy.append([name, "—", "—", "—", "—", "—", crit, now])
            continue
        pct = st["fakt"] / st["ideal"] * 100 if st["ideal"] else 0.0
        umumiy.append([name, st["aktiv"], num(st["ideal"]), num(st["fakt"]),
                       num(pct), num(st["delay"]), crit, now])
        trend_rows.append([day, name, st["aktiv"], num(st["ideal"]), num(st["fakt"]),
                           num(pct), num(st["delay"]), crit])
        rate = one_pct_rate(st["aktiv"])
        ball_comp = max(0.0, pct - 70) * rate
        delay_pct = (st["delay"] * 3.33 / st["aktiv"]) if st["aktiv"] else 0.0
        delay_comp = max(0.0, 10 - delay_pct) * rate
        kpi_prog.append([name, st["aktiv"], f"{rate:,.0f}".replace(",", " "),
                         num(pct), round(ball_comp), num(delay_pct, 2),
                         round(delay_comp), 5_000_000,
                         round(ball_comp + delay_comp + 5_000_000)])

    audit_tab = [list(HEADERS_AUDIT)]
    for sheet, tab, lvl, msg, _key in sorted(fresh, key=lambda f: 0 if f[2] == auditmod.CRIT else 1):
        audit_tab.append([sheet, tab, "KRITIK" if lvl == auditmod.CRIT else "ogohlantirish", msg, day])
    for (sheet, tab, _lvl, msg, _key), e in acked:
        audit_tab.append([sheet, tab, "tan olingan", msg, e.get("date", day)])
    if len(audit_tab) == 1:
        audit_tab.append(["—", "—", "—", "Muammo topilmadi ✅", day])

    undiruv_tab = build_undiruv(day, now)

    kpi_enabled = bool(fetchmod.load_full_config().get("kpi_enabled"))
    kpi_tab = [
        ["KPI QOIDALARI HOLATI", "TASDIQLANGAN" if kpi_enabled else "QORALAMA (kpi_enabled: false)"],
        ["Fix (barcha PM)", "5 000 000"],
        ["1% formulasi", "100 000 + (n−6)×25 000, n=aktiv loyihalar [6..16]"],
        ["Ball komponenti", "(bajarilish% − 70) × 1%_qiymati, manfiy=0"],
        ["Kechikish komponenti", "(10 − kechikish%) × 1%_qiymati, manfiy=0"],
        ["Uchrashuv / Yangi proekt", "soni × 100 000 / soni × 500 000"],
        [],
        ["OY YAKUNI PROGNOZI (taxminiy — uchrashuv/yangi-proekt komponentlarisiz, "
         "kechikish% = Σkun×3,33%/aktiv taxmini bilan)"],
        ["PM", "Aktiv", "1% qiymati", "Bajarilish %", "Ball komp.",
         "Kechikish %", "Kechikish komp.", "Fix", "Prognoz jami"],
    ] + kpi_prog + [
        [],
        ["Yangilangan", time.strftime("%Y-%m-%d %H:%M")],
    ]

    return {"umumiy": umumiy, "trend": trend_rows, "audit": audit_tab, "kpi": kpi_tab,
            "undiruv": undiruv_tab}


def build_undiruv(day, now):
    """SMM "Undiruv <oy>" tabidan dashboard jadvali. Ma'lumot bo'lmasa None
    (tab yozilmaydi — mavjud holati saqlanadi)."""
    import undiruv as undiruvmod

    try:
        rows, tab = undiruvmod.load_rows(day)
    except Exception as e:
        log(f"undiruv o'qilmadi: {e}")
        return None
    if not rows:
        return None
    today = date.fromisoformat(day)

    def status_label(r):
        if r["holat"] == "pending" and r["muddat"] and r["muddat"] < today:
            return "MUDDAT O'TDI 🔴"
        return undiruvmod.STATUS_LABEL[r["holat"]]

    order = {"MUDDAT O'TDI 🔴": 0, "Kutilmoqda": 1, "Pauza ⏸": 2, "Ketdi ⛔": 3,
             "Undirildi ✅": 4}
    out = [[f"UNDIRUV — {tab}", "", "", "", "", "", ""], list(HEADERS_UNDIRUV)]
    for r in sorted(rows, key=lambda r: (order.get(status_label(r), 9),
                                         r["muddat"] or today)):
        out.append([
            r["pm"], r["loyiha"],
            round(r["kelishilgan"]) or "",
            round(r["undirildi"]) or "",
            round(r["qoldiq"] or r["aktiv"]) or "",
            undiruvmod._due_str(r["muddat"]),
            status_label(r),
        ])
    kelishilgan = round(sum(r["qoldiq"] + r["undirildi"] for r in rows))
    undirildi = round(sum(r["undirildi"] for r in rows))
    qoldiq = round(sum(r["qoldiq"] for r in rows))
    aktiv = round(sum(r["aktiv"] for r in rows))
    pct = f"{undirildi / kelishilgan * 100:.1f}%".replace(".", ",") if kelishilgan else "—"
    out.append([])
    out.append(["JAMI (kelishilgan)", "", kelishilgan, undirildi, qoldiq, "", pct])
    if aktiv:
        out.append(["Aktiv (ehtimoliy)", "", aktiv, "", aktiv, "", ""])
    out.append(["Yangilangan", now, "", "", "", "", ""])
    return out


def push(tabs):
    import dashboard_writer as dw

    dw.overwrite_tab("Umumiy", tabs["umumiy"])
    dw.append_rows_idempotent("Trend", list(HEADERS_TREND), tabs["trend"], key_idx=(0, 1))
    dw.overwrite_tab("Audit", tabs["audit"])
    dw.overwrite_tab("KPI", tabs["kpi"])
    if tabs.get("undiruv"):
        dw.overwrite_tab("Undiruv", tabs["undiruv"])
    dw.save_state()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="yozmasdan jadvallarni ko'rsatish")
    args = ap.parse_args()
    try:
        tabs = build(args.date)
    except Exception as e:
        log(f"XATO: build — {e}")
        return 1
    if args.dry_run:
        for name in ("umumiy", "trend", "audit", "kpi", "undiruv"):
            if not tabs.get(name):
                continue
            print(f"\n===== TAB: {name} =====")
            rows = tabs[name] if name != "trend" else [HEADERS_TREND] + tabs[name]
            for r in rows[:25]:
                print(" | ".join(str(c) for c in r))
        return 0
    try:
        push(tabs)
    except Exception as e:
        log(f"XATO: yozish — {type(e).__name__}: {e}")
        return 1
    log("dashboard yangilandi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
