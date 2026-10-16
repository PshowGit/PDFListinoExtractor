"""Finestra «Configura nuovo fornitore»: mappatura visiva delle colonne di un listino sconosciuto.

Flusso: apri il PDF e scegli la pagina -> la pre-analisi (nel processo separato) trova colonne e
intestazione e le evidenzia sulla pagina -> per ogni colonna si sceglie il campo da un menu ->
ancora, formato prezzi e opzioni -> «Anteprima» estrae la sola pagina scelta (sempre nel processo
separato) -> «Salva fornitore» scrive il profilo nelle regole personali.
La logica sta in processors/wizard.py (ModelloWizard): qui c'e' solo il collegamento con i widget.
"""
import io
import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import config
from gui.lavoro import LavoroInProcesso
from gui.preview_table import PreviewTable
from percorsi import icona
from processors.lavori import ANALISI, ANTEPRIMA
from processors.profilo import normalizza
from processors.wizard import (
    COLORI_CAMPO,
    ETICHETTE_ANCORA,
    ETICHETTE_CAMPO,
    ETICHETTE_FORMATO,
    ModelloWizard,
)

log = logging.getLogger(__name__)
ZOOM = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def _chiave_per_etichetta(tabella: dict[str, str], etichetta: str) -> str:
    return next(k for k, v in tabella.items() if v == etichetta)


def _rgba(colore: str, alfa: int) -> tuple[int, int, int, int]:
    return int(colore[1:3], 16), int(colore[3:5], 16), int(colore[5:7], 16), alfa


