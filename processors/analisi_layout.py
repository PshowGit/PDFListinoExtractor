"""Pre-analisi di un listino sconosciuto, per il wizard: colonne, campo proposto per ognuna, ancora.

Le colonne si leggono dalla riga d'intestazione se c'e' (sinonimi: "SKU", "Part Number" -> Codice);
altrimenti si ricostruiscono raggruppando gli inizi di riga, con i prezzi allineati a destra
riconosciuti a parte (il loro inizio varia con la lunghezza della cifra, la loro fine no).
Il campo di ogni colonna si propone dal contenuto; l'intestazione, quando c'e', ha la precedenza.
L'ancora proposta la calcola lo stesso motore che poi estrarra' (ParserListino.prepara): proposta
ed estrazione non possono contraddirsi.
"""
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from extractors.pdf_reader import apri_pdf
from extractors.table_extractor import (
    ColonnaFisica,
    Metriche,
    Riga,
    allinea_al_contenuto,
    assegna_colonna,
    e_ripetuta,
    firme_ripetute,
    linee_divisorie,
    metriche,
    raggruppa_righe,
    rileva_intestazioni,
)
from extractors.text_extractor import estrai_span
from processors.data_validator import ean_valido
from processors.estrazione import _campione
from processors.models import ALTRO_PREZZO, INTESTAZIONI, MARCA, TESTO_GENERICO, Span
from processors.price_parser import parse_prezzo
from processors.profilo import (
    CAMPI_DATI,
    CONTIENE_PREDEFINITO,
    REGEX_CODICE_PARENTESI,
    campo_da_intestazione,
    normalizza,
)

_CODICE_PARENTESI = re.compile(REGEX_CODICE_PARENTESI)
_ASPETTO_PREZZO = re.compile(r"\d[.,]\d{1,2}\b|â‚¬|\bEUR\b", re.IGNORECASE)
_CODICE_SECCO = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9._/\-]{2,}$")  # un token con cifre: "AB-123/4"
_IT, _EN = re.compile(r"\d,\d{2}$"), re.compile(r"\d\.\d{2}$")
QUOTA_PREVALENTE = 0.6
QUOTA_MISTA = 0.2


@dataclass
class ColonnaRilevata:
    x0: float
    x1: float
    etichetta: str
    campo_proposto: str
    esempi: list[str] = field(default_factory=list)
    da_intestazione: bool = False
    righe: int = 0
    fine_testo: float | None = None  # fine del testo della colonna (solo se ricostruita senza intestazione)
    etichetta_completa: str = ""  # l'etichetta con le sue righe seguenti («Prezzo al Pubblico»): per il nome


@dataclass(frozen=True)
class DensitaPagina:
    """Quanto una pagina del campione sembra una tabella di prezzi: serve a non partire dall'indice."""

    numero: int
    prezzi: int  # scritte con l'aspetto di un prezzo, fuori da testate e intestazioni
    intestazione: bool  # se ha una riga d'intestazione riconosciuta


@dataclass
class AnalisiLayout:
    percorso: str
    pagina: int
    pagine_totali: int
    larghezza: float
    altezza: float
    colonne: list[ColonnaRilevata]
    intestazione: tuple[float, float] | None  # la prima, da cui si leggono le colonne
    ancora_proposta: str
    corpo: float
    interlinea: float
    formato_prezzo_proposto: str = "auto"
    regex_codice_proposta: str | None = None
    linee_divisorie_proposte: bool = False
    avvisi: list[str] = field(default_factory=list)
    pagine_campione: list[DensitaPagina] = field(default_factory=list)
    # una pagina con una tabella, quando quella analizzata sembra un indice o una copertina (v. pagina_consigliata)
    pagina_consigliata: int | None = None
    # tutte le righe d'intestazione della pagina (y0, y1): un catalogo ne ha una per tabella
    intestazioni: list[tuple[float, float]] = field(default_factory=list)


def _profilo_generico() -> dict:
    """Un profilo con una colonna per campo: serve a riconoscere un'intestazione qualunque per sinonimi."""
    return normalizza({"nome": "_", "colonne": [{"campo": c} for c in CAMPI_DATI]})


