"""Caricamento e salvataggio delle regole di estrazione per fornitore.

Le regole predefinite sono quelle distribuite col programma (in sola lettura se installato in
Program Files). Se in %LOCALAPPDATA%\\PDFListinoExtractor esiste un supplier_rules.json personale,
i suoi fornitori si aggiungono a quelli predefiniti o li sostituiscono per chiave: un aggiornamento
del programma porta regole nuove senza cancellare quelle dell'utente. Il wizard, la rinomina e la
rimozione di un fornitore scrivono soltanto il file personale.

Formato: versione 2, descritto da config/supplier_rules.schema.json. Un file personale nella
versione 1 si legge ancora (la conversione avviene in memoria) e si riscrive in versione 2 solo al
primo salvataggio, conservandone una copia .bak.

I fornitori personali si esportano in un file dello stesso formato e si importano su un'altra
postazione: l'importazione li aggiunge a quelli che ci sono, senza sovrascriverne nessuno.
"""
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
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


class NomeNonValido(ValueError):
    pass


# Cio' che puo' andare storto leggendo un file di regole scritto a mano
_ERRORI_LETTURA = (OSError, ValueError, TypeError, AttributeError)


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


def _leggi_personali(percorso: Path) -> dict:
    """Il file personale letto e verificato; solleva un'eccezione di _ERRORI_LETTURA se non e' usabile."""
    extra = _leggi(percorso)
    if not isinstance(extra, dict):
        raise TypeError("il file deve contenere un oggetto JSON")
    if _e_versione_2(extra):
        valida_schema(extra)
    if not isinstance(extra.get("fornitori", {}), dict):
        raise TypeError("la voce \"fornitori\" deve essere un oggetto")
    return extra


def carica_regole(percorso: Path = PERCORSO_REGOLE, personali: Path | None = None) -> dict:
    global avviso_regole_personali
    tutte = _leggi(percorso)
    if personali is None and percorso == PERCORSO_REGOLE:
        personali = percorso_regole_personali()
    avviso_regole_personali = None
    if personali is not None and personali.is_file():
        try:
            extra = _leggi_personali(personali)
            fornitori = extra.get("fornitori", {})
        except _ERRORI_LETTURA as e:
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


def chiavi_personali(percorso: Path | None = None) -> set[str]:
    """Fornitori del file personale: i soli che si possono rinominare o rimuovere.

    Vuoto se il file manca o non e' usabile, perche' in quel caso carica_regole lo ignora.
    """
    percorso = percorso or percorso_regole_personali()
    if not percorso.is_file():
        return set()
    try:
        return set(_leggi_personali(percorso).get("fornitori", {}))
    except _ERRORI_LETTURA:
        return set()


def _da_modificare(percorso: Path) -> dict:
    if percorso.is_file():
        return _a_versione_2(_leggi(percorso))
    return {"versione_schema": VERSIONE_SCHEMA, "fornitori": {}}


def _scrivi_personali(dati: dict, percorso: Path, copia: bool = True) -> None:
    """Scrittura atomica (file temporaneo + sostituzione), in utf-8-sig come lo salverebbe il Blocco
    note, con una copia .bak del file precedente. Il contenuto viene validato prima di toccare il
    file: se non e' valido, file e copia restano com'erano.
    """
    valida_schema(dati)
    if copia and percorso.is_file():
        shutil.copy2(percorso, percorso.with_suffix(".json.bak"))
    temporaneo = percorso.with_suffix(".json.tmp")
    with open(temporaneo, "w", encoding="utf-8-sig") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    os.replace(temporaneo, percorso)


def salva_fornitore_personale(chiave: str, profilo: dict, percorso: Path | None = None) -> Path:
    """Aggiunge o sostituisce un fornitore nel file personale."""
    percorso = percorso or percorso_regole_personali()
    dati = _da_modificare(percorso)
    dati["fornitori"][chiave] = {k: v for k, v in profilo.items() if k != "sinonimi"}
    _scrivi_personali(dati, percorso)
    log.info("Salvato il fornitore %s in %s", chiave, percorso)
    return percorso


