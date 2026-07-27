#!/usr/bin/env python3
"""Dashboard sheet'iga dizayn beruvchi BIR MARTALIK idempotent skript.

Nima qiladi (Sheets API batchUpdate, faqat formatlash — qiymatlarga tegmaydi):
  Barcha tab'lar: 1-qator freeze + bold + to'q ko'k fon + oq matn (11),
                  data font 10, raqam ustunlari o'ngga, ustunlar auto-resize.
  Umumiy/Trend:   "Bajarilish %" KPI rang shkalasi (>=90 yashil, 80+ sariq,
                  70+ to'q sariq, <70 qizil), kechikish>0 och qizil,
                  kritik>0 qizil bold — ochiq diapazonlarga (2-qator ->).
  Trend:          banding + Sana yyyy-mm-dd.
  KPI:            pul ustunlari #,##0 (minglik), "Prognoz jami" bold,
                  9-qator sarlavha bold + och kulrang.
  Audit:          Daraja "kritik" qizil matn, "tan olingan" kulrang matn.
  Bonus:          yashirin TrendWide (QUERY pivot, o'zi yangilanadi) +
                  Umumiy'da PM'lar bo'yicha Bajarilish % line chart.

Idempotent: qayta ishga tushirilsa eski conditional rule / banding / o'z
chartini o'chirib qaytadan qo'yadi — dublikat hosil bo'lmaydi.

dashboard_writer.py xulosasi (tekshirildi): writer tab'larni DELETE/RECREATE
qilmaydi, faqat values.clear + update — formatlash saqlanib qoladi.

Ishlatish:  venv/bin/python scripts/format_dashboard.py
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import fetch as fetchmod  # noqa: E402
import dashboard_writer as dw  # noqa: E402

CHART_TITLE = "Bajarilish % — PM dinamikasi"
HELPER = "TrendWide"
# Lokal (;) ga bog'liq bo'lmasligi uchun argument ajratkich sifatida ';'
HELPER_FORMULA = ('=QUERY(Trend!A:H; '
                  '"select A, max(F) where A is not null group by A pivot B"; 1)')
MAX_COL_PX = 500  # auto-resize'dan keyin shu kenglikdan oshgan ustun qisqartiriladi


def log(msg):
    print(f"[format_dashboard] {msg}", flush=True)


def rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255,
            "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


C_HEADER = rgb("1A3E6E")   # to'q ko'k
C_WHITE = rgb("FFFFFF")
C_GREEN = rgb("B7E1CD")    # >=90
C_YELLOW = rgb("FCE8B2")   # 80–89.9
C_ORANGE = rgb("F9CB9C")   # 70–79.9
C_RED_BG = rgb("EA9999")   # <70
C_RED_SOFT = rgb("F4CCCC") # kechikish>0
C_RED_TXT = rgb("CC0000")
C_GRAY_TXT = rgb("999999")
C_GRAY_BG = rgb("EFEFEF")  # KPI 9-qator
C_BAND2 = rgb("F3F6FA")    # banding ikkinchi rang


def grange(sid, sr=None, er=None, sc=None, ec=None):
    """Ochiq (unbounded) GridRange — None chegara tashlab ketiladi."""
    g = {"sheetId": sid}
    if sr is not None: g["startRowIndex"] = sr
    if er is not None: g["endRowIndex"] = er
    if sc is not None: g["startColumnIndex"] = sc
    if ec is not None: g["endColumnIndex"] = ec
    return g


def repeat_cell(rng, cell_format, fields):
    return {"repeatCell": {"range": rng,
                           "cell": {"userEnteredFormat": cell_format},
                           "fields": f"userEnteredFormat({fields})"}}


def bool_rule(rng, cond_type, values, fmt, index):
    rule = {"ranges": [rng],
            "booleanRule": {
                "condition": {"type": cond_type,
                              "values": [{"userEnteredValue": v} for v in values]},
                "format": fmt}}
    if not values:
        del rule["booleanRule"]["condition"]["values"]
    return {"addConditionalFormatRule": {"rule": rule, "index": index}}


def pct_scale_rules(sid, col, start_index):
    """KPI chegaralari: birinchi mos kelgan qoida g'olib (tartib muhim)."""
    rng = grange(sid, sr=1, sc=col, ec=col + 1)
    steps = [("NUMBER_GREATER_THAN_EQ", ["90"], {"backgroundColor": C_GREEN}),
             ("NUMBER_GREATER_THAN_EQ", ["80"], {"backgroundColor": C_YELLOW}),
             ("NUMBER_GREATER_THAN_EQ", ["70"], {"backgroundColor": C_ORANGE}),
             ("NUMBER_LESS", ["70"], {"backgroundColor": C_RED_BG})]
    return [bool_rule(rng, t, v, f, start_index + i)
            for i, (t, v, f) in enumerate(steps)]


