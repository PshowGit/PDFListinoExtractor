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


def test_filtro_per_tipo_di_anomalia(tabella):
    from gui.preview_table import DA_VERIFICARE, TUTTE

    tipi = dict(tabella.tipi_anomalia())
    assert tipi["Duplicato"] == 2 and tipi["Prezzo mancante"] >= 1
    tabella.imposta_filtro("Duplicato")
    assert tabella.mostrate() == 2
    assert {tabella.articolo(i).codice for i in tabella.tree.get_children()} == {"(00123-A)"}
    tabella.imposta_filtro(DA_VERIFICARE)
    assert tabella.mostrate() == tabella.conteggi()[1]
    tabella.imposta_filtro(TUTTE)
    assert tabella.mostrate() == 9
    # il conteggio riguarda tutte le righe, non solo quelle mostrate
    tabella.imposta_filtro("Prezzo mancante")
    assert dict(tabella.tipi_anomalia()) == tipi


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


def _attendi(radice, condizione, secondi=60):
    import time

    limite = time.monotonic() + secondi
    while not condizione():
        if time.monotonic() > limite:
            raise AssertionError("tempo scaduto")
        radice.update()
        time.sleep(0.05)


def test_wizard_dalla_pdf_al_fornitore_salvato(radice, tmp_path, monkeypatch):
    from tkinter import messagebox

    import config
    from gui.wizard_fornitore import WizardFornitore
    from tests.sintetico_generico import crea_listino_generico

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    pdf = crea_listino_generico(tmp_path / "Listino ACME è.pdf")
    salvati = []
    w = WizardFornitore(radice, config.elenco_fornitori(), al_salvataggio=salvati.append, pdf=pdf)
    w.withdraw()
    _attendi(radice, lambda: w.modello is not None)  # analisi nel processo separato
    assert [m.get() for m in w._menu_colonne] == ["Codice", "Descrizione", "EAN", "Prezzo"]
    assert [n.get() for n in w._nomi_colonne] == ["SKU", "Description", "EAN", "Price EUR"]
    assert w.lbl_totale.cget("text") == "di 3"

    # un cambio di mappatura arriva al modello e si vede sulla pagina; il nome segue il ruolo
    w.seleziona_colonna(2)
    w.imposta_campo(2, "ignora")
    assert w.modello.campi[2] == "ignora" and w._nomi_colonne[2].get() == ""
    w.imposta_campo(2, "ean")
    assert w._nomi_colonne[2].get() == "EAN"

    w._anteprima()
    _attendi(radice, lambda: w._lavoro is None)
    assert [a.codice for a in w.tabella.articoli()] == ["SP-100", "SP-200", "SP-300", "0007-X", "AMP-1"]
    assert "5 articoli" in w.lbl_anteprima.cget("text")

    w.ent_nome.insert(0, "ACME Audio")
    assert w._salva()
    assert salvati == ["acme_audio"]
    assert (tmp_path / "PDFListinoExtractor" / "supplier_rules.json").read_bytes().startswith(b"\xef\xbb\xbf")
    assert config.elenco_fornitori()["acme_audio"] == "ACME Audio"


def test_wizard_con_pdf_non_valido_mostra_l_errore(radice, tmp_path, monkeypatch):
    from tkinter import messagebox

    from gui.wizard_fornitore import WizardFornitore

    errori = []
    monkeypatch.setattr(messagebox, "showerror", lambda titolo, testo, **k: errori.append(testo))
    rotto = tmp_path / "rotto.pdf"
    rotto.write_bytes(b"x" * 50)
    w = WizardFornitore(radice, {}, pdf=rotto)
    w.withdraw()
    _attendi(radice, lambda: errori)
    assert "PDF" in errori[0] and w.modello is None
    w.chiudi()


