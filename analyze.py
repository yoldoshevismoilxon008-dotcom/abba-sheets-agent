#!/usr/bin/env python3
"""diff.json'ni ixcham kontekstga aylantirib, `claude -p` bilan tahlil qildiradi.

Kontekstga FAQAT diff + statistika + watch izohlari kiradi (to'liq dump emas).
Natija: data/snapshots/YYYY-MM-DD/report.md

Maxsus holatlar:
  - Hech qanday o'zgarish bo'lmasa — Claude chaqirilmaydi, qisqa hisobot yoziladi.
  - Claude ishlamasa — quruq raqamlardan fallback hisobot yoziladi (kun bo'sh qolmaydi).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"
PROMPT_TPL = BASE / "prompts" / "daily-report.md"

MAX_ROWS = 30      # kontekstda har bo'limdagi maksimal qatorlar
MAX_ROW_CHARS = 260
CLAUDE_TIMEOUT = 600

CLAUDE_FALLBACK_PATHS = [
    "/opt/homebrew/bin/claude",  # macOS (brew)
    "/usr/local/bin/claude",
    "/usr/bin/claude",  # Linux (native installer / paket)
    str(Path.home() / ".claude/local/claude"),
    str(Path.home() / ".local/bin/claude"),
]


def log(msg):
    print(f"[analyze] {msg}", flush=True)


def load_env():
    """CLAUDE_BIN / CLAUDE_MODEL kabi ixtiyoriy sozlamalar uchun .env ni o'qiydi."""
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def trunc(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_row(row, header):
    """Qatorni 'Sarlavha=qiymat; ...' ko'rinishida ixchamlaydi."""
    parts = []
    for i, v in enumerate(row):
        v = str(v).strip()
        if not v:
            continue
        h = str(header[i]).strip() if i < len(header) else ""
        parts.append(f"{h}={trunc(v, 60)}" if h else trunc(v, 60))
    return trunc("; ".join(parts), MAX_ROW_CHARS) or "(bo'sh qator)"


def fmt_changes(changes):
    parts = [f"{col}: «{trunc(v['old'], 60)}» → «{trunc(v['new'], 60)}»" for col, v in changes.items()]
    return trunc("; ".join(parts), MAX_ROW_CHARS)


def build_context(diff):
    L = []
    if diff.get("fetch_errors"):
        L.append("FETCH XATOLARI (bu sheetlar bugun o'qilmadi):")
        for sid, e in diff["fetch_errors"].items():
            L.append(f"- {e.get('name') or sid}: {trunc(e.get('error', ''), 200)}")
    if diff.get("missing_today"):
        L.append("KECHA BOR EDI, BUGUN YO'Q:")
        for sid, m in diff["missing_today"].items():
            L.append(f"- {m['name']}: {trunc(m['reason'], 200)}")

    for sheet in diff["sheets"].values():
        L.append(f"\n=== SHEET: {sheet['name']} ===")
        if sheet.get("watch"):
            L.append(f"E'tibor (watch): {sheet['watch']}")
        if sheet.get("baseline"):
            L.append("(bu sheet uchun birinchi snapshot — solishtirish yo'q)")
        if sheet.get("removed_ranges"):
            L.append(f"O'chirilgan range'lar: {', '.join(sheet['removed_ranges'])}")
        ot = sheet.get("other_tabs")
        if ot and ot.get("changed"):
            L.append(
                f"Kuzatuvdan tashqari tab'lar: {ot['total']} tadan {len(ot['changed'])} tasi "
                f"o'zgargan ({', '.join(ot['changed'][:8])}) — batafsil diff yuritilmaydi, "
                "hisobotda faqat 1 qator eslat."
            )

        for rng, d in sheet["ranges"].items():
            st = d["stats"]
            header = d.get("header", [])
            if d.get("baseline"):
                tag = " (yangi range)" if d.get("new_range") else ""
                L.append(f"[{rng}]{tag} {st['rows_now']} qator. Ustunlar: {', '.join(header) or '—'}")
                for row in d.get("sample", []):
                    L.append(f"  namuna: {fmt_row(row, header)}")
                continue

            L.append(
                f"[{rng}] qatorlar {st['rows_prev']} → {st['rows_now']} | "
                f"yangi: {st['added']}, o'chgan: {st['removed']}, o'zgargan: {st['changed']}"
            )
            if d.get("header_changed"):
                hc = d["header_changed"]
                L.append(f"  DIQQAT — sarlavha qatori o'zgargan: {hc['old']} → {hc['new']}")
            for title, items in (("YANGI QATORLAR", d["added"]), ("O'CHGAN QATORLAR", d["removed"])):
                if not items:
                    continue
                L.append(f"  {title} ({len(items)}):")
                for it in items[:MAX_ROWS]:
                    L.append(f"  - {it['key']}: {fmt_row(it['row'], header)}")
                if len(items) > MAX_ROWS:
                    L.append(f"  - … yana {len(items) - MAX_ROWS} ta")
            if d["changed"]:
                L.append(f"  O'ZGARGAN QATORLAR ({len(d['changed'])}):")
                for it in d["changed"][:MAX_ROWS]:
                    L.append(f"  - {it['key']}: {fmt_changes(it['changes'])}")
                if len(d["changed"]) > MAX_ROWS:
                    L.append(f"  - … yana {len(d['changed']) - MAX_ROWS} ta")
    return "\n".join(L)


def kpi_block():
    """(KPI qoidalari matni, rejim ko'rsatmasi) — barcha prompt'larga qo'shiladi.
    config.yaml dagi kpi_enabled flag pul hisob-kitoblarini ochadi/yopadi."""
    rules_path = BASE / "prompts" / "kpi-qoidalar.md"
    rules = rules_path.read_text(encoding="utf-8").strip() if rules_path.exists() else ""
    if not rules:
        return "(KPI qoidalari fayli hali yo'q)", (
            "KPI qoidalari yo'q — KPI pul/oylik hisob-kitobi so'ralsa, qoidalar hali "
            "kiritilmaganini ayt."
        )
    enabled = False
    try:
        import yaml

        with open(BASE / "config.yaml", encoding="utf-8") as f:
            enabled = bool((yaml.safe_load(f) or {}).get("kpi_enabled"))
    except Exception:
        pass
    if enabled:
        mode = (
            "KPI qoidalari TASDIQLANGAN — KPI summa/oylik hisob-kitobi so'ralsa, "
            "yuqoridagi qoidalar bo'yicha bosqichma-bosqich hisobla (raqamlarni ko'rsatib)."
        )
    else:
        mode = (
            "DIQQAT: KPI qoidalari hali TASDIQLANMAGAN (qoralama, [TEKSHIRILSIN] joylari bor). "
            "Ulardan atama va kontekst sifatida foydalan, LEKIN KPI pul/oylik summasini "
            "HISOBLAB BERMA — bunday savolga: «KPI qoidalari hali tasdiqlanmagan — summa "
            "hisoblay olmayman. Ismoilxon \"KPI tasdiqlayman\" desa yoqiladi» deb javob ber."
        )
    return rules, mode


def find_claude():
    b = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if b:
        return b
    for c in CLAUDE_FALLBACK_PATHS:
        if Path(c).exists():
            return c
    raise RuntimeError("claude CLI topilmadi — .env da CLAUDE_BIN ni ko'rsating")


def run_claude(prompt, effort=None, allowed_tools=None):
    """effort: None (default — settings'dagi max) yoki 'low'..'max'.
    --effort FLAG ishlatiladi — settings.json'dagi global env'ni ham yengadi
    (env-override ishonchsiz: settings o'z qiymatini qaytadan qo'yadi).
    allowed_tools: masalan ["Read"] — vision (rasm o'qish) uchun."""
    cmd = [find_claude(), "-p", "--output-format", "text"]
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    r = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"claude -p xato (kod {r.returncode}): {r.stderr.strip()[:400]}")
    return r.stdout.strip()


