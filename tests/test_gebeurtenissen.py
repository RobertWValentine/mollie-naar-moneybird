from mollie_moneybird_sync.gebeurtenissen import (
    van_afrekening,
    van_betaling,
    van_chargeback,
    van_refund,
)

# Antwoorden in de vorm van de Mollie API, met verzonnen kenmerken.

BETALING = {
    "id": "tr_SBvrjn9Wvgfygw2wMqZcU",
    "status": "paid",
    "method": "directdebit",
    "amount": {"value": "8.00", "currency": "EUR"},
    "description": "Bestelling 10639",
    "createdAt": "2026-08-11T05:38:45+00:00",
    "paidAt": "2026-08-11T23:31:16+00:00",
    "details": {"consumerName": "J. Jansen", "consumerAccount": "NL00BANK0123456789"},
}

KAARTBETALING = {
    "id": "tr_DIh7yfJs1ON43xKmTecQo",
    "status": "paid",
    "method": "creditcard",
    "amount": {"value": "2.50", "currency": "EUR"},
    "description": "Bestelling 10213",
    "createdAt": "2026-08-11T18:00:00+00:00",
    "paidAt": "2026-08-11T18:09:00+00:00",
    "details": {"cardHolder": "REVOLUT", "cardNumber": "7880"},
}

OPEN_BETALING = {
    "id": "tr_nogNietBetaald",
    "status": "pending",
    "amount": {"value": "3.00", "currency": "EUR"},
    "description": "Bestelling 10753",
    "createdAt": "2026-08-12T07:59:00+00:00",
    "paidAt": None,
}

CHARGEBACK = {
    "id": "chb_z46PDjqipVJIqVLB5Lzxo",
    "amount": {"value": "2.50", "currency": "EUR"},
    "settlementAmount": {"value": "-2.50", "currency": "EUR"},
    "createdAt": "2026-08-11T12:17:12+00:00",
    "reason": {"code": "AC06", "description": "Account blocked for Direct Debit"},
    "paymentId": "tr_OhbVrpoiVgRV5IfLBcbfn",
}

REFUND = {
    "id": "re_verzonnen",
    "status": "refunded",
    "amount": {"value": "5.00", "currency": "EUR"},
    "description": "Terugbetaling bestelling 10000",
    "createdAt": "2026-08-06T10:00:00+00:00",
    "paymentId": "tr_ietsAnders",
    "_embedded": {"payment": {"id": "tr_ietsAnders", "method": "ideal"}},
}

AFREKENING = {
    "id": "stl_RBMeyy",
    "reference": "10000001.2608.02",
    "status": "paidout",
    "amount": {"value": "2545.58", "currency": "EUR"},
    "settledAt": "2026-08-11T04:31:11+00:00",
    "periods": {
        "2026": {
            "07": {
                "invoiceId": "inv_MDHqJ38aRU",
                "invoiceReference": "MOL-NL-R2026.0000765432",
                "costs": [
                    {"description": "SEPA Direct Debit", "count": 545,
                     "amountGross": {"value": "230.8075", "currency": "EUR"}},
                    {"description": "Rounding differences", "count": 550,
                     "amountGross": {"value": "3.5714", "currency": "EUR"}},
                ],
            },
            "08": {
                "invoiceId": None,
                "invoiceReference": "MOL-NL-R2026.0001234567",
                "costs": [
                    {"description": "iDEAL", "count": 7,
                     "amountGross": {"value": "2.7104", "currency": "EUR"}},
                    {"description": "Fee Reimbursement", "count": 6,
                     "amountGross": {"value": "-2.5410", "currency": "EUR"}},
                ],
            },
        }
    },
}

LOPENDE_AFREKENING = {
    "id": "open",
    "status": "open",
    "amount": {"value": "3593.78", "currency": "EUR"},
    "periods": {"2026": {"08": {"invoiceId": None, "invoiceReference": None,
                                "costs": [{"description": "iDEAL", "count": 1,
                                           "amountGross": {"value": "0.32",
                                                           "currency": "EUR"}}]}}},
}


def test_betaling_boekt_op_de_nederlandse_datum():
    """23:31 UTC is 01:31 in Nederland, dus de volgende dag."""
    r = van_betaling(BETALING)
    assert r["date"] == "2026-08-12"
    assert r["amount"] == "8.00"
    assert r["message"] == (
        "Mollie Payment - J. Jansen - Bestelling 10639 - tr_SBvrjn9Wvgfygw2wMqZcU"
    )
    assert r["sleutel"] == "tr_SBvrjn9Wvgfygw2wMqZcU"


