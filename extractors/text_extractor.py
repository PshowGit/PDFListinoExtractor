"""Estrazione del testo con coordinate dalle pagine con testo selezionabile."""
import re

import pymupdf

from processors.models import Span

# Senza TEXT_PRESERVE_IMAGES: di default "dict" porta con se' i byte di ogni immagine della pagina,
# ed era il 75% del tempo di estrazione sul listino JBL (4-11 immagini per pagina).
FLAG_TESTO = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

# Due spans della stessa riga piu' vicini di cosi' (in frazioni del corpo) sono la stessa parola:
# un cambio di font a meta' parola, o un glifo scritto a parte.
UNIONE_SENZA_SPAZIO = 0.15
# ...a meno che il secondo sia un bollino: una parola sola in maiuscolo, dopo uno spazio e piu' grande di oltre
# questa quota, come «NEW» in corpo 12 dopo il codice «23550 » in corpo 9 (Etabeta, pagina 269). Unito, il codice
# diventava un titolo: l'articolo spariva e il titolo era la categoria dei seguenti
SCARTO_CORPO_UNIONE = 0.15
_NUMERO = re.compile(r"^\d[\d.,]*$")

# Legature di Calibri con il ToUnicode sbagliato, come le scrive Acrobat Distiller: il PDF dice
# "Ɵ" dove il glifo e' "ti". Misurato sul listino Etabeta (387 pagine): 187 "Ɵ", 58 "Ʃ", 30 "ƫ", tutti
# in Calibri e mai altrove; le parole ricomposte (tipo, prodotto, attivazione) non lasciano dubbi.
GLIFI_CALIBRI = {"Ɵ": "ti", "Ʃ": "tt", "ƫ": "tti"}
LEGATURE = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
# Lo stesso listino ha 3.400 legature vere seguite da uno spazio che non c'e' ("Ampliﬁ catore"):
# lo spazio fra la legatura e una minuscola si toglie, quello davanti alla legatura resta.
_SPAZIO_DOPO_LEGATURA = re.compile("([" + "".join(LEGATURE) + "]) (?=[a-zà-ÿ])")


def normalizza_glifi(testo: str) -> str:
    testo = _SPAZIO_DOPO_LEGATURA.sub(r"\1", testo)
    for vecchio, nuovo in (*GLIFI_CALIBRI.items(), *LEGATURE.items()):
        testo = testo.replace(vecchio, nuovo)
    return testo


def _due_numeri(prec: dict, s: dict) -> bool:
    """Due numeri separati da uno spazio sono due celle, anche se si toccano: nel listino Midiware di giugno 2017
    «15.750,00», uno span col solo spazio e «13.853,00» erano una scritta sola, che finiva nella colonna dopo."""
    sinistra, destra = prec["text"].split()[-1:], s["text"].split()[:1]
    return (bool(sinistra and destra) and (prec["text"][-1:].isspace() or s["text"][:1].isspace())
            and all(_NUMERO.match(t[0]) for t in (sinistra, destra)))


def _e_bollino(prec: dict, s: dict) -> bool:
    """Se `s` e' un bollino scritto subito dopo `prec` (v. SCARTO_CORPO_UNIONE)."""
    parole = s["text"].split()
    return (prec["text"][-1:].isspace() and len(parole) == 1 and parole[0].isupper()
            and s["size"] > (1 + SCARTO_CORPO_UNIONE) * prec["size"])


_STILE_NEL_FONT = re.compile(r"^.*\+|[-,].*$|(MT|PS)$")


def _famiglia(font: str | None) -> str:
    """Il nome del font senza prefisso del sottoinsieme, stile e suffisso: «Arial-BoldItalicMT» e «ArialMT» sono Arial."""
    return _STILE_NEL_FONT.sub("", _STILE_NEL_FONT.sub("", font or ""))


