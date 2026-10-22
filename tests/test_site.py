"""`bra site` : les quatre ecrans dans un dossier, plus `index.html` (copie de la carte)."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

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


def test_aucune_page_n_appelle_un_domaine_de_polices_tiers(db, tmp_path):
    """Google Fonts transmettrait l'IP de chaque visiteur : les polices sont auto-hebergees."""
    out = tmp_path / "site"
    generer(db, out)
    for page in out.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "googleapis" not in html and "gstatic" not in html, page.name
    assert (out / "polices" / "OFL.txt").is_file()


def _chromium() -> str | None:
    if os.environ.get("BRA_CHROMIUM"):
        return os.environ["BRA_CHROMIUM"]
    trouves = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    return trouves[0] if trouves else shutil.which("chromium") or shutil.which("chromium-browser")


@pytest.mark.skipif(_chromium() is None, reason="Chromium headless absent (BRA_CHROMIUM)")
def test_polices_chargees_depuis_le_site(db, tmp_path):
    out = tmp_path / "site"
    generer(db, out)
    page = out / "carte.html"
    script = (
        "Promise.all([document.fonts.load('500 14px \"Archivo\"'), document.fonts.load('500 14px \"Source Serif 4\"')])"
        ".then(()=>{document.title='fonts:'+document.fonts.check('500 14px \"Archivo\"')"
        "+document.fonts.check('500 14px \"Source Serif 4\"')});"
    )
    page.write_text(page.read_text(encoding="utf-8").replace("</html>", f"<script>{script}</script></html>"), encoding="utf-8")
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=6000", "--dump-dom", f"file://{page}"],
        capture_output=True, text=True, timeout=180, check=True,
    )
    assert "fonts:truetrue" in sortie.stdout