def test_kaartbetaling_gebruikt_de_kaarthouder():
    r = van_betaling(KAARTBETALING)
    assert "REVOLUT" in r["message"]
    assert r["date"] == "2026-08-11"


def test_onbetaalde_betaling_wordt_niet_geboekt():
    assert van_betaling(OPEN_BETALING) is None


def test_chargeback_noemt_reden_en_beide_kenmerken():
    regels = van_chargeback(CHARGEBACK)
    assert len(regels) == 1
    r = regels[0]
    assert r["amount"] == "-2.50"
    assert r["message"] == (
        "Mollie Chargeback - AC06 - Account blocked for Direct Debit"
        " - chb_z46PDjqipVJIqVLB5Lzxo - tr_OhbVrpoiVgRV5IfLBcbfn"
    )


def test_chargeback_zonder_settlementamount_blijft_een_afschrijving():
    """Mollie haalt settlementAmount op 1 januari 2027 weg (docs.mollie.com/reference/get-chargeback).

    `amount` is positief; de terugboeking moet toch negatief en de terugdraaiing positief blijven.
    """
    zonder = {k: v for k, v in CHARGEBACK.items() if k != "settlementAmount"}
    regels = van_chargeback(dict(zonder, reversedAt="2026-08-20T09:00:00+00:00"))
    assert regels[0]["amount"] == "-2.50"
    assert regels[1]["amount"] == "2.50"


def test_paypal_refund_via_mollie_wordt_niet_geboekt():
    """Het geld ging nooit over het Mollie-saldo; de PayPal-import boekt de refund al.

    Mollie zet settlementAmount bij een PayPal-refund op nul en haalt het veld op 1 januari 2027 weg.
    """
    paypal = dict(REFUND, _embedded={"payment": {"id": "tr_ietsAnders", "method": "paypal"}})
    assert van_refund(paypal) is None
    assert van_refund(dict(paypal, settlementAmount={"value": "0.00", "currency": "EUR"})) is None


def test_refund_zonder_settlementamount_en_zonder_betaling_wordt_niet_geboekt():
    """Zonder het veld en zonder de meegestuurde betaling is een PayPal-refund niet te herkennen."""
    zonder = {k: v for k, v in REFUND.items() if k != "_embedded"}
    assert van_refund(zonder) is None
    # met settlementAmount blijft het oude gedrag: dat bedrag is wat er van het saldo afging
    assert van_refund(dict(zonder, settlementAmount={"value": "-5.00", "currency": "EUR"}))["amount"] == "-5.00"


def test_vreemde_valuta_zonder_settlementamount_wordt_niet_geboekt():
    """Zonder settlementAmount staat het eurobedrag alleen nog in de afrekening."""
    usd = {"value": "43.38", "currency": "USD"}
    cb = {k: v for k, v in CHARGEBACK.items() if k != "settlementAmount"}
    assert van_chargeback(dict(cb, amount=usd)) == []
    assert van_refund(dict(REFUND, amount=usd)) is None


def test_refund_van_nul_wordt_niet_geboekt():
    assert van_refund(dict(REFUND, settlementAmount={"value": "0.00", "currency": "EUR"})) is None


def test_refund_is_negatief():
    r = van_refund(REFUND)
    assert r["amount"] == "-5.00"
    assert "re_verzonnen" in r["message"]


def test_afrekening_geeft_uitbetaling_en_kosten():
    regels = van_afrekening(AFREKENING)
    assert len(regels) == 5  # 1 uitbetaling + 4 kostenregels

    uitbetaling = regels[0]
    assert uitbetaling["amount"] == "-2545.58"
    assert uitbetaling["message"] == "Mollie Settlement - stl_RBMeyy"


def test_kostenregels_dragen_het_juiste_factuurnummer():
    regels = {r["message"]: r["amount"] for r in van_afrekening(AFREKENING)}
    assert regels["Mollie Cost - inv_MDHqJ38aRU - SEPA Direct Debit"
                  " - MOL-NL-R2026.0000765432 - stl_RBMeyy"] == "-230.81"
    assert regels["Mollie Cost - iDEAL - MOL-NL-R2026.0001234567"
                  " - stl_RBMeyy"] == "-2.71"


def test_teruggave_van_kosten_is_positief():
    """Fee Reimbursement staat negatief bij Mollie en hoort positief te boeken."""
    regels = {r["message"]: r["amount"] for r in van_afrekening(AFREKENING)}
    assert regels["Mollie Cost - Fee Reimbursement - MOL-NL-R2026.0001234567"
                  " - stl_RBMeyy"] == "2.54"


