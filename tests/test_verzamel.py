"""verzamel en de rondes: een record dat niet veilig te boeken is, laat de ronde zichtbaar falen."""
import logging
from types import SimpleNamespace

import pytest

from mollie_moneybird_sync import cli, sync
from mollie_moneybird_sync.http import HttpFout
from mollie_moneybird_sync.state import State

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
    assert len(fouten) == 1 and fouten[0]["sleutels"] == ["chb_verzonnenUSD"]


def test_refund_zonder_meegestuurde_betaling_haalt_de_betaling_op():
    mollie = NepMollie()
    regels = sync.verzamel(mollie, "2027-01-01", [])
    assert mollie.opgevraagd == ["tr_verzonnenRefund"]
    assert [r["amount"] for r in regels if r["sleutel"] == "re_verzonnenZonder"] == ["-5.00"]


def test_paypal_refund_na_ophalen_van_de_betaling_wordt_niet_geboekt():
    regels = sync.verzamel(NepMollie(methode="paypal"), "2027-01-01", [])
    assert "re_verzonnenZonder" not in [r["sleutel"] for r in regels]


class MollieZonderBetaling(NepMollie):
    def __init__(self, status=404):
        super().__init__()
        self.status = status

    def betaling(self, betaling_id):
        raise HttpFout(self.status, "verzonnen")


@pytest.mark.parametrize("status", [404, 410])
def test_betaling_die_niet_bestaat_telt_als_niet_te_boeken_en_de_rest_gaat_door(status):
    fouten = []
    regels = sync.verzamel(MollieZonderBetaling(status), "2027-01-01", fouten)
    assert sorted(r["sleutel"] for r in regels) == ["chb_verzonnenEUR"]
    assert any(f["sleutels"] == ["re_verzonnenZonder"] and str(status) in f["melding"] for f in fouten)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_tijdelijke_fout_of_tokenfout_bij_ophalen_stopt_de_ronde(status):
    """Zegt niets over de refund: niet per refund melden (dan zou iemand hem met de hand boeken)."""
    with pytest.raises(HttpFout):
        sync.verzamel(MollieZonderBetaling(status), "2027-01-01", [])


def test_al_geboekte_refund_haalt_geen_betaling_op():
    mollie = NepMollie()
    sync.verzamel(mollie, "2027-01-01", [], gezien=lambda s: s == "re_verzonnenZonder")
    assert mollie.opgevraagd == []


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


class NepStateNieuw(NepState):
    def gezien(self, sleutel):
        return False


def _nep_ronde(monkeypatch, state=NepState, mutaties=()):
    mollie = NepMollie()
    monkeypatch.setattr(sync, "MollieClient", lambda token: mollie)
    monkeypatch.setattr(sync, "MoneybirdClient", lambda *a: SimpleNamespace(mutaties=lambda rekening: list(mutaties)))
    monkeypatch.setattr(sync, "State", lambda pad: state())
    monkeypatch.setattr(sync, "_controleer_intentie", lambda state: None)
    config = SimpleNamespace(mollie_token="m", moneybird_token="mb", administratie_id="1",
                             rekening_id="2", state_pad="x", max_terugkijk_dagen=14)
    return config, mollie


def test_al_geboekt_record_telt_niet_als_niet_te_boeken(monkeypatch):
    """Na 1 januari 2027 mist ook een al geboekte terugboeking haar settlementAmount.
    Telt die mee, dan wordt de ronde onterecht rood en boekt wie hem met de hand boekt dubbel."""
    config, mollie = _nep_ronde(monkeypatch)
    assert sync.draai(config)["niet_te_boeken"] == 0
    assert sync.draai(config, dry_run=True)["niet_te_boeken"] == 0
    assert mollie.opgevraagd == []


def test_teruggedraaide_terugboeking_telt_tot_ook_de_terugdraaiing_geboekt_is(monkeypatch):
    class AlleenOrigineel(NepState):
        def gezien(self, sleutel):
            return sleutel == "chb_verzonnenUSD"

    config, mollie = _nep_ronde(monkeypatch, state=AlleenOrigineel)
    mollie.chargebacks = lambda grens: [dict(CHARGEBACK_USD, reversedAt="2027-01-07T12:00:00+00:00")]
    assert sync.draai(config, dry_run=True)["niet_te_boeken"] == 1