def _cluster(valori: list[float], distanza: float) -> list[list[float]]:
    gruppi: list[list[float]] = []
    for v in sorted(valori):
        if gruppi and v - gruppi[-1][-1] <= distanza:
            gruppi[-1].append(v)
        else:
            gruppi.append([v])
    return gruppi


def _sembra_prezzo(testo: str) -> bool:
    return bool(_ASPETTO_PREZZO.search(testo)) and parse_prezzo(testo).valore is not None


def colonne_senza_intestazione(spans: list[Span], metr: Metriche, larghezza: float) -> list[tuple[float, float]]:
    """Colonne (inizio, fine) ricostruite dalla posizione del testo, quando manca l'intestazione.

    La fine conta quanto l'inizio: con l'estensione orizzontale, l'assegnazione usa la stessa regola
    della sovrapposizione che vale con l'intestazione, e un "on request" allineato a destra resta nella
    colonna prezzi anche se comincia prima delle cifre (trovato col PDF generico senza intestazione).
    """
    prezzi = [s for s in spans if _sembra_prezzo(s.testo)]
    colonne: list[tuple[float, float]] = []
    # prezzi allineati a destra: si raggruppano per fine, e la colonna comincia al piu' lungo
    for gruppo in _cluster([s.x1 for s in prezzi], 3.0):
        if len(gruppo) >= 3:
            membri = [s for s in prezzi if min(gruppo) - 0.01 <= s.x1 <= max(gruppo) + 0.01]
            colonne.append((min(s.x0 for s in membri) - 1, max(s.x1 for s in membri)))
    in_prezzi = {id(s) for s in prezzi if any(x0 <= s.x0 and s.x1 <= x1 + 0.01 for x0, x1 in colonne)}
    resto = [s for s in spans if id(s) not in in_prezzi]
    supporto = max(3, round(0.04 * len(spans)))
    for gruppo in _cluster([s.x0 for s in resto], max(8.0, 1.5 * metr.corpo)):
        if len(gruppo) >= supporto:
            x = min(gruppo)
            if all(abs(x - x0) > metr.corpo for x0, _ in colonne):
                fine = max(s.x1 for s in resto if min(gruppo) <= s.x0 <= max(gruppo))
                colonne.append((x, fine))
    colonne.sort()
    # una colonna non si estende oltre l'inizio della successiva
    return [(x0, min(x1, colonne[i + 1][0] - 1) if i + 1 < len(colonne) else x1) for i, (x0, x1) in enumerate(colonne)]


def colonne_interne(colonne: list[ColonnaFisica], spans: list[Span], tol: float,
                    corpo: float) -> list[tuple[int, float, float]]:
    """Colonne senza etichetta dentro una colonna d'intestazione: (indice della colonna, inizio, fine).

    In un listino esportato da Excel l'intestazione nomina solo alcune colonne: nel Compumania sopra tipo
    («Computer»), marca («Compumania») e descrizione c'e' un'etichetta sola, il titolo della sezione
    («Personal computer»), e la descrizione usciva «Computer Compumania Core i3-3240...». Una colonna
    interna comincia alla stessa x (entro 2 pt) in almeno QUOTA_INTERNA delle righe della colonna, almeno
    due corpi dopo il suo inizio, e quasi nessuna riga ha un testo che la attraversa. Le parti di una
    descrizione in stili diversi («Dimensioni BAP:» + «315x315») cominciano ovunque e non contano.
    """
    per: dict[int, list[Span]] = {}
    for s in spans:
        n = assegna_colonna(s, colonne, 6.0)
        if n is not None:
            per.setdefault(n, []).append(s)
    trovate: list[tuple[int, float, float]] = []
    for n, membri in sorted(per.items()):
        righe = [sorted(r.spans, key=lambda s: s.x0) for r in raggruppa_righe(membri, tol)]
        if len(righe) < MINIMO_RIGHE_INTERNA:
            continue
        inizi = []
        for x in sorted({round(s.x0) for r in righe for s in r[1:]}):
            if x - colonne[n].x < 2 * corpo or any(abs(x - y) <= 2 for y in inizi):
                continue
            con = sum(1 for r in righe if any(abs(s.x0 - x) <= 2 for s in r[1:]))
            attraversano = sum(1 for r in righe if any(s.x0 < x - 2 and s.x1 > x + 1 for s in r))
            if con >= QUOTA_INTERNA * len(righe) and attraversano <= QUOTA_ATTRAVERSATA * len(righe):
                inizi.append(x)
        for k, x in enumerate(inizi):
            dopo = inizi[k + 1] - 2 if k + 1 < len(inizi) else float("inf")
            fine = max(s.x1 for r in righe for s in r if x - 2 <= s.x0 < dopo)
            trovate.append((n, float(x), min(fine, dopo + 1)))
    return trovate


