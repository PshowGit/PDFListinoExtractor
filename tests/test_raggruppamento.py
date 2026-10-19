from extractors.table_extractor import Riga
from processors.models import Span
from processors.raggruppamento import a_fianco_dei_dati, coda_staccata, corse, estensioni, gruppi, nella_fascia


def _riga(testo, y):
    return Riga([Span(testo, 100, y, 150, y + 8, 7, 1)])


def _ancora(r):
    return r.testo.startswith("(")


def test_corse_si_spezzano_sullo_stacco_e_sui_tagli():
    righe = [_riga("a", 0), _riga("b", 10), _riga("c", 40), _riga("d", 50)]
    assert [[r.testo for r in c] for c in corse(righe, 15)] == [["a", "b"], ["c", "d"]]
    assert [[r.testo for r in c] for c in corse(righe[:2], 15, tagli=[5])] == [["a"], ["b"]]


def test_corsa_con_una_ancora_e_un_articolo_intero():
    # nome su due righe, codice, EAN: tutto un articolo
    righe = [_riga("Nome", 0), _riga("riga 2", 10.5), _riga("(C1)", 21), _riga("123", 31.5)]
    [g] = gruppi(righe, _ancora, 15)
    assert [r.testo for r in g.righe] == ["Nome", "riga 2", "(C1)", "123"]
    assert g.ancora.testo == "(C1)" and g.inizio == 0


def test_piu_ancore_si_tagliano_nel_distacco_piu_ampio():
    # il caso JBL che con uno stacco fisso fondeva 66 articoli: EAN, poi 14,5 pt, poi il nome successivo
    righe = [_riga("A", 0), _riga("(C1)", 10.5), _riga("ean1", 21), _riga("B", 35.5), _riga("(C2)", 46),
             _riga("ean2", 56.5)]
    g1, g2 = gruppi(righe, _ancora, 15.75)
    assert [r.testo for r in g1.righe] == ["A", "(C1)", "ean1"]
    assert [r.testo for r in g2.righe] == ["B", "(C2)", "ean2"]


def test_tabella_a_una_riga_per_articolo():
    righe = [_riga(f"(C{i})", i * 12) for i in range(5)]
    assert [g.ancora.testo for g in gruppi(righe, _ancora, 18)] == [f"(C{i})" for i in range(5)]
    assert all(len(g.righe) == 1 for g in gruppi(righe, _ancora, 18))


def test_corse_senza_ancora_non_creano_articoli():
    righe = [_riga("testo sparso", 0), _riga("(C1)", 100)]
    assert [g.ancora.testo for g in gruppi(righe, _ancora, 15)] == ["(C1)"]


def _span(testo, x, y, corpo=9.0, altezza=10.0):
    return Riga([Span(testo, x, y, x + len(testo) * 0.5 * corpo, y + altezza, corpo, 1)])


# misure vere del catalogo Etabeta: corpo 9, passo 11,6, tolleranza 3,6
CORPO, PASSO, TOL = 9.0, 11.6, 3.6


def _bollino(titolo, dati, ancore, intestazioni=()):
    return a_fianco_dei_dati(titolo, dati, ancore, list(intestazioni), CORPO, PASSO, TOL)


def test_bollino_accanto_alla_descrizione_di_un_articolo():
    # pagina 16: «NEW» a sinistra, fra le righe «Touch» e «Win11»
    new = _span("NEW", 82, 458.5, corpo=12, altezza=13.4)
    dati = [_span("Aggiunta opzionale per versione schermo Touch", 238, 454.7),
            _span("Aggiunta opzionale per mini PC", 238, 469.2)]
    assert _bollino(new, dati, [_span("Touch", 167, 454.7)])


def test_bollino_a_cavallo_di_due_righe():
    # pagina 17: si sovrappone a ciascuna riga meno della tolleranza, a tutte e due insieme di piu'
    new = _span("NEW", 82, 757.4, corpo=12, altezza=13.4)
    dati = [_span("Aggiunta opzionale per versione schermo Touch", 238, 750.9),
            _span("Aggiunta opzionale per mini PC", 238, 768.6)]
    assert _bollino(new, dati, [_span("Touch", 167, 750.9)])


def test_bollino_nella_scheda_sotto_il_codice():
    # il codice in cima alla scheda, piu' di un passo sopra: vale perche' non c'e' un'intestazione in mezzo
    new = _span("NEW", 82, 677, corpo=12, altezza=13.4)
    dati = [_span("HPF/LPF -X-Over universale a 2/3/4 vie", 167, 669.8),
            _span("- Controllo del rumore ambientale", 167, 680.6)]
    codice = _span("AQM-408", 167, 603.8)
    assert _bollino(new, dati, [codice])
    assert not _bollino(new, dati, [codice], intestazioni=[640])


