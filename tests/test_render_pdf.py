"""render_pdf regressiya testlari — 2026-09-07 yiqilishidan keyin qo'shildi.

O'sha kuni PDF render yiqildi, lekin logda faqat "Chrome PDF yaratmadi (fayl
chiqmadi yoki juda kichik)" qoldi: Chrome stderr DEVNULL ga ketardi, returncode
tekshirilmasdi, timeout va bo'sh chiqish bir xil xabar berardi. Bu testlar shu
ikki narsani qo'riqlaydi:

  1. Nomos/bo'sh input ichki AttributeError emas, ANIQ ValueError bersin
     (va jimgina bo'sh PDF yasalmasin).
  2. Chrome yiqilganda xato matni sababni ayrim ko'rsatsin: timeout / fayl
     yaratilmadi / juda kichik, + chrome stderr'ining ma'noli qatorlari.

Chrome haqiqatda chaqirilmaydi — find_chrome soxta skriptga yo'naltiriladi,
shuning uchun test tez va CI'da ham ishlaydi.

pytest tests/test_render_pdf.py  yoki  python3 tests/test_render_pdf.py
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_pdf  # noqa: E402

_FIND_CHROME_ORIG = render_pdf.find_chrome


def _fake_chrome(script_body):
    """--print-to-pdf=PATH argumentini o'qib, berilgan tanani bajaradigan soxta chrome."""
    f = tempfile.NamedTemporaryFile("w", prefix="fakechrome-", suffix=".sh", delete=False)
    f.write(
        "#!/bin/bash\n"
        'for a in "$@"; do case "$a" in --print-to-pdf=*) OUT="${a#--print-to-pdf=}";; esac; done\n'
        + script_body
        + "\n"
    )
    f.close()
    os.chmod(f.name, os.stat(f.name).st_mode | stat.S_IEXEC)
    return f.name


_FAKES = []


def _with_fake_chrome(script_body):
    path = _fake_chrome(script_body)
    _FAKES.append(path)
    render_pdf.find_chrome = lambda: path
    return path


def _restore():
    render_pdf.find_chrome = _FIND_CHROME_ORIG
    while _FAKES:                      # soxta skriptlar /tmp da yig'ilmasin
        try:
            os.unlink(_FAKES.pop())
        except OSError:
            pass


def _tmp_paths():
    d = Path(tempfile.mkdtemp(prefix="render-test-"))
    html = d / "r.html"
    html.write_text("<html><body>salom</body></html>", encoding="utf-8")
    return html, d / "r.pdf"


# ------------------------------------------------------- 1) input validatsiyasi

def test_validate_rad_etadi_none_va_notogri_turlarni():
    for bad in (None, "satr", [1, 2], 42):
        try:
            render_pdf.validate_report_data(bad)
        except ValueError as e:
            assert "dict bo'lishi kerak" in str(e), f"noaniq xabar: {e}"
        else:
            raise AssertionError(f"{bad!r} uchun ValueError kutilgandi")


def test_validate_rad_etadi_bosh_dictni():
    """Bo'sh dict ilgari jimgina bo'sh PDF yasardi — endi aniq xato."""
    try:
        render_pdf.validate_report_data({})
    except ValueError as e:
        assert "bo'sh" in str(e)
    else:
        raise AssertionError("bo'sh dict uchun ValueError kutilgandi")


def test_validate_rad_etadi_notogri_maydon_turini():
    try:
        render_pdf.validate_report_data({"date": "2026-09-07", "pms": "ro'yxat-emas"})
    except ValueError as e:
        assert "pms" in str(e) and "list" in str(e)
    else:
        raise AssertionError("pms=str uchun ValueError kutilgandi")


def test_validate_otkazadi_minimal_togri_inputni():
    ok = {"date": "2026-09-07", "pms": [], "totals": {}, "undiruv": None}
    assert render_pdf.validate_report_data(ok) is ok


def test_render_nomos_inputda_chromegacha_bormaydi():
    """render() validatsiyadan o'tmasa Chrome umuman chaqirilmasin."""
    called = []
    render_pdf.find_chrome = lambda: called.append(1) or "/yo'q"
    try:
        for bad in (None, {}, "satr"):
            try:
                render_pdf.render(bad, "/tmp/hech-qachon.pdf")
            except ValueError:
                pass
            else:
                raise AssertionError(f"{bad!r} uchun ValueError kutilgandi")
        assert not called, "nomos inputda Chrome chaqirilmasligi kerak"
    finally:
        _restore()


