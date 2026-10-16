"""Logica del wizard «Configura nuovo fornitore», indipendente da Tk.

Tiene la mappatura colonna -> campo decisa dall'utente sopra l'analisi del layout, la valida e la
traduce in un profilo (schema 2). La finestra (gui/wizard_fornitore.py) e' solo il suo involucro:
cosi' la parte che decide cosa finisce nel file delle regole si prova senza aprire finestre.
"""
from processors.analisi_layout import AnalisiLayout, profilo_da_analisi
from processors.profilo import CAMPI_ANCORA, chiave_da_nome

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

    def imposta_campo(self, indice: int, campo: str) -> None:
        if campo not in ETICHETTE_CAMPO:
            raise ValueError(f"Campo sconosciuto: {campo}")
        self.campi[indice] = campo

    def campi_mappati(self) -> set[str]:
        return set().union(*(campi_di(c) for c in self.campi if c != "ignora")) if self.campi else set()

    def chiave(self) -> str:
        """Riusa la chiave di un fornitore con lo stesso nome (lo sostituisce), altrimenti ne crea una nuova."""
        for chiave, nome in self.esistenti.items():
            if nome.strip().lower() == self.nome.strip().lower():
                return chiave
        return chiave_da_nome(self.nome, set(self.esistenti))

    def sostituisce_esistente(self) -> bool:
        return self.chiave() in self.esistenti

    def errori(self) -> list[str]:
        e = []
        if not self.nome.strip():
            e.append("Indicare il nome del fornitore.")
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
        return profilo_da_analisi(
            self.analisi,
            self.campi,
            nome=self.nome.strip() or "Nuovo fornitore",
            ancora=self.ancora,
            formato_prezzo=self.formato_prezzo,
            codice_con_parentesi=self.codice_con_parentesi,
            linee=self.linee_divisorie,
            codici_tra_parentesi=self.codici_tra_parentesi,
        )
