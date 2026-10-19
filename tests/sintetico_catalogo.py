"""Terzo PDF sintetico: un catalogo come quello di Etabeta (Larentis), il layout piu' ostile visto finora.

Riproduce, misurate sul PDF vero: piu' tabelle per pagina, ognuna con l'intestazione
«MARCA | Articolo | titolo centrato | Listino»; codice e prezzo centrati in celle di 1, 2 o 4 righe a
interlinea uniforme, cosi' che fra un articolo e l'altro non c'e' nessuno spazio in piu'; linee di
griglia fra le celle (variante `linee=False`: senza); una tabella che prosegue nella pagina dopo
senza intestazione; una sezione con modelli scritti come nomi («IsoLater»); un prezzo «Chiedere /
quotazioni» su due righe (prezzi scritti «EUR 888,00»: il font helv dei PDF di prova non ha il «€»); testo promozionale centrato nella colonna della marca;
schede prodotto (pagine 140 e 225 del PDF vero): codice, titolo e prezzo sulla prima riga, una linea sotto e
le caratteristiche nella sola colonna della descrizione, nella cella successiva; un bollino «NEW» in corpo
12 sotto il codice, nella sua cella, che non e' un titolo di sezione (pagina 13).
"""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pymupdf

CORPO, PASSO = 9, 10.8
X_MARCA, X_ART, X_DESC, X_PREZZO_DX = 70, 167, 238, 566.7


@dataclass(frozen=True)
class AttesoCatalogo:
    modello: str
    descrizione: str
    prezzo: Decimal | None
    pagina: int
    categoria: str
    anomalie: tuple[str, ...] = ()
    marca: str | None = None  # None: quella dell'intestazione, la prima parte della categoria


# (righe del modello, righe della descrizione, righe del prezzo)
PAGINE = [
    [
        ("tabella", "VISSONIC", "MODULI INPUT"),
        (["VMHM4I"], ["Scheda input 4 canali HDMI"], ["EUR 888,00"]),
        (["VMHM2I-4K"], ["Scheda input 2 canali HDMI 4k@60Hz con", "audio analogico"], ["EUR 1.400,00"]),
        (["VMHM2I"], ["Scheda input 2 canali HDMI 4k@30Hz con", "audio analogico"], ["EUR 1.073,00"]),
        (["VMHD4I"], ["Scheda input 4 canali HDBaseT"], ["EUR 1.850,00"]),
        (["VMX-1"], ["Matrice modulare", "Potenza 20W", "Frequenza 2-15kHz", "Dimensioni 115x115"], ["EUR 44,00"]),
        ("spazio", 30),
        ("tabella", "ARX", "AUDIBOX"),
        (["IsoLater"], ["Trasformatore di isolamento"], ["EUR 218,00"]),
        (["Super Splitter", "Duo"], ["Transformer Isolated 2xInput", "2xDirect Out - 2xSplit 1"], ["EUR 340,00"]),
        (["Pro DI"], ["Bilanciatore attivo", "Active Direct Box"], ["Chiedere", "quotazioni"]),
    ],
    [
        # la tabella ARX prosegue senza intestazione in cima alla pagina
        (["Iso Switcher"], ["Commutatore stereo A/B", "2+2 XLR/In - 2 XLR/Out"], ["EUR 175,00"]),
        ("spazio", 30),
        ("tabella", "MOGAMI", "CAVI CAT5E"),
        (["M-CAT5E-2"], ["Cavo Mogami CAT5E - 2 metri"], ["EUR 16,00"]),
        (["M-CAT5E-3"], ["Cavo Mogami CAT5E - 3 metri"], ["EUR 19,00"]),
    ],
]
# solo nella variante con griglia: nel PDF vero le schede prodotto hanno sempre le linee, e i tre codici in
# piu' porterebbero oltre il 70% i modelli con l'aspetto di un codice, togliendo la sezione dei nomi (ARX)
PAGINA_SCHEDE = [
    ("tabella", "PAN Acoustic", "FULL RANGE SPEAKER"),
    ("scheda", "P04-AMT", "Diffusore passivo 2 Vie", "EUR 2.432,00",
     ["4x3,5 woofer high quality", "Potenza 200W/4ohm", "Dimensioni 506x107x118mm"]),
    ("scheda", "P12-AMT", "Diffusore passivo Bass Reflex", "EUR 3.553,00", ["12x3,5 woofer", "Peso 8,8kg"]),
    (["P8-CX"], ["Diffusore coassiale", "Woofer 8 HQ", "Risposta 60Hz-22KHz"], ["EUR 2.275,00"], "NEW"),
    (["PCX-WB"], ["Staffa a muro fissa"], ["EUR 185,00"]),
]
# una scheda col solo logo, senza intestazione di tabella e senza nominare la marca (pagina 224 del PDF vero):
# la marca della tabella precedente non vale, resta vuota e segnalata
PAGINA_SENZA_INTESTAZIONE = [
    (["CQ02-IR"], ["Kit telecomando IR"], ["EUR 56,00"]),
]

