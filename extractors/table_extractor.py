"""Ricostruzione della tabella: colonne, area utile della pagina e righe di testo."""
import re
from dataclasses import dataclass

from processors.models import Span

MODELLO, DESCRIZIONE, PREZZO, TITOLO = "modello", "descrizione", "prezzo", "titolo"


@dataclass(frozen=True)
class Colonne:
    modello_x: float
    descrizione_x: float
    prezzo_x: float
    rilevate: bool  # False = posizioni predefinite della configurazione
    y_intestazione: float | None = None  # bordo inferiore dell'intestazione, se trovata


@dataclass
class Riga:
    """Spans della stessa colonna allineati sulla stessa linea di base."""

    spans: list[Span]

    @property
    def y0(self) -> float:
        return min(s.y0 for s in self.spans)

    @property
    def y1(self) -> float:
        return max(s.y1 for s in self.spans)

    @property
    def x0(self) -> float:
        return min(s.x0 for s in self.spans)

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.spans)

    @property
    def testo(self) -> str:
        return " ".join(s.testo for s in sorted(self.spans, key=lambda s: s.x0))

    @property
    def size(self) -> float:
        return max(s.size for s in self.spans)

    @property
    def confidenza(self) -> float | None:
        valori = [s.confidenza for s in self.spans if s.confidenza is not None]
        return min(valori) if valori else None


def _etichetta_combacia(testo: str, etichetta: str) -> bool:
    # il testo PDF ha l'etichetta intera ("Prezzo al"), l'OCR una parola per volta ("Prezzo")
    return testo == etichetta or testo == etichetta.split()[0]


def rileva_colonne(spans: list[Span], regole: dict) -> Colonne:
    """Posizione delle colonne letta dall'intestazione della pagina, se c'e'."""
    etichette = regole["intestazioni"]
    trovate: dict[str, Span] = {}
    for s in sorted(spans, key=lambda s: s.y0):
        for chiave, etichetta in etichette.items():
            if chiave not in trovate and _etichetta_combacia(s.testo, etichetta):
                trovate[chiave] = s
    if len(trovate) == 3:
        ys = [s.y0 for s in trovate.values()]
        if max(ys) - min(ys) < 5:  # le tre etichette devono stare sulla stessa riga
            return Colonne(
                trovate["modello"].x0,
                trovate["descrizione"].x0,
                trovate["prezzo"].x0,
                True,
                max(s.y1 for s in trovate.values()),
            )
    d = regole["colonne_predefinite"]
    return Colonne(d["modello_x"], d["descrizione_x"], d["prezzo_x"], False)


def filtra_area_utile(spans: list[Span], regole: dict, colonne: Colonne) -> list[Span]:
    """Toglie intestazione ripetuta, piè di pagina e numeri di pagina."""
    y_min = regole["area"]["y_min"]
    if colonne.y_intestazione is not None:
        # sotto la seconda riga dell'intestazione ("Pubblico" sta 10pt sotto "Prezzo al")
        y_min = colonne.y_intestazione + 12
    y_max = regole["area"]["y_max"]
    piede = [re.compile(p) for p in regole["piede_pagina"]]
    testata = [re.compile(p) for p in regole["testi_intestazione"]]
    tenuti = []
    for s in spans:
        if s.y0 < y_min or s.y0 > y_max:
            continue
        if any(p.search(s.testo) for p in piede):
            continue
        if any(p.search(s.testo) for p in testata) and s.y0 < y_min + 15:
            continue
        tenuti.append(s)
    return tenuti


def colonna_di(span: Span, colonne: Colonne, regole: dict) -> str:
    tol = regole["tolleranza_colonna"]
    if span.size >= regole["soglia_titolo"] or span.x0 < colonne.modello_x - tol:
        return TITOLO
    if span.x0 < colonne.descrizione_x - tol:
        return MODELLO
    if span.x0 < colonne.prezzo_x - tol:
        return DESCRIZIONE
    return PREZZO


def raggruppa_righe(spans: list[Span], tolleranza: float) -> list[Riga]:
    """Raggruppa per coordinata verticale gli spans di una stessa colonna."""
    righe: list[Riga] = []
    for s in sorted(spans, key=lambda s: (s.y0, s.x0)):
        if righe and abs(s.y0 - righe[-1].spans[0].y0) <= tolleranza:
            righe[-1].spans.append(s)
        else:
            righe.append(Riga([s]))
    return righe


def tabella_pagina(spans: list[Span], regole: dict) -> tuple[Colonne, dict[str, list[Riga]]]:
    """Righe della pagina divise per colonna, dopo aver tolto testata e piede."""
    colonne = rileva_colonne(spans, regole)
    utili = filtra_area_utile(spans, regole, colonne)
    per_colonna: dict[str, list[Span]] = {MODELLO: [], DESCRIZIONE: [], PREZZO: [], TITOLO: []}
    for s in utili:
        per_colonna[colonna_di(s, colonne, regole)].append(s)
    tol = regole["tolleranza_riga"]
    return colonne, {k: raggruppa_righe(v, tol) for k, v in per_colonna.items()}
