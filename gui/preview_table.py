"""Tabella di anteprima: ordinamento, modifica, eliminazione e filtro delle anomalie.

Le colonne sono quelle dell'estrazione (`RisultatoEstrazione.colonne`), seguite da pagina e anomalie:
nome e ordine li decide il profilo, ordinamento e modifica li decide il ruolo.
"""
import tkinter as tk
from collections.abc import Callable
from decimal import Decimal
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import customtkinter as ctk

from processors.data_validator import conta_tipi, tipo_anomalia, valida
from processors.models import ALTRO_PREZZO, COLONNE_STANDARD, MARCA, TESTO_GENERICO, Articolo, ColonnaUscita
from processors.price_parser import formatta_prezzo, parse_prezzo
from processors.profilo import colonne_uscita, normalizza

# dopo le colonne del documento: non modificabili, non esportate
FISSE = (ColonnaUscita("pagina", "Pag.", "pagina"), ColonnaUscita("note", "Anomalie", "note"))
LARGHEZZE = {"modello": 170, "codice": 160, "ean": 110, "descrizione": 420, "prezzo": 90, TESTO_GENERICO: 140, MARCA: 130,
             ALTRO_PREZZO: 90, "pagina": 45, "note": 260}
RUOLI_PREZZO = ("prezzo", ALTRO_PREZZO)
# larghezza delle colonne dal contenuto: su quante righe misurarla e fra quali limiti, in pixel dello schermo
CAMPIONE_LARGHEZZE, LARGHEZZA_MINIMA, LARGHEZZA_MASSIMA = 300, 50, 320
SCRITTE_MISURATE = 5  # per colonna, le piu' lunghe del campione
# filtro della tabella: tutte le righe, quelle con almeno un'anomalia, o quelle con un tipo di anomalia (il suo nome)
TUTTE, DA_VERIFICARE = None, "__da_verificare__"


def _decimale(a: Articolo, col: ColonnaUscita) -> Decimal | None:
    """Il valore di una colonna di prezzo; None se manca o non e' un prezzo riconoscibile."""
    valore = a.prezzo if col.ruolo == "prezzo" else a.valore(col.chiave)
    return valore if isinstance(valore, Decimal) else None


def testo_cella(a: Articolo, col: ColonnaUscita) -> str:
    """Il valore di una colonna come si mostra: i prezzi all'italiana, o il testo del PDF se non lo erano."""
    if col.ruolo in RUOLI_PREZZO:
        valore = _decimale(a, col)
        if valore is not None:
            return formatta_prezzo(valore)
        return (a.prezzo_testo or "") if col.ruolo == "prezzo" else str(a.valore(col.chiave) or "")
    return str(a.valore(col.chiave) or "").replace("\n", " ")


def _chiave_ordinamento(col: ColonnaUscita):
    def chiave(a: Articolo):
        if col.ruolo in RUOLI_PREZZO:
            # i prezzi mancanti in fondo, qualunque sia il verso
            valore = _decimale(a, col)
            return (valore is None, valore if valore is not None else Decimal(0))
        if col.ruolo == "pagina":
            return (a.pagina, a.bbox[1])
        if col.ruolo == "note":
            return (not a.tutte_le_anomalie(), "; ".join(a.tutte_le_anomalie()))
        return (a.valore(col.chiave) or "").lower()

    return chiave


