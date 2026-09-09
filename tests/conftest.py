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
