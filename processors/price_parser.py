"""Normalizzazione dei prezzi: dal testo del PDF a un Decimal, senza indovinare."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_VALUTA = re.compile(r"(€|eur(o)?|\s| )", re.IGNORECASE)

_IT_MIGLIAIA = re.compile(r"^\d{1,3}(\.\d{3})+,\d{1,2}$")  # 1.234,56
_IT_SEMPLICE = re.compile(r"^\d+,\d{1,2}$")  # 1234,56 / 12,5
_EN_MIGLIAIA = re.compile(r"^\d{1,3}(,\d{3})+\.\d{1,2}$")  # 1,234.56
_EN_SEMPLICE = re.compile(r"^\d+\.\d{1,2}$")  # 1234.56
_SOLO_MIGLIAIA_PUNTO = re.compile(r"^\d{1,3}(\.\d{3})+$")  # 1.234 -> migliaia IT o decimali EN?
_SOLO_MIGLIAIA_VIRGOLA = re.compile(r"^\d{1,3}(,\d{3})+$")  # 1,234 -> migliaia EN o decimali IT?
_INTERO = re.compile(r"^\d+$")


@dataclass(frozen=True)
class RisultatoPrezzo:
    valore: Decimal | None
    ambiguo: bool = False
    motivo: str = ""


def _dec(testo: str) -> Decimal:
    return Decimal(testo).quantize(Decimal("0.01"))


def parse_prezzo(testo: str, formato: str = "auto") -> RisultatoPrezzo:
    """Interpreta un prezzo. `formato` e' "it", "en" o "auto".

    Un valore riconosciuto ma interpretabile in due modi torna con `ambiguo=True`
    e il motivo: la scelta finale e' dell'utente, non del parser.
    """
    if testo is None:
        return RisultatoPrezzo(None, motivo="Prezzo mancante")
    t = _VALUTA.sub("", str(testo))
    if not t:
        return RisultatoPrezzo(None, motivo="Prezzo mancante")
    try:
        if _IT_MIGLIAIA.match(t) or (_IT_SEMPLICE.match(t) and formato != "en"):
            return RisultatoPrezzo(_dec(t.replace(".", "").replace(",", ".")))
        if _EN_MIGLIAIA.match(t) or (_EN_SEMPLICE.match(t) and formato != "it"):
            return RisultatoPrezzo(_dec(t.replace(",", "")))
        if _IT_SEMPLICE.match(t):  # formato "en" ma testo con virgola decimale
            return RisultatoPrezzo(_dec(t.replace(",", ".")), True, f"Formato prezzo inatteso: «{testo}»")
        if _EN_SEMPLICE.match(t):  # formato "it" ma testo con punto decimale
            return RisultatoPrezzo(_dec(t), True, f"Formato prezzo inatteso: «{testo}»")
        if _SOLO_MIGLIAIA_PUNTO.match(t):
            if formato == "it":
                return RisultatoPrezzo(_dec(t.replace(".", "")))
            return RisultatoPrezzo(_dec(t.replace(".", "")), True, f"Prezzo ambiguo: «{testo}» (migliaia o decimali?)")
        if _SOLO_MIGLIAIA_VIRGOLA.match(t):
            if formato == "en":
                return RisultatoPrezzo(_dec(t.replace(",", "")))
            return RisultatoPrezzo(_dec(t.replace(",", "")), True, f"Prezzo ambiguo: «{testo}» (migliaia o decimali?)")
        if _INTERO.match(t):
            return RisultatoPrezzo(_dec(t))
    except InvalidOperation:
        pass
    return RisultatoPrezzo(None, motivo=f"Prezzo non riconosciuto: «{testo}»")


def sembra_prezzo(testo: str) -> bool:
    """Vero se il testo ha la forma di un prezzo (anche ambiguo)."""
    return parse_prezzo(testo).valore is not None


def formatta_prezzo(valore: Decimal | None) -> str:
    """Rappresentazione italiana per l'interfaccia: 1.234,56."""
    if valore is None:
        return ""
    s = f"{valore:,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")