def test_il_fornitore_salvato_compare_e_si_seleziona_nella_finestra_principale(radice, tmp_path, monkeypatch):
    from config import salva_fornitore_personale
    from gui.main_window import FinestraPrincipale

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    radice.destroy()
    app = FinestraPrincipale()
    app.withdraw()
    try:
        salva_fornitore_personale("acme", {"nome": "ACME", "colonne": [{"campo": "codice"}, {"campo": "prezzo"}]})
        app._fornitore_salvato("acme")
        assert app.menu_fornitore.get() == "ACME" and app.chiave_fornitore == "acme"
        assert "ACME" in app.menu_fornitore.cget("values")
        assert app.regole["colonne"][0]["campo"] == "codice"
    finally:
        app.destroy()
    import customtkinter as ctk

    nuova = ctk.CTk()
    nuova.withdraw()
    radice.destroy = nuova.destroy


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


def test_il_dialogo_del_nome_parte_dal_nome_attuale(radice):
    from gui.dialoghi import DialogoTesto

    d = DialogoTesto(radice, "Rinomina fornitore", "Nuovo nome:", "ACME")
    assert d.campo.get() == "ACME"
    d.campo.delete(0, "end")
    d.campo.insert(0, "ACME Audio")
    d._conferma()  # come Invio o il pulsante OK
    assert d.risultato == "ACME Audio" and not d.winfo_exists()

    d = DialogoTesto(radice, "Rinomina fornitore", "Nuovo nome:", "ACME")
    d.destroy()  # come Esc, Annulla o la chiusura della finestra
    assert d.risultato is None and not d.winfo_exists()


def test_rinominare_e_rimuovere_un_fornitore_dalla_finestra_principale(radice, tmp_path, monkeypatch):
    from tkinter import messagebox

    import gui.main_window as finestra
    from config import salva_fornitore_personale

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    salva_fornitore_personale("acme", {"nome": "ACME", "colonne": [{"campo": "codice"}, {"campo": "prezzo"}]})
    avvisi = []
    monkeypatch.setattr(messagebox, "showwarning", lambda titolo, testo, **k: avvisi.append(testo))
    radice.destroy()
    app = finestra.FinestraPrincipale()
    app.withdraw()
    try:
        distribuito = app.fornitori["jbl_exhibo"]
        # il fornitore distribuito col programma e' in sola lettura
        assert app.chiave_fornitore == "jbl_exhibo"
        assert app.btn_rinomina.cget("state") == "disabled" and app.btn_rimuovi.cget("state") == "disabled"
        assert app.btn_modifica.cget("state") == "disabled"
        app._cambia_fornitore("ACME")
        assert app.btn_rinomina.cget("state") == "normal" and app.btn_rimuovi.cget("state") == "normal"
        assert app.btn_modifica.cget("state") == "normal"

        monkeypatch.setattr(finestra, "chiedi_testo", lambda *a, **k: "ACME Audio 2026")
        app._rinomina_fornitore()
        assert app.menu_fornitore.get() == "ACME Audio 2026" and app.chiave_fornitore == "acme"
        assert list(app.menu_fornitore.cget("values")) == [distribuito, "ACME Audio 2026"]
        assert app.regole["nome"] == "ACME Audio 2026"

        monkeypatch.setattr(finestra, "chiedi_testo", lambda *a, **k: distribuito.lower())
        app._rinomina_fornitore()
        assert "Esiste gia'" in avvisi[0] and app.menu_fornitore.get() == "ACME Audio 2026"

        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
        app._rimuovi_fornitore()
        assert "acme" in app.fornitori

        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        app._rimuovi_fornitore()
        assert list(app.fornitori) == ["jbl_exhibo"] and app.chiave_fornitore == "jbl_exhibo"
        assert list(app.menu_fornitore.cget("values")) == [distribuito]
        assert app.menu_fornitore.get() == distribuito
        assert app.btn_rimuovi.cget("state") == "disabled"
    finally:
        app.destroy()
    import customtkinter as ctk

    nuova = ctk.CTk()
    nuova.withdraw()
    radice.destroy = nuova.destroy


