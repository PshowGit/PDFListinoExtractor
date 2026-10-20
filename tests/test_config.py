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


def _profilo(nome, campo="codice"):
    return {"nome": nome, "colonne": [{"campo": campo}, {"campo": "prezzo"}]}


def test_esportare_e_importare_su_un_altra_postazione(tmp_path):
    vecchia = tmp_path / "vecchia" / "supplier_rules.json"
    vecchia.parent.mkdir()
    config.salva_fornitore_personale("acme", _profilo("ACME"), vecchia)
    config.salva_fornitore_personale("beta", _profilo("Beta", "ean"), vecchia)
    esportato = tmp_path / "Fornitori.json"
    assert config.esporta_fornitori_personali(esportato, vecchia) == 2
    assert esportato.read_bytes().startswith(b"\xef\xbb\xbf")  # come il file personale
    assert not esportato.with_suffix(".json.bak").exists()

    nuova = tmp_path / "nuova" / "supplier_rules.json"
    nuova.parent.mkdir()
    esito = config.importa_fornitori(esportato, nuova)  # sulla postazione nuova il file non c'e' ancora
    assert esito.aggiunti == ["acme", "beta"] and not esito.rinominati and not esito.gia_presenti
    assert _fornitori_nel_file(nuova) == _fornitori_nel_file(vecchia)
    assert {"acme", "beta"} <= set(carica_regole(PERCORSO_REGOLE, personali=nuova)["fornitori"])


def test_senza_fornitori_personali_non_si_esporta(tmp_path):
    with pytest.raises(OSError):
        config.esporta_fornitori_personali(tmp_path / "f.json", tmp_path / "assente.json")
    percorso = _personali_con(tmp_path, acme="ACME")
    config.rimuovi_fornitore_personale("acme", percorso)
    with pytest.raises(config.RegoleNonValide):
        config.esporta_fornitori_personali(tmp_path / "f.json", percorso)
    assert not (tmp_path / "f.json").exists()


def test_importare_non_sovrascrive_i_fornitori_locali(tmp_path):
    percorso = tmp_path / "supplier_rules.json"
    config.salva_fornitore_personale("acme", _profilo("ACME"), percorso)
    config.salva_fornitore_personale("gamma", _profilo("Gamma"), percorso)
    locali = _fornitori_nel_file(percorso)
    distribuito = carica_regole(PERCORSO_REGOLE, personali=tmp_path / "assente.json")["fornitori"]["jbl_exhibo"]
    da_importare = tmp_path / "importa.json"
    da_importare.write_text(json.dumps({"versione_schema": 2, "fornitori": {
        "acme": _profilo("ACME", "ean"),  # stessa chiave e stesso nome, regole diverse
        "delta": _profilo("gamma", "modello"),  # chiave nuova, nome gia' in uso (maiuscole a parte)
        "epsilon": _profilo(distribuito["nome"]),  # il nome del fornitore distribuito
    }}), encoding="utf-8")

    esito = config.importa_fornitori(da_importare, percorso)
    fornitori = _fornitori_nel_file(percorso)
    assert fornitori["acme"] == locali["acme"] and fornitori["gamma"] == locali["gamma"]
    assert fornitori["acme_importato"] == _profilo("ACME - Importato", "ean")
    assert fornitori["delta"]["nome"] == "gamma - Importato"
    assert fornitori["epsilon"]["nome"] == f"{distribuito['nome']} - Importato"
    assert esito.aggiunti == ["acme_importato", "delta", "epsilon"]
    assert esito.rinominati == [("ACME", "ACME - Importato"), ("gamma", "gamma - Importato"),
                                (distribuito["nome"], f"{distribuito['nome']} - Importato")]
    assert _fornitori_nel_file(percorso.with_suffix(".json.bak")) == locali
    nomi = [p["nome"].lower() for p in carica_regole(PERCORSO_REGOLE, personali=percorso)["fornitori"].values()]
    assert len(nomi) == len(set(nomi))  # il menu riconosce il fornitore dal nome

    # reimportare lo stesso file non crea copie, e senza nulla di nuovo il file non si tocca
    prima = percorso.read_bytes()
    esito = config.importa_fornitori(da_importare, percorso)
    assert esito.aggiunti == [] and len(esito.gia_presenti) == 3
    assert percorso.read_bytes() == prima


