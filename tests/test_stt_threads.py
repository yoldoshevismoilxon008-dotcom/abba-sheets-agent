"""whisper.cpp thread soni konteyner kvotasidan olinadi (24.11 hodisasi).

Ilgari os.cpu_count()-1 olinardi: Railway konteynerida bu HOST yadrolari (o'nlab) — ggml
thread'lari 8 vCPU kvotasida bir-birini kutib qolib, 3 s ovoz 10 daqiqada ham tugamadi va bot
shu vaqt javob bermadi. pytest tests/test_stt_threads.py — tarmoq va model kerak emas.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stt  # noqa: E402


@pytest.fixture
def cg(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "CGROUP", tmp_path)
    monkeypatch.delenv("WHISPER_THREADS", raising=False)
    monkeypatch.setattr(stt.os, "cpu_count", lambda: 48)          # Railway host'idek
    monkeypatch.setattr(stt.os, "sched_getaffinity", lambda pid: set(range(48)), raising=False)
    return tmp_path


def test_cgroup_v2_kvotasi_host_yadrolari_emas(cg):
    (cg / "cpu.max").write_text("800000 100000\n")                 # 8 vCPU
    assert stt._cpu_kvota() == 8
    assert stt.whisper_threads() == 4                               # ko'pi bilan 4, 47 emas


def test_kichik_kvota(cg):
    (cg / "cpu.max").write_text("200000 100000\n")                 # 2 vCPU
    assert stt.whisper_threads() == 2
    (cg / "cpu.max").write_text("300000 100000\n")                 # 3 vCPU → bitta bo'sh qolsin
    assert stt.whisper_threads() == 2


def test_cgroup_v1_va_cheksiz_kvota(cg):
    (cg / "cpu.max").write_text("max 100000\n")                    # v2 cheksiz → keyingi manba
    (cg / "cpu").mkdir()
    (cg / "cpu" / "cpu.cfs_quota_us").write_text("150000\n")
    (cg / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
    assert stt._cpu_kvota() == 1.5
    assert stt.whisper_threads() == 1


def test_kvota_yoq_bolsa_affinity_lekin_baribir_cheklangan(cg):
    assert stt._cpu_kvota() == 48
    assert stt.whisper_threads() == stt.WHISPER_MAX_THREADS


def test_env_ustun(cg, monkeypatch):
    (cg / "cpu.max").write_text("800000 100000\n")
    monkeypatch.setenv("WHISPER_THREADS", "6")
    assert stt.whisper_threads() == 6


@pytest.mark.parametrize("sekund,kutilgan", [(None, 300), (0, 300), (3, 90), (60, 300),
                                             (180, 600), (600, 600)])
def test_timeout_uzunlikka_qarab(sekund, kutilgan):
    assert stt._timeout(sekund) == kutilgan


def test_transcribe_thread_va_timeout_whisperga_boradi(cg, monkeypatch, tmp_path):
    (cg / "cpu.max").write_text("800000 100000\n")
    monkeypatch.setattr(stt, "stt_ready", lambda: (True, ""))
    monkeypatch.setattr(stt, "whisper_bin", lambda: "/bin/whisper-cli")
    chaqiruvlar = []

    def run(cmd, **kw):
        chaqiruvlar.append((cmd, kw.get("timeout")))
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"wav")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "  salom  dunyo \n", "")

    monkeypatch.setattr(stt.subprocess, "run", run)
    assert stt.transcribe(tmp_path / "v.ogg", sekund=5) == "salom dunyo"
    cmd, timeout = chaqiruvlar[-1]
    assert cmd[cmd.index("-t") + 1] == "4" and timeout == 90


def test_transcribe_timeout_aniq_xato(cg, monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "stt_ready", lambda: (True, ""))
    monkeypatch.setattr(stt, "whisper_bin", lambda: "/bin/whisper-cli")

    def run(cmd, **kw):
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"wav")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(stt.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="90 s da tugamadi"):
        stt.transcribe(tmp_path / "v.ogg", sekund=3)
