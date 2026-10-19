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


def _grezzi(*parti):
    """Span grezzi attaccati uno all'altro: (testo, corpo, larghezza)."""
    spans, x = [], 100.0
    for testo, corpo, larghezza in parti:
        spans.append({"text": testo, "bbox": (x, 0, x + larghezza, corpo), "size": corpo})
        x += larghezza
    return [s["text"] for s in _unisci_contigui(spans)]


def test_il_bollino_attaccato_al_codice_resta_a_parte():
    # pagina 269: «23550  » in corpo 9 e «NEW» in corpo 12 si toccano; uniti erano un titolo e l'articolo spariva
    assert _grezzi(("23550  ", 9, 30), ("NEW", 12, 28)) == ["23550  ", "NEW"]
    # pagina 378: anche la descrizione dopo il bollino resta a parte
    assert _grezzi(("SK213-T3 ", 9, 43), ("NEW", 12, 28), (" ", 9, 5), ("Cavo High End", 9, 60)) == [
        "SK213-T3 ", "NEW", " Cavo High End"]


def test_una_scritta_grande_seguita_da_una_piccola_resta_unita():
    # pagine 112 e 142: divise, «SERIE» e «Turbo Speaker Horn» cadevano fra i dati
    assert _grezzi(("NEW MI", 18, 67), (" ", 10, 5), ("SERIE", 10, 30)) == ["NEW MI SERIE"]
    assert _grezzi(("SW", 16, 26), (" ", 11, 5), ("Turbo Speaker Horn", 11, 105)) == ["SW Turbo Speaker Horn"]


def _griglia_con_piu_prezzi(percorso: Path) -> Path:
    """Una tabella a griglia: una cella con due voci (codice e prezzo ciascuna, come RSL-8/RSL-16 dell'Etabeta), una
    con un codice e due varianti (come ACT-6Dante), una con due prezzi sulla stessa riga."""
    import pymupdf

    righe = [  # (y, codice, descrizione, prezzo)
        (125, "AB-100", "Primo articolo", "EUR 10,00"),
        (150, "AB-200", "Secondo articolo", "EUR 20,00"), (163, "AB-300", "Terzo articolo", "EUR 30,00"),
        (185, "AB-400", "Versione nera", "EUR 40,00"), (198, None, "Versione bianca", "EUR 45,00"),
        (225, "AB-500", "Quinto articolo", "EUR 50,00"),
        (250, "AB-600", "Due prezzi in fila", "EUR 60,00 EUR 66,00"),
    ]
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for x, testo in ((60, "Articolo"), (160, "Descrizione"), (480, "Listino")):
        page.insert_text((x, 100), testo, fontsize=9)
    for y in (112, 140, 175, 212, 238, 262):
        page.draw_line((40, y), (560, y), width=0.5)
    for y, codice, descrizione, prezzo in righe:
        if codice:
            page.insert_text((60, y), codice, fontsize=9)
        page.insert_text((160, y), descrizione, fontsize=9)
        page.insert_text((540 - pymupdf.get_text_length(prezzo, fontsize=9), y), prezzo, fontsize=9)
    doc.save(percorso)
    doc.close()
    return percorso


def test_piu_prezzi_nella_stessa_cella_una_riga_per_prezzo(tmp_path):
    pdf = _griglia_con_piu_prezzi(tmp_path / "griglia.pdf")
    a = analizza_pdf(str(pdf), 1)
    profilo = profilo_da_analisi(a, [c.campo_proposto for c in a.colonne], linee=True)
    r = estrai_listino(pdf, profilo)
    righe = [(x.modello, x.descrizione, x.prezzo) for x in r.articoli]
    assert righe[:6] == [
        ("AB-100", "Primo articolo", Decimal("10.00")),
        ("AB-200", "Secondo articolo", Decimal("20.00")), ("AB-300", "Terzo articolo", Decimal("30.00")),
        ("AB-400", "Versione nera", Decimal("40.00")), ("AB-400", "Versione bianca", Decimal("45.00")),
        ("AB-500", "Quinto articolo", Decimal("50.00")),
    ]
    # le due voci di una cella sono articoli puliti; le varianti dello stesso codice si segnalano
    assert not r.articoli[1].note_estrazione and not r.articoli[2].note_estrazione
    assert all(x.note_estrazione["modello"].startswith("Variante") for x in r.articoli[3:5])
    # due prezzi sulla stessa riga: non si sceglie, ma si possono scegliere dall'anteprima
    sesto = r.articoli[6]
    assert sesto.prezzo is None and sesto.prezzo_testo == "EUR 60,00 | EUR 66,00"
    assert sesto.note_estrazione["prezzo"].startswith("Piu' prezzi")


def test_due_prezzi_separati_da_uno_spazio_sono_due_celle():
    # listino Midiware di giugno 2017: uniti, sconfinavano nella colonna dopo
    assert _grezzi(("15.750,00", 8, 29), (" ", 8, 5), ("13.853,00", 8, 29)) == ["15.750,00 ", "13.853,00"]


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


@reale
def test_etabeta_dall_indice_il_wizard_consiglia_una_tabella():
    # pagina 1 e' l'indice, senza prezzi: la proposta li' e' sbagliata
    assert analizza_pdf(str(ETABETA), 1).pagina_consigliata == 13
    a = analizza_pdf(str(ETABETA), 13)
    assert [c.campo_proposto for c in a.colonne] == ["marca", "modello", "descrizione", "prezzo"]
    # la fine della descrizione non scavalca i prezzi (un testo a tutta larghezza la portava a 0,95)
    p = profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])
    assert p["colonne"][2]["x_fine_relativo"] < p["colonne"][3]["x_relativo"]
