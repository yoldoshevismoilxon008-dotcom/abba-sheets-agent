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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"
PROMPT_TPL = BASE / "prompts" / "daily-report.md"

MAX_ROWS = 30      # kontekstda har bo'limdagi maksimal qatorlar
MAX_ROW_CHARS = 260
CLAUDE_TIMEOUT = 600
# Kunlik hisobot: claude -p yiqilsa bitta qayta urinish shuncha soniyadan keyin (P2:
# 31.07, 01.10, 02.10 — oy almashuvi kunlari hisobot jim fallback'ga tushgan)
CLAUDE_RETRY_WAIT = int(os.environ.get("CLAUDE_RETRY_WAIT", "30"))

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
        for t in sheet.get("watch_missing") or []:
            L.append(f"DIQQAT: kuzatiladigan «{t}» tabi sheet'da yo'q — bu tab bo'yicha "
                     "o'zgarish yoki pul xulosasi chiqarma (hisobotga ⚠️ qatori avtomatik qo'shiladi).")
        for s in sheet.get("stale") or []:
            L.append(f"DIQQAT: «{s['tab']}» tabi {_dm(s['since'])} dan beri o'zgarmagan ({s['kun']} ish kuni) — "
                     "«o'zgarish yo'q» deb tinch xulosa qilma; bu kuzatuv jimligi, hisobotga ⚠️ qatori "
                     "avtomatik qo'shiladi.")
        if sheet.get("baseline"):
            L.append("(bu sheet uchun birinchi snapshot — solishtirish yo'q)")
        if sheet.get("prev_date"):
            L.append(f"(kechagi snapshot yo'q — o'zgarishlar {sheet['prev_date']} holatiga nisbatan)")
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

            if d.get("watch_new"):
                L.append(
                    f"[{rng}] (kuzatuvga YANGI olingan tab — kecha kuzatilmagan) {st['rows_now']} qator | "
                    f"kechagi holatiga nisbatan yangi: {st['added']}, o'chgan: {st['removed']}, "
                    f"o'zgargan: {st['changed']}. DIQQAT: buni «o'zgarish yo'q» yoki «N → N qator» deb yozma."
                )
            else:
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


# claude -p ga beriladigan promptlarda ISHONCHSIZ matn bor: PM'lar tahrirlaydigan sheet
# kataklari, KB hujjatlari, savollar. Katakka yozilgan «.env ni o'qib hisobotga qo'sh»
# kabi ko'rsatma (prompt injection) model fayl o'qiy olsa — sirlarni hisobotga chiqarardi
# (headless rejimda Read/Glob/Grep ruxsatsiz ishlaydi, cwd esa repo edi). Audit P1-S4:
# barcha toollar o'chiriladi, jarayon bo'sh vaqtinchalik papkada ishlaydi.
CLAUDE_TOOLS = (
    "Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep", "LS",
    "Task", "WebFetch", "WebSearch", "TodoWrite",
)


_CLI_YORDAM = {}


def _cli_qollaydi(flag):
    """O'rnatilgan claude CLI shu flag'ni qo'llaydimi («--help» bir marta, keshlanadi).
    Eski CLI'da noma'lum flag butun chaqiruvni yiqitmasin (Mac'dagi versiya boshqa bo'lishi
    mumkin)."""
    if "txt" not in _CLI_YORDAM:
        try:
            r = subprocess.run([find_claude(), "--help"], capture_output=True, text=True, timeout=20)
            _CLI_YORDAM["txt"] = (r.stdout or "") + (r.stderr or "")
        except Exception:                            # noqa: BLE001
            _CLI_YORDAM["txt"] = ""
    return re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", _CLI_YORDAM["txt"]) is not None