def test_lopende_afrekening_wordt_niet_geboekt():
    """Die heeft nog geen definitieve bedragen en geen factuurnummer."""
    assert van_afrekening(LOPENDE_AFREKENING) == []


def test_kostenregels_hebben_een_eigen_sleutel_per_periode():
    """Twee kostenregels met dezelfde omschrijving en een ander tarief komen
    in de historie echt voor, dus het volgnummer hoort in de sleutel."""
    dubbel = {"2026": {"07": {"invoiceId": "inv_x", "invoiceReference": "MOL-NL-R1",
                              "costs": [
                                  {"description": "SEPA Direct Debit",
                                   "amountGross": {"value": "1.8150", "currency": "EUR"}},
                                  {"description": "SEPA Direct Debit",
                                   "amountGross": {"value": "21.1750", "currency": "EUR"}}]}}}
    tweetarieven = dict(AFREKENING, periods=dubbel)
    sleutels = [r["sleutel"] for r in van_afrekening(tweetarieven)]
    assert len(sleutels) == len(set(sleutels)), "sleutels moeten uniek zijn"

    sleutels = [r["sleutel"] for r in van_afrekening(AFREKENING)]
    assert len(sleutels) == len(set(sleutels)), "sleutels moeten uniek zijn"
    assert "stl_RBMeyy:2026-08:0:iDEAL" in sleutels


AFREKENING_MET_TERUGDRAAIING = {
    "id": "stl_iGFfWd", "status": "paidout",
    "amount": {"value": "1725.35", "currency": "EUR"},
    "settledAt": "2026-08-04T04:55:12+00:00",
    "periods": {"2026": {"07": {
        "invoiceId": "inv_MDHqJ38aRU",
        "invoiceReference": "MOL-NL-R2026.0000765432",
        "revenue": [
            {"description": "SEPA Direct Debit",
             "amountGross": {"value": "1510.52", "currency": "EUR"}},
            {"description": "SEPA Direct Debit Failed",
             "amountGross": {"value": "-43.00", "currency": "EUR"}},
            {"description": "SEPA Direct Debit Chargeback",
             "amountGross": {"value": "-5.00", "currency": "EUR"}},
        ],
        "costs": [
            {"description": "SEPA Direct Debit",
             "amountGross": {"value": "153.61", "currency": "EUR"}},
        ],
    }}},
}


def test_het_omzetblok_levert_geen_enkele_regel():
    """Het omzetblok is een samenvatting van wat elders al per stuk staat.

    De positieve regels zijn de betalingen, die boeken we uit de betalingenlijst.
    De negatieve regels zijn chargebacks en refunds, en die hebben allebei een
    eigen record bij Mollie (chb_ en re_) dat wij ook al per stuk boeken. Een
    mislukte incasso is daarbij geen aparte soort maar gewoon een chargeback met
    een andere reden: het aantal chb_-records valt samen met de regels
    "Chargeback" plus "Failed" in de afrekeningen. Alles uit het omzetblok is
    dus dubbel.
    """
    berichten = [r["message"] for r in van_afrekening(AFREKENING_MET_TERUGDRAAIING)]
    assert berichten
    assert not any(m.startswith("Mollie Reversal") for m in berichten)
    assert not any("Chargeback" in m for m in berichten)
    assert not any("Refund" in m for m in berichten)


def test_afrekening_levert_alleen_uitbetaling_en_kosten():
    """Wat er wel uit een afrekening komt: de uitbetaling en de kostentotalen."""
    soorten = {r["message"].split(" - ")[0]
               for r in van_afrekening(AFREKENING_MET_TERUGDRAAIING)}
    assert soorten == {"Mollie Settlement", "Mollie Cost"}


def test_kostenregel_draagt_wel_het_mollie_factuurnummer():
    """Daarop koppelt Moneybird de kosten aan de juiste Mollie-inkoopfactuur."""
    berichten = [r["message"] for r in van_afrekening(AFREKENING_MET_TERUGDRAAIING)]
    kosten = [m for m in berichten if m.startswith("Mollie Cost")]
    assert kosten
    assert all("MOL-NL-" in m for m in kosten)


def test_chargeback_in_de_omzet_wordt_overgeslagen():
    """Die boeken we al per stuk, met reden en kenmerk. Anders telt hij dubbel."""
    berichten = [r["message"] for r in van_afrekening(AFREKENING_MET_TERUGDRAAIING)]
    assert not any("Chargeback" in m for m in berichten)


