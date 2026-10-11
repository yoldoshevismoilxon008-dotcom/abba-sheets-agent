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
sys.path.insert(0, str(BASE))
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"

import re  # noqa: E402

from fetch import norm, tab_of_range  # noqa: E402

SERVICE_FILES = {"_meta.json", "diff.json", "report.json", "report-live.json"}

# Yig'indi bloki boshlanadigan qatorning yorlig'i (Undiruv: A ustunida «Jami»)
JAMI_YORLIQ = {"jami", "jami:", "jamlanma", "итого"}  # tor ro'yxat: undan keyin hammasi pozitsion
# Kalit katagida nom emas, son/summa («$121 610», «58») — harfsiz qiymat
_SON_KALIT_RE = re.compile(r"^[\d\s.,%$€+\-()]+$")
# Tartib raqami ustuni: bunday kalit ustunida son — haqiqiy kalit (nomsiz emas)
RAQAM_USTUN = {"№", "#", "no", "n", "t/r", "т/р", "nomer", "raqam"}


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


def _find_key(header, key_column):
    """Kalit ustuni indeksi; nomli kalit sarlavhada bo'lmasa None."""
    if isinstance(key_column, int):
        return max(0, key_column - 1)
    if isinstance(key_column, str) and key_column.strip():
        want = key_column.strip().lower()
        for i, h in enumerate(header):
            if str(h).strip().lower() == want:
                return i
        return None
    return 0


def key_index(header, key_column, warn=True):
    i = _find_key(header, key_column)
    if i is None:
        if warn:
            log(f"ogohlantirish: key_column '{key_column}' sarlavhada topilmadi — 1-ustun olindi")
        return 0
    return i


def _key_row(vals, key_column, scan=6):
    """Kalit ustuni NOMI turgan birinchi qator indeksi (topilmasa None)."""
    if isinstance(key_column, str) and key_column.strip():
        want = norm(key_column)
        for i, row in enumerate(vals[:scan]):
            if any(norm(c) == want for c in row):
                return i
    return None


def header_index(vals, key_column=None, scan=6):
    """Sarlavha qatori: kalit ustuni NOMI turgan birinchi qator (bor bo'lsa), aks holda
    detect_header. Sarlavhada bitta katak bo'sh qolsa (08.10: «Ishlar nomi» bo'sh) ko'p
    to'ldirilgan ma'lumot qatori sarlavha bo'lib, butun tab siljimasin (audit K7)."""
    i = _key_row(vals, key_column, scan)
    return detect_header(vals, scan) if i is None else i


def _is_jami_row(row, kidx):
    """Kalit ustunigacha (u ham kiradi) birinchi to'ldirilgan katak «Jami» yorlig'imi
    (undiruv.parse_rows bilan bir xil belgi: jadval shu qatorda tugaydi)."""
    for c in row[:kidx + 1]:
        s = norm(c)
        if s:
            return s in JAMI_YORLIQ
    return False


def _son_kalit(key):
    return bool(_SON_KALIT_RE.match(key)) and any(ch.isdigit() for ch in key)


