from __future__ import annotations

"""Koppelt een teruggeboekte incasso aan de creditnota die erbij hoort.

Hoe het loopt zonder ons. De WooCommerce-plugin maakt bij een terugboeking een
creditnota en zet daar meteen een betaling bij op de tussenrekening "Te
rubriceren ontvangen betalingen". Die betaling hangt aan geen enkele
bankmutatie: het is een tijdelijke post. Onze eigen import zet ondertussen de
echte bankregel op de Mollie-rekening. Die twee vinden elkaar niet vanzelf,
dus de creditnota staat op betaald terwijl er een bedrag op de tussenrekening
blijft staan en de bankregel onverwerkt blijft.

Koppelen we de bankregel aan de creditnota, dan verplaatst Moneybird die
bestaande betaling zelf van de tussenrekening naar de bankrekening. Er hoeft
dus niets verwijderd te worden. Getoetst in de praktijk: de tussenrekening
had daarna één post minder, de betaling hield zijn eigen ID en wees daarna
naar onze mutatie.
Let op: het grootboekrapport loopt een paar minuten achter op die verplaatsing.

Matchen gaat op het `chb_`-kenmerk, nooit op het bedrag. Op één dag staan
regelmatig twee terugboekingen van hetzelfde bedrag; matchen op bedrag zou die
verwisselen en dan hangt de betaling van de ene klant aan de creditnota van de
andere.
"""
import re

KENMERK = re.compile(r"chb_[A-Za-z0-9]+")


def kenmerk_van(tekst: str) -> str:
    gevonden = KENMERK.search(tekst or "")
    return gevonden.group() if gevonden else ""


def is_terugboeking(mutatie: dict) -> bool:
    """Een terugboeking, en niet de kostenregel die Mollie erover rekent.

    Beide dragen het woord Chargeback. "Mollie Cost - Chargebacks - MOL-NL-..."
    is de fee en hoort bij de maandfactuur van Mollie, niet bij een creditnota.
    """
    bericht = mutatie.get("message") or ""
    return "Mollie Chargeback" in bericht and bool(kenmerk_van(bericht))


def _zelfde_kenmerk(links: str, rechts: str) -> bool:
    """Kenmerken kunnen afgekapt in een omschrijving staan, dus voorvoegsel telt."""
    if not links or not rechts:
        return False
    return links.startswith(rechts) or rechts.startswith(links)


def zoek_creditnota(mutatie: dict, facturen: list) -> tuple:
    """Geeft (creditnota, reden) terug; bij een treffer is de reden leeg.

    Weigert bij twijfel. Een verkeerd gekoppelde betaling is lastiger te
    herstellen dan een regel die nog een ronde blijft liggen.
    """
    kenmerk = kenmerk_van(mutatie.get("message") or "")
    if not kenmerk:
        return None, "geen chb-kenmerk in de omschrijving"

    treffers = [f for f in facturen
                if _zelfde_kenmerk(kenmerk, kenmerk_van(f.get("reference") or ""))]
    if not treffers:
        return None, f"geen creditnota met {kenmerk}"
    if len(treffers) > 1:
        nummers = ", ".join(str(f.get("invoice_id")) for f in treffers)
        return None, f"{len(treffers)} creditnota's met {kenmerk} ({nummers})"

    nota = treffers[0]
    bedrag = round(float(mutatie["amount"]), 2)
    op_nota = round(float(nota["total_price_incl_tax"]), 2)
    if bedrag != op_nota:
        return None, f"bedrag wijkt af: bankregel {bedrag:.2f}, creditnota {op_nota:.2f}"
    return nota, ""
