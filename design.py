#!/usr/bin/env python3
"""PDF dizayn boshqaruvi: theme validatsiya, referens-rasm tahlili (vision),
preview, tasdiq/bekor sikli, git commit. Bot (/dizayn + media) shu modul
orqali ishlaydi. Draft'lar hech qachon avtomatik 09:00 ga chiqmaydi —
faqat «tasdiq»dan keyin active_theme o'zgaradi.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import analyze
import render_pdf

BRAND = BASE / "data" / "brand"
THEMES = BRAND / "themes"
INBOX = BRAND / "inbox"
PENDING = BRAND / "pending.json"
PREVIEW = BRAND / "preview.pdf"
SNAPSHOTS = BASE / "data" / "snapshots"

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_KEYS = [
    "page_bg", "card_bg", "text", "muted", "accent",
    "badge_ok", "badge_bad", "badge_quiet",
    "kpi_green", "kpi_yellow", "kpi_orange", "kpi_red",
    "bar_track", "grid_line",
]
LOGO_EXTS = ("png", "svg", "jpg", "jpeg", "webp")
MAX_FILE = 10 * 1024 * 1024

VISION_PROMPT = """Sen dizayn tahlilchisisan. Avval quyidagi rasmni Read tool bilan o'qi:
{path}

Bu — kunlik KPI hisoboti (A4 infografika) dizayni uchun REFERENS. Undan palitra
va uslubni ajratib, FAQAT quyidagi YAML'ni qaytar (boshqa hech qanday matn,
kod-blok belgilarisiz):

page_bg: "#RRGGBB"
card_bg: "#RRGGBB"
text: "#RRGGBB"
muted: "#RRGGBB"
accent: "#RRGGBB"
badge_ok: "#RRGGBB"
badge_bad: "#RRGGBB"
badge_quiet: "#RRGGBB"
kpi_green: "#RRGGBB"
kpi_yellow: "#RRGGBB"
kpi_orange: "#RRGGBB"
kpi_red: "#RRGGBB"
bar_track: "#RRGGBB"
grid_line: "#RRGGBB"
radius: "3mm"
card_border: "none"
card_shadow: "0 0.5mm 2mm rgba(0,0,0,.15)"
line_colors: ["#RRGGBB", "#RRGGBB", "#RRGGBB", "#RRGGBB"]
style_notes: "1-2 jumla o'zbekcha uslub tavsifi"
palette_summary: "asosiy hex ranglar, vergul bilan"

Qoidalar: hamma rang 6 xonali hex. text vs page_bg/card_bg KONTRASTLI bo'lsin
(o'qish mumkin bo'lsin). Rasm och bo'lsa — och theme, to'q bo'lsa — to'q.
kpi_green/red — semantik (yaxshi/yomon), referensdagi eng mos ranglardan.
radius va soyani uslub xarakteriga moslashtir (keskin/flat → 0-1mm, yumshoq → 3-5mm)."""

TEXT_EDIT_PROMPT = """Quyida kunlik KPI hisoboti PDF'ining joriy theme YAML'i va
foydalanuvchining dizayn o'zgartirish so'rovi bor. So'rovni bajarib, TO'LIQ
yangilangan YAML'ni qaytar (xuddi shu kalitlar, faqat kerakli qiymatlar
o'zgargan holda; boshqa hech qanday matn, kod-blok belgilarisiz).
style_notes'ga qisqacha nima o'zgarganini yoz.

JORIY THEME:
{current}

SO'ROV: {instruction}"""


def log(msg):
    print(f"[design] {msg}", flush=True)


# ---------- pending ----------

def load_pending():
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_pending(p):
    BRAND.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")


def clear_pending():
    try:
        PENDING.unlink()
    except OSError:
        pass


# ---------- theme utils ----------

def theme_list():
    if not THEMES.is_dir():
        return []
    return sorted(p.stem for p in THEMES.glob("*.yaml") if not p.stem.startswith("draft"))


def active_name():
    return render_pdf.active_theme_name()


