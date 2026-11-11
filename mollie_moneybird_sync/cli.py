from __future__ import annotations

"""Opdrachtregel: python -m mollie_moneybird_sync [--dry-run]"""
import argparse
import logging
import sys

from .config import Config, ConfigFout
from .controle import controleer
from .http import HttpFout
from .mollie_client import MollieClient
from .moneybird_client import MoneybirdClient
from .sync import (
    Lock,
    Vergrendeld,
    aansluiten,
    draai,
    draai_paypal,
    koppel_terugboekingen,
)


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Mollie-transacties naar Moneybird")
    p.add_argument("--dry-run", action="store_true",
                   help="toon wat er zou worden geboekt, schrijf niets")
    p.add_argument("--aansluiten", action="store_true",
                   help="eenmalig: vergelijk met wat er in Moneybird staat en boek het verschil")
    p.add_argument("--dagen", type=int, default=None,
                   help="venster in dagen: standaard 30 bij --aansluiten, "
                        "en bij --paypal de gewone terugblik uit de omgeving")
    p.add_argument("--paypal", action="store_true",
                   help="haal PayPal-transacties op en zet ze op de PayPal-rekening")
    p.add_argument("--terugboekingen", action="store_true",
                   help="koppel teruggeboekte incasso's aan hun creditnota")
    p.add_argument("--forceer-leeg", action="store_true",
                   help="sta --aansluiten toe op een rekening zonder mutaties")
    p.add_argument("--controleer", action="store_true",
                   help="toets of de laatste afrekeningen sluiten op wat Mollie uitbetaalde")
    p.add_argument("--rekeningen", action="store_true",
                   help="toon de financiele rekeningen van de administratie met hun ID")
    p.add_argument("--verwijder-afschrift", metavar="ID",
                   help="verwijder een afschrift en alle mutaties eronder")
    p.add_argument("--wis-intentie", action="store_true",
                   help="wis een blijvende schrijf-intentie na handmatig herstel")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        return _voer_uit(args, Config())
    except ConfigFout as e:
        print(f"Instelling ontbreekt: {e}", file=sys.stderr)
        return 2


