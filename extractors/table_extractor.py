"""Geometria della pagina, senza coordinate fisse: righe visive, statistiche del documento,
testate e piedi ripetuti, riga d'intestazione e colonne fisiche.

Ogni soglia e' un multiplo di una statistica del documento (corpo mediano, interlinea mediana) o
una frazione della pagina: lo stesso codice legge un listino A4 in corpo 7 e uno in A3 in corpo 11.
"""
import itertools
import re
import statistics
from collections import Counter
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
    # etichette che nessun nome riconosce (marca, titolo della tabella): diventano la categoria
    variabili: list[str] = field(default_factory=list)


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
    parole = set(t.split())
    for i, col in enumerate(profilo["colonne"]):
        for etichetta in col.get("intestazioni", []):
            e = normalizza_testo(etichetta)
            # anche un'etichetta che contiene tutte le parole di quella dichiarata: nello stesso
            # catalogo Etabeta la colonna si chiama "Articolo" e, in alcune sezioni, "Codice/Articolo"
            if e and (t == e or t.startswith(e + " ") or (len(e) > 3 and set(e.split()) <= parole)):
                return i
    campo, _ = campo_da_intestazione(testo, profilo.get("sinonimi"))
    if campo is None:
        return None
    for i, col in enumerate(profilo["colonne"]):
        contenuti = col.get("contiene", []) if col["campo"] == "identificativo" else [col["campo"]]
        if campo in contenuti:
            return i
    return None


def _per_posizione(variabili: list[Span], riconosciute: dict[int, Span], profilo: dict,
                   larghezza: float | None) -> dict[int, Span]:
    """Etichette non riconosciute per nome, abbinate alle colonne del profilo per posizione.

    Nel catalogo Etabeta l'intestazione e' «MARCA | Articolo | titolo della tabella | Listino»: marca e
    titolo cambiano a ogni tabella, quindi nessun nome li riconosce. Un'etichetta che sta fra due
    riconosciute puo' essere solo una colonna del profilo che sta fra le due, la piu' vicina alla sua
    posizione salvata. Serve un profilo con le posizioni: col profilo generico della pre-analisi
    l'abbinamento non si fa, e il campo lo propone il contenuto.
    """
    cols = profilo["colonne"]
    if larghezza is None or not any(c.get("x_relativo") is not None for c in cols):
        return {}
    ordinate = sorted(riconosciute.items(), key=lambda kv: kv[1].x0)
    assegnate: dict[int, Span] = {}
    for u in sorted(variabili, key=lambda s: s.x0):
        sinistra = max((i for i, s in ordinate if s.x0 < u.x0), default=-1)
        destra = min((i for i, s in ordinate if s.x0 > u.x0), default=len(cols))
        candidate = [i for i in range(sinistra + 1, destra)
                     if i not in riconosciute and i not in assegnate and cols[i].get("x_relativo") is not None]
        if not candidate:
            continue

        def distanza(i, u=u):
            x = cols[i]["x_relativo"] * larghezza
            return 0.0 if u.x0 - 6 <= x <= u.x1 + 6 else min(abs(x - u.x0), abs(x - u.x1))

        migliore = min(candidate, key=distanza)
        if distanza(migliore) <= 0.25 * larghezza:
            assegnate[migliore] = u
    return assegnate


def rileva_intestazioni(righe_pagina: list[Riga], profilo: dict, metr: Metriche,
                        larghezza: float | None = None) -> list[Intestazione]:
    """Tutte le righe d'intestazione della pagina: quelle con almeno due etichette che riconoscono colonne
    diverse del profilo. Un catalogo ne ha una per tabella, piu' tabelle per pagina."""
    trovate: list[Intestazione] = []
    n = 0
    while n < len(righe_pagina):
        intest, n = _intestazione_da(righe_pagina, n, profilo, metr, larghezza)
        if intest is not None:
            trovate.append(intest)
    return trovate


def rileva_intestazione(righe_pagina: list[Riga], profilo: dict, metr: Metriche,
                        larghezza: float | None = None) -> Intestazione | None:
    """La prima riga d'intestazione della pagina, se c'e'."""
    trovate = rileva_intestazioni(righe_pagina, profilo, metr, larghezza)
    return trovate[0] if trovate else None


