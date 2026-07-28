#!/usr/bin/env python3
"""SMM "Undiruv <oy>" tabini parse qilib, kunlik hisobot uchun jamlaydi.

Tab tuzilmasi (header 2-qatorda): № | Nomi | Ma'sul shaxs | Summa (qoldiq) |
Undirildi | Aktive Summary | Final data (to'lov muddati, KK.OO) | To'lov xolati.
"Jami"/"Ehtimoli aktive" qatorlari jadval tugaganini bildiradi.

Sheet'ning o'z jami mantiqi: Kelishilgan = Σqoldiq + Σundirildi (Aktive Summary
alohida "ehtimoliy" pul sifatida yuritiladi — kelishilganga qo'shilmaydi).
"""
import re
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import diff as diffmod
import fetch as fetchmod

MONEY_RE = re.compile(r"[-\d.,]+")
DDMM_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})$")
DUE_SOON_DAYS = 4


def log(msg):
    print(f"[undiruv] {msg}", flush=True)


def money(v):
    """"$1 800" / "1 800,50" → float. Bo'sh/matn → 0."""
    s = str(v).replace("\xa0", "").replace(" ", "").replace(" ", "")
    m = MONEY_RE.search(s)
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return 0.0


def parse_due(v, today):
    """"06.07" (KK.OO) → date (joriy yil). "0"/bo'sh/boshqa → None."""
    m = DDMM_RE.match(str(v).strip())
    if not m:
        return None
    dd, mm = int(m.group(1)), int(m.group(2))
    try:
        return date(today.year, mm, dd)
    except ValueError:
        return None


def _col(header, *needles):
    """Avval aniq (norm==needle), keyin substring moslik."""
    normed = [fetchmod.norm(h) for h in header]
    for nd in needles:
        for i, n in enumerate(normed):
            if n == nd:
                return i
        for i, n in enumerate(normed):
            if n and nd in n:
                return i
    return None


def _status(v):
    n = fetchmod.norm(v)
    if "qilindi" in n or "✅" in str(v):
        return "paid"
    if "pauza" in n or "⏸" in str(v):
        return "pauza"
    if "ketdi" in n or "⛔" in str(v):
        return "ketdi"
    return "pending"


STATUS_LABEL = {"paid": "Undirildi ✅", "pauza": "Pauza ⏸", "ketdi": "Ketdi ⛔",
                "pending": "Kutilmoqda"}


def parse_rows(vals, today):
    """Tab qiymatlari → [{loyiha, pm, qoldiq, undirildi, aktiv, kelishilgan,
    muddat: date|None, holat}]. Jami/summary qatorlari kirmaydi."""
    h = diffmod.detect_header(vals)
    header = [str(x) for x in (vals[h] if vals else [])]
    c_name = _col(header, "nomi")
    c_pm = _col(header, "shaxs")
    c_left = _col(header, "summa")
    c_paid = _col(header, "undirildi")
    c_active = _col(header, "aktive")
    c_due = _col(header, "final")
    c_status = _col(header, "xolati")
    if c_name is None or c_paid is None:
        return []
    rows = []
    for row in vals[h + 1:]:
        get = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""
        first = fetchmod.norm(get(0))
        name = get(c_name)
        if first == "jami" or fetchmod.norm(name).startswith("ehtimoli"):
            break  # jadval tugadi — pastda yig'indi bloklari
        if not name:
            continue
        qoldiq, undirildi, aktiv = money(get(c_left)), money(get(c_paid)), money(get(c_active))
        rows.append({
            "loyiha": name,
            "pm": get(c_pm) or "—",
            "qoldiq": qoldiq,
            "undirildi": undirildi,
            "aktiv": aktiv,
            "kelishilgan": (qoldiq + undirildi) if (qoldiq or undirildi) else aktiv,
            "muddat": parse_due(get(c_due), today),
            "holat": _status(get(c_status)),
        })
    return rows


def find_tab(snap, today=None):
    """Snapshot'dagi joriy oy "Undiruv <oy>" range kaliti (topilmasa None)."""
    want = f"undiruv {fetchmod.current_month_name(today)}"
    for rng in snap.get("ranges", {}):
        if fetchmod.norm(fetchmod.tab_of_range(rng)) == want:
            return rng
    return None


