"""Finestra principale: selezione PDF, estrazione in background, anteprima ed esportazione."""
import logging
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import config
from config import elenco_fornitori, regole_fornitore
from exporters.excel_exporter import EsportazioneFallita, esporta_listino, esporta_report_anomalie
from extractors.pdf_reader import InfoPdf, PdfNonValido, verifica_pdf
from gui.dialoghi import FinestraAvvisi, chiedi_testo, in_primo_piano
from gui.lavoro import LavoroInProcesso
from gui.page_viewer import FinestraPagina
from gui.pannelli import pannello_diviso
from gui.preview_table import DA_VERIFICARE, TUTTE, PreviewTable, testo_cella
from percorsi import icona
from processors.estrazione import RisultatoEstrazione
from processors.lavori import ESTRAZIONE
from processors.models import Articolo
from processors.price_parser import formatta_prezzo
from version import TITOLO_APP, __version__

log = logging.getLogger(__name__)
# quota della barra per la prima passata (lettura del testo): misurato 70% del tempo sul JBL, 76% sull'Etabeta
PESO_LETTURA = 0.7


def _durata(secondi: float) -> str:
    secondi = round(secondi)
    return f"{secondi} s" if secondi < 60 else f"{secondi // 60} min {secondi % 60:02d} s"


class FinestraPrincipale(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{TITOLO_APP} {__version__}")
        if icona().is_file():
            self.iconbitmap(str(icona()))
        self.geometry("1280x820")
        self.minsize(1040, 640)  # la riga del fornitore: menu, tre pulsanti e il wizard

        self.fornitori = elenco_fornitori()
        self.personali = config.chiavi_personali()  # i soli che si possono rinominare o rimuovere
        self.chiave_fornitore = next(iter(self.fornitori))
        self.regole = regole_fornitore(self.chiave_fornitore)
        self.info_pdf: InfoPdf | None = None
        self._lavoro: LavoroInProcesso | None = None  # estrazione in corso
        self._wizard = None
        self.avvisi: list[str] = []  # dell'ultima estrazione
        self._finestra_avvisi = None

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
        scelta = ctk.CTkFrame(f, fg_color="transparent")
        scelta.grid(row=1, column=2, padx=4, pady=(2, 10), sticky="w")
        self.menu_fornitore = ctk.CTkOptionMenu(
            scelta, values=list(self.fornitori.values()), command=self._cambia_fornitore, width=280
        )
        self.menu_fornitore.pack(side="left")
        self.btn_modifica = ctk.CTkButton(
            scelta, text="Modifica…", command=self._modifica_fornitore, width=80, fg_color="gray"
        )
        self.btn_modifica.pack(side="left", padx=(8, 0))
        self.btn_rinomina = ctk.CTkButton(
            scelta, text="Rinomina…", command=self._rinomina_fornitore, width=85, fg_color="gray"
        )
        self.btn_rinomina.pack(side="left", padx=(6, 0))
        self.btn_rimuovi = ctk.CTkButton(
            scelta, text="Rimuovi", command=self._rimuovi_fornitore, width=80,
            fg_color="#B04A4A", hover_color="#8E3B3B",
        )
        self.btn_rimuovi.pack(side="left", padx=(6, 0))
        self.btn_wizard = ctk.CTkButton(
            f, text="Configura nuovo fornitore…", command=self._apri_wizard, width=200, fg_color="gray"
        )
        self.btn_wizard.grid(row=1, column=3, padx=10, pady=(2, 10), sticky="e")
        self.lbl_file = ctk.CTkLabel(f, text="Nessun file selezionato", anchor="w")
        self.lbl_file.grid(row=2, column=0, columnspan=3, padx=10, sticky="ew")
        self.lbl_info = ctk.CTkLabel(f, text="", anchor="w", text_color="gray")
        self.lbl_info.grid(row=3, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

    def _cambia_fornitore(self, nome: str):
        self._imposta_fornitore(next(k for k, v in self.fornitori.items() if v == nome))

    def _imposta_fornitore(self, chiave: str):
        self.chiave_fornitore = chiave
        self.menu_fornitore.set(self.fornitori[chiave])
        self.regole = regole_fornitore(chiave)
        self.tabella.regole = self.regole
        self._aggiorna_pulsanti()

    def _ricarica_fornitori(self, seleziona: str):
        """Rilegge l'elenco dopo un salvataggio, una rinomina o una rimozione e seleziona `seleziona`,
        o il predefinito se non c'e' piu'."""
        self.fornitori = elenco_fornitori()
        self.personali = config.chiavi_personali()
        self.menu_fornitore.configure(values=list(self.fornitori.values()))
        self._imposta_fornitore(seleziona if seleziona in self.fornitori else next(iter(self.fornitori)))
        if self._wizard is not None and self._wizard.winfo_exists():
            self._wizard.aggiorna_fornitori(self.fornitori)

    def _modifica_fornitore(self):
        chiave = self.chiave_fornitore
        try:
            profilo = config.profilo_personale(chiave)
        except (OSError, ValueError, KeyError) as e:
            log.exception("Lettura del fornitore da modificare non riuscita")
            messagebox.showerror("Modifica fornitore", str(e), parent=self)
            return
        self._apri_wizard(modifica=(chiave, profilo))

    def _rinomina_fornitore(self):
        chiave = self.chiave_fornitore
        attuale = self.fornitori[chiave]
        nome = chiedi_testo(self, "Rinomina fornitore", f"Nuovo nome per «{attuale}»:", attuale)
        if nome is None or nome.strip() == attuale:
            return
        try:
            config.rinomina_fornitore_personale(chiave, nome)
        except config.NomeNonValido as e:
            messagebox.showwarning("Rinomina fornitore", str(e), parent=self)
            return
        except (OSError, ValueError, KeyError) as e:
            log.exception("Rinomina del fornitore non riuscita")
            messagebox.showerror("Rinomina non riuscita", str(e), parent=self)
            return
        self._ricarica_fornitori(chiave)

    def _rimuovi_fornitore(self):
        chiave = self.chiave_fornitore
        nome = self.fornitori[chiave]
        if not messagebox.askyesno(
            "Rimuovi fornitore",
            f"Rimuovere il fornitore «{nome}» e le sue regole?\n\n"
            f"La versione precedente del file resta nella copia di sicurezza:\n"
            f"{config.percorso_regole_personali().with_suffix('.json.bak')}",
            icon="warning",
            parent=self,
        ):
            return
        try:
            config.rimuovi_fornitore_personale(chiave)
        except (OSError, ValueError, KeyError) as e:
            log.exception("Rimozione del fornitore non riuscita")
            messagebox.showerror("Rimozione non riuscita", str(e), parent=self)
            return
        self._ricarica_fornitori(chiave)
        if chiave in self.fornitori:  # sostituiva un fornitore distribuito col programma, che torna in uso
            messagebox.showinfo(
                "Rimuovi fornitore",
                f"Torna in uso la configurazione distribuita col programma: «{self.fornitori[chiave]}».",
                parent=self,
            )

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
        self.tabella.imposta_filtro(TUTTE)
        self.tabella.carica([])
        self.avvisi = []  # erano del PDF di prima
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
        self.lbl_stato = ctk.CTkLabel(f, text="In attesa di un PDF", anchor="w", width=420)
        self.lbl_stato.grid(row=1, column=3, padx=10, pady=(2, 10), sticky="w")
        self.btn_avvisi = ctk.CTkButton(f, text="Avvisi…", command=self._mostra_avvisi, width=110, fg_color="gray")
        self.btn_avvisi.grid(row=1, column=4, padx=(4, 10), pady=(2, 10))

    def _avvia_estrazione(self):
        if self.info_pdf is None or self._lavoro is not None:
            return
        self.barra.set(0)
        self.lbl_stato.configure(text="Avvio…")
        self._inizio = time.monotonic()
        # in un processo e non in un thread: v. processors/lavori.py per il perche'
        self._lavoro = LavoroInProcesso(
            self,
            ESTRAZIONE,
            {"percorso": str(self.info_pdf.percorso), "regole": self.regole},
            alla_fine=self._estrazione_finita,
            all_errore=self._estrazione_fallita,
            al_progresso=self._progresso,
            all_annullamento=self._estrazione_annullata,
            alla_lettura=self._lettura,
        ).avvia()
        self._aggiorna_pulsanti()

    def _annulla_estrazione(self):
        if self._lavoro is not None:
            self._lavoro.annulla()
            self.lbl_stato.configure(text="Annullamento in corso…")

    def _lettura(self, n: int, tot: int):
        """Prima passata: la barra va da 0 a PESO_LETTURA mentre si legge il testo delle pagine."""
        frazione = PESO_LETTURA * n / tot
        self.barra.set(frazione)
        # dopo l'ultima pagina, prima dell'analisi, si calcolano le statistiche del documento (circa 1 s
        # sull'Etabeta): senza dirlo, la scritta restava ferma su «Lettura pagina 387 di 387»
        fase = "Lettura completata: statistiche del documento…" if n == tot else f"Lettura pagina {n} di {tot}"
        self.lbl_stato.configure(text=fase + self._tempi(frazione))

    def _progresso(self, n: int, tot: int, art: int):
        """Seconda passata: l'analisi delle pagine lette, da PESO_LETTURA alla fine."""
        frazione = PESO_LETTURA + (1 - PESO_LETTURA) * n / tot
        self.barra.set(frazione)
        self.lbl_stato.configure(text=f"Analisi pagina {n} di {tot} · {art} articoli{self._tempi(frazione)}")

    def _tempi(self, frazione: float) -> str:
        """Tempo trascorso e, quando la stima ha senso, quello che resta, in proporzione a quanto fatto."""
        trascorso = time.monotonic() - getattr(self, "_inizio", time.monotonic())
        testo = f" · {_durata(trascorso)}"
        if frazione >= 0.05 and trascorso >= 1:
            residuo = trascorso * (1 - frazione) / frazione
            testo += f" · ancora circa {_durata(residuo)}" if residuo >= 1 else " · quasi finito"
        return testo

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
        self.tabella.imposta_filtro(TUTTE)  # un'estrazione nuova si guarda dall'inizio
        self.tabella.carica(ris.articoli, ris.colonne)  # le colonne che il documento ha
        self.barra.set(1)
        n, _ = self.tabella.conteggi()
        testo = f"Completato: {ris.pagine_totali} pagine · {n} articoli"
        if ris.pagine_ocr:
            testo += f" · {len(ris.pagine_ocr)} pagine via OCR"
        testo += f" · {_durata(time.monotonic() - getattr(self, '_inizio', time.monotonic()))}"
        self.lbl_stato.configure(text=testo)
        self.avvisi = list(ris.avvisi)
        self._aggiorna_contatori()
        if ris.avvisi:
            self._mostra_avvisi()  # tutti, in una finestra che non blocca: si puo' riaprire da «Avvisi»
        elif n == 0:
            messagebox.showwarning("Nessun articolo", "Nel PDF non e' stato riconosciuto alcun articolo.", parent=self)

    def _mostra_avvisi(self):
        if not self.avvisi:
            return
        if self._finestra_avvisi is not None and self._finestra_avvisi.winfo_exists():
            self._finestra_avvisi.destroy()
        self._finestra_avvisi = FinestraAvvisi(self, self.avvisi)

    # --- C: anteprima -------------------------------------------------------------------------

    def _sezione_anteprima(self):
        f = ctk.CTkFrame(self)
        f.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        barra = ctk.CTkFrame(f, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        ctk.CTkLabel(barra, text="3. Anteprima", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
        ctk.CTkLabel(barra, text="Mostra:").pack(side="left", padx=(16, 4))
        # tutte le righe, quelle da verificare o un tipo di anomalia, ognuno col suo conteggio
        self._voci_filtro: dict[str, str | None] = {"Tutte le righe": TUTTE}
        self.menu_filtro = ctk.CTkOptionMenu(barra, values=list(self._voci_filtro), command=self._filtro,
                                             width=260, dynamic_resizing=False)
        self.menu_filtro.pack(side="left")
        self.lbl_conteggi = ctk.CTkLabel(barra, text="")  # le righe mostrate su quelle estratte
        self.lbl_conteggi.pack(side="left", padx=10)
        self.btn_pagina = ctk.CTkButton(barra, text="Mostra pagina PDF", command=self._mostra_pagina, width=150)
        self.btn_pagina.pack(side="right", padx=4)
        self.btn_elimina = ctk.CTkButton(
            barra,
            text="Elimina selezionate",
            command=lambda: self.tabella.elimina_selezionati(chiedi_conferma=True),
            fg_color="#B04A4A",
            hover_color="#8E3B3B",
            width=150,
        )
        self.btn_elimina.pack(side="right", padx=4)

        # tabella e dettaglio divisi da un separatore trascinabile: il dettaglio di una descrizione lunga si legge
        # alzandolo, la tabella si allarga abbassandolo
        self.pannello = pannello_diviso(f, verticale=True)
        self.pannello.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 8))
        self.tabella = PreviewTable(
            self.pannello, self.regole, on_change=self._aggiorna_contatori, on_select=self._mostra_dettaglio
        )
        self.dettaglio = ctk.CTkTextbox(self.pannello, height=90, wrap="word")
        self.pannello.add(self.tabella, minsize=120, stretch="always")
        self.pannello.add(self.dettaglio, minsize=48, height=90, stretch="never")
        self.dettaglio.insert(
            "1.0",
            "Doppio clic o Invio (F2) per correggere la cella; ← → scelgono la colonna (segnata con ▸). "
            "Nella correzione Invio conferma e scende, Tab passa alla cella accanto, Esc annulla; la descrizione "
            "si apre in una finestra (Ctrl+Invio salva). F8 va alla prossima riga da verificare, Maiusc+F8 alla "
            "precedente. Canc elimina le righe selezionate. Clic sull'intestazione per ordinare.",
        )
        self.dettaglio.configure(state="disabled")

    def _filtro(self, voce: str):
        self.tabella.imposta_filtro(self._voci_filtro.get(voce, TUTTE))
        self._aggiorna_contatori()

    def _aggiorna_contatori(self):
        """Contatori e voci del filtro, ricalcolati dopo ogni estrazione, correzione o eliminazione."""
        n, anomali = self.tabella.conteggi()
        filtro = self.tabella.filtro
        tipi = self.tabella.tipi_anomalia()
        if filtro not in (TUTTE, DA_VERIFICARE) and filtro not in dict(tipi):
            tipi.append((filtro, 0))  # il tipo scelto resta nel menu anche quando non ne restano piu'
        voci = {f"Tutte le righe ({n})": TUTTE, f"Da verificare ({anomali})": DA_VERIFICARE}
        voci.update({f"{tipo} ({k})": tipo for tipo, k in tipi})
        self._voci_filtro = voci
        self.menu_filtro.configure(values=list(voci))
        self.menu_filtro.set(next(voce for voce, f in voci.items() if f == filtro))
        if not n:
            testo = ""
        elif filtro is TUTTE:
            testo = f"{n} righe · {anomali} da verificare"
        else:
            testo = f"{self.tabella.mostrate()} di {n} righe"
        self.lbl_conteggi.configure(text=testo)
        self._aggiorna_pulsanti()

    def _mostra_dettaglio(self, a: Articolo | None):
        self.dettaglio.configure(state="normal")
        self.dettaglio.delete("1.0", "end")
        if a is not None:
            colonne = self.tabella.colonne
            dati = "   ".join(f"{c.etichetta} {testo_cella(a, c) or '—'}" for c in colonne
                               if c.ruolo not in ("descrizione", "prezzo"))
            prezzo = ""
            if any(c.ruolo == "prezzo" for c in colonne):
                # l'euro solo dopo un prezzo vero, non dopo «senza prezzo» o un testo non riconosciuto
                prezzo = (f"{formatta_prezzo(a.prezzo)} €" if a.prezzo is not None
                          else a.prezzo_testo or "senza prezzo") + "   ·   "
            righe = [f"{dati}   ·   {prezzo}pag. {a.pagina}   ·   {a.categoria}"]
            if any(c.ruolo == "descrizione" for c in colonne):
                righe.append(a.descrizione)
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
            n = esporta_listino(articoli, percorso, self.tabella.colonne)
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
            n = esporta_report_anomalie(articoli, percorso, self.tabella.colonne)
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

        personale = self.chiave_fornitore in self.personali
        self.btn_seleziona.configure(state=stato(not occupato))
        self.menu_fornitore.configure(state=stato(not occupato))
        self.btn_modifica.configure(state=stato(personale and not occupato))
        self.btn_rinomina.configure(state=stato(personale and not occupato))
        self.btn_rimuovi.configure(state=stato(personale and not occupato))
        self.btn_wizard.configure(state=stato(not occupato))
        self.btn_estrai.configure(state=stato(self.info_pdf is not None and not occupato))
        self.btn_annulla.configure(state=stato(occupato))
        if hasattr(self, "btn_esporta"):
            self.btn_esporta.configure(state=stato(ha_dati and not occupato))
            self.btn_report.configure(state=stato(ha_dati and not occupato))
            self.btn_elimina.configure(state=stato(ha_dati and not occupato))
            self.btn_pagina.configure(state=stato(ha_dati and not occupato))
        if hasattr(self, "btn_avvisi"):
            self.btn_avvisi.configure(text=f"Avvisi ({len(self.avvisi)})…" if self.avvisi else "Avvisi…",
                                      state=stato(bool(self.avvisi) and not occupato))

    def _chiudi(self):
        if self._lavoro is not None:
            self._lavoro.termina()
        if self._wizard is not None and self._wizard.winfo_exists():
            self._wizard.chiudi()
        self.destroy()

    # --- wizard -------------------------------------------------------------------------------

    def _apri_wizard(self, modifica: tuple[str, dict] | None = None):
        """Wizard per un fornitore nuovo, o con `modifica` = (chiave, profilo) per correggerne uno salvato."""
        from gui.wizard_fornitore import WizardFornitore

        if self._wizard is not None and self._wizard.winfo_exists():
            in_primo_piano(self._wizard)
            if modifica is not None:
                messagebox.showinfo(
                    "Modifica fornitore", "Il wizard e' gia' aperto: chiudilo prima di modificare un fornitore.",
                    parent=self._wizard,
                )
            return
        iniziale = self.info_pdf.percorso if self.info_pdf else None
        self._wizard = WizardFornitore(
            self, self.fornitori, al_salvataggio=self._fornitore_salvato, pdf=iniziale, modifica=modifica
        )

    def _fornitore_salvato(self, chiave: str):
        """Il wizard ha salvato un fornitore: lo si rende disponibile e lo si seleziona."""
        self._ricarica_fornitori(chiave)
