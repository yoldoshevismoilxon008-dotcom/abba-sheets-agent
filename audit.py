#!/usr/bin/env python3
"""Data audit — sheet'lardagi ma'lumot sifatini deterministik tekshiradi,
keyin (ixtiyoriy) Claude xulosa/takliflar beradi.

Tekshiruvlar (Python, deterministik):
  - bo'sh majburiy kataklar: manager, reyting, shartnoma muddati, tugash sanasi
  - yilsiz sanalar ("15.12" — qaysi yil?)
  - raqam kutilgan joyda matn (reyting, ball ustunlari)
  - Jami=0, lekin ball yig'indisi bor
  - nomsiz (loyiha nomi bo'sh) lekin to'ldirilgan qatorlar
  - tab'lararo nomuvofiqlik: oy tabida bor, Main'da yo'q loyihalar (va aksincha)
  - Main tabi umuman yo'qligi (strukturaviy)

Rejimlar:
  audit.py                          # jonli o'qish, to'liq md hisobot stdout'ga
  audit.py --from-snapshot DATE     # snapshot'dan (tarmoqsiz)
  audit.py --out FILE               # hisobotni faylga yozish
  audit.py --critical-line          # faqat 1 qatorlik kritik xulosa (bo'lsa)
  audit.py --no-claude              # faqat deterministik qism
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import analyze
import diff as diffmod
import fetch as fetchmod

AUDIT_PROMPT = BASE / "prompts" / "audit.md"

NUM_RE = re.compile(r"^[-+]?[\d\s.,]+%?$")
NOYEAR_RE = re.compile(r"^\d{1,2}[./]\d{1,2}$")

CRIT = "critical"
WARN = "warning"

import os as _os

DATA = Path(_os.environ.get("DATA_DIR") or (BASE / "data"))
ACK_FILE = DATA / "audit-acknowledged.yaml"

# Topilma kalitlari (barqaror — /ack shu kalitlar bilan ishlaydi)
KEY_LABELS = {
    "main-tab-yoq": "Main tabi yo'q",
    "oy-tab-yoq": "Joriy oy tabi yo'q",
    "nomsiz-qator": "Nomsiz to'ldirilgan qator",
    "manager-bosh": "Manager katagi bo'sh",
    "reyting-bosh": "Reyting bo'sh",
    "reyting-raqam-emas": "Reyting raqam emas",
    "shartnoma-bosh": "Shartnoma muddati bo'sh",
    "tugash-bosh": "Tugash sanasi bo'sh",
    "sana-yilsiz": "Yilsiz sana",
    "jami-nol": "Jami=0, ball bor",
    "ball-raqam-emas": "Ball raqam emas",
    "oy-mainda-yoq": "Oy tabida bor, Main'da yo'q",
    "mainda-oy-yoq": "Main'da bor, oy tabida yo'q",
}


def load_acked():
    """data/audit-acknowledged.yaml → [{key, sheet?, date, note}]"""
    import yaml

    if not ACK_FILE.exists():
        return []
    try:
        data = yaml.safe_load(ACK_FILE.read_text(encoding="utf-8")) or {}
        return [e for e in (data.get("acknowledged") or []) if e.get("key")]
    except Exception as e:
        log(f"acknowledged.yaml o'qilmadi: {e}")
        return []


def add_ack(key, note=""):
    """Yangi ack yozuvi qo'shadi (bot /ack buyrug'i uchun)."""
    import yaml
    from datetime import date as _date

    entries = load_acked()
    if any(e["key"] == key and not e.get("sheet") for e in entries):
        return False
    entries.append({"key": key, "date": _date.today().isoformat(), "note": note or ""})
    ACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACK_FILE.write_text(
        "# Tan olingan audit muammolari — hisobotlarda KRITIK deb takrorlanmaydi.\n"
        "# key: topilma turi (audit.KEY_LABELS), sheet: ixtiyoriy (faqat shu sheet),\n"
        "# date: qachondan, note: izoh. /ack buyrug'i shu faylga yozadi.\n"
        + yaml.safe_dump({"acknowledged": entries}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


def match_ack(finding, entries):
    _sheet, _tab, _lvl, _msg, key = finding
    for e in entries:
        if e.get("key") == key and (not e.get("sheet") or e.get("sheet") == _sheet):
            return e
    return None


def split_acked(findings):
    """(yangi topilmalar, [(topilma, ack_yozuvi), ...])"""
    entries = load_acked()
    fresh, acked = [], []
    for f in findings:
        e = match_ack(f, entries)
        (acked.append((f, e)) if e else fresh.append(f))
    return fresh, acked


def log(msg):
    print(f"[audit] {msg}", file=sys.stderr, flush=True)


def find_col(header, *needles):
    """Sarlavhadan ustunni topadi (substring, normalizatsiya bilan)."""
    for i, h in enumerate(header):
        n = fetchmod.norm(h)
        if n and any(nd in n for nd in needles):
            return i
    return None


def cell(row, idx):
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def is_num(v):
    return bool(NUM_RE.match(v.replace(" ", ""))) if v else False


def nonzero(v):
    return bool(re.search(r"[1-9]", v))


# Oy tab'lari pastidagi oylik/koeffitsiyent bloklarining belgi-so'zlari:
# shu qatorga yetganda jadval tugagan hisoblanadi
MARKER_CELLS = {
    "kpi turi", "joriy kpi", "proekt manager", "kechikish kun", "kechga qolish",
    "o'rtacha ball", "meetinglar", "yangi mijozlar 1 hafta", "narvon", "shablon",
    "proekt", "limit",
}
SUM_ROW_MAX = 150  # bitta loyiha bali bundan katta bo'lmaydi — kattasi yig'indi qatori


def _is_marker_row(row):
    cells = {fetchmod.norm(c) for c in row if str(c).strip()}
    if cells & MARKER_CELLS:
        return True
    if any("oyligi" in c for c in cells):
        return True
    if {"summa", "fix"} <= cells or {"limit", "foiz"} <= cells:
        return True
    return False


def _numval(v):
    try:
        return float(v.replace("\xa0", "").replace(" ", "").replace(",", ".").rstrip("%"))
    except (ValueError, AttributeError):
        return None


def data_rows(vals):
    """(header, [(real_qator_raqami, row), ...]) — jadvalning HAQIQIY qatorlari.
    Birinchi to'liq bo'sh qator yoki oylik-blok markeri = jadval tugadi."""
    h = diffmod.detect_header(vals)
    header = [str(x) for x in (vals[h] if vals else [])]
    rows = []
    for n, row in enumerate(vals[h + 1:], start=h + 2):
        if not any(str(c).strip() for c in row):
            break
        if _is_marker_row(row):
            break
        rows.append((n, row))
    return header, rows


def audit_main_tab(sheet_name, vals, findings):
    header, rows = data_rows(vals)
    c_name = find_col(header, "loyihalar", "loyiha nomi")
    c_rate = find_col(header, "reyting")
    c_mgr = find_col(header, "manager")
    c_contract = find_col(header, "shartnoma")
    c_end = find_col(header, "tugash")
    c_jami = next((i for i, h in enumerate(header) if fetchmod.norm(h) == "jami"), None)
    c_ball = find_col(header, "ball yeg", "ball yig")

    names = set()
    for n, row in rows:
        name = cell(row, c_name)
        filled = sum(1 for c in row if str(c).strip())
        if not name:
            ball = _numval(cell(row, c_ball)) or _numval(cell(row, c_jami))
            if filled >= 2 and (ball is None or ball < SUM_ROW_MAX):
                findings.append((sheet_name, "Main", CRIT, f"{n}-qator: loyiha nomi bo'sh, lekin qator to'ldirilgan", "nomsiz-qator"))
            continue
        names.add(fetchmod.norm(name))
        if c_mgr is not None and not cell(row, c_mgr):
            findings.append((sheet_name, "Main", CRIT, f"«{name}» ({n}-q): manager bo'sh", "manager-bosh"))
        rate = cell(row, c_rate)
        if c_rate is not None:
            if not rate:
                findings.append((sheet_name, "Main", CRIT, f"«{name}» ({n}-q): reyting bo'sh", "reyting-bosh"))
            elif not is_num(rate):
                findings.append((sheet_name, "Main", CRIT, f"«{name}» ({n}-q): reyting raqam emas: {rate!r}", "reyting-raqam-emas"))
        contract = cell(row, c_contract)
        if c_contract is not None and not contract:
            findings.append((sheet_name, "Main", WARN, f"«{name}» ({n}-q): shartnoma muddati bo'sh", "shartnoma-bosh"))
        end = cell(row, c_end)
        if c_end is not None:
            if not end:
                if "har oy" not in fetchmod.norm(contract):
                    findings.append((sheet_name, "Main", WARN, f"«{name}» ({n}-q): tugash sanasi bo'sh", "tugash-bosh"))
            elif NOYEAR_RE.match(end):
                findings.append((sheet_name, "Main", WARN, f"«{name}» ({n}-q): tugash sanasi yilsiz: {end!r}", "sana-yilsiz"))
        jami = cell(row, c_jami)
        ball = cell(row, c_ball)
        if c_jami is not None and c_ball is not None and jami and not nonzero(jami) and nonzero(ball):
            findings.append((sheet_name, "Main", CRIT, f"«{name}» ({n}-q): Jami=0, lekin ball yig'indisi {ball!r}", "jami-nol"))
    return names


def audit_month_tab(sheet_name, tab, vals, findings):
    header, rows = data_rows(vals)
    c_proj = find_col(header, "proekt nomi", "proekt")
    c_ideal = find_col(header, "ideal")
    c_fact = find_col(header, "proekt bali")
    names = set()
    for n, row in rows:
        name = cell(row, c_proj)
        scores = [cell(row, c_ideal), cell(row, c_fact)]
        if not name:
            nums = [x for x in (_numval(s) for s in scores) if x is not None]
            # katta qiymatlar — yig'indi (jami) qatori, muammo emas
            if any(nonzero(s) for s in scores) and (not nums or max(nums) < SUM_ROW_MAX):
                findings.append((sheet_name, tab, CRIT, f"{n}-qator: proekt nomi bo'sh, lekin ballari bor", "nomsiz-qator"))
            continue
        names.add(fetchmod.norm(name))
        for label, idx in (("Kpi ideal bali", c_ideal), ("Proekt bali", c_fact)):
            v = cell(row, idx)
            if idx is not None and v and not is_num(v):
                findings.append((sheet_name, tab, CRIT, f"«{name}» ({n}-q): {label} raqam emas: {v!r}", "ball-raqam-emas"))
    return names


def audit_sheet(snap, findings):
    """Bitta sheet snapshot'i (ranges + tabs) ustida barcha tekshiruvlar."""
    if not snap.get("pm_kpi", True):
        return  # PM KPI formatida emas (masalan SMM) — Main/oy tekshiruvlari yot
    name = snap.get("name", snap.get("id", "?"))
    ranges = snap.get("ranges", {})
    by_tab = {fetchmod.tab_of_range(r): r for r in ranges}
    tabs = snap.get("tabs") or list(by_tab.keys())

    main_tab = next((t for t in tabs if fetchmod.norm(t) == "main"), None)
    month = fetchmod.current_month_name()
    month_tabs = [t for t in tabs if fetchmod.norm(t) == month]
    month_tab = month_tabs[-1] if month_tabs else None

    main_names = None
    if main_tab is None:
        findings.append((name, "—", CRIT, "Main tabi topilmadi (o'chirilganmi?) — loyihalar reyestri va deadline'lar yo'q", "main-tab-yoq"))
    elif main_tab in by_tab:
        main_names = audit_main_tab(name, ranges[by_tab[main_tab]].get("values", []), findings)

    month_names = None
    if month_tab is None:
        findings.append((name, "—", CRIT, f"Joriy oy ({month.capitalize()}) tabi topilmadi", "oy-tab-yoq"))
    elif month_tab in by_tab:
        month_names = audit_month_tab(name, month_tab, ranges[by_tab[month_tab]].get("values", []), findings)

    if main_names is not None and month_names is not None:
        for p in sorted(month_names - main_names):
            findings.append((name, month_tab, CRIT, f"«{p}» oy tabida bor, lekin Main'da YO'Q (KPI bog'lanmaydi)", "oy-mainda-yoq"))
        for p in sorted(main_names - month_names):
            findings.append((name, "Main", WARN, f"«{p}» Main'da bor, lekin joriy oy tabida yo'q", "mainda-oy-yoq"))


