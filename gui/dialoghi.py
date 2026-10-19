"""Piccole finestre di dialogo modali, nello stile delle altre finestre.

CTkInputDialog non si puo' compilare in anticipo e ha i pulsanti in inglese: per rinominare serve
il nome attuale gia' scritto e selezionato.
"""
import tkinter as tk

import customtkinter as ctk

from percorsi import icona


class DialogoTesto(ctk.CTkToplevel):
    """Chiede una riga di testo, gia' compilata con `iniziale`. `risultato` resta None se si annulla."""

    def __init__(self, master, titolo: str, messaggio: str, iniziale: str = ""):
        super().__init__(master)
        self.title(titolo)
        self.resizable(False, False)
        self.transient(master)
        if icona().is_file():
            self.after(250, lambda: self.winfo_exists() and self.iconbitmap(str(icona())))
        self.risultato: str | None = None

        self.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(self, text=messaggio, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(16, 6)
        )
        self.campo = ctk.CTkEntry(self, width=380)
        self.campo.insert(0, iniziale)
        self.campo.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20)
        ctk.CTkButton(self, text="OK", width=110, command=self._conferma).grid(
            row=2, column=0, sticky="e", padx=(20, 6), pady=16
        )
        ctk.CTkButton(self, text="Annulla", width=110, fg_color="gray", command=self.destroy).grid(
            row=2, column=1, sticky="w", padx=(6, 20), pady=16
        )
        self.bind("<Return>", lambda e: self._conferma())
        self.bind("<Escape>", lambda e: self.destroy())
        self._centra(master)
        self.after(150, self._attiva)  # prima la finestra non e' ancora visibile e il fuoco non resta

    def _centra(self, master):
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        # wm_geometry e non geometry: CTk riscala i valori di geometry, mentre winfo_* sono gia' in pixel
        self.wm_geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _attiva(self):
        if not self.winfo_exists():
            return
        self.lift()
        self.campo.focus_set()
        self.campo.select_range(0, "end")
        try:
            self.grab_set()  # finche' e' aperta, la finestra principale non risponde
        except tk.TclError:
            pass

    def _conferma(self):
        self.risultato = self.campo.get()
        self.destroy()


def chiedi_testo(master, titolo: str, messaggio: str, iniziale: str = "") -> str | None:
    dialogo = DialogoTesto(master, titolo, messaggio, iniziale)
    master.wait_window(dialogo)
    return dialogo.risultato