def test_titolo_di_sezione_su_una_fascia_sua_non_e_un_bollino():
    titolo = _span("CAVI", 167, 400, corpo=12, altezza=13.4)
    dati = [_span("Cavo Mogami CAT5E - 2 metri", 238, 418)]
    assert not _bollino(titolo, dati, [_span("M-CAT5E-2", 167, 418)])


def test_non_sono_bollini_titoli_lunghi_grandi_o_accanto_a_testo_di_altro_corpo():
    dati = [_span("La serie HS sono altoparlanti full-range", 167, 249.8),
            _span("Sono accuratamente testati", 167, 260.6)]
    ancore = [_span("ALA6.2W", 167, 200)]
    assert not _bollino(_span("HS", 68, 253.9, corpo=16, altezza=17.8), dati, ancore)  # logo di serie
    assert not _bollino(_span("NEW PRODUCT", 82, 253.9, corpo=12), dati, ancore)  # due parole
    promozionale = [_span("il controllo flessibile da remoto", 272, 213.7, corpo=11)]
    assert not _bollino(_span("Vari", 81, 205.3, corpo=12, altezza=20.1), promozionale, ancore)  # testo in corpo 11


def test_bollino_senza_articolo_accanto_non_e_un_bollino():
    # «ALA» sopra il testo introduttivo, prima della prima tabella della pagina: nessuna ancora sopra
    titolo = _span("ALA", 63, 35.6, corpo=12, altezza=13.4)
    dati = [_span("La serie ALA sono altoparlanti passivi", 167, 36.9)]
    assert not _bollino(titolo, dati, [_span("NSP-8", 167, 95)], intestazioni=[77.5])


# --- coda in fondo alla pagina (misure vere del catalogo Etabeta: interlinea 11,6, corpo 9) ---------------

INTERLINEA = 11.6


def _coda(testo, altre):
    return coda_staccata(testo, altre, INTERLINEA, CORPO)


def test_nota_centrata_dopo_uno_stacco_si_stacca():
    # pagina 44: «Sul sito www.cloud.co.uk potete scaricare...», centrata in un riquadro suo
    testo = [_span("Scheda modulo RS232 opzionale", 238, 521.9), _span("Modulo opzionale che si inserisce", 167, 533.1),
             _span("e silenziamento del microfono", 167, 554.7), _span("Sul sito www.cloud.co.uk", 200, 581.5),
             _span("i Datasheet, i Manuali d’uso", 153, 592.3)]
    altre = [_span("CDIS100", 167, 521.2), _span("€ 128,00", 532, 521.2)]
    assert _coda(testo, altre) == 3


def test_nota_in_un_altro_corpo_si_stacca():
    # pagina 73: «VEDI vari SUB...» in corpo 10, allineata al codice
    testo = [_span("Fligth case per 2 diffusori", 238, 693), _span("VEDI vari SUB abbinabili", 168, 732.6, corpo=10)]
    assert _coda(testo, [_span("K-LA12A/FC", 167, 693.2)]) == 1


def test_blocco_lontano_si_stacca():
    # pagina 166: una riga sola sette interlinee sotto l'articolo
    testo = [_span("Microfono a condensatore", 238, 603.6), _span("Accessori compresi: Cavo 5 metri", 238, 649),
             _span("tutti i vari sistemi di montaggio", 238, 730.2)]
    assert _coda(testo, [_span("PL-1601", 167, 603.6)]) == 2


def test_caratteristiche_dopo_uno_stacco_restano():
    codice = _span("SP12.1PB", 167, 704)
    # pagina 42: allineate alla descrizione
    testo = [_span("Subwoofer Passivo 12”", 238, 704), _span("Potenza Continua: 350W", 238, 732.1),
             _span("Risposta in frequenza: 39-180Hz", 238, 742.9)]
    assert _coda(testo, [codice]) is None
    # pagina 25: a tutta larghezza, dall'inizio della colonna del codice
    testo = [_span("Bluetooth Wireless Headset", 241, 579.2), _span("- Microfono ECM Array", 167, 603.5),
             _span("- Echo Cancellation", 167, 614.3)]
    assert _coda(testo, [_span("HP30", 167, 579.5)]) is None


def test_dopo_uno_stacco_con_un_codice_il_testo_e_di_un_articolo():
    # pagina 155: un kit con due codici, il secondo nello stacco
    testo = [_span("POPS System kit composto da:", 167, 589.3), _span("Cavi da 30 m su ruzzole", 167, 645.1),
             _span("Mobile in compensato marino", 300, 739.4)]
    altre = [_span("1x POPS-15", 167, 601.9), _span("1x POPS-SUB", 167, 728.6)]
    assert _coda(testo, altre) is None


def test_estensioni_e_tagli():
    assert estensioni([0, 50], []) == [(0, 50), (50, float("inf"))]
    assert estensioni([0, 50], [30]) == [(0, 30), (50, float("inf"))]
    assert nella_fascia(_riga("x", 49), (0, 50), 2) is False
    assert nella_fascia(_riga("x", 47), (0, 50), 2) is True
