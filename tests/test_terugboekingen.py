"""Toetst het matchen van een teruggeboekte incasso aan zijn creditnota.

De gevallen volgen echte terugboekingen, met verzonnen kenmerken. Namen van
klanten staan er niet in; het kenmerk is genoeg om te matchen en dat is precies
het punt van deze module.
"""
from mollie_moneybird_sync.terugboekingen import (
    is_terugboeking,
    kenmerk_van,
    zoek_creditnota,
)

TERUGBOEKING = {
    "id": "409570154303911718",
    "date": "2026-08-26",
    "amount": "-1.0",
    "message": "Mollie Chargeback - AC04 - Account closed - chb_XXdo0cZuzren68K4TunPF "
               "- tr_RPeMOkIUpkDyr7OSJoRu1",
}

CREDITNOTA = {
    "id": "471331509839301031",
    "invoice_id": "202615802",
    "total_price_incl_tax": "-1.0",
    "reference": "SEPA Chargeback - chb_XXdo0cZuzren68K4TunPF",
}


def test_terugboeking_vindt_zijn_creditnota():
    nota, reden = zoek_creditnota(TERUGBOEKING, [CREDITNOTA, dict(CREDITNOTA,
                                                                 invoice_id="999",
                                                                 reference="iets anders")])
    assert reden == ""
    assert nota["invoice_id"] == "202615802"


def test_afgekapt_kenmerk_matcht_ook():
    """In sommige omschrijvingen staat het kenmerk korter dan in de referentie."""
    kort = dict(TERUGBOEKING, message="Mollie Chargeback - SL01 - chb_XXdo0cZ - tr_abc")
    nota, reden = zoek_creditnota(kort, [CREDITNOTA])
    assert reden == ""
    assert nota is CREDITNOTA


def test_zonder_creditnota_blijft_de_regel_staan():
    nota, reden = zoek_creditnota(TERUGBOEKING, [])
    assert nota is None
    assert "geen creditnota" in reden


def test_twee_kandidaten_is_geen_keuze():
    """Weigeren, niet gokken: dan hangt de betaling bij de verkeerde klant."""
    nota, reden = zoek_creditnota(TERUGBOEKING, [CREDITNOTA, dict(CREDITNOTA, invoice_id="202615803")])
    assert nota is None
    assert "2 creditnota's" in reden


def test_bedrag_moet_kloppen():
    """Twee terugboekingen van 3,00 op één dag komen echt voor."""
    nota, reden = zoek_creditnota(TERUGBOEKING, [dict(CREDITNOTA, total_price_incl_tax="-2.5")])
    assert nota is None
    assert "bedrag wijkt af" in reden


def test_de_kostenregel_van_mollie_is_geen_terugboeking():
    """"Mollie Cost - Chargebacks" is de fee en hoort bij de maandfactuur."""
    fee = {"message": "Mollie Cost - Chargebacks - MOL-NL-R2026.0001234567 - stl_3hjOkY",
           "amount": "-36.30", "date": "2026-08-25"}
    assert is_terugboeking(fee) is False
    assert is_terugboeking(TERUGBOEKING) is True


def test_een_gewone_betaling_is_geen_terugboeking():
    betaling = {"message": "Mollie Payment - Bestelling 11755 - tr_Xsf2o3gyrDO1xkxwnQrS7",
                "amount": "5.00", "date": "2026-08-28"}
    assert is_terugboeking(betaling) is False


def test_kenmerk_uit_lege_tekst():
    assert kenmerk_van("") == ""
    assert kenmerk_van(None) == ""


def test_onverwerkt_in_periode_valt_terug_op_de_sync_api(monkeypatch):
    """In de sandbox weigert de lijstweergave (400 Too many); dan via de synchronisatie-API."""
    from mollie_moneybird_sync.http import HttpFout
    from mollie_moneybird_sync.moneybird_client import MoneybirdClient

    client = MoneybirdClient("t", "422782489638346578", pauze=0)

    def weiger(pad):
        raise HttpFout(400, '{"error":"Too many financial mutations to return, please use sync API"}')
    monkeypatch.setattr(client, "onverwerkt", weiger)
    monkeypatch.setattr(client, "mutaties_in_periode", lambda rek, per: [
        {"id": "1", "state": "unprocessed", "amount": "-2.5"},
        {"id": "2", "state": "processed", "amount": "-3.0"},
    ])
    uit = client.onverwerkt_in_periode("427048281489325288", "20260701..20261231")
    assert [m["id"] for m in uit] == ["1"]
