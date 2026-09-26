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

    def aantal(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM verwerkt").fetchone()[0]

    def leeg(self) -> bool:
        return self.aantal() == 0

    def sluit(self) -> None:
        self.db.close()
