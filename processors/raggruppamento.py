"""Raggruppamento delle righe in articoli, a partire dalla colonna d'ancoraggio.

Funzioni pure su `Riga`: non sanno nulla di PDF, profili o campi. Il chiamante dice quali righe
della colonna d'ancoraggio sono ancore (un codice valido, un EAN, un prezzo...) e qual e' lo
stacco che separa due articoli; qui si decide dove comincia e dove finisce ciascun articolo.
"""
import itertools
from collections.abc import Callable
from dataclasses import dataclass

from extractors.table_extractor import Riga


@dataclass
class Gruppo:
    """Un articolo nella colonna d'ancoraggio: le sue righe e quella che l'ha individuato."""

    righe: list[Riga]
    ancora: Riga

    @property
    def inizio(self) -> float:
        return min(r.y0 for r in self.righe)


def corse(righe: list[Riga], stacco: float, tagli: list[float] = ()) -> list[list[Riga]]:
    """Righe consecutive senza un distacco maggiore di `stacco` e senza un taglio (titolo, linea) in mezzo."""
    risultato: list[list[Riga]] = []
    for r in sorted(righe, key=lambda r: r.y0):
        if risultato:
            prec = risultato[-1][-1]
            tagliata = any(prec.y0 < t < r.y0 for t in tagli)
            if r.y0 - prec.y0 <= stacco and not tagliata:
                risultato[-1].append(r)
                continue
        risultato.append([r])
    return risultato


def gruppi(righe: list[Riga], e_ancora: Callable[[Riga], bool], stacco: float, tagli: list[float] = ()) -> list[Gruppo]:
    """Articoli individuati nella colonna d'ancoraggio.

    Una corsa con una sola ancora e' un articolo intero (nome su piu' righe, codice, EAN). Una corsa
    con piu' ancore contiene piu' articoli: fra due ancore consecutive si taglia nel distacco piu'
    ampio, a parita' il piu' vicino all'ancora successiva. In una tabella a una riga per articolo
    e' il taglio subito prima dell'ancora; nel listino JBL, dove fra EAN di un articolo e nome del
    successivo ci sono 14,5 pt contro 10,5 dentro l'articolo, cade proprio li' (misurato: con un
    semplice stacco fisso 66 articoli su 673 si fondevano a coppie).
    Le corse senza ancore non formano articoli: sono testo che il chiamante attribuisce per posizione.
    """
    risultato: list[Gruppo] = []
    for corsa in corse(righe, stacco, tagli):
        indici = [i for i, r in enumerate(corsa) if e_ancora(r)]
        if not indici:
            continue
        inizi = [0]
        for a, b in itertools.pairwise(indici):
            # taglio nel distacco piu' ampio fra la riga a e la riga b (a parita', il piu' tardo)
            distacchi = [(corsa[k + 1].y0 - corsa[k].y0, k + 1) for k in range(a, b)]
            inizi.append(max(distacchi)[1])
        for n, i in enumerate(indici):
            fine = inizi[n + 1] if n + 1 < len(inizi) else len(corsa)
            risultato.append(Gruppo(corsa[inizi[n]:fine], corsa[i]))
    return risultato


def celle(righe: list[Riga], separatori: list[float], tagli: list[float]) -> list[Gruppo] | None:
    """Articoli come celle di una griglia: le righe della colonna d'ancoraggio fra due linee divisorie.

    Vale solo se le linee sono fitte, almeno una ogni due righe di quella colonna: allora la griglia
    dice da sola dove finisce un articolo, e non serve che il modello abbia l'aspetto di un codice
    (catalogo Etabeta, sezione ARX: «IsoLater», «Super Splitter Duo»). Con poche linee (JBL: le
    sottolineature dell'intestazione) restituisce None e vale il raggruppamento per ancore.
    """
    if not righe or len(separatori) < max(3, 0.5 * len(righe)):
        return None
    bordi = sorted(set(separatori) | set(tagli))
    gruppi_celle: dict[int, list[Riga]] = {}
    for r in sorted(righe, key=lambda r: r.y0):
        cella = sum(1 for b in bordi if b <= r.y0)
        gruppi_celle.setdefault(cella, []).append(r)
    risultato = []
    for cella, v in sorted(gruppi_celle.items()):
        g = Gruppo(v, v[0])
        # la cella intera, perche' anche le altre colonne si dividano sulla stessa griglia
        g.cella = (bordi[cella - 1] if cella > 0 else float("-inf"), bordi[cella] if cella < len(bordi) else float("inf"))
        risultato.append(g)
    return risultato


