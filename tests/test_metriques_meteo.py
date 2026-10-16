"""Bloc meteo de la couche metriques (T8, spec section 5.3).

La serie `tests/series/meteo/` est faite de bulletins reels, reduits a leur
en-tete, leur cartouche de risque et leur bloc meteo :

- Aspe-Ossau, 4 -> 28 decembre 2024 (jours couverts), format moderne :
  echeances 06/12/18 h de J et 00 h de J+1. Deux trous d'archive reels, le 6
  et le 20 decembre. Isotherme 0 degC du jour (06 h / 12 h) :

      jour  04   05   07   08   ..  16   17   18   19   21  ..  25   26   27
      06 h  1500 2800 2800 1300 ..  3500 3800 3200 3400 1500 .. 3600 3500 3000
      12 h  1500 2700 1800 1200 ..  3700 3700 3300 2600 1800 .. 3500 3500 2900

- Aspe-Ossau, 10 et 11 janvier 2023, format ancien : echeances 00/06/12 h de J.
  L'echeance de 00 h porte 1600 m puis 3100 m, hors de la valeur du jour.
- Aspe-Ossau, 6 decembre 2023, couvert par deux bulletins reels : redige le 5
  a 16 h (echeance de 12 h vide) et a 18 h. `risque_journalier` retient 18 h.
- Cinto Rotondo, 6 avril 2026 : deux diffusions sous le meme DATEBULLETIN,
  dont la seconde deplace l'echeance d'un jour (correctif de `to_frames`).
- Queyras, 10 janvier 2023 (`ALTITUDEVENT1="3000" ALTITUDEVENT2="9999"`, un
  seul vent) et 23 decembre 2024 (2000 et 3000 m).
- Haute-Tarentaise, 23 decembre 2024 : vents a 3000 et 4000 m, deux altitudes
  dans la tranche haute.
- Champsaur, 23 decembre 2024 : `FF1="400"` a 18 h, hors de la valeur du jour.

Seuls les blocs etrangers a la meteo et au risque ont ete retires.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime

import duckdb
import polars as pl
import pytest

from bra_analytics.build import build
from bra_analytics.metriques import meteo

from .conftest import SERIES

ASPE, QUEYRAS, CHAMPSAUR, TARENTAISE, CINTO = 65, 17, 19, 6, 40


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("metriques_meteo")
    db = tmp / "bra.duckdb"
    build(SERIES / "meteo", tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


def _jour(con, massif: int, jour: date) -> dict:
    df = meteo.serie_jour(con, massifs=[massif]).filter(
        pl.col("jour_validite") == jour
    )
    assert df.height == 1, (massif, jour)
    return df.row(0, named=True)


def _vents(con, massif: int, jour: date) -> dict[int, dict]:
    df = meteo.vent_jour(con, massifs=[massif])
    return {r["altitude_m"]: r for r in df.iter_rows(named=True) if r["jour_validite"] == jour}


def _saison(con, massif: int, saison: str, fenetre: str = "saison_complete", **seuils) -> dict:
    df = meteo.metriques_saison(con, fenetre=fenetre, massifs=[massif], saisons=[saison], **seuils)
    assert df.height == 1
    return df.row(0, named=True)


# --- vues ---------------------------------------------------------------------

def test_les_vues_existent_apres_le_build(con) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    assert set(meteo.VUES) <= presentes


def test_vues_temporaires_sur_un_entrepot_en_lecture_seule(tmp_path) -> None:
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(SERIES / "meteo", out, db)
    c = duckdb.connect(str(db))
    for vue in meteo.VUES:
        c.execute(f"DROP VIEW {vue}")
    c.close()
    c = duckdb.connect(str(db), read_only=True)
    try:
        assert _saison(c, ASPE, "2024-2025")["jours_couverts"] == 23
    finally:
        c.close()


def test_toute_sortie_se_dit_prevision(con) -> None:
    """Le bloc meteo est une prevision : chaque vue le porte, ligne a ligne."""
    for vue in meteo.VUES:
        origines = {r[0] for r in con.execute(f"SELECT DISTINCT origine FROM {vue}").fetchall()}
        assert origines == {"prevision"}, vue


# --- convention d'extraction ----------------------------------------------------

def test_meme_definition_du_jour_dans_les_deux_epoques(con) -> None:
    """06 h et 12 h seulement : le 00 h de J (ancien format), le 18 h de J et le
    00 h de J+1 (format moderne) n'entrent pas dans la valeur du jour."""
    ancien = _jour(con, ASPE, date(2023, 1, 11))  # 00 h a 3100 m, ignore
    assert ancien["format_famille"] == "legacy"
    assert (ancien["iso0_06h_m"], ancien["iso0_12h_m"]) == (1900, 1600)
    assert (ancien["iso0_min_m"], ancien["iso0_max_m"]) == (1600, 1900)
    assert ancien["echeances_jour"] == 2

    moderne = _jour(con, ASPE, date(2024, 12, 19))  # 18 h a 1800 m, ignore
    assert moderne["format_famille"] == "moderne"
    assert (moderne["iso0_min_m"], moderne["iso0_max_m"]) == (2600, 3400)
    assert moderne["echeances_jour"] == 2
    # Limite pluie-neige : 2500 et 2100 m ; le 1500 m de 18 h n'entre pas.
    assert moderne["limite_pluie_neige_min_m"] == 2100


