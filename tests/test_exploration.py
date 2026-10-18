"""Ecran d'exploration (T14, spec section 6).

Deux niveaux, comme `test_comparaison.py`. Le payload se teste en Python contre
les vues de `metriques/pentes.py` et contre la serie lue a la main (docstring de
`test_metriques_pentes.py`). Le comportement de la page -- etiquette d'altitude,
croisement par tranche, restriction d'epoque des situations, refus de comparer
-- vit dans le gabarit : il se teste en le rendant dans Chromium headless et en
lisant le DOM. Ces tests sont sautes si aucun Chromium n'est installe.

Entrepot : les neuf jours de decembre 2024 de `tests/series/transport/` (roses,
vent, `sat`) plus les saisons 2016 a 2023 de `tests/series/risque/` (cartouche
de risque seul, donc sans situations typiques). Les bulletins de decembre 2024
et 2025 de la serie `risque` sont laisses de cote : ils doubleraient les jours
de `transport` sans en porter la rose.
"""

from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import duckdb
import pytest

from bra_analytics import exploration
from bra_analytics.build import build
from bra_analytics.fenetres import DEFAUT, SAISON_COMPLETE, SAISONS_NON_COMPARABLES
from bra_analytics.metriques import pentes, risque
from bra_analytics.metriques.risque import ComparaisonRefusee

from .conftest import SERIES
from .test_comparaison import _chromium, chromium

ASPE = 65


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("exploration")
    source = tmp / "source"
    source.mkdir()
    for f in (SERIES / "risque").glob("*.xml"):
        if "_202412" not in f.name and "_202512" not in f.name:
            shutil.copy(f, source / f.name)
    for f in (SERIES / "transport").glob("*.xml"):
        shutil.copy(f, source / f.name)
    chemin = tmp / "bra.duckdb"
    build(source, tmp / "warehouse", chemin)
    return chemin


@pytest.fixture(scope="module")
def data(db) -> dict:
    return exploration.payload(db)


@pytest.fixture(scope="module")
def con(db):
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


# --- payload ---------------------------------------------------------------------

def test_roses_egales_aux_vues_de_t9(con, data) -> None:
    """Le payload porte les comptes de la vue, pas une reconstruction."""
    for fenetre in (SAISON_COMPLETE, DEFAUT.nom):
        df = pentes.rose_saison(con, fenetre=fenetre)
        for (mid, saison), g in df.group_by(["massif_id", "saison"]):
            rose = data["roses"][str(mid)][saison].get(fenetre)
            par_o = {r["orientation"]: r for r in g.iter_rows(named=True)}
            assert rose["s"] == [par_o[o]["jours_signales"] for o in data["orientations"]]
            assert rose["s3"] == [par_o[o]["jours_signales_ge3"] for o in data["orientations"]]
            assert rose["s4"] == [par_o[o]["jours_signales_ge4"] for o in data["orientations"]]
            premiere = next(iter(par_o.values()))
            assert (rose["c"], rose["c3"], rose["c4"]) == (
                premiere["jours_couverts"], premiere["jours_ge3"], premiere["jours_ge4"],
            )


def test_rose_de_decembre_2024_relue_a_la_main(data) -> None:
    rose = data["roses"][str(ASPE)]["2024-2025"][SAISON_COMPLETE]
    assert data["orientations"] == ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    assert rose["c"] == 9  # le trou du 6 decembre n'est pas un jour
    assert rose["s"] == [9, 9, 5, 5, 4, 4, 4, 4]
    assert (rose["c3"], rose["s3"]) == (4, [4] * 8)


def test_aucune_rose_ne_porte_d_altitude(data) -> None:
    """Pas de matrice altitude x orientation : une rose est un jeu de huit comptes, rien d'autre."""
    assert data["altitude"] == "non localisée en altitude"
    for saisons in data["roses"].values():
        for fenetres in saisons.values():
            for rose in fenetres.values():
                assert set(rose) == {"c", "s", "c3", "s3", "c4", "s4"}
                assert all(len(rose[k]) == 8 for k in ("s", "s3", "s4"))


def test_croisement_egal_a_la_vue_et_ventile_par_tranche(con, data) -> None:
    df = pentes.croisement_vent(con, fenetre=SAISON_COMPLETE, massifs=[ASPE])
    par_tranche = data["vent"][str(ASPE)]["2024-2025"][SAISON_COMPLETE]
    assert set(par_tranche) == set(df["tranche"])
    for r in df.iter_rows(named=True):
        i = data["orientations"].index(r["direction_vent"])
        assert par_tranche[r["tranche"]][i] == [r["jours_vent"], r["jours_pente_chargee_signalee"]]
    # Vent de N en tranche haute : 3 jours, pente chargee (S) signalee 2 fois (test_metriques_pentes).
    assert par_tranche["haute"][0] == [3, 2]


