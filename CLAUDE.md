# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cos'è

Applicazione desktop Windows (Python 3.12, customtkinter) che estrae da un listino prezzi PDF le colonne **Modello | Codice | EAN | Descrizione | Prezzo** e le esporta nel foglio Excel `Listino`. Il motore è universale: ricava colonne e articoli dalla geometria del documento. Un fornitore nuovo si configura dal wizard «Configura nuovo fornitore» e finisce nelle regole personali. Il profilo distribuito è quello del listino JBL di Exhibo (gennaio 2026: 121 pagine, 673 articoli). Il progetto è in italiano: commenti, messaggi di commit e interfaccia sono in italiano.

## Ambiente (vale su questa macchina)

- C: è stretto: prefissare i comandi con `$env:TMP='D:\tmp'; $env:TEMP='D:\tmp'` (PowerShell).
- Le dipendenze sono gestite con `uv`. I listini reali `samples/Listino_JBL_Gen_2026.pdf` e `samples/Etabeta_Larentis.pdf` sono esclusi da git (materiale commerciale). I test che li usano si saltano se il file manca.
- **`%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json` contiene i fornitori veri dell'utente**, creati col wizard (JBL, GTD, JVL). Non leggerlo per prova, non sovrascriverlo, non cancellarlo. I test usano `monkeypatch.setenv("LOCALAPPDATA", tmp_path)`, e `tools\collaudo_installer.ps1` lancia il programma con una `%LOCALAPPDATA%` di prova in `D:\tmp`. Ogni nuovo collaudo deve fare lo stesso.
- Inno Setup 6 è installato per utente, in `%LOCALAPPDATA%\Programs\Inno Setup 6`. Tesseract non è installato, quindi il test OCR viene saltato.

## Comandi

```powershell
uv run python main.py                                   # avvio dal sorgente
uv run pytest -q                                        # suite completa (170 test, 1 saltato senza Tesseract)
uv run pytest tests/test_pdf_extraction.py -v           # un file
uv run pytest tests/test_gui.py::test_ordinamento_per_prezzo_con_mancanti_in_fondo -v   # un test
uv run ruff check .                                     # lint (config in pyproject.toml)
uv run python tools/misura.py <pdf> [--profilo]         # tempi di estrazione senza interfaccia
uv run python tools/analizza_pdf.py <pdf> [1,27]        # testo con coordinate, per i casi che il wizard non copre
uv run python tools/prova_gui.py <pdf> <out.xlsx>       # collaudo della finestra vera (report .collaudo.json)
uv run python tools/prova_wizard.py <pdf> <out.png> [pagina]   # collaudo visivo del wizard, non salva nulla
uv run python tools/misura_copertura.py <pdf> [pagina]  # prezzi del PDF attribuiti a un articolo, con la proposta del wizard
```

`misura_copertura` è la misura di qualità indipendente dal motore. Conta, pagina per pagina, le scritte con la forma di un prezzo e le confronta con gli articoli che ne hanno uno. Una pagina «in eccesso» vuol dire un prezzo inventato, una «con perdite» articoli persi. Sul catalogo Etabeta: 97,4%, 0 pagine in eccesso. Prima di cambiare il motore conviene salvare l'estrazione del JBL in un JSON fuori dal repository e confrontarla campo per campo dopo la modifica: è così che sono stati trovati i difetti di raggruppamento.

Distribuzione:

```bat
scripts\build_exe.bat          rem sync + test + PyInstaller -> dist\PDFListinoExtractor\ (onedir)
scripts\build_installer.bat    rem Inno Setup -> dist\PDFListinoExtractor_Setup.exe
uv run python scripts\imposta_versione.py 1.3.0    rem unica via per cambiare versione (version.py + pyproject.toml)
powershell -ExecutionPolicy Bypass -File tools\collaudo_installer.ps1 <setup_vecchio> <setup_nuovo> <pdf>
```