def test_jour_couvert_par_deux_bulletins_lu_dans_celui_du_risque(con) -> None:
    """Le 06/12/2023 est couvert par les redactions de 16 h et 18 h : la meteo
    vient de celle que `risque_journalier` retient, pas d'un autre arbitrage."""
    j = _jour(con, ASPE, date(2023, 12, 6))
    assert j["date_bulletin"] == datetime(2023, 12, 5, 18, 0)
    assert (j["iso0_06h_m"], j["iso0_12h_m"]) == (1800, 2200)  # 16 h : 2300 / vide

    ecarts = con.execute("""
        SELECT count(*) FROM meteo_jour m
        FULL JOIN (SELECT * FROM risque_journalier WHERE massif_coherent) r
          USING (massif_id, jour_validite)
        WHERE m.date_bulletin IS DISTINCT FROM r.date_bulletin
    """).fetchone()[0]
    assert ecarts == 0


def test_tables_filles_de_la_version_retenue(con) -> None:
    """Cinto Rotondo, 06/04/2026 : la reedition retenue prevoit le 6 ; la meteo
    du jour existe (avant le correctif de `to_frames`, elle portait le 7)."""
    j = _jour(con, CINTO, date(2026, 4, 6))
    assert j["motif_lacune"] is None
    assert (j["iso0_06h_m"], j["iso0_12h_m"]) == (3100, 3100)


def test_un_jour_sans_valeur_reste_etiquete(con) -> None:
    """Aucun jour couvert n'est retire : meme nombre de lignes que
    `risque_journalier`, une lacune portant son motif."""
    n_meteo = con.execute("SELECT count(*) FROM meteo_jour").fetchone()[0]
    n_risque = con.execute(
        "SELECT count(*) FROM risque_journalier WHERE massif_coherent"
    ).fetchone()[0]
    assert n_meteo == n_risque


# --- isotherme : variations ------------------------------------------------------

def test_variation_en_24h_jamais_par_dessus_un_trou(con) -> None:
    assert _jour(con, ASPE, date(2024, 12, 5))["variation_iso0_24h_m"] == pytest.approx(2750 - 1500)
    assert _jour(con, ASPE, date(2024, 12, 7))["variation_iso0_24h_m"] is None   # le 6 manque
    assert _jour(con, ASPE, date(2024, 12, 21))["variation_iso0_24h_m"] is None  # le 20 manque
    s = _saison(con, ASPE, "2024-2025")
    assert (s["paires_consecutives_iso0"], s["paires_ecartees_iso0"]) == (20, 2)


def test_iso0_saison_avec_ses_jours(con) -> None:
    s = _saison(con, ASPE, "2024-2025")
    assert (s["jours_couverts"], s["jours_avec_iso0"]) == (23, 23)
    assert (s["iso0_min_m"], s["date_iso0_min"]) == (700, date(2024, 12, 10))
    assert (s["iso0_max_m"], s["date_iso0_max"]) == (3800, date(2024, 12, 17))


def test_jours_iso0_au_dessus_du_seuil_parametrable(con) -> None:
    """Un jour compte si l'isotherme depasse le seuil a 06 h *et* a 12 h : le
    19/12 (3400 puis 2600 m) n'est pas un jour de redoux a 3400 m."""
    s = _saison(con, ASPE, "2024-2025")
    assert (s["seuil_iso0_m"], s["jours_iso0_au_dessus_seuil"]) == (3400, 4)
    s = _saison(con, ASPE, "2024-2025", seuil_iso0_m=3000)
    assert (s["seuil_iso0_m"], s["jours_iso0_au_dessus_seuil"]) == (3000, 5)


