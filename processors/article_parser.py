"""Dalle righe della pagina agli articoli, per qualunque listino descritto da un profilo.

Il profilo dice solo quale colonna contiene quale campo; tutte le distanze si ricavano dal documento
(v. extractors/table_extractor.py). L'articolo si individua dalla colonna d'ancoraggio
(processors/raggruppamento.py): per il listino JBL e' il codice tra parentesi, che a differenza del
prezzo non manca mai. Cosi' un prezzo mancante diventa un'anomalia segnalata invece di fondere due
articoli in uno.
"""
import itertools
import re
import statistics

from extractors.table_extractor import (
    ESTERNO,
    TITOLO,
    ColonnaFisica,
    Metriche,
    Riga,
    allinea_al_contenuto,
    colonna_di,
    e_ripetuta,
    firme_ripetute,
    metriche,
    raggruppa_righe,
    rileva_intestazioni,
    risolvi_colonne,
)
from processors import raggruppamento
from processors.data_validator import ean_valido
from processors.models import Articolo, Span
from processors.price_parser import RisultatoPrezzo, parse_prezzo
from processors.profilo import CAMPI_ANCORA, CONTIENE_PREDEFINITO, normalizza

_SPAZI = re.compile(r"\s+")
# il campo d'ancoraggio deve coprire almeno questa quota delle righe del campo piu' denso
QUOTA_DENSITA_ANCORA = 0.6
# se almeno questa quota delle righe della colonna Modello ha l'aspetto di un codice, l'ancora
# accetta solo quelle: le altre sono testo che passa di li' (pagine descrittive, indice)
QUOTA_ASPETTO_CODICE = 0.7
_TOKEN_CODICE = re.compile(r"^(?=.*\d)[\w./+\-]+$|^[A-Z][A-Z0-9./+\-]{2,}$")


def aspetto_codice(testo: str) -> bool:
    """Un identificativo come lo scrivono i listini: al piu' tre parole, la prima con una cifra o
    tutta maiuscola (DCP-1000, TU-NE1, Decoair-350L, TRIPOD-GA). Non lo sono «esaurimento» o
    «6 ingressi di linea stereo con», righe di testo descrittivo cadute nella colonna Articolo."""
    parole = testo.split()
    return 0 < len(parole) <= 3 and len(testo) <= 40 and bool(_TOKEN_CODICE.match(parole[0]))


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


def _pulito(testo: str) -> str:
    return _SPAZI.sub(" ", testo).strip()


class _Tabella:
    """Una pagina divisa in colonne fisiche: righe per colonna e titoli."""

    def __init__(self, colonne: list[ColonnaFisica], righe: dict[int, list[Riga]], titoli: list[Riga]):
        self.colonne = colonne
        self.righe = righe
        self.titoli = titoli