def test_aansluiten_telt_wat_niet_geboekt_is_en_niet_wat_al_in_moneybird_staat(monkeypatch):
    config, _ = _nep_ronde(monkeypatch, state=NepStateNieuw)
    assert sync.aansluiten(config, dagen=3, dry_run=True, forceer_leeg=True)["niet_te_boeken"] == 1
    al_daar = [{"id": "1", "date": "2027-01-05", "amount": "-40.00",
                "message": "Mollie Chargeback - AC06 - x - chb_verzonnenUSD - tr_verzonnenUSD"}]
    config, _ = _nep_ronde(monkeypatch, state=NepStateNieuw, mutaties=al_daar)
    assert sync.aansluiten(config, dagen=3, dry_run=True)["niet_te_boeken"] == 0


def test_draai_met_nieuwe_regels_geeft_niet_te_boeken_terug(monkeypatch):
    """De echte gevallen: een droge ronde en een schrijvende ronde met nieuwe regels."""
    config, _ = _nep_ronde(monkeypatch, state=NepStateNieuw)
    droog = sync.draai(config, dry_run=True)
    assert droog["regels"] == 2 and droog["niet_te_boeken"] == 1
    monkeypatch.setattr(sync, "_schrijf", lambda *a: "afschrift_1")
    echt = sync.draai(config)
    assert echt["afschrift_id"] == "afschrift_1" and echt["niet_te_boeken"] == 1


def test_refund_zonder_paymentid_of_zonder_betaalmethode_telt_als_niet_te_boeken():
    mollie = NepMollie()
    kaal = {k: v for k, v in REFUND_ZONDER_BETALING.items() if k != "paymentId"}
    zonder_methode = dict(REFUND_ZONDER_BETALING, id="re_verzonnenLeeg", _embedded={"payment": {"id": "tr_x"}})
    mollie.refunds = lambda grens: [kaal, zonder_methode]
    fouten = []
    regels = sync.verzamel(mollie, "2027-01-01", fouten)
    assert mollie.opgevraagd == []
    assert not [r for r in regels if r["sleutel"].startswith("re_")]
    assert len([f for f in fouten if "re_verzonnen" in str(f)]) == 2


def test_controleer_meldt_een_ontoetsbare_afrekening_als_afwijkend_en_gaat_door():
    from mollie_moneybird_sync import controle

    def afrekening(stl):
        return {"id": stl, "status": "paidout", "settledAt": "2027-01-06T00:00:00+00:00",
                "amount": {"value": "0.00", "currency": "EUR"}, "periods": {}}

    mollie = SimpleNamespace(
        afrekeningen=lambda: [afrekening("stl_verzonnenA"), afrekening("stl_verzonnenB")],
        betalingen_van_afrekening=lambda stl: [],
        chargebacks_van_afrekening=lambda stl: [CHARGEBACK_USD] if stl == "stl_verzonnenA" else [],
    )
    assert [u["sluit"] for u in controle.controleer(mollie)] == [False, True]


def _omgeving(monkeypatch, tmp_path):
    for naam, waarde in (("MOLLIE_TOKEN", "access_x"), ("MONEYBIRD_TOKEN", "mb"),
                         ("MONEYBIRD_ADMINISTRATION_ID", "111"), ("MONEYBIRD_FINANCIAL_ACCOUNT_ID", "222")):
        monkeypatch.setenv(naam, waarde)
    monkeypatch.setenv("LOCK_PATH", str(tmp_path / "test.lock"))


def test_aansluiten_met_niet_te_boeken_geeft_exitcode_1_en_meldt_het(monkeypatch, tmp_path, capsys):
    _omgeving(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "aansluiten", lambda cfg, **k: {
        "bestaande_mutaties": 5, "regels": 3, "al_geboekt": 2, "ontbreekt": 1,
        "afschrift_id": "x", "niet_te_boeken": 1})
    assert cli.main(["--aansluiten"]) == 1
    assert "1 niet te boeken, zie het log" in capsys.readouterr().err


def test_ronde_met_niet_te_boeken_regels_geeft_exitcode_1(monkeypatch, tmp_path):
    _omgeving(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 1})
    assert cli.main([]) == 1
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: {"regels": 3, "afschrift_id": "x", "niet_te_boeken": 0})
    assert cli.main([]) == 0


