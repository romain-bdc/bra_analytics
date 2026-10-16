"""Bloc rose des pentes et situations typiques (T9, spec section 5.4).

Serie `tests/series/transport/` : Aspe-Ossau, neuf jours couverts de
decembre 2024 (2, 3, 4, 5, 7, 8, 9, 10 et 11 ; trou d'archive le 6), bulletins
reels. Roses relues a la main dans le XML :

    jour   2  3  4  5  7  8  9  10 11
    risque 1  1  1  1  2  4  4  4  3
    roses  NE,N (jours 2-5) ; NE,E,SE,N (7) ; les huit secteurs (8 a 11)
    sat1   6  6  6  6  2  2  1  1  2
    sat2   -  -  -  -  -  1  -  2  1

Serie `tests/series/risque/` : Aspe-Ossau 2016 a 2025, reduite au cartouche de
risque (ni `SitAvalTyp` ni vent) ; le 12 decembre 2023 y a une rose vide a
risque 1.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from bra_analytics.build import build
from bra_analytics.metriques import pentes

from .conftest import SERIES

ASPE = 65


def _con(tmp_path_factory, serie: str):
    tmp = tmp_path_factory.mktemp(f"pentes_{serie}")
    db = tmp / "bra.duckdb"
    build(SERIES / serie, tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    return c


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    c = _con(tmp_path_factory, "transport")
    yield c
    c.close()


@pytest.fixture(scope="module")
def con_risque(tmp_path_factory):
    c = _con(tmp_path_factory, "risque")
    yield c
    c.close()


def _rose(con) -> dict[str, dict]:
    df = pentes.rose_saison(con, massifs=[ASPE], saisons=["2024-2025"])
    return {r["orientation"]: r for r in df.iter_rows(named=True)}


def test_les_vues_existent_apres_le_build(con) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    assert set(pentes.VUES) | {pentes.VUE_VENT} <= presentes


# --- frequence d'exposition --------------------------------------------------

def test_frequence_d_exposition_par_secteur(con) -> None:
    rose = _rose(con)
    assert list(rose) == list(pentes.ORIENTATIONS)  # ordre de lecture de la rose
    assert {s: rose[s]["jours_signales"] for s in rose} == {
        "N": 9, "NE": 9, "E": 5, "SE": 5, "S": 4, "SW": 4, "W": 4, "NW": 4,
    }
    assert all(r["jours_couverts"] == 9 for r in rose.values())  # le trou du 6 n'est pas un jour
    assert rose["E"]["frequence"] == pytest.approx(5 / 9)


def test_frequence_ponderee_sur_les_jours_a_risque_eleve(con) -> None:
    rose = _rose(con)["S"]
    # Jours >= 3 : 8, 9, 10, 11 ; jours >= 4 : 8, 9, 10. Les huit secteurs y sont signales.
    assert (rose["jours_ge3"], rose["jours_signales_ge3"], rose["frequence_ge3"]) == (4, 4, 1.0)
    assert (rose["jours_ge4"], rose["jours_signales_ge4"], rose["frequence_ge4"]) == (3, 3, 1.0)


def test_frequence_ponderee_nulle_sans_jour_de_ce_niveau(con_risque) -> None:
    # Aspe 2016-2017 : un seul jour couvert, a risque 2 -> aucun jour >= 3, donc pas de 0/0 rendu en 0 %.
    df = pentes.rose_saison(con_risque, massifs=[ASPE], saisons=["2016-2017"], orientations=["N"])
    r = df.row(0, named=True)
    assert (r["jours_ge3"], r["frequence_ge3"], r["jours_ge4"], r["frequence_ge4"]) == (0, None, 0, None)
    assert r["frequence"] == 1.0


# --- secteur dominant, concentration ----------------------------------------

def test_secteur_dominant_et_ex_aequo(con) -> None:
    r = pentes.resume_saison(con, massifs=[ASPE]).row(0, named=True)
    # N et NE sont signales les neuf jours : premier dans l'ordre de lecture, deux ex aequo.
    assert (r["secteur_dominant"], r["secteurs_ex_aequo"], r["jours_secteur_dominant"]) == ("N", 2, 9)


def test_concentration_est_accompagnee_de_ses_jours(con) -> None:
    r = pentes.resume_saison(con, massifs=[ASPE]).row(0, named=True)
    assert r["jours_couverts"] == 9
    assert r["secteurs_moyens"] == pytest.approx((4 * 2 + 4 + 4 * 8) / 9)
    assert (r["jours_ge3"], r["secteurs_moyens_ge3"]) == (4, 8.0)


def test_rose_vide_comptee_pas_ecartee(con_risque) -> None:
    df = pentes.resume_saison(con_risque, massifs=[ASPE], saisons=["2023-2024"])
    r = df.row(0, named=True)
    # 12 decembre 2023 : rose vide a risque 1 ; les trois autres jours ont des secteurs.
    assert (r["jours_couverts"], r["jours_sans_secteur"], r["rose_vide_risque_ge2"]) == (4, 1, 0)


# --- saisonnalite ------------------------------------------------------------

def test_saisonnalite_publie_saisons_et_jours(con) -> None:
    df = pentes.saisonnalite(con, massifs=[ASPE], orientations=["E"])
    r = df.row(0, named=True)
    assert (r["mois"], r["nb_saisons"], r["jours_couverts"], r["jours_signales"]) == (12, 1, 9, 5)


# --- croisement vent x orientation ------------------------------------------

def test_croisement_vent_se_ventile_par_tranche_et_direction(con) -> None:
    df = pentes.croisement_vent(con, massifs=[ASPE], tranches=["haute"])
    lignes = {r["direction_vent"]: r for r in df.iter_rows(named=True)}
    # Vent de N en tranche haute : 5, 9 et 10 decembre. La pente chargee est S,
    # signalee les 9 et 10 seulement. Vent de NW : 3, 7 et 8 -> pente SE, signalee les 7 et 8.
    assert (lignes["N"]["jours_vent"], lignes["N"]["jours_pente_chargee_signalee"]) == (3, 2)
    assert (lignes["NW"]["jours_vent"], lignes["NW"]["jours_pente_chargee_signalee"]) == (3, 2)
    assert lignes["N"]["altitudes_vent"] == "3000"
    assert {r["tranche"] for r in df.iter_rows(named=True)} == {"haute"}


def test_croisement_vent_ecarte_les_directions_variables(con) -> None:
    df = pentes.croisement_vent(con, massifs=[ASPE])
    assert "VRB" not in set(df["direction_vent"])  # le 2 decembre, vent bas variable : aucune pente chargee


def test_croisement_refuse_une_tranche_inconnue(con) -> None:
    with pytest.raises(ValueError, match="tranches inconnues"):
        pentes.croisement_vent(con, tranches=["stratosphere"])


# --- situations typiques -----------------------------------------------------

def test_situations_comptees_par_rang_et_code(con) -> None:
    df = pentes.situations(con, massifs=[ASPE])
    comptes = {(r["rang"], r["code"]): r["jours"] for r in df.iter_rows(named=True)}
    assert comptes == {(1, 1): 2, (1, 2): 3, (1, 6): 4, (2, 1): 2, (2, 2): 1}
    assert set(df["jours_couverts"]) == {9}  # sat2 absent n'ote pas de jour au denominateur
    assert set(df["restriction"]) == {"depuis la saison 2024-2025"}


def test_situations_traduites_par_leurs_libelles_du_glossaire(con) -> None:
    df = pentes.situations(con, massifs=[ASPE])
    libelles = {r["code"]: r["libelle"] for r in df.iter_rows(named=True)}
    assert libelles == {1: "Neige fraîche", 2: "Neige soufflée / plaques à vent", 6: "Manteau insuffisant"}
    assert set(df["libelle_source"]) == {"inferee (glossaire 2.7)"}


def test_le_code_6_n_est_pas_une_situation_typique(con) -> None:
    df = pentes.situations(con, massifs=[ASPE])
    assert {r["code"]: r["est_situation_typique"] for r in df.iter_rows(named=True)} == {
        1: True, 2: True, 6: False,
    }


def test_pas_de_situation_sur_une_saison_qui_n_en_porte_pas(con_risque) -> None:
    # La serie `risque` n'a plus de `SitAvalTyp` : aucune ligne, pas des lignes nulles.
    df = pentes.situations(con_risque, massifs=[ASPE])
    assert df.height == 0


# --- arguments ---------------------------------------------------------------

def test_orientation_inconnue_refusee(con) -> None:
    with pytest.raises(ValueError, match="orientations inconnues"):
        pentes.rose_saison(con, orientations=["NNE"])


def test_fenetre_inconnue_refusee(con) -> None:
    with pytest.raises(ValueError, match="fenetre inconnue"):
        pentes.rose_saison(con, fenetre="hiver")


def test_la_fenetre_coeur_ecarte_les_jours_qui_lui_sont_anterieurs(con) -> None:
    # Les neuf jours du 2 au 11 decembre precedent le 15 decembre, debut de `coeur`.
    assert pentes.resume_saison(con, fenetre="coeur", massifs=[ASPE]).height == 0
    assert pentes.rose_saison(con, fenetre="coeur", massifs=[ASPE]).height == 0


def test_les_frames_gardent_leur_schema_sans_ligne(con_risque) -> None:
    df = pentes.situations(con_risque, massifs=[ASPE])
    assert isinstance(df, pl.DataFrame) and "code" in df.columns
