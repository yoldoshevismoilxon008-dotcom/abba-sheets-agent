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


def owner_pdf(rows, tab, today, source, push_lines=None, title=None, data_source=None,
              overdue=None, view=None):
    """Egaga dizaynli undiruv PDF (render_pdf pipeline, abba logo, theme).
    data_source ∈ {'live','snapshot'} — 'snapshot' bo'lsa PDF boshiga 🧊 banner.
    overdue=(n, sum) — build_push hisobi; berilsa PDF badge SHU raqamni oladi va
    o'zi qayta hisoblamaydi (bitta hujjatda bitta manba bo'lsin).
    view — undiruv.korinish(): berilsa PDF o'tgan oy qoldiqlari va keyingi oy ≤5 kunlik
    to'lovlarini ham ko'rsatadi (09:30 push AYNAN shularni PM'ga yuboradi — C3).
    Muvaffaqiyatda True; yiqilsa False — chaqiruvchi matn fallback yuboradi."""
    try:
        import render_pdf

        d = undiruv.report_data(rows, tab, today, source=source, view=view)
        if overdue is not None:
            d["overdue_n"], d["overdue_sum"] = overdue
        # data_source berilmasa — display source satridan chiqaramiz
        d["data_source"] = data_source or ("snapshot" if str(source).startswith("snapshot") else "live")
        # PM ustuni tabda umuman yo'q bo'lsa — PDF boshiga qora banner
        if rows and not rows[0].get("pm_col_present", True):
            n = sum(1 for r in rows if undiruv.is_unpaid(r))
            d["pm_col_warn"] = (f"⚠️ «{tab}» tabida «Ma'sul shaxs» ustuni YO'Q — "
                                f"{n} qator PM'ga yo'naltirilmadi")
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
    """SNAPSHOT'dan "Undiruv <month_name>" qatorlari (topilmasa (None, [])).
    Faqat fallback — production jonli o'qiydi (_month_rows_src). Tab tanlash
    undiruv.find_tab bilan (imlo/yil-suffiks mustahkam)."""
    for snap in diffmod.load_day(day)[0].values():
        if snap.get("pm_kpi", True):
            continue
        rng = undiruv.find_tab(snap, today, month=month_name)
        if rng:
            vals = snap["ranges"][rng].get("values", [])
            return fetchmod.tab_of_range(rng), undiruv.parse_rows(vals, today)
    return None, []


def _month_rows_src(month_name, today, day):
    """JONLI-birinchi (undiruv.fetch_live_month), xato/topilmasa SNAPSHOT
    fallback. Qaytadi: (tab, rows, source) — source ∈ {'live','snapshot','none'}.
    Production 09:00/09:30 HAR DOIM jonli o'qishi uchun."""
    try:
        tab, rows = undiruv.fetch_live_month(month_name, today)
        if tab is not None:
            return tab, rows, "live"
        log(f"jonli: «Undiruv {month_name}» topilmadi — snapshot fallback")
    except Exception as e:
        log(f"jonli o'qish xato ({month_name}): {type(e).__name__}: {str(e)[:120]} — snapshot")
    tab, rows = _month_rows(day, month_name, today)
    return tab, rows, ("snapshot" if tab else "none")


def _fmt(v):
    return f"${v:,.0f}".replace(",", " ")


def _tafsil(r, oy):
    """Qaror bo'yicha qo'shilgan (jadvalda hali yo'q) qoldiq bo'lsa — PM ko'radigan izoh:
    « (oktyabr $1 350 + sentyabr qoldig'i $364)», to'lov bo'lsa « … − to'langan $1 000»."""
    q = r.get("qoshimcha")
    if not q or q.get("jadvalda"):
        return ""
    tol = f" − to'langan {_fmt(r['undirildi'])}" if r.get("undirildi", 0) > 0 else ""
    return f" ({oy} {_fmt(q['asl'])} + {q['oy']} qoldig'i {_fmt(q['summa'])}{tol})"


def _qaror_satri(m, yangi_oy):
    """Ega qarori qo'llangan ko'chirish → jamlama satri (qaysi qaror nima qildi)."""
    k = m.get("_kochish") or {}
    otgan_oy = k.get("oy") or "o'tgan oy"      # f-string ichida teskari chiziq bo'lmasin (3.9)
    if k.get("turi") == "qaror_qoshildi":
        kel = k.get("cur_kelishilgan", k.get("cur_summa", 0))
        qol = k.get("cur_summa", kel)
        qism = f", qoldiq {_fmt(qol)}" if round(qol) != round(kel) else ""
        return (f"{m['loyiha']} — {otgan_oy} qoldig'i {_fmt(m['qoldiq'])} "
                f"{yangi_oy} summasiga qo'shildi (jami {_fmt(kel)}{qism})")
    if k.get("turi") == "qaror_yangi_toliq":
        return (f"{m['loyiha']} — {yangi_oy}dagi {_fmt(k.get('cur_summa', 0))} to'liq summa "
                f"({otgan_oy} {_fmt(m['qoldiq'])} alohida so'ralmaydi)")
    return None


