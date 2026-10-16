"""Flusso completo PDF -> articoli validati, indipendente dall'interfaccia.

Due passate: la prima raccoglie il testo di ogni pagina, la seconda lo legge. Servono entrambe
perche' le soglie del motore (corpo e interlinea mediani, testate e piedi ripetuti, ancora per
densita') sono statistiche del documento intero, non di una pagina.
"""
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from extractors import ocr_extractor
from extractors.pdf_reader import apri_pdf
from extractors.table_extractor import linee_divisorie
from extractors.text_extractor import estrai_span
from processors.article_parser import ParserListino
from processors.data_validator import valida
from processors.models import Articolo, Span
from processors.profilo import normalizza

log = logging.getLogger(__name__)

# (pagine elaborate, pagine totali, articoli trovati finora)
Progresso = Callable[[int, int, int], None]
# pagine su cui si calcolano le statistiche quando se ne estrae solo una (anteprima del wizard)
CAMPIONE_ANTEPRIMA = 30


class EstrazioneAnnullata(Exception):
    pass


@dataclass
class RisultatoEstrazione:
    articoli: list[Articolo]
    pagine_totali: int
    pagine_ocr: list[int] = field(default_factory=list)
    pagine_saltate: list[int] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)
    ancora: str = ""  # campo su cui sono stati individuati gli articoli


@dataclass
class _Pagina:
    numero: int
    spans: list[Span]
    larghezza: float
    altezza: float
    separatori: list[float]


def _campione(totale: int, scelte: list[int]) -> list[int]:
    """Indici (da 0) di un campione distribuito sul documento, che include le pagine scelte."""
    passo = max(1, totale // CAMPIONE_ANTEPRIMA)
    return sorted(set(range(0, totale, passo)) | {n - 1 for n in scelte})


def estrai_listino(
    percorso: str | Path,
    regole: dict,
    progresso: Progresso | None = None,
    annulla: threading.Event | None = None,
    solo_pagine: list[int] | None = None,
) -> RisultatoEstrazione:
    regole = normalizza(regole)
    doc = apri_pdf(percorso)
    try:
        cfg_ocr = regole["ocr"]
        minimi = cfg_ocr.get("caratteri_minimi_pagina", 20)
        divisorie = regole["spaziatura"]["linee_divisorie"]
        ris = RisultatoEstrazione([], doc.page_count)
        indici = _campione(doc.page_count, solo_pagine) if solo_pagine else range(doc.page_count)
        ocr_ok: bool | None = None
        pagine: list[_Pagina] = []
        for indice in indici:
            if annulla is not None and annulla.is_set():
                raise EstrazioneAnnullata()
            numero = indice + 1
            page = doc[indice]
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
                        spans = ocr_extractor.estrai_span_ocr(page, numero, cfg_ocr.get("dpi", 300),
                                                              cfg_ocr.get("lingua", "ita+eng"))
                        ris.pagine_ocr.append(numero)
                separatori = linee_divisorie(page, page.rect.width) if divisorie else []
                pagine.append(_Pagina(numero, spans, page.rect.width, page.rect.height, separatori))
            except Exception as e:
                # una pagina rotta non deve far perdere le altre
                log.exception("Errore a pagina %s", numero)
                ris.avvisi.append(f"Pagina {numero}: errore di lettura ({e})")

        parser = ParserListino(regole)
        parser.prepara([(p.spans, p.larghezza, p.altezza) for p in pagine])
        ris.ancora = parser.ancora
        da_leggere = [p for p in pagine if not solo_pagine or p.numero in solo_pagine]
        totale = len(da_leggere) if solo_pagine else doc.page_count
        for n, p in enumerate(da_leggere, 1):
            if annulla is not None and annulla.is_set():
                raise EstrazioneAnnullata()
            try:
                ris.articoli.extend(parser.elabora_pagina(p.spans, p.numero, p.larghezza, p.altezza, p.separatori))
            except Exception as e:
                log.exception("Errore a pagina %s", p.numero)
                ris.avvisi.append(f"Pagina {p.numero}: errore di analisi ({e})")
            if progresso:
                progresso(n if solo_pagine else p.numero, totale, len(ris.articoli))
        if ris.pagine_saltate:
            ris.avvisi.append(
                "Pagine scansionate non lette perche' l'OCR (Tesseract) non e' installato: "
                + ", ".join(map(str, ris.pagine_saltate))
            )
        ris.avvisi.extend(parser.avvisi)
        valida(ris.articoli, regole)
        return ris
    finally:
        doc.close()
