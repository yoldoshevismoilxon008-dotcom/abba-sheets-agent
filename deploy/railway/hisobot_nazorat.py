#!/usr/bin/env python3
"""Railway hisobot nazorati — Mac tomonida, Railway'dan TASHQARIDA.

13.11 hodisasi: Railway servisni 12.11 20:50 da to'xtatgan (platforma tomonida). Shundan
keyin 09:00 run ham, 🩺 health ham, 12:00 xabari ham yo'qoldi — ularning hammasi
Railway ichidan ketadi, servis o'chsa o'zi haqida xabar bera olmaydi
(claude-brain: bilim/avtomatik-tizim-qoidalari B6). Bu skript Mac'da ishlaydi va
hisobotlar repo'si klonida (~/.abba-hisobotlar) bugungi «hisobot YYYY-MM-DD» commit'ini
qidiradi. Commit'ni Railway'dagi push_reports.py yozadi, muallifi abba-sheets-agent.

Klonni com.abba.reports-pull har 10 daqiqada tortadi (deploy/railway/vault_pull.sh).
Bu skript klonga YOZMAYDI, ikki job bitta klonda to'qnashmasin. Klon qachon tortilgani
FETCH_HEAD vaqtidan olinadi: muvaffaqiyatli fetch uni har safar qayta yozadi.

Qoida (Asia/Tashkent; run har kuni, dam olish kunlari ham — supervisor.py cron'ida kun
cheklovi yo'q):
  • 09:30 gacha — hech narsa qilmaydi (run 09:00–09:01 da tushadi).
  • Commit bor → jim. Bugun ogohlantirish ketgan bo'lsa, o'sha kanallarga bir marta «✅ keldi».
  • Commit yo'q va klon 09:30 dan KEYIN tortilgan → «⚠️ run bo'lmadi» (kuniga bir marta).
  • Commit yo'q, klon 09:30 dan beri tortilmagan → hali qaror yo'q, kutiladi. Mac uxlagan
    yoki endi uyg'ongan, internet yo'q yoki GitHub SSH ishlamayapti — bularni farqlab
    bo'lmaydi. Bu holat Mac uyg'oq paytida ESKI_CHEGARA marta (~2 soat) davom etsa →
    «⚠️ tekshirib bo'lmadi» (kuniga bir marta). Jim qolinmaydi (A2).

Kanallar: macOS bildirishnomasi (osascript) va Telegram (.env dagi TELEGRAM_BOT_TOKEN va
TELEGRAM_CHAT_ID). Token log'ga ham, holat fayliga ham yozilmaydi. Har kanal alohida
kuzatiladi: vaqtinchalik xato bo'lsa, keyingi ishga tushishda qayta uriniladi (kuniga
ko'pi bilan MAX_URINISH marta). 4xx (token eskirgan, chat topilmadi) bo'lsa, o'sha kuni
qayta urinilmaydi.

Ishga tushirish: launchd com.abba.hisobot-nazorat, har 10 daqiqa va RunAtLoad
(deploy/railway/nazorat_install.sh o'rnatadi). Faqat standart kutubxona —
/usr/bin/python3 (3.9) bilan ishlaydi.
Sinov: --hozir 2026-11-13T09:40 --quruq (soxta vaqt, hech narsa yubormaydi);
kanallarni tekshirish: --sinov (holatga tegmaydi).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Tashkent")
except Exception:                                   # noqa: BLE001 — zoneinfo yo'q: UTC+5, DST yo'q
    from datetime import timezone

    TZ = timezone(timedelta(hours=5), "Asia/Tashkent")

MUDDAT = dtime(9, 30)          # shu vaqtgacha bugungi hisobot commit'i tushgan bo'lishi kerak
# supervisor.py dagi DAILY_AT va DAILY_AT + CATCHUP_GRACE_H bilan bir xil bo'lsin (test tekshiradi)
RUN_VAQTI = dtime(9, 0)
CATCHUP_TUGASH = dtime(12, 0)
ESKI_CHEGARA = 12              # klon 09:30 dan beri tortilmagan holda shuncha ishga tushish ≈ 2 soat uyg'oq
MAX_URINISH = 3                # vaqtinchalik xatoda bitta kanalga bitta xabar uchun kuniga
AUTHOR = "abba-sheets-agent"
_HISOBOT_RE = re.compile(r"^hisobot (\d{4}-\d{2}-\d{2})$")
TG_API = os.environ.get("HISOBOT_NAZORAT_TG_API", "https://api.telegram.org")
OSASCRIPT = os.environ.get("HISOBOT_NAZORAT_OSASCRIPT", "/usr/bin/osascript")

HOME = Path.home()
KLON = HOME / ".abba-hisobotlar"
UY = HOME / ".abba-nazorat"
ENV = HOME / "abba-sheets-agent" / ".env"

_SIRLAR = set()                # log/holatga chiqmasligi kerak bo'lgan qiymatlar (token)


def _toza(s):
    s = str(s)
    for sir in _SIRLAR:
        if sir:
            s = s.replace(sir, "***")
    return s


def log(msg):
    t = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[hisobot-nazorat] {t} {_toza(msg)}", flush=True)


def _dm(d):
    return d.strftime("%d.%m")


# ---- Klon ----

def _git(klon, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "-C", str(klon), *args], capture_output=True, text=True,
                       timeout=30, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout


def hisobotlar(klon):
    """{sana_iso: commit vaqti} — AUTHOR'ning «hisobot <sana>» commit'lari, barcha ref'lardan.
    `--all`: rebase yiqilsa ham fetch qilingan origin/main ko'rinadi. Bir kunga bir nechta
    commit bo'lsa, eng ertasi olinadi."""
    out = _git(klon, "log", "--all", "-n", "500", f"--author={AUTHOR}",
               "--format=%an%x1f%s%x1f%ct")
    res = {}
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3 or parts[0] != AUTHOR:
            continue
        m = _HISOBOT_RE.match(parts[1].strip())
        if not m:
            continue
        t = datetime.fromtimestamp(int(parts[2]), TZ)
        if m.group(1) not in res or t < res[m.group(1)]:
            res[m.group(1)] = t
    return res