def _noaniq_satr(r, oy):
    sabab = r.get("_noaniq") or "ikki o'xshash nom"
    return f"{r['loyiha']} ({r['pm']}, {oy}: {sabab})"


def _slotga_yig(per_pm, nodate_pm):
    """PM ismlari → slot bo'yicha BIRLASHTIRILGAN xabar tarkibi: (by_slot{slot: (ism,
    satrlar)}, slot_n{slot: soni}, slot_nd{slot: sanasizlar}). Bitta PM ismi ikki tabda
    ikki xil yozilishi mumkin («Azizxo'ja»/«Azizxo’ja») — bitta xabar. run_daily va
    /pm_push test (test_to_saved) AYNAN shu yig'uvchidan (sinov haqiqiysidan farq qilmasin)."""
    by_slot, slot_n, slot_nd = {}, {}, {}
    for pm_name in sorted(set(per_pm) | set(nodate_pm)):
        sk = _slot_key(pm_name)
        nm, lines = by_slot.get(sk, (pm_name, []))
        by_slot[sk] = (nm, lines + per_pm.get(pm_name, []))
        slot_nd.setdefault(sk, []).extend(nodate_pm.get(pm_name, []))
        slot_n[sk] = len(by_slot[sk][1]) + len(slot_nd[sk])
    return by_slot, slot_n, slot_nd


def _xabar_matni(dd, lines, nd):
    """PM eslatma matni (run_daily va test_to_saved — bitta shakl)."""
    body = "\n".join(lines)
    if nd:
        nd_block = ("📅 Sana belgilanmagan — aniq to'lov sanasini yozing:\n"
                    + "\n".join(f"• {x}" for x in nd))
        body = (body + "\n\n" + nd_block) if body else nd_block
    return (f"🔔 Undiruv eslatmasi — {dd}\n\n" + body
            + "\n\nHar biri bo'yicha holat + aniq to'lov sanasini shu yerga yozing.")