def test_seuil_invalide_refuse(con) -> None:
    with pytest.raises(ValueError):
        meteo.metriques_saison(con, seuil_iso0_m=0)
    with pytest.raises(ValueError):
        meteo.vent_saison(con, seuil_vent_fort_kmh="70")  # type: ignore[arg-type]


# --- redoux ------------------------------------------------------------------------

def test_episode_de_redoux_avec_le_risque_avant_et_apres(con) -> None:
    df = meteo.episodes_redoux(con, massifs=[ASPE])
    eps = [(r["debut"], r["fin"], r["risque_veille"], r["risque_max_pendant"],
            r["risque_lendemain"], r["franchissement_observe"], r["rompu_par_trou"])
           for r in df.iter_rows(named=True)]
    assert eps == [
        (date(2024, 12, 16), date(2024, 12, 17), 3, 3, 3, True, False),
        (date(2024, 12, 25), date(2024, 12, 26), 3, 2, 2, True, False),
    ]


def test_episode_de_redoux_rompu_par_un_trou(con) -> None:
    """Seuil 1700 m : le 5 et le 7 decembre sont au-dessus, le 6 manque. Deux
    suites, chacune rompue par le trou, jamais recollees en une."""
    df = meteo.episodes_redoux(
        con, massifs=[ASPE], saisons=["2024-2025"], seuil_iso0_m=1700,
        duree_min_redoux_jours=1,
    ).filter(pl.col("debut") < date(2024, 12, 10))
    assert [(r["debut"], r["fin"], r["rompu_par_trou"]) for r in df.iter_rows(named=True)] == [
        (date(2024, 12, 5), date(2024, 12, 5), True),
        (date(2024, 12, 7), date(2024, 12, 7), True),
    ]


def test_suite_trop_courte_etiquetee_et_non_comptee(con) -> None:
    df = meteo.episodes_redoux(con, massifs=[ASPE], duree_min_redoux_jours=3,
                               retenus_seulement=False)
    assert df.height == 2 and not any(df["retenu"].to_list())
    assert _saison(con, ASPE, "2024-2025", duree_min_redoux_jours=3)["episodes_redoux"] == 0
    assert _saison(con, ASPE, "2024-2025")["episodes_redoux"] == 2


# --- vent ----------------------------------------------------------------------------

def test_vent_unique_des_alpes_du_sud_en_tranche_haute_aux_deux_epoques(con) -> None:
    """Queyras : un seul vent, a 3000 m, dans la colonne basse en 2023 ; deux
    vents, dont 3000 m dans la colonne haute, en 2024. Le vent a 3000 m reste
    en tranche haute, quelle que soit sa colonne."""
    v2023 = _vents(con, QUEYRAS, date(2023, 1, 10))
    assert list(v2023) == [3000]
    assert (v2023[3000]["tranche"], v2023[3000]["vitesse_max_kmh"]) == ("haute", 80)

    v2024 = _vents(con, QUEYRAS, date(2024, 12, 23))
    assert {a: r["tranche"] for a, r in v2024.items()} == {2000: "moyenne", 3000: "haute"}
    assert v2024[3000]["vitesse_max_kmh"] == 90


def test_deux_altitudes_dans_la_meme_tranche(con) -> None:
    df = meteo.vent_saison(con, massifs=[TARENTAISE], tranches=["haute"])
    s = df.row(0, named=True)
    assert s["altitudes_vent"] == "3000/4000"
    assert s["vitesse_max_kmh"] == 110  # la plus forte des deux altitudes


def test_jours_de_vent_fort_strictement_au_dessus_du_seuil(con) -> None:
    """Les 9 et 14 decembre plafonnent a 70 km/h pile en tranche haute : ils ne
    comptent pas au seuil par defaut."""
    haute = meteo.vent_saison(con, massifs=[ASPE], saisons=["2024-2025"], tranches=["haute"])
    assert haute.row(0, named=True)["jours_vent_fort"] == 6
    haute = meteo.vent_saison(con, massifs=[ASPE], saisons=["2024-2025"], tranches=["haute"],
                              seuil_vent_fort_kmh=100)
    assert haute.row(0, named=True)["jours_vent_fort"] == 3