def _sanitize_css(v):
    return re.sub(r"[^\w\s#().,%-]", "", str(v))[:120]


def validate_theme(d):
    """(tozalangan_theme, muammoli_kalitlar). Yetishmagani default'dan."""
    out = dict(render_pdf.DEFAULT_THEME)
    issues = []
    if not isinstance(d, dict):
        return out, ["yaml o'qilmadi"]
    for k in COLOR_KEYS:
        v = str(d.get(k, "")).strip()
        if HEX_RE.match(v):
            out[k] = v
        elif k in d:
            issues.append(k)
    lc = d.get("line_colors")
    if isinstance(lc, list):
        good = [str(c).strip() for c in lc if HEX_RE.match(str(c).strip())]
        if len(good) >= 4:
            out["line_colors"] = good[:4]
        else:
            issues.append("line_colors")
    r = str(d.get("radius", "")).strip()
    if re.match(r"^\d+(\.\d+)?(mm|px)$", r):
        out["radius"] = r
    for k in ("card_border", "card_shadow"):
        if d.get(k):
            out[k] = _sanitize_css(d[k])
    if d.get("font"):
        # CSS-xavfsiz: faqat harf/raqam, bo'shliq, vergul, qo'shtirnoq, defis
        out["font"] = re.sub(r"[^\w\s,\"'-]", "", str(d["font"]))[:220]
    for k in ("style_notes", "palette_summary"):
        if d.get(k):
            out[k] = str(d[k])[:220]
    return out, issues


