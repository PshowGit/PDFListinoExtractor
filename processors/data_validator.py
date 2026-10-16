"""Controlli sugli articoli estratti. Nulla viene corretto o scartato: si segnala soltanto."""
from collections import defaultdict
from decimal import Decimal

from processors.models import Articolo


def ean_valido(ean: str) -> bool:
    """GTIN-8/12/13/14 con cifra di controllo corretta."""
    if not ean.isdigit() or len(ean) not in (8, 12, 13, 14):
        return False
    cifre = [int(c) for c in ean]
    controllo = cifre.pop()
    # da destra, escluso il controllo: pesi 3,1,3,1...
    somma = sum(c * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(cifre)))
    return (10 - somma % 10) % 10 == controllo


def _parentesi_sbilanciate(testo: str) -> bool:
    return testo.count("(") != testo.count(")")


def chiave_duplicato(a: Articolo) -> str:
    return (a.codice or a.modello).strip().upper()


def valida(articoli: list[Articolo], regole: dict | None = None) -> None:
    """Ricalcola `anomalie` su ogni articolo. Si puo' rieseguire dopo ogni modifica dell'utente."""
    regole = regole or {}
    prezzo_massimo = Decimal(str(regole.get("prezzo_massimo", 1_000_000)))
    conf_minima = regole.get("ocr", {}).get("confidenza_minima", 70)

    pagine_per_chiave: dict[str, list[int]] = defaultdict(list)
    for a in articoli:
        k = chiave_duplicato(a)
        if k:
            pagine_per_chiave[k].append(a.pagina)

    for a in articoli:
        an: list[str] = []
        note = a.note_estrazione
        if not a.modello.strip() and "modello" not in note:
            an.append("Modello mancante")
        if not a.codice.strip() and "codice" not in note:
            an.append("Codice mancante")
        if not a.descrizione.strip():
            an.append("Descrizione mancante")
        if a.prezzo is None:
            if "prezzo" not in note:
                an.append("Prezzo mancante")
        elif a.prezzo == 0:
            an.append("Prezzo pari a zero — verificare")
        elif a.prezzo < 0 or a.prezzo > prezzo_massimo:
            an.append(f"Prezzo fuori scala: {a.prezzo}")
        if a.ean and not ean_valido(a.ean) and "ean" not in note:
            an.append(f"EAN non valido: «{a.ean}»")
        if _parentesi_sbilanciate(a.modello) or _parentesi_sbilanciate(a.descrizione):
            an.append("Testo forse troncato nel PDF (parentesi non chiusa)")
        k = chiave_duplicato(a)
        if k and len(pagine_per_chiave[k]) > 1:
            altre = sorted(set(pagine_per_chiave[k]))
            an.append(f"Duplicato: compare {len(pagine_per_chiave[k])} volte (pag. {', '.join(map(str, altre))})")
        if a.da_ocr and a.confidenza_minima is not None and a.confidenza_minima < conf_minima:
            an.append(f"Testo OCR incerto (confidenza {a.confidenza_minima:.0f}%)")
        a.anomalie = an
