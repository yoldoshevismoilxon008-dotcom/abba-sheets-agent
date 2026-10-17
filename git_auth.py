"""GitHub PAT'ni git'ga ARGV'SIZ uzatish (audit P2).

Ilgari token URL ichida git buyrug'i argumentida edi
(git clone https://x-access-token:TOKEN@github.com/...): `ps` / /proc/<pid>/cmdline
orqali shu mashinadagi istalgan jarayon ko'ra olardi. Endi URL tokensiz, token esa
GIT_CONFIG_* env orqali http.extraHeader (Basic) bo'lib beriladi — env faqat jarayon
egasiga (va root'ga) ko'rinadi va .git/config'ga yozilmaydi. git ≥ 2.31 kerak.
"""
import base64
import os

HEADER_KEY = "http.https://github.com/.extraheader"


def url(repo):
    """Tokensiz GitHub URL (argv va .git/config uchun)."""
    return f"https://github.com/{repo}.git"


def env(token, base=None):
    """git subprocess uchun env: base (default os.environ) + github.com auth header.
    token bo'sh bo'lsa — base nusxasi o'zgarishsiz. os.environ'ni O'ZGARTIRMAYDI
    (supervisor ichidagi boshqa jarayonlarga — claude -p — token tushmasin)."""
    e = dict(os.environ if base is None else base)
    if not token:
        return e
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    n = int(e.get("GIT_CONFIG_COUNT") or 0)
    e["GIT_CONFIG_COUNT"] = str(n + 1)
    e[f"GIT_CONFIG_KEY_{n}"] = HEADER_KEY
    e[f"GIT_CONFIG_VALUE_{n}"] = f"AUTHORIZATION: basic {basic}"
    return e
