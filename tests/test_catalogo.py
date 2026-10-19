"""Il catalogo Etabeta (Larentis): codici centrati nelle celle, piu' tabelle per pagina, griglia, legature.

Il PDF vero non e' nel repository (materiale commerciale): i casi sono riprodotti in
tests/sintetico_catalogo.py, e i test sul PDF vero si saltano se samples/Etabeta_Larentis.pdf manca.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from extractors.table_extractor import Riga
from extractors.text_extractor import _unisci_contigui, normalizza_glifi
from processors.analisi_layout import analizza_pdf, profilo_da_analisi
from processors.article_parser import aspetto_codice
from processors.estrazione import estrai_listino
from processors.models import Span
from processors.raggruppamento import celle, e_centrata, fasce_centrate
from tests.sintetico_catalogo import attesi, crea_catalogo

ETABETA = Path(__file__).resolve().parent.parent / "samples" / "Etabeta_Larentis.pdf"


# --- testo ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "grezzo, atteso",
    [
        ("ProgeƩato", "Progettato"), ("Il Ɵpo", "Il tipo"), ("l’aƫvazione", "l’attivazione"),
        ("Ampliﬁ catore", "Amplificatore"), ("Diﬀ usore", "Diffusore"), ("di ﬁ ssaggio", "di fissaggio"),
        ("On/Oﬀ ", "On/Off "), ("Staﬀ a", "Staffa"), ("eﬃ ciente", "efficiente"),
    ],
)
def test_glifi_e_legature(grezzo, atteso):
    assert normalizza_glifi(grezzo) == atteso


def test_span_attaccati_sono_una_parola_sola():
    # "Proge" + "Ʃ" + "ato": tre span a distacco zero, come li scrive Acrobat Distiller con Calibri
    spans = [{"text": "Proge", "bbox": (10, 0, 30, 9), "size": 9}, {"text": "Ʃ", "bbox": (30, 0, 33, 9), "size": 9},
             {"text": "ato per", "bbox": (33, 0, 60, 9), "size": 9}, {"text": "durare", "bbox": (64, 0, 90, 9), "size": 9}]
    assert [s["text"] for s in _unisci_contigui(spans)] == ["ProgeƩato per", "durare"]


@pytest.mark.parametrize("testo, atteso", [
    ("DCP-1000", True), ("TU-NE1", True), ("Decoair-350L", True), ("TRIPOD-GA", True), ("M-CAT5E-2", True),
    ("esaurimento", False), ("6 ingressi di linea stereo con", False), ("Il ti", False), ("Zoccoli portalampada", False),
])
def test_aspetto_da_codice(testo, atteso):
    assert aspetto_codice(testo) is atteso


# --- raggruppamento ------------------------------------------------------------------------------

def _r(y):
    return Riga([Span("x", 238, y, 300, y + 9, 9, 1)])


def test_celle_centrate_simmetriche_attorno_al_codice():
    # misure vere di pagina 22: VMHM4I a 48,7 (1 riga), VMHM2I-4K a 65,2 (righe 59,5 e 70,3), VMHM2I a 85,9
    ys = [48.4, 59.5, 70.3, 80.3, 91.1]
    ancore = [48.7, 65.2, 85.9]
    fasce = fasce_centrate(ys, ancore, [], 3.6, 14.6)
    per_articolo = [[y for y in ys if lo <= y < hi] for lo, hi in fasce]
    assert per_articolo == [[48.4], [59.5, 70.3], [80.3, 91.1]]
    assert e_centrata(ys, ancore, [], 3.6, 14.6)


def test_righe_equidistanti_di_una_tabella_normale_non_sono_centrate():
    # una riga per articolo a passo 12: la riga sopra ogni codice e' quella dell'articolo prima
    ys = [100 + 12 * i for i in range(8)]
    assert not e_centrata(ys, ys, [], 3.6, 14.6)


def test_celle_della_griglia():
    righe = [_r(50), _r(62), _r(74), _r(86)]  # "Super Splitter" a 62 e "Duo" a 74 nella stessa cella
    gruppi = celle(righe, [45, 57, 82, 95], [])
    assert [[r.y0 for r in g.righe] for g in gruppi] == [[50], [62, 74], [86]]
    assert celle(righe, [45], []) is None  # poche linee: non e' una griglia


# --- catalogo sintetico --------------------------------------------------------------------------

@pytest.fixture(params=[True, False], ids=["con_griglia", "senza_griglia"])
def catalogo(request, tmp_path):
    return crea_catalogo(tmp_path / "catalogo.pdf", linee=request.param), request.param


def test_proposta_del_wizard_sul_catalogo(catalogo):
    pdf, linee = catalogo
    a = analizza_pdf(str(pdf), 1)
    # la colonna della marca: il testo promozionale sotto si ignora, la marca e' la sua etichetta, che cambia
    # da una tabella all'altra; il titolo centrato della tabella e' la descrizione
    assert [c.campo_proposto for c in a.colonne] == ["marca", "modello", "descrizione", "prezzo"]
    assert (a.ancora_proposta, a.formato_prezzo_proposto, a.linee_divisorie_proposte) == ("modello", "it", linee)
    assert a.colonne[2].x0 == pytest.approx(238, abs=1)  # dove comincia il testo, non il titolo centrato


def test_estrazione_del_catalogo(catalogo):
    pdf, linee = catalogo
    a = analizza_pdf(str(pdf), 1)
    ris = estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne]))
    articoli = ris.articoli
    # la nota in fondo alla pagina 2 non e' nella descrizione dell'ultimo articolo. Con la griglia sembra il seguito
    # dell'articolo e va staccata, e finisce negli avvisi; senza, la cella centrata sul codice finisce prima
    if linee:
        assert any("Pagina 2: testo in fondo alla pagina" in x and "Per specifiche complete" in x for x in ris.avvisi)
    attesi_ = attesi(linee)
    assert len(articoli) == len(attesi_)
    for x, t in zip(articoli, attesi_, strict=True):
        assert (x.modello, x.descrizione, x.prezzo, x.pagina, x.categoria) == (
            t.modello, t.descrizione, t.prezzo, t.pagina, t.categoria), t.modello
        # la marca dell'intestazione della tabella, anche dove la tabella prosegue senza (Iso Switcher)
        assert x.valore("marca") == (t.categoria.split(" · ")[0] if t.marca is None else t.marca), t.modello
        for attesa in t.anomalie:
            assert any(attesa in y for y in x.tutte_le_anomalie()), (t.modello, x.tutte_le_anomalie())


# --- catalogo vero -------------------------------------------------------------------------------

reale = pytest.mark.skipif(not ETABETA.is_file(), reason="catalogo Etabeta non presente in samples/")


@pytest.fixture(scope="module")
def etabeta():
    a = analizza_pdf(str(ETABETA), 22)
    return a, estrai_listino(ETABETA, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne]))


@reale
def test_etabeta_copertura_dei_prezzi(etabeta):
    import pymupdf

    from extractors.text_extractor import estrai_span
    from tools.misura_copertura import FORMA_PREZZO

    _, ris = etabeta
    with pymupdf.open(ETABETA) as d:
        nel_pdf = {i + 1: sum(1 for s in estrai_span(d[i], i + 1) if FORMA_PREZZO.match(s.testo))
                   for i in range(d.page_count)}
    estratti: dict[int, int] = {}
    for x in ris.articoli:
        if x.prezzo is not None:
            estratti[x.pagina] = estratti.get(x.pagina, 0) + 1
    assert not [p for p, n in estratti.items() if n > nel_pdf[p]]  # nessun prezzo inventato
    assert sum(estratti.values()) >= 0.97 * sum(nel_pdf.values())  # misurato: 97,4%


@reale
def test_etabeta_casi_misurati(etabeta):
    a, ris = etabeta
    assert [c.campo_proposto for c in a.colonne] == ["marca", "modello", "descrizione", "prezzo"]
    assert [c.etichetta for c in ris.colonne] == ["Marca", "Modello", "Descrizione", "Prezzo"]
    per = {(x.pagina, x.modello): x for x in ris.articoli}
    # codice centrato in una cella di due righe (pagina 22)
    x = per[(22, "VMHM2I-4K")]
    assert x.descrizione == "Scheda input 2 canali HDMI risoluzione 4k@60Hz con embedder e de-embedder audio analogico"
    assert x.prezzo == Decimal("1400.00") and x.categoria == "VISSONIC · MODULI INPUT PER MATRICI VIDEO X9"
    # modelli scritti come nomi, in una griglia (pagina 80)
    assert per[(80, "Q Switch")].descrizione.startswith("Commutatore 4 canali stereo")
    assert per[(80, "Super Splitter Duo")].prezzo == Decimal("340.00")
    # tabella che prosegue in cima alla pagina senza intestazione (pagina 236)
    assert per[(236, "BE-AD/W")].prezzo == Decimal("14.00")
    # marca e titolo della tabella come categoria (pagina 4)
    assert per[(4, "M-CAT5E-2")].categoria == "MOGAMI · CAVI MOGAMI CAT-5ProB-3381/RJ45"
    # la marca come colonna (pagine 22, 270, e 13 dove un bollino «NEW» la cambiava)
    assert per[(22, "VMHM2I-4K")].valore("marca") == "VISSONIC"
    assert per[(270, "CC-960")].valore("marca") == "Konig & Meyer"
    assert per[(13, "HBTY")].valore("marca") == "VISSONIC"
    # legature ricomposte nei dati
    assert not any(c in x.descrizione for x in ris.articoli for c in "ﬀﬁﬂﬃƟƩƫ")