def fallback_report(diff, err):
    L = [f"📊 {diff['date']} — Sheets kunlik hisobot (avtomatik)", ""]
    L.append(f"⚠️ AI tahlil ishlamadi ({trunc(err, 160)}). Quruq raqamlar:")
    for sheet in diff["sheets"].values():
        for rng, d in sheet["ranges"].items():
            st = d["stats"]
            if d.get("baseline"):
                L.append(f"▸ {sheet['name']} [{rng}]: birinchi snapshot, {st['rows_now']} qator")
            else:
                L.append(
                    f"▸ {sheet['name']} [{rng}]: +{st['added']} yangi, "
                    f"−{st['removed']} o'chgan, ~{st['changed']} o'zgargan "
                    f"({st['rows_prev']} → {st['rows_now']} qator)"
                )
    for m in (diff.get("missing_today") or {}).values():
        L.append(f"▸ {m['name']}: bugun o'qilmadi — {trunc(m['reason'], 120)}")
    L += other_tabs_note(diff)
    return "\n".join(L)


def is_quiet(diff):
    """Hech narsa o'zgarmagan oddiy kun — Claude'ni bezovta qilmaymiz.
    (track_other_tabs o'zgarishlari quiet'ni buzmaydi — ular hisobotga
    faqat 1 qator eslatma sifatida qo'shiladi.)"""
    t = diff["totals"]
    return (
        not diff.get("baseline")
        and t["added"] == t["removed"] == t["changed"] == 0
        and t.get("header_changed", 0) == 0
        and not diff.get("fetch_errors")
        and not diff.get("missing_today")
        and not any(s.get("baseline") or s.get("removed_ranges") for s in diff["sheets"].values())
    )


