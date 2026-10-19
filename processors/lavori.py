"""Punto d'ingresso unico del processo separato: estrazione, pre-analisi del wizard, anteprima.

Tutto cio' che apre il PDF con PyMuPDF gira qui e non in un thread dell'interfaccia: PyMuPDF tiene il
GIL durante l'analisi di ogni pagina, e in un thread la finestra restava ferma per quasi tutta la
durata del lavoro (misurato: 5 s di blocco su un listino di 1.210 pagine). Si comunica solo per
messaggi sulla coda:
    ("lettura", pagina, totale) · ("progresso", pagina, totale, articoli) · ("fine", risultato) · ("annullata",)
    ("errore", messaggio_per_l_utente, dettagli_tecnici)
"""
import traceback

ESTRAZIONE, ANALISI, ANTEPRIMA = "estrazione", "analisi", "anteprima"


def _estrazione(coda, annulla, percorso: str, regole: dict):
    from processors.estrazione import estrai_listino

    return estrai_listino(
        percorso, regole, progresso=lambda n, tot, art: coda.put(("progresso", n, tot, art)), annulla=annulla,
        lettura=lambda n, tot: coda.put(("lettura", n, tot)),
    )


def _anteprima(coda, annulla, percorso: str, regole: dict, pagina: int):
    from processors.estrazione import estrai_listino

    return estrai_listino(percorso, regole, annulla=annulla, solo_pagine=[pagina])


ZOOM_ANTEPRIMA = 2.0  # la pagina si disegna una volta sola, a questa scala; lo zoom del wizard la ridimensiona


def _analisi(coda, annulla, percorso: str, pagina: int):
    """Analisi del layout e immagine PNG della pagina, entrambe calcolate qui e non nell'interfaccia."""
    import pymupdf

    from processors.analisi_layout import analizza_pdf

    analisi = analizza_pdf(percorso, pagina)
    with pymupdf.open(percorso) as doc:
        png = doc[pagina - 1].get_pixmap(matrix=pymupdf.Matrix(ZOOM_ANTEPRIMA, ZOOM_ANTEPRIMA)).tobytes("png")
    return analisi, png


COMPITI = {ESTRAZIONE: _estrazione, ANALISI: _analisi, ANTEPRIMA: _anteprima}


def esegui(compito: str, parametri: dict, coda, annulla) -> None:
    from extractors.pdf_reader import PdfNonValido
    from processors.estrazione import EstrazioneAnnullata

    try:
        coda.put(("fine", COMPITI[compito](coda, annulla, **parametri)))
    except EstrazioneAnnullata:
        coda.put(("annullata",))
    except PdfNonValido as e:
        coda.put(("errore", str(e), ""))
    except Exception as e:
        coda.put(("errore", f"Errore imprevisto: {e}. Dettagli nel file di log.", traceback.format_exc()))
