#!/usr/bin/env python3
"""PM undiruv-push moduli: 4 PM lichkasiga kunlik undiruv eslatmalari.

Oqim:
  - Onboarding: t.me/<bot>?start=pm_<slot> deep-link → egaga approve so'rovi →
    /approve_<slot> yoki /reject_<slot> → DATA/pm_chats.json (volume).
  - Kunlik push (supervisor APScheduler 09:30, 09:00 pipeline'dan keyin):
    joriy oy "Undiruv <oy>" + o'tgan oy carryover, undiruv.is_unpaid filtri
    (YAGONA manba — /test_undiruv bilan bir xil), muddat o'tgan yoki ≤5 kun.
    Kuniga 1 marta (DATA/undiruv_push_state.json). Oxirida egaga jamlama.
  - PM lichkada nima yozsa — egaga forward; PM'ga boshqa funksiya yo'q.

CLI: pm_push.py [--dry-run] [--force] [--date YYYY-MM-DD]
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import analyze
import diff as diffmod
import fetch as fetchmod
import undiruv

DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
CHATS_FILE = DATA / "pm_chats.json"
CONTACTS_FILE = DATA / "pm_contacts.json"  # userbot yetkazish: slot → @username/+tel
STATE_FILE = DATA / "undiruv_push_state.json"

PUSH_DUE_DAYS = undiruv.PUSH_DUE_DAYS  # yagona chegara — undiruv.py'da
API = "https://api.telegram.org/bot{token}/{method}"


def log(msg):
    print(f"[pm_push] {msg}", flush=True)


def _owner():
    analyze.load_env()
    return (os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def _tg(method, payload, attempts=2):
    """Barcha Telegram chaqiruvlari shu nuqtadan (testda monkeypatch qilinadi)."""
    import requests

    token, _ = _owner()
    for i in range(attempts):
        try:
            r = requests.post(API.format(token=token, method=method), json=payload, timeout=30)
            if r.status_code == 200:
                return True
            log(f"{method} HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            log(f"{method} xato: {type(e).__name__}: {str(e)[:120]}")
        if i + 1 < attempts:
            time.sleep(2)
    return False


def send_to(chat_id, text):
    return _tg("sendMessage", {"chat_id": chat_id, "text": text,
                               "disable_web_page_preview": True})


def send_owner(text):
    _token, owner = _owner()
    return send_to(owner, text)


def _send_doc_owner(path, caption, filename):
    """Egaga PDF hujjat (testda monkeypatch qilinadi)."""
    import send as sendmod

    token, owner = _owner()
    sendmod.tg_send_document(token, owner, str(path), caption, filename=filename)
    return True


def owner_pdf(rows, tab, today, source, push_lines=None, title=None):
    """Egaga dizaynli undiruv PDF (render_pdf pipeline, abba logo, theme).
    Muvaffaqiyatda True; yiqilsa False — chaqiruvchi matn fallback yuboradi."""
    try:
        import render_pdf

        d = undiruv.report_data(rows, tab, today, source=source)
        if push_lines:
            d["push_info"] = push_lines
        out = DATA / "qa-pdf" / f"Undiruv-{d['oy']}-{today.isoformat()}.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        render_pdf.render_undiruv(d, out)
        return _send_doc_owner(out, undiruv.pdf_caption(d, title=title), out.name)
    except Exception as e:
        log(f"undiruv PDF bo'lmadi ({type(e).__name__}: {str(e)[:150]}) — matn rejimi")
        return False


# ---------- slotlar / mapping ----------

def _slot_key(name):
    """"Azizxo'ja" → "azizxoja" (deep-link va json kaliti uchun barqaror)."""
    return "".join(ch for ch in fetchmod.norm(name) if ch.isalnum())


def slots_from_config():
    """{slot: DisplayNom} — pm_kpi sheet nomlarining birinchi so'zidan."""
    out = {}
    for s in fetchmod.load_config(include_qa_only=True):
        if s.get("pm_kpi", True) and not s.get("qa_only"):
            first = str(s.get("name", "")).split()[0]
            if first:
                out[_slot_key(first)] = first
    return out