def sinxron_vaqti(klon):
    """Klon oxirgi marta muvaffaqiyatli tortilgan vaqt (FETCH_HEAD mtime) yoki None."""
    p = _git(klon, "rev-parse", "--git-path", "FETCH_HEAD").strip()
    f = Path(p) if os.path.isabs(p) else Path(klon) / p
    try:
        return datetime.fromtimestamp(f.stat().st_mtime, TZ)
    except OSError:
        return None


# ---- Xabarlar: {sarlavha, qisqa (macOS), toliq (Telegram)} ----

def _oxirgi_matn(oxirgi, bugun):
    if not oxirgi:
        return "oxirgi 500 commit ichida hisobot topilmadi"
    sana, t = oxirgi
    n = (bugun - datetime.strptime(sana, "%Y-%m-%d").date()).days
    return f"{_dm(t)} {t:%H:%M} ({n} kun oldin)"


def xabar_yoq(bugun, oxirgi, hozir):
    dm, ox = _dm(bugun), _oxirgi_matn(oxirgi, bugun)
    catchup = hozir.time() < CATCHUP_TUGASH
    return {
        "sarlavha": "⚠️ ABBA hisobot: bugun run bo'lmadi",
        "qisqa": f"{dm} {RUN_VAQTI:%H:%M} hisoboti kelmadi. Oxirgisi: {ox}. "
                 "Railway (honest-clarity) va Billing'ni tekshiring.",
        "toliq": (
            f"⚠️ abba-sheets-agent: bugungi ({dm}) {RUN_VAQTI:%H:%M} hisobot kelmadi.\n"
            f"Hisobotlar repo'sida «hisobot {bugun.isoformat()}» commit'i yo'q "
            f"(Mac {hozir:%H:%M} da tekshirdi). Oxirgi hisobot: {ox}.\n"
            "Railway servisi to'xtagan (to'lov yoki deploy) yoki run/push yiqilgan bo'lishi "
            "mumkin. Railway → honest-clarity → deploy log va Billing'ni tekshiring.\n"
            + (f"Servis {CATCHUP_TUGASH:%H:%M} gacha tiklansa, bugungi run o'zi yuradi (catch-up)."
               if catchup else
               f"Catch-up oynasi ({CATCHUP_TUGASH:%H:%M} gacha) o'tgan: servis tiklansa, keyingi "
               f"run ertaga {RUN_VAQTI:%H:%M} da.")
        ),
    }


