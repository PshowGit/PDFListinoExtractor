"""Cambia la versione del programma in tutti i punti in cui compare.

    uv run python scripts/imposta_versione.py 1.2.0

Aggiorna version.py (la fonte che leggono applicazione, .spec e installer) e pyproject.toml.
Dopo, rigenerare i pacchetti con scripts\\build_exe.bat e scripts\\build_installer.bat.
"""
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
FORMATO = re.compile(r"^\d+\.\d+\.\d+$")


def sostituisci(percorso: Path, schema: str, nuova: str) -> None:
    testo = percorso.read_text(encoding="utf-8")
    aggiornato, n = re.subn(schema, lambda m: m.group(1) + nuova + m.group(3), testo, count=1, flags=re.MULTILINE)
    if n != 1:
        sys.exit(f"ERRORE: versione non trovata in {percorso}")
    percorso.write_text(aggiornato, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or not FORMATO.match(sys.argv[1]):
        sys.exit("Uso: imposta_versione.py MAGGIORE.MINORE.CORREZIONE   (es. 1.2.0)")
    nuova = sys.argv[1]
    sostituisci(RADICE / "version.py", r'^(__version__ = ")([^"]+)(")', nuova)
    sostituisci(RADICE / "pyproject.toml", r'^(version = ")([^"]+)(")', nuova)
    print(f"Versione impostata a {nuova}")


if __name__ == "__main__":
    main()