`PDFListinoExtractor.exe --collaudo <pdf> <out.xlsx>` collauda l'eseguibile impacchettato: apre la finestra, estrae, esporta e scrive un report JSON. `--collaudo-wizard <pdf> <regole.json> [pagina]` fa lo stesso col wizard, dall'analisi al salvataggio, scrivendo nel file indicato e non nelle regole dell'utente. Su un catalogo va indicata una pagina con una tabella: la prima è spesso l'indice, e lì la proposta non ha senso. Serve anche a verificare che `jsonschema` e lo schema siano inclusi dal `.spec`. `tools\collaudo_installer.ps1` installa per l'utente corrente, aggiorna, disinstalla e verifica 21 punti; l'installazione in Program Files (UAC) non si può automatizzare.

## Architettura

Flusso: `extractors/pdf_reader` (apertura e verifica, sola lettura) → `extractors/text_extractor` oppure `ocr_extractor` (produce `Span` con le coordinate) → `extractors/table_extractor` (geometria: statistiche del documento, testate ripetute, intestazione, colonne fisiche) → `processors/raggruppamento` (righe → articoli, funzioni pure) → `processors/article_parser` (campi) → `processors/data_validator` → `exporters/excel_exporter`. A orchestrare è `processors/estrazione.estrai_listino`, in **due passate**: le soglie sono statistiche dell'intero documento, quindi prima si leggono tutte le pagine e poi le si interpreta. L'interfaccia in `gui/` non contiene logica di estrazione. Il wizard ha la sua logica in `processors/wizard.py` (`ModelloWizard`, senza Tk) e la pre-analisi in `processors/analisi_layout.py`. Progetto e motivazioni: `docs/progetto-estrazione-universale.md`.

**Nessuna coordinata fissa.** Il profilo (schema 2, `config/supplier_rules.schema.json`, completato da `processors/profilo.normalizza`) dice solo quale colonna contiene quale campo. Ogni distanza è un multiplo del corpo o dell'interlinea mediana del documento. Non aggiungere soglie in punti assoluti. **I casi di non regressione sono due e vanno tenuti entrambi.**
- **Listino JBL**: stessi 673 articoli del motore a coordinate fisse, campo per campo, sia col profilo distribuito sia con la sola proposta del wizard (`tests/test_universale.py`).
- **Catalogo Etabeta** (`tests/test_catalogo.py`, PDF vero + `tests/sintetico_catalogo.py`): almeno il 97% dei prezzi attribuiti e nessuna pagina in eccesso.

Una regola nuova che aggiusta uno dei due rompe spesso l'altro: è successo più volte. Il motore è anche provato su un layout opposto (`tests/sintetico_generico.py`, con e senza intestazione).

Scelte non ovvie, ognuna motivata da una misura o da un difetto reale:

- **L'articolo si individua dall'ancora**, cioè il campo scelto nel profilo o dedotto per densità: codice, poi EAN, poi modello, poi prezzo, il primo che copre almeno il 60% del campo più denso. Il prezzo è l'ultima scelta perché è il campo che può mancare: ancorando sul prezzo, un articolo senza prezzo si fonde con quello sopra (c'è un test che lo dimostra). Il prezzo è quello che cade nell'estensione verticale dell'articolo: se ce ne sono due **non se ne sceglie uno**, si segnala, con la colonna che ha fallito.
- **In una corsa con più ancore si taglia nel distacco più ampio** fra due ancore, non con uno stacco fisso. Nel JBL fra EAN e nome successivo ci sono 14,5 pt contro 10,5 dentro l'articolo; con un fattore fisso 66 articoli su 673 si fondevano a coppie.
- **Un testo va alla colonna la cui etichetta gli si sovrappone di più** (`assegna_colonna`), e solo in mancanza alla colonna che comincia più vicino a sinistra. È ciò che legge le colonne allineate a destra: «1,249.50» comincia prima dell'etichetta «Price». Per lo stesso motivo il profilo salva `x_fine_relativo` per le colonne ricostruite senza intestazione.
- **Un'etichetta d'intestazione su due righe** («Prezzo al / Pubblico») si riconosce come seguito solo se è vicina, allineata **e dello stesso corpo**. Senza il controllo sul corpo, un titolo di sezione allineato alla prima colonna veniva assorbito nell'intestazione.
- **Testate e piedi non vanno elencati**: sono le righe ripetute alla stessa altezza su almeno metà delle pagine, nelle fasce alta e bassa (`firme_ripetute`, cifre normalizzate).
- **Una pagina può avere più intestazioni**, una per tabella (`rileva_intestazioni`). Si tolgono tutte dal corpo e fanno da taglio; quello che sta sopra la prima **non** si scarta, perché una tabella può proseguire dalla pagina precedente. Le etichette che non sono il nome di un campo, cioè marca e titolo della tabella, diventano la categoria e si abbinano alle colonne del profilo **per posizione** (`_per_posizione`). Per questo il wizard non le salva come intestazioni. «Listino» è un sinonimo di Prezzo: un titolo da solo non fa un'intestazione, servono due etichette riconosciute.
- **L'inizio di una colonna si ricalcola su ogni pagina dal testo** sotto la sua etichetta (`allinea_al_contenuto`), perché un titolo centrato comincia dopo il suo testo e perché nello stesso catalogo le sezioni hanno colonne in posizioni diverse. Per la stessa ragione la pre-analisi misura l'allineamento pagina per pagina.
- **Tre modi di dividere le altre colonne fra gli articoli**, scelti dai dati e non dal profilo:
  1. **Griglia fitta** (almeno una linea divisoria ogni due righe dell'ancora): ogni cella è un articolo (`celle`). Il bordo sfiora la cima del testo da sotto, quindi taglia una tolleranza più in alto.
  2. **Codice centrato** nella cella a interlinea uniforme (`e_centrata` → `fasce_centrate`): cella simmetrica attorno al codice.
  3. **Negli altri casi**: distacco più ampio dopo il punto medio fra due ancore, ma solo se il blocco sotto il taglio arriva all'ancora successiva (`fasce`).
- **Ancora Modello**: se nel documento almeno il 70% dei valori ha l'aspetto di un codice (`aspetto_codice`), le righe che non lo hanno non sono articoli. In griglia, una cella senza prezzo e senza codice non è un articolo.
- **Testo dal PDF**: `text_extractor` unisce gli span che si toccano (`_unisci_contigui`) e ricompone legature e glifi di Calibri scritti male da Acrobat Distiller («Ɵ»→ti, «Ʃ»→tt, «ƫ»→tti, «Ampliﬁ catore»). Senza, le descrizioni del catalogo Etabeta uscivano spezzate.
- **Il validatore segnala solo i campi che il profilo prevede**: su un listino senza colonna Modello, «Modello mancante» su ogni riga era rumore.
- **Le anomalie non si correggono mai in automatico.** Gli errori dell'estrazione stanno in `Articolo.note_estrazione` (per campo) e un intervento dell'utente sul campo li cancella (`Articolo.imposta`). Quelle del validatore stanno in `Articolo.anomalie` e si ricalcolano da zero dopo ogni modifica, perché i duplicati dipendono da tutte le righe. Non si scartano nemmeno i duplicati.
- **Tutto ciò che apre il PDF gira in un processo separato** (`processors/lavori.esegui`: estrazione, analisi del wizard, anteprima; lato interfaccia `gui/lavoro.LavoroInProcesso`, contesto `spawn`), non in un thread. PyMuPDF tiene il GIL durante l'analisi di ogni pagina: in un thread l'interfaccia restava ferma per tutto il lavoro (5 s su un PDF di 1.210 pagine). Ne seguono due obblighi: ogni script che apre una finestra deve avere la guardia `if __name__ == "__main__"`, e `main.py` chiama `multiprocessing.freeze_support()` per l'eseguibile. Si ridisegna solo l'ultimo avanzamento ricevuto, perché aggiornare a ogni pagina bloccava la finestra.
- **`get_text("dict")` va chiamato con `FLAG_TESTO`**, che esclude le immagini: di default porta con sé i byte di ogni immagine ed era il 75% del tempo di estrazione.
- **Percorsi** (`percorsi.py`): le risorse sono in sola lettura (`_MEIPASS` nell'eseguibile, che può stare in Program Files). Log e regole personali vanno in `%LOCALAPPDATA%\PDFListinoExtractor`, che aggiornamenti e disinstallazione non toccano. `config.carica_regole` unisce alle regole distribuite quelle di `%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json`, letto in `utf-8-sig` perché il Blocco note salva col BOM; se il file è illeggibile o non rispetta lo schema viene ignorato con un avviso e non blocca l'avvio. Un file nella versione 1 (formato della 1.0.0) si legge ancora. Il wizard e i pulsanti «Modifica…»/«Rinomina…»/«Rimuovi» accanto al menu Fornitore scrivono **solo** quel file (`config.salva_`/`rinomina_`/`rimuovi_fornitore_personale`, tutte via `_scrivi_personali`): schema verificato prima di toccare file e copia, file temporaneo + `os.replace`, copia `.bak`, `utf-8-sig`. Si rinominano e si rimuovono solo i fornitori personali (`config.chiavi_personali`); quelli distribuiti restano in sola lettura, e togliere un personale con la stessa chiave rimette in uso quello distribuito. Il nome deve restare unico, maiuscole a parte, perché menu e wizard riconoscono il fornitore dal nome.
- **Modificare un fornitore nel wizard** (`ModelloWizard.applica_profilo`): le colonne salvate si riabbinano a quelle trovate sulla pagina prima per etichetta, poi per posizione relativa (`abbina_colonne`, fasce contigue fra una colonna e la successiva: un `x_relativo` arrotondato per difetto cadeva fuori). La chiave resta la stessa anche cambiando nome. Al salvataggio `_con_originale` sovrappone la mappatura al profilo com'era: restano `escludi`, `prezzo_massimo`, le regex di EAN e prezzo, le spaziature, una regex del codice personalizzata e le intestazioni aggiunte a mano. Sul JBL, aprire il profilo e salvarlo senza toccare nulla dà gli stessi 673 articoli (`tests/test_universale.py`).
- **Versione**: l'unica fonte è `version.py`, letto dal titolo della finestra, dal `.spec` (proprietà dell'eseguibile) e da `build_installer.bat`. L'`AppId` in `installer/PDFListinoExtractor.iss` non va mai cambiato, o un aggiornamento verrebbe installato come un programma diverso. `[InstallDelete]` svuota `_internal` a ogni aggiornamento. `EDITORE` resta vuoto finché non se ne indica uno reale.
- **Formato dell'export**: il codice resta tra parentesi (`codice_con_parentesi`); Modello, Codice ed EAN sono celle di testo (`@`); un prezzo mancante è una cella vuota, non `0`. Dove la colonna Descrizione è vuota (accessori), la descrizione ripete il nome del modello.

## Test

`tests/sintetico.py` (impaginazione JBL), `tests/sintetico_generico.py` (layout opposto) e `tests/sintetico_catalogo.py` (catalogo Etabeta, con e senza griglia) generano PDF con i risultati attesi in `ATTESI`. Per un caso nuovo si aggiungono lì sia il contenuto della pagina sia il risultato atteso. Il font `helv` dei PDF sintetici non ha il «€»: scrivere «EUR». Per i test con Tk non serve un display virtuale su Windows. Una suite verde però non basta: il blocco dell'interfaccia, il problema del BOM, l'intestazione che assorbiva i titoli, il «Modello mancante» su ogni riga e tutti i difetti del catalogo Etabeta sono emersi solo provando l'applicazione vera o un PDF vero (`tools/prova_gui.py`, `tools/prova_wizard.py`, `--collaudo`, `--collaudo-wizard`, `tools/collaudo_installer.ps1`).

## Licenze

Il programma è **AGPL-3.0-or-later** (`LICENSE`, testo ufficiale preso da `gh api licenses/agpl-3.0`), perché PyMuPDF è AGPL. Il repository `PshowGit/PDFListinoExtractor` è pubblico ed è la fonte del sorgente a cui rimanda l'installer: una dipendenza nuova deve avere una licenza compatibile e va aggiunta a `installer/LICENZE_TERZE_PARTI.txt`.
