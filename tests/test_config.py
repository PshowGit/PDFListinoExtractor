import json

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