class ParserListino:
    """Parser con stato: statistiche del documento, ancora e ultimo articolo (per le prosecuzioni)."""

    def __init__(self, regole: dict):
        self.p = normalizza(regole)
        rx = self.p["regex"]
        self.re_codice = re.compile(rx["codice"]) if rx.get("codice") else None
        self.re_ean = re.compile(rx["ean"]) if rx.get("ean") else None
        self.re_prezzo = re.compile(rx["prezzo"]) if rx.get("prezzo") else None
        self.re_escludi = [re.compile(e) for e in self.p.get("escludi", [])]
        self.metr: Metriche | None = None
        self.firme: set = set()
        self.ancora: str | None = None if self.p["ancora"] == "auto" else self.p["ancora"]
        self.passo_ancora: float | None = None
        self.categoria = ""
        self.ultimo: Articolo | None = None
        self.avvisi: list[str] = []

    # --- preparazione sul documento ---------------------------------------------------------

    def prepara(self, pagine: list[tuple[list[Span], float, float]]) -> None:
        """Statistiche, righe ripetute e ancora, calcolate una volta sola su tutte le pagine (o un campione)."""
        self.metr = metriche([s for s, _, _ in pagine])
        self.firme = firme_ripetute([(s, h) for s, _, h in pagine], self.metr.tolleranza_riga)
        tabelle = [self._tabella(s, w, h) for s, w, h in pagine]
        if self.ancora is None:
            self.ancora = self._ancora_per_densita(tabelle)
        self.solo_codici = self._modelli_sono_codici(tabelle)
        self.passo_ancora = self._passo(tabelle)

    def _modelli_sono_codici(self, tabelle: list[_Tabella]) -> bool:
        """Vero se il documento scrive i modelli come codici: allora una riga che non lo sembra non e'
        un articolo. Sul catalogo Etabeta l'87% dei valori e' una parola sola come DCP-1000; un listino
        che scrive i modelli per esteso non supera la soglia e non viene filtrato."""
        if self.ancora != "modello":
            return False
        testi = []
        for t in tabelle:
            n = self._colonna_del_campo(t, "modello")
            if n is not None and self._profilo_colonna(t.colonne[n])["campo"] == "modello":
                testi += [_pulito(r.testo) for r in t.righe.get(n, []) if _pulito(r.testo)]
        return bool(testi) and sum(map(aspetto_codice, testi)) >= QUOTA_ASPETTO_CODICE * len(testi)

    def _assicura_preparato(self, spans, larghezza, altezza) -> None:
        if self.metr is None:  # chiamato su una pagina sola, senza preparazione: si usa quella pagina
            self.prepara([(spans, larghezza, altezza)])

    def _ancora_per_densita(self, tabelle: list[_Tabella]) -> str:
        conteggi = {campo: 0 for campo in CAMPI_ANCORA}
        for t in tabelle:
            for campo in CAMPI_ANCORA:
                n = self._colonna_del_campo(t, campo)
                if n is not None:
                    conteggi[campo] += sum(1 for r in t.righe.get(n, []) if self._e_ancora(r, campo, t.colonne[n]))
        massimo = max(conteggi.values(), default=0)
        for campo in CAMPI_ANCORA:  # codice, EAN, modello, prezzo: il prezzo e' proprio il campo che puo' mancare
            if massimo and conteggi[campo] >= QUOTA_DENSITA_ANCORA * massimo:
                return campo
        return "modello"

    def _passo(self, tabelle: list[_Tabella]) -> float:
        """Interlinea tipica della colonna d'ancoraggio: e' la misura dello stacco fra due articoli."""
        corpo = self.metr.corpo
        distanze = []
        for t in tabelle:
            n = self._colonna_del_campo(t, self.ancora)
            ys = [r.y0 for r in t.righe.get(n, [])] if n is not None else []
            distanze += [b - a for a, b in itertools.pairwise(ys) if 0.8 * corpo <= b - a <= 3 * corpo]
        return statistics.median(distanze) if distanze else self.metr.interlinea

    # --- pagina -----------------------------------------------------------------------------

    def _tabella(self, spans: list[Span], larghezza: float, altezza: float) -> _Tabella:
        tol = self.metr.tolleranza_riga
        righe_pagina = raggruppa_righe(spans, tol)
        # un catalogo ha un'intestazione per tabella, piu' tabelle per pagina: le colonne si leggono
        # dalla prima, tutte si tolgono dal corpo e fanno da taglio fra un articolo e l'altro
        intestazioni = rileva_intestazioni(righe_pagina, self.p, self.metr, larghezza)
        colonne = risolvi_colonne(intestazioni[0] if intestazioni else None, self.p, larghezza)
        corpo: list[Span] = []
        for riga in righe_pagina:
            # si tolgono le righe d'intestazione, non cio' che sta sopra la prima: nel catalogo Etabeta
            # una tabella prosegue dalla pagina precedente senza intestazione e la prima compare piu' in
            # basso. Testata e titolo del documento sopra l'intestazione (JBL) li toglie la ripetizione.
            if any(i.y0 - tol <= riga.y0 <= i.y1 for i in intestazioni):
                continue
            if e_ripetuta(riga, altezza, self.firme) or any(r.search(riga.testo) for r in self.re_escludi):
                continue
            corpo.extend(s for s in riga.spans if not any(r.search(s.testo) for r in self.re_escludi))
        if intestazioni:
            colonne = allinea_al_contenuto(colonne, corpo, self.p["spaziatura"]["tolleranza_colonna_pt"],
                                           profilo=self.p, larghezza=larghezza)
        per_colonna: dict[int, list[Span]] = {}
        titoli: list[Span] = []
        for s in corpo:
            dove = colonna_di(s, colonne, self.p, self.metr)
            if dove == TITOLO:
                titoli.append(s)
            elif (dove != ESTERNO and colonne[dove].indice is not None
                  and self.p["colonne"][colonne[dove].indice]["campo"] != "ignora"):
                # le colonne da ignorare (la marca e il testo promozionale di un catalogo) restano
                # confini, ma il loro testo non entra in nessun campo
                per_colonna.setdefault(dove, []).append(s)
        t = _Tabella(
            colonne,
            {n: raggruppa_righe(v, tol) for n, v in per_colonna.items()},
            raggruppa_righe(titoli, tol),
        )
        t.intestazioni = intestazioni
        return t

    def _profilo_colonna(self, col: ColonnaFisica) -> dict:
        return self.p["colonne"][col.indice]

    def _campi_colonna(self, col: ColonnaFisica) -> list[str]:
        pc = self._profilo_colonna(col)
        return pc.get("contiene", CONTIENE_PREDEFINITO) if pc["campo"] == "identificativo" else [pc["campo"]]

    def _colonna_del_campo(self, t: _Tabella, campo: str) -> int | None:
        for n, col in enumerate(t.colonne):
            if col.indice is not None and campo in self._campi_colonna(col):
                return n
        return None

    def _e_ancora(self, riga: Riga, campo: str, col: ColonnaFisica) -> bool:
        testo = _pulito(riga.testo)
        composita = self._profilo_colonna(col)["campo"] == "identificativo"
        if campo == "codice":
            if self.re_codice is not None:
                return bool(self.re_codice.match(testo))
            return bool(testo) and not composita
        if campo == "ean":
            return bool((self.re_ean is None or self.re_ean.match(testo)) and ean_valido(testo))
        if campo == "prezzo":
            return self._prezzo_da_testo(testo).valore is not None
        # modello: in una colonna semplice ogni riga e' un articolo, in una composita lo e' la riga
        # che non e' ne' un codice ne' un EAN
        if composita:
            return bool(testo) and not self._e_ancora(riga, "codice", col) and not self._e_ancora(riga, "ean", col)
        if getattr(self, "solo_codici", False):
            return aspetto_codice(testo)
        return bool(testo)

    def elabora_pagina(
        self,
        spans: list[Span],
        pagina: int,
        larghezza: float = 595.0,
        altezza: float = 842.0,
        separatori: list[float] = (),
    ) -> list[Articolo]:
        self._assicura_preparato(spans, larghezza, altezza)
        t = self._tabella(spans, larghezza, altezza)
        tol = self.metr.tolleranza_riga
        n_ancora = self._colonna_del_campo(t, self.ancora)
        intest = getattr(t, "intestazioni", [])
        # una linea divisoria e' il bordo superiore di una cella, e il riquadro del testo dentro la cella
        # la sfiora da sopra (Etabeta: linea a 59,7, testo da 59,5): taglia quindi una tolleranza piu' in alto,
        # o la prima riga di ogni cella finisce nella cella precedente
        tagli = sorted([r.y0 for r in t.titoli] + [y - tol for y in separatori] + [i.y0 for i in intest])
        # categoria: titoli di sezione e, nei cataloghi, marca e titolo scritti nell'intestazione della tabella
        categorie = sorted([(r.y0, r.testo) for r in t.titoli]
                           + [(i.y0, " · ".join(i.variabili)) for i in intest if i.variabili])
        gruppi = []
        if n_ancora is not None:
            col = t.colonne[n_ancora]
            composita = self._profilo_colonna(col)["campo"] == "identificativo"
            celle = None
            if separatori and not composita:
                # griglia fitta: ogni cella e' un articolo, qualunque aspetto abbia il modello
                righe_ancora = [r for r in t.righe.get(n_ancora, []) if _pulito(r.testo)]
                celle = raggruppamento.celle(righe_ancora, [y - tol for y in separatori],
                                             [r.y0 for r in t.titoli] + [i.y0 for i in intest[1:]])
                if celle is not None:
                    # una cella e' un articolo se ha un prezzo o un modello con l'aspetto di un codice:
                    # le altre sono testo promozionale caduto nella griglia («Honeywell e' la soluzione...»)
                    n_prezzo = self._colonna_del_campo(t, "prezzo")
                    prezzi_y = [r.y0 for r in t.righe.get(n_prezzo, [])] if n_prezzo is not None else []
                    celle = [g for g in celle if aspetto_codice(_pulito(g.righe[0].testo))
                             or any(g.cella[0] <= y < g.cella[1] for y in prezzi_y)]
            gruppi = celle if celle is not None else raggruppamento.gruppi(
                t.righe.get(n_ancora, []),
                lambda r: self._e_ancora(r, self.ancora, col),
                self.p["spaziatura"]["fattore_stacco"] * self.passo_ancora,
                tagli,
            )
        inizi = [g.inizio for g in gruppi]
        finestra = 0.6 * self.passo_ancora
        # righe di ogni colonna divise fra gli articoli; quelle prima del primo sono una prosecuzione
        prima: dict[int, list[Riga]] = {}
        per_articolo: list[dict[int, list[Riga]]] = [{} for _ in gruppi]
        for n, righe in t.righe.items():
            if n == n_ancora:
                dentro = {id(r) for g in gruppi for r in g.righe}
                for k, g in enumerate(gruppi):
                    per_articolo[k][n] = list(g.righe)
                fasce = raggruppamento.estensioni(inizi, tagli)
                resto = [r for r in righe if id(r) not in dentro]
            elif gruppi and getattr(gruppi[0], "cella", None) is not None:
                # griglia: le altre colonne si dividono sulle stesse celle dell'ancora
                fasce = [g.cella for g in gruppi]
                resto = righe
            else:
                ys = sorted(r.y0 for r in righe)
                contiguo = 1.2 * self.metr.interlinea
                ancore_y = [g.ancora.y0 for g in gruppi]
                if raggruppamento.e_centrata(ys, inizi, tagli, tol, contiguo):
                    fasce = raggruppamento.fasce_centrate(ys, ancore_y, tagli, tol, contiguo)
                else:
                    fasce = raggruppamento.fasce(ys, inizi, tagli, tol, finestra, contiguo)
                resto = righe
            for r in resto:
                k = next((k for k, (lo, hi) in enumerate(fasce) if lo - (tol if n == n_ancora else 0) <= r.y0
                          < hi - (tol if n == n_ancora else 0)), None)
                if k is not None:
                    per_articolo[k].setdefault(n, []).append(r)
                elif not inizi or r.y0 < inizi[0]:
                    prima.setdefault(n, []).append(r)
        self._prosecuzione(t, prima, pagina, categorie)

        articoli = []
        for k, inizio in enumerate(inizi):
            sopra = [testo for y, testo in categorie if y < inizio]
            if sopra:
                self.categoria = sopra[-1]
            per_colonna = {n: sorted(v, key=lambda r: r.y0) for n, v in per_articolo[k].items()}
            art = self._articolo(t, per_colonna, pagina)
            articoli.append(art)
            self.ultimo = art
        if not gruppi and categorie:
            self.categoria = categorie[-1][1]
        return articoli

    def _prosecuzione(self, t: _Tabella, prima: dict[int, list[Riga]], pagina: int, categorie) -> None:
        """Testo in cima alla pagina, prima del primo articolo: e' il seguito dell'ultimo articolo."""
        prima = {n: righe for n, righe in prima.items() if righe}
        if not prima:
            return
        primo_y = min(r.y0 for righe in prima.values() for r in righe)
        if self.ultimo is None or any(y < primo_y for y, _ in categorie):
            testo = unisci_righe([r.testo for righe in prima.values() for r in righe])
            self.avvisi.append(f"Pagina {pagina}: testo non attribuito a nessun articolo: «{testo[:80]}»")
            return
        art = self.ultimo
        for n, righe in prima.items():
            col = t.colonne[n]
            campi = self._campi_colonna(col)
            testi = [r.testo for r in righe]
            if "descrizione" in campi:
                base = "" if art.descrizione_da_modello else art.descrizione
                art.descrizione = unisci_righe([base, *testi])
                art.descrizione_da_modello = False
            elif "prezzo" in campi:
                if art.prezzo is None and not art.prezzo_testo and len(righe) == 1:
                    self._assegna_prezzo(art, righe, col)
                else:
                    art.note_estrazione["prezzo"] = (
                        f"Altro prezzo trovato a pagina {pagina} (colonna «{col.etichetta}»): «{righe[0].testo}» — verificare"
                    )
            else:
                campo = campi[0]
                if not getattr(art, campo):
                    setattr(art, campo, unisci_righe(testi))
                else:
                    art.note_estrazione[campo] = (
                        f"Testo in piu' a pagina {pagina} (colonna «{col.etichetta}»): «{unisci_righe(testi)[:60]}»"
                    )

    # --- campi ------------------------------------------------------------------------------

    def _articolo(self, t: _Tabella, per_colonna: dict[int, list[Riga]], pagina: int) -> Articolo:
        art = Articolo(pagina=pagina, categoria=self.categoria)
        prezzi_visti = False
        for n, righe in sorted(per_colonna.items()):
            if not righe:
                continue
            col = t.colonne[n]
            pc = self._profilo_colonna(col)
            if pc["campo"] == "identificativo":
                self._composita(art, righe, pc.get("contiene", CONTIENE_PREDEFINITO), col)
            elif pc["campo"] == "prezzo":
                if prezzi_visti:  # due colonne prezzo: non si sceglie
                    art.note_estrazione["prezzo"] = f"Prezzo anche nella colonna «{col.etichetta}»: verificare"
                else:
                    self._assegna_prezzo(art, righe, col)
                prezzi_visti = True
            elif pc["campo"] == "codice":
                self._codice(art, unisci_righe([r.testo for r in righe]), col)
            elif pc["campo"] in ("modello", "ean", "descrizione"):
                testo = unisci_righe([r.testo for r in righe])
                attuale = getattr(art, pc["campo"])
                setattr(art, pc["campo"], unisci_righe([attuale, testo]) if attuale else testo)
        mappati = self._campi_mappati(t)
        if not prezzi_visti and "prezzo" in mappati:
            art.note_estrazione["prezzo"] = "Prezzo mancante"
        if not art.codice and "codice" in mappati and "codice" not in art.note_estrazione:
            art.note_estrazione["codice"] = "Codice non trovato"
        if not art.descrizione and self.p["descrizione_vuota_usa_modello"] and art.modello:
            art.descrizione = art.modello
            # non e' un'anomalia: serve a sapere che una prosecuzione a pagina nuova la sostituisce
            art.descrizione_da_modello = True

        tutte = [r for righe in per_colonna.values() for r in righe]
        if tutte:
            art.bbox = (min(r.x0 for r in tutte), min(r.y0 for r in tutte), max(r.x1 for r in tutte), max(r.y1 for r in tutte))
        confidenze = [r.confidenza for r in tutte if r.confidenza is not None]
        if confidenze:
            art.da_ocr = True
            art.confidenza_minima = min(confidenze)
        return art

    def _campi_mappati(self, t: _Tabella) -> set[str]:
        return {c for col in t.colonne if col.indice is not None for c in self._campi_colonna(col)}

    def _codice(self, art: Articolo, testo: str, col: ColonnaFisica) -> None:
        testo = _pulito(testo)
        if self.re_codice is None:
            art.codice = testo
            return
        m = self.re_codice.match(testo)
        if not m:
            art.codice = testo
            art.note_estrazione["codice"] = f"Codice in formato inatteso nella colonna «{col.etichetta}»: «{testo}»"
            return
        valore = (m.groupdict().get("valore") or m.group(0)).strip()
        art.codice = f"({valore})" if self.p["codice_con_parentesi"] and "valore" in m.groupdict() else valore

    def _composita(self, art: Articolo, righe: list[Riga], contiene: list[str], col: ColonnaFisica) -> None:
        """Piu' campi impilati nella stessa colonna (JBL: nome su piu' righe, codice tra parentesi, EAN).

        Il campo con un'espressione regolare fa da perno: le righe sopra vanno ai campi che lo precedono
        in `contiene`, quelle sotto ai campi che lo seguono, una riga per campo.
        """
        testi = [_pulito(r.testo) for r in righe]
        perno = next((c for c in ("codice", "ean") if c in contiene and self._regex_di(c) is not None), None)
        indice = None
        if perno is not None:
            rx = self._regex_di(perno)
            indice = next((i for i, x in enumerate(testi) if rx.match(x)), None)
        if indice is None:
            art.modello = unisci_righe(testi) if "modello" in contiene else ""
            if perno is not None:
                art.note_estrazione[perno] = f"{perno.capitalize()} non trovato nella colonna «{col.etichetta}»"
            return
        prima = contiene[: contiene.index(perno)]
        dopo = contiene[contiene.index(perno) + 1:]
        if prima:
            setattr(art, prima[0], unisci_righe(testi[:indice]))
            if not testi[:indice]:
                art.note_estrazione[prima[0]] = f"{prima[0].capitalize()} mancante nella colonna «{col.etichetta}»"
        if perno == "codice":
            self._codice(art, testi[indice], col)
        else:
            art.ean = testi[indice]
        sotto = testi[indice + 1:]
        for campo, testo in zip(dopo, sotto, strict=False):
            setattr(art, campo, testo)
        if dopo and len(sotto) > len(dopo):
            art.note_estrazione[dopo[-1]] = f"Righe in piu' sotto il codice: «{' / '.join(sotto[len(dopo):])}»"

    def _regex_di(self, campo: str):
        return self.re_codice if campo == "codice" else self.re_ean

    def _prezzo_da_testo(self, testo: str) -> RisultatoPrezzo:
        if self.re_prezzo is not None:
            m = self.re_prezzo.search(testo)
            if not m:
                return RisultatoPrezzo(None, motivo="Prezzo non riconosciuto dall'espressione del fornitore")
            testo = m.groupdict().get("valore") or m.group(0)
        return parse_prezzo(testo, self.p["formato_prezzo"])

    def _assegna_prezzo(self, art: Articolo, righe: list[Riga], col: ColonnaFisica) -> None:
        if len(righe) > 1:
            validi = [r for r in righe if self._prezzo_da_testo(r.testo).valore is not None]
            if not validi:
                # "Chiedere / quotazioni" su due righe: e' un testo solo, non due prezzi
                art.prezzo_testo = unisci_righe([r.testo for r in righe])
                art.note_estrazione["prezzo"] = (
                    f"Prezzo non riconosciuto: «{art.prezzo_testo}» (colonna «{col.etichetta}»)"
                )
                return
            if len(validi) == 1:
                righe = validi
        if len(righe) > 1:
            art.prezzo_testo = " | ".join(r.testo for r in righe)
            art.note_estrazione["prezzo"] = (
                f"Piu' prezzi per lo stesso articolo ({art.prezzo_testo}) nella colonna «{col.etichetta}»: "
                "indicare quello corretto"
            )
            return
        art.prezzo_testo = righe[0].testo
        esito = self._prezzo_da_testo(righe[0].testo)
        art.prezzo = esito.valore
        if esito.motivo:
            art.note_estrazione["prezzo"] = f"{esito.motivo} (colonna «{col.etichetta}»)"
