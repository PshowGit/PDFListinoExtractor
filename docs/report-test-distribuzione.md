# Report dei test di distribuzione — PDFListinoExtractor 1.0.0

Eseguiti il 16/10/2026 su Windows 10 Pro 22H2 (x64), con Python 3.12 presente sulla macchina di sviluppo.
Artefatti verificati: `dist\PDFListinoExtractor_Setup.exe` (28,9 MB) e
`dist\PDFListinoExtractor\PDFListinoExtractor.exe` (4,9 MB + `_internal`, 85 MB in tutto),
compilati con PyInstaller 6.22.3 e Inno Setup 6.

## Esito per punto richiesto

| # | Test | Esito | Come è stato verificato |
|---|---|---|---|
| 1 | Avvio su PC con Python installato | ✅ | eseguibile avviato su questa macchina; finestra «Estrattore listini PDF 1.0.0» |
| 2 | Avvio su Windows pulito senza Python | ⚠️ approssimato | **non c'è un secondo PC né una VM**, e Windows Sandbox non è attivo (attivarlo vuol dire cambiare impostazioni di sistema). Eseguibile lanciato con ambiente ripulito: `PATH` ridotto a `C:\Windows`, `PYTHONHOME`/`PYTHONPATH` su cartelle inesistenti → collaudo `ok`, 673 articoli. Le DLL caricate (`python312.dll`, `tcl86t.dll`, `tk86t.dll`, `mupdfcpp64.dll`) vengono tutte da `_internal`, e i runtime Microsoft (`VCRUNTIME140`, `MSVCP140`, `ucrtbase`) sono inclusi nel pacchetto |
| 3 | GUI senza console | ✅ | `console=False`; avviando l'eseguibile si apre solo la finestra, senza processi figli di console |
| 4 | Caricamento di un PDF | ✅ | `--collaudo` sul listino JBL di gennaio 2026 |
| 5 | Estrazione corretta | ✅ | 673 articoli, 16 da verificare: gli stessi numeri dell'esecuzione dal sorgente |
| 6 | Esportazione Excel | ✅ | 673 righe esportate, 673 righe nel file |
| 7 | Apertura e validità dell'Excel | ✅ | aperto in **Microsoft Excel** via COM: un foglio `Listino`, 5 colonne, prezzi numerici (`Double`, SOMMA = 1.498.201), filtro attivo, riquadri bloccati |
| 8 | Percorsi con spazi e accenti | ✅ | PDF in `D:\tmp\Prova spazi àèìòù\Listini fornitore\Listino JBL è gennaio.pdf`, export in `Uscita è.xlsx`, installazione in `D:\tmp\Installazione prova àèù\PDFListinoExtractor` |
| 9 | PDF non valido | ✅ | file di testo rinominato `.pdf` → messaggio «Il file non e' un PDF valido o e' danneggiato», nessun crash |
| 10 | Installazione tramite installer | ✅ | installazione silenziosa, codice 0 |
| 11 | Creazione dei collegamenti | ✅ | menu Start e desktop, entrambi puntano all'eseguibile installato |
| 12 | Avvio da menu Start e da desktop | ✅ | aperti i due `.lnk`, comparsa la finestra «Estrattore listini PDF 1.0.0» |
| 13 | Disinstallazione | ✅ | programma, collegamenti, cartella e voce in «App installate» rimossi; dati utente ed Excel esportati conservati |
| 14 | Aggiornamento da versione precedente | ✅ | 0.9.0 → 1.0.0: una sola voce in «App installate», stessa cartella, librerie vecchie rimosse, regole personali (stesso hash), Excel esportato e log conservati, regole personali lette dalla versione nuova |

I punti 10–14 sono automatizzati in `tools\collaudo_installer.ps1`: **21 controlli su 21 superati**
nell'ultima esecuzione, sugli artefatti finali.

## Limiti dichiarati

- **Installazione in Program Files non provata in automatico.** Il collaudo installa «solo per l'utente
  attuale», perché la modalità per tutti gli utenti chiede la conferma UAC, che solo una persona può dare.
  L'installer è lo stesso e cambia soltanto la cartella (`{autopf}`). La prima schermata della procedura
  guidata è stata verificata a schermo: è in italiano e offre le due modalità. Da provare a mano una volta:
  doppio clic sull'installer → *Installa per tutti gli utenti*.
- **Ambiente pulito approssimato** (punto 2): una macchina senza Python vera resta da provare.
- **OCR non incluso né provato**: Tesseract non è installato su questa macchina, e il listino del fornitore è
  testuale. Su un PDF scansionato il programma elenca le pagine che non ha potuto leggere.
- **Eseguibile non firmato**: SmartScreen può mostrare un avviso al primo avvio dell'installer.

## Difetti trovati dal collaudo e corretti

1. **Un file di regole personali salvato col BOM UTF-8 impediva l'avvio.** Lo salvano così sia il Blocco note
   sia PowerShell. Prima il programma si chiudeva all'avvio; ora il BOM viene accettato, e un file
   illeggibile viene ignorato con un avviso. Tre test nuovi in `tests/test_config.py`.
2. **Misura dei tempi della onefile sbagliata** (difetto del test, non del programma). In onefile la finestra
   appartiene a un processo figlio. Rimisurata: onefile ~3,3 s contro onedir ~1,1 s all'avvio.

## Licenze

Tutte permissive (MIT, BSD, Apache 2.0, MIT-CMU, PSF), salvo **PyMuPDF: AGPL-3.0** o licenza commerciale
Artifex. Per l'uso interno non ci sono obblighi aggiuntivi. Per distribuire fuori dall'organizzazione serve
rendere disponibile il sorgente oppure una licenza commerciale. Dettagli in
`installer\LICENZE_TERZE_PARTI.txt`.