def test_wizard_in_modifica_riprende_e_aggiorna_il_fornitore(radice, tmp_path, monkeypatch):
    from tkinter import messagebox

    import config
    from gui.wizard_fornitore import WizardFornitore
    from processors.analisi_layout import analizza_pdf
    from processors.wizard import ModelloWizard
    from tests.sintetico_generico import crea_listino_generico

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    pdf = crea_listino_generico(tmp_path / "acme.pdf")
    m = ModelloWizard(analizza_pdf(str(pdf), 1))
    m.nome, m.formato_prezzo = "ACME", "it"
    m.imposta_campo(2, "ignora")
    config.salva_fornitore_personale("acme", {**m.profilo(), "escludi": ["PROMO"]})

    salvati = []
    w = WizardFornitore(radice, config.elenco_fornitori(), al_salvataggio=salvati.append, pdf=pdf,
                        modifica=("acme", config.profilo_personale("acme")))
    w.withdraw()
    _attendi(radice, lambda: w.modello is not None)
    assert "Modifica fornitore" in w.title() and w.btn_salva.cget("text") == "Salva modifiche"
    assert [x.get() for x in w._menu_colonne] == ["Codice", "Descrizione", "— ignora —", "Prezzo"]
    assert [x.get() for x in w._nomi_colonne] == ["SKU", "Description", "", "Price EUR"]
    assert w.ent_nome.get() == "ACME" and w.menu_formato.get() == "Italiano (1.234,56)"
    assert "4 colonne su 4 riprese" in w.lbl_stato.cget("text")

    w.imposta_campo(2, "ean")
    w.ent_nome.delete(0, "end")
    w.ent_nome.insert(0, "ACME Audio")
    assert w._salva()
    assert salvati == ["acme"]
    salvato = config.profilo_personale("acme")
    assert salvato["nome"] == "ACME Audio" and salvato["colonne"][2]["campo"] == "ean"
    assert salvato["escludi"] == ["PROMO"]  # cio' che il wizard non mostra resta
    assert set(config.chiavi_personali()) == {"acme"}


def test_tabella_con_le_colonne_dell_estrazione(radice):
    from gui.preview_table import PreviewTable
    from processors.models import Articolo, ColonnaUscita

    colonne = [ColonnaUscita("modello", "Articolo", "modello"), ColonnaUscita("testo_1", "Colore", "testo_generico"),
               ColonnaUscita("prezzo", "Listino", "prezzo")]
    regole = {"nome": "X", "colonne": [{"campo": "modello"}, {"campo": "testo_generico"}, {"campo": "prezzo"}]}
    t = PreviewTable(radice, regole)
    arts = [Articolo("B-2", prezzo=Decimal("5.00"), pagina=1, altri={"testo_1": "Rosso"}),
            Articolo("A-1", pagina=1, note_estrazione={"testo_1": "Testo in piu' a pagina 2"}),
            Articolo("C-3", prezzo=Decimal("2.50"), pagina=2)]
    t.carica(arts, colonne)
    assert t.tree["columns"] == ("modello", "testo_1", "prezzo", "pagina", "note")
    assert [t.tree.heading(c, "text") for c in ("modello", "testo_1", "prezzo")] == ["Articolo", "Colore", "Listino"]
    assert t.tree.item(t.tree.get_children()[0], "values")[:3] == ("B-2", "Rosso", "5,00")
    for _ in range(2):  # crescente e decrescente: il prezzo mancante resta in fondo
        t.ordina("prezzo")
        assert t.articoli()[-1].modello == "A-1"
    t.ordina("testo_1")
    assert [a.modello for a in t.articoli()][-1] == "B-2"  # "" < "rosso"
    iid = next(i for i in t.tree.get_children() if t.articolo(i).modello == "A-1")
    assert t.modifica_campo(iid, "testo_1", " Blu ")
    a = t.articolo(iid)
    assert a.altri["testo_1"] == "Blu" and "testo_1" not in a.note_estrazione
    assert a.anomalie == ["Prezzo mancante"]  # anomalie ricalcolate: il profilo prevede il prezzo


