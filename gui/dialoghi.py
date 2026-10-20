"""Piccole finestre di dialogo modali, nello stile delle altre finestre.

CTkInputDialog non si puo' compilare in anticipo e ha i pulsanti in inglese: per rinominare serve
il nome attuale gia' scritto e selezionato.
"""
import queue
import threading
import tkinter as tk

import customtkinter as ctk

import aggiornamento
from percorsi import icona
from version import __version__


def in_primo_piano(finestra: tk.Misc) -> None:
    """Porta una finestra davanti alle altre, col fuoco. Su Windows un CTkToplevel appena creato finisce dietro la
    finestra principale (CTk ne sistema l'icona e i colori dopo l'apertura), e chi clicca «Configura nuovo
    fornitore» credeva che non succedesse nulla. Per un attimo «sempre in primo piano», poi di nuovo normale:
    la finestra principale si deve poter riportare davanti."""
    def davanti():
        if not finestra.winfo_exists():
            return
        if finestra.state() == "iconic":
            finestra.deiconify()
        finestra.lift()
        finestra.attributes("-topmost", True)
        finestra.focus_force()
        finestra.after(400, lambda: finestra.winfo_exists() and finestra.attributes("-topmost", False))

    davanti()
    finestra.after(300, davanti)  # dopo le sistemazioni di CTk, che riportavano davanti la principale


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


class FinestraAvvisi(ctk.CTkToplevel):
    """Tutti gli avvisi dell'estrazione, uno per riga, da leggere o copiare. Non e' modale: si puo' tenere
    aperta accanto alla tabella. Prima se ne vedevano i primi 20 in un messaggio (sul catalogo Etabeta 127),
    e un avviso come «TUTTA QUESTA LINEA E' IN ESAURIMENTO» poteva restare nascosto."""

    def __init__(self, master, avvisi: list[str]):
        super().__init__(master)
        self.title(f"Avvisi dell'estrazione ({len(avvisi)})")
        self.geometry("820x420")
        self.transient(master)
        if icona().is_file():
            self.after(250, lambda: self.winfo_exists() and self.iconbitmap(str(icona())))
        self.avvisi = list(avvisi)
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=780, text=(
            "Testo che il programma non ha attribuito a nessun articolo, o pagine che non ha potuto leggere. "
            "Non blocca l'esportazione: serve a controllare che non manchi niente.")).pack(
            fill="x", padx=14, pady=(12, 4))
        self.testo = ctk.CTkTextbox(self, wrap="word")
        self.testo.pack(fill="both", expand=True, padx=12, pady=4)
        self.testo.insert("1.0", "\n".join(self.avvisi))
        self.testo.configure(state="disabled")
        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(barra, text="Chiudi", width=110, command=self.destroy).pack(side="right")
        ctk.CTkButton(barra, text="Copia negli appunti", width=150, fg_color="gray", command=self.copia).pack(
            side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        in_primo_piano(self)

    def copia(self) -> None:
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.avvisi))


def _modale(finestra: ctk.CTkToplevel) -> None:
    if not finestra.winfo_exists():
        return
    finestra.lift()
    finestra.focus_force()
    try:
        finestra.grab_set()  # finche' e' aperta, la finestra principale non risponde
    except tk.TclError:
        pass


