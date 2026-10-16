"""Caricamento e salvataggio delle regole di estrazione per fornitore.

Le regole predefinite sono quelle distribuite col programma (in sola lettura se installato in
Program Files). Se in %LOCALAPPDATA%\\PDFListinoExtractor esiste un supplier_rules.json personale,
i suoi fornitori si aggiungono a quelli predefiniti o li sostituiscono per chiave: un aggiornamento
del programma porta regole nuove senza cancellare quelle dell'utente. Il wizard scrive soltanto il
file personale.

Formato: versione 2, descritto da config/supplier_rules.schema.json. Un file personale nella
versione 1 si legge ancora (la conversione avviene in memoria) e si riscrive in versione 2 solo al
primo salvataggio, conservandone una copia .bak.
"""
import json
import logging
import os
import shutil
from pathlib import Path

from percorsi import cartella_dati_utente, cartella_risorse
from processors.profilo import normalizza

log = logging.getLogger(__name__)
PERCORSO_REGOLE = cartella_risorse() / "config" / "supplier_rules.json"
PERCORSO_SCHEMA = cartella_risorse() / "config" / "supplier_rules.schema.json"
NOME_FILE_PERSONALE = "supplier_rules.json"
VERSIONE_SCHEMA = 2

# Motivo per cui le regole personali sono state ignorate, da mostrare all'utente; None se tutto ok.
avviso_regole_personali: str | None = None


class RegoleNonValide(ValueError):
    pass


def percorso_regole_personali() -> Path:
    return cartella_dati_utente() / NOME_FILE_PERSONALE


def _leggi(percorso: Path) -> dict:
    # utf-8-sig: il Blocco note e PowerShell salvano col BOM, e json lo rifiuta (trovato nel collaudo)
    with open(percorso, encoding="utf-8-sig") as f:
        return json.load(f)


def valida_schema(dati: dict) -> None:
    """Solleva RegoleNonValide con un messaggio leggibile se il file non rispetta lo schema 2."""
    import jsonschema

    schema = _leggi(PERCORSO_SCHEMA)
    errori = sorted(jsonschema.Draft202012Validator(schema).iter_errors(dati), key=lambda e: list(e.path))
    if errori:
        e = errori[0]
        dove = "/".join(str(p) for p in e.path) or "radice"
        raise RegoleNonValide(f"{dove}: {e.message}")


def _e_versione_2(dati: dict) -> bool:
    return dati.get("versione_schema") == VERSIONE_SCHEMA


def carica_regole(percorso: Path = PERCORSO_REGOLE, personali: Path | None = None) -> dict:
    global avviso_regole_personali
    tutte = _leggi(percorso)
    if personali is None and percorso == PERCORSO_REGOLE:
        personali = percorso_regole_personali()
    avviso_regole_personali = None
    if personali is not None and personali.is_file():
        try:
            extra = _leggi(personali)
            if not isinstance(extra, dict):
                raise TypeError("il file deve contenere un oggetto JSON")
            if _e_versione_2(extra):
                valida_schema(extra)
            fornitori = extra.get("fornitori", {})
            if not isinstance(fornitori, dict):
                raise TypeError("la voce \"fornitori\" deve essere un oggetto")
        except (OSError, ValueError, TypeError, AttributeError) as e:
            # un file personale rovinato non deve impedire l'avvio: si usano le regole distribuite
            avviso_regole_personali = (
                f"Il file di regole personali non e' leggibile ed e' stato ignorato:\n{personali}\n\n{e}"
            )
            log.warning(avviso_regole_personali)
            return tutte
        tutte["fornitori"].update(fornitori)
        tutte.setdefault("sinonimi", {})
        for campo, voci in extra.get("sinonimi", {}).items():
            tutte["sinonimi"].setdefault(campo, []).extend(voci)
        if extra.get("predefinito") in tutte["fornitori"]:
            tutte["predefinito"] = extra["predefinito"]
    return tutte


def regole_fornitore(chiave: str | None = None, percorso: Path = PERCORSO_REGOLE) -> dict:
    """Regole del fornitore indicato (o del predefinito), complete dei valori predefiniti."""
    tutte = carica_regole(percorso)
    chiave = chiave or tutte["predefinito"]
    if chiave not in tutte["fornitori"]:
        raise KeyError(f"Fornitore sconosciuto nella configurazione: {chiave}")
    return normalizza(tutte["fornitori"][chiave], tutte.get("sinonimi"))


def elenco_fornitori(percorso: Path = PERCORSO_REGOLE) -> dict[str, str]:
    """Chiave -> nome leggibile, per la scelta nell'interfaccia; il predefinito per primo."""
    tutte = carica_regole(percorso)
    chiavi = [tutte["predefinito"]] + [k for k in tutte["fornitori"] if k != tutte["predefinito"]]
    return {k: tutte["fornitori"][k].get("nome", k) for k in chiavi}


def _a_versione_2(dati: dict) -> dict:
    """Riporta un file personale (anche versione 1) al formato 2, senza i valori calcolati."""
    if _e_versione_2(dati):
        return dati
    fornitori = {}
    for chiave, profilo in dati.get("fornitori", {}).items():
        p = normalizza(profilo)
        p.pop("sinonimi", None)
        fornitori[chiave] = p
    nuovo = {"versione_schema": VERSIONE_SCHEMA, "fornitori": fornitori}
    if "predefinito" in dati:
        nuovo["predefinito"] = dati["predefinito"]
    return nuovo


def salva_fornitore_personale(chiave: str, profilo: dict, percorso: Path | None = None) -> Path:
    """Aggiunge o sostituisce un fornitore nel file personale.

    Scrittura atomica (file temporaneo + sostituzione), in utf-8-sig come lo salverebbe il Blocco
    note, con una copia .bak del file precedente. Il file risultante viene validato prima di
    sostituire il vecchio: se non e' valido il vecchio resta com'era.
    """
    percorso = percorso or percorso_regole_personali()
    if percorso.is_file():
        dati = _a_versione_2(_leggi(percorso))
        shutil.copy2(percorso, percorso.with_suffix(".json.bak"))
    else:
        dati = {"versione_schema": VERSIONE_SCHEMA, "fornitori": {}}
    profilo = {k: v for k, v in profilo.items() if k != "sinonimi"}
    dati["fornitori"][chiave] = profilo
    valida_schema(dati)
    temporaneo = percorso.with_suffix(".json.tmp")
    with open(temporaneo, "w", encoding="utf-8-sig") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    os.replace(temporaneo, percorso)
    log.info("Salvato il fornitore %s in %s", chiave, percorso)
    return percorso
