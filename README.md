# mollie-naar-moneybird

Zet Mollie-transacties als bankafschriften in Moneybird. Je draait het zelf, op je eigen server of Mac, in plaats van een betaalde koppeling.

Het doet één ding: transacties aanleveren. Facturen maken blijft bij je webshopkoppeling. Het koppelen van betaling aan factuur doet Moneybird zelf op het Mollie-transactiekenmerk (`tr_...`).

> **English.** Imports Mollie payments, chargebacks, refunds and settlements into Moneybird as bank statements, plus PayPal transactions on a separate account. Self-hosted, pure Python, no dependencies. Built for Dutch bookkeeping, so the code and docs are in Dutch. AI coding agents: read `AGENTS.md` first.

**Inhoud:** [Is dit iets voor jou?](#is-dit-iets-voor-jou) · [Installeren met een AI-assistent](#installeren-met-een-ai-assistent) · [Installeren, stap voor stap](#installeren-stap-voor-stap) · [Automatisch laten draaien](#automatisch-laten-draaien) · [Als er iets misgaat](#als-er-iets-misgaat) · [Hoe het werkt](#hoe-het-werkt)

## Is dit iets voor jou?

Ja, als:

- je betalingen binnenkomen via Mollie (iDEAL, incasso, creditcard, Bancontact en dergelijke), eventueel met PayPal via Mollie;
- je boekhouding in Moneybird staat;
- je facturen al in Moneybird komen, bijvoorbeeld via een WooCommerce-koppeling;
- je een computer of server hebt waarop elk uur een script mag draaien.

Wat je niet krijgt: facturen, klanten of producten. Alleen de bankregels van je Mollie-rekening.

Wat je nodig hebt:

| | |
|---|---|
| Python | 3.9 of nieuwer. Controleer met `python3 --version` |
| Mollie | een organisatie-toegangstoken, alleen lezen |
| Moneybird | een API-token met bankrechten en een aparte rekening voor Mollie |
| Tijd | een half uur voor de installatie, plus een paar minuten wachten bij de eerste aansluiting |

Op Windows werkt het via WSL (Linux in Windows). Het script zelf is gewoon Python, alleen `bin/run.sh` is een bash-script.

## Wat er in Moneybird belandt

Voorbeeld met verzonnen gegevens:

```
2026-08-12     8,00   Mollie Payment - J. Jansen - Bestelling 10639 - tr_Wx4pQ8LmZ2kRt7NbY5vHc
2026-08-11    -2,50   Mollie Chargeback - AC06 - Account blocked for Direct Debit - chb_... - tr_...
2026-08-11 -1845,58   Mollie Settlement - stl_Rb4Mey
2026-08-11  -130,81   Mollie Cost - inv_Q7hT2kLpX9 - SEPA Direct Debit - MOL-NL-R2026.0000765432 - stl_Rb4Mey
2026-08-11   -43,00   Mollie Reversal - SEPA Direct Debit Failed - MOL-NL-R2026.0001234567 - stl_Rb4Mey
```

Elke betaling komt op de dag van betalen, met het `tr_`-kenmerk erin. Staat dat kenmerk ook op je verkoopfactuur, dan koppelt Moneybird de twee vanzelf.

## Installeren met een AI-assistent

Werk je met een AI-assistent die op je eigen computer commando's mag uitvoeren, zoals Claude Code, OpenAI Codex of Cursor, dan kan die de installatie met je doorlopen. In deze repo staat daarvoor `AGENTS.md`: de stappen, de controles en wat de assistent nooit zonder jou mag doen.

Open een terminal in een lege map, start je assistent en plak dit:

```
Installeer https://github.com/RobertWValentine/mollie-naar-moneybird voor mij.
Lees eerst AGENTS.md in die repo en volg die stap voor stap.
Vraag mij nooit om tokens in deze chat te plakken: ik zet ze zelf in .env.
Schrijf niets naar Moneybird zonder dat ik de droogloop heb gezien en ja heb gezegd.
```

Een gewone chat in de browser (ChatGPT, Claude.ai) kan geen commando's op jouw computer uitvoeren. Die kan je wel door deze README praten: plak de link en vraag om uitleg per stap.

## Installeren, stap voor stap

### 1. Code ophalen

```bash
git clone https://github.com/RobertWValentine/mollie-naar-moneybird.git
cd mollie-naar-moneybird
```

Geen git? Download de zip via de groene knop **Code** op GitHub en pak hem uit.

Controleer dan of de tijdzone er is:

```bash
python3 -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Amsterdam')"
```

Dit hoort **niets** te tonen. Zie je `ZoneInfoNotFoundError`, installeer dan de tijdzonedata met `pip install tzdata` of op Linux `sudo apt install tzdata`. Het script weigert zonder tijdzone te draaien. Dat is met opzet: ruim een derde van de betalingen valt na 22:00 UTC en zou anders op de verkeerde dag landen.

Wil je eerst zien dat alles werkt, draai dan de tests. Die hebben pytest nodig en geen internet:

```bash
python3 -m pip install pytest
python3 -m pytest tests/ -q
```

Je ziet dan zoiets als:

```
............................................................  [100%]
60 passed in 0.12s
```

### 2. Mollie-token maken

In het Mollie-dashboard: **Ontwikkelaars > API access tokens > organisatie-toegangstoken aanmaken**. Het token begint met `access_`. Een gewone API-key (`live_...`) is aan één website gekoppeld en werkt hier niet.

Geef alleen leesrechten: `payments.read`, `settlements.read`, `refunds.read`, `chargebacks.read`. Het script schrijft nooit iets naar Mollie.

### 3. Moneybird klaarzetten

1. **Administratie-ID.** Open je administratie in Moneybird. Het lange getal in de adresbalk, direct na `moneybird.com/`, is het ID.
2. **Rekening voor Mollie.** Heb je nog geen aparte rekening voor je Mollie-saldo, maak die dan aan in Moneybird, zonder bankkoppeling. Draai dit script nooit op je gewone bankrekening.
3. **Token.** Ga naar **Instellingen > Externe en AI-koppelingen > API token aanmaken**. Het formulier staat onderaan de pagina, onder de uitleg. Rechten: facturen, documenten, bank, instellingen.
4. **Automatisch koppelen.** Laat **automatisch koppelen** bij je bankrekeningen aanstaan. Die functie hangt de betalingen op het `tr_`-kenmerk aan je facturen.

### 4. `.env` invullen

```bash
cp .env.example .env
chmod 600 .env
```

Open `.env` in een teksteditor en vul in:

```
MOLLIE_TOKEN=access_...
MONEYBIRD_TOKEN=...
MONEYBIRD_ADMINISTRATION_ID=123456789012345678
```

`MONEYBIRD_FINANCIAL_ACCOUNT_ID` laat je nog even leeg. Die vind je in de volgende stap. `.env` staat in `.gitignore` en gaat dus nooit mee naar GitHub.

Op een Mac mag een token ook in de keychain in plaats van in `.env`: service `mollie-api` of `moneybird-api`, account `default` (of wat je in `KEYCHAIN_ACCOUNT` zet).

### 5. De juiste rekening kiezen

```bash
./bin/run.sh --rekeningen
```

Je ziet de rekeningen van je administratie, met hun ID ervoor. Bijvoorbeeld:

```
  421098765432109876  BankAccount            Zakelijke rekening
  438765432109876543  BankAccount            Mollie
```

Zie je rekeningen van een andere administratie, dan hoort je token bij de verkeerde administratie. Zet het ID van de Mollie-rekening in `.env`:

```
MONEYBIRD_FINANCIAL_ACCOUNT_ID=438765432109876543
```

### 6. Oude koppeling uitzetten

Gebruik je nu een andere dienst die Mollie-transacties in Moneybird zet, trek die koppeling dan eerst in: **Instellingen > Externe en AI-koppelingen**, de regel van die dienst verwijderen. Verwijder ook de webhooks van die dienst. Twee importeurs tegelijk geeft dubbele regels.

### 7. Droogloop

```bash
./bin/run.sh --aansluiten --dry-run --dagen 30
```

Dit schrijft niets. Het vergelijkt de laatste 30 dagen bij Mollie met wat er al op de rekening in Moneybird staat. Bij een rekening met veel regels duurt dat een paar minuten, omdat Moneybird maar 150 verzoeken per 5 minuten toestaat. Je ziet zoiets als:

```
2026-09-27 10:15:02,114 INFO Bestaande mutaties ophalen uit Moneybird...
2026-09-27 10:17:40,882 INFO 1204 mutaties gevonden op rekening 438765432109876543
2026-09-27 10:17:44,310 INFO Opgehaald: 312 regels (betalingen 280, chargebacks 9, refunds 2, afrekeningen 21)
2026-09-27 10:17:44,402 INFO Al geboekt: 305. Nog te boeken: 7.
2026-09-27 10:17:44,403 INFO   ONTBREEKT 2026-09-26       8.00  Mollie Payment - J. Jansen - Bestelling 10712 - tr_...
...
1204 bestaande mutaties, 312 Mollie-regels, 305 al geboekt, 7 ontbrak
```

Zo lees je het:

- **Een klein aantal ontbrekend** betekent dat je vorige koppeling iets achterliep. Normaal.
- **Honderden ontbrekend** op een rekening die al jaren gevuld wordt: stop en zoek eerst uit waarom. Vaak boekte de vorige koppeling op een andere datum.
- **Een lege rekening** geeft een foutmelding. Dat vangnet zit erin omdat een verkeerd rekening-ID anders het hele venster als ontbrekend zou boeken. Is de rekening echt nieuw en leeg, draai dan met `--forceer-leeg`.

### 8. Aansluiten

Klopt de droogloop, draai hem dan echt:

```bash
./bin/run.sh --aansluiten --dagen 30
```

```
1204 bestaande mutaties, 312 Mollie-regels, 305 al geboekt, 7 ontbrak, afschrift 445566778899001122
```

In Moneybird staat nu één nieuw afschrift met de ontbrekende regels. Wat al geboekt was, onthoudt het script, zodat het dat nooit opnieuw boekt. Je mag `--aansluiten` zo vaak draaien als je wilt: het kijkt steeds naar wat er feitelijk op de rekening staat.

### 9. Controleren

```bash
./bin/run.sh --controleer
```

```
2026-09-27 10:21:05,017 INFO stl_Rb4Mey: bruto 2019.39 + correcties -43.00 + terugboekingen -130.81 - uitbetaling 1845.58 = 0.00  OK
...
4 afrekeningen getoetst, 0 wijken af
```

Per afrekening telt het script alle regels op en legt dat naast wat Mollie werkelijk uitbetaalde. Sluit dat, dan mist er geen soort regel. Een cent verschil is afronding, want Mollie rekent kosten in vier decimalen.

Kijk daarna ook in Moneybird zelf: de betalingen horen vanzelf aan hun facturen te hangen.

### 10. Een gewone ronde

```bash
./bin/run.sh --dry-run    # eerst kijken
./bin/run.sh              # boeken
```

```
7 regels, afschrift 445566778899001133
```

Is er niets bij gekomen, dan staat er `Niets nieuws.` in het logboek en `0 regels` op de laatste regel. Dit is de ronde die je elk uur laat draaien.

### PayPal (optioneel)

Een PayPal-betaling via Mollie raakt het Mollie-saldo niet: het geld gaat rechtstreeks naar je PayPal-account. Die transacties haalt het script daarom bij PayPal zelf op en zet ze op een eigen rekening in Moneybird.

1. Maak in het PayPal-ontwikkelaarsportaal een app voor live gebruik en noteer client-ID en secret.
2. Maak in Moneybird een rekening voor PayPal en zoek het ID op met `--rekeningen`.
3. Vul in `.env`: `MONEYBIRD_PAYPAL_ACCOUNT_ID`, `PAYPAL_CLIENT_ID` en `PAYPAL_SECRET`.
4. Draai `./bin/run.sh --paypal --dry-run` en daarna zonder `--dry-run`.

Aan het eind toetst het script het saldo in Moneybird tegen dat bij PayPal en meldt een verschil.

## Automatisch laten draaien

**Linux-server (cron).** Open `crontab -e` en zet erin:

```
17 * * * * /pad/naar/mollie-naar-moneybird/bin/run.sh >> /var/log/mollie-moneybird-sync.log 2>&1
37 * * * * /pad/naar/mollie-naar-moneybird/bin/run.sh --paypal >> /var/log/mollie-moneybird-sync.log 2>&1
```

De tweede regel alleen als je PayPal gebruikt. Zet `STATE_PATH` in `.env` op een map die blijft bestaan, bijvoorbeeld `/var/lib/mollie-moneybird-sync/state.db`. Maak die map eerst aan.

**Mac (launchd).** Maak `~/Library/LaunchAgents/mollie-moneybird-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>mollie-moneybird-sync</string>
    <key>ProgramArguments</key>
    <array><string>/Users/JOUWNAAM/mollie-naar-moneybird/bin/run.sh</string></array>
    <key>StartInterval</key><integer>3600</integer>
    <key>StandardOutPath</key><string>/Users/JOUWNAAM/Library/Logs/mollie-moneybird-sync.log</string>
    <key>StandardErrorPath</key><string>/Users/JOUWNAAM/Library/Logs/mollie-moneybird-sync.log</string>
</dict>
</plist>
```

Zet hem aan met `launchctl load ~/Library/LaunchAgents/mollie-moneybird-sync.plist`.

Slaapt de machine, dan slaat een ronde over en haalt de volgende alles in: het script kijkt `MAX_LOOKBACK_DAYS` terug (standaard 14) en slaat over wat al verwerkt is. Lag hij langer plat, draai dan eenmalig `--aansluiten --dagen` met een ruimer venster.

**Bijwerken.** `git pull` in de map. Wat al verwerkt is staat in de state (`STATE_PATH`) en blijft bewaard.

**Stoppen.** Haal de cronregel weg of doe `launchctl unload` op de plist. Er blijft niets draaien.

## Als er iets misgaat

| wat je ziet | wat het betekent |
|---|---|
| `Instelling ontbreekt: ...` | een waarde in `.env` is leeg of `.env` staat in een andere map. De melding zegt welke waarde en waar je hem vindt |
| `Mollie weigert het verzoek` of `Moneybird weigert het verzoek` | het token klopt niet, hoort bij een andere administratie of mist rechten. Maak het opnieuw aan volgens stap 2 of 3 |
| `Tijdzonedata voor Europe/Amsterdam ontbreekt` | installeer `tzdata`, zie stap 1 |
| `Rekening ... bevat geen enkele mutatie` | verkeerd rekening-ID of token van een andere administratie; bij een echt lege rekening `--forceer-leeg` |
| exitcode 1 | de run is gestopt, er is niets half geboekt |
| `Er draait al een run` | een andere run is bezig, exitcode 0, de volgende ronde gaat gewoon door |
| `Een vorige run is afgebroken tijdens het schrijven` | zoek de genoemde referentie op in Moneybird. Staat het afschrift er: laat het staan en draai `--aansluiten`. Staat het er niet: draai opnieuw. Daarna `--wis-intentie` |
| `Moneybird nam X van de Y regels aan` | Moneybird verwierp regels. Er is niets als verwerkt weggeschreven, dus na het wegnemen van de oorzaak draait hij gewoon opnieuw |
| `Poging 1 mislukt (...), opnieuw over ...s` | een leesverzoek mislukte en wordt herhaald. Schrijfverzoeken worden nooit herhaald |

Een heel afschrift terugdraaien: `./bin/run.sh --verwijder-afschrift <id>`. Dat verwijdert ook de mutaties eronder. Let op: mutaties die al aan een factuur gekoppeld zijn, worden daarmee stil ontkoppeld en die facturen springen terug naar open.

Meer detail in het logboek met `--verbose`.

## Hoe het werkt

Vier bronnen, elk met zijn eigen boekmoment:

| bron | wanneer | regel |
|---|---|---|
| betaling | op de betaaldatum | brutobedrag, met `tr_` |
| chargeback | op de terugboekdatum | negatief bedrag, met reden, `chb_` en `tr_` |
| refund | zodra hij is verwerkt | negatief bedrag, met `re_` en `tr_` |
| afrekening | op de uitbetaaldag | uitbetaling, kostentotalen per periode en correcties |

**Kosten** staan bewust niet per transactie. Mollie rekent ze af per afrekeningsperiode en per kostensoort. Elk periodeblok draagt zijn eigen Mollie-factuurnummer. Dat nummer is er al voordat de factuur bestaat, dus de kostenregel verwijst meteen naar de juiste factuur.

**Datums** staan in Nederlandse tijd, inclusief zomertijd.

**Teruggeboekte incasso's** koppelt `--terugboekingen` aan hun creditnota, op het `chb_`-kenmerk en nooit op het bedrag.

**Dubbelbescherming** in drie lagen:

1. Elke verwerkte gebeurtenis staat met zijn eigen sleutel in SQLite. Hij komt daar pas in nadat Moneybird het afschrift heeft bevestigd.
2. Een lockfile met proces-ID voorkomt dat twee runs elkaar overlappen.
3. Schrijfacties worden nooit herhaald bij een serverfout of een time-out, want dan weet je niet of Moneybird het al verwerkt had.

**Het saldo** van de Mollie-rekening in Moneybird is geen goede maatstaf. Het script boekt op de betaaldatum, Mollie rekent later af, dus er staat altijd geld onderweg. Toets met `--controleer`.

**Wat het niet ziet.** Alles binnen een afrekening sluit op de cent. Daarbuiten vallen drie dingen: Mollie die bij je afschrijft als je saldo negatief loopt, een correctie van een Mollie-factuur buiten een afrekening om en aflossingen van Mollie Capital. Die zie je aan een saldo dat afwijkt van wat Mollie zegt.

## Geen garantie, geen support

Dit is gereedschap dat we zelf gebruiken en delen zoals het is, onder de MIT-licentie: zonder garantie en zonder aansprakelijkheid. Het schrijft in je boekhouding. Draai het eerst met `--dry-run` en het liefst eerst tegen een Moneybird-testadministratie. Controleer het resultaat met `--controleer` en met je eigen ogen.

## Licentie

MIT, zie `LICENSE`.
