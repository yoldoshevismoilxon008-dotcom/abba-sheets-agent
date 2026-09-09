"""Q&A manba qamrovi: loyiha savolida HAMMA manba qaralsin (09.09.2026 bug'i).

Real hodisa — savol: «Zubairda Livardi loyihasi bormi?»
Bot javobi: sentabr PM KPI tabida yo'q, "Loyihalarning ishlash muddati" da ham
yo'q → "loyiha yopilgan yoki jadvaldan tushib qolgan bo'lishi mumkin".
Lekin o'sha kunning undiruv PDF'ida Livardi bor edi (Zubair, $3 400, avgustdan
ko'chgan carryover) — ya'ni bot O'Z hisobotiga zid javob berdi.

Sabab: sheets_for_question savolda "zubair" borligini ko'rib FAQAT "Zubair PM KPI"
sheet'ini tanlagan; undiruv esa "SMM proektlar" sheet'ida — u umuman qaralmagan.

Bu testlar 2026-09-07 snapshotida ishlaydi (Livardi o'sha kunda 4 joyda bor:
Undiruv sentabr(2026) q36, Undiruv avgust(2026) q38, Pm proektlar After q42).

pytest tests/test_qa_project_lookup.py  yoki  python3 tests/test_qa_project_lookup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot_listener as bl   # noqa: E402
import fetch as fetchmod    # noqa: E402
import diff as diffmod      # noqa: E402

SNAP_DAY = "2026-09-07"
Q_LIVARDI = "Zubairda Livardi loyihasi bormi?"
Q_PLAIN = "Zubair KPI qanday?"


def _snaps():
    return diffmod.load_day(SNAP_DAY)[0]


def _cfg():
    return fetchmod.load_config(include_qa_only=True)


def _selected(q):
    """{sheet nomi: [tanlangan tablar]} — Q&A kontekstiga aynan nima tushadi."""
    out = {}
    snaps = _snaps()
    for s in bl.sheets_for_question(_cfg(), q, None):
        snap = snaps.get(s["id"])
        if not snap:
            continue
        _tabs, sel_tabs, _r, _lv, _notes = bl.select_from_snapshot(snap, q, None)
        out[s.get("name")] = sel_tabs
    return out


def _has_livardi(sheet_name, tab):
    """Snapshotda shu tabda «Livardi» bormi (test asosini tekshirish uchun)."""
    for snap in _snaps().values():
        if snap.get("name") != sheet_name:
            continue
        for rng, blk in (snap.get("ranges") or {}).items():
            if fetchmod.tab_of_range(rng) != tab:
                continue
            for row in blk.get("values") or []:
                if any("livardi" in str(c).lower() for c in row):
                    return True
    return False


# ------------------------------------------------------- asos: ma'lumot bor

def test_snapshotda_livardi_undiruvda_bor():
    """Test asosi: Livardi undiruv tab'ida haqiqatan bor (aks holda test ma'nosiz)."""
    assert _has_livardi("SMM proektlar", "Undiruv sentabr(2026)"), \
        "Livardi joriy oy undiruv tabida topilmadi — snapshot o'zgargan bo'lishi mumkin"


# ------------------------------------------------------- asosiy regressiya

def test_livardi_savolida_smm_sheet_ham_tanlanadi():
    """Bug: savolda "zubair" borligi uchun faqat Zubair PM KPI tanlanardi."""
    names = list(_selected(Q_LIVARDI))
    assert "SMM proektlar" in names, f"undiruv manbasi qaralmadi: {names}"


def test_livardi_savolida_undiruv_joriy_oy_qaraladi():
    sel = _selected(Q_LIVARDI)
    smm = sel.get("SMM proektlar", [])
    assert "Undiruv sentabr(2026)" in smm, f"joriy oy undiruv tabi yo'q: {smm}"


def test_livardi_savolida_undiruv_oldingi_oy_ham_qaraladi():
    """Carryover loyiha o'tgan oy tabida qoladi — u ham qaralishi shart."""
    smm = _selected(Q_LIVARDI).get("SMM proektlar", [])
    assert "Undiruv avgust(2026)" in smm, f"oldingi oy undiruv tabi yo'q: {smm}"


def test_livardi_kontekstiga_livardi_qatori_haqiqatan_tushadi():
    """Uchidan-uchiga: tanlangan tablar orasida Livardi bor tab bo'lsin."""
    sel = _selected(Q_LIVARDI)
    hits = [(sh, t) for sh, tabs in sel.items() for t in tabs if _has_livardi(sh, t)]
    assert hits, f"Livardi hech bir tanlangan tabda yo'q: {sel}"


def test_pm_kpi_sheetlari_ham_qoladi():
    """Undiruv qo'shilishi PM KPI manbasini siqib chiqarmasin."""
    names = list(_selected(Q_LIVARDI))
    assert "Zubair PM KPI" in names, names


def test_pm_kpi_asosiy_tablari_saqlanadi():
    sel = _selected(Q_LIVARDI)
    zub = sel.get("Zubair PM KPI", [])
    assert "Loyihalarning ishlash muddati" in zub, zub


def test_smm_asosiy_tablari_yoqolmaydi():
    """Regressiya qo'riqchisi: undiruv qo'shilganda watch-tab fallback'i
    o'chib, Smm main / Pm proektlar After tushib qolgan edi."""
    smm = _selected(Q_LIVARDI).get("SMM proektlar", [])
    for t in ("Smm main", "Pm proektlar After"):
        assert t in smm, f"«{t}» tanlovdan chiqib ketdi: {smm}"


# ------------------------------------------------------- tor savol o'zgarmasin

def test_oddiy_kpi_savoli_kengaymaydi():
    """Loyiha qidiruvi bo'lmagan savol avvalgidek TOR qoladi (kontekst shishmasin)."""
    names = list(_selected(Q_PLAIN))
    assert names == ["Zubair PM KPI"], f"tor savol kengayib ketdi: {names}"


def test_is_project_lookup_ajratadi():
    for q in ("Zubairda Livardi loyihasi bormi?", "Livardi proekti qayerda?",
              "bu loyiha qachon tugaydi?"):
        assert bl.is_project_lookup(q), q
    for q in ("Zubair KPI qanday?", "undiruv qancha?", "bugungi hisobot"):
        assert not bl.is_project_lookup(q), q


def test_loyiha_savolida_qamrov_korsatmasi_beriladi():
    """Javobda qaysi tablar qaralgani aytilishi uchun ko'rsatma notes'ga tushsin."""
    snaps = _snaps()
    smm = next(s for s in snaps.values() if s.get("name") == "SMM proektlar")
    _t, _sel, _r, _lv, notes = bl.select_from_snapshot(smm, Q_LIVARDI, None)
    assert any("Loyiha qidiruvi" in n for n in notes), notes


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