def _intestazione_da(righe_pagina, n, profilo, metr, larghezza):
    """Intestazione che comincia alla riga n (o None) e indice della riga da cui riprendere la ricerca."""
    riga = righe_pagina[n]
    riconosciute: dict[int, Span] = {}
    variabili: list[Span] = []
    for s in sorted(riga.spans, key=lambda s: s.x0):
        i = _indice_colonna(s.testo, profilo)
        if i is not None and i not in riconosciute:
            riconosciute[i] = s
        elif i is None:
            variabili.append(s)
    if len(riconosciute) < 2:
        return None, n + 1
    per_posizione = _per_posizione(variabili, riconosciute, profilo, larghezza)
    colonne = [ColonnaFisica(s.x0, i, s.testo, s.x1) for i, s in (*riconosciute.items(), *per_posizione.items())]
    # le etichette non riconosciute della stessa riga sono colonne vere, da non far sconfinare
    for s in variabili:
        if s not in per_posizione.values() and all(abs(s.x0 - c.x) > 1 for c in colonne):
            colonne.append(ColonnaFisica(s.x0, None, s.testo, s.x1))
    colonne.sort(key=lambda c: c.x)
    # categoria: le etichette che non sono il nome di un campo (marca, titolo della tabella), anche se il
    # profilo le ha salvate come intestazione della loro colonna; tranne il nome di una colonna di testo
    # («Colore»), che e' un'etichetta fissa come le altre
    di_testo = {id(s) for i, s in riconosciute.items() if profilo["colonne"][i]["campo"] == "testo_generico"}
    categoria = [s.testo for s in sorted(riga.spans, key=lambda s: s.x0)
                 if id(s) not in di_testo and campo_da_intestazione(s.testo, profilo.get("sinonimi"))[0] is None]
    intest = Intestazione(riga.y0, riga.y1, colonne, categoria)
    corpo_etichette = statistics.median(s.size for s in riga.spans)
    # seconda riga di un'etichetta ("Prezzo al" / "Pubblico"): subito sotto, allineata a
    # un'etichetta e dello stesso corpo. Il corpo conta: un titolo di sezione allineato alla
    # prima colonna veniva scambiato per il seguito dell'intestazione (trovato col PDF generico)
    n += 1
    while n < len(righe_pagina):
        seguente = righe_pagina[n]
        vicina = seguente.y0 - intest.y1 <= corpo_etichette
        allineata = all(any(abs(s.x0 - c.x) <= 2 for c in colonne) for s in seguente.spans)
        stesso_corpo = all(abs(s.size - corpo_etichette) <= 0.15 * corpo_etichette for s in seguente.spans)
        if not (vicina and allineata and stesso_corpo):
            break
        intest.y1 = seguente.y1
        n += 1
    return intest, n


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


def allinea_al_contenuto(colonne: list[ColonnaFisica], spans: list[Span], tolleranza: float = 6.0,
                         minimo: int = 2, profilo: dict | None = None,
                         larghezza: float | None = None) -> list[ColonnaFisica]:
    """Inizio delle colonne d'intestazione spostato sul testo della pagina, quando l'etichetta e' centrata.

    Il titolo di una tabella Etabeta («MODULI INPUT PER MATRICI VIDEO X9») e' centrato e comincia a
    x≈290, la sua descrizione a x=238: con l'inizio dell'etichetta, una riga corta come «IR» finiva
    nella colonna dei codici e diventava un articolo. Si calcola su ogni pagina, perche' nello stesso
    catalogo le sezioni hanno colonne in posizioni diverse (Articolo a x=167 o a x=136). L'inizio si
    sposta solo all'indietro e mai oltre la fine dell'etichetta precedente; con etichette allineate al
    testo (JBL) non si sposta affatto.
    """
    per: dict[int, list[Span]] = {}
    for s in spans:
        n = assegna_colonna(s, colonne, tolleranza)
        if n is not None:
            per.setdefault(n, []).append(s)
    nuove = []
    for n, c in enumerate(colonne):
        membri = per.get(n, [])
        limite = colonne[n - 1].x1 if n > 0 and colonne[n - 1].x1 is not None else 0.0
        x = c.x
        moda, quanti = Counter(round(s.x0) for s in membri).most_common(1)[0] if membri else (None, 0)
        if c.x1 is not None and moda is not None and quanti >= minimo and limite < moda < c.x - 1:
            x = float(moda)
        elif profilo is not None and larghezza and c.indice is not None:
            # troppo poco testo sulla pagina per dirlo (una tabella che comincia in fondo): vale la
            # posizione salvata nel profilo, se cade fra l'etichetta precedente e questa
            x_profilo = profilo["colonne"][c.indice].get("x_relativo")
            if x_profilo is not None and limite < x_profilo * larghezza < c.x - 1:
                x = x_profilo * larghezza
        nuove.append(ColonnaFisica(x, c.indice, c.etichetta, c.x1))
    return nuove


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
