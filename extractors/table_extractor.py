"""Geometria della pagina, senza coordinate fisse: righe visive, statistiche del documento,
testate e piedi ripetuti, riga d'intestazione e colonne fisiche.

Ogni soglia e' un multiplo di una statistica del documento (corpo mediano, interlinea mediana) o
una frazione della pagina: lo stesso codice legge un listino A4 in corpo 7 e uno in A3 in corpo 11.
"""
import itertools
import re
import statistics
from dataclasses import dataclass, field

from processors.models import Span
from processors.profilo import campo_da_intestazione, normalizza_testo

TITOLO, ESTERNO = "titolo", "esterno"
# Una riga e' testata o piede se compare alla stessa altezza su almeno questa quota di pagine,
# e solo nelle fasce alta e bassa della pagina: il corpo di un listino non si ripete identico.
QUOTA_RIPETIZIONE = 0.5
FASCIA_TESTATA, FASCIA_PIEDE = 0.25, 0.80
_CIFRE = re.compile(r"\d+")


@dataclass
class Riga:
    """Spans allineati sulla stessa linea di base (di una colonna, o dell'intera pagina)."""

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


@dataclass(frozen=True)
class Metriche:
    corpo: float  # corpo mediano del testo
    interlinea: float  # distanza mediana fra righe consecutive dello stesso blocco

    @property
    def tolleranza_riga(self) -> float:
        return max(1.0, 0.4 * self.corpo)


@dataclass
class ColonnaFisica:
    x: float  # inizio della colonna, in punti
    indice: int | None  # posizione nel profilo, None = colonna non mappata (fa solo da confine)
    etichetta: str  # testo dell'intestazione, o descrizione della posizione
    x1: float | None = None  # fine dell'etichetta d'intestazione, se la colonna viene da li'


@dataclass
class Intestazione:
    y0: float
    y1: float  # fine dell'intestazione, comprese le etichette su due righe ("Prezzo al / Pubblico")
    colonne: list[ColonnaFisica] = field(default_factory=list)


def raggruppa_righe(spans: list[Span], tolleranza: float) -> list[Riga]:
    righe: list[Riga] = []
    for s in sorted(spans, key=lambda s: (s.y0, s.x0)):
        if righe and abs(s.y0 - righe[-1].spans[0].y0) <= tolleranza:
            righe[-1].spans.append(s)
        else:
            righe.append(Riga([s]))
    return righe


def metriche(pagine: list[list[Span]]) -> Metriche:
    """Corpo e interlinea mediani dell'intero documento (o del campione di pagine)."""
    corpi = [s.size for spans in pagine for s in spans if s.size > 0]
    corpo = statistics.median(corpi) if corpi else 10.0
    distanze = []
    for spans in pagine:
        # righe che iniziano alla stessa x, cioe' nella stessa colonna: fra righe qualsiasi della
        # pagina la distanza mescola colonne diverse (misurato: 23,7 pt su una tabella a 11 pt)
        per_x: dict[int, set[float]] = {}
        for s in spans:
            per_x.setdefault(round(s.x0 / corpo), set()).add(round(s.y0, 1))
        for ys in per_x.values():
            ys = sorted(ys)
            # solo le distanze "da riga a riga": quelle fra paragrafi o articoli sono piu' grandi
            distanze += [b - a for a, b in itertools.pairwise(ys) if 0.8 * corpo <= b - a <= 3 * corpo]
    interlinea = statistics.median(distanze) if distanze else 1.5 * corpo
    return Metriche(corpo, interlinea)


def _firma(riga: Riga, altezza: float) -> tuple[int, str] | None:
    rel = riga.y0 / altezza if altezza else 0.5
    if FASCIA_TESTATA < rel < FASCIA_PIEDE:
        return None
    return round(riga.y0 / 3), _CIFRE.sub("#", normalizza_testo(riga.testo))


def firme_ripetute(pagine: list[tuple[list[Span], float]], tolleranza: float) -> set[tuple[int, str]]:
    """Righe di testata e piede: stesso testo (cifre a parte) alla stessa altezza su molte pagine."""
    if len(pagine) < 2:
        return set()
    conteggio: dict[tuple[int, str], int] = {}
    for spans, altezza in pagine:
        viste = {f for r in raggruppa_righe(spans, tolleranza) if (f := _firma(r, altezza))}
        for f in viste:
            conteggio[f] = conteggio.get(f, 0) + 1
    soglia = max(2, round(QUOTA_RIPETIZIONE * len(pagine)))
    ripetute = {f for f, n in conteggio.items() if n >= soglia}
    # le altezze sono arrotondate a 3 pt: una riga a cavallo fra due fasce vale per entrambe
    return ripetute | {(y + d, t) for y, t in ripetute for d in (-1, 1)}


def e_ripetuta(riga: Riga, altezza: float, firme: set[tuple[int, str]]) -> bool:
    f = _firma(riga, altezza)
    return f is not None and f in firme


