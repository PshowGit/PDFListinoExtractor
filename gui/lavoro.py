"""Un lavoro nel processo separato, visto dall'interfaccia: avvio, avanzamento, esito, annullamento.

Il processo e' `spawn` (v. processors/lavori.py per il perche'). L'interfaccia non attende mai:
legge la coda ogni INTERVALLO_MS con `after`. Di un avanzamento si ridisegna solo l'ultimo
arrivato, perche' aggiornare la barra per ogni pagina in coda bloccava la finestra fino a 300 ms.
"""
import logging
import multiprocessing
import queue
from collections.abc import Callable

from processors.lavori import esegui

log = logging.getLogger(__name__)
INTERVALLO_MS = 100
_CONTESTO = multiprocessing.get_context("spawn")


class LavoroInProcesso:
    def __init__(
        self,
        widget,
        compito: str,
        parametri: dict,
        alla_fine: Callable[[object], None],
        all_errore: Callable[[str], None],
        al_progresso: Callable[[int, int, int], None] | None = None,
        all_annullamento: Callable[[], None] | None = None,
        alla_lettura: Callable[[int, int], None] | None = None,
    ):
        self.widget = widget
        self.compito = compito
        self.parametri = parametri
        self.alla_fine = alla_fine
        self.all_errore = all_errore
        self.al_progresso = al_progresso
        self.all_annullamento = all_annullamento
        self.alla_lettura = alla_lettura
        self._coda = _CONTESTO.Queue()
        self._annulla = _CONTESTO.Event()
        self._processo = None

    @property
    def attivo(self) -> bool:
        return self._processo is not None

    def avvia(self) -> "LavoroInProcesso":
        self._processo = _CONTESTO.Process(
            target=esegui, args=(self.compito, self.parametri, self._coda, self._annulla), daemon=True,
            name=self.compito,
        )
        self._processo.start()
        self.widget.after(INTERVALLO_MS, self._leggi)
        return self

    def annulla(self) -> None:
        self._annulla.set()

    def termina(self) -> None:
        """Alla chiusura della finestra: chiede di fermarsi e, se non basta, chiude il processo."""
        if self._processo is None:
            return
        self._annulla.set()
        self._processo.join(timeout=1)
        if self._processo.is_alive():
            self._processo.terminate()
        self._processo = None

    def _leggi(self) -> None:
        if self._processo is None:
            return
        ultimo, finale = None, None
        try:
            while True:
                msg = self._coda.get_nowait()
                if msg[0] in ("progresso", "lettura"):
                    ultimo = msg  # di lettura o analisi, si ridisegna solo l'ultimo
                else:
                    finale = msg
                    break
        except queue.Empty:
            pass
        if ultimo is not None:
            gestore = self.al_progresso if ultimo[0] == "progresso" else self.alla_lettura
            if gestore:
                gestore(*ultimo[1:])
        if finale is None and not self._processo.is_alive():
            # morto senza dire niente (memoria esaurita, processo ucciso...)
            finale = ("errore", f"Il lavoro si e' interrotto (codice {self._processo.exitcode}).", "")
        if finale is None:
            self.widget.after(INTERVALLO_MS, self._leggi)
            return
        self._processo.join(timeout=2)
        self._processo = None
        if finale[0] == "fine":
            self.alla_fine(finale[1])
        elif finale[0] == "annullata":
            if self.all_annullamento:
                self.all_annullamento()
        else:
            _, messaggio, dettagli = finale
            if dettagli:
                log.error("%s non riuscita: %s\n%s", self.compito, messaggio, dettagli)
            self.all_errore(messaggio)
