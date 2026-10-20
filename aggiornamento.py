"""Aggiornamento dalle release di GitHub: controllo, download verificato, installazione.

All'avvio dell'eseguibile installato la finestra principale chiede in un thread l'ultima release
(`cerca_aggiornamento`). Se e' piu' recente e l'utente non l'ha ignorata compare un pulsante; con
«Aggiorna ora» si scarica il setup, se ne verifica lo SHA-256 con quello che GitHub dichiara per il
file (il setup non e' firmato: e' l'unica garanzia che sia integro) e lo si avvia in modo semi
silenzioso, poi il programma si chiude, perche' l'installer svuota `_internal`.

Qui niente Tk: le funzioni girano anche fuori dal thread dell'interfaccia. Ogni errore di rete
diventa un "nessun aggiornamento" nel log, senza disturbare chi lavora.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from percorsi import cartella_dati_utente, impacchettato
from version import NOME_APP, __version__

log = logging.getLogger(__name__)

REPOSITORY = "PshowGit/PDFListinoExtractor"
URL_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
URL_SCARICAMENTI = f"https://github.com/{REPOSITORY}/releases/download/"
# Per il collaudo (tools/collaudo_aggiornamento.ps1): un'API finta su un server locale. Con questa
# variabile il setup si puo' scaricare dallo stesso server invece che da GitHub.
VARIABILE_URL = "PDFLISTINO_URL_AGGIORNAMENTI"
NOME_SETUP = f"{NOME_APP}_Setup.exe"
APP_ID = "{F0411EB9-947B-42C1-B41A-62EFF2E34BD1}"  # come in installer/PDFListinoExtractor.iss
CHIAVE_DISINSTALLAZIONE = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
# Parametro dell'installer (vedi [Code] nel .iss): riapre il programma alla fine anche in modo silenzioso
RIAVVIA = "/RIAVVIA"
NOME_PREFERENZE = "preferenze.json"
TIMEOUT_S = 8


class AggiornamentoNonValido(Exception):
    pass


@dataclass(frozen=True)
class Rilascio:
    versione: str  # "1.7.0"
    tag: str  # "v1.7.0"
    note: str  # testo della release, in Markdown
    pagina: str  # pagina web della release
    url_setup: str
    sha256: str  # minuscolo, senza prefisso
    dimensione: int


def attivo() -> bool:
    """Solo nell'eseguibile: dal sorgente non c'e' nulla da aggiornare."""
    return impacchettato()


def versione_da_tag(tag: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None  # type: ignore[return-value]


def _url_api() -> str:
    return os.environ.get(VARIABILE_URL) or URL_API


def _origine(url: str) -> str:
    return "/".join(url.split("/", 3)[:3]) + "/"


def _url_ammesso(url: str) -> bool:
    if os.environ.get(VARIABILE_URL):
        return url.startswith(_origine(_url_api()))
    return url.startswith(URL_SCARICAMENTI)


def _richiesta(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"{NOME_APP}/{__version__}",
    })