def _indice_colonna(testo: str, profilo: dict) -> int | None:
    """Colonna del profilo riconosciuta da un'etichetta: prima le intestazioni dichiarate, poi i sinonimi."""
    t = normalizza_testo(testo)
    for i, col in enumerate(profilo["colonne"]):
        for etichetta in col.get("intestazioni", []):
            e = normalizza_testo(etichetta)
            if e and (t == e or t.startswith(e + " ")):
                return i
    campo, _ = campo_da_intestazione(testo, profilo.get("sinonimi"))
    if campo is None:
        return None
    for i, col in enumerate(profilo["colonne"]):
        contenuti = col.get("contiene", []) if col["campo"] == "identificativo" else [col["campo"]]
        if campo in contenuti:
            return i
    return None


def rileva_intestazione(righe_pagina: list[Riga], profilo: dict, metr: Metriche) -> Intestazione | None:
    """La prima riga in cui almeno due etichette riconoscono colonne diverse del profilo."""
    for n, riga in enumerate(righe_pagina):
        riconosciute: dict[int, Span] = {}
        for s in sorted(riga.spans, key=lambda s: s.x0):
            i = _indice_colonna(s.testo, profilo)
            if i is not None and i not in riconosciute:
                riconosciute[i] = s
        if len(riconosciute) < 2:
            continue
        colonne = [ColonnaFisica(s.x0, i, s.testo, s.x1) for i, s in riconosciute.items()]
        # le etichette non riconosciute della stessa riga sono colonne vere, da non far sconfinare
        for s in riga.spans:
            if all(abs(s.x0 - c.x) > 1 for c in colonne) and _indice_colonna(s.testo, profilo) is None:
                colonne.append(ColonnaFisica(s.x0, None, s.testo, s.x1))
        colonne.sort(key=lambda c: c.x)
        y1 = riga.y1
        corpo_etichette = statistics.median(s.size for s in riga.spans)
        # seconda riga di un'etichetta ("Prezzo al" / "Pubblico"): subito sotto, allineata a
        # un'etichetta e dello stesso corpo. Il corpo conta: un titolo di sezione allineato alla
        # prima colonna veniva scambiato per il seguito dell'intestazione (trovato col PDF generico)
        for seguente in righe_pagina[n + 1:]:
            vicina = seguente.y0 - y1 <= corpo_etichette
            allineata = all(any(abs(s.x0 - c.x) <= 2 for c in colonne) for s in seguente.spans)
            stesso_corpo = all(abs(s.size - corpo_etichette) <= 0.15 * corpo_etichette for s in seguente.spans)
            if not (vicina and allineata and stesso_corpo):
                break
            y1 = seguente.y1
        return Intestazione(riga.y0, y1, colonne)
    return None


def risolvi_colonne(intestazione: Intestazione | None, profilo: dict, larghezza: float) -> list[ColonnaFisica]:
    """Colonne della pagina: dall'intestazione, completate con le posizioni relative del profilo."""
    colonne = list(intestazione.colonne) if intestazione else []
    presenti = {c.indice for c in colonne if c.indice is not None}
    for i, col in enumerate(profilo["colonne"]):
        if i not in presenti and col.get("x_relativo") is not None:
            x = col["x_relativo"] * larghezza
            fine = col.get("x_fine_relativo")
            etichetta = f"{col['campo'].capitalize()}, x≈{x:.0f}"  # nelle note: quale colonna ha fallito
            colonne.append(ColonnaFisica(x, i, etichetta, fine * larghezza if fine is not None else None))
    return sorted(colonne, key=lambda c: c.x)


def assegna_colonna(span: Span, colonne: list[ColonnaFisica], tolleranza: float) -> int | None:
    """Indice della colonna di uno span; None se sta a sinistra della prima colonna.

    Prima conta la sovrapposizione con le etichette d'intestazione: e' l'unico modo di leggere bene
    una colonna allineata a destra, dove "1,249.50" comincia prima dell'etichetta "Price" (trovato
    col PDF generico). Senza sovrapposizione vale la colonna che comincia piu' vicino a sinistra.
    """
    sovrapposizioni = [
        (min(span.x1, c.x1) - max(span.x0, c.x), n) for n, c in enumerate(colonne) if c.x1 is not None
    ]
    migliore = max(sovrapposizioni, default=(0, None))
    if migliore[0] > 0:
        return migliore[1]
    candidate = [n for n, c in enumerate(colonne) if c.x - tolleranza <= span.x0]
    return candidate[-1] if candidate else None


def colonna_di(span: Span, colonne: list[ColonnaFisica], profilo: dict, metr: Metriche) -> int | str:
    """Indice (nella lista `colonne`) della colonna dello span, oppure TITOLO / ESTERNO."""
    sp = profilo["spaziatura"]
    if span.size >= sp["fattore_titolo"] * metr.corpo:
        return TITOLO
    n = assegna_colonna(span, colonne, sp["tolleranza_colonna_pt"])
    if n is None:
        return TITOLO if colonne else ESTERNO  # a sinistra della prima colonna: titolo di sezione
    return n


def linee_divisorie(page, larghezza: float) -> list[float]:
    """Altezze delle righe orizzontali disegnate che attraversano almeno meta' pagina."""
    ys = []
    for disegno in page.get_drawings():
        r = disegno.get("rect")
        if r is not None and r.width >= 0.4 * larghezza and r.height <= 2:
            ys.append((r.y0 + r.y1) / 2)
    return sorted(ys)
