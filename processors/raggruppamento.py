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


def nella_fascia(riga: Riga, fascia: tuple[float, float], tolleranza: float) -> bool:
    inizio, fine = fascia
    return inizio - tolleranza <= riga.y0 < fine - tolleranza
