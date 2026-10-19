"""Mecanisme transverse (T15) : attribution, etat dans l'URL, exports CSV et PNG.

Le payload et le branchement des gabarits se testent en Python. Le comportement
-- lien CSV rempli de ce que la trace a employe, hash conserve d'un ecran a
l'autre, PNG rasterise -- vit dans `templates/partage.js` : on rend les vraies
pages dans Chromium headless (`--dump-dom`) et on lit le DOM. Ces tests sont
sautes si aucun Chromium n'est installe.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

import pytest

from bra_analytics import carte, comparaison, dashboard, exploration, fiche, partage
from bra_analytics.build import build
from bra_analytics.dashboard import injecter

from .conftest import SERIES

TEMPLATES = Path(dashboard.__file__).parent / "templates"
ASPE = 65
DONNEES = "Données Météo-France, Licence Ouverte 2.0"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("partage")
    chemin = tmp / "bra.duckdb"
    source = tmp / "source"
    for bloc in ("risque", "enneigement", "meteo"):
        shutil.copytree(SERIES / bloc, source, dirs_exist_ok=True)
    build(source, tmp / "warehouse", chemin)
    return chemin


@pytest.fixture(scope="module")
def pages(db) -> dict[str, tuple[Path, dict]]:
    """Gabarit et payload de chaque ecran, par identifiant d'`partage.ECRANS`."""
    return {
        "carte": (carte.TEMPLATE, carte.payload(db)),
        "fiche": (fiche.TEMPLATE, fiche.payload(db)),
        "comparaison": (comparaison.TEMPLATE, comparaison.payload(db)),
        "exploration": (exploration.TEMPLATE, exploration.payload(db)),
        "dashboard": (dashboard.TEMPLATE, dashboard.payload(db)),
    }


# --- branchement : un ecran qui ne s'enregistre pas fait echouer ces tests ---------

def test_chaque_gabarit_d_ecran_est_branche() -> None:
    """Un nouvel ecran doit etre dans `ECRANS` et appeler `PARTAGE.demarrer`."""
    ecrans = {e.id for e in partage.ECRANS}
    gabarits = {p.stem for p in TEMPLATES.glob("*.html")}
    assert gabarits == ecrans, f"gabarits {gabarits ^ ecrans} hors de partage.ECRANS (ou l'inverse)"
    for ident in ecrans:
        html = (TEMPLATES / f"{ident}.html").read_text(encoding="utf-8")
        assert "__PARTAGE__" in html, ident
        assert 'id="attribution"' in html, ident
        assert f'PARTAGE.demarrer({{ ecran: "{ident}"' in html, ident
        assert "location.hash" not in html, f"{ident} lit ou ecrit l'URL sans passer par PARTAGE"
        assert "history.replaceState" not in html, ident


def test_ecrans_ont_des_fichiers_distincts_et_l_archive_dans_le_payload(pages) -> None:
    assert len({e.fichier for e in partage.ECRANS}) == len(partage.ECRANS)
    for ident, (_, data) in pages.items():
        bloc = data["partage"]
        assert bloc["donnees"] == DONNEES, ident
        assert bloc["archive"], ident
        assert bloc["genere"], ident
    assert pages["carte"][1]["partage"]["contours"].startswith("Contours des massifs")
    assert "15/02/2024" in pages["carte"][1]["partage"]["contours"]
    # Seule la carte porte les contours.
    assert all(pages[i][1]["partage"]["contours"] is None for i in ("fiche", "comparaison", "dashboard"))


def test_les_marqueurs_sont_tous_remplaces(pages) -> None:
    for ident, (gabarit, data) in pages.items():
        html = injecter(gabarit, data)
        for marqueur in ("__PARTAGE__", "__ECRANS__", "__COMMUN__", "__DONNEES__"):
            assert marqueur not in html, (ident, marqueur)
        for e in partage.ECRANS:
            assert f'"fichier":"{e.fichier}"' in html.replace(" ", ""), (ident, e.id)


# --- pages rendues dans Chromium ---------------------------------------------------

def _chromium() -> str | None:
    if os.environ.get("BRA_CHROMIUM"):
        return os.environ["BRA_CHROMIUM"]
    trouves = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    return trouves[0] if trouves else shutil.which("chromium") or shutil.which("chromium-browser")


chromium = pytest.mark.skipif(_chromium() is None, reason="Chromium headless absent (BRA_CHROMIUM)")


