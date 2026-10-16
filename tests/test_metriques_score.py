"""Score composite versionne (T10, spec section 5.5).

La vue `score_saison` ne lit que trois vues amont (`risque_saison`,
`neige_fraiche_saison`, `meteo_vent_saison`), dont les blocs T6-T8 ont leurs
propres tests sur bulletins reels. Ici ces trois vues sont posees a la main
sur une base en memoire : chaque cas du score (composante manquante, tranche
la plus exposee, ligne non comparable) se relit sans reconstruire l'entrepot.
"""

from __future__ import annotations

import duckdb
import pytest

from bra_analytics.metriques import score
from bra_analytics.metriques.score import Formule

SAISON = "2022-2023"


def _base() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        """
        CREATE VIEW risque_saison AS SELECT * FROM (VALUES
          -- massif 1 : 0,45 de jours >= 3 ; massif 2 : sans neige ; massif 3 : non comparable
          ('coeur', '2022-2023', 1, 2022, 'A', 'Z', true,  NULL, 100, 45),
          ('coeur', '2022-2023', 2, 2022, 'B', 'Z', true,  NULL, 100, 90),
          ('coeur', '2022-2023', 3, 2022, 'C', 'Z', false, 'motif', 100, 10),
          ('coeur', '2022-2023', 4, 2022, 'D', 'Z', true,  NULL, 100, 100),
          ('commune', '2022-2023', 1, 2022, 'A', 'Z', false, NULL, 100, 45)
        ) t(fenetre, saison, massif_id, saison_debut, massif_nom, zone, comparable,
            motif_exclusion, jours_avec_indice, jours_3_plus)
        """
    )
    con.execute(
        """
        CREATE VIEW neige_fraiche_saison AS SELECT * FROM (VALUES
          ('coeur', '2022-2023', 1, 'moyenne', true,  'secteurs', false, 100, 7),
          ('coeur', '2022-2023', 3, 'moyenne', true,  'secteurs', false, 100, 7),
          ('coeur', '2022-2023', 4, 'moyenne', true,  'fourchette', true, 100, 50)
        ) t(fenetre, saison, massif_id, tranche, comparable, lecture_cumul,
            rupture_de_serie, jours_observes, jours_chute)
        """
    )
    con.execute(
        """
        CREATE VIEW meteo_vent_saison AS SELECT * FROM (VALUES
          -- massif 1 : la tranche haute (30 %) l'emporte sur la basse (5 %)
          ('coeur', '2022-2023', 1, 'basse', true, 100, 5),
          ('coeur', '2022-2023', 1, 'haute', true, 90, 27),
          ('coeur', '2022-2023', 2, 'haute', true, 100, 10),
          ('coeur', '2022-2023', 3, 'haute', true, 100, 10),
          ('coeur', '2022-2023', 4, 'haute', true, 100, 90)
        ) t(fenetre, saison, massif_id, tranche, comparable, jours_avec_vent, jours_vent_fort)
        """
    )
    score.creer_vues(con)
    return con


@pytest.fixture(scope="module")
def lignes() -> dict[int, dict]:
    df = score.scores(_base())
    return {r["massif_id"]: r for r in df.iter_rows(named=True)}


# --- la formule et sa version ------------------------------------------------

def test_formule_expose_version_poids_et_ancres() -> None:
    f = score.formule()
    assert f["version"] == score.FORMULE.version
    assert [c["nom"] for c in f["composantes"]] == list(score.COMPOSANTES)
    assert sum(c["poids"] for c in f["composantes"]) == pytest.approx(1.0)
    assert f["fenetre"] == "coeur"


def test_changer_un_poids_change_la_version() -> None:
    f = score.FORMULE
    voisine = Formule(
        numero=f.numero,
        poids={"risque": 0.4, "neige": 0.4, "vent": 0.2},
        ancres=f.ancres,
        definitions=f.definitions,
        fenetre=f.fenetre,
    )
    assert voisine.version != f.version


def test_changer_une_ancre_change_la_version() -> None:
    f = score.FORMULE
    voisine = Formule(
        numero=f.numero,
        poids=f.poids,
        ancres={**f.ancres, "vent": (0.0, 0.26)},
        definitions=f.definitions,
        fenetre=f.fenetre,
    )
    assert voisine.version != f.version


def test_une_formule_incoherente_est_refusee() -> None:
    f = score.FORMULE
    with pytest.raises(ValueError, match="sommer a 1"):
        Formule(1, {"risque": 0.5, "neige": 0.5, "vent": 0.5}, f.ancres, f.definitions, "coeur")
    with pytest.raises(ValueError, match="borne basse"):
        Formule(1, f.poids, {**f.ancres, "neige": (0.2, 0.1)}, f.definitions, "coeur")


