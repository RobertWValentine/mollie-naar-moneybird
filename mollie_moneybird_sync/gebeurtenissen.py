from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

"""Zet Mollie-gegevens om in bankmutaties voor Moneybird.

Er zijn vier bronnen, en elk levert zijn eigen soort regel:

| bron        | wanneer geboekt      | regel                                  |
|-------------|----------------------|----------------------------------------|
| betaling    | op de betaaldatum    | brutobedrag, met tr_-kenmerk           |
| chargeback  | op de terugboekdatum | negatief bedrag, met chb_ en tr_       |
| refund      | op de terugbetaaldag | negatief bedrag, met re_ en tr_        |
| afrekening  | op de uitbetaaldag   | uitbetaling, plus kostentotalen        |

De kosten staan bewust niet per transactie. Mollie rekent ze af per
afrekeningsperiode en per kostensoort, en levert ze zo ook aan. Elk
periodeblok draagt zijn eigen factuurnummer, en dat nummer is er al voordat
de factuur bestaat. Daarom kan de kostenregel meteen naar de juiste
Mollie-factuur verwijzen.

Elke regel krijgt een eigen sleutel, zodat een tweede run hem overslaat.
"""

from .tijd import lokale_datum


def _samen(*delen) -> str:
    return " - ".join(str(d) for d in delen if d)


