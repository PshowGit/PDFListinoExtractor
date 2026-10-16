# Estrazione universale e wizard di mappatura — progetto

Stato: implementato sul ramo `feat/estrazione-universale`. Il listino JBL/Exhibo è il caso di non regressione:
dopo il cambio di motore deve dare gli stessi 673 articoli, uguali campo per campo.

## 1. Piano architetturale: dalle coordinate fisse alla geometria del documento

Oggi il profilo JBL contiene numeri assoluti (`colonne_predefinite` x=102/202/467, `area` y=160–780, `soglia_titolo`
10 pt, `distanza_blocco` 14 pt, tre regex di piè di pagina). Valgono solo per quel PDF. Il nuovo motore ricava ogni
soglia **dal documento stesso** e il profilo conserva soltanto ciò che è davvero una scelta: quale colonna contiene
quale campo.

| Prima (fisso) | Dopo (ricavato dal documento) |
|---|---|
| `area.y_min` / `y_max` | inizio del corpo = sotto la **riga d'intestazione** riconosciuta a ogni pagina; testata e piede = **righe che si ripetono** alla stessa altezza su almeno metà delle pagine (cifre normalizzate: «Pagina 3 di 121» ≡ «Pagina 4 di 121») |
| `piede_pagina`, `testi_intestazione` | come sopra; `escludi` resta per i casi che la ripetizione non coglie |
| `colonne_predefinite` (pt assoluti) | x delle etichette d'intestazione, abbinate ai campi per **sinonimi** («SKU», «Part Number» → Codice); se manca l'intestazione, `x_relativo` = frazione della larghezza pagina |
| `soglia_titolo` = 10 pt | titolo = corpo ≥ `fattore_titolo` × corpo mediano del documento |
| `distanza_blocco` = 14 pt | stacco fra articoli = distacco > `fattore_stacco` × interlinea mediana della colonna d'ancoraggio |
| `tolleranza_riga` = 2,5 pt | 0,4 × corpo mediano |
| ancora = colonna Modello | ancora = **campo scelto o dedotto per densità** (sotto) |

### Perché non DBSCAN

Il clustering spaziale porterebbe nell'installer scikit-learn e SciPy (oltre 100 MB, più dell'intero programma),
e il suo parametro `eps` è a sua volta una distanza fissa: si sposterebbe il numero magico, non lo si eliminerebbe.
Un listino è una tabella: struttura per **colonne** (allineamento orizzontale) e per **righe** (passo verticale).
Due statistiche robuste del documento, l'interlinea mediana e il corpo mediano, bastano a tarare ogni soglia, e
il risultato resta spiegabile riga per riga a chi deve verificarlo.

### Raggruppamento in articoli (`processors/raggruppamento.py`)

1. **Righe visive**: spans della stessa colonna con y entro 0,4 × corpo mediano.
2. **Ancora**: il campo che identifica un articolo. Se il profilo non lo fissa, si deduce per densità: fra i campi
   identificativi (in quest'ordine: codice, EAN, modello, prezzo) si sceglie il primo le cui righe *valide* (codice
   che rispetta la sua regex, EAN con cifra di controllo, prezzo leggibile) sono almeno il 60% di quelle del campo
   più denso. La descrizione non è mai ancora: va a capo per costruzione. Il prezzo è l'ultima scelta, perché è
   proprio il campo che può mancare; ancorare sul codice fa sì che un prezzo mancante diventi un'anomalia invece
   di fondere due articoli.
3. **Corse**: le righe della colonna d'ancoraggio si spezzano in corse dove il distacco supera
   `fattore_stacco` × interlinea. In una corsa con una sola ancora, l'intera corsa è un articolo (JBL: nome su più
   righe, codice, EAN). In una corsa con più ancore (tabella a una riga per articolo) si taglia a ogni ancora;
   le righe prima della prima ancora vanno alla prima.
4. **Estensione verticale**: un articolo va dalla prima riga della sua corsa all'inizio dell'articolo
   successivo, o al primo titolo o linea divisoria che incontra. Le righe delle altre colonne in quella fascia gli
   appartengono.
5. **Prosecuzione**: il testo in cima a una pagina, prima del primo articolo, prosegue l'ultimo articolo della
   pagina precedente.

