"""`bra site` : les quatre ecrans, `index.html` (redirection), polices, version.json, .nojekyll."""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser

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


def _generer(db, out):
    # L'arbre de travail est sale pendant le developpement : le refus a son propre test.
    return generer(db, out, allow_dirty=True)


def _chromium() -> str | None:
    if os.environ.get("BRA_CHROMIUM"):
        return os.environ["BRA_CHROMIUM"]
    trouves = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    return trouves[0] if trouves else shutil.which("chromium") or shutil.which("chromium-browser")


chromium = pytest.mark.skipif(_chromium() is None, reason="Chromium headless absent (BRA_CHROMIUM)")


def _dump_dom(url: str) -> str:
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=6000", "--dump-dom", url],
        capture_output=True, text=True, timeout=180, check=True,
    )
    return sortie.stdout


class _Liens(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "data-ecran" in a:
            self.hrefs.append(a["href"])


def test_chaque_ecran_et_les_fichiers_du_site_sont_ecrits(db, tmp_path):
    out = tmp_path / "site"
    _generer(db, out)
    for ecran in ECRANS:
        assert (out / ecran.fichier).stat().st_size > 0
    for nom in ("index.html", "version.json", ".nojekyll", "polices/OFL.txt", "apercu.png"):
        assert (out / nom).is_file(), nom


def test_chaque_page_porte_description_et_open_graph(db, tmp_path):
    out = tmp_path / "site"
    _generer(db, out)
    for ecran in ECRANS:
        html = (out / ecran.fichier).read_text(encoding="utf-8")
        for balise in ('name="description"', 'property="og:title"', 'property="og:description"', 'property="og:image"'):
            assert balise in html, (ecran.fichier, balise)


def test_aucune_page_n_appelle_un_domaine_de_polices_tiers(db, tmp_path):
    """Google Fonts transmettrait l'IP de chaque visiteur : les polices sont auto-hebergees."""
    out = tmp_path / "site"
    _generer(db, out)
    for page in out.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "googleapis" not in html and "gstatic" not in html, page.name


def test_index_redirige_vers_la_carte_en_conservant_le_fragment(db, tmp_path):
    out = tmp_path / "site"
    _generer(db, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert 'location.replace("carte.html" + location.hash)' in index
    assert '<meta http-equiv="refresh" content="0; url=carte.html">' in index
    assert "<title>" in index and 'name="description"' in index


@chromium
def test_navigation_et_fragment_de_bout_en_bout(db, tmp_path):
    """index.html#m=...&s=... aboutit sur la carte avec l'etat intact ; chaque lien de navigation existe."""
    out = tmp_path / "site"
    _generer(db, out)
    dom = _dump_dom(f"file://{out / 'index.html'}#m=68&s=2023-2024")
    assert "<title>Carte des massifs BRA</title>" in dom
    liens = _Liens()
    liens.feed(dom)
    assert len(liens.hrefs) == len(ECRANS)
    for href in liens.hrefs:
        fichier, _, fragment = href.partition("#")
        assert (out / fichier).is_file(), href
        assert "m=68" in fragment and "s=2023-2024" in fragment, href


@chromium
def test_polices_chargees_depuis_le_site(db, tmp_path):
    out = tmp_path / "site"
    _generer(db, out)
    page = out / "carte.html"
    script = (
        "Promise.all([document.fonts.load('500 14px \"Archivo\"'), document.fonts.load('500 14px \"Source Serif 4\"')])"
        ".then(()=>{document.title='fonts:'+document.fonts.check('500 14px \"Archivo\"')"
        "+document.fonts.check('500 14px \"Source Serif 4\"')});"
    )
    page.write_text(page.read_text(encoding="utf-8").replace("</html>", f"<script>{script}</script></html>"), encoding="utf-8")
    assert "fonts:truetrue" in _dump_dom(f"file://{page}")


def _tree(out) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


def test_deux_executions_donnent_le_meme_arbre_a_genere_pres(db, tmp_path):
    out = tmp_path / "site"
    _generer(db, out)
    premier = _tree(out)
    (out / "residu.txt").write_text("x")  # un etat residuel doit disparaitre
    _generer(db, out)
    second = _tree(out)
    v1, v2 = json.loads(premier.pop("version.json")), json.loads(second.pop("version.json"))
    v1.pop("genere"), v2.pop("genere")
    assert v1 == v2 and v1["archive"]
    assert premier == second


def test_refuse_sans_entrepot(tmp_path):
    with pytest.raises(SystemExit, match="bra build"):
        generer(tmp_path / "absent.duckdb", tmp_path / "site", allow_dirty=True)


def test_refuse_un_arbre_sale(db, tmp_path, monkeypatch):
    from bra_analytics import site

    monkeypatch.setattr(site, "_git", lambda *a: "abc123" if a[0] == "rev-parse" else " M fichier.py")
    with pytest.raises(SystemExit, match="allow-dirty"):
        generer(db, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_ne_supprime_pas_un_depot_git(db, tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(SystemExit, match="jetable"):
        generer(db, tmp_path, allow_dirty=True)
