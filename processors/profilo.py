"""Profili di fornitore (schema versione 2): valori predefiniti, conversione dalla versione 1, sinonimi.

Un profilo resta un dizionario semplice, come esce dal JSON: viaggia cosi' fino al processo di
estrazione senza conversioni. `normalizza` lo completa con i valori predefiniti, cosi' chi lo legge
non deve gestire chiavi mancanti.
"""
import copy
import functools
import re
import unicodedata

from processors.models import INTESTAZIONI, TESTO_GENERICO, ColonnaUscita

CAMPI_DATI = ("modello", "codice", "ean", "descrizione", "prezzo")
CAMPI_COLONNA = (*CAMPI_DATI, "identificativo", TESTO_GENERICO, "ignora")
CAMPI_ANCORA = ("codice", "ean", "modello", "prezzo")  # ordine di preferenza nella scelta automatica
CONTIENE_PREDEFINITO = ["modello", "codice", "ean"]

REGEX_CODICE_PARENTESI = r"^\((?P<valore>[^()]+)\)$"
REGEX_EAN = r"^\d{8,14}$"

# Sinonimi delle intestazioni, confrontati dopo `normalizza_testo`. Le voci piu' lunghe vincono
# sulle piu' corte ("prezzo al pubblico" prima di "prezzo"). "listino" e' il titolo di quasi ogni
# documento (JBL) ma anche l'etichetta della colonna prezzi (Etabeta): resta, perche' una riga e'
# un'intestazione solo se riconosce almeno due colonne diverse, e un titolo da solo non basta.
SINONIMI: dict[str, list[str]] = {
    "modello": ["modello", "model", "articolo", "art", "prodotto", "product", "nome", "name", "item", "tipo"],
    "codice": [
        "codice", "cod", "codice articolo", "cod art", "sku", "part number", "part no", "p n", "pn", "code",
        "item code", "item no", "ref", "rif", "riferimento", "order code", "codice ordine", "article no",
    ],
    "ean": ["ean", "ean13", "ean 13", "barcode", "codice a barre", "gtin", "upc"],
    "descrizione": ["descrizione", "description", "desc", "dettagli", "caratteristiche", "details"],
    "prezzo": [
        "prezzo", "price", "listino", "prezzo listino", "listino prezzi", "prezzo al pubblico", "prezzo al", "importo",
        "list price", "msrp", "rrp", "prezzo netto", "netto", "euro", "eur", "€", "prezzo unitario", "unit price",
    ],
}

PREDEFINITI = {
    "ancora": "auto",
    "spaziatura": {
        "tolleranza_colonna_pt": 6.0,
        "fattore_stacco": 1.5,
        "fattore_titolo": 1.3,
        "linee_divisorie": False,
    },
    "regex": {"codice": None, "ean": REGEX_EAN, "prezzo": None},
    "formato_prezzo": "auto",
    "codice_con_parentesi": True,
    "descrizione_vuota_usa_modello": True,
    "escludi": [],
    "prezzo_massimo": 1_000_000,
    "ocr": {"caratteri_minimi_pagina": 20, "dpi": 300, "lingua": "ita+eng", "confidenza_minima": 70},
}


