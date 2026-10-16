"""Secondo PDF sintetico, con un layout opposto a quello JBL: serve a provare che il motore e' universale.

Tabella a una riga per articolo, colonne SKU | Description | EAN | Price EUR in quest'ordine, corpo 9,
prezzi in formato inglese allineati a destra, descrizioni su due righe, titoli di sezione, testata e
piede ripetuti. Variante `con_intestazione=False`: la stessa tabella senza la riga delle etichette,
da cui le colonne vanno ricostruite dalla sola posizione del testo.
"""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymupdf

CORPO, INTERLINEA, STACCO = 9, 11, 6
X_SKU, X_DESC, X_EAN, X_PREZZO_DX = 40, 120, 380, 550


def ean13(base12: str) -> str:
    somma = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(base12))
    return base12 + str((10 - somma % 10) % 10)


@dataclass(frozen=True)
class AttesoGenerico:
    codice: str
    descrizione: str
    ean: str
    prezzo: Decimal | None
    pagina: int
    categoria: str
    anomalie: tuple[str, ...] = ()


E = [ean13(f"80123456{n:04d}") for n in range(1, 10)]

PAGINE = [
    [
        ("titolo", "Speakers"),
        ("art", "SP-100", ["Bookshelf speaker 2-way, 50W"], E[0], "249.00"),
        ("art", "SP-200", ["Floorstanding speaker 3-way, 150W,", "walnut finish"], E[1], "1,249.50"),
        ("art", "SP-300", ["Active subwoofer 12 inch, 300W"], E[2], ""),
        ("art", "0007-X", ["Wall bracket for SP-100 speakers"], "", "19.90"),
        ("titolo", "Amplifiers"),
        ("art", "AMP-1", ["Stereo power amplifier 2x100W"], E[3], "on request"),
    ],
    [
        ("art", "AMP-2", ["Stereo power amplifier 2x400W,", "rack mount 2U"], E[4], "2,100.00"),
        ("art", "AMP-3", ["Mixer amplifier 120W with 4 zones"], E[5], "899.00"),
    ],
    [
        ("titolo", "Accessories"),
        ("art", "CBL-10", ["Speaker cable 10 m, 2x2.5 mm"], E[6], "35.00"),
    ],
]

ATTESI = [
    AttesoGenerico("SP-100", "Bookshelf speaker 2-way, 50W", E[0], Decimal("249.00"), 1, "Speakers"),
    AttesoGenerico("SP-200", "Floorstanding speaker 3-way, 150W, walnut finish", E[1], Decimal("1249.50"), 1, "Speakers"),
    AttesoGenerico("SP-300", "Active subwoofer 12 inch, 300W", E[2], None, 1, "Speakers", ("Prezzo mancante",)),
    AttesoGenerico("0007-X", "Wall bracket for SP-100 speakers", "", Decimal("19.90"), 1, "Speakers"),
    AttesoGenerico("AMP-1", "Stereo power amplifier 2x100W", E[3], None, 1, "Amplifiers", ("non riconosciuto",)),
    AttesoGenerico("AMP-2", "Stereo power amplifier 2x400W, rack mount 2U", E[4], Decimal("2100.00"), 2, "Amplifiers"),
    AttesoGenerico("AMP-3", "Mixer amplifier 120W with 4 zones", E[5], Decimal("899.00"), 2, "Amplifiers"),
    AttesoGenerico("CBL-10", "Speaker cable 10 m, 2x2.5 mm", E[6], Decimal("35.00"), 3, "Accessories"),
]


def _scrivi(page, x, y, testo, corpo=CORPO):
    page.insert_text((x, y), testo, fontsize=corpo, fontname="helv")


def _a_destra(page, x_dx, y, testo):
    w = pymupdf.get_text_length(testo, fontname="helv", fontsize=CORPO)
    _scrivi(page, x_dx - w, y, testo)


def crea_listino_generico(percorso: str | Path, con_intestazione: bool = True) -> Path:
    percorso = Path(percorso)
    doc = pymupdf.open()
    for n, contenuto in enumerate(PAGINE, 1):
        page = doc.new_page(width=595, height=842)
        _scrivi(page, 40, 40, "ACME Audio Srl - Price List 2026", 14)
        _scrivi(page, 40, 58, "All prices in EUR, VAT excluded", 8)
        y = 110.0
        if con_intestazione:
            for x, etichetta in ((X_SKU, "SKU"), (X_DESC, "Description"), (X_EAN, "EAN")):
                _scrivi(page, x, y, etichetta)
            _a_destra(page, X_PREZZO_DX, y, "Price EUR")
        y += 24
        for elem in contenuto:
            if elem[0] == "titolo":
                _scrivi(page, X_SKU, y + 4, elem[1], 13)
                y += 26
                continue
            _, sku, righe, ean, prezzo = elem
            _scrivi(page, X_SKU, y, sku)
            for i, r in enumerate(righe):
                _scrivi(page, X_DESC, y + i * INTERLINEA, r)
            if ean:
                _scrivi(page, X_EAN, y, ean)
            if prezzo:
                _a_destra(page, X_PREZZO_DX, y, prezzo)
            y += len(righe) * INTERLINEA + STACCO
        _scrivi(page, 40, 805, "ACME Audio Srl - www.acme.example - info@acme.example", 7)
        _scrivi(page, 520, 805, f"Page {n} / {len(PAGINE)}", 7)
    doc.save(percorso)
    doc.close()
    return percorso
