import json

import pytest

import config
from config import RegoleNonValide, _leggi, salva_fornitore_personale, valida_schema
from processors.analisi_layout import analizza_pdf
from processors.estrazione import estrai_listino
from processors.wizard import ModelloWizard
from tests.sintetico_generico import crea_listino_generico


@pytest.fixture
def modello(tmp_path):
    pdf = crea_listino_generico(tmp_path / "g.pdf")
    return ModelloWizard(analizza_pdf(str(pdf), 1), {"jbl_exhibo": "JBL (Exhibo) - Listino al pubblico"}), pdf


def test_proposte_iniziali(modello):
    m, _ = modello
    assert m.campi == ["codice", "descrizione", "ean", "prezzo"]
    assert (m.ancora, m.formato_prezzo, m.codici_tra_parentesi) == ("codice", "en", False)


def test_errori_di_mappatura(modello):
    m, _ = modello
    assert any("nome" in e for e in m.errori())
    m.nome = "ACME"
    assert m.errori() == []
    m.imposta_campo(3, "descrizione")
    assert any("Descrizione" in e and "piu' colonne" in e for e in m.errori())
    m.imposta_campo(3, "prezzo")
    m.imposta_campo(0, "ignora")
    m.imposta_campo(2, "ignora")
    assert any("identifichi" in e for e in m.errori())
    assert any("ancora" in e.lower() for e in m.errori())  # ancora sul codice, colonna codice ignorata
    with pytest.raises(ValueError):
        m.imposta_campo(0, "inesistente")


def test_colonna_composita_richiede_le_parentesi(modello):
    m, _ = modello
    m.nome = "X"
    m.imposta_campo(0, "identificativo")
    assert any("parentesi" in e for e in m.errori())
    m.codici_tra_parentesi = True
    assert not any("parentesi" in e for e in m.errori())


def test_chiave_nuova_o_riusata(modello):
    m, _ = modello
    m.nome = "ACME Audio"
    assert m.chiave() == "acme_audio" and not m.sostituisce_esistente()
    m.nome = "jbl (exhibo) - listino al PUBBLICO"
    assert m.chiave() == "jbl_exhibo" and m.sostituisce_esistente()


def test_il_profilo_del_wizard_rispetta_lo_schema_ed_estrae(modello):
    m, pdf = modello
    m.nome = "ACME Audio"
    profilo = m.profilo()
    valida_schema({"versione_schema": 2, "fornitori": {m.chiave(): profilo}})
    assert len(estrai_listino(pdf, profilo).articoli) == 8


def test_salvataggio_utf8_sig_atomico_e_con_copia(tmp_path, modello):
    m, _ = modello
    m.nome = "ACME Audio"
    file = tmp_path / "supplier_rules.json"
    salva_fornitore_personale("acme_audio", m.profilo(), file)
    assert file.read_bytes().startswith(b"\xef\xbb\xbf")  # come lo salva il Blocco note
    assert not (tmp_path / "supplier_rules.json.bak").exists()
    m.nome = "Secondo"
    salva_fornitore_personale("secondo", m.profilo(), file)
    dati = _leggi(file)
    assert set(dati["fornitori"]) == {"acme_audio", "secondo"} and dati["versione_schema"] == 2
    assert (tmp_path / "supplier_rules.json.bak").exists()
    assert not (tmp_path / "supplier_rules.json.tmp").exists()


def test_salvataggio_converte_un_file_versione_1(tmp_path, modello):
    from tests.test_profilo import VECCHIO_JBL

    m, _ = modello
    m.nome = "ACME"
    file = tmp_path / "supplier_rules.json"
    file.write_text(json.dumps({"fornitori": {"vecchio": VECCHIO_JBL}}), encoding="utf-8")
    salva_fornitore_personale("acme", m.profilo(), file)
    dati = _leggi(file)
    valida_schema(dati)
    assert dati["fornitori"]["vecchio"]["colonne"][0]["campo"] == "identificativo"
    assert json.loads((tmp_path / "supplier_rules.json.bak").read_text(encoding="utf-8")) == {
        "fornitori": {"vecchio": VECCHIO_JBL}}