@functools.lru_cache(maxsize=65536)
def normalizza_testo(testo: str) -> str:
    """Minuscolo, senza accenti, punteggiatura come spazio: "Cod. Art." -> "cod art"."""
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode() if testo else ""
    if "€" in testo:
        t += " €"
    t = re.sub(r"[^\w€]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


@functools.lru_cache(maxsize=256)
def _voci_normalizzate(extra: tuple) -> tuple[tuple[str, str], ...]:
    """(campo, sinonimo normalizzato), calcolate una volta: si confrontano con ogni riga di ogni pagina,
    e normalizzarle a ogni confronto quintuplicava il tempo di estrazione (misurato sul JBL: 1,0 -> 5,5 s)."""
    aggiunte = dict(extra)
    return tuple(
        (campo, v)
        for campo in CAMPI_DATI
        for voce in (*SINONIMI[campo], *aggiunte.get(campo, ()))
        if (v := normalizza_testo(voce))
    )


@functools.lru_cache(maxsize=65536)
def _campo_da_intestazione(testo: str, extra: tuple) -> tuple[str | None, int]:
    t = normalizza_testo(testo)
    migliore, lunghezza = None, 0
    if t:
        for campo, v in _voci_normalizzate(extra):
            if (t == v or t.startswith(v + " ")) and len(v) > lunghezza:
                migliore, lunghezza = campo, len(v)
    return migliore, lunghezza


def campo_da_intestazione(testo: str, sinonimi_extra: dict | None = None) -> tuple[str | None, int]:
    """Campo riconosciuto in un'etichetta d'intestazione e lunghezza del sinonimo che l'ha riconosciuto."""
    extra = tuple(sorted((k, tuple(v)) for k, v in (sinonimi_extra or {}).items()))
    return _campo_da_intestazione(testo, extra)


def _fondi(base: dict, sopra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in sopra.items():
        out[k] = _fondi(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def da_versione_1(vecchio: dict) -> dict:
    """Converte un profilo del formato precedente (colonne in punti assoluti) nel formato 2."""
    larghezza = 595.0  # A4 verticale: e' la pagina su cui erano state misurate le coordinate
    pos = vecchio.get("colonne_predefinite", {})
    etichette = vecchio.get("intestazioni", {})
    regex_codice = vecchio.get("regex_codice", REGEX_CODICE_PARENTESI).replace("?P<codice>", "?P<valore>")

    def x(chiave):
        return round(pos[chiave] / larghezza, 4) if chiave in pos else None

    nuovo = {
        "nome": vecchio.get("nome", "Fornitore"),
        "colonne": [
            {"campo": "identificativo", "intestazioni": [etichette.get("modello", "Modello")],
             "x_relativo": x("modello_x"), "contiene": list(CONTIENE_PREDEFINITO)},
            {"campo": "descrizione", "intestazioni": [etichette.get("descrizione", "Descrizione")],
             "x_relativo": x("descrizione_x")},
            {"campo": "prezzo", "intestazioni": [etichette.get("prezzo", "Prezzo")], "x_relativo": x("prezzo_x")},
        ],
        "ancora": "codice",
        "spaziatura": {"tolleranza_colonna_pt": vecchio.get("tolleranza_colonna", 6.0)},
        "regex": {"codice": regex_codice},
        "escludi": list(vecchio.get("piede_pagina", [])),
    }
    for chiave in ("formato_prezzo", "codice_con_parentesi", "descrizione_vuota_usa_modello", "prezzo_massimo", "ocr"):
        if chiave in vecchio:
            nuovo[chiave] = vecchio[chiave]
    return nuovo


def e_versione_1(profilo: dict) -> bool:
    return "colonne_predefinite" in profilo or isinstance(profilo.get("intestazioni"), dict)


def normalizza(profilo: dict, sinonimi_extra: dict | None = None) -> dict:
    """Profilo completo di tutti i valori, pronto per il motore (accetta anche la versione 1)."""
    if e_versione_1(profilo):
        profilo = da_versione_1(profilo)
    out = _fondi(PREDEFINITI, profilo)
    colonne = []
    for c in out.get("colonne", []):  # un profilo personale senza colonne estrae zero articoli, non si rompe
        c = {"intestazioni": [], "x_relativo": None, **c}
        if c["campo"] == "identificativo":
            c.setdefault("contiene", list(CONTIENE_PREDEFINITO))
        colonne.append(c)
    out["colonne"] = colonne
    out["sinonimi"] = sinonimi_extra or out.get("sinonimi", {})
    return out


def campi_mappati(profilo: dict) -> set[str]:
    """I cinque campi standard che il profilo prevede (le colonne di testo non sono campi del motore)."""
    campi: set[str] = set()
    for c in profilo["colonne"]:
        if c["campo"] == "identificativo":
            campi.update(c.get("contiene", CONTIENE_PREDEFINITO))
        elif c["campo"] not in ("ignora", TESTO_GENERICO):
            campi.add(c["campo"])
    return campi


def chiavi_testo(profilo: dict) -> dict[int, str]:
    """Indice della colonna del profilo -> chiave della sua colonna di testo ("testo_1", "testo_2"...)."""
    indici = [i for i, c in enumerate(profilo["colonne"]) if c["campo"] == TESTO_GENERICO]
    return {i: f"testo_{n}" for n, i in enumerate(indici, 1)}


def colonne_uscita(profilo: dict) -> list[ColonnaUscita]:
    """Le colonne della tabella e del foglio "Listino", nell'ordine del profilo: solo quelle che ci sono.

    Una colonna composita ne da' una per campo impilato (JBL: tre colonne fisiche, cinque in uscita);
    le colonne da ignorare non ne danno; un campo standard compare una volta sola anche se lo scrivono
    due colonne del PDF (il parser le unisce). Il nome e' l'`etichetta` del profilo, se c'e', altrimenti
    quello standard: un profilo salvato prima delle colonne dinamiche esporta come prima.
    """
    testo = chiavi_testo(profilo)
    out: list[ColonnaUscita] = []
    visti: set[str] = set()
    for i, c in enumerate(profilo["colonne"]):
        campo = c["campo"]
        if campo == TESTO_GENERICO:
            n = len([k for k in testo if k <= i])
            nome = c.get("etichetta") or next(iter(c.get("intestazioni") or []), "") or f"Testo {n}"
            out.append(ColonnaUscita(testo[i], nome, TESTO_GENERICO))
            continue
        campi = c.get("contiene", CONTIENE_PREDEFINITO) if campo == "identificativo" else [campo]
        for f in campi:
            if f in CAMPI_DATI and f not in visti:
                visti.add(f)
                nome = (c.get("etichetta") if campo != "identificativo" else None) or INTESTAZIONI[f]
                out.append(ColonnaUscita(f, nome, f))
    return out


def chiave_da_nome(nome: str, esistenti: set[str] | frozenset = frozenset()) -> str:
    """Chiave valida per lo schema (minuscole, cifre, _), resa unica rispetto a quelle esistenti."""
    base = re.sub(r"[^a-z0-9]+", "_", normalizza_testo(nome)).strip("_")[:56] or "fornitore"
    chiave, n = base, 2
    while chiave in esistenti:
        chiave, n = f"{base}_{n}", n + 1
    return chiave
