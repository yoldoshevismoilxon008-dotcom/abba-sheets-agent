"""Maxfiy qiymatlarni log va Telegram matnlaridan yashirish (audit P0-1).

requests tarmoq xatosi matni so'rov URL'ini o'z ichiga oladi: «.../bot<TOKEN>/sendDocument».
Bu matn chatga (send_retry «⚠️ ... {str(e)}»), data/logs ga va Railway log oqimiga tushib,
bot tokenini oshkor qilardi (har tarmoq uzilishida, getUpdates siklida har 10 soniyada).

  redact(s)   — barcha log() va chatga ketadigan matnlar uchun yagona filtr;
  safe_exc(e) — requests xatosini XUDDI SHU turdagi, lekin tokensiz xato bilan almashtiradi:
                `raise safe_exc(e) from None` — chaqiruvchilarning
                `except requests.RequestException` bloklari avvalgidek ishlaydi, asl xato
                zanjiri (URL bilan) traceback'ga chiqmaydi.
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