def load_chats():
    try:
        d = json.loads(CHATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("slots", {})
    d.setdefault("pending", {})
    return d


def save_chats(d):
    CHATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHATS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _who(msg):
    u = msg.get("from") or {}
    uname = u.get("username")
    return ("@" + uname) if uname else (u.get("first_name") or "nomsiz")


def slot_of_chat(chat_id, chats=None):
    chats = chats or load_chats()
    for slot, e in chats["slots"].items():
        if str(e.get("chat_id")) == str(chat_id):
            return slot
    return None


# ---------- PM kontaktlari (userbot yetkazish) ----------

def load_contacts():
    try:
        return json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_contact(slot, contact):
    """Egadan /pm_set <slot> <@username|+tel>. Qaytadi: javob matni."""
    slots = slots_from_config()
    if slot not in slots:
        return f"Noma'lum slot: {slot}. Mavjud: {', '.join(slots)}"
    contact = contact.strip()
    if not (contact.startswith("@") or contact.startswith("+")):
        return "Kontakt @username yoki +998... ko'rinishida bo'lsin."
    c = load_contacts()
    old = c.get(slot)
    c[slot] = contact
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return (f"✅ {slots[slot]} kontakti: {contact}"
            + (f" (eski: {old})" if old and old != contact else ""))


# ---------- onboarding / PM xabarlari (bot_listener chaqiradi) ----------

def handle_incoming(chat_id, msg):
    """Begona chat'dan kelgan xabar. Qaytadi: holat satri yoki None (bot jim
    ignore qiladi). FAQAT shu yerda begona chat bilan muloqot bo'ladi."""
    text = (msg.get("text") or "").strip()
    chats = load_chats()
    slots = slots_from_config()
    slot = slot_of_chat(chat_id, chats)

    # 1) Deep-link onboarding: /start pm_<slot>
    if text.lower().startswith("/start"):
        parts = text.split(None, 1)
        payload = parts[1].strip().lower() if len(parts) > 1 else ""
        if payload.startswith("pm_"):
            want = payload[3:]
            if want not in slots:
                send_to(chat_id, "Havola noto'g'ri yoki eskirgan.")
                return "pm-start-bad"
            who = _who(msg)
            chats["pending"][want] = {
                "chat_id": chat_id, "username": who,
                "asked": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            save_chats(chats)
            send_to(chat_id, "So'rov yuborildi — admin tasdiqlagach, kunlik undiruv "
                             "eslatmalari shu yerga keladi.")
            cur = chats["slots"].get(want)
            cur_s = f" (hozir ulangan: {cur.get('username')})" if cur else ""
            send_owner(
                f"🔗 {who} (chat_id {chat_id}) {slots[want]} sifatida ulanmoqchi{cur_s} — "
                f"/approve_{want} yoki /reject_{want}"
            )
            return "pm-start"
        if slot is None:
            return None  # begona /start — jim ignore

    # 2) Ulangan PM'dan xabar — egaga forward, PM'ga boshqa funksiya yo'q
    if slot:
        who = _who(msg)
        display = slots.get(slot, slot)
        if text:
            send_owner(f"💬 {display} ({who}): {text[:3500]}")
        else:
            send_owner(f"💬 {display} ({who}) matn bo'lmagan xabar yubordi:")
            _tg("forwardMessage", {
                "chat_id": _owner()[1], "from_chat_id": chat_id,
                "message_id": msg.get("message_id"),
            })
        if text.startswith("/"):
            send_to(chat_id, "Bu bot faqat undiruv eslatmalari uchun.")
        return "pm-msg"
    return None


def approve(slot):
    """Egadan /approve_<slot>. Qaytadi: egaga javob matni."""
    chats = load_chats()
    slots = slots_from_config()
    if slot not in slots:
        return f"Noma'lum slot: {slot}. Mavjud: {', '.join(slots)}"
    p = chats["pending"].pop(slot, None)
    if not p:
        return f"{slots[slot]} uchun kutilayotgan so'rov yo'q."
    old = chats["slots"].get(slot)
    chats["slots"][slot] = {
        "chat_id": p["chat_id"], "username": p.get("username", "?"),
        "approved": date.today().isoformat(),
    }
    save_chats(chats)
    send_to(p["chat_id"], f"✅ Ulandingiz — endi {slots[slot]} bo'yicha kunlik undiruv "
                          "eslatmalari shu yerga keladi.")
    extra = f" (avvalgi {old.get('username')} almashtirildi)" if old else ""
    return f"✅ {slots[slot]} ← {p.get('username')} (chat_id {p['chat_id']}) ulandi{extra}."


def reject(slot):
    chats = load_chats()
    slots = slots_from_config()
    p = chats["pending"].pop(slot, None)
    if not p:
        return f"{slots.get(slot, slot)} uchun kutilayotgan so'rov yo'q."
    save_chats(chats)
    send_to(p["chat_id"], "So'rov rad etildi.")
    return f"❌ {slots.get(slot, slot)} so'rovi rad etildi ({p.get('username')})."


def status_text():
    slots = slots_from_config()
    contacts = load_contacts()
    st = _load_state()
    L = ["👥 **PM undiruv-push (eganing akkauntidan, userbot):**"]
    try:
        import userbot_sender

        ok, why = userbot_sender.available()
        L.append(f"Userbot: {'tayyor ✅' if ok else 'sozlanmagan — ' + why}")
    except Exception as e:
        L.append(f"Userbot: xato — {str(e)[:80]}")
    for slot, name in slots.items():
        c = contacts.get(slot)
        line = f"• {name}: {c}" if c else f"• {name}: kontakt yo'q — /pm_set {slot} @username"
        if st.get("sent", {}).get(slot):
            line += f" · oxirgi: yuborildi ✅ ({st.get('date')})"
        elif st.get("failed", {}).get(slot):
            line += f" · oxirgi: XATO ❌ {str(st['failed'][slot])[:50]}"
        L.append(line)
    if st.get("date"):
        L.append(f"Oxirgi push: {st['date']} ({st.get('tab', '?')})")
    L.append("Sinov: /pm_push test — 4 xabar o'z Saved Messages'ingizga")
    return "\n".join(L)


# ---------- kunlik push ----------

def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _month_rows(day, month_name, today):
    """Snapshot'dan "Undiruv <month_name>" qatorlari (topilmasa (None, [])).
    Joriy va o'tgan oy uchun bitta yo'l — undiruv.parse_rows (yagona parser)."""
    want = f"undiruv {month_name}"
    for snap in diffmod.load_day(day)[0].values():
        if snap.get("pm_kpi", True):
            continue
        for rng in snap.get("ranges", {}):
            if fetchmod.norm(fetchmod.tab_of_range(rng)) == want:
                vals = snap["ranges"][rng].get("values", [])
                return fetchmod.tab_of_range(rng), undiruv.parse_rows(vals, today)
    return None, []


def _fmt(v):
    return f"${v:,.0f}".replace(",", " ")


def build_push(today, cur_rows, prev_rows, prev_month):
    """(pm_display → [qator matnlari], stats). Filtr: undiruv.is_unpaid +
    muddat o'tgan yoki ≤PUSH_DUE_DAYS kun. Sanasizlar PM'ga ketmaydi (stats'da).
    Carryover (o'tgan oy) qatorlari "(<oy> qoldig'i)" belgisi bilan."""
    per_pm = {}
    stats = {"overdue_sum": 0, "overdue_n": 0, "pauza": [], "bad_sum": 0, "no_date": 0,
             "aktiv_n": 0, "aktiv_sum": 0, "closed_carry": [], "conflict": []}
    # Aktiv obuna (joriy oy) — pul so'ralmaydi, faqat ega jamlamasida ma'lumot
    for r in cur_rows:
        if undiruv.is_active_only(r):
            stats["aktiv_n"] += 1
            stats["aktiv_sum"] += round(r["aktiv"])
    # Carryover: joriy oy tabida allaqachon to'langan/yuritilayotgan loyihalar
    # o'tgan oy qoldig'i sifatida SO'RALMAYDI — faqat ega jamlamasida
    # "sheet'ni tuzatish kerak" bloki
    prev_real, closed = undiruv.carryover_filter(prev_rows, cur_rows)
    stats["closed_carry"] = [
        {"loyiha": r["loyiha"], "pm": r["pm"], "summa": round(r["qoldiq_net"])}
        for r in closed
    ]
    for r, carry in [(r, False) for r in cur_rows] + [(r, True) for r in prev_real]:
        if not undiruv.is_unpaid(r):
            continue
        if r.get("ziddiyat"):
            stats["conflict"].append(
                {"loyiha": r["loyiha"], "pm": r["pm"],
                 "d": round(r["qoldiq"]), "e": round(r["undirildi"])}
            )
        summa = r["qoldiq_net"]
        name = r["loyiha"] + (f" ({prev_month} qoldig'i)" if carry else "")
        if r["holat"] == "pauza":
            stats["pauza"].append(f"{r['loyiha']} ({r['pm']})")
        if r["muddat"] is None:
            stats["no_date"] += 1
            continue
        days_left = (r["muddat"] - today).days
        if days_left > PUSH_DUE_DAYS:
            continue
        if days_left < 0:
            line = f"🔴 MUDDAT O'TDI ({-days_left} kun): {name} — qoldiq {_fmt(summa)}"
            stats["overdue_sum"] += summa
            stats["overdue_n"] += 1
        else:
            qoldi = "bugun oxirgi kun" if days_left == 0 else f"{days_left} kun qoldi"
            line = (f"⏳ Undiruv: {name} — qoldiq {_fmt(summa)}, "
                    f"muddat {undiruv._due_str(r['muddat'])} ({qoldi})")
        per_pm.setdefault(r["pm"], []).append(line)
    # Summa katagi son emas (bo'sh ham, raqamli ham emas — masalan #REF!, matn)
    import re as _re

    for r in cur_rows + prev_rows:
        raw = str(r.get("qoldiq_raw", "")).strip()
        if raw and not _re.search(r"\d", raw):
            stats["bad_sum"] += 1
    return per_pm, stats


def run_daily(today=None, force=False, dry_run=False, day=None):
    """Kunlik push. Qaytadi: (holat, jamlama_matni) — test/CLI uchun."""
    today = today or date.today()
    day = day or today.isoformat()
    st = _load_state()
    if st.get("date") == today.isoformat() and not force:
        log(f"bugun allaqachon yuborilgan ({st.get('date')}) — skip")
        return "skip", ""

    cur_month = fetchmod.current_month_name(today)
    prev_month = fetchmod.MONTHS[(fetchmod.MONTHS.index(cur_month) - 1) % 12]
    snap_day = day
    tab, cur_rows = _month_rows(snap_day, cur_month, today)
    if tab is None:
        # bugungi snapshot bo'lmasa oxirgi mavjud kundan urinamiz
        days = sorted(d.name for d in diffmod.SNAPSHOTS.iterdir()
                      if d.is_dir() and len(d.name) == 10) if diffmod.SNAPSHOTS.is_dir() else []
        if days and days[-1] != snap_day:
            snap_day = days[-1]
            tab, cur_rows = _month_rows(snap_day, cur_month, today)
    if tab is None:
        msg = (f"⚠️ Undiruv push: joriy oy tabi «Undiruv {cur_month}» topilmadi "
               f"(snapshot: {snap_day}) — PM'larga hech narsa yuborilmadi. "
               "Yangi oy tabi ochilganda avtomatik davom etadi.")
        if not dry_run:
            send_owner(msg)
            _save_state({"date": today.isoformat(), "tab": None, "sent": {}})
        log("joriy oy tabi yo'q — ogohlantirish yuborildi")
        return "no-tab", msg

    _ptab, prev_rows = _month_rows(snap_day, prev_month, today)
    per_pm, stats = build_push(today, cur_rows, prev_rows or [], prev_month)

    contacts = load_contacts()
    slots = slots_from_config()
    by_slot = {}
    for pm_name, lines in per_pm.items():
        by_slot[_slot_key(pm_name)] = (pm_name, lines)

    dd = today.strftime("%d.%m.%Y")
    # Xabarlarni tayyorlash (yetkazish: EGANING akkauntidan, userbot_sender)
    msgs, no_contact, texts = [], {}, {}
    for slot, (pm_name, lines) in by_slot.items():
        text = (f"🔔 Undiruv eslatmasi — {dd}\n\n" + "\n".join(lines)
                + "\n\nHar biri bo'yicha holat + aniq to'lov sanasini shu yerga yozing.")
        texts[slot] = text
        c = contacts.get(slot)
        if not c:
            no_contact[slot] = len(lines)
            continue
        msgs.append((slot, c, text))

    sent, failed = {}, {}
    fallback_reason = ""
    if msgs and not dry_run:
        try:
            import userbot_sender

            for slot, ok2, err in userbot_sender.send_messages(msgs):
                if ok2:
                    sent[slot] = len(by_slot[slot][1])
                else:
                    failed[slot] = err
        except Exception as e:
            # Session yo'q/yaroqsiz yoki telethon xatosi — hech kimga ketmadi
            fallback_reason = str(e)[:200]
            failed.update({slot: "yuborilmadi" for slot, _c, _t in msgs})
            log(f"userbot ishlamadi: {fallback_reason}")
    elif dry_run:
        for slot, _c, _t in msgs:
            log(f"[dry-run] {by_slot[slot][0]} → {_c}:\n{_t}\n")
            sent[slot] = len(by_slot[slot][1])

    # Egaga jamlama (yetkazish holati bilan)
    L = [f"📤 Undiruv push jamlamasi — {dd} (tab: {tab}, snapshot: {snap_day})"]
    for slot, name in slots.items():
        if slot in sent:
            L.append(f"• {name} ({contacts.get(slot, '?')}): {sent[slot]} eslatma yuborildi ✅")
        elif slot in failed:
            L.append(f"• {name} ({contacts.get(slot, '?')}): YUBORILMADI ❌ — {failed[slot][:80]}")
        elif slot in no_contact:
            L.append(f"• {name}: kontakt yo'q — /pm_set {slot} @username · "
                     f"{no_contact[slot]} eslatma kutmoqda")
        else:
            L.append(f"• {name}: bugun eslatma yo'q")
    if fallback_reason:
        L.append(f"⚠️ Userbot: {fallback_reason} — bugun QO'LDA yuboring "
                 "(tayyor matnlar alohida keladi)")
    L.append(f"⏰ Muddat o'tganlar: {stats['overdue_n']} ta, jami {_fmt(stats['overdue_sum'])}")
    if stats["conflict"]:
        cf = stats["conflict"]
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, D={_fmt(i['d'])} E={_fmt(i['e'])})"
                        for i in cf[:6])
        L.append(f"⚠️ Ziddiyatli qator (Undirildi > Summa): {len(cf)} ta — sheet'ni "
                 f"tekshirish kerak: {det}" + (f" +{len(cf) - 6}" if len(cf) > 6 else ""))
    if stats["closed_carry"]:
        cc = stats["closed_carry"]
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, {_fmt(i['summa'])})" for i in cc[:6])
        more = f" +{len(cc) - 6}" if len(cc) > 6 else ""
        L.append(f"🧹 {prev_month.capitalize()} tabida yopilmagan ({cur_month}da to'langan): "
                 f"{len(cc)} ta, {_fmt(sum(i['summa'] for i in cc))} — sheet'ni tuzatish "
                 f"kerak: {det}{more}")
    if stats["aktiv_n"]:
        L.append(f"💳 Aktiv obuna (so'ralmaydi): {stats['aktiv_n']} loyiha, {_fmt(stats['aktiv_sum'])}")
    if stats["pauza"]:
        L.append(f"⏸ Pauza: {', '.join(stats['pauza'][:8])}")
    if stats["bad_sum"] or stats["no_date"]:
        L.append(f"⚠️ Data: Summa son emas — {stats['bad_sum']} qator · sanasiz — "
                 f"{stats['no_date']} qator (PM'ga ketmadi)")
    summary = "\n".join(L)
    # Egaga: dizaynli PDF (jamlama bloki bilan); yiqilsa matn fallback.
    # dry_run'da ham egaga PDF ketadi (sinov ko'rinishi), faqat PM'lar va
    # state chetda qoladi.
    dd_title = ("🧪 [DRY] " if dry_run else "📤 ") + f"Undiruv push jamlamasi — {dd}"
    if not owner_pdf(cur_rows, tab, today, f"snapshot {snap_day}",
                     push_lines=L[1:], title=dd_title):
        send_owner(("[DRY-RUN — PM'larga yuborilmadi]\n" if dry_run else "") + summary)
    # Userbot butunlay ishlamagan kun: egaga 4 TAYYOR matn — qo'lda yuborish uchun
    if fallback_reason and not dry_run:
        for slot, _c, text in msgs:
            send_owner(f"📋 {by_slot[slot][0]} uchun tayyor matn "
                       f"({contacts.get(slot, '?')}):\n\n{text}")
    if not dry_run:
        _save_state({"date": today.isoformat(), "tab": tab, "sent": sent,
                     "failed": failed, "no_contact": no_contact})
    log(f"push tayyor: {len(sent)} yuborildi, {len(failed)} xato, "
        f"{len(no_contact)} kontaktsiz")
    return "sent", summary


