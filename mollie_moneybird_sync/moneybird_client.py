from __future__ import annotations

"""Schrijft bankafschriften naar Moneybird."""
import datetime as dt
import logging
import os
import time

from .http import HttpFout, verzoek

log = logging.getLogger(__name__)
BASIS = "https://moneybird.com/api/v2"


class MoneybirdClient:
    def __init__(self, token: str, administratie_id: str, pauze: float | None = None):
        self.token = token
        self.administratie_id = administratie_id
        # Pauze tussen opeenvolgende verzoeken bij het doorlopen van alle
        # mutaties. Twee seconden houdt ruim afstand van de limiet.
        self.pauze = pauze if pauze is not None else float(
            os.environ.get("MONEYBIRD_PAUZE", "2.0"))

    def _url(self, pad: str) -> str:
        return f"{BASIS}/{self.administratie_id}/{pad}"

    def maak_afschrift(self, rekening_id: str, referentie: str, mutaties: list[dict]) -> dict:
        """Eén POST met alle mutaties eronder. Slaagt of faalt in zijn geheel."""
        payload = {
            "financial_statement": {
                "reference": referentie,
                "financial_account_id": rekening_id,
                "financial_mutations_attributes": {
                    str(i): m for i, m in enumerate(mutaties)
                },
            }
        }
        return verzoek(self._url("financial_statements.json"), self.token, "POST",
                       payload, idempotent=False) or {}


    def verwijder_afschrift(self, afschrift_id: str) -> None:
        verzoek(self._url(f"financial_statements/{afschrift_id}.json"), self.token,
                "DELETE", idempotent=False)

    def rekeningen(self) -> list[dict]:
        return verzoek(self._url("financial_accounts.json"), self.token) or []

    def saldo(self, rekening_id: str, vanaf_jaar: int = 2025) -> float:
        """Het saldo van een kleine rekening, opgeteld uit zijn mutaties.

        Alleen bruikbaar voor een rekening met weinig verkeer, zoals PayPal.
        De lijstweergave weigert boven de honderd mutaties per verzoek, dus we
        vragen per jaar en tellen op. Loopt een jaar toch tegen die grens aan,
        dan faalt dit met een melding in plaats van een te laag saldo te
        rapporteren: een stilzwijgend afgekapte lijst zou een verschil
        verzinnen dat er niet is.
        """
        return round(sum(float(m["amount"])
                         for m in self.mutaties_klein(rekening_id, vanaf_jaar)), 2)

    def mutaties_klein(self, rekening_id: str, vanaf_jaar: int = 2025) -> list:
        """De mutaties van een rekening met weinig verkeer, per jaar opgehaald.

        De lijstweergave weigert boven de honderd mutaties per verzoek. Zit een
        jaar tegen die grens aan, dan falen we met een melding: een
        stilzwijgend afgekapte lijst zou een verschil verzinnen dat er niet is,
        of erger, een regel als ontbrekend aanmerken die er al staat.
        """
        alles: list = []
        for jaar in range(vanaf_jaar, dt.date.today().year + 1):
            pad = self._url(
                f"financial_mutations.json?filter=financial_account_id:{rekening_id},"
                f"period:{jaar}0101..{jaar}1231"
            )
            regels = verzoek(pad, self.token) or []
            if not isinstance(regels, list):
                raise RuntimeError(f"Moneybird weigerde de mutaties van {jaar}: {regels}")
            if len(regels) >= 100:
                raise RuntimeError(
                    f"Rekening {rekening_id} heeft in {jaar} honderd of meer mutaties. "
                    "De lijstweergave kapt daar af, dus deze uitkomst zou onbetrouwbaar zijn."
                )
            alles.extend(regels)
        return alles

    def onverwerkt(self, filter_tekst: str) -> list:
        """Mutaties die aan een filter voldoen, met de afkapgrens bewaakt.

        Moneybird levert er hoogstens honderd terug en zegt er niet bij dat hij
        afkapt. Zitten we op honderd, dan is het venster te groot en moet de
        aanroeper het opsplitsen; stil doorgaan zou werk laten liggen dat je
        denkt te hebben gezien.
        """
        pad = self._url(f"financial_mutations.json?filter={filter_tekst}")
        regels = verzoek(pad, self.token) or []
        if not isinstance(regels, list):
            raise RuntimeError(f"Moneybird weigerde het filter '{filter_tekst}': {regels}")
        if len(regels) >= 100:
            raise RuntimeError(
                f"Honderd mutaties op filter '{filter_tekst}'; de lijst kapt daar af. "
                "Splits de periode op."
            )
        return regels

    def onverwerkt_in_periode(self, rekening_id: str, periode: str) -> list:
        """Onverwerkte mutaties van een rekening in een periode, ook als het er veel zijn.

        De lijstweergave weigert boven de honderd ("Too many financial mutations
        to return, please use sync API"); in de sandbox, waar nooit gekoppeld
        is, gebeurt dat meteen. Dan halen we alles op via de synchronisatie-API
        en filteren we zelf op state.
        """
        pad = f"financial_account_id:{rekening_id},period:{periode},state:unprocessed"
        try:
            return self.onverwerkt(pad)
        except HttpFout as e:
            if e.status != 400:
                raise
        except RuntimeError:
            pass
        log.info("Lijst te groot voor %s, via de synchronisatie-API", periode)
        return [m for m in self.mutaties_in_periode(rekening_id, periode)
                if m.get("state") == "unprocessed"]

    def mutaties_in_periode(self, rekening_id: str, periode: str) -> list:
        """Alle mutaties van een rekening in een periode, via de synchronisatie-API."""
        pad = self._url(f"financial_mutations/synchronization.json?"
                        f"filter=financial_account_id:{rekening_id},period:{periode}")
        ids = [x["id"] for x in (verzoek(pad, self.token) or [])]
        alles: list = []
        for i in range(0, len(ids), 100):
            if i:
                time.sleep(self.pauze)
            alles.extend(verzoek(self._url("financial_mutations/synchronization.json"), self.token,
                                 "POST", {"ids": ids[i:i + 100]}) or [])
        return alles

    def mutatie(self, mutatie_id: str) -> dict:
        return verzoek(self._url(f"financial_mutations/{mutatie_id}.json"), self.token) or {}

    def verkoopfacturen_van_dag(self, datum: str) -> list:
        """Alle verkoopfacturen en creditnota's van één dag.

        Moneybird levert er hoogstens honderd per pagina, en op een gewone dag
        maakt de WooCommerce-plugin er meer dan dat. Zonder doorbladeren mis je
        stilzwijgend een deel van de dag, en dan lijkt een creditnota te
        ontbreken die er gewoon is.
        """
        dag = datum.replace("-", "")
        alles: list = []
        for pagina in range(1, 51):
            pad = self._url(
                f"sales_invoices.json?filter=period:{dag}..{dag}"
                f"&page={pagina}&per_page=100"
            )
            brok = verzoek(pad, self.token) or []
            if not isinstance(brok, list):
                raise RuntimeError(f"Onverwacht antwoord voor {datum}: {brok}")
            alles.extend(brok)
            if len(brok) < 100:
                return alles
            time.sleep(self.pauze)
        raise RuntimeError(
            f"Meer dan vijfduizend documenten op {datum}; dat klopt niet, "
            "en doorgaan zou een onvolledige lijst opleveren."
        )

    def koppel_aan_document(self, mutatie_id: str, document_id: str, bedrag: str) -> dict:
        """Hangt een bankmutatie als betaling aan een verkoopfactuur of creditnota.

        Het bedrag gaat als absolute waarde mee; Moneybird neemt de richting van
        de mutatie zelf. Negatief meesturen boekt ertegenin en verdubbelt het
        openstaande bedrag.
        """
        absoluut = f"{abs(round(float(bedrag), 2)):.2f}"
        return verzoek(
            self._url(f"financial_mutations/{mutatie_id}/link_booking.json"),
            self.token, "PATCH",
            {"booking_type": "SalesInvoice", "booking_id": document_id,
             "price": absoluut, "price_base": absoluut},
            idempotent=False,
        ) or {}

    def mutaties(self, rekening_id: str) -> list[dict]:
        """Alle bankmutaties van één rekening, via de synchronisatie-API.

        De gewone lijstweergave weigert boven de honderd mutaties, en dat zijn
        er hier duizenden. De synchronisatie-API haalt eerst alle ID's op en
        daarna de mutaties zelf, honderd per keer.
        """
        pad = self._url("financial_mutations/synchronization.json")
        antwoord = verzoek(pad, self.token) or []
        if not isinstance(antwoord, list):
            raise RuntimeError(
                f"Onverwacht antwoord van de synchronisatie-API: {type(antwoord).__name__}"
            )
        ids = [x["id"] for x in antwoord]
        brokken = (len(ids) + 99) // 100
        log.info("%d mutaties ophalen in %d stappen", len(ids), brokken)

        alles: list = []
        for nummer, i in enumerate(range(0, len(ids), 100), start=1):
            if nummer > 1:
                # Moneybird staat een beperkt aantal verzoeken per vijf minuten
                # toe. Bij vijftienduizend mutaties zijn dat honderdvijftig
                # stappen, en zonder pauze loop je halverwege op een 429.
                time.sleep(self.pauze)
            brok = verzoek(pad, self.token, "POST", {"ids": ids[i:i + 100]}) or []
            alles.extend(brok)
            if nummer % 25 == 0 or nummer == brokken:
                log.info("  %d van de %d stappen", nummer, brokken)
        return [m for m in alles if str(m.get("financial_account_id")) == str(rekening_id)]
