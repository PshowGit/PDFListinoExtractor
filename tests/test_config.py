import json

import pytest

import config
from config import PERCORSO_REGOLE, carica_regole


def test_senza_file_personale_valgono_le_regole_distribuite(tmp_path):
    tutte = carica_regole(PERCORSO_REGOLE, personali=tmp_path / "assente.json")
    assert tutte["predefinito"] == "jbl_exhibo"


def test_le_regole_personali_si_aggiungono_e_sostituiscono(tmp_path):
    personali = tmp_path / "supplier_rules.json"
    personali.write_text(
        json.dumps({"predefinito": "altro", "fornitori": {"altro": {"nome": "Altro fornitore"}}}),
        encoding="utf-8",
    )
    tutte = carica_regole(PERCORSO_REGOLE, personali=personali)
    assert set(tutte["fornitori"]) == {"jbl_exhibo", "altro"}
    assert tutte["predefinito"] == "altro"


def test_file_personale_salvato_col_bom(tmp_path):
    # il Blocco note e Set-Content -Encoding UTF8 scrivono il BOM: e' il caso trovato nel collaudo
    personali = tmp_path / "supplier_rules.json"
    personali.write_bytes(b"\xef\xbb\xbf" + json.dumps({"fornitori": {"x": {"nome": "X"}}}).encode())
    assert "x" in carica_regole(PERCORSO_REGOLE, personali=personali)["fornitori"]
    assert config.avviso_regole_personali is None


def test_file_personale_rovinato_non_impedisce_l_avvio(tmp_path):
    personali = tmp_path / "supplier_rules.json"
    personali.write_text("{ non e' json", encoding="utf-8")
    tutte = carica_regole(PERCORSO_REGOLE, personali=personali)
    assert set(tutte["fornitori"]) == {"jbl_exhibo"}
    assert "ignorato" in config.avviso_regole_personali


def test_predefinito_personale_inesistente_e_ignorato(tmp_path):
    personali = tmp_path / "supplier_rules.json"
    personali.write_text(json.dumps({"predefinito": "nessuno", "fornitori": {}}), encoding="utf-8")
    assert carica_regole(PERCORSO_REGOLE, personali=personali)["predefinito"] == "jbl_exhibo"


def test_le_regole_personali_si_leggono_da_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cartella = tmp_path / "PDFListinoExtractor"
    cartella.mkdir()
    (cartella / "supplier_rules.json").write_text(
        json.dumps({"fornitori": {"mio": {"nome": "Mio"}}}), encoding="utf-8"
    )
    assert "mio" in config.elenco_fornitori()
    assert next(iter(config.elenco_fornitori())) == "jbl_exhibo"  # il predefinito resta primo


def _personali_con(tmp_path, **fornitori):
    percorso = tmp_path / "supplier_rules.json"
    for chiave, nome in fornitori.items():
        config.salva_fornitore_personale(chiave, {"nome": nome, "colonne": [{"campo": "codice"}]}, percorso)
    return percorso


def _fornitori_nel_file(percorso):
    return json.loads(percorso.read_text(encoding="utf-8-sig"))["fornitori"]


def test_rinominare_cambia_solo_il_nome(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME", beta="Beta")
    config.rinomina_fornitore_personale("acme", "  ACME Audio 2026 ", percorso)
    fornitori = _fornitori_nel_file(percorso)
    assert fornitori["acme"] == {"nome": "ACME Audio 2026", "colonne": [{"campo": "codice"}]}
    assert fornitori["beta"]["nome"] == "Beta"
    assert json.loads(percorso.with_suffix(".json.bak").read_text(encoding="utf-8-sig"))["fornitori"]["acme"][
        "nome"] == "ACME"


def test_rinominare_rifiuta_un_nome_vuoto_o_gia_usato(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME", beta="Beta")
    prima = percorso.read_bytes()
    distribuito = carica_regole(PERCORSO_REGOLE, personali=tmp_path / "assente.json")["fornitori"]["jbl_exhibo"]
    for nome in ("   ", "beta", distribuito["nome"].upper()):
        with pytest.raises(config.NomeNonValido):
            config.rinomina_fornitore_personale("acme", nome, percorso)
    assert percorso.read_bytes() == prima
    config.rinomina_fornitore_personale("acme", "acme", percorso)  # cambiare solo maiuscole e' lecito
    assert _fornitori_nel_file(percorso)["acme"]["nome"] == "acme"


def test_il_fornitore_distribuito_non_si_rinomina_ne_si_rimuove(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME")
    with pytest.raises(KeyError):
        config.rinomina_fornitore_personale("jbl_exhibo", "JBL", percorso)
    with pytest.raises(KeyError):
        config.rimuovi_fornitore_personale("jbl_exhibo", percorso)
    with pytest.raises(KeyError):
        config.rimuovi_fornitore_personale("acme", tmp_path / "assente.json")


def test_rimuovere_toglie_il_fornitore_e_il_suo_predefinito(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME", beta="Beta")
    dati = json.loads(percorso.read_text(encoding="utf-8-sig"))
    dati["predefinito"] = "acme"
    percorso.write_text(json.dumps(dati), encoding="utf-8")
    config.rimuovi_fornitore_personale("acme", percorso)
    dati = json.loads(percorso.read_text(encoding="utf-8-sig"))
    assert set(dati["fornitori"]) == {"beta"} and "predefinito" not in dati
    assert "acme" in json.loads(percorso.with_suffix(".json.bak").read_text(encoding="utf-8-sig"))["fornitori"]
    assert carica_regole(PERCORSO_REGOLE, personali=percorso)["predefinito"] == "jbl_exhibo"


def test_rimuovere_l_ultimo_fornitore_lascia_un_file_valido(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME")
    config.rimuovi_fornitore_personale("acme", percorso)
    assert set(carica_regole(PERCORSO_REGOLE, personali=percorso)["fornitori"]) == {"jbl_exhibo"}
    assert config.avviso_regole_personali is None


def test_rimuovere_un_fornitore_che_ne_sostituiva_uno_distribuito_lo_ripristina(tmp_path):
    percorso = _personali_con(tmp_path, jbl_exhibo="JBL modificato")
    assert carica_regole(PERCORSO_REGOLE, personali=percorso)["fornitori"]["jbl_exhibo"]["nome"] == "JBL modificato"
    config.rimuovi_fornitore_personale("jbl_exhibo", percorso)
    assert carica_regole(PERCORSO_REGOLE, personali=percorso)["fornitori"]["jbl_exhibo"]["nome"] != "JBL modificato"


def test_chiavi_personali(tmp_path):
    assert config.chiavi_personali(tmp_path / "assente.json") == set()
    percorso = _personali_con(tmp_path, acme="ACME", beta="Beta")
    assert config.chiavi_personali(percorso) == {"acme", "beta"}
    percorso.write_text("{ rovinato", encoding="utf-8")
    assert config.chiavi_personali(percorso) == set()  # come carica_regole, che lo ignora
