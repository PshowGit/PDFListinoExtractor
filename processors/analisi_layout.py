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
from dataclasses import dataclass, field

from extractors.pdf_reader import apri_pdf
from extractors.table_extractor import (
    ColonnaFisica,
    Metriche,
    assegna_colonna,
    e_ripetuta,
    firme_ripetute,
    linee_divisorie,
    metriche,
    raggruppa_righe,
    rileva_intestazione,
)
from extractors.text_extractor import estrai_span
from processors.data_validator import ean_valido
from processors.estrazione import _campione
from processors.models import Span
from processors.price_parser import parse_prezzo
from processors.profilo import CAMPI_DATI, CONTIENE_PREDEFINITO, REGEX_CODICE_PARENTESI, normalizza

_CODICE_PARENTESI = re.compile(REGEX_CODICE_PARENTESI)
_ASPETTO_PREZZO = re.compile(r"\d[.,]\d{1,2}\b|€|\bEUR\b", re.IGNORECASE)
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


@dataclass
class AnalisiLayout:
    percorso: str
    pagina: int
    pagine_totali: int
    larghezza: float
    altezza: float
    colonne: list[ColonnaRilevata]
    intestazione: tuple[float, float] | None
    ancora_proposta: str
    corpo: float
    interlinea: float
    formato_prezzo_proposto: str = "auto"
    regex_codice_proposta: str | None = None
    linee_divisorie_proposte: bool = False
    avvisi: list[str] = field(default_factory=list)


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

    spans_pag, larghezza, altezza = pagine[pagina]
    metr = metriche([s for s, _, _ in pagine.values()])
    tol = metr.tolleranza_riga
    firme = firme_ripetute([(s, h) for s, _, h in pagine.values()], tol)
    generico = _profilo_generico()

    def corpo_e_intestazione(spans, alt):
        righe = raggruppa_righe(spans, tol)
        intest = rileva_intestazione(righe, generico, metr)
        corpo = [
            s for r in righe
            if not e_ripetuta(r, alt, firme) and (intest is None or r.y0 > intest.y1)
            for s in r.spans if s.size < 1.3 * metr.corpo
        ]
        return corpo, intest

    _corpo_pag, intest = corpo_e_intestazione(spans_pag, altezza)
    corpi = {n: corpo_e_intestazione(s, h)[0] for n, (s, _, h) in pagine.items()}
    avvisi = []
    if intest is not None:
        fisiche = intest.colonne
        partenze = [(c.x, c.etichetta, generico["colonne"][c.indice]["campo"] if c.indice is not None else None)
                    for c in fisiche]
    else:
        avvisi.append("Nessuna riga d'intestazione riconosciuta: colonne ricostruite dalla posizione del testo.")
        tutti = [s for v in corpi.values() for s in v]
        ricostruite = colonne_senza_intestazione(tutti, metr, larghezza)
        fisiche = [ColonnaFisica(x0, i, f"Colonna {i + 1}", x1) for i, (x0, x1) in enumerate(ricostruite)]
        partenze = [(c.x, c.etichetta, None) for c in fisiche]
    if not partenze:
        raise ValueError(f"Pagina {pagina}: nessuna colonna riconoscibile (la pagina ha testo selezionabile?)")

    xs = [x for x, _, _ in partenze]
    testi: list[list[str]] = [[] for _ in partenze]
    esempi: list[list[str]] = [[] for _ in partenze]
    for n, spans in corpi.items():
        for gruppo in _righe_per_colonna(spans, fisiche, tol):
            for indice, riga in gruppo:
                testi[indice].append(riga.testo)
                if n == pagina and len(esempi[indice]) < 4 and riga.testo not in esempi[indice]:
                    esempi[indice].append(riga.testo)

    colonne = []
    for i, (x, etichetta, campo_intestazione) in enumerate(partenze):
        dal_contenuto = proponi_campo(testi[i])
        campo = campo_intestazione or dal_contenuto
        if dal_contenuto == "identificativo" and campo in ("modello", "codice"):
            campo = "identificativo"  # l'intestazione dice "Modello", ma ci sono anche codice ed EAN
        x1 = xs[i + 1] - 1 if i + 1 < len(xs) else larghezza
        fine = fisiche[i].x1 if intest is None else None
        colonne.append(ColonnaRilevata(x, x1, etichetta, campo, esempi[i], intest is not None, len(testi[i]), fine))

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
    return analisi


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
) -> dict:
    """Profilo (schema 2) da una mappatura colonna -> campo decisa sulle colonne dell'analisi.

    Due opzioni distinte sulle parentesi: `codici_tra_parentesi` dice che nel PDF i codici sono
    scritti cosi' (serve a riconoscerli, e a separarli dal nome in una colonna composita);
    `codice_con_parentesi` dice se tenerle nell'Excel.
    """
    if codici_tra_parentesi is None:
        codici_tra_parentesi = analisi.regex_codice_proposta is not None
    colonne = []
    for col, campo in zip(analisi.colonne, campi, strict=True):
        voce = {
            "campo": campo,
            "intestazioni": [col.etichetta] if col.da_intestazione else [],
            "x_relativo": round(col.x0 / analisi.larghezza, 4),
        }
        if not col.da_intestazione and col.fine_testo is not None:
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
