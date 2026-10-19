"""Logica del wizard «Configura nuovo fornitore», indipendente da Tk.

Tiene la mappatura colonna -> campo decisa dall'utente sopra l'analisi del layout, la valida e la
traduce in un profilo (schema 2). La finestra (gui/wizard_fornitore.py) e' solo il suo involucro:
cosi' la parte che decide cosa finisce nel file delle regole si prova senza aprire finestre.

Per modificare un fornitore gia' salvato, `applica_profilo` riporta la sua mappatura sulle colonne
trovate nella pagina analizzata; al salvataggio `profilo` conserva le regole che il wizard non mostra.
"""
from processors.analisi_layout import AnalisiLayout, profilo_da_analisi
from processors.profilo import CAMPI_ANCORA, REGEX_CODICE_PARENTESI, chiave_da_nome, normalizza, normalizza_testo

ETICHETTE_CAMPO = {
    "ignora": "— ignora —",
    "modello": "Modello",
    "codice": "Codice",
    "ean": "EAN",
    "descrizione": "Descrizione",
    "prezzo": "Prezzo",
    "identificativo": "Modello + Codice + EAN (impilati)",
}
ETICHETTE_ANCORA = {
    "auto": "Automatica (per densità)",
    "codice": "Codice",
    "ean": "EAN",
    "modello": "Modello",
    "prezzo": "Prezzo",
}
ETICHETTE_FORMATO = {"it": "Italiano (1.234,56)", "en": "Inglese (1,234.56)", "auto": "Automatico"}
COLORI_CAMPO = {
    "ignora": "#9E9E9E",
    "modello": "#1F77B4",
    "codice": "#9467BD",
    "ean": "#8C564B",
    "descrizione": "#2CA02C",
    "prezzo": "#D62728",
    "identificativo": "#FF7F0E",
}


def campi_di(campo_colonna: str) -> set[str]:
    return {"modello", "codice", "ean"} if campo_colonna == "identificativo" else {campo_colonna}


def abbina_colonne(analisi: AnalisiLayout, salvate: list[dict]) -> list[int | None]:
    """Per ogni colonna rilevata, l'indice della colonna salvata che le corrisponde (o None).

    Prima per etichetta d'intestazione, poi per posizione: la colonna salvata comincia dentro la fascia
    della colonna rilevata, che va dalla fine della precedente alla sua (la prima dal bordo sinistro):
    le fasce sono contigue, e un x_relativo arrotondato per difetto non cade fra due colonne. Fra piu'
    candidate vince la piu' vicina, e ogni colonna salvata si usa una volta sola. Le posizioni sono
    frazioni della larghezza.
    """
    abbinate: list[int | None] = [None] * len(analisi.colonne)
    libere = set(range(len(salvate)))
    for i, col in enumerate(analisi.colonne):
        if not col.da_intestazione:
            continue
        etichetta = normalizza_testo(col.etichetta)
        j = next((j for j in sorted(libere)
                  if any(normalizza_testo(t) == etichetta for t in salvate[j].get("intestazioni") or [])), None)
        if j is not None:
            abbinate[i] = j
            libere.discard(j)
    coppie = []
    for i, col in enumerate(analisi.colonne):
        inizio = 0.0 if i == 0 else analisi.colonne[i - 1].x1 / analisi.larghezza
        fine = col.x1 / analisi.larghezza
        for j in libere:
            x = salvate[j].get("x_relativo")
            if abbinate[i] is None and x is not None and inizio <= x <= fine:
                coppie.append((abs(x - col.x0 / analisi.larghezza), i, j))
    for _, i, j in sorted(coppie):
        if abbinate[i] is None and j in libere:
            abbinate[i] = j
            libere.discard(j)
    return abbinate