def rilascio_da_api(dati: dict) -> Rilascio | None:
    """La release descritta dall'API, se ha un tag vX.Y.Z e il setup con il suo SHA-256."""
    if dati.get("draft") or dati.get("prerelease"):
        return None
    tag = dati.get("tag_name", "")
    numeri = versione_da_tag(tag)
    if numeri is None:
        log.info("Release con un tag non riconosciuto: %r", tag)
        return None
    setup = next((a for a in dati.get("assets") or [] if a.get("name") == NOME_SETUP), None)
    if setup is None:
        log.info("La release %s non ha %s", tag, NOME_SETUP)
        return None
    digest = str(setup.get("digest") or "")
    url = str(setup.get("browser_download_url") or "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) or not _url_ammesso(url):
        log.warning("Setup della release %s senza SHA-256 o da un indirizzo inatteso: %s", tag, url)
        return None
    return Rilascio(
        versione=".".join(map(str, numeri)), tag=tag, note=dati.get("body") or "",
        pagina=dati.get("html_url") or f"https://github.com/{REPOSITORY}/releases", url_setup=url,
        sha256=digest.split(":", 1)[1].lower(), dimensione=int(setup.get("size") or 0),
    )


def cerca_aggiornamento(attuale: str = __version__, apri=urllib.request.urlopen) -> Rilascio | None:
    """L'ultima release se e' piu' recente di `attuale`; None anche se la rete non risponde."""
    try:
        with apri(_richiesta(_url_api()), timeout=TIMEOUT_S) as risposta:
            dati = json.loads(risposta.read().decode("utf-8-sig"))
        rilascio = rilascio_da_api(dati) if isinstance(dati, dict) else None
    except (OSError, ValueError) as e:  # offline, timeout, proxy, limite dell'API, JSON rovinato
        log.info("Controllo degli aggiornamenti non riuscito: %s", e)
        return None
    if rilascio is None or versione_da_tag(rilascio.versione) <= (versione_da_tag(attuale) or (0, 0, 0)):
        log.info("Nessun aggiornamento: installata %s, pubblicata %s", attuale, rilascio and rilascio.versione)
        return None
    log.info("Disponibile la versione %s (installata %s)", rilascio.versione, attuale)
    return rilascio


# --- preferenze -------------------------------------------------------------------------------
# In un file a parte: supplier_rules.json ha uno schema chiuso, e una chiave in piu' farebbe ignorare
# all'avvio tutti i fornitori dell'utente.

def _percorso_preferenze() -> Path:
    return cartella_dati_utente() / NOME_PREFERENZE


def _leggi_preferenze() -> dict:
    try:
        with open(_percorso_preferenze(), encoding="utf-8-sig") as f:
            dati = json.load(f)
        return dati if isinstance(dati, dict) else {}
    except (OSError, ValueError):
        return {}


def versione_ignorata() -> str | None:
    v = _leggi_preferenze().get("versione_ignorata")
    return v if isinstance(v, str) else None


def ignora_versione(versione: str) -> None:
    dati = {**_leggi_preferenze(), "versione_ignorata": versione}
    percorso = _percorso_preferenze()
    temporaneo = percorso.with_suffix(".json.tmp")
    with open(temporaneo, "w", encoding="utf-8-sig") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    os.replace(temporaneo, percorso)
    log.info("Versione %s ignorata", versione)


# --- download e installazione -----------------------------------------------------------------

def _file_scaricato(versione: str) -> Path:
    return Path(tempfile.gettempdir()) / f"{NOME_APP}_Setup_{versione}.exe"


def pulisci_scaricati() -> None:
    """Toglie dalla cartella temporanea i setup scaricati per gli aggiornamenti precedenti."""
    for f in Path(tempfile.gettempdir()).glob(f"{NOME_APP}_Setup_*.exe*"):
        try:
            f.unlink()
        except OSError:  # l'installer che ha riaperto il programma puo' essere ancora in esecuzione
            pass


def scarica(
    rilascio: Rilascio,
    avanzamento: Callable[[int, int], None] = lambda letti, totale: None,
    annullato: Callable[[], bool] = lambda: False,
    apri=urllib.request.urlopen,
) -> Path | None:
    """Scarica il setup e ne verifica lo SHA-256. None se annullato; AggiornamentoNonValido se il
    file non e' quello dichiarato (e allora non resta su disco)."""
    finale = _file_scaricato(rilascio.versione)
    parziale = finale.with_name(finale.name + ".part")
    impronta = hashlib.sha256()
    letti = 0
    try:
        with apri(_richiesta(rilascio.url_setup), timeout=TIMEOUT_S) as risposta, open(parziale, "wb") as f:
            totale = int(risposta.headers.get("Content-Length") or rilascio.dimensione or 0)
            while blocco := risposta.read(256 * 1024):
                if annullato():
                    break
                f.write(blocco)
                impronta.update(blocco)
                letti += len(blocco)
                avanzamento(letti, totale)
        if annullato():
            parziale.unlink(missing_ok=True)
            return None
        if impronta.hexdigest() != rilascio.sha256:
            parziale.unlink(missing_ok=True)
            raise AggiornamentoNonValido(
                "Il file scaricato non corrisponde a quello pubblicato (SHA-256 diverso): non verra' installato."
            )
        os.replace(parziale, finale)
    except OSError:
        parziale.unlink(missing_ok=True)
        raise
    log.info("Scaricato %s (%d byte, SHA-256 verificato)", finale, letti)
    return finale


def _cartella_registrata(radice) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(radice, CHIAVE_DISINSTALLAZIONE, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def modo_installazione(cartella: Path | None = None) -> str | None:
    """"/CURRENTUSER" o "/ALLUSERS" secondo come e' stato installato il programma in esecuzione; None se
    non viene da un setup (una copia di dist, il sorgente): allora non si aggiorna da qui."""
    if sys.platform != "win32":
        return None
    import winreg

    cartella = cartella or Path(sys.executable).parent

    def stessa(percorso: str | None) -> bool:
        def norma(p) -> str:
            return os.path.normcase(os.path.normpath(str(p)))
        return bool(percorso) and norma(percorso) == norma(cartella)

    if stessa(_cartella_registrata(winreg.HKEY_CURRENT_USER)):
        return "/CURRENTUSER"
    if stessa(_cartella_registrata(winreg.HKEY_LOCAL_MACHINE)):
        return "/ALLUSERS"
    return None


def argomenti_setup(setup: Path, modo: str, cartella: Path) -> list[str]:
    registro = Path(tempfile.gettempdir()) / f"{NOME_APP}_aggiornamento.log"
    # /SILENT e non /VERYSILENT: l'utente vede l'avanzamento dopo che la finestra si e' chiusa.
    # /DIR senza la barra finale: davanti alle virgolette diventerebbe un carattere di escape.
    return [str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", modo, f"/DIR={str(cartella).rstrip(os.sep)}",
            f"/LOG={registro}", RIAVVIA]


def avvia_installazione(setup: Path, modo: str, cartella: Path | None = None) -> None:
    """Avvia il setup staccato dal programma, che subito dopo deve chiudersi."""
    argomenti = argomenti_setup(setup, modo, cartella or Path(sys.executable).parent)
    log.info("Avvio dell'aggiornamento: %s", subprocess.list2cmdline(argomenti))
    try:
        subprocess.Popen(argomenti, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    except OSError as e:
        if getattr(e, "winerror", None) != 740:  # serve l'elevazione: la chiede la shell (UAC)
            raise
        os.startfile(argomenti[0], "runas", subprocess.list2cmdline(argomenti[1:]))  # type: ignore[attr-defined]


def testo_note(markdown: str) -> str:
    """Le note della release, leggibili come testo semplice (titoli, grassetti e codice senza simboli).

    Le righe di un paragrafo o di una voce d'elenco si riuniscono: le note vanno a capo a ~110
    caratteri, e nella finestra, che va a capo da se', restavano spezzate a meta'."""
    righe: list[str] = []
    seguito = False  # la riga precedente e' testo a cui una riga normale si attacca
    for riga in markdown.replace("\r\n", "\n").split("\n"):
        titolo = re.match(r"^#{1,6}\s", riga) is not None
        voce = re.match(r"^\s*([-*]|\d+\.) ", riga) is not None
        riga = re.sub(r"^#{1,6}\s*", "", riga)
        riga = re.sub(r"^(\s*)[-*] ", r"\1• ", riga)
        riga = riga.replace("**", "").replace("`", "")
        riga = re.sub(r"(?<![\w*])\*(\S[^*]*?)\*(?![\w*])", r"\1", riga)  # *corsivo*
        if seguito and riga.strip() and not titolo and not voce:
            righe[-1] += " " + riga.strip()
            continue
        righe.append(riga.rstrip())
        seguito = bool(riga.strip()) and not titolo
    return "\n".join(righe).strip()
