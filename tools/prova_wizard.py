"""Collaudo visivo del wizard: lo apre su un PDF, attende l'analisi, esegue l'anteprima, cattura la finestra.

    uv run python tools/prova_wizard.py <pdf> <immagine.png> [pagina]

Non salva nulla: il fornitore resta solo nella finestra, che poi si chiude.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def collauda(pdf: Path, immagine: Path, pagina: int) -> None:
    import customtkinter as ctk
    from PIL import ImageGrab

    import config
    from gui.wizard_fornitore import WizardFornitore

    ctk.set_appearance_mode("light")
    radice = ctk.CTk()
    radice.withdraw()
    w = WizardFornitore(radice, config.elenco_fornitori())
    w.geometry("1440x920+10+10")
    w.attributes("-topmost", True)  # la cattura riprende solo questa finestra, non cio' che sta sotto
    w.pdf, w.pagina = pdf, pagina

    def attendi(condizione, secondi=60):
        limite = time.monotonic() + secondi
        while not condizione():
            if time.monotonic() > limite:
                raise SystemExit("tempo scaduto")
            radice.update()
            time.sleep(0.05)

    w._analizza()
    attendi(lambda: w.modello is not None)
    w.seleziona_colonna(0)
    t0 = time.perf_counter()
    w._anteprima()
    attendi(lambda: w._lavoro is None)
    durata = time.perf_counter() - t0
    for _ in range(10):
        radice.update()
        time.sleep(0.05)
    x, y = w.winfo_rootx(), w.winfo_rooty()
    ImageGrab.grab((x, y, x + w.winfo_width(), y + w.winfo_height())).save(immagine)
    print("colonne:", [(c.etichetta, campo) for c, campo in zip(w.modello.analisi.colonne, w.modello.campi, strict=True)])
    print("ancora:", w.modello.ancora, "| anteprima:", w.lbl_anteprima.cget("text"), f"| {durata:.1f} s")
    w.chiudi()
    radice.destroy()


if __name__ == "__main__":  # obbligatorio: il processo di analisi reimporta questo modulo
    collauda(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 1)