def row_entries(values, kidx, start_row=2, son_kalit_ok=False):
    """Header'dan keyingi qatorlar: [(asosiy_kalit, qator), ...] tartibda (takror bo'lishi mumkin).

    Barqaror kalitlar (audit K6) — kalit qiymati har kuni o'zgarsa diff soxta
    «N yangi, N o'chgan» qator va «qatorlar siljigan» anomaliyasini beradi:
      • «Jami» qatoridan boshlab yig'indi bloki — POZITSION kalit «(jami bloki +k)»: u
        yerdagi «Nomi» katagida summa/son turadi («$121 610», «58»), u kalit bo'lolmaydi;
      • bo'sh yoki harfsiz (son/summa) kalit — oldingi NOMLI qatorga bog'langan kalit
        «(nomsiz qator: «X» dan keyin #k)» — yuqoriga qator qo'shilsa hammasi qayta
        kalitlanmaydi (avval «(bo'sh kalit, 67-qator)» edi);
      • oxirgi nomli qatordan KEYINGI nomsiz qatorlar (Jami yorlig'isiz yig'indi qatorlari:
        Smm main «58», «$83 765») — «(jadval ostida #k)»: pastga loyiha qo'shilsa yoki
        tartib o'zgarsa kaliti o'zgarmaydi.
    son_kalit_ok=True — kalit ustuni tartib raqami («№»): sonlar haqiqiy kalit."""
    items = []                                   # (tur, qiymat, qator): tur 'jami'|'nom'|'nomsiz'
    jami_n = None
    for n, row in enumerate(values, start=start_row):
        if not any(str(c).strip() for c in row):
            continue
        if jami_n is None and _is_jami_row(row, kidx):
            jami_n = n
        if jami_n is not None:
            items.append(("jami", n - jami_n, row))
            continue
        key = str(row[kidx]).strip() if kidx < len(row) else ""
        if key and (son_kalit_ok or not _son_kalit(key)):
            items.append(("nom", key, row))
        else:
            items.append(("nomsiz", None, row))
    oxirgi_nom = max((i for i, it in enumerate(items) if it[0] == "nom"), default=-1)
    out, last, k, ost = [], None, 0, 0
    for i, (tur, val, row) in enumerate(items):
        if tur == "jami":
            out.append((f"(jami bloki +{val})", row))
        elif tur == "nom":
            last, k = val, 0
            out.append((val, row))
        elif i > oxirgi_nom and last is not None:
            ost += 1
            out.append((f"(jadval ostida #{ost})", row))
        else:
            k += 1
            joy = f"«{last}» dan keyin" if last else "boshida"
            out.append((f"(nomsiz qator: {joy} #{k})", row))
    return out


def _sfx(base, i):
    return base if i == 0 else f"{base} #{i + 1}"


def _put(d, key, row):
    """Takrorlanmas kalit bilan yozadi (haqiqiy nom «X #2» suffiksli kalit bilan to'qnashmasin)."""
    k, n = key, 2
    while k in d:
        k, n = f"{key} ({n})", n + 1
    d[k] = row


def row_map(values, kidx, start_row=2):
    """Header'dan keyingi qatorlar: kalit → qator. Bo'sh/takror kalitlar ham deterministik
    (takror nom — tartib bo'yicha «X», «X #2», ...)."""
    out, seen = {}, {}
    for base, row in row_entries(values, kidx, start_row):
        i = seen.get(base, 0)
        seen[base] = i + 1
        _put(out, _sfx(base, i), row)
    return out


def _col_pairs(header_old, header_new):
    """Ustunlar xaritasi. None — kataklar pozitsiya bo'yicha solishtiriladi: sarlavha
    o'zgarmagan YOKI o'zgargan, lekin nomli ustunlar joyidan siljimagan (katak bo'shatilgan
    yoki ustun qayta nomlangan — 08.10 «Ishlar nomi» bo'sh qolgan kunning 18 o'zgarishi
    shu ustunda edi). Ustun qo'shilib/o'chib siljigan bo'lsa (audit K7: 11.08 — 72 yangi +
    72 o'chgan; 27.08 — «Ma'sul shaxs» qo'shildi) ustunlar SARLAVHA NOMI bo'yicha
    juftlanadi: [(nom, old_i, new_i)]. Faqat bir tomonda bor nomli ustun qiyoslanmaydi
    (header_changed'da aytiladi); nomsiz ustunlar _row_changes'da eng yaqin chapdagi nomli
    ustunning siljishi bilan juftlanadi."""
    if not header_old or not header_new or header_old == header_new:
        return None

    def labels(h):
        seen, out = {}, {}
        for i, x in enumerate(h):
            nm = str(x).strip()
            if not nm:
                continue
            seen[nm] = seen.get(nm, 0) + 1
            out[_sfx(nm, seen[nm] - 1)] = i
        return out

    lo, ln = labels(header_old), labels(header_new)
    pairs = [(nm, lo[nm], i) for nm, i in ln.items() if nm in lo]
    if all(io == i for _, io, i in pairs):
        return None                                  # hech narsa siljimagan — pozitsion
    used_o = {io for _, io, _ in pairs}
    used_n = {i for _, _, i in pairs}
    free_o = set(lo.values()) - used_o
    for nm, i in ln.items():
        if i not in used_n and i in free_o:
            pairs.append((nm, i, i))
    return pairs


