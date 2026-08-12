#!/usr/bin/env python3
"""Kunlik hisobotni Telegram'ga yuboradi (HTML parse_mode, 4096 belgidan bo'lib).

Ishlatish:
  python send.py                    # bugungi report.md ni yuboradi
  python send.py --date 2026-07-18  # shu kunning hisobotini yuboradi
  python send.py --get-chat-id      # botga yozilgan xabarlardan chat_id topib beradi
  python send.py --text "..."       # ixtiyoriy matn yuboradi (masalan, xato alert)
  python send.py --dry-run          # yubormasdan, bo'laklarni ekranga chiqaradi
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent
SNAPSHOTS = Path(os.environ.get("DATA_DIR") or (BASE / "data")) / "snapshots"

CHUNK_LIMIT = 4000  # Telegram limiti 4096 — teglar uchun zaxira qoldiramiz
API = "https://api.telegram.org/bot{token}/{method}"


def log(msg):
    print(f"[send] {msg}", flush=True)


def load_env():
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def md_to_html(text):
    """Markdown'ning minimal qismini Telegram HTML'ga o'giradi (qolgani escape)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out, pre_buf, in_pre = [], [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_pre:
                out.append("<pre>" + "\n".join(pre_buf) + "</pre>")
                pre_buf = []
            in_pre = not in_pre
            continue
        if in_pre:
            pre_buf.append(line)
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            line = f"<b>{m.group(1)}</b>"
        out.append(line)
    if in_pre and pre_buf:
        out.append("<pre>" + "\n".join(pre_buf) + "</pre>")
    return "\n".join(out)


def html_to_plain(s):
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def esc(s):
    """Telegram HTML uchun & < > ni escape qiladi (matn tugunlari uchun)."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def code(s):
    """Qiymatni Telegram <code> ichiga o'raydi (escape bilan). YAGONA yo'l — hamma joyda shu.

    QOIDA: Telegram <code> TASHQARISIDA «X.md/.uz/.co/.io» kabi qiymatni domen deb
    AVTOLINK qiladi (buzuq havola, masalan http://natija.md/). Shuning uchun Telegram'ga
    chiqadigan HAR QANDAY fayl yo'li / origin / vault_path / title SHU bilan o'ralsin.

    Natija — TAYYOR HTML: FAQAT is_html=True yo'li bilan yuboriladigan xabarlarda ishlat
    (tg_send / send_retry(is_html=True) / edit_status(html=True)). md_to_html'dan
    O'TKAZMA — aks holda ikki marta escape bo'ladi (&amp;amp;)."""
    return f"<code>{esc(s)}</code>"


_MANBA_RE = re.compile(r"^\s*[-*>]*\s*manba(?:lar)?\s*[:：]\s*(.+)$", re.IGNORECASE)


def format_kb_source_block(ans, vault="claude-brain"):
    """Model javobidagi «Manba: <nisbiy yo'l>» qatori(lar)ini XAVFSIZ manba blokiga
    aylantiradi. Qaytadi: (ans_manbasiz, html_blok).

    Nega: Telegram <code> TASHQARISIDA «X.md» ni domen deb avtolink qiladi
    (.md — Moldova TLD) → buzuq havola. Shuning uchun yo'l <code> ichida (havola EMAS)
    beriladi; ochish uchun ostига nusxalanadigan obsidian:// qatori (u ham <code> —
    <a href> QILINMAYDI, chunki Telegram obsidian:// ni rad etadi va butun xabar ketmaydi).
    Path-siz «Manba: <title>» (yuklangan hujjat) qatori o'zgarmasdan qoladi.
    Xatoda (ans, "") — manba bloki javobni yiqitmasin."""
    try:
        vault = (vault or "claude-brain").strip() or "claude-brain"
        paths, kept = [], []
        for line in ans.splitlines():
            m = _MANBA_RE.match(line)
            found = []
            if m:
                for tok in re.split(r"[,\n]|\s{2,}", m.group(1)):
                    tok = tok.strip(" \t`*[](){}<>").strip()
                    if tok and ("/" in tok or tok.lower().endswith(".md")):
                        if tok not in paths and tok not in found:
                            found.append(tok)
            if found:
                paths.extend(found)          # path-li «Manba» qatori olib tashlanadi
            else:
                kept.append(line)            # oddiy «Manba: title» yoki matn — qoladi
        if not paths:
            return ans, ""
        shown, out = paths[:3], []
        for p in shown:
            disp = p if p.lower().endswith(".md") else p + ".md"
            url = (f"obsidian://open?vault={quote(vault, safe='')}"
                   f"&file={quote(disp[:-3], safe='')}")     # .md kengaytmasisiz
            out.append(f"Manba: {code(disp)}")
            out.append(code(url))
        extra = len(paths) - len(shown)
        if extra > 0:
            out.append(f"+{extra} ta manba")
        return "\n".join(kept).rstrip(), "\n".join(out)
    except Exception:
        return ans, ""


def split_chunks(text, limit=CHUNK_LIMIT):
    """Qator chegaralarida bo'ladi; bitta qator limitdan uzun bo'lsa — qattiq kesadi."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur += line
    if cur.strip():
        chunks.append(cur)
    return [c.strip("\n") for c in chunks if c.strip()]


def tg_call(token, method, payload):
    import requests

    return requests.post(API.format(token=token, method=method), json=payload, timeout=30)


def tg_send_document(token, chat_id, path, caption="", filename=None):
    """PDF/faylni yuboradi. Xatoda exception — chaqiruvchi matnga fallback qiladi."""
    import os as _os

    import requests

    with open(path, "rb") as f:
        r = requests.post(
            API.format(token=token, method="sendDocument"),
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"document": (filename or _os.path.basename(path), f, "application/pdf")},
            timeout=180,
        )
    if r.status_code != 200:
        raise RuntimeError(f"sendDocument {r.status_code}: {r.text[:250]}")


