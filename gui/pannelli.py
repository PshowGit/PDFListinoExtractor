"""Pannelli divisi da un separatore trascinabile, del colore della finestra che li contiene.

customtkinter non ne ha: si usa il PanedWindow di Tk, con lo sfondo del contenitore perche' il separatore
si veda solo come uno spazio fra le parti.
"""
import tkinter as tk

import customtkinter as ctk

SPESSORE = 8  # del separatore, in pixel: abbastanza da prenderlo col mouse


def colore_di(widget) -> str:
    """Il colore di sfondo con cui customtkinter disegna `widget` (risalendo i contenitori trasparenti)."""
    while widget is not None:
        try:
            colore = widget.cget("fg_color")
        except (tk.TclError, ValueError):
            colore = None
        if colore and colore != "transparent":
            if isinstance(colore, (list, tuple)):
                colore = colore[1] if ctk.get_appearance_mode() == "Dark" else colore[0]
            return colore
        widget = widget.master
    return "gray86"


def pannello_diviso(master, verticale: bool) -> tk.PanedWindow:
    """Un PanedWindow che impila le parti (`verticale`) o le affianca; si aggiungono con `add`."""
    colore = colore_di(master)
    return tk.PanedWindow(master, orient="vertical" if verticale else "horizontal", sashwidth=SPESSORE,
                          sashrelief="flat", borderwidth=0, background=colore, opaqueresize=True)
