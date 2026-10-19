"""Controlli sugli articoli estratti. Nulla viene corretto o scartato: si segnala soltanto."""
import re
from collections import Counter, defaultdict
from decimal import Decimal

from processors.models import Articolo
from processors.profilo import CAMPI_DATI, campi_mappati, normalizza


def ean_valido(ean: str) -> bool:
    """GTIN-8/12/13/14 con cifra di controllo corretta."""
    if not ean.isdigit() or len(ean) not in (8, 12, 13, 14):
        return False
    cifre = [int(c) for c in ean]
    controllo = cifre.pop()
    # da destra, escluso il controllo: pesi 3,1,3,1...
    somma = sum(c * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(cifre)))
    return (10 - somma % 10) % 10 == controllo


def _parentesi_sbilanciate(testo: str) -> bool:
    return testo.count("(") != testo.count(")")


# fin dove un'anomalia dice il suo tipo: dopo vengono i dettagli (valore, colonna, pagine)
_DETTAGLI = re.compile(r"[:(«—]")
_VARIABILI = re.compile(r"\s+(a pagina \d+|nella colonna)\s*$")


def tipo_anomalia(testo: str) -> str:
    """Il tipo di un'anomalia, senza i dettagli che cambiano da un articolo all'altro.

    «Duplicato: compare 3 volte (pag. 4, 7)» -> «Duplicato»; «Prezzo non riconosciuto: «€ —» (colonna
    «Listino»)» -> «Prezzo non riconosciuto»; «Testo in piu' a pagina 12 (colonna...)» -> «Testo in piu'».
    """
    tipo = _DETTAGLI.split(testo, maxsplit=1)[0].strip()
    return _VARIABILI.sub("", tipo).strip() or testo.strip()


def conta_tipi(articoli: list[Articolo]) -> list[tuple[str, int]]:
    """Quanti articoli hanno ciascun tipo di anomalia, dal piu' frequente; un articolo conta una volta per tipo."""
    conteggio = Counter(t for a in articoli for t in {tipo_anomalia(x) for x in a.tutte_le_anomalie()})
    return sorted(conteggio.items(), key=lambda kv: (-kv[1], kv[0]))


def chiave_duplicato(a: Articolo) -> str:
    return (a.codice or a.modello).strip().upper()


def valida(articoli: list[Articolo], regole: dict | None = None) -> None:
    """Ricalcola `anomalie` su ogni articolo. Si puo' rieseguire dopo ogni modifica dell'utente."""
    regole = regole or {}
    prezzo_massimo = Decimal(str(regole.get("prezzo_massimo", 1_000_000)))
    conf_minima = regole.get("ocr", {}).get("confidenza_minima", 70)
    # Si segnala come mancante solo cio' che il profilo prevede: un listino senza colonna Modello
    # metteva "Modello mancante" su ogni riga, e un'anomalia su tutte le righe non ne indica nessuna
    # (trovato nel wizard col PDF generico). Senza profilo valgono tutti i campi.
    previsti = set(CAMPI_DATI)
    if regole.get("colonne"):
        # le colonne di testo in piu' non hanno controlli: sono testo libero
        previsti = campi_mappati(normalizza(regole))

    marca_prevista = any(c.get("campo") == "marca" for c in regole.get("colonne") or [])

    pagine_per_chiave: dict[str, list[int]] = defaultdict(list)
    for a in articoli:
        k = chiave_duplicato(a)
        if k:
            pagine_per_chiave[k].append(a.pagina)

    for a in articoli:
        an: list[str] = []
        note = a.note_estrazione
        if "modello" in previsti and not a.modello.strip() and "modello" not in note:
            an.append("Modello mancante")
        if "codice" in previsti and not a.codice.strip() and "codice" not in note:
            an.append("Codice mancante")
        if "descrizione" in previsti and not a.descrizione.strip():
            an.append("Descrizione mancante")
        if a.prezzo is None:
            if "prezzo" in previsti and "prezzo" not in note:
                an.append("Prezzo mancante")
        elif a.prezzo == 0:
            an.append("Prezzo pari a zero — verificare")
        elif a.prezzo < 0 or a.prezzo > prezzo_massimo:
            an.append(f"Prezzo fuori scala: {a.prezzo}")
        if marca_prevista and not str(a.valore("marca")).strip():
            an.append("Marca mancante")
        if a.ean and not ean_valido(a.ean) and "ean" not in note:
            an.append(f"EAN non valido: «{a.ean}»")
        if _parentesi_sbilanciate(a.modello) or _parentesi_sbilanciate(a.descrizione):
            an.append("Testo forse troncato nel PDF (parentesi non chiusa)")
        k = chiave_duplicato(a)
        if k and len(pagine_per_chiave[k]) > 1:
            altre = sorted(set(pagine_per_chiave[k]))
            an.append(f"Duplicato: compare {len(pagine_per_chiave[k])} volte (pag. {', '.join(map(str, altre))})")
        if a.da_ocr and a.confidenza_minima is not None and a.confidenza_minima < conf_minima:
            an.append(f"Testo OCR incerto (confidenza {a.confidenza_minima:.0f}%)")
        a.anomalie = an
