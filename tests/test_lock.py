"""De lock: standaard naast de state, en een oude lock is een fout."""
import os
import time

from mollie_moneybird_sync import cli
from mollie_moneybird_sync.config import Config
from mollie_moneybird_sync.sync import Lock, Vergrendeld


def _instellingen(monkeypatch, tmp_path):
    for naam, waarde in [("MOLLIE_TOKEN", "access_x"), ("MONEYBIRD_TOKEN", "mb"),
                         ("MONEYBIRD_ADMINISTRATION_ID", "111"),
                         ("MONEYBIRD_FINANCIAL_ACCOUNT_ID", "222")]:
        monkeypatch.setenv(naam, waarde)
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.delenv("LOCK_PATH", raising=False)
    monkeypatch.delenv("LOCK_ALERT_MINUTES", raising=False)


def _bezet(pad, minuten_oud):
    # Een lockfile met onze eigen PID: dat proces draait aantoonbaar nog.
    with open(pad, "w") as f:
        f.write(str(os.getpid()))
    oud = time.time() - minuten_oud * 60
    os.utime(pad, (oud, oud))


def test_lock_staat_standaard_naast_de_state(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    assert Config().lock_pad == str(tmp_path / "mollie-moneybird-sync.lock")


def test_lock_path_uit_de_omgeving_wint(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCK_PATH", str(tmp_path / "elders.lock"))
    assert Config().lock_pad == str(tmp_path / "elders.lock")


def test_lock_maakt_een_ontbrekende_map_aan(tmp_path):
    pad = tmp_path / "nieuw" / "run.lock"
    with Lock(str(pad)):
        assert pad.exists()
    assert not pad.exists()


def test_vergrendeld_draagt_de_leeftijd_van_de_lock(tmp_path):
    pad = tmp_path / "run.lock"
    _bezet(pad, 90)
    try:
        with Lock(str(pad)):
            raise AssertionError("de lock had bezet moeten zijn")
    except Vergrendeld as e:
        assert 89 <= e.minuten <= 91


def test_verse_lock_is_gewone_overlap_met_exitcode_0(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    _bezet(tmp_path / "mollie-moneybird-sync.lock", 5)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: (_ for _ in ()).throw(
        AssertionError("de run mocht niet starten")))
    assert cli.main([]) == 0
    assert "Er draait al een run" in caplog.text


def test_oude_lock_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    _bezet(tmp_path / "mollie-moneybird-sync.lock", 61)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: (_ for _ in ()).throw(
        AssertionError("de run mocht niet starten")))
    assert cli.main([]) == 3
    assert "minuten oud" in caplog.text


def test_alarmgrens_is_instelbaar(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCK_ALERT_MINUTES", "10")
    _bezet(tmp_path / "mollie-moneybird-sync.lock", 15)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