def test_un_profilo_non_valido_non_tocca_il_file(tmp_path, modello):
    m, _ = modello
    m.nome = "ACME"
    file = tmp_path / "supplier_rules.json"
    salva_fornitore_personale("acme", m.profilo(), file)
    prima = file.read_bytes()
    with pytest.raises(RegoleNonValide):
        salva_fornitore_personale("rotto", {"nome": "Rotto", "colonne": []}, file)
    assert file.read_bytes() == prima


def test_il_fornitore_salvato_e_subito_utilizzabile(tmp_path, monkeypatch, modello):
    m, pdf = modello
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    m.nome = "ACME Audio"
    salva_fornitore_personale(m.chiave(), m.profilo())
    assert config.elenco_fornitori()["acme_audio"] == "ACME Audio"
    assert len(estrai_listino(pdf, config.regole_fornitore("acme_audio")).articoli) == 8


def _salvato(m, **opzioni):
    """Profilo come lo salverebbe il wizard dopo qualche scelta dell'utente."""
    m.nome = "ACME"
    m.imposta_campo(2, "ignora")
    m.ancora, m.formato_prezzo, m.linee_divisorie, m.codice_con_parentesi = "codice", "it", True, False
    for chiave, valore in opzioni.items():
        setattr(m, chiave, valore)
    return m.profilo()


def test_modifica_riprende_la_mappatura_salvata(modello):
    m, pdf = modello
    salvato = _salvato(m)
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1), {"jbl_exhibo": "JBL", "acme": "ACME"})
    assert nuovo.applica_profilo("acme", salvato) == 4
    assert nuovo.campi == ["codice", "descrizione", "ignora", "prezzo"]
    assert (nuovo.nome, nuovo.ancora, nuovo.formato_prezzo) == ("ACME", "codice", "it")
    assert (nuovo.linee_divisorie, nuovo.codice_con_parentesi, nuovo.codici_tra_parentesi) == (True, False, False)
    # la chiave resta quella del fornitore modificato anche cambiando il nome, senza chiedere di sostituire
    nuovo.nome = "ACME Audio 2026"
    assert nuovo.chiave() == "acme" and not nuovo.sostituisce_esistente()
    assert nuovo.errori() == []
    assert nuovo.profilo() == {**salvato, "nome": "ACME Audio 2026"}


def test_modifica_senza_intestazione_abbina_per_posizione(tmp_path):
    pdf = crea_listino_generico(tmp_path / "senza.pdf", con_intestazione=False)
    m = ModelloWizard(analizza_pdf(str(pdf), 1))
    m.nome = "Senza"
    m.imposta_campo(1, "ignora")
    salvato = m.profilo()
    assert all(c["intestazioni"] == [] for c in salvato["colonne"])
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1))
    assert nuovo.applica_profilo("senza", salvato) == len(salvato["colonne"])
    assert nuovo.campi == m.campi


def test_modifica_con_colonne_non_abbinate_tiene_la_proposta(modello):
    m, pdf = modello
    salvato = _salvato(m)
    salvato["colonne"] = [salvato["colonne"][0], salvato["colonne"][3]]
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1), {"acme": "ACME"})
    assert nuovo.applica_profilo("acme", salvato) == 2
    assert nuovo.campi == ["codice", "descrizione", "ean", "prezzo"]  # descrizione ed EAN: proposta


def test_modifica_conserva_le_regole_che_il_wizard_non_mostra(modello):
    m, pdf = modello
    salvato = _salvato(m, codici_tra_parentesi=False)
    salvato.update(escludi=["PROMO"], prezzo_massimo=5000, descrizione_vuota_usa_modello=False)
    salvato["spaziatura"]["fattore_stacco"] = 2.0
    salvato["regex"]["ean"] = r"^\d{13}$"
    salvato["colonne"][3]["intestazioni"] = ["Prezzo netto", "Price EUR"]
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1), {"acme": "ACME"})
    nuovo.applica_profilo("acme", salvato)
    nuovo.linee_divisorie = False
    p = nuovo.profilo()
    assert (p["escludi"], p["prezzo_massimo"], p["descrizione_vuota_usa_modello"]) == (["PROMO"], 5000, False)
    assert p["spaziatura"] == {**salvato["spaziatura"], "linee_divisorie": False}
    assert p["regex"]["ean"] == r"^\d{13}$"
    assert p["colonne"][3]["intestazioni"] == ["Prezzo netto", "Price EUR"]  # i sinonimi aggiunti restano
    valida_schema({"versione_schema": 2, "fornitori": {"acme": p}})
    assert len(estrai_listino(pdf, p).articoli) == 8