def _shift(pairs, idx, to_new=True):
    """Nomsiz ustun indeksini boshqa tomonga o'tkazadi: eng yaqin chapdagi nomli juftning
    siljishi bilan (pairs None — o'zgarishsiz)."""
    if pairs is None:
        return idx
    best = None
    for _nm, io, i in pairs:
        a, b = (io, i) if to_new else (i, io)
        if a == idx:
            return b
        if a < idx and (best is None or a > best[0]):
            best = (a, b)
    return idx + (best[1] - best[0]) if best else idx


def _row_changes(old_row, new_row, header, pairs):
    ch = {}
    if pairs is None:
        for i in range(max(len(old_row), len(new_row))):
            va = str(old_row[i]) if i < len(old_row) else ""
            vb = str(new_row[i]) if i < len(new_row) else ""
            if va != vb:
                ch[colname(header, i)] = {"old": va, "new": vb}
        return ch
    used_o = {io for _, io, _ in pairs}
    used_n = {i for _, _, i in pairs}
    for nm, io, i in pairs:
        va = str(old_row[io]) if io < len(old_row) else ""
        vb = str(new_row[i]) if i < len(new_row) else ""
        if va != vb:
            ch[nm] = {"old": va, "new": vb}
    # nomsiz ustunlar va sarlavhadan o'ngdagi kataklar — siljish bilan (yo'qolib qolmasin)
    for io in range(max(len(old_row), len(new_row))):
        if io in used_o:
            continue
        i = _shift(pairs, io)
        if i < 0 or i in used_n:
            continue
        used_n.add(i)
        va = str(old_row[io]) if io < len(old_row) else ""
        vb = str(new_row[i]) if i < len(new_row) else ""
        if va != vb:
            ch[colname(header, i)] = {"old": va, "new": vb}
    return ch


def _match_rows(old_entries, new_entries, header, pairs):
    """old/new qatorlarga kalit beradi → (om, nm). Yagona nom — o'z nomi. Takror nom
    guruhida yangi qatorlar tartib bo'yicha emas, QIYMATLARI eng o'xshash eski qator
    bilan juftlanadi (audit K6): tepaga bir xil nomli qator qo'shilsa eski qator
    «o'zgardi», o'zi «qo'shildi» deb chiqmasin (07.10: «Biboo snack #2»)."""
    og, ng = {}, {}
    for b, r in old_entries:
        og.setdefault(b, []).append(r)
    for b, r in new_entries:
        ng.setdefault(b, []).append(r)
    om, nm = {}, {}
    for b in dict.fromkeys([b for b, _ in old_entries] + [b for b, _ in new_entries]):
        O, N = og.get(b, []), ng.get(b, [])
        for i, r in enumerate(O):
            _put(om, _sfx(b, i), r)
        if not O or (len(O) <= 1 and len(N) <= 1):
            for j, r in enumerate(N):
                _put(nm, _sfx(b, j), r)
            continue
        cand = sorted((len(_row_changes(o, n, header, pairs)), abs(i - j), i, j)
                      for i, o in enumerate(O) for j, n in enumerate(N))
        used_o, got = set(), {}
        for _, _, i, j in cand:
            if i in used_o or j in got:
                continue
            used_o.add(i)
            got[j] = i
        nxt = len(O)
        for j, r in enumerate(N):
            if j in got:
                _put(nm, _sfx(b, got[j]), r)
            else:
                _put(nm, _sfx(b, nxt), r)
                nxt += 1
    return om, _nomsiz_qayta_juftla(om, nm, header, pairs)


