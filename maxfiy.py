"""Maxfiy qiymatlarni log va Telegram matnlaridan yashirish (audit P0-1).

requests tarmoq xatosi matni so'rov URL'ini o'z ichiga oladi: «.../bot<TOKEN>/sendDocument».
Bu matn chatga (send_retry «⚠️ ... {str(e)}»), data/logs ga va Railway log oqimiga tushib,
bot tokenini oshkor qilardi (har tarmoq uzilishida, getUpdates siklida har 10 soniyada).

  redact(s)   — barcha log() va chatga ketadigan matnlar uchun yagona filtr;
  safe_exc(e) — requests xatosini XUDDI SHU turdagi, lekin tokensiz xato bilan almashtiradi:
                `raise safe_exc(e) from None` — chaqiruvchilarning
                `except requests.RequestException` bloklari avvalgidek ishlaydi, asl xato
                zanjiri (URL bilan) traceback'ga chiqmaydi;
  telefon_yashir(s) — vault'ga ketadigan matnda (09:00 hisobot, chat arxivi) telefon
                raqamlarini «[telefon]» bilan almashtiradi (pastda, o'z bo'limida).
"""
import os
import re

# Qiymati matnda uchrasa «***» ga almashtiriladigan env o'zgaruvchilar
ENV_SIRLAR = (
    "TELEGRAM_BOT_TOKEN", "GH_TOKEN_REPORTS", "GH_TOKEN_VAULT", "MODEL_TOKEN",
    "TG_API_HASH", "TG_SESSION_STRING", "TG_SESSION_B64", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY", "GOOGLE_SA_JSON", "CONFIG_LOCAL_B64", "UNDIRUV_QAROR_B64",
)
_MIN_UZUNLIK = 8  # qisqa qiymatlar (masalan «1») oddiy matnni buzmasin

# Env'da bo'lmasa ham taniladigan shakllar
_NAQSHLAR = (
    # /bot<TOKEN>/method — dumi qisqa bo'lsa ham (xato matni 120 belgida kesilganda
    # tokenning yarmi qolardi — review): «bot<id>:» dan keyingi hamma narsa yashiriladi
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]*"), "bot***"),
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "***"),           # yalang'och bot token
    (re.compile(r"x-access-token:[^@\s'\"]+@"), "x-access-token:***@"),  # git remote URL
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "gh*_***"),           # GitHub token
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github_pat_***"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"), "sk-ant-***"),         # Anthropic kalit
)


def redact(s):
    """Matndagi maxfiy qiymatlarni «***» bilan almashtiradi (har qanday obyekt → str)."""
    s = str(s)
    for k in ENV_SIRLAR:
        v = os.environ.get(k, "").strip()
        if len(v) >= _MIN_UZUNLIK and v in s:
            s = s.replace(v, "***")
    for rx, rep in _NAQSHLAR:
        s = rx.sub(rep, s)
    return s


def safe_exc(e):
    """Xato → xuddi shu turdagi, matni redakt qilingan xato. Konstruktor boshqa argument
    talab qilsa — requests.RequestException (baribir RequestException ierarxiyasida)."""
    msg = redact(str(e))
    try:
        return type(e)(msg)
    except Exception:                                   # noqa: BLE001
        import requests

        return requests.RequestException(msg)


def xato_xabar(sarlavha, e):
    """Chatga ko'rsatiladigan xato: faqat sarlavha + xato TURI. Tafsilot (redakt qilingan)
    logda qoladi — xato matni URL/token yoki ichki yo'llarni o'z ichiga olishi mumkin."""
    return f"{sarlavha} ({type(e).__name__}). Tafsilot logda."


# ---------------------------------------------------------------- telefon raqamlari
#
# 09:00 hisobot (push_reports) va chat arxivi (chat_log, push_chat) hisobotlar repo'si
# orqali vault'ga (GitHub) va u yerdan WALL-E bilim bazasiga tushadi. Mijoz yoki lead
# telefoni u yerda kerak emas. 27.11.2026 dagi maxfiylik skani hisobot jadvalidan iqtibos
# qilingan telefonni vault'da topgan.
#
# Qoida TG audit (abba-tg-audit/maxfiylik.py) bilan BIR XIL. U yerda 27.11 da ~490 ming
# real xabarda o'lchangan: summa, sana, ID va INN raqamlariga tegilmaydi. Vault'dagi 122 ta
# 09:00 hisobot va chat arxivida yolg'on moslik 0. Xuddi shu blok Mac'dagi miya
# yig'uvchisida ham bor (deploy/mac-sync/miya/asos.py) — u bu faylni import qila olmaydi
# (~/.abba-miya ga alohida nusxalanadi). Ikki nusxa bir xilligini
# tests/test_telefon_yashir.py qo'riqlaydi: birini o'zgartirsangiz, ikkinchisini ham.
#
# Faqat vault'ga ketadigan nusxa uchun. Egasiga bot javobi va loglar o'zgarmaydi.
# Ma'lum cheklovlar: so'z bilan aytilgan raqam (ovozli xabar transkripti), harfga
# yopishgan raqam (username, parol) va kam uchraydigan xorijiy shakllar («+» siz AQSh
# 3-3-4) yashirilmaydi.

