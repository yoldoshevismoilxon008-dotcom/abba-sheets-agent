"""Ikkinchi miya yig'uvchisi — umumiy yadro.

Mac'da ishlaydi (launchd, soatlik). Manbalardan (Claude sessiyalari, skillar, kod,
WALL-E kunlik ma'lumotlari) Obsidian vault'ga (~/claude-brain) avtomatik yozuvlar
yaratadi. Bu fayl: yo'llar, vaqt, slug, frontmatter, maxfiy qiymatlarni yashirish
va xavfsiz yozuvchi.

Qat'iy qoidalar:
  - Faqat AVTO_JOYLAR ichiga yozadi. Qolgan vault (kunlik/, bilim/, loyihalar) —
    egasi va Claude sessiyalari qo'lda yozadi, yig'uvchi ularga TEGMAYDI.
  - `manba: miya-avto` belgisi yo'q mavjud faylga hech qachon yozmaydi.
  - Kontent o'zgarmasa faylga tegmaydi: git va WALL-E bilim bazasi (vault_sync har
    o'zgargan katta fayl uchun Claude chaqiradi) behuda yangilanmasin.
  - QOLDA belgisidan pastdagi qism (egasi Obsidian'da yozgan izoh) saqlanadi.
  - Python 3.9 (macOS /usr/bin/python3), faqat standart kutubxona.
  - Bu repo PUBLIC: kodda shaxsiy ma'lumot (ism, kontakt, mijoz nomi) bo'lmasin.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
TZ = ZoneInfo("Asia/Tashkent")


def vault() -> Path:
    return Path(os.environ.get("MIYA_VAULT") or HOME / "claude-brain")


def claude_dir() -> Path:
    return Path(os.environ.get("MIYA_CLAUDE_DIR") or HOME / ".claude")


def state_dir() -> Path:
    return Path(os.environ.get("MIYA_STATE") or HOME / ".abba-miya" / "state")


# Yig'uvchi yozadigan joylar (vault ildiziga nisbiy). Boshqa hamma joy — qo'lda.
AVTO_JOYLAR = ("claude/", "kod/", "wall-e/", "tizim/", "BOSH-SAHIFA.md")
BELGI = "manba: miya-avto"            # frontmatter'dagi avto-yozuv belgisi
BELGI_BASE = "# manba: miya-avto"     # .base (YAML) fayllar uchun
QOLDA = "<!-- miya:qo'lda -->"         # shu qatordan pastdagi matn saqlanadi
QOLDA_BLOK = ("\n## ✍️ Izohlarim\n" + QOLDA + "\n"
              "_Shu chiziqdan pastga yozganingiz avtomatik yangilanishda saqlanadi._\n")


# ---------------------------------------------------------------- vaqt

def ts_parse(s) -> datetime | None:
    """ISO ('...Z' ham) yoki epoch-ms/sekund → aware datetime (UTC). Xato → None."""
    if s is None or s == "":
        return None
    try:
        if isinstance(s, (int, float)):
            v = float(s)
            if v > 1e12:          # millisekund
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        t = str(s).strip().replace("Z", "+00:00")
        # 3.9 fromisoformat faqat 3 yoki 6 xonali kasrni tushunadi
        m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", t)
        if m:
            frac = (m.group(2) + "000000")[:6]
            t = f"{m.group(1)}.{frac}{m.group(3)}"
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, OverflowError, OSError):
        return None


def mahalliy(d: datetime | None) -> datetime | None:
    return d.astimezone(TZ) if d else None


def vaqt_str(d: datetime | None, sana_faqat=False) -> str:
    if not d:
        return ""
    d = mahalliy(d)
    return d.strftime("%Y-%m-%d") if sana_faqat else d.strftime("%Y-%m-%d %H:%M")


def bugun() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- matn

_KIRILL = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ў": "o",
    "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_APOSTROF = "'ʻʼ‘’`´"


def slug(matn: str, maks: int = 60) -> str:
    """Fayl nomi uchun ASCII slug: o'zbek apostroflari tashlanadi, kirill → lotin."""
    s = (matn or "").lower()
    s = "".join(_KIRILL.get(ch, ch) for ch in s)
    s = "".join(ch for ch in s if ch not in _APOSTROF)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > maks:
        s = s[:maks].rsplit("-", 1)[0] or s[:maks]
    return s or "nomsiz"