def build_push(today, cur_rows, prev_rows, prev_month, view=None):
    """(pm_display → [qator matnlari], stats). Filtr: undiruv.is_unpaid +
    muddat o'tgan yoki ≤PUSH_DUE_DAYS kun. Sanasizlar PM'ga ketmaydi (stats'da).
    Carryover (o'tgan oy) qatorlari "(<oy> qoldig'i)" belgisi bilan.

    view — undiruv.korinish() natijasi (production yo'li). Berilsa: o'tgan oy tasnifi
    shu yerdan (imloga chidamli moslik + ega qarorlari), keyingi oyga ko'chgan joriy
    qatorlar (`keyingi_oyga`) eski muddat bilan SO'RALMAYDI, keyingi oyning muddati
    ≤PUSH_DUE_DAYS qatorlari «(<oy>)» belgisi bilan PM'ga qo'shiladi. Berilmasa —
    eski xulq (carryover_filter)."""
    per_pm = {}
    # overdue_* = JORIY oy tabi (PDF badge/kartochkalari bilan bir xil to'plam).
    # O'tgan oydan ko'chgan qarzlar ALOHIDA sanaladi (overdue_carry_*) — ilgari
    # ikkalasi bitta hisobga qo'shilib, PDF ichida zid raqam chiqarardi.
    stats = {"overdue_sum": 0, "overdue_n": 0, "overdue_carry_n": 0, "overdue_carry_sum": 0,
             "pauza": [], "bad_sum": 0, "no_date": 0,
             "aktiv_n": 0, "aktiv_sum": 0, "closed_carry": [], "moved_carry": [],
             "unpaid_n": 0, "status_blank": [],
             "pm_missing": [], "pm_col_missing": False, "pm_col_tab": "",
             "nodate_pm": {}, "nodate_n": 0,   # muddatsiz undirilmaganlar (PM kesimida)
             # oy almashuvi (view bilan): keyingi oy, ko'chganlar, summa farqli, qarorlar
             "keyingi_n": 0, "keyingi_sum": 0, "keyingi_tab": None, "keyingi_oy": None,
             "keyingi_bor": False, "keyingi_kochgan": [], "keyingi_yopilgan": [],
             "keyingi_source": None, "farqli": [], "noaniq": [],
             "qaror_qollangan": [], "qaror_izoh": []}
    cur_oy = (view or {}).get("oy") or fetchmod.current_month_name(today)
    # PM ustuni tabda UMUMAN yo'qmi (avgust holati) — joriy oy qatorlaridan
    if cur_rows and not cur_rows[0].get("pm_col_present", True):
        stats["pm_col_missing"] = True
    # Aktiv obuna (joriy oy) — pul so'ralmaydi, faqat ega jamlamasida ma'lumot
    for r in cur_rows:
        if undiruv.is_active_only(r):
            stats["aktiv_n"] += 1
            stats["aktiv_sum"] += round(r["aktiv"])
    # Carryover: joriy oy tabida allaqachon to'langan/yuritilayotgan loyihalar
    # o'tgan oy qoldig'i sifatida SO'RALMAYDI — faqat ega jamlamasida
    # "sheet'ni tuzatish kerak" bloki
    if view is not None:
        pv = view["prev"]
        prev_real, closed, moved = pv["real"], pv["closed"], pv["moved"]
        stats["farqli"] = [{"loyiha": r["loyiha"], "pm": r["pm"], "otgan": round(r["qoldiq"]),
                            "yangi": r["_kochish"]["cur_summa"], "yangi_loyiha": r["_kochish"]["cur_loyiha"],
                            "yonalish": f"{prev_month} → {cur_oy}"} for r in pv["farqli"]]
        stats["noaniq"] = [_noaniq_satr(r, prev_month) for r in pv["noaniq"]]
        stats["qaror_izoh"] = list(pv["izoh"])
        stats["qaror_qollangan"] = [x for x in (_qaror_satri(m, cur_oy) for m in moved) if x]
    else:
        prev_real, closed, moved = undiruv.carryover_filter(prev_rows, cur_rows)
    stats["closed_carry"] = [
        {"loyiha": r["loyiha"], "pm": r["pm"], "summa": round(r["qoldiq"])}
        for r in closed
    ]
    # Joriy oy tabiga KO'CHIRILGAN qoldiqlar — PM'ga ikkinchi marta so'ralmaydi,
    # lekin egaga ko'rinadi (jim yutilmasin).
    stats["moved_carry"] = [
        {"loyiha": r["loyiha"], "pm": r["pm"], "summa": round(r["qoldiq"]),
         "matn": undiruv.kochish_matn(r)}          # «Rivo → Rivo water ($1 800 → 04.10)»
        for r in moved
    ]
    for r, carry in [(r, False) for r in cur_rows] + [(r, True) for r in prev_real]:
        if not undiruv.is_unpaid(r):
            continue
        if r.get("keyingi_oyga"):
            # keyingi oy tabiga ko'chgan/yopilgan (joriy oy qatori ham, o'tgan oy qoldig'i
            # ham — ega uni keyingi oy tabiga yozgan bo'lsa) — eski muddat bilan so'ralmaydi
            continue
        stats["unpaid_n"] += 1
        summa = r["qoldiq"]  # so'raladigan qarz = D (ayirmasiz)
        # PM'ga ketadigan xabar TOZA qoladi (⚠️ chalg'itmasin) — status-bo'sh
        # belgisi faqat ega jamlamasi/PDF'da ko'rinadi
        if r.get("status_blank"):
            stats["status_blank"].append(f"{r['loyiha']} ({r['pm']})")
        name = r["loyiha"] + (f" ({prev_month} qoldig'i)" if carry else "")
        tafsil = "" if carry else _tafsil(r, cur_oy)
        if r["holat"] == "pauza":
            stats["pauza"].append(f"{r['loyiha']} ({r['pm']})")
        # Muddat yo'q, lekin qarz bor — YO'QOLMASIN: PM'i borlar PM xabaridagi
        # "sana belgilanmagan" bo'limiga; PM'sizlar egaga (pm_missing).
        if r["muddat"] is None:
            stats["no_date"] += 1
            stats["nodate_n"] += 1
            nd = f"{name} — qoldiq {_fmt(summa)}"
            if r.get("pm_missing"):
                stats["pm_missing"].append({"loyiha": r["loyiha"], "line": "📅 " + nd + " (sanasiz)"})
            else:
                stats["nodate_pm"].setdefault(r["pm"], []).append(nd)
            continue
        days_left = (r["muddat"] - today).days
        if days_left > PUSH_DUE_DAYS:
            continue
        if days_left < 0:
            line = f"🔴 MUDDAT O'TDI ({-days_left} kun): {name} — qoldiq {_fmt(summa)}{tafsil}"
            if carry:                      # o'tgan oy qoldig'i — alohida hisob
                stats["overdue_carry_sum"] += summa
                stats["overdue_carry_n"] += 1
            else:
                stats["overdue_sum"] += summa
                stats["overdue_n"] += 1
        else:
            qoldi = "bugun oxirgi kun" if days_left == 0 else f"{days_left} kun qoldi"
            line = (f"⏳ Undiruv: {name} — qoldiq {_fmt(summa)}{tafsil}, "
                    f"muddat {undiruv._due_str(r['muddat'])} ({qoldi})")
        # PM aniqlanmagan (ustun yo'q yoki katak bo'sh) — PM'GA YO'NALTIRILMAYDI,
        # egaga ogohlantirish + qo'lda yuborish uchun tayyor matn
        if r.get("pm_missing"):
            stats["pm_missing"].append({"loyiha": r["loyiha"], "line": line})
            continue
        per_pm.setdefault(r["pm"], []).append(line)
    # Keyingi oy (oy oxirida): muddati ≤PUSH_DUE_DAYS — PM'ga «(<oy>)» belgisi bilan
    k = (view or {}).get("keyingi")
    if k is not None:
        stats["keyingi_bor"] = True
        stats["keyingi_tab"], stats["keyingi_oy"] = k.get("tab"), k.get("oy")
        stats["keyingi_source"] = k.get("source")
        flag = ([r for r in cur_rows if r.get("keyingi_oyga")]
                + [r for r in prev_real if r.get("keyingi_oyga")])

        def _ki(r):
            kk = r["keyingi_oyga"]
            return {"loyiha": r["loyiha"], "pm": r["pm"], "summa": round(r["qoldiq"]),
                    "yangi_muddat": undiruv._due_str(kk.get("muddat")), "turi": kk.get("turi"),
                    "matn": undiruv.kochish_matn(r)}
        stats["keyingi_kochgan"] = [_ki(r) for r in flag if r["keyingi_oyga"].get("turi") != "yopilgan"]
        stats["keyingi_yopilgan"] = [_ki(r) for r in flag if r["keyingi_oyga"].get("turi") == "yopilgan"]
        stats["farqli"] += [{"loyiha": r["loyiha"], "pm": r["pm"], "otgan": round(r["qoldiq"]),
                             "yangi": r["_kochish"]["cur_summa"], "yangi_loyiha": r["_kochish"]["cur_loyiha"],
                             "yonalish": r.get("_yonalish") or f"{cur_oy} → {k['oy']}"}
                            for r in k.get("farqli", [])]
        stats["noaniq"] += [_noaniq_satr(r, cur_oy) for r in k.get("noaniq", [])]
        stats["qaror_izoh"] += list(k.get("izoh", []))
        stats["qaror_qollangan"] += [x for x in (_qaror_satri(m, k["oy"]) for m in k.get("kochgan", [])) if x]
        for r in k.get("yaqin", []):
            days_left = (r["muddat"] - today).days
            qoldi = "bugun oxirgi kun" if days_left == 0 else f"{days_left} kun qoldi"
            line = (f"⏳ Undiruv: {r['loyiha']} ({k['oy']}) — qoldiq {_fmt(r['qoldiq'])}"
                    f"{_tafsil(r, k['oy'])}, muddat {undiruv._due_str(r['muddat'])} ({qoldi})")
            if r.get("pm_missing"):
                # PM'siz — PM xabariga TUSHMAYDI (egaga qo'lda yuborish ro'yxati); «PM xabarlariga
                # qo'shildi» sanog'iga kirmasin (review C6)
                stats["pm_missing"].append({"loyiha": r["loyiha"], "line": line})
                continue
            stats["keyingi_n"] += 1
            stats["keyingi_sum"] += round(r["qoldiq"])
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
    prev_month = undiruv.oy_ofset(today, -1)[0]
    snap_day = day
    prev_tab = st.get("tab")           # o'tgan run tabi — yangi oy aniqlash uchun
    # YAGONA yig'uvchi (C3): joriy + o'tgan (+ oy oxirida keyingi) oy — kunlik KPI
    # bloki, dashboard va /test_undiruv bilan AYNAN bir xil tasnif. JONLI-birinchi
    # (production MAJBURIY jonli); jonli xato bo'lsa snapshot.
    view = undiruv.korinish(today, day=snap_day, prefer_live=True)
    tab, cur_rows, cur_src = view["tab"], view["rows"], view["source"]
    birinchi_izoh, birinchi_src = list(view.get("notes") or []), cur_src
    if tab is None and cur_src in ("none", "xato"):
        # snapshot ham bugun yo'q — oxirgi mavjud kundan urinamiz
        days = sorted(d.name for d in diffmod.SNAPSHOTS.iterdir()
                      if d.is_dir() and len(d.name) == 10) if diffmod.SNAPSHOTS.is_dir() else []
        if days and days[-1] != snap_day:
            snap_day = days[-1]
            view = undiruv.korinish(today, day=snap_day, prefer_live=False)
            tab, cur_rows, cur_src = view["tab"], view["rows"], view["source"]
            # jonli o'qish xatosi haqidagi izoh yo'qolmasin (review DN6/CN5)
            view["notes"] = [n for n in birinchi_izoh if "o'qilmadi" in n] + [
                n for n in (view.get("notes") or []) if n not in birinchi_izoh]
    # Egaga izohlar: tab ambiguity/xato, ega qarorlari holati, oy oxiri ogohlantirishlari —
    # har biri alohida satr, belgisi bilan (PDF'da bir qatorga qo'shilib ketmasin — CN7)
    izoh_satrlar = undiruv.izoh_satrlari(view.get("notes") or [])
    tab_note = "\n".join(izoh_satrlar)
    if tab is None:
        oqilmadi = birinchi_src == "xato" or cur_src == "xato"
        msg = (f"⚠️ Undiruv push: joriy oy tabi «Undiruv {cur_month}({view.get('yil', today.year)})» "
               + ("O'QILMADI (jonli xato, snapshot'da ham yo'q) — PM'larga hech narsa yuborilmadi. "
                  "Keyinroq /pm_push force bilan qayta urining."
                  if oqilmadi else
                  "topilmadi (jonli va snapshot) — PM'larga hech narsa yuborilmadi. "
                  "Yangi oy tabi ochilganda avtomatik davom etadi.")
               + (f"\n{tab_note}" if tab_note else ""))
        if not dry_run:
            send_owner(msg)
            _save_state({"date": today.isoformat(), "tab": None, "sent": {}})
        log("joriy oy tabi yo'q — ogohlantirish yuborildi")
        return "no-tab", msg

    prev_rows = view["prev"]["rows"]
    # Manba: jonli bo'lmasa (birortasi snapshot) — banner chiqadi
    data_source = view.get("data_source", "live")
    per_pm, stats = build_push(today, cur_rows, prev_rows or [], prev_month, view=view)
    stats["pm_col_tab"] = tab  # guard xabari uchun
    # Yangi oy tabi birinchi marta o'qildi (o'tgan run boshqa tab edi)
    new_month_tab = bool(prev_tab) and fetchmod.norm(prev_tab) != fetchmod.norm(tab)

    contacts = load_contacts()
    slots = slots_from_config()
    nodate_pm = stats.get("nodate_pm", {})
    # by_slot: overdue/due-soon YOKI faqat-muddatsiz qatorli PM'lar ham kirsin
    # Bitta PM ismi ikki tabda ikki xil yozilishi mumkin («Azizxo'ja»/«Azizxo’ja») —
    # bir slotga BIRLASHTIRILADI (ilgari ikkinchisi birinchisining satrlarini
    # jimgina ustidan yozardi; keyingi oy qatorlari qo'shilgach xavf oshdi).
    by_slot, slot_n, slot_nd = _slotga_yig(per_pm, nodate_pm)

    dd = today.strftime("%d.%m.%Y")
    # Xabarlarni tayyorlash (yetkazish: EGANING akkauntidan, userbot_sender)
    msgs, no_contact, texts = [], {}, {}
    for slot, (pm_name, lines) in by_slot.items():
        text = _xabar_matni(dd, lines, slot_nd.get(slot, []))
        texts[slot] = text
        c = contacts.get(slot)
        if not c:
            no_contact[slot] = slot_n[slot]
            continue
        msgs.append((slot, c, text))

    sent, failed = {}, {}
    fallback_reason = ""
    userbot_note = ""      # kontakt yo'q bo'lsa ham userbot holati tekshiriladi
    if msgs and not dry_run:
        try:
            import userbot_sender

            for slot, ok2, err in userbot_sender.send_messages(msgs):
                if ok2:
                    sent[slot] = slot_n[slot]
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
            sent[slot] = slot_n[slot]
    elif no_contact:
        # Yuboriladigan xabar yo'q, chunki BIRORTA kontakt sozlanmagan.
        # Ilgari bu holatda userbot umuman chaqirilmasdi va uning nosozligi
        # "kontakt yo'q" ostida ko'rinmay qolardi — endi holat baribir
        # tekshiriladi (available() tarmoqqa chiqmaydi, arzon).
        try:
            import userbot_sender

            ok_u, why_u = userbot_sender.available()
            if not ok_u:
                userbot_note = why_u
        except Exception as e:
            userbot_note = f"{type(e).__name__}: {str(e)[:120]}"
        if userbot_note:
            log(f"userbot ham tayyor emas: {userbot_note}")

    # Egaga jamlama — boshida bannerlar: 🧊 SNAPSHOT + PM-ustun guard + reconcile
    L = []
    _banner = undiruv.snapshot_banner(data_source, snap_day)
    if _banner:
        L.append(_banner)
    L.extend(izoh_satrlar)             # tab/xato/qaror/oy oxiri izohlari — har biri alohida satr
    if new_month_tab:                  # yangi oy tabi birinchi marta o'qildi
        t = undiruv.totals(cur_rows)
        n_unpaid = sum(1 for r in cur_rows if undiruv.is_unpaid(r))
        L.append(f"🆕 Yangi oy tabi: «{tab}» — undirilmagan {n_unpaid} loyiha "
                 f"{_fmt(t.get('qoldiq', 0))}; kelishilgan {_fmt(t.get('kelishilgan', 0))}, "
                 f"undirildi {_fmt(t.get('undirildi', 0))} ({t.get('pct', 0):.0f}%).")
    # PM ustuni UMUMAN yo'q (avgust) — qora banner, PM'ga push yuborilmaydi
    if stats.get("pm_col_missing"):
        n = len(stats["pm_missing"])
        L.append(f"⚠️ **{stats['pm_col_tab']}** tabida «Ma'sul shaxs» ustuni YO'Q — "
                 f"{n} qator PM'ga yo'naltirilmadi (qo'lda yuborish uchun matn quyida).")
    _warn = undiruv.reconcile_warn(undiruv.totals(cur_rows))
    if _warn:
        L.append(_warn)
    manba = "jonli holat" if data_source == "live" else f"snapshot {snap_day}"
    L.append(f"📤 Undiruv push jamlamasi — {dd} (tab: {tab}, manba: {manba})")
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
    if no_contact:
        # Kontaktsizlik ALOHIDA va ko'rinadigan holat: PM qatorlari orasida
        # yo'qolib ketmasin — push haqiqatda ketmaganini bir qatorda aytadi.
        L.append(f"⚠️ {len(no_contact)} ta PM uchun kontakt sozlanmagan — "
                 f"push YUBORILMADI ({sum(no_contact.values())} eslatma kutmoqda). "
                 f"Sozlash: /pm_set <slot> @username")
    if userbot_note:
        L.append(f"⚠️ Userbot ham tayyor emas: {userbot_note} — kontakt "
                 "sozlangach ham yubora olmaydi")
    if fallback_reason:
        L.append(f"⚠️ Userbot: {fallback_reason} — bugun QO'LDA yuboring "
                 "(tayyor matnlar alohida keladi)")
    # Joriy oy raqami PDF badge/kartochkalari bilan AYNAN bir xil to'plamdan;
    # o'tgan oy qoldig'i alohida qo'shimcha bo'lib ko'rinadi (yig'ib yuborilmaydi).
    _od = f"⏰ Muddat o'tganlar: {stats['overdue_n']} ta, jami {_fmt(stats['overdue_sum'])}"
    if stats.get("overdue_carry_n"):
        _od += (f" · + {prev_month} qoldig'i: {stats['overdue_carry_n']} ta, "
                f"{_fmt(stats['overdue_carry_sum'])}")
    L.append(_od)
    if stats["status_blank"]:
        sb, tot = stats["status_blank"], stats.get("unpaid_n") or len(stats["status_blank"])
        # Oy boshida BARCHA qatorda status bo'sh bo'ladi — bu anomaliya emas.
        # Nomlar ro'yxati faqat qisman bo'sh bo'lgandagina ma'noli.
        if len(sb) >= 0.8 * tot:
            L.append(f"ℹ️ Status bo'sh: {len(sb)}/{tot} qator (deyarli hammasi) — "
                     f"oy boshida normal, D>0 bo'lgani uchun qarz sanaldi")
        else:
            det = ", ".join(sb[:6]) + (f" +{len(sb) - 6}" if len(sb) > 6 else "")
            L.append(f"⚠️ Status bo'sh: {len(sb)}/{tot} qator — D>0 bo'lgani uchun qarz "
                     f"sanaldi; sheet'da holatni belgilang: {det}")
    if stats["closed_carry"]:
        cc = stats["closed_carry"]
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, {_fmt(i['summa'])})" for i in cc[:6])
        more = f" +{len(cc) - 6}" if len(cc) > 6 else ""
        L.append(f"🧹 {prev_month.capitalize()} tabida yopilmagan ({cur_month}da to'langan "
                 f"yoki ketgan deb yozilgan): "
                 f"{len(cc)} ta, {_fmt(sum(i['summa'] for i in cc))} — sheet'ni tuzatish "
                 f"kerak: {det}{more}")
    if stats["moved_carry"]:
        mc = stats["moved_carry"]
        # nomi farqli (fuzzy) bog'lanishlar «A → B» bo'lib ko'rinadi — ega tekshira olsin (M3)
        det = ", ".join(f"{i['matn']} — {i['pm']}" for i in mc[:8])
        more = f" +{len(mc) - 8}" if len(mc) > 8 else ""
        L.append(f"🔁 {prev_month.capitalize()}dan {cur_month} tabiga ko'chirilgan "
                 f"(nomi mos va summa teng yoki ega qarori): {len(mc)} ta, "
                 f"{_fmt(sum(i['summa'] for i in mc))} — PM'ga IKKI marta "
                 f"so'ralmadi: {det}{more}")
    # Oy oxiri: keyingi oy tabi — ko'chganlar, muddati yaqinlar, tab yo'qligi (jim emas)
    k_oy = (stats.get("keyingi_oy") or "keyingi oy")
    if stats.get("keyingi_kochgan"):
        kc = stats["keyingi_kochgan"]
        det = ", ".join(i["matn"] for i in kc[:8])
        more = f" +{len(kc) - 8}" if len(kc) > 8 else ""
        L.append(f"🔁 {k_oy.capitalize()} tabiga ko'chirilgan — eski muddat bilan "
                 f"PM'dan SO'RALMADI: {len(kc)} ta, {_fmt(sum(i['summa'] for i in kc))}: {det}{more}")
    if stats.get("keyingi_yopilgan"):
        ky = stats["keyingi_yopilgan"]
        det = ", ".join(f"{i['matn']} — {i['pm']}" for i in ky[:8])
        L.append(f"🧹 {k_oy.capitalize()} tabida to'langan/ketgan deb yozilgan, eski tabda ochiq — "
                 f"PM'dan so'ralmadi, eski tabni tuzating: {len(ky)} ta, "
                 f"{_fmt(sum(i['summa'] for i in ky))}: {det}")
    if stats.get("keyingi_n"):
        # «eslatildi» emas: yetkazish holati (yuborildi/xato/kontakt yo'q/DRY) yuqoridagi
        # PM satrlarida — bu satr faqat nima qo'shilganini aytadi (review M10/C6/S7)
        L.append(f"📅 {k_oy.capitalize()} (keyingi oy, «{stats.get('keyingi_tab')}»): muddati "
                 f"≤{PUSH_DUE_DAYS} kun — {stats['keyingi_n']} ta, {_fmt(stats['keyingi_sum'])} — "
                 f"PM xabarlariga qo'shildi (yetkazish holati yuqorida)")
    elif stats.get("keyingi_bor") and not stats.get("keyingi_tab"):
        if stats.get("keyingi_source") == "xato":
            L.append(f"⚠️ {k_oy.capitalize()} tabi O'QILMADI (xato) — ko'chgan qarzlar eski muddat "
                     f"bilan so'raldi, keyingi oy to'lovlari eslatilmadi")
        else:
            L.append(f"ℹ️ {k_oy.capitalize()} tabi hali yo'q — keyingi oy to'lovlari oldindan eslatilmadi")
    if stats.get("farqli"):
        fq = stats["farqli"]
        det = ", ".join(f"{i['loyiha']} ({i['pm']}, {i['yonalish']}: {_fmt(i['otgan'])} → "
                        f"{_fmt(i['yangi'])})" for i in fq[:6])
        L.append(f"⚖️ Summa farqli — ko'chirilgan deb OLINMADI, o'tgan qoldiq ham so'ralmoqda "
                 f"(qaror kerak): {det}" + (f" +{len(fq) - 6}" if len(fq) > 6 else ""))
    if stats.get("noaniq"):
        L.append(f"⚠️ Moslik noaniq — qarz alohida so'ralmoqda (bir loyiha bo'lsa tabni "
                 f"tuzating): {'; '.join(stats['noaniq'][:6])}")
    for q in stats.get("qaror_qollangan") or []:
        L.append("📝 Ega qarori: " + q)
    for q in stats.get("qaror_izoh") or []:
        L.append("📝 " + q)
    # PM ustuni BOR, lekin ayrim kataklar bo'sh (ustun umuman yo'q bo'lsa
    # yuqorida qora banner chiqqan — bu yerda takrorlanmaydi)
    if stats["pm_missing"] and not stats["pm_col_missing"]:
        pmm = stats["pm_missing"]
        det = ", ".join(i["loyiha"] for i in pmm[:8]) + (f" +{len(pmm) - 8}" if len(pmm) > 8 else "")
        L.append(f"⚠️ PM'siz {len(pmm)} qator (PM katagi bo'sh — PM'ga ketmadi, "
                 f"qo'lda yuboring): {det}")
    if stats["aktiv_n"]:
        L.append(f"💳 Aktiv obuna (so'ralmaydi): {stats['aktiv_n']} loyiha, {_fmt(stats['aktiv_sum'])}")
    if stats["pauza"]:
        L.append(f"⏸ Pauza: {', '.join(stats['pauza'][:8])}")
    if stats["bad_sum"] or stats["no_date"]:
        parts = []
        if stats["bad_sum"]:
            parts.append(f"Summa son emas — {stats['bad_sum']} qator")
        if stats["no_date"]:
            nd_pm = sum(len(v) for v in stats.get("nodate_pm", {}).values())
            parts.append(f"sanasiz — {stats['no_date']} qator "
                         f"({nd_pm} tasi PM'ga «sana belgilanmagan» bo'limida yuborildi)")
        L.append("⚠️ Data: " + " · ".join(parts))
    summary = "\n".join(L)
    # Egaga: dizaynli PDF (jamlama bloki bilan); yiqilsa matn fallback.
    # dry_run'da ham egaga PDF ketadi (sinov ko'rinishi), faqat PM'lar va
    # state chetda qoladi.
    dd_title = ("🧪 [DRY] " if dry_run else "📤 ") + f"Undiruv push jamlamasi — {dd}"
    # push_info bloki: jamlama satrlari (📤-sarlavhasiz; reconciliation warn qoladi)
    push_lines = [x for x in L if not x.startswith("📤 Undiruv push jamlamasi")]
    pdf_src = "jonli holat" if data_source == "live" else f"snapshot {snap_day}"
    if not owner_pdf(cur_rows, tab, today, pdf_src, push_lines=push_lines,
                     title=dd_title, data_source=data_source,
                     overdue=(stats["overdue_n"], stats["overdue_sum"]), view=view):
        send_owner(("[DRY-RUN — PM'larga yuborilmadi]\n" if dry_run else "") + summary)
    # Userbot butunlay ishlamagan kun: egaga 4 TAYYOR matn — qo'lda yuborish uchun
    if fallback_reason and not dry_run:
        for slot, _c, text in msgs:
            send_owner(f"📋 {by_slot[slot][0]} uchun tayyor matn "
                       f"({contacts.get(slot, '?')}):\n\n{text}")
    # PM aniqlanmagan qatorlar (ustun yo'q yoki katak bo'sh) — qo'lda yuborish
    # uchun tayyor matn (userbot fallback'i kabi). dry'da ham egaga ko'rsatiladi.
    if stats["pm_missing"]:
        pmm_text = "\n".join(i["line"] for i in stats["pm_missing"])
        why = (f"«{stats['pm_col_tab']}» tabida PM ustuni yo'q"
               if stats["pm_col_missing"] else "PM katagi bo'sh")
        send_owner(f"📋 PM aniqlanmagan {len(stats['pm_missing'])} qator ({why}) — "
                   f"tegishli PM'ga QO'LDA yuboring:\n\n{pmm_text}")
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
    prev_month = undiruv.oy_ofset(today, -1)[0]
    # run_daily bilan AYNAN bir xil yig'uvchi (C3) — sinov xabari haqiqiysidan farq qilmasin
    view = undiruv.korinish(today, day=day, prefer_live=True)
    tab, cur_rows = view["tab"], view["rows"]
    if tab is None:
        days = sorted(d.name for d in diffmod.SNAPSHOTS.iterdir()
                      if d.is_dir() and len(d.name) == 10) if diffmod.SNAPSHOTS.is_dir() else []
        if days:
            day = days[-1]
            view = undiruv.korinish(today, day=day, prefer_live=False)
            tab, cur_rows = view["tab"], view["rows"]
    if tab is None:
        return f"«Undiruv {cur_month}» tabi topilmadi — sinov uchun ma'lumot yo'q."
    per_pm, _stats = build_push(today, cur_rows, view["prev"]["rows"] or [], prev_month, view=view)
    nodate_pm = _stats.get("nodate_pm", {})
    if not per_pm and not nodate_pm:
        return "Bugun birorta PM uchun eslatma yo'q — sinovga xabar chiqmadi."
    dd = today.strftime("%d.%m.%Y")
    # run_daily bilan AYNAN bir xil yig'uvchi: PM ismi variantlari bitta xabarga (review C8/S8)
    by_slot, _slot_n, slot_nd = _slotga_yig(per_pm, nodate_pm)
    msgs = []
    for slot, (pm_name, lines) in by_slot.items():
        text = (f"🧪 [SINOV — {pm_name} ko'radigan xabar]\n"
                + _xabar_matni(dd, lines, slot_nd.get(slot, [])))
        msgs.append((slot, "me", text))
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