def fasce_con_seguito(celle_articoli: list[tuple[float, float]], bordi: list[float],
                      fermi: list[float]) -> list[tuple[float, float]]:
    """Fasce delle colonne diverse dall'ancora in una griglia: la cella dell'articolo piu' le celle che
    la seguono senza testo nella colonna dell'ancora.

    In una scheda prodotto (Etabeta, pagine 140 e 225) una linea separa la prima riga (codice, titolo,
    prezzo) dalle caratteristiche, che restano in una cella senza codice: andavano perse, 2.900 righe sul
    catalogo. Il seguito si ferma alla cella dell'articolo successivo, al primo fermo (titolo, intestazione,
    cella con un testo che non e' un articolo) e all'ultima linea: sotto l'ultima linea della pagina il
    testo non e' racchiuso in una cella, e di solito e' promozionale.
    """
    out = []
    for n, (inizio, fine) in enumerate(celle_articoli):
        limite = celle_articoli[n + 1][0] if n + 1 < len(celle_articoli) else float("inf")
        limite = min([limite] + [f for f in fermi if f >= fine])
        chiusi = [b for b in bordi if fine <= b <= limite]
        out.append((inizio, max(chiusi, default=fine)))
    return out


def estensioni(inizi: list[float], tagli: list[float]) -> list[tuple[float, float]]:
    """Fascia verticale di ogni articolo: dal suo inizio al successivo, o al primo taglio che incontra."""
    out = []
    for n, inizio in enumerate(inizi):
        fine = inizi[n + 1] if n + 1 < len(inizi) else float("inf")
        dopo = [t for t in tagli if t > inizio]
        if dopo:
            fine = min(fine, min(dopo))
        out.append((inizio, fine))
    return out


def fasce(ys: list[float], inizi: list[float], tagli: list[float], tolleranza: float,
          finestra: float, contiguo: float) -> list[tuple[float, float]]:
    """Fasce verticali degli articoli per una colonna che non e' quella d'ancoraggio.

    Il confine fra due articoli non e' l'inizio del secondo, ma il distacco piu' ampio fra le righe
    di questa colonna, cercato fra il punto medio delle due ancore e poco dopo la seconda. Nel
    catalogo Etabeta il codice sta a meta' altezza di una descrizione di 2-4 righe: le prime righe
    cominciano fino a 15 pt sopra il codice e, col confine all'inizio, finivano nell'articolo
    precedente. Dove la descrizione comincia insieme all'articolo (JBL) il distacco piu' ampio dopo il
    punto medio e' proprio quello prima del secondo articolo: il risultato non cambia.
    Il primo articolo risale finche' le righe sono attaccate (distacco fino a `contiguo`): nel JBL la
    prosecuzione dalla pagina precedente sta a 14,5 pt dal primo articolo e resta fuori.
    """
    if not inizi:
        return []
    ys = sorted(ys)
    inizio = inizi[0] - tolleranza
    proprie = [y for y in ys if y >= inizio]
    attuale = proprie[0] if proprie else inizi[0]
    for y in reversed([y for y in ys if y < inizi[0] - tolleranza]):
        if attuale - y > contiguo or any(y < t < attuale for t in tagli):
            break
        inizio, attuale = y, y
    # fine del blocco di righe attaccate che comincia da ogni riga
    fine_blocco = list(ys)
    for i in range(len(ys) - 2, -1, -1):
        if ys[i + 1] - ys[i] <= contiguo:
            fine_blocco[i] = fine_blocco[i + 1]
    out = []
    for a, b in itertools.pairwise(inizi):
        nel_mezzo = [t for t in tagli if a < t < b]
        if nel_mezzo:
            out.append((inizio, min(nel_mezzo)))
            inizio = max(nel_mezzo)
            continue
        meta = (a + b) / 2
        # un taglio vale solo se il blocco sotto di esso arriva all'ancora successiva: altrimenti
        # quelle righe sono la coda del primo articolo, non la testa del secondo (JBL: un articolo
        # senza descrizione si prendeva la fine di quella del precedente)
        candidati = [
            (ys[j + 1] - ys[j], ys[j + 1])
            for j in range(len(ys) - 1)
            if meta <= ys[j + 1] < b + finestra and ys[j] >= a - tolleranza and fine_blocco[j + 1] >= b - tolleranza
        ]
        confine = max(candidati)[1] if candidati else b - tolleranza
        out.append((inizio, confine))
        inizio = confine
    dopo = [t for t in tagli if t > inizi[-1]]
    out.append((inizio, min(dopo) if dopo else float("inf")))
    return out


def e_centrata(ys: list[float], inizi: list[float], tagli: list[float], tolleranza: float,
               contiguo: float) -> bool:
    """La colonna ha il testo centrato sull'ancora? Vero se almeno un quinto degli articoli ha righe
    attaccate sopra il proprio inizio e piu' vicine a lui che all'articolo precedente.

    Nel JBL la descrizione comincia insieme all'articolo; in una tabella a righe equidistanti la riga
    sopra ogni codice e' quella dell'articolo prima, a meta' strada non ci arriva: nessuno dei due
    casi conta. Nel catalogo Etabeta il codice sta a meta' della cella e la prima riga gli sta 5 pt sopra.
    `inizi` sono gli inizi degli articoli, non le righe delle ancore: nel JBL il codice e' la seconda riga.
    """
    if len(inizi) < 2:
        return False
    sopra = 0
    for k, s in enumerate(inizi):
        meta = (inizi[k - 1] + s) / 2 if k > 0 else s - contiguo
        if any(max(s - contiguo, meta) < y < s - tolleranza and not any(y < t < s for t in tagli) for y in ys):
            sopra += 1
    return sopra >= max(2, 0.2 * len(inizi))