def qisqart(matn: str, n: int) -> str:
    """n belgigacha, so'z chegarasida, '…' bilan."""
    t = (matn or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n].rstrip()
    if " " in cut[n // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:—-") + "…"


def bir_qator(matn: str, n: int = 200) -> str:
    """Jadval/ro'yxat ichi uchun: yangi qatorlarsiz, '|' xavfsiz."""
    t = re.sub(r"\s+", " ", matn or "").strip().replace("|", "¦")
    return qisqart(t, n)


def wikilink(yol: str, nom: str | None = None) -> str:
    """[[yol|nom]] — yo'l .md'siz, vault ildizidan. Nomdagi ] va | xavfsizlanadi."""
    y = yol[:-3] if yol.endswith(".md") else yol
    if not nom:
        return f"[[{y}]]"
    n = nom.replace("|", "¦").replace("]", ")").replace("[", "(")
    return f"[[{y}|{n}]]"


def uy_yol(p) -> str:
    """Absolyut yo'l → ~/... ko'rinishi (uy papkasi nomi chiqmasin)."""
    s = str(p)
    h = str(HOME)
    if s == h:
        return "~"
    if s.startswith(h + "/"):
        return "~/" + s[len(h) + 1:]
    return s


# ---------------------------------------------------------------- maxfiylik

_MAXFIY = "[MAXFIY]"
_REDAKT = [
    # yopiq kalit bloklari
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),                 # Telegram bot token
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),                    # Anthropic
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),     # OpenAI
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                      # Google API key
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),                    # Google OAuth secret
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}"),                     # Google access token
    re.compile(r"\b1//0[0-9A-Za-z_-]{30,}"),                       # Google refresh token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                           # AWS
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),                # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"\b[A-Za-z0-9+/_-]{120,}={0,2}"),                  # uzun base64 (sessiya satri)
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
    re.compile(r"(?i)api_hash[\"']?\s*[:=]\s*[\"']?[0-9a-f]{32}\b"),
    re.compile(r"(?m)^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY|APIKEY|PASSWORD|PASSWD|"
               r"SESSION|PRIVATE_KEY|API_HASH)[A-Z0-9_]*\s*=\s*[\"']?[^\s\"'#]{8,}"),
    re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/\"']+:[^\s@/\"']+@"),
]
# Shaxsiy ma'lumot (vault GitHub'ga va WALL-E bilim bazasiga ketadi): telefon, email, karta
_TELEFON = re.compile(r"(?<!\d)\+?998[\s-]?\(?\d{2}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_KARTA = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")