# ------------------------------------------------- 2) Chrome yiqilishi — aniq sabab

def test_chrome_fayl_yaratmasa_sabab_aniq():
    _with_fake_chrome("exit 3")          # PDF yozmaydi
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=5)
    except RuntimeError as e:
        msg = str(e)
        assert "fayl yaratmadi" in msg, msg
        assert "exit=3" in msg, f"returncode xato matnida yo'q: {msg}"
    else:
        raise AssertionError("RuntimeError kutilgandi")
    finally:
        _restore()


def test_kichik_pdf_hajm_bilan_raddi():
    _with_fake_chrome('printf "%s" "kichik" > "$OUT"; exit 0')
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=5)
    except RuntimeError as e:
        msg = str(e)
        assert "juda kichik" in msg and str(render_pdf.MIN_PDF_BYTES) in msg, msg
    else:
        raise AssertionError("RuntimeError kutilgandi")
    finally:
        _restore()


def test_timeout_sababi_alohida_korsatiladi():
    """Chrome osilib qolsa — 'timeout' deyilsin, 'fayl chiqmadi' emas."""
    _with_fake_chrome("sleep 30")
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=2)
    except RuntimeError as e:
        assert "timeout" in str(e), str(e)
    else:
        raise AssertionError("RuntimeError kutilgandi")
    finally:
        _restore()


def test_chrome_stderr_xato_matniga_tushadi():
    _with_fake_chrome('echo "FATAL: profile lock qo\'lga olinmadi" >&2; exit 1')
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=5)
    except RuntimeError as e:
        assert "profile lock" in str(e), f"chrome stderr xatoga qo'shilmagan: {e}"
    else:
        raise AssertionError("RuntimeError kutilgandi")
    finally:
        _restore()


def test_shovqin_qatorlari_sababni_kolmasin():
    """CVDisplayLink kabi zararsiz shovqin bo'lsa ham asl xato ko'rinsin."""
    noise = "; ".join(
        [f'echo "[ERROR:cv_display_link_mac.mm] CVDisplayLinkCreateWithCGDisplay failed" >&2'] * 5
    )
    _with_fake_chrome(f'{noise}; echo "FATAL: haqiqiy sabab" >&2; exit 1')
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=5)
    except RuntimeError as e:
        assert "haqiqiy sabab" in str(e), f"asl sabab shovqin ostida qoldi: {e}"
        assert "CVDisplayLink" not in str(e), f"shovqin xatoga tushdi: {e}"
    else:
        raise AssertionError("RuntimeError kutilgandi")
    finally:
        _restore()


def test_yiqilganda_chrome_logi_diskda_qoladi():
    _with_fake_chrome('echo "FATAL: nimadir" >&2; exit 1')
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=5)
    except RuntimeError:
        kept = Path(str(pdf).rsplit(".", 1)[0] + ".chrome-stderr.log")
        assert kept.exists() and kept.stat().st_size > 0, "chrome stderr nusxasi saqlanmadi"
    finally:
        _restore()


def test_muvaffaqiyatda_profil_papkasi_tozalanadi():
    """Har render alohida mktemp profil oladi va ortidan tozalaydi."""
    before = {p.name for p in Path(tempfile.gettempdir()).glob("chrome-pdf-*")}
    _with_fake_chrome(f'head -c {render_pdf.MIN_PDF_BYTES + 100} /dev/zero > "$OUT"; exit 0')
    html, pdf = _tmp_paths()
    try:
        render_pdf.html_to_pdf(html, pdf, wait_s=10)
        assert pdf.exists() and pdf.stat().st_size > render_pdf.MIN_PDF_BYTES
        after = {p.name for p in Path(tempfile.gettempdir()).glob("chrome-pdf-*")}
        assert after <= before, f"profil papkasi qoldi: {after - before}"
    finally:
        _restore()


# ---------------------------------------------------------------- skript rejimi

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} o'tdi, {failed} yiqildi (jami {len(tests)})")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