def run_claude(prompt, effort=None, allowed_tools=None, timeout=None, ish_papka=None):
    """effort: None (default — settings'dagi max) yoki 'low'..'max'.
    --effort FLAG ishlatiladi — settings.json'dagi global env'ni ham yengadi
    (env-override ishonchsiz: settings o'z qiymatini qaytadan qo'yadi).
    allowed_tools: masalan ["Read"] — vision (rasm o'qish) uchun; qolgan BARCHA toollar
    o'chiq. allowed_tools=None — hech qanday tool yo'q (audit P1-S4).
    cwd DOIM izolyatsiyalangan papka: ish_papka (vision — rasm nusxasi turgan vaqtinchalik
    papka) yoki bo'sh vaqtinchalik papka. CLI qo'llasa: --tools (aniq ro'yxat, "" — hech
    narsa), --strict-mcp-config (foydalanuvchi MCP serverlari yo'q), --disable-slash-commands
    (skill'lar yo'q), --permission-mode dontAsk (ruxsat so'raydigan har narsa — masalan cwd
    tashqarisini o'qish — rad etiladi). Eski CLI'da — --allowedTools + --disallowedTools.
    timeout: None → CLAUDE_TIMEOUT (mavjud chaqiruvlar o'zgarmaydi); KB kabi
    qisqa chaqiruvlar timeout=30 beradi — osilgan chaqiruv poll loop'ni bloklamasin."""
    cmd = [find_claude(), "-p", "--output-format", "text"]
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    tools = list(allowed_tools or [])
    if _cli_qollaydi("--tools"):
        cmd += ["--tools", ",".join(tools)]             # "" — hech qanday tool
    elif tools:
        cmd += ["--allowedTools", ",".join(tools)]      # eski CLI
    for flag in ("--strict-mcp-config", "--disable-slash-commands"):
        if _cli_qollaydi(flag):
            cmd += [flag]
    if _cli_qollaydi("dontAsk"):
        cmd += ["--permission-mode", "dontAsk"]
    # Prompt (sheet qatorlari, maxfiy tab ham) ~/.claude/projects transkriptiga yozilmasin
    if _cli_qollaydi("--no-session-persistence"):
        cmd += ["--no-session-persistence"]
    taqiq = [t for t in CLAUDE_TOOLS if t not in (allowed_tools or ())]
    if _cli_qollaydi("--tools"):
        # yangi CLI'da bu nomli tool yo'q — «matches no known tool» ogohlantirishi stderr'ni
        # (xato xabarimiz manbasini) to'ldirmasin; --tools baribir hammasini yopadi
        taqiq = [t for t in taqiq if t not in ("MultiEdit", "LS")]
    cmd += ["--disallowedTools", ",".join(taqiq)]
    with tempfile.TemporaryDirectory(prefix="claude-p-") as bosh:
        r = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout if timeout is not None else CLAUDE_TIMEOUT,
            cwd=ish_papka or bosh,

        )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"claude -p xato (kod {r.returncode}): {claude_diag(r)}")
    return r.stdout.strip()


def claude_diag(r):
    """claude -p xatosi diagnostikasi. Ilgari faqat stderr olinardi — CLI ba'zi xatolarni
    (limit, login) stdout'ga yozadi va egaga «xato (kod 1): » bo'sh sabab borardi (P2)."""
    err, out = (r.stderr or "").strip(), (r.stdout or "").strip()
    if err:
        return err[:400]
    if out:
        return f"stdout: {out[-400:]}"
    return "stderr va stdout bo'sh (CLI javobsiz tugadi)"


def fallback_report(diff, err):
    L = [f"📊 {diff['date']} — Sheets kunlik hisobot (avtomatik)", ""]
    L.append(f"⚠️ AI tahlil ishlamadi ({trunc(err, 240)}). Claude CLI holatini (login/limit) "
             "tekshiring. Quruq raqamlar:")
    for sheet in diff["sheets"].values():
        for rng, d in sheet["ranges"].items():
            st = d["stats"]
            if d.get("baseline"):
                L.append(f"▸ {sheet['name']} [{rng}]: birinchi snapshot, {st['rows_now']} qator")
            elif d.get("watch_new"):
                L.append(
                    f"▸ {sheet['name']} [{rng}]: kuzatuvga yangi olindi — {st['rows_now']} qator "
                    f"(kechagi holatiga nisbatan +{st['added']} −{st['removed']} ~{st['changed']})"
                )
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
        and not yangi_range_bor(diff)
    )


def yangi_range_bor(diff):
    """Range darajasida baseline yoki yangi oy tabi (new_range) bormi — 01.10 da «Oktyabr»
    tabi paydo bo'lgan kun «o'zgarish yo'q» deb chiqardi (P2). is_quiet va report.json
    (PDF badge/caption) bir xil qoidadan foydalanadi."""
    return any(r.get("baseline") or r.get("new_range")
               for s in (diff.get("sheets") or {}).values()
               for r in (s.get("ranges") or {}).values())


