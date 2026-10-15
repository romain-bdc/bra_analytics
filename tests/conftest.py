from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def fixture(name: str) -> Path:
    return FIXTURES / name


def bulletins_valides() -> list[Path]:
    """Fixtures de bulletins reguliers, hors cas volontairement aberrants."""
    return sorted(p for p in FIXTURES.glob("*.xml") if not p.name.startswith("anomalie_"))

# Series de bulletins reels consecutifs, tenues a part de `FIXTURES` : `build()`
# parcourt son repertoire source recursivement, et les tests qui construisent
# l'entrepot sur `FIXTURES` comptent ses fichiers. Une serie ajoutee la-dedans
# deplacerait leurs attendus (c'est arrive une fois avec une saison de plus).
SERIES = Path(__file__).parent / "series"
