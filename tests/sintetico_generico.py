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


# --- colonne dinamiche -----------------------------------------------------------------------------
# Due listini con colonne diverse dalle cinque standard: il foglio "Listino" deve avere le loro, con i
# loro nomi. "tre": Articolo | Descrizione | Prezzo, niente codice ne' EAN. "colore": una colonna in piu'
# («Colour») fra quelle note, che non e' il nome di nessun campo.
_ART = [
    ("SP-100", ["Bookshelf speaker 50W"], E[0], "Black", "249.00"),
    ("SP-200", ["Floorstanding speaker", "walnut finish"], E[1], "Walnut", "1,249.50"),
    ("SP-300", ["Active subwoofer 300W"], E[2], "White", "599.00"),
    ("AMP-1", ["Stereo amplifier 2x100W"], E[3], "Silver", "349.00"),
    ("AMP-2", ["Power amplifier 2x400W", "rack mount 2U"], E[4], "Black", "2,100.00"),
    ("CBL-10", ["Speaker cable 10 m"], E[5], "Red", "35.00"),
]
VARIANTI = {
    # (etichetta, x, allineamento, valore dell'articolo)
    "tre": [("Articolo", 40, "sx", lambda a: [a[0]]), ("Descrizione", 140, "sx", lambda a: a[1]),
            ("Prezzo", 550, "dx", lambda a: [a[4]])],
    "colore": [("SKU", 40, "sx", lambda a: [a[0]]), ("Description", 120, "sx", lambda a: a[1]),
               ("Colour", 300, "sx", lambda a: [a[3]]), ("EAN", 380, "sx", lambda a: [a[2]]),
               ("Price EUR", 550, "dx", lambda a: [a[4]])],
}
ATTESI_COLONNE = {
    "tre": (["Articolo", "Descrizione", "Prezzo"],
            [[a[0], " ".join(a[1]), float(a[4].replace(",", ""))] for a in _ART]),
    "colore": (["SKU", "Description", "Colour", "EAN", "Price EUR"],
               [[a[0], " ".join(a[1]), a[3], a[2], float(a[4].replace(",", ""))] for a in _ART]),
}


def crea_listino_colonne(percorso: str | Path, variante: str) -> Path:
    percorso = Path(percorso)
    colonne = VARIANTI[variante]
    doc = pymupdf.open()
    for n, articoli in enumerate((_ART[:3], _ART[3:]), 1):  # tre per pagina: serve a misurare l'allineamento
        page = doc.new_page(width=595, height=842)
        _scrivi(page, 40, 40, "ACME Audio Srl - Listino 2026", 14)
        y = 110.0
        for etichetta, x, allinea, _ in colonne:
            (_a_destra if allinea == "dx" else _scrivi)(page, x, y, etichetta)
        y += 24
        for a in articoli:
            righe = 1
            for _, x, allinea, valore in colonne:
                for i, testo in enumerate(valore(a)):
                    (_a_destra if allinea == "dx" else _scrivi)(page, x, y + i * INTERLINEA, testo)
                righe = max(righe, len(valore(a)))
            y += righe * INTERLINEA + STACCO
        _scrivi(page, 520, 805, f"Pagina {n} / 2", 7)
    doc.save(percorso)
    doc.close()
    return percorso
