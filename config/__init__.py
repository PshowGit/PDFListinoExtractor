"""Caricamento delle regole di estrazione per fornitore.

Le regole predefinite sono quelle distribuite col programma (in sola lettura se installato in
Program Files). Se in %LOCALAPPDATA%\\PDFListinoExtractor esiste un supplier_rules.json personale,
i suoi fornitori si aggiungono a quelli predefiniti o li sostituiscono per chiave: un aggiornamento
del programma porta regole nuove senza cancellare quelle dell'utente.
"""
import json
import logging
from pathlib import Path

from percorsi import cartella_dati_utente, cartella_risorse

log = logging.getLogger(__name__)
PERCORSO_REGOLE = cartella_risorse() / "config" / "supplier_rules.json"
NOME_FILE_PERSONALE = "supplier_rules.json"


def percorso_regole_personali() -> Path:
    return cartella_dati_utente() / NOME_FILE_PERSONALE


# Motivo per cui le regole personali sono state ignorate, da mostrare all'utente; None se tutto ok.
avviso_regole_personali: str | None = None


def _leggi(percorso: Path) -> dict:
    # utf-8-sig: il Blocco note e PowerShell salvano col BOM, e json lo rifiuta (trovato nel collaudo)
    with open(percorso, encoding="utf-8-sig") as f:
        return json.load(f)


def carica_regole(percorso: Path = PERCORSO_REGOLE, personali: Path | None = None) -> dict:
    global avviso_regole_personali
    tutte = _leggi(percorso)
    if personali is None and percorso == PERCORSO_REGOLE:
        personali = percorso_regole_personali()
    avviso_regole_personali = None
    if personali is not None and personali.is_file():
        try:
            extra = _leggi(personali)
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
        if extra.get("predefinito") in tutte["fornitori"]:
            tutte["predefinito"] = extra["predefinito"]
    return tutte


def regole_fornitore(chiave: str | None = None, percorso: Path = PERCORSO_REGOLE) -> dict:
    """Regole del fornitore indicato, o di quello predefinito."""
    tutte = carica_regole(percorso)
    chiave = chiave or tutte["predefinito"]
    if chiave not in tutte["fornitori"]:
        raise KeyError(f"Fornitore sconosciuto nella configurazione: {chiave}")
    return tutte["fornitori"][chiave]


def elenco_fornitori(percorso: Path = PERCORSO_REGOLE) -> dict[str, str]:
    """Chiave -> nome leggibile, per la scelta nell'interfaccia; il predefinito per primo."""
    tutte = carica_regole(percorso)
    chiavi = [tutte["predefinito"]] + [k for k in tutte["fornitori"] if k != tutte["predefinito"]]
    return {k: tutte["fornitori"][k].get("nome", k) for k in chiavi}
