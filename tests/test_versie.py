"""De versie in het pakket is gelijk aan die in pyproject.toml."""
import pathlib
import re

import mollie_moneybird_sync

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_versie_gelijk_aan_pyproject():
    tekst = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'^version = "([^"]+)"', tekst, re.M).group(1) == mollie_moneybird_sync.__version__
