import json

import pytest

import config
from config import PERCORSO_REGOLE, _leggi, carica_regole, regole_fornitore, valida_schema
from processors.profilo import campo_da_intestazione, chiave_da_nome, da_versione_1, normalizza

VECCHIO_JBL = {
    "nome": "JBL vecchio formato",
    "intestazioni": {"modello": "Modello", "descrizione": "Descrizione", "prezzo": "Prezzo al"},
    "colonne_predefinite": {"modello_x": 102.0, "descrizione_x": 202.0, "prezzo_x": 467.0},
    "tolleranza_colonna": 6.0,
    "piede_pagina": ["^Pagina \\d+ di \\d+$"],
    "regex_codice": "^\\((?P<codice>[^()]+)\\)$",
    "codice_con_parentesi": True,
    "formato_prezzo": "it",
}


def test_le_regole_distribuite_rispettano_lo_schema():
    valida_schema(_leggi(PERCORSO_REGOLE))


@pytest.mark.parametrize(
    "etichetta, campo",
    [
        ("SKU", "codice"), ("Part Number", "codice"), ("Cod. Art.", "codice"), ("P/N", "codice"),
        ("Prezzo al Pubblico", "prezzo"), ("Price EUR", "prezzo"), ("Prezzo al", "prezzo"),
        ("Descrizione", "descrizione"), ("Description", "descrizione"), ("EAN13", "ean"),
        ("Modello", "modello"), ("Codice a barre", "ean"),
    ],
)
def test_sinonimi_delle_intestazioni(etichetta, campo):
    assert campo_da_intestazione(etichetta)[0] == campo


def test_listino_non_e_una_colonna_prezzo():
    # e' il titolo di quasi ogni documento: riconoscerlo creerebbe una colonna inesistente
    assert campo_da_intestazione("Listino")[0] is None


def test_sinonimi_aggiuntivi_del_fornitore():
    assert campo_da_intestazione("Matricola fornitore")[0] is None
    assert campo_da_intestazione("Matricola fornitore", {"codice": ["matricola"]})[0] == "codice"


def test_conversione_dalla_versione_1():
    nuovo = da_versione_1(VECCHIO_JBL)
    assert [c["campo"] for c in nuovo["colonne"]] == ["identificativo", "descrizione", "prezzo"]
    assert nuovo["colonne"][0]["x_relativo"] == round(102 / 595, 4)
    assert "?P<valore>" in nuovo["regex"]["codice"]
    assert nuovo["ancora"] == "codice"


def test_normalizza_completa_e_accetta_la_versione_1():
    p = normalizza(VECCHIO_JBL)
    assert p["spaziatura"]["fattore_stacco"] == 1.5
    assert p["colonne"][0]["contiene"] == ["modello", "codice", "ean"]
    assert normalizza(p) == p  # idempotente


def test_un_profilo_versione_1_estrae_come_quello_nuovo(pdf_sintetico):
    from processors.estrazione import estrai_listino

    vecchio = estrai_listino(pdf_sintetico, VECCHIO_JBL).articoli
    nuovo = estrai_listino(pdf_sintetico, regole_fornitore("jbl_exhibo")).articoli
    assert [(a.codice, a.descrizione, a.prezzo) for a in vecchio] == [(a.codice, a.descrizione, a.prezzo) for a in nuovo]


def test_file_personale_versione_1_si_legge_ancora(tmp_path):
    personali = tmp_path / "supplier_rules.json"
    personali.write_text(json.dumps({"fornitori": {"vecchio": VECCHIO_JBL}}), encoding="utf-8")
    tutte = carica_regole(PERCORSO_REGOLE, personali=personali)
    assert "vecchio" in tutte["fornitori"] and config.avviso_regole_personali is None


def test_file_personale_versione_2_non_valido_e_ignorato(tmp_path):
    personali = tmp_path / "supplier_rules.json"
    personali.write_text(json.dumps({"versione_schema": 2, "fornitori": {"x": {"nome": "X"}}}), encoding="utf-8")
    tutte = carica_regole(PERCORSO_REGOLE, personali=personali)
    assert "x" not in tutte["fornitori"]
    assert "colonne" in config.avviso_regole_personali


def test_chiave_da_nome():
    assert chiave_da_nome("Fornitore Città & Co.") == "fornitore_citta_co"
    assert chiave_da_nome("ACME", {"acme"}) == "acme_2"
    assert chiave_da_nome("!!!") == "fornitore"