def _voer_uit(args, config: Config) -> int:

    if args.rekeningen:
        for r in MoneybirdClient(config.moneybird_token, config.administratie_id).rekeningen():
            print(f"  {r['id']}  {r.get('type',''):<22} {r.get('name') or r.get('identifier','')}")
        return 0

    if args.verwijder_afschrift:
        MoneybirdClient(config.moneybird_token,
                        config.administratie_id).verwijder_afschrift(args.verwijder_afschrift)
        print(f"afschrift {args.verwijder_afschrift} verwijderd")
        return 0

    if args.wis_intentie:
        from .state import State
        state = State(config.state_pad)
        rij = state.openstaande_intentie()
        if not rij:
            print("geen openstaande intentie")
        else:
            state.wis_intentie(rij[0])
            print(f"intentie {rij[0]} gewist")
        state.sluit()
        return 0

    if args.controleer:
        uitkomsten = controleer(MollieClient(config.mollie_token))
        scheef = [u for u in uitkomsten if not u["sluit"]]
        print(f"{len(uitkomsten)} afrekeningen getoetst, {len(scheef)} wijken af")
        return 1 if scheef else 0

    # De PayPal-ronde krijgt een eigen lock. Ze schrijven naar verschillende
    # rekeningen en mogen elkaar niet blokkeren: een Mollie-run die lang duurt
    # zou de PayPal-run anders stilzwijgend overslaan.
    lock_pad = config.lock_pad
    if args.paypal:
        lock_pad = f"{config.lock_pad}.paypal"
    elif args.terugboekingen:
        lock_pad = f"{config.lock_pad}.terugboekingen"

    # Eerst alle instellingen van deze ronde toetsen, zodat een ontbrekende
    # waarde gemeld wordt voordat er iets bij Mollie of Moneybird wordt opgevraagd.
    nodig = ["moneybird_token", "administratie_id"]
    if not args.paypal:
        nodig.append("rekening_id")
    if not (args.paypal or args.terugboekingen):
        nodig.append("mollie_token")
    for instelling in nodig:
        getattr(config, instelling)  # gooit ConfigFout met uitleg als hij ontbreekt

    try:
        with Lock(lock_pad):
            if args.paypal:
                resultaat = draai_paypal(config, dagen=args.dagen,
                                         dry_run=args.dry_run)
            elif args.terugboekingen:
                resultaat = koppel_terugboekingen(config, dry_run=args.dry_run)
            elif args.aansluiten:
                resultaat = aansluiten(config, dagen=args.dagen or 30,
                                       dry_run=args.dry_run,
                                       forceer_leeg=args.forceer_leeg)
            else:
                resultaat = draai(config, dry_run=args.dry_run)
    except Vergrendeld as e:
        logging.warning(str(e))
        return 0
    except ConfigFout:
        raise
    except HttpFout as e:
        if not _toegang_geweigerd(e):
            logging.exception("Run mislukt")
            return 1
        dienst, variabelen = _dienst(e.url)
        print(f"{dienst} weigert het verzoek (HTTP {e.status}). Controleer {variabelen} "
              f"in .env: klopt het token en heeft het de juiste rechten? "
              f"Antwoord van {dienst}: {e.body[:200]}", file=sys.stderr)
        return 1
    except Exception:
        logging.exception("Run mislukt")
        return 1

    afschrift = resultaat.get("afschrift_id")
    staart = f", afschrift {afschrift}" if afschrift else ""
    if args.terugboekingen:
        blijft = resultaat["overgeslagen"]
        print(f"{resultaat['gevonden']} terugboekingen, {resultaat['gekoppeld']} gekoppeld, "
              f"{len(blijft)} blijft staan")
        for r in blijft:
            print(f"  {r['datum']} {r['bedrag']}: {r['reden']}")
        return 0
    if args.paypal:
        saldo = ""
        if resultaat.get("saldo_getoetst"):
            saldo = (f", saldo {resultaat['saldo_moneybird']:.2f} tegenover PayPal "
                     f"{resultaat['saldo_paypal']:.2f}")
            if resultaat["verschil"]:
                saldo += f", VERSCHIL {resultaat['verschil']:.2f}"
        print(f"{resultaat['transacties']} PayPal-transacties, "
              f"{resultaat['regels']} nieuwe regels{staart}{saldo}")
        return 1 if resultaat.get("verschil") else 0
    if args.aansluiten:
        print(
            f"{resultaat['bestaande_mutaties']} bestaande mutaties, "
            f"{resultaat['regels']} Mollie-regels, "
            f"{resultaat['al_geboekt']} al geboekt, "
            f"{resultaat['ontbreekt']} ontbrak{staart}"
        )
    else:
        print(f"{resultaat['regels']} regels{staart}")
    if resultaat.get("niet_te_boeken"):
        # De rest is geboekt; de exitcode zet de hartslag op rood (zie het log voor de kenmerken).
        print(f"{resultaat['niet_te_boeken']} niet te boeken, zie het log", file=sys.stderr)
        return 1
    return 0


def _toegang_geweigerd(fout: HttpFout) -> bool:
    """Een fout die op het token wijst: geweigerd, of een ongeldige Authorization-kop."""
    if fout.status in (401, 403):
        return True
    return fout.status == 400 and "authoriz" in fout.body.lower()


def _dienst(url: str) -> tuple:
    if "mollie.com" in url:
        return "Mollie", "MOLLIE_TOKEN"
    if "paypal.com" in url:
        return "PayPal", "PAYPAL_CLIENT_ID en PAYPAL_SECRET"
    return "Moneybird", "MONEYBIRD_TOKEN en MONEYBIRD_ADMINISTRATION_ID"


if __name__ == "__main__":
    sys.exit(main())
