#!/usr/bin/env python3
"""Ovozli xabarlar: STT (whisper.cpp + o'zbekcha rubaistt modeli) va TTS (edge-tts).

STT: Telegram OGG/Opus → ffmpeg 16kHz mono WAV → whisper-cli → matn.
Model: DATA/models/ggml-rubaistt.bin — yo'q bo'lsa MODEL_URL env'dan yuklab
olinadi (HF resolve-link yoki GDrive direct; private HF uchun MODEL_TOKEN).
TTS: edge-tts (uz-UZ-SardorNeural / MadinaNeural) → MP3 → OGG/Opus voice.

CLI: stt.py --check | --transcribe FILE | --tts "matn" [--out f.ogg]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR") or (BASE / "data"))
MODEL_PATH = DATA / "models" / "ggml-rubaistt.bin"
VOICE_CONFIG = DATA / "voice_config.json"

WHISPER_CANDIDATES = [
    os.environ.get("WHISPER_BIN", "").strip() or None,
    "/usr/local/bin/whisper-cli",
    str(Path.home() / "uzbek-dictation/whisper.cpp/build/bin/whisper-cli"),
]
MIN_MODEL_BYTES = 700 * 1024 * 1024  # 785MB model — 700MB'dan kichigi chala fayl
DOWNLOAD_ATTEMPTS = 3
_last_error = ""  # /stt_status uchun (process ichida)

TTS_VOICES = {"sardor": "uz-UZ-SardorNeural", "madina": "uz-UZ-MadinaNeural"}
TTS_MAX_CHARS = 500


def log(msg):
    print(f"[stt] {msg}", flush=True)


def whisper_bin():
    for c in WHISPER_CANDIDATES:
        if c and Path(c).exists():
            return c
    return shutil.which("whisper-cli")


def stt_ready():
    """(True, "") yoki (False, sabab) — ovozli xabarni qabul qilishdan oldin."""
    if not whisper_bin():
        return False, "whisper-cli binary topilmadi"
    if not (MODEL_PATH.exists() and MODEL_PATH.stat().st_size > MIN_MODEL_BYTES):
        return False, f"model yo'q/chala: {MODEL_PATH}"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg topilmadi"
    return True, ""


# ---------- model yetkazish ----------

_model_lock = threading.Lock()


def _set_err(msg):
    global _last_error
    _last_error = msg
    log(msg)


def _head_info(url, headers):
    """(Content-Length, Content-Type) — bilinmasa (0, "")."""
    import requests

    try:
        r = requests.head(url, headers=headers, timeout=30, allow_redirects=True)
        return int(r.headers.get("Content-Length") or 0), r.headers.get("Content-Type", "")
    except Exception:
        return 0, ""


def ensure_model():
    """MODEL_URL env'dan modelni /data/models ga ATOMIK yuklab oladi:
    <path>.part → tugagach rename (yarim fayl asosiy nom bilan QOLMAYDI).
    Startup'da mavjud fayl HEAD Content-Length bilan solishtiriladi — mos
    kelmasa/chala (<700MB) bo'lsa o'chirilib qayta yuklanadi. 3 urinish,
    imkon bo'lsa Range bilan resume. HF: .../resolve/main/ggml-rubaistt.bin
    (private bo'lsa MODEL_TOKEN=hf_...)."""
    global _last_error
    url = os.environ.get("MODEL_URL", "").strip()
    headers = {}
    tok = os.environ.get("MODEL_TOKEN", "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    expected, ctype = _head_info(url, headers) if url else (0, "")

    # 1) Mavjud faylning butunligi
    if MODEL_PATH.exists():
        sz = MODEL_PATH.stat().st_size
        if sz >= MIN_MODEL_BYTES and (not expected or sz == expected):
            return True
        _set_err(f"mavjud model chala ({sz >> 20} MB, kutilgan "
                 f"{expected >> 20 if expected else '≥700'} MB) — o'chirilib qayta yuklanadi")
        MODEL_PATH.unlink(missing_ok=True)
    if not url:
        _set_err("MODEL_URL berilmagan — model yuklab olinmaydi")
        return False
    if "text/html" in ctype.lower():
        _set_err("MODEL_URL HTML qaytardi (GDrive virus-scan sahifasi bo'lishi mumkin) — "
                 "HuggingFace linkiga o'ting")
        return False
    if not _model_lock.acquire(blocking=False):
        return False  # boshqa thread yuklayapti

    try:
        import requests

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 2) Disk joyi (part'dagi mavjud qism hisobga olinadi)
        part = MODEL_PATH.with_suffix(".part")
        have = part.stat().st_size if part.exists() else 0
        need = max(expected, 800 << 20) - have + (50 << 20)  # + zaxira
        free = shutil.disk_usage(MODEL_PATH.parent).free
        if free < need:
            _set_err(f"joy yetarli emas: {free >> 20} MB bo'sh, {need >> 20} MB kerak")
            return False

        exp_mb = expected >> 20 if expected else "?"
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                done = part.stat().st_size if part.exists() else 0
                req_headers = dict(headers)
                if done and expected:
                    req_headers["Range"] = f"bytes={done}-"
                    log(f"urinish {attempt}/{DOWNLOAD_ATTEMPTS}: {done >> 20} MB'dan davom (Range)")
                else:
                    done = 0
                    log(f"urinish {attempt}/{DOWNLOAD_ATTEMPTS}: yuklab olish boshlandi ({url[:70]}…)")
                with requests.get(url, headers=req_headers, stream=True,
                                  timeout=(30, 180), allow_redirects=True) as r:
                    if "text/html" in r.headers.get("Content-Type", "").lower():
                        _set_err("MODEL_URL HTML qaytardi (GDrive virus-scan sahifasi "
                                 "bo'lishi mumkin) — HuggingFace linkiga o'ting")
                        part.unlink(missing_ok=True)
                        return False
                    if done and r.status_code != 206:
                        done = 0  # server Range qo'llamadi — boshdan
                    r.raise_for_status()
                    mode = "ab" if done else "wb"
                    next_mark = (done // (100 << 20) + 1) * (100 << 20)
                    with open(part, mode) as f:
                        for chunk in r.iter_content(chunk_size=1 << 20):
                            f.write(chunk)
                            done += len(chunk)
                            if done >= next_mark:
                                log(f"yuklandi {done >> 20}/{exp_mb} MB")
                                next_mark += 100 << 20
                sz = part.stat().st_size
                if sz < (1 << 20):
                    _set_err(f"MODEL_URL {sz} baytlik javob qaytardi (HTML sahifa "
                             "bo'lishi mumkin) — HuggingFace linkiga o'ting")
                    part.unlink(missing_ok=True)
                    return False
                if expected and sz != expected:
                    raise IOError(f"hajm mos emas: {sz >> 20} MB != {exp_mb} MB")
                if sz < MIN_MODEL_BYTES:
                    raise IOError(f"fayl juda kichik: {sz >> 20} MB")
                part.rename(MODEL_PATH)
                _last_error = ""
                log(f"model tayyor ({sz >> 20} MB)")
                return True
            except Exception as e:
                _set_err(f"urinish {attempt}/{DOWNLOAD_ATTEMPTS} xato — "
                         f"{type(e).__name__}: {str(e)[:150]}")
                if attempt < DOWNLOAD_ATTEMPTS:
                    time.sleep(5)
        return False
    finally:
        _model_lock.release()


def status_text():
    """/stt_status uchun bitta xabar: model/disk/binary/TTS holati."""
    L = ["🎤 **STT holati:**"]
    if MODEL_PATH.exists():
        L.append(f"• Model: bor — {MODEL_PATH.stat().st_size >> 20} MB ({MODEL_PATH})")
    else:
        part = MODEL_PATH.with_suffix(".part")
        p = f" (.part: {part.stat().st_size >> 20} MB yuklanmoqda)" if part.exists() else ""
        L.append(f"• Model: YO'Q{p} — MODEL_URL: "
                 f"{'bor' if os.environ.get('MODEL_URL') else 'berilmagan'}")
    try:
        du = shutil.disk_usage(DATA)
        L.append(f"• Disk (/data): {du.free >> 20} MB bo'sh / {du.total >> 20} MB")
    except Exception:
        pass
    wb = whisper_bin()
    L.append(f"• whisper-cli: {wb or 'YO‘Q'}")
    L.append(f"• ffmpeg: {'bor' if shutil.which('ffmpeg') else 'YO‘Q'}")
    ok, why = stt_ready()
    L.append(f"• Umumiy: {'tayyor ✅' if ok else 'sozlanmagan — ' + why}")
    L.append(f"• TTS: {'on' if tts_enabled() else 'off'} ({tts_voice()})")
    if _last_error:
        L.append(f"• Oxirgi yuklash xatosi: {_last_error[:200]}")
    return "\n".join(L)


def ensure_model_async():
    """Supervisor startup'da — bot bloklanmasin."""
    threading.Thread(target=ensure_model, daemon=True).start()


# ---------- STT ----------

def transcribe(src_path):
    """Ovoz fayli (ogg/opus/mp3/...) → o'zbekcha matn."""
    ok, why = stt_ready()
    if not ok:
        raise RuntimeError(why)
    with tempfile.TemporaryDirectory(prefix="stt-") as td:
        wav = Path(td) / "audio.wav"
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_path), "-ar", "16000", "-ac", "1",
             "-f", "wav", str(wav)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0 or not wav.exists():
            raise RuntimeError(f"ffmpeg xato: {r.stderr[-200:]}")
        r = subprocess.run(
            [whisper_bin(), "-m", str(MODEL_PATH), "-f", str(wav),
             "-l", "uz", "-nt", "--no-prints",
             "-t", str(max(2, (os.cpu_count() or 4) - 1))],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode != 0:
            raise RuntimeError(f"whisper xato (kod {r.returncode}): {r.stderr[-200:]}")
        text = " ".join(l.strip() for l in r.stdout.splitlines() if l.strip())
        return re.sub(r"\s+", " ", text).strip()


# ---------- TTS ----------

def tts_config():
    try:
        return json.loads(VOICE_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tts_enabled():
    return bool(tts_config().get("tts", True))  # default ON


def set_tts(on):
    cfg = tts_config()
    cfg["tts"] = bool(on)
    VOICE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    VOICE_CONFIG.write_text(json.dumps(cfg), encoding="utf-8")


def tts_voice():
    return TTS_VOICES.get(tts_config().get("voice", "sardor"), TTS_VOICES["sardor"])


def short_summary(text, limit=TTS_MAX_CHARS):
    """Javob matnidan ovoz uchun qisqa xulosa: markdown belgilarisiz,
    gap chegarasida ≤limit belgi."""
    t = re.sub(r"```.*?```", " ", str(text), flags=re.S)
    t = re.sub(r"[*_#`|]+", "", t)
    t = re.sub(r"[•▸\-–—]\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: dot + 1] if dot > limit // 2 else cut).strip()


def tts(text, out_ogg):
    """Matn → OGG/Opus voice fayl (Telegram sendVoice formati)."""
    import asyncio

    import edge_tts

    text = short_summary(text)
    if not text:
        raise RuntimeError("TTS uchun matn bo'sh")
    out_ogg = Path(out_ogg)
    out_ogg.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-") as td:
        mp3 = Path(td) / "say.mp3"

        async def _gen():
            await edge_tts.Communicate(text, tts_voice()).save(str(mp3))

        asyncio.run(_gen())
        if not mp3.exists() or mp3.stat().st_size < 200:
            raise RuntimeError("edge-tts audio yaratmadi")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3), "-c:a", "libopus", "-b:a", "48k",
             "-ac", "1", str(out_ogg)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0 or not out_ogg.exists():
            raise RuntimeError(f"ffmpeg opus xato: {r.stderr[-200:]}")
    return out_ogg


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--transcribe", metavar="FILE")
    ap.add_argument("--tts", metavar="MATN")
    ap.add_argument("--out", default="tts-out.ogg")
    a = ap.parse_args()
    if a.check:
        ok, why = stt_ready()
        print(f"stt_ready: {ok} {why}")
        print(f"whisper: {whisper_bin()} | model: {MODEL_PATH} "
              f"({MODEL_PATH.stat().st_size >> 20 if MODEL_PATH.exists() else 0} MB) | "
              f"tts: {'on' if tts_enabled() else 'off'} ({tts_voice()})")
    elif a.transcribe:
        print(transcribe(a.transcribe))
    elif a.tts:
        print(tts(a.tts, a.out))
