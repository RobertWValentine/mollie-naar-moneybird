import sqlite3

import pytest

from mollie_moneybird_sync import sync
from mollie_moneybird_sync.state import State


def test_onthoudt_verwerkte_mutaties(tmp_path):
    s = State(str(tmp_path / "state.db"))
    assert s.leeg()
    assert not s.gezien("baltr_a")

    s.markeer(["baltr_a", "baltr_b"], afschrift_id="123", datum="2026-08-10")
    assert s.gezien("baltr_a")
    assert s.gezien("baltr_b")
    assert not s.gezien("baltr_c")
    assert s.aantal() == 2


def test_dubbel_markeren_telt_niet_dubbel(tmp_path):
    """Dit beschermt tegen dubbel boeken als een ronde twee keer loopt."""
    s = State(str(tmp_path / "state.db"))
    s.markeer(["baltr_a"], "123")
    s.markeer(["baltr_a"], "456")
    assert s.aantal() == 1


def test_blijft_bestaan_na_herstart(tmp_path):
    pad = str(tmp_path / "state.db")
    s = State(pad)
    s.markeer(["baltr_a"], "123")
    s.sluit()

    opnieuw = State(pad)
    assert opnieuw.gezien("baltr_a")


def test_intentie_wordt_onthouden_en_gewist(tmp_path):
    """Sterft een run tussen het schrijven en het onthouden, dan moet de
    volgende run dat merken in plaats van alles opnieuw te boeken."""
    s = State(str(tmp_path / "state.db"))
    assert s.openstaande_intentie() is None

    s.zet_intentie("mollie-2026-08-12-900-abc123", 900)
    rij = s.openstaande_intentie()
    assert rij[0] == "mollie-2026-08-12-900-abc123"
    assert rij[1] == 900

    s.wis_intentie("mollie-2026-08-12-900-abc123")
    assert s.openstaande_intentie() is None


def test_state_onthoudt_open_records_tot_ze_geboekt_zijn(tmp_path):
    s = State(str(tmp_path / "s.db"))
    s.onthoud_open([("chb_verzonnenA", "melding A"), ("", "leeg")])
    assert s.open_niet_geboekt() == [("chb_verzonnenA", "melding A")]
    s.markeer(["chb_verzonnenA"], "handmatig", "2027-01-05")
    assert s.open_niet_geboekt() == []


def test_open_records_oudste_eerst_en_te_vergeten(tmp_path):
    s = State(str(tmp_path / "s.db"))
    s.onthoud_open([("chb_verzonnenB", "B"), ("re_verzonnenC", "C")])
    s.onthoud_open([("chb_verzonnenB", "B opnieuw")])
    assert s.open_niet_geboekt() == [("chb_verzonnenB", "B"), ("re_verzonnenC", "C")]
    s.vergeet_open(["chb_verzonnenB"])
    assert s.open_niet_geboekt() == [("re_verzonnenC", "C")]


def test_state_van_0_2_0_zonder_open_tabel_werkt(tmp_path):
    """Een bestaande state heeft de tabel nog niet: aanmaken bij gebruik, geen migratie."""
    pad = str(tmp_path / "s.db")
    s = State(pad)
    s.markeer(["chb_verzonnenA"], "123")
    s.db.execute("DROP TABLE IF EXISTS open_niet_te_boeken")
    s.sluit()
    opnieuw = State(pad)
    assert opnieuw.open_niet_geboekt() == []
    opnieuw.vergeet_open(["chb_verzonnenA"])
    assert opnieuw.gezien("chb_verzonnenA")


def test_melding_bij_open_intentie_wijst_de_veilige_weg(tmp_path):
    s = State(str(tmp_path / "s.db"))
    s.zet_intentie("mollie-2027-01-05-3-abc", 3)
    with pytest.raises(RuntimeError) as e:
        sync._controleer_intentie(s)
    tekst = str(e.value)
    assert "--verwijder-afschrift" in tekst and "--wis-intentie" in tekst
    assert "--aansluiten" not in tekst and "nooit" in tekst


def test_state_onthoudt_het_begin_van_de_laatste_ronde(tmp_path):
    pad = str(tmp_path / "s.db")
    s = State(pad)
    assert s.laatste_ronde("mollie") is None
    s.zet_ronde("mollie", "2026-11-10T04:17:02+00:00")
    s.zet_ronde("mollie", "2026-11-10T05:17:02+00:00")
    s.sluit()
    opnieuw = State(pad)
    assert opnieuw.laatste_ronde("mollie") == "2026-11-10T05:17:02+00:00"
    assert opnieuw.laatste_ronde("paypal") is None
    opnieuw.sluit()


def test_state_van_v020_zonder_nieuwe_tabellen_werkt(tmp_path):
    pad = tmp_path / "oud.db"
    con = sqlite3.connect(pad)
    con.execute("CREATE TABLE verwerkt (id TEXT PRIMARY KEY, afschrift_id TEXT, datum TEXT,"
                " toegevoegd_op TEXT DEFAULT CURRENT_TIMESTAMP)")
    con.commit()
    con.close()
    s = State(str(pad))
    assert s.laatste_ronde("mollie") is None and s.open_niet_geboekt() == []
    s.sluit()
