"""Finestra principale: selezione PDF, estrazione in background, anteprima ed esportazione."""
import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import config
from config import elenco_fornitori, regole_fornitore
from exporters.excel_exporter import EsportazioneFallita, esporta_listino, esporta_report_anomalie
from extractors.pdf_reader import InfoPdf, PdfNonValido, verifica_pdf
from gui.lavoro import LavoroInProcesso
from gui.page_viewer import FinestraPagina
from gui.preview_table import PreviewTable
from percorsi import icona
from processors.estrazione import RisultatoEstrazione
from processors.lavori import ESTRAZIONE
from processors.models import Articolo
from processors.price_parser import formatta_prezzo
from version import TITOLO_APP, __version__

log = logging.getLogger(__name__)


class FinestraPrincipale(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{TITOLO_APP} {__version__}")
        if icona().is_file():
            self.iconbitmap(str(icona()))
        self.geometry("1280x820")
        self.minsize(980, 640)

        self.fornitori = elenco_fornitori()
        self.chiave_fornitore = next(iter(self.fornitori))
        self.regole = regole_fornitore(self.chiave_fornitore)
        self.info_pdf: InfoPdf | None = None
        self._lavoro: LavoroInProcesso | None = None  # estrazione in corso
        self._wizard = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._sezione_pdf()
        self._sezione_elaborazione()
        self._sezione_anteprima()
        self._sezione_esportazione()
        self._aggiorna_pulsanti()
        self.protocol("WM_DELETE_WINDOW", self._chiudi)
        if config.avviso_regole_personali:
            self.after(300, lambda: messagebox.showwarning(
                "Regole personali ignorate", config.avviso_regole_personali, parent=self
            ))

    # --- A: selezione PDF ---------------------------------------------------------------------

    def _sezione_pdf(self):
        f = ctk.CTkFrame(self)
        f.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        f.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(f, text="1. Listino PDF", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=10, pady=(8, 2), sticky="w"
        )
        self.btn_seleziona = ctk.CTkButton(f, text="Seleziona PDF", command=self._seleziona_pdf, width=140)
        self.btn_seleziona.grid(row=1, column=0, padx=10, pady=(2, 10), sticky="w")
        ctk.CTkLabel(f, text="Fornitore:").grid(row=1, column=1, padx=(10, 4), pady=(2, 10))
        self.menu_fornitore = ctk.CTkOptionMenu(
            f, values=list(self.fornitori.values()), command=self._cambia_fornitore, width=280
        )
        self.menu_fornitore.grid(row=1, column=2, padx=4, pady=(2, 10), sticky="w")
        self.btn_wizard = ctk.CTkButton(
            f, text="Configura nuovo fornitore…", command=self._apri_wizard, width=200, fg_color="gray"
        )
        self.btn_wizard.grid(row=1, column=3, padx=10, pady=(2, 10), sticky="e")
        self.lbl_file = ctk.CTkLabel(f, text="Nessun file selezionato", anchor="w")
        self.lbl_file.grid(row=2, column=0, columnspan=3, padx=10, sticky="ew")
        self.lbl_info = ctk.CTkLabel(f, text="", anchor="w", text_color="gray")
        self.lbl_info.grid(row=3, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

    def _cambia_fornitore(self, nome: str):
        self.chiave_fornitore = next(k for k, v in self.fornitori.items() if v == nome)
        self.regole = regole_fornitore(self.chiave_fornitore)
        self.tabella.regole = self.regole

    def _seleziona_pdf(self):
        percorso = filedialog.askopenfilename(
            title="Seleziona il listino PDF", filetypes=[("PDF", "*.pdf"), ("Tutti i file", "*.*")]
        )
        if not percorso:
            return
        try:
            info = verifica_pdf(percorso, self.regole["ocr"]["caratteri_minimi_pagina"])
        except PdfNonValido as e:
            self.info_pdf = None
            self.lbl_file.configure(text=Path(percorso).name)
            self.lbl_info.configure(text=f"✖ {e}", text_color="#D9534F")
            self._aggiorna_pulsanti()
            return
        self.info_pdf = info
        self.lbl_file.configure(text=f"{info.percorso.name}   —   {info.percorso.parent}")
        tipo = (
            "scansionato: servira' l'OCR"
            if info.scansionato
            else f"testuale ({info.pagine_con_testo} pagine con testo selezionabile)"
        )
        self.lbl_info.configure(text=f"✔ PDF leggibile · {info.pagine} pagine · {tipo}", text_color="gray")
        self.tabella.carica([])
        self._aggiorna_contatori()
        self._aggiorna_pulsanti()

    # --- B: elaborazione ----------------------------------------------------------------------

    def _sezione_elaborazione(self):
        f = ctk.CTkFrame(self)
        f.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        f.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(f, text="2. Elaborazione", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=10, pady=(8, 2), sticky="w"
        )
        self.btn_estrai = ctk.CTkButton(f, text="Estrai articoli", command=self._avvia_estrazione, width=140)
        self.btn_estrai.grid(row=1, column=0, padx=10, pady=(2, 10))
        self.btn_annulla = ctk.CTkButton(
            f, text="Annulla", command=self._annulla_estrazione, width=90, fg_color="gray", state="disabled"
        )
        self.btn_annulla.grid(row=1, column=1, padx=4, pady=(2, 10))
        self.barra = ctk.CTkProgressBar(f)
        self.barra.set(0)
        self.barra.grid(row=1, column=2, padx=10, pady=(2, 10), sticky="ew")
        self.lbl_stato = ctk.CTkLabel(f, text="In attesa di un PDF", anchor="w", width=360)
        self.lbl_stato.grid(row=1, column=3, padx=10, pady=(2, 10), sticky="w")

    def _avvia_estrazione(self):
        if self.info_pdf is None or self._lavoro is not None:
            return
        self.barra.set(0)
        self.lbl_stato.configure(text="Avvio…")
        # in un processo e non in un thread: v. processors/lavori.py per il perche'
        self._lavoro = LavoroInProcesso(
            self,
            ESTRAZIONE,
            {"percorso": str(self.info_pdf.percorso), "regole": self.regole},
            alla_fine=self._estrazione_finita,
            all_errore=self._estrazione_fallita,
            al_progresso=self._progresso,
            all_annullamento=self._estrazione_annullata,
        ).avvia()
        self._aggiorna_pulsanti()

    def _annulla_estrazione(self):
        if self._lavoro is not None:
            self._lavoro.annulla()
            self.lbl_stato.configure(text="Annullamento in corso…")

    def _progresso(self, n: int, tot: int, art: int):
        self.barra.set(n / tot)
        self.lbl_stato.configure(text=f"Pagina {n} di {tot} · {art} articoli trovati")

    def _estrazione_annullata(self):
        self._lavoro = None
        self.lbl_stato.configure(text="Estrazione annullata")
        self.barra.set(0)
        self._aggiorna_pulsanti()

    def _estrazione_fallita(self, messaggio: str):
        self._lavoro = None
        self.lbl_stato.configure(text="Estrazione non riuscita")
        self._aggiorna_pulsanti()
        messagebox.showerror("Errore", messaggio, parent=self)

    def _estrazione_finita(self, ris: RisultatoEstrazione):
        self._lavoro = None
        self._aggiorna_pulsanti()
        self.tabella.carica(ris.articoli)
        self.barra.set(1)
        n, _ = self.tabella.conteggi()
        testo = f"Completato: {ris.pagine_totali} pagine · {n} articoli"
        if ris.pagine_ocr:
            testo += f" · {len(ris.pagine_ocr)} pagine via OCR"
        self.lbl_stato.configure(text=testo)
        self._aggiorna_contatori()
        if ris.avvisi:
            messagebox.showwarning("Avvisi dell'estrazione", "\n".join(ris.avvisi[:20]), parent=self)
        elif n == 0:
            messagebox.showwarning("Nessun articolo", "Nel PDF non e' stato riconosciuto alcun articolo.", parent=self)

    # --- C: anteprima -------------------------------------------------------------------------

    def _sezione_anteprima(self):
        f = ctk.CTkFrame(self)
        f.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        barra = ctk.CTkFrame(f, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        ctk.CTkLabel(barra, text="3. Anteprima", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
        self.lbl_conteggi = ctk.CTkLabel(barra, text="")
        self.lbl_conteggi.pack(side="left", padx=12)
        self.chk_anomalie = ctk.CTkCheckBox(barra, text="Solo righe con anomalie", command=self._filtro)
        self.chk_anomalie.pack(side="left", padx=12)
        self.btn_pagina = ctk.CTkButton(barra, text="Mostra pagina PDF", command=self._mostra_pagina, width=150)
        self.btn_pagina.pack(side="right", padx=4)
        self.btn_elimina = ctk.CTkButton(
            barra,
            text="Elimina righe selezionate",
            command=lambda: self.tabella.elimina_selezionati(chiedi_conferma=True),
            fg_color="#B04A4A",
            hover_color="#8E3B3B",
            width=190,
        )
        self.btn_elimina.pack(side="right", padx=4)

        self.tabella = PreviewTable(
            f, self.regole, on_change=self._aggiorna_contatori, on_select=self._mostra_dettaglio
        )
        self.tabella.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self.dettaglio = ctk.CTkTextbox(f, height=90, wrap="word")
        self.dettaglio.grid(row=2, column=0, sticky="ew", padx=6, pady=(4, 8))
        self.dettaglio.insert(
            "1.0",
            "Doppio clic su una cella per correggerla (la descrizione si apre in una finestra). "
            "Canc elimina le righe selezionate. Clic sull'intestazione per ordinare.",
        )
        self.dettaglio.configure(state="disabled")

    def _filtro(self):
        self.tabella.imposta_filtro_anomalie(bool(self.chk_anomalie.get()))

    def _aggiorna_contatori(self):
        n, anomali = self.tabella.conteggi()
        self.lbl_conteggi.configure(text=f"{n} articoli · {anomali} da verificare" if n else "")
        self._aggiorna_pulsanti()

    def _mostra_dettaglio(self, a: Articolo | None):
        self.dettaglio.configure(state="normal")
        self.dettaglio.delete("1.0", "end")
        if a is not None:
            righe = [
                (
                    f"{a.modello}   {a.codice}   EAN {a.ean or '—'}   ·   "
                    f"{formatta_prezzo(a.prezzo) or a.prezzo_testo or 'senza prezzo'} €   ·   "
                    f"pag. {a.pagina}   ·   {a.categoria}"
                ),
                a.descrizione,
            ]
            if a.tutte_le_anomalie():
                righe.append("⚠ " + " · ".join(a.tutte_le_anomalie()))
            self.dettaglio.insert("1.0", "\n".join(righe))
        self.dettaglio.configure(state="disabled")

    def _mostra_pagina(self):
        a = self.tabella.selezionato()
        if a is None or self.info_pdf is None:
            messagebox.showinfo("Mostra pagina", "Seleziona prima un articolo.", parent=self)
            return
        try:
            FinestraPagina(self, self.info_pdf.percorso, a)
        except Exception as e:
            log.exception("Anteprima pagina fallita")
            messagebox.showerror("Errore", f"Impossibile mostrare la pagina: {e}", parent=self)

    # --- D: esportazione ----------------------------------------------------------------------

    def _sezione_esportazione(self):
        f = ctk.CTkFrame(self)
        f.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 12))
        ctk.CTkLabel(f, text="4. Esportazione", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        self.btn_esporta = ctk.CTkButton(f, text="Esporta in Excel", command=self._esporta, width=160)
        self.btn_esporta.pack(side="left", padx=10, pady=10)
        self.btn_report = ctk.CTkButton(
            f, text="Report anomalie…", command=self._esporta_report, width=150, fg_color="gray"
        )
        self.btn_report.pack(side="left", padx=4, pady=10)

    def _nome_proposto(self, suffisso: str = "") -> str:
        base = self.info_pdf.percorso.stem if self.info_pdf else "listino"
        return f"{base}{suffisso}.xlsx"

    def _esporta(self):
        articoli = self.tabella.articoli()
        if not articoli:
            messagebox.showwarning("Esporta", "Non ci sono articoli da esportare.", parent=self)
            return
        _, anomali = self.tabella.conteggi()
        if anomali and not messagebox.askyesno(
            "Esporta",
            f"{anomali} righe hanno ancora anomalie da verificare.\nEsportare comunque?",
            parent=self,
        ):
            return
        percorso = filedialog.asksaveasfilename(
            title="Salva il listino in Excel",
            defaultextension=".xlsx",
            initialfile=self._nome_proposto(),
            filetypes=[("Cartella di lavoro Excel", "*.xlsx")],
            confirmoverwrite=True,  # chiede conferma prima di sovrascrivere
        )
        if not percorso:
            return
        try:
            n = esporta_listino(articoli, percorso)
        except EsportazioneFallita as e:
            messagebox.showerror("Esportazione non riuscita", str(e), parent=self)
            return
        log.info("Esportate %s righe in %s", n, percorso)
        messagebox.showinfo("Esportazione completata", f"Esportate {n} righe in:\n{percorso}", parent=self)

    def _esporta_report(self):
        articoli = self.tabella.articoli()
        if not any(a.tutte_le_anomalie() for a in articoli):
            messagebox.showinfo("Report anomalie", "Nessuna anomalia da riportare.", parent=self)
            return
        percorso = filedialog.asksaveasfilename(
            title="Salva il report delle anomalie",
            defaultextension=".xlsx",
            initialfile=self._nome_proposto("_anomalie"),
            filetypes=[("Cartella di lavoro Excel", "*.xlsx")],
            confirmoverwrite=True,
        )
        if not percorso:
            return
        try:
            n = esporta_report_anomalie(articoli, percorso)
        except EsportazioneFallita as e:
            messagebox.showerror("Esportazione non riuscita", str(e), parent=self)
            return
        messagebox.showinfo("Report salvato", f"{n} anomalie salvate in:\n{percorso}", parent=self)

    # --- stato --------------------------------------------------------------------------------

    def _aggiorna_pulsanti(self):
        occupato = self._lavoro is not None
        ha_dati = bool(self.tabella.articoli()) if hasattr(self, "tabella") else False
        def stato(attivo: bool) -> str:
            return "normal" if attivo else "disabled"

        self.btn_seleziona.configure(state=stato(not occupato))
        self.menu_fornitore.configure(state=stato(not occupato))
        self.btn_wizard.configure(state=stato(not occupato))
        self.btn_estrai.configure(state=stato(self.info_pdf is not None and not occupato))
        self.btn_annulla.configure(state=stato(occupato))
        if hasattr(self, "btn_esporta"):
            self.btn_esporta.configure(state=stato(ha_dati and not occupato))
            self.btn_report.configure(state=stato(ha_dati and not occupato))
            self.btn_elimina.configure(state=stato(ha_dati and not occupato))
            self.btn_pagina.configure(state=stato(ha_dati and not occupato))

    def _chiudi(self):
        if self._lavoro is not None:
            self._lavoro.termina()
        if self._wizard is not None and self._wizard.winfo_exists():
            self._wizard.chiudi()
        self.destroy()

    # --- wizard -------------------------------------------------------------------------------

    def _apri_wizard(self):
        from gui.wizard_fornitore import WizardFornitore

        if self._wizard is not None and self._wizard.winfo_exists():
            self._wizard.lift()
            return
        iniziale = self.info_pdf.percorso if self.info_pdf else None
        self._wizard = WizardFornitore(self, self.fornitori, al_salvataggio=self._fornitore_salvato, pdf=iniziale)

    def _fornitore_salvato(self, chiave: str):
        """Il wizard ha salvato un fornitore: lo si rende disponibile e lo si seleziona."""
        self.fornitori = elenco_fornitori()
        self.menu_fornitore.configure(values=list(self.fornitori.values()))
        self.menu_fornitore.set(self.fornitori[chiave])
        self._cambia_fornitore(self.fornitori[chiave])
