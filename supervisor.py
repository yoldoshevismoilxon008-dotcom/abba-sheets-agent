#!/usr/bin/env python3
"""Railway supervisor — bot va kunlik scheduler BITTA processda.

Boot tartibi:
  1. Secrets: GOOGLE_SA_JSON (base64 env) → DATA_DIR/credentials/service-account.json
  2. Brand seed: image'dagi data/brand → DATA_DIR/brand (faqat yo'q fayllar —
     bot orqali tasdiqlangan theme/logo redeploy'da saqlanib qoladi)
  3. APScheduler (background): har kuni 09:00 Asia/Tashkent → run.sh subprocess;
     misfire_grace_time 3 soat — deploy/restart 09:00 ga to'g'ri kelsa keyin bajaradi
  4. bot_listener.main() — asosiy thread. Yiqilsa process o'ladi → Railway
     restart policy qayta ko'taradi (launchd KeepAlive ekvivalenti).

Kunlik pipeline'dan keyin hisobotlar repo'ga push (push_reports.py, env bo'lsa).
"""
import base64
import os
import shutil
import subprocess
import sys
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


def main():
    log(f"boshlandi (DATA_DIR={DATA})")
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    boot_secrets()
    boot_brand()
    boot_seed()
    # STT modeli (785MB) — fonda, bot bloklanmaydi; MODEL_URL bo'lmasa jim
    try:
        import stt

        stt.ensure_model_async()
    except Exception as e:
        log(f"stt model preload boshlanmadi: {e}")

    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="Asia/Tashkent")
    sched.add_job(
        run_daily, "cron", hour=9, minute=0,
        misfire_grace_time=3 * 3600, coalesce=True,
    )
    sched.add_job(
        run_pm_push, "cron", hour=9, minute=30,
        misfire_grace_time=3 * 3600, coalesce=True,
    )
    sched.start()
    log("scheduler tayyor: 09:00 pipeline + 09:30 PM undiruv push (Asia/Tashkent)")

    import bot_listener

    bot_listener.main()


if __name__ == "__main__":
    main()
