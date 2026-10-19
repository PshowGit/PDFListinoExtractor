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
from dataclasses import dataclass

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
from processors.models import CAMPI, MARCA, TESTO_GENERICO, Articolo, Span
from processors.price_parser import RisultatoPrezzo, parse_prezzo
from processors.profilo import CAMPI_ANCORA, CONTIENE_PREDEFINITO, chiavi_testo, normalizza, normalizza_testo

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


# una parola come la legge il vocabolario: lettere, anche unite da trattini ("water-resistant")
_PAROLA = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
# fine riga che puo' essere una sillabazione: lettere seguite dal trattino, dopo l'inizio o un segno che non
# e' ne' lettera ne' cifra ne' trattino ("recen-", "l’appli-", "Mic/Linea/Chi-"; non "RS232-USB-", "6500K-")
_CODA_SILLABA = re.compile(r"(?:^|[^\w-])([^\W\d_]+)-$")
_TESTA_SILLABA = re.compile(r"[^\W\d_]+")


def _parole(spans: list[Span]) -> frozenset[str]:
    """Parole del documento, in minuscolo: quelle unite da trattini sia intere sia nei loro pezzi.

    Non conta la parola che chiude una riga col trattino ("recen-"): e' proprio cio' che si vuole capire.
    """
    parole: set[str] = set()
    for s in spans:
        for m in _PAROLA.finditer(s.testo):
            if s.testo[m.end():m.end() + 1] == "-":
                continue
            parola = m.group(0).lower()
            parole.add(parola)
            parole.update(parola.split("-"))
    return frozenset(parole)


def _trattino(sinistra: str, destra: str, parole: frozenset[str]) -> str | None:
    """Che cosa dice il documento del trattino in fondo a `sinistra`, seguito a capo da `destra`.

    None se non puo' spezzare una parola: senza lettere ai suoi lati (codici e sigle: "MTC-29UB", "RJ-45")
    o con la maiuscola dopo ("Bi-Amp", "Dip-Switch"). Altrimenti "composto" se la forma col trattino
    compare nel documento ("U-bracket"), "sillaba" se compare la parola intera ("processo-re",
    "Ri-soluzione"), "spezzata" se il pezzo di sinistra non e' una parola ("recen-temente"), "parole" se
    lo e' ("two-part", "high-performance").
    """
    coda = _CODA_SILLABA.search(sinistra.rsplit(" ", 1)[-1])
    testa = _TESTA_SILLABA.match(destra)
    if coda is None or testa is None or not destra[0].islower():
        return None
    pezzo, seguito = coda.group(1).lower(), testa.group(0).lower()
    if f"{pezzo}-{seguito}" in parole:
        return "composto"
    if pezzo + seguito in parole:
        return "sillaba"
    return "parole" if pezzo in parole else "spezzata"


@dataclass(frozen=True)
class Vocabolario:
    """Le parole del documento e se il documento va a capo spezzando le parole col trattino.

    Il trattino di una parola andata a capo si toglie quando la parola intera compare nel documento; quando
    il pezzo di sinistra non e' una parola («recen-temente») solo se il documento sillaba. Senza questa
    condizione un listino breve in inglese perdeva il trattino di «water-resistant» («water» non vi compare
    da solo). Misurato: nel listino JBL nessuna sillabazione confermata contro 46 composti, nessun trattino
    tolto; nel catalogo Etabeta 39 parole ricomposte («Alo-ne», «l’appli-cazione») e i composti lasciati come
    sono («Plug-in», «pre-fader»). Resta «com-pattata»: «com» e' una parola del documento (da «.com»).
    """

    parole: frozenset[str] = frozenset()
    sillaba: bool = False

    @classmethod
    def del_documento(cls, pagine: list[list[Span]], corpo: float) -> "Vocabolario":
        """Il documento sillaba se i trattini a capo confermati come parole spezzate sono piu' di quelli
        confermati come composti. A capo e' la riga che comincia alla stessa x, entro due corpi sotto."""
        parole = _parole([s for spans in pagine for s in spans])
        conferme = {"sillaba": 0, "composto": 0}
        for spans in pagine:
            for s in spans:
                if not _CODA_SILLABA.search(s.testo):
                    continue
                sotto = [t for t in spans if s.y0 < t.y0 <= s.y0 + 2 * corpo and abs(t.x0 - s.x0) <= corpo]
                if sotto:
                    esito = _trattino(s.testo, min(sotto, key=lambda t: t.y0).testo, parole)
                    if esito in conferme:
                        conferme[esito] += 1
        return cls(parole, conferme["sillaba"] > conferme["composto"])

    def a_capo(self, sinistra: str, destra: str) -> bool:
        """Se il trattino in fondo a `sinistra` spezza una parola andata a capo, e va tolto."""
        esito = _trattino(sinistra, destra, self.parole)
        return esito == "sillaba" or (esito == "spezzata" and self.sillaba)