def test_situations_egales_a_la_vue_et_depuis_leur_premiere_saison(con, data) -> None:
    assert data["situations_depuis"] == "2024-2025"
    sit = data["situations"][str(ASPE)]
    assert set(sit) == {"2024-2025"}  # les saisons anterieures n'ont pas de ligne : pas de zero
    c = sit["2024-2025"][SAISON_COMPLETE]
    assert c["c"] == 9
    # sat1 relu a la main : 6 6 6 6 2 2 1 1 2 ; sat2 : 1 (8), 2 (10), 1 (11).
    dominante = {code: j for rang, code, j in c["l"] if rang == 1}
    assert dominante == {6: 4, 2: 3, 1: 2}
    df = pentes.situations(con, fenetre=SAISON_COMPLETE, massifs=[ASPE])
    assert sorted(c["l"]) == sorted([r["rang"], r["code"], r["jours"]] for r in df.iter_rows(named=True))
    assert data["libelles_sat"]["2"] == pentes.LIBELLES_SAT[2]
    assert data["code_sans_mecanisme"] == pentes.CODE_SANS_MECANISME


def test_refus_de_comparer_hors_coeur_vient_de_risque(data) -> None:
    assert data["refus"][DEFAUT.nom] is None
    for f in data["fenetres"]:
        if f["nom"] == DEFAUT.nom:
            continue
        with pytest.raises(ComparaisonRefusee):
            risque.fenetre_comparable(f["nom"])
        assert data["refus"][f["nom"]] == exploration.refus(f["nom"])
        assert data["refus"][f["nom"]]


def test_saisons_non_comparables_etiquetees_pas_supprimees(data) -> None:
    par_nom = {s["nom"]: s for s in data["saisons"]}
    for saison, motif in SAISONS_NON_COMPARABLES.items():
        if saison in par_nom:
            assert par_nom[saison]["comparable"] is False
            assert par_nom[saison]["motif"] == motif


def test_seuils_et_bornes_viennent_du_python(data) -> None:
    assert [c["seuil"] for c in data["conditions"]] == [None, risque.SEUIL_EPISODE, 4]
    coeur = next(f for f in data["fenetres"] if f["nom"] == DEFAUT.nom)
    assert coeur["debut"] == list(DEFAUT.debut) and coeur["fin"] == list(DEFAUT.fin)


def test_entrepot_sans_meteo_garde_les_roses_et_signale_le_vent(tmp_path) -> None:
    chemin = tmp_path / "bra.duckdb"
    build(SERIES / "risque", tmp_path / "warehouse", chemin)
    d = exploration.payload(chemin)
    assert d["vent"] is None and d["roses"] and d["situations_depuis"] is None


def test_la_page_est_autonome(db, tmp_path) -> None:
    html = exploration.render(db, tmp_path / "e.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "__DONNEES__" not in html and "__COMMUN__" not in html
    assert "<script src" not in html
    assert "Licence Ouverte 2.0" in html


# --- page, rendue dans Chromium ---------------------------------------------------

class _Page(HTMLParser):
    """Texte par `id`, et chaque element `.carte` / `.alt` / `.vide` avec ses attributs."""

    def __init__(self) -> None:
        super().__init__()
        self.balises: list[tuple[str, dict]] = []
        self.texte: dict[str, str] = {}
        self._pile: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.balises.append((tag, a))
        ident = a.get("id")
        if ident:
            self.texte[ident] = ""
        if tag not in ("br", "meta", "link", "input", "option", "line", "rect", "path", "circle"):
            self._pile.append(ident)

    def handle_endtag(self, tag):
        if self._pile:
            self._pile.pop()

    def handle_data(self, d):
        for ident in self._pile:
            if ident:
                self.texte[ident] += d

    def classe(self, nom: str) -> list[dict]:
        return [a for _, a in self.balises if nom in a.get("class", "").split()]


def _rendre(html: str, fragment: str, tmp: Path) -> _Page:
    page = tmp / "page.html"
    page.write_text(html, encoding="utf-8")
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=4000", "--dump-dom",
         f"file://{page}#{fragment}"],
        capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    dom = _Page()
    dom.feed(sortie)
    return dom


@pytest.fixture(scope="module")
def html(db, tmp_path_factory) -> str:
    return exploration.render(db, tmp_path_factory.mktemp("page") / "e.html").read_text(encoding="utf-8")


def _secteurs(dom: _Page, nom: str) -> list[tuple[str, int, int]]:
    return [(a["data-secteur"], int(a["data-jours"]), int(a["data-couverts"])) for a in dom.classe(nom) if "data-secteur" in a]


@chromium
def test_chaque_rose_des_pentes_et_chaque_situation_est_etiquetee_non_localisee(html, tmp_path) -> None:
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025,2023-2024&f=saison_complete", tmp_path)
    assert "Comparaison de saisons refusée" in dom.texte["alerte"]  # deux saisons hors coeur : rien n'est dessine
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&k=toutes&t=haute", tmp_path)
    for grille, forme in (("g-pentes", "rose"), ("g-croise", "croisement"), ("g-sit", "situations")):
        assert dom.texte[grille].count("non localisée en altitude") == 1, grille
    # La rose des vents a une altitude reelle : elle porte sa tranche, pas l'etiquette.
    assert "non localisée" not in dom.texte["g-vent"]
    assert "non localisée en altitude" in dom.texte["sous-pentes"]


