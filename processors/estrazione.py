"""Flusso completo PDF -> articoli validati, indipendente dall'interfaccia."""
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from extractors import ocr_extractor
from extractors.pdf_reader import apri_pdf
from extractors.text_extractor import estrai_span
from processors.article_parser import ParserListino
from processors.data_validator import valida
from processors.models import Articolo

log = logging.getLogger(__name__)

# (pagine elaborate, pagine totali, articoli trovati finora)
Progresso = Callable[[int, int, int], None]


class EstrazioneAnnullata(Exception):
    pass


@dataclass
class RisultatoEstrazione:
    articoli: list[Articolo]
    pagine_totali: int
    pagine_ocr: list[int] = field(default_factory=list)
    pagine_saltate: list[int] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


def estrai_listino(
    percorso: str | Path,
    regole: dict,
    progresso: Progresso | None = None,
    annulla: threading.Event | None = None,
) -> RisultatoEstrazione:
    doc = apri_pdf(percorso)
    try:
        parser = ParserListino(regole)
        cfg_ocr = regole.get("ocr", {})
        minimi = cfg_ocr.get("caratteri_minimi_pagina", 20)
        ocr_ok: bool | None = None
        articoli: list[Articolo] = []
        ris = RisultatoEstrazione(articoli, doc.page_count)
        for indice, page in enumerate(doc):
            if annulla is not None and annulla.is_set():
                raise EstrazioneAnnullata()
            numero = indice + 1
            try:
                spans = estrai_span(page, numero)
                if sum(len(s.testo) for s in spans) < minimi:
                    if ocr_ok is None:
                        ocr_ok = ocr_extractor.ocr_disponibile()
                    if not ocr_ok:
                        if page.get_images():
                            ris.pagine_saltate.append(numero)
                        spans = []
                    else:
                        spans = ocr_extractor.estrai_span_ocr(
                            page, numero, cfg_ocr.get("dpi", 300), cfg_ocr.get("lingua", "ita+eng")
                        )
                        ris.pagine_ocr.append(numero)
                articoli.extend(parser.elabora_pagina(spans, numero))
            except Exception as e:
                # una pagina rotta non deve far perdere le altre
                log.exception("Errore a pagina %s", numero)
                ris.avvisi.append(f"Pagina {numero}: errore di lettura ({e})")
            if progresso:
                progresso(numero, doc.page_count, len(articoli))
        if ris.pagine_saltate:
            ris.avvisi.append(
                "Pagine scansionate non lette perche' l'OCR (Tesseract) non e' installato: "
                + ", ".join(map(str, ris.pagine_saltate))
            )
        ris.avvisi.extend(parser.avvisi)
        valida(articoli, regole)
        return ris
    finally:
        doc.close()


def esegui_in_processo(percorso: str, regole: dict, coda, annulla) -> None:
    """Punto d'ingresso del processo di estrazione avviato dall'interfaccia.

    L'estrazione gira in un processo e non in un thread perche' PyMuPDF tiene il GIL durante
    l'analisi di ogni pagina: in un thread l'interfaccia restava ferma per quasi tutta la durata
    del lavoro (misurato: 5 s di blocco su un listino di 1.210 pagine). Comunica solo per messaggi.
    """
    try:
        ris = estrai_listino(
            percorso,
            regole,
            progresso=lambda n, tot, art: coda.put(("progresso", n, tot, art)),
            annulla=annulla,
        )
        coda.put(("fine", ris))
    except EstrazioneAnnullata:
        coda.put(("annullata",))
    except Exception as e:
        import traceback

        from extractors.pdf_reader import PdfNonValido

        if isinstance(e, PdfNonValido):
            coda.put(("errore", str(e), ""))
        else:
            coda.put(("errore", f"Errore imprevisto: {e}. Dettagli nel file di log.", traceback.format_exc()))
