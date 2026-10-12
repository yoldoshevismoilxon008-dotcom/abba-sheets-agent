#!/usr/bin/env python3
"""Railway supervisor — bot va kunlik scheduler BITTA processda.

Boot tartibi:
  1. Secrets: GOOGLE_SA_JSON (base64 env) → DATA_DIR/credentials/service-account.json
  2. Brand seed: image'dagi data/brand → DATA_DIR/brand (faqat yo'q fayllar —
     bot orqali tasdiqlangan theme/logo redeploy'da saqlanib qoladi)
  3. APScheduler (background): har kuni 09:00 Asia/Tashkent → run.sh subprocess,
     09:30 PM push (pipeline tugashini kutadi). Restart/deploy 09:00 dan keyin bo'lsa
     boot catch-up o'sha kungi ishni 3 soat ichida bajaradi (daily_last_run.txt)
  4. bot_listener.main() — asosiy thread. Yiqilsa process o'ladi → Railway
     restart policy qayta ko'taradi (launchd KeepAlive ekvivalenti).

Kunlik pipeline'dan keyin hisobotlar repo'ga push (push_reports.py, env bo'lsa).
"""
import base64
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))


def log(msg):
    print(f"[supervisor] {msg}", flush=True)


def boot_secrets():
    """GOOGLE_SA_JSON (base64) → volume'dagi service-account.json (600)."""
    b64 = os.environ.get("GOOGLE_SA_JSON", "").strip()
    if not b64:
        return
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        log(f"XATO: GOOGLE_SA_JSON base64 o'qilmadi: {e}")
        return
    dst = DATA / "credentials" / "service-account.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.read_bytes() != raw:
        dst.write_bytes(raw)
        os.chmod(dst, 0o600)
        log(f"service account yozildi: {dst}")


def _copy_missing(src, dst):
    """src'dagi faylni dst'da YO'Q bo'lsagina nusxalaydi (volume ustun turadi)."""
    if not src.is_dir() or src.resolve() == dst.resolve():
        return 0
    copied = 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        t = dst / p.relative_to(src)
        if not t.exists():
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)
            copied += 1
    return copied


def boot_brand():
    """Image'dagi brand (git'dan) → volume. Foydalanuvchi keyin tasdiqlagan
    dizayn ustun turadi (faqat yo'q fayllar nusxalanadi)."""
    n = _copy_missing(BASE / "data" / "brand", DATA / "brand")
    if n:
        log(f"brand seed: {n} fayl volume'ga nusxalandi")


def boot_seed():
    """seed/ (git'dan) → volume — Mac'dan ko'chirilgan holat (ack ro'yxati,
    bot suhbat xotirasi). Bir martalik: volume'da bori qayta yozilmaydi."""
    n = _copy_missing(BASE / "seed", DATA)
    if n:
        log(f"holat seed: {n} fayl volume'ga nusxalandi")


# ---- Kunlik ishlar tartibi (P2) ----
# MemoryJobStore: konteyner 09:00 dan keyin restart/deploy bo'lsa cron keyingi kunga
# suriladi (misfire_grace_time faqat ISHLAB TURGAN scheduler'ga yordam beradi) — o'sha
# kungi hisobot va PM push jim o'tib ketardi. Bugungi pipeline marker fayli + boot
# catch-up shuni yopadi (oyna — misfire_grace_time bilan bir xil 3 soat). 09:30 PM push
# esa 09:00 pipeline TUGASHINI kutadi (ilgari kutmasdi).
TZ = "Asia/Tashkent"
DAILY_AT, PM_PUSH_AT = (9, 0), (9, 30)
CATCHUP_GRACE_H = 3
PM_WAIT_SEC = 50 * 60
DAILY_MARKER = DATA / "daily_last_run.txt"
# run.sh log'idagi «hisobot ketdi / pipeline tugadi» belgilari — marker yo'q bo'lsa ham
# (birinchi deploy kuni eski kod yuborgan, yoki restart send'dan keyin marker'dan oldin)
# bugungi hisobot qayta yuborilmasin (review: catch-up ikki marta yuborardi)
_DAILY_DONE_RE = re.compile(r"\[send\] PDF hisobot yuborildi|===== tugadi")
_PIPELINE_LOCK = threading.Lock()
_PM_LOCK = threading.Lock()


def _hozir():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(TZ))


def daily_job():
    """09:00 cron va boot catch-up: kunlik pipeline (lock ostida) + bugungi marker."""
    with _PIPELINE_LOCK:
        run_daily()
        try:
            DAILY_MARKER.parent.mkdir(parents=True, exist_ok=True)
            DAILY_MARKER.write_text(_hozir().date().isoformat(), encoding="utf-8")
        except Exception as e:
            log(f"kunlik marker yozilmadi: {e}")