def xabar_noma(bugun, oxirgi, sinxron, xato):
    dm, ox = _dm(bugun), _oxirgi_matn(oxirgi, bugun)
    if xato:
        sabab = f"klonni o'qib bo'lmadi: {xato}"
    elif sinxron:
        sabab = f"repo {_dm(sinxron)} {sinxron:%H:%M} dan beri tortilmayapti"
    else:
        sabab = "repo hali bir marta ham tortilmagan (FETCH_HEAD yo'q)"
    return {
        "sarlavha": "⚠️ ABBA hisobot: tekshirib bo'lmadi",
        "qisqa": f"Bugungi ({dm}) run noma'lum: {sabab}. Internet, GitHub SSH yoki reports-pull.",
        "toliq": (
            f"⚠️ abba-sheets-agent: bugungi ({dm}) hisobotni Mac tekshira olmadi — {sabab}.\n"
            "Sabab: internet, GitHub SSH yoki com.abba.reports-pull. "
            f"Oxirgi ko'ringan hisobot: {ox}.\n"
            "Log: ~/abba-sheets-agent/data/logs/reports-pull.log"
        ),
    }


def xabar_tiklandi(bugun, t):
    dm = _dm(bugun)
    return {
        "sarlavha": "✅ ABBA hisobot keldi",
        "qisqa": f"Bugungi ({dm}) hisobot {t:%H:%M} da keldi.",
        "toliq": f"✅ abba-sheets-agent: bugungi ({dm}) hisobot keldi — {t:%H:%M}. "
                 "Ertalabki ogohlantirish endi o'rinsiz.",
    }


def xabar_sinov():
    return {
        "sarlavha": "🧪 ABBA hisobot nazorati: sinov",
        "qisqa": "Sinov xabari. Ogohlantirish shu ko'rinishda keladi.",
        "toliq": "🧪 abba-sheets-agent hisobot nazorati (Mac): sinov xabari. Bugungi hisobot "
                 f"{MUDDAT:%H:%M} gacha kelmasa, ogohlantirish shu yerga keladi.",
    }


# ---- Kanallar: f(xabar) -> (holat, xato); holat ∈ ok | xato | doimiy_xato ----