def _personale(dati: dict, chiave: str) -> dict:
    if chiave not in dati["fornitori"]:
        raise KeyError(f"{chiave} non e' un fornitore delle regole personali")
    return dati["fornitori"][chiave]


def profilo_personale(chiave: str, percorso: Path | None = None) -> dict:
    """Il profilo di un fornitore personale cosi' com'e' salvato (in versione 2), da modificare nel wizard."""
    return _personale(_da_modificare(percorso or percorso_regole_personali()), chiave)


def rinomina_fornitore_personale(chiave: str, nome: str, percorso: Path | None = None) -> Path:
    """Cambia il nome con cui un fornitore personale compare nel menu; chiave e regole restano.

    Il nome deve restare unico, maiuscole a parte, anche rispetto ai fornitori distribuiti: il
    menu e il wizard riconoscono il fornitore dal nome.
    """
    percorso = percorso or percorso_regole_personali()
    nome = nome.strip()
    if not nome:
        raise NomeNonValido("Il nome del fornitore non puo' essere vuoto.")
    dati = _da_modificare(percorso)
    profilo = _personale(dati, chiave)
    tutti = {**_leggi(PERCORSO_REGOLE)["fornitori"], **dati["fornitori"]}
    if any(k != chiave and p.get("nome", k).strip().lower() == nome.lower() for k, p in tutti.items()):
        raise NomeNonValido(f"Esiste gia' un fornitore «{nome}».")
    profilo["nome"] = nome
    _scrivi_personali(dati, percorso)
    log.info("Rinominato il fornitore %s in «%s»", chiave, nome)
    return percorso


def rimuovi_fornitore_personale(chiave: str, percorso: Path | None = None) -> Path:
    """Toglie un fornitore dal file personale (la versione precedente resta nella copia .bak).

    Se aveva la stessa chiave di un fornitore distribuito, torna in uso quello.
    """
    percorso = percorso or percorso_regole_personali()
    dati = _da_modificare(percorso)
    _personale(dati, chiave)
    del dati["fornitori"][chiave]
    if dati.get("predefinito") == chiave:
        del dati["predefinito"]
    _scrivi_personali(dati, percorso)
    log.info("Rimosso il fornitore %s da %s", chiave, percorso)
    return percorso


def esporta_fornitori_personali(destinazione: Path, percorso: Path | None = None) -> int:
    """Scrive in `destinazione` i fornitori del file personale, per importarli su un'altra postazione.

    Solo i fornitori creati dall'utente (quelli distribuiti li ha gia' ogni installazione) e i suoi
    sinonimi; il predefinito no, perche' riguarda la postazione. Restituisce quanti fornitori ha scritto.
    """
    percorso = percorso or percorso_regole_personali()
    dati = _a_versione_2(_leggi_personali(percorso))
    if not dati["fornitori"]:
        raise RegoleNonValide("Non ci sono fornitori personali da esportare.")
    uscita = {"versione_schema": VERSIONE_SCHEMA, "fornitori": dati["fornitori"]}
    if dati.get("sinonimi"):
        uscita["sinonimi"] = dati["sinonimi"]
    _scrivi_personali(uscita, Path(destinazione), copia=False)
    log.info("Esportati %d fornitori in %s", len(uscita["fornitori"]), destinazione)
    return len(uscita["fornitori"])


SUFFISSO_IMPORTATO = " - Importato"


@dataclass
class EsitoImportazione:
    aggiunti: list[str] = field(default_factory=list)  # chiavi nel file personale, nell'ordine del file
    rinominati: list[tuple[str, str]] = field(default_factory=list)  # (nome nel file, nome dato)
    gia_presenti: list[str] = field(default_factory=list)  # nomi saltati perche' identici a un fornitore locale


