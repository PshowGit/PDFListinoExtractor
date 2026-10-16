# Estrattore listini PDF → Excel

Applicazione desktop (Python, customtkinter) che legge un listino prezzi PDF, ne estrae gli articoli
e li salva in un file Excel pronto all'uso. È ottimizzata per il **listino JBL distribuito da Exhibo**
(«Listino Gennaio 2026 — Prezzi al pubblico»), ma le regole di lettura stanno in un file di
configurazione e si possono adattare ad altri fornitori.

## Cosa produce

Un file `.xlsx` con un solo foglio, **`Listino`**, e cinque colonne:

| Modello | Codice | EAN | Descrizione | Prezzo |
|---|---|---|---|---:|
| CSA1120Z | (JBNCSA1120Z-U-EU) | 8710150083632 | Amplificatore JBL CSA1120Z 1 x 120W DriveCore… | 735,00 |

- **Modello, Codice, EAN** sono le tre righe della colonna «Modello» del PDF, in quest'ordine. Il codice
  resta tra parentesi, come nel listino (`"codice_con_parentesi": false` nella configurazione per toglierle).
  Sono celle di testo: zeri iniziali, punti e trattini restano com'erano.
- **Descrizione**: il testo della colonna Descrizione, con le righe ricomposte. Per gli accessori, dove
  la colonna è vuota e il nome sta tutto nella colonna Modello, si ripete il nome del modello.
- **Prezzo**: numero vero (non testo), formato `#,##0.00`. Se il prezzo manca resta vuoto, non `0`.

Intestazioni in grassetto, filtri automatici, prima riga bloccata, descrizione con testo a capo.
Nessuna colonna tecnica: le anomalie si vedono nell'anteprima e si possono salvare in un **report separato**.

## Installazione per l'utente finale (senza Python)

1. Eseguire `PDFListinoExtractor_Setup.exe`. Il programma **non è firmato digitalmente**: Windows
   SmartScreen può mostrare «PC protetto da Windows» → *Ulteriori informazioni* → *Esegui comunque*.
2. Scegliere **Installa per tutti gli utenti** (in `C:\Program Files\PDFListinoExtractor`, chiede la conferma
   di amministratore) oppure **solo per l'utente attuale** (in `%LOCALAPPDATA%\Programs`, senza privilegi).
3. Scegliere la cartella e, se si vuole, il collegamento sul desktop. Il collegamento nel menu Start
   viene sempre creato.

**Aggiornamento**: eseguire l'installer della versione nuova. Riconosce quella già installata, usa la stessa
cartella e sostituisce interamente le librerie. Se il programma è aperto, propone di chiuderlo.

**Disinstallazione**: *Impostazioni → App → PDFListinoExtractor → Disinstalla*. Rimuove programma,
collegamenti e voce in «App installate».

Aggiornamento e disinstallazione **non toccano i dati dell'utente**:

| Cosa | Dove |
|---|---|
| Log degli errori | `%LOCALAPPDATA%\PDFListinoExtractor\logs\app.log` |
| Regole personali (facoltative) | `%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json` |
| File Excel esportati | dove li ha salvati l'utente |

Il file di regole personali ha la stessa forma di `config/supplier_rules.json`. I fornitori che contiene si
aggiungono a quelli inclusi nel programma, o li sostituiscono se hanno la stessa chiave. Se il file è
illeggibile il programma lo segnala e parte con le regole incluse.

## Compilare eseguibile e installer