def gather(from_snapshot=None):
    """Snapshot'lardan yoki jonli o'qishdan sheet ma'lumotlarini yig'adi."""
    if from_snapshot:
        sheets = diffmod.load_day(from_snapshot)[0]
        if not sheets:
            raise RuntimeError(f"{from_snapshot} uchun snapshot topilmadi")
        return list(sheets.values()), f"snapshot: {from_snapshot}"
    gc = fetchmod.gclient()
    out = []
    for s in fetchmod.load_config():
        name = s.get("name", s["id"])
        try:
            ranges, meta = fetchmod.fetch_sheet(gc, s)
            out.append({"id": s["id"], "name": name, "ranges": ranges,
                        "tabs": meta["tabs"], "pm_kpi": s.get("pm_kpi", True)})
        except Exception as e:
            log(f"'{name}' o'qilmadi: {str(e)[:150]}")
    if not out:
        raise RuntimeError("birorta ham sheet o'qilmadi")
    return out, "jonli holat"


def run_checks(from_snapshot=None):
    snaps, source = gather(from_snapshot)
    findings = []
    for snap in snaps:
        audit_sheet(snap, findings)
    return findings, source


def render(findings, source, today):
    """Yangi topilmalar to'liq, tan olinganlari — bitta qisqa qator (kalit bo'yicha
    guruhlangan). Qaytadi: (matn, YANGI kritiklar ro'yxati)."""
    fresh, acked = split_acked(findings)
    crit = [f for f in fresh if f[2] == CRIT]
    warn = [f for f in fresh if f[2] == WARN]
    L = [f"🧪 **Data audit** ({today}, manba: {source})", ""]
    if not findings:
        L.append("Hammasi toza — muammo topilmadi ✅")
        return "\n".join(L), crit
    if fresh:
        L.append(f"Yangi topilmalar: {len(crit)} kritik, {len(warn)} ogohlantirish")
        by_sheet = {}
        for sheet, tab, lvl, msg, _key in fresh:
            by_sheet.setdefault(sheet, []).append((tab, lvl, msg))
        for sheet, items in by_sheet.items():
            L.append(f"\n▸ **{sheet}**")
            for tab, lvl, msg in sorted(items, key=lambda x: 0 if x[1] == CRIT else 1):
                mark = "🔴" if lvl == CRIT else "🟡"
                L.append(f"{mark} [{tab}] {msg}")
    else:
        L.append("Yangi muammo yo'q ✅")
    if acked:
        groups = {}
        for (sheet, _tab, _lvl, _msg, key), e in acked:
            g = groups.setdefault(key, {"sheets": set(), "e": e})
            g["sheets"].add(sheet)
        L.append("")
        L.append("🤝 Tan olingan (kritik ro'yxatdan chiqarilgan):")
        for key, g in groups.items():
            d = str(g["e"].get("date", ""))
            dd = f"{d[8:10]}.{d[5:7]}" if len(d) == 10 else d
            note = f"; {g['e']['note']}" if g["e"].get("note") else ""
            L.append(f"• {KEY_LABELS.get(key, key)} — {len(g['sheets'])} sheet ({dd} dan{note})")
    return "\n".join(L), crit