def other_tabs_note(diff):
    """track_other_tabs sheet'lari uchun 1 qatorlik eslatmalar ro'yxati."""
    L = []
    for sheet in diff["sheets"].values():
        ot = sheet.get("other_tabs")
        if ot and ot.get("changed"):
            names = ", ".join(ot["changed"][:6])
            more = f" +{len(ot['changed']) - 6}" if len(ot["changed"]) > 6 else ""
            L.append(
                f"▸ {sheet['name']}: kuzatuvdan tashqari {len(ot['changed'])}/{ot['total']} "
                f"tab o'zgargan ({names}{more})"
            )
    return L


def undiruv_block(day):
    """Kunlik hisobot oxiriga qo'shiladigan Undiruv bloki (bo'lmasa bo'sh)."""
    try:
        import undiruv

        return undiruv.report_block(day)
    except Exception as e:
        log(f"undiruv bloki tuzilmadi: {e}")
        return ""


def _day_stats(day):
    """Kun snapshot'idan har sheet uchun {aktiv, ideal, fakt, pct, delay}.
    Lazy importlar — modul davralarini (audit→analyze) buzmaslik uchun."""
    import audit as auditmod
    import diff as diffmod
    import fetch as fetchmod

    out = {}
    for snap in diffmod.load_day(day)[0].values():
        for rng in snap.get("watch_ranges", []):
            tab = fetchmod.tab_of_range(rng)
            if fetchmod.norm(tab) not in fetchmod.MONTHS:
                continue
            vals = snap.get("ranges", {}).get(rng, {}).get("values", [])
            header, rows = auditmod.data_rows(vals)
            ci = auditmod.find_col(header, "ideal")
            cf = auditmod.find_col(header, "proekt bali")
            ck = auditmod.find_col(header, "kechga qolgan", "kech")
            aktiv, si, sf, dl = 0, 0.0, 0.0, 0.0
            for _, row in rows:
                vi = auditmod._numval(auditmod.cell(row, ci)) or 0.0
                vf = auditmod._numval(auditmod.cell(row, cf)) or 0.0
                dl += auditmod._numval(auditmod.cell(row, ck)) or 0.0
                if vi > 0:
                    aktiv += 1
                si += vi
                sf += vf
            out[snap.get("name", "?")] = {
                "aktiv": aktiv, "ideal": round(si, 1), "fakt": round(sf, 1),
                "pct": round(sf / si * 100, 1) if si else 0.0,
                "delay_days": round(dl, 1),
                "delay_pct": round((dl * 3.33 / aktiv), 2) if aktiv else 0.0,
                "fetched_at": snap.get("fetched_at", day),
            }
    return out


