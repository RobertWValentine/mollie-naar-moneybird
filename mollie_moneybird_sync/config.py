from __future__ import annotations

"""Configuratie uit omgevingsvariabelen.

Op een Mac mag een token ook in de keychain staan. De service heet dan
mollie-api, moneybird-api of paypal-api, met als account de waarde van
KEYCHAIN_ACCOUNT (standaard "default").
"""
import os
import subprocess


def _keychain(service: str, account: str) -> str | None:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _keychain_account() -> str:
    return os.environ.get("KEYCHAIN_ACCOUNT", "default")


class ConfigFout(RuntimeError):
    """Een instelling ontbreekt. De melding zegt welke en waar hij vandaan komt."""


def _secret(env_naam: str, service: str, account: str) -> str:
    waarde = os.environ.get(env_naam) or _keychain(service, account)
    if not waarde:
        raise ConfigFout(
            f"Geen token gevonden. Zet {env_naam} in de omgeving, of in de keychain "
            f"onder service '{service}' met account '{account}'."
        )
    return waarde


def _verplicht(naam: str, uitleg: str) -> str:
    waarde = os.environ.get(naam, "").strip()
    if not waarde:
        raise ConfigFout(f"{naam} is niet ingesteld. Zet het in .env. {uitleg}")
    return waarde


def _geheel(naam: str, standaard: int) -> int:
    """Een geheel getal uit de omgeving. Leeg is de standaardwaarde; iets anders
    dan een getal is een leesbare fout in plaats van een Python-foutmelding."""
    waarde = os.environ.get(naam, "").strip()
    if not waarde:
        return standaard
    try:
        return int(waarde)
    except ValueError:
        raise ConfigFout(f"{naam} moet een heel getal zijn, nu '{waarde}'. Pas het aan in .env.") from None


class Config:
    def __init__(self) -> None:
        # Tokens en ID's worden pas opgehaald als een opdracht ze gebruikt.
        # Zo werkt --rekeningen al voordat het rekening-ID bekend is, en zegt
        # een ontbrekende instelling welke het is in plaats van een KeyError.
        # De PayPal-kant staat los. Een administratie zonder PayPal hoeft deze
        # niet te zetten; de PayPal-run weigert dan met een leesbare melding in
        # plaats van op een KeyError te struikelen.
        self.paypal_rekening_id = os.environ.get("MONEYBIRD_PAYPAL_ACCOUNT_ID", "")
        self._paypal_sleutels: tuple | None = None
        self.state_pad = os.environ.get(
            "STATE_PATH", os.path.expanduser("~/.mollie-moneybird-sync/state.db")
        )
        # De lock staat standaard naast de state, in een map van de gebruiker die
        # de run draait. In een gedeelde map als /tmp kan een andere gebruiker
        # het bestand aanmaken en daarmee elke ronde tegenhouden.
        self.lock_pad = os.environ.get("LOCK_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(self.state_pad)), "mollie-moneybird-sync.lock"
        )
        # Een lock die langer bezet is dan dit aantal minuten is geen gewone
        # overlap meer maar een vastgelopen run of een vreemd bestand. De run
        # eindigt dan met exitcode 3, zodat een hartslagmonitor rood wordt.
        # Standaard 90: ruim boven een uurlijkse cron, zodat de grens niet op
        # het interval zelf valt.
        self.lock_alarm_minuten = _geheel("LOCK_ALERT_MINUTES", 90)
        # Hoe ver terug we kijken. Let op: dit venster loopt op de datum
        # waarop een betaling is aangemaakt, terwijl we boeken op de datum
        # waarop hij is voldaan. Gemeten zit daar tot vijf dagen tussen, met
        # het zwaartepunt op twee tot vier. Veertien dagen geeft dus ruime
        # marge; korter dan een week is vragen om gemiste betalingen.
        self.max_terugkijk_dagen = _geheel("MAX_LOOKBACK_DAYS", 14)

    @property
    def mollie_token(self) -> str:
        return _secret("MOLLIE_TOKEN", "mollie-api", _keychain_account())

    @property
    def moneybird_token(self) -> str:
        return _secret("MONEYBIRD_TOKEN", "moneybird-api", _keychain_account())

    @property
    def administratie_id(self) -> str:
        return _verplicht(
            "MONEYBIRD_ADMINISTRATION_ID",
            "Dat is het lange getal in de adresbalk van Moneybird, direct na moneybird.com/.",
        )

    @property
    def rekening_id(self) -> str:
        return _verplicht(
            "MONEYBIRD_FINANCIAL_ACCOUNT_ID",
            "Zoek het ID van je Mollie-rekening op met --rekeningen.",
        )

    # De PayPal-sleutels worden pas opgehaald als de PayPal-run ze nodig heeft.
    # Een administratie zonder PayPal hoeft ze niet te hebben, en een gewone
    # Mollie-run moet niet stuklopen op een ontbrekende sleutel.
    @property
    def paypal_client_id(self) -> str:
        return self._paypal("PAYPAL_CLIENT_ID", f"{_keychain_account()}-client-id")

    @property
    def paypal_secret(self) -> str:
        return self._paypal("PAYPAL_SECRET", f"{_keychain_account()}-secret")

    def _paypal(self, env_naam: str, account: str) -> str:
        return _secret(env_naam, "paypal-api", account)
