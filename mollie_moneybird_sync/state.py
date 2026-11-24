from __future__ import annotations

"""Onthoudt welke Mollie-balansmutaties al in Moneybird staan.

Een ID wordt pas weggeschreven nadat Moneybird het afschrift heeft bevestigd.
Breekt een run halverwege af, dan komen de niet-bevestigde mutaties de
volgende run gewoon terug.
"""
import os
import sqlite3


class State:
    def __init__(self, pad: str):
        os.makedirs(os.path.dirname(os.path.abspath(pad)), exist_ok=True)
        self.db = sqlite3.connect(pad)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS verwerkt ("
            " id TEXT PRIMARY KEY,"
            " afschrift_id TEXT,"
            " datum TEXT,"
            " toegevoegd_op TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()

    def _zorg_voor_intentietabel(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS intentie ("
            " referentie TEXT PRIMARY KEY,"
            " aantal INTEGER,"
            " gestart_op TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def zet_intentie(self, referentie: str, aantal: int) -> None:
        """Legt vast dat we op het punt staan te schrijven.

        Sterft het proces tussen het antwoord van Moneybird en het wegschrijven
        van de sleutels, dan weten we bij de volgende run dat er mogelijk een
        afschrift bestaat dat we niet hebben onthouden. Zonder dit zou die
        volgende run alles opnieuw boeken.
        """
        self._zorg_voor_intentietabel()
        self.db.execute(
            "INSERT OR REPLACE INTO intentie (referentie, aantal) VALUES (?, ?)",
            (referentie, aantal),
        )
        self.db.commit()

    def openstaande_intentie(self):
        self._zorg_voor_intentietabel()
        rij = self.db.execute(
            "SELECT referentie, aantal, gestart_op FROM intentie"
        ).fetchone()
        return rij

    def wis_intentie(self, referentie: str) -> None:
        self._zorg_voor_intentietabel()
        self.db.execute("DELETE FROM intentie WHERE referentie = ?", (referentie,))
        self.db.commit()

    def gezien(self, mutatie_id: str) -> bool:
        cur = self.db.execute("SELECT 1 FROM verwerkt WHERE id = ?", (mutatie_id,))
        return cur.fetchone() is not None

    def markeer(self, ids: list[str], afschrift_id: str, datum: str = "") -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO verwerkt (id, afschrift_id, datum) VALUES (?, ?, ?)",
            [(i, afschrift_id, datum) for i in ids],
        )
        self.db.commit()

    def _zorg_voor_opentabel(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS open_niet_te_boeken ("
            " id TEXT PRIMARY KEY,"
            " melding TEXT,"
            " eerst_gezien TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def onthoud_open(self, rijen: list[tuple[str, str]]) -> None:
        """Onthoudt niet te boeken records, zodat ze gemeld blijven als ze buiten het venster vallen.

        Een record dat al open staat houdt zijn eerste melding en het moment waarop hij
        voor het eerst gezien is.
        """
        self._zorg_voor_opentabel()
        self.db.executemany(
            "INSERT OR IGNORE INTO open_niet_te_boeken (id, melding) VALUES (?, ?)",
            [(i, melding) for i, melding in rijen if i],
        )
        self.db.commit()

    def open_niet_geboekt(self) -> list[tuple[str, str]]:
        """(id, melding) van de open records die nog niet als verwerkt vastliggen, oudste eerst."""
        self._zorg_voor_opentabel()
        return [tuple(rij) for rij in self.db.execute(
            "SELECT id, melding FROM open_niet_te_boeken"
            " WHERE id NOT IN (SELECT id FROM verwerkt)"
            " ORDER BY eerst_gezien, rowid"
        )]

    def vergeet_open(self, ids: list[str]) -> None:
        self._zorg_voor_opentabel()
        self.db.executemany("DELETE FROM open_niet_te_boeken WHERE id = ?", [(i,) for i in ids])
        self.db.commit()

    def _zorg_voor_rondetabel(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS ronde ("
            " naam TEXT PRIMARY KEY,"
            " gestart_op TEXT)"
        )

    def zet_ronde(self, naam: str, gestart_op: str) -> None:
        """Legt het begin vast van de laatste ronde die zonder fout eindigde.

        `--aansluiten --dry-run` laat een regel die de state nog niet kent dan even wachten:
        die is na het begin van die ronde zichtbaar geworden en is geen gat.
        """
        self._zorg_voor_rondetabel()
        self.db.execute(
            "INSERT OR REPLACE INTO ronde (naam, gestart_op) VALUES (?, ?)",
            (naam, gestart_op),
        )
        self.db.commit()

    def laatste_ronde(self, naam: str) -> str | None:
        self._zorg_voor_rondetabel()
        rij = self.db.execute("SELECT gestart_op FROM ronde WHERE naam = ?", (naam,)).fetchone()
        return rij[0] if rij else None

    def aantal(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM verwerkt").fetchone()[0]

    def leeg(self) -> bool:
        return self.aantal() == 0

    def sluit(self) -> None:
        self.db.close()
