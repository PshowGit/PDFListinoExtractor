"""Finestra che mostra la pagina di origine di un articolo, con l'articolo evidenziato."""
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
import pymupdf
from PIL import Image, ImageDraw, ImageTk

from percorsi import icona
from processors.models import Articolo

ZOOM = 2.0
MARGINE = 4


def immagine_pagina(percorso: Path, articolo: Articolo) -> Image.Image:
    with pymupdf.open(percorso) as doc:
        page = doc[articolo.pagina - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    x0, y0, x1, y1 = (v * ZOOM for v in articolo.bbox)
    if x1 > x0:
        livello = Image.new("RGBA", img.size, (0, 0, 0, 0))
        disegno = ImageDraw.Draw(livello)
        rett = (x0 - MARGINE, y0 - MARGINE, x1 + MARGINE, y1 + MARGINE)
        disegno.rectangle(rett, fill=(255, 200, 0, 60), outline=(230, 80, 0, 255), width=3)
        img = Image.alpha_composite(img.convert("RGBA"), livello).convert("RGB")
    return img


class FinestraPagina(ctk.CTkToplevel):
    def __init__(self, master, percorso: Path, articolo: Articolo):
        super().__init__(master)
        self.title(f"Pagina {articolo.pagina} — {articolo.codice or articolo.modello}")
        if icona().is_file():
            # CTkToplevel imposta la propria icona dopo 200 ms: la nostra va messa dopo
            self.after(250, lambda: self.iconbitmap(str(icona())))
        self.geometry("900x900")
        img = immagine_pagina(percorso, articolo)
        self._foto = ImageTk.PhotoImage(img)  # riferimento da tenere, o tk lo cancella

        cornice = tk.Frame(self)
        cornice.pack(fill="both", expand=True)
        canvas = tk.Canvas(cornice, highlightthickness=0, background="#777777")
        sy = tk.Scrollbar(cornice, orient="vertical", command=canvas.yview)
        sx = tk.Scrollbar(cornice, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set, scrollregion=(0, 0, img.width, img.height))
        canvas.create_image(0, 0, image=self._foto, anchor="nw")
        canvas.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        cornice.grid_rowconfigure(0, weight=1)
        cornice.grid_columnconfigure(0, weight=1)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        # porta l'articolo in vista
        y_centro = (articolo.bbox[1] * ZOOM) - 200
        self.after(50, lambda: canvas.yview_moveto(max(0.0, y_centro / img.height)))
        self.after(100, self.lift)
