"""De lock: standaard naast de state, en een oude lock is een fout."""
import errno
import fcntl
import os
import pathlib
import stat
import subprocess
import sys
import time

import pytest

from mollie_moneybird_sync import cli
from mollie_moneybird_sync.config import Config
from mollie_moneybird_sync.state import State
from mollie_moneybird_sync.sync import Lock, Vergrendeld

ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def _houd_vast(pad, minuten_oud) -> int:
    # Houdt de lock echt vast, zoals een lopende run: flock plus de eigen PID.
    fd = os.open(pad, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode())
        oud = time.time() - minuten_oud * 60
        os.utime(pad, (oud, oud))
    except BaseException:
        os.close(fd)
        raise
    return fd


def test_lock_staat_standaard_naast_de_state(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    assert Config().lock_pad == str(tmp_path / "mollie-moneybird-sync.lock")


def test_lock_path_uit_de_omgeving_wint(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCK_PATH", str(tmp_path / "elders.lock"))
    assert Config().lock_pad == str(tmp_path / "elders.lock")


def test_lockfile_blijft_staan_na_de_run(tmp_path):
    pad = tmp_path / "nieuw" / "run.lock"
    with Lock(str(pad)):
        assert pad.read_text() == str(os.getpid())
    assert pad.exists() and pad.read_text() == ""


def test_vergrendeld_draagt_de_leeftijd_van_de_lock(tmp_path):
    pad = tmp_path / "run.lock"
    fd = _houd_vast(pad, 90)
    try:
        with pytest.raises(Vergrendeld) as e:
            with Lock(str(pad)):
                raise AssertionError("de lock had bezet moeten zijn")
    finally:
        os.close(fd)
    assert 89 <= e.value.minuten <= 91


def test_verse_lock_is_gewone_overlap_met_exitcode_0(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 5)
    try:
        monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: (_ for _ in ()).throw(
            AssertionError("de run mocht niet starten")))
        assert cli.main([]) == 0
    finally:
        os.close(fd)
    assert "Er draait al een run" in caplog.text


def test_oude_lock_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 91)
    try:
        monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: (_ for _ in ()).throw(
            AssertionError("de run mocht niet starten")))
        assert cli.main([]) == 3
    finally:
        os.close(fd)
    assert "minuten oud" in caplog.text


def test_alarmgrens_is_instelbaar(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCK_ALERT_MINUTES", "10")
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 15)
    try:
        monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
        assert cli.main([]) == 3
    finally:
        os.close(fd)


def test_alarmgrens_standaard_90_en_leeg_is_standaard(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    assert Config().lock_alarm_minuten == 90
    monkeypatch.setenv("LOCK_ALERT_MINUTES", "")
    assert Config().lock_alarm_minuten == 90


def test_ongeldige_getallen_geven_een_leesbare_regel(monkeypatch, tmp_path, capsys):
    _instellingen(monkeypatch, tmp_path)
    for naam in ("LOCK_ALERT_MINUTES", "MAX_LOOKBACK_DAYS"):
        monkeypatch.setenv(naam, "abc")
        assert cli.main(["--dry-run"]) == 2
        fout = capsys.readouterr().err
        assert naam in fout
        assert "Traceback" not in fout
        monkeypatch.delenv(naam)


def test_nul_of_negatief_is_geen_geldige_waarde(monkeypatch, tmp_path, capsys):
    _instellingen(monkeypatch, tmp_path)
    for naam, waarde in (("MAX_LOOKBACK_DAYS", "0"), ("LOCK_ALERT_MINUTES", "-5")):
        monkeypatch.setenv(naam, waarde)
        assert cli.main(["--dry-run"]) == 2
        assert naam in capsys.readouterr().err
        monkeypatch.delenv(naam)


def test_hardlink_als_lock_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    doel = tmp_path / "elders.txt"
    _bezet(doel, 0)
    os.link(doel, tmp_path / "mollie-moneybird-sync.lock")
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "geen gewoon bestand" in caplog.text


def test_nieuwe_lockmap_heeft_rechten_700(tmp_path):
    pad = tmp_path / "nieuw" / "run.lock"
    with Lock(str(pad)):
        pass
    assert stat.S_IMODE((tmp_path / "nieuw").stat().st_mode) == 0o700


def test_onbekende_leeftijd_is_gewone_overlap(monkeypatch, tmp_path):
    _instellingen(monkeypatch, tmp_path)
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 120)
    try:
        monkeypatch.setattr(Lock, "_leeftijd_minuten", lambda self, fd: None)
        monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
        assert cli.main([]) == 0
    finally:
        os.close(fd)


def test_lock_met_tijd_in_de_toekomst_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    _bezet(tmp_path / "mollie-moneybird-sync.lock", -60 * 24)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "toekomst" in caplog.text


def test_symlink_als_lock_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    doel = tmp_path / "elders.txt"
    _bezet(doel, 0)
    os.symlink(doel, tmp_path / "mollie-moneybird-sync.lock")
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "geen gewoon bestand" in caplog.text
    assert doel.exists()


def test_lock_van_een_andere_gebruiker_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    _bezet(tmp_path / "mollie-moneybird-sync.lock", 0)
    echte_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: echte_uid + 1)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "andere gebruiker" in caplog.text


