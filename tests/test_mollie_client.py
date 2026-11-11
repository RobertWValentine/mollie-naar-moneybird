import pytest

from mollie_moneybird_sync import mollie_client
from mollie_moneybird_sync.mollie_client import MollieClient


def _pagina(rijen, met_next=True):
    antwoord = {"_embedded": {"payments": rijen}}
    if met_next:
        antwoord["_links"] = {"next": {"href": "https://api.mollie.com/v2/payments?page=2"}}
    return antwoord


def test_lijst_loopt_door_over_paginas(monkeypatch):
    beurten = [
        _pagina([{"id": "tr_1", "createdAt": "2026-08-01T10:00:00+00:00"}]),
        _pagina([{"id": "tr_2", "createdAt": "2026-07-01T10:00:00+00:00"}], met_next=False),
    ]
    monkeypatch.setattr(mollie_client, "verzoek", lambda *a, **k: beurten.pop(0))
    rijen = list(MollieClient("x")._lijst("/payments", "payments"))
    assert [r["id"] for r in rijen] == ["tr_1", "tr_2"]


def test_lijst_stopt_bij_grensdatum(monkeypatch):
    pagina = _pagina([
        {"id": "tr_1", "createdAt": "2026-08-01T10:00:00+00:00"},
        {"id": "tr_oud", "createdAt": "2026-06-01T10:00:00+00:00"},
    ])
    monkeypatch.setattr(mollie_client, "verzoek", lambda *a, **k: pagina)
    rijen = list(MollieClient("x")._lijst("/payments", "payments", grens="2026-07-01"))
    assert [r["id"] for r in rijen] == ["tr_1"]


def test_lijst_faalt_bij_afkapping_in_plaats_van_stil_te_stoppen(monkeypatch):
    """Een halve lijst ziet er compleet uit. Dat mag nooit stil gebeuren."""
    monkeypatch.setattr(
        mollie_client, "verzoek",
        lambda *a, **k: _pagina([{"id": "tr_x", "createdAt": "2026-08-01T10:00:00+00:00"}]),
    )
    with pytest.raises(RuntimeError, match="Paginalimiet"):
        list(MollieClient("x")._lijst("/payments", "payments", limiet_paginas=3))


def test_balansmutaties_falen_ook_bij_afkapping(monkeypatch):
    monkeypatch.setattr(
        mollie_client, "verzoek",
        lambda *a, **k: {
            "_embedded": {"balance_transactions": [{"id": "baltr_1"}]},
            "_links": {"next": {"href": "https://api.mollie.com/v2/x?page=2"}},
        },
    )
    with pytest.raises(RuntimeError, match="Paginalimiet"):
        list(MollieClient("x").balansmutaties("bal_x", limiet_paginas=2))


def test_refunds_vraagt_de_betaling_mee(monkeypatch):
    """Zonder settlementAmount (weg per 1 januari 2027) herkent van_refund een PayPal-refund aan de betaling."""
    paden = []

    def nep(url, *a, **k):
        paden.append(url)
        return {"_embedded": {"refunds": []}}
    monkeypatch.setattr(mollie_client, "verzoek", nep)
    list(MollieClient("x").refunds(""))
    assert "embed=payment" in paden[0]


def test_betaling_haalt_een_betaling_op(monkeypatch):
    paden = []

    def nep(url, *a, **k):
        paden.append(url)
        return {"id": "tr_verzonnen", "method": "ideal"}
    monkeypatch.setattr(mollie_client, "verzoek", nep)
    assert MollieClient("x").betaling("tr_verzonnen")["method"] == "ideal"
    assert paden[0].endswith("/payments/tr_verzonnen")


def test_betaling_codeert_het_kenmerk_in_het_pad(monkeypatch):
    paden = []
    monkeypatch.setattr(mollie_client, "verzoek", lambda url, *a, **k: paden.append(url) or {})
    MollieClient("x").betaling("tr_x/../refunds?limit=1")
    assert paden[0].endswith("/payments/tr_x%2F..%2Frefunds%3Flimit%3D1")
