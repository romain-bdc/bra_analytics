"""Bloc risque de la couche metriques (T6, spec section 5.1).

La serie `tests/series/risque/` est faite de bulletins reels, reduits a leur
en-tete et a leur cartouche de risque :

- Aspe-Ossau, 4 -> 22 decembre 2024 (jours couverts) :

      jour   04 05 .. 07 08 09 10 11 12 13 14 15 16 17 18 19 .. 21 22
      risque  1  1  .  2  4  4  4  3  2  2  2  3  3  3  3  3  .  2  3

  Deux trous d'archive reels : le 6 et le 20 decembre (aucun fichier pour le
  massif dans la source). Le second coupe un episode >= 3 en cours.
- Aspe-Ossau, 16 decembre de chaque saison 2016-2017 -> 2025-2026 : la base
  de l'ecart a la normale. 2019-2020 (non comparable) y porte un 3.
- Oisans, 28 -> 30 avril 2021 : 2, 3, puis `RISQUE1="-1"` -- un episode borde
  par un jour sans indice, et non par un trou.
- Aspe-Ossau, 12, 14 et 15 decembre 2023 (1, 3, 3), avec le 16 a 3 : un
  episode a cheval sur l'ouverture de la fenetre `coeur`. Le bulletin du 13
  (a 3) est **volontairement omis** : le trou qu'il laisse precede l'episode
  hors de la fenetre, et ne doit pas le rompre dans `coeur`.
- Luchonnais, 05/11/2023 : `RISQUE1="-1"` avec un `RISQUEMAXI="1"`, l'une des
  quatorze lignes non estimees mais comptees dans les moyennes.

Seuls les blocs etrangers au risque ont ete retires : en-tete et cartouche sont
ceux de la source, octet pour octet. `schema_version`, qui se lit dans la
structure du fichier, n'y est donc pas fidele.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from bra_analytics.build import build
from bra_analytics.fenetres import SAISON_COMPLETE
from bra_analytics.metriques import risque

from .conftest import SERIES

ASPE, OISANS, LUCHONNAIS = 65, 15, 68


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("metriques_risque")
    db = tmp / "bra.duckdb"
    build(SERIES / "risque", tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


def _saison(con, massif: int, saison: str, fenetre: str = SAISON_COMPLETE) -> dict:
    df = risque.metriques_saison(con, fenetre=fenetre, massifs=[massif], saisons=[saison])
    assert df.height == 1, (massif, saison, fenetre)
    return df.row(0, named=True)


# --- vues ---------------------------------------------------------------------

def test_les_vues_existent_apres_le_build(con) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    assert set(risque.VUES) <= presentes


def test_vues_temporaires_sur_un_entrepot_en_lecture_seule(tmp_path) -> None:
    """Un entrepot construit avant T6 n'a pas les vues : les fonctions les posent
    en vues temporaires, sans ecrire dans la base ouverte en lecture seule."""
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(SERIES / "risque", out, db)
    c = duckdb.connect(str(db))
    for vue in risque.VUES:
        c.execute(f"DROP VIEW {vue}")
    c.close()

    c = duckdb.connect(str(db), read_only=True)
    try:
        assert _saison(c, ASPE, "2024-2025")["jours_couverts"] == 17
    finally:
        c.close()


# --- risque du jour -----------------------------------------------------------

def test_risque_du_jour_indexe_sur_jour_validite(con) -> None:
    """Le bulletin redige le 15/12 decrit le 16/12 ; un trou n'a pas de ligne."""
    df = risque.serie_jour(con, massifs=[ASPE], saisons=["2024-2025"])
    par_jour = dict(zip(df["jour_validite"].to_list(), df["risque_maxi"].to_list()))
    assert par_jour[date(2024, 12, 16)] == 3
    assert date(2024, 12, 6) not in par_jour
    assert date(2024, 12, 20) not in par_jour
    assert df.height == 17


# --- comptes, parts, moyenne, mediane -----------------------------------------

