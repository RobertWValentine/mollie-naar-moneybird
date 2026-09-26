from mollie_moneybird_sync.tijd import lokale_datum


def test_late_avond_utc_valt_in_nederland_op_de_volgende_dag():
    """Precies het venster waarin Mollie zijn incasso's verwerkt."""
    assert lokale_datum("2026-08-11T23:31:16+00:00") == "2026-08-12"
    assert lokale_datum("2026-08-11T22:00:00+00:00") == "2026-08-12"


def test_vroeg_op_de_avond_blijft_dezelfde_dag():
    assert lokale_datum("2026-08-11T21:59:00+00:00") == "2026-08-11"
    assert lokale_datum("2026-08-11T05:38:45+00:00") == "2026-08-11"


def test_wintertijd_schuift_een_uur_minder_op():
    """In de winter is Nederland UTC+1, dus de grens ligt op 23:00."""
    assert lokale_datum("2026-01-15T22:30:00+00:00") == "2026-01-15"
    assert lokale_datum("2026-01-15T23:30:00+00:00") == "2026-01-16"


def test_z_notatie_werkt_ook():
    assert lokale_datum("2026-08-11T23:31:16Z") == "2026-08-12"


def test_lege_of_onleesbare_waarde_breekt_niet():
    assert lokale_datum("") == ""
    assert lokale_datum("geen datum") == "geen datum"