@chromium
def test_rose_dessinee_egale_la_serie_relue_a_la_main(html, tmp_path) -> None:
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&k=toutes&t=haute", tmp_path)
    # Premiere rose de la page : celle des pentes ; viennent ensuite les secteurs du vent.
    secteurs = _secteurs(dom, "wedge")
    assert secteurs[:8] == [
        ("N", 9, 9), ("NE", 9, 9), ("E", 5, 9), ("SE", 5, 9), ("S", 4, 9), ("SW", 4, 9), ("W", 4, 9), ("NW", 4, 9),
    ]
    assert len(secteurs) == 16  # pentes + vent
    # Les jours ge3 : quatre jours, les huit secteurs.
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&k=ge3&t=haute", tmp_path)
    assert all((j, c) == (4, 4) for _, j, c in _secteurs(dom, "wedge")[:8])


@chromium
def test_croisement_se_lit_par_tranche_de_vent(html, data, tmp_path) -> None:
    attendu = data["vent"][str(ASPE)]["2024-2025"][SAISON_COMPLETE]["haute"]
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&t=haute", tmp_path)
    barres = _secteurs(dom, "barre")
    # En affichage "roses", les seules barres par secteur de la page sont celles du croisement.
    assert barres == [(o, attendu[i][1], attendu[i][0]) for i, o in enumerate(data["orientations"])]
    assert "haute" in dom.texte["sous-croise"] and "toutes tranches confondues" in dom.texte["sous-croise"]
    # Une tranche sans vent publie reste vide : elle n'est pas completee.
    absente = next(t["nom"] for t in data["tranches"] if t["nom"] not in data["vent"][str(ASPE)]["2024-2025"][SAISON_COMPLETE])
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&t={absente}", tmp_path)
    assert "Aucun vent directionnel publié" in dom.texte["g-croise"]


@chromium
def test_saison_anterieure_aux_situations_ecrit_sa_restriction(html, tmp_path) -> None:
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2023-2024&f=saison_complete", tmp_path)
    assert "à partir de la saison 2024-2025" in dom.texte["g-sit"]
    assert "Ce n'est pas un zéro" in dom.texte["g-sit"]
    assert not [a for a in dom.classe("barre") if "data-code" in a]  # aucune barre de situation


@chromium
def test_comparaison_de_saisons_refusee_hors_coeur_et_permise_sur_coeur(html, data, tmp_path) -> None:
    hors = _rendre(html, f"x=saisons&m={ASPE}&c=2022-2023,2023-2024&f=commune", tmp_path)
    assert "refusée" in hors.texte["alerte"] and data["refus"]["commune"][:20] in hors.texte["alerte"].replace("é", "e")
    assert not hors.classe("carte")
    sur_coeur = _rendre(html, f"x=saisons&m={ASPE}&c=2022-2023,2023-2024&f={DEFAUT.nom}", tmp_path)
    assert sur_coeur.texte["alerte"].strip() == ""
    assert len(sur_coeur.classe("carte")) >= 2
    # Une seule saison se lit sur n'importe quelle fenetre.
    seule = _rendre(html, f"x=saisons&m={ASPE}&c=2023-2024&f=commune", tmp_path)
    assert seule.texte["alerte"].strip() == ""


@chromium
def test_saison_non_comparable_etiquetee_avec_son_motif(html, data, tmp_path) -> None:
    saison = next(s for s in SAISONS_NON_COMPARABLES if s in {x["nom"] for x in data["saisons"]})
    dom = _rendre(html, f"x=saisons&m={ASPE}&c={saison}&f=saison_complete", tmp_path)
    nc = [a for a in dom.classe("carte") if "nc" in a["class"].split()]
    assert nc and all(a["data-entite"] == saison for a in nc)
    assert any("non comparable" in a.get("class", "") or a.get("title") == SAISONS_NON_COMPARABLES[saison]
               for _, a in dom.balises)


@chromium
def test_les_barres_donnent_les_memes_comptes_que_les_roses(html, tmp_path) -> None:
    rose = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&d=rose", tmp_path)
    barres = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete&d=barres", tmp_path)
    # Barres : pentes, vent, croisement (24 secteurs) ; roses : pentes et vent (16) puis le croisement en barres.
    assert _secteurs(rose, "wedge") == _secteurs(barres, "barre")[:16]
    assert _secteurs(rose, "barre") == _secteurs(barres, "barre")[16:]
    assert not barres.classe("wedge")


@chromium
def test_attribution_et_date_d_archive_sont_visibles(html, tmp_path) -> None:
    dom = _rendre(html, f"x=saisons&m={ASPE}&c=2024-2025&f=saison_complete", tmp_path)
    assert "Licence Ouverte 2.0" in dom.texte["attrib"] and "archive arrêtée au" in dom.texte["attrib"]