def test_jours_par_seuil(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert (s["jours_3_plus"], s["jours_4_plus"], s["jours_5"]) == (10, 3, 0)
    c = _saison(con, ASPE, "2024-2025", "coeur")  # 15 -> 22 decembre
    assert (c["jours_couverts"], c["jours_3_plus"], c["jours_4_plus"]) == (7, 6, 0)


def test_part_des_jours_par_niveau(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    parts = [s[f"part_niveau_{n}"] for n in range(1, 6)]
    assert parts == pytest.approx([2 / 17, 5 / 17, 7 / 17, 3 / 17, 0.0], abs=1e-4)
    assert sum(parts) == pytest.approx(1.0, abs=1e-3)


def test_part_rapportee_aux_jours_avec_indice(con) -> None:
    """Un jour sans indice n'entre ni au numerateur ni au denominateur : il est
    publie a part, pour que la repartition se lise comme la moyenne."""
    s = _saison(con, OISANS, "2020-2021")
    assert (s["jours_couverts"], s["jours_avec_indice"], s["jours_sans_indice"]) == (3, 2, 1)
    assert s["part_niveau_2"] == pytest.approx(0.5)
    assert s["part_niveau_3"] == pytest.approx(0.5)


def test_moyenne_toujours_accompagnee_des_jours_couverts(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert s["risque_moyen"] == pytest.approx(45 / 17, abs=1e-3)
    assert s["jours_avec_indice"] == 17
    c = _saison(con, ASPE, "2024-2025", "coeur")
    assert c["risque_moyen"] == pytest.approx(20 / 7, abs=1e-3)
    assert c["jours_avec_indice"] == 7


def test_non_estime_avec_maxi_compte_dans_la_moyenne(con) -> None:
    """Le critere est `risque_maxi IS NOT NULL`, pas `risque_estime` : la ligne
    du 05/11/2023 (RISQUE1=-1, RISQUEMAXI=1) entre dans le calcul."""
    s = _saison(con, LUCHONNAIS, "2023-2024")
    assert (s["jours_avec_indice"], s["jours_non_estimes"], s["risque_moyen"]) == (1, 1, 1.0)


def test_mediane(con) -> None:
    assert _saison(con, ASPE, "2024-2025")["risque_median"] == 3
    assert _saison(con, OISANS, "2020-2021")["risque_median"] == pytest.approx(2.5)


# --- maximum, premiere et derniere occurrence --------------------------------

def test_maximum_saisonnier_et_sa_date(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert (s["risque_max"], s["date_max"], s["jours_au_max"]) == (4, date(2024, 12, 8), 3)


def test_premiere_et_derniere_occurrence_3(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert (s["premier_jour_3_plus"], s["dernier_jour_3_plus"]) == (
        date(2024, 12, 8), date(2024, 12, 22))


# --- duree de saison : reprise de `couverture` --------------------------------

def test_duree_de_saison_reprise_de_couverture(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    attendu = con.execute(
        "SELECT premier_jour, dernier_jour, jours_calendaires, jours_manquants "
        "FROM couverture WHERE massif_id = ? AND saison = ?", [ASPE, "2024-2025"]
    ).fetchone()
    assert (s["premier_jour"], s["dernier_jour"], s["jours_calendaires"],
            s["jours_manquants"]) == attendu == (date(2024, 12, 4), date(2024, 12, 22), 19, 2)


# --- episodes >= 3 ------------------------------------------------------------

def test_un_trou_rompt_un_episode(con) -> None:
    """15 -> 19 decembre a 3, trou le 20 : l'episode s'arrete au 19 et il est
    marque rompu, au lieu d'etre recolle au 3 du 22."""
    ep = risque.episodes(con, massifs=[ASPE], saisons=["2024-2025"])
    lignes = [(r["debut"], r["fin"], r["duree_jours"], r["rompu_par_trou"])
              for r in ep.sort("debut").iter_rows(named=True)]
    assert lignes == [
        (date(2024, 12, 8), date(2024, 12, 11), 4, False),
        (date(2024, 12, 15), date(2024, 12, 19), 5, True),
        (date(2024, 12, 22), date(2024, 12, 22), 1, False),
    ]


def test_episodes_rompus_publies_a_cote_du_compte(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert (s["episodes"], s["episodes_rompus_par_trou"]) == (3, 1)
    assert (s["duree_mediane_episode"], s["plus_long_episode"],
            s["plus_long_episode_debut"]) == (4, 5, date(2024, 12, 15))


def test_episode_borde_par_un_jour_sans_indice(con) -> None:
    """Un jour `RISQUE1=-1` n'est pas un trou d'archive, mais il ne dit pas non
    plus que l'episode s'arrete : il est compte a part."""
    s = _saison(con, OISANS, "2020-2021")
    assert (s["episodes"], s["episodes_rompus_par_trou"],
            s["episodes_bordes_sans_indice"]) == (1, 0, 1)


def test_episodes_restreints_a_la_fenetre(con) -> None:
    """En `coeur` (15/12 -> 15/04), l'episode du 8 au 11 decembre sort."""
    c = _saison(con, ASPE, "2024-2025", "coeur")
    assert (c["episodes"], c["episodes_rompus_par_trou"]) == (2, 1)


def test_episode_tronque_par_la_fenetre(con) -> None:
    """Aspe-Ossau, 14 -> 16 decembre 2023 a 3, apres un trou le 13 : `coeur`
    ouvre le 15. L'episode y garde deux jours, il est marque tronque, et le
    trou -- hors de la fenetre -- ne l'y rompt pas."""
    s = _saison(con, ASPE, "2023-2024")
    assert (s["episodes"], s["plus_long_episode"], s["episodes_tronques_par_fenetre"],
            s["episodes_rompus_par_trou"]) == (1, 3, 0, 1)
    c = _saison(con, ASPE, "2023-2024", "coeur")
    assert (c["episodes"], c["plus_long_episode"], c["episodes_tronques_par_fenetre"],
            c["episodes_rompus_par_trou"]) == (1, 2, 1, 0)


def test_saison_sans_episode(con) -> None:
    s = _saison(con, ASPE, "2018-2019")  # un seul jour, a 2
    assert s["episodes"] == 0
    assert s["episodes_rompus_par_trou"] == 0
    assert s["plus_long_episode"] is None


# --- variations ---------------------------------------------------------------

def test_variations_entre_jours_consecutifs_seulement(con) -> None:
    """5 -> 7 decembre (1 -> 2) et 19 -> 21 (3 -> 2) enjambent un trou : ce ne
    sont pas des variations en 24 h, et elles sont comptees a part."""
    s = _saison(con, ASPE, "2024-2025")
    assert (s["hausses_1_plus"], s["hausses_2_plus"]) == (3, 1)
    assert (s["baisses_1_plus"], s["baisses_2_plus"]) == (2, 0)
    assert (s["paires_consecutives"], s["paires_ecartees"]) == (14, 2)


def test_variation_au_jour(con) -> None:
    df = risque.serie_jour(con, massifs=[ASPE], saisons=["2024-2025"])
    var = dict(zip(df["jour_validite"].to_list(), df["variation"].to_list()))
    assert var[date(2024, 12, 8)] == 2
    assert var[date(2024, 12, 7)] is None   # veille absente : trou du 6
    assert var[date(2024, 12, 21)] is None  # veille absente : trou du 20
    assert var[date(2024, 12, 4)] is None   # premier jour de la saison


def test_variations_en_fenetre_exigent_les_deux_jours_dedans(con) -> None:
    """14 -> 15 decembre (2 -> 3) chevauche l'ouverture de `coeur` : la veille
    est hors fenetre, la paire n'y compte pas."""
    c = _saison(con, ASPE, "2024-2025", "coeur")
    assert (c["hausses_1_plus"], c["paires_consecutives"], c["paires_ecartees"]) == (1, 5, 1)


def test_variation_avec_un_jour_sans_indice(con) -> None:
    """29 -> 30 avril 2021 : le 30 est `RISQUE1=-1`, pas de variation."""
    s = _saison(con, OISANS, "2020-2021")
    assert (s["paires_consecutives"], s["paires_ecartees"]) == (1, 1)
    assert s["hausses_1_plus"] == 1


# --- ecart a la normale -------------------------------------------------------

def test_ecart_a_la_normale(con) -> None:
    """16 decembre, saisons comparables : 2, 3, 2, 2, 2, 3, 3, 3, 2 -> mediane 2.

    Le 3 de 2019-2020 n'y entre pas ; sinon la mediane de dix valeurs vaudrait 2,5.
    """
    df = risque.serie_jour(con, massifs=[ASPE])
    ligne = df.filter(df["jour_validite"] == date(2024, 12, 16)).row(0, named=True)
    assert (ligne["normale"], ligne["saisons_normale"], ligne["ecart_normale"]) == (2, 9, 1)


def test_pas_d_ecart_pour_une_saison_non_comparable(con) -> None:
    df = risque.serie_jour(con, massifs=[ASPE], saisons=["2019-2020"])
    ligne = df.row(0, named=True)
    assert ligne["ecart_normale"] is None
    assert ligne["saison_comparable"] is False
    assert ligne["motif_exclusion"]


def test_pas_d_ecart_hors_fenetre_coeur(con) -> None:
    df = risque.serie_jour(con, massifs=[ASPE], saisons=["2024-2025"])
    ligne = df.filter(df["jour_validite"] == date(2024, 12, 8)).row(0, named=True)
    assert (ligne["normale"], ligne["ecart_normale"]) == (None, None)


def test_pas_de_normale_sur_trop_peu_de_saisons(con) -> None:
    """Le 15 decembre n'est couvert que par deux saisons dans la serie : une
    normale aussi mince n'en est pas une, et au pire (une saison) elle serait
    la valeur du jour elle-meme."""
    df = risque.serie_jour(con, massifs=[ASPE], saisons=["2024-2025"])
    ligne = df.filter(df["jour_validite"] == date(2024, 12, 15)).row(0, named=True)
    assert ligne["saisons_normale"] == 2
    assert (ligne["normale"], ligne["ecart_normale"]) == (None, None)


def test_seuil_de_saisons_parametrable(tmp_path) -> None:
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(SERIES / "risque", out, db)
    c = duckdb.connect(str(db))
    try:
        risque.creer_vues(c, min_saisons_normale=1)
        df = risque.serie_jour(c, massifs=[ASPE], saisons=["2024-2025"])
        ligne = df.filter(df["jour_validite"] == date(2024, 12, 15)).row(0, named=True)
        assert (ligne["normale"], ligne["ecart_normale"]) == (3, 0)
    finally:
        c.close()


# --- second indice ------------------------------------------------------------

def test_second_indice(con) -> None:
    df = risque.second_indice(con, massifs=[ASPE], saisons=["2024-2025"])
    ligne = df.filter(df["jour_validite"] == date(2024, 12, 16)).row(0, named=True)
    assert (ligne["risque1"], ligne["risque2"], ligne["loc_type"],
            ligne["altitude_seuil_m"], ligne["risque_maxi"]) == (2, 3, "altitude", 1800, 3)
    simple = df.filter(df["jour_validite"] == date(2024, 12, 9)).row(0, named=True)
    assert (simple["risque1"], simple["risque2"], simple["loc_type"]) == (4, None, None)


# --- comparaisons inter-saisons -----------------------------------------------

@pytest.mark.parametrize("fenetre", ["commune", SAISON_COMPLETE])
def test_comparaison_refusee_hors_coeur(con, fenetre: str) -> None:
    with pytest.raises(risque.ComparaisonRefusee):
        risque.comparer_saisons(con, fenetre=fenetre)
    with pytest.raises(risque.ComparaisonRefusee):
        risque.moyenne_pluriannuelle(con, fenetre=fenetre)


def test_fenetre_inconnue(con) -> None:
    with pytest.raises(ValueError):
        risque.comparer_saisons(con, fenetre="hiver")


def test_comparaison_sur_coeur(con) -> None:
    """Toutes les saisons sont rendues, les non comparables etiquetees et non
    supprimees ; la moyenne vient avec ses jours."""
    df = risque.comparer_saisons(con, massifs=[ASPE])
    par_saison = {r["saison"]: r for r in df.iter_rows(named=True)}
    assert par_saison["2024-2025"]["jours_avec_indice"] == 7
    assert par_saison["2024-2025"]["risque_moyen"] == pytest.approx(20 / 7, abs=1e-3)
    assert par_saison["2024-2025"]["comparable"] is True
    assert par_saison["2019-2020"]["comparable"] is False
    assert par_saison["2019-2020"]["motif_exclusion"]


def test_moyenne_pluriannuelle_sur_les_saisons_comparables(con) -> None:
    """Metrique d'accueil (spec section 3.2) : coeur, saisons comparables seulement."""
    df = risque.moyenne_pluriannuelle(con, massifs=[ASPE])
    ligne = df.row(0, named=True)
    # 16/12 de 2016 a 2023 hors 2019 (7 jours), le 15/12/2023 (le 14 est hors
    # fenetre), les 7 jours de 2024-2025 et le 16/12/2025 : 16 jours, 2019-2020
    # exclu.
    assert ligne["saisons"] == 9
    assert ligne["jours_avec_indice"] == 16
    assert ligne["risque_moyen"] == pytest.approx(
        (2 + 3 + 2 + 2 + 2 + 3 + 3 + 3 + 20 + 2) / 16, abs=1e-3)
    assert ligne["jours_4_plus"] == 0