_V, _A, _M = "VISSONIC · MODULI INPUT", "ARX · AUDIBOX", "MOGAMI · CAVI CAT5E"
_P = "PAN Acoustic · FULL RANGE SPEAKER"
ATTESI = [
    AttesoCatalogo("VMHM4I", "Scheda input 4 canali HDMI", Decimal("888.00"), 1, _V),
    AttesoCatalogo("VMHM2I-4K", "Scheda input 2 canali HDMI 4k@60Hz con audio analogico", Decimal("1400.00"), 1, _V),
    AttesoCatalogo("VMHM2I", "Scheda input 2 canali HDMI 4k@30Hz con audio analogico", Decimal("1073.00"), 1, _V),
    AttesoCatalogo("VMHD4I", "Scheda input 4 canali HDBaseT", Decimal("1850.00"), 1, _V),
    AttesoCatalogo("VMX-1", "Matrice modulare Potenza 20W Frequenza 2-15kHz Dimensioni 115x115", Decimal("44.00"), 1, _V),
    AttesoCatalogo("IsoLater", "Trasformatore di isolamento", Decimal("218.00"), 1, _A),
    AttesoCatalogo("Super Splitter Duo", "Transformer Isolated 2xInput 2xDirect Out - 2xSplit 1", Decimal("340.00"), 1, _A),
    AttesoCatalogo("Pro DI", "Bilanciatore attivo Active Direct Box", None, 1, _A, ("Chiedere quotazioni",)),
    AttesoCatalogo("Iso Switcher", "Commutatore stereo A/B 2+2 XLR/In - 2 XLR/Out", Decimal("175.00"), 2, _A),
    AttesoCatalogo("M-CAT5E-2", "Cavo Mogami CAT5E - 2 metri", Decimal("16.00"), 2, _M),
    AttesoCatalogo("M-CAT5E-3", "Cavo Mogami CAT5E - 3 metri", Decimal("19.00"), 2, _M),
    AttesoCatalogo("P04-AMT", "Diffusore passivo 2 Vie 4x3,5 woofer high quality Potenza 200W/4ohm "
                   "Dimensioni 506x107x118mm", Decimal("2432.00"), 3, _P),
    AttesoCatalogo("P12-AMT", "Diffusore passivo Bass Reflex 12x3,5 woofer Peso 8,8kg", Decimal("3553.00"), 3, _P),
    AttesoCatalogo("P8-CX", "Diffusore coassiale Woofer 8 HQ Risposta 60Hz-22KHz", Decimal("2275.00"), 3, _P),
    AttesoCatalogo("PCX-WB", "Staffa a muro fissa", Decimal("185.00"), 3, _P),
    AttesoCatalogo("CQ02-IR", "Kit telecomando IR", Decimal("56.00"), 4, _P, ("Marca mancante",), marca=""),
]