def mac_yubor(xabar):
    """macOS bildirishnomasi. Matn argv orqali beriladi — AppleScript qo'shtirnoq/apostrof
    muammosi yo'q."""
    cmd = [OSASCRIPT,
           "-e", "on run argv",
           "-e", 'display notification (item 2 of argv) with title (item 1 of argv) '
                 'sound name "Glass"',
           "-e", "end run",
           xabar["sarlavha"], xabar["qisqa"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return "doimiy_xato", f"{OSASCRIPT} topilmadi"
    except subprocess.TimeoutExpired:
        return "xato", "osascript 20 s da tugamadi"
    if r.returncode != 0:
        return "xato", f"osascript kod {r.returncode}: {r.stderr.strip()[:150]}"
    return "ok", None


def tg_yubor(token, chat_id, matn, api=None):
    """Telegram sendMessage. Token faqat URL'da — xato matnlarida «***» bilan almashtiriladi.
    4xx (429 dan tashqari) — doimiy: token eskirgan/noto'g'ri, chat topilmadi."""
    def yashir(s):
        return s.replace(token, "***") if token else s

    api = (api or TG_API).rstrip("/")
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": matn,
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"{api}/bot{token}/sendMessage", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode("utf-8")).get("description", "")
        except Exception:                           # noqa: BLE001
            desc = ""
        holat = "xato" if e.code == 429 or e.code >= 500 else "doimiy_xato"
        return holat, yashir(f"HTTP {e.code} {desc}".strip())
    except Exception as e:                          # noqa: BLE001 — tarmoq, TLS, timeout
        return "xato", yashir(f"{type(e).__name__}: {e}")
    if body.get("ok"):
        return "ok", None
    return "doimiy_xato", yashir(f"ok=false {body.get('description', '')}")


def env_oqi(path):
    """Oddiy KEY=VALUE .env o'quvchi (export, qo'shtirnoq, izohlar). Fayl yo'q → {}."""
    d = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return d
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        k, sep, v = s.partition("=")
        if not sep:
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        else:
            v = v.split(" #", 1)[0].strip()
        d[k.strip()] = v
    return d


def yuboruvchilar(kanal, env_path, quruq=False):
    """{nom: f(xabar)} — `kanal` dagi kanallar («mac,telegram»). quruq — hech narsa
    yubormaydi, xabarni stdout'ga chiqaradi."""
    res = {}
    for nom in [k.strip() for k in kanal.split(",") if k.strip()]:
        if quruq:
            def f(xabar, nom=nom):
                matn = xabar["toliq"] if nom == "telegram" else f"{xabar['sarlavha']} — {xabar['qisqa']}"
                print(f"[quruq:{nom}] {matn}")
                return "ok", None
            res[nom] = f
        elif nom == "mac":
            res[nom] = mac_yubor
        elif nom == "telegram":
            env = env_oqi(env_path)
            token = env.get("TELEGRAM_BOT_TOKEN", "")
            chat = env.get("TELEGRAM_CHAT_ID", "")
            _SIRLAR.add(token)
            if token and chat:
                res[nom] = lambda xabar, token=token, chat=chat: tg_yubor(token, chat, xabar["toliq"])
            else:
                yoq = ", ".join(k for k, v in (("TELEGRAM_BOT_TOKEN", token),
                                               ("TELEGRAM_CHAT_ID", chat)) if not v)
                res[nom] = lambda xabar, yoq=yoq: ("doimiy_xato", f"{env_path} da {yoq} yo'q")
        else:
            log(f"noma'lum kanal: {nom} — o'tkazildi")
    return res


# ---- Holat (kuniga bitta yozuv) ----

def holat_oqi(path, bugun_iso):
    try:
        h = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(h, dict) and h.get("sana") == bugun_iso:
            return h
    except (OSError, ValueError):
        pass
    return {"sana": bugun_iso}


def holat_yoz(path, h):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _yubor(holat_k, kanallar, xabar, tur, hozir):
    """Har kanalga bir marta: «ok» yoki «doimiy_xato» bo'lgan, yoki MAX_URINISH tugagan
    kanal qayta urinilmaydi. holat_k — {kanal: {holat, urinish, vaqt, xato?}}."""
    for nom, f in kanallar.items():
        st = holat_k.get(nom) or {}
        if st.get("holat") in ("ok", "doimiy_xato") or st.get("urinish", 0) >= MAX_URINISH:
            continue
        try:
            natija, xato = f(xabar)
        except Exception as e:                      # noqa: BLE001
            natija, xato = "xato", f"{type(e).__name__}: {e}"
        yangi = {"holat": natija, "urinish": st.get("urinish", 0) + 1, "vaqt": f"{hozir:%H:%M}"}
        if xato:
            yangi["xato"] = _toza(xato)[:200]
        holat_k[nom] = yangi
        log(f"{tur} → {nom}: {natija}" + (f" ({_toza(xato)})" if xato else ""))


def ishga_tushir(hozir, klon, holat_fayl, kanallar):
    """Bitta tekshiruv. Qaytaradi: erta | bor | yoq | kutish | noma'lum."""
    bugun = hozir.date()
    iso = bugun.isoformat()
    muddat = datetime.combine(bugun, MUDDAT, TZ)
    if hozir < muddat:
        return "erta"
    h = holat_oqi(holat_fayl, iso)
    xato = None
    try:
        hs = hisobotlar(klon)
        sinxron = sinxron_vaqti(klon)
    except Exception as e:                          # noqa: BLE001 — klon yo'q, git yo'q, timeout
        hs, sinxron, xato = {}, None, f"{type(e).__name__}: {e}"
    oldingi = sorted((s, t) for s, t in hs.items() if s <= iso)
    oxirgi = oldingi[-1] if oldingi else None
    bugungi = hs.get(iso)

    if bugungi:
        natija = "bor"
        if h.get("natija") != "bor":
            log(f"{iso}: bugungi hisobot bor ({bugungi:%H:%M})")
        yetgan = {k for tur in (h.get("ogoh") or {}).values() for k, st in tur.items()
                  if st.get("holat") == "ok"}
        if yetgan:
            _yubor(h.setdefault("tiklandi", {}), {k: f for k, f in kanallar.items() if k in yetgan},
                   xabar_tiklandi(bugun, bugungi), "tiklandi", hozir)
    elif (sinxron and sinxron >= muddat) or h.get("natija") == "yoq":
        # «yo'q» kun davomida saqlanadi: keyin klon yana eskirsa ham qaror o'zgarmaydi
        natija = "yoq"
        if h.get("natija") != "yoq":
            log(f"{iso}: bugungi hisobot YO'Q (klon {sinxron:%H:%M} da tortilgan; "
                f"oxirgisi: {_oxirgi_matn(oxirgi, bugun)})")
        _yubor(h.setdefault("ogoh", {}).setdefault("yoq", {}), kanallar,
               xabar_yoq(bugun, oxirgi, hozir), "ogohlantirish", hozir)
    else:
        h["eskirgan"] = h.get("eskirgan", 0) + 1
        if h["eskirgan"] == 1:
            if xato:
                sabab = f"klonni o'qib bo'lmadi ({xato})"
            elif sinxron:
                sabab = (f"klon {muddat:%H:%M} dan beri tortilmagan "
                         f"(oxirgi: {sinxron:%d.%m %H:%M})")
            else:
                sabab = "klon hali tortilmagan (FETCH_HEAD yo'q)"
            log(f"{iso}: hali qaror yo'q — {sabab}")
        if h["eskirgan"] >= ESKI_CHEGARA:
            natija = "noma'lum"
            _yubor(h.setdefault("ogoh", {}).setdefault("tekshirib_bolmadi", {}), kanallar,
                   xabar_noma(bugun, oxirgi, sinxron, xato), "tekshirib bo'lmadi", hozir)
        else:
            natija = "kutish"
    h["natija"] = natija if natija in ("bor", "yoq") else h.get("natija")
    h["oxirgi_tekshiruv"] = f"{hozir:%H:%M}"
    holat_yoz(holat_fayl, h)
    return natija


def _vaqt(s):
    t = datetime.fromisoformat(s)
    return t.replace(tzinfo=TZ) if t.tzinfo is None else t.astimezone(TZ)


def _yiqildi_ogohlantir(holat_fayl, e):
    """Skriptning o'zi yiqilsa — kuniga bir marta macOS bildirishnomasi (jim o'lmasin)."""
    marker = Path(holat_fayl).with_name("yiqildi.txt")
    bugun = datetime.now(TZ).date().isoformat()
    try:
        if marker.read_text(encoding="utf-8").strip() == bugun:
            return
    except OSError:
        pass
    mac_yubor({"sarlavha": "⚠️ ABBA hisobot nazorati yiqildi",
               "qisqa": f"{type(e).__name__}: {str(e)[:120]}. Log: ~/.abba-nazorat/nazorat.log"})
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(bugun, encoding="utf-8")
    except OSError:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Railway hisobot nazorati (Mac)")
    ap.add_argument("--klon", default=str(KLON), help="hisobotlar repo kloni")
    ap.add_argument("--holat", default=str(UY / "holat.json"), help="kunlik holat fayli")
    ap.add_argument("--env", default=str(ENV), help="TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manbasi")
    ap.add_argument("--kanal", default="mac,telegram", help="mac,telegram")
    ap.add_argument("--hozir", help="soxta vaqt, masalan 2026-11-13T09:40 (Toshkent)")
    ap.add_argument("--quruq", action="store_true", help="hech narsa yubormaydi, xabarni chiqaradi")
    ap.add_argument("--sinov", action="store_true", help="kanallarga sinov xabari (holatga tegmaydi)")
    a = ap.parse_args(argv)
    try:
        kanallar = yuboruvchilar(a.kanal, Path(a.env).expanduser(), quruq=a.quruq)
        if a.sinov:
            bad = 0
            for nom, f in kanallar.items():
                natija, xato = f(xabar_sinov())
                print(f"sinov → {nom}: {natija}" + (f" ({_toza(xato)})" if xato else ""))
                bad += natija != "ok"
            return 1 if bad else 0
        hozir = _vaqt(a.hozir) if a.hozir else datetime.now(TZ)
        natija = ishga_tushir(hozir, Path(a.klon).expanduser(), Path(a.holat).expanduser(), kanallar)
        if a.hozir or a.quruq:
            print(f"natija: {natija}")
        return 0
    except Exception as e:                          # noqa: BLE001
        log(f"XATO: {type(e).__name__}: {e}")
        if not (a.quruq or a.hozir or a.sinov):
            _yiqildi_ogohlantir(Path(a.holat).expanduser(), e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
