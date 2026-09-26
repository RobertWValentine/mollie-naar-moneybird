from __future__ import annotations

"""Kale HTTP-laag met herhaalpogingen. Geen externe afhankelijkheden."""
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

HERHAALBAAR = {429, 500, 502, 503, 504}


class HttpFout(RuntimeError):
    def __init__(self, status: int, body: str, retry_after: float = 0.0, url: str = ""):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status = status
        self.body = body
        self.retry_after = retry_after
        self.url = url


def _wachttijd(fout, poging: int) -> float:
    """Hoe lang wachten voor de volgende poging.

    Bij een rate limit is de gewone verdubbeling te kort: Moneybird laat een
    beperkt aantal verzoeken per vijf minuten toe, dus een paar seconden
    wachten levert meteen weer een 429 op. Stuurt de server een Retry-After
    mee, dan is dat leidend.
    """
    if isinstance(fout, HttpFout) and fout.status == 429:
        if fout.retry_after:
            return min(fout.retry_after + 1, 300)
        return min(30 * poging, 300)
    return 2 ** poging


def verzoek(
    url: str,
    token: str,
    methode: str = "GET",
    payload: dict | None = None,
    pogingen: int = 6,
    idempotent: bool = True,
) -> dict | None:
    """Voert een verzoek uit en herhaalt bij tijdelijke fouten.

    `idempotent` moet op False bij een POST die iets aanmaakt. Bij een 500 of
    een time-out weet je namelijk niet of de server het al verwerkt heeft; nog
    een keer posten maakt dan een tweede afschrift met alle mutaties er nog een
    keer onder. Bij een 429 is dat wel veilig, want dan is er zeker niets
    verwerkt.
    """
    kop = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        kop["Content-Type"] = "application/json"

    laatste: Exception | None = None
    for poging in range(1, pogingen + 1):
        req = urllib.request.Request(url, data=data, method=methode, headers=kop)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                rauw = resp.read()
                return json.loads(rauw) if rauw else None
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                retry_after = float(e.headers.get("Retry-After") or 0)
            except (TypeError, ValueError):
                retry_after = 0.0
            herhaalbaar = e.code == 429 if not idempotent else e.code in HERHAALBAAR
            if not herhaalbaar:
                raise HttpFout(e.code, body, retry_after, url=url) from e
            laatste = HttpFout(e.code, body, retry_after, url=url)
        except (urllib.error.URLError, TimeoutError) as e:
            if not idempotent:
                # Het verzoek kan al aangekomen zijn. Opnieuw sturen zou een
                # tweede afschrift kunnen maken.
                raise
            laatste = e

        if poging < pogingen:
            wacht = _wachttijd(laatste, poging)
            log.warning("Poging %d mislukt (%s), opnieuw over %ss",
                        poging, laatste, round(wacht))
            time.sleep(wacht)

    raise laatste  # type: ignore[misc]