def save_last(det_text):
    """Oxirgi audit natijasini saqlaydi — Q&A bot doim kontekstda ushlaydi."""
    try:
        (DATA / "last-audit.md").write_text(det_text + "\n", encoding="utf-8")
    except OSError as e:
        log(f"last-audit saqlanmadi: {e}")


def claude_summary(det_text, today):
    kpi_rules, kpi_mode = analyze.kpi_block()
    prompt = (
        AUDIT_PROMPT.read_text(encoding="utf-8")
        .replace("{{DATE}}", today)
        .replace("{{FINDINGS}}", det_text)
        .replace("{{KPI_RULES}}", kpi_rules)
        .replace("{{KPI_MODE}}", kpi_mode)
    )
    return analyze.run_claude(prompt)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-snapshot", metavar="DATE", help="jonli o'rniga snapshot'dan o'qish")
    ap.add_argument("--out", help="hisobotni shu faylga yozish")
    ap.add_argument("--critical-line", action="store_true", help="faqat 1 qatorlik kritik xulosa")
    ap.add_argument("--no-claude", action="store_true", help="Claude xulosasisiz")
    args = ap.parse_args()
    today = date.today().isoformat()

    try:
        findings, source = run_checks(args.from_snapshot)
    except Exception as e:
        if args.critical_line:
            return 0  # kunlik hisobotni buzmaymiz
        log(f"XATO: {e}")
        return 1

    det_text, crit = render(findings, source, today)
    save_last(det_text)

    if args.critical_line:
        if crit:
            sheets = len({f[0] for f in crit})
            print(f"⚠️ Data audit: {len(crit)} kritik topilma ({sheets} sheet) — batafsil: /audit")
        return 0

    report = det_text
    if not args.no_claude and findings:
        try:
            summary = claude_summary(det_text, today)
            report = det_text + "\n\n💡 **Xulosa va takliflar (AI):**\n" + summary
        except Exception as e:
            log(f"Claude xulosa ishlamadi: {e}")
            report += "\n\n(AI xulosa ishlamadi — yuqoridagi deterministik natijalar bilan cheklandi)"

    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        log(f"yozildi: {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
