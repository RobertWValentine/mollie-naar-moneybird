"""verzamel en de rondes: een record dat niet veilig te boeken is, laat de ronde zichtbaar falen."""
from types import SimpleNamespace

from mollie_moneybird_sync import cli, sync
from mollie_moneybird_sync.http import HttpFout

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


class MollieZonderBetaling(NepMollie):
    def betaling(self, betaling_id):
        raise HttpFout(404, "not found")


def test_mislukt_ophalen_van_de_betaling_telt_als_niet_te_boeken_en_de_rest_gaat_door():
    fouten = []
    regels = sync.verzamel(MollieZonderBetaling(), "2027-01-01", fouten)
    assert sorted(r["sleutel"] for r in regels) == ["chb_verzonnenEUR"]
    assert any("re_verzonnenZonder" in f and "404" in f for f in fouten)


def test_refund_in_behandeling_haalt_geen_betaling_op():
    mollie = NepMollie()
    mollie.refunds = lambda grens: [dict(REFUND_ZONDER_BETALING, status="pending")]
    sync.verzamel(mollie, "2027-01-01", [])
    assert mollie.opgevraagd == []


class NepState:
    def gezien(self, sleutel):
        return True

    def sluit(self):
        pass


def _nep_ronde(monkeypatch):
    monkeypatch.setattr(sync, "MollieClient", lambda token: NepMollie())
    monkeypatch.setattr(sync, "MoneybirdClient", lambda *a: SimpleNamespace(mutaties=lambda rekening: []))
    monkeypatch.setattr(sync, "State", lambda pad: NepState())
    monkeypatch.setattr(sync, "_controleer_intentie", lambda state: None)
    return SimpleNamespace(mollie_token="m", moneybird_token="mb", administratie_id="1",
                           rekening_id="2", state_pad="x", max_terugkijk_dagen=14)


def test_draai_geeft_het_aantal_niet_te_boeken_terug(monkeypatch):
    config = _nep_ronde(monkeypatch)
    assert sync.draai(config)["niet_te_boeken"] == 1
    assert sync.draai(config, dry_run=True)["niet_te_boeken"] == 1


def test_aansluiten_geeft_het_aantal_niet_te_boeken_terug(monkeypatch):
    config = _nep_ronde(monkeypatch)
    resultaat = sync.aansluiten(config, dagen=3, dry_run=True, forceer_leeg=True)
    assert resultaat["niet_te_boeken"] == 1


def test_ronde_met_niet_te_boeken_regels_geeft_exitcode_1(monkeypatch, tmp_path):
    for naam, waarde in (("MOLLIE_TOKEN", "access_x"), ("MONEYBIRD_TOKEN", "mb"),
                         ("MONEYBIRD_ADMINISTRATION_ID", "111"), ("MONEYBIRD_FINANCIAL_ACCOUNT_ID", "222")):
        monkeypatch.setenv(naam, waarde)
    monkeypatch.setenv("LOCK_PATH", str(tmp_path / "test.lock"))
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 1})
    assert cli.main([]) == 1
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 0})
    assert cli.main([]) == 0
