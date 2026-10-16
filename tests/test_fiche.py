"""Fiche massif-saison (T11, spec section 6).

Construite sur `tests/series/risque/` comme la carte : Aspe-Ossau y est
diffuse le 16 decembre de chaque saison (jour dans `coeur`), plus decembre
2023 et 2024. Neuf saisons comparables en portent donc un bulletin au meme
jour du calendrier, assez pour franchir `MIN_SAISONS_NORMALE`.
"""

from __future__ import annotations

import shutil
from datetime import date

import duckdb
import pytest

from bra_analytics import fiche
from bra_analytics.build import build
from bra_analytics.dashboard import ABSENT, SANS_INDICE
from bra_analytics.fenetres import DEFAUT, FENETRES, SAISONS_NON_COMPARABLES
from bra_analytics.metriques import risque

from .conftest import SERIES

ASPE = 65


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fiche")
    chemin = tmp / "bra.duckdb"
    # Les trois blocs de la fiche (risque, neige, meteo) dans un meme entrepot ;
    # les fichiers communs a deux series sont identiques et dedupliques par build().
    source = tmp / "source"
    for bloc in ("risque", "enneigement", "meteo"):
        shutil.copytree(SERIES / bloc, source, dirs_exist_ok=True)
    build(source, tmp / "warehouse", chemin)
    return chemin


@pytest.fixture(scope="module")
def data(db) -> dict:
    return fiche.payload(db)


def test_axe_calendaire_porte_le_29_fevrier() -> None:
    axe = fiche.axe_calendaire()
    assert axe[0] == "10-01" and axe[-1] == "06-30"
    assert "02-29" in axe
    assert len(axe) == len(set(axe)) == 274


def test_serie_de_risque_relit_risque_journalier(db, data) -> None:
    """Un caractere par jour depuis `origine`, `decalage_rang` ramene au rang de la saison."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        jours = risque.serie_jour(con, massifs=[ASPE])
    finally:
        con.close()
    assert jours.height > 0
    for r in jours.iter_rows(named=True):
        e = data["series"][ASPE][r["saison"]]
        i = (r["jour_validite"] - date.fromisoformat(e["origine"])).days
        attendu = SANS_INDICE if r["risque_maxi"] is None else str(r["risque_maxi"])
        assert e["risque"][i] == attendu
        assert i - e["decalage_rang"] + 1 == r["jour_de_saison"]
    for e in data["series"][ASPE].values():
        assert len(e["risque"]) == e["longueur"]
        assert e["risque"][e["decalage_rang"]] != ABSENT


def test_mediane_de_la_bande_egale_la_normale_de_t6(db, data) -> None:
    """La bande ne redefinit pas la normale : sa mediane est `risque_jour.normale`."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        jours = risque.serie_jour(con, massifs=[ASPE])
    finally:
        con.close()
    normales = {
        r["jour_validite"].strftime("%m-%d"): r["normale"]
        for r in jours.iter_rows(named=True)
        if r["normale"] is not None
    }
    assert normales
    bande = data["bandes"]["calendaire"][ASPE]
    for k, case in enumerate(data["axe"]):
        if case in normales:
            assert bande["mediane"][k] == normales[case]


def test_bande_ordonnee_et_vide_sous_le_seuil_de_saisons(data) -> None:
    bande = data["bandes"]["calendaire"][ASPE]
    pleines = [k for k, m in enumerate(bande["mediane"]) if m is not None]
    assert pleines
    for k in pleines:
        assert bande["q1"][k] <= bande["mediane"][k] <= bande["q3"][k]
    # Toute case hors des jours portant au moins `min_saisons_bande` saisons est vide.
    assert len(pleines) < len(data["axe"])
    assert data["min_saisons_bande"] == risque.MIN_SAISONS_NORMALE


def test_bande_par_rang_et_calendaire_partagent_la_population(data) -> None:
    rang = data["bandes"]["rang"][ASPE]
    assert any(m is not None for m in rang["mediane"])
    assert len(rang["mediane"]) == data["rang_max"]


def test_saison_non_comparable_etiquetee_pas_supprimee(data) -> None:
    par_nom = {s["nom"]: s for s in data["saisons"]}
    for saison, motif in SAISONS_NON_COMPARABLES.items():
        if saison in par_nom:
            assert par_nom[saison]["comparable"] is False
            assert par_nom[saison]["motif"] == motif
    assert par_nom["2023-2024"]["comparable"] is True


def test_indicateurs_egaux_aux_metriques(db, data) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        coeur = risque.metriques_saison(con, fenetre=DEFAUT.nom, massifs=[ASPE])
    finally:
        con.close()
    assert coeur.height > 0
    for r in coeur.iter_rows(named=True):
        ind = data["indicateurs"][ASPE][r["saison"]][DEFAUT.nom]["risque"]
        assert ind["risque_moyen"] == r["risque_moyen"]
        assert ind["jours_avec_indice"] == r["jours_avec_indice"]


def test_bornes_de_fenetre_viennent_de_fenetres_py(data) -> None:
    offertes = {f["nom"]: f for f in data["fenetres"]}
    assert set(offertes) == set(fiche.FENETRES_FICHE)
    coeur = next(f for f in FENETRES if f.nom == DEFAUT.nom)
    assert offertes[DEFAUT.nom]["debut"] == list(coeur.debut)
    assert offertes[DEFAUT.nom]["fin"] == list(coeur.fin)


def test_la_page_est_autonome(db, tmp_path) -> None:
    out = fiche.render(db, tmp_path / "fiche.html")
    html = out.read_text(encoding="utf-8")
    assert "__DONNEES__" not in html
    assert html.startswith("<!doctype html>")
    # Pas de ressource de script chargee du reseau : seules les polices le sont.
    assert "<script src" not in html
    assert "Licence Ouverte 2.0" in html


def test_series_numeriques_alignees_sur_la_serie_de_risque(data) -> None:
    """Chaque serie porte un champ par jour depuis `origine` : meme longueur que le risque."""
    vues = 0
    for e in data["series"][ASPE].values():
        blocs = [e["iso0"][k] for k in e.get("iso0", {})]
        blocs += [v for t in e.get("neige", {}).values() for v in t.values()]
        blocs += list(e.get("vent", {}).values())
        for b in blocs:
            assert len(b.split(",")) == e["longueur"]
            vues += 1
    assert vues > 0
