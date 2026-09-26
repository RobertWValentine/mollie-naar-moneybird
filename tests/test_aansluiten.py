from mollie_moneybird_sync.aansluiten import kenmerken_van, splits

# Mutaties zoals een eerdere koppeling ze in Moneybird zette.
BESTAAND = [
    {"date": "2026-08-11", "amount": "8.0",
     "message": "Mollie Payment - J. Jansen - Bestelling 10639 - tr_SBvrjn9Wvgfygw2wMqZcU"},
    {"date": "2026-08-11", "amount": "-2.5",
     "message": "Mollie Chargeback - AC06 - Account blocked for Direct Debit"
                " - chb_z46PDjqipVJIqVLB5Lzxo - tr_OhbVrpoiVgRV5IfLBcbfn"},
    {"date": "2026-08-11", "amount": "-2545.58",
     "message": "Mollie Settlement - stl_RBMeyy"},
    {"date": "2026-08-11", "amount": "-2.71",
     "message": "Mollie Cost - iDEAL - MOL-NL-R2026.0001234567"},
]


def _regel(sleutel, datum, bedrag, bericht):
    return {"sleutel": sleutel, "date": datum, "amount": bedrag, "message": bericht}


def _sleutels(stapel):
    return [r["sleutel"] for r in stapel]


def test_kenmerken_uit_omschrijving():
    assert kenmerken_van(
        "Mollie Payment - J. Jansen - Bestelling 10639 - tr_SBvrjn9Wvgfygw2wMqZcU"
    ) == {"tr_SBvrjn9Wvgfygw2wMqZcU"}


def test_factuurnummer_telt_als_kenmerk():
    assert kenmerken_van("Mollie Cost - iDEAL - MOL-NL-R2026.0001234567") == {
        "MOL-NL-R2026.0001234567"
    }


def test_al_geboekte_regels_worden_herkend():
    regels = [
        _regel("tr_SBvrjn9Wvgfygw2wMqZcU", "2026-08-11", "8.00",
               "Mollie Payment - J. Jansen - Bestelling 10639 - tr_SBvrjn9Wvgfygw2wMqZcU"),
        _regel("stl_RBMeyy", "2026-08-11", "-2545.58", "Mollie Settlement - stl_RBMeyy"),
        _regel("stl_RBMeyy:2026-08:iDEAL", "2026-08-11", "-2.71",
               "Mollie Cost - iDEAL - MOL-NL-R2026.0001234567"),
    ]
    geboekt, ontbreekt = splits(regels, BESTAAND)
    assert len(geboekt) == 3 and not ontbreekt


def test_nieuwe_regel_wordt_niet_herkend():
    regels = [_regel("tr_nieuw", "2026-08-12", "5.00",
                     "Mollie Payment - A. Nieuw - Bestelling 11000 - tr_nieuw")]
    geboekt, ontbreekt = splits(regels, BESTAAND)
    assert not geboekt and _sleutels(ontbreekt) == ["tr_nieuw"]


def test_twee_kostensoorten_met_hetzelfde_bedrag_gaan_niet_mis():
    """Beide dragen hetzelfde factuurnummer en hetzelfde bedrag.

    Zonder tellen zou de tweede ten onrechte als geboekt gelden en
    stilzwijgend uit de boeken verdwijnen.
    """
    bestaand = [
        {"date": "2026-08-11", "amount": "-0.39",
         "message": "Mollie Cost - Pay By Bank - MOL-NL-R2026.0001234567"},
        {"date": "2026-08-11", "amount": "-0.39",
         "message": "Mollie Cost - Credit card - MOL-NL-R2026.0001234567"},
    ]
    regels = [
        _regel("stl_x:2026-08:Pay By Bank", "2026-08-11", "-0.39",
               "Mollie Cost - Pay By Bank - MOL-NL-R2026.0001234567"),
        _regel("stl_x:2026-08:Credit card", "2026-08-11", "-0.39",
               "Mollie Cost - Credit card - MOL-NL-R2026.0001234567"),
        _regel("stl_x:2026-08:iDEAL", "2026-08-11", "-0.39",
               "Mollie Cost - iDEAL - MOL-NL-R2026.0001234567"),
    ]
    geboekt, ontbreekt = splits(regels, bestaand)
    assert len(geboekt) == 2, "twee bestaande regels dekken twee nieuwe"
    assert len(ontbreekt) == 1, "de derde hoort te ontbreken"


def test_mislukte_incasso_en_herhaling_op_hetzelfde_kenmerk():
    bestaand = [{"date": "2026-08-11", "amount": "-2.5",
                 "message": "Mollie Payment - J. Thomas - tr_zelfde"}]
    regels = [
        _regel("tr_zelfde-mislukt", "2026-08-11", "-2.50",
               "Mollie Payment - J. Thomas - tr_zelfde"),
        _regel("tr_zelfde", "2026-08-11", "2.50",
               "Mollie Payment - J. Thomas - tr_zelfde"),
    ]
    geboekt, ontbreekt = splits(regels, bestaand)
    assert _sleutels(geboekt) == ["tr_zelfde-mislukt"]
    assert _sleutels(ontbreekt) == ["tr_zelfde"]


def test_regel_met_kenmerk_valt_nooit_terug_op_datum_en_bedrag():
    """Anders zou een donatie van 2,50 elke andere donatie van 2,50 afdekken."""
    bestaand = [{"date": "2026-08-11", "amount": "2.5",
                 "message": "Handmatige regel zonder kenmerk"}]
    regels = [_regel("tr_iets", "2026-08-11", "2.50",
                     "Mollie Payment - X - tr_iets")]
    _, ontbreekt = splits(regels, bestaand)
    assert _sleutels(ontbreekt) == ["tr_iets"]


def test_lege_rekening_levert_alles_als_ontbrekend():
    """Gedrag van splits zelf. sync.aansluiten weigert dit zonder --forceer-leeg."""
    regels = [_regel("tr_x", "2026-08-11", "8.00", "Mollie Payment - X - tr_x")]
    geboekt, ontbreekt = splits(regels, [])
    assert not geboekt and len(ontbreekt) == 1
