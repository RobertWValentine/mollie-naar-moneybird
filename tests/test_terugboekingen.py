"""Toetst het matchen van een teruggeboekte incasso aan zijn creditnota.

De gevallen volgen echte terugboekingen, met verzonnen kenmerken. Namen van
klanten staan er niet in; het kenmerk is genoeg om te matchen en dat is precies
het punt van deze module.
"""
import pytest

from mollie_moneybird_sync import moneybird_client
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


@pytest.mark.parametrize("weigert", ["get", "post"])
def test_mutaties_in_periode_en_aantal_weigeren_een_antwoord_dat_geen_lijst_is(monkeypatch, weigert):
    """Een foutobject als lijst lezen gaf een vals gat of een lege rekening."""
    fout = {"error": "verzonnen fout"}

    def verzoek(pad, token, methode="GET", *a, **k):
        if methode == weigert.upper():
            return fout
        return [{"id": "1"}] if methode == "GET" else [{"id": "1", "amount": "1.0"}]

    monkeypatch.setattr(moneybird_client, "verzoek", verzoek)
    client = moneybird_client.MoneybirdClient("t", "1", pauze=0)
    with pytest.raises(RuntimeError, match="Onverwacht antwoord"):
        client.mutaties_in_periode("2", "20261113..20261124")
    if weigert == "get":
        with pytest.raises(RuntimeError, match="Onverwacht antwoord"):
            client.aantal_mutaties("2", "20260101..20261231")


def test_aantal_mutaties_telt_alleen_de_ids_van_de_periode(monkeypatch):
    paden = []

    def verzoek(pad, token, methode="GET", *a, **k):
        paden.append((methode, pad))
        return [{"id": "1"}, {"id": "2"}]

    monkeypatch.setattr(moneybird_client, "verzoek", verzoek)
    client = moneybird_client.MoneybirdClient("t", "1", pauze=0)
    assert client.aantal_mutaties("2", "20260101..20261231") == 2
    assert paden == [("GET", "https://moneybird.com/api/v2/1/financial_mutations/synchronization.json"
                             "?filter=financial_account_id:2,period:20260101..20261231")]


def test_mutaties_is_verouderd():
    assert moneybird_client.MoneybirdClient.mutaties.__doc__.startswith(
        "Verouderd sinds 0.3.0, gaat weg in 0.4.0; gebruik mutaties_in_periode.")


def _nep_koppeling(monkeypatch, terugboekingen: list, nota_op: dict):
    """Nep-Moneybird: onverwerkte terugboekingen plus per dag de creditnota's van die dag."""
    from types import SimpleNamespace

    from mollie_moneybird_sync import sync

    opgehaald: list = []

    def verkoopfacturen_van_dag(datum):
        opgehaald.append(datum)
        return nota_op.get(datum, [])

    monkeypatch.setattr(sync, "_periodes_dit_en_vorig_jaar", lambda: ["20270101..20271231"])
    monkeypatch.setattr(sync, "MoneybirdClient", lambda *a: SimpleNamespace(
        onverwerkt_in_periode=lambda rekening, periode: list(terugboekingen),
        verkoopfacturen_van_dag=verkoopfacturen_van_dag,
    ))
    config = SimpleNamespace(moneybird_token="t", administratie_id="1", rekening_id="2")
    return sync, config, opgehaald


def _terugboeking(datum: str, kenmerk: str = "chb_verzonnenK") -> dict:
    return {"id": f"m-{datum}", "date": datum, "amount": "-1.0",
            "message": f"Mollie Chargeback - AC04 - {kenmerk} - tr_verzonnenX"}


NOTA_VERZONNEN = {"id": "n1", "invoice_id": "1", "total_price_incl_tax": "-1.0",
                  "reference": "SEPA Chargeback - chb_verzonnenK"}


def test_creditnota_drie_dagen_na_de_bankregel_wordt_gekoppeld(monkeypatch):
    sync, config, _ = _nep_koppeling(monkeypatch, [_terugboeking("2027-01-02")],
                                     {"2027-01-05": [NOTA_VERZONNEN]})
    uit = sync.koppel_terugboekingen(config, dry_run=True)
    assert uit["gekoppeld"] == 1
    assert uit["overgeslagen"] == []


def test_creditnota_drie_dagen_voor_de_bankregel_wordt_gekoppeld(monkeypatch):
    sync, config, _ = _nep_koppeling(monkeypatch, [_terugboeking("2027-01-02")],
                                     {"2026-12-30": [NOTA_VERZONNEN]})
    assert sync.koppel_terugboekingen(config, dry_run=True)["gekoppeld"] == 1


def test_creditnota_vier_dagen_ernaast_blijft_staan(monkeypatch):
    sync, config, _ = _nep_koppeling(monkeypatch, [_terugboeking("2027-01-02")],
                                     {"2027-01-06": [NOTA_VERZONNEN]})
    uit = sync.koppel_terugboekingen(config, dry_run=True)
    assert uit["gekoppeld"] == 0
    assert [o["reden"] for o in uit["overgeslagen"]] == ["geen creditnota met chb_verzonnenK"]


def test_elke_dag_een_keer_opgehaald_bij_overlappende_vensters(monkeypatch):
    sync, config, opgehaald = _nep_koppeling(
        monkeypatch,
        [_terugboeking("2027-01-02", "chb_verzonnenA"), _terugboeking("2027-01-03", "chb_verzonnenB")],
        {})
    sync.koppel_terugboekingen(config, dry_run=True)
    assert sorted(opgehaald) == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02",
                                 "2027-01-03", "2027-01-04", "2027-01-05", "2027-01-06"]


def test_venster_is_de_vereniging_van_de_daglijsten():
    from mollie_moneybird_sync import sync

    class Nep:
        def __init__(self):
            self.dagen: list = []

        def verkoopfacturen_van_dag(self, datum):
            self.dagen.append(datum)
            return [{"dag": datum}]

    nep, cache = Nep(), {"2027-01-01": [{"dag": "uit de cache"}]}
    uit = sync._facturen_in_venster(nep, "2027-01-02", cache, marge=1)
    assert uit == [{"dag": "uit de cache"}, {"dag": "2027-01-02"}, {"dag": "2027-01-03"}]
    assert nep.dagen == ["2027-01-02", "2027-01-03"]
    assert sync.TERUGBOEKING_MARGE_DAGEN == 3


def test_exacte_treffer_gaat_voor_een_voorvoegsel():
    exact = {"invoice_id": "1", "total_price_incl_tax": "-1.0",
             "reference": "SEPA Chargeback - chb_verzonnenAB"}
    langer = dict(exact, invoice_id="2", reference="SEPA Chargeback - chb_verzonnenABC")
    mutatie = {"amount": "-1.0", "message": "Mollie Chargeback - chb_verzonnenAB - tr_verzonnenX"}
    assert zoek_creditnota(mutatie, [langer, exact])[0] is exact


def test_twee_exacte_treffers_blijven_staan():
    exact = {"invoice_id": "1", "total_price_incl_tax": "-1.0",
             "reference": "SEPA Chargeback - chb_verzonnenAB"}
    tweede = dict(exact, invoice_id="2")
    mutatie = {"amount": "-1.0", "message": "Mollie Chargeback - chb_verzonnenAB - tr_verzonnenX"}
    nota, reden = zoek_creditnota(mutatie, [exact, tweede])
    assert nota is None
    assert "2 creditnota's" in reden