def build_caption(data, title="kunlik KPI hisobot"):
    """report.json dict'idan qisqa caption (≤1024)."""
    t = data.get("totals", {})
    if t.get("quiet"):
        holat = "😴 O'zgarish yo'q"
    elif data.get("new_criticals"):
        holat = f"🔴 {len(data['new_criticals'])} yangi kritik topilma"
    else:
        holat = "✅ Yangi kritik yo'q"
    d = data.get("date", "")
    dd = f"{d[8:10]}.{d[5:7]}.{d[:4]}" if len(d) == 10 else d
    u = data.get("undiruv") or {}
    u_line = ""
    if u.get("kelishilgan"):
        fmt = lambda v: f"${v:,.0f}".replace(",", " ")
        u_line = (
            f"💰 Undiruv ({u.get('oy', '')}): {str(u.get('pct', 0)).replace('.', ',')}% — "
            f"{fmt(u['undirildi'])} / {fmt(u['kelishilgan'])}"
        )
        if u.get("muddat_otgan"):
            tot = sum(i.get("summa", 0) for i in u["muddat_otgan"])
            u_line += f" · ⏰ muddat o'tgan: {len(u['muddat_otgan'])} ta ({fmt(tot)})"
    lines = [
        f"📊 {dd} — {title}",
        holat + (f" · 🤝 tan olingan: {len(data['acknowledged'])}" if data.get("acknowledged") else ""),
        " · ".join(f"{p['name']} {p['pct']}%" for p in data.get("pms", [])),
        f"O'zgarishlar: +{t.get('added', 0)} yangi · −{t.get('removed', 0)} o'chgan · ~{t.get('changed', 0)} o'zgargan",
        u_line,
        "To'liq matn: Obsidian arxivi · /audit · /dashboard",
    ]
    return "\n".join(x for x in lines if x.strip())[:1024]


def tg_send(token, chat_id, html_text):
    r = tg_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    if r.status_code != 200:
        # HTML parse xatosi bo'lsa — teglarsiz oddiy matn bilan qayta urinamiz
        log(f"HTML rejimda xato ({r.status_code}: {r.text[:200]}) — oddiy matnda qayta urinaman")
        r = tg_call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": html_to_plain(html_text),
            "disable_web_page_preview": True,
        })
    if r.status_code != 200:
        raise RuntimeError(f"Telegram xato {r.status_code}: {r.text[:300]}")


