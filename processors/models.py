"""Strutture dati condivise fra estrattori, parser, validatore, esportatore e interfaccia."""
from dataclasses import dataclass, field
from decimal import Decimal

# Campi esportati, nell'ordine delle colonne del foglio "Listino".
CAMPI = ("modello", "codice", "ean", "descrizione", "prezzo")
INTESTAZIONI = {
    "modello": "Modello",
    "codice": "Codice",
    "ean": "EAN",
    "descrizione": "Descrizione",
    "prezzo": "Prezzo",
}


@dataclass(frozen=True)
class Span:
    """Un frammento di testo con la sua posizione nella pagina (coordinate PDF, punti)."""

    testo: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    pagina: int
    confidenza: float | None = None  # solo per il testo da OCR, 0-100


@dataclass
class Articolo:
    modello: str = ""
    codice: str = ""
    ean: str = ""
    descrizione: str = ""
    prezzo: Decimal | None = None
    pagina: int = 0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    categoria: str = ""
    prezzo_testo: str = ""
    da_ocr: bool = False
    # Vero se la descrizione e' stata copiata dal nome del modello perche' la colonna era vuota.
    descrizione_da_modello: bool = False
    confidenza_minima: float | None = None
    # Anomalie rilevate durante l'estrazione, per campo: modificare il campo le rimuove,
    # perche' a quel punto il valore l'ha deciso l'utente e non il parser.
    note_estrazione: dict[str, str] = field(default_factory=dict)
    # Anomalie del validatore: ricalcolate da zero a ogni validazione.
    anomalie: list[str] = field(default_factory=list)

    def tutte_le_anomalie(self) -> list[str]:
        return list(self.note_estrazione.values()) + self.anomalie

    def imposta(self, campo: str, valore) -> None:
        setattr(self, campo, valore)
        self.note_estrazione.pop(campo, None)
        if campo == "descrizione":
            self.descrizione_da_modello = False
