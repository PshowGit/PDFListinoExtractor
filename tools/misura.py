"""Tempo e profilo dell'estrazione senza interfaccia: uv run python tools/misura.py <pdf>"""
import cProfile
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import regole_fornitore
from processors.estrazione import estrai_listino

pdf = sys.argv[1]
t = time.perf_counter()
r = estrai_listino(pdf, regole_fornitore())
print("senza GUI:", round(time.perf_counter() - t, 2), "s,", len(r.articoli), "articoli")
if "--profilo" in sys.argv:
    prof = cProfile.Profile()
    prof.runcall(estrai_listino, pdf, regole_fornitore())
    pstats.Stats(prof).sort_stats("cumulative").print_stats(14)