def test_vent_hors_plage_a_18h_hors_de_la_valeur_du_jour(con) -> None:
    v = _vents(con, CHAMPSAUR, date(2024, 12, 23))
    assert v[2000]["vitesse_max_kmh"] == 45
    assert v[2000]["vitesses_hors_plage"] == 0


def test_vent_hors_plage_exclu_et_compte(tmp_path) -> None:
    """Aucune prevision reelle ne porte de vent hors plage a 06 h ou 12 h : on
    reprend le bulletin Champsaur reel et on y deplace a 06 h l'erreur que la
    source porte a 18 h (`FF1="400"`)."""
    src = tmp_path / "src"
    src.mkdir()
    texte = (SERIES / "meteo" / "champsaur_20241222161300.xml").read_text(encoding="utf-8")
    origine = 'DATE="2024-12-23T06:00:00" FF1="45"'
    assert origine in texte
    (src / "champsaur_20241222161300.xml").write_text(
        texte.replace(origine, 'DATE="2024-12-23T06:00:00" FF1="400"'), encoding="utf-8"
    )
    db = tmp_path / "bra.duckdb"
    build(src, tmp_path / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    try:
        v = _vents(c, CHAMPSAUR, date(2024, 12, 23))[2000]
        assert v["vitesse_06h_kmh"] is None
        assert v["vitesses_hors_plage"] == 1
        assert v["vitesse_max_kmh"] is None
        s = meteo.vent_saison(c, massifs=[CHAMPSAUR], tranches=["moyenne"]).row(0, named=True)
        assert (s["jours_vent_fort"], s["jours_avec_vent"], s["vitesses_hors_plage"]) == (0, 0, 1)
    finally:
        c.close()


def test_tranche_inconnue_refusee(con) -> None:
    with pytest.raises(ValueError):
        meteo.vent_jour(con, tranches=["sommet"])


# --- temps sensible ------------------------------------------------------------------

def test_repartition_des_codes_avec_libelles(con) -> None:
    df = meteo.temps_sensible(con, massifs=[ASPE], saisons=["2024-2025"])
    assert df["part"].sum() == pytest.approx(1.0, abs=1e-3)
    assert df["echeances"].sum() == 46  # deux echeances par jour couvert
    par_code = {r["temps_sensible"]: r for r in df.iter_rows(named=True)}
    assert par_code[80]["temps_sensible_libelle"] == "averses de neige"


def test_code_hors_palette_compte_sans_libelle(con) -> None:
    df = meteo.temps_sensible(con, massifs=[ASPE], saisons=["2022-2023"])
    par_code = {r["temps_sensible"]: r for r in df.iter_rows(named=True)}
    assert set(par_code) == {5, 10}
    assert not par_code[5]["dans_palette"] and par_code[5]["temps_sensible_libelle"] is None
    assert par_code[5]["echeances"] == 2


# --- portees -----------------------------------------------------------------------

def test_fenetre_coeur_ne_compte_que_les_paires_interieures(con) -> None:
    """`coeur` ouvre le 15 decembre : la variation du 14 au 15 n'y entre pas."""
    c = _saison(con, ASPE, "2024-2025", fenetre="coeur")
    assert c["jours_couverts"] == 13  # 15 -> 28 decembre, sauf le 20
    assert (c["paires_consecutives_iso0"], c["paires_ecartees_iso0"]) == (11, 1)
    assert c["comparable"] is True


def test_vent_du_jour_par_tranche_retient_le_plus_fort(con) -> None:
    """Haute-Tarentaise, prevision du 23/12/2024 : deux vents en tranche haute,
    3000 m (`FF1` 75 puis 95 km/h) et 4000 m (`FF2` 95 puis 110 km/h, `DD2="N"`
    a 12 h). La tranche porte le plus fort, sa direction, et les altitudes
    qu'elle reunit ; la regle est ecrite une fois, ici, et non dans l'ecran."""
    df = meteo.vent_tranche_jour(con, massifs=[6], tranches=["haute"])
    (ligne,) = df.filter(df["jour_validite"] == date(2024, 12, 23)).rows(named=True)
    assert ligne["vitesse_kmh"] == 110
    assert ligne["direction"] == "N"
    assert ligne["altitudes_vent"] == "3000/4000"
    assert ligne["origine"] == "prevision"
