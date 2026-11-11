from __future__ import annotations

"""Zelfcontrole: sluit onze boeking op wat Mollie zelf heeft uitbetaald?

Een afrekening is een gesloten kringloop. Mollie betaalt uit wat er aan omzet
binnenkwam min de kosten. Boeken wij alle onderdelen goed, dan moet gelden:

    bruto betalingen + correcties + terugboekingen - uitbetaling = 0

Loopt dat uiteen, dan missen we een soort regel. Precies zo is ontdekt dat
teruggedraaide incasso's als negatieve omzetregel in de afrekening staan en
niet als losse chargeback.
"""
import logging

from .gebeurtenissen import NietTeBoeken, van_afrekening, van_betaling, van_chargeback

log = logging.getLogger(__name__)

# Mollie geeft kostenbedragen in vier decimalen; wij ronden elke regel apart
# af. Daardoor mag er per afrekening een cent verschil overblijven.
MARGE = 0.02


def toets_afrekening(mollie, afrekening: dict) -> dict:
    stl = afrekening["id"]
    uitbetaling = float(afrekening["amount"]["value"])

    bruto = 0.0
    aantal = 0
    for betaling in mollie.betalingen_van_afrekening(stl):
        regel = van_betaling(betaling)
        if regel:
            bruto += float(regel["amount"])
            aantal += 1

    correcties = sum(
        float(r["amount"]) for r in van_afrekening(afrekening)
        if not r["message"].startswith("Mollie Settlement")
    )
    toetsbaar = True
    try:
        terug = sum(
            float(r["amount"])
            for cb in mollie.chargebacks_van_afrekening(stl)
            for r in van_chargeback(cb)
        )
    except NietTeBoeken as e:
        # Eén terugboeking zonder eurobedrag maakt deze afrekening ontoetsbaar. Melden als
        # afwijkend en doorgaan met de volgende, niet de hele controle laten stoppen.
        log.error("Afrekening %s niet te toetsen: %s", stl, e)
        terug, toetsbaar = 0.0, False

    verschil = round(bruto + correcties + terug - uitbetaling, 2)
    return {
        "afrekening": stl,
        "betalingen": aantal,
        "bruto": round(bruto, 2),
        "correcties": round(correcties, 2),
        "terugboekingen": round(terug, 2),
        "uitbetaling": uitbetaling,
        "verschil": verschil,
        "toetsbaar": toetsbaar,
        "sluit": toetsbaar and abs(verschil) <= MARGE,
    }


def controleer(mollie, aantal: int = 4) -> list:
    """Toetst de laatste uitbetaalde afrekeningen."""
    uitbetaald = [a for a in mollie.afrekeningen() if a.get("status") == "paidout"]
    uitkomsten = []
    for afrekening in uitbetaald[:aantal]:
        uitkomst = toets_afrekening(mollie, afrekening)
        uitkomsten.append(uitkomst)
        log.info(
            "%s: bruto %.2f + correcties %.2f + terugboekingen %.2f "
            "- uitbetaling %.2f = %.2f  %s",
            uitkomst["afrekening"], uitkomst["bruto"], uitkomst["correcties"],
            uitkomst["terugboekingen"], uitkomst["uitbetaling"],
            uitkomst["verschil"],
            "OK" if uitkomst["sluit"] else ("WIJKT AF" if uitkomst["toetsbaar"] else "NIET TE TOETSEN"),
        )
    return uitkomsten