def fasce_centrate(ys: list[float], ancore: list[float], tagli: list[float], tolleranza: float,
                   contiguo: float) -> list[tuple[float, float]]:
    """Fasce per una colonna centrata sull'ancora: ogni cella e' simmetrica rispetto al suo codice.

    Nel catalogo Etabeta le righe sono equidistanti (10-11 pt) anche fra un articolo e l'altro, quindi
    non c'e' un distacco da cercare; il codice pero' sta a meta' della sua cella. Nota la cima della
    cella (la prima riga non ancora presa), la fine e' 2·ancora − cima; la cella dopo comincia li'.
    """
    ys = sorted(ys)
    out = []
    i = 0
    for k, s in enumerate(ancore):
        prossima = ancore[k + 1] if k + 1 < len(ancore) else float("inf")
        limite_taglio = min([t for t in tagli if t > s], default=float("inf"))
        if k == 0:  # la prima cella risale finche' le righe sono attaccate
            proprie = [y for y in ys if y >= s - tolleranza]
            attuale = proprie[0] if proprie else s
            for y in reversed([y for y in ys if y < s - tolleranza]):
                if attuale - y > contiguo or any(y < t < attuale for t in tagli):
                    break
                attuale = y
            i = next((n for n, y in enumerate(ys) if y >= attuale), len(ys))
        cima = ys[i] if i < len(ys) and ys[i] <= s + tolleranza else s
        fine = min(2 * s - cima + tolleranza, prossima - tolleranza, limite_taglio)
        fine = max(fine, s + tolleranza)  # una cella contiene almeno la riga della sua ancora
        out.append((min(cima, s) - 0.01, fine))
        while i < len(ys) and ys[i] < fine:
            i += 1
    return out


# larghezza massima di un bollino, in corpi del testo: «NEW» in corpo 12 su un catalogo in corpo 9 e' largo 3,1
LARGHEZZA_BOLLINO = 4
# corpo massimo di un bollino, in corpi del testo: «NEW» e' in corpo 12 su 9 (1,33); i loghi di serie
# accanto al testo introduttivo («HS SERIE PASSIVE Speaker») sono in corpo 16-18 (da 1,78)
CORPO_BOLLINO = 1.5
# scarto ammesso fra il corpo di una riga e il corpo del testo del documento
SCARTO_CORPO = 0.15


def _distanza(a: Riga, b: Riga) -> float:
    """Distanza verticale fra due righe: zero se si sovrappongono."""
    return max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))


def a_fianco_dei_dati(titolo: Riga, righe_dati: list[Riga], righe_ancora: list[Riga], intestazioni: list[float],
                      corpo: float, passo: float, tolleranza: float) -> bool:
    """Un titolo che e' un bollino accanto a un articolo, non un titolo di sezione.

    Il «NEW» del catalogo Etabeta (corpo 12) sta di fianco alla descrizione di un articolo, a sinistra del
    codice o nella sua colonna: diventava la categoria degli articoli seguenti (52 articoli) e tagliava
    l'articolo in due. Un titolo di sezione occupa invece una fascia sua. Il bollino e' una parola sola,
    stretta e appena piu' grande del testo; sta alla stessa altezza di righe di dati nel corpo del testo (sovrapposte in tutto per piu' di
    `tolleranza`: a pagina 17 sta a cavallo di due righe) e dentro un articolo, cioe' a meno di un `passo` da
    una riga della colonna d'ancoraggio o sotto una di esse senza un'intestazione in mezzo (nelle schede il
    codice e' in cima e il bollino piu' in basso). Senza le ultime due condizioni passavano per bollini
    «Vari», seconda riga del titolo «Accessori / Vari» accanto a testo promozionale in corpo 11, e i loghi di
    serie («ALA», «VS») accanto al testo introduttivo prima della prima tabella della pagina: l'introduzione
    finiva nell'articolo della pagina precedente; senza il limite sul corpo, quelli fra due tabelle («HS»).
    """
    if (len(titolo.testo.split()) != 1 or titolo.x1 - titolo.x0 > LARGHEZZA_BOLLINO * corpo
            or titolo.size > CORPO_BOLLINO * corpo):
        return False
    sovrapposto = sum(max(0.0, min(titolo.y1, r.y1) - max(titolo.y0, r.y0))
                      for r in righe_dati if abs(r.size - corpo) <= SCARTO_CORPO * corpo)
    if sovrapposto <= tolleranza:
        return False
    return any(_distanza(titolo, r) <= passo
               or (r.y0 < titolo.y0 and not any(r.y0 < y < titolo.y0 for y in intestazioni)) for r in righe_ancora)


def nella_fascia(riga: Riga, fascia: tuple[float, float], tolleranza: float) -> bool:
    inizio, fine = fascia
    return inizio - tolleranza <= riga.y0 < fine - tolleranza