def test_importare_un_secondo_conflitto_numera_il_nome(tmp_path):
    percorso = tmp_path / "supplier_rules.json"
    config.salva_fornitore_personale("acme", _profilo("ACME"), percorso)
    config.salva_fornitore_personale("acme_importato", _profilo("ACME - Importato", "ean"), percorso)
    da_importare = tmp_path / "importa.json"
    da_importare.write_text(json.dumps({"versione_schema": 2, "fornitori": {"acme": _profilo("ACME", "modello")}}),
                            encoding="utf-8")
    esito = config.importa_fornitori(da_importare, percorso)
    assert esito.aggiunti == ["acme_importato_2"]
    assert _fornitori_nel_file(percorso)["acme_importato_2"]["nome"] == "ACME - Importato 2"


def test_importare_un_fornitore_che_sostituiva_quello_distribuito(tmp_path):
    # sulla postazione di partenza il personale con la chiave del distribuito lo sostituiva: idem qui
    da_importare = tmp_path / "importa.json"
    da_importare.write_text(json.dumps({"versione_schema": 2, "fornitori": {
        "jbl_exhibo": _profilo("JBL modificato")}}), encoding="utf-8")
    percorso = tmp_path / "supplier_rules.json"
    assert config.importa_fornitori(da_importare, percorso).aggiunti == ["jbl_exhibo"]
    assert carica_regole(PERCORSO_REGOLE, personali=percorso)["fornitori"]["jbl_exhibo"]["nome"] == "JBL modificato"


def test_importare_un_file_della_versione_1_e_i_sinonimi(tmp_path):
    percorso = _personali_con(tmp_path, acme="ACME")
    da_importare = tmp_path / "vecchio.json"
    v1 = {"nome": "Zeta", "colonne_predefinite": {"modello_x": 40, "descrizione_x": 200, "prezzo_x": 500}}
    da_importare.write_bytes(b"\xef\xbb\xbf" + json.dumps({"fornitori": {"zeta": v1}}).encode())
    assert config.importa_fornitori(da_importare, percorso).aggiunti == ["zeta"]
    zeta = _fornitori_nel_file(percorso)["zeta"]
    assert zeta["nome"] == "Zeta" and [c["campo"] for c in zeta["colonne"]] == ["identificativo", "descrizione", "prezzo"]

    con_sinonimi = tmp_path / "sinonimi.json"
    con_sinonimi.write_text(json.dumps({"versione_schema": 2, "sinonimi": {"codice": ["Art.", "Rif."]},
                                        "fornitori": {"acme": _profilo("ACME")}}), encoding="utf-8")
    config.importa_fornitori(con_sinonimi, percorso)
    config.importa_fornitori(con_sinonimi, percorso)
    dati = json.loads(percorso.read_text(encoding="utf-8-sig"))
    assert dati["sinonimi"] == {"codice": ["Art.", "Rif."]}  # senza doppioni


@pytest.mark.parametrize("contenuto", [
    "{ non e' json",
    "[1, 2]",
    json.dumps({"versione_schema": 2, "fornitori": {}}),
    json.dumps({"versione_schema": 2, "fornitori": {"Chiave Errata": {"nome": "X", "colonne": [{"campo": "codice"}]}}}),
    json.dumps({"versione_schema": 2, "fornitori": {"x": {"nome": "X", "colonne": [{"campo": "colore"}]}}}),
    json.dumps({"versione_schema": 2, "fornitori": {"x": {"nome": "X"}}}),
])
def test_importare_un_file_non_valido_non_tocca_nulla(tmp_path, contenuto):
    percorso = _personali_con(tmp_path, acme="ACME")
    prima = percorso.read_bytes()
    da_importare = tmp_path / "importa.json"
    da_importare.write_text(contenuto, encoding="utf-8")
    with pytest.raises(config.RegoleNonValide, match="importa.json"):
        config.importa_fornitori(da_importare, percorso)
    assert percorso.read_bytes() == prima
