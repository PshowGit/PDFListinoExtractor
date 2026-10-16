"""Avvio dell'applicazione: log su file, poi la finestra principale."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Nell'eseguibile senza console stdout/stderr non esistono: una libreria che ci scrive anche solo
# un avviso farebbe cadere il programma senza alcun messaggio.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

log = logging.getLogger("main")


def configura_log() -> None:
    from percorsi import cartella_log

    gestore = RotatingFileHandler(cartella_log() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    gestore.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[gestore])


def mostra_errore(titolo: str, messaggio: str) -> None:
    """Messaggio all'utente anche quando la finestra principale non esiste (ancora)."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        radice = tk.Tk()
        radice.withdraw()
        messagebox.showerror(titolo, messaggio, parent=radice)
        radice.destroy()
    except Exception:
        log.exception("Impossibile mostrare il messaggio di errore: %s", messaggio)


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()  # l'estrazione gira in un processo figlio, anche nell'eseguibile
    try:
        configura_log()
    except OSError as e:
        mostra_errore("Avvio non riuscito", f"Impossibile creare la cartella dei log:\n{e}")
        return 1
    from version import TITOLO_APP, __version__

    log.info("Avvio %s %s (impacchettato=%s)", TITOLO_APP, __version__, getattr(sys, "frozen", False))
    try:
        import customtkinter as ctk

        from gui.collaudo import collaudo_richiesto, esegui_collaudo
        from gui.main_window import FinestraPrincipale

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        if collaudo_richiesto(sys.argv):
            return esegui_collaudo(sys.argv)
        app = FinestraPrincipale()
        app.mainloop()
        return 0
    except Exception as e:
        from percorsi import cartella_log

        log.exception("Errore non gestito")
        mostra_errore(
            "Errore imprevisto",
            f"Il programma ha incontrato un errore e deve chiudersi:\n{e}\n\n"
            f"Dettagli nel file di log:\n{cartella_log() / 'app.log'}",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
