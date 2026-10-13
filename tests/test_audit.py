"""Audit de disponibilite champ x saison (T2).

L'audit decide quelles metriques de la spec sont calculables avant qu'on en
ecrive une seule. Il se teste donc sur ce qu'il affirme : qu'un champ propre a
une epoque est vu absent ailleurs, que le statut d'une metrique decoule de la
disponibilite mesuree, et que le document produit est reproductible.
"""

from __future__ import annotations

import duckdb
import pytest

from bra_analytics import audit
from bra_analytics.build import build

from .conftest import FIXTURES


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("audit")
    db = tmp / "bra.duckdb"
    build(FIXTURES, tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


def _part(dispo, table: str, champ: str, saison: str) -> float:
    ligne = dispo.filter(
        (dispo["table"] == table) & (dispo["champ"] == champ) & (dispo["saison"] == saison)
    )
    assert ligne.height == 1, (table, champ, saison)
    return ligne["part"][0]


def test_un_champ_propre_a_une_epoque_est_absent_ailleurs(con) -> None:
    """`sat1` n'existe que depuis 2024 : nul en 2022-2023, rempli en 2023-2024."""
    dispo = audit.disponibilite(con)
    assert _part(dispo, "bulletins", "sat1", "2022-2023") == 0.0
    assert _part(dispo, "bulletins", "sat1", "2023-2024") == 1.0


def _statut(statuts, nom: str) -> dict:
    ligne = statuts.filter(statuts["metrique"] == nom)
    assert ligne.height == 1, nom
    return ligne.row(0, named=True)


def test_statut_des_metriques_decoule_de_la_disponibilite(con) -> None:
    """Le statut n'est pas ecrit a la main : il se lit dans la mesure."""
    statuts = audit.statuts(audit.disponibilite(con))

    # `jour_validite` et non l'indice : dans les fixtures, la saison 2017-2018
    # n'est portee que par l'avis de fin de saison du Chablais (`RISQUE1="0"`),
    # donc sans aucun `risque_maxi`.
    assert _statut(statuts, "Durée de saison BRA")["statut"] == "calculable"
    risque = _statut(statuts, "Risque du jour")
    assert risque["statut"] == "sous-ensemble"
    assert "2017-2018" not in risque["saisons"]

    sat = _statut(statuts, "Situations typiques")
    assert sat["statut"] == "sous-ensemble"
    assert sat["saisons"] == "2023-2024, 2024-2025, 2025-2026"


def test_un_texte_redige_ne_fait_pas_un_indice(con) -> None:
    """`naturel` et `accidentel` sont remplis, mais ce sont des textes.

    La metrique « indices naturel et accidentel » est donc non calculable
    quelle que soit la disponibilite du champ.
    """
    statuts = audit.statuts(audit.disponibilite(con))
    ligne = _statut(statuts, "Indices naturel et accidentel")
    assert ligne["statut"] == "non calculable"
    assert "texte" in ligne["motif"]


def test_altitudes_de_reference_par_massif_et_saison(con) -> None:
    """Les paliers lus dans le XML d'Aspe-Ossau 2023 (NIVEAU ALTI, ALTITUDESS,
    ALTITUDEVENT1/2) ressortent tels quels, une liste par source."""
    alt = audit.altitudes_reference(con)
    alt = alt.filter((alt["massif_id"] == 65) & (alt["saison"] == "2022-2023"))
    par_source = dict(zip(alt["source"], alt["altitudes"]))
    assert par_source == {
        "enneigement": "1500/2000/2500",
        "neige_fraiche": "1800",
        "vent_bas": "1500",
        "vent_haut": "3000",
    }


def test_ecarts_entre_prevision_et_historique_meteo() -> None:
    """Spec § 4.3 : un champ renseigne en prevision mais jamais dans
    l'historique doit ressortir, saison par saison.

    Entree construite : les fixtures ne contiennent aucun ecart mesurable, car
    le seul attribut que le `BSH` 2024 perd (`MERNUAGES`) vaut `-1` -- sans
    objet, converti en nul -- dans la prevision elle-meme.
    """
    c = duckdb.connect()
    c.execute(
        "CREATE VIEW bulletins AS SELECT * FROM (VALUES "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', true, 'moderne')) "
        "t(massif_id, date_bulletin, saison, massif_coherent, format_famille)"
    )
    colonnes = ", ".join(
        f"NULL::INTEGER AS {c}" for c in ("vent_bas_vitesse_kmh", "vent_haut_vitesse_kmh",
                                          "iso_moins10_m", "limite_pluie_neige_m",
                                          "temps_sensible")
    )
    c.execute(
        "CREATE VIEW meteo AS SELECT massif_id, date_bulletin, saison, origine, "
        "iso_0_m, mer_nuages_m, NULL::VARCHAR AS vent_bas_direction, "
        "NULL::VARCHAR AS vent_haut_direction, NULL::VARCHAR AS temps_sensible_libelle, "
        f"{colonnes} FROM (VALUES "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'prevision', 2000, 1500), "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'historique', 1800, NULL)) "
        "t(massif_id, date_bulletin, saison, origine, iso_0_m, mer_nuages_m)"
    )
    ecarts = audit.ecarts_meteo(c)
    assert ecarts.select("saison", "champ").rows() == [("2023-2024", "mer_nuages_m")]


