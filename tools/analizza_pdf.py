"""Analisi di un listino nuovo, prima di scriverne le regole.

    uv run python tools/analizza_pdf.py <pdf>            # riepilogo pagina per pagina
    uv run python tools/analizza_pdf.py <pdf> 1,27       # testo con coordinate delle pagine 1 e 27

Le coordinate stampate (x, y, corpo) sono quelle che vanno in config/supplier_rules.json.
"""
import sys

import pymupdf

path = sys.argv[1]
pagine = [int(p) for p in sys.argv[2].split(",")] if len(sys.argv) > 2 else None

doc = pymupdf.open(path)
print(f"pagine: {doc.page_count}")
if pagine is None:
    for i, page in enumerate(doc):
        txt = page.get_text()
        print(f"--- p{i + 1} caratteri={len(txt)} immagini={len(page.get_images())}")
        print("   ", txt[:160].replace("\n", " | "))
    sys.exit()

for n in pagine:
    page = doc[n - 1]
    print(f"===== PAGINA {n} {page.rect}")
    righe = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    x0, y0, x1, _ = s["bbox"]
                    righe.append((round(y0, 1), round(x0, 1), round(x1, 1), s["size"], s["text"]))
    for y, x0, x1, size, testo in sorted(righe):
        print(f"y={y:6} x={x0:6}-{x1:6} corpo={size:4.1f} | {testo}")