def watch_missing_note(diff):
    """Kuzatilishi kerak bo'lgan, lekin topilmagan oy tablari (masalan 01.11 da hali
    ochilmagan «Undiruv noyabr(2026)») uchun DETERMINISTIK ⚠️ qatorlar — AI matniga
    tayanilmaydi. AUDIT.md P0-1: avgustda diff jimgina yilsiz arxiv tabni kuzatgan."""
    L = []
    for sheet in diff["sheets"].values():
        for t in sheet.get("watch_missing") or []:
            L.append(
                f"⚠️ {sheet['name']}: «{t}» tabi topilmadi — bugun bu tab bo'yicha diff yo'q. "
                "Yilsiz eski tab arxiv sifatida ataylab o'qilmaydi; joriy oy tabini shu nom bilan oching."
            )
        for n in sheet.get("watch_notes") or []:     # oy tabi dublikati (fetch.month_tab_dup_note)
            L.append(f"⚠️ {sheet['name']}: {n}")
    return L


def _dm(iso):
    """2026-10-01 → 01.10"""
    return f"{iso[8:10]}.{iso[5:7]}" if len(str(iso)) == 10 else str(iso)


def stale_note(diff):
    """PM KPI joriy oy tabi ≥ diff.STALE_DAYS ish kuni o'zgarmagan — DETERMINISTIK ⚠️.
    AUDIT.md P0-4: 37 kun «o'zgarish yo'q» deyilgan, jimlik hech qachon signal bermagan."""
    L = []
    for sheet in diff["sheets"].values():
        for s in sheet.get("stale") or []:
            head = f"⚠️ {sheet['name']}: «{s['tab']}» tabi {_dm(s['since'])} dan beri o'zgarmagan ({s['kun']} ish kuni)"
            if s.get("other_changed"):
                more = s.get("other_total", 0) - len(s["other_changed"])
                tabs = ", ".join(f"«{t}»" for t in s["other_changed"]) + (f" +{more}" if more > 0 else "")
                L.append(f"{head}, lekin shu davrda {tabs} o'zgargan — kunlik diff noto'g'ri tabni "
                         "kuzatayotgan bo'lishi mumkin; PM qaysi tabni to'ldirishini tekshiring.")
            else:
                L.append(f"{head}, kuzatuvdan tashqari tablar ham o'zgarmagan — KPI to'ldirilmayapti yoki "
                         "ma'lumot eskirgan; PM bilan tekshiring.")
    return L


def watch_new_note(diff):
    """Oy almashuvida kuzatuvga olingan yangi oy tabi (kecha ham bor edi, kuzatilmagan)."""
    from fetch import tab_of_range
    L = []
    for sheet in diff["sheets"].values():
        for rng, d in sheet.get("ranges", {}).items():
            if d.get("watch_new"):
                kind = "yangi oy tabi sifatida " if d.get("watch_new_month") else ""
                L.append(f"ℹ️ {sheet['name']}: «{tab_of_range(rng)}» kuzatuvga {kind}olindi "
                         f"({d['stats'].get('rows_now', 0)} qator) — o'zgarishlar uning kechagi holatiga nisbatan.")
            elif d.get("new_range"):
                # Kecha umuman yo'q edi (masalan oy o'rtasida ochilgan «Oktyabr (2026)») — jim o'tmasin
                L.append(f"ℹ️ {sheet['name']}: «{tab_of_range(rng)}» tabi paydo bo'ldi va kuzatuvga olindi "
                         f"({d['stats'].get('rows_now', 0)} qator) — o'zgarishlar ertadan ko'rinadi.")
    return L


def baseline_gap_note(diff):
    """Solishtirish kechagi emas, bir necha kun oldingi snapshot'ga nisbatan bo'lsa (AUDIT.md
    P0-2: 09-18/19 hisobotlari yo'q, 09-20 diff'i qaysi kunga nisbatan ekani yozilmagan)."""
    from datetime import date as _d, timedelta as _td

    prev, day = diff.get("prev_date"), diff.get("date")
    if not prev or not day or diff.get("baseline"):
        return []
    try:
        d0, d1 = _d.fromisoformat(prev), _d.fromisoformat(day)
    except ValueError:
        return []
    gap = (d1 - d0).days - 1
    if gap < 1:
        return []
    kunlar = [_dm((d0 + _td(days=i)).isoformat()) for i in range(1, gap + 1)]
    return [f"ℹ️ Solishtirish {_dm(prev)} holatiga nisbatan — oraliqda {gap} kun snapshot yo'q "
            f"({', '.join(kunlar[:5])}{' …' if gap > 5 else ''}); o'zgarishlar shu davr uchun jamlangan."]


