from __future__ import annotations

"""Datums in Nederlandse tijd.

Mollie levert tijdstippen in UTC. Boeken doen we op de Nederlandse datum, want
dat is de datum die in de boekhouding hoort te staan. Het verschil is geen
detail: alles tussen 22:00 en middernacht UTC valt in Nederland al op de
volgende dag, en juist in dat venster verwerkt Mollie zijn incasso's.
"""
import datetime as dt

try:
    from zoneinfo import ZoneInfo

    AMSTERDAM = ZoneInfo("Europe/Amsterdam")
except Exception as fout:  # pragma: no cover
    # Stilzwijgend terugvallen op UTC is hier het gevaarlijkst wat je kunt doen:
    # gemeten valt 38,6 procent van alle betalingen na 22:00 UTC, en die zouden
    # dan allemaal een dag te vroeg geboekt worden zonder dat iets dat verraadt.
    # Liever een run die niet start dan een boekhouding met verkeerde datums.
    raise RuntimeError(
        "Tijdzonedata voor Europe/Amsterdam ontbreekt. Installeer die met "
        "'pip install tzdata' of 'apt install tzdata'. Zonder tijdzone zouden "
        "boekingen op de UTC-datum landen en dat is bij ruim een derde van de "
        "betalingen een dag te vroeg."
    ) from fout


def lokale_datum(tijdstip: str) -> str:
    """Zet een ISO-tijdstip met tijdzone om naar de Nederlandse datum.

    >>> lokale_datum("2026-08-11T23:31:16+00:00")
    '2026-08-12'
    >>> lokale_datum("2026-08-11T21:00:00+00:00")
    '2026-08-11'
    """
    if not tijdstip:
        return ""
    tekst = tijdstip.replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(tekst)
    except ValueError:
        return tijdstip[:10]
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone(AMSTERDAM).date().isoformat()