def unisci_righe(testi: list[str], vocabolario: Vocabolario | None = None) -> str:
    """Unisce righe spezzate senza incollare parole separate.

    Una riga che termina con un trattino attaccato a una parola ("water-") prosegue nella
    successiva senza spazio ("water-resistant"); un trattino isolato (" -") resta un separatore.
    Con il vocabolario del documento, il trattino di una parola andata a capo si toglie
    («Alo-» / «ne» -> «Alone»; v. `Vocabolario`).
    """
    risultato = ""
    for t in testi:
        t = _SPAZI.sub(" ", t).strip()
        if not t:
            continue
        if not risultato:
            risultato = t
        elif risultato.endswith("-") and len(risultato) > 1 and not risultato[-2].isspace():
            if vocabolario is not None and vocabolario.a_capo(risultato, t):
                risultato = risultato[:-1]
            risultato += t
        else:
            risultato += " " + t
    return risultato


def _pulito(testo: str) -> str:
    return _SPAZI.sub(" ", testo).strip()


def _nominata(marca: str, spans: list[Span]) -> bool:
    """Se il testo della pagina nomina la marca: ogni sua parola di almeno tre lettere ("Konig & Meyer")."""
    testo = normalizza_testo(" ".join(s.testo for s in spans)).replace(" ", "")
    parole = [w for w in normalizza_testo(marca).split() if len(w) >= 3]
    return bool(parole) and all(w in testo for w in parole)


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
        self.chiavi_testo = chiavi_testo(self.p)  # indice della colonna del profilo -> "testo_1"...
        # colonna della marca: il suo valore e' l'etichetta che l'intestazione di ogni tabella le scrive sopra
        self.indice_marca = next((i for i, c in enumerate(self.p["colonne"]) if c["campo"] == MARCA), None)
        self.marca = ""
        self.metr: Metriche | None = None
        self.firme: set = set()
        self.vocabolario = Vocabolario()  # parole del documento, per i trattini a capo
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
        self.vocabolario = Vocabolario.del_documento([s for s, _, _ in pagine], self.metr.corpo)
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
                  and self.p["colonne"][colonne[dove].indice]["campo"] not in ("ignora", MARCA)):
                # le colonne da ignorare (il testo promozionale di un catalogo) e quella della marca, che
                # la prende dall'intestazione, restano confini, ma il testo sotto non entra in nessun campo
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

    def _e_bollino(self, titolo: Riga, righe_ancora: list[Riga], separatori: list[float]) -> bool:
        """Un testo grande chiuso fra due linee della griglia, nella cella di un codice, e' un bollino
        («NEW» in corpo 12 sotto il codice, catalogo Etabeta), non un titolo di sezione: non deve tagliare
        l'articolo ne' diventare la categoria di quelli che seguono (34 articoli sul catalogo).

        Basta che la cella abbia dati per scambiare per bollini anche titoli di sezione veri («Light Pro»)
        e lasciare passare testo promozionale che il titolo tagliava: provato e scartato.
        """
        bordi = sorted(y - self.metr.tolleranza_riga for y in separatori)
        sopra = [b for b in bordi if b <= titolo.y0]
        sotto = [b for b in bordi if b > titolo.y0]
        if not sopra or not sotto:
            return False
        return any(sopra[-1] <= r.y0 < sotto[0] and aspetto_codice(_pulito(r.testo)) for r in righe_ancora)

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
        if separatori and n_ancora is not None:
            t.titoli = [r for r in t.titoli if not self._e_bollino(r, t.righe.get(n_ancora, []), separatori)]
        # una linea divisoria e' il bordo superiore di una cella, e il riquadro del testo dentro la cella
        # la sfiora da sopra (Etabeta: linea a 59,7, testo da 59,5): taglia quindi una tolleranza piu' in alto,
        # o la prima riga di ogni cella finisce nella cella precedente
        tagli = sorted([r.y0 for r in t.titoli] + [y - tol for y in separatori] + [i.y0 for i in intest])
        # categoria: titoli di sezione e, nei cataloghi, marca e titolo scritti nell'intestazione della tabella
        categorie = sorted([(r.y0, r.testo) for r in t.titoli]
                           + [(i.y0, " · ".join(i.variabili)) for i in intest if i.variabili])
        # marca: l'etichetta d'intestazione abbinata alla colonna della marca; una tabella che prosegue
        # nella pagina dopo senza intestazione tiene quella di prima, come la categoria
        marche = sorted((i.y0, c.etichetta) for i in intest for c in i.colonne
                        if self.indice_marca is not None and c.indice == self.indice_marca)
        if not intest and self.marca and not _nominata(self.marca, spans):
            # una pagina senza intestazione di tabella non dice di chi e': la marca della tabella precedente
            # vale solo se la pagina la nomina (Cloud, pagine 45-56). Nel catalogo Etabeta le altre sono schede
            # col solo logo (Chromateq a pagina 224, AVMATRIX a 325), dove quella marca era sbagliata in 208
            # articoli: resta vuota e il validatore la segnala, invece di inventarla
            self.marca = ""
        gruppi = []
        if n_ancora is not None:
            col = t.colonne[n_ancora]
            composita = self._profilo_colonna(col)["campo"] == "identificativo"
            celle = None
            if separatori and not composita:
                # griglia fitta: ogni cella e' un articolo, qualunque aspetto abbia il modello
                righe_ancora = [r for r in t.righe.get(n_ancora, []) if _pulito(r.testo)]
                bordi = [y - tol for y in separatori]
                tagli_celle = [r.y0 for r in t.titoli] + [i.y0 for i in intest[1:]]
                celle = raggruppamento.celle(righe_ancora, bordi, tagli_celle)
                if celle is not None:
                    # una cella e' un articolo se ha un prezzo o un modello con l'aspetto di un codice:
                    # le altre sono testo promozionale caduto nella griglia («Honeywell e' la soluzione...»)
                    n_prezzo = self._colonna_del_campo(t, "prezzo")
                    prezzi_y = [r.y0 for r in t.righe.get(n_prezzo, [])] if n_prezzo is not None else []
                    articoli_celle = [g for g in celle if aspetto_codice(_pulito(g.righe[0].testo))
                                      or any(g.cella[0] <= y < g.cella[1] for y in prezzi_y)]
                    tenute = {id(g) for g in articoli_celle}
                    tutti_bordi = sorted(set(bordi + tagli_celle))
                    # una cella con un prezzo e' un'altra voce anche senza codice («Master 2500/FC Flight
                    # case», i cavi al metro): ferma il seguito come un titolo o un testo che non e' un articolo
                    celle_prezzo = [max((b for b in tutti_bordi if b <= y), default=float("-inf")) for y in prezzi_y]
                    fermi = ([r.y0 for r in t.titoli] + [i.y0 for i in intest] + celle_prezzo
                             + [g.cella[0] for g in celle if id(g) not in tenute])
                    # le altre colonne prendono anche le celle che seguono senza codice ne' prezzo (le
                    # caratteristiche sotto la prima riga di una scheda prodotto)
                    fasce_griglia = raggruppamento.fasce_con_seguito(
                        [g.cella for g in articoli_celle], tutti_bordi, fermi)
                    celle = articoli_celle
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
                # griglia: le altre colonne si dividono sulle stesse celle dell'ancora, con il loro seguito
                fasce = fasce_griglia
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
            marca = [m for y, m in marche if y < inizio]
            if marca:
                self.marca = marca[-1]
            per_colonna = {n: sorted(v, key=lambda r: r.y0) for n, v in per_articolo[k].items()}
            art = self._articolo(t, per_colonna, pagina)
            if self.indice_marca is not None:
                art.altri[MARCA] = self.marca
            articoli.append(art)
            self.ultimo = art
        if not gruppi and categorie:
            self.categoria = categorie[-1][1]
        if not gruppi and marche:
            self.marca = marche[-1][1]
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
                art.descrizione = unisci_righe([base, *testi], self.vocabolario)
                art.descrizione_da_modello = False
            elif "prezzo" in campi:
                if art.prezzo is None and not art.prezzo_testo and len(righe) == 1:
                    self._assegna_prezzo(art, righe, col)
                else:
                    art.note_estrazione["prezzo"] = (
                        f"Altro prezzo trovato a pagina {pagina} (colonna «{col.etichetta}»): «{righe[0].testo}» — verificare"
                    )
            else:
                campo = self._chiave(col)
                if not art.valore(campo):
                    libero = self._profilo_colonna(col)["campo"] == TESTO_GENERICO
                    self._scrivi(art, campo, unisci_righe(testi, self.vocabolario if libero else None))
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
            elif pc["campo"] in ("modello", "ean", "descrizione", TESTO_GENERICO):
                chiave = self._chiave(col)
                # solo nel testo libero un trattino a capo puo' spezzare una parola: modelli ed EAN sono codici
                parole = self.vocabolario if pc["campo"] in ("descrizione", TESTO_GENERICO) else None
                testo = unisci_righe([r.testo for r in righe], parole)
                attuale = art.valore(chiave)
                self._scrivi(art, chiave, unisci_righe([attuale, testo], parole) if attuale else testo)
        mappati = self._campi_mappati(t)
        if not prezzi_visti and "prezzo" in mappati:
            art.note_estrazione["prezzo"] = "Prezzo mancante"
        if not art.codice and "codice" in mappati and "codice" not in art.note_estrazione:
            art.note_estrazione["codice"] = "Codice non trovato"
        # solo se il profilo ha una colonna Descrizione: senza, non c'e' una descrizione da riempire
        if not art.descrizione and self.p["descrizione_vuota_usa_modello"] and art.modello and "descrizione" in mappati:
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

    def _chiave(self, col: ColonnaFisica) -> str:
        """Dove va il testo di una colonna semplice: il suo campo, o "testo_N" per una colonna di testo."""
        campo = self._profilo_colonna(col)["campo"]
        return self.chiavi_testo[col.indice] if campo == TESTO_GENERICO else campo

    @staticmethod
    def _scrivi(art: Articolo, chiave: str, valore: str) -> None:
        # non `imposta`: quella e' la correzione dell'utente e cancella le note dell'estrazione
        if chiave in CAMPI:
            setattr(art, chiave, valore)
        else:
            art.altri[chiave] = valore

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
