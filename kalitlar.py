#!/usr/bin/env python3
"""Egasining kalit so'zlari: odamlar (ism — kimligi) va atamalar (so'z — ma'nosi).

Manba — Obsidian vault'dagi abba-sheets-agent/kalit-sozlar.md: serverda vault_sync uni private
repo'dan DATA/vault ga tortadi, Mac'da — ~/claude-brain. Repo PUBLIC — ism va lavozimlar kodga
yozilmaydi, ro'yxatni egasi Obsidian'da to'ldiradi.

Fayl formati: «## Bo'lim» sarlavhalari ostida «- **Kalit** — ma'nosi» qatorlari (qalin shart
emas, «1.» ham bo'ladi; ajratuvchi «—», «–», « - » yoki «:»). Boshqa qatorlar (matn, «>»
iqtibos, ma'nosiz band) e'tiborsiz.

whisper_royxati() — ovoz tanishga (whisper --prompt), prompt_matni() — Claude jadval tuzganda,
royxat() — /kalit buyrug'i.
"""
import re
from pathlib import Path

import vault_sync
from maxfiy import redact

NISBIY = Path("abba-sheets-agent") / "kalit-sozlar.md"
FAYLLAR = (vault_sync.CLONE / NISBIY, Path.home() / "claude-brain" / NISBIY)
# 24.11 TTS sinovi: odamlar+atamalar 14/23 → 16/23; 53 ta loyiha qo'shilsa foyda kamaydi
WHISPER_MAX = 400

_QATOR = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.+?)\s*(?:—|–|\s-\s|:)\s*(.+?)\s*$")
_SARLAVHA = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_KESH = {"kalit": None, "royxat": []}


def log(msg):
    print(f"[kalit] {redact(msg)}", flush=True)


def fayl():
    return next((f for f in FAYLLAR if f.is_file()), None)


def royxat():
    """[(bo'lim, kalit, ma'no)] fayldagi tartibda. Fayl yo'q yoki o'qilmasa — []."""
    f = fayl()
    if f is None:
        return []
    try:
        kesh_kalit = (f, f.stat().st_mtime_ns)
        if _KESH["kalit"] == kesh_kalit:
            return _KESH["royxat"]
        matn = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        log(f"o'qilmadi: {type(e).__name__}")
        return []
    out, bolim = [], ""
    for line in matn.splitlines():
        s = _SARLAVHA.match(line)
        if s:
            bolim = s.group(1)
            continue
        m = _QATOR.match(line)
        if not m:
            continue
        kalit = m.group(1).strip("*_ ")
        mano = m.group(2).strip("*_ ")
        if kalit and mano and len(kalit) <= 60:
            out.append((bolim, kalit, mano[:200]))
    _KESH.update(kalit=kesh_kalit, royxat=out)
    log(f"{len(out)} ta kalit so'z yuklandi ({f.parent.parent.name}/{NISBIY})")
    return out


def whisper_royxati():
    """Kalitlar (fayl tartibida, jami ≤ WHISPER_MAX belgi) — whisper --prompt uchun."""
    out, n = [], 0
    for _, kalit, _ in royxat():
        n += len(kalit) + 2
        if n > WHISPER_MAX:
            break
        out.append(kalit)
    return out


def prompt_matni():
    """Claude uchun lug'at: bo'lim nomi, ostida «- Kalit — ma'nosi». Bo'sh bo'lsa «(yo'q)»."""
    L, oldingi = [], None
    for bolim, kalit, mano in royxat():
        if bolim != oldingi:
            if bolim:
                L.append(f"{bolim}:")
            oldingi = bolim
        L.append(f"- {kalit} — {mano}")
    return "\n".join(L) or "(yo'q)"
