# Changelog

Alle wijzigingen aan mollie-naar-moneybird worden hier bijgehouden.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-24

Werk bij tussen twee rondes, op een moment waarop geen ronde loopt. Vanaf 0.3.0 werkt de lock met `flock` en blijft de lockfile staan; verwijder hem niet.

### Added
- `MoneybirdClient.aantal_mutaties(rekening_id, periode)` telt de mutaties van een rekening in een periode zonder ze op te halen.

### Changed
- `--terugboekingen` zoekt de creditnota tot drie dagen vóór en na de bankregel (`TERUGBOEKING_MARGE_DAGEN`). Tot nu toe zocht het alleen op de dag van de bankregel; viel de creditnota een dag later, dan bleef de regel staan. Elke dag wordt binnen een ronde maar één keer bij Moneybird opgehaald, ook als de vensters van terugboekingen op naburige dagen overlappen. Een creditnota met precies hetzelfde `chb_`-kenmerk gaat voor op een die alleen met het kenmerk begint; twee kandidaten blijven laten staan. Matchen blijft op het kenmerk en nooit op het bedrag. Tests erbij.
- Exitcode 4 betekent: verwerkt, met N records die niet te boeken zijn. Wie in een script op exitcode 1 toetst, voegt 4 toe. Een cronregel met `&&` hoeft niet te veranderen. Tot nu toe gaf zo'n run exitcode 1, net als een mislukte run. De foutentabel in de README noemt nu alle exitcodes. Tests erbij.

### Deprecated
- `MoneybirdClient.mutaties` gaat weg in 0.4.0; gebruik `mutaties_in_periode`. Zonder periode haalt het alle mutaties van de administratie op.

### Fixed
- `--aansluiten` vergelijkt met de mutaties van de rekening over het venster plus een week, minstens over vorig jaar en dit jaar. Ze komen per kalenderjaar binnen met een vaste periode. Tot nu toe haalde het alle mutaties van de administratie op, zonder periode. Een droge en een schrijvende ronde vergelijken met dezelfde mutaties. Bij `--dry-run` telt een regel die de state nog niet kent vlak na een geslaagde ronde als `wacht op de volgende ronde` en niet als ontbrekend: hij is na het begin van die ronde bij Mollie verschenen. Dat geldt tot 2 uur na het begin van de ronde, als `--dagen` niet groter is dan `MAX_LOOKBACK_DAYS`. Tot nu toe gaf een droogloop vlak na een ronde vals alarm over zulke regels. Een regel die de state wel kent en die in Moneybird ontbreekt, telt altijd als ontbrekend. De laatste regel eindigt nu op `N ontbrak, M wacht op de volgende ronde`; een toets op `, 0 ontbrak` blijft werken. De state onthoudt het begin van de laatste geslaagde ronde in een eigen tabel die bij het eerste gebruik wordt aangemaakt: een state van 0.2.0 werkt zonder migratie. Een droge ronde legt niets vast. De toets op een lege rekening telt de mutaties over dezelfde periodes. Een antwoord van de synchronisatie-API dat geen lijst is, geeft nu ook bij `mutaties_in_periode` een leesbare fout in plaats van een Python-fout of een verkeerde lijst. Het valse gat in de eerste dagen van januari is hiermee niet verholpen: een meting liet zien dat Moneybird zonder periode ook de mutaties van vorig jaar levert, dus de oorzaak ligt elders en is nog niet gevonden. Tests erbij.
- De melding bij een open intentie (`Een vorige run is afgebroken tijdens het schrijven`) wijst nu de veilige weg. Staat het afschrift in Moneybird: verwijder het met `--verwijder-afschrift <id>` en wis daarna de intentie met `--wis-intentie`, zodat de volgende ronde de regels opnieuw boekt. Staat het er niet: wis alleen de intentie. Tot nu toe raadde de melding aan het afschrift te laten staan en `--aansluiten` te draaien, maar `--aansluiten` weigert zolang de intentie open staat; wie daarna de intentie wiste terwijl het afschrift bleef staan, boekte die regels dubbel. De README volgt dezelfde route. Test erbij.
- Een record dat niet te boeken is, blijft gemeld tot het met `--handmatig-geboekt` is vastgelegd of een ronde het alsnog boekt. Tot nu toe verdween het uit de melding zodra het buiten het venster van `MAX_LOOKBACK_DAYS` viel; de run werd dan weer groen zonder dat het geboekt was. De state onthoudt zulke records nu in een eigen tabel, die bij het eerste gebruik wordt aangemaakt: een state van 0.2.0 werkt zonder migratie. Een dry run schrijft er niets in. De logregel van een record van buiten het venster eindigt op `(buiten het venster)`; zo'n record legt `--aansluiten` niet als al geboekt vast en telt het mee, ook als het met de hand in Moneybird staat. Daarom is `--handmatig-geboekt` daarvoor altijd nodig. Komt een open record in het venster zonder fout terug (bijvoorbeeld een refund die een PayPal-betaling bleek), dan telt het niet meer mee. Tests erbij.
- De lock is nu een `flock` op de lockfile. Tot nu toe kon een run die de lockfile net had aangemaakt maar nog geen proces-ID had geschreven, door een tweede run als achtergebleven worden opgeruimd; dan draaiden er twee tegelijk. Stopt een run, ook door een crash, dan is de lock meteen vrij. Het bestand blijft na een run staan en hoeft nooit opgeruimd te worden; een achtergebleven lockfile van 0.2.0 wordt gewoon overgenomen. Een lockfile die niet te openen of niet te vergrendelen is (een map op het pad, geen rechten, `ENOLCK` op een netwerkschijf) geeft exitcode 3 met de reden in de melding. Bij `--handmatig-geboekt` geven zo'n lockfile en een lock die `LOCK_ALERT_MINUTES` of langer bezet is nu ook exitcode 3 in plaats van 1, met dezelfde melding als bij een gewone ronde; een gewone overlap blijft exitcode 1. De melding bij een oude lock raadt het verwijderen van de lockfile nu af. Tests erbij.