### Anomalie per colonna

`note_estrazione` resta per campo e continua a non correggere nulla, ma ora dice **quale colonna fisica** ha
fallito e con quale testo, es. *«Prezzo (colonna «Price», x≈480): «su richiesta» non riconosciuto»*. La
modifica dell'utente cancella la nota del campo, come prima.

### Un processo per ogni lavoro pesante

Pre-analisi del wizard, anteprima su una pagina ed estrazione completa passano tutte da
`processors/lavori.py`, nello stesso processo separato (`spawn`) che già evita il blocco del GIL. Lato interfaccia
c'è un solo involucro, `gui/lavoro.py`.

## 2. Schema JSON di `supplier_rules.json` (versione 2)

Lo schema formale è `config/supplier_rules.schema.json` (JSON Schema draft 2020-12): viene applicato al caricamento
e prima di ogni salvataggio. Esempio, che è il profilo JBL distribuito:

```json
{
  "versione_schema": 2,
  "predefinito": "jbl_exhibo",
  "fornitori": {
    "jbl_exhibo": {
      "nome": "JBL (Exhibo) - Listino al pubblico",
      "colonne": [
        {"campo": "identificativo", "intestazioni": ["Modello"], "x_relativo": 0.1714,
         "contiene": ["modello", "codice", "ean"]},
        {"campo": "descrizione", "intestazioni": ["Descrizione"], "x_relativo": 0.3395},
        {"campo": "prezzo", "intestazioni": ["Prezzo al", "Prezzo al Pubblico"], "x_relativo": 0.7849}
      ],
      "ancora": "codice",
      "spaziatura": {"tolleranza_colonna_pt": 6, "fattore_stacco": 1.5, "fattore_titolo": 1.3,
                     "linee_divisorie": false},
      "regex": {"codice": "^\\((?P<valore>[^()]+)\\)$", "ean": "^\\d{8,14}$", "prezzo": null},
      "formato_prezzo": "it",
      "codice_con_parentesi": true,
      "descrizione_vuota_usa_modello": true,
      "escludi": [],
      "prezzo_massimo": 1000000,
      "ocr": {"caratteri_minimi_pagina": 20, "dpi": 300, "lingua": "ita+eng", "confidenza_minima": 70}
    }
  }
}
```

