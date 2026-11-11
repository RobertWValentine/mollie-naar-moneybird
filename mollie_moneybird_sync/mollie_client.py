from __future__ import annotations

"""Leest de Mollie API. Schrijft nooit."""
import logging

from .http import verzoek

log = logging.getLogger(__name__)
BASIS = "https://api.mollie.com/v2"

# Vangnet tegen een oneindige lus, niet tegen grote lijsten. Bij 250 rijen per
# pagina is dit 125.000 rijen, ruim boven elke terugblik die we draaien.
LIMIET_PAGINAS = 500


def _bewaak(paginas: int, limiet: int, pad: str) -> None:
    """Faalt zodra de paginalimiet op is terwijl Mollie nog meer heeft.

    Eerder stopte de lus hier gewoon. Dat leverde een halve lijst op die er
    compleet uitzag: een lange terugblik gaf precies het maximum aan betalingen
    terug, de oudste maanden ontbraken en de aansluitcontrole meldde duizenden
    verzonnen verschillen. Een onvolledige lijst
    is geen resultaat.
    """
    if paginas >= limiet:
        raise RuntimeError(
            f"Paginalimiet van {limiet} bereikt op {pad} terwijl Mollie nog een "
            f"volgende pagina aanbiedt. De lijst is dus onvolledig en wordt niet "
            f"teruggegeven. Kies een kortere terugblik of verhoog limiet_paginas."
        )


class MollieClient:
    def __init__(self, token: str):
        self.token = token

    def _get(self, pad: str) -> dict:
        return verzoek(f"{BASIS}{pad}", self.token) or {}


    def balansmutaties(self, balans_id: str, limiet_paginas: int = LIMIET_PAGINAS):
        """Levert balansmutaties op, nieuwste eerst."""
        url = f"{BASIS}/balances/{balans_id}/transactions?limit=250"
        paginas = 0
        while url:
            _bewaak(paginas, limiet_paginas, f"/balances/{balans_id}/transactions")
            data = verzoek(url, self.token) or {}
            paginas += 1
            mutaties = data.get("_embedded", {}).get("balance_transactions", [])
            if not mutaties:
                return
            yield from mutaties
            volgende = (data.get("_links") or {}).get("next")
            url = volgende["href"] if volgende else None

    def _lijst(self, pad: str, sleutel: str, grens: str = "",
               limiet_paginas: int = LIMIET_PAGINAS):
        """Loopt een gepagineerde lijst af, nieuwste eerst.

        Stopt bij de grensdatum (op `createdAt`). Raakt de paginalimiet op
        terwijl Mollie nog een volgende pagina aanbiedt, dan stopt het niet maar
        faalt het. Zie `_bewaak` voor waarom.
        """
        url = f"{BASIS}{pad}"
        paginas = 0
        while url:
            _bewaak(paginas, limiet_paginas, pad)
            data = verzoek(url, self.token) or {}
            paginas += 1
            rijen = data.get("_embedded", {}).get(sleutel, [])
            if not rijen:
                return
            for rij in rijen:
                if grens and rij.get("createdAt", "")[:10] < grens:
                    return
                yield rij
            volgende = (data.get("_links") or {}).get("next")
            url = volgende["href"] if volgende else None

    def betalingen(self, grens: str):
        """Betalingen, nieuwste eerst, tot de grensdatum.

        De lijst bevat `details`, dus naam en betaalmethode komen mee zonder
        extra call per betaling.
        """
        return self._lijst("/payments?limit=250", "payments", grens)

    def chargebacks(self, grens: str):
        return self._lijst("/chargebacks?limit=250", "chargebacks", grens)

    def betaling(self, betaling_id: str) -> dict:
        """Eén betaling, voor een refund waarbij de betaling niet is meegestuurd."""
        return self._get(f"/payments/{betaling_id}")

    def refunds(self, grens: str):
        """Met de betaling erbij: zonder settlementAmount (weg per 1 januari 2027) is een
        PayPal-refund alleen aan de betaalmethode te herkennen (docs.mollie.com/reference/list-all-refunds)."""
        return self._lijst("/refunds?limit=250&embed=payment", "refunds", grens)

    def betalingen_van_afrekening(self, afrekening_id: str):
        """De betalingen die in één afrekening zijn meegenomen."""
        return self._lijst(f"/settlements/{afrekening_id}/payments?limit=250", "payments")

    def chargebacks_van_afrekening(self, afrekening_id: str):
        return self._lijst(
            f"/settlements/{afrekening_id}/chargebacks?limit=250", "chargebacks")

    def afrekeningen(self):
        """Alle afrekeningen, met hun periodeblokken en kostentotalen.

        Gepagineerd: bij wekelijkse uitbetaling duurt het jaren voor je boven
        de 250 komt, maar een stille afkapping wil je nooit.
        """
        return list(self._lijst("/settlements?limit=250", "settlements"))