def test_la_version_voyage_avec_chaque_valeur(lignes) -> None:
    assert {r["version_score"] for r in lignes.values()} == {score.FORMULE.version}


# --- normalisation -----------------------------------------------------------

def test_normaliser_borne_aux_ancres() -> None:
    bas, haut = score.ANCRES["risque"]
    assert score.normaliser("risque", bas) == 0.0
    assert score.normaliser("risque", haut) == 1.0
    assert score.normaliser("risque", 0.0) == 0.0  # sous l'ancre : borne, pas negatif
    assert score.normaliser("risque", 1.0) == 1.0  # au-dessus : borne, pas > 1
    assert score.normaliser("risque", (bas + haut) / 2) == pytest.approx(0.5)
    assert score.normaliser("risque", None) is None


# --- la vue ------------------------------------------------------------------

def test_composantes_et_score_d_une_ligne_complete(lignes) -> None:
    r = lignes[1]
    assert (r["part_risque"], r["part_neige"]) == (0.45, 0.07)
    assert r["part_vent"] == pytest.approx(0.30)  # tranche haute : 27 / 90
    assert r["tranche_vent"] == "haute"
    assert (r["jours_risque"], r["jours_neige"], r["jours_vent"]) == (100, 100, 90)
    # risque (0,45-0,10)/0,70 = 0,5 ; neige (0,07-0,02)/0,10 = 0,5 ; vent borne a 1
    assert r["score"] == pytest.approx(100 * (0.5 * 0.5 + 0.3 * 0.5 + 0.2 * 1.0))


def test_la_vue_et_le_calcul_python_donnent_la_meme_valeur(lignes) -> None:
    for r in lignes.values():
        attendu = score.calculer(r["part_risque"], r["part_neige"], r["part_vent"])
        assert r["score"] == attendu


def test_composante_manquante_donne_un_score_nul_etiquete(lignes) -> None:
    r = lignes[2]  # pas de neige fraiche du tout
    assert r["score"] is None
    assert r["composantes_manquantes"] == "neige"
    assert r["part_risque"] == 0.9  # les composantes presentes restent lisibles


def test_ligne_complete_n_a_pas_de_composante_manquante(lignes) -> None:
    assert lignes[1]["composantes_manquantes"] is None


def test_ligne_non_comparable_garde_son_score_et_son_motif(lignes) -> None:
    r = lignes[3]
    assert r["comparable"] is False
    assert r["motif_exclusion"] == "motif"
    assert r["score"] is not None  # etiquetee, pas supprimee


def test_score_borne_a_100(lignes) -> None:
    assert lignes[4]["score"] == 100.0


def test_la_rupture_de_lecture_de_la_neige_voyage(lignes) -> None:
    assert (lignes[4]["lecture_neige"], lignes[4]["rupture_neige"]) == ("fourchette", True)
    assert lignes[1]["rupture_neige"] is False


def test_seule_la_fenetre_coeur_est_lue() -> None:
    df = score.scores(_base(), massifs=[1])
    assert df.height == 1  # la ligne `commune` du massif 1 n'entre pas


def test_comparables_seulement_filtre() -> None:
    df = score.scores(_base(), comparables_seulement=True)
    assert 3 not in df["massif_id"].to_list()


def test_scores_pose_la_vue_sur_une_base_qui_ne_l_a_pas() -> None:
    con = _base()
    con.execute(f"DROP VIEW {score.VUE}")
    assert score.scores(con).height == 4


def test_la_vue_existe_apres_le_build(tmp_path) -> None:
    from bra_analytics.build import build

    from .conftest import SERIES

    db = tmp_path / "bra.duckdb"
    build(SERIES / "transport", tmp_path / "warehouse", db)
    con = duckdb.connect(str(db), read_only=True)
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    assert score.VUE in presentes
    # La serie (decembre) tombe avant la fenetre `coeur` : aucune ligne, mais la
    # vue s'evalue de bout en bout sur les vraies vues amont.
    df = score.scores(con)
    assert "version_score" in df.columns
    con.close()


def test_la_version_v1_est_figee() -> None:
    # Un changement d'ancre, de poids ou de definition change l'empreinte : ce test
    # force a le faire exprès (nouvelle version, glossaire § 13 mis a jour).
    assert score.FORMULE.version == "1-fa30d1"