def load_rows(day, today=None):
    """Kun snapshotidan undiruv qatorlari. Qaytaradi: (rows, tab_nomi) yoki ([], None)."""
    today = today or date.fromisoformat(day)
    for snap in diffmod.load_day(day)[0].values():
        if snap.get("pm_kpi", True):
            continue
        rng = find_tab(snap, today)
        if rng:
            vals = snap["ranges"][rng].get("values", [])
            return parse_rows(vals, today), fetchmod.tab_of_range(rng)
    return [], None


def _fmt_usd(v):
    return f"${v:,.0f}".replace(",", " ")


def _due_str(d):
    return f"{d.day:02d}.{d.month:02d}" if d else "—"


def summary(day, today=None):
    """report.json uchun 'undiruv' bloki. Ma'lumot bo'lmasa None."""
    today = today or date.fromisoformat(day)
    rows, tab = load_rows(day, today)
    if not rows:
        return None
    kelishilgan = sum(r["qoldiq"] + r["undirildi"] for r in rows)
    undirildi = sum(r["undirildi"] for r in rows)
    qoldiq = sum(r["qoldiq"] for r in rows)
    aktiv = sum(r["aktiv"] for r in rows)

    def unpaid(r):
        return r["holat"] not in ("paid", "ketdi") and (r["qoldiq"] > 0 or r["aktiv"] > 0)

    def item(r):
        return {
            "pm": r["pm"], "loyiha": r["loyiha"],
            "summa": round(r["qoldiq"] or r["aktiv"]),
            "muddat": _due_str(r["muddat"]),
            "kun": (today - r["muddat"]).days if r["muddat"] else None,
        }

    overdue = sorted(
        (item(r) for r in rows if unpaid(r) and r["muddat"] and r["muddat"] < today),
        key=lambda x: -(x["kun"] or 0),
    )
    soon = sorted(
        (item(r) for r in rows
         if unpaid(r) and r["muddat"] and 0 <= (r["muddat"] - today).days <= DUE_SOON_DAYS),
        key=lambda x: x["muddat"],
    )
    return {
        "oy": fetchmod.current_month_name(today),
        "tab": tab,
        "kelishilgan": round(kelishilgan),
        "undirildi": round(undirildi),
        "qoldiq": round(qoldiq),
        "aktiv": round(aktiv),
        "pct": round(undirildi / kelishilgan * 100, 1) if kelishilgan else 0.0,
        "muddat_otgan": overdue,
        "muddat_yaqin": soon,
    }


def _group_pm(items):
    by = {}
    for it in items:
        g = by.setdefault(it["pm"], [])
        g.append(it)
    return by


def report_block(day, today=None):
    """report.md oxiriga qo'shiladigan matn bloki (Telegram matn-fallback va
    Obsidian arxiv uchun). Ma'lumot bo'lmasa bo'sh satr."""
    s = summary(day, today)
    if not s:
        return ""
    L = [
        f"💰 **Undiruv ({s['oy']})** — {s['tab']}",
        f"Kelishilgan {_fmt_usd(s['kelishilgan'])} · undirildi {_fmt_usd(s['undirildi'])} "
        f"({str(s['pct']).replace('.', ',')}%) · qoldiq {_fmt_usd(s['qoldiq'])}"
        + (f" · aktiv {_fmt_usd(s['aktiv'])}" if s["aktiv"] else ""),
    ]
    if s["muddat_otgan"]:
        tot = sum(i["summa"] for i in s["muddat_otgan"])
        L.append(f"⏰ Muddati o'tgan, undirilmagan: {len(s['muddat_otgan'])} loyiha, {_fmt_usd(tot)}:")
        for pm, items in _group_pm(s["muddat_otgan"]).items():
            det = ", ".join(f"{i['loyiha']} ({_fmt_usd(i['summa'])}, {i['muddat']})" for i in items)
            L.append(f"  • {pm}: {det}")
    if s["muddat_yaqin"]:
        det = ", ".join(
            f"{i['loyiha']} ({i['pm']}, {_fmt_usd(i['summa'])}, {i['muddat']})"
            for i in s["muddat_yaqin"]
        )
        L.append(f"🔜 Muddati ≤{DUE_SOON_DAYS} kun: {det}")
    if not s["muddat_otgan"] and not s["muddat_yaqin"]:
        L.append("⏰ Muddati o'tgan yoki yaqin qolgan undirilmagan loyiha yo'q ✅")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--json", action="store_true", help="summary'ni JSON ko'rinishida chiqarish")
    args = ap.parse_args()
    if args.json:
        print(json.dumps(summary(args.date), ensure_ascii=False, indent=1))
    else:
        print(report_block(args.date) or "(undiruv ma'lumoti topilmadi)")
