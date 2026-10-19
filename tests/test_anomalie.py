"""Tipi di anomalia: i messaggi raggruppati senza i dettagli che cambiano da un articolo all'altro."""
import pytest

from processors.data_validator import conta_tipi, tipo_anomalia
from processors.models import Articolo


@pytest.mark.parametrize("messaggio, tipo", [
    ("Duplicato: compare 3 volte (pag. 4, 11, 12)", "Duplicato"),
    ("Marca mancante", "Marca mancante"),
    ("Prezzo non riconosciuto: «da Pagina 111» (colonna «Prezzo, x≈524»)", "Prezzo non riconosciuto"),
    ("Prezzo non riconosciuto dall'espressione del fornitore (colonna «Listino»)",
     "Prezzo non riconosciuto dall'espressione del fornitore"),
    ("Altro prezzo trovato a pagina 4 (colonna «Listino»): «.» — verificare", "Altro prezzo trovato"),
    ("Testo in piu' a pagina 23 (colonna «Modello»): «innovative»", "Testo in piu'"),
    ("Piu' prezzi per lo stesso articolo (€ 53,00 | € 53,00) nella colonna «Listino»: indicare",
     "Piu' prezzi per lo stesso articolo"),
    ("Codice in formato inatteso nella colonna «Codice»: «X1»", "Codice in formato inatteso"),
    ("Codice non trovato nella colonna «Modello»", "Codice non trovato"),
    ("Codice non trovato", "Codice non trovato"),
    ("Secondo prezzo nella colonna «Netto»: verificare", "Secondo prezzo"),
    ("Prezzo pari a zero — verificare", "Prezzo pari a zero"),
    ("EAN non valido: «3677»", "EAN non valido"),
    ("Testo forse troncato nel PDF (parentesi non chiusa)", "Testo forse troncato nel PDF"),
    ("Testo OCR incerto (confidenza 54%)", "Testo OCR incerto"),
])
def test_tipo_di_anomalia(messaggio, tipo):
    assert tipo_anomalia(messaggio) == tipo


def test_conteggio_per_tipo_un_articolo_conta_una_volta():
    articoli = [
        Articolo("A", anomalie=["Duplicato: compare 2 volte (pag. 1, 2)", "Marca mancante"]),
        Articolo("A", anomalie=["Duplicato: compare 2 volte (pag. 1, 2)"]),
        # due anomalie dello stesso tipo sullo stesso articolo: conta una volta
        Articolo("B", note_estrazione={"prezzo": "Prezzo non riconosciuto: «x»"},
                 anomalie=["Prezzo non riconosciuto: «y»"]),
        Articolo("C"),
    ]
    assert conta_tipi(articoli) == [("Duplicato", 2), ("Marca mancante", 1), ("Prezzo non riconosciuto", 1)]
