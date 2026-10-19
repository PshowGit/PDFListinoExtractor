# Estrattore listini PDF → Excel

Applicazione desktop (Python, customtkinter) che legge un listino prezzi PDF, ne estrae gli articoli
e li salva in un file Excel pronto all'uso. Il motore non contiene coordinate fisse: ricava colonne,
righe e articoli dalla geometria di ogni documento. Un fornitore nuovo si configura dal **wizard**,
senza toccare file. Il profilo incluso è quello del **listino JBL distribuito da Exhibo** («Listino
Gennaio 2026 — Prezzi al pubblico»).

## Cosa produce

Un file `.xlsx` con un solo foglio, **`Listino`**, con le colonne che il listino ha davvero, con i nomi
scelti nel wizard. Un catalogo con «Articolo | Descrizione | Listino» dà quelle tre colonne, senza Codice
né EAN vuoti; una colonna in più («Colore», «Note») esce col suo nome. Il profilo JBL incluso, e ogni
fornitore configurato prima delle colonne dinamiche, dà le cinque colonne di sempre:

| Modello | Codice | EAN | Descrizione | Prezzo |
|---|---|---|---|---:|
| CSA1120Z | (JBNCSA1120Z-U-EU) | 8710150083632 | Amplificatore JBL CSA1120Z 1 x 120W DriveCore… | 735,00 |

- **Modello, Codice, EAN** sono le tre righe della colonna «Modello» del PDF, in quest'ordine. Il codice
  resta tra parentesi, come nel listino (`"codice_con_parentesi": false` nella configurazione per toglierle).
  Sono celle di testo: zeri iniziali, punti e trattini restano com'erano.
- **Descrizione**: il testo della colonna Descrizione, con le righe ricomposte. Per gli accessori, dove
  la colonna è vuota e il nome sta tutto nella colonna Modello, si ripete il nome del modello.
- **Prezzo**: numero vero (non testo), formato `#,##0.00`. Se il prezzo manca resta vuoto, non `0`.
- Le colonne in più sono celle di testo.

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

Il file di regole personali lo scrive il wizard, nel formato di `config/supplier_rules.json` (schema
versione 2; un file della versione 1.0 si legge ancora e si converte al primo salvataggio). I fornitori che
contiene si aggiungono a quelli inclusi nel programma, o li sostituiscono se hanno la stessa chiave. Se il
file è illeggibile il programma lo segnala e parte con le regole incluse.

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

**Licenze.** Il programma è distribuito con licenza **GNU Affero General Public License v3.0 o successive**
([LICENSE](LICENSE)), la stessa di PyMuPDF, su cui si basa. Chi distribuisce l'eseguibile deve rendere
disponibile il sorgente alle stesse condizioni: è questo repository,
https://github.com/PshowGit/PDFListinoExtractor. Le altre dipendenze hanno licenze permissive (MIT, BSD,
Apache 2.0, PSF); l'elenco completo è in `installer\LICENZE_TERZE_PARTI.txt`, installato col programma insieme
alla licenza. Tesseract non è incluso: il listino JBL è testuale e non ne ha bisogno.

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

## Configurare un nuovo fornitore (wizard)

Nella finestra principale: **Configura nuovo fornitore…**

1. **Apri PDF…** e scegli una pagina rappresentativa (◀ ▶). La pre-analisi, eseguita in un processo separato,
   trova la riga d'intestazione e le colonne e le evidenzia sulla pagina, un colore per campo. Riconosce le
   intestazioni per sinonimi: «SKU», «Part Number», «Cod. art.» valgono come Codice. Se l'intestazione manca,
   ricostruisce le colonne dalla posizione del testo, con i prezzi allineati a destra trattati a parte.
2. Per ogni colonna il menu propone un campo, dedotto da intestazione e contenuto: Modello, Codice, EAN,
   Descrizione, Prezzo, *Modello + Codice + EAN impilati* nella stessa colonna (come nel listino JBL),
   *Testo* per una colonna in più, oppure *ignora*. Sotto il menu c'è il **nome della colonna** nella tabella
   e nell'Excel: l'intestazione del PDF se è il nome di quel campo («Articolo», «Listino», «Prezzo al
   Pubblico»), altrimenti il nome standard; si può cambiare. Un clic su una colonna della pagina evidenzia
   il suo menu.
3. **Ancora**: il campo su cui si individua ogni articolo. «Automatica» sceglie il campo identificativo più
   denso, nell'ordine codice, EAN, modello, prezzo. Il prezzo viene per ultimo di proposito: se l'ancora fosse
   il prezzo, un articolo senza prezzo si fonderebbe con quello sopra.
