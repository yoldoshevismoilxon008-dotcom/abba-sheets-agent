#!/usr/bin/env python3
"""WOW ai — kunlik reja/hisobotni Google Sheets ko'rinishidagi PNG jadvalga chizish.

Pillow + Inter shrifti (assets/fonts, OFL) — brauzersiz, deterministik va tez (~0,1 s).
Rasmda emoji yo'q (Inter'da glif yo'q): holat rangli «pill» bilan ko'rsatiladi.

chiz(...) → PNG baytlari. CLI: python3 wow_jadval.py out.png — namunaviy jadval.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
FONTS = BASE / "assets" / "fonts"

W = 1200                      # Telegram foto uchun qulay kenglik (siqilganda ham o'qiladi)
PAD = 48
CELL_X = 16                   # katak ichki chekkasi (gorizontal)
CELL_Y = 14                   # katak ichki chekkasi (vertikal)
LINE_H = 34                   # matn qatori balandligi
HEAD_H = 52                   # jadval sarlavha qatori

BG = (255, 255, 255)
INK = (32, 33, 36)
MUTED = (95, 99, 104)
HEAD_INK = (60, 64, 67)
GRID = (218, 220, 224)
HEAD_BG = (241, 243, 244)
ZEBRA = (250, 251, 252)
ACCENT = (26, 115, 232)

# holat → (fon, matn rangi, yorliq)
HOLATLAR = {
    "bajarildi": ((230, 244, 234), (19, 115, 51), "Bajarildi"),
    "jarayonda": ((254, 247, 224), (176, 96, 0), "Jarayonda"),
    "bajarilmadi": ((252, 232, 230), (197, 34, 31), "Bajarilmadi"),
    "ertaga": ((232, 240, 254), (25, 103, 210), "Ertaga"),
    "": ((241, 243, 244), (95, 99, 104), "—"),
}

_fonts = {}


def _font(weight, size):
    key = (weight, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)
    return _fonts[key]


def _wrap(draw, text, font, max_w):
    """So'z chegarasida bo'ladi; ustunga sig'magan bitta uzun so'z harf bo'yicha kesiladi."""
    lines = []
    for para in str(text or "").split("\n"):
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}".strip()
            if draw.textlength(cand, font=font) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            while draw.textlength(word, font=font) > max_w and len(word) > 1:
                n = len(word)
                while n > 1 and draw.textlength(word[:n], font=font) > max_w:
                    n -= 1
                lines.append(word[:n])
                word = word[n:]
            cur = word
        lines.append(cur)
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines or [""]


def xulosa_matn(jadval, hisobot):
    """Jadval ostidagi qator: reja — «Jami: 6 ta vazifa»; hisobot — holatlar bo'yicha son."""
    if not hisobot:
        return f"Jami: {len(jadval)} ta vazifa"
    sanoq = {}
    for r in jadval:
        sanoq[r.get("holat") or ""] = sanoq.get(r.get("holat") or "", 0) + 1
    qism = [f"{HOLATLAR[k][2]}: {sanoq[k]}" for k in ("bajarildi", "jarayonda", "bajarilmadi",
                                                      "ertaga") if sanoq.get(k)]
    if sanoq.get(""):
        qism.append(f"Holati aytilmagan: {sanoq['']}")
    qism.append(f"Jami: {len(jadval)}")
    return " · ".join(qism)


