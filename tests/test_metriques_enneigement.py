"""Bloc enneigement de la couche metriques (T7, spec section 5.2).

La serie `tests/series/enneigement/` est faite de bulletins reels. Seuls les
blocs etrangers a l'enneigement ont ete retires (images embarquees en base64,
blocs METEO, BSH/RISQUES, TENDANCES) ; en-tete, releves et neige fraiche sont
ceux de la source, octet pour octet.

- Aspe-Ossau, 27 janvier -> 11 fevrier 2025 (famille moderne). Deux trous
  d'archive reels : aucun bulletin redige les 3 et 4 fevrier. Deux
  reeditions reelles : le 9 fevrier (06:07 et 06:22, meme `DATEBULLETIN`,
  puis 17:00) et le 11 fevrier (16:00 puis 18:00). La journee de neige
  fraiche du 30 janvier est publiee 30/50 cm par le bulletin du 31, puis
  revisee a 25/30 cm par ceux du 1er, du 2 et du 5 fevrier.
- Aspe-Ossau, 2 -> 16 novembre 2017 (famille legacy, secteur unique
  `massif`). Les 2, 3 et 4 novembre portent `LimiteNord="-1"` sur un releve
  fait : pas d'enneigement continu. Le bulletin du 8 est **volontairement
  omis** : un trou d'un jour dans la periode d'enneigement continu. Les cumuls
  du 10 et du 11 valent `-2` (non observes).
- Haute-Bigorre, 20 et 21 janvier 2021 : deux secteurs nommes (Nord / Sud),
  dont certains `-2`.
- Chablais, 15 janvier de chaque saison 2016-2017 -> 2025-2026 : paliers
  1000/1500/2000 m (deux paliers dans la tranche basse) et base de l'ecart a
  la normale. 2019-2020 est non comparable.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import duckdb
import polars as pl
import pytest

from bra_analytics.build import build, iter_xml_files, parse_all, to_frames
from bra_analytics.fenetres import SAISON_COMPLETE
from bra_analytics.metriques import enneigement

from .conftest import SERIES

ASPE, BIGORRE, CHABLAIS = 65, 66, 1
SERIE = SERIES / "enneigement"
LOGGER = "bra_analytics.metriques.enneigement"


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("metriques_enneigement")
    db = tmp / "bra.duckdb"
    build(SERIE, tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def frames():
    return to_frames(parse_all(iter_xml_files(SERIE)))


def _jour(df: pl.DataFrame, jour: date, **filtres: object) -> dict:
    lignes = df.filter(pl.col("jour") == jour)
    for col, val in filtres.items():
        lignes = lignes.filter(pl.col(col) == val)
    assert lignes.height == 1, (jour, filtres, lignes)
    return lignes.row(0, named=True)


def _une(df: pl.DataFrame) -> dict:
    assert df.height == 1, df
    return df.row(0, named=True)


# --- vues ---------------------------------------------------------------------

def test_les_vues_existent_apres_le_build(con) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    assert set(enneigement.VUES) <= presentes


def test_vues_temporaires_sur_un_entrepot_en_lecture_seule(tmp_path) -> None:
    """Un entrepot construit avant T7 n'a pas les vues : les fonctions les posent
    en vues temporaires, sans ecrire dans la base ouverte en lecture seule."""
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(SERIE, out, db)
    c = duckdb.connect(str(db))
    for vue in reversed(enneigement.VUES):
        c.execute(f"DROP VIEW {vue}")
    c.close()

    c = duckdb.connect(str(db), read_only=True)
    try:
        assert enneigement.neige_fraiche(c, massifs=[ASPE], saisons=["2024-2025"]).height == 21
    finally:
        c.close()


def test_aucune_sortie_ne_presente_l_enneigement_comme_une_mesure(con) -> None:
    """L'enneigement du BRA est indicatif : aucune colonne des vues ne dit `mesure`
    (la table brute nomme `altitude_mesure_m` l'altitude de reference)."""
    for vue in enneigement.VUES:
        colonnes = [r[0] for r in con.execute(f"DESCRIBE {vue}").fetchall()]
        assert not [c for c in colonnes if "mesure" in c], vue


# --- neige fraiche : une redaction par jour -----------------------------------

def test_neige_fraiche_une_ligne_par_jour(con) -> None:
    df = enneigement.neige_fraiche(con)
    assert df.select("massif_id", "jour").is_duplicated().sum() == 0


def test_dedup_retient_la_redaction_la_plus_tardive(con) -> None:
    """Le 30 janvier 2025 : 30/50 cm dans le bulletin du 31, 25/30 dans ceux du
    1er, du 2 et du 5 fevrier. La redaction la plus tardive l'emporte."""
    df = enneigement.neige_fraiche(con, massifs=[ASPE], saisons=["2024-2025"])
    j = _jour(df, date(2025, 1, 30))
    assert (j["cumul_min_cm"], j["cumul_max_cm"]) == (25, 30)
    assert j["date_bulletin"] == datetime(2025, 2, 5, 16, 0)
    assert (j["redactions"], j["redactions_divergentes"]) == (4, True)


def test_le_journal_ecrit_chaque_ligne_ecartee(frames, caplog) -> None:
    """Une ligne de journal par ligne perdue : WARNING pour la valeur revisee,
    DEBUG pour les repetitions a l'identique."""
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        ecartees, divergentes = enneigement.log_neige_fraiche_discards(
            frames["neige_fraiche"], frames["bulletins"])
    traces = [r for r in caplog.records if r.getMessage().startswith("neige fraiche")]
    assert len(traces) == ecartees
    avert = [r.getMessage() for r in traces if r.levelno == logging.WARNING]
    assert divergentes == len(avert) == 1
    assert "massif=65 jour=2025-01-30" in avert[0]
    assert "cumul_max=50 retenu=30" in avert[0]
    assert "aspe_ossau_20250131164600.xml" in avert[0]


def test_journal_et_vue_s_accordent(con, frames) -> None:
    """Ce que la vue garde et ce que le journal ecarte partitionnent exactement
    les lignes historiques : le journal rejoue le tri de la vue."""
    nf = frames["neige_fraiche"].filter(pl.col("origine") == "historique")
    ecartees = enneigement.neige_fraiche_discards(frames["neige_fraiche"], frames["bulletins"])
    gardees = enneigement.neige_fraiche(con)
    assert ecartees.height + gardees.height == nf.height
    cle = ["massif_id", "date_bulletin", "jour"]
    assert ecartees.select(cle).join(gardees.select(cle), on=cle, how="inner").height == 0
    # Chaque jour ecarte a sa ligne retenue, et elle est plus tardive.
    retenues = gardees.select("massif_id", "jour", pl.col("date_bulletin").alias("retenue"))
    jointes = ecartees.join(retenues, on=["massif_id", "jour"], how="left")
    assert jointes["retenue"].null_count() == 0
    assert (jointes["retenue"] > jointes["date_bulletin"]).all()


def test_le_rapport_de_build_compte_les_lignes_ecartees(tmp_path) -> None:
    """Le total apparait dans `bra build`, pas seulement dans le journal."""
    rapport, _ = build(SERIE, tmp_path / "warehouse", None)
    assert (rapport.neige_fraiche_dropped, rapport.neige_fraiche_divergent) == (126, 1)
    assert rapport.enneigement_dropped == 6
    assert "neige fraiche historique ecartee : 126" in rapport.summary()


def test_bloc_historique_moderne_recale_d_un_jour(con) -> None:
    """Le BSH moderne date la fenetre de 24 h au lendemain du bloc principal.
    La date source reste lisible ; le jour est celui du bloc principal."""
    df = enneigement.neige_fraiche(con, massifs=[ASPE], saisons=["2024-2025"])
    j = _jour(df, date(2025, 1, 30))
    assert j["date_cumul_source"] == datetime(2025, 1, 31)


def test_bloc_historique_legacy_non_recale(con) -> None:
    df = enneigement.neige_fraiche(con, massifs=[BIGORRE])
    j = _jour(df, date(2021, 1, 15))
    assert j["date_cumul_source"] == datetime(2021, 1, 15)


def test_secteurs_et_non_observes_avant_2024(con) -> None:
    """Deux secteurs : bornes derivees. Un secteur a `-2` : non observe, l'autre
    fait les deux bornes. Les deux a `-2` : cumul nul, pas zero."""
    df = enneigement.neige_fraiche(con, massifs=[BIGORRE])
    deux = _jour(df, date(2021, 1, 15))
    assert (deux["secteur1_cumul_cm"], deux["secteur2_cumul_cm"]) == (5, 2)
    assert (deux["cumul_min_cm"], deux["cumul_max_cm"], deux["lecture_cumul"]) == (2, 5, "secteurs")
    un = _jour(df, date(2021, 1, 16))
    assert (un["secteur1_cumul_cm"], un["cumul_min_cm"], un["cumul_max_cm"]) == (None, 0, 0)
    aucun = _jour(df, date(2021, 1, 17))
    assert aucun["cumul_max_cm"] is None


def test_la_neige_fraiche_ne_lit_pas_la_prevision(con) -> None:
    """Le 11 fevrier 2025 n'est decrit que par le bloc de prevision : pas de ligne."""
    df = enneigement.neige_fraiche(con, massifs=[ASPE], saisons=["2024-2025"])
    assert df["jour"].max() == date(2025, 2, 10)


# --- neige fraiche : saison, episodes, cumul ----------------------------------

def test_neige_fraiche_saison(con) -> None:
    s = _une(enneigement.neige_fraiche_saison(con, massifs=[ASPE], saisons=["2024-2025"]))
    assert (s["tranche"], s["altitude_min_m"], s["altitude_max_m"]) == ("moyenne", 1800, 1800)
    assert (s["jours_couverts"], s["jours_observes"], s["jours_non_observes"]) == (21, 21, 0)
    assert s["cumul_max_cm"] == 114
    assert (s["seuil_chute_cm"], s["jours_chute"]) == (enneigement.SEUIL_CHUTE_CM, 3)
    assert (s["plus_forte_chute_cm"], s["date_plus_forte_chute"]) == (30, date(2025, 1, 30))
    assert (s["episodes_chute"], s["plus_long_episode"]) == (2, 2)
    assert (s["lecture_cumul"], s["rupture_de_serie"]) == ("fourchette", False)
    assert s["comparable"] is False  # saison entiere : bornes brutes


def test_cumul_minore_par_les_jours_non_observes(con) -> None:
    """Le 27 octobre, le 10 et le 11 novembre 2017 sont a `-2` : ils ne comptent
    pas zero, ils sont publies a part."""
    s = _une(enneigement.neige_fraiche_saison(con, massifs=[ASPE], saisons=["2017-2018"]))
    assert (s["jours_couverts"], s["jours_non_observes"], s["cumul_max_cm"]) == (20, 3, 70)
    assert s["lecture_cumul"] == "secteurs"


def test_episodes_de_chute_seuil_parametrable(con) -> None:
    """Seuil 5 cm, 2017 : 4-5 novembre ; 8-9 novembre, borde par le 10 non
    observe ; 12 novembre, borde par le 11 non observe."""
    ep = enneigement.episodes_chute(con, massifs=[ASPE], saisons=["2017-2018"], seuil_chute_cm=5)
    lignes = [(r["debut"], r["fin"], r["cumul_max_cm"], r["borde_non_observe"], r["rompu_par_trou"])
              for r in ep.sort("debut").iter_rows(named=True)]
    assert lignes == [
        (date(2017, 11, 4), date(2017, 11, 5), 30, False, False),
        (date(2017, 11, 8), date(2017, 11, 9), 35, True, False),
        (date(2017, 11, 12), date(2017, 11, 12), 5, True, False),
    ]


def test_episode_de_chute_sur_deux_jours(con) -> None:
    ep = enneigement.episodes_chute(con, massifs=[ASPE], saisons=["2024-2025"])
    premier = ep.sort("debut").row(0, named=True)
    assert (premier["debut"], premier["fin"], premier["duree_jours"],
            premier["cumul_max_cm"], premier["plus_forte_chute_cm"]) == (
        date(2025, 1, 30), date(2025, 1, 31), 2, 50, 30)


def test_cumul_sur_une_periode(con) -> None:
    df = enneigement.cumul_neige_fraiche(
        con, debut=date(2025, 1, 28), fin=date(2025, 2, 1), massifs=[ASPE])
    s = _une(df)
    assert (s["cumul_max_cm"], s["cumul_min_cm"], s["jours_couverts"]) == (82, 45, 5)
    assert s["lecture_cumul"] == "fourchette"


def test_cumul_refuse_d_enjamber_la_rupture_de_2023_2024(con) -> None:
    with pytest.raises(enneigement.RuptureDeSerie):
        enneigement.cumul_neige_fraiche(
            con, debut=date(2017, 11, 1), fin=date(2025, 2, 1), massifs=[ASPE])


# --- releve du jour : limite, indicateur, dedup -------------------------------

def test_limite_nulle_sans_enneigement_continu_n_est_pas_une_lacune(con) -> None:
    df = enneigement.releves(con, massifs=[ASPE], saisons=["2017-2018"])
    j = _jour(df, date(2017, 11, 3))
    assert (j["releve_fait"], j["limite_nord_m"], j["sans_enneigement_continu_nord"]) == (
        True, None, True)
    assert date(2017, 11, 8) not in df["jour"].to_list()


def test_releve_reedite_retient_la_redaction_la_plus_tardive(con) -> None:
    """11 fevrier 2025 : 16:00 puis 18:00. 8 fevrier : le bulletin du 9 a 06:00
    redonne le releve du 8, plus tard que celui du 8 a 17:00."""
    df = enneigement.releves(con, massifs=[ASPE], saisons=["2024-2025"])
    assert df.select("jour").is_duplicated().sum() == 0
    assert _jour(df, date(2025, 2, 11))["date_bulletin"] == datetime(2025, 2, 11, 18, 0)
    assert _jour(df, date(2025, 2, 8))["date_bulletin"] == datetime(2025, 2, 9, 6, 0)


def test_releves_ecartes_journalises_et_accordes(con, frames, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        perdues = enneigement.log_enneigement_discards(frames["enneigement"], frames["bulletins"])
    traces = [r.getMessage() for r in caplog.records if r.getMessage().startswith("enneigement")]
    assert perdues == len(traces) == 6  # deux releves de trois paliers
    assert any("jour=2025-02-11" in t and "aspe_ossau_20250211161300.xml" in t for t in traces)
    jour = frames["enneigement"].filter(pl.col("origine") == "jour").height
    gardees = con.execute(
        "SELECT sum(paliers) + count(*) FILTER (NOT releve_fait) FROM enneigement_jour"
    ).fetchone()[0]
    assert jour - perdues == gardees


# --- enneigement continu ------------------------------------------------------

def _continu(con, **kw) -> dict:
    df = enneigement.enneigement_continu(con, massifs=[ASPE], saisons=["2017-2018"], **kw)
    return df.filter(pl.col("versant") == "nord").row(0, named=True)


def test_date_d_enneigement_continu(con) -> None:
    """Sans enneigement continu du 2 au 4 novembre, limite sous 1800 m du 5 au
    16 ; le trou du 8 (un jour) ne rompt pas la periode, il est compte."""
    c = _continu(con)
    assert (c["debut_enneigement_continu"], c["fin_enneigement_continu"]) == (
        date(2017, 11, 5), date(2017, 11, 16))
    assert (c["duree_jours"], c["jours_observes_periode"], c["jours_non_observes_periode"]) == (12, 11, 1)
    # Les jours sans enneigement continu sont des jours observes, au-dessus.
    assert (c["jours_observes"], c["jours_sous_seuil_saison"]) == (14, 11)
    assert c["seuil_limite_m"] == enneigement.SEUIL_LIMITE_M == 1800


def test_un_trou_rompt_la_periode_si_on_ne_le_tolere_pas(con) -> None:
    c = _continu(con, trou_tolere_jours=0)
    assert (c["debut_enneigement_continu"], c["periodes"]) == (date(2017, 11, 9), 2)


def test_seuil_de_limite_parametrable(con) -> None:
    """Seuil 1500 m : le 5 (1700 m) est au-dessus, le 15 (1600 m) aussi."""
    c = _continu(con, seuil_limite_m=1500)
    assert (c["debut_enneigement_continu"], c["fin_enneigement_continu"]) == (
        date(2017, 11, 6), date(2017, 11, 14))


# --- epaisseur par palier et par tranche --------------------------------------

def test_palier_retenu_le_plus_haut_de_sa_tranche(con) -> None:
    df = enneigement.paliers(con, massifs=[CHABLAIS], saisons=["2024-2025"])
    basse = df.filter(pl.col("tranche") == "basse").sort("altitude_m")
    assert basse["altitude_m"].to_list() == [1000, 1500]
    assert basse["palier_retenu"].to_list() == [False, True]
    assert basse["paliers_dans_tranche"].to_list() == [2, 2]
    assert df.filter(pl.col("tranche") == "haute").height == 0  # rien d'interpole


def test_ecart_a_la_normale_par_palier(con) -> None:
    """1500 m nord, 15 janvier, saisons comparables : 85, 100, 80, 120, 90, 15,
    70, 50, 70 -> mediane 80. Le 70 de 2019-2020 n'y entre pas."""
    df = enneigement.paliers(con, massifs=[CHABLAIS])
    j = _jour(df, date(2025, 1, 15), altitude_m=1500)
    assert (j["normale_nord_cm"], j["saisons_normale_nord"], j["ecart_normale_nord_cm"]) == (80, 9, -30)
    # Normale du palier, pas de la tranche : 1000 m a la sienne.
    assert _jour(df, date(2025, 1, 15), altitude_m=1000)["normale_nord_cm"] == 10


def test_pas_d_ecart_pour_une_saison_non_comparable(con) -> None:
    df = enneigement.paliers(con, massifs=[CHABLAIS], saisons=["2019-2020"])
    j = _jour(df, date(2020, 1, 15), altitude_m=1500)
    assert (j["normale_nord_cm"], j["ecart_normale_nord_cm"], j["saison_comparable"]) == (80, None, False)
    assert j["motif_exclusion"]


def test_pas_de_normale_sur_trop_peu_de_saisons(con) -> None:
    """Aspe-Ossau n'a qu'une saison au 30 janvier dans la serie."""
    df = enneigement.paliers(con, massifs=[ASPE], saisons=["2024-2025"])
    j = _jour(df, date(2025, 1, 30), altitude_m=1500)
    assert (j["saisons_normale_nord"], j["normale_nord_cm"], j["ecart_normale_nord_cm"]) == (1, None, None)


def test_seuil_de_saisons_parametrable(tmp_path) -> None:
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(SERIE, out, db)
    c = duckdb.connect(str(db))
    try:
        enneigement.creer_vues(c, min_saisons_normale=10)
        df = enneigement.paliers(c, massifs=[CHABLAIS], saisons=["2024-2025"])
        assert _jour(df, date(2025, 1, 15), altitude_m=1500)["normale_nord_cm"] is None
    finally:
        c.close()


def test_epaisseur_par_tranche_sur_la_saison(con) -> None:
    df = enneigement.metriques_saison(con, massifs=[ASPE], saisons=["2024-2025"])
    basse = _une(df.filter(pl.col("tranche") == "basse"))
    assert (basse["altitude_min_m"], basse["jours_releves"]) == (1500, 14)
    assert (basse["seuil_epaisseur_cm"], basse["jours_enneiges_nord"],
            basse["jours_enneiges_sud"]) == (1, 12, 11)
    assert (basse["epaisseur_max_nord_cm"], basse["date_max_nord"]) == (45, date(2025, 2, 1))
    haute = _une(df.filter(pl.col("tranche") == "haute"))
    assert (haute["epaisseur_max_nord_cm"], haute["date_max_nord"], haute["jours_au_max_nord"]) == (
        200, date(2025, 2, 8), 1)
    # Couverture : 14 releves sur un span de 16 jours (trous des 3 et 4 fevrier).
    assert (basse["jours_periode"], basse["couverture_pct"]) == (16, 87.5)


def test_seuil_d_epaisseur_parametrable(con) -> None:
    df = enneigement.metriques_saison(
        con, massifs=[ASPE], saisons=["2024-2025"], tranches=["basse"], seuil_epaisseur_cm=30)
    assert _une(df)["jours_enneiges_nord"] == 6


def test_fenetre_et_comparabilite(con) -> None:
    coeur = enneigement.metriques_saison(con, fenetre="coeur", massifs=[CHABLAIS])
    par_saison = {r["saison"]: r for r in coeur.filter(pl.col("tranche") == "basse").iter_rows(named=True)}
    assert par_saison["2024-2025"]["comparable"] is True
    assert par_saison["2024-2025"]["jours_periode"] == 122
    assert par_saison["2019-2020"]["comparable"] is False
    assert par_saison["2019-2020"]["motif_exclusion"]
    with pytest.raises(ValueError):
        enneigement.metriques_saison(con, fenetre="hiver")
    entiere = enneigement.metriques_saison(con, fenetre=SAISON_COMPLETE, massifs=[CHABLAIS])
    assert not entiere["comparable"].any()
