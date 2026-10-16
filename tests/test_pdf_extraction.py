import threading
from decimal import Decimal

import pymupdf
import pytest

from extractors.ocr_extractor import ocr_disponibile
from extractors.pdf_reader import PdfNonValido, verifica_pdf
from processors.estrazione import EstrazioneAnnullata, estrai_listino
from tests.conftest import CAMPIONE_REALE
from tests.sintetico import ATTESI, crea_scansione

TESTI_ESTRANEI = ("Prezzo al", "Pubblico", "Pagina ", "Exhibo", "Listino", "Gennaio 2026", "Tel. 039")


def test_pdf_sintetico_risultati_attesi(pdf_sintetico, regole):
    ris = estrai_listino(pdf_sintetico, regole)
    assert ris.pagine_totali == 4
    assert ris.avvisi == []
    assert len(ris.articoli) == len(ATTESI)
    for art, att in zip(ris.articoli, ATTESI):
        assert (art.modello, art.codice, art.ean, art.descrizione, art.prezzo, art.pagina) == (
            att.modello, att.codice, att.ean, att.descrizione, att.prezzo, att.pagina,
        ), att.codice
        anomalie = " ".join(art.tutte_le_anomalie())
        for attesa in att.anomalie:
            assert attesa in anomalie, f"{att.codice}: manca «{attesa}» in «{anomalie}»"
        if not att.anomalie:
            assert not art.tutte_le_anomalie(), f"{att.codice}: anomalie inattese {art.tutte_le_anomalie()}"


def test_intestazioni_e_pie_di_pagina_ripetuti_non_entrano_nei_dati(pdf_sintetico, regole):
    for a in estrai_listino(pdf_sintetico, regole).articoli:
        for campo in (a.modello, a.codice, a.ean, a.descrizione):
            assert not any(t in campo for t in TESTI_ESTRANEI), campo


def test_le_categorie_sono_assegnate(pdf_sintetico, regole):
    arts = estrai_listino(pdf_sintetico, regole).articoli
    assert arts[0].categoria == "Amplificatori"
    assert arts[3].categoria == "Diffusori"
    assert arts[-1].categoria == "Diffusori"  # pagina 3 senza titolo: la categoria prosegue


def test_progresso_per_ogni_pagina(pdf_sintetico, regole):
    chiamate = []
    estrai_listino(pdf_sintetico, regole, progresso=lambda n, tot, art: chiamate.append((n, tot)))
    assert chiamate == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_annullamento(pdf_sintetico, regole):
    stop = threading.Event()
    with pytest.raises(EstrazioneAnnullata):
        estrai_listino(pdf_sintetico, regole, progresso=lambda *a: stop.set(), annulla=stop)


def _messaggi_dal_processo(pdf, regole, annulla_subito=False):
    import multiprocessing

    from processors.lavori import ESTRAZIONE, esegui

    ctx = multiprocessing.get_context("spawn")
    coda, annulla = ctx.Queue(), ctx.Event()
    if annulla_subito:
        annulla.set()
    p = ctx.Process(target=esegui, args=(ESTRAZIONE, {"percorso": str(pdf), "regole": regole}, coda, annulla))
    p.start()
    messaggi = []
    while not messaggi or messaggi[-1][0] == "progresso":
        messaggi.append(coda.get(timeout=60))
    p.join(timeout=10)
    return messaggi, p.exitcode


def test_estrazione_nel_processo_separato(pdf_sintetico, regole):
    messaggi, uscita = _messaggi_dal_processo(pdf_sintetico, regole)
    assert uscita == 0
    assert [m[1] for m in messaggi if m[0] == "progresso"] == [1, 2, 3, 4]
    tipo, ris = messaggi[-1]
    assert tipo == "fine" and [a.codice for a in ris.articoli] == [a.codice for a in ATTESI]


def test_annullamento_nel_processo_separato(pdf_sintetico, regole):
    messaggi, _ = _messaggi_dal_processo(pdf_sintetico, regole, annulla_subito=True)
    assert messaggi[-1] == ("annullata",)


def test_errore_nel_processo_separato_arriva_leggibile(tmp_path, regole):
    rotto = tmp_path / "rotto.pdf"
    rotto.write_bytes(b"x" * 100)
    messaggi, _ = _messaggi_dal_processo(rotto, regole)
    assert messaggi[-1][0] == "errore" and "PDF" in messaggi[-1][1]


def test_file_mancante(tmp_path):
    with pytest.raises(PdfNonValido, match="non trovato"):
        verifica_pdf(tmp_path / "inesistente.pdf")


def test_file_vuoto(tmp_path):
    p = tmp_path / "vuoto.pdf"
    p.write_bytes(b"")
    with pytest.raises(PdfNonValido, match="vuoto"):
        verifica_pdf(p)