def attesi(linee: bool) -> list[AttesoCatalogo]:
    """Senza griglia un nome su due righe («Super Splitter / Duo») non si distingue da due articoli:
    nella variante senza linee quell'articolo ha il nome su una riga sola."""
    if linee:
        return ATTESI
    return [AttesoCatalogo("Super Splitter Duo" if a.modello == "Super Splitter Duo" else a.modello,
                           a.descrizione, a.prezzo, a.pagina, a.categoria, a.anomalie) for a in ATTESI if a.pagina < 3]


def _scrivi(page, x, y, testo, corpo=CORPO):
    page.insert_text((x, y), testo, fontsize=corpo, fontname="helv")


def _a_destra(page, x_dx, y, testo, corpo=CORPO):
    _scrivi(page, x_dx - pymupdf.get_text_length(testo, fontname="helv", fontsize=corpo), y, testo, corpo)


def _centrato(page, x_centro, y, testo, corpo=CORPO):
    _scrivi(page, x_centro - pymupdf.get_text_length(testo, fontname="helv", fontsize=corpo) / 2, y, testo, corpo)


def crea_catalogo(percorso: str | Path, linee: bool = True) -> Path:
    percorso = Path(percorso)
    doc = pymupdf.open()
    for n, contenuto in enumerate(PAGINE + ([PAGINA_SCHEDE, PAGINA_SENZA_INTESTAZIONE] if linee else []), 1):
        page = doc.new_page(width=595.2, height=842)
        _centrato(page, 297, 22, "SUONO", 14)  # testata ripetuta
        _scrivi(page, 520, 820, str(n + 3), 9)  # numero di pagina
        y = 60.0
        if n == 1:  # testo promozionale centrato nella colonna della marca, fra una tabella e l'altra
            for i, riga in enumerate(("Design compatto", "e versatile")):
                _centrato(page, 110, 360 + i * PASSO, riga)
        for elem in contenuto:
            if elem[0] == "spazio":
                y += elem[1]
                continue
            if elem[0] == "scheda":
                # prima riga: codice, titolo e prezzo; sotto, separate da una linea, le caratteristiche
                _, codice, titolo, prezzo, caratteristiche = elem
                for riga_y in (y, y + PASSO):
                    if linee:
                        page.draw_line((135, riga_y - 6.5), (570, riga_y - 6.5), width=0.5)
                _scrivi(page, X_ART, y, codice)
                _scrivi(page, X_DESC, y, titolo)
                _a_destra(page, X_PREZZO_DX, y, prezzo)
                for i, testo in enumerate(caratteristiche, 1):
                    _scrivi(page, X_DESC, y + i * PASSO, testo)
                y += (len(caratteristiche) + 1) * PASSO
                continue
            if elem[0] == "tabella":
                _, marca, titolo = elem
                _scrivi(page, X_MARCA, y, marca, 10)
                _scrivi(page, X_ART, y, "Articolo")
                _centrato(page, 380, y, titolo)
                _scrivi(page, 527, y, "Listino")
                y += 13
                continue
            modello, descrizione, prezzi, *bollino = elem
            if not linee and len(modello) > 1:
                modello = [" ".join(modello)]
            righe = max(len(modello), len(descrizione), len(prezzi))
            if linee:  # bordo superiore della cella: poco sotto la cima del primo testo, come nel PDF vero
                page.draw_line((135, y - 6.5), (570, y - 6.5), width=0.5)
            for col, testi, allinea in ((X_ART, modello, "sx"), (X_DESC, descrizione, "sx"),
                                        (X_PREZZO_DX, prezzi, "dx")):
                partenza = y + (righe - len(testi)) * PASSO / 2  # centrato nella cella
                for i, testo in enumerate(testi):
                    if allinea == "dx":
                        _a_destra(page, col, partenza + i * PASSO, testo)
                    else:
                        _scrivi(page, col, partenza + i * PASSO, testo)
            if bollino:  # in grande sotto il codice, nell'ultima riga della sua cella
                _scrivi(page, X_ART, y + (righe - 1) * PASSO, bollino[0], 12)
            y += righe * PASSO
    doc.save(percorso)
    doc.close()
    return percorso