def _bedrag(waarde: str, omkeren: bool = False) -> str:
    """Handelsafronding op centen, met Decimal en niet met float.

    `round(float(x), 2)` deed twee dingen fout tegelijk: het rekent op een
    binaire benadering en het rondt halve centen naar het even getal. Mollie's
    brutobedrag 11,4950 werd daardoor 11,49 terwijl 11,50 hoort. Dat scheelt
    een cent per regel die precies op een halve cent uitkomt, en die cent komt
    terug in de aansluiting van elke maandfactuur.
    """
    getal = Decimal(str(waarde)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if omkeren:
        getal = -getal
    return f"{getal:.2f}"


def _naam(betaling: dict) -> str:
    details = betaling.get("details") or {}
    return (
        details.get("consumerName")
        or details.get("cardHolder")
        or details.get("bankAccountHolder")
        or ""
    )


def van_betaling(betaling: dict) -> dict | None:
    """Eén regel voor een geslaagde betaling, op de datum van betalen.

    PayPal valt hier bewust buiten. Zo'n betaling staat bij Mollie altijd op
    `paid`, maar het geld gaat rechtstreeks naar het PayPal-account: de
    uitbetalingsreferentie blijft leeg, hij komt in geen enkele afrekening voor
    en raakt het Mollie-saldo nooit. Boek je hem hier toch, dan staat de
    Mollie-rekening te hoog en staat de donatie dubbel zodra de PayPal-import
    hem ophaalt.
    """
    if betaling.get("method") == "paypal":
        return None
    if betaling.get("status") != "paid" or not betaling.get("paidAt"):
        return None
    tr = betaling["id"]
    return {
        "sleutel": tr,
        "tijd": betaling["paidAt"],
        "date": lokale_datum(betaling["paidAt"]),
        "amount": _bedrag(betaling["amount"]["value"]),
        "message": _samen("Mollie Payment", _naam(betaling),
                          betaling.get("description", ""), tr),
    }


def van_chargeback(chargeback: dict) -> list:
    """De terugboeking, en als die later is teruggedraaid ook de tegenboeking.

    Win je een geschil, dan komt het geld terug. Mollie zet dan `reversedAt`
    op de chargeback in plaats van er een nieuw record voor te maken.
    """
    reden = chargeback.get("reason") or {}
    bedrag = (chargeback.get("settlementAmount") or chargeback["amount"])["value"]
    tr = chargeback.get("paymentId", "")
    regels = [{
        "sleutel": chargeback["id"],
        "tijd": chargeback["createdAt"],
        "date": lokale_datum(chargeback["createdAt"]),
        "amount": _bedrag(bedrag),
        "message": _samen("Mollie Chargeback", reden.get("code", ""),
                          reden.get("description", ""), chargeback["id"], tr),
    }]
    if chargeback.get("reversedAt"):
        regels.append({
            "sleutel": f"{chargeback['id']}:teruggedraaid",
            "tijd": chargeback["reversedAt"],
            "date": lokale_datum(chargeback["reversedAt"]),
            "amount": _bedrag(bedrag, omkeren=True),
            "message": _samen("Mollie Chargeback Reversed", chargeback["id"], tr),
        })
    return regels


def van_refund(refund: dict) -> dict | None:
    """Alleen een afgeronde terugbetaling is geld dat er echt uit is.

    Een refund doorloopt queued, pending, processing, refunded, failed en
    canceled. Boek je hem in de wachtrij, dan boek je geld weg dat er nog is,
    en bij `failed` komt er nooit een tegenboeking.
    """
    if refund.get("status") != "refunded":
        return None
    # settlementAmount is wat er van de balans afgaat; amount is wat de klant
    # krijgt. Bij euro's gelijk, bij vreemde valuta niet.
    bedrag = (refund.get("settlementAmount") or refund["amount"])["value"]
    getal = float(bedrag)
    return {
        "sleutel": refund["id"],
        "tijd": refund["createdAt"],
        "date": lokale_datum(refund["createdAt"]),
        # settlementAmount is al negatief, amount niet.
        "amount": _bedrag(bedrag, omkeren=getal > 0),
        "message": _samen("Mollie Refund", refund.get("description", ""),
                          refund["id"], refund.get("paymentId", "")),
    }


def van_afrekening(afrekening: dict) -> list:
    """Uitbetalingsregel plus de kostentotalen per periode.

    Wordt pas geboekt als de afrekening is uitbetaald; een lopende afrekening
    heeft nog geen definitieve bedragen en geen factuurnummer.
    """
    if afrekening.get("status") != "paidout" or not afrekening.get("settledAt"):
        return []

    stl = afrekening["id"]
    datum = lokale_datum(afrekening["settledAt"])
    tijd = afrekening["settledAt"]
    regels = [{
        "sleutel": stl,
        "tijd": tijd,
        "date": datum,
        "amount": _bedrag(afrekening["amount"]["value"], omkeren=True),
        "message": _samen("Mollie Settlement", stl),
    }]

    for jaar, maanden in (afrekening.get("periods") or {}).items():
        for maand, blok in (maanden or {}).items():
            factuur_id = blok.get("invoiceId") or ""
            verwijzing = blok.get("invoiceReference") or ""

            # Het omzetblok levert bewust NIETS op. Het is een samenvatting per
            # betaalmethode van wat elders al per stuk staat:
            #   positieve regels = de betalingen, die boeken we uit de
            #     betalingenlijst, met naam en tr_-kenmerk
            #   negatieve regels = chargebacks en refunds, die hebben een eigen
            #     record bij Mollie (chb_ en re_) en boeken we ook al per stuk
            # Een mislukte incasso is daarbij geen aparte soort maar een
            # chargeback met een andere reden. Het aantal chb_-records valt samen
            # met de regels "Chargeback" plus "Failed" in de afrekeningen.
            #
            # Boek je dit blok toch, dan staan die posten dubbel op de
            # Mollie-rekening. Het saldo verhult dat,
            # want er staat altijd duizenden euro's onderweg: Mollie maakt zijn
            # balansmutatie pas als een incasso is bijgeschreven, wij boeken op
            # de betaaldatum. Alleen vergelijken op kenmerk deugt hier.

            for nummer, kosten in enumerate(blok.get("costs") or []):
                omschrijving = kosten.get("description", "")
                regels.append({
                    # Nummer erbij: bij een tariefwijziging binnen een periode
                    # komt dezelfde omschrijving twee keer voor, met een ander
                    # tarief en een ander bedrag. Aangetroffen in de historie.
                    "sleutel": f"{stl}:{jaar}-{maand}:{nummer}:{omschrijving}",
                    "tijd": tijd,
                    "date": datum,
                    "amount": _bedrag(kosten["amountGross"]["value"], omkeren=True),
                    "message": _samen("Mollie Cost", factuur_id, omschrijving,
                                      verwijzing, stl),
                })
    return regels


# PayPal noemt een transactiesoort met een gebeurteniscode. Wij hebben er twee
# nodig om de regel de juiste naam te geven; al het andere krijgt een neutrale
# omschrijving en wordt gewoon geboekt. Overslaan is hier het gevaarlijke pad:
# elke regel die PayPal levert heeft het saldo geraakt, dus wat wij niet boeken
# valt uit de aansluiting.
PAYPAL_UITBETALING = {"T0400", "T0403"}


def van_paypal_transactie(transactie: dict) -> list:
    """Eén of twee regels per PayPal-transactie: het brutobedrag en de kosten.

    De kosten staan bij PayPal ín de transactie (`fee_amount`, al negatief) en
    niet in een aparte afrekening zoals bij Mollie. We zetten ze toch op een
    eigen regel, zodat de brutodonatie zichzelf aan de verkoopfactuur kan
    koppelen en de kosten los op een kostenrekening kunnen.

    Het koppelen lukt doordat PayPal het Mollie-kenmerk meedraagt in
    `custom_field`. Een gewone bankkoppeling levert dat kenmerk niet.
    """
    transactie_id = transactie.get("transaction_id")
    tijd = transactie.get("transaction_initiation_date") or ""
    bedrag = (transactie.get("transaction_amount") or {}).get("value")
    if not transactie_id or not tijd or bedrag is None:
        return []

    datum = lokale_datum(tijd)
    code = transactie.get("transaction_event_code") or ""
    kenmerk = transactie.get("custom_field") or ""
    aanduiding = transactie.get("invoice_id") or transactie.get("transaction_subject") or ""

    if code in PAYPAL_UITBETALING or (float(bedrag) < 0 and not kenmerk and not aanduiding):
        omschrijving = _samen("PayPal Withdrawal", "overboeking naar bank", transactie_id)
    elif float(bedrag) >= 0:
        omschrijving = _samen("PayPal Payment", aanduiding, kenmerk or transactie_id)
    else:
        omschrijving = _samen("PayPal Mutatie", code, aanduiding, kenmerk or transactie_id)

    regels = [{
        "sleutel": f"pp:{transactie_id}",
        "tijd": tijd,
        "date": datum,
        "amount": _bedrag(bedrag),
        "message": omschrijving,
    }]

    kosten = (transactie.get("fee_amount") or {}).get("value")
    if kosten is not None and round(float(kosten), 2) != 0:
        regels.append({
            "sleutel": f"pp:{transactie_id}:kosten",
            "tijd": tijd,
            "date": datum,
            # PayPal levert de fee al negatief; _bedrag laat het teken staan.
            "amount": _bedrag(kosten),
            "message": _samen("PayPal Cost", aanduiding, transactie_id),
        })
    return regels