class ModelloWizard:
    def __init__(self, analisi: AnalisiLayout, fornitori_esistenti: dict[str, str] | None = None):
        self.analisi = analisi
        self.esistenti = dict(fornitori_esistenti or {})  # chiave -> nome
        self.campi = [c.campo_proposto for c in analisi.colonne]
        self.ancora = analisi.ancora_proposta if analisi.ancora_proposta in CAMPI_ANCORA else "auto"
        self.formato_prezzo = analisi.formato_prezzo_proposto
        self.codici_tra_parentesi = analisi.regex_codice_proposta is not None  # come sono scritti nel PDF
        self.codice_con_parentesi = True  # se tenerle nell'Excel
        self.linee_divisorie = analisi.linee_divisorie_proposte
        self.nome = ""
        # solo modificando un fornitore salvato: la sua chiave, il profilo com'era e, per colonna, la voce
        # salvata che le corrisponde
        self.chiave_fissa: str | None = None
        self.originale: dict | None = None
        self.origine: list[dict | None] = [None] * len(self.campi)

    def applica_profilo(self, chiave: str, profilo: dict) -> int:
        """Riprende un fornitore salvato per modificarlo; restituisce quante colonne ha ritrovato.

        Le colonne che non corrispondono a nessuna di quelle salvate tengono la proposta dell'analisi.
        """
        effettivo = normalizza(profilo)  # i valori predefiniti di cio' che il file non dice
        self.chiave_fissa, self.originale = chiave, profilo
        self.nome = profilo.get("nome", "")
        salvate = profilo.get("colonne", [])
        self.origine = [None if j is None else salvate[j] for j in abbina_colonne(self.analisi, salvate)]
        for i, voce in enumerate(self.origine):
            if voce is not None and voce["campo"] in ETICHETTE_CAMPO:
                self.campi[i] = voce["campo"]
        self.ancora = effettivo["ancora"] if effettivo["ancora"] in ETICHETTE_ANCORA else "auto"
        self.formato_prezzo = effettivo["formato_prezzo"]
        self.codici_tra_parentesi = effettivo["regex"].get("codice") is not None
        self.codice_con_parentesi = effettivo["codice_con_parentesi"]
        self.linee_divisorie = effettivo["spaziatura"]["linee_divisorie"]
        return sum(v is not None for v in self.origine)

    def imposta_campo(self, indice: int, campo: str) -> None:
        if campo not in ETICHETTE_CAMPO:
            raise ValueError(f"Campo sconosciuto: {campo}")
        self.campi[indice] = campo

    def campi_mappati(self) -> set[str]:
        return set().union(*(campi_di(c) for c in self.campi if c != "ignora")) if self.campi else set()

    def chiave(self) -> str:
        """Riusa la chiave di un fornitore con lo stesso nome (lo sostituisce), altrimenti ne crea una nuova.

        Modificando un fornitore la chiave resta la sua, anche se cambia il nome.
        """
        if self.chiave_fissa:
            return self.chiave_fissa
        for chiave, nome in self.esistenti.items():
            if nome.strip().lower() == self.nome.strip().lower():
                return chiave
        return chiave_da_nome(self.nome, set(self.esistenti))

    def sostituisce_esistente(self) -> bool:
        """Se il salvataggio sovrascrive un altro fornitore (da confermare); non vale modificandone uno."""
        return self.chiave_fissa is None and self.chiave() in self.esistenti

    def errori(self) -> list[str]:
        e = []
        if not self.nome.strip():
            e.append("Indicare il nome del fornitore.")
        elif self.chiave_fissa and any(
            k != self.chiave_fissa and n.strip().lower() == self.nome.strip().lower() for k, n in self.esistenti.items()
        ):
            e.append(f"Esiste gia' un fornitore «{self.nome.strip()}»: scegliere un altro nome.")
        mappati = self.campi_mappati()
        if not mappati:
            e.append("Associare almeno una colonna a un campo.")
        if not mappati & {"codice", "modello", "ean"}:
            e.append("Serve almeno una colonna che identifichi l'articolo (Codice, Modello o EAN).")
        if self.ancora != "auto" and self.ancora not in mappati:
            e.append(f"L'ancora «{ETICHETTE_ANCORA[self.ancora]}» non corrisponde a nessuna colonna associata.")
        for campo in ("descrizione", "prezzo"):
            if sum(1 for c in self.campi if c == campo) > 1:
                e.append(f"Il campo {ETICHETTE_CAMPO[campo]} e' associato a piu' colonne: sceglierne una.")
        if "identificativo" in self.campi and not self.codici_tra_parentesi:
            e.append("La colonna «Modello + Codice + EAN» richiede codici scritti tra parentesi: e' cio' che separa"
                     " il codice dal nome.")
        return e

    def profilo(self) -> dict:
        nuovo = profilo_da_analisi(
            self.analisi,
            self.campi,
            nome=self.nome.strip() or "Nuovo fornitore",
            ancora=self.ancora,
            formato_prezzo=self.formato_prezzo,
            codice_con_parentesi=self.codice_con_parentesi,
            linee=self.linee_divisorie,
            codici_tra_parentesi=self.codici_tra_parentesi,
        )
        return nuovo if self.originale is None else self._con_originale(nuovo)

    def _con_originale(self, nuovo: dict) -> dict:
        """Il profilo modificato sopra quello salvato: restano le regole che il wizard non mostra
        (esclusioni, prezzo massimo, regex di EAN e prezzo, spaziature) e le intestazioni aggiunte."""
        orig = self.originale
        out = {**orig, **{k: v for k, v in nuovo.items() if k not in ("spaziatura", "regex")}}
        out["spaziatura"] = {**orig.get("spaziatura", {}), **nuovo["spaziatura"]}
        regex = dict(orig.get("regex") or {})
        # una regex del codice personalizzata resta finche' si dice che i codici sono tra parentesi
        regex["codice"] = (regex.get("codice") or REGEX_CODICE_PARENTESI) if self.codici_tra_parentesi else None
        out["regex"] = regex
        for voce, salvata in zip(out["colonne"], self.origine, strict=True):
            if salvata is None or salvata["campo"] != voce["campo"]:
                continue
            voce["intestazioni"] = list(dict.fromkeys((salvata.get("intestazioni") or []) + voce["intestazioni"]))
            if voce["campo"] == "identificativo" and salvata.get("contiene"):
                voce["contiene"] = list(salvata["contiene"])
        return out
