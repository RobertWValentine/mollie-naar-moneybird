"""verzamel en de rondes: een record dat niet veilig te boeken is, laat de ronde zichtbaar falen."""
from mollie_moneybird_sync import cli, sync

CHARGEBACK_USD = {
    "id": "chb_verzonnenUSD",
    "amount": {"value": "43.38", "currency": "USD"},
    "createdAt": "2027-01-05T12:00:00+00:00",
    "reason": {"code": "AC06", "description": "Account blocked"},
    "paymentId": "tr_verzonnenUSD",
}
CHARGEBACK_EUR = {
    "id": "chb_verzonnenEUR",
    "amount": {"value": "2.50", "currency": "EUR"},
    "createdAt": "2027-01-05T12:00:00+00:00",
    "reason": {"code": "AC06", "description": "Account blocked"},
    "paymentId": "tr_verzonnenEUR",
}
REFUND_ZONDER_BETALING = {
    "id": "re_verzonnenZonder",
    "status": "refunded",
    "amount": {"value": "5.00", "currency": "EUR"},
    "description": "Terugbetaling",
    "createdAt": "2027-01-05T10:00:00+00:00",
    "paymentId": "tr_verzonnenRefund",
}


class NepMollie:
    def __init__(self, methode="ideal"):
        self.methode = methode
        self.opgevraagd = []

    def betalingen(self, grens):
        return []

    def chargebacks(self, grens):
        return [CHARGEBACK_USD, CHARGEBACK_EUR]

    def refunds(self, grens):
        return [REFUND_ZONDER_BETALING]

    def afrekeningen(self):
        return []

    def betaling(self, betaling_id):
        self.opgevraagd.append(betaling_id)
        return {"id": betaling_id, "method": self.methode}


def test_verzamel_boekt_de_rest_en_telt_wat_niet_te_boeken_is():
    fouten = []
    mollie = NepMollie()
    regels = sync.verzamel(mollie, "2027-01-01", fouten)
    assert sorted(r["sleutel"] for r in regels) == ["chb_verzonnenEUR", "re_verzonnenZonder"]
    assert len(fouten) == 1 and "chb_verzonnenUSD" in fouten[0]


def test_refund_zonder_meegestuurde_betaling_haalt_de_betaling_op():
    mollie = NepMollie()
    regels = sync.verzamel(mollie, "2027-01-01", [])
    assert mollie.opgevraagd == ["tr_verzonnenRefund"]
    assert [r["amount"] for r in regels if r["sleutel"] == "re_verzonnenZonder"] == ["-5.00"]


def test_paypal_refund_na_ophalen_van_de_betaling_wordt_niet_geboekt():
    regels = sync.verzamel(NepMollie(methode="paypal"), "2027-01-01", [])
    assert "re_verzonnenZonder" not in [r["sleutel"] for r in regels]


def test_ronde_met_niet_te_boeken_regels_geeft_exitcode_1(monkeypatch, tmp_path):
    for naam, waarde in (("MOLLIE_TOKEN", "access_x"), ("MONEYBIRD_TOKEN", "mb"),
                         ("MONEYBIRD_ADMINISTRATION_ID", "111"), ("MONEYBIRD_FINANCIAL_ACCOUNT_ID", "222")):
        monkeypatch.setenv(naam, waarde)
    monkeypatch.setenv("LOCK_PATH", str(tmp_path / "test.lock"))
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 1})
    assert cli.main([]) == 1
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 0})
    assert cli.main([]) == 0
