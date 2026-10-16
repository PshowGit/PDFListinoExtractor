"""Test dell'anteprima senza mostrarla: crea la finestra Tk, la usa e la distrugge."""
import tkinter as tk
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from exporters.excel_exporter import esporta_listino
from processors.estrazione import estrai_listino


@pytest.fixture
def radice():
    try:
        import customtkinter as ctk

        root = ctk.CTk()
    except tk.TclError as e:
        pytest.skip(f"nessun display disponibile: {e}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tabella(radice, pdf_sintetico, regole):
    from gui.preview_table import PreviewTable

    t = PreviewTable(radice, regole)
    t.carica(estrai_listino(pdf_sintetico, regole).articoli)
    return t


def test_righe_esportate_uguali_ai_record_approvati(tabella, tmp_path):
    ids = tabella.tree.get_children()
    assert len(ids) == 9
    tabella.tree.selection_set(ids[1:3])
    assert tabella.elimina_selezionati() == 2
    p = tmp_path / "approvati.xlsx"
    assert esporta_listino(tabella.articoli(), p) == 7
    assert load_workbook(p)["Listino"].max_row == 8  # 7 righe + intestazione


def test_il_filtro_anomalie_non_riduce_l_esportazione(tabella):
    tabella.imposta_filtro_anomalie(True)
    mostrate = len(tabella.tree.get_children())
    assert 0 < mostrate < 9
    assert len(tabella.articoli()) == 9


def test_correggere_il_prezzo_toglie_l_anomalia(tabella):
    iid = next(i for i in tabella.tree.get_children() if tabella.articolo(i).codice == "(SPK-003)")
    assert tabella.articolo(iid).tutte_le_anomalie()
    assert tabella.modifica_campo(iid, "prezzo", "1.090,50")
    a = tabella.articolo(iid)
    assert a.prezzo == Decimal("1090.50") and not a.tutte_le_anomalie()
    assert not tabella.modifica_campo(iid, "prezzo", "boh")
    assert a.prezzo == Decimal("1090.50")


def test_eliminare_un_duplicato_aggiorna_l_altro(tabella):
    dup = [i for i in tabella.tree.get_children() if tabella.articolo(i).codice == "(00123-A)"]
    assert len(dup) == 2
    tabella.tree.selection_set(dup[1])
    tabella.elimina_selezionati()
    assert not any("Duplicato" in x for x in tabella.articolo(dup[0]).tutte_le_anomalie())


def test_ordinamento_per_prezzo_con_mancanti_in_fondo(tabella):
    tabella.ordina("prezzo")
    prezzi = [a.prezzo for a in tabella.articoli()]
    validi = [p for p in prezzi if p is not None]
    assert validi == sorted(validi) and prezzi[-1] is None
    tabella.ordina("prezzo")
    prezzi = [a.prezzo for a in tabella.articoli()]
    assert [p for p in prezzi if p is not None] == sorted(validi, reverse=True) and prezzi[-1] is None


def test_la_finestra_principale_si_costruisce(radice):
    from gui.main_window import FinestraPrincipale

    radice.destroy()
    app = FinestraPrincipale()
    app.withdraw()
    try:
        assert app.btn_estrai.cget("state") == "disabled"
        assert app.btn_esporta.cget("state") == "disabled"
    finally:
        app.destroy()
    # la fixture distruggera' una radice gia' distrutta: si ricrea per simmetria
    import customtkinter as ctk

    nuova = ctk.CTk()
    nuova.withdraw()
    radice.destroy = nuova.destroy