def _luhn(raqam: str) -> bool:
    r = [int(c) for c in raqam if c.isdigit()]
    if len(r) != 16:
        return False
    s = 0
    for i, d in enumerate(reversed(r)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0
_KALIT_QIYMAT = re.compile(
    r"(?i)\b(password|passwd|pass|parol|secret|token|api[_-]?key|access[_-]?key|"
    r"auth|cookie|session[_-]?string|bearer)\b(\s*[:=]\s*|\s+)([\"']?)([^\s\"']{6,})"
)
_URL_PAROL = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@")


def redakt(matn: str) -> str:
    """Sir ko'rinishidagi qiymatlarni [MAXFIY] bilan almashtiradi (xavfsizlik to'ri:
    yozuvlarga tool natijalari kirmaydi, lekin so'rov/javob matnida sir bo'lishi mumkin)."""
    if not matn:
        return matn
    t = matn.replace(str(HOME) + "/", "~/")
    for rx in _REDAKT:
        t = rx.sub(_MAXFIY, t)
    t = _URL_PAROL.sub(lambda m: m.group(1) + _MAXFIY + "@", t)
    t = _TELEFON.sub("[telefon]", t)
    t = _EMAIL.sub("[email]", t)
    t = _KARTA.sub(lambda m: "[karta]" if _luhn(m.group(0)) else m.group(0), t)

    def _kq(m):
        kalit, ajr, qoshtirnoq, qiymat = m.group(1), m.group(2), m.group(3), m.group(4)
        # "token qo'yilgach" kabi oddiy gaplarga tegmaslik: bo'shliq bilan ajralganda
        # faqat qiymat sirga o'xshasa (raqam+harf aralash, 16+ belgi) yashiriladi
        if ajr.strip() == "":
            if not (len(qiymat) >= 16 and re.search(r"\d", qiymat) and re.search(r"[A-Za-z]", qiymat)):
                return m.group(0)
        if qiymat == _MAXFIY:
            return m.group(0)
        return f"{kalit}{ajr}{qoshtirnoq}{_MAXFIY}"

    return _KALIT_QIYMAT.sub(_kq, t)


# ---------------------------------------------------------------- frontmatter

def fm_oqi(matn: str) -> dict:
    """Oddiy YAML frontmatter o'quvchi (SKILL.md va vault yozuvlari uchun yetarli):
    `kalit: qiymat`, qo'shtirnoqli qiymat, `kalit: >` / `kalit: |` blok skalyar.
    Ichma-ich lug'atlar o'qilmaydi (kerak emas)."""
    if not matn.startswith("---"):
        return {}
    qatorlar = matn.splitlines()
    natija = {}
    i = 1
    while i < len(qatorlar):
        q = qatorlar[i]
        if q.strip() == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", q)
        if not m:
            i += 1
            continue
        k, v = m.group(1), m.group(2).strip()
        if v in (">", "|", ">-", "|-", ">+", "|+"):
            blok = []
            i += 1
            while i < len(qatorlar) and (qatorlar[i].startswith((" ", "\t")) or not qatorlar[i].strip()):
                if qatorlar[i].strip() == "---":
                    break
                blok.append(qatorlar[i].strip())
                i += 1
            natija[k] = (" " if v.startswith(">") else "\n").join(x for x in blok if x).strip()
            continue
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            if v[0] == '"':
                try:
                    v = json.loads(v)
                except ValueError:
                    v = v[1:-1]
            else:
                v = v[1:-1].replace("''", "'")
        natija[k] = v
        i += 1
    return natija


def _yaml_skalyar(v) -> str:
    if v is None:
        return '""'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?", s):
        return s if " " not in s else json.dumps(s, ensure_ascii=False)
    if (re.fullmatch(r"[A-Za-z0-9_.\-/~]+", s) and not s.isdigit() and s != "~"
            and not re.fullmatch(r"[\d.]+", s)
            and s.lower() not in ("true", "false", "null", "yes", "no", "on", "off")):
        return s
    return json.dumps(s, ensure_ascii=False)   # JSON qatori = to'g'ri YAML double-quoted


def frontmatter(d: dict) -> str:
    """Obsidian Properties uchun YAML. Ro'yxatlar blok ko'rinishida; bo'sh qiymat tashlanadi."""
    qatorlar = ["---"]
    for k, v in d.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (list, tuple)):
            qatorlar.append(f"{k}:")
            for x in v:
                qatorlar.append(f"  - {_yaml_skalyar(x)}")
        else:
            qatorlar.append(f"{k}: {_yaml_skalyar(v)}")
    qatorlar.append(BELGI)
    qatorlar.append("---")
    return "\n".join(qatorlar) + "\n"


def avto_izoh(nima: str) -> str:
    return (f"> [!info] Avtomatik yozuv — {nima}\n"
            "> Miya yig'uvchisi (WALL-E) yangilaydi; tepadagi qismni qo'lda o'zgartirmang. "
            "O'z izohingizni eng pastdagi «Izohlarim» bo'limiga yozing.\n")