4. Formato dei prezzi, codici tra parentesi (nel PDF ed eventualmente nell'Excel), linee orizzontali come
   separatori, nome del fornitore.
5. **Anteprima pagina** estrae solo quella pagina e mostra la tabella con le anomalie. **Salva fornitore** lo
   aggiunge al menu «Fornitore» della finestra principale.

Il fornitore finisce in `%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json`. Il file è in UTF-8 con BOM
(si apre col Blocco note), viene scritto in modo atomico e validato con `config/supplier_rules.schema.json`;
la versione precedente resta in una copia `.bak`. Gli aggiornamenti del programma non lo toccano.

Accanto al menu «Fornitore»:

- **Modifica…** riapre il fornitore nel wizard: si apre un suo listino e la mappatura salvata viene riportata
  sulle colonne trovate (prima per intestazione, poi per posizione). Le colonne che non si ritrovano tengono la
  proposta dell'analisi e la riga di stato lo dice. «Salva modifiche» aggiorna lo stesso fornitore, anche se
  se ne cambia il nome, e conserva le regole che il wizard non mostra (esclusioni, prezzo massimo, regex).
- **Rinomina…** cambia il nome con cui compare il fornitore; le regole restano le stesse.
- **Rimuovi** lo toglie dal file personale.

Valgono solo per i fornitori configurati col wizard: il profilo distribuito col programma è in sola lettura e
per lui i tre pulsanti restano disattivati. Due fornitori non possono avere lo stesso nome.

## Come funziona il motore

Ogni soglia è ricavata dal documento: nessuna coordinata fissa. Dettagli e motivazioni in
[docs/progetto-estrazione-universale.md](docs/progetto-estrazione-universale.md).

- **Colonne**: dalla riga d'intestazione di ogni pagina, abbinata ai campi del profilo per etichetta o
  sinonimo. Un testo appartiene alla colonna la cui etichetta gli si sovrappone di più, ed è così che si
  leggono le colonne allineate a destra. Senza intestazione valgono le posizioni salvate nel profilo, in
  frazioni della larghezza pagina.
- **Testata e piè di pagina**: righe che si ripetono alla stessa altezza su almeno metà delle pagine (cifre
  escluse, quindi «Pagina 3 di 121» ≡ «Pagina 4 di 121»). Non vanno elencate.
- **Titoli di categoria**: corpo ≥ 1,3 volte il corpo mediano del documento. Chiudono l'articolo
  precedente e non entrano nei dati.
- **Articoli**: si individuano dalla colonna dell'ancora. Righe consecutive senza un distacco maggiore di
  1,5 volte la sua interlinea mediana formano una corsa. Una corsa con più ancore si taglia fra un'ancora e
  l'altra **nel distacco più ampio**: in una tabella a una riga per articolo è subito prima dell'ancora;
  nel listino JBL è fra l'EAN di un articolo e il nome del successivo.
- Il prezzo è quello nella colonna Prezzo dentro l'estensione verticale dell'articolo. Se ce n'è più di uno,
  il programma **non sceglie**: lascia il prezzo vuoto e segnala la riga, indicando la colonna.
- Una descrizione che prosegue in cima alla pagina successiva viene riattaccata all'articolo giusto.

Sul listino JBL il motore dà gli stessi 673 articoli del vecchio motore a coordinate fisse, identici campo
per campo. Li dà anche partendo dalla sola proposta automatica del wizard, senza il profilo scritto a mano.

### Anomalie segnalate (mai corrette in automatico)

Prezzo mancante, zero, ambiguo o fuori scala · più prezzi per lo stesso articolo · EAN con lunghezza o cifra
di controllo sbagliata · codice o modello mancante · testo con parentesi non chiusa (troncato già nel PDF) ·
codice duplicato (non viene eliminato: lo stesso articolo può comparire in due sezioni) · testo OCR con
confidenza bassa.

Sul listino di gennaio 2026 le segnalazioni sono 16, tutte reali: 6 prezzi a `0,00`, 6 EAN non validi
(dove al posto dell'EAN il PDF riporta altro, es. `PRX412M`), 4 testi troncati nel PDF stesso.

Per un caso che il wizard non copre, `uv run python tools/analizza_pdf.py "listino.pdf" 1,2` stampa ogni riga
di testo con posizione e corpo del carattere.

## Test

```powershell
uv run pytest -q          # 153 test; quello OCR si salta se Tesseract non è installato
uv run ruff check .
```

I test usano due PDF sintetici con risultati attesi noti. `tests/sintetico.py` imita l'impaginazione JBL;
`tests/sintetico_generico.py` è un layout opposto (SKU | Description | EAN | Price, formato inglese, una riga
per articolo), anche nella variante senza intestazione. Se presente usano anche il listino reale
`samples/Listino_JBL_Gen_2026.pdf`, con 673 articoli attesi. Collaudi sulla finestra vera:
`tools/prova_gui.py` (estrazione), `tools/prova_wizard.py` (wizard) e, sull'eseguibile,
`--collaudo` e `--collaudo-wizard <pdf> <regole.json>`.

## Struttura

```text
main.py                     avvio, log, messaggi d'errore anche senza console
version.py                  versione e identita' del programma (unica fonte)
percorsi.py                 risorse in sola lettura e dati utente in %LOCALAPPDATA%
PDFListinoExtractor.spec    compilazione PyInstaller
installer/                  script Inno Setup, LEGGIMI e licenze di terze parti installati col programma
scripts/                    build_exe.bat, build_installer.bat, imposta_versione.py
assets/icona.ico            icona (rigenerabile con tools/crea_icona.py)
docs/                       progetto del motore universale, report dei test di distribuzione
config/                     supplier_rules.json (regole distribuite) e supplier_rules.schema.json
extractors/                 pdf_reader (apertura e verifica), text_extractor (testo + coordinate),
                            table_extractor (geometria: statistiche, testate ripetute, intestazione,
                            colonne), ocr_extractor (Tesseract)
processors/                 raggruppamento (righe -> articoli), article_parser (campi), profilo (schema 2,
                            sinonimi), analisi_layout (pre-analisi del wizard), wizard (logica del wizard),
                            estrazione, lavori (processo separato), price_parser, data_validator, models
exporters/excel_exporter.py foglio Listino + report anomalie
gui/                        main_window, wizard_fornitore, lavoro (processo separato), preview_table,
                            page_viewer, collaudo (--collaudo, --collaudo-wizard)
tests/                      test automatici e generatore del PDF sintetico
tools/                      analisi di un PDF nuovo, misure, collaudo dell'interfaccia
```
