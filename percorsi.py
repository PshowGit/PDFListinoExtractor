"""Dove il programma legge le risorse e dove scrive i propri dati.

Le risorse (configurazione predefinita, icona) stanno accanto al codice, o nella cartella
dell'eseguibile quando e' impacchettato con PyInstaller: in un'installazione in Program Files
sono in sola lettura. Tutto cio' che il programma scrive (log, configurazione personale) va in
%LOCALAPPDATA%\\PDFListinoExtractor, che resta intatto anche dopo una disinstallazione.
"""
import os
import sys
from pathlib import Path

from version import NOME_APP


def impacchettato() -> bool:
    return bool(getattr(sys, "frozen", False))


def cartella_risorse() -> Path:
    if impacchettato():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def cartella_dati_utente() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    cartella = Path(base) / NOME_APP
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def cartella_log() -> Path:
    # in sviluppo i log restano nel progetto, dove li cerca chi ci lavora
    cartella = cartella_dati_utente() / "logs" if impacchettato() else cartella_risorse() / "logs"
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def icona() -> Path:
    return cartella_risorse() / "assets" / "icona.ico"
