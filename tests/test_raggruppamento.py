from extractors.table_extractor import Riga
from processors.models import Span
from processors.raggruppamento import corse, estensioni, gruppi, nella_fascia


def _riga(testo, y):
    return Riga([Span(testo, 100, y, 150, y + 8, 7, 1)])


def _ancora(r):
    return r.testo.startswith("(")


def test_corse_si_spezzano_sullo_stacco_e_sui_tagli():
    righe = [_riga("a", 0), _riga("b", 10), _riga("c", 40), _riga("d", 50)]
    assert [[r.testo for r in c] for c in corse(righe, 15)] == [["a", "b"], ["c", "d"]]
    assert [[r.testo for r in c] for c in corse(righe[:2], 15, tagli=[5])] == [["a"], ["b"]]


def test_corsa_con_una_ancora_e_un_articolo_intero():
    # nome su due righe, codice, EAN: tutto un articolo
    righe = [_riga("Nome", 0), _riga("riga 2", 10.5), _riga("(C1)", 21), _riga("123", 31.5)]
    [g] = gruppi(righe, _ancora, 15)
    assert [r.testo for r in g.righe] == ["Nome", "riga 2", "(C1)", "123"]
    assert g.ancora.testo == "(C1)" and g.inizio == 0


def test_piu_ancore_si_tagliano_nel_distacco_piu_ampio():
    # il caso JBL che con uno stacco fisso fondeva 66 articoli: EAN, poi 14,5 pt, poi il nome successivo
    righe = [_riga("A", 0), _riga("(C1)", 10.5), _riga("ean1", 21), _riga("B", 35.5), _riga("(C2)", 46),
             _riga("ean2", 56.5)]
    g1, g2 = gruppi(righe, _ancora, 15.75)
    assert [r.testo for r in g1.righe] == ["A", "(C1)", "ean1"]
    assert [r.testo for r in g2.righe] == ["B", "(C2)", "ean2"]


def test_tabella_a_una_riga_per_articolo():
    righe = [_riga(f"(C{i})", i * 12) for i in range(5)]
    assert [g.ancora.testo for g in gruppi(righe, _ancora, 18)] == [f"(C{i})" for i in range(5)]
    assert all(len(g.righe) == 1 for g in gruppi(righe, _ancora, 18))


def test_corse_senza_ancora_non_creano_articoli():
    righe = [_riga("testo sparso", 0), _riga("(C1)", 100)]
    assert [g.ancora.testo for g in gruppi(righe, _ancora, 15)] == ["(C1)"]


def test_estensioni_e_tagli():
    assert estensioni([0, 50], []) == [(0, 50), (50, float("inf"))]
    assert estensioni([0, 50], [30]) == [(0, 30), (50, float("inf"))]
    assert nella_fascia(_riga("x", 49), (0, 50), 2) is False
    assert nella_fascia(_riga("x", 47), (0, 50), 2) is True
