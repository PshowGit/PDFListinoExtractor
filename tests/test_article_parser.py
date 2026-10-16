from decimal import Decimal

from processors.article_parser import ParserListino, unisci_righe
from processors.data_validator import ean_valido
from processors.models import Span


def _span(testo, x, y, size=7.0, pagina=1):
    return Span(testo, x, y, x + len(testo) * 3.5, y + 8, size, pagina)


def _testata(pagina=1):
    return [
        _span("Modello", 102, 137.9, pagina=pagina),
        _span("Descrizione", 202, 137.9, pagina=pagina),
        _span("Prezzo al", 467, 137.9, pagina=pagina),
        _span("Pubblico", 467, 148.4, pagina=pagina),
    ]


def test_unisci_righe_non_incolla_parole_e_ricompone_i_trattini():
    assert unisci_righe(["Diffusore  water-", "resistant", "IP55"]) == "Diffusore water-resistant IP55"
    assert unisci_righe(["Serie A -", "nero"]) == "Serie A - nero"
    assert unisci_righe(["", "  uno  ", "due"]) == "uno due"


def test_codici_con_zeri_iniziali_punti_e_trattini_restano_testo(regole):
    spans = _testata() + [
        _span("007-A.12", 102, 200),
        _span("(000123.B-X)", 102, 210.5),
        _span("0012345678905", 102, 221),
        _span("Descrizione", 202, 200),
        _span("1.000,00", 478, 200),
    ]
    [a] = ParserListino(regole).elabora_pagina(spans, 1)
    assert a.modello == "007-A.12"
    assert a.codice == "(000123.B-X)"
    assert a.ean == "0012345678905"
    assert a.prezzo == Decimal("1000.00")


def test_codice_senza_parentesi_se_configurato(regole):
    regole["codice_con_parentesi"] = False
    spans = _testata() + [_span("X1", 102, 200), _span("(JB-X1)", 102, 210.5), _span("10,00", 487, 200)]
    [a] = ParserListino(regole).elabora_pagina(spans, 1)
    assert a.codice == "JB-X1"


def test_un_prezzo_mancante_non_fonde_due_articoli(regole):
    spans = _testata() + [
        _span("A1", 102, 200), _span("(C-A1)", 102, 210.5), _span("Primo", 202, 200),
        _span("A2", 102, 260), _span("(C-A2)", 102, 270.5), _span("Secondo", 202, 260), _span("5,00", 487, 260),
    ]
    a1, a2 = ParserListino(regole).elabora_pagina(spans, 1)
    assert (a1.codice, a1.prezzo, a1.descrizione) == ("(C-A1)", None, "Primo")
    assert "Prezzo mancante" in a1.note_estrazione["prezzo"]
    assert (a2.codice, a2.prezzo) == ("(C-A2)", Decimal("5.00"))


def test_la_descrizione_non_passa_al_modello_successivo(regole):
    spans = _testata() + [
        _span("A1", 102, 200), _span("(C-A1)", 102, 210.5), _span("riga uno", 202, 200),
        _span("riga due", 202, 210.5), _span("riga tre", 202, 221), _span("riga quattro", 202, 231.5),
        _span("1,00", 487, 200),
        _span("A2", 102, 246), _span("(C-A2)", 102, 256.5), _span("altro", 202, 246), _span("2,00", 487, 246),
    ]
    a1, a2 = ParserListino(regole).elabora_pagina(spans, 1)
    assert a1.descrizione == "riga uno riga due riga tre riga quattro"
    assert a2.descrizione == "altro"


def test_il_titolo_di_categoria_chiude_l_articolo_e_non_entra_nei_dati(regole):
    spans = _testata() + [
        _span("A1", 102, 200), _span("(C-A1)", 102, 210.5), _span("1,00", 487, 200),
        _span("Diffusori", 30, 240, size=19),
        _span("A2", 102, 280), _span("(C-A2)", 102, 290.5), _span("2,00", 487, 280),
    ]
    a1, a2 = ParserListino(regole).elabora_pagina(spans, 1)
    assert "Diffusori" not in a1.descrizione + a1.modello
    assert a2.categoria == "Diffusori"


def test_ean_valido():
    assert ean_valido("8710150083632")
    assert ean_valido("691991014208")  # UPC-A a 12 cifre
    assert not ean_valido("8710150083633")
    assert not ean_valido("PRX412M")
    assert not ean_valido("3677")
