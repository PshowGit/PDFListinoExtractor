"""Collaudo dell'interfaccia dal sorgente: stesso percorso di `PDFListinoExtractor.exe --collaudo`.

    uv run python tools/prova_gui.py <pdf> <file.xlsx>

Il report e lo screenshot finiscono accanto al file Excel (.collaudo.json / .collaudo.png).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":  # obbligatorio: il processo di estrazione reimporta questo modulo
    import customtkinter as ctk

    from gui.collaudo import esegui_collaudo

    ctk.set_appearance_mode("light")
    codice = esegui_collaudo(["", "--collaudo", sys.argv[1], sys.argv[2]])
    print(Path(sys.argv[2]).with_suffix(".collaudo.json").read_text(encoding="utf-8"))
    sys.exit(codice)