def parse_theme_yaml(text):
    import yaml

    t = text.strip()
    m = re.search(r"```(?:yaml)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    i = t.find("page_bg")
    if i > 0:
        t = t[i:]
    return yaml.safe_load(t)


def save_draft(theme):
    import yaml

    THEMES.mkdir(parents=True, exist_ok=True)
    theme = dict(theme)
    theme["name"] = "draft"
    (THEMES / "draft.yaml").write_text(
        yaml.safe_dump(theme, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def set_active(name):
    """config.yaml'dagi active_theme qatorini almashtiradi (kommentlar saqlanadi)."""
    p = BASE / "config.yaml"
    s = p.read_text(encoding="utf-8")
    new = re.sub(r'(?m)^active_theme:.*$', f'active_theme: "{name}"', s)
    if new == s and "active_theme:" not in s:
        new = f'active_theme: "{name}"\n' + s
    p.write_text(new, encoding="utf-8")


def git_commit_brand(msg):
    try:
        subprocess.run(["git", "-C", str(BASE), "add", "data/brand", "config.yaml"],
                       capture_output=True, timeout=30)
        subprocess.run(
            ["git", "-C", str(BASE), "commit", "-q", "-m",
             msg + "\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"],
            capture_output=True, timeout=30,
        )
        log(f"git commit: {msg}")
    except Exception as e:
        log(f"git commit bo'lmadi: {e}")


# ---------- media ----------

def download(token, file_id, name):
    import requests

    r = requests.get(
        f"https://api.telegram.org/bot{token}/getFile",
        params={"file_id": file_id}, timeout=30,
    ).json()
    fp = r.get("result", {}).get("file_path")
    if not fp:
        raise RuntimeError(f"getFile xato: {str(r)[:150]}")
    data = requests.get(
        f"https://api.telegram.org/file/bot{token}/{fp}", timeout=120
    ).content
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", name)[:60]
    path = INBOX / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"
    path.write_bytes(data)
    return path


def set_logo_draft(src):
    ext = src.suffix.lower().lstrip(".")
    if ext not in LOGO_EXTS:
        ext = "png"
    for old in BRAND.glob("logo-draft.*"):
        old.unlink()
    dst = BRAND / f"logo-draft.{ext}"
    shutil.copy(src, dst)
    return dst


def logo_draft_uri():
    import base64

    mimes = {"png": "image/png", "svg": "image/svg+xml", "jpg": "image/jpeg",
             "jpeg": "image/jpeg", "webp": "image/webp"}
    for p in BRAND.glob("logo-draft.*"):
        mime = mimes.get(p.suffix.lower().lstrip("."), "image/png")
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    return ""


def apply_logo_draft():
    drafts = list(BRAND.glob("logo-draft.*"))
    if not drafts:
        return False
    for old in BRAND.glob("logo.*"):
        old.unlink()
    d = drafts[0]
    d.rename(BRAND / f"logo{d.suffix.lower()}")
    return True


def discard_logo_draft():
    for p in BRAND.glob("logo-draft.*"):
        p.unlink()


# ---------- tahlil ----------

def analyze_reference(image_path):
    """Referens rasm → (theme, issues). Vision: claude Read tool bilan."""
    ans = analyze.run_claude(
        VISION_PROMPT.format(path=image_path), effort="medium", allowed_tools=["Read"]
    )
    theme, issues = validate_theme(parse_theme_yaml(ans))
    return theme, issues


def instruction_to_draft(instruction):
    """Matnli dizayn so'rovi → joriy theme asosida yangi draft."""
    import yaml

    cur, _ = render_pdf.load_theme()
    cur_yaml = yaml.safe_dump(
        {k: v for k, v in cur.items() if k not in ("name",)},
        allow_unicode=True, sort_keys=False,
    )
    ans = analyze.run_claude(
        TEXT_EDIT_PROMPT.format(current=cur_yaml, instruction=instruction),
        effort="low",
    )
    theme, issues = validate_theme(parse_theme_yaml(ans))
    return theme, issues


# ---------- preview ----------

def latest_report_data():
    if not SNAPSHOTS.is_dir():
        return None
    for d in sorted((p for p in SNAPSHOTS.iterdir() if p.is_dir()), reverse=True):
        j = d / "report.json"
        if j.exists():
            try:
                return json.loads(j.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def pending_details(p):
    """«batafsil» so'ralganda — to'liq tahlil (default javobda ko'rsatilmaydi)."""
    t = (p or {}).get("type")
    if t == "logo":
        for f in BRAND.glob("logo-draft.*"):
            return (
                f"🖼 Logo-draft: {f.name} ({f.stat().st_size // 1024} KB, {f.suffix[1:].upper()})\n"
                "Joylashuvi: header chapida, balandligi 9mm.\n\n«tasdiq» / «bekor»"
            )
        return "Logo-draft topilmadi."
    name = "draft" if t == "theme" else (p or {}).get("name", "default")
    theme, _ = render_pdf.load_theme(name)
    L = [f"🎨 Theme tafsiloti ({name}):"]
    if theme.get("style_notes"):
        L.append(f"Uslub: {theme['style_notes']}")
    if theme.get("palette_summary"):
        L.append(f"Palitra: {theme['palette_summary']}")
    L += [
        f"• Sahifa foni {theme['page_bg']} · karta {theme['card_bg']}",
        f"• Matn {theme['text']} · ikkilamchi {theme['muted']} · urg'u (panel sarlavhalari) {theme['accent']}",
        f"• KPI: yaxshi {theme['kpi_green']} · o'rta {theme['kpi_yellow']} · past {theme['kpi_orange']} · kritik {theme['kpi_red']}",
        f"• Badge: ok {theme['badge_ok']} · muammo {theme['badge_bad']} · tinch {theme['badge_quiet']}",
        f"• Progress-bar foni {theme['bar_track']} · trend grid {theme['grid_line']}",
        f"• Trend chiziqlari (PM tartibida): {', '.join(theme['line_colors'])}",
        f"• Burchak {theme['radius']} · border {theme['card_border']} · soya {theme['card_shadow']}",
        "",
        "«tasdiq» / «bekor»",
    ]
    return "\n".join(L)


def make_preview(theme_name=None, use_logo_draft=False):
    data = latest_report_data()
    if not data:
        raise RuntimeError("report.json topilmadi — avval kunlik hisobot yaratilgan bo'lishi kerak")
    logo_uri = logo_draft_uri() if use_logo_draft else None
    render_pdf.render(data, PREVIEW, theme_name=theme_name, logo_uri=logo_uri)
    return PREVIEW