class WizardFornitore(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        fornitori: dict[str, str],
        al_salvataggio: Callable[[str], None] | None = None,
        pdf: Path | None = None,
        percorso_regole: Path | None = None,
    ):
        super().__init__(master)
        self.title("Configura nuovo fornitore")
        self.geometry("1440x920")
        self.minsize(1100, 720)
        if icona().is_file():
            self.after(250, lambda: self.iconbitmap(str(icona())))
        self.fornitori = fornitori
        self.al_salvataggio = al_salvataggio
        self.percorso_regole = percorso_regole  # None = file personale in %LOCALAPPDATA%
        self.pdf: Path | None = None
        self.pagina = 1
        self.pagine_totali: int | None = None
        self.modello: ModelloWizard | None = None
        self.zoom = 1.0
        self._base: Image.Image | None = None
        self._foto = None
        self._lavoro: LavoroInProcesso | None = None
        self._riquadri: list[ctk.CTkFrame] = []
        self._menu_colonne: list[ctk.CTkOptionMenu] = []
        self._selezionata: int | None = None
        self.ultimo_salvataggio: Path | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._barra_comandi()
        self._area_pagina()
        self._pannello_mappatura()
        self._area_anteprima()
        self.lbl_stato = ctk.CTkLabel(self, text="Apri un listino PDF per cominciare.", anchor="w")
        self.lbl_stato.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self.chiudi)
        self._aggiorna_comandi()
        if pdf is not None:
            self.pdf = Path(pdf)
            self.after(200, self._analizza)

    # --- costruzione --------------------------------------------------------------------------

    def _barra_comandi(self):
        f = ctk.CTkFrame(self)
        f.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
        self.btn_apri = ctk.CTkButton(f, text="Apri PDF…", width=110, command=self._apri_pdf)
        self.btn_apri.pack(side="left", padx=8, pady=8)
        self.lbl_pdf = ctk.CTkLabel(f, text="Nessun PDF", anchor="w", width=320)
        self.lbl_pdf.pack(side="left", padx=4)
        ctk.CTkLabel(f, text="Pagina").pack(side="left", padx=(16, 4))
        self.btn_prec = ctk.CTkButton(f, text="◀", width=32, command=lambda: self._vai(self.pagina - 1))
        self.btn_prec.pack(side="left")
        self.ent_pagina = ctk.CTkEntry(f, width=56, justify="center")
        self.ent_pagina.insert(0, "1")
        self.ent_pagina.bind("<Return>", lambda e: self._vai_a_testo())
        self.ent_pagina.pack(side="left", padx=4)
        self.btn_succ = ctk.CTkButton(f, text="▶", width=32, command=lambda: self._vai(self.pagina + 1))
        self.btn_succ.pack(side="left")
        self.lbl_totale = ctk.CTkLabel(f, text="", width=60)
        self.lbl_totale.pack(side="left", padx=4)
        self.btn_analizza = ctk.CTkButton(f, text="Analizza pagina", width=130, command=self._analizza)
        self.btn_analizza.pack(side="left", padx=8)
        ctk.CTkButton(f, text="+", width=32, command=lambda: self._cambia_zoom(1)).pack(side="right", padx=(4, 8))
        self.lbl_zoom = ctk.CTkLabel(f, text="100%", width=50)
        self.lbl_zoom.pack(side="right")
        ctk.CTkButton(f, text="−", width=32, command=lambda: self._cambia_zoom(-1)).pack(side="right", padx=4)
        ctk.CTkLabel(f, text="Zoom").pack(side="right", padx=4)

    def _area_pagina(self):
        cornice = tk.Frame(self, background="#777777")
        cornice.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=6)
        self.canvas = tk.Canvas(cornice, highlightthickness=0, background="#777777")
        sy = tk.Scrollbar(cornice, orient="vertical", command=self.canvas.yview)
        sx = tk.Scrollbar(cornice, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        cornice.grid_rowconfigure(0, weight=1)
        cornice.grid_columnconfigure(0, weight=1)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Button-1>", self._clic_pagina)

    def _pannello_mappatura(self):
        p = ctk.CTkFrame(self, width=430)
        p.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        p.grid_propagate(False)
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(p, text="Colonne rilevate", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2)
        )
        self.elenco_colonne = ctk.CTkScrollableFrame(p)
        self.elenco_colonne.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self.elenco_colonne.grid_columnconfigure(0, weight=1)

        o = ctk.CTkFrame(p, fg_color="transparent")
        o.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        o.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(o, text="Ancora").grid(row=0, column=0, sticky="w", pady=3)
        self.menu_ancora = ctk.CTkOptionMenu(o, values=list(ETICHETTE_ANCORA.values()), command=self._cambia_ancora)
        self.menu_ancora.grid(row=0, column=1, sticky="ew", pady=3)
        ctk.CTkLabel(o, text="Prezzi").grid(row=1, column=0, sticky="w", pady=3)
        self.menu_formato = ctk.CTkOptionMenu(o, values=list(ETICHETTE_FORMATO.values()), command=self._cambia_formato)
        self.menu_formato.grid(row=1, column=1, sticky="ew", pady=3)
        self.chk_parentesi_pdf = ctk.CTkCheckBox(o, text="Codici scritti tra parentesi nel PDF", command=self._opzioni)
        self.chk_parentesi_pdf.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
        self.chk_parentesi_excel = ctk.CTkCheckBox(o, text="Tieni le parentesi nell'Excel", command=self._opzioni)
        self.chk_parentesi_excel.grid(row=3, column=0, columnspan=2, sticky="w", pady=3)
        self.chk_linee = ctk.CTkCheckBox(o, text="Usa le linee orizzontali come separatori", command=self._opzioni)
        self.chk_linee.grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        ctk.CTkLabel(o, text="Nome").grid(row=5, column=0, sticky="w", pady=(10, 3))
        self.ent_nome = ctk.CTkEntry(o, placeholder_text="es. Fornitore X - listino 2026")
        self.ent_nome.grid(row=5, column=1, sticky="ew", pady=(10, 3))
        self.ent_nome.bind("<KeyRelease>", lambda e: self._opzioni())

        self.lbl_errori = ctk.CTkLabel(p, text="", text_color="#C0392B", anchor="w", justify="left", wraplength=400)
        self.lbl_errori.grid(row=3, column=0, sticky="ew", padx=10, pady=4)
        b = ctk.CTkFrame(p, fg_color="transparent")
        b.grid(row=4, column=0, sticky="ew", padx=8, pady=(4, 10))
        self.btn_anteprima = ctk.CTkButton(b, text="Anteprima pagina", command=self._anteprima)
        self.btn_anteprima.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_salva = ctk.CTkButton(b, text="Salva fornitore", command=self._salva, fg_color="#2E7D32",
                                       hover_color="#1B5E20")
        self.btn_salva.pack(side="left", expand=True, fill="x", padx=(4, 0))

    def _area_anteprima(self):
        f = ctk.CTkFrame(self, height=230)
        f.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=6)
        f.grid_propagate(False)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        self.lbl_anteprima = ctk.CTkLabel(f, text="Anteprima: non ancora eseguita", anchor="w",
                                          font=ctk.CTkFont(weight="bold"))
        self.lbl_anteprima.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        self.tabella = PreviewTable(f, normalizza({"nome": "_", "colonne": [{"campo": "modello"}]}))
        self.tabella.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

    # --- PDF e pagina -------------------------------------------------------------------------

    def _apri_pdf(self):
        percorso = filedialog.askopenfilename(
            parent=self, title="Listino del nuovo fornitore", filetypes=[("PDF", "*.pdf"), ("Tutti i file", "*.*")]
        )
        if percorso:
            self.pdf = Path(percorso)
            self.pagina = 1
            self.pagine_totali = None
            self._analizza()

    def _vai(self, pagina: int):
        if self.pdf is None or self._lavoro is not None:
            return
        massimo = self.pagine_totali or pagina
        pagina = max(1, min(pagina, massimo))
        if pagina != self.pagina:
            self.pagina = pagina
            self._analizza()

    def _vai_a_testo(self):
        try:
            self._vai(int(self.ent_pagina.get()))
        except ValueError:
            self.ent_pagina.delete(0, "end")
            self.ent_pagina.insert(0, str(self.pagina))

    def _analizza(self):
        if self.pdf is None or self._lavoro is not None:
            return
        self.lbl_pdf.configure(text=self.pdf.name)
        self.ent_pagina.delete(0, "end")
        self.ent_pagina.insert(0, str(self.pagina))
        self._stato(f"Analisi della pagina {self.pagina}…")
        self._lavoro = LavoroInProcesso(
            self, ANALISI, {"percorso": str(self.pdf), "pagina": self.pagina},
            alla_fine=self._analisi_pronta, all_errore=self._lavoro_fallito,
        ).avvia()
        self._aggiorna_comandi()

    def _analisi_pronta(self, risultato):
        self._lavoro = None
        analisi, png = risultato
        nome = self.modello.nome if self.modello else ""
        self.modello = ModelloWizard(analisi, self.fornitori)
        self.modello.nome = nome or self.ent_nome.get()
        self.pagine_totali = analisi.pagine_totali
        self.lbl_totale.configure(text=f"di {analisi.pagine_totali}")
        self._base = Image.open(io.BytesIO(png)).convert("RGB")
        if self._foto is None:  # primo PDF: zoom che fa stare la pagina nel riquadro
            larghezza = max(400, self.canvas.winfo_width())
            self.zoom = max(z for z in ZOOM if z * analisi.larghezza <= larghezza) if any(
                z * analisi.larghezza <= larghezza for z in ZOOM) else ZOOM[0]
        self._costruisci_colonne()
        self._mostra_opzioni()
        self._ridisegna()
        avvisi = " ".join(analisi.avvisi)
        self._stato(
            f"Pagina {analisi.pagina}: {len(analisi.colonne)} colonne, ancora proposta «"
            f"{ETICHETTE_ANCORA.get(analisi.ancora_proposta, analisi.ancora_proposta)}». {avvisi}"
        )
        self._aggiorna_comandi()

    def _lavoro_fallito(self, messaggio: str):
        self._lavoro = None
        self._stato("Operazione non riuscita.")
        self._aggiorna_comandi()
        messagebox.showerror("Errore", messaggio, parent=self)

    # --- mappatura ----------------------------------------------------------------------------

    def _costruisci_colonne(self):
        for w in self.elenco_colonne.winfo_children():
            w.destroy()
        self._riquadri, self._menu_colonne, self._selezionata = [], [], None
        for i, col in enumerate(self.modello.analisi.colonne):
            r = ctk.CTkFrame(self.elenco_colonne, border_width=2, border_color="#D0D0D0")
            r.grid(row=i, column=0, sticky="ew", padx=2, pady=3)
            r.grid_columnconfigure(1, weight=1)
            campione = ctk.CTkLabel(r, text="", width=14, height=40, corner_radius=4,
                                    fg_color=COLORI_CAMPO[self.modello.campi[i]])
            campione.grid(row=0, column=0, rowspan=2, padx=(6, 8), pady=6)
            titolo = f"{i + 1}. «{col.etichetta}»" if col.da_intestazione else f"{i + 1}. {col.etichetta}"
            ctk.CTkLabel(r, text=titolo, anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=1, sticky="ew", pady=(6, 0)
            )
            esempi = f"x≈{col.x0:.0f} · " + (" · ".join(e[:40] for e in col.esempi[:3]) or "nessun testo qui")
            ctk.CTkLabel(r, text=esempi, anchor="w", justify="left", text_color="gray", wraplength=230,
                         font=ctk.CTkFont(size=11)).grid(row=1, column=1, sticky="ew", pady=(0, 6))
            menu = ctk.CTkOptionMenu(r, values=list(ETICHETTE_CAMPO.values()), width=150,
                                     command=lambda etichetta, i=i, c=campione: self._cambia_campo(i, etichetta, c))
            menu.set(ETICHETTE_CAMPO[self.modello.campi[i]])
            menu.grid(row=0, column=2, rowspan=2, padx=6)
            self._riquadri.append(r)
            self._menu_colonne.append(menu)

    def _mostra_opzioni(self):
        m = self.modello
        self.menu_ancora.set(ETICHETTE_ANCORA[m.ancora])
        self.menu_formato.set(ETICHETTE_FORMATO[m.formato_prezzo])
        for chk, valore in ((self.chk_parentesi_pdf, m.codici_tra_parentesi),
                            (self.chk_parentesi_excel, m.codice_con_parentesi), (self.chk_linee, m.linee_divisorie)):
            chk.select() if valore else chk.deselect()
        if m.nome and not self.ent_nome.get():
            self.ent_nome.insert(0, m.nome)
        self._mostra_errori()

    def imposta_campo(self, indice: int, campo: str) -> None:
        """Come scegliere dal menu della colonna (usato anche dai test)."""
        self._menu_colonne[indice].set(ETICHETTE_CAMPO[campo])
        campione = self._riquadri[indice].winfo_children()[0]
        self._cambia_campo(indice, ETICHETTE_CAMPO[campo], campione)

    def _cambia_campo(self, indice: int, etichetta: str, campione):
        campo = _chiave_per_etichetta(ETICHETTE_CAMPO, etichetta)
        self.modello.imposta_campo(indice, campo)
        campione.configure(fg_color=COLORI_CAMPO[campo])
        self._ridisegna()
        self._mostra_errori()

    def _cambia_ancora(self, etichetta: str):
        if self.modello:
            self.modello.ancora = _chiave_per_etichetta(ETICHETTE_ANCORA, etichetta)
            self._mostra_errori()

    def _cambia_formato(self, etichetta: str):
        if self.modello:
            self.modello.formato_prezzo = _chiave_per_etichetta(ETICHETTE_FORMATO, etichetta)

    def _opzioni(self):
        if not self.modello:
            return
        self.modello.codici_tra_parentesi = bool(self.chk_parentesi_pdf.get())
        self.modello.codice_con_parentesi = bool(self.chk_parentesi_excel.get())
        self.modello.linee_divisorie = bool(self.chk_linee.get())
        self.modello.nome = self.ent_nome.get()
        self._mostra_errori()

    def _mostra_errori(self, includi_nome: bool = False):
        errori = self.modello.errori() if self.modello else []
        if not includi_nome:
            errori = [e for e in errori if "nome" not in e.lower()]
        self.lbl_errori.configure(text="\n".join(f"• {e}" for e in errori))
        return errori

    # --- disegno della pagina -----------------------------------------------------------------

    def _cambia_zoom(self, verso: int):
        i = min(range(len(ZOOM)), key=lambda n: abs(ZOOM[n] - self.zoom))
        self.zoom = ZOOM[max(0, min(len(ZOOM) - 1, i + verso))]
        self._ridisegna()

    def _ridisegna(self):
        self.lbl_zoom.configure(text=f"{self.zoom * 100:.0f}%")
        if self._base is None or self.modello is None:
            return
        a = self.modello.analisi
        scala = self.zoom  # pixel per punto
        img = self._base.resize((round(a.larghezza * scala), round(a.altezza * scala)), Image.LANCZOS)
        livello = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(livello)
        alto = (a.intestazione[0] - 4) if a.intestazione else 0
        for i, (col, campo) in enumerate(zip(a.colonne, self.modello.campi, strict=True)):
            colore = COLORI_CAMPO[campo]
            x0, x1 = col.x0 * scala, col.x1 * scala
            d.rectangle((x0, alto * scala, x1, img.height - 1), fill=_rgba(colore, 0 if campo == "ignora" else 38),
                        outline=_rgba(colore, 255), width=3 if i == self._selezionata else 1)
            d.rectangle((x0, alto * scala, x0 + 22, alto * scala + 16), fill=_rgba(colore, 255))
            d.text((x0 + 6, alto * scala + 2), str(i + 1), fill="white")
        if a.intestazione:
            d.rectangle((2, a.intestazione[0] * scala - 2, img.width - 3, a.intestazione[1] * scala + 2),
                        outline=(40, 40, 40, 200), width=2)
        img = Image.alpha_composite(img.convert("RGBA"), livello).convert("RGB")
        self._foto = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._foto, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, img.width, img.height))

    def _clic_pagina(self, evento):
        """Clic su una colonna della pagina: ne evidenzia il riquadro e il menu."""
        if self.modello is None:
            return
        x = self.canvas.canvasx(evento.x) / self.zoom
        for i, col in enumerate(self.modello.analisi.colonne):
            if col.x0 <= x <= col.x1:
                self.seleziona_colonna(i)
                return

    def seleziona_colonna(self, indice: int):
        self._selezionata = indice
        for n, r in enumerate(self._riquadri):
            r.configure(border_color="#1F6AA5" if n == indice else "#D0D0D0")
        self._ridisegna()
        col = self.modello.analisi.colonne[indice]
        self._stato(f"Colonna {indice + 1} «{col.etichetta}»: scegli il campo dal menu a destra.")

    # --- anteprima e salvataggio --------------------------------------------------------------

    def _anteprima(self):
        if self.modello is None or self._lavoro is not None:
            return
        errori = self._mostra_errori()
        if errori:
            self._stato("Correggere la mappatura prima dell'anteprima.")
            return
        profilo = self.modello.profilo()
        self._stato(f"Anteprima della pagina {self.pagina}…")
        self._lavoro = LavoroInProcesso(
            self, ANTEPRIMA, {"percorso": str(self.pdf), "regole": profilo, "pagina": self.pagina},
            alla_fine=lambda ris: self._anteprima_pronta(ris, profilo), all_errore=self._lavoro_fallito,
        ).avvia()
        self._aggiorna_comandi()

    def _anteprima_pronta(self, ris, profilo: dict):
        self._lavoro = None
        self.tabella.regole = normalizza(profilo)
        self.tabella.carica(ris.articoli)
        n, anomali = self.tabella.conteggi()
        self.lbl_anteprima.configure(
            text=f"Anteprima pagina {self.pagina}: {n} articoli · {anomali} da verificare · "
                 f"ancora «{ETICHETTE_ANCORA.get(ris.ancora, ris.ancora)}»"
        )
        self._stato("Controlla la tabella: se le righe sono giuste, salva il fornitore.")
        self._aggiorna_comandi()

    def _salva(self) -> bool:
        if self.modello is None:
            return False
        self._opzioni()
        errori = self._mostra_errori(includi_nome=True)
        if errori:
            messagebox.showwarning("Mappatura incompleta", "\n".join(errori), parent=self)
            return False
        chiave = self.modello.chiave()
        if self.modello.sostituisce_esistente() and not messagebox.askyesno(
            "Fornitore esistente",
            f"Esiste gia' un fornitore «{self.fornitori[chiave]}».\nSostituirlo con questa configurazione?",
            parent=self,
        ):
            return False
        try:
            percorso = config.salva_fornitore_personale(chiave, self.modello.profilo(), self.percorso_regole)
        except (OSError, config.RegoleNonValide) as e:
            log.exception("Salvataggio del fornitore non riuscito")
            messagebox.showerror("Salvataggio non riuscito", str(e), parent=self)
            return False
        self.ultimo_salvataggio = percorso
        if self.al_salvataggio:
            self.al_salvataggio(chiave)
        messagebox.showinfo(
            "Fornitore salvato",
            f"«{self.modello.nome.strip()}» e' ora disponibile nel menu Fornitore.\n\nRegole salvate in:\n{percorso}",
            parent=self,
        )
        self.chiudi()
        return True

    # --- stato --------------------------------------------------------------------------------

    def _stato(self, testo: str):
        self.lbl_stato.configure(text=testo)

    def _aggiorna_comandi(self):
        occupato = self._lavoro is not None
        pronto = self.modello is not None and not occupato

        def stato(attivo):
            return "normal" if attivo else "disabled"

        self.btn_apri.configure(state=stato(not occupato))
        for b in (self.btn_prec, self.btn_succ, self.btn_analizza):
            b.configure(state=stato(self.pdf is not None and not occupato))
        self.btn_anteprima.configure(state=stato(pronto))
        self.btn_salva.configure(state=stato(pronto))

    def chiudi(self):
        if self._lavoro is not None:
            self._lavoro.termina()
            self._lavoro = None
        self.destroy()