# «Articolo: SHARK H4 Plus»: un'etichetta con i due punti a inizio riga e al piu' tre parole di valore, la prima
# di almeno due caratteri («Dimensioni: Ø 780 mm», p93, ha un simbolo in un altro font: non e' un codice)
_ETICHETTA_E_CODICE = re.compile(r"^\s*[^\W\d_][\w.]*:\s*(?=\S*\w\w)\S+(?:\s+\S+){0,2}\s*$")


def _codice_e_descrizione(prec: dict, s: dict) -> bool:
    """Se `prec` e' «etichetta: codice» e `s` e' scritto in un'altra famiglia di font, dopo uno spazio.

    Etabeta, pagine di AV-MATRIX: «Articolo:» e il codice in Arial, la descrizione in Arial Narrow sulla stessa
    riga. Uniti, il codice non e' piu' un codice e l'articolo sparisce. Serve l'etichetta: un «Ω» o una virgoletta
    in Arial dentro una frase in Arial Narrow (p65) o un titolo in maiuscolo scritto con due font (p154) non sono
    un codice, e un grassetto o un corsivo della stessa famiglia non separa nulla.
    """
    a, b = _famiglia(prec.get("font")), _famiglia(s.get("font"))
    return bool(a and b and a != b and (prec["text"][-1:].isspace() or s["text"][:1].isspace())
                and _ETICHETTA_E_CODICE.match(prec["text"]))


def _unisci_contigui(spans: list[dict]) -> list[dict]:
    """Spans di una riga PyMuPDF uniti quando si toccano: "Proge" + "Ʃ" + "ato" e' una parola sola.

    Un bollino resta a parte, e cosi' il testo che lo segue in un altro corpo («NEW» e la descrizione di SK213-T3).
    Una scritta grande seguita da una piu' piccola resta invece unita («SW Turbo Speaker Horn», «NEW MI SERIE»):
    divisa, la parte piccola cadeva fra i dati e diventava un articolo.
    """
    uniti: list[dict] = []
    for s in spans:
        if uniti:
            prec = uniti[-1]
            distacco = s["bbox"][0] - prec["bbox"][2]
            stessa_riga = abs(s["bbox"][1] - prec["bbox"][1]) < 0.5 * max(s["size"], 1)
            dopo_bollino = prec.get("bollino") and abs(s["size"] - prec["size"]) > SCARTO_CORPO_UNIONE * prec["size"]
            if (stessa_riga and -0.5 <= distacco < UNIONE_SENZA_SPAZIO * max(s["size"], prec["size"])
                    and not _e_bollino(prec, s) and not dopo_bollino and not _due_numeri(prec, s)
                    and not _codice_e_descrizione(prec, s)):
                b0, b1 = prec["bbox"], s["bbox"]
                uniti[-1] = {
                    "text": prec["text"] + s["text"],
                    "bbox": (b0[0], min(b0[1], b1[1]), b1[2], max(b0[3], b1[3])),
                    "size": max(prec["size"], s["size"]),
                    "font": s.get("font"),
                }
                continue
            if stessa_riga and _e_bollino(prec, s):
                uniti.append({"text": s["text"], "bbox": tuple(s["bbox"]), "size": s["size"], "bollino": True,
                              "font": s.get("font")})
                continue
        uniti.append({"text": s["text"], "bbox": tuple(s["bbox"]), "size": s["size"], "font": s.get("font")})
    return uniti


def estrai_span(page: pymupdf.Page, pagina: int) -> list[Span]:
    """Tutti i frammenti di testo non vuoti della pagina, con bbox e corpo del carattere."""
    spans: list[Span] = []
    for blocco in page.get_text("dict", flags=FLAG_TESTO)["blocks"]:
        for riga in blocco.get("lines", []):
            for s in _unisci_contigui(riga["spans"]):
                testo = normalizza_glifi(s["text"]).strip()
                if not testo:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                spans.append(Span(testo, x0, y0, x1, y1, s["size"], pagina))
    return spans
