"""Ricostruzione degli articoli dalle righe della tabella.

Regola del listino JBL/Exhibo, misurata sul campione di gennaio 2026 (673 articoli su 121 pagine):
la colonna Modello di ogni articolo e' un blocco di righe ravvicinate (interlinea 10,5 pt) fatto di
  1. il nome del modello, su una o piu' righe;
  2. il codice d'ordine tra parentesi, sempre presente e univoco;
  3. l'EAN, facoltativo (a volte al suo posto c'e' un altro identificativo).
Il prezzo sta sulla stessa linea della prima riga del blocco; la descrizione occupa la sua colonna
dall'inizio del blocco fino all'inizio dell'articolo successivo (o del titolo di categoria).

L'articolo si individua quindi dalla colonna Modello e non dal prezzo: cosi' un prezzo mancante
diventa un'anomalia segnalata, invece di fondere due articoli in uno.
"""
import re

from extractors.table_extractor import DESCRIZIONE, MODELLO, PREZZO, TITOLO, Riga, tabella_pagina
from processors.models import Articolo, Span
from processors.price_parser import parse_prezzo

_SPAZI = re.compile(r"\s+")


def unisci_righe(testi: list[str]) -> str:
    """Unisce righe spezzate senza incollare parole separate.

    Una riga che termina con un trattino attaccato a una parola ("water-") prosegue nella
    successiva senza spazio ("water-resistant"); un trattino isolato (" -") resta un separatore.
    """
    risultato = ""
    for t in testi:
        t = _SPAZI.sub(" ", t).strip()
        if not t:
            continue
        if not risultato:
            risultato = t
        elif risultato.endswith("-") and len(risultato) > 1 and not risultato[-2].isspace():
            risultato += t
        else:
            risultato += " " + t
    return risultato


def _nel_tratto(riga: Riga, inizio: float, fine: float, tol: float) -> bool:
    return inizio - tol <= riga.y0 < fine - tol


def _bbox(righe: list[Riga]) -> tuple[float, float, float, float]:
    return (
        min(r.x0 for r in righe),
        min(r.y0 for r in righe),
        max(r.x1 for r in righe),
        max(r.y1 for r in righe),
    )