class DialogoAggiornamento(ctk.CTkToplevel):
    """Le note della nuova versione e la scelta: «aggiorna», «ignora» o None (Annulla, Esc, chiusura).

    Se il programma non viene da un setup (`installabile` falso) non si puo' aggiornare da qui: al
    posto di «Aggiorna ora» c'e' la pagina della release."""

    def __init__(self, master, rilascio: aggiornamento.Rilascio, installabile: bool = True):
        super().__init__(master)
        self.title("Aggiornamento disponibile")
        self.geometry("680x480")
        self.transient(master)
        if icona().is_file():
            self.after(250, lambda: self.winfo_exists() and self.iconbitmap(str(icona())))
        self.scelta: str | None = None
        ctk.CTkLabel(
            self, anchor="w", font=ctk.CTkFont(size=15, weight="bold"),
            text=f"E' disponibile la versione {rilascio.versione} (installata: {__version__})",
        ).pack(fill="x", padx=16, pady=(14, 2))
        spiegazione = (
            "«Aggiorna ora» scarica l'installazione, ne verifica l'integrita' e la avvia: il programma si chiude "
            "e si riapre aggiornato. Fornitori configurati, log e file Excel restano dove sono."
            if installabile else
            "Questa copia del programma non e' stata installata col setup, quindi non si aggiorna da sola: "
            "l'installazione si scarica dalla pagina della versione."
        )
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=640, text=spiegazione).pack(
            fill="x", padx=16, pady=(0, 6))
        self.note = ctk.CTkTextbox(self, wrap="word")
        self.note.pack(fill="both", expand=True, padx=12, pady=4)
        self.note.insert("1.0", aggiornamento.testo_note(rilascio.note) or "Nessuna nota per questa versione.")
        self.note.configure(state="disabled")
        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkButton(barra, text="Annulla", width=110, fg_color="gray", command=self.destroy).pack(side="right")
        ctk.CTkButton(barra, text="Ignora questa versione", width=170, fg_color="gray",
                      command=lambda: self._scegli("ignora")).pack(side="right", padx=8)
        self.btn_aggiorna = ctk.CTkButton(
            barra, text="Aggiorna ora" if installabile else "Apri la pagina di download", width=190,
            command=lambda: self._scegli("aggiorna"),
        )
        self.btn_aggiorna.pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        in_primo_piano(self)
        self.after(150, lambda: _modale(self))

    def _scegli(self, scelta: str) -> None:
        self.scelta = scelta
        self.destroy()


class FinestraScaricamento(ctk.CTkToplevel):
    """Scarica il setup in un thread, con la barra di avanzamento. Alla fine `percorso` e' il file
    scaricato e verificato, oppure None con `errore` (o niente, se si e' annullato)."""

    def __init__(self, master, rilascio: aggiornamento.Rilascio, scarica=None):
        scarica = scarica or aggiornamento.scarica
        super().__init__(master)
        self.title("Aggiornamento")
        self.resizable(False, False)
        self.transient(master)
        if icona().is_file():
            self.after(250, lambda: self.winfo_exists() and self.iconbitmap(str(icona())))
        self.percorso = None
        self.errore: str | None = None
        self._annulla = threading.Event()
        self._coda: queue.Queue = queue.Queue()
        ctk.CTkLabel(self, anchor="w", text=f"Scaricamento della versione {rilascio.versione}…").pack(
            fill="x", padx=20, pady=(16, 6))
        self.barra = ctk.CTkProgressBar(self, width=420)
        self.barra.set(0)
        self.barra.pack(padx=20)
        self.lbl = ctk.CTkLabel(self, anchor="w", text_color="gray", text="")
        self.lbl.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkButton(self, text="Annulla", width=110, fg_color="gray", command=self.annulla).pack(pady=14)
        self.protocol("WM_DELETE_WINDOW", self.annulla)
        self.bind("<Escape>", lambda e: self.annulla())

        def lavoro():
            try:
                esito = ("fatto", scarica(rilascio, lambda letti, totale: self._coda.put(("avanzamento", letti, totale)),
                                          self._annulla.is_set))
            except aggiornamento.AggiornamentoNonValido as e:
                esito = ("errore", str(e))
            except OSError as e:
                esito = ("errore", f"Scaricamento non riuscito: {e}")
            self._coda.put(esito)

        threading.Thread(target=lavoro, daemon=True).start()
        in_primo_piano(self)
        self.after(150, lambda: _modale(self))
        self.after(100, self._controlla)

    def annulla(self) -> None:
        self._annulla.set()
        self.lbl.configure(text="Annullamento…")

    def _controlla(self) -> None:
        if not self.winfo_exists():
            return
        ultimo = None
        try:
            while True:
                messaggio = self._coda.get_nowait()
                if messaggio[0] != "avanzamento":
                    if messaggio[0] == "fatto":
                        self.percorso = messaggio[1]
                    else:
                        self.errore = messaggio[1]
                    self.destroy()
                    return
                ultimo = messaggio  # si ridisegna solo l'ultimo avanzamento
        except queue.Empty:
            pass
        if ultimo is not None and not self._annulla.is_set():
            _, letti, totale = ultimo
            if totale:
                self.barra.set(min(letti / totale, 1))
                self.lbl.configure(text=f"{letti / 1e6:.1f} di {totale / 1e6:.1f} MB")
            else:
                self.lbl.configure(text=f"{letti / 1e6:.1f} MB")
        self.after(100, self._controlla)


def chiedi_testo(master, titolo: str, messaggio: str, iniziale: str = "") -> str | None:
    dialogo = DialogoTesto(master, titolo, messaggio, iniziale)
    master.wait_window(dialogo)
    return dialogo.risultato