def _leggi_da_importare(sorgente: Path) -> dict:
    """Il file da importare in versione 2 e validato; RegoleNonValide se non e' un file di regole."""
    try:
        dati = _leggi(sorgente)
        if not isinstance(dati, dict) or not isinstance(dati.get("fornitori"), dict):
            raise TypeError("non contiene un elenco di fornitori")
        if not _e_versione_2(dati):  # un supplier_rules.json della versione 1.0 copiato a mano
            dati = _a_versione_2(dati)
        valida_schema(dati)
    except OSError:
        raise
    except _ERRORI_LETTURA as e:
        raise RegoleNonValide(f"{Path(sorgente).name} non e' un file di fornitori valido: {e}") from e
    if not dati["fornitori"]:
        raise RegoleNonValide(f"{Path(sorgente).name} non contiene fornitori.")
    return dati


def _senza_nome(profilo: dict) -> dict:
    return {k: v for k, v in profilo.items() if k != "nome"}


def _gia_importato(profilo: dict, locale: dict) -> bool:
    """Lo stesso fornitore c'e' gia': regole identiche e lo stesso nome, o quello che gli ha dato
    un'importazione precedente. Reimportare lo stesso file non deve creare copie."""
    nome = profilo["nome"].strip().lower()
    for p in locale.values():
        n = p.get("nome", "").strip().lower()
        if _senza_nome(p) == _senza_nome(profilo) and (
            n == nome or n.startswith(nome + SUFFISSO_IMPORTATO.lower())
        ):
            return True
    return False


def _chiave_libera(base: str, occupate) -> str:
    base = base[:64]
    n = 2
    chiave = base
    while chiave in occupate:
        chiave = f"{base[:60]}_{n}"
        n += 1
    return chiave


def importa_fornitori(sorgente: Path, percorso: Path | None = None) -> EsitoImportazione:
    """Aggiunge al file personale i fornitori di un file esportato (o di un supplier_rules.json).

    Non sovrascrive nulla: un fornitore con la chiave di uno personale riceve una chiave nuova, e
    uno col nome di un fornitore gia' nel menu il suffisso « - Importato» (il nome deve restare
    unico, come nella rinomina). Con la chiave di un fornitore distribuito lo sostituisce, come
    faceva sulla postazione da cui viene. Un fornitore identico a uno locale si salta. Se il file
    non e' valido solleva RegoleNonValide e il file personale resta com'era.
    """
    percorso = percorso or percorso_regole_personali()
    importati = _leggi_da_importare(Path(sorgente))
    dati = _da_modificare(percorso)
    locale = dati["fornitori"]
    distribuiti = _leggi(PERCORSO_REGOLE)["fornitori"]
    esito = EsitoImportazione()
    for chiave, profilo in importati["fornitori"].items():
        profilo = {**profilo, "nome": profilo["nome"].strip() or chiave}
        if _gia_importato(profilo, locale):
            esito.gia_presenti.append(profilo["nome"])
            continue
        if chiave in locale:
            chiave = _chiave_libera(f"{chiave}_importato", locale)
        usati = {
            p.get("nome", k).strip().lower() for k, p in {**distribuiti, **locale}.items() if k != chiave
        }
        nome = profilo["nome"]
        if nome.lower() in usati:
            nome = f"{profilo['nome']}{SUFFISSO_IMPORTATO}"
            n = 2
            while nome.lower() in usati:
                nome = f"{profilo['nome']}{SUFFISSO_IMPORTATO} {n}"
                n += 1
            esito.rinominati.append((profilo["nome"], nome))
        locale[chiave] = {**profilo, "nome": nome}
        esito.aggiunti.append(chiave)
    sinonimi_nuovi = False
    for campo, voci in importati.get("sinonimi", {}).items():
        presenti = dati.setdefault("sinonimi", {}).setdefault(campo, [])
        for voce in voci:
            if voce not in presenti:
                presenti.append(voce)
                sinonimi_nuovi = True
    if esito.aggiunti or sinonimi_nuovi:
        _scrivi_personali(dati, percorso)
    log.info(
        "Importati da %s: %d fornitori, %d rinominati, %d gia' presenti",
        sorgente, len(esito.aggiunti), len(esito.rinominati), len(esito.gia_presenti),
    )
    return esito