def test_quantiles_ecartent_la_sentinelle(con) -> None:
    """Un `-1` n'est pas une vitesse de vent : il ne compte ni dans `n` ni dans
    les quantiles. Les fixtures en portent un en prevision (vent haut, bulletin
    de 2016), ce qui suffit a distinguer les deux lectures."""
    total, sentinelles = con.execute(
        "SELECT count(vent_haut_vitesse_kmh), "
        "count(*) FILTER (vent_haut_vitesse_kmh = -1) "
        f"FROM ({audit._source('meteo')}) WHERE origine = 'prevision'"
    ).fetchone()
    assert sentinelles >= 1

    (ligne,) = [q for q in audit._quantiles(con) if "vent_haut_vitesse_kmh" in q[0]]
    assert ligne[3] == total - sentinelles


def test_rapport_reproductible(con) -> None:
    """Deux executions sur le meme entrepot rendent le meme document, octet pour
    octet : `docs/disponibilite.md` est versionne, un diff doit y signifier un
    changement de donnees et rien d'autre."""
    assert audit.rapport(con) == audit.rapport(con)


def test_bra_audit_ecrit_le_document(tmp_path, con) -> None:
    from bra_analytics.cli import main

    db = tmp_path / "bra.duckdb"
    build(FIXTURES, tmp_path / "warehouse", db)
    out = tmp_path / "disponibilite.md"
    assert main(["audit", "--db", str(db), "--out", str(out)]) == 0
    texte = out.read_text(encoding="utf-8")
    assert texte.startswith("# Disponibilité des champs")
    # Chaque metrique de la spec y figure avec son statut.
    for m in audit.METRIQUES:
        assert m.nom in texte


def test_un_qualificatif_texte_n_empeche_pas_un_indice(con) -> None:
    """Le second indice lit `loc_type`, un texte (`altitude` / `orientation`),
    mais ce sont `risque1` et `risque2` qui portent l'indice : le champ texte ne
    doit pas la rendre non calculable. (Sur les fixtures elle reste restreinte a
    un sous-ensemble : peu de bulletins y distinguent deux zones.)"""
    statuts = audit.statuts(audit.disponibilite(con))
    ligne = _statut(statuts, "Second indice")
    assert ligne["statut"] != "non calculable"
    assert "texte" not in (ligne["motif"] or "")


def test_sentinelles_non_converties(con) -> None:
    """Un `-1` reste dans certaines colonnes numeriques, ou il fausse toute
    somme. Lu dans le XML d'Aspe-Ossau 2023 : `SS242="-1"` sur chaque jour du
    bloc neige fraiche ; aucun `-1` dans le bloc 2026."""
    s = audit.sentinelles(con)
    nf = s.filter((s["table"] == "neige_fraiche") & (s["champ"] == "cumul_max_cm"))
    par_saison = dict(zip(nf["saison"], nf["sentinelles"]))
    assert par_saison.get("2022-2023", 0) > 0
    assert par_saison.get("2025-2026", 0) == 0


def test_une_sentinelle_ne_rend_pas_un_champ_disponible(con) -> None:
    """`-1` n'est pas une valeur. Aspe-Ossau 2023 porte `SS242="-1"` sur chaque
    jour : la colonne est remplie, mais rien n'y est exploitable."""
    dispo = audit.disponibilite(con)
    ligne = dispo.filter(
        (dispo["table"] == "neige_fraiche") & (dispo["champ"] == "cumul_max_cm")
        & (dispo["saison"] == "2022-2023")
    ).row(0, named=True)
    assert ligne["part"] < 1.0


def test_neige_fraiche_legacy_hors_calcul(con) -> None:
    """Avant 2024, `cumul_max_cm` porte le cumul d'un second secteur, pas un
    maximum (`SECTEURSS2` dans le XML legacy). Les metriques de neige fraiche
    ne sont calculables que sur la famille moderne."""
    statuts = audit.statuts(audit.disponibilite(con))
    ligne = _statut(statuts, "Épisodes de chute")
    assert ligne["statut"] == "sous-ensemble"
    assert ligne["saisons"] == "2023-2024, 2024-2025, 2025-2026"
    assert "secteur" in ligne["motif"]


def test_un_champ_rare_dans_l_historique_est_un_ecart() -> None:
    """Porte par un tiers seulement des lignes d'historique, contre toutes les
    lignes de prevision, un champ ne soutient pas la convention § 4.3 : la
    serie extraite serait trouee aux deux tiers."""
    c = duckdb.connect()
    c.execute(
        "CREATE VIEW bulletins AS SELECT * FROM (VALUES "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', true, 'moderne')) "
        "t(massif_id, date_bulletin, saison, massif_coherent, format_famille)"
    )
    nuls = ", ".join(
        f"NULL::{t} AS {n}" for n, t in (
            ("vent_bas_vitesse_kmh", "INTEGER"), ("vent_haut_vitesse_kmh", "INTEGER"),
            ("iso_moins10_m", "INTEGER"), ("limite_pluie_neige_m", "INTEGER"),
            ("temps_sensible", "INTEGER"), ("mer_nuages_m", "INTEGER"),
            ("vent_bas_direction", "VARCHAR"), ("vent_haut_direction", "VARCHAR"),
            ("temps_sensible_libelle", "VARCHAR"),
        )
    )
    c.execute(
        f"CREATE VIEW meteo AS SELECT massif_id, date_bulletin, saison, origine, iso_0_m, {nuls} "
        "FROM (VALUES "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'prevision', 2000), "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'historique', 1800), "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'historique', NULL), "
        "(65, TIMESTAMP '2024-01-17 16:00', '2023-2024', 'historique', NULL)) "
        "t(massif_id, date_bulletin, saison, origine, iso_0_m)"
    )
    assert ("2023-2024", "iso_0_m") in audit.ecarts_meteo(c).select("saison", "champ").rows()
