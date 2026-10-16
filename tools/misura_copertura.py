"""Quanti prezzi del PDF l'estrazione attribuisce a un articolo: una misura indipendente dal motore.

    uv run python tools/misura_copertura.py <pdf> [pagina_per_il_wizard]

Conta, pagina per pagina, le scritte che hanno la forma di un prezzo («€ 1.234,56») e le confronta con
gli articoli estratti che hanno un prezzo. Un'estrazione che attribuisce piu' prezzi di quanti la pagina
ne contenga ne inventa; una che ne attribuisce meno perde articoli. Il profilo e' la proposta del wizard.
"""
import collections
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from extractors.text_extractor import estrai_span
from processors.analisi_layout import analizza_pdf, profilo_da_analisi
from processors.estrazione import estrai_listino

# il JBL scrive i prezzi senza simbolo; Etabeta a volte senza il punto delle migliaia («€ 5479,00»)
FORMA_PREZZO = re.compile(r"^(€|EUR)?\s?(\d{1,3}(\.\d{3})+|\d+),\d\d$")


def misura(pdf: str, pagina: int) -> dict:
    a = analizza_pdf(pdf, pagina)
    profilo = profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])
    t = time.perf_counter()
    r = estrai_listino(pdf, profilo)
    durata = time.perf_counter() - t
    with pymupdf.open(pdf) as d:
        nel_pdf = {i + 1: sum(1 for s in estrai_span(d[i], i + 1) if FORMA_PREZZO.match(s.testo))
                   for i in range(d.page_count)}
    estratti = collections.Counter(x.pagina for x in r.articoli if x.prezzo is not None)
    totale = sum(nel_pdf.values())
    return {
        "mappatura": [(c.etichetta, c.campo_proposto) for c in a.colonne],
        "ancora": r.ancora,
        "articoli": len(r.articoli),
        "prezzi_nel_pdf": totale,
        "prezzi_attribuiti": sum(estratti.values()),
        "copertura": sum(estratti.values()) / totale if totale else 1.0,
        "pagine_in_eccesso": [p for p in nel_pdf if estratti[p] > nel_pdf[p]],
        "pagine_con_perdite": sorted(((nel_pdf[p] - estratti[p], p) for p in nel_pdf if estratti[p] < nel_pdf[p]),
                                     reverse=True)[:12],
        "secondi": round(durata, 1),
        "anomalie": collections.Counter(y.split(":")[0].split("(")[0].strip()[:40]
                                        for x in r.articoli for y in x.tutte_le_anomalie()).most_common(6),
    }


if __name__ == "__main__":
    for chiave, valore in misura(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1).items():
        print(f"{chiave}: {valore:.1%}" if chiave == "copertura" else f"{chiave}: {valore}")
