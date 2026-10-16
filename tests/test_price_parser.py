from decimal import Decimal

import pytest

from processors.price_parser import formatta_prezzo, parse_prezzo


@pytest.mark.parametrize(
    "testo, atteso",
    [
        ("735,00", "735.00"),
        ("1.234,56", "1234.56"),
        ("12.345.678,90", "12345678.90"),
        ("12,5", "12.50"),
        ("€ 1.234,56", "1234.56"),
        ("1.234,56 €", "1234.56"),
        ("EUR 99,90", "99.90"),
        ("0,00", "0.00"),
        ("1234", "1234.00"),
    ],
)
def test_formati_italiani(testo, atteso):
    esito = parse_prezzo(testo, "it")
    assert esito.valore == Decimal(atteso)
    assert not esito.ambiguo


@pytest.mark.parametrize("testo, atteso", [("1,234.56", "1234.56"), ("1234.56", "1234.56"), ("€1,000.00", "1000.00")])
def test_formati_internazionali(testo, atteso):
    esito = parse_prezzo(testo, "en")
    assert esito.valore == Decimal(atteso) and not esito.ambiguo


def test_in_auto_riconosce_entrambi_senza_ambiguita():
    assert parse_prezzo("1.234,56").valore == Decimal("1234.56")
    assert parse_prezzo("1,234.56").valore == Decimal("1234.56")


@pytest.mark.parametrize("testo", ["1.234", "1,234"])
def test_migliaia_senza_decimali_sono_ambigue_in_auto(testo):
    esito = parse_prezzo(testo)
    assert esito.ambiguo and "ambiguo" in esito.motivo


def test_con_formato_dichiarato_le_migliaia_non_sono_ambigue():
    assert parse_prezzo("1.234", "it").valore == Decimal("1234.00")
    assert not parse_prezzo("1.234", "it").ambiguo


def test_punto_decimale_in_un_listino_italiano_e_segnalato():
    esito = parse_prezzo("1234.56", "it")
    assert esito.valore == Decimal("1234.56") and esito.ambiguo


@pytest.mark.parametrize("testo", ["", None, "su richiesta", "12,345,6", "-"])
def test_valori_non_riconosciuti(testo):
    esito = parse_prezzo(testo, "it")
    assert esito.valore is None and esito.motivo


def test_formattazione_italiana():
    assert formatta_prezzo(Decimal("1234.5")) == "1.234,50"
    assert formatta_prezzo(None) == ""