def main():
    did = dw.dashboard_id()
    dw.guard(did)  # allowlist — faqat dashboard'ga yozamiz
    sh = dw.rw_client().open_by_key(did)
    meta = sh.fetch_sheet_metadata({
        "fields": ("properties(title,locale),"
                   "sheets(properties(sheetId,title,hidden,"
                   "gridProperties(rowCount,columnCount)),"
                   "conditionalFormats,bandedRanges,charts(chartId,spec(title)))")})
    locale = meta.get("properties", {}).get("locale", "?")
    sheets = {s["properties"]["title"]: s for s in meta.get("sheets", [])}
    log(f"spreadsheet: {meta.get('properties', {}).get('title')!r} (locale={locale})")

    def sid(title):
        return sheets[title]["properties"]["sheetId"]

    reqs = []
    missing = [t for t in ("Umumiy", "Trend", "Audit", "KPI") if t not in sheets]
    if missing:
        log(f"OGOHLANTIRISH: tab topilmadi, o'tkazib yuboriladi: {missing}")

    # ---- 1) Umumiy uslub: freeze, sarlavha, data font, o'ng tekislash ----
    NUM_COLS = {"Umumiy": (1, 7), "Trend": (2, 8), "Audit": None, "KPI": None}
    for tab in ("Umumiy", "Trend", "Audit", "KPI"):
        if tab not in sheets:
            continue
        s = sid(tab)
        reqs.append({"updateSheetProperties": {
            "properties": {"sheetId": s, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}})
        reqs.append(repeat_cell(
            grange(s, sr=0, er=1),
            {"backgroundColor": C_HEADER,
             "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": C_WHITE}},
            "backgroundColor,textFormat"))
        reqs.append(repeat_cell(grange(s, sr=1), {"textFormat": {"fontSize": 10}},
                                "textFormat.fontSize"))
        if NUM_COLS[tab]:
            c0, c1 = NUM_COLS[tab]
            reqs.append(repeat_cell(grange(s, sr=1, sc=c0, ec=c1),
                                    {"horizontalAlignment": "RIGHT"},
                                    "horizontalAlignment"))

        # Eski conditional rule'larni tozalash (idempotentlik)
        for _ in sheets[tab].get("conditionalFormats", []):
            reqs.append({"deleteConditionalFormatRule": {"sheetId": s, "index": 0}})

    # ---- 2) Umumiy va Trend: KPI rang qoidalari (ochiq diapazon, 2-qator ->) ----
    # Umumiy: E=Bajarilish%(4) F=Kechikish kunlari(5) G=Kritik audit(6)
    # Trend:  F=Bajarilish%(5) G=Kechikish(6)        H=Kritik(7)
    for tab, (c_pct, c_delay, c_crit) in (("Umumiy", (4, 5, 6)),
                                          ("Trend", (5, 6, 7))):
        if tab not in sheets:
            continue
        s = sid(tab)
        idx = 0
        rules = pct_scale_rules(s, c_pct, idx)
        idx += len(rules)
        rules.append(bool_rule(grange(s, sr=1, sc=c_delay, ec=c_delay + 1),
                               "NUMBER_GREATER", ["0"],
                               {"backgroundColor": C_RED_SOFT}, idx)); idx += 1
        rules.append(bool_rule(grange(s, sr=1, sc=c_crit, ec=c_crit + 1),
                               "NUMBER_GREATER", ["0"],
                               {"textFormat": {"bold": True,
                                               "foregroundColor": C_RED_TXT}}, idx))
        reqs.extend(rules)

    # ---- 3) Trend: banding + Sana yyyy-mm-dd ----
    if "Trend" in sheets:
        s = sid("Trend")
        for br in sheets["Trend"].get("bandedRanges", []):
            reqs.append({"deleteBanding": {"bandedRangeId": br["bandedRangeId"]}})
        rows = sheets["Trend"]["properties"]["gridProperties"]["rowCount"]
        reqs.append({"addBanding": {"bandedRange": {
            "range": grange(s, sr=1, er=rows, sc=0, ec=8),
            "rowProperties": {"firstBandColor": C_WHITE,
                              "secondBandColor": C_BAND2}}}})
        reqs.append(repeat_cell(
            grange(s, sr=1, sc=0, ec=1),
            {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}},
            "numberFormat"))

    # ---- 4) KPI: pul formatlari, Prognoz jami bold, 9-qator sarlavha ----
    if "KPI" in sheets:
        s = sid("KPI")
        reqs.append(repeat_cell(grange(s, sr=8, er=9),
                                {"backgroundColor": C_GRAY_BG,
                                 "textFormat": {"bold": True}},
                                "backgroundColor,textFormat.bold"))
        for col in (2, 4, 6, 7, 8):  # C, E, G, H, I — pul ustunlari
            reqs.append(repeat_cell(
                grange(s, sr=9, sc=col, ec=col + 1),
                {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}},
                "numberFormat"))
        reqs.append(repeat_cell(grange(s, sr=8, sc=8, ec=9),
                                {"textFormat": {"bold": True}}, "textFormat.bold"))
        reqs.append(repeat_cell(grange(s, sr=8, sc=1, ec=9),
                                {"horizontalAlignment": "RIGHT"},
                                "horizontalAlignment"))

    # ---- 5) Audit: Daraja matn ranglari ----
    if "Audit" in sheets:
        s = sid("Audit")
        rng = grange(s, sr=1, sc=2, ec=3)  # C = Daraja
        reqs.append(bool_rule(rng, "TEXT_CONTAINS", ["kritik"],
                              {"textFormat": {"foregroundColor": C_RED_TXT}}, 0))
        reqs.append(bool_rule(rng, "TEXT_EQ", ["tan olingan"],
                              {"textFormat": {"foregroundColor": C_GRAY_TXT}}, 1))

    # ---- Auto-resize (font o'zgargandan keyin, shu batch oxirida) ----
    for tab in ("Umumiy", "Trend", "Audit", "KPI"):
        if tab not in sheets:
            continue
        cols = sheets[tab]["properties"]["gridProperties"]["columnCount"]
        reqs.append({"autoResizeDimensions": {"dimensions": {
            "sheetId": sid(tab), "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": cols}}})

    log(f"asosiy batchUpdate: {len(reqs)} ta so'rov yuborilmoqda…")
    sh.batch_update({"requests": reqs})
    log("asosiy formatlash qo'llandi ✅")

    # ---- 6) BONUS: TrendWide (yashirin, QUERY) + Umumiy'da line chart ----
    try:
        n_pm = len(fetchmod.load_full_config().get("sheets", []))
        if "Umumiy" not in sheets or "Trend" not in sheets or n_pm == 0:
            raise RuntimeError("Umumiy/Trend tabi yoki PM ro'yxati yo'q")
        if HELPER in sheets:
            helper_id = sid(HELPER)
            sh.values_clear(f"'{HELPER}'!A1:Z1000")
            sh.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": helper_id, "hidden": True},
                "fields": "hidden"}}]})
        else:
            reply = sh.batch_update({"requests": [{"addSheet": {"properties": {
                "title": HELPER, "hidden": True,
                "gridProperties": {"rowCount": 1000, "columnCount": 12}}}}]})
            helper_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]
        sh.values_update(f"'{HELPER}'!A1",
                         params={"valueInputOption": "USER_ENTERED"},
                         body={"values": [[HELPER_FORMULA]]})

        chart_reqs = []
        for tab_meta in sheets.values():  # eski nusxalarni o'chirish
            for ch in tab_meta.get("charts", []):
                if ch.get("spec", {}).get("title") == CHART_TITLE:
                    chart_reqs.append({"deleteEmbeddedObject":
                                       {"objectId": ch["chartId"]}})
        series = [{"series": {"sourceRange": {"sources":
                      [grange(helper_id, sr=0, sc=c, ec=c + 1)]}},
                   "targetAxis": "LEFT_AXIS"} for c in range(1, n_pm + 1)]
        chart_reqs.append({"addChart": {"chart": {
            "spec": {"title": CHART_TITLE,
                     "basicChart": {"chartType": "LINE",
                                    "legendPosition": "BOTTOM_LEGEND",
                                    "headerCount": 1,
                                    "domains": [{"domain": {"sourceRange": {"sources":
                                        [grange(helper_id, sr=0, sc=0, ec=1)]}}}],
                                    "series": series}},
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": sid("Umumiy"),
                               "rowIndex": 1, "columnIndex": 9},
                "widthPixels": 640, "heightPixels": 380}}}}})
        sh.batch_update({"requests": chart_reqs})
        log(f"bonus: {HELPER} (yashirin) + chart qo'yildi ✅")
    except Exception as e:
        log(f"bonus chart QOLDI (asosiy formatlash buzilmadi): {type(e).__name__}: {e}")

    # ---- 7) Juda kengayib ketgan ustunlarni qisqartirish ----
    meta2 = sh.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title),data(columnMetadata(pixelSize)))"})
    clamp = []
    for s2 in meta2.get("sheets", []):
        title = s2["properties"]["title"]
        if title not in ("Umumiy", "Trend", "Audit", "KPI"):
            continue
        cols_meta = (s2.get("data") or [{}])[0].get("columnMetadata", [])
        for i, cm in enumerate(cols_meta):
            px = cm.get("pixelSize", 100)
            if px > MAX_COL_PX:
                log(f"clamp: [{title}] {chr(65 + i)} ustuni {px}px → {MAX_COL_PX}px")
                clamp.append({"updateDimensionProperties": {
                    "range": {"sheetId": s2["properties"]["sheetId"],
                              "dimension": "COLUMNS",
                              "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": MAX_COL_PX},
                    "fields": "pixelSize"}})
    if clamp:
        sh.batch_update({"requests": clamp})

    log(f"TAYYOR: {dw.dashboard_url()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