## [0.2.0] - 2026-11-14

Belangrijk vóór 1 januari 2027: Mollie haalt dan `settlementAmount` weg bij terugboekingen en refunds. Zonder deze versie komt een terugboeking daarna als bijschrijving in Moneybird.

### Security
- De lock staat standaard naast de state (`mollie-moneybird-sync.lock` in de map van `STATE_PATH`) in plaats van in `/tmp`. In een gedeelde map kon een andere gebruiker het bestand aanmaken en zo elke ronde tegenhouden. Een ontbrekende map wordt aangemaakt met rechten 700. Wie `LOCK_PATH` zelf zet, houdt die plek.
- Een lock die langer bezet is dan `LOCK_ALERT_MINUTES` (standaard 90) geeft exitcode 3 en een foutregel met de leeftijd van de lock. Tot nu toe eindigde zo'n run altijd met exitcode 0, zodat een vastgelopen lock de keten kon stilleggen terwijl de hartslagmonitor groen bleef. Een gewone overlap blijft exitcode 0. De standaard ligt ruim boven een uurlijkse cron, zodat de grens niet op het interval zelf valt.
- Een lockfile die geen gewoon bestand is (bijvoorbeeld een symlink of een hardlink), van een andere gebruiker is of een tijd in de toekomst heeft, geeft meteen exitcode 3. Zo'n bestand kan niet van een eigen run zijn; zonder deze toets kon iemand met een bestand met een toekomstige tijd het alarm omzeilen. De leeftijd wordt gelezen zonder een symlink te volgen.
- `LOCK_ALERT_MINUTES` en `MAX_LOOKBACK_DAYS` die geen geheel getal van minstens 1 zijn, geven één leesbare regel en exitcode 2 in plaats van een Python-foutmelding of een stil leeg venster. Leeg betekent de standaardwaarde. Tests erbij.
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
