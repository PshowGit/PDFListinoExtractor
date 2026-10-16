"""Collaudo automatico dell'interfaccia vera, utilizzabile anche sull'eseguibile installato.

    PDFListinoExtractor.exe --collaudo <pdf> <file.xlsx>

Apre la finestra principale, carica il PDF, estrae col processo separato come farebbe l'utente,
esporta in Excel, salva uno screenshot e un report JSON accanto al file Excel, poi chiude.
Codice di uscita 0 se tutto e' andato a buon fine. Non cambia nulla nell'uso normale.
"""
import itertools
import json
import sys
import time
import traceback
from pathlib import Path

OPZIONE = "--collaudo"


def collaudo_richiesto(argv: list[str]) -> bool:
    return OPZIONE in argv


def esegui_collaudo(argv: list[str]) -> int:
    i = argv.index(OPZIONE)
    pdf, xlsx = Path(argv[i + 1]), Path(argv[i + 2])
    report_path = xlsx.with_suffix(".collaudo.json")
    report: dict = {"pdf": str(pdf), "xlsx": str(xlsx), "esito": "fallito"}
    try:
        _collauda(pdf, xlsx, report)
    except Exception as e:
        report["errore"] = f"{type(e).__name__}: {e}"
        report["traceback"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["esito"] == "ok" else 1


def _collauda(pdf: Path, xlsx: Path, report: dict) -> None:
    from openpyxl import load_workbook
    from PIL import ImageGrab

    from exporters.excel_exporter import esporta_listino
    from extractors.pdf_reader import PdfNonValido, verifica_pdf
    from gui.main_window import FinestraPrincipale
    from percorsi import cartella_log, impacchettato
    from version import __version__

    report.update(versione=__version__, impacchettato=impacchettato(), eseguibile=sys.executable,
                  log=str(cartella_log() / "app.log"))
    app = FinestraPrincipale()
    app.geometry("1400x860+20+20")
    report["titolo_finestra"] = app.title()
    report["fornitori"] = list(app.fornitori)
    try:
        app.info_pdf = verifica_pdf(pdf)
    except PdfNonValido as e:
        # anche un PDF non valido e' un esito di collaudo: il messaggio deve essere leggibile
        report.update(esito="pdf_non_valido", messaggio=str(e))
        app.destroy()
        return
    app._aggiorna_pulsanti()
    battiti: list[float] = []
    tempi: dict[str, float] = {}

    def battito():
        battiti.append(time.perf_counter())
        if app._lavoro is not None:
            app.after(50, battito)

    def avvia():
        tempi["inizio"] = time.perf_counter()
        app._avvia_estrazione()
        battito()

    def fine():
        if app._lavoro is not None or "inizio" not in tempi:
            app.after(100, fine)
            return
        try:
            tempi["fine"] = time.perf_counter()
            app.update()
            articoli = app.tabella.articoli()
            n_esportate = esporta_listino(articoli, xlsx)
            ws = load_workbook(xlsx)["Listino"]
            x, y = app.winfo_rootx(), app.winfo_rooty()
            ImageGrab.grab((x, y, x + app.winfo_width(), y + app.winfo_height())).save(
                xlsx.with_suffix(".collaudo.png")
            )
            pause = [round((b - a) * 1000) for a, b in itertools.pairwise(battiti)]
            report.update(
                stato=app.lbl_stato.cget("text"),
                articoli=len(articoli),
                da_verificare=sum(1 for a in articoli if a.tutte_le_anomalie()),
                righe_esportate=n_esportate,
                righe_excel=ws.max_row - 1,
                intestazioni_excel=[c.value for c in ws[1]],
                prima_riga_excel=[c.value for c in ws[2]] if ws.max_row > 1 else None,
                durata_s=round(tempi["fine"] - tempi["inizio"], 2),
                pausa_massima_ms=max(pause, default=0),
            )
            ok = articoli and n_esportate == len(articoli) == ws.max_row - 1
            report["esito"] = "ok" if ok else "fallito"
        except Exception as e:
            report["errore"] = f"{type(e).__name__}: {e}"
            report["traceback"] = traceback.format_exc()
        finally:
            app.destroy()

    app.after(300, avvia)
    app.after(600, fine)
    app.mainloop()
