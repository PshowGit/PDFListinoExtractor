"""Apertura e verifica del PDF. Il file viene solo letto: non si salva mai nulla sull'originale."""
from dataclasses import dataclass
from pathlib import Path

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)  # gli errori li riportiamo noi, in italiano


class PdfNonValido(Exception):
    """Il file non e' un PDF leggibile; il messaggio e' pensato per l'utente."""


@dataclass(frozen=True)
class InfoPdf:
    percorso: Path
    pagine: int
    pagine_con_testo: int

    @property
    def scansionato(self) -> bool:
        return self.pagine_con_testo == 0


def apri_pdf(percorso: str | Path) -> pymupdf.Document:
    p = Path(percorso)
    if not p.is_file():
        raise PdfNonValido(f"File non trovato: {p}")
    if p.stat().st_size == 0:
        raise PdfNonValido("Il file e' vuoto (0 byte).")
    try:
        doc = pymupdf.open(p, filetype="pdf")
    except Exception as e:  # pymupdf solleva tipi diversi a seconda del danno
        raise PdfNonValido(f"Il file non e' un PDF valido o e' danneggiato ({e}).") from e
    if doc.needs_pass:
        doc.close()
        raise PdfNonValido("Il PDF e' protetto da password.")
    if doc.page_count == 0:
        doc.close()
        raise PdfNonValido("Il PDF non contiene pagine.")
    return doc


def pagina_ha_testo(page: pymupdf.Page, caratteri_minimi: int = 20) -> bool:
    return len(page.get_text().strip()) >= caratteri_minimi


def verifica_pdf(percorso: str | Path, caratteri_minimi: int = 20) -> InfoPdf:
    """Apre il PDF, ne controlla la leggibilita' pagina per pagina e lo richiude."""
    doc = apri_pdf(percorso)
    try:
        con_testo = 0
        for i, page in enumerate(doc):
            try:
                if pagina_ha_testo(page, caratteri_minimi):
                    con_testo += 1
            except Exception as e:
                raise PdfNonValido(f"Pagina {i + 1} illeggibile: {e}") from e
        return InfoPdf(Path(percorso), doc.page_count, con_testo)
    finally:
        doc.close()