def _top_changes(diff_sheet, limit=3):
    L = []
    for rng, d in (diff_sheet.get("ranges") or {}).items():
        for it in d.get("changed", []):
            ch = it.get("changes", {})
            col, v = next(iter(ch.items()), (None, None))
            if col:
                L.append(f"{it['key']}: {col} {v['old']}→{v['new']}" + (f" (+{len(ch) - 1})" if len(ch) > 1 else ""))
        for it in d.get("added", []):
            L.append(f"+ {it['key']}")
        for it in d.get("removed", []):
            L.append(f"− {it['key']}")
    return L[:limit]


def pct_color(pct):
    """KPI chegaralari: ≥90 yashil / 80-90 sariq / 70-80 to'q sariq / <70 qizil."""
    if pct >= 90:
        return "green"
    if pct >= 80:
        return "yellow"
    if pct >= 70:
        return "orange"
    return "red"


def make_insights(report_text):
    """Hisobotdan 2-3 qisqa insight (claude, past effort; yiqilsa bo'sh)."""
    try:
        ans = run_claude(
            "Quyidagi kunlik KPI hisobotidan eng muhim 2-3 ta insight'ni ajrat. "
            "Har biri alohida qatorda, ≤90 belgi, raqam bilan, o'zbekcha. Faqat "
            "qatorlarni yoz, boshqa hech narsa.\n\nHISOBOT:\n" + report_text[:4000],
            effort="low",
        )
        lines = [l.strip("•- ").strip() for l in ans.splitlines() if l.strip()]
        return lines[:3]
    except Exception as e:
        log(f"insights claude xato: {e}")
        return []


