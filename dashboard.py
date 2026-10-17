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
import math
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


def foiz2(x):
    """Bajarilish % — 2 xonaga PASTGA kesiladi (yaxlitlanmaydi): sheet'dagi ≥90 yashil
    qoidasi PDF (yaxlitlanmagan pct_color) bilan bir tomonda qolsin — 89,996 → 89,99, 90,00
    emas (P2). 1e-6 — float shovqini (89,96·100 = 8995,9999…) kesib yuborilmasin."""
    return math.floor(x * 100 + 1e-6) / 100 if isinstance(x, float) else x


def sheet_stats(snap):
    """Snapshot'dagi joriy oy watch tabidan PM statistikasi."""
    for rng in snap.get("watch_ranges", []):
        tab = fetchmod.tab_of_range(rng)
        if not fetchmod.is_month_watch_tab(tab):         # «Oktyabr» yoki «Oktyabr (2026)»
            continue
        vals = snap.get("ranges", {}).get(rng, {}).get("values", [])
        st = auditmod.pm_stats(vals)       # yagona hisob: PDF, Q&A va dashboard bir xil
        return {"tab": tab, "aktiv": st["aktiv"], "ideal": st["ideal"], "fakt": st["fakt"],
                "delay": st["delay"], "ideal_bosh": st["ideal_bosh"]}
    return None


ONE_PCT_MIN_N, ONE_PCT_MAX_N = 6, 16   # qoidadagi jadval faqat shu oraliqni qamraydi


