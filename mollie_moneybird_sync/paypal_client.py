from __future__ import annotations

"""Leest transacties uit PayPal via de Transaction Search API.

Twee eigenaardigheden van die API bepalen de vorm van deze module:

- Een verzoek beslaat hooguit 31 dagen. Een langere terugblik wordt dus in
  vensters geknipt. De historie gaat drie jaar terug, niet verder.
- Levert een venster niets op, dan ontbreekt `transaction_details` volledig in
  het antwoord. Dat is geen fout maar een lege maand.

Elke geleverde transactie raakt het saldo en draagt zijn eigen
`ending_balance`. Dat maakt een harde controle mogelijk die bij Mollie niet
kan: het saldo dat wij boeken moet gelijk zijn aan wat PayPal zelf zegt.
"""
import base64
import datetime as dt
import json
import logging
import urllib.parse
import urllib.request

from .http import verzoek

log = logging.getLogger(__name__)
BASIS = "https://api-m.paypal.com"
VENSTER_DAGEN = 31


class PaypalClient:
    def __init__(self, client_id: str, secret: str):
        self.client_id = client_id
        self.secret = secret
        self._token: str | None = None

    def token(self) -> str:
        """Haalt een toegangstoken op met client credentials.

        Dit verzoek gaat niet door `verzoek`: het wil Basic-auth en een
        formulierbody, geen bearer met JSON.
        """
        if self._token:
            return self._token
        auth = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        req = urllib.request.Request(
            f"{BASIS}/v1/oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            antwoord = json.loads(resp.read())
        token = antwoord.get("access_token")
        if not token:
            raise RuntimeError("PayPal gaf geen toegangstoken terug.")
        self._token = token
        return token

    def _pagina(self, start: str, eind: str, pagina: int) -> dict:
        vraag = urllib.parse.urlencode({
            "start_date": f"{start}T00:00:00-0000",
            "end_date": f"{eind}T23:59:59-0000",
            "fields": "all",
            "page_size": 100,
            "page": pagina,
        })
        return verzoek(f"{BASIS}/v1/reporting/transactions?{vraag}", self.token()) or {}

    def transacties(self, vanaf: str, tot: str | None = None) -> list[dict]:
        """Alle transacties tussen twee datums, in vensters van 31 dagen.

        Geeft de `transaction_info`-blokken terug, oplopend in de tijd.
        """
        begin = dt.date.fromisoformat(vanaf)
        einde = dt.date.fromisoformat(tot) if tot else dt.date.today()
        if begin > einde:
            return []

        alles: list[dict] = []
        venster_start = begin
        while venster_start <= einde:
            venster_eind = min(venster_start + dt.timedelta(days=VENSTER_DAGEN - 1), einde)
            pagina = 1
            while True:
                antwoord = self._pagina(venster_start.isoformat(), venster_eind.isoformat(),
                                        pagina)
                details = antwoord.get("transaction_details")
                if not details:
                    # Een lege periode levert geen transaction_details op. Dat
                    # is geen fout; alleen doorlopen naar het volgende venster.
                    break
                alles.extend(d["transaction_info"] for d in details if "transaction_info" in d)
                totaal = int(antwoord.get("total_pages") or 1)
                if pagina >= totaal:
                    break
                pagina += 1
            venster_start = venster_eind + dt.timedelta(days=1)

        alles.sort(key=lambda t: (t.get("transaction_initiation_date") or "",
                                  t.get("transaction_id") or ""))
        log.info("PayPal: %d transacties tussen %s en %s",
                 len(alles), begin.isoformat(), einde.isoformat())
        return alles


def eindsaldo(transacties: list[dict]) -> str | None:
    """Het saldo dat PayPal noemt bij de laatste transactie.

    Geen transacties in het venster betekent geen uitspraak over het saldo;
    dan geeft dit None terug in plaats van nul, want nul zou een bewering zijn.
    """
    if not transacties:
        return None
    laatste = transacties[-1]
    saldo = (laatste.get("ending_balance") or {}).get("value")
    return saldo if saldo is not None else None