TELEFON_BELGI = "[telefon]"

# Mobil va shahar kodlari (O'zbekiston)
_KOD = r"(?:20|33|50|55|71|77|78|88|9[0-9])"
# Ko'zga ko'rinmaydigan ajratuvchilar: NBSP, ingichka va tor bo'shliq, uzilmas tire, qisqa tire
_KORINMAS = "   ‑–"
# Ajratuvchi: bo'shliq, -, . va yuqoridagilar
_A = r"[ \-." + _KORINMAS + "]"

# +998 90 000 00 00 · 998900000000 · +998 (90) 000-00-00 · «+ 998» yoki ikki bo'shliq bilan
_UZ = re.compile(r"(?<!\d)(?:\+ ?)?998" + _A + r"{0,2}\(?\d{2}\)?" + _A + r"{0,2}\d{3}"
                 + _A + r"{0,2}\d{2}" + _A + r"{0,2}\d{2}(?!\d)")

# Boshqa davlatlar: «+» va jami 11–13 raqam (+7 916 000 00 00). 10 va kam raqamli
# «+» sonlar summa o'zgarishi bo'lishi mumkin (+170 000 000), ularga tegilmaydi.
_XALQARO = re.compile(r"(?<![\w+])\+\d[\d \-()." + _KORINMAS + r"]{9,18}\d(?!\d)")

# Mahalliy, ajratilgan: 90 000 00 00 · (90)000-00-00 · (90) 0000000 · 90 000 0000.
# Qavssiz koddan keyin ajratuvchi SHART: summalar (90 000 000) 2-3-3 bo'ladi va bu
# shaklga tushmaydi. Gap oxiridagi nuqta yoki vergul mumkin, o'nlik kasr (3.14) emas.
_MAHALLIY = re.compile(
    r"(?<![\d+])(?<!\d[.,])"
    r"(?:\(" + _KOD + r"\)" + _A + r"{0,2}|" + _KOD + r"\)?" + _A + r"{1,2})"
    r"\d{3}" + _A + r"{0,2}\d{2}" + _A + r"{0,2}\d{2}(?!\d|[.,]\d)")

# Yopishgan 9 raqam (900000000) — kalit so'zsiz ham. Real xabarlarda bu shakl deyarli
# har doim telefon. Faqat undan keyin pul birligi kelsa yoki oldin narx/ID/INN/№ so'zi
# bo'lsa tegilmaydi.
_YOPISHGAN = re.compile(r"(?<![\w+#№/=@$])(?<!\d[.,])(" + _KOD + r"\d{7})(?!\w|[.,]\d)")
_PUL_KEYIN = re.compile("[  ]{0,2}" + r"(?:so['ʻ’`‘]?m|sum\b|сум|сўм|ming|минг|тыс|mln|млн"
                        r"|\$|usd|y\.?e\b|у\.?е\b|uzs)", re.I)
_PUL_OLDIN = re.compile(r"(?:narx\w*|summa\w*|jami|цен\w*|сумм\w*|итого|price|total)\W{0,3}$",
                        re.I)
_ID_OLDIN = re.compile(r"(?:\bid|\binn|\bstir|инн|стир|\bmfo|мфо|№|#|hisob raqam\w*|р/с|x/r"
                       r"|karta\w*|card\w*)\W{0,3}$", re.I)

# Kalit so'zdan keyingi yopishgan 9 raqam har doim telefon deb olinadi
# («tel: 900000000 so'm» kabi chalkash holatda ham).
_KALIT_SOZ = re.compile(
    r"(?i)((?:tel|telefon|phone|raqam|raqamim|nomer|номер|тел|телефон|📞|☎)\W{0,12})"
    r"(" + _KOD + r"\d{7})(?!\d)")


def _xalqaro(m):
    raqamlar = sum(ch.isdigit() for ch in m.group(0))
    return TELEFON_BELGI if 11 <= raqamlar <= 13 else m.group(0)


def _yopishgan(m):
    s = m.string
    oldin = s[max(0, m.start() - 24):m.start()]
    if _PUL_KEYIN.match(s, m.end()) or _ID_OLDIN.search(oldin) or _PUL_OLDIN.search(oldin):
        return m.group(0)
    return TELEFON_BELGI


def telefon_yashir(matn):
    """Matndagi telefon raqamlarini TELEFON_BELGI bilan almashtiradi; bo'sh matn o'zgarmaydi.
    Kesishdan (qisqartirishdan) OLDIN chaqiring — aks holda chegarada raqam yarmi qoladi."""
    if not matn:
        return matn
    t = _UZ.sub(TELEFON_BELGI, matn)
    t = _XALQARO.sub(_xalqaro, t)
    t = _MAHALLIY.sub(TELEFON_BELGI, t)
    t = _YOPISHGAN.sub(_yopishgan, t)
    return _KALIT_SOZ.sub(lambda m: m.group(1) + TELEFON_BELGI, t)
