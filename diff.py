#!/usr/bin/env python3
"""Bugungi snapshotni eng oxirgi oldingi snapshot bilan solishtiradi.

Qator darajasida: kalit sifatida birinchi ustun (yoki config'dagi key_column —
ustun sarlavhasi yoki 1-based raqam) ishlatiladi.

Natija: data/snapshots/YYYY-MM-DD/diff.json
  sheets.<id>.ranges.<range> = {added, removed, changed, header, stats, ...}
Oldingi snapshot umuman bo'lmasa — baseline rejimi (birinchi kun).
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import os

BASE = Path(__file__).resolve().parent
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"

SERVICE_FILES = {"_meta.json", "diff.json", "report.json", "report-live.json"}


def log(msg):
    print(f"[diff] {msg}", flush=True)


def col_letter(i):
    """0-based indeks → A, B, ... Z, AA, AB..."""
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def colname(header, i):
    if i < len(header) and str(header[i]).strip():
        return str(header[i]).strip()
    return f"{col_letter(i)}-ustun"


def detect_header(vals, scan=6):
    """Sarlavha qatori indeksini topadi: birinchi ~6 qator ichida eng ko'p
    to'ldirilgan katakli qator (sheet'larda 1-qator ko'pincha bo'sh/URL)."""
    best, best_n = 0, -1
    for i, row in enumerate(vals[:scan]):
        n = sum(1 for c in row if str(c).strip())
        if n > best_n:
            best, best_n = i, n
    return best


def load_day(day):
    """Kun papkasidagi barcha sheet snapshotlarini id bo'yicha qaytaradi."""
    sheets, meta = {}, {}
    d = SNAPSHOTS / day
    if not d.is_dir():
        return sheets, meta
    meta_path = d / "_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    for p in sorted(d.glob("*.json")):
        if p.name in SERVICE_FILES:
            continue
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
            sheets[snap["id"]] = snap
        except Exception as e:
            log(f"o'qib bo'lmadi: {day}/{p.name} — {e}")
    return sheets, meta


def prev_day(today):
    """Bugundan oldingi, ichida sheet snapshotlari bor eng oxirgi kun."""
    if not SNAPSHOTS.is_dir():
        return None
    days = []
    for x in SNAPSHOTS.iterdir():
        if not (x.is_dir() and len(x.name) == 10 and x.name < today):
            continue
        if any(f.name not in SERVICE_FILES for f in x.glob("*.json")):
            days.append(x.name)
    return max(days) if days else None


def key_index(header, key_column):
    if isinstance(key_column, int):
        return max(0, key_column - 1)
    if isinstance(key_column, str) and key_column.strip():
        want = key_column.strip().lower()
        for i, h in enumerate(header):
            if str(h).strip().lower() == want:
                return i
        log(f"ogohlantirish: key_column '{key_column}' sarlavhada topilmadi — 1-ustun olindi")
    return 0


def row_map(values, kidx, start_row=2):
    """Header'dan keyingi qatorlar: kalit → qator. Bo'sh/takror kalitlar ham deterministik."""
    out, dup = {}, {}
    for n, row in enumerate(values, start=start_row):
        if not any(str(c).strip() for c in row):
            continue
        key = str(row[kidx]).strip() if kidx < len(row) else ""
        if not key:
            key = f"(bo'sh kalit, {n}-qator)"
        if key in out:
            dup[key] = dup.get(key, 1) + 1
            key = f"{key} #{dup[key]}"
        out[key] = row
    return out


