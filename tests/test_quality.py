"""Controles de coherence."""

import polars as pl

from bra_analytics.build import to_frames
from bra_analytics.parser import parse_file
from bra_analytics.quality import Anomalie, check_bulletins, check_filles, coverage_gaps, report

from .conftest import bulletins_valides, fixture


def all_bulletins() -> pl.DataFrame:
    """Bulletins reguliers : les cas aberrants ont leurs tests dedies."""
    parsed = [p for f in bulletins_valides() for p in parse_file(f)]
    return to_frames(parsed)["bulletins"]


def test_aucune_erreur_sur_les_fixtures() -> None:
    erreurs = [a for a in check_bulletins(all_bulletins()) if a.gravite == "erreur"]
    assert erreurs == [], [str(a) for a in erreurs]


def test_amendement_signale() -> None:
    signaux = {a.controle: a for a in check_bulletins(all_bulletins()) if a.gravite == "signal"}
    assert signaux["amendement"].lignes == 1


def test_risque_hors_echelle_detecte() -> None:
    df = all_bulletins().with_columns(risque1=pl.lit(7, dtype=pl.Int8))
    controles = {a.controle for a in check_bulletins(df) if a.gravite == "erreur"}
    assert "risque1_hors_echelle" in controles


def test_cle_dupliquee_detectee() -> None:
    df = all_bulletins()
    controles = {a.controle for a in check_bulletins(pl.concat([df, df])) if a.gravite == "erreur"}
    assert "cle_dupliquee" in controles


def test_echeance_anterieure_detectee() -> None:
    df = all_bulletins().with_columns(date_echeance=pl.col("date_bulletin").dt.offset_by("-2d"))
    controles = {a.controle for a in check_bulletins(df) if a.gravite == "erreur"}
    assert "echeance_anterieure" in controles


def test_entrepot_vide() -> None:
    from bra_analytics import schema

    vide = pl.DataFrame(schema=schema.BULLETINS)
    assert check_bulletins(vide)[0].controle == "entrepot_vide"


def test_couverture_compte_les_trous() -> None:
    gaps = coverage_gaps(all_bulletins())
    assert "jours_manquants" in gaps.columns
    assert gaps.filter(pl.col("jours_manquants") < 0).height == 0


def test_rapport_lisible() -> None:
    texte = report(all_bulletins())
    assert "bulletins controles" in texte
    assert "Erreurs" in texte


def test_risque_non_estime_est_un_signal_pas_une_erreur() -> None:
    anomalies = {a.controle: a for a in check_bulletins(all_bulletins())}
    assert anomalies["risque_non_estime"].gravite == "signal"
    assert anomalies["risque_non_estime"].lignes == 1
    assert "risque1_hors_echelle" not in anomalies


def test_libelle_incoherent_avec_le_referentiel() -> None:
    """ID=3 (Mont-Blanc) porte MASSIF="MOYENNE MONTAGNE" dans un bulletin de 2016.

    C'est un message technique annoncant l'absence de BRA en moyenne montagne,
    diffuse sous l'identifiant d'un massif reel.
    """
    parsed = parse_file(fixture("anomalie_2016_moyenne_montagne.xml"))
    df = to_frames(parsed)["bulletins"]
    erreurs = {a.controle for a in check_bulletins(df) if a.gravite == "erreur"}
    assert "libelle_massif_incoherent" in erreurs


# --------------------------------------------------------------------------
# Tables filles : chaque conversion de sentinelle reste comptee
# --------------------------------------------------------------------------

def _filles(*noms: str) -> dict[str, pl.DataFrame]:
    return to_frames([p for n in noms for p in parse_file(fixture(n))])


def _controles(frames: dict[str, pl.DataFrame]) -> dict[str, Anomalie]:
    return {a.controle: a for a in check_filles(frames)}


def test_vent_aberrant_est_une_erreur() -> None:
    """Champsaur, prevision du 23/12/2024 a 18 h : `FF1="400"`. Signale, pas
    corrige ; les metriques l'excluent."""
    c = _controles(_filles("anomalie_2024_champsaur_vent_aberrant.xml"))
    assert c["vent_hors_plage"].gravite == "erreur"
    assert c["vent_hors_plage"].lignes == 1


def test_conversions_comptees() -> None:
    c = _controles(_filles(
        "anomalie_2023_andorre_releves_vides.xml",
        "anomalie_2022_haute_bigorre_secteurs.xml",
        "anomalie_2025_couserans_sans_enneigement.xml",
    ))
    assert c["echeance_meteo_vide"].lignes == 1
    assert c["releve_enneigement_vide"].lignes == 1
    assert c["neige_fraiche_non_observee"].lignes == 1
    assert c["sans_enneigement_continu"].lignes == 1
    assert all(a.gravite == "signal" for k, a in c.items() if k != "vent_hors_plage")


def test_aucune_erreur_dans_les_tables_filles_des_fixtures() -> None:
    frames = to_frames([p for f in bulletins_valides() for p in parse_file(f)])
    erreurs = [a for a in check_filles(frames) if a.gravite == "erreur"]
    assert erreurs == [], [str(a) for a in erreurs]


def test_vent_unique_signale() -> None:
    """Queyras 2023 : un seul vent, `ALTITUDEVENT2="9999"` lu comme absent."""
    df = _filles("anomalie_2023_queyras_vent_unique.xml")["bulletins"]
    signaux = {a.controle: a for a in check_bulletins(df) if a.gravite == "signal"}
    assert signaux["vent_unique"].lignes == 1


def test_rapport_inclut_les_tables_filles() -> None:
    frames = _filles("anomalie_2024_champsaur_vent_aberrant.xml")
    texte = report(frames["bulletins"], frames)
    assert "vent_hors_plage" in texte
