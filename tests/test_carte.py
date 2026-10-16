"""Carte d'accueil (T12, spec section 6).

Construite sur la serie `tests/series/risque/` (voir test_metriques_risque) :
Aspe-Ossau y est diffuse sur `coeur` a chacune des neuf saisons comparables
(16 decembre de chaque saison, plus decembre 2023 et 2024) ; Oisans (28-30
avril 2021) et Luchonnais (05/11/2023) ont des bulletins, mais aucun dans
`coeur` ; les 33 autres massifs n'ont aucun bulletin. C'est exactement le cas
que la carte doit distinguer : un massif sans donnee n'est pas un massif a zero.
"""

from __future__ import annotations

import json
import re

import duckdb
import polars as pl
import pytest

from bra_analytics import carte
from bra_analytics.build import build
from bra_analytics.fenetres import DEFAUT, FENETRES, SAISONS_NON_COMPARABLES, MOIS_FR
from bra_analytics.massifs import MASSIFS
from bra_analytics.metriques import risque

from .conftest import SERIES

ASPE, OISANS, LUCHONNAIS = 65, 15, 68


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("carte")
    chemin = tmp / "bra.duckdb"
    build(SERIES / "risque", tmp / "warehouse", chemin)
    return chemin


@pytest.fixture(scope="module")
def data(db) -> dict:
    return carte.payload(db)


def _massif(data: dict, massif_id: int) -> dict:
    (m,) = [m for m in data["massifs"] if m["id"] == massif_id]
    return m


# --- valeurs ---------------------------------------------------------------------

def test_valeurs_egales_a_moyenne_pluriannuelle(db, data) -> None:
    """La carte ne recalcule rien : elle reprend la metrique d'accueil de T6."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        attendu = risque.moyenne_pluriannuelle(con)
    finally:
        con.close()
    assert attendu.height > 0
    for row in attendu.iter_rows(named=True):
        m = _massif(data, row["massif_id"])
        for cle in ("risque_moyen", "jours_couverts", "jours_avec_indice",
                    "jours_3_plus", "jours_4_plus", "jours_5", "saisons"):
            assert m[cle] == row[cle], (row["massif_id"], cle)


def test_maximum_atteint_repris_de_metriques_saison(db, data) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        saisons = risque.metriques_saison(con, fenetre=DEFAUT.nom, massifs=[ASPE])
    finally:
        con.close()
    retenues = saisons.filter(pl.col("comparable"))
    maxi = retenues["risque_max"].max()
    m = _massif(data, ASPE)
    assert m["risque_max"] == maxi
    assert m["jours_au_max"] == retenues.filter(pl.col("risque_max") == maxi)["jours_au_max"].sum()
    # Une saison ecartee ne fournit pas le maximum : 2019-2020 porte un 3 le 16/12.
    assert "2019-2020" not in m["saisons_presentes"]


def test_une_moyenne_ne_voyage_jamais_sans_ses_jours(data) -> None:
    """Indice ordinal : la moyenne s'accompagne des jours couverts et des jours a 4 ou 5."""
    avec = [m for m in data["massifs"] if m["risque_moyen"] is not None]
    assert avec
    for m in avec:
        assert isinstance(m["jours_couverts"], int) and m["jours_couverts"] > 0
        assert isinstance(m["jours_4_plus"], int)
        assert isinstance(m["jours_avec_indice"], int)


# --- diffusion -------------------------------------------------------------------

def test_les_36_massifs_sont_presents(data) -> None:
    assert sorted(m["id"] for m in data["massifs"]) == sorted(m.id for m in MASSIFS)


def test_massif_non_diffuse_distinct_d_un_massif_a_zero(data) -> None:
    aspe = _massif(data, ASPE)
    assert aspe["diffusion"] == "complete"
    assert aspe["jours_5"] == 0  # un vrai zero : diffuse, jamais a 5

    for mid in (OISANS, LUCHONNAIS, 1):
        m = _massif(data, mid)
        assert m["diffusion"] == "absente", mid
        # Pas de zero invente : la valeur est absente, pas nulle.
        assert m["risque_moyen"] is None and m["jours_3_plus"] is None
        assert m["jours_couverts"] == 0
        assert m["saisons_presentes"] == []


def test_classement_de_la_diffusion() -> None:
    comparables = ["2016-2017", "2017-2018", "2018-2019"]
    assert carte.diffusion(comparables, comparables) == ("complete", [])
    assert carte.diffusion(["2018-2019"], comparables) == (
        "partielle", ["2016-2017", "2017-2018"])
    assert carte.diffusion([], comparables) == ("absente", comparables)


def test_saisons_manquantes_publiees(data) -> None:
    m = _massif(data, ASPE)
    assert m["saisons_manquantes"] == []
    assert len(m["saisons_presentes"]) == len(data["saisons_comparables"])


