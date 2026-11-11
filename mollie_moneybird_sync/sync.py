from __future__ import annotations

"""Voert één synchronisatieronde uit."""
import datetime as dt
import hashlib
import logging
import os

from .aansluiten import splits
from .config import Config
from .gebeurtenissen import (
    NietTeBoeken,
    van_afrekening,
    van_betaling,
    van_chargeback,
    van_paypal_transactie,
    van_refund,
)
from .mollie_client import MollieClient
from .moneybird_client import MoneybirdClient
from .paypal_client import PaypalClient, eindsaldo
from .state import State
from .terugboekingen import is_terugboeking, zoek_creditnota
from .tijd import lokale_datum

log = logging.getLogger(__name__)


class Vergrendeld(RuntimeError):
    pass


class Lock:
    """Voorkomt dat twee runs elkaar overlappen.

    Het aanmaken gebeurt met O_EXCL, zodat twee processen die tegelijk starten
    niet allebei door kunnen. Een oude lockfile wordt alleen opgeruimd als het
    proces erin aantoonbaar weg is; een run die langer duurt dan verwacht mag
    niet door de volgende opzij worden gezet. Bij het opruimen controleren we
    of de lock nog van ons is.
    """

    def __init__(self, pad: str):
        self.pad = pad
        self.van_ons = False

    def _draait_nog(self) -> bool:
        try:
            with open(self.pad) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def __enter__(self):
        for poging in (1, 2):
            try:
                fd = os.open(self.pad, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._draait_nog():
                    raise Vergrendeld(
                        f"Er draait al een run. Lockfile: {self.pad}"
                    ) from None
                if poging == 1:
                    log.warning("Lockfile van een verdwenen proces opgeruimd")
                    try:
                        os.remove(self.pad)
                    except FileNotFoundError:
                        pass
                    continue
                raise Vergrendeld(f"Lockfile blijft bestaan: {self.pad}") from None
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self.van_ons = True
            return self
        raise Vergrendeld(f"Kon de lock niet nemen: {self.pad}")

    def __exit__(self, *_):
        if not self.van_ons:
            return
        try:
            with open(self.pad) as f:
                if int(f.read().strip() or 0) != os.getpid():
                    return
            os.remove(self.pad)
        except (OSError, ValueError):
            pass


def verzamel(mollie: MollieClient, grens: str, fouten: list | None = None) -> list:
    """Haalt alle boekbare gebeurtenissen op vanaf de grensdatum.

    Vier bronnen, elk met zijn eigen moment van boeken. Betalingen worden
    opgehaald op aanmaakdatum maar geboekt op betaaldatum; die twee liggen
    doorgaans een dag uit elkaar, dus het venster moet ruimer zijn dan de
    periode die je wilt boeken.

    Een record dat niet veilig te boeken is (NietTeBoeken) komt in `fouten` en de rest
    gaat gewoon door; de aanroeper laat de ronde daarna met exitcode 1 eindigen.
    """
    regels: list = []
    aantallen: dict = {}
    fouten = fouten if fouten is not None else []

    def veilig(functie, record):
        try:
            return functie(record)
        except NietTeBoeken as e:
            log.error("Niet geboekt: %s", e)
            fouten.append(str(e))
            return None

    for betaling in mollie.betalingen(grens):
        regel = van_betaling(betaling)
        if regel:
            regels.append(regel)
    aantallen["betalingen"] = len(regels)

    voor = len(regels)
    for chargeback in mollie.chargebacks(grens):
        regels.extend(veilig(van_chargeback, chargeback) or [])
    aantallen["chargebacks"] = len(regels) - voor

    voor = len(regels)
    for refund in mollie.refunds(grens):
        # Zonder settlementAmount (weg per 1 januari 2027) is de betaalmethode nodig;
        # stuurt Mollie de betaling niet mee, dan halen we haar op.
        if (not refund.get("settlementAmount") and not (refund.get("_embedded") or {}).get("payment")
                and refund.get("paymentId")):
            refund = dict(refund, _embedded={"payment": mollie.betaling(refund["paymentId"])})
        regel = veilig(van_refund, refund)
        if regel:
            regels.append(regel)
    aantallen["refunds"] = len(regels) - voor

    voor = len(regels)
    for afrekening in mollie.afrekeningen():
        uitbetaald = lokale_datum(afrekening.get("settledAt") or "")
        if uitbetaald and uitbetaald >= grens:
            regels.extend(van_afrekening(afrekening))
    aantallen["afrekeningen"] = len(regels) - voor

    # Op het werkelijke tijdstip, niet op de sleutel. Die sleutel is bij een
    # betaling het tr_-kenmerk, en dat is een willekeurige reeks; sorteren
    # daarop zet de regels van een dag in willekeurige volgorde in Moneybird.
    regels.sort(key=lambda r: (r["date"], r.get("tijd", ""), r["sleutel"]))
    log.info(
        "Opgehaald: %d regels (betalingen %d, chargebacks %d, refunds %d, afrekeningen %d)",
        len(regels), aantallen["betalingen"], aantallen["chargebacks"],
        aantallen["refunds"], aantallen["afrekeningen"],
    )
    return regels


def _grens(dagen: int) -> str:
    return (dt.date.today() - dt.timedelta(days=dagen)).isoformat()


def _referentie(voorvoegsel: str, regels: list) -> str:
    """Een referentie die bij dezelfde inhoud altijd gelijk is.

    Zo is een afschrift na een onderbroken run terug te vinden in Moneybird.
    """
    sleutel = hashlib.sha1(
        "".join(r["sleutel"] for r in regels).encode()
    ).hexdigest()[:10]
    return f"{voorvoegsel}-{regels[0]['date']}-{len(regels)}-{sleutel}"


def _controleer_intentie(state: State) -> None:
    """Weigert te draaien als een vorige run halverwege is gestorven."""
    rij = state.openstaande_intentie()
    if not rij:
        return
    referentie, aantal, gestart = rij
    raise RuntimeError(
        f"Een vorige run is afgebroken tijdens het schrijven ({gestart}). Er kan een "
        f"afschrift met referentie '{referentie}' en {aantal} regels in Moneybird "
        "staan dat niet is onthouden. Zoek dat op: staat het er, verwijder het met "
        f"--verwijder-afschrift, of laat het staan en draai --aansluiten. Wis daarna "
        "de intentie met --wis-intentie. Zonder deze controle zouden die regels "
        "opnieuw geboekt worden."
    )


def _schrijf(moneybird: MoneybirdClient, config: Config, state: State,
             regels: list, voorvoegsel: str, rekening_id: str = "") -> str:
    """Zet de regels als één afschrift weg en onthoudt ze pas daarna."""
    mutaties = [{"date": r["date"], "amount": r["amount"], "message": r["message"]}
                for r in regels]
    referentie = _referentie(voorvoegsel, regels)

    state.zet_intentie(referentie, len(mutaties))
    afschrift = moneybird.maak_afschrift(rekening_id or config.rekening_id,
                                         referentie, mutaties)

    afschrift_id = str(afschrift.get("id", ""))
    geboekt = afschrift.get("financial_mutations") or []
    if not afschrift_id:
        raise RuntimeError(
            f"Moneybird gaf geen afschrift-ID terug voor referentie {referentie}."
        )
    if len(geboekt) != len(mutaties):
        raise RuntimeError(
            f"Moneybird nam {len(geboekt)} van de {len(mutaties)} regels aan in "
            f"afschrift {afschrift_id}. Niets is als verwerkt weggeschreven, zodat "
            "de ontbrekende regels niet stilzwijgend verdwijnen."
        )

    state.markeer([r["sleutel"] for r in regels], afschrift_id, regels[-1]["date"])
    state.wis_intentie(referentie)
    return afschrift_id


def draai(config: Config, dry_run: bool = False) -> dict:
    mollie = MollieClient(config.mollie_token)
    moneybird = MoneybirdClient(config.moneybird_token, config.administratie_id)
    state = State(config.state_pad)
    _controleer_intentie(state)

    fouten: list = []
    regels = verzamel(mollie, _grens(config.max_terugkijk_dagen), fouten)
    nieuw = [r for r in regels if not state.gezien(r["sleutel"])]

    if not nieuw:
        log.info("Niets nieuws.")
        state.sluit()
        return {"regels": 0, "afschrift_id": None, "niet_te_boeken": len(fouten)}

    if dry_run:
        log.info("DRY RUN, er wordt niets geschreven. %d regels:", len(nieuw))
        for r in nieuw[:40]:
            log.info("  %s %10s  %s", r["date"], r["amount"], r["message"])
        if len(nieuw) > 40:
            log.info("  ... en nog %d", len(nieuw) - 40)
        state.sluit()
        return {"regels": len(nieuw), "afschrift_id": None, "dry_run": True, "niet_te_boeken": len(fouten)}

    afschrift_id = _schrijf(moneybird, config, state, nieuw, "mollie")
    state.sluit()
    log.info("Afschrift %s aangemaakt met %d regels", afschrift_id, len(nieuw))
    return {"regels": len(nieuw), "afschrift_id": afschrift_id, "niet_te_boeken": len(fouten)}


def aansluiten(
    config: Config,
    dagen: int = 30,
    dry_run: bool = False,
    forceer_leeg: bool = False,
) -> dict:
    """Overstap van de oude koppeling: boek precies wat er nog niet staat.

    Vergelijkt met wat er feitelijk in de Moneybird-rekening staat, niet met
    een tijdstip. Zo maakt het niet uit of de oude koppeling er halverwege mee
    ophield of een gat liet.
    """
    mollie = MollieClient(config.mollie_token)
    moneybird = MoneybirdClient(config.moneybird_token, config.administratie_id)
    state = State(config.state_pad)
    _controleer_intentie(state)

    log.info("Bestaande mutaties ophalen uit Moneybird...")
    bestaand = moneybird.mutaties(config.rekening_id)
    log.info("%d mutaties gevonden op rekening %s", len(bestaand), config.rekening_id)

    if not bestaand and not forceer_leeg:
        state.sluit()
        raise RuntimeError(
            f"Rekening {config.rekening_id} bevat geen enkele mutatie. Dat wijst op een "
            "verkeerd rekening-ID of een token voor de verkeerde administratie. Zonder "
            "die controle zou het hele venster als ontbrekend worden geboekt. Klopt het "
            "dat de rekening leeg is, draai dan met --forceer-leeg."
        )

    fouten: list = []
    regels = verzamel(mollie, _grens(dagen), fouten)
    geboekt, ontbreekt = splits(regels, bestaand)
    log.info("Al geboekt: %d. Nog te boeken: %d.", len(geboekt), len(ontbreekt))

    resultaat = {
        "bestaande_mutaties": len(bestaand),
        "regels": len(regels),
        "al_geboekt": len(geboekt),
        "ontbreekt": len(ontbreekt),
        "afschrift_id": None,
        "niet_te_boeken": len(fouten),
    }

    if dry_run:
        for r in ontbreekt[:40]:
            log.info("  ONTBREEKT %s %10s  %s", r["date"], r["amount"], r["message"])
        if len(ontbreekt) > 40:
            log.info("  ... en nog %d", len(ontbreekt) - 40)
        resultaat["dry_run"] = True
        state.sluit()
        return resultaat

    if geboekt:
        state.markeer([r["sleutel"] for r in geboekt], "bestond-al", geboekt[-1]["date"])

    if ontbreekt:
        resultaat["afschrift_id"] = _schrijf(
            moneybird, config, state, ontbreekt, "mollie-aansluiting")
        log.info("Aansluitafschrift %s met %d regels",
                 resultaat["afschrift_id"], len(ontbreekt))

    state.sluit()
    return resultaat


def draai_paypal(config: Config, dagen: int | None = None, dry_run: bool = False) -> dict:
    """Haalt PayPal-transacties op en zet ze op de PayPal-rekening.

    De rekening staat los van Mollie: PayPal-betalingen raken het Mollie-saldo
    nooit. Na afloop toetsen we het saldo tegen wat PayPal zelf zegt. Dat kan
    hier wél, anders dan bij Mollie, omdat elke geleverde transactie zijn eigen
    `ending_balance` draagt en er bij PayPal niets onderweg is.
    """
    if not config.paypal_rekening_id:
        raise RuntimeError(
            "Geen PayPal-rekening ingesteld. Zet MONEYBIRD_PAYPAL_ACCOUNT_ID in de "
            "omgeving; het ID vind je met --rekeningen."
        )

    paypal = PaypalClient(config.paypal_client_id, config.paypal_secret)
    moneybird = MoneybirdClient(config.moneybird_token, config.administratie_id)
    state = State(config.state_pad)
    _controleer_intentie(state)

    vanaf = _grens(dagen if dagen is not None else config.max_terugkijk_dagen)
    transacties = paypal.transacties(vanaf)

    regels: list = []
    for transactie in transacties:
        regels.extend(van_paypal_transactie(transactie))
    regels.sort(key=lambda r: (r["date"], r.get("tijd", ""), r["sleutel"]))

    onbekend = [r for r in regels if not state.gezien(r["sleutel"])]

    # Ook vergelijken met wat er feitelijk op de rekening staat, niet alleen
    # met onze eigen state. Regels die er al met de hand in zijn gezet zouden
    # op een verse state anders dubbel geboekt
    # worden. De rekening is klein genoeg om dat elke ronde te doen.
    bestaand = moneybird.mutaties_klein(config.paypal_rekening_id)
    al_geboekt, nieuw = splits(onbekend, bestaand)
    if al_geboekt:
        log.info("%d regels stonden al op de rekening, alleen onthouden", len(al_geboekt))
        state.markeer([r["sleutel"] for r in al_geboekt], "bestond-al",
                      al_geboekt[-1]["date"])

    log.info("PayPal: %d regels uit %d transacties, waarvan %d nieuw",
             len(regels), len(transacties), len(nieuw))

    resultaat = {
        "transacties": len(transacties),
        "regels": len(nieuw),
        "afschrift_id": None,
        "paypal_saldo": eindsaldo(transacties),
    }

    if not nieuw:
        log.info("Niets nieuws bij PayPal.")
    elif dry_run:
        log.info("DRY RUN, er wordt niets geschreven. %d regels:", len(nieuw))
        for r in nieuw:
            log.info("  %s %10s  %s", r["date"], r["amount"], r["message"])
        resultaat["dry_run"] = True
    else:
        resultaat["afschrift_id"] = _schrijf(
            moneybird, config, state, nieuw, "paypal", config.paypal_rekening_id)
        log.info("Afschrift %s aangemaakt met %d regels",
                 resultaat["afschrift_id"], len(nieuw))

    if not dry_run:
        resultaat.update(controleer_paypal_saldo(moneybird, config, resultaat["paypal_saldo"]))

    state.sluit()
    return resultaat


def controleer_paypal_saldo(moneybird: MoneybirdClient, config: Config,
                            saldo_paypal: str | None) -> dict:
    """Toetst het saldo van de Moneybird-rekening tegen dat van PayPal.

    Zonder transacties in het venster doet PayPal geen uitspraak over het
    saldo. Dan melden we dat er niets te toetsen viel, in plaats van nul te
    veronderstellen.
    """
    if saldo_paypal is None:
        log.info("Geen PayPal-transacties in het venster, saldo niet getoetst.")
        return {"saldo_getoetst": False}

    geboekt = moneybird.saldo(config.paypal_rekening_id)
    verschil = round(geboekt - float(saldo_paypal), 2)
    if verschil == 0:
        log.info("Saldo sluit: %.2f, gelijk aan PayPal.", geboekt)
    else:
        log.warning(
            "SALDO WIJKT AF: Moneybird %.2f tegenover PayPal %s, verschil %.2f. "
            "Er ontbreekt een regel of er staat er een te veel.",
            geboekt, saldo_paypal, verschil,
        )
    return {"saldo_getoetst": True, "saldo_moneybird": geboekt,
            "saldo_paypal": float(saldo_paypal), "verschil": verschil}


def koppel_terugboekingen(config: Config, dry_run: bool = False) -> dict:
    """Hangt elke onverwerkte terugboeking aan zijn creditnota.

    Werkt alleen op de Mollie-rekening en raakt niets anders aan. Wat niet
    eenduidig te matchen is blijft staan en wordt gemeld: dat kost hooguit een
    ronde, terwijl een verkeerde koppeling handwerk kost om te herstellen.
    """
    moneybird = MoneybirdClient(config.moneybird_token, config.administratie_id)

    openstaand: list = []
    for periode in _periodes_dit_en_vorig_jaar():
        mutaties = moneybird.onverwerkt_in_periode(config.rekening_id, periode)
        openstaand.extend(m for m in mutaties if is_terugboeking(m))

    log.info("%d onverwerkte terugboekingen", len(openstaand))
    resultaat = {"gevonden": len(openstaand), "gekoppeld": 0, "overgeslagen": []}

    # Per dag hoeven we de facturenlijst maar één keer op te halen, en dat
    # scheelt op een dag met vier terugboekingen drie keer doorbladeren.
    per_dag: dict = {}
    for mutatie in sorted(openstaand, key=lambda m: m["date"]):
        datum = mutatie["date"]
        if datum not in per_dag:
            per_dag[datum] = moneybird.verkoopfacturen_van_dag(datum)
        nota, reden = zoek_creditnota(mutatie, per_dag[datum])

        if not nota:
            log.warning("  %s %8s laten staan: %s", datum, mutatie["amount"], reden)
            resultaat["overgeslagen"].append(
                {"datum": datum, "bedrag": mutatie["amount"], "reden": reden})
            continue

        if dry_run:
            log.info("  %s %8s -> creditnota %s", datum, mutatie["amount"],
                     nota["invoice_id"])
            resultaat["gekoppeld"] += 1
            continue

        moneybird.koppel_aan_document(mutatie["id"], nota["id"], mutatie["amount"])
        na = moneybird.mutatie(mutatie["id"])
        if na.get("state") != "processed" or not na.get("payments"):
            raise RuntimeError(
                f"Moneybird nam de koppeling van {datum} {mutatie['amount']} aan "
                f"creditnota {nota['invoice_id']} niet aan: state {na.get('state')}. "
                "Gestopt, zodat de rest niet blind achteraan gaat."
            )
        log.info("  %s %8s -> creditnota %s", datum, mutatie["amount"], nota["invoice_id"])
        resultaat["gekoppeld"] += 1

    if dry_run:
        resultaat["dry_run"] = True
    return resultaat


def _periodes_dit_en_vorig_jaar() -> list:
    """Halfjaarvensters, want de lijstweergave weigert boven honderd mutaties."""
    jaar = dt.date.today().year
    return [f"{j}0101..{j}0630" for j in (jaar - 1, jaar)] + \
           [f"{j}0701..{j}1231" for j in (jaar - 1, jaar)]