def _con_interne(colonne: list[ColonnaFisica], riferimento: list[ColonnaFisica],
                 interne: list[tuple[int, float, float]]) -> list[ColonnaFisica]:
    """Le colonne di una pagina con le colonne interne trovate su quella di riferimento, spostate come la
    colonna che le contiene. L'etichetta della colonna non va oltre la prima interna: un titolo lungo
    («Consumabile Carta, cartuccia, nastro, toner, tamburo») copriva marca e descrizione."""
    nuove: list[ColonnaFisica] = []
    for i, c in enumerate(colonne):
        sue = [(x, fine) for n, x, fine in interne if n == i]
        scarto = c.x - riferimento[i].x
        x1 = c.x1 if c.x1 is None or not sue else min(c.x1, sue[0][0] + scarto - 1)
        nuove.append(ColonnaFisica(c.x, c.indice, c.etichetta, x1))
        nuove.extend(ColonnaFisica(x + scarto, None, "", fine + scarto) for x, fine in sue)
    return nuove


def proponi_campo(testi: list[str]) -> str:
    """Campo piu' probabile per una colonna, dal suo contenuto."""
    testi = [t.strip() for t in testi if t.strip()]
    if not testi:
        return "ignora"
    n = len(testi)

    def quota(pred):
        return sum(1 for t in testi if pred(t)) / n

    q_prezzo = quota(_sembra_prezzo)
    q_ean = quota(ean_valido)
    q_par = quota(lambda t: bool(_CODICE_PARENTESI.match(t)))
    parole = statistics.mean(len(t.split()) for t in testi)
    if q_prezzo >= QUOTA_PREVALENTE:
        return "prezzo"
    if q_ean >= QUOTA_PREVALENTE:
        return "ean"
    if q_par >= QUOTA_MISTA and 1 - q_par >= QUOTA_MISTA:
        return "identificativo"  # nome, codice tra parentesi ed EAN impilati (come JBL)
    if q_par >= QUOTA_PREVALENTE:
        return "codice"
    if parole >= 3:
        return "descrizione"
    if quota(lambda t: bool(_CODICE_SECCO.match(t))) >= QUOTA_PREVALENTE:
        return "codice"
    return "modello"


def _formato_prezzo(testi: list[str]) -> str:
    it = sum(1 for t in testi if _IT.search(t.strip()))
    en = sum(1 for t in testi if _EN.search(t.strip()))
    if it > 2 * en:
        return "it"
    if en > 2 * it:
        return "en"
    return "auto"


