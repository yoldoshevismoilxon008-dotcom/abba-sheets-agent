#!/usr/bin/env python3
"""report.json → 1 sahifalik A4 infografik PDF (Chrome headless bilan).

  render_pdf.py [--date YYYY-MM-DD] [--json PATH --out PATH] [--keep-html]

Grafiklar tashqi kutubxonasiz: CSS barlar + inline SVG sparkline.
PDF: data/snapshots/DATE/report.pdf. Yiqilsa exit 1 — run.sh matn rejimiga
o'tadi (hisobot hech qachon yo'qolmaydi).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
SNAPSHOTS = DATA / "snapshots"
TEMPLATE_DIR = BASE / "templates"

CHROME_CANDIDATES = [
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux (server)
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/snap/bin/chromium",
]
BRAND = DATA / "brand"
THEMES_DIR = BRAND / "themes"

# To'liq default theme — yaml yetishmagan kalitlar shu yerdan to'ldiriladi
DEFAULT_THEME = {
    "name": "default",
    "style_notes": "",
    "font": '-apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif',
    "page_bg": "#f4f6f9", "card_bg": "#ffffff",
    "text": "#1a1d21", "muted": "#6b7480", "accent": "#3b6fe0",
    "radius": "3mm",
    "card_shadow": "0 0.5mm 2mm rgba(20,30,50,.08)", "card_border": "none",
    "badge_ok": "#1e9e56", "badge_bad": "#d93025", "badge_quiet": "#5f6b7a",
    "kpi_green": "#1e9e56", "kpi_yellow": "#c8a400",
    "kpi_orange": "#e8710a", "kpi_red": "#d93025",
    "bar_track": "#e8ecf1", "grid_line": "#eef1f5",
    "line_colors": ["#3b6fe0", "#d93025", "#e8a400", "#1e9e56"],
}


def active_theme_name():
    try:
        import yaml

        with open(BASE / "config.yaml", encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get("active_theme") or "default")
    except Exception:
        return "default"


def load_theme(name=None):
    """(theme_dict, nomi). Yaml yo'q/buzuq bo'lsa — default."""
    import yaml

    name = name or active_theme_name()
    theme = dict(DEFAULT_THEME)
    p = THEMES_DIR / f"{name}.yaml"
    if p.exists():
        try:
            theme.update({k: v for k, v in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).items() if v is not None})
        except Exception as e:
            log(f"theme '{name}' o'qilmadi ({e}) — default")
            name = "default"
    else:
        if name != "default":
            log(f"theme '{name}' topilmadi — default")
        name = "default" if not p.exists() else name
    theme["name"] = name
    return theme, name


def logo_data_uri():
    """data/brand/logo.* → base64 data URI (draft emas — faqat tasdiqlangan)."""
    import base64

    for ext, mime in (("png", "image/png"), ("svg", "image/svg+xml"),
                      ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("webp", "image/webp")):
        p = BRAND / f"logo.{ext}"
        if p.exists():
            return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    return ""

WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def log(msg):
    print(f"[render_pdf] {msg}", flush=True)


def find_chrome():
    b = os.environ.get("CHROME_BIN", "").strip()
    if b and Path(b).exists():
        return b
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    import shutil

    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        w = shutil.which(name)
        if w:
            return w
    raise RuntimeError("Chrome topilmadi — .env da CHROME_BIN ko'rsating")


def human_date(d):
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return f"{dt.day:02d}.{dt.month:02d}.{dt.year} ({WEEKDAYS[dt.weekday()]})"
    except Exception:
        return d or "—"


def sparkline_points(trend, pm_full, w=300, h=92, pad=6):
    """Trend nuqtalarini SVG polyline koordinatalariga aylantiradi.
    Shkala: 0% → pastki, 100% → yuqori (74px=20%, 18px=80% chiziqlariga mos)."""
    vals = []
    for t in trend:
        v = t.get("pcts", {}).get(pm_full)
        vals.append(v)
    known = [v for v in vals if v is not None]
    if not known:
        return ""
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        if v is None:
            continue
        x = pad + (w - 2 * pad) * (i / max(1, n - 1))
        y = 88 - (max(0.0, min(100.0, v)) * 0.933)  # 0%→88, 100%→~5
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def build_html(data, theme=None, logo_uri=None):
    from jinja2 import Environment, FileSystemLoader

    if theme is None:
        theme, _ = load_theme()
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    tpl = env.get_template("daily-report.html")
    colors = theme.get("line_colors") or DEFAULT_THEME["line_colors"]
    pms = []
    for i, pm in enumerate(data.get("pms", [])):
        pm = dict(pm)
        pm["line_color"] = colors[i % len(colors)]
        pm["spark"] = sparkline_points(data.get("trend", []), pm["full"])
        pms.append(pm)
    trend = data.get("trend", [])
    trend_range = (
        f"{human_date(trend[0]['date']).split(' ')[0]} – {human_date(trend[-1]['date']).split(' ')[0]}"
        if trend else "—"
    )
    return tpl.render(
        pms=pms,
        theme=theme,
        logo_uri=logo_uri if logo_uri is not None else logo_data_uri(),
        totals=data.get("totals", {}),
        new_criticals=data.get("new_criticals", []),
        acknowledged=data.get("acknowledged", []),
        insights=data.get("insights", []),
        date_human=human_date(data.get("date", "")),
        prev_date_human=human_date(data.get("prev_date") or "").split(" ")[0],
        snapshot_time=str(data.get("snapshot_time", ""))[11:16] or data.get("snapshot_time", ""),
        generated_at=data.get("generated_at", ""),
        trend_days=len(trend),
        trend_range=trend_range,
    )


# ---------- Q&A infografik PDF (bot javoblari uchun) ----------

# Semantik rang nomi → theme kaliti (Claude JSON'da faqat shu nomlarni beradi)
QA_COLOR_MAP = {
    "green": "kpi_green", "yellow": "kpi_yellow", "orange": "kpi_orange",
    "red": "kpi_red", "accent": "accent", "muted": "muted",
}
# Raqamli hujayra: ixtiyoriy belgi-prefiks/suffiks (↑↓⚠️ kabi) bilan son
QA_NUMISH_RE = re.compile(r"^[^\w]{0,3}\d[\d\s.,]*%?[^\w]{0,4}$")
QA_LIMITS = {"kpis": 4, "rows": 24, "cols": 8, "bars": 12, "series": 4,
             "points": 24, "warnings": 6, "insights": 5}


def _qa_hex(theme, name, default=None):
    key = QA_COLOR_MAP.get(str(name or "").strip().lower())
    if key:
        return theme.get(key) or DEFAULT_THEME[key]
    return default or theme["accent"]


def _qa_num(v):
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", ".").rstrip("%"))
    except (ValueError, AttributeError):
        return None


def _qa_disp(v):
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _qa_kpis(data, theme):
    out = []
    for k in (data.get("kpis") or [])[: QA_LIMITS["kpis"]]:
        if not isinstance(k, dict):
            continue
        out.append({
            "label": str(k.get("label", ""))[:40],
            "value": str(k.get("value", ""))[:20],
            "sub": str(k.get("sub", ""))[:60],
            "hex": _qa_hex(theme, k.get("color")),
        })
    return out


def _qa_table(data):
    t = data.get("table")
    if not (isinstance(t, dict) and isinstance(t.get("rows"), list) and t.get("rows")):
        return None
    cols = [str(c)[:40] for c in (t.get("columns") or [])][: QA_LIMITS["cols"]]
    width = len(cols) or QA_LIMITS["cols"]
    rows = []
    for r in t["rows"][: QA_LIMITS["rows"]]:
        if not isinstance(r, list):
            continue
        cells = [str(c)[:70] for c in r][:width]
        cells += [""] * (len(cols) - len(cells) if cols else 0)
        rows.append([{"v": c, "num": bool(QA_NUMISH_RE.match(c.strip()))} for c in cells])
    if not rows:
        return None
    # Ustun raqamli hisoblanadi: bo'sh bo'lmagan hujayralarining 70%+ raqamli bo'lsa
    num_cols = []
    for i in range(len(cols)):
        vals = [row[i] for row in rows if i < len(row) and row[i]["v"].strip()]
        num_cols.append(bool(vals) and sum(c["num"] for c in vals) >= 0.7 * len(vals))
    return {"title": str(t.get("title", ""))[:80], "columns": cols, "rows": rows,
            "num_cols": num_cols, "cut_from": len(t["rows"])}


def _qa_bars(data, theme):
    b = data.get("bars")
    if not (isinstance(b, dict) and isinstance(b.get("items"), list)):
        return None
    line_colors = theme.get("line_colors") or DEFAULT_THEME["line_colors"]
    items = []
    for i, it in enumerate(b["items"][: QA_LIMITS["bars"]]):
        if not isinstance(it, dict):
            continue
        v = _qa_num(it.get("value"))
        if v is None:
            continue
        items.append({
            "label": str(it.get("label", "?"))[:30],
            "value": v,
            "display": str(it.get("display") or _qa_disp(v))[:14],
            "note": str(it.get("note", ""))[:26],
            "hex": _qa_hex(theme, it.get("color"), default=line_colors[i % len(line_colors)]),
        })
    if not items:
        return None
    unit = str(b.get("unit", "")).strip()
    vmax = max(it["value"] for it in items)
    scale = 100.0 if unit == "%" and vmax <= 100 else max(vmax, 0.0001)
    for it in items:
        it["width"] = round(max(0.0, min(100.0, it["value"] / scale * 100)), 1)
    return {"title": str(b.get("title", "Solishtirma"))[:80], "items": items,
            "has_notes": any(it["note"] for it in items)}


def _qa_trend(data, theme):
    """(series, grid, xlabels, title) — min-max avtoshkala, null'lar segment uzadi."""
    tr = data.get("trend")
    if not (isinstance(tr, dict) and isinstance(tr.get("series"), list)):
        return [], [], [], ""
    line_colors = theme.get("line_colors") or DEFAULT_THEME["line_colors"]
    labels = [str(x)[:12] for x in (tr.get("labels") or [])][: QA_LIMITS["points"]]
    raw, all_vals, npts = [], [], 0
    for s in tr["series"][: QA_LIMITS["series"]]:
        if not isinstance(s, dict):
            continue
        pts = [_qa_num(p) for p in (s.get("points") or [])[: QA_LIMITS["points"]]]
        if not any(p is not None for p in pts):
            continue
        raw.append({"name": str(s.get("name", "?"))[:20], "points": pts})
        all_vals += [p for p in pts if p is not None]
        npts = max(npts, len(pts))
    if not raw or npts < 2:
        return [], [], [], ""
    vmin, vmax = min(all_vals), max(all_vals)
    if vmax - vmin < 1e-9:
        vmin, vmax = vmin - 1, vmax + 1
    pad = (vmax - vmin) * 0.08
    vmin, vmax = vmin - pad, vmax + pad

    def x(i):
        return 8 + 284 * (i / max(1, npts - 1))

    def y(v):
        return 84 - (max(vmin, min(vmax, v)) - vmin) / (vmax - vmin) * 72

    series = []
    for si, s in enumerate(raw):
        segs, cur, last = [], [], None
        for i, p in enumerate(s["points"]):
            if p is None:
                if len(cur) >= 2:
                    segs.append(" ".join(cur))
                cur = []
                continue
            cur.append(f"{x(i):.1f},{y(p):.1f}")
            last = (round(x(i), 1), round(y(p), 1))
        if len(cur) >= 2:
            segs.append(" ".join(cur))
        if segs or last:
            series.append({"name": s["name"], "color": line_colors[si % len(line_colors)],
                           "segments": segs, "last": last})
    grid = []
    for gy in (14, 48, 82):
        gv = vmin + (84 - gy) / 72 * (vmax - vmin)
        grid.append({"y": gy, "label": _qa_disp(round(gv, 1))})
    xlabels = []
    if labels:
        idx = sorted({0, len(labels) // 2, len(labels) - 1})
        for j, i in enumerate(idx):
            anchor = "start" if i == 0 else ("end" if i == len(labels) - 1 else "middle")
            xlabels.append({"x": round(x(i), 1), "anchor": anchor, "label": labels[i]})
    return series, grid, xlabels, str(tr.get("title", "Trend"))[:80]


def _qa_lines(data, key, limit, maxlen=220):
    return [str(x)[:maxlen] for x in (data.get(key) or [])[:limit] if str(x).strip()]


def build_qa_html(data, theme=None, logo_uri=None):
    """Q&A JSON (Claude'dan) → HTML. Barcha bloklar ixtiyoriy, kirish yumshoq
    normalizatsiya qilinadi — buzuq blok tashlanadi, hujjat baribir chiqadi."""
    from jinja2 import Environment, FileSystemLoader

    if theme is None:
        theme, _ = load_theme()
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    tpl = env.get_template("qa-report.html")
    table = _qa_table(data)
    note = str(data.get("note", "")).strip()[:300]
    if table and table["cut_from"] > len(table["rows"]) and "qisqartirildi" not in note:
        extra = f"Jadval qisqartirildi ({len(table['rows'])}/{table['cut_from']}) — to'liq ro'yxat uchun aniqroq savol bering."
        note = (note + " " + extra).strip()
    series, grid, xlabels, trend_title = _qa_trend(data, theme)
    q = str(data.get("question", "")).strip()
    return tpl.render(
        theme=theme,
        logo_uri=logo_uri if logo_uri is not None else logo_data_uri(),
        title=str(data.get("title") or "Savol-javob")[:90],
        summary=str(data.get("summary", "")).strip()[:600],
        question=(q[:110] + "…") if len(q) > 110 else q,
        asked_at=str(data.get("asked_at", ""))[:16],
        kpis=_qa_kpis(data, theme),
        table=table,
        bars=_qa_bars(data, theme),
        trend_series=series, trend_grid=grid, trend_xlabels=xlabels, trend_title=trend_title,
        warnings=_qa_lines(data, "warnings", QA_LIMITS["warnings"]),
        insights=_qa_lines(data, "insights", QA_LIMITS["insights"]),
        note=note,
        source=str(data.get("source", "—"))[:160],
        generated_at=data.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def render_qa(data, out_pdf, keep_html=False, theme_name=None):
    """Q&A JSON → PDF. Kunlik render() bilan bir xil theme-fallback siyosati."""
    theme, resolved = load_theme(theme_name)
    try:
        return _render_with(data, out_pdf, theme, keep_html, builder=build_qa_html)
    except Exception as e:
        if resolved == "default":
            raise
        log(f"theme '{resolved}' bilan QA render yiqildi ({e}) — default fallback")
        theme, _ = load_theme("default")
        return _render_with(data, out_pdf, theme, keep_html, builder=build_qa_html)


def html_to_pdf(html_path, pdf_path, wait_s=60):
    """Chrome ba'zan PDF yozib bo'lgach ham chiqmaydi (macOS'da kuzatildi) —
    shuning uchun jarayon emas, FAYL kuzatiladi: hajm barqarorlashgach Chrome
    o'ldiriladi."""
    import time as _time

    chrome = find_chrome()
    Path(pdf_path).unlink(missing_ok=True)
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-first-run",
        "--user-data-dir=/tmp/chrome-pdf", "--no-pdf-header-footer",
    ]
    # Server (Linux) muhitida kerak bo'lishi mumkin: CHROME_FLAGS="--no-sandbox"
    cmd += os.environ.get("CHROME_FLAGS", "").split()
    cmd += [f"--print-to-pdf={pdf_path}", f"file://{html_path}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline, last = _time.time() + wait_s, -1
    try:
        while _time.time() < deadline:
            if proc.poll() is not None:
                break
            p = Path(pdf_path)
            if p.exists():
                size = p.stat().st_size
                if size > 5000 and size == last:
                    break  # hajm barqarorlashdi — PDF tayyor
                last = size
            _time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if not (Path(pdf_path).exists() and Path(pdf_path).stat().st_size > 5000):
        raise RuntimeError("Chrome PDF yaratmadi (fayl chiqmadi yoki juda kichik)")


def render(data, out_pdf, keep_html=False, theme_name=None, logo_uri=None):
    """theme_name berilmasa config'dagi active_theme. Yiqilsa DEFAULT bilan
    qayta uriniladi (hisobot hech qachon theme sabab yo'qolmasin)."""
    theme, resolved = load_theme(theme_name)
    try:
        return _render_with(data, out_pdf, theme, keep_html, logo_uri)
    except Exception as e:
        if resolved == "default":
            raise
        log(f"theme '{resolved}' bilan render yiqildi ({e}) — default fallback")
        theme, _ = load_theme("default")
        return _render_with(data, out_pdf, theme, keep_html, logo_uri)


def _render_with(data, out_pdf, theme, keep_html, logo_uri=None, builder=None):
    html = (builder or build_html)(data, theme=theme, logo_uri=logo_uri)
    html_path = Path(str(out_pdf).rsplit(".", 1)[0] + ".html")
    html_path.write_text(html, encoding="utf-8")
    try:
        html_to_pdf(html_path, out_pdf)
    finally:
        if not keep_html:
            try:
                html_path.unlink()
            except OSError:
                pass
    log(f"PDF tayyor: {out_pdf} ({Path(out_pdf).stat().st_size // 1024} KB, theme: {theme.get('name')})")
    return out_pdf


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--json", help="report.json yo'li (default: snapshot papkasidan)")
    ap.add_argument("--out", help="PDF yo'li (default: snapshot papkasiga)")
    ap.add_argument("--theme", help="theme nomi (default: config'dagi active_theme)")
    ap.add_argument("--keep-html", action="store_true")
    args = ap.parse_args()

    jpath = Path(args.json) if args.json else SNAPSHOTS / args.date / "report.json"
    if not jpath.exists():
        log(f"XATO: {jpath} yo'q — avval analyze.py ishga tushiring")
        return 1
    out = Path(args.out) if args.out else SNAPSHOTS / args.date / "report.pdf"
    try:
        data = json.loads(jpath.read_text(encoding="utf-8"))
        render(data, out, keep_html=args.keep_html, theme_name=args.theme)
    except Exception as e:
        log(f"XATO: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
