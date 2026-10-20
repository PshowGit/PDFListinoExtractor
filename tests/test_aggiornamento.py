import hashlib
import io
import json
import subprocess
import urllib.error

import pytest

import aggiornamento
from aggiornamento import AggiornamentoNonValido, Rilascio

SETUP = b"MZ finto setup " * 1000
URL = "https://github.com/PshowGit/PDFListinoExtractor/releases/download/v9.1.0/PDFListinoExtractor_Setup.exe"


def _api(tag="v9.1.0", digest=None, url=URL, nome="PDFListinoExtractor_Setup.exe", **altro):
    return {
        "tag_name": tag, "draft": False, "prerelease": False, "body": "## Novità\n\n- **Una** cosa",
        "html_url": f"https://github.com/PshowGit/PDFListinoExtractor/releases/tag/{tag}",
        "assets": [{"name": nome, "size": len(SETUP), "browser_download_url": url,
                    "digest": digest or "sha256:" + hashlib.sha256(SETUP).hexdigest()}],
        **altro,
    }


class _Risposta(io.BytesIO):
    def __init__(self, dati: bytes):
        super().__init__(dati)
        self.headers = {"Content-Length": str(len(dati))}


def _apri(contenuto, richieste=None):
    def apri(richiesta, timeout):
        if richieste is not None:
            richieste.append(richiesta)
        if isinstance(contenuto, Exception):
            raise contenuto
        return _Risposta(contenuto if isinstance(contenuto, bytes) else json.dumps(contenuto).encode())
    return apri


@pytest.fixture(autouse=True)
def _isolato(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("TMP", str(tmp_path / "temp"))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.delenv(aggiornamento.VARIABILE_URL, raising=False)
    (tmp_path / "temp").mkdir()
    monkeypatch.setattr(aggiornamento.tempfile, "tempdir", None)  # rilegge TMP


def test_versione_da_tag():
    assert aggiornamento.versione_da_tag("v1.10.0") == (1, 10, 0) > aggiornamento.versione_da_tag("v1.9.3")
    assert aggiornamento.versione_da_tag("1.6.0") == (1, 6, 0)
    for tag in ("", "v1.6", "v1.6.0-beta", "latest", None):
        assert aggiornamento.versione_da_tag(tag) is None


def test_una_versione_piu_recente_si_propone():
    richieste = []
    r = aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(_api(), richieste))
    assert r is not None and r.versione == "9.1.0" and r.tag == "v9.1.0"
    assert r.sha256 == hashlib.sha256(SETUP).hexdigest() and r.url_setup == URL
    assert richieste[0].full_url == aggiornamento.URL_API


@pytest.mark.parametrize("tag", ["v1.6.0", "v1.5.2", "v0.9.0"])
def test_una_versione_uguale_o_precedente_no(tag):
    assert aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(_api(tag))) is None


@pytest.mark.parametrize("errore", [
    urllib.error.URLError("offline"), TimeoutError("timeout"), ConnectionResetError(),
    urllib.error.HTTPError(aggiornamento.URL_API, 403, "rate limit", {}, None), b"{ non e' json",
])
def test_gli_errori_di_rete_sono_silenziosi(errore):
    assert aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(errore)) is None


@pytest.mark.parametrize("dati", [
    _api(nome="altro.exe"),  # senza il setup
    _api(digest="md5:1234"),  # senza SHA-256: non si potrebbe verificare
    _api(url="https://example.com/PDFListinoExtractor_Setup.exe"),  # da un altro sito
    _api(tag="ultima"),
    _api(draft=True),
    [1, 2],
])
def test_release_che_non_si_propongono(dati):
    assert aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(dati)) is None


def test_col_server_di_collaudo_si_scarica_da_li(monkeypatch):
    monkeypatch.setenv(aggiornamento.VARIABILE_URL, "http://127.0.0.1:8765/latest.json")
    locale = "http://127.0.0.1:8765/PDFListinoExtractor_Setup.exe"
    assert aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(_api(url=locale))).url_setup == locale
    assert aggiornamento.cerca_aggiornamento("1.6.0", apri=_apri(_api(url=URL))) is None


def test_versione_ignorata_in_un_file_a_parte(tmp_path):
    assert aggiornamento.versione_ignorata() is None
    aggiornamento.ignora_versione("9.1.0")
    assert aggiornamento.versione_ignorata() == "9.1.0"
    cartella = tmp_path / "appdata" / "PDFListinoExtractor"
    assert not (cartella / "supplier_rules.json").exists()  # le regole dei fornitori non si toccano
    (cartella / "preferenze.json").write_text("{ rovinato", encoding="utf-8")
    assert aggiornamento.versione_ignorata() is None