def analizza(pagine: dict[int, tuple[list[Span], float, float]], pagina: int, separatori: int = 0) -> AnalisiLayout:
    """Analisi su pagine gia' lette: {numero: (spans, larghezza, altezza)}; `pagina` e' quella mostrata."""
    from processors.article_parser import ParserListino

    _, larghezza, altezza = pagine[pagina]
    metr = metriche([s for s, _, _ in pagine.values()])
    tol = metr.tolleranza_riga
    firme = firme_ripetute([(s, h) for s, _, h in pagine.values()], tol)
    generico = _profilo_generico()

    def corpo_e_intestazione(spans, alt):
        righe = raggruppa_righe(spans, tol)
        # tutte le intestazioni: un catalogo ne ha una per tabella, e le successive non sono contenuto
        intestazioni = rileva_intestazioni(righe, generico, metr)
        prima = intestazioni[0] if intestazioni else None
        corpo = [
            s for r in righe
            if not e_ripetuta(r, alt, firme) and (prima is None or r.y0 > prima.y1)
            and not any(i.y0 - tol <= r.y0 <= i.y1 for i in intestazioni[1:])
            for s in r.spans if s.size < 1.3 * metr.corpo
        ]
        return corpo, prima, intestazioni

    tutte = {n: corpo_e_intestazione(s, h) for n, (s, _, h) in pagine.items()}
    letture = {n: (corpo, prima) for n, (corpo, prima, _) in tutte.items()}
    corpi = {n: corpo for n, (corpo, _) in letture.items()}
    intest = letture[pagina][1]
    avvisi = []
    # colonne di ogni pagina: quelle della sua intestazione, allineate al suo testo. Nello stesso
    # catalogo le sezioni hanno colonne in posizioni diverse, e una misura sull'intero campione
    # mescolava le sezioni (Articolo a x=167 in una, a x=136 in un'altra)
    colonne_di: dict[int, list[ColonnaFisica]] = {}
    if intest is not None:
        struttura = [c.indice for c in intest.colonne]
        for n, (corpo, prima) in letture.items():
            if prima is not None and [c.indice for c in prima.colonne] == struttura:
                colonne_di[n] = allinea_al_contenuto(prima.colonne, corpo)
        fisiche = colonne_di[pagina]
        interne = colonne_interne(fisiche, corpi[pagina], tol, metr.corpo)
        if interne:
            colonne_di = {n: _con_interne(cols, fisiche, interne) for n, cols in colonne_di.items()}
            fisiche = colonne_di[pagina]
        partenze = [(c.x, c.etichetta, generico["colonne"][c.indice]["campo"] if c.indice is not None else None)
                    for c in fisiche]
    else:
        avvisi.append("Nessuna riga d'intestazione riconosciuta: colonne ricostruite dalla posizione del testo.")
        tutti = [s for v in corpi.values() for s in v]
        ricostruite = colonne_senza_intestazione(tutti, metr, larghezza)
        fisiche = [ColonnaFisica(x0, i, f"Colonna {i + 1}", x1) for i, (x0, x1) in enumerate(ricostruite)]
        partenze = [(c.x, c.etichetta, None) for c in fisiche]
        colonne_di = dict.fromkeys(corpi, fisiche)
    if not partenze:
        raise ValueError(f"Pagina {pagina}: nessuna colonna riconoscibile (la pagina ha testo selezionabile?)")

    xs = [x for x, _, _ in partenze]
    testi: list[list[str]] = [[] for _ in partenze]
    esempi: list[list[str]] = [[] for _ in partenze]
    spans_col: list[list[Span]] = [[] for _ in partenze]
    allineato: list[list[tuple[float, int]]] = [[] for _ in partenze]  # (allineamento, righe) per pagina
    for n, cols in colonne_di.items():
        per_pagina: list[list[Riga]] = [[] for _ in partenze]
        for gruppo in _righe_per_colonna(corpi[n], cols, tol):
            for indice, riga in gruppo:
                testi[indice].append(riga.testo)
                per_pagina[indice].append(riga)
                if n == pagina:
                    spans_col[indice].extend(riga.spans)
                    if len(esempi[indice]) < 4 and riga.testo not in esempi[indice]:
                        esempi[indice].append(riga.testo)
        for indice, righe in enumerate(per_pagina):
            if len(righe) >= 3:
                allineato[indice].append((allineamento(righe), len(righe)))

    def allineamento_medio(i: int) -> float:
        totale = sum(n for _, n in allineato[i])
        return sum(a * n for a, n in allineato[i]) / totale if totale else 0.0

    # etichette su due righe («Prezzo al» / «Pubblico»): la seconda riga va all'etichetta con cui si
    # sovrappone di piu', come il testo alle colonne. Serve solo al nome proposto della colonna
    complete = [c.etichetta for c in fisiche]
    con_etichetta = [i for i, c in enumerate(fisiche) if c.etichetta]  # senza le colonne interne
    if intest is not None and len(intest.colonne) == len(con_etichetta):
        seguito = sorted((s for s in pagine[pagina][0] if intest.y0 + tol < s.y0 <= intest.y1), key=lambda s: (s.y0, s.x0))
        for s in seguito:
            n = assegna_colonna(s, intest.colonne, generico["spaziatura"]["tolleranza_colonna_pt"])
            if n is not None:
                complete[con_etichetta[n]] = f"{complete[con_etichetta[n]]} {s.testo.strip()}"
    colonne = []
    piu_piena = max((len(t) for t in testi), default=0)
    # ruoli gia' dati da un'etichetta riconosciuta: servono a riconoscere una colonna in piu' (sotto)
    da_etichetta = {c for _, _, c in partenze if c is not None}
    for i, (x, etichetta, campo_intestazione) in enumerate(partenze):
        dal_contenuto = proponi_campo(testi[i])
        quasi_vuota = len(testi[i]) < QUOTA_COLONNA_VUOTA * piu_piena  # didascalie sparse, non dati
        if campo_intestazione is None and (quasi_vuota or allineamento_medio(i) < QUOTA_ALLINEAMENTO):
            # nessun nome noto e testo non allineato: testo promozionale o marca (catalogo Etabeta)
            dal_contenuto = "ignora"
        campo = campo_intestazione or dal_contenuto
        if dal_contenuto == "identificativo" and campo in ("modello", "codice"):
            campo = "identificativo"  # l'intestazione dice "Modello", ma ci sono anche codice ed EAN
        if campo_intestazione is None and intest is not None and campo in ("modello", "descrizione") and (
            campo in da_etichetta or (campo == "modello" and da_etichetta & {"codice", "identificativo"})
        ):
            # un'etichetta che non e' il nome di un campo («Colour») sopra testo allineato, quando quel ruolo
            # l'ha gia' un'altra colonna, o l'articolo ha gia' il suo codice: e' una colonna in piu'
            campo = TESTO_GENERICO
        variabile = campo_intestazione is None and intest is not None and len(
            {cols[i].etichetta for cols in colonne_di.values() if len(cols) == len(partenze)}
        ) >= 2
        if campo == "ignora" and variabile:
            # sopra testo da ignorare, un'etichetta che cambia da una tabella all'altra e non e' il nome di
            # un campo: la marca (catalogo Etabeta: «VISSONIC», «MOGAMI», «Konig & Meyer»)
            campo = MARCA
        # un'etichetta che cambia fra le tabelle e' un titolo, non il nome della colonna: non si salva come
        # intestazione, o sulla sua tabella la categoria restava vuota (Compumania: «Personal computer»
        # sopra il tipo); una colonna interna non ha etichetta
        da_intestazione = intest is not None and bool(etichetta) and not variabile
        etichetta = etichetta or f"Colonna {i + 1}"
        x1 = xs[i + 1] - 1 if i + 1 < len(xs) else larghezza
        fine = max([s.x1 for s in spans_col[i]] + ([fisiche[i].x1] if fisiche[i].x1 else []), default=None)
        if fine is not None:
            # non oltre l'inizio della colonna dopo: sulla pagina 13 dell'Etabeta un testo a tutta larghezza portava
            # la fine della descrizione sopra i prezzi, e sulle pagine senza intestazione i prezzi andavano persi
            fine = min(fine, x1)
        colonne.append(ColonnaRilevata(x, x1, etichetta, campo, esempi[i], da_intestazione, len(testi[i]), fine,
                                       complete[i]))
    # piu' colonne di prezzi (Midiware: Listino, Dealer, Premium, Street): il prezzo dell'articolo e' uno, quello
    # che l'etichetta chiama prezzo o il primo; gli altri sono prezzi in piu'. Quattro «Prezzo» non si salvano, e
    # ogni riga aveva l'anomalia «Secondo prezzo»
    di_prezzo = [i for i, c in enumerate(colonne) if c.campo_proposto == "prezzo"]
    principale = next((i for i in di_prezzo if partenze[i][2] == "prezzo"), di_prezzo[0] if di_prezzo else None)
    for i in di_prezzo:
        if i != principale:
            colonne[i].campo_proposto = ALTRO_PREZZO

    ha_parentesi = any(c.campo_proposto in ("identificativo",) for c in colonne) or any(
        _CODICE_PARENTESI.match(t) for c, tt in zip(colonne, testi, strict=True) if c.campo_proposto == "codice" for t in tt
    )
    prezzi = [t for c, tt in zip(colonne, testi, strict=True) if c.campo_proposto == "prezzo" for t in tt]
    analisi = AnalisiLayout(
        percorso="", pagina=pagina, pagine_totali=0, larghezza=larghezza, altezza=altezza, colonne=colonne,
        intestazione=(intest.y0, intest.y1) if intest else None, ancora_proposta="auto",
        corpo=metr.corpo, interlinea=metr.interlinea, formato_prezzo_proposto=_formato_prezzo(prezzi),
        regex_codice_proposta=REGEX_CODICE_PARENTESI if ha_parentesi else None,
        linee_divisorie_proposte=separatori >= 3, avvisi=avvisi,
    )
    parser = ParserListino(profilo_da_analisi(analisi, [c.campo_proposto for c in colonne]))
    parser.prepara(list(pagine.values()))
    analisi.ancora_proposta = parser.ancora
    analisi.pagine_campione = [DensitaPagina(n, sum(1 for s in corpo if _sembra_prezzo(s.testo)), prima is not None)
                               for n, (corpo, prima) in sorted(letture.items())]
    analisi.pagina_consigliata = pagina_consigliata(analisi.pagine_campione, pagina)
    analisi.intestazioni = [(i.y0, i.y1) for i in tutte[pagina][2]]
    return analisi