Servono [uv](https://docs.astral.sh/uv/) e [Inno Setup 6](https://jrsoftware.org/isdl.php) (lo script
lo trova sia nell'installazione per utente sia in quella per tutti gli utenti).

```bat
scripts\build_exe.bat          rem dipendenze, test, PyInstaller -> dist\PDFListinoExtractor\PDFListinoExtractor.exe
scripts\build_installer.bat    rem Inno Setup -> dist\PDFListinoExtractor_Setup.exe
```

Entrambi si fermano con un messaggio e un codice di uscita diverso da 0 se un passo fallisce, e
`build_exe.bat` non compila se i test non passano.

**Nuova versione**: la versione sta solo in `version.py`. La leggono il titolo della finestra, le proprietà
dell'eseguibile e l'installer.

```bat
uv run python scripts\imposta_versione.py 1.1.0
scripts\build_exe.bat && scripts\build_installer.bat
```

L'`AppId` in `installer\PDFListinoExtractor.iss` non va mai cambiato: è ciò che fa riconoscere
all'installer la versione già presente. L'editore va indicato in `version.py` (`EDITORE`), ed è vuoto finché
non se ne indica uno reale.

**onedir o onefile.** Si distribuisce la modalità *onedir* dentro l'installer. Misurata sullo stesso PC, la
*onefile* parte in ~3,3 s contro ~1,1 s, perché a ogni avvio si scompatta in una cartella temporanea su C:,
e se viene chiusa a forza lascia lì i suoi residui. L'installer dà già all'utente un file unico. Per
riprodurre il confronto: `set PDFLISTINO_ONEFILE=1` prima di `uv run pyinstaller PDFListinoExtractor.spec`.

**Collaudo dell'eseguibile**: `PDFListinoExtractor.exe --collaudo <pdf> <file.xlsx>` apre la finestra vera,
estrae, esporta e scrive accanto all'Excel un report `.collaudo.json` e uno screenshot. Il collaudo completo
di installazione, aggiornamento e disinstallazione è `tools\collaudo_installer.ps1` (v.
[docs/report-test-distribuzione.md](docs/report-test-distribuzione.md)).

**Licenze.** Tutte le dipendenze sono permissive, salvo **PyMuPDF, che è AGPL-3.0** (o licenza commerciale
Artifex). Per l'uso interno non ci sono obblighi aggiuntivi. Distribuire il programma *fuori*
dall'organizzazione obbliga a rendere disponibile il sorgente, oppure richiede la licenza commerciale. Elenco
completo in `installer\LICENZE_TERZE_PARTI.txt`, installato insieme al programma. Tesseract non è incluso:
il listino JBL è testuale e non ne ha bisogno.

## Installazione per lo sviluppo

Serve Python 3.12. Con [uv](https://docs.astral.sh/uv/) (consigliato):

```powershell
cd D:\Programmi\PDFListinoExtractor
uv sync
```

In alternativa con pip: `python -m venv .venv`, poi `.venv\Scripts\pip install -r requirements.txt`.

**OCR (facoltativo)**: serve solo per i PDF scansionati. Installare
[Tesseract-OCR per Windows](https://github.com/UB-Mannheim/tesseract/wiki) nel percorso predefinito
(`C:\Program Files\Tesseract-OCR`), con la lingua italiana. Senza Tesseract il programma funziona lo stesso
sui PDF testuali e, su quelli scansionati, dice quali pagine non ha potuto leggere.

## Avvio

```powershell
uv run python main.py
```

1. **Seleziona PDF**: il programma controlla che il file sia un PDF leggibile e indica il numero di pagine
   e se è testuale o scansionato.
2. **Estrai articoli**: l'estrazione gira in un processo separato, quindi la finestra resta utilizzabile;
   si può annullare.
3. **Anteprima**: le righe con anomalie sono evidenziate in arancione (spunta «Solo righe con anomalie»
   per vedere solo quelle). Si può:
   - ordinare cliccando sull'intestazione di una colonna;
   - correggere con un doppio clic su una cella (la descrizione si apre in una finestra);
   - eliminare le righe selezionate (tasto `Canc` o pulsante);
   - aprire la pagina di origine con l'articolo evidenziato (**Mostra pagina PDF**).
4. **Esporta in Excel**: si sceglie nome e cartella, con conferma prima di sovrascrivere. Viene esportato
   esattamente ciò che è in tabella, filtro escluso.

Il PDF originale viene solo letto, mai modificato. Gli errori tecnici finiscono in `logs/app.log` quando si
lavora dal sorgente, in `%LOCALAPPDATA%\PDFListinoExtractor\logs\app.log` nel programma installato.

## Come legge il listino JBL/Exhibo

Regole ricavate dal listino di gennaio 2026 (121 pagine, 673 articoli):

- PDF testuale, tre colonne a coordinate fisse. Le posizioni si leggono a ogni pagina dall'intestazione
  «Modello / Descrizione / Prezzo al Pubblico»; se l'intestazione manca si usano quelle della configurazione.
- Intestazione ripetuta (y < ~160), piè di pagina Exhibo e «Pagina N di 121» (y > 780) vengono scartati.
- I titoli di categoria (corpo ≥ 10, es. «Amplificatori») chiudono l'articolo precedente e non entrano nei dati.
- Un articolo è un **blocco di righe ravvicinate nella colonna Modello**: nome (una o più righe), codice tra
  parentesi, EAN facoltativo. L'articolo si individua da qui e non dal prezzo: se un prezzo mancasse,
  l'articolo verrebbe segnalato invece di fondersi con il successivo.
- Il prezzo è quello nella colonna Prezzo dentro l'estensione verticale dell'articolo. Se ce n'è più di uno,
  il programma **non sceglie**: lascia il prezzo vuoto e segnala la riga.
- Una descrizione che prosegue in cima alla pagina successiva viene riattaccata all'articolo giusto.

### Anomalie segnalate (mai corrette in automatico)

Prezzo mancante, zero, ambiguo o fuori scala · più prezzi per lo stesso articolo · EAN con lunghezza o cifra
di controllo sbagliata · codice o modello mancante · testo con parentesi non chiusa (troncato già nel PDF) ·
codice duplicato (non viene eliminato: lo stesso articolo può comparire in due sezioni) · testo OCR con
confidenza bassa.

Sul listino di gennaio 2026 le segnalazioni sono 16, tutte reali: 6 prezzi a `0,00`, 6 EAN non validi
(dove al posto dell'EAN il PDF riporta altro, es. `PRX412M`), 4 testi troncati nel PDF stesso.

## Un altro fornitore

Aggiungere un profilo in `config/supplier_rules.json` (copiando `jbl_exhibo`) e regolare le coordinate.
Per ricavarle:

```powershell
uv run python tools/analizza_pdf.py "percorso\listino.pdf" 1,2
```

stampa ogni riga di testo con posizione e corpo del carattere. Il profilo compare nel menu «Fornitore».

## Test

```powershell
uv run pytest -q          # 66 test; quello OCR si salta se Tesseract non è installato
uv run ruff check .
```

I test usano un PDF sintetico con risultati attesi noti (`tests/sintetico.py`, copia in
`samples/listino_sintetico.pdf`) e, se presente, il listino reale `samples/Listino_JBL_Gen_2026.pdf`
(673 articoli attesi). `tools/prova_gui.py` è il collaudo dell'interfaccia: avvia la finestra vera, estrae,
cattura uno screenshot, esporta e misura la reattività durante il lavoro.

## Struttura

```text
main.py                     avvio, log, messaggi d'errore anche senza console
version.py                  versione e identita' del programma (unica fonte)
percorsi.py                 risorse in sola lettura e dati utente in %LOCALAPPDATA%
PDFListinoExtractor.spec    compilazione PyInstaller
installer/                  script Inno Setup, LEGGIMI e licenze di terze parti installati col programma
scripts/                    build_exe.bat, build_installer.bat, imposta_versione.py
assets/icona.ico            icona (rigenerabile con tools/crea_icona.py)
docs/                       report dei test di distribuzione
config/supplier_rules.json  regole per fornitore
extractors/                 pdf_reader (apertura e verifica), text_extractor (testo + coordinate),
                            table_extractor (colonne, area utile, righe), ocr_extractor (Tesseract)
processors/                 article_parser (articoli), price_parser (prezzi), data_validator (anomalie),
                            estrazione (flusso completo, anche in processo separato), models
exporters/excel_exporter.py foglio Listino + report anomalie
gui/                        main_window, preview_table, page_viewer, collaudo (--collaudo)
tests/                      test automatici e generatore del PDF sintetico
tools/                      analisi di un PDF nuovo, misure, collaudo dell'interfaccia
```
