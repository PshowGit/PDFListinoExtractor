# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cos'è

Applicazione desktop Windows (Python 3.12, customtkinter) che estrae da un listino prezzi PDF le colonne **Modello | Codice | EAN | Descrizione | Prezzo** e le esporta nel foglio Excel `Listino`. È tarata sul listino JBL distribuito da Exhibo (gennaio 2026: 121 pagine, 673 articoli), ma le regole di lettura stanno in `config/supplier_rules.json`. Il progetto è in italiano: commenti, messaggi di commit e interfaccia sono in italiano.

## Ambiente (vale su questa macchina)

- C: è stretto: prefissare i comandi con `$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'` (PowerShell).
- Le dipendenze sono gestite con `uv`. Il listino reale `samples/Listino_JBL_Gen_2026.pdf` è escluso da git (materiale commerciale). I test che lo usano si saltano se il file manca.
- Inno Setup 6 è installato per utente, in `%LOCALAPPDATA%\Programs\Inno Setup 6`. Tesseract non è installato, quindi il test OCR viene saltato.

## Comandi

```powershell
uv run python main.py                                   # avvio dal sorgente
uv run pytest -q                                        # suite completa (66 test, 1 saltato senza Tesseract)
uv run pytest tests/test_pdf_extraction.py -v           # un file
uv run pytest tests/test_gui.py::test_ordinamento_per_prezzo_con_mancanti_in_fondo -v   # un test
uv run ruff check .                                     # lint (config in pyproject.toml)
uv run python tools/misura.py <pdf> [--profilo]         # tempi di estrazione senza interfaccia
uv run python tools/analizza_pdf.py <pdf> [1,27]        # testo con coordinate, per tarare un fornitore nuovo
uv run python tools/prova_gui.py <pdf> <out.xlsx>       # collaudo della finestra vera (report .collaudo.json)
```

Distribuzione:

```bat
scripts\build_exe.bat          rem sync + test + PyInstaller -> dist\PDFListinoExtractor\ (onedir)
scripts\build_installer.bat    rem Inno Setup -> dist\PDFListinoExtractor_Setup.exe
uv run python scripts\imposta_versione.py 1.1.0    rem unica via per cambiare versione (version.py + pyproject.toml)
powershell -ExecutionPolicy Bypass -File tools\collaudo_installer.ps1 <setup_vecchio> <setup_nuovo> <pdf>
```

`PDFListinoExtractor.exe --collaudo <pdf> <out.xlsx>` collauda l'eseguibile impacchettato: apre la finestra, estrae, esporta e scrive un report JSON. `tools\collaudo_installer.ps1` installa per l'utente corrente, aggiorna, disinstalla e verifica 21 punti; l'installazione in Program Files (UAC) non si può automatizzare.

## Architettura

Flusso: `extractors/pdf_reader` (apertura e verifica, sola lettura) → `extractors/text_extractor` oppure `ocr_extractor` (produce `Span` con le coordinate) → `extractors/table_extractor` (colonne lette dall'intestazione della pagina, area utile, righe per colonna) → `processors/article_parser` → `processors/data_validator` → `exporters/excel_exporter`. A orchestrare è `processors/estrazione.estrai_listino`; l'interfaccia in `gui/` non contiene logica di estrazione.

Scelte non ovvie, ognuna motivata da una misura o da un difetto reale:

- **L'articolo si individua dalla colonna Modello, non dal prezzo.** Ogni articolo è un blocco di righe ravvicinate (`distanza_blocco`): nome su una o più righe, `(codice)`, EAN facoltativo. Ancorando sul prezzo, un prezzo mancante fonderebbe due articoli in uno. Il prezzo è quello che cade nell'estensione verticale del blocco: se ce ne sono due **non se ne sceglie uno**, si segnala.
- **Le anomalie non si correggono mai in automatico.** Gli errori dell'estrazione stanno in `Articolo.note_estrazione` (per campo) e un intervento dell'utente sul campo li cancella (`Articolo.imposta`). Quelle del validatore stanno in `Articolo.anomalie` e si ricalcolano da zero dopo ogni modifica, perché i duplicati dipendono da tutte le righe. Non si scartano nemmeno i duplicati.
- **L'estrazione gira in un processo separato** (`esegui_in_processo`, contesto `spawn`), non in un thread. PyMuPDF tiene il GIL durante l'analisi di ogni pagina: in un thread l'interfaccia restava ferma per tutto il lavoro (5 s su un PDF di 1.210 pagine). Ne seguono due obblighi: ogni script che apre la finestra deve avere la guardia `if __name__ == "__main__"`, e `main.py` chiama `multiprocessing.freeze_support()` per l'eseguibile. In `_leggi_coda` si ridisegna solo l'ultimo avanzamento ricevuto, perché aggiornare a ogni pagina bloccava la finestra.
- **`get_text("dict")` va chiamato con `FLAG_TESTO`**, che esclude le immagini: di default porta con sé i byte di ogni immagine ed era il 75% del tempo di estrazione.
- **Percorsi** (`percorsi.py`): le risorse sono in sola lettura (`_MEIPASS` nell'eseguibile, che può stare in Program Files). Log e regole personali vanno in `%LOCALAPPDATA%\PDFListinoExtractor`, che aggiornamenti e disinstallazione non toccano. `config.carica_regole` unisce alle regole distribuite quelle di `%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json`, letto in `utf-8-sig` perché il Blocco note salva col BOM; se il file è illeggibile viene ignorato con un avviso e non blocca l'avvio.
- **Versione**: l'unica fonte è `version.py`, letto dal titolo della finestra, dal `.spec` (proprietà dell'eseguibile) e da `build_installer.bat`. L'`AppId` in `installer/PDFListinoExtractor.iss` non va mai cambiato, o un aggiornamento verrebbe installato come un programma diverso. `[InstallDelete]` svuota `_internal` a ogni aggiornamento. `EDITORE` resta vuoto finché non se ne indica uno reale.
- **Formato dell'export**: il codice resta tra parentesi (`codice_con_parentesi`); Modello, Codice ed EAN sono celle di testo (`@`); un prezzo mancante è una cella vuota, non `0`. Dove la colonna Descrizione è vuota (accessori), la descrizione ripete il nome del modello.

## Test

`tests/sintetico.py` genera un PDF con l'impaginazione del listino reale e i risultati attesi in `ATTESI`. Per un caso nuovo si aggiungono lì sia il contenuto della pagina sia il risultato atteso. Per i test con Tk non serve un display virtuale su Windows. Una suite verde però non basta: il blocco dell'interfaccia e il problema del BOM sono emersi solo provando l'applicazione vera (`tools/prova_gui.py`, `--collaudo`, `tools/collaudo_installer.ps1`).

## Licenze

PyMuPDF è **AGPL-3.0**. Il repository `PshowGit/PDFListinoExtractor` è pubblico, ma non ha ancora un file di licenza del programma. L'elenco dei componenti di terze parti è in `installer/LICENZE_TERZE_PARTI.txt`.