def test_to_saved(today=None, day=None):
    """/pm_push test: xabarlarni PM'larga EMAS, eganing "Saved Messages"iga
    yuboradi (jonli sinov; state yozilmaydi). Qaytadi: natija matni."""
    import undiruv as _u  # noqa: F401 (parity: xuddi run_daily yo'li)

    today = today or date.today()
    day = day or today.isoformat()
    cur_month = fetchmod.current_month_name(today)
    prev_month = fetchmod.MONTHS[(fetchmod.MONTHS.index(cur_month) - 1) % 12]
    tab, cur_rows = _month_rows(day, cur_month, today)
    if tab is None:
        days = sorted(d.name for d in diffmod.SNAPSHOTS.iterdir()
                      if d.is_dir() and len(d.name) == 10) if diffmod.SNAPSHOTS.is_dir() else []
        if days:
            day = days[-1]
            tab, cur_rows = _month_rows(day, cur_month, today)
    if tab is None:
        return f"«Undiruv {cur_month}» tabi topilmadi — sinov uchun ma'lumot yo'q."
    _pt, prev_rows = _month_rows(day, prev_month, today)
    per_pm, _stats = build_push(today, cur_rows, prev_rows or [], prev_month)
    if not per_pm:
        return "Bugun birorta PM uchun eslatma yo'q — sinovga xabar chiqmadi."
    dd = today.strftime("%d.%m.%Y")
    msgs = []
    for pm_name, lines in per_pm.items():
        text = (f"🧪 [SINOV — {pm_name} ko'radigan xabar]\n"
                f"🔔 Undiruv eslatmasi — {dd}\n\n" + "\n".join(lines)
                + "\n\nHar biri bo'yicha holat + aniq to'lov sanasini shu yerga yozing.")
        msgs.append((_slot_key(pm_name), "me", text))
    import userbot_sender

    res = userbot_sender.send_messages(msgs)
    ok_n = sum(1 for _s, ok2, _e in res if ok2)
    lines = [f"🧪 Sinov: {ok_n}/{len(res)} xabar Saved Messages'ga yuborildi"]
    lines += [f"• {s}: {'✅' if ok2 else '❌ ' + e[:60]}" for s, ok2, e in res]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="yubormasdan chiqarish")
    ap.add_argument("--force", action="store_true", help="bugun yuborilgan bo'lsa ham")
    ap.add_argument("--date", help="YYYY-MM-DD (simulyatsiya)")
    args = ap.parse_args()
    t = date.fromisoformat(args.date) if args.date else None
    status, summary = run_daily(today=t, force=args.force, dry_run=args.dry_run,
                                day=args.date)
    print(f"holat: {status}\n{summary}")
