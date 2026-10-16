"""PDF sintetico che riproduce l'impaginazione del listino JBL/Exhibo, con risultati attesi noti.

Uso da riga di comando per salvarne una copia da aprire nell'applicazione:
    uv run python -m tests.sintetico samples/listino_sintetico.pdf
"""
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymupdf

LARGHEZZA, ALTEZZA = 595, 842
X_MOD, X_DES, X_PREZZO_DX = 102, 202, 504.8
CORPO, INTERLINEA = 7, 10.5


@dataclass(frozen=True)
class Atteso:
    modello: str
    codice: str
    ean: str
    descrizione: str
    prezzo: Decimal | None
    pagina: int
    anomalie: tuple[str, ...] = ()  # sottostringhe che devono comparire fra le anomalie


ATTESI = [
    Atteso("AMP100", "(00123-A)", "8710150083632",
           "Amplificatore compatto 2 x 120W, classe D, 4ohm/8ohm/70V/100V, staffa inclusa.",
           Decimal("1234.56"), 1, ("Duplicato",)),
    Atteso("AMP-200/B", "(0045.B-X)", "", "Mixer amplificato 240W", Decimal("735.00"), 1),
    Atteso("Cover per diffusore X1 nero", "(JB-COVER-01)", "691991014208",
           "Cover per diffusore X1 nero", Decimal("49.00"), 1),
    Atteso("SPK1", "(SPK-001)", "691991014215", "Diffusore water-resistant IP55, 2 vie",
           Decimal("12345.00"), 2),
    Atteso("SPK2", "(SPK-002)", "", "Articolo senza prezzo", None, 2, ("Prezzo mancante",)),
    Atteso("AMP100", "(00123-A)", "", "Ripetuto in un'altra sezione", Decimal("1234.56"), 2, ("Duplicato",)),
    Atteso("SPK3", "(SPK-003)", "", "Articolo con due prezzi", None, 2, ("Piu' prezzi",)),
    Atteso("SPK4", "(SPK-004)", "691991014222", "Descrizione che prosegue nella pagina successiva.",
           Decimal("250.00"), 2),
    Atteso("SUB 18", "(000777)", "1234567", "Subwoofer 18'' a pagina 3", Decimal("0.00"), 3,
           ("Prezzo pari a zero", "EAN non valido")),
]

# Contenuto pagina per pagina: titoli, articoli (righe modello, righe descrizione, prezzi), testo libero.
PAGINE = [
    [
        ("titolo", "Amplificatori"),
        ("art", ["AMP100", "(00123-A)", "8710150083632"],
         ["Amplificatore compatto 2 x 120W,", "classe D, 4ohm/8ohm/70V/100V,", "staffa inclusa."], ["1.234,56"]),
        ("art", ["AMP-200/B", "(0045.B-X)"], ["Mixer amplificato 240W"], ["735,00"]),
        ("art", ["Cover per diffusore", "X1 nero", "(JB-COVER-01)", "691991014208"], [], ["49,00"]),
    ],
    [
        ("titolo", "Diffusori"),
        ("art", ["SPK1", "(SPK-001)", "691991014215"], ["Diffusore water-", "resistant IP55, 2 vie"], ["12.345,00"]),
        ("art", ["SPK2", "(SPK-002)"], ["Articolo senza prezzo"], []),
        ("art", ["AMP100", "(00123-A)"], ["Ripetuto in un'altra sezione"], ["1.234,56"]),
        ("art", ["SPK3", "(SPK-003)"], ["Articolo con due prezzi"], ["100,00", "90,00"]),
        ("spazio", 290),  # spinge l'ultimo articolo in fondo alla pagina, sopra il piede
        ("art", ["SPK4", "(SPK-004)", "691991014222"], ["Descrizione che prosegue"], ["250,00"]),
    ],
    [
        ("seguito", ["nella pagina successiva."]),
        ("art", ["SUB 18", "(000777)", "1234567"], ["Subwoofer 18'' a pagina 3"], ["0,00"]),
    ],
    [],  # pagina senza articoli
]


def _scrivi(page, x, y, testo, corpo=CORPO):
    page.insert_text((x, y), testo, fontsize=corpo, fontname="helv")


def _testata_e_piede(page, numero, totale):
    _scrivi(page, 32, 30, "Listino", 16)
    _scrivi(page, 487, 30, "Gennaio 2026", 12)
    _scrivi(page, 431, 110, "Sostituisce e annulla i precedenti", 9)
    _scrivi(page, 462, 122, "Prezzi in Euro I.V.A. esclusa", 8)
    _scrivi(page, X_MOD, 144, "Modello")
    _scrivi(page, X_DES, 144, "Descrizione")
    _scrivi(page, 467, 144, "Prezzo al")
    _scrivi(page, 467, 154.5, "Pubblico")
    _scrivi(page, 170, 793, "Exhibo S.p.A. Communication Systems - Via Leonardo da Vinci, 6")
    _scrivi(page, 502, 798, f"Pagina {numero} di {totale}")
    _scrivi(page, 197, 803, "Tel. 039-4984.1 - e mail: info@exhibo.it")


def crea_listino_sintetico(percorso: str | Path) -> Path:
    percorso = Path(percorso)
    doc = pymupdf.open()
    for n, contenuto in enumerate(PAGINE, 1):
        page = doc.new_page(width=LARGHEZZA, height=ALTEZZA)
        _testata_e_piede(page, n, len(PAGINE))
        y = 205.0
        for elem in contenuto:
            tipo = elem[0]
            if tipo == "titolo":
                _scrivi(page, 30, y, elem[1], 19)
                y += 36
            elif tipo == "spazio":
                y += elem[1]
            elif tipo == "seguito":
                for riga in elem[1]:
                    _scrivi(page, X_DES, y, riga)
                    y += INTERLINEA
                y += 20
            else:
                _, modello, descrizione, prezzi = elem
                for i, riga in enumerate(modello):
                    _scrivi(page, X_MOD, y + i * INTERLINEA, riga)
                for i, riga in enumerate(descrizione):
                    _scrivi(page, X_DES, y + i * INTERLINEA, riga)
                for i, prezzo in enumerate(prezzi):
                    w = pymupdf.get_text_length(prezzo, fontname="helv", fontsize=CORPO)
                    _scrivi(page, X_PREZZO_DX - w, y + i * INTERLINEA, prezzo)
                y += max(len(modello), len(descrizione), len(prezzi)) * INTERLINEA + 28
    doc.save(percorso)
    doc.close()
    return percorso


def crea_scansione(origine: str | Path, destinazione: str | Path, dpi: int = 200) -> Path:
    """Copia "scansionata" del PDF: ogni pagina diventa un'immagine, senza testo selezionabile."""
    destinazione = Path(destinazione)
    with pymupdf.open(origine) as src, pymupdf.open() as out:
        for page in src:
            pix = page.get_pixmap(dpi=dpi)
            nuova = out.new_page(width=page.rect.width, height=page.rect.height)
            nuova.insert_image(nuova.rect, pixmap=pix)
        out.save(destinazione)
    return destinazione


if __name__ == "__main__":
    print(crea_listino_sintetico(sys.argv[1] if len(sys.argv) > 1 else "listino_sintetico.pdf"))
