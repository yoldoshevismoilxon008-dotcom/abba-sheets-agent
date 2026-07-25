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
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
SNAPSHOTS = BASE / "data" / "snapshots"
TEMPLATE_DIR = BASE / "templates"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
BRAND = BASE / "data" / "brand"
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
        f"--print-to-pdf={pdf_path}", f"file://{html_path}",
    ]
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


def _render_with(data, out_pdf, theme, keep_html, logo_uri=None):
    html = build_html(data, theme=theme, logo_uri=logo_uri)
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
