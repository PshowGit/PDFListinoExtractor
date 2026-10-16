"""Estrazione del testo con coordinate dalle pagine con testo selezionabile."""
import pymupdf

from processors.models import Span

# Senza TEXT_PRESERVE_IMAGES: di default "dict" porta con se' i byte di ogni immagine della pagina,
# ed era il 75% del tempo di estrazione sul listino JBL (4-11 immagini per pagina).
FLAG_TESTO = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


def estrai_span(page: pymupdf.Page, pagina: int) -> list[Span]:
    """Tutti i frammenti di testo non vuoti della pagina, con bbox e corpo del carattere."""
    spans: list[Span] = []
    for blocco in page.get_text("dict", flags=FLAG_TESTO)["blocks"]:
        for riga in blocco.get("lines", []):
            for s in riga["spans"]:
                testo = s["text"].strip()
                if not testo:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                spans.append(Span(testo, x0, y0, x1, y1, s["size"], pagina))
    return spans