def test_twee_locks_tegelijk_sluiten_elkaar_uit(tmp_path):
    pad = str(tmp_path / "run.lock")
    with Lock(pad):
        with pytest.raises(Vergrendeld) as e:
            with Lock(pad):
                pass
        assert e.value.vreemd == "" and 0 <= e.value.minuten < 1


def test_lege_lockfile_die_vastgehouden_wordt_blokkeert(tmp_path):
    pad = tmp_path / "run.lock"  # de race: houder zonder PID
    fd = os.open(pad, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(Vergrendeld):
            with Lock(str(pad)):
                pass
        assert pad.exists()
    finally:
        os.close(fd)


KIND = """
import os, sys, time
sys.path.insert(0, {root!r})
from mollie_moneybird_sync.sync import Lock, Vergrendeld
while not os.path.exists({start!r}):
    time.sleep(0.005)
try:
    with Lock({pad!r}):
        open({uit!r}, "w").write("kreeg")
        time.sleep(1)
except Vergrendeld:
    open({uit!r}, "w").write("bezet")
"""


def test_gelijktijdige_start_van_twee_processen_laat_er_een_door(tmp_path):
    start = tmp_path / "start"
    pad = tmp_path / "run.lock"
    uit = [tmp_path / "uit1", tmp_path / "uit2"]
    kinderen = [
        subprocess.Popen([sys.executable, "-c", KIND.format(
            root=str(ROOT), start=str(start), pad=str(pad), uit=str(u))])
        for u in uit
    ]
    time.sleep(0.5)  # beide kinderen staan klaar en wachten op het startbestand
    start.write_text("")
    for k in kinderen:
        assert k.wait(timeout=30) == 0
    uitkomsten = [u.read_text() for u in uit]
    assert sorted(uitkomsten) == ["bezet", "kreeg"]


def test_achtergebleven_lockfile_van_v020_wordt_overgenomen(tmp_path):
    pad = tmp_path / "run.lock"
    pad.write_text("999999")
    with Lock(str(pad)):
        assert pad.read_text() == str(os.getpid())


def test_proces_dat_sterft_laat_de_lock_vrij(tmp_path):
    pad = str(tmp_path / "run.lock")
    code = ("import os,sys; sys.path.insert(0, %r); from mollie_moneybird_sync.sync import Lock; "
            "l = Lock(%r); l.__enter__(); os._exit(0)") % (str(ROOT), pad)
    subprocess.run([sys.executable, "-c", code], check=True)
    with Lock(pad):
        pass


def test_map_op_het_lockpad_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    (tmp_path / "mollie-moneybird-sync.lock").mkdir()
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "geen gewoon bestand" in caplog.text


@pytest.mark.skipif(os.geteuid() == 0, reason="root opent ook een bestand met rechten 000")
def test_lockfile_zonder_rechten_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    pad = tmp_path / "mollie-moneybird-sync.lock"
    pad.write_text("")
    pad.chmod(0)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "EACCES" in caplog.text


def test_flock_dat_niet_kan_geeft_exitcode_3(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)

    def geen_lock(fd, op):
        raise OSError(errno.ENOLCK, "No locks available")
    monkeypatch.setattr(fcntl, "flock", geen_lock)
    monkeypatch.setattr(cli, "draai", lambda cfg, dry_run: None)
    assert cli.main([]) == 3
    assert "ENOLCK" in caplog.text


def test_handmatig_geboekt_met_vreemde_lock_geeft_exitcode_3_zonder_traceback(
        monkeypatch, tmp_path, capsys):
    _instellingen(monkeypatch, tmp_path)
    State(str(tmp_path / "state.db")).sluit()
    (tmp_path / "mollie-moneybird-sync.lock").mkdir()
    assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 3
    assert "Traceback" not in capsys.readouterr().err


def test_melding_bij_oude_lock_raadt_verwijderen_af(monkeypatch, tmp_path, caplog):
    _instellingen(monkeypatch, tmp_path)
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 120)
    try:
        assert cli.main([]) == 3
    finally:
        os.close(fd)
    assert "Verwijder de lockfile niet" in caplog.text


def test_handmatig_geboekt_met_te_lang_bezette_lock_geeft_exitcode_3(
        monkeypatch, tmp_path, capsys):
    _instellingen(monkeypatch, tmp_path)
    State(str(tmp_path / "state.db")).sluit()
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 120)
    try:
        assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 3
    finally:
        os.close(fd)
    fout = capsys.readouterr().err
    assert "120 minuten oud" in fout and "Verwijder de lockfile niet" in fout


def test_handmatig_geboekt_met_jonge_bezette_lock_geeft_exitcode_1(
        monkeypatch, tmp_path, capsys):
    _instellingen(monkeypatch, tmp_path)
    State(str(tmp_path / "state.db")).sluit()
    fd = _houd_vast(tmp_path / "mollie-moneybird-sync.lock", 5)
    try:
        assert cli.main(["--handmatig-geboekt", "chb_verzonnenUSD"]) == 1
    finally:
        os.close(fd)
    assert "Probeer het zo opnieuw." in capsys.readouterr().err