class ParserListino:
    """Parser con stato: ricorda l'ultimo articolo per le descrizioni che proseguono a pagina nuova."""

    def __init__(self, regole: dict):
        self.regole = regole
        self.re_codice = re.compile(regole["regex_codice"])
        self.categoria = ""
        self.ultimo: Articolo | None = None
        self.avvisi: list[str] = []

    def elabora_pagina(self, spans: list[Span], pagina: int) -> list[Articolo]:
        _, righe = tabella_pagina(spans, self.regole)
        tol = self.regole["tolleranza_riga"]
        titoli = righe[TITOLO]
        blocchi = self._blocchi_modello(righe[MODELLO], titoli)
        articoli: list[Articolo] = []

        inizio_primo = blocchi[0][0].y0 if blocchi else float("inf")
        self._continuazione(righe, titoli, inizio_primo, pagina, tol)

        for i, blocco in enumerate(blocchi):
            inizio = blocco[0].y0
            fine = blocchi[i + 1][0].y0 if i + 1 < len(blocchi) else float("inf")
            titoli_dopo = [t.y0 for t in titoli if t.y0 > inizio]
            if titoli_dopo:
                fine = min(fine, min(titoli_dopo))
            titoli_prima = [t for t in titoli if t.y0 < inizio]
            if titoli_prima:
                self.categoria = titoli_prima[-1].testo
            desc = [r for r in righe[DESCRIZIONE] if _nel_tratto(r, inizio, fine, tol)]
            prezzi = [r for r in righe[PREZZO] if _nel_tratto(r, inizio, fine, tol)]
            art = self._articolo(blocco, desc, prezzi, pagina)
            articoli.append(art)
            self.ultimo = art

        if not blocchi and titoli:
            self.categoria = titoli[-1].testo
        return articoli

    def _blocchi_modello(self, righe_modello: list[Riga], titoli: list[Riga]) -> list[list[Riga]]:
        distanza = self.regole["distanza_blocco"]
        blocchi: list[list[Riga]] = []
        for r in righe_modello:
            if blocchi:
                prec = blocchi[-1][-1]
                titolo_in_mezzo = any(prec.y0 < t.y0 < r.y0 for t in titoli)
                if r.y0 - prec.y0 <= distanza and not titolo_in_mezzo:
                    blocchi[-1].append(r)
                    continue
            blocchi.append([r])
        return blocchi

    def _continuazione(self, righe, titoli, inizio_primo: float, pagina: int, tol: float) -> None:
        """Testo in cima alla pagina, prima del primo articolo: e' il seguito dell'ultimo articolo."""
        desc = [r for r in righe[DESCRIZIONE] if r.y0 < inizio_primo - tol]
        prezzi = [r for r in righe[PREZZO] if r.y0 < inizio_primo - tol]
        if not desc and not prezzi:
            return
        primo = min(r.y0 for r in desc + prezzi)
        titolo_sopra = any(t.y0 < primo for t in titoli)
        if self.ultimo is None or titolo_sopra:
            testo = unisci_righe([r.testo for r in desc + prezzi])
            self.avvisi.append(f"Pagina {pagina}: testo non attribuito a nessun articolo: «{testo[:80]}»")
            return
        art = self.ultimo
        if desc:
            # la descrizione copiata dal nome del modello non e' una descrizione: la si sostituisce
            base = "" if art.descrizione_da_modello else art.descrizione
            art.descrizione = unisci_righe([base] + [r.testo for r in desc])
            art.descrizione_da_modello = False
        if prezzi:
            if art.prezzo is None and not art.prezzo_testo and len(prezzi) == 1:
                self._assegna_prezzo(art, prezzi)
            else:
                art.note_estrazione["prezzo"] = (
                    f"Altro prezzo trovato a pagina {pagina}: «{prezzi[0].testo}» — verificare"
                )

    def _articolo(self, blocco: list[Riga], desc: list[Riga], prezzi: list[Riga], pagina: int) -> Articolo:
        r = self.regole
        art = Articolo(pagina=pagina, categoria=self.categoria)
        testi = [x.testo for x in blocco]
        indice = next((i for i, t in enumerate(testi) if self.re_codice.match(_SPAZI.sub(" ", t).strip())), None)
        if indice is None:
            art.modello = unisci_righe(testi)
            art.note_estrazione["codice"] = "Codice tra parentesi non trovato"
        else:
            art.modello = unisci_righe(testi[:indice])
            codice = self.re_codice.match(_SPAZI.sub(" ", testi[indice]).strip()).group("codice").strip()
            art.codice = f"({codice})" if r.get("codice_con_parentesi", True) else codice
            sotto = [t.strip() for t in testi[indice + 1:]]
            if sotto:
                art.ean = sotto[0]
            if len(sotto) > 1:
                art.note_estrazione["ean"] = f"Righe in piu' sotto il codice: «{' / '.join(sotto[1:])}»"
            if not art.modello:
                art.note_estrazione["modello"] = "Nome del modello mancante"

        art.descrizione = unisci_righe([x.testo for x in desc])
        if not art.descrizione and r.get("descrizione_vuota_usa_modello", True) and art.modello:
            art.descrizione = art.modello
            # non e' un'anomalia: serve a sapere che una prosecuzione a pagina nuova la sostituisce
            art.descrizione_da_modello = True

        self._assegna_prezzo(art, prezzi)

        tutte = blocco + desc + prezzi
        art.bbox = _bbox(tutte)
        confidenze = [x.confidenza for x in tutte if x.confidenza is not None]
        if confidenze:
            art.da_ocr = True
            art.confidenza_minima = min(confidenze)
        return art

    def _assegna_prezzo(self, art: Articolo, prezzi: list[Riga]) -> None:
        if not prezzi:
            art.note_estrazione["prezzo"] = "Prezzo mancante"
            return
        if len(prezzi) > 1:
            art.prezzo_testo = " | ".join(p.testo for p in prezzi)
            art.note_estrazione["prezzo"] = (
                f"Piu' prezzi per lo stesso articolo ({art.prezzo_testo}): indicare quello corretto"
            )
            return
        art.prezzo_testo = prezzi[0].testo
        esito = parse_prezzo(prezzi[0].testo, self.regole.get("formato_prezzo", "auto"))
        art.prezzo = esito.valore
        if esito.motivo:
            art.note_estrazione["prezzo"] = esito.motivo
