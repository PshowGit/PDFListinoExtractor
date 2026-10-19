from decimal import Decimal

import pytest

from processors.article_parser import ParserListino, Vocabolario, _parole, unisci_righe
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


# vocabolario di un documento finto: «alone» e «risoluzione» intere, «U-bracket» col trattino, «two» e «part»
_DOCUMENTO = [_span(t, 0, 0) for t in ("Effetto alone", "alta risoluzione", "staffa U-bracket", "two way",
                                       "part number", "per l’appli-", "recen-")]


def _vocabolario(sillaba: bool) -> Vocabolario:
    return Vocabolario(_parole(_DOCUMENTO), sillaba)


@pytest.mark.parametrize("righe, atteso", [
    (["Effetto Alo-", "ne."], "Effetto Alone."),  # la parola intera c'e' nel documento
    (["Ri-", "soluzione 4k"], "Risoluzione 4k"),
    (["usato recen-", "temente"], "usato recentemente"),  # «recen» non e' una parola, e il documento sillaba
    (["con l’appli-", "cazione"], "con l’applicazione"),  # dopo l'elisione
    (["Mic/Linea/Chi-", "tarra"], "Mic/Linea/Chitarra"),
    (["staffa U-", "bracket"], "staffa U-bracket"),  # la forma col trattino c'e' nel documento
    (["giunto two-", "part"], "giunto two-part"),  # due parole: un composto
    (["cavo MTC-", "29UB"], "cavo MTC-29UB"),  # codici e sigle
    (["RS232-USB-", "converter"], "RS232-USB-converter"),
    (["temperatura 6500K-", "kelvin"], "temperatura 6500K-kelvin"),
    (["Bi-", "Amp"], "Bi-Amp"),  # maiuscola dopo il trattino
])
def test_trattino_a_capo_in_un_documento_che_sillaba(righe, atteso):
    assert unisci_righe(righe, _vocabolario(sillaba=True)) == atteso


def test_in_un_documento_che_non_sillaba_resta_il_trattino_dei_pezzi_sconosciuti():
    # «water» non compare da solo: senza prove che il documento sillabi, «water-resistant» resta com'e'
    assert unisci_righe(["Diffusore water-", "resistant"], _vocabolario(sillaba=False)) == "Diffusore water-resistant"
    assert unisci_righe(["usato recen-", "temente"], _vocabolario(sillaba=False)) == "usato recen-temente"
    # la parola intera nel documento basta sempre
    assert unisci_righe(["Effetto Alo-", "ne."], _vocabolario(sillaba=False)) == "Effetto Alone."


def test_il_vocabolario_non_conta_la_parola_spezzata_a_fine_riga():
    parole = _parole(_DOCUMENTO)
    assert {"alone", "u-bracket", "u", "bracket", "two", "part"} <= parole
    assert "recen" not in parole and "appli" not in parole


def test_il_documento_sillaba_se_le_parole_spezzate_confermate_sono_piu_dei_composti():
    def riga(testo, y):
        return Span(testo, 100, y, 100 + len(testo) * 4, y + 9, 9, 1)

    altrove = [riga("alta risoluzione", 300), riga("effetto alone", 320)]
    sillaba = [riga("Ri-", 100), riga("soluzione 4k", 110.8), riga("Effetto Alo-", 150), riga("ne.", 160.8)]
    assert Vocabolario.del_documento([sillaba + altrove], 9).sillaba
    composti = [riga("staffa U-", 100), riga("bracket", 110.8), riga("staffa U-bracket", 300)]
    assert not Vocabolario.del_documento([composti], 9).sillaba
    # la riga sotto deve cominciare alla stessa x: non e' il seguito una riga di un'altra colonna
    lontana = [riga("Ri-", 100), Span("soluzione", 400, 110.8, 440, 119.8, 9, 1), *altrove]
    assert not Vocabolario.del_documento([lontana], 9).sillaba


def test_senza_vocabolario_i_trattini_restano():
    assert unisci_righe(["Effetto Alo-", "ne."]) == "Effetto Alo-ne."


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