def test_file_danneggiato(tmp_path):
    p = tmp_path / "rotto.pdf"
    p.write_bytes(b"questo non e' un pdf, solo testo qualsiasi " * 20)
    with pytest.raises(PdfNonValido):
        verifica_pdf(p)


def test_pdf_protetto(tmp_path, pdf_sintetico):
    p = tmp_path / "protetto.pdf"
    with pymupdf.open(pdf_sintetico) as d:
        d.save(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    with pytest.raises(PdfNonValido, match="password"):
        verifica_pdf(p)


def test_il_pdf_originale_non_viene_modificato(pdf_sintetico, regole):
    prima = pdf_sintetico.read_bytes()
    estrai_listino(pdf_sintetico, regole)
    assert pdf_sintetico.read_bytes() == prima


def test_scansione_senza_ocr_e_segnalata(tmp_path, pdf_sintetico, regole, monkeypatch):
    scan = crea_scansione(pdf_sintetico, tmp_path / "scan.pdf")
    assert verifica_pdf(scan).scansionato
    monkeypatch.setattr("extractors.ocr_extractor.ocr_disponibile", lambda: False)
    ris = estrai_listino(scan, regole)
    assert ris.articoli == []
    assert ris.pagine_saltate == [1, 2, 3, 4]
    assert any("OCR" in a for a in ris.avvisi)


@pytest.mark.skipif(not ocr_disponibile(), reason="Tesseract non installato")
def test_scansione_con_ocr(tmp_path, pdf_sintetico, regole):
    scan = crea_scansione(pdf_sintetico, tmp_path / "scan.pdf", dpi=300)
    ris = estrai_listino(scan, regole)
    assert ris.pagine_ocr == [1, 2, 3, 4]
    codici = [a.codice for a in ris.articoli]
    assert "(SPK-001)" in codici
    assert all(a.da_ocr for a in ris.articoli)


# --- listino reale ---------------------------------------------------------------------------

reale = pytest.mark.skipif(not CAMPIONE_REALE.is_file(), reason="listino campione non presente in samples/")


@pytest.fixture(scope="module")
def estratto_reale():
    from config import regole_fornitore

    return estrai_listino(CAMPIONE_REALE, regole_fornitore("jbl_exhibo"))


@reale
def test_reale_numero_articoli(estratto_reale):
    assert estratto_reale.pagine_totali == 121
    assert len(estratto_reale.articoli) == 673
    assert estratto_reale.avvisi == []


@reale
def test_reale_primo_articolo(estratto_reale):
    a = estratto_reale.articoli[0]
    assert (a.modello, a.codice, a.ean, a.prezzo) == ("CSA1120Z", "(JBNCSA1120Z-U-EU)", "8710150083632", Decimal("735.00"))
    assert a.descrizione.startswith("Amplificatore JBL CSA1120Z 1 x 120W DriveCore, Fanless, 4ohm/8ohm/70V/100V")
    assert a.descrizione.endswith("in termini di risparmio energetico.")
    assert a.categoria == "Amplificatori"


@reale
def test_reale_codici_univoci_e_tutti_presenti(estratto_reale):
    codici = [a.codice for a in estratto_reale.articoli]
    assert all(c.startswith("(") and c.endswith(")") for c in codici)
    assert len(set(codici)) == len(codici)


@reale
def test_reale_casi_particolari(estratto_reale):
    per_codice = {a.codice: a for a in estratto_reale.articoli}
    # nome su due righe e colonna descrizione vuota
    a = per_codice["(JBPRX825W-230D)"]
    assert a.modello == "JBL PRX825W/230 DIFFUSORE ATTIVO 2 VIE,"
    assert a.descrizione == a.modello
    assert a.prezzo == Decimal("1920.00")
    # terza riga che non e' un EAN: tenuta e segnalata
    a = per_codice["(JBPRX412MD)"]
    assert a.ean == "PRX412M" and any("EAN non valido" in x for x in a.tutte_le_anomalie())
    # trattino a fine riga ricomposto
    assert "water-resistant" in per_codice["(JBEON715-CVR-WX)"].modello


@reale
def test_reale_anomalie_note(estratto_reale):
    zero = [a.codice for a in estratto_reale.articoli if a.prezzo == 0]
    assert len(zero) == 6
    assert all(any("zero" in x for x in a.tutte_le_anomalie()) for a in estratto_reale.articoli if a.prezzo == 0)
    assert all(a.prezzo is not None for a in estratto_reale.articoli)


@reale
def test_reale_niente_testata_nei_dati(estratto_reale):
    for a in estratto_reale.articoli:
        for campo in (a.modello, a.codice, a.ean, a.descrizione):
            assert not any(t in campo for t in ("Prezzo al", "Pagina ", "Exhibo S.p.A", "Tel. 039")), campo