class _Dom(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attrs: dict[str, dict] = {}
        self.texte: dict[str, str] = {}
        self.csv: list[dict] = []
        self.liens: dict[str, str] = {}
        self.titre = ""
        self._pile: list[str | None] = []
        self._dans_titre = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        ident = a.get("id")
        if ident:
            self.attrs[ident] = a
            self.texte[ident] = ""
        if tag == "a" and "exp-csv" in a.get("class", ""):
            self.csv.append(a)
        if tag == "a" and "data-ecran" in a:
            self.liens[a["data-ecran"]] = a["href"]
        self._dans_titre = tag == "title"
        if tag not in ("br", "meta", "link", "input", "option", "line", "rect", "path", "circle"):
            self._pile.append(ident)

    def handle_endtag(self, tag):
        self._dans_titre = False
        if self._pile:
            self._pile.pop()

    def handle_data(self, d):
        if self._dans_titre:
            self.titre += d
        for ident in self._pile:
            if ident:
                self.texte[ident] += d


def _rendre(html: str, fragment: str, tmp: Path, script: str = "") -> _Dom:
    page = tmp / "page.html"
    page.write_text(html.replace("</html>", f"<script>{script}</script></html>") if script else html, encoding="utf-8")
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=6000", "--dump-dom",
         f"file://{page}#{fragment}"],
        capture_output=True, text=True, timeout=180, check=True,
    )
    assert "Uncaught" not in sortie.stderr, sortie.stderr[-1500:]
    dom = _Dom()
    dom.feed(sortie.stdout)
    return dom


def _csv(a: dict) -> tuple[list[str], list[str], list[str]]:
    """(lignes `#`, colonnes, lignes de donnees) d'un lien d'export."""
    brut = urllib.parse.unquote(a["href"].split(",", 1)[1]).lstrip("﻿")
    lignes = [x for x in brut.split("\r\n") if x]
    tete = [x for x in lignes if x.startswith("#")]
    corps = [x for x in lignes if not x.startswith("#")]
    return tete, corps[0].split(","), corps[1:]


@pytest.fixture(scope="module")
def rendus(pages, tmp_path_factory) -> dict[str, _Dom]:
    if _chromium() is None:
        pytest.skip("Chromium headless absent")
    tmp = tmp_path_factory.mktemp("rendus")
    a_lire = fiche_massif = pages["fiche"][1]["massifs"]
    (saisons,) = [m["saisons"] for m in fiche_massif if m["id"] == ASPE]
    s = saisons[-1]
    frag = {
        "carte": "mc=risque_moyen",
        "fiche": f"m={ASPE}&s={s}&t=moyenne&f=coeur&zz=garde",
        "comparaison": f"x=saison&m={ASPE}&s={s}&k=risque_moyen&f=coeur",
        "exploration": f"x=saisons&m={ASPE}&c={s}&f=coeur&q=toutes&t=haute&g=barres&zz=garde",
        "dashboard": f"m={ASPE}&f=coeur",
    }
    del a_lire
    out = {}
    for ident, (gabarit, data) in pages.items():
        (tmp / ident).mkdir()
        out[ident] = _rendre(injecter(gabarit, data), frag[ident], tmp / ident)
    return out


@chromium
@pytest.mark.parametrize("ident", [e.id for e in partage.ECRANS])
def test_attribution_et_date_d_archive_visibles(rendus, pages, ident) -> None:
    texte = rendus[ident].texte["attribution"]
    assert DONNEES in texte
    archive = pages[ident][1]["partage"]["archive"]
    jour = int(archive[8:])
    assert re.search(rf"archive arrêtée au {jour}\w* \S+ {archive[:4]}", texte), texte
    # La navigation relie les quatre ecrans, l'ecran courant marque.
    assert set(rendus[ident].liens) == {e.id for e in partage.ECRANS}


@chromium
def test_attribution_des_contours_sur_la_carte(rendus) -> None:
    dom = rendus["carte"]
    for ident in ("attribution", "attribution-contours"):
        assert "Contours des massifs : Météo-France, Licence Ouverte 2.0" in dom.texte[ident]
        assert "15/02/2024" in dom.texte[ident]
    assert DONNEES in dom.texte["attribution-contours"]


@chromium
def test_chaque_graphe_a_son_export_csv_et_png(rendus) -> None:
    attendus = {"carte": 1, "fiche": 4, "comparaison": 2, "exploration": None, "dashboard": 5}
    for ident, n in attendus.items():
        # Exploration : une trace par entite et par bloc, selon les blocs publies ; au moins une.
        assert (len(rendus[ident].csv) >= 1) if n is None else (len(rendus[ident].csv) == n), ident
        for a in rendus[ident].csv:
            assert a["download"].startswith(f"bra-{ident}-") and a["download"].endswith(".csv")
            assert int(a["data-lignes"]) >= 0