class PreviewTable(ctk.CTkFrame):
    def __init__(
        self,
        master,
        regole: dict,
        on_change: Callable[[], None] | None = None,
        on_select: Callable[[Articolo | None], None] | None = None,
        **kw,
    ):
        super().__init__(master, **kw)
        self.regole = regole
        self.on_change = on_change
        self.on_select = on_select
        self._articoli: dict[str, Articolo] = {}
        self._ordine: list[str] = []
        self._filtro: str | None = TUTTE
        self._verso: dict[str, bool] = {}
        self._ordinata: tuple[str, bool] | None = None  # colonna dell'ultimo ordinamento e se discendente
        self._editor: tk.Widget | None = None
        self._in_modifica: tuple[str, int] | None = None  # riga e colonna dell'editor aperto
        self.attiva = 0  # colonna (fra quelle del documento) che Invio e F2 correggono
        self._finestra_descrizione: ctk.CTkToplevel | None = None
        self._prossimo_id = 0
        self.colonne: list[ColonnaUscita] = (
            colonne_uscita(normalizza(regole)) if regole.get("colonne") else list(COLONNE_STANDARD)
        )

        self._stile()
        self.tree = ttk.Treeview(self, show="headings", selectmode="extended")
        self._configura_colonne()
        self.tree.tag_configure("anomalia", background="#FFE3C2", foreground="#000000")
        sy = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._doppio_clic)
        self.tree.bind("<Delete>", lambda e: self.elimina_selezionati(chiedi_conferma=True))
        self.tree.bind("<<TreeviewSelect>>", self._selezione)
        # tastiera: correggere senza mouse; ogni gestore ferma il comportamento predefinito del Treeview
        for tasto in ("<Return>", "<KP_Enter>", "<F2>"):
            self.tree.bind(tasto, lambda e: self._ferma(self.modifica_attiva()))
        self.tree.bind("<Left>", lambda e: self._ferma(self.sposta_colonna(-1)))
        self.tree.bind("<Right>", lambda e: self._ferma(self.sposta_colonna(1)))
        self.tree.bind("<F8>", lambda e: self._ferma(self.vai_da_verificare(1)))
        self.tree.bind("<Shift-F8>", lambda e: self._ferma(self.vai_da_verificare(-1)))

    @staticmethod
    def _ferma(_esito=None) -> str:
        return "break"

    def _stile(self):
        stile = ttk.Style(self)
        try:
            stile.theme_use("clam")
        except tk.TclError:
            pass
        scuro = ctk.get_appearance_mode() == "Dark"
        sfondo, testo = ("#2B2B2B", "#EDEDED") if scuro else ("#FFFFFF", "#111111")
        stile.configure("Treeview", background=sfondo, fieldbackground=sfondo, foreground=testo, rowheight=24)
        stile.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        stile.map("Treeview", background=[("selected", "#1F6AA5")], foreground=[("selected", "#FFFFFF")])

    def _tutte(self) -> list[ColonnaUscita]:
        return [*self.colonne, *FISSE]

    def _colonna(self, chiave: str) -> ColonnaUscita:
        return next(c for c in self._tutte() if c.chiave == chiave)

    def _configura_colonne(self) -> None:
        self.tree.configure(columns=[c.chiave for c in self._tutte()])
        self._verso.clear()
        self._ordinata = None
        self.attiva = min(self.attiva, len(self.colonne) - 1) if self.colonne else 0
        for c in self._tutte():
            self.tree.heading(c.chiave, command=lambda k=c.chiave: self.ordina(k))
            self.tree.column(
                c.chiave,
                width=LARGHEZZE[c.ruolo],
                anchor="e" if c.ruolo in (*RUOLI_PREZZO, "pagina") else "w",
                stretch=c.ruolo in ("descrizione", "note"),
            )
        self._intestazioni()

    def _intestazioni(self) -> None:
        """Titoli delle colonne: «▸» sulla colonna attiva, la freccia sull'ultima ordinata."""
        for n, c in enumerate(self._tutte()):
            testo = ("▸ " if n == self.attiva and n < len(self.colonne) else "") + c.etichetta
            if self._ordinata and self._ordinata[0] == c.chiave:
                testo += " ▼" if self._ordinata[1] else " ▲"
            self.tree.heading(c.chiave, text=testo)

    # --- dati -------------------------------------------------------------------------------

    def carica(self, articoli: list[Articolo], colonne: list[ColonnaUscita] | None = None) -> None:
        """Mostra gli articoli; con `colonne` (quelle dell'estrazione) la tabella prende le sue colonne."""
        if colonne is not None and list(colonne) != self.colonne:
            self.colonne = list(colonne)
            self._configura_colonne()
        self._articoli.clear()
        self._ordine.clear()
        for a in articoli:
            iid = f"a{self._prossimo_id}"
            self._prossimo_id += 1
            self._articoli[iid] = a
            self._ordine.append(iid)
        self._adatta_larghezze()
        self._ridisegna()

    def _adatta_larghezze(self) -> None:
        """Ogni colonna larga quanto il suo contenuto (su un campione di righe) e il suo titolo, entro dei limiti:
        con le colonne dinamiche le larghezze fisse per ruolo erano troppo strette per «Codice/Articolo» e troppo
        larghe per un modello di sei caratteri. Descrizione e anomalie restano quelle che si allargano."""
        if not self._articoli:
            return
        testo = tkfont.nametofont("TkDefaultFont")
        titolo = tkfont.Font(font=("Segoe UI", 9, "bold"))
        righe = [self._valori(self._articoli[i]) for i in self._ordine[:CAMPIONE_LARGHEZZE]]
        for n, c in enumerate(self.colonne):
            if c.ruolo == "descrizione":
                continue
            # si misurano solo le scritte piu' lunghe: misurarle tutte bloccava la finestra per 360 ms alla fine
            # dell'estrazione del JBL (la prima misura di ogni carattere costa, poi Tk la ricorda)
            lunghe = sorted({str(r[n]) for r in righe}, key=len, reverse=True)[:SCRITTE_MISURATE]
            # il titolo con lo spazio per «▸ » e per la freccia dell'ordinamento
            misure = [titolo.measure(f"▸ {c.etichetta} ▲") + 12] + [testo.measure(s) + 16 for s in lunghe]
            self.tree.column(c.chiave, width=max(LARGHEZZA_MINIMA, min(LARGHEZZA_MASSIMA, max(misure))))

    def articoli(self) -> list[Articolo]:
        """Tutti i record approvati, nell'ordine mostrato, ignorando il filtro."""
        return [self._articoli[i] for i in self._ordine]

    def articolo(self, iid: str) -> Articolo:
        return self._articoli[iid]

    def iid_di(self, articolo: Articolo) -> str | None:
        """La riga di un articolo (lo stesso oggetto, non uno uguale: due duplicati sono righe diverse)."""
        return next((iid for iid, a in self._articoli.items() if a is articolo), None)

    def selezionato(self) -> Articolo | None:
        sel = self.tree.selection()
        return self._articoli[sel[0]] if sel else None

    def conteggi(self) -> tuple[int, int]:
        tutti = self.articoli()
        return len(tutti), sum(1 for a in tutti if a.tutte_le_anomalie())

    def tipi_anomalia(self) -> list[tuple[str, int]]:
        """Tipi di anomalia di tutte le righe (non solo di quelle mostrate), dal piu' frequente."""
        return conta_tipi(self.articoli())

    @property
    def filtro(self) -> str | None:
        return self._filtro

    def imposta_filtro(self, filtro: str | None) -> None:
        """TUTTE, DA_VERIFICARE o il nome di un tipo di anomalia (v. data_validator.tipo_anomalia)."""
        self._filtro = filtro
        self._ridisegna()

    def imposta_filtro_anomalie(self, attivo: bool) -> None:
        self.imposta_filtro(DA_VERIFICARE if attivo else TUTTE)

    def _passa_il_filtro(self, a: Articolo) -> bool:
        if self._filtro is TUTTE:
            return True
        anomalie = a.tutte_le_anomalie()
        if self._filtro == DA_VERIFICARE:
            return bool(anomalie)
        return any(tipo_anomalia(x) == self._filtro for x in anomalie)

    def mostrate(self) -> int:
        return len(self.tree.get_children())

    # --- vista ------------------------------------------------------------------------------

    def _valori(self, a: Articolo) -> tuple:
        return (*(testo_cella(a, c) for c in self.colonne), a.pagina, "; ".join(a.tutte_le_anomalie()))

    def _ridisegna(self) -> None:
        selezione = set(self.tree.selection())
        attuale = self.tree.focus()
        prima = list(self.tree.get_children())
        self.tree.delete(*self.tree.get_children())
        for iid in self._ordine:
            a = self._articoli[iid]
            if not self._passa_il_filtro(a):
                continue
            tag = ("anomalia",) if a.tutte_le_anomalie() else ()
            self.tree.insert("", "end", iid=iid, values=self._valori(a), tags=tag)
        rimaste = [i for i in selezione if self.tree.exists(i)]
        if rimaste:
            self.tree.selection_set(rimaste)
            self.tree.focus(attuale if self.tree.exists(attuale) else rimaste[0])
        elif attuale in prima:
            # la riga selezionata non c'e' piu' (corretta col filtro attivo, o eliminata): si passa a quella che
            # ne prende il posto, o all'ultima, invece di perdere il punto in cui si stava lavorando
            dopo = [i for i in prima[prima.index(attuale) + 1:] if self.tree.exists(i)]
            altre = dopo or [i for i in reversed(prima[:prima.index(attuale)]) if self.tree.exists(i)]
            if altre:
                self.seleziona(altre[0])

    def seleziona(self, iid: str) -> None:
        """Seleziona una riga, ci mette il cursore della tastiera e la fa vedere."""
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def _riga_corrente(self) -> str | None:
        corrente = self.tree.focus()
        if corrente and self.tree.exists(corrente):
            return corrente
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _dopo_modifica(self) -> None:
        valida(self.articoli(), self.regole)  # i duplicati dipendono da tutte le righe
        self._ridisegna()
        if self.on_change:
            self.on_change()

    def ordina(self, campo: str) -> None:
        col = self._colonna(campo)
        discendente = self._verso.get(campo, False)
        chiave = _chiave_ordinamento(col)
        self._ordine.sort(key=lambda i: chiave(self._articoli[i]), reverse=discendente)
        if col.ruolo in RUOLI_PREZZO and discendente:  # tieni comunque i mancanti in fondo
            self._ordine.sort(key=lambda i: _decimale(self._articoli[i], col) is None)
        self._verso[campo] = not discendente
        self._ordinata = (campo, discendente)
        self._intestazioni()
        self._ridisegna()

    def elimina_selezionati(self, chiedi_conferma: bool = False) -> int:
        sel = list(self.tree.selection())
        if not sel:
            return 0
        if chiedi_conferma and not messagebox.askyesno(
            "Elimina righe", f"Eliminare {len(sel)} righe dall'elenco?", parent=self
        ):
            return 0
        for iid in sel:
            self._ordine.remove(iid)
            del self._articoli[iid]
        self._dopo_modifica()
        return len(sel)

    # --- modifica ---------------------------------------------------------------------------

    def modifica_campo(self, iid: str, campo: str, testo: str) -> bool:
        """Applica una correzione dell'utente. Ritorna False se il valore non e' accettabile."""
        a = self._articoli[iid]
        if self._colonna(campo).ruolo == "prezzo":
            testo = testo.strip()
            if not testo:
                a.imposta("prezzo", None)
                a.prezzo_testo = ""
            else:
                esito = parse_prezzo(testo, self.regole.get("formato_prezzo", "auto"))
                if esito.valore is None:
                    return False
                a.imposta("prezzo", esito.valore)
                a.prezzo_testo = testo
        elif self._colonna(campo).ruolo == ALTRO_PREZZO:
            testo = testo.strip()
            esito = parse_prezzo(testo, self.regole.get("formato_prezzo", "auto")) if testo else None
            if esito is not None and esito.valore is None:
                return False
            a.imposta(campo, esito.valore if esito is not None else "")
        else:
            a.imposta(campo, testo.strip())
        self._dopo_modifica()
        return True

    def _selezione(self, _evento=None):
        if self.on_select:
            self.on_select(self.selezionato())

    def _doppio_clic(self, evento):
        iid = self.tree.identify_row(evento.y)
        colonna = self.tree.identify_column(evento.x)
        if not iid or not colonna:
            return
        indice = int(colonna[1:]) - 1
        if indice >= len(self.colonne):  # pagina e anomalie non si modificano
            return
        self.modifica(iid, indice)

    # --- tastiera ---------------------------------------------------------------------------

    def sposta_colonna(self, verso: int) -> None:
        """← e →: la colonna che Invio e F2 correggono (solo quelle del documento)."""
        if self.colonne:
            self.attiva = max(0, min(len(self.colonne) - 1, self.attiva + verso))
            self._intestazioni()
            self._mostra_colonna(self.attiva)

    def modifica_attiva(self) -> None:
        """Invio e F2: corregge la colonna attiva della riga corrente."""
        iid = self._riga_corrente()
        if iid is not None and self.colonne:
            self.modifica(iid, self.attiva)

    def modifica(self, iid: str, indice: int) -> None:
        """Apre la correzione di una cella: in una finestra la descrizione, sul posto le altre."""
        self.attiva = indice
        self._intestazioni()
        self.seleziona(iid)
        if self.colonne[indice].ruolo == "descrizione":
            self._modifica_descrizione(iid)
        else:
            self._modifica_in_linea(iid, indice)

    def vai_da_verificare(self, verso: int = 1) -> str | None:
        """F8 e Maiusc+F8: la prossima (o la precedente) riga mostrata con un'anomalia, ricominciando dall'inizio."""
        righe = list(self.tree.get_children())
        if not righe:
            return None
        corrente = self._riga_corrente()
        partenza = righe.index(corrente) if corrente in righe else (-1 if verso > 0 else 0)
        for passo in range(1, len(righe) + 1):
            iid = righe[(partenza + verso * passo) % len(righe)]
            if self._articoli[iid].tutte_le_anomalie():
                self.seleziona(iid)
                return iid
        return None

    def _mostra_colonna(self, indice: int) -> None:
        """Scorre la tabella in orizzontale finche' la colonna si vede."""
        larghezze = [self.tree.column(c.chiave, "width") for c in self._tutte()]
        totale = sum(larghezze) or 1
        inizio, fine = sum(larghezze[:indice]) / totale, sum(larghezze[:indice + 1]) / totale
        da, a = self.tree.xview()
        if inizio < da or fine > a:
            self.tree.xview_moveto(max(0.0, inizio if inizio < da else fine - (a - da)))

    def _modifica_in_linea(self, iid: str, indice: int):
        self._chiudi_editor()
        campo = self.colonne[indice].chiave
        self._mostra_colonna(indice)
        self.tree.update_idletasks()
        # una riga fuori vista (o la tabella non ancora disegnata) non ha riquadro: l'editor va in alto
        x, y, w, h = self.tree.bbox(iid, f"#{indice + 1}") or (0, 0, 120, 24)
        a = self._articoli[iid]
        di_prezzo = self._colonna(campo).ruolo in RUOLI_PREZZO
        iniziale = testo_cella(a, self._colonna(campo)) if di_prezzo else a.valore(campo)
        # piu' prezzi trovati per lo stesso articolo («€ 250,00 | € 290,00»): si sceglie da un menu, o si scrive
        scelte = [p.strip() for p in str(iniziale).split(" | ")] if di_prezzo and " | " in str(iniziale) else []
        if scelte:
            entry = ttk.Combobox(self.tree, values=scelte)
            entry.set(scelte[0])
            entry.bind("<<ComboboxSelected>>", lambda e: self._ferma(self.conferma_editor("giu")))
        else:
            entry = tk.Entry(self.tree)
            entry.insert(0, iniziale)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=max(w, 120), height=h)
        entry.focus_set()
        self._editor = entry
        self._in_modifica = (iid, indice)
        # Invio conferma e scende di riga (come in Excel); Tab e Maiusc+Tab confermano e aprono la cella accanto
        entry.bind("<Return>", lambda e: self._ferma(self.conferma_editor("giu")))
        entry.bind("<KP_Enter>", lambda e: self._ferma(self.conferma_editor("giu")))
        entry.bind("<Tab>", lambda e: self._ferma(self.conferma_editor("destra")))
        entry.bind("<Shift-Tab>", lambda e: self._ferma(self.conferma_editor("sinistra")))
        entry.bind("<Escape>", lambda e: self._ferma(self.annulla_editor()))
        entry.bind("<FocusOut>", lambda e: self._fuori_dall_editor())

    def conferma_editor(self, dopo: str | None = None) -> bool:
        """Applica il valore dell'editor; poi `dopo` = "giu", "destra" o "sinistra" dice dove proseguire.

        Se la riga sparisce col filtro attivo (l'anomalia era quella cercata), si prosegue dalla riga che ne ha
        preso il posto. Un prezzo non valido lascia l'editor aperto.
        """
        if self._editor is None or self._in_modifica is None:
            return False
        iid, indice = self._in_modifica
        valore = self._editor.get()
        self._editor.unbind("<FocusOut>")  # il messaggio d'errore prende il focus: l'editor deve restare
        if not self.modifica_campo(iid, self.colonne[indice].chiave, valore):
            messagebox.showerror("Prezzo non valido", f"«{valore}» non e' un prezzo riconoscibile.", parent=self)
            if self._editor is not None:
                self._editor.bind("<FocusOut>", lambda e: self._fuori_dall_editor())
                self._editor.focus_set()
            return False
        self._chiudi_editor()
        rimasta = self.tree.exists(iid)
        corrente = iid if rimasta else self._riga_corrente()
        if dopo == "giu" and rimasta:
            righe = list(self.tree.get_children())
            if righe.index(iid) + 1 < len(righe):
                self.seleziona(righe[righe.index(iid) + 1])
        elif dopo in ("destra", "sinistra") and corrente is not None:
            prossima = indice + (1 if dopo == "destra" else -1)
            if 0 <= prossima < len(self.colonne):
                self.modifica(corrente, prossima)
                return True
        self.tree.focus_set()
        return True

    def annulla_editor(self) -> None:
        self._chiudi_editor()
        self.tree.focus_set()

    def _fuori_dall_editor(self):
        """Il fuoco ha lasciato l'editor: si chiude, tranne quando e' passato alla tendina del menu dei prezzi,
        che e' una finestra a parte e altrimenti si chiudeva prima di poter scegliere."""
        editor = self._editor

        def controlla():
            try:
                fuoco = self.focus_get()
            except (KeyError, tk.TclError):  # Tk non sa nominare la tendina del Combobox: e' aperta
                return
            if self._editor is editor and editor is not None and not str(fuoco or "").startswith(str(editor)):
                self._chiudi_editor()

        if isinstance(editor, ttk.Combobox):
            self.after(150, controlla)
        else:
            self._chiudi_editor()

    def _chiudi_editor(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None
            self._in_modifica = None

    def _modifica_descrizione(self, iid: str):
        a = self._articoli[iid]
        fin = ctk.CTkToplevel(self)
        fin.title(f"Descrizione — {a.codice or a.modello}")
        fin.geometry("640x320")
        fin.transient(self.winfo_toplevel())
        box = ctk.CTkTextbox(fin, wrap="word")
        box.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        box.insert("1.0", a.descrizione)
        barra = ctk.CTkFrame(fin, fg_color="transparent")
        barra.pack(fill="x", padx=10, pady=(0, 10))

        def chiudi():
            fin.destroy()
            self.tree.focus_set()  # la tastiera torna sulla tabella

        def salva():
            self.modifica_campo(iid, "descrizione", " ".join(box.get("1.0", "end").split()))
            chiudi()

        ctk.CTkButton(barra, text="Salva (Ctrl+Invio)", command=salva, width=140).pack(side="right")
        ctk.CTkButton(barra, text="Annulla (Esc)", command=chiudi, width=110, fg_color="gray").pack(
            side="right", padx=8
        )
        # Invio nella casella va a capo: per salvare da tastiera serve Ctrl+Invio
        fin.bind("<Control-Return>", lambda e: self._ferma(salva()))
        fin.bind("<Escape>", lambda e: self._ferma(chiudi()))
        fin.protocol("WM_DELETE_WINDOW", chiudi)
        fin.after(100, fin.grab_set)
        fin.after(150, box.focus_set)
        self._finestra_descrizione = fin
