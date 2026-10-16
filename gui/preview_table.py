"""Tabella di anteprima: ordinamento, modifica, eliminazione e filtro delle anomalie."""
import tkinter as tk
from collections.abc import Callable
from decimal import Decimal
from tkinter import messagebox, ttk

import customtkinter as ctk

from processors.data_validator import valida
from processors.models import Articolo
from processors.price_parser import formatta_prezzo, parse_prezzo

COLONNE = ("modello", "codice", "ean", "descrizione", "prezzo", "pagina", "note")
TITOLI = {
    "modello": "Modello",
    "codice": "Codice",
    "ean": "EAN",
    "descrizione": "Descrizione",
    "prezzo": "Prezzo",
    "pagina": "Pag.",
    "note": "Anomalie",
}
LARGHEZZE = {"modello": 170, "codice": 160, "ean": 110, "descrizione": 420, "prezzo": 90, "pagina": 45, "note": 260}
MODIFICABILI = {"modello", "codice", "ean", "descrizione", "prezzo"}


def _chiave_ordinamento(campo: str):
    def chiave(a: Articolo):
        if campo == "prezzo":
            # i prezzi mancanti in fondo, qualunque sia il verso
            return (a.prezzo is None, a.prezzo if a.prezzo is not None else Decimal(0))
        if campo == "pagina":
            return (a.pagina, a.bbox[1])
        if campo == "note":
            return (not a.tutte_le_anomalie(), "; ".join(a.tutte_le_anomalie()))
        return (getattr(a, campo) or "").lower()

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
        self._solo_anomalie = False
        self._verso: dict[str, bool] = {}
        self._editor: tk.Widget | None = None
        self._prossimo_id = 0

        self._stile()
        self.tree = ttk.Treeview(self, columns=COLONNE, show="headings", selectmode="extended")
        for c in COLONNE:
            self.tree.heading(c, text=TITOLI[c], command=lambda c=c: self.ordina(c))
            self.tree.column(
                c,
                width=LARGHEZZE[c],
                anchor="e" if c in ("prezzo", "pagina") else "w",
                stretch=c in ("descrizione", "note"),
            )
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

    # --- dati -------------------------------------------------------------------------------

    def carica(self, articoli: list[Articolo]) -> None:
        self._articoli.clear()
        self._ordine.clear()
        for a in articoli:
            iid = f"a{self._prossimo_id}"
            self._prossimo_id += 1
            self._articoli[iid] = a
            self._ordine.append(iid)
        self._ridisegna()

    def articoli(self) -> list[Articolo]:
        """Tutti i record approvati, nell'ordine mostrato, ignorando il filtro."""
        return [self._articoli[i] for i in self._ordine]

    def articolo(self, iid: str) -> Articolo:
        return self._articoli[iid]

    def selezionato(self) -> Articolo | None:
        sel = self.tree.selection()
        return self._articoli[sel[0]] if sel else None

    def conteggi(self) -> tuple[int, int]:
        tutti = self.articoli()
        return len(tutti), sum(1 for a in tutti if a.tutte_le_anomalie())

    def imposta_filtro_anomalie(self, attivo: bool) -> None:
        self._solo_anomalie = attivo
        self._ridisegna()

    # --- vista ------------------------------------------------------------------------------

    def _valori(self, a: Articolo) -> tuple:
        return (
            a.modello,
            a.codice,
            a.ean,
            a.descrizione.replace("\n", " "),
            formatta_prezzo(a.prezzo) if a.prezzo is not None else (a.prezzo_testo or ""),
            a.pagina,
            "; ".join(a.tutte_le_anomalie()),
        )

    def _ridisegna(self) -> None:
        selezione = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for iid in self._ordine:
            a = self._articoli[iid]
            if self._solo_anomalie and not a.tutte_le_anomalie():
                continue
            tag = ("anomalia",) if a.tutte_le_anomalie() else ()
            self.tree.insert("", "end", iid=iid, values=self._valori(a), tags=tag)
        rimaste = [i for i in selezione if self.tree.exists(i)]
        if rimaste:
            self.tree.selection_set(rimaste)

    def _dopo_modifica(self) -> None:
        valida(self.articoli(), self.regole)  # i duplicati dipendono da tutte le righe
        self._ridisegna()
        if self.on_change:
            self.on_change()

    def ordina(self, campo: str) -> None:
        discendente = self._verso.get(campo, False)
        chiave = _chiave_ordinamento(campo)
        self._ordine.sort(key=lambda i: chiave(self._articoli[i]), reverse=discendente)
        if campo == "prezzo" and discendente:  # tieni comunque i mancanti in fondo
            self._ordine.sort(key=lambda i: self._articoli[i].prezzo is None)
        self._verso[campo] = not discendente
        for c in COLONNE:
            freccia = (" ▼" if discendente else " ▲") if c == campo else ""
            self.tree.heading(c, text=TITOLI[c] + freccia)
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
        if campo == "prezzo":
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
        campo = COLONNE[int(colonna[1:]) - 1]
        if campo not in MODIFICABILI:
            return
        if campo == "descrizione":
            self._modifica_descrizione(iid)
        else:
            self._modifica_in_linea(iid, campo, colonna)

    def _modifica_in_linea(self, iid: str, campo: str, colonna: str):
        self._chiudi_editor()
        x, y, w, h = self.tree.bbox(iid, colonna)
        a = self._articoli[iid]
        iniziale = formatta_prezzo(a.prezzo) if campo == "prezzo" and a.prezzo is not None else (
            a.prezzo_testo if campo == "prezzo" else getattr(a, campo)
        )
        entry = tk.Entry(self.tree)
        entry.insert(0, iniziale)
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=max(w, 120), height=h)
        entry.focus_set()
        self._editor = entry

        def conferma(_e=None):
            valore = entry.get()
            if not self.modifica_campo(iid, campo, valore):
                messagebox.showerror("Prezzo non valido", f"«{valore}» non e' un prezzo riconoscibile.", parent=self)
                entry.focus_set()
                return
            self._chiudi_editor()

        entry.bind("<Return>", conferma)
        entry.bind("<KP_Enter>", conferma)
        entry.bind("<Escape>", lambda e: self._chiudi_editor())
        entry.bind("<FocusOut>", lambda e: self._chiudi_editor())

    def _chiudi_editor(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None

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

        def salva():
            self.modifica_campo(iid, "descrizione", " ".join(box.get("1.0", "end").split()))
            fin.destroy()

        ctk.CTkButton(barra, text="Salva", command=salva, width=100).pack(side="right")
        ctk.CTkButton(barra, text="Annulla", command=fin.destroy, width=100, fg_color="gray").pack(
            side="right", padx=8
        )
        fin.after(100, fin.grab_set)