def get_chat_id(token):
    import requests

    r = requests.get(API.format(token=token, method="getUpdates"), timeout=30)
    if r.status_code != 200:
        log(f"XATO: getUpdates {r.status_code}: {r.text[:200]}")
        return 1
    chats = {}
    for u in r.json().get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("edited_message") or {}
        c = msg.get("chat")
        if c:
            chats[c["id"]] = c
    if not chats:
        print("Hech qanday chat topilmadi.")
        print("  1) Telegram'da botingizni toping va /start deb yozing")
        print("  2) (guruh uchun) botni guruhga qo'shib, guruhda bitta xabar yozing")
        print("  3) shu buyruqni qayta ishga tushiring")
        return 1
    print("Topilgan chatlar:")
    for cid, c in chats.items():
        title = (
            c.get("title")
            or " ".join(filter(None, [c.get("first_name"), c.get("last_name")]))
            or c.get("username", "?")
        )
        print(f"  chat_id: {cid}    ({c.get('type')}: {title})")
    print("\nTanlagan chat_id ni .env ga yozing:  TELEGRAM_CHAT_ID=<id>")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: bugun)")
    ap.add_argument("--get-chat-id", action="store_true", help="getUpdates orqali chat_id topish")
    ap.add_argument("--text", help="report o'rniga shu matnni yuborish (xato alertlar uchun)")
    ap.add_argument("--dry-run", action="store_true", help="yubormasdan bo'laklarni ko'rsatish")
    args = ap.parse_args()
    load_env()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if args.get_chat_id:
        if not token:
            log("XATO: avval .env ga TELEGRAM_BOT_TOKEN yozing")
            return 1
        return get_chat_id(token)

    if args.text is not None:
        html = md_to_html(args.text)
    else:
        # PDF rejimi: report.pdf bo'lsa — hujjat + caption; yiqilsa matnga fallback
        pdf = SNAPSHOTS / args.date / "report.pdf"
        if pdf.exists() and not args.dry_run:
            if not token or not chat_id:
                log("XATO: .env da TELEGRAM_BOT_TOKEN va TELEGRAM_CHAT_ID to'ldirilmagan")
                return 1
            try:
                jp = SNAPSHOTS / args.date / "report.json"
                data = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"date": args.date}
                tg_send_document(
                    token, chat_id, str(pdf), build_caption(data),
                    filename=f"KPI-hisobot-{args.date}.pdf",
                )
                log("PDF hisobot yuborildi")
                return 0
            except Exception as e:
                log(f"OGOHLANTIRISH: PDF yuborilmadi ({str(e)[:150]}) — matn rejimiga o'tildi")
        elif pdf.exists() and args.dry_run:
            log(f"[dry-run] PDF yuborilgan bo'lardi: {pdf}")
        path = SNAPSHOTS / args.date / "report.md"
        if not path.exists():
            log(f"XATO: {path} topilmadi — avval analyze.py ishga tushiring")
            return 1
        html = md_to_html(path.read_text(encoding="utf-8"))

    chunks = split_chunks(html)
    if not chunks:
        log("XATO: yuboriladigan matn bo'sh")
        return 1

    if args.dry_run:
        print(f"[dry-run] {len(chunks)} ta bo'lak yuborilgan bo'lardi:")
        for i, c in enumerate(chunks, 1):
            print(f"\n--- bo'lak {i}/{len(chunks)} ({len(c)} belgi) ---")
            print(c)
        return 0

    if not token or not chat_id:
        log("XATO: .env da TELEGRAM_BOT_TOKEN va TELEGRAM_CHAT_ID to'ldirilmagan")
        return 1

    try:
        for i, c in enumerate(chunks, 1):
            tg_send(token, chat_id, c)
            log(f"yuborildi: {i}/{len(chunks)}")
            if i < len(chunks):
                time.sleep(0.5)
    except Exception as e:
        log(f"XATO: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