| Chiave | Significato |
|---|---|
| `colonne[].campo` | `modello`, `codice`, `ean`, `descrizione`, `prezzo`, `identificativo` (più campi impilati nella stessa colonna, nell'ordine di `contiene`) oppure `ignora` |
| `colonne[].intestazioni` | etichette che riconoscono la colonna nella riga d'intestazione, oltre ai sinonimi predefiniti del campo |
| `colonne[].x_relativo` | inizio della colonna come frazione della larghezza pagina, usato quando l'intestazione non c'è |
| `ancora` | `auto` oppure il campo su cui si individua l'articolo |
| `spaziatura.*` | moltiplicatori delle statistiche del documento, non distanze; `linee_divisorie` usa le righe orizzontali disegnate nel PDF come separatori fra articoli |
| `regex.codice` / `regex.ean` | riconoscono il campo in una colonna `identificativo` e lo validano in una colonna semplice; il gruppo `valore`, se presente, è la parte da tenere |
| `regex.prezzo` | facoltativa: estrae il prezzo da un testo più lungo (gruppo `valore`), prima della normalizzazione |
| `sinonimi` (radice, facoltativa) | sinonimi aggiuntivi per campo, che si sommano a quelli predefiniti |

**Compatibilità.** Un file nella versione 1 (quello di prima, con `intestazioni` come dizionario e
`colonne_predefinite`) si converte in memoria al caricamento e si riscrive in versione 2 soltanto al primo
salvataggio dal wizard, conservandone una copia `.bak`.

**Dove si salva.** Il wizard scrive soltanto `%LOCALAPPDATA%\PDFListinoExtractor\supplier_rules.json`, in
`utf-8-sig`, attraverso un file temporaneo e una sostituzione atomica: un'interruzione non lascia un file a metà.
Le regole distribuite col programma non si toccano mai, quindi un aggiornamento non sovrascrive i fornitori
dell'utente. Un fornitore personale con la stessa chiave di uno distribuito lo sostituisce.

## 3. Wizard «Configura nuovo fornitore» (`gui/wizard_fornitore.py`)

1. Apri PDF e scegli la pagina (◀ ▶). La pagina viene disegnata in un riquadro scorrevole con zoom.
2. La pre-analisi, eseguita nel processo separato, trova la riga d'intestazione e le colonne: dall'intestazione
   se c'è, altrimenti raggruppando gli inizi di riga, con le colonne di prezzi allineati a destra riconosciute a
   parte. Le colonne compaiono evidenziate a colori sulla pagina.
3. Per ogni colonna, un `CTkOptionMenu` col campo proposto, dedotto da intestazione e contenuto.
4. `CTkOptionMenu` dell'ancora (proposta per densità), formato prezzi, codice tra parentesi, linee divisorie.
5. «Anteprima»: estrae solo la pagina scelta, nel processo separato, e mostra la tabella di prova con le anomalie.
6. «Salva fornitore»: valida (nome, almeno un campo identificativo, ancora mappata), salva e rende il fornitore
   subito disponibile nella finestra principale.

La logica del wizard (`processors/wizard.py`, classe `ModelloWizard`) non dipende da Tk e si prova senza finestra.

## 4. Verifiche

| Prova | Esito |
|---|---|
| Listino JBL reale col profilo distribuito (schema 2, senza coordinate) | 673 articoli, **0 differenze** campo per campo e anomalia per anomalia rispetto al motore a coordinate fisse |
| Listino JBL reale con la **sola proposta del wizard** (pagina 1, nessuna correzione), con e senza linee divisorie | 673 articoli, 0 differenze |
| Layout generico (SKU / Description / EAN / Price, formato inglese, una riga per articolo) | 8/8 articoli corretti, ancora dedotta sul codice, testata e piede ripetuti tolti senza regole |
| Stesso layout **senza riga d'intestazione** | 8/8, colonne ricostruite dalla posizione del testo |
| Wizard vero sul PDF generico e sul JBL (pagina 27): analisi + anteprima nel processo separato | 0,7 s e 0,9 s; mappatura proposta corretta in entrambi i casi |
| Wizard **nell'eseguibile impacchettato** (`--collaudo-wizard`, percorso con accenti) | analisi, anteprima, salvataggio in `utf-8-sig` validato dallo schema, 8 articoli dal profilo salvato |
| Aggiornamento dall'installer 1.0.0 al 1.1.0 (`tools/collaudo_installer.ps1`) | 21/21; regole personali nel formato 1.0 conservate e lette dalla 1.1 |

Difetti trovati solo provando, e corretti:

1. **Stacco fisso fra articoli**: 66 articoli JBL su 673 si fondevano a coppie, perché fra un articolo e
   l'altro in alcune pagine ci sono 14,5 pt contro 10,5. Ora si taglia nel distacco più ampio fra due ancore.
2. **Colonne allineate a destra**: col criterio «inizio della colonna» un prezzo lungo finiva nella colonna
   accanto. Ora conta la sovrapposizione con l'etichetta, e senza intestazione il profilo salva anche la fine
   della colonna.
3. **Titolo assorbito dall'intestazione**: la regola delle etichette su due righe prendeva un titolo di
   sezione allineato alla prima colonna. Ora serve anche lo stesso corpo.
4. **Interlinea misurata male** (23,7 pt su righe a 11): mescolava colonne diverse. Ora si misura fra righe
   che iniziano alla stessa x.
5. **«Modello mancante» su ogni riga** di un listino senza colonna Modello: ora il validatore segnala solo
   i campi previsti dal profilo.

Limiti dichiarati:

- La pre-analisi lavora su testo selezionabile. Su una pagina scansionata il wizard lo dice e non propone
  nulla, anche se l'estrazione con un profilo già fatto passa comunque dall'OCR.
- Un listino con l'**ancora sul modello in una colonna semplice** tratta ogni riga come un articolo: i nomi
  su due righe vanno mappati su una colonna composita, o ancorati a un altro campo.
- Una corsa con più ancore e distacchi tutti uguali (nome del successivo attaccato all'EAN precedente,
  senza spazio in più) assegna le righe all'ancora precedente: l'anteprima lo mostra prima di salvare.
