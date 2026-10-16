"""Profili di fornitore (schema versione 2): valori predefiniti, conversione dalla versione 1, sinonimi.

Un profilo resta un dizionario semplice, come esce dal JSON: viaggia cosi' fino al processo di
estrazione senza conversioni. `normalizza` lo completa con i valori predefiniti, cosi' chi lo legge
non deve gestire chiavi mancanti.
"""
import copy
import re
import unicodedata

CAMPI_DATI = ("modello", "codice", "ean", "descrizione", "prezzo")
CAMPI_COLONNA = (*CAMPI_DATI, "identificativo", "ignora")
CAMPI_ANCORA = ("codice", "ean", "modello", "prezzo")  # ordine di preferenza nella scelta automatica
CONTIENE_PREDEFINITO = ["modello", "codice", "ean"]

REGEX_CODICE_PARENTESI = r"^\((?P<valore>[^()]+)\)$"
REGEX_EAN = r"^\d{8,14}$"

# Sinonimi delle intestazioni, confrontati dopo `normalizza_testo`. Le voci piu' lunghe vincono
# sulle piu' corte ("prezzo al pubblico" prima di "prezzo"). "listino" manca di proposito: e'
# il titolo di quasi ogni documento, e diventerebbe una colonna Prezzo inesistente.
SINONIMI: dict[str, list[str]] = {
    "modello": ["modello", "model", "articolo", "art", "prodotto", "product", "nome", "name", "item", "tipo"],
    "codice": [
        "codice", "cod", "codice articolo", "cod art", "sku", "part number", "part no", "p n", "pn", "code",
        "item code", "item no", "ref", "rif", "riferimento", "order code", "codice ordine", "article no",
    ],
    "ean": ["ean", "ean13", "ean 13", "barcode", "codice a barre", "gtin", "upc"],
    "descrizione": ["descrizione", "description", "desc", "dettagli", "caratteristiche", "details"],
    "prezzo": [
        "prezzo", "price", "prezzo listino", "listino prezzi", "prezzo al pubblico", "prezzo al", "importo",
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


def normalizza_testo(testo: str) -> str:
    """Minuscolo, senza accenti, punteggiatura come spazio: "Cod. Art." -> "cod art"."""
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode() if testo else ""
    if "€" in testo:
        t += " €"
    t = re.sub(r"[^\w€]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def campo_da_intestazione(testo: str, sinonimi_extra: dict | None = None) -> tuple[str | None, int]:
    """Campo riconosciuto in un'etichetta d'intestazione e lunghezza del sinonimo che l'ha riconosciuto."""
    t = normalizza_testo(testo)
    if not t:
        return None, 0
    migliore, lunghezza = None, 0
    for campo in CAMPI_DATI:
        voci = SINONIMI[campo] + list((sinonimi_extra or {}).get(campo, []))
        for voce in voci:
            v = normalizza_testo(voce)
            if v and (t == v or t.startswith(v + " ")) and len(v) > lunghezza:
                migliore, lunghezza = campo, len(v)
    return migliore, lunghezza


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
    campi: set[str] = set()
    for c in profilo["colonne"]:
        if c["campo"] == "identificativo":
            campi.update(c.get("contiene", CONTIENE_PREDEFINITO))
        elif c["campo"] != "ignora":
            campi.add(c["campo"])
    return campi


def chiave_da_nome(nome: str, esistenti: set[str] | frozenset = frozenset()) -> str:
    """Chiave valida per lo schema (minuscole, cifre, _), resa unica rispetto a quelle esistenti."""
    base = re.sub(r"[^a-z0-9]+", "_", normalizza_testo(nome)).strip("_")[:56] or "fornitore"
    chiave, n = base, 2
    while chiave in esistenti:
        chiave, n = f"{base}_{n}", n + 1
    return chiave