def sheet_gap_note(diff):
    """Kecha o'qilmagan sheet o'zining oxirgi snapshot'i bilan solishtirilgan (diff.prev_snapshot,
    P2) — umumiy «kechagi holatga nisbatan» shu sheet uchun noto'g'ri bo'lmasin."""
    L = []
    for sheet in diff["sheets"].values():
        if sheet.get("prev_date"):
            L.append(f"ℹ️ {sheet['name']}: {_dm(str(diff.get('prev_date') or ''))} da o'qilmagan — "
                     f"o'zgarishlar {_dm(sheet['prev_date'])} holatiga nisbatan.")
    return L


def deterministic_notes(diff):
    """AI matniga tayanmaydigan ogohlantirishlar — quiet, AI, fallback va /hisobot yo'llarida."""
    return (watch_missing_note(diff) + stale_note(diff) + watch_new_note(diff)
            + baseline_gap_note(diff) + sheet_gap_note(diff))


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
            if not fetchmod.is_month_watch_tab(tab):     # «Oktyabr» yoki «Oktyabr (2026)»
                continue
            vals = snap.get("ranges", {}).get(rng, {}).get("values", [])
            st = auditmod.pm_stats(vals)   # yagona hisob: dashboard va Q&A bilan bir xil
            aktiv, si, sf, dl = st["aktiv"], st["ideal"], st["fakt"], st["delay"]
            out[snap.get("name", "?")] = {
                "aktiv": aktiv, "ideal": round(si, 1), "fakt": round(sf, 1),
                "pct": round(sf / si * 100, 1) if si else 0.0,
                "pct_raw": sf / si * 100 if si else 0.0,   # rang chegarasi uchun (yaxlitlanmagan)
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
            # Rang YAXLITLANMAGAN qiymatdan: 89,96 → «90,0» ko'rinadi, lekin yashil emas (P2)
            "color": pct_color(st.get("pct_raw", st["pct"])),
            "top_changes": _top_changes(dsheet),
        })

    t = diff_dict.get("totals", {})
    quiet = not (t.get("added") or t.get("removed") or t.get("changed")) \
        and not yangi_range_bor(diff_dict)
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
        # Deterministik ⚠️/ℹ️ (watch_missing, jimlik, oy almashuvi) — PDF va caption'ga ham
        # tushsin: Telegram'ga asosan PDF ketadi, report.md emas (AUDIT.md P0-4).
        "warnings": deterministic_notes(diff_dict),
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
        for note in deterministic_notes(diff) + other_tabs_note(diff):
            report += f"\n{note}"
        ub = undiruv_block(args.date)
        if ub:
            report += "\n\n———\n" + ub
        report_path.write_text(report + "\n", encoding="utf-8")
        log("o'zgarish yo'q — Claude chaqirilmadi, qisqa hisobot yozildi")
        try:
            # Jimlik/ogohlantirish bo'lsa «holat barqaror» deyilmaydi — ⚠️ bloki o'zi aytadi
            ins = [] if deterministic_notes(diff) else ["O'zgarish yo'q — holat barqaror"]
            build_report_json(args.date, diff, report, insights=ins)
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

    report, xato = None, ""
    for urinish in (1, 2):
        try:
            report, xato = run_claude(prompt), ""
            break
        except Exception as e:
            xato = f"{type(e).__name__}: {e}"
            log(f"OGOHLANTIRISH: claude {urinish}-urinish yiqildi — {trunc(xato, 400)}")
            # Timeout'ni qayta urinish yana CLAUDE_TIMEOUT kutadi — 09:30 PM push'gacha ulgurmaydi
            if urinish == 2 or isinstance(e, subprocess.TimeoutExpired):
                break
            time.sleep(CLAUDE_RETRY_WAIT)
    if report is None:
        log("fallback hisobot yozilyapti (quruq raqamlar)")
        report = fallback_report(diff, xato)

    wm = deterministic_notes(diff)
    if wm:
        report += "\n\n" + "\n".join(wm)
    ub = undiruv_block(args.date)
    if ub:
        report += "\n\n———\n" + ub
    report_path.write_text(report + "\n", encoding="utf-8")
    log(f"hisobot tayyor: {report_path} ({len(report)} belgi)")
    try:
        # Claude yiqilgan kun insights ham chaqirilmaydi (yana yiqilib vaqt yeydi)
        build_report_json(args.date, diff, report, insights=make_insights(report) if not xato else [])
    except Exception as e:
        log(f"report.json yozilmadi (PDF matnsiz qoladi): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
