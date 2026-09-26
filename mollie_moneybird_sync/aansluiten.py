from __future__ import annotations

"""Sluit aan op wat er al in Moneybird staat.

Bij de overstap van de oude koppeling moeten we weten welke regels er al zijn.
Aansluiten op een tijdstip is te wankel: stopt de oude koppeling er halverwege
mee, of laat hij een gat, dan mis je regels of boek je dubbel. Daarom
vergelijken we met wat er feitelijk in de rekening staat.

Twee dingen die dit lastiger maken dan het lijkt:

1. Een mislukte incasso en de geslaagde herhaling delen hetzelfde
   `tr_`-kenmerk. Daarom is de sleutel kenmerk plus bedrag, niet kenmerk alleen.
2. Twee gelijke regels op hetzelfde kenmerk en bedrag zijn daarmee nog steeds
   niet te onderscheiden. Daarom tellen we hoe vaak een sleutel voorkomt en
   verbruiken we hem, in plaats van alleen te kijken of hij bestaat.

Kostenregels dragen geen transactiekenmerk maar het Mollie-factuurnummer.
Samen met het bedrag is dat onderscheidend genoeg, en doordat we tellen gaan
twee kostensoorten met hetzelfde bedrag in dezelfde periode niet mis.
"""
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

KENMERK = re.compile(
    r"\b((?:tr|re|chb|stl|trf|inv)_[A-Za-z0-9]+|MOL-[A-Z]{2}-[A-Z]\d{4}\.\d+)\b"
)


def _bedrag(waarde) -> float:
    # Zelfde handelsafronding als de schrijfkant (gebeurtenissen._bedrag),
    # anders vallen sleutels van oude en nieuwe regels een cent uit elkaar.
    return float(Decimal(str(waarde)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def kenmerken_van(tekst: str) -> set:
    return set(KENMERK.findall(tekst or ""))


def bestaande_sleutels(mutaties: list) -> tuple:
    """Telt de sleutels van wat er al in Moneybird staat.

    Een Counter en geen set, zodat twee identieke regels ook als twee tellen.
    De tweede teller is alleen voor mutaties zonder enig kenmerk, en wordt met
    opzet spaarzaam gebruikt: bij tweeduizend donaties van 2,50 per maand
    levert datum plus bedrag anders valse treffers op.
    """
    op_kenmerk: Counter = Counter()
    op_datum: Counter = Counter()
    for m in mutaties:
        bedrag = _bedrag(m["amount"])
        datum = (m.get("date") or "")[:10]
        gevonden = kenmerken_van(m.get("message", ""))
        for k in gevonden:
            op_kenmerk[(k, bedrag)] += 1
        if not gevonden:
            op_datum[(datum, bedrag)] += 1
    return op_kenmerk, op_datum


def splits(regels: list, mutaties: list) -> tuple:
    """Geeft (al geboekt, nog te boeken) terug.

    Verbruikt elke gevonden sleutel, zodat twee gelijke regels niet allebei op
    dezelfde bestaande mutatie kunnen matchen.
    """
    op_kenmerk, op_datum = bestaande_sleutels(mutaties)
    geboekt, ontbreekt = [], []

    for regel in regels:
        bedrag = _bedrag(regel["amount"])
        kenmerken = kenmerken_van(regel["message"])
        treffer = None

        for k in kenmerken:
            if op_kenmerk[(k, bedrag)] > 0:
                treffer = (k, bedrag)
                break

        if treffer:
            op_kenmerk[treffer] -= 1
            geboekt.append(regel)
            continue

        if kenmerken:
            # Er is een kenmerk, maar het staat niet in Moneybird. Terugvallen
            # op datum plus bedrag zou hier valse treffers geven.
            ontbreekt.append(regel)
            continue

        sleutel = (regel["date"], bedrag)
        if op_datum[sleutel] > 0:
            op_datum[sleutel] -= 1
            geboekt.append(regel)
        else:
            ontbreekt.append(regel)

    return geboekt, ontbreekt
