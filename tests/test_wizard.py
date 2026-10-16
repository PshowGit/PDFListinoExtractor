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
