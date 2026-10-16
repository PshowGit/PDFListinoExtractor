"""Il motore su layout diversi da quello JBL, e il percorso del wizard (analisi -> profilo -> estrazione)."""
import pytest

from processors.analisi_layout import analizza_pdf, profilo_da_analisi, proponi_campo
from processors.estrazione import estrai_listino
from tests.conftest import CAMPIONE_REALE
from tests.sintetico import ATTESI as ATTESI_JBL
from tests.sintetico_generico import ATTESI, crea_listino_generico


def _confronta(articoli, attesi):
    assert len(articoli) == len(attesi)
    for a, t in zip(articoli, attesi, strict=True):
        assert (a.codice, a.descrizione, a.ean, a.prezzo, a.pagina, a.categoria) == (
            t.codice, t.descrizione, t.ean, t.prezzo, t.pagina, t.categoria), t.codice
        tutte = " ".join(a.tutte_le_anomalie())
        for attesa in t.anomalie:
            assert attesa in tutte, f"{t.codice}: manca «{attesa}» in «{tutte}»"


@pytest.fixture(params=[True, False], ids=["con_intestazione", "senza_intestazione"])
def generico(request, tmp_path):
    return crea_listino_generico(tmp_path / "generico.pdf", con_intestazione=request.param), request.param


def test_analisi_propone_la_mappatura_giusta(generico):
    pdf, con_intestazione = generico
    a = analizza_pdf(str(pdf), 1)
    assert [c.campo_proposto for c in a.colonne] == ["codice", "descrizione", "ean", "prezzo"]
    assert a.ancora_proposta == "codice"
    assert a.formato_prezzo_proposto == "en"
    assert (a.intestazione is not None) is con_intestazione
    if con_intestazione:
        assert [c.etichetta for c in a.colonne] == ["SKU", "Description", "EAN", "Price EUR"]


def test_estrazione_universale_con_la_mappatura_proposta(generico):
    pdf, _ = generico
    a = analizza_pdf(str(pdf), 1)
    ris = estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne]))
    _confronta(ris.articoli, ATTESI)
    assert ris.ancora == "codice"


def test_testata_e_piede_ripetuti_spariscono_senza_regole(generico):
    pdf, _ = generico
    a = analizza_pdf(str(pdf), 1)
    for art in estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])).articoli:
        testo = f"{art.modello} {art.codice} {art.descrizione}"
        assert "ACME" not in testo and "Page " not in testo


def test_anteprima_su_una_pagina_sola(generico):
    pdf, _ = generico
    a = analizza_pdf(str(pdf), 2)
    ris = estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne]), solo_pagine=[2])
    assert [x.codice for x in ris.articoli] == ["AMP-2", "AMP-3"]


def test_ancora_sul_prezzo_fonde_gli_articoli_senza_prezzo(tmp_path):
    # il motivo per cui il prezzo e' l'ultima scelta: SP-300 non ha prezzo e si attacca a SP-200
    pdf = crea_listino_generico(tmp_path / "g.pdf")
    a = analizza_pdf(str(pdf), 1)
    ris = estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne], ancora="prezzo"))
    assert "SP-300" not in [x.codice for x in ris.articoli]


def test_non_si_segnalano_campi_che_il_profilo_non_prevede(tmp_path):
    # il listino generico non ha colonna Modello: "Modello mancante" su ogni riga era solo rumore
    pdf = crea_listino_generico(tmp_path / "g.pdf")
    a = analizza_pdf(str(pdf), 1)
    articoli = estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])).articoli
    assert not any("Modello" in x for art in articoli for x in art.tutte_le_anomalie())
    assert sum(1 for art in articoli if art.tutte_le_anomalie()) == 2  # SP-300 senza prezzo, AMP-1 "on request"


def test_colonna_prezzo_che_fallisce_dice_quale_colonna(tmp_path):
    pdf = crea_listino_generico(tmp_path / "g.pdf")
    a = analizza_pdf(str(pdf), 1)
    amp1 = next(x for x in estrai_listino(pdf, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])).articoli
                if x.codice == "AMP-1")
    assert "Price EUR" in amp1.note_estrazione["prezzo"] and "on request" in amp1.note_estrazione["prezzo"]


@pytest.mark.parametrize(
    "testi, campo",
    [
        (["1.234,56", "99,00", "12,50"], "prezzo"),
        (["8710150083632", "691991014208", "8712345678906"], "ean"),
        (["CSA1120Z", "(JBNCSA1120Z-U-EU)", "8710150083632", "AC16", "(JBAC16)"], "identificativo"),
        (["Amplificatore stereo da 100 W", "Diffusore a due vie per esterni"], "descrizione"),
        (["AB-123", "XY-77/2", "Q-9001"], "codice"),
        (["Rosso", "Blu"], "modello"),
        ([], "ignora"),
    ],
)
def test_proposta_del_campo_dal_contenuto(testi, campo):
    assert proponi_campo(testi) == campo


def test_wizard_sul_pdf_jbl_sintetico_riproduce_il_profilo_scritto_a_mano(pdf_sintetico, regole):
    a = analizza_pdf(str(pdf_sintetico), 1)
    assert [c.campo_proposto for c in a.colonne] == ["identificativo", "descrizione", "prezzo"]
    dal_wizard = estrai_listino(pdf_sintetico, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne])).articoli
    assert [(x.modello, x.codice, x.ean, x.descrizione, x.prezzo) for x in dal_wizard] == [
        (t.modello, t.codice, t.ean, t.descrizione, t.prezzo) for t in ATTESI_JBL]


@pytest.mark.skipif(not CAMPIONE_REALE.is_file(), reason="listino campione non presente in samples/")
def test_wizard_sul_listino_reale_coincide_col_profilo_distribuito(regole):
    a = analizza_pdf(str(CAMPIONE_REALE), 1)
    dal_wizard = estrai_listino(CAMPIONE_REALE, profilo_da_analisi(a, [c.campo_proposto for c in a.colonne]))
    distribuito = estrai_listino(CAMPIONE_REALE, regole)
    chiave = [(x.modello, x.codice, x.ean, x.descrizione, x.prezzo, x.categoria) for x in distribuito.articoli]
    assert len(chiave) == 673
    assert [(x.modello, x.codice, x.ean, x.descrizione, x.prezzo, x.categoria) for x in dal_wizard.articoli] == chiave