# ---------------------------------------------------------------- yozuvchi

def _bizniki(matn: str, yol: str) -> bool:
    bosh = "\n".join(matn.splitlines()[:40])
    if yol.endswith(".base"):
        return BELGI_BASE in bosh
    return BELGI in bosh


def _qolda_saqla(eski: str, yangi: str) -> str:
    """Eski fayldagi QOLDA belgisidan keyingi qismni yangi matnga ko'chiradi."""
    if QOLDA not in eski or QOLDA not in yangi:
        return yangi
    eski_dum = eski.split(QOLDA, 1)[1]
    return yangi.split(QOLDA, 1)[0] + QOLDA + eski_dum


class Yozuvchi:
    """Vault'ga xavfsiz yozish: ruxsat etilgan joy, qo'lda yozilgan faylni himoya,
    o'zgarmasa tegmaslik, atomik almashtirish. quruq=True — diskka yozmaydi."""

    def __init__(self, vault_yol: Path | None = None, quruq: bool = False):
        self.vault = Path(vault_yol or vault())
        self.quruq = quruq
        self.hisob = Counter()
        self.ozgargan: list = []
        self.ogohlar: list = []

    def ruxsatmi(self, rel: str) -> bool:
        parts = Path(rel).parts
        if not rel or rel.startswith("/") or ".." in parts:
            return False
        return any(rel == j or (j.endswith("/") and rel.startswith(j)) for j in AVTO_JOYLAR)

    def yoz(self, rel: str, matn: str) -> str:
        rel = rel.replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        if not self.ruxsatmi(rel):
            raise ValueError(f"ruxsat etilmagan yo'l: {rel}")
        if not matn.endswith("\n"):
            matn += "\n"
        p = self.vault / rel
        eski = None
        if p.exists():
            try:
                eski = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                eski = ""
            if not _bizniki(eski, rel):
                self.hisob["qolda"] += 1
                self.ogohlar.append(f"{rel}: qo'lda yozilgan fayl — ustiga yozilmadi")
                return "qolda"
            matn = _qolda_saqla(eski, matn)
            if eski == matn:
                self.hisob["ozgarmagan"] += 1
                return "ozgarmagan"
        holat = "yangi" if eski is None else "yangilandi"
        if not self.quruq:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".miya-", suffix=".tmp", dir=str(p.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(matn)
                os.replace(tmp, p)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        self.hisob[holat] += 1
        self.ozgargan.append((holat, rel))
        return holat


# ---------------------------------------------------------------- holat (state)

def holat_oqi(nom: str) -> dict:
    p = state_dir() / f"{nom}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def holat_yoz(nom: str, d: dict) -> None:
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    p = sd / f"{nom}.json"
    fd, tmp = tempfile.mkstemp(prefix=f".{nom}-", suffix=".tmp", dir=str(sd))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


class Qulf:
    """Bir vaqtda bitta yig'uvchi ishlasin (launchd + qo'lda ishga tushirish)."""

    def __init__(self, nom: str = "miya"):
        state_dir().mkdir(parents=True, exist_ok=True)
        self.p = state_dir() / f"{nom}.lock"
        self.f = None

    def __enter__(self):
        self.f = open(self.p, "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            self.f = None
            raise RuntimeError("boshqa yig'uvchi hozir ishlayapti")
        return self

    def __exit__(self, *a):
        if self.f:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


_LOG_MAX = 1_000_000


def log(msg: str) -> None:
    sd = state_dir()
    try:
        sd.mkdir(parents=True, exist_ok=True)
        p = sd.parent / "miya.log"
        if p.exists() and p.stat().st_size > _LOG_MAX:
            matn = p.read_text(encoding="utf-8", errors="replace")
            p.write_text(matn[-_LOG_MAX // 2:], encoding="utf-8")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} {redakt(msg)}\n")
    except OSError:
        pass