def _nomsiz_qayta_juftla(om, nm, header, pairs, max_farq=1):
    """Kaliti siljigan nomsiz qatorlar MAZMUNI bo'yicha qayta juftlanadi: yuqoridagi loyiha
    nomi o'chirilsa ostidagi o'zgarmagan nomsiz qatorlar boshqa «dan keyin» zanjiriga o'tib,
    «o'chgan + yangi» bo'lib chiqmasin. Faqat aynan teng yoki ≤max_farq katak farqli
    qatorlar (aks holda boshqa qatorni «o'zgardi» deb to'qib qo'ymaslik uchun)."""
    rem = [k for k in om if k not in nm and k.startswith("(nomsiz qator")]
    add = [k for k in nm if k not in om and k.startswith("(nomsiz qator")]
    if not rem or not add:
        return nm
    cand = sorted((len(_row_changes(om[a], nm[b], header, pairs)), ia, ib, a, b)
                  for ia, a in enumerate(rem) for ib, b in enumerate(add))
    ren, used = {}, set()
    for farq, _ia, _ib, a, b in cand:
        if farq > max_farq or a in used or b in ren:
            continue
        used.add(a)
        ren[b] = a
    return {ren.get(k, k): v for k, v in nm.items()}


def diff_range(old_vals, new_vals, key_column):
    # Sarlavha qatori kalit ustuni nomi bo'yicha; nom faqat bir tomonda bo'lsa (sarlavha
    # tahrirlangan) ikkinchi tomon ham o'sha qatordan olinadi
    ko, kn = _key_row(old_vals, key_column), _key_row(new_vals, key_column)
    ho = ko if ko is not None else (kn if kn is not None and kn < len(old_vals) else detect_header(old_vals))
    hn = kn if kn is not None else (ko if ko is not None and ko < len(new_vals) else detect_header(new_vals))
    header_old = [str(x) for x in (old_vals[ho] if old_vals else [])]
    header_new = [str(x) for x in (new_vals[hn] if new_vals else [])]
    header = header_new or header_old
    pairs = _col_pairs(header_old, header_new)
    # Kalit ustuni HAR TOMONNING O'Z sarlavhasidan (audit K7): ustun qo'shilsa eski
    # qatorlar boshqa ustun bilan kalitlanib, hammasi «o'chgan + yangi» bo'lib chiqardi.
    # Kalit sarlavhasi faqat bir tomonda bo'lsa (qayta nomlangan/bo'shatilgan) — ikkinchi
    # tomonga ustunlar xaritasi orqali o'tkaziladi, 1-ustunga (№) qaytmaydi.
    kidx_new = _find_key(header, key_column)
    kidx_old = _find_key(header_old or header, key_column)
    if kidx_new is None and kidx_old is None:
        kidx_new = kidx_old = key_index(header, key_column)
    elif kidx_new is None:
        kidx_new = _shift(pairs, kidx_old, to_new=True)
    elif kidx_old is None:
        kidx_old = _shift(pairs, kidx_new, to_new=False)

    def raqam(h, k):
        return k < len(h) and norm(h[k]) in RAQAM_USTUN

    om, nm = _match_rows(
        row_entries(old_vals[ho + 1:], kidx_old, ho + 2, raqam(header_old or header, kidx_old)),
        row_entries(new_vals[hn + 1:], kidx_new, hn + 2, raqam(header, kidx_new)),
        header, pairs)
    added = [{"key": k, "row": nm[k]} for k in nm if k not in om]
    removed = [{"key": k, "row": om[k]} for k in om if k not in nm]
    changed = []
    for k, new_row in nm.items():
        old_row = om.get(k)
        if old_row is None:
            continue
        ch = _row_changes(old_row, new_row, header, pairs)
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
        if snap.get("watch_missing"):
            # Kuzatilishi kerak bo'lgan, lekin topilmagan oy tabi (fetch.expected_month_tab)
            entry["watch_missing"] = list(snap["watch_missing"])
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
        # track_other_tabs (masalan SMM): watch'dan tashqari tab'lar uchun faqat
        # "o'zgardi/o'zgarmadi" (values tengligi) — hisobotda soni ko'rsatiladi,
        # batafsil diff YO'Q (spam bo'lmasin). totals'ga ham QO'SHILMAYDI.
        if snap.get("track_other_tabs") and old_snap is not None:
            changed_tabs = []
            for rng, data in all_ranges.items():
                if rng in watch:
                    continue
                old_rng = old_snap.get("ranges", {}).get(rng)
                if old_rng is not None and old_rng.get("values", []) != data.get("values", []):
                    changed_tabs.append(tab_of_range(rng))
            entry["other_tabs"] = {
                "total": sum(1 for r in all_ranges if r not in watch),
                "changed": changed_tabs,
            }
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