def pm_push_job():
    """09:30: avval kunlik pipeline tugashini kutadi (ko'pi bilan PM_WAIT_SEC), keyin push.
    _PM_LOCK — cron va catch-up bir vaqtda ikki marta yubormasin."""
    if _PIPELINE_LOCK.acquire(timeout=PM_WAIT_SEC):
        _PIPELINE_LOCK.release()
    else:
        log(f"OGOHLANTIRISH: kunlik pipeline {PM_WAIT_SEC // 60} daqiqada tugamadi — "
            "PM push kutmasdan ishga tushdi")
    with _PM_LOCK:
        run_pm_push()


def catchup_kerak(hozir, at, marker_kun=""):
    """Bugungi `at` (soat, daqiqa) ishi o'tib ketganmi: vaqti kelgan, CATCHUP_GRACE_H
    oynasi ichida va bugun bajarilmagan (marker_kun — oxirgi bajarilgan kun)."""
    boshi = hozir.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    return boshi <= hozir < boshi + timedelta(hours=CATCHUP_GRACE_H) \
        and marker_kun != hozir.date().isoformat()


def bugun_bajarilganmi(kun, marker_kun=""):
    """Bugungi pipeline hisobotni yuborib bo'lganmi: marker YOKI run.sh log'ida
    PDF yuborilgani / pipeline tugagani (DATA/logs/<kun>.log)."""
    if marker_kun == kun:
        return True
    try:
        return bool(_DAILY_DONE_RE.search(
            (DATA / "logs" / f"{kun}.log").read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def boot_catchup():
    """Boot: bugungi pipeline / PM push restart sababli o'tib ketgan bo'lsa — bajaradigan
    funksiya (yoki None). PM push «bugun yuborilgan»ni o'zi tekshiradi (pm_push state)."""
    hozir = _hozir()
    try:
        marker = DAILY_MARKER.read_text(encoding="utf-8").strip()
    except Exception:
        marker = ""
    daily = catchup_kerak(hozir, DAILY_AT, marker) \
        and not bugun_bajarilganmi(hozir.date().isoformat(), marker)
    pm = catchup_kerak(hozir, PM_PUSH_AT)
    if not (daily or pm):
        return None

    def _ish():
        if daily:
            log("catch-up: bugungi 09:00 pipeline o'tib ketgan (restart/deploy) — hozir ishga tushadi")
            daily_job()
        if pm:
            log("catch-up: 09:30 PM push (bugun yuborilgan bo'lsa o'zi skip qiladi)")
            pm_push_job()
    return _ish


def run_daily():
    log("kunlik pipeline boshlandi (run.sh)")
    env = dict(os.environ, LOG_TEE="1")
    try:
        r = subprocess.run(["/bin/bash", str(BASE / "run.sh")], env=env, timeout=3600)
        log(f"kunlik pipeline tugadi (kod {r.returncode})")
    except subprocess.TimeoutExpired:
        log("XATO: kunlik pipeline 60 daqiqada tugamadi — to'xtatildi")
        return
    if os.environ.get("REPORTS_REPO"):
        try:
            pr = subprocess.run(
                [sys.executable, str(BASE / "push_reports.py")], env=env, timeout=600
            )
            log(f"hisobot push tugadi (kod {pr.returncode})")
        except subprocess.TimeoutExpired:
            log("XATO: hisobot push 10 daqiqada tugamadi")


def run_tg_kunlik_watch(today=None):
    """12:00 — Mac'dagi TG kunlik monitoring bugun kelganmi (AUDIT.md P0-2). Kelmagan
    bo'lsa egaga kuniga bir marta xabar: Mac uxlasa yoki push yo'qolsa hech kim bilmasdi."""
    try:
        import tg_kunlik
        from datetime import date

        today = today or date.today()
        h, err = tg_kunlik.tekshir(today)
        if err:
            _notify_owner_once_daily(f"⚠️ TG kunlik monitoring holatini tekshirib bo'lmadi: {err}",
                                     key="tg_kunlik")
            return
        if h is None:
            return
        msg = tg_kunlik.alert_text(today, h)
        log(f"tg-kunlik nazorat: {msg or 'bugungi natija bor'}")
        if msg:
            _notify_owner_once_daily(msg, key="tg_kunlik")
    except Exception as e:                       # noqa: BLE001
        log(f"XATO: tg-kunlik nazorat — {type(e).__name__}: {e}")


def run_pm_push():
    """PM'larga undiruv eslatmalari (09:30 — kunlik pipeline'dan keyin)."""
    log("PM undiruv push boshlandi")
    try:
        import pm_push

        status, _ = pm_push.run_daily()
        log(f"PM undiruv push tugadi ({status})")
    except Exception as e:
        log(f"XATO: PM undiruv push yiqildi — {type(e).__name__}: {e}")
        try:
            import send as sendmod

            token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            if token and chat:
                sendmod.tg_send(token, chat,
                                f"⚠️ PM undiruv push yiqildi: {str(e)[:200]}")
        except Exception:
            pass


def _notify_owner_once_daily(msg, key="vault_sync"):
    """Egaga kuniga ATIGI BIR MARTA Telegram xabar (10 daqiqalik xato spam bo'lmasin).
    key — alohida mavzu markeri (vault_sync va push_chat mustaqil xabar bersin)."""
    from datetime import date

    marker = DATA / f"{key}_notify.txt"
    today = date.today().isoformat()
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
            return
    except Exception:
        pass
    try:
        import send as sendmod

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if token and chat:
            sendmod.tg_send(token, chat, msg)
            marker.write_text(today, encoding="utf-8")
    except Exception as e:
        log(f"vault xato-notify yuborilmadi: {e}")


def run_vault_sync():
    """Har 10 daqiqada vault → KB sinxron. Xato bo'lsa bot ISHLASHDA DAVOM ETADI
    (KB yiqilsa Q&A davom etadi qoidasi) — xato faqat logga + egaga kuniga bir marta."""
    try:
        import vault_sync

        res = vault_sync.run()
        status = res.get("status")
        if status == "ok":
            c = res.get("counts") or {}
            if c.get("ingested") or c.get("archived") or c.get("errors"):
                log(f"vault sinxron: {c}")     # o'zgarish bo'lmasa jim (log shishmasin)
        elif status in ("git_error", "error"):
            import send as sendmod

            err = vault_sync._sanitize(str(res.get("error", "")))
            log(f"vault sinxron XATO: {err}")
            # notify tg_send (HTML) orqali ketadi — yo'l/URL <code> ichida (avtolink yo'q)
            _notify_owner_once_daily(
                "⚠️ Vault sinxron xatosi (bot ishlashda davom etmoqda):\n"
                + sendmod.code(err[:300])
            )
        else:
            # disabled / no_kbignore / unconfigured / busy — kutilgan holat, notify yo'q
            log(f"vault sinxron: {status}")
    except Exception as e:
        log(f"XATO: vault sinxron yiqildi — {type(e).__name__}: {e}")


def run_push_chat():
    """Har 10 daqiqada chat arxivini REPORTS_REPO'ga push (B2.2). Best-effort.
    Jim doimiy yiqilish ko'rinmas qolmasin: NOTIFY_AFTER ketma-ket xatodan keyin egaga
    (kuniga bir marta) xabar — chat arxivi Obsidian/bazaga bormayotganini bildiradi."""
    try:
        import push_chat

        push_chat.main()
        s = push_chat.stat()
        if s.get("fail_streak", 0) >= push_chat.NOTIFY_AFTER:
            import send as sendmod

            _notify_owner_once_daily(
                f"⚠️ Chat push {s['fail_streak']} marta ketma-ket yiqildi (~1 soat) — "
                "arxiv Obsidian/bazaga bormayapti:\n"
                + sendmod.code(str(s.get("last_error") or "")[:300]),
                key="push_chat",
            )
    except Exception as e:
        log(f"XATO: chat push yiqildi — {type(e).__name__}: {e}")


def main():
    log(f"boshlandi (DATA_DIR={DATA})")
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    boot_secrets()
    boot_brand()
    boot_seed()
    # Bilim bazasi (KB) — sxema (idempotent). Yiqilsa bot baribir ko'tariladi.
    try:
        import kb

        kb.init_db()
        log("kb: init ok")
    except Exception as e:
        log(f"kb init o'tkazildi (KB o'chiq, Q&A ishlashda davom etadi): {e}")
    # STT modeli (785MB) — fonda, bot bloklanmaydi; MODEL_URL bo'lmasa jim
    try:
        import stt

        stt.ensure_model_async()
    except Exception as e:
        log(f"stt model preload boshlanmadi: {e}")
    # Userbot session: TG_SESSION_B64 env -> /data (fayl bo'lsa tegilmaydi)
    try:
        import userbot_sender

        userbot_sender.ensure_session()
    except Exception as e:
        log(f"userbot session tayyorlanmadi: {e}")

    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="Asia/Tashkent")
    sched.add_job(
        daily_job, "cron", hour=DAILY_AT[0], minute=DAILY_AT[1],
        misfire_grace_time=CATCHUP_GRACE_H * 3600, coalesce=True,
    )
    sched.add_job(
        pm_push_job, "cron", hour=PM_PUSH_AT[0], minute=PM_PUSH_AT[1],
        misfire_grace_time=CATCHUP_GRACE_H * 3600, coalesce=True,
    )
    sched.add_job(
        run_tg_kunlik_watch, "cron", hour=12, minute=0,
        misfire_grace_time=3 * 3600, coalesce=True,
    )
    sched.add_job(
        run_vault_sync, "interval", minutes=10,
        max_instances=1, coalesce=True,
    )
    sched.add_job(
        run_push_chat, "interval", minutes=10,
        max_instances=1, coalesce=True,
    )
    catchup = boot_catchup()
    if catchup:
        # trigger'siz — darhol, fon thread'ida; misfire_grace_time=None: start kechiksa ham o'tkazilmaydi
        sched.add_job(catchup, id="catchup", misfire_grace_time=None)
    sched.start()
    log("scheduler tayyor: 09:00 pipeline + 09:30 PM undiruv + 12:00 TG-kunlik nazorat + "
        "har 10daq vault sinxron + chat push (Asia/Tashkent)")

    import bot_listener

    bot_listener.main()


if __name__ == "__main__":
    main()
