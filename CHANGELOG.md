# Changelog

Alle wijzigingen aan mollie-naar-moneybird worden hier bijgehouden.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-14

Belangrijk vóór 1 januari 2027: Mollie haalt dan `settlementAmount` weg bij terugboekingen en refunds. Zonder deze versie komt een terugboeking daarna als bijschrijving in Moneybird.

### Security
- De lock staat standaard naast de state (`mollie-moneybird-sync.lock` in de map van `STATE_PATH`) in plaats van in `/tmp`. In een gedeelde map kon een andere gebruiker het bestand aanmaken en zo elke ronde tegenhouden. Een ontbrekende map wordt aangemaakt met rechten 700. Wie `LOCK_PATH` zelf zet, houdt die plek.
- Een lock die langer bezet is dan `LOCK_ALERT_MINUTES` (standaard 90) geeft exitcode 3 en een foutregel met de leeftijd van de lock. Tot nu toe eindigde zo'n run altijd met exitcode 0, zodat een vastgelopen lock de keten kon stilleggen terwijl de hartslagmonitor groen bleef. Een gewone overlap blijft exitcode 0. De standaard ligt ruim boven een uurlijkse cron, zodat de grens niet op het interval zelf valt.
- Een lockfile die geen gewoon bestand is (bijvoorbeeld een symlink), van een andere gebruiker is of een tijd in de toekomst heeft, geeft meteen exitcode 3. Zo'n bestand kan niet van een eigen run zijn; zonder deze toets kon iemand met een bestand met een toekomstige tijd het alarm omzeilen. De leeftijd wordt gelezen zonder een symlink te volgen.
- `LOCK_ALERT_MINUTES` en `MAX_LOOKBACK_DAYS` die geen geheel getal zijn, geven één leesbare regel en exitcode 2 in plaats van een Python-foutmelding. Leeg betekent de standaardwaarde. Tests erbij.
- `SECURITY.md`: hoe je een kwetsbaarheid privé meldt.

### Fixed
- Een terugboeking blijft een afschrijving als Mollie geen `settlementAmount` meer meestuurt. Mollie haalt dat veld op 1 januari 2027 weg (docs.mollie.com/reference/get-chargeback); het overblijvende `amount` is positief en werd tot nu toe ongewijzigd geboekt, zodat een terugboeking als bijschrijving in Moneybird zou komen. De terugdraaiing blijft een bijschrijving. Test erbij.
- Een refund van een PayPal-betaling die via Mollie loopt wordt niet meer op de Mollie-rekening geboekt: het geld raakt het Mollie-saldo niet en de PayPal-import boekt hem al. Tot nu toe gaf zo'n refund een regel van 0,00; zonder `settlementAmount` (weg per 1 januari 2027) zou het een echte afschrijving worden, dus dubbel. De refundlijst vraagt daarvoor de betaling mee (`embed=payment`). Stuurt Mollie de betaling niet mee, dan haalt de import haar op (`GET /payments/{id}`). Gemeten op 11 november 2026 met de live API: de refund draagt `_embedded.payment.method` en de link naar de volgende pagina houdt `embed=payment`. Een record dat niet veilig te boeken is (geen `settlementAmount` en geen betaalmethode, of een andere valuta dan euro zonder `settlementAmount`) gooit `NietTeBoeken`: de ronde boekt de rest, meldt het kenmerk in het log en eindigt met exitcode 1, zodat een hartslagmonitor rood wordt. Een refund van 0,00 wordt niet meer geboekt. Een record dat al geboekt is (in de state, of bij `--aansluiten` met zijn kenmerk al in Moneybird) telt niet als niet te boeken: na 1 januari 2027 mist ook een al geboekte terugboeking haar `settlementAmount`, en anders werd de run onterecht rood en zou een handmatige boeking dubbel zijn. Bestaat de betaling niet (404, 410), dan telt die ene refund als niet te boeken; een tijdelijke fout of tokenfout bij het ophalen stopt de run vóór het schrijven. Er wordt alleen opgehaald bij een afgeronde refund die nog niet geboekt is. De valutatoets op `amount` faalt dicht: geen valuta is geen euro. `settlementAmount` staat al in de valuta van het saldo en gaat zonder toets. `--controleer` meldt een afrekening met zo'n terugboeking als `NIET TE TOETSEN` en toetst de rest, in plaats van te stoppen. Het betalingskenmerk gaat gecodeerd in de URL. `--aansluiten` herkent een terugdraaiing in Moneybird aan het teken en legt een niet te boeken record dat al in Moneybird staat ook in de state vast. De logregel noemt de kenmerken die na een handmatige boeking nog vastgelegd moeten worden. Een terugboeking van 0,00 wordt net als een refund van 0,00 niet geboekt.

### Added
- `--handmatig-geboekt <kenmerk>` legt vast dat een niet te boeken terugboeking (`chb_...`, `chb_...:teruggedraaid`) of refund (`re_...`) met de hand is geboekt; daarna telt hij niet meer mee en wordt de run weer groen. Het accepteert alleen een kenmerk dat op dat moment als niet te boeken openstaat (met `--dagen` in het venster van `--aansluiten`), in een bestaande state, onder het slot en niet samen met een andere opdracht. Met `--dry-run` schrijft het niets. Een tokenfout krijgt de tokenhint, een storing het advies het later opnieuw te proberen; in beide gevallen is er niets vastgelegd. De foutentabel in de README zegt wanneer je dit gebruikt. Tests erbij, ook voor `verzamel`, `draai`, `aansluiten`, `--controleer` en de exitcode.

### Changed
- CI draait nu op Python 3.11 en 3.15. Alle tests slagen op 3.15.2 zonder aanpassing aan de code.
- `CLAUDE.md` staat in de root en importeert `AGENTS.md`, zodat Claude Code de installatie-instructies leest. Claude Code leest `AGENTS.md` niet zelf zolang er een `CLAUDE.md` is.
- Pakketnaam in `pyproject.toml` is nu `mollie-naar-moneybird`, gelijk aan de repo. De Python-module heet nog steeds `mollie_moneybird_sync`, dus `python3 -m mollie_moneybird_sync` en `bin/run.sh` werken zoals voorheen.

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