# --- libelles et periode -----------------------------------------------------------

def test_libelle_dit_les_saisons_comparables_sur_le_total(data) -> None:
    assert carte.libelle_saisons(9, 11) == "neuf saisons comparables sur onze"
    # La serie de test n'a pas de 2015-2016 : neuf comparables sur dix saisons.
    assert data["libelle_saisons"] == "neuf saisons comparables sur dix"
    assert "dix ans" not in json.dumps(data, ensure_ascii=False)


def test_saisons_comparables_derivees_de_fenetres(data) -> None:
    assert len(data["saisons_comparables"]) == 9
    assert not set(data["saisons_comparables"]) & set(SAISONS_NON_COMPARABLES)
    assert set(data["saisons_ecartees"]) == {"2019-2020"}
    assert data["saisons_ecartees"]["2019-2020"] == SAISONS_NON_COMPARABLES["2019-2020"]


def test_fenetre_vient_de_fenetres_py(data) -> None:
    f = data["fenetre"]
    assert f["nom"] == DEFAUT.nom
    assert f["debut"] == list(DEFAUT.debut) and f["fin"] == list(DEFAUT.fin)
    assert f["libelle"] == DEFAUT.libelle


def test_metriques_proposees(data) -> None:
    cles = {m["cle"]: m for m in data["metriques"]}
    assert set(cles) == {"risque_moyen", "jours_3_plus_par_saison", "risque_max", "duree_enneigement"}
    # La duree d'enneigement depend de T7 : annoncee, pas inventee.
    assert cles["duree_enneigement"]["disponible"] is False
    assert cles["duree_enneigement"]["motif"]
    assert all(m["disponible"] for k, m in cles.items() if k != "duree_enneigement")
    assert all("duree_enneigement" not in m for m in data["massifs"])


def test_attributions_et_date_d_archive(data) -> None:
    # Dernier jour couvert de la serie : le bulletin du 15/12/2025, valide le 16.
    assert data["archive_jusqu_au"] == "2025-12-16"
    texte = " ".join(data["attribution"].values())
    assert "Météo-France" in texte and "Licence Ouverte 2.0" in texte
    assert "15/02/2024" in data["attribution"]["contours"]


# --- contours ----------------------------------------------------------------------

def test_contours_raccordes_sur_massif_id(data) -> None:
    codes = [f["properties"]["code"] for f in data["contours"]["features"]]
    assert sorted(codes) == sorted(m["id"] for m in data["massifs"])
    assert len(codes) == 36


# --- gabarit -----------------------------------------------------------------------

def test_gabarit_ne_recopie_ni_bornes_ni_saisons() -> None:
    """Bornes et saisons ecartees voyagent dans le payload, jamais dans le gabarit."""
    html = carte.TEMPLATE.read_text(encoding="utf-8")
    assert "__DONNEES__" in html
    for saison in SAISONS_NON_COMPARABLES:
        assert saison not in html
    mois_accentues = {"fevrier": "février", "aout": "août", "decembre": "décembre"}
    for f in FENETRES:
        for m, j in (f.debut, f.fin):
            nom = MOIS_FR[m - 1]
            for graphie in {nom, mois_accentues.get(nom, nom)}:
                assert not re.search(rf"\b{j}\s+{graphie}", html), (f.nom, j, graphie)
            assert not re.search(rf"\[\s*{m}\s*,\s*{j}\s*\]", html), (f.nom, m, j)
    assert not re.search(r"\b(neuf|onze)\b", html)


def test_bra_carte_ecrit_une_page_autonome(db, tmp_path, capsys) -> None:
    from bra_analytics.cli import main

    out = tmp_path / "sous" / "carte.html"
    assert main(["carte", "--db", str(db), "--out", str(out)]) == 0
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "__DONNEES__" not in page
    blob = re.search(r"const D = (\{.*?\});\n", page, re.S).group(1)
    data = json.loads(blob.replace("<\\/", "</"))
    assert len(data["massifs"]) == 36
    assert "carte" in capsys.readouterr().out


def test_jours_3_plus_rapportes_aux_saisons_diffusees(data) -> None:
    """Un compte brut penalise les massifs diffuses moins longtemps (Haut-Var
    depuis novembre 2018, Andorre absente en 2025-2026) : la carte affiche le
    nombre moyen de jours >= 3 par saison diffusee, le compte brut restant
    dans le payload pour le survol."""
    for m in data["massifs"]:
        if m["jours_3_plus"] is None:
            assert m["jours_3_plus_par_saison"] is None
            continue
        assert m["saisons"] > 0
        assert m["jours_3_plus_par_saison"] == round(m["jours_3_plus"] / m["saisons"], 1)