def _rilascio(sha=None) -> Rilascio:
    return Rilascio("9.1.0", "v9.1.0", "", "", URL, sha or hashlib.sha256(SETUP).hexdigest(), len(SETUP))


def test_scarica_e_verifica(tmp_path):
    avanzamenti = []
    percorso = aggiornamento.scarica(_rilascio(), lambda letti, totale: avanzamenti.append((letti, totale)),
                                     apri=_apri(SETUP))
    assert percorso == tmp_path / "temp" / "PDFListinoExtractor_Setup_9.1.0.exe"
    assert percorso.read_bytes() == SETUP and avanzamenti[-1] == (len(SETUP), len(SETUP))


def test_un_file_diverso_da_quello_pubblicato_non_resta(tmp_path):
    with pytest.raises(AggiornamentoNonValido, match="SHA-256"):
        aggiornamento.scarica(_rilascio("0" * 64), apri=_apri(SETUP))
    assert list((tmp_path / "temp").iterdir()) == []


def test_scaricamento_annullato_o_interrotto(tmp_path):
    assert aggiornamento.scarica(_rilascio(), annullato=lambda: True, apri=_apri(SETUP)) is None
    with pytest.raises(OSError):
        aggiornamento.scarica(_rilascio(), apri=_apri(urllib.error.URLError("caduta")))
    assert list((tmp_path / "temp").iterdir()) == []


def test_pulisci_scaricati(tmp_path):
    temp = tmp_path / "temp"
    for nome in ("PDFListinoExtractor_Setup_9.0.0.exe", "PDFListinoExtractor_Setup_9.1.0.exe.part", "altro.exe"):
        (temp / nome).write_bytes(b"x")
    aggiornamento.pulisci_scaricati()
    assert [f.name for f in temp.iterdir()] == ["altro.exe"]


def test_argomenti_dell_installer(tmp_path):
    cartella = tmp_path / "Installazione prova àèù" / "PDFListinoExtractor"
    argomenti = aggiornamento.argomenti_setup(tmp_path / "setup.exe", "/CURRENTUSER", cartella)
    assert argomenti[1:5] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"]
    assert f"/DIR={cartella}" in argomenti and aggiornamento.RIAVVIA in argomenti
    # la cartella con la barra finale non deve chiudere le virgolette con un escape
    con_barra = aggiornamento.argomenti_setup(tmp_path / "s.exe", "/ALLUSERS", str(cartella) + "\\")
    assert f"/DIR={cartella}" in con_barra


def test_avvia_installazione_staccata(tmp_path, monkeypatch):
    chiamate = []
    monkeypatch.setattr(subprocess, "Popen", lambda argomenti, **k: chiamate.append((argomenti, k)))
    aggiornamento.avvia_installazione(tmp_path / "setup.exe", "/ALLUSERS", tmp_path)
    argomenti, opzioni = chiamate[0]
    assert argomenti[0] == str(tmp_path / "setup.exe") and "/ALLUSERS" in argomenti
    assert opzioni["creationflags"] & subprocess.DETACHED_PROCESS


def test_modo_installazione_dal_registro(tmp_path, monkeypatch):
    import winreg

    cartella = tmp_path / "PDFListinoExtractor"
    registrate = {}
    monkeypatch.setattr(aggiornamento, "_cartella_registrata", lambda radice: registrate.get(radice))
    assert aggiornamento.modo_installazione(cartella) is None  # una copia di dist o il sorgente
    registrate[winreg.HKEY_LOCAL_MACHINE] = str(cartella).upper() + "\\"
    assert aggiornamento.modo_installazione(cartella) == "/ALLUSERS"
    registrate[winreg.HKEY_CURRENT_USER] = str(cartella) + "\\"
    assert aggiornamento.modo_installazione(cartella) == "/CURRENTUSER"
    registrate[winreg.HKEY_CURRENT_USER] = str(tmp_path / "altra")
    assert aggiornamento.modo_installazione(cartella) == "/ALLUSERS"


def test_dal_sorgente_non_si_aggiorna():
    assert aggiornamento.attivo() is False


def test_testo_delle_note():
    testo = aggiornamento.testo_note("## Novità\r\n\r\n- **Esporta** il file `.json`\r\n*Esegui comunque*")
    assert testo == "Novità\n\n• Esporta il file .json Esegui comunque"


def test_le_righe_spezzate_si_riuniscono():
    note = (
        "## Novità\n\n### Titolo\n\nPrimo paragrafo che va\na capo.\n\n"
        "- Voce che va\n  a capo.\n- Seconda voce.\n\nFine."
    )
    assert aggiornamento.testo_note(note) == (
        "Novità\n\nTitolo\n\nPrimo paragrafo che va a capo.\n\n• Voce che va a capo.\n• Seconda voce.\n\nFine."
    )
