from __future__ import annotations

"""Voert één synchronisatieronde uit."""
import datetime as dt
import errno
import fcntl
import hashlib
import logging
import os
import stat
import time

from .aansluiten import kenmerken_van, splits
from .config import Config
from .gebeurtenissen import (
    NietTeBoeken,
    van_afrekening,
    van_betaling,
    van_chargeback,
    van_paypal_transactie,
    van_refund,
)
from .http import HttpFout
from .mollie_client import MollieClient
from .moneybird_client import MoneybirdClient
from .paypal_client import PaypalClient, eindsaldo
from .state import State
from .terugboekingen import is_terugboeking, zoek_creditnota
from .tijd import lokale_datum, utc

log = logging.getLogger(__name__)


class Vergrendeld(RuntimeError):
    """Een andere run houdt de lock vast. `minuten` is de leeftijd van de
    lockfile, of None als die niet te bepalen is. `vreemd` zegt waarom de
    lockfile niet te vertrouwen is (leeg als hij wel te vertrouwen is)."""

    def __init__(self, melding: str, minuten: float | None = None, vreemd: str = ""):
        super().__init__(melding)
        self.minuten = minuten
        self.vreemd = vreemd


class Lock:
    """Voorkomt dat twee runs elkaar overlappen.

    De lock is een `flock` op de lockfile zelf. De kernel geeft hem vrij zodra het
    proces stopt, ook bij een crash, dus een achtergebleven lockfile houdt niets
    tegen en hoeft nooit opgeruimd te worden. Het bestand blijft na een run staan:
    wie het verwijdert terwijl een run loopt, laat de volgende run een nieuw bestand
    vergrendelen en dan draaien er twee tegelijk. Tijdens een run staat de PID erin.
    """

    def __init__(self, pad: str):
        self.pad = pad
        self._fd: int | None = None

    def _leeftijd_minuten(self, fd: int) -> float | None:
        try:
            return (time.time() - os.fstat(fd).st_mtime) / 60
        except OSError:
            return None

    @staticmethod
    def _vreemd_stat(st: os.stat_result) -> str:
        """Waarom een lockfile met deze stat verdacht is, of leeg.

        Een eigen run maakt een gewoon bestand, van dezelfde gebruiker, met de
        tijd van nu. Een symlink, een hardlink, een bestand van een andere
        gebruiker of een tijd in de toekomst is meestal door iemand anders
        achtergelaten. Een klok die meer dan een minuut terugsprong of een
        back-up met hardlinks kan dit ook bij de eigen lockfile veroorzaken.
        Zo'n bestand mag de rondes niet ongemerkt tegenhouden.
        """
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return "geen gewoon bestand"
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return "van een andere gebruiker"
        if st.st_mtime > time.time() + 60:
            return "met een tijd in de toekomst"
        return ""

    def _vreemd(self) -> str:
        """De toets van `_vreemd_stat` op het pad zelf, zonder een symlink te volgen."""
        try:
            st = os.lstat(self.pad)
        except FileNotFoundError:
            return ""
        except OSError as e:
            return f"niet te lezen ({e.__class__.__name__})"
        return self._vreemd_stat(st)

    def __enter__(self) -> Lock:
        fd = None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.pad)), mode=0o700, exist_ok=True)
            fd = os.open(self.pad, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            vreemd = self._vreemd_stat(os.fstat(fd))
            if vreemd:
                os.close(fd)
                fd = None
                raise Vergrendeld(
                    f"Lockfile {self.pad} is niet van een eigen run: {vreemd}.", None, vreemd,
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                minuten = self._leeftijd_minuten(fd)
                os.close(fd)
                fd = None
                raise Vergrendeld(f"Er draait al een run. Lockfile: {self.pad}", minuten) from None
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
        except OSError as e:
            if fd is not None:
                os.close(fd)
            reden = self._vreemd() or f"lock niet te nemen ({errno.errorcode.get(e.errno, e.errno)})"
            raise Vergrendeld(
                f"Lockfile {self.pad} is niet te gebruiken: {reden}.", None, reden,
            ) from None
        self._fd = fd
        return self

    def __exit__(self, *_) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


BETALING_WEG = (404, 410)  # de betaling bestaat niet (meer): blijvend, dus per refund melden
# Zo lang na het begin van de laatste geslaagde ronde mag een regel die de state nog niet kent
# bij --aansluiten --dry-run wachten. Ligt de import stil, dan telt daarna alles weer als gat.
RONDE_MAX_LEEFTIJD = dt.timedelta(hours=2)


def _sleutels_van(record: dict) -> list:
    """De sleutels die een terugboeking of refund in de state krijgt, zonder hem om te zetten."""
    sleutels = [record.get("id", "")]
    if record.get("reversedAt"):
        sleutels.append(f"{record.get('id', '')}:teruggedraaid")
    return sleutels


def _meld(fouten: list, gezien) -> int:
    """Logt en telt de niet te boeken records die nog niet geboekt zijn.

    Een record dat al geboekt is (in de state of al in Moneybird) telt niet mee. Na
    1 januari 2027 mist ook een al geboekte terugboeking haar settlementAmount; zonder
    deze filter werd de ronde dan onterecht rood en zou wie hem met de hand boekt hem
    dubbel boeken.
    """
    open_ = [f for f in fouten if not all(gezien(s) for s in f["sleutels"])]
    for f in open_:
        nog = ", ".join(s for s in f["sleutels"] if not gezien(s))
        log.error("Niet geboekt: %s (na een handmatige boeking vastleggen: %s)", f["melding"], nog)
    return len(open_)


def _bewaar_open(fouten: list, state: State) -> None:
    """Onthoudt de niet te boeken records die nog niet geboekt zijn.

    Zo blijven ze gemeld als ze buiten het venster vallen, tot ze met --handmatig-geboekt
    zijn vastgelegd of een ronde ze alsnog boekt.
    """
    state.onthoud_open([(s, f["melding"]) for f in fouten for s in f["sleutels"]
                        if not state.gezien(s)])


def _met_open_uit_state(fouten: list, state: State, gezien_in_venster: set) -> list:
    """`fouten` plus de open records uit de state die het venster niet meer laat zien."""
    in_fouten = {s for f in fouten for s in f["sleutels"]}
    return fouten + [
        {"sleutels": [i], "melding": f"{melding} (buiten het venster)"}
        for i, melding in state.open_niet_geboekt()
        if i not in in_fouten and i not in gezien_in_venster
    ]


def _ruim_open_op(fouten: list, state: State, gezien_in_venster: set, dry_run: bool) -> list:
    """Bewaart de nieuwe open records en voegt de oude van buiten het venster toe.

    Een open record dat in het venster zonder fout terugkomt (bijvoorbeeld een refund die
    een PayPal-betaling bleek), is weer in orde: dat gaat uit de state. Bij een dry run
    wordt niets geschreven; zo'n record telt dan alleen niet mee.
    """
    if dry_run:
        return _met_open_uit_state(fouten, state, gezien_in_venster)
    _bewaar_open(fouten, state)
    in_fouten = {s for f in fouten for s in f["sleutels"]}
    weer_in_orde = [i for i, _ in state.open_niet_geboekt()
                    if i in gezien_in_venster and i not in in_fouten]
    if weer_in_orde:
        state.vergeet_open(weer_in_orde)
    return _met_open_uit_state(fouten, state, gezien_in_venster)


def open_niet_te_boeken(config: Config, dagen: int | None = None) -> set:
    """De sleutels die nu als niet te boeken openstaan: alleen die mag --handmatig-geboekt vastleggen.

    Een geldig maar verkeerd geplakt kenmerk van een gewone, nog niet geboekte refund zou
    die refund anders voorgoed uit de import houden. `dagen` volgt het venster van de ronde
    die het record meldde (--aansluiten kijkt standaard 30 dagen terug). Daarbij komen de open
    records uit de state, ook die buiten het venster vielen.
    """
    mollie = MollieClient(config.mollie_token)
    state = State(config.state_pad)
    try:
        fouten: list = []
        verzamel(mollie, _grens(dagen or config.max_terugkijk_dagen), fouten, state.gezien)
        open_ = {s for f in fouten for s in f["sleutels"] if not state.gezien(s)}
        return open_ | {i for i, _ in state.open_niet_geboekt()}
    finally:
        state.sluit()


def verzamel(mollie: MollieClient, grens: str, fouten: list | None = None, gezien=None,
             gezien_in_venster: set | None = None) -> list:
    """Haalt alle boekbare gebeurtenissen op vanaf de grensdatum.

    Vier bronnen, elk met zijn eigen moment van boeken. Betalingen worden
    opgehaald op aanmaakdatum maar geboekt op betaaldatum; die twee liggen
    doorgaans een dag uit elkaar, dus het venster moet ruimer zijn dan de
    periode die je wilt boeken.

    Een record dat niet veilig te boeken is (NietTeBoeken) komt met zijn sleutels in
    `fouten` en de rest gaat gewoon door; de aanroeper filtert met `_meld` wat al geboekt
    is en laat de ronde daarna met exitcode 4 eindigen. `gezien` slaat het ophalen van
    de betaling over voor een refund die al geboekt is. `gezien_in_venster` krijgt de
    sleutels van elke terugboeking en refund in het venster, met of zonder fout.
    """
    regels: list = []
    aantallen: dict = {}
    fouten = fouten if fouten is not None else []
    gezien = gezien or (lambda sleutel: False)
    gezien_in_venster = gezien_in_venster if gezien_in_venster is not None else set()

    def veilig(functie, record):
        try:
            return functie(record)
        except NietTeBoeken as e:
            fouten.append({"sleutels": _sleutels_van(record), "melding": str(e)})
            return None

    for betaling in mollie.betalingen(grens):
        regel = van_betaling(betaling)
        if regel:
            regels.append(regel)
    aantallen["betalingen"] = len(regels)

    voor = len(regels)
    for chargeback in mollie.chargebacks(grens):
        gezien_in_venster.update(_sleutels_van(chargeback))
        regels.extend(veilig(van_chargeback, chargeback) or [])
    aantallen["chargebacks"] = len(regels) - voor

    voor = len(regels)
    for refund in mollie.refunds(grens):
        gezien_in_venster.update(_sleutels_van(refund))
        # Zonder settlementAmount (weg per 1 januari 2027) is de betaalmethode nodig;
        # stuurt Mollie de betaling niet mee, dan halen we haar op. Alleen bij een
        # afgeronde refund die nog niet geboekt is.
        if (refund.get("status") == "refunded" and not refund.get("settlementAmount")
                and not (refund.get("_embedded") or {}).get("payment") and refund.get("paymentId")
                and not gezien(refund.get("id", ""))):
            try:
                betaling = mollie.betaling(refund["paymentId"])
            except HttpFout as e:
                # Een tijdelijke fout (429, 5xx) of een tokenprobleem zegt niets over deze
                # refund: de ronde stopt vóór het schrijven en de volgende probeert opnieuw.
                if e.status not in BETALING_WEG:
                    raise
                fouten.append({"sleutels": [refund.get("id", "")],
                               "melding": f"{refund.get('id')}: betaling {refund['paymentId']} "
                                          f"bestaat niet (HTTP {e.status})"})
                continue
            refund = dict(refund, _embedded={"payment": betaling})
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


def _aansluitperiodes(vandaag: dt.date, dagen: int) -> list[str]:
    """De periodes waarin --aansluiten de mutaties in Moneybird telt en ophaalt, per kalenderjaar.

    Het venster plus een week marge en minstens heel vorig jaar en dit jaar, tot en met
    morgen (de Nederlandse datum kan een dag voor lopen). Zo ziet de vergelijking ook een
    regel die met de hand op een oude datum is geboekt. Een groot venster dekt altijd
    zichzelf. Anders zou een schrijvende ronde zo'n regel nog eens boeken.
    """
    begin = min(vandaag - dt.timedelta(days=dagen + 7), dt.date(vandaag.year - 1, 1, 1))
    eind = vandaag + dt.timedelta(days=1)
    return [f"{max(begin, dt.date(jaar, 1, 1)):%Y%m%d}..{min(eind, dt.date(jaar, 12, 31)):%Y%m%d}"
            for jaar in range(begin.year, eind.year + 1)]


def _wacht_op_ronde(ontbreekt: list, gezien, laatste: str | None, nu: dt.datetime, dagen: int,
                    max_terugkijk_dagen: int,
                    max_leeftijd: dt.timedelta = RONDE_MAX_LEEFTIJD) -> tuple[list, list]:
    """Splitst de ontbrekende regels in (wacht, ontbreekt).

    Een geslaagde ronde boekt elke regel in zijn venster die de state niet kent. Kent de
    state een regel dan nog niet, dan is hij na het begin van die ronde zichtbaar geworden:
    hij wacht op de volgende ronde. Dat geldt alleen vlak na een ronde (`max_leeftijd`) en
    als het venster niet groter is dan dat van de ronde. Een regel die de state wel kent en
    die in Moneybird ontbreekt, is een echt gat en wacht nooit. Het tijdstip van de regel
    speelt geen rol: een refund kan voor de ronde zijn aangemaakt en pas daarna afgerond.
    """
    begin = utc(laatste) if laatste else None
    if begin is None or nu - begin > max_leeftijd or dagen > max_terugkijk_dagen:
        return [], list(ontbreekt)
    return ([r for r in ontbreekt if not gezien(r["sleutel"])],
            [r for r in ontbreekt if gezien(r["sleutel"])])


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
        "staan dat niet is onthouden. Zoek die referentie op in Moneybird. Staat het "
        "afschrift er, verwijder het dan met --verwijder-afschrift <id> en wis daarna "
        "de intentie met --wis-intentie; de volgende ronde boekt de regels opnieuw. "
        "Staat het er niet, wis dan alleen de intentie. Wis de intentie nooit terwijl "
        "het afschrift blijft staan: dan boekt de volgende ronde die regels dubbel."
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

    gestart = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fouten: list = []
    gezien_in_venster: set = set()
    regels = verzamel(mollie, _grens(config.max_terugkijk_dagen), fouten, state.gezien,
                      gezien_in_venster=gezien_in_venster)
    fouten = _ruim_open_op(fouten, state, gezien_in_venster, dry_run)
    niet_te_boeken = _meld(fouten, state.gezien)
    nieuw = [r for r in regels if not state.gezien(r["sleutel"])]

    if not nieuw:
        log.info("Niets nieuws.")
        if not dry_run:
            state.zet_ronde("mollie", gestart)
        state.sluit()
        return {"regels": 0, "afschrift_id": None, "niet_te_boeken": niet_te_boeken}

    if dry_run:
        log.info("DRY RUN, er wordt niets geschreven. %d regels:", len(nieuw))
        for r in nieuw[:40]:
            log.info("  %s %10s  %s", r["date"], r["amount"], r["message"])
        if len(nieuw) > 40:
            log.info("  ... en nog %d", len(nieuw) - 40)
        state.sluit()
        return {"regels": len(nieuw), "afschrift_id": None, "dry_run": True, "niet_te_boeken": niet_te_boeken}

    afschrift_id = _schrijf(moneybird, config, state, nieuw, "mollie")
    state.zet_ronde("mollie", gestart)
    state.sluit()
    log.info("Afschrift %s aangemaakt met %d regels", afschrift_id, len(nieuw))
    return {"regels": len(nieuw), "afschrift_id": afschrift_id, "niet_te_boeken": niet_te_boeken}


def aansluiten(
    config: Config,
    dagen: int = 30,
    dry_run: bool = False,
    forceer_leeg: bool = False,
) -> dict:
    """Overstap van de oude koppeling: boek precies wat er nog niet staat.

    Vergelijkt met wat er feitelijk in de Moneybird-rekening staat, niet met
    een tijdstip. Zo maakt het niet uit of de oude koppeling er halverwege mee
    ophield of een gat liet. De mutaties komen per kalenderjaar binnen: het venster plus
    een week en minstens vorig jaar en dit jaar (`_aansluitperiodes`), voor een droge en
    een schrijvende ronde gelijk.

    Bij een dry run wacht een regel die de state nog niet kent vlak na een geslaagde
    ronde op de volgende ronde in plaats van als ontbrekend te tellen (`_wacht_op_ronde`).
    """
    mollie = MollieClient(config.mollie_token)
    moneybird = MoneybirdClient(config.moneybird_token, config.administratie_id)
    state = State(config.state_pad)
    _controleer_intentie(state)

    periodes = _aansluitperiodes(dt.date.today(), dagen)
    if not forceer_leeg and sum(
        moneybird.aantal_mutaties(config.rekening_id, periode) for periode in periodes
    ) == 0:
        state.sluit()
        raise RuntimeError(
            f"Rekening {config.rekening_id} bevat geen enkele mutatie. Dat wijst op een "
            "verkeerd rekening-ID of een token voor de verkeerde administratie. Zonder "
            "die controle zou het hele venster als ontbrekend worden geboekt. Klopt het "
            "dat de rekening leeg is, draai dan met --forceer-leeg."
        )

    log.info("Bestaande mutaties ophalen uit Moneybird...")
    bestaand: list = []
    for periode in periodes:
        bestaand.extend(moneybird.mutaties_in_periode(config.rekening_id, periode))
    log.info("%d mutaties gevonden op rekening %s", len(bestaand), config.rekening_id)

    # Al geboekt is wat in de state staat, of wat met zijn kenmerk al in Moneybird staat.
    # Een terugboeking of refund is een afschrijving, een terugdraaiing een bijschrijving
    # met hetzelfde kenmerk: het teken houdt ze uit elkaar.
    in_moneybird = {(k, float(m["amount"]) > 0) for m in bestaand
                    for k in kenmerken_van(m.get("message", ""))}

    def gezien(sleutel: str) -> bool:
        kenmerk, _, soort = sleutel.partition(":")
        return state.gezien(sleutel) or (kenmerk, soort == "teruggedraaid") in in_moneybird

    gestart = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fouten: list = []
    gezien_in_venster: set = set()
    regels = verzamel(mollie, _grens(dagen), fouten, gezien, gezien_in_venster=gezien_in_venster)
    # Alleen een fout uit dit venster mag hieronder als bestond-al vast. Een open record van
    # buiten het venster sluit alleen met --handmatig-geboekt of doordat een ronde hem boekt.
    # Zo'n open record telt ook alleen op de state: een handboeking in Moneybird sluit hem niet.
    venster_fouten = fouten
    buiten_venster = _ruim_open_op(fouten, state, gezien_in_venster, dry_run)[len(venster_fouten):]
    niet_te_boeken = _meld(venster_fouten, gezien) + _meld(buiten_venster, state.gezien)
    geboekt, ontbreekt = splits(regels, bestaand)
    wacht: list = []
    if dry_run:
        wacht, ontbreekt = _wacht_op_ronde(
            ontbreekt, state.gezien, state.laatste_ronde("mollie"),
            dt.datetime.now(dt.timezone.utc), dagen, config.max_terugkijk_dagen)
    log.info("Al geboekt: %d. Nog te boeken: %d. Wacht op de volgende ronde: %d.",
             len(geboekt), len(ontbreekt), len(wacht))

    resultaat = {
        "bestaande_mutaties": len(bestaand),
        "regels": len(regels),
        "al_geboekt": len(geboekt),
        "ontbreekt": len(ontbreekt),
        "wacht": len(wacht),
        "afschrift_id": None,
        "niet_te_boeken": niet_te_boeken,
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

    # Een niet te boeken record dat al in Moneybird staat, ook in de state vastleggen. Anders
    # meldt de volgende gewone ronde (die alleen de state kent) hem weer als niet geboekt.
    al_in_moneybird = [s for f in venster_fouten for s in f["sleutels"]
                       if not state.gezien(s) and gezien(s)]
    if al_in_moneybird:
        state.markeer(al_in_moneybird, "bestond-al", dt.date.today().isoformat())

    if ontbreekt:
        resultaat["afschrift_id"] = _schrijf(
            moneybird, config, state, ontbreekt, "mollie-aansluiting")
        log.info("Aansluitafschrift %s met %d regels",
                 resultaat["afschrift_id"], len(ontbreekt))

    state.zet_ronde("mollie", gestart)
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


TERUGBOEKING_MARGE_DAGEN = 3


def _facturen_in_venster(moneybird, datum: str, cache: dict,
                         marge: int = TERUGBOEKING_MARGE_DAGEN) -> list:
    """De facturen van `datum - marge` tot en met `datum + marge`.

    De creditnota valt niet altijd op de dag van de bankregel. Elke dag wordt
    binnen een ronde maar één keer opgehaald: overlappende vensters van
    terugboekingen op naburige dagen kosten zo geen extra verzoeken.
    """
    dag = dt.date.fromisoformat(datum)
    facturen: list = []
    for verschil in range(-marge, marge + 1):
        sleutel = (dag + dt.timedelta(days=verschil)).isoformat()
        if sleutel not in cache:
            cache[sleutel] = moneybird.verkoopfacturen_van_dag(sleutel)
        facturen.extend(cache[sleutel])
    return facturen


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

    # De creditnota zoeken we tot TERUGBOEKING_MARGE_DAGEN vóór en na de
    # bankregel. Per dag halen we de facturenlijst maar één keer op, ook als
    # de vensters van terugboekingen op naburige dagen overlappen.
    per_dag: dict = {}
    for mutatie in sorted(openstaand, key=lambda m: m["date"]):
        datum = mutatie["date"]
        nota, reden = zoek_creditnota(mutatie, _facturen_in_venster(moneybird, datum, per_dag))

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