def build_report_json(day, diff_dict, report_text, insights=None, out_name="report.json"):
    """PDF renderer uchun tuzilmali ma'lumot: data/snapshots/DAY/<out_name>"""
    import audit as auditmod
    import diff as diffmod

    today_stats = _day_stats(day)
    prev = diff_dict.get("prev_date")
    prev_stats = _day_stats(prev) if prev else {}

    # 7 kunlik trend (mavjud kunlardan)
    days = sorted(
        x.name for x in SNAPSHOTS.iterdir()
        if x.is_dir() and len(x.name) == 10 and x.name <= day
    )[-7:]
    trend = []
    for d in days:
        st = today_stats if d == day else _day_stats(d)
        trend.append({"date": d, "pcts": {n: s["pct"] for n, s in st.items()}})

    try:
        findings, _src = auditmod.run_checks(from_snapshot=day)
        fresh, acked = auditmod.split_acked(findings)
    except Exception as e:
        log(f"audit (json) xato: {e}")
        fresh, acked = [], []
    ack_groups = {}
    for (sheet, _t, _l, _m, key), e in acked:
        g = ack_groups.setdefault(key, {"sheets": set(), "e": e})
        g["sheets"].add(sheet)
    acked_lines = []
    for key, g in ack_groups.items():
        d0 = str(g["e"].get("date", ""))
        dd = f"{d0[8:10]}.{d0[5:7]}" if len(d0) == 10 else d0
        acked_lines.append(f"{auditmod.KEY_LABELS.get(key, key)} — {len(g['sheets'])} sheet ({dd} dan)")

    pms = []
    for name in sorted(today_stats):
        st = today_stats[name]
        pv = prev_stats.get(name, {}).get("pct")
        delta = round(st["pct"] - pv, 1) if pv is not None else None
        dsheet = next(
            (s for s in diff_dict.get("sheets", {}).values() if s.get("name") == name), {}
        )
        pms.append({
            "full": name,
            "name": name.split()[0],
            "aktiv": st["aktiv"], "ideal": st["ideal"], "fakt": st["fakt"],
            "pct": st["pct"], "delay_days": st["delay_days"], "delay_pct": st["delay_pct"],
            "delta": delta,
            "color": pct_color(st["pct"]),
            "top_changes": _top_changes(dsheet),
        })

    t = diff_dict.get("totals", {})
    quiet = not (t.get("added") or t.get("removed") or t.get("changed"))
    data = {
        "date": day,
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "snapshot_time": next(iter(today_stats.values()), {}).get("fetched_at", day),
        "prev_date": prev,
        "totals": {
            "added": t.get("added", 0), "removed": t.get("removed", 0),
            "changed": t.get("changed", 0), "quiet": quiet,
        },
        "pms": pms,
        "trend": trend,
        "new_criticals": [
            f"{s}: {m}" for s, _t2, lvl, m, _k in fresh if lvl == auditmod.CRIT
        ][:6],
        "acknowledged": acked_lines,
        "insights": insights if insights is not None else [],
    }
    try:
        import undiruv as undiruvmod

        data["undiruv"] = undiruvmod.summary(day)
    except Exception as e:
        log(f"undiruv (json) xato: {e}")
        data["undiruv"] = None
    out = SNAPSHOTS / day / out_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{out_name} yozildi ({len(pms)} PM, {len(trend)} kunlik trend)")
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: bugun)")
    args = ap.parse_args()
    load_env()

    day_dir = SNAPSHOTS / args.date
    diff_path = day_dir / "diff.json"
    if not diff_path.exists():
        log(f"XATO: {diff_path} yo'q — avval diff.py ishga tushiring")
        return 1
    diff = json.loads(diff_path.read_text(encoding="utf-8"))
    report_path = day_dir / "report.md"

    if is_quiet(diff):
        names = ", ".join(s["name"] for s in diff["sheets"].values())
        rows = sum(
            r["stats"].get("rows_now", 0) for s in diff["sheets"].values() for r in s["ranges"].values()
        )
        report = (
            f"📊 {args.date} — Sheets kunlik hisobot\n\n"
            f"O'zgarish yo'q. {len(diff['sheets'])} ta sheet ({names}), jami {rows} qator "
            f"tekshirildi — {diff['prev_date']} holatidan farq topilmadi."
        )
        for note in other_tabs_note(diff):
            report += f"\n{note}"
        ub = undiruv_block(args.date)
        if ub:
            report += "\n\n———\n" + ub
        report_path.write_text(report + "\n", encoding="utf-8")
        log("o'zgarish yo'q — Claude chaqirilmadi, qisqa hisobot yozildi")
        try:
            build_report_json(args.date, diff, report, insights=["O'zgarish yo'q — holat barqaror"])
        except Exception as e:
            log(f"report.json yozilmadi (PDF matnsiz qoladi): {e}")
        return 0

    if not PROMPT_TPL.exists():
        log(f"XATO: prompt shabloni yo'q: {PROMPT_TPL}")
        return 1

    if diff.get("baseline"):
        mode = (
            "Bu birinchi kun — solishtiradigan oldingi snapshot yo'q. Har sheet'ning hozirgi "
            "holatini qisqa tavsiflab BASELINE hisobot yoz: nechta qator, qanday ustunlar, "
            "namunalardan ko'zga tashlangan muhim narsalar. Ertadan boshlab o'zgarishlar kuzatilishini ayt."
        )
    else:
        mode = (
            f"Oldingi snapshot ({diff['prev_date']}) va bugun ({diff['date']}) orasidagi "
            "o'zgarishlarni tahlil qil."
        )

    context = build_context(diff)
    kpi_rules, kpi_mode = kpi_block()
    prompt = (
        PROMPT_TPL.read_text(encoding="utf-8")
        .replace("{{DATE}}", diff["date"])
        .replace("{{PREV_DATE}}", str(diff.get("prev_date") or "—"))
        .replace("{{MODE}}", mode)
        .replace("{{KPI_RULES}}", kpi_rules)
        .replace("{{KPI_MODE}}", kpi_mode)
        .replace("{{CONTEXT}}", context)
    )
    log(f"kontekst: {len(context)} belgi, claude -p chaqirilmoqda…")

    try:
        report = run_claude(prompt)
    except Exception as e:
        log(f"OGOHLANTIRISH: {e}")
        log("fallback hisobot yozilyapti (quruq raqamlar)")
        report = fallback_report(diff, str(e))

    ub = undiruv_block(args.date)
    if ub:
        report += "\n\n———\n" + ub
    report_path.write_text(report + "\n", encoding="utf-8")
    log(f"hisobot tayyor: {report_path} ({len(report)} belgi)")
    try:
        build_report_json(args.date, diff, report, insights=make_insights(report))
    except Exception as e:
        log(f"report.json yozilmadi (PDF matnsiz qoladi): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