def diff_range(old_vals, new_vals, key_column):
    ho, hn = detect_header(old_vals), detect_header(new_vals)
    header_old = [str(x) for x in (old_vals[ho] if old_vals else [])]
    header_new = [str(x) for x in (new_vals[hn] if new_vals else [])]
    header = header_new or header_old
    kidx = key_index(header, key_column)

    om = row_map(old_vals[ho + 1:], kidx, start_row=ho + 2)
    nm = row_map(new_vals[hn + 1:], kidx, start_row=hn + 2)
    added = [{"key": k, "row": nm[k]} for k in nm if k not in om]
    removed = [{"key": k, "row": om[k]} for k in om if k not in nm]
    changed = []
    for k, new_row in nm.items():
        old_row = om.get(k)
        if old_row is None:
            continue
        ch = {}
        for i in range(max(len(old_row), len(new_row))):
            va = str(old_row[i]) if i < len(old_row) else ""
            vb = str(new_row[i]) if i < len(new_row) else ""
            if va != vb:
                ch[colname(header, i)] = {"old": va, "new": vb}
        if ch:
            changed.append({"key": k, "changes": ch})

    out = {
        "header": header,
        "added": added,
        "removed": removed,
        "changed": changed,
        "stats": {
            "rows_prev": len(om),
            "rows_now": len(nm),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }
    if header_old and header_new and header_old != header_new:
        out["header_changed"] = {"old": header_old, "new": header_new}
    return out


def baseline_range(vals):
    """Solishtiradigan narsa yo'q: hozirgi holat tavsifi (header + hajm + namuna)."""
    h = detect_header(vals)
    header = [str(x) for x in (vals[h] if vals else [])]
    data = [r for r in vals[h + 1:] if any(str(c).strip() for c in r)]
    return {
        "baseline": True,
        "header": header,
        "sample": data[:5],
        "stats": {"rows_now": len(data), "added": 0, "removed": 0, "changed": 0},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: bugun)")
    args = ap.parse_args()
    today = args.date

    new_sheets, new_meta = load_day(today)
    if not new_sheets:
        log(f"XATO: {today} uchun snapshot yo'q — avval fetch.py ishga tushiring")
        return 1

    prev = prev_day(today)
    old_sheets = load_day(prev)[0] if prev else {}

    result = {
        "date": today,
        "prev_date": prev,
        "baseline": prev is None,
        "fetch_errors": new_meta.get("errors", {}),
        "missing_today": {},
        "sheets": {},
        "totals": {"sheets": 0, "added": 0, "removed": 0, "changed": 0, "header_changed": 0},
    }

    for sid, snap in new_sheets.items():
        entry = {"name": snap.get("name", sid), "watch": snap.get("watch", ""), "ranges": {}}
        old_snap = old_sheets.get(sid)
        if prev is not None and old_snap is None:
            entry["baseline"] = True  # yangi qo'shilgan sheet
        all_ranges = snap.get("ranges", {})
        # Kunlik diff faqat watch range'lar bo'yicha (Main + joriy oy) — shovqin bo'lmasin.
        # Eski (watch_ranges'siz) snapshotlarda hammasi olinadi.
        watch = [r for r in (snap.get("watch_ranges") or all_ranges.keys()) if r in all_ranges]
        for rng in watch:
            vals = all_ranges[rng].get("values", [])
            old_rng = (old_snap or {}).get("ranges", {}).get(rng)
            # key_column skalyar (hamma range uchun) yoki {range: kalit} dict bo'lishi mumkin
            kc = snap.get("key_column", 1) or 1
            if isinstance(kc, dict):
                kc = kc.get(rng, 1)
            if old_snap is None or old_rng is None:
                r = baseline_range(vals)
                if old_snap is not None:
                    r["new_range"] = True
            else:
                r = diff_range(old_rng.get("values", []), vals, kc)
            entry["ranges"][rng] = r
            st = r["stats"]
            for k in ("added", "removed", "changed"):
                result["totals"][k] += st.get(k, 0)
            if "header_changed" in r:
                result["totals"]["header_changed"] += 1
        if old_snap is not None:
            # Faqat sheet'dan chindan yo'qolgan watch range'lar (oy almashishi emas)
            old_watch = [
                r for r in (old_snap.get("watch_ranges") or old_snap.get("ranges", {}).keys())
                if r in old_snap.get("ranges", {})
            ]
            gone = [r for r in old_watch if r not in all_ranges]
            if gone:
                entry["removed_ranges"] = gone
        result["sheets"][sid] = entry

    for sid, old_snap in old_sheets.items():
        if sid not in new_sheets:
            fe = result["fetch_errors"].get(sid, {})
            result["missing_today"][sid] = {
                "name": old_snap.get("name", sid),
                "reason": fe.get("error", "config'dan olib tashlangan yoki o'qilmadi"),
            }

    result["totals"]["sheets"] = len(result["sheets"])

    out_path = SNAPSHOTS / today / "diff.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    t = result["totals"]
    if result["baseline"]:
        log(f"baseline rejim (oldingi snapshot yo'q): {t['sheets']} sheet")
    else:
        log(
            f"{prev} → {today}: {t['sheets']} sheet | "
            f"+{t['added']} yangi, -{t['removed']} o'chgan, ~{t['changed']} o'zgargan"
        )
    log(f"yozildi: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