@chromium
def test_csv_de_la_carte_reprend_les_valeurs_tracees(rendus, pages) -> None:
    (a,) = rendus["carte"].csv
    tete, colonnes, lignes = _csv(a)
    data = pages["carte"][1]
    assert any(DONNEES in t and data["partage"]["archive"] in t for t in tete)
    assert colonnes[:5] == ["massif_id", "massif", "zone", "metrique", "valeur"]
    assert len(lignes) == len(data["massifs"]) == 36
    attendu = {m["id"]: m["risque_moyen"] for m in data["massifs"]}
    for ligne in lignes:
        c = ligne.split(",")
        valeur = attendu[int(c[0])]
        assert (c[4] == "") if valeur is None else float(c[4]) == pytest.approx(valeur)


@chromium
def test_csv_de_la_fiche_compte_les_jours_publies_de_la_saison_lue(rendus, pages) -> None:
    data = pages["fiche"][1]
    (saisons,) = [m["saisons"] for m in data["massifs"] if m["id"] == ASPE]
    s = saisons[-1]
    e = data["series"][ASPE][s]
    a = next(x for x in rendus["fiche"].csv if "risque" in x["download"])
    tete, colonnes, lignes = _csv(a)
    assert colonnes == ["serie", "saison", "jour", "abscisse", "valeur", "q1", "q3", "remarque"]
    lue = [x.split(",") for x in lignes if x.startswith("saison_lue,")]
    assert len(lue) == sum(1 for c in e["risque"] if c != ".")
    # `0` = publie sans indice : ligne gardee, valeur vide, motif dit.
    sans = [x for x in lue if x[7] == "publié sans indice"]
    assert len(sans) == e["risque"].count("0") and all(x[4] == "" for x in sans)
    assert all(x[1] == s for x in lue)
    # Jours reels, pas des abscisses : le premier jour publie est une date ISO.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", lue[0][2])
    assert any(f"saison {s}" in t for t in tete) or any(s in t for t in tete)


@chromium
def test_csv_du_classement_garde_les_saisons_non_classees_et_leur_motif(rendus, pages) -> None:
    a = next(x for x in rendus["comparaison"].csv if "classement" in x["download"])
    _, colonnes, lignes = _csv(a)
    assert colonnes == ["massif_id", "saison", "metrique", "fenetre", "rang", "ex_aequo", "valeur", "jours_avec_valeur", "comparable", "motif"]
    data = pages["comparaison"][1]
    saisons = {s["nom"] for s in data["saisons"]}
    vues = {x.split(",")[1] for x in lignes}
    assert vues and vues <= saisons
    # Etiqueter plutot que supprimer : toute ligne non comparable porte son motif.
    for x in lignes:
        c = x.split(",", 9)
        if c[8] == "0":
            assert c[4] == "" and c[9] != ""


@chromium
def test_csv_du_tableau_de_bord_est_celui_des_aggregats(rendus, pages) -> None:
    data = pages["dashboard"][1]
    a = next(x for x in rendus["dashboard"].csv if "repartition" in x["download"])
    _, colonnes, lignes = _csv(a)
    assert colonnes[0] == "saison" and colonnes[-2:] == ["sans_indice", "jours"]
    for ligne in lignes:
        c = ligne.split(",")
        niveaux = list(map(int, c[1:7]))      # cinq indices + sans indice
        assert sum(niveaux) == int(c[7])
    couv = next(x for x in rendus["dashboard"].csv if "couverture" in x["download"])
    _, cols, rows = _csv(couv)
    assert cols == ["saison", "jour", "massifs_pourvus", "massifs_selectionnes"]
    assert rows and all(int(r.split(",")[3]) == 1 for r in rows)   # massif 65 seul


@chromium
def test_le_hash_complet_voyage_d_un_ecran_a_l_autre(rendus) -> None:
    """Le lien vers un autre ecran porte l'etat courant, cles inconnues comprises."""
    lien = rendus["fiche"].liens["comparaison"]
    assert lien.startswith("comparaison.html#")
    p = urllib.parse.parse_qs(lien.split("#", 1)[1])
    assert p["m"] == [str(ASPE)] and p["zz"] == ["garde"] and p["f"] == ["coeur"]
    # La carte ecrit sa cle sans effacer celles des autres ; le dashboard de meme.
    assert "mc" in urllib.parse.parse_qs(rendus["carte"].liens["fiche"].split("#", 1)[1])
    assert urllib.parse.parse_qs(rendus["dashboard"].liens["fiche"].split("#", 1)[1])["m"] == [str(ASPE)]