@pytest.mark.parametrize("variante", ["tre", "colore"])
def test_colonne_dinamiche_dal_pdf_all_excel(radice, tmp_path, variante):
    # tutto il percorso: proposta del wizard, profilo, estrazione, tabella, foglio "Listino"
    from exporters.excel_exporter import esporta_listino
    from gui.preview_table import PreviewTable
    from processors.analisi_layout import analizza_pdf
    from processors.wizard import ModelloWizard
    from tests.sintetico_generico import ATTESI_COLONNE, crea_listino_colonne

    intestazioni, righe = ATTESI_COLONNE[variante]
    pdf = crea_listino_colonne(tmp_path / f"{variante}.pdf", variante)
    m = ModelloWizard(analizza_pdf(str(pdf), 1))
    m.nome = "ACME"
    assert m.errori() == []
    profilo = m.profilo()
    ris = estrai_listino(pdf, profilo)
    assert [c.etichetta for c in ris.colonne] == intestazioni

    t = PreviewTable(radice, profilo)
    t.carica(ris.articoli, ris.colonne)
    assert [t.tree.heading(c, "text") for c in t.tree["columns"]] == [*intestazioni, "Pag.", "Anomalie"]
    assert not any(a.tutte_le_anomalie() for a in t.articoli())

    p = tmp_path / f"{variante}.xlsx"
    assert esporta_listino(t.articoli(), p, t.colonne) == len(righe)
    ws = load_workbook(p)["Listino"]
    assert [c.value for c in ws[1]] == intestazioni and ws.max_column == len(intestazioni)
    assert [list(r) for r in ws.iter_rows(min_row=2, values_only=True)] == righe
    if variante == "tre":
        assert not {"Codice", "EAN"} & set(intestazioni)
    else:
        assert ws.cell(2, intestazioni.index("Colour") + 1).number_format == "@"


def test_menu_del_filtro_coi_contatori(radice, tmp_path, monkeypatch, pdf_sintetico, regole):
    from gui.main_window import FinestraPrincipale

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    radice.destroy()
    app = FinestraPrincipale()
    app.withdraw()
    try:
        app.tabella.carica(estrai_listino(pdf_sintetico, regole).articoli)
        app._aggiorna_contatori()
        n, anomali = app.tabella.conteggi()
        voci = app.menu_filtro.cget("values")
        assert voci[:2] == [f"Tutte le righe ({n})", f"Da verificare ({anomali})"]
        assert "Duplicato (2)" in voci
        app._filtro("Duplicato (2)")
        assert app.tabella.mostrate() == 2 and app.menu_filtro.get() == "Duplicato (2)"
        assert app.lbl_conteggi.cget("text") == f"2 di {n} righe"
        # eliminare un duplicato aggiorna i contatori; il tipo scelto resta nel menu anche a zero
        app.tabella.tree.selection_set(app.tabella.tree.get_children()[0])
        app.tabella.elimina_selezionati()
        assert app.menu_filtro.get() == "Duplicato (0)" and app.tabella.mostrate() == 0
        assert f"Da verificare ({anomali - 2})" in app.menu_filtro.cget("values")
    finally:
        app.destroy()
    import customtkinter as ctk

    nuova = ctk.CTk()
    nuova.withdraw()
    radice.destroy = nuova.destroy


def test_dettaglio_con_le_colonne_del_documento(radice, tmp_path, monkeypatch):
    from gui.main_window import FinestraPrincipale
    from processors.models import Articolo, ColonnaUscita

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    radice.destroy()
    app = FinestraPrincipale()
    app.withdraw()
    try:
        colonne = [ColonnaUscita("modello", "Articolo", "modello"), ColonnaUscita("descrizione", "Descrizione", "descrizione"),
                   ColonnaUscita("prezzo", "Listino", "prezzo")]
        a = Articolo("VMHM4I", descrizione="Scheda input 4 canali HDMI", prezzo=Decimal("888.00"), pagina=22,
                     categoria="VISSONIC · MODULI INPUT")
        app.tabella.carica([a], colonne)
        app._mostra_dettaglio(a)
        testo = app.dettaglio.get("1.0", "end")
        assert "Articolo VMHM4I" in testo and "888,00 €" in testo and "Scheda input 4 canali HDMI" in testo
        assert "EAN" not in testo and "Codice" not in testo
    finally:
        app.destroy()
    import customtkinter as ctk

    nuova = ctk.CTk()
    nuova.withdraw()
    radice.destroy = nuova.destroy
