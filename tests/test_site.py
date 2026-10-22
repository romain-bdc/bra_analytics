"""`bra site` : les quatre ecrans dans un dossier, plus `index.html` (copie de la carte)."""

from __future__ import annotations

import shutil

import pytest

from bra_analytics.build import build
from bra_analytics.partage import ECRANS
from bra_analytics.site import generer

from .conftest import SERIES


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("site")
    chemin = tmp / "bra.duckdb"
    # Les ecrans lisent tous les blocs : risque, neige et meteo dans un meme entrepot.
    source = tmp / "source"
    for bloc in ("risque", "enneigement", "meteo"):
        shutil.copytree(SERIES / bloc, source, dirs_exist_ok=True)
    build(source, tmp / "warehouse", chemin)
    return chemin


def test_chaque_ecran_et_l_index_sont_ecrits(db, tmp_path):
    out = tmp_path / "site"
    generer(db, out)
    for ecran in ECRANS:
        assert (out / ecran.fichier).stat().st_size > 0
    # l'accueil est la carte : meme contenu, nom d'index
    assert (out / "index.html").read_text(encoding="utf-8") == (out / "carte.html").read_text(encoding="utf-8")


def test_generation_idempotente(db, tmp_path):
    out = tmp_path / "site"
    generer(db, out)
    avant = {p.name for p in out.iterdir()}
    generer(db, out)
    assert {p.name for p in out.iterdir()} == avant