@chromium
@pytest.mark.parametrize("ident", [e.id for e in partage.ECRANS])
def test_une_url_collee_reproduit_le_meme_ecran(pages, rendus, ident, tmp_path) -> None:
    """Rendre la page a l'URL qu'elle a ecrite redonne les memes exports, au lien pres."""
    premier = rendus[ident]
    lien = next(v for k, v in premier.liens.items() if k != ident)
    hash_ecrit = lien.split("#", 1)[1]
    gabarit, data = pages[ident]
    second = _rendre(injecter(gabarit, data), hash_ecrit, tmp_path)
    assert len(second.csv) == len(premier.csv)
    for a, b in zip(premier.csv, second.csv):
        _, ca, la = _csv(a)
        _, cb, lb = _csv(b)
        assert (ca, la) == (cb, lb)
        assert a["download"] == b["download"]
    # Et l'etat ecrit est stable : on le retrouve a l'identique.
    lien2 = next(v for k, v in second.liens.items() if k != ident)
    assert urllib.parse.parse_qs(lien2.split("#", 1)[1]) == urllib.parse.parse_qs(hash_ecrit)


@chromium
def test_changer_d_ecran_ne_reinitialise_pas_le_filtre(pages, rendus, tmp_path) -> None:
    """Fiche -> comparaison avec le hash de la fiche : massif et saison sont repris."""
    hash_fiche = rendus["fiche"].liens["comparaison"].split("#", 1)[1]
    gabarit, data = pages["comparaison"]
    dom = _rendre(injecter(gabarit, data), hash_fiche, tmp_path)
    retour = urllib.parse.parse_qs(dom.liens["fiche"].split("#", 1)[1])
    depart = urllib.parse.parse_qs(hash_fiche)
    for cle in ("m", "s", "zz"):
        assert retour[cle] == depart[cle], cle
    assert str(ASPE) in dom.titre or "Comparaison" in dom.titre


@chromium
def test_export_png_produit_une_image(pages, tmp_path) -> None:
    gabarit, data = pages["fiche"]
    (saisons,) = [m["saisons"] for m in data["massifs"] if m["id"] == ASPE]
    script = (
        "PARTAGE.png(document.getElementById('g-risque')).then("
        "u => { document.title = 'PNG|' + u.slice(0, 22) + '|' + u.length; },"
        "e => { document.title = 'ERR|' + e.message; });"
    )
    dom = _rendre(injecter(gabarit, data), f"m={ASPE}&s={saisons[-1]}", tmp_path, script)
    assert dom.titre.startswith("PNG|data:image/png;base64,|"), dom.titre
    assert int(dom.titre.rsplit("|", 1)[1]) > 5000


@chromium
def test_csv_de_l_exploration_reprend_les_comptes_traces_et_garde_l_etat_etranger(rendus, pages) -> None:
    dom = rendus["exploration"]
    a = next(x for x in dom.csv if x["download"].startswith("bra-exploration-pentes-"))
    _, colonnes, lignes = _csv(a)
    assert colonnes[:6] == ["entite", "massif_id", "saison", "secteur", "jours", "jours_couverts"]
    assert len(lignes) == len(pages["exploration"][1]["orientations"]) == 8
    # Les liens de navigation reportent le fragment complet, cle etrangere comprise.
    assert all("zz=garde" in h for h in dom.liens.values())


@chromium
def test_l_etat_de_la_carte_et_le_mode_de_comparaison_traversent_les_ecrans(pages, tmp_path) -> None:
    """Revue T15 : `d=1` rouvre les tableaux de la carte ; `x=choix` survit a un passage par l'exploration."""
    (tmp_path / "c").mkdir()
    carte_dom = _rendre(injecter(pages["carte"][0], pages["carte"][1]), "mc=risque_moyen&d=1", tmp_path / "c")
    assert "Masquer" in carte_dom.texte["tbl"]
    (tmp_path / "e").mkdir()
    expl = _rendre(injecter(pages["exploration"][0], pages["exploration"][1]), f"x=choix&m={ASPE}", tmp_path / "e")
    assert "x=choix" in expl.liens["comparaison"]