def test_modifica_conserva_una_regex_del_codice_personalizzata(modello):
    m, pdf = modello
    salvato = _salvato(m)
    salvato["regex"]["codice"] = r"^\[(?P<valore>[^\]]+)\]$"
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1), {"acme": "ACME"})
    nuovo.applica_profilo("acme", salvato)
    assert nuovo.codici_tra_parentesi
    assert nuovo.profilo()["regex"]["codice"] == r"^\[(?P<valore>[^\]]+)\]$"
    nuovo.codici_tra_parentesi = False
    assert nuovo.profilo()["regex"]["codice"] is None


def test_modifica_non_puo_prendere_il_nome_di_un_altro_fornitore(modello):
    m, pdf = modello
    salvato = _salvato(m)
    nuovo = ModelloWizard(analizza_pdf(str(pdf), 1), {"jbl_exhibo": "JBL (Exhibo)", "acme": "ACME"})
    nuovo.applica_profilo("acme", salvato)
    nuovo.nome = "jbl (exhibo)"
    assert any("Esiste gia'" in e for e in nuovo.errori())
    nuovo.nome = "acme"
    assert nuovo.errori() == []


# --- colonne dinamiche ---------------------------------------------------------------------------

@pytest.fixture
def colore(tmp_path):
    from tests.sintetico_generico import crea_listino_colonne

    pdf = crea_listino_colonne(tmp_path / "colore.pdf", "colore")
    return ModelloWizard(analizza_pdf(str(pdf), 1)), pdf


def test_colonna_in_piu_proposta_come_testo_col_suo_nome(colore):
    m, _ = colore
    # «Colour» non e' il nome di un campo e il contenuto direbbe «modello», ma l'articolo ha gia' il codice
    assert m.campi == ["codice", "descrizione", "testo_generico", "ean", "prezzo"]
    assert m.etichette == ["SKU", "Description", "Colour", "EAN", "Price EUR"]


def test_il_profilo_salva_i_nomi_e_l_export_li_usa(colore):
    from tests.sintetico_generico import ATTESI_COLONNE

    m, pdf = colore
    m.nome = "ACME"
    p = m.profilo()
    valida_schema({"versione_schema": 2, "fornitori": {"acme": p}})
    assert [c.get("etichetta") for c in p["colonne"]] == ["SKU", "Description", "Colour", None, "Price EUR"]
    assert p["colonne"][2]["intestazioni"] == ["Colour"]  # per ritrovarla nelle altre pagine
    r = estrai_listino(pdf, p)
    assert [c.etichetta for c in r.colonne] == ATTESI_COLONNE["colore"][0]
    assert [x.altri["testo_1"] for x in r.articoli] == [riga[2] for riga in ATTESI_COLONNE["colore"][1]]
    assert all(x.categoria == "" for x in r.articoli)  # «Colour» non e' una marca


def test_il_nome_segue_il_ruolo_ma_non_cancella_quello_scelto(colore):
    m, _ = colore
    m.imposta_campo(2, "ignora")
    assert m.etichette[2] == ""
    m.imposta_campo(2, "testo_generico")
    assert m.etichette[2] == "Colour"
    m.imposta_etichetta(1, "Descr. breve")
    m.imposta_campo(1, "testo_generico")
    assert m.etichette[1] == "Descr. breve"


def test_nomi_proposti_sul_listino_generico(modello):
    m, _ = modello
    assert m.etichette == ["SKU", "Description", "EAN", "Price EUR"]


def test_nome_proposto_da_un_etichetta_su_due_righe(pdf_sintetico):
    # «Prezzo al» / «Pubblico»: il nome e' l'etichetta intera; la colonna composita esce coi nomi standard
    m = ModelloWizard(analizza_pdf(str(pdf_sintetico), 1))
    assert m.campi == ["identificativo", "descrizione", "prezzo"]
    assert m.etichette == ["", "Descrizione", "Prezzo al Pubblico"]