def chiz(sarlavha, ost_sarlavha, jadval, hisobot=False, belgi="WOW ai"):
    """jadval: [{"ish", "izoh", "holat"}]. hisobot=True — «Holat» ustuni (kechki hisobot).
    «Izoh» ustuni faqat kamida bitta qatorda izoh bo'lsa chiziladi (sodda bo'lsin)."""
    f_title = _font("Bold", 40)
    f_sub = _font("Regular", 24)
    f_belgi = _font("SemiBold", 20)
    f_head = _font("SemiBold", 22)
    f_cell = _font("Regular", 24)
    f_num = _font("Medium", 24)
    f_pill = _font("SemiBold", 20)
    f_foot = _font("Medium", 22)

    izohli = any((r.get("izoh") or "").strip() for r in jadval)
    tbl_w = W - 2 * PAD
    w_num = 64
    w_holat = 200 if hisobot else 0
    w_izoh = 320 if izohli else 0
    w_ish = tbl_w - w_num - w_holat - w_izoh
    cols = [("№", w_num), ("Vazifa", w_ish)]
    if izohli:
        cols.append(("Izoh", w_izoh))
    if hisobot:
        cols.append(("Holat", w_holat))

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_lines = _wrap(probe, sarlavha, f_title, tbl_w - 140)
    qatorlar = []
    for r in jadval:
        ish = _wrap(probe, r.get("ish") or "", f_cell, w_ish - 2 * CELL_X)
        izoh = _wrap(probe, r.get("izoh") or "", f_cell, w_izoh - 2 * CELL_X) if izohli else [""]
        n = max(len(ish), len(izoh), 1)
        qatorlar.append((ish, izoh, r.get("holat") or "", n * LINE_H + 2 * CELL_Y))

    top = 10 + PAD
    head_h = len(title_lines) * 52 + 8 + 34
    tbl_top = top + head_h + 28
    tbl_h = HEAD_H + sum(q[3] for q in qatorlar)
    height = tbl_top + tbl_h + 30 + 32 + PAD

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 6), fill=ACCENT)                      # Sheets tab rangi kabi chiziq

    y = top
    for line in title_lines:
        d.text((PAD, y), line, font=f_title, fill=INK)
        y += 52
    y += 8
    d.text((PAD, y), ost_sarlavha, font=f_sub, fill=MUTED)
    if belgi:
        bw = d.textlength(belgi, font=f_belgi)
        d.text((W - PAD - bw, top + 12), belgi, font=f_belgi, fill=MUTED)

    # sarlavha qatori
    x0, y0 = PAD, tbl_top
    d.rectangle((x0, y0, x0 + tbl_w, y0 + HEAD_H), fill=HEAD_BG)
    x = x0
    for nom, w in cols:
        d.text((x + CELL_X, y0 + (HEAD_H - 26) // 2), nom, font=f_head, fill=HEAD_INK)
        x += w

    # qatorlar (gorizontal chiziqlar oxirida — zebra foni ularni yopmasin)
    y = y0 + HEAD_H
    chegaralar = []
    for i, (ish, izoh, holat, h) in enumerate(qatorlar, 1):
        if i % 2 == 0:
            d.rectangle((x0, y, x0 + tbl_w, y + h), fill=ZEBRA)
        x = x0
        d.text((x + CELL_X, y + CELL_Y), str(i), font=f_num, fill=MUTED)
        x += w_num
        ty = y + CELL_Y
        for line in ish:
            d.text((x + CELL_X, ty), line, font=f_cell, fill=INK)
            ty += LINE_H
        x += w_ish
        if izohli:
            ty = y + CELL_Y
            for line in izoh:
                d.text((x + CELL_X, ty), line, font=f_cell, fill=MUTED)
                ty += LINE_H
            x += w_izoh
        if hisobot:
            fon, rang, yorliq = HOLATLAR.get(holat, HOLATLAR[""])
            pw = d.textlength(yorliq, font=f_pill) + 28
            ph = 34
            px = x + CELL_X
            py = y + CELL_Y + (LINE_H - ph) // 2
            d.rounded_rectangle((px, py, px + pw, py + ph), radius=ph // 2, fill=fon)
            d.text((px + 14, py + 5), yorliq, font=f_pill, fill=rang)
        y += h
        chegaralar.append(y)

    # to'r: qator chegaralari + tashqi ramka + ustun chiziqlari + sarlavha osti
    for cy in chegaralar:
        d.line((x0, cy, x0 + tbl_w, cy), fill=GRID, width=1)
    d.rectangle((x0, y0, x0 + tbl_w, y0 + tbl_h), outline=GRID, width=1)
    d.line((x0, y0 + HEAD_H, x0 + tbl_w, y0 + HEAD_H), fill=GRID, width=1)
    x = x0
    for _nom, w in cols[:-1]:
        x += w
        d.line((x, y0, x, y0 + tbl_h), fill=GRID, width=1)

    d.text((PAD, y0 + tbl_h + 22), xulosa_matn(jadval, hisobot), font=f_foot, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    import sys

    namuna = [
        {"ish": "Livardi: oylik kontent-reja tasdiqlash", "izoh": "soat 11:00 gacha",
         "holat": "bajarildi"},
        {"ish": "Yangi PM bilan 5 ta loyiha bo'yicha uchrashuv", "izoh": "", "holat": "jarayonda"},
        {"ish": "Orzu: reels TZ berish va dizayner bilan kelishish — "
                "ikki variant, ruscha va o'zbekcha matn", "izoh": "dizayner bilan",
         "holat": "bajarilmadi"},
        {"ish": "Undiruv: muddati o'tgan 3 mijozga qo'ng'iroq", "izoh": "", "holat": "ertaga"},
        {"ish": "Ketgan mijozlar ro'yxatini yangilash", "izoh": "", "holat": ""},
    ]
    out = sys.argv[1] if len(sys.argv) > 1 else "wow-jadval-namuna.png"
    Path(out).write_bytes(chiz("Kunlik hisobot", "Ismoilxon · 23.11.2026, dushanba",
                               namuna, hisobot=True))
    print(out)