QUOTA_ALLINEAMENTO = 0.5
QUOTA_COLONNA_VUOTA = 0.1
# colonna interna (v. colonne_interne): righe che vi cominciano, righe che la attraversano, righe per giudicare
QUOTA_INTERNA = 0.6
QUOTA_ATTRAVERSATA = 0.05
MINIMO_RIGHE_INTERNA = 5
# una pagina con meno di questa quota dei prezzi di una pagina tipica del campione non e' una tabella
QUOTA_PAGINA_DEBOLE = 0.25


def pagina_consigliata(densita: list[DensitaPagina], pagina: int) -> int | None:
    """Una pagina da cui partire, se quella analizzata non sembra una tabella di prezzi; altrimenti None.

    La prima pagina di un catalogo e' spesso copertina o indice: sull'Etabeta la pagina 1 non ha prezzi e la
    proposta li' e' sbagliata (6.465 «articoli», colonne «Colonna 1/2/3»). Una pagina e' debole se ha meno di
    QUOTA_PAGINA_DEBOLE della mediana dei prezzi delle pagine del campione che ne hanno; si consiglia la
    prima con almeno la mediana e un'intestazione, o in mancanza la prima con almeno la mediana. La pagina 1
    del listino JBL (3 prezzi su una mediana di 5) non e' debole e la sua proposta non cambia.
    """
    con_prezzi = [d.prezzi for d in densita if d.prezzi]
    if not con_prezzi or pagina not in {d.numero for d in densita} or pagina in pagine_con_tabella(densita):
        return None
    mediana = statistics.median(con_prezzi)
    piene = [d for d in densita if d.prezzi >= mediana]
    scelta = next((d for d in piene if d.intestazione), piene[0] if piene else None)
    return scelta.numero if scelta is not None and scelta.numero != pagina else None


