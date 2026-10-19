"""Unica fonte della versione e dell'identita' del programma.

La leggono l'applicazione (titolo della finestra), il file .spec (proprieta' dell'eseguibile) e
scripts/build_installer.bat (versione dell'installer). Per cambiarla:
    uv run python scripts/imposta_versione.py 1.2.0
che aggiorna anche pyproject.toml.
"""

__version__ = "1.3.0"

NOME_APP = "PDFListinoExtractor"
TITOLO_APP = "Estrattore listini PDF"
DESCRIZIONE = "Estrazione di listini prezzi PDF in Excel"
# Lasciato vuoto di proposito: va indicato solo un editore reale. Se valorizzato, compare nelle
# proprieta' dell'eseguibile e in "App installate" di Windows.
EDITORE = ""
