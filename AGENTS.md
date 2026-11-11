# Instructies voor AI-assistenten

Dit bestand is voor AI-assistenten die deze repo voor iemand installeren of aanpassen, zoals Claude Code, OpenAI Codex, Cursor of een vergelijkbaar programma. Praat met de gebruiker in de taal van de gebruiker. De README is de handleiding voor mensen. Dit bestand zegt wat jij doet, wat je controleert en wat je nooit zonder de gebruiker doet.

Dit programma schrijft in iemands boekhouding. Een fout daar kost de gebruiker uren herstelwerk of geeft een verkeerde btw-aangifte. Werk daarom langzaam en laat elke stap zien.

## Harde regels

1. **Vraag nooit om tokens in de chat.** Laat de gebruiker ze zelf in `.env` zetten. Lees `.env` niet voor, toon er geen waarden uit en zet er nooit iets van in een commit, logbestand of issue.
2. **Nooit schrijven zonder droogloop.** Draai elke ronde eerst met `--dry-run`, laat de uitvoer zien, leg uit wat er zou gebeuren en wacht op een uitdrukkelijk ja van de gebruiker.
3. **Deze vlaggen alleen na expliciete toestemming:** `--forceer-leeg`, `--verwijder-afschrift`, `--wis-intentie` en `--handmatig-geboekt`. Leg eerst uit wat ze doen en waarom je ze nodig denkt te hebben.
4. **Nooit op de gewone bankrekening.** `MONEYBIRD_FINANCIAL_ACCOUNT_ID` moet een aparte rekening voor Mollie zijn. Twijfel je, vraag het.
5. **Eén importeur tegelijk.** Vraag of er al een andere dienst Mollie-transacties in Moneybird zet. Zo ja: de gebruiker trekt die eerst in. Anders ontstaan dubbele regels.
6. **Stop bij iets onverwachts.** Een foutmelding, honderden ontbrekende regels, een lege rekening of een verschil bij `--controleer`: stop, laat het zien en vraag hoe verder. Ga niet zelf repareren in de boekhouding.
7. **Pas de code niet aan om een fout weg te werken** tijdens een installatie. De meldingen zijn vangnetten.

## Stappen

Werk ze in deze volgorde af. Na elke stap: vertel kort wat je zag.

1. **Omgeving.** `python3 --version` moet 3.9 of hoger zijn. Controleer de tijdzone met `python3 -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Amsterdam')"`. Die hoort niets te tonen. Zo niet: `pip install tzdata` of `sudo apt install tzdata`, met toestemming.
2. **Code.** Clone de repo in een map die de gebruiker kiest. Draai `python3 -m pip install pytest` en `python3 -m pytest tests/ -q`. Alle tests moeten slagen. Ze hebben geen internet nodig.
3. **Mollie-token.** Laat de gebruiker in het Mollie-dashboard een organisatie-toegangstoken maken (begint met `access_`), alleen leesrechten: `payments.read`, `settlements.read`, `refunds.read`, `chargebacks.read`. Een `live_`-key werkt niet.
4. **Moneybird.** Laat de gebruiker:
   - het administratie-ID uit de adresbalk halen (het getal na `moneybird.com/`);
   - een aparte rekening voor Mollie aanmaken als die er nog niet is, zonder bankkoppeling;
   - een API-token maken via Instellingen > Externe en AI-koppelingen, met rechten voor facturen, documenten, bank en instellingen;
   - controleren dat automatisch koppelen bij de bankrekeningen aanstaat.
5. **`.env`.** Draai `cp .env.example .env && chmod 600 .env`. Vraag de gebruiker `MOLLIE_TOKEN`, `MONEYBIRD_TOKEN` en `MONEYBIRD_ADMINISTRATION_ID` zelf in te vullen en te melden wanneer dat klaar is.
6. **Rekening.** Draai `./bin/run.sh --rekeningen`. Laat de lijst zien en vraag welke de Mollie-rekening is. Laat de gebruiker dat ID in `MONEYBIRD_FINANCIAL_ACCOUNT_ID` zetten.
7. **Oude koppeling.** Vraag naar een bestaande importeur (regel 5 hierboven).
8. **Droogloop.** Draai `./bin/run.sh --aansluiten --dry-run --dagen 30`. Dat kan een paar minuten duren. Vat samen: hoeveel mutaties er al staan, hoeveel Mollie-regels, hoeveel al geboekt en hoeveel ontbreken. Een klein aantal ontbrekend is normaal. Honderden op een gevulde rekening: stop en overleg.
9. **Aansluiten.** Pas na een ja: `./bin/run.sh --aansluiten --dagen 30`. Meld het afschrift-ID uit de laatste regel.
10. **Controleren.** Draai `./bin/run.sh --controleer`. Alle afrekeningen horen `OK` te geven. Een cent verschil is afronding. Vraag de gebruiker in Moneybird te kijken of de betalingen aan hun facturen hangen.
11. **Automatisch.** Vraag of het elk uur moet draaien en op welk systeem. Gebruik de cron- of launchd-voorbeelden uit de README en vul de echte paden in. Laat het bestand zien voordat je het activeert.
12. **PayPal**, alleen als de gebruiker PayPal via Mollie gebruikt: zie de README. Weer eerst `--paypal --dry-run`.

## Na afloop

Geef de gebruiker een korte samenvatting: waar de code staat, waar `.env` en de state staan, hoe vaak het draait, waar het logboek staat en hoe je het stopt. Wijs op de sectie "Als er iets misgaat" in de README.

## Als je code wijzigt

Draai `python3 -m pytest tests/ -q` en `ruff check mollie_moneybird_sync tests` vóór elke commit en werk `CHANGELOG.md` bij. Zet nooit echte klantnamen, transactiekenmerken, IBAN's of administratie-ID's in code, tests of documentatie: dit is een openbare repo.
