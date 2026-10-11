#!/usr/bin/env python3
"""Railway supervisor — bot va kunlik scheduler BITTA processda.

Boot tartibi:
  1. Secrets: GOOGLE_SA_JSON (base64 env) → DATA_DIR/credentials/service-account.json,
     UNDIRUV_QAROR_B64 → DATA_DIR/undiruv_qaror.json; Sheet ID'lar tekshiriladi
     (CONFIG_LOCAL_B64 / config.local.yaml — yo'q bo'lsa egaga ogohlantirish)
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


from maxfiy import redact  # noqa: E402  (audit P0-1: log'da token/sir yo'q)


def log(msg):
    print(f"[supervisor] {redact(msg)}", flush=True)


def _env_fayl(var, dst):
    """Env (base64) → volume'dagi fayl (600). Env manba: o'zgarsa fayl yangilanadi."""
    b64 = os.environ.get(var, "").strip()
    if not b64:
        return False
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        log(f"XATO: {var} base64 o'qilmadi: {type(e).__name__}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.read_bytes() != raw:
        dst.write_bytes(raw)
        os.chmod(dst, 0o600)
        log(f"{var} → {dst} yozildi")
    return True


def boot_secrets():
    """Railway Variables (base64) → volume:
      GOOGLE_SA_JSON    → credentials/service-account.json
      UNDIRUV_QAROR_B64 → undiruv_qaror.json (ega qarorlari — public repo'da emas, P0-2).
    Sheet ID'lar (CONFIG_LOCAL_B64) faylga yozilmaydi — fetch env'dan to'g'ridan-to'g'ri o'qiydi."""
    _env_fayl("GOOGLE_SA_JSON", DATA / "credentials" / "service-account.json")
    boot_qarorlar()


QAROR_ENV = "UNDIRUV_QAROR_B64"


def boot_qarorlar():
    """UNDIRUV_QAROR_B64 → DATA/undiruv_qaror.json. Env — manba: qiymat buzuq bo'lsa yoki
    o'chirilsa, avval env'dan yozilgan fayl JIM qo'llanaverib qolmasin (review) — u
    .stale ga olinadi va egaga ⚠️. Qo'lda qo'yilgan fayl (env'dan yozilmagan) tegilmaydi."""
    dst = DATA / "undiruv_qaror.json"
    belgi = DATA / "undiruv_qaror.json.env"          # fayl env'dan yozilganini bildiradi
    b64 = "".join(os.environ.get(QAROR_ENV, "").split())
    if not b64:
        if belgi.exists() and dst.exists():
            dst.replace(DATA / "undiruv_qaror.json.stale")
            belgi.unlink()
            _qaror_ogohlantir(f"{QAROR_ENV} o'chirilgan — eski qarorlar qo'llanmaydi "
                              "(undiruv_qaror.json.stale ga olindi)")
        return False
    try:
        import json

        raw = base64.b64decode(b64, validate=True)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("qarorlar"), list):
            raise ValueError("«qarorlar» ro'yxati yo'q")
    except Exception as e:                           # noqa: BLE001
        if dst.exists():
            dst.replace(DATA / "undiruv_qaror.json.stale")
        belgi.unlink(missing_ok=True)
        _qaror_ogohlantir(f"{QAROR_ENV} buzuq ({type(e).__name__}) — ega qarorlari QO'LLANMAYDI, "
                          "qiymatni qayta nusxalang")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.read_bytes() != raw:
        dst.write_bytes(raw)
        os.chmod(dst, 0o600)
        log(f"{QAROR_ENV} → {dst} yozildi")
    belgi.write_text("env\n", encoding="utf-8")
    return True


def _qaror_ogohlantir(sabab):
    msg = f"⚠️ abba-sheets-agent: {sabab}."
    log(msg)
    _notify_owner_once_daily(msg, key="undiruv_qaror")


def boot_config_check():
    """Maxfiy konfiguratsiya holati (boot'da va har kuni 09:00 dan oldin): Sheet ID'lar,
    nomi mos kelmagan sheet'lar, dashboard_id, ega qarorlari fayli. Muammo bo'lsa egaga
    kuniga bir marta ⚠️ — jim tushib qolish bo'lmasin (review P0-2). True — hammasi joyida."""
    try:
        import fetch
        import undiruv

        bor = fetch.load_config(include_qa_only=True)
        idsiz, ortiqcha, dash_ok = fetch.overlay_holati()
        qaror_ok = undiruv.qaror_fayl().exists()
    except Exception as e:                          # noqa: BLE001
        log(f"config tekshiruvi o'tkazildi: {type(e).__name__}: {e}")
        return False
    if not bor:
        msg = ("⚠️ abba-sheets-agent: Google Sheet ID'lar topilmadi — CONFIG_LOCAL_B64 (Railway "
               "Variables) yoki config.local.yaml o'rnatilmagan. Kunlik hisobot, Q&A va PM "
               "eslatmalari ishlamaydi. Yasash: python3 scripts/maxfiy_migratsiya.py")
        log(msg)
        _notify_owner_once_daily(msg, key="config_ids")
        return False
    satrlar = []
    if idsiz:
        satrlar.append("ID'si yo'q sheet'lar (o'qilmaydi): " + ", ".join(idsiz))
    if ortiqcha:
        satrlar.append("hech qaysi sheet nomiga mos kelmagan ID kalitlari: " + ", ".join(ortiqcha))
    if not dash_ok:
        satrlar.append("dashboard_id yo'q — dashboard yangilanmaydi")
    if not qaror_ok:
        satrlar.append(f"undiruv_qaror.json yo'q ({QAROR_ENV} o'rnatilmagan) — ega qarorlari "
                       "qo'llanmaydi, o'tgan oy qoldiqlari alohida so'raladi")
    if satrlar:
        msg = "⚠️ abba-sheets-agent konfiguratsiyasi:\n• " + "\n• ".join(satrlar)
        log(msg)
        _notify_owner_once_daily(msg, key="config_holat")
        return False
    return True


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
    boot_config_check()                 # ID/qaror muammosi har kuni egaga ko'rinsin (kuniga 1 marta)
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
    boot_config_check()
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
        run_daily, "cron", hour=9, minute=0,
        misfire_grace_time=3 * 3600, coalesce=True,
    )
    sched.add_job(
        run_pm_push, "cron", hour=9, minute=30,
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
    sched.start()
    log("scheduler tayyor: 09:00 pipeline + 09:30 PM undiruv + har 10daq vault sinxron + chat push (Asia/Tashkent)")

    import bot_listener

    bot_listener.main()


if __name__ == "__main__":
    main()
