"""Toetst dat elke opdracht alleen de instellingen eist die hij nodig heeft."""
import pytest

from mollie_moneybird_sync import cli, config

VARIABELEN = ["MOLLIE_TOKEN", "MONEYBIRD_TOKEN", "MONEYBIRD_ADMINISTRATION_ID",
              "MONEYBIRD_FINANCIAL_ACCOUNT_ID", "KEYCHAIN_ACCOUNT"]


@pytest.fixture(autouse=True)
def schone_omgeving(monkeypatch):
    for naam in VARIABELEN:
        monkeypatch.delenv(naam, raising=False)
    monkeypatch.setattr(config, "_keychain", lambda service, account: None)


def test_rekeningen_zonder_mollie_token_en_rekening(monkeypatch, capsys):
    """--rekeningen is er om het rekening-ID te vinden, dus mag het niet eisen."""
    monkeypatch.setenv("MONEYBIRD_TOKEN", "mb")
    monkeypatch.setenv("MONEYBIRD_ADMINISTRATION_ID", "111")

    class NepMoneybird:
        def __init__(self, token, administratie_id):
            assert (token, administratie_id) == ("mb", "111")

        def rekeningen(self):
            return [{"id": "222", "type": "BankAccount", "name": "Mollie"}]

    monkeypatch.setattr(cli, "MoneybirdClient", NepMoneybird)
    assert cli.main(["--rekeningen"]) == 0
    assert "222" in capsys.readouterr().out


def test_ontbrekende_instelling_geeft_een_leesbare_regel(capsys):
    code = cli.main(["--rekeningen"])
    uit = capsys.readouterr()
    assert code == 2
    assert "MONEYBIRD_TOKEN" in uit.err
    assert "Traceback" not in uit.err + uit.out


def test_gewone_ronde_meldt_ontbrekend_rekening_id(monkeypatch, capsys):
    monkeypatch.setenv("MOLLIE_TOKEN", "access_x")
    monkeypatch.setenv("MONEYBIRD_TOKEN", "mb")
    monkeypatch.setenv("MONEYBIRD_ADMINISTRATION_ID", "111")
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: cfg.rekening_id)
    assert cli.main(["--dry-run"]) == 2
    uit = capsys.readouterr()
    assert "MONEYBIRD_FINANCIAL_ACCOUNT_ID" in uit.err
    assert "--rekeningen" in uit.err
    assert "Traceback" not in uit.err + uit.out


def test_ontbrekend_rekening_id_vóór_enig_netwerkverkeer(monkeypatch, capsys):
    """Eerst alle instellingen toetsen, dan pas Mollie bellen."""
    monkeypatch.setenv("MOLLIE_TOKEN", "access_x")
    monkeypatch.setenv("MONEYBIRD_TOKEN", "mb")
    monkeypatch.setenv("MONEYBIRD_ADMINISTRATION_ID", "111")

    def geen_netwerk(*a, **k):
        raise AssertionError("er werd gebeld voordat de instellingen klopten")

    monkeypatch.setattr(cli, "draai", geen_netwerk)
    assert cli.main(["--dry-run"]) == 2
    assert "MONEYBIRD_FINANCIAL_ACCOUNT_ID" in capsys.readouterr().err


def test_geweigerd_token_geeft_een_leesbare_regel(monkeypatch, capsys):
    from mollie_moneybird_sync.http import HttpFout

    for naam, waarde in [("MOLLIE_TOKEN", "access_x"), ("MONEYBIRD_TOKEN", "mb"),
                         ("MONEYBIRD_ADMINISTRATION_ID", "111"),
                         ("MONEYBIRD_FINANCIAL_ACCOUNT_ID", "222")]:
        monkeypatch.setenv(naam, waarde)
    monkeypatch.setenv("LOCK_PATH", "/tmp/mollie-moneybird-sync-test.lock")

    def geweigerd(cfg, dry_run):
        raise HttpFout(401, '{"detail":"Invalid token"}', url="https://api.mollie.com/v2/payments")

    monkeypatch.setattr(cli, "draai", geweigerd)
    assert cli.main(["--dry-run"]) == 1
    uit = capsys.readouterr()
    assert "Mollie" in uit.err
    assert "MOLLIE_TOKEN" in uit.err
    assert "Traceback" not in uit.err + uit.out