def _handmatig_omgeving(monkeypatch, tmp_path, mollie=None):
    _omgeving(monkeypatch, tmp_path)
    pad = tmp_path / "state.db"
    monkeypatch.setenv("STATE_PATH", str(pad))
    State(str(pad)).sluit()  # een bestaande, lege state
    nep = mollie or NepMollie()
    monkeypatch.setattr(sync, "MollieClient", lambda token: nep)
    return pad


def _gezien_in(pad, kenmerk):
    state = State(str(pad))
    try:
        return state.gezien(kenmerk)
    finally:
        state.sluit()


@pytest.mark.parametrize("kenmerk", ["chb_verzonnenUSD", " chb_verzonnenUSD "])
def test_handmatig_geboekt_legt_een_open_kenmerk_vast(monkeypatch, tmp_path, capsys, kenmerk):
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    assert cli.main(["--handmatig-geboekt", kenmerk]) == 0
    assert "staat nu als geboekt" in capsys.readouterr().out
    assert _gezien_in(pad, "chb_verzonnenUSD")


def test_handmatig_geboekt_kent_ook_de_terugdraaiing_en_een_refund(monkeypatch, tmp_path):
    mollie = NepMollie()
    mollie.chargebacks = lambda grens: [dict(CHARGEBACK_USD, reversedAt="2027-01-07T12:00:00+00:00")]
    mollie.refunds = lambda grens: [{k: v for k, v in REFUND_ZONDER_BETALING.items() if k != "paymentId"}]
    pad = _handmatig_omgeving(monkeypatch, tmp_path, mollie)
    for kenmerk in ("chb_verzonnenUSD:teruggedraaid", "re_verzonnenZonder"):
        assert cli.main(["--handmatig-geboekt", kenmerk]) == 0
        assert _gezien_in(pad, kenmerk)


@pytest.mark.parametrize("kenmerk", ["", "tr_verzonnen", "stl_verzonnen", "chb_x;drop", "re_",
                                     "re_verzonnenZonder:teruggedraaid", "re_verzonnenAnders"])
def test_handmatig_geboekt_weigert_wat_niet_open_staat(monkeypatch, tmp_path, kenmerk):
    """Ook een leeg kenmerk (een lege variabele in een script) mag niet doorvallen naar een gewone ronde."""
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "draai", lambda *a, **k: pytest.fail("een gewone ronde gestart"))
    assert cli.main(["--handmatig-geboekt", kenmerk]) == 2
    assert not _gezien_in(pad, kenmerk.strip())


def test_handmatig_geboekt_schrijft_niets_bij_dry_run(monkeypatch, tmp_path, capsys):
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD", "--dry-run"]) == 0
    assert "zou chb_verzonnenUSD" in capsys.readouterr().out
    assert not _gezien_in(pad, "chb_verzonnenUSD")


def test_handmatig_geboekt_weigert_zonder_state_of_met_een_andere_opdracht(monkeypatch, tmp_path):
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD", "--aansluiten"]) == 2
    assert not _gezien_in(pad, "chb_verzonnenUSD")
    pad.unlink()
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 2
    assert not pad.exists()


def test_alleen_niet_te_boeken_en_niets_nieuws_wordt_gemeld(monkeypatch):
    """Het gewone productiegeval: verder niets nieuws, één open record. De hartslag moet rood."""
    class AllesBehalveUSD(NepState):
        def gezien(self, sleutel):
            return sleutel != "chb_verzonnenUSD"

    config, _ = _nep_ronde(monkeypatch, state=AllesBehalveUSD)
    uit = sync.draai(config)
    assert uit["regels"] == 0 and uit["niet_te_boeken"] == 1


def test_melding_noemt_de_kenmerken_die_nog_vastgelegd_moeten_worden(caplog):
    fouten = [{"sleutels": ["chb_verzonnenUSD", "chb_verzonnenUSD:teruggedraaid"],
               "melding": "chb_verzonnenUSD in USD zonder settlementAmount"}]
    with caplog.at_level(logging.ERROR):
        assert sync._meld(fouten, lambda s: s == "chb_verzonnenUSD") == 1
    assert "vastleggen: chb_verzonnenUSD:teruggedraaid" in caplog.text


class OnthoudtState(NepStateNieuw):
    def __init__(self):
        self.gemarkeerd = []

    def markeer(self, ids, afschrift_id, datum=""):
        self.gemarkeerd += [(i, afschrift_id) for i in ids]