def pagine_con_tabella(densita: list[DensitaPagina]) -> set[int]:
    """Le pagine del campione che non sono deboli: almeno QUOTA_PAGINA_DEBOLE della mediana dei prezzi."""
    con_prezzi = [d.prezzi for d in densita if d.prezzi]
    if not con_prezzi:
        return set()
    mediana = statistics.median(con_prezzi)
    return {d.numero for d in densita if d.prezzi and d.prezzi >= QUOTA_PAGINA_DEBOLE * mediana}


def allineamento(righe: list[Riga]) -> float:
    """Quota delle righe di una colonna che cominciano, o finiscono, alla stessa x (entro 2 pt).

    I dati di una tabella sono allineati a sinistra (codici, descrizioni) o a destra (prezzi); il testo
    promozionale e le marche di un catalogo sono centrati, e qui danno valori bassi. Si misura sulle
    righe e non sugli span: Â«Dimensioni BAP: 315x315Â» sono due span, e il secondo comincia ovunque.
    """
    if not righe:
        return 0.0

    def quota(valori):
        moda = Counter(round(v) for v in valori).most_common(1)[0][0]
        return sum(1 for v in valori if abs(v - moda) <= 2) / len(valori)

    return max(quota([r.x0 for r in righe]), quota([r.x1 for r in righe]))


