"""OCR facoltativo per le pagine scansionate (Tesseract via pytesseract).

Produce gli stessi `Span` dell'estrattore testuale, in coordinate PDF, cosi' il parser
non deve sapere da dove arriva il testo. Ogni parola porta la sua confidenza.
"""
import io
import shutil
from pathlib import Path

import pymupdf

from processors.models import Span

_PERCORSI_NOTI = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


def _configura_tesseract():
    try:
        import pytesseract
    except ImportError:
        return None
    if not shutil.which(pytesseract.pytesseract.tesseract_cmd):
        for p in _PERCORSI_NOTI:
            if p.is_file():
                pytesseract.pytesseract.tesseract_cmd = str(p)
                break
    return pytesseract


def ocr_disponibile() -> bool:
    pt = _configura_tesseract()
    if pt is None:
        return False
    try:
        pt.get_tesseract_version()
        return True
    except Exception:
        return False


def estrai_span_ocr(page: pymupdf.Page, pagina: int, dpi: int = 300, lingua: str = "ita+eng") -> list[Span]:
    pytesseract = _configura_tesseract()
    if pytesseract is None:
        raise RuntimeError("pytesseract non installato")
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        dati = pytesseract.image_to_data(img, lang=lingua, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        # lingua non installata: si ripiega sull'inglese, sempre presente
        dati = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT)
    scala = 72.0 / dpi
    spans: list[Span] = []
    for i, testo in enumerate(dati["text"]):
        testo = (testo or "").strip()
        conf = float(dati["conf"][i])
        if not testo or conf < 0:
            continue
        x0 = dati["left"][i] * scala
        y0 = dati["top"][i] * scala
        x1 = x0 + dati["width"][i] * scala
        y1 = y0 + dati["height"][i] * scala
        # l'altezza della parola e' circa il 70% del corpo del carattere
        spans.append(Span(testo, x0, y0, x1, y1, (y1 - y0) / 0.7, pagina, conf))
    return spans
