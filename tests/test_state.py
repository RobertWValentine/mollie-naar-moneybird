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
