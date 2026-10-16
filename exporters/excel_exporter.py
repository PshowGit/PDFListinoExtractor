"""Scrittura del foglio "Listino" (solo le colonne richieste) e del report anomalie separato."""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from processors.models import CAMPI, INTESTAZIONI, Articolo

LARGHEZZE = {"modello": 30, "codice": 24, "ean": 16, "descrizione": 90, "prezzo": 14}
FORMATO_PREZZO = "#,##0.00"


class EsportazioneFallita(Exception):
    pass


def _salva(wb: Workbook, percorso: Path) -> None:
    try:
        wb.save(percorso)
    except PermissionError as e:
        raise EsportazioneFallita(
            f"Impossibile scrivere {percorso.name}: il file e' aperto in un altro programma (Excel?)."
        ) from e
    except OSError as e:
        raise EsportazioneFallita(f"Impossibile scrivere {percorso}: {e}") from e


def esporta_listino(articoli: list[Articolo], percorso: str | Path) -> int:
    """Scrive gli articoli nel foglio "Listino" e ritorna il numero di righe esportate."""
    if not articoli:
        raise EsportazioneFallita("Nessun articolo da esportare.")
    percorso = Path(percorso)
    wb = Workbook()
    ws = wb.active
    ws.title = "Listino"
    ws.append([INTESTAZIONI[c] for c in CAMPI])
    for cella in ws[1]:
        cella.font = Font(bold=True)
        cella.alignment = Alignment(vertical="center")

    for a in articoli:
        prezzo = float(a.prezzo) if a.prezzo is not None else None
        ws.append([a.modello, a.codice, a.ean, a.descrizione, prezzo])

    colonna = {c: i + 1 for i, c in enumerate(CAMPI)}
    for riga in ws.iter_rows(min_row=2):
        for campo in ("modello", "codice", "ean"):
            riga[colonna[campo] - 1].number_format = "@"  # testo: niente zeri iniziali persi
        riga[colonna["descrizione"] - 1].alignment = Alignment(wrap_text=True, vertical="top")
        riga[colonna["prezzo"] - 1].number_format = FORMATO_PREZZO
        for campo in ("modello", "codice", "ean", "prezzo"):
            riga[colonna[campo] - 1].alignment = Alignment(vertical="top")

    for campo, n in colonna.items():
        ws.column_dimensions[get_column_letter(n)].width = LARGHEZZE[campo]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    _salva(wb, percorso)
    return len(articoli)


def esporta_report_anomalie(articoli: list[Articolo], percorso: str | Path) -> int:
    """File separato, per la verifica: non tocca la struttura del foglio "Listino"."""
    percorso = Path(percorso)
    wb = Workbook()
    ws = wb.active
    ws.title = "Anomalie"
    ws.append(["Pagina", "Modello", "Codice", "Anomalia"])
    for cella in ws[1]:
        cella.font = Font(bold=True)
    righe = 0
    for a in articoli:
        for anomalia in a.tutte_le_anomalie():
            ws.append([a.pagina, a.modello, a.codice, anomalia])
            righe += 1
    for lettera, w in zip("ABCD", (8, 30, 24, 90)):
        ws.column_dimensions[lettera].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    _salva(wb, percorso)
    return righe