def test_refund_in_de_omzet_wordt_overgeslagen():
    """Net als een chargeback boeken we een refund al per stuk, met re_ en tr_.

    In de praktijk aangetroffen: een iDEAL Refund stond twee keer op de
    Mollie-rekening, eerst als "Mollie Refund - re_..." en een week later als
    "Mollie Reversal - ... - iDEAL Refund - ...". Het geld gaat maar een keer
    van het saldo af.
    """
    met_refund = {
        "id": "stl_refundtest",
        "status": "paidout",
        "settledAt": "2026-07-07T05:00:00+00:00",
        "amount": {"value": "100.00", "currency": "EUR"},
        "periods": {"2026": {"07": {
            "invoiceReference": "MOL-NL-R2026.0000765432",
            "invoiceId": "inv_MDHqJ38aRU",
            "revenue": [
                {"description": "iDEAL Refund",
                 "amountGross": {"value": "-88.00", "currency": "EUR"}, "count": 1},
                {"description": "SEPA Direct Debit Refund",
                 "amountGross": {"value": "-12.50", "currency": "EUR"}, "count": 2},
                {"description": "SEPA Direct Debit Failed",
                 "amountGross": {"value": "-7.50", "currency": "EUR"}, "count": 1},
            ],
            "costs": [],
        }}},
    }
    berichten = [r["message"] for r in van_afrekening(met_refund)]
    assert not any("Refund" in m for m in berichten)


def test_positieve_omzet_wordt_niet_geboekt():
    """Die zit al in de losse betalingsregels."""
    berichten = [r["message"] for r in van_afrekening(AFREKENING_MET_TERUGDRAAIING)]
    assert not any("Mollie Reversal - inv_MDHqJ38aRU - SEPA Direct Debit -" in m
                   for m in berichten)


def test_teruggedraaide_chargeback_krijgt_een_tegenboeking():
    """Win je het geschil, dan komt het geld terug. Mollie zet dan reversedAt."""
    gewonnen = dict(CHARGEBACK, reversedAt="2026-08-20T09:00:00+00:00")
    regels = van_chargeback(gewonnen)
    assert len(regels) == 2
    assert regels[1]["amount"] == "2.50"
    assert regels[1]["date"] == "2026-08-20"
    assert "Reversed" in regels[1]["message"]
    assert regels[0]["sleutel"] != regels[1]["sleutel"]


def test_refund_in_de_wachtrij_wordt_niet_geboekt():
    """Anders boek je geld weg dat er nog is, en bij failed komt het nooit terug."""
    for status in ("queued", "pending", "processing", "failed", "canceled"):
        assert van_refund(dict(REFUND, status=status)) is None


def test_refund_gebruikt_het_afrekenbedrag():
    """settlementAmount is wat er van de balans afgaat, amount wat de klant krijgt."""
    r = van_refund(dict(REFUND, settlementAmount={"value": "-5.20", "currency": "EUR"}))
    assert r["amount"] == "-5.20"


def test_elke_regel_draagt_het_werkelijke_tijdstip():
    """Binnen een dag moet de volgorde kloppen. Sorteren op de sleutel geeft
    bij betalingen de volgorde van het tr_-kenmerk, en dat is willekeurig."""
    assert van_betaling(BETALING)["tijd"] == "2026-08-11T23:31:16+00:00"
    assert van_chargeback(CHARGEBACK)[0]["tijd"] == "2026-08-11T12:17:12+00:00"
    assert van_refund(REFUND)["tijd"] == "2026-08-06T10:00:00+00:00"
    for r in van_afrekening(AFREKENING):
        assert r["tijd"] == "2026-08-11T04:31:11+00:00"


def test_halve_cent_rondt_handelsmatig_omhoog():
    """Mollie's brutobedrag 11,4950 hoort 11,50 te worden, niet 11,49.

    round(float(x), 2) gaf 11,49: het rekent op een binaire benadering en rondt
    halve centen naar het even getal. Dat leverde per maandfactuur een cent
    verschil op ten opzichte van de regels van de oude koppeling.
    """
    from mollie_moneybird_sync.gebeurtenissen import _bedrag

    assert _bedrag("11.4950") == "11.50"
    assert _bedrag("2.1175") == "2.12"
    assert _bedrag("0.4235") == "0.42"
    assert _bedrag("11.4950", omkeren=True) == "-11.50"