def _righe_per_colonna(spans: list[Span], colonne: list[ColonnaFisica], tol: float):
    """Spans divisi per colonna (con la stessa regola dell'estrazione) e raggruppati in righe."""
    per: dict[int, list[Span]] = {}
    for s in spans:
        n = assegna_colonna(s, colonne, 6.0)
        if n is not None:
            per.setdefault(n, []).append(s)
    return [[(i, r) for r in raggruppa_righe(v, tol)] for i, v in per.items()]


def profilo_da_analisi(
    analisi: AnalisiLayout,
    campi: list[str],
    nome: str = "Nuovo fornitore",
    ancora: str = "auto",
    formato_prezzo: str | None = None,
    codice_con_parentesi: bool = True,
    linee: bool | None = None,
    codici_tra_parentesi: bool | None = None,
    etichette: list[str] | None = None,
) -> dict:
    """Profilo (schema 2) da una mappatura colonna -> campo decisa sulle colonne dell'analisi.

    Due opzioni distinte sulle parentesi: `codici_tra_parentesi` dice che nel PDF i codici sono
    scritti cosi' (serve a riconoscerli, e a separarli dal nome in una colonna composita);
    `codice_con_parentesi` dice se tenerle nell'Excel. `etichette` sono i nomi delle colonne nella
    tabella e nell'Excel: si salvano solo quelli diversi dal nome standard del campo.
    """
    if codici_tra_parentesi is None:
        codici_tra_parentesi = analisi.regex_codice_proposta is not None
    colonne = []
    for i, (col, campo) in enumerate(zip(analisi.colonne, campi, strict=True)):
        # si salva come intestazione solo un'etichetta che e' il nome di un campo: la marca o il titolo
        # di una tabella valgono per quella tabella sola, e le altre si riconoscono per posizione
        nome_di_campo = campo_da_intestazione(col.etichetta)[0] is not None
        voce = {
            "campo": campo,
            # una colonna di testo o un prezzo in piu' si ritrova dal suo nome («Colour», «Dealer»), come quelle
            # col nome di un campo
            "intestazioni": [col.etichetta] if col.da_intestazione and (
                nome_di_campo or campo in (TESTO_GENERICO, ALTRO_PREZZO)) else [],
            "x_relativo": round(col.x0 / analisi.larghezza, 4),
        }
        nome_colonna = (etichette[i] if etichette is not None else "").strip()
        if nome_colonna and campo not in ("ignora", "identificativo") and nome_colonna != INTESTAZIONI.get(campo):
            voce["etichetta"] = nome_colonna
        if col.fine_testo is not None:
            voce["x_fine_relativo"] = round(min(1.0, col.fine_testo / analisi.larghezza), 4)
        if campo == "identificativo":
            voce["contiene"] = list(CONTIENE_PREDEFINITO)
        colonne.append(voce)
    regex_codice = REGEX_CODICE_PARENTESI if codici_tra_parentesi else None
    return {
        "nome": nome,
        "colonne": colonne,
        "ancora": ancora,
        "spaziatura": {"linee_divisorie": analisi.linee_divisorie_proposte if linee is None else linee},
        "regex": {"codice": regex_codice},
        "formato_prezzo": formato_prezzo or analisi.formato_prezzo_proposto,
        "codice_con_parentesi": codice_con_parentesi,
    }


def analizza_pdf(percorso: str, pagina: int) -> AnalisiLayout:
    """Legge un campione del documento (compresa la pagina scelta) e lo analizza."""
    doc = apri_pdf(percorso)
    try:
        if not 1 <= pagina <= doc.page_count:
            raise ValueError(f"Pagina {pagina} inesistente: il PDF ne ha {doc.page_count}.")
        pagine = {}
        for indice in _campione(doc.page_count, [pagina]):
            page = doc[indice]
            pagine[indice + 1] = (estrai_span(page, indice + 1), page.rect.width, page.rect.height)
        if not pagine[pagina][0]:
            raise ValueError(
                f"La pagina {pagina} non ha testo selezionabile (PDF scansionato?): la mappatura si fa su testo."
            )
        separatori = len(linee_divisorie(doc[pagina - 1], doc[pagina - 1].rect.width))
        analisi = analizza(pagine, pagina, separatori)
        analisi.percorso = str(percorso)
        analisi.pagine_totali = doc.page_count
        return analisi
    finally:
        doc.close()
