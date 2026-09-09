"""Controles de coherence."""

import polars as pl

from bra_analytics.build import to_frames
from bra_analytics.parser import parse_file
from bra_analytics.quality import check_bulletins, coverage_gaps, report

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
