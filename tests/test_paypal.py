"""Toetst de vertaling van PayPal-transacties naar bankmutaties.

De fixtures volgen de vorm van het echte antwoord van de Transaction Search
API. Kenmerken en bedragen zijn verzonnen. De naam en het e-mailadres van
de donateur staan er bewust niet in: die horen in de administratie, niet in een
testbestand.
"""
from mollie_moneybird_sync.gebeurtenissen import van_betaling, van_paypal_transactie
from mollie_moneybird_sync.paypal_client import eindsaldo

DONATIE = {
    "transaction_id": "5XK0518347382997Q",
    "transaction_event_code": "T0006",
    "transaction_initiation_date": "2026-01-09T10:01:53Z",
    "transaction_amount": {"currency_code": "EUR", "value": "88.00"},
    "fee_amount": {"currency_code": "EUR", "value": "-3.34"},
    "transaction_status": "S",
    "transaction_subject": "Order 16497",
    "invoice_id": "Order 16497",
    "custom_field": "tr_oGMbJmTPSIAoCLrZ3aWZk",
    "ending_balance": {"currency_code": "EUR", "value": "84.66"},
}

UITBETALING = {
    "transaction_id": "3TB33130A02162149",
    "transaction_event_code": "T0403",
    "transaction_initiation_date": "2026-08-16T11:56:26Z",
    "transaction_amount": {"currency_code": "EUR", "value": "-84.66"},
    "transaction_status": "R",
    "ending_balance": {"currency_code": "EUR", "value": "0.00"},
}


def test_donatie_geeft_bruto_en_kosten():
    regels = van_paypal_transactie(DONATIE)
    assert len(regels) == 2

    bruto, kosten = regels
    assert bruto["date"] == "2026-01-09"
    assert bruto["amount"] == "88.00"
    assert bruto["sleutel"] == "pp:5XK0518347382997Q"
    assert kosten["amount"] == "-3.34"
    assert kosten["sleutel"] == "pp:5XK0518347382997Q:kosten"


def test_het_mollie_kenmerk_staat_in_de_omschrijving():
    """Daarop koppelt Moneybird de donatie aan de verkoopfactuur."""
    bruto = van_paypal_transactie(DONATIE)[0]
    assert "tr_oGMbJmTPSIAoCLrZ3aWZk" in bruto["message"]
    assert bruto["message"] == "PayPal Payment - Order 16497 - tr_oGMbJmTPSIAoCLrZ3aWZk"


def test_uitbetaling_heet_uitbetaling_en_heeft_geen_kostenregel():
    regels = van_paypal_transactie(UITBETALING)
    assert len(regels) == 1
    assert regels[0]["amount"] == "-84.66"
    assert regels[0]["message"] == (
        "PayPal Withdrawal - overboeking naar bank - 3TB33130A02162149"
    )


def test_transactie_zonder_kosten_geeft_een_regel():
    zonder = dict(DONATIE)
    zonder.pop("fee_amount")
    assert len(van_paypal_transactie(zonder)) == 1

    nul = dict(DONATIE, fee_amount={"currency_code": "EUR", "value": "0.00"})
    assert len(van_paypal_transactie(nul)) == 1


def test_onbekende_soort_wordt_toch_geboekt():
    """Overslaan is hier het gevaarlijke pad: elke regel raakte het saldo."""
    vreemd = {
        "transaction_id": "X1",
        "transaction_event_code": "T1107",
        "transaction_initiation_date": "2026-03-01T09:00:00Z",
        "transaction_amount": {"currency_code": "EUR", "value": "-12.50"},
        "invoice_id": "Order 1",
    }
    regels = van_paypal_transactie(vreemd)
    assert len(regels) == 1
    assert regels[0]["amount"] == "-12.50"
    assert "T1107" in regels[0]["message"]


def test_onvolledige_transactie_levert_niets():
    assert van_paypal_transactie({"transaction_id": "X2"}) == []
    assert van_paypal_transactie({}) == []


def test_eindsaldo_is_het_saldo_van_de_laatste_transactie():
    assert eindsaldo([DONATIE, UITBETALING]) == "0.00"


def test_zonder_transacties_doet_paypal_geen_uitspraak():
    """Geen transacties betekent onbekend saldo, niet nul."""
    assert eindsaldo([]) is None


def test_paypal_betaling_hoort_niet_op_de_mollie_rekening():
    """PayPal raakt het Mollie-saldo nooit."""
    betaling = {
        "id": "tr_oGMbJmTPSIAoCLrZ3aWZk",
        "status": "paid",
        "paidAt": "2026-01-09T10:01:53+00:00",
        "amount": {"value": "88.00", "currency": "EUR"},
        "method": "paypal",
        "description": "Order 16497",
    }
    assert van_betaling(betaling) is None

    # Een ideal-betaling met verder dezelfde vorm hoort er wel gewoon in.
    assert van_betaling(dict(betaling, method="ideal")) is not None