def test_aansluiten_legt_een_niet_te_boeken_record_dat_al_in_moneybird_staat_vast(monkeypatch):
    """Anders meldt de volgende gewone ronde hem weer, en boekt wie de README volgt dubbel."""
    state = OnthoudtState()
    al_daar = [{"id": "1", "date": "2027-01-05", "amount": "-40.00",
                "message": "Mollie Chargeback - AC06 - x - chb_verzonnenUSD - tr_verzonnenUSD"}]
    config, _ = _nep_ronde(monkeypatch, state=lambda: state, mutaties=al_daar)
    monkeypatch.setattr(sync, "_schrijf", lambda *a: "afschrift_1")
    assert sync.aansluiten(config, dagen=3)["niet_te_boeken"] == 0
    assert ("chb_verzonnenUSD", "bestond-al") in state.gemarkeerd


def test_aansluiten_herkent_ook_de_terugdraaiing_in_moneybird_aan_het_teken(monkeypatch):
    bericht = "Mollie Chargeback - chb_verzonnenUSD - tr_verzonnenUSD"
    alleen_af = [{"id": "1", "date": "2027-01-05", "amount": "-40.00", "message": bericht}]
    beide = alleen_af + [{"id": "2", "date": "2027-01-07", "amount": "40.00", "message": "Reversed " + bericht}]
    for mutaties, verwacht in ((alleen_af, 1), (beide, 0)):
        config, mollie = _nep_ronde(monkeypatch, state=NepStateNieuw, mutaties=mutaties)
        mollie.chargebacks = lambda grens: [dict(CHARGEBACK_USD, reversedAt="2027-01-07T12:00:00+00:00")]
        assert sync.aansluiten(config, dagen=3, dry_run=True)["niet_te_boeken"] == verwacht


def test_handmatig_geboekt_bij_storing_of_slot_legt_niets_vast(monkeypatch, tmp_path, capsys):
    pad = _handmatig_omgeving(monkeypatch, tmp_path, MollieZonderBetaling(503))
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 1
    assert "niets vastgelegd" in capsys.readouterr().err
    assert not _gezien_in(pad, "chb_verzonnenUSD")
    pad = _handmatig_omgeving(monkeypatch, tmp_path, MollieZonderBetaling(401))
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 1
    assert "MOLLIE_TOKEN" in capsys.readouterr().err
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    with sync.Lock(str(tmp_path / "test.lock")):
        assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 1
    assert not _gezien_in(pad, "chb_verzonnenUSD")


def test_handmatig_geboekt_volgt_het_venster_van_dagen(monkeypatch, tmp_path):
    """--aansluiten kijkt 30 dagen terug; een record van daar moet ook vast te leggen zijn."""
    vensters = []
    pad = _handmatig_omgeving(monkeypatch, tmp_path)
    echt = sync.verzamel
    monkeypatch.setattr(sync, "verzamel", lambda mollie, grens, *a: vensters.append(grens) or echt(mollie, grens, *a))
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD", "--dagen", "30", "--dry-run"]) == 0
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD", "--dry-run"]) == 0
    assert vensters[0] < vensters[1]
    assert not _gezien_in(pad, "chb_verzonnenUSD")


def test_aansluiten_herkent_een_met_de_hand_geboekte_refund(monkeypatch):
    al_daar = [{"id": "1", "date": "2027-01-05", "amount": "-5.00",
                "message": "Mollie Refund - re_verzonnenZonder - tr_verzonnenRefund"}]
    config, mollie = _nep_ronde(monkeypatch, state=NepStateNieuw, mutaties=al_daar)
    mollie.chargebacks = lambda grens: []
    mollie.refunds = lambda grens: [{k: v for k, v in REFUND_ZONDER_BETALING.items() if k != "paymentId"}]
    assert sync.aansluiten(config, dagen=3, dry_run=True)["niet_te_boeken"] == 0


def test_controleer_noemt_een_ontoetsbare_afrekening_zonder_nan():
    from mollie_moneybird_sync import controle

    mollie = SimpleNamespace(
        betalingen_van_afrekening=lambda stl: [],
        chargebacks_van_afrekening=lambda stl: [CHARGEBACK_USD],
    )
    uit = controle.toets_afrekening(mollie, {"id": "stl_verzonnen", "status": "paidout",
                                             "settledAt": "2027-01-06T00:00:00+00:00",
                                             "amount": {"value": "0.00", "currency": "EUR"}, "periods": {}})
    assert uit["toetsbaar"] is False and uit["sluit"] is False
    assert uit["verschil"] == uit["verschil"]  # geen NaN