def one_pct_rate(n):
    """1% qiymati: 100k + (n−6)×25k, n — aktiv loyihalar [6..16]. Oraliqdan tashqarida
    None («qoida yo'q»): ilgari qisilardi — n=18 da 350 000 (formula 400 000), n=0 da
    100 000 va prognozda pul chiqardi, qoida esa n<6 / n>16 ni hali belgilamagan (P2)."""
    if not (ONE_PCT_MIN_N <= n <= ONE_PCT_MAX_N):
        return None
    return 100_000 + (n - ONE_PCT_MIN_N) * 25_000


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
        # Bajarilish % — foiz2: sheet'dagi rang qoidasi (≥90 yashil) PDF bilan bir xil
        # tomonda (1 xonada 89,96 → 90,0 yashil bo'lardi, PDF'da sariq) (P2)
        umumiy.append([name, st["aktiv"], num(st["ideal"]), num(st["fakt"]),
                       foiz2(pct), num(st["delay"]), crit, now])
        trend_rows.append([day, name, st["aktiv"], num(st["ideal"]), num(st["fakt"]),
                           foiz2(pct), num(st["delay"]), crit])
        rate = one_pct_rate(st["aktiv"])
        delay_pct = (st["delay"] * 3.33 / st["aktiv"]) if st["aktiv"] else 0.0
        if rate is None:
            # Qoida bu aktiv soni uchun 1% qiymatini bermaydi — taxminiy pul ko'rsatilmaydi
            kpi_prog.append([name, st["aktiv"], f"qoida yo'q (n={st['aktiv']})", num(pct), "—",
                             num(delay_pct, 2), "—", 5_000_000, "—"])
            continue
        ball_comp = max(0.0, pct - 70) * rate
        delay_comp = max(0.0, 10 - delay_pct) * rate
        # 1% qiymati SON bo'lib yoziladi (ilgari "350 000" matni — #,##0 formati ishlamasdi)
        kpi_prog.append([name, st["aktiv"], rate,
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
        view = undiruvmod.korinish(date.fromisoformat(day), day)  # jonli-birinchi, kesh yo'q
        rows, tab, source = view["rows"], view["tab"], view["source"]
    except Exception as e:
        log(f"undiruv o'qilmadi: {e}")
        return None
    if tab is None:
        # Joriy oy tabi topilmadi/o'qilmadi — o'tgan oy jadvali jim qolib ketmasin (review CN8):
        # KPI bloki va push bilan bir xil ogohlantirish
        out = [["UNDIRUV — ⚠️ joriy oy tabi yo'q", "", "", "", "", "", ""]]
        out += [[n, "", "", "", "", "", ""] for n in undiruvmod.izoh_satrlari(view.get("notes") or [])]
        out.append(["Yangilangan", now, "", "", "", "", ""])
        return out
    if not rows:
        sx = undiruvmod.sarlavha_izohlari(view.get("notes"))
        if not sx:
            return None
        # Joriy tabda qator yo'q va sarlavha izohi bor — kechagi jadval jim qolib ketmasin.
        # Sarlavhada tab nomi YO'Q: izoh o'tgan oy tabiniki bo'lishi mumkin (joriy tab yangi
        # ochilgan, bo'sh) — qaysi tab ekanini izoh satrining o'zi aytadi
        out = [["UNDIRUV — ⚠️ tab sarlavhasi o'qilmadi (izoh quyida)", "", "", "", "", "", ""]]
        out += [[n, "", "", "", "", "", ""] for n in undiruvmod.izoh_satrlari(view.get("notes") or [])]
        out.append(["Yangilangan", now, "", "", "", "", ""])
        return out
    today = date.fromisoformat(day)

    def status_label(r):
        # Aktiv obuna (oldindan to'langan) — pul so'ralmaydi, muddat o'tgan
        # hisoblanmaydi
        if undiruvmod.is_active_only(r):
            return "Aktiv obuna 💳"
        if undiruvmod.is_unpaid(r) and r.get("keyingi_oyga"):
            # Oy oxirida keyingi oy tabiga ko'chgan/yopilgan — «muddat o'tdi» emas (PM'dan
            # so'ralmaydi); yopilgani alohida: joriy tabni tuzatish kerak (C2)
            if r["keyingi_oyga"].get("turi") == "yopilgan":
                return "Keyingi oy tabida yopilgan 🧹"
            return "Keyingi oyga ko'chdi 🔁"
        if undiruvmod.is_unpaid(r) and r["muddat"] and r["muddat"] < today:
            return "MUDDAT O'TDI 🔴"
        return undiruvmod.STATUS_LABEL[r["holat"]]

    order = {"MUDDAT O'TDI 🔴": 0, "Kutilmoqda": 1, "Keyingi oyga ko'chdi 🔁": 2,
             "Keyingi oy tabida yopilgan 🧹": 2, "Aktiv obuna 💳": 3, "Pauza ⏸": 4,
             "Ketdi ⛔": 5, "Undirildi ✅": 6}
    src_tag = "  🧊 SNAPSHOT (jonli emas)" if source == "snapshot" else ""
    out = [[f"UNDIRUV — {tab}{src_tag}", "", "", "", "", "", ""], list(HEADERS_UNDIRUV)]
    for r in sorted(rows, key=lambda r: (order.get(status_label(r), 9),
                                         r["muddat"] or today)):
        aktiv_only = undiruvmod.is_active_only(r)
        unpaid = undiruvmod.is_unpaid(r)
        out.append([
            r["pm"], r["loyiha"],
            (round(r["aktiv"]) if aktiv_only else round(r["kelishilgan"])) or "",
            round(r["undirildi"]) or "",
            (round(r["qoldiq"]) if unpaid else "") or "",  # so'raladigan qarz = D
            undiruvmod._due_str(r["muddat"]),
            status_label(r),
        ])
    # YAGONA jamlama manbai — Telegram/PDF bilan aynan mos (undiruv.totals)
    t = undiruvmod.totals(rows)
    pct = f"{str(t['pct']).replace('.', ',')}%" if t["kelishilgan"] else "—"
    out.append([])
    out.append(["JAMI (kelishilgan)", "", t["kelishilgan"], t["undirildi"], t["qoldiq"], "", pct])
    if t["aktiv"]:
        out.append(["Aktiv obuna (so'ralmaydi)", "", t["aktiv"], "", "", "", ""])
    for w in (undiruvmod.status_blank_warn(t), undiruvmod.bad_sum_warn(t)):
        if w:
            out.append([w, "", "", "", "", "", ""])
    # Ega qarori bo'yicha qo'shilgan (jadvalda hali yo'q) qoldiq — JAMI sheet «Jami»sidan
    # shuncha farq qiladi; izohsiz farq chalg'itadi (review M9/C11)
    for r in rows:
        q = r.get("qoshimcha")
        if q and not q.get("jadvalda"):
            out.append([f"📝 Ega qarori: {r['loyiha']} +{q['summa']} ({q.get('oy', '')} qoldig'i) — "
                        f"jadvalda hali yo'q, JAMI shunga farq qiladi", "", "", "", "", "", ""])
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
