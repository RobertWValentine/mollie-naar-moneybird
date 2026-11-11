# Changelog

Alle wijzigingen aan mollie-naar-moneybird worden hier bijgehouden.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Een terugboeking blijft een afschrijving als Mollie geen `settlementAmount` meer meestuurt. Mollie haalt dat veld op 1 januari 2027 weg (docs.mollie.com/reference/get-chargeback); het overblijvende `amount` is positief en werd tot nu toe ongewijzigd geboekt, zodat een terugboeking als bijschrijving in Moneybird zou komen. De terugdraaiing blijft een bijschrijving. Test erbij.

### Changed
- CI draait nu op Python 3.11 en 3.15. Alle tests slagen op 3.15.2 zonder aanpassing aan de code.

## [0.1.0] - 2026-09-26

### Added
- Eerste openbare versie. Mollie-betalingen, chargebacks, refunds en afrekeningen als bankafschriften in Moneybird, op de betaal- of boekdatum in Nederlandse tijd.
- PayPal-transacties op een eigen Moneybird-rekening (`--paypal`), met saldotoets.
- Teruggeboekte incasso's koppelen aan hun creditnota op het `chb_`-kenmerk (`--terugboekingen`).
- `--aansluiten` om een bestaande rekening bij te werken, `--controleer` om afrekeningen tegen de uitbetaling te toetsen.
- Dubbelbescherming: verwerkte sleutels in SQLite, lockfile, schrijf-intenties en geen herhaalde schrijfacties.
- Keychain-account instelbaar met `KEYCHAIN_ACCOUNT`.
- README met installatie stap voor stap, verwachte uitvoer per stap, cron- en launchd-voorbeeld en een foutentabel.
- `AGENTS.md`: installatie-instructies en harde regels voor AI-assistenten.
- Elke opdracht vraagt alleen de instellingen die hij nodig heeft, dus `--rekeningen` werkt al voordat het rekening-ID bekend is.
- Een ontbrekende instelling of een geweigerd token geeft één leesbare regel in plaats van een Python-foutmelding. De instellingen worden getoetst voordat er iets wordt opgevraagd.
- `.env.example` zet de state standaard in de thuismap, zodat het ook op een Mac direct werkt.
