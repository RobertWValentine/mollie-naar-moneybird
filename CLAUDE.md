# mollie-naar-moneybird

Zet Mollie- en PayPal-transacties als bankafschriften in Moneybird. Pure Python, geen afhankelijkheden buiten de standaardbibliotheek (plus `tzdata` op een kale server).

## Commando's
- Tests: `make test` (pytest, geen netwerk)
- Lint: `make lint` (ruff)
- Proefdraai: `./bin/run.sh --dry-run`

## Indeling
- `mollie_moneybird_sync/gebeurtenissen.py`: vertaalt Mollie- en PayPal-records naar mutaties
- `sync.py`: de rondes (gewoon, aansluiten, PayPal, terugboekingen)
- `state.py`: SQLite met verwerkte sleutels en schrijf-intenties
- `mollie_client.py`, `moneybird_client.py`, `paypal_client.py`: API-clients

## Regels
- Geen echte klantgegevens, kenmerken of administratie-ID's in code, tests of documentatie. Dit is een openbare repo.
- Schrijfacties naar Moneybird nooit herhalen bij een time-out of serverfout.
- CHANGELOG.md bijwerken bij elke wijziging.
- Elke wijziging die gebruikers raakt krijgt een versie: CHANGELOG-kop met versie en datum, `version` in `pyproject.toml`, tag `vX.Y.Z` en een GitHub Release met de CHANGELOG-tekst.

## Installatie voor een gebruiker
Installeer je deze repo voor iemand, volg dan de instructies hieronder (uit `AGENTS.md`):

@AGENTS.md
