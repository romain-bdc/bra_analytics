"""Bloc risque de la couche metriques (spec section 5.1, tache T6).

Quatre vues, posees sur `risque_journalier` et restreintes a `massif_coherent` :

- `risque_jour`           massif x jour : risque du jour, variation depuis la
                          veille, ecart a la normale ;
- `risque_episode`        un episode >= 3 par ligne, par portee ;
- `risque_saison`         massif x saison x portee : comptes par seuil, parts,
                          moyenne, mediane, maximum, occurrences >= 3, episodes,
                          variations, duree de saison ;
- `risque_second_indice`  massif x jour : `risque1` / `risque2` / `loc_type`,
                          pour la vue experte.

Une *portee* est l'une des fenetres de `fenetres.py` ou la saison entiere ; la
colonne s'appelle `fenetre`, comme dans `saison_fenetre`.

Deux pieges de la spec sont traites ici, pas laisses a l'interface :

- **un trou d'archive rompt un episode.** Un jour sans bulletin n'est pas
  recolle : la suite s'arrete, l'episode est marque `rompu_par_trou`, et le
  nombre d'episodes rompus est publie a cote du compte. L'archive compte 2 492
  jours-massif manquants a l'interieur des spans (exploration.md, 2 ter) ;
- **une variation ne se calcule qu'entre deux jours consecutifs.** Les paires
  qui enjambent un trou, ou dont un jour est sans indice, sont comptees a part
  (`paires_ecartees`) plutot qu'oubliees.

Les comparaisons inter-saisons passent par `comparer_saisons()` et
`moyenne_pluriannuelle()`, qui **refusent** toute fenetre autre que `coeur` :
hors de cette fenetre, pres de la moitie de l'ecart entre les epoques est un
artefact de la sentinelle `RISQUE1=-1` (glossaire, 2.3).
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import polars as pl

from ..build import _litteral
from ..fenetres import (
    DEFAUT,
    FENETRES,
    PAR_NOM,
    SAISON_COMPLETE,
    SAISONS_NON_COMPARABLES,
    Fenetre,
)

# Seuil d'un episode : indice 3 "marque", le premier niveau ou un skieur seul
# peut declencher (echelle europeenne, glossaire section 1).
SEUIL_EPISODE = 3

# Nombre minimal de saisons comparables pour publier une normale a une date.
# En dessous, la "mediane des saisons" n'est qu'une poignee de valeurs : le
# 29 fevrier n'existe que dans une saison comparable (2023-2024), et sa
# normale serait la valeur du jour elle-meme, d'ou un ecart nul de facon
# mecanique. 5 est la majorite des 9 saisons comparables ; Andorre en compte 8,
# le Haut-Var Haut-Verdon 7 (diffuse depuis novembre 2018).
MIN_SAISONS_NORMALE = 5

VUES: tuple[str, ...] = ("risque_jour", "risque_episode", "risque_saison", "risque_second_indice")

# La normale et les comparaisons s'appuient sur la fenetre par defaut ; elle
# doit etre celle qui autorise la comparaison, sinon tout ce module ment.
if not DEFAUT.comparable_entre_saisons:
    raise RuntimeError(f"la fenetre par defaut {DEFAUT.nom!r} n'autorise pas la comparaison")


class ComparaisonRefusee(ValueError):
    """Comparaison inter-saisons demandee hors d'une fenetre qui l'autorise."""


# --------------------------------------------------------------------------
# SQL des vues
# --------------------------------------------------------------------------

def _exclusions() -> str:
    """Saisons non comparables, en litteral `VALUES`, depuis `fenetres.py`."""
    return ", ".join(
        f"({_litteral(saison)}, {_litteral(motif)})"
        for saison, motif in SAISONS_NON_COMPARABLES.items()
    )


def _sql_risque_jour(min_saisons_normale: int) -> str:
    coeur = f"fenetre_{DEFAUT.nom}"
    fenetres = ", ".join(f"fenetre_{f.nom}" for f in FENETRES)
    # Ecart a la normale. "A la meme date" se lit ici "au meme jour du
    # calendrier" (mois-jour), et non au meme `jour_de_saison` : l'ouverture de
    # la diffusion varie de deux semaines d'une saison a l'autre, si bien qu'un
    # meme rang de saison tomberait a des dates nivologiquement differentes.
    #
    # La normale ne se calcule que sur la fenetre `coeur` et les saisons
    # comparables : c'est une comparaison inter-saisons d'indice, et hors de
    # `coeur` les jours `-1` d'avant juin 2021 en sont absents alors que les
    # memes jours recents y entrent a 1. La saison lue entre dans sa propre
    # normale quand elle est comparable : la spec dit "mediane des saisons
    # comparables", sans exclusion.
    #
    # `median()` est la mediane usuelle : elle vaut x,5 quand le nombre de
    # saisons est pair et que les deux valeurs centrales different. On ne la
    # tronque pas vers un niveau entier, ce qui biaiserait l'ecart vers le bas.
    return f"""
        WITH base AS (
          SELECT
            saison, saison_debut, massif_id, massif_nom, zone,
            jour_validite, jour_de_saison, risque_maxi, risque_estime,
            {fenetres},
            lag(jour_validite) OVER w AS jour_precedent,
            lag(risque_maxi)   OVER w AS risque_precedent
          FROM risque_journalier
          WHERE massif_coherent
          WINDOW w AS (PARTITION BY massif_id, saison ORDER BY jour_validite)
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {_exclusions()}),
        normales AS (
          SELECT
            massif_id,
            strftime(jour_validite, '%m-%d') AS jour_annee,
            median(risque_maxi)              AS mediane,
            count(DISTINCT saison)           AS saisons
          FROM base
          WHERE {coeur}
            AND risque_maxi IS NOT NULL
            AND saison NOT IN (SELECT saison FROM exclusions)
          GROUP BY massif_id, jour_annee
        )
        SELECT
          b.saison, b.saison_debut, b.massif_id, b.massif_nom, b.zone,
          b.jour_validite, b.jour_de_saison, b.risque_maxi, b.risque_estime,
          {", ".join(f"b.fenetre_{f.nom}" for f in FENETRES)},
          e.motif_exclusion IS NULL AS saison_comparable,
          e.motif_exclusion,
          b.jour_precedent,
          date_diff('day', b.jour_precedent, b.jour_validite) = 1 AS veille_couverte,
          -- NULL des que la veille manque ou que l'un des deux jours est sans
          -- indice : un ecart de deux jours n'est pas une hausse en 24 h.
          CASE WHEN date_diff('day', b.jour_precedent, b.jour_validite) = 1
               THEN b.risque_maxi - b.risque_precedent END AS variation,
          CASE WHEN b.{coeur} THEN n.saisons END AS saisons_normale,
          CASE WHEN b.{coeur} AND n.saisons >= {int(min_saisons_normale)}
               THEN n.mediane END AS normale,
          CASE WHEN b.{coeur} AND e.motif_exclusion IS NULL
                    AND n.saisons >= {int(min_saisons_normale)}
               THEN b.risque_maxi - n.mediane END AS ecart_normale
        FROM base b
        LEFT JOIN exclusions e USING (saison)
        LEFT JOIN normales n
          ON n.massif_id = b.massif_id
         AND n.jour_annee = strftime(b.jour_validite, '%m-%d')
    """


def _sql_risque_episode() -> str:
    fenetres = ", ".join(f"fenetre_{f.nom}" for f in FENETRES)
    portees = "\n".join(
        f"          UNION ALL BY NAME SELECT '{f.nom}' AS fenetre, * FROM jours_haut "
        f"WHERE fenetre_{f.nom}"
        for f in FENETRES
    )
    # Un episode se definit une seule fois, sur la serie de la saison entiere :
    # une suite de jours couverts *consecutifs au calendrier* a `risque_maxi`
    # >= 3. Une fenetre ne fait que le rogner -- l'episode qui chevauche
    # l'ouverture de `coeur` y garde ses jours interieurs et est marque
    # `tronque_par_fenetre`, sans devenir un autre episode.
    #
    # Ce qui borde un episode, de part et d'autre :
    # - un jour couvert a < 3 : fin franche ;
    # - un jour sans bulletin (`rompu_par_trou`) : on ne sait pas si l'episode
    #   continuait, il n'est pas recolle a la suite ;
    # - un jour couvert sans indice (`borde_sans_indice`) : pas un trou
    #   d'archive, mais pas une fin franche non plus. Le cas est frequent aux
    #   lisieres de la pratique du `-1` (fin avril 2017-2021) ;
    # - le premier ou le dernier jour de la saison : fin de serie, rien a signaler.
    return f"""
        WITH base AS (
          SELECT
            saison, saison_debut, massif_id, jour_validite, risque_maxi, {fenetres},
            lag(jour_validite)  OVER w AS jour_prec,
            lag(risque_maxi)    OVER w AS risque_prec,
            lead(jour_validite) OVER w AS jour_suiv,
            lead(risque_maxi)   OVER w AS risque_suiv
          FROM risque_journalier
          WHERE massif_coherent
          WINDOW w AS (PARTITION BY massif_id, saison ORDER BY jour_validite)
        ),
        marques AS (
          SELECT *,
            coalesce(risque_maxi >= {SEUIL_EPISODE}, false) AS haut,
            coalesce(risque_maxi >= {SEUIL_EPISODE}, false)
              AND NOT coalesce(date_diff('day', jour_prec, jour_validite) = 1
                               AND risque_prec >= {SEUIL_EPISODE}, false) AS ouvre
          FROM base
        ),
        jours_haut AS (
          SELECT * FROM (
            SELECT *,
              sum(CAST(ouvre AS INTEGER)) OVER (
                PARTITION BY massif_id, saison ORDER BY jour_validite
                ROWS UNBOUNDED PRECEDING) AS episode
            FROM marques
          ) WHERE haut
        ),
        entiers AS (
          SELECT
            massif_id, saison, episode,
            min(jour_validite) AS debut_entier,
            max(jour_validite) AS fin_entiere,
            -- Ce qui precede le premier jour, et ce qui suit le dernier.
            arg_min(coalesce(date_diff('day', jour_prec, jour_validite) > 1, false),
                    jour_validite) AS trou_avant,
            arg_max(coalesce(date_diff('day', jour_validite, jour_suiv) > 1, false),
                    jour_validite) AS trou_apres,
            arg_min(coalesce(date_diff('day', jour_prec, jour_validite) = 1
                             AND risque_prec IS NULL, false), jour_validite) AS sans_indice_avant,
            arg_max(coalesce(date_diff('day', jour_validite, jour_suiv) = 1
                             AND risque_suiv IS NULL, false), jour_validite) AS sans_indice_apres
          FROM jours_haut
          GROUP BY massif_id, saison, episode
        ),
        portees AS (
          SELECT '{SAISON_COMPLETE}' AS fenetre, * FROM jours_haut
{portees}
        ),
        rognes AS (
          SELECT
            p.fenetre, p.saison, p.massif_id, p.episode,
            any_value(p.saison_debut) AS saison_debut,
            min(p.jour_validite)      AS debut,
            max(p.jour_validite)      AS fin,
            count(*)                  AS duree_jours,
            max(p.risque_maxi)        AS niveau_max
          FROM portees p
          GROUP BY p.fenetre, p.saison, p.massif_id, p.episode
        )
        -- Une bordure ne compte que du cote ou la portee n'a pas rogne
        -- l'episode : un trou du 13 decembre ne rompt rien dans `coeur`, qui
        -- ouvre le 15 -- l'episode y est deja `tronque_par_fenetre`.
        SELECT
          r.fenetre, r.saison, r.saison_debut, r.massif_id, r.episode,
          r.debut, r.fin, r.duree_jours, r.niveau_max,
          (e.trou_avant AND r.debut = e.debut_entier)
            OR (e.trou_apres AND r.fin = e.fin_entiere)          AS rompu_par_trou,
          (e.sans_indice_avant AND r.debut = e.debut_entier)
            OR (e.sans_indice_apres AND r.fin = e.fin_entiere)   AS borde_sans_indice,
          r.debut > e.debut_entier OR r.fin < e.fin_entiere      AS tronque_par_fenetre
        FROM rognes r
        JOIN entiers e USING (massif_id, saison, episode)
    """


def _sql_risque_saison() -> str:
    portees = "\n".join(
        f"          UNION ALL BY NAME\n"
        f"          SELECT '{f.nom}' AS fenetre,\n"
        f"                 {f.comparable_entre_saisons} AS fenetre_comparable,\n"
        # Une variation compte dans la fenetre si ses *deux* jours y sont :
        # la hausse du 14 au 15 decembre n'appartient pas a `coeur`.
        f"                 {f.sql_predicat('jour_precedent')} AS paire_dans_portee,\n"
        f"                 {f.sql_duree()} AS jours_periode, *\n"
        f"          FROM risque_jour WHERE fenetre_{f.nom}"
        for f in FENETRES
    )
    niveaux = ",\n".join(
        f"            count(*) FILTER (risque_maxi = {n}) AS jours_niveau_{n},\n"
        # Les parts se rapportent aux jours *avec indice*, comme la moyenne :
        # elles somment a 1, et un jour `-1` d'avant 2021 n'y figure pas comme
        # un jour a 0. Les jours sans indice sont publies a part.
        f"            round(count(*) FILTER (risque_maxi = {n})"
        f" / nullif(count(risque_maxi), 0), 4) AS part_niveau_{n}"
        for n in range(1, 6)
    )
    return f"""
        WITH portees AS (
          SELECT '{SAISON_COMPLETE}' AS fenetre, false AS fenetre_comparable,
                 true AS paire_dans_portee, CAST(NULL AS BIGINT) AS jours_periode, *
          FROM risque_jour
{portees}
        ),
        marquees AS (
          SELECT *, max(risque_maxi) OVER (PARTITION BY fenetre, saison, massif_id) AS max_portee
          FROM portees
        ),
        stats AS (
          SELECT
            fenetre, saison, massif_id,
            any_value(saison_debut)                          AS saison_debut,
            any_value(massif_nom)                            AS massif_nom,
            any_value(zone)                                  AS zone,
            any_value(fenetre_comparable) AND any_value(saison_comparable) AS comparable,
            any_value(motif_exclusion)                       AS motif_exclusion,
            any_value(jours_periode)                         AS jours_periode,
            count(*)                                         AS jours_couverts,
            -- `risque_maxi IS NOT NULL`, et non `risque_estime` : quatorze
            -- lignes portent RISQUE1=-1 avec un RISQUEMAXI reel. Elles sont non
            -- estimees *et* comptees, comme dans `saison_fenetre`.
            count(risque_maxi)                               AS jours_avec_indice,
            count(*) - count(risque_maxi)                    AS jours_sans_indice,
            count(*) FILTER (NOT risque_estime)              AS jours_non_estimes,
            count(*) FILTER (risque_maxi >= 3)               AS jours_3_plus,
            count(*) FILTER (risque_maxi >= 4)               AS jours_4_plus,
            count(*) FILTER (risque_maxi = 5)                AS jours_5,
{niveaux},
            round(avg(risque_maxi), 3)                       AS risque_moyen,
            median(risque_maxi)                              AS risque_median,
            max(risque_maxi)                                 AS risque_max,
            min(jour_validite) FILTER (risque_maxi = max_portee) AS date_max,
            count(*) FILTER (risque_maxi = max_portee)       AS jours_au_max,
            min(jour_validite) FILTER (risque_maxi >= 3)     AS premier_jour_3_plus,
            max(jour_validite) FILTER (risque_maxi >= 3)     AS dernier_jour_3_plus,
            count(*) FILTER (paire_dans_portee AND variation >= 1)  AS hausses_1_plus,
            count(*) FILTER (paire_dans_portee AND variation >= 2)  AS hausses_2_plus,
            count(*) FILTER (paire_dans_portee AND variation <= -1) AS baisses_1_plus,
            count(*) FILTER (paire_dans_portee AND variation <= -2) AS baisses_2_plus,
            count(*) FILTER (paire_dans_portee AND variation IS NOT NULL) AS paires_consecutives,
            count(*) FILTER (paire_dans_portee AND jour_precedent IS NOT NULL
                             AND variation IS NULL)          AS paires_ecartees
          FROM marquees
          GROUP BY fenetre, saison, massif_id
        ),
        episodes AS (
          SELECT
            fenetre, saison, massif_id,
            count(*)                                     AS episodes,
            count(*) FILTER (rompu_par_trou)             AS episodes_rompus_par_trou,
            count(*) FILTER (borde_sans_indice)          AS episodes_bordes_sans_indice,
            count(*) FILTER (tronque_par_fenetre)        AS episodes_tronques_par_fenetre,
            median(duree_jours)                          AS duree_mediane_episode,
            max(duree_jours)                             AS plus_long_episode,
            first(debut ORDER BY duree_jours DESC, debut) AS plus_long_episode_debut
          FROM risque_episode
          GROUP BY fenetre, saison, massif_id
        )
        SELECT
          s.* EXCLUDE (jours_periode),
          coalesce(e.episodes, 0)                      AS episodes,
          coalesce(e.episodes_rompus_par_trou, 0)      AS episodes_rompus_par_trou,
          coalesce(e.episodes_bordes_sans_indice, 0)   AS episodes_bordes_sans_indice,
          coalesce(e.episodes_tronques_par_fenetre, 0) AS episodes_tronques_par_fenetre,
          e.duree_mediane_episode,
          e.plus_long_episode,
          e.plus_long_episode_debut,
          -- Duree de saison : reprise telle quelle de `couverture`, et donc
          -- toujours celle de la saison entiere, quelle que soit la portee.
          c.premier_jour,
          c.dernier_jour,
          c.jours_calendaires,
          c.jours_manquants,
          -- Couverture de la portee : une fenetre se rapporte a sa duree
          -- nominale (une saison tronquee ne doit pas y paraitre complete), la
          -- saison entiere a son span observe.
          coalesce(s.jours_periode, c.jours_calendaires) AS jours_periode,
          round(100.0 * s.jours_couverts
                / coalesce(s.jours_periode, c.jours_calendaires), 1) AS couverture_pct
        FROM stats s
        LEFT JOIN episodes e USING (fenetre, saison, massif_id)
        LEFT JOIN couverture c USING (saison, massif_id)
    """


def _sql_risque_second_indice() -> str:
    # `risque_journalier` ne porte ni `risque2_evolution` ni les secteurs : on
    # les reprend de `bulletins` par sa cle `(massif_id, date_bulletin)`, qui y
    # est unique (deduplication du build), donc la jointure ne duplique rien.
    return """
        SELECT
          r.saison, r.massif_id, r.massif_nom, r.zone, r.jour_validite,
          r.risque_maxi, r.risque1, r.risque1_evolution, r.risque2,
          b.risque2_evolution, r.loc_type, r.altitude_seuil_m,
          b.loc1_secteur, b.loc2_secteur
        FROM risque_journalier r
        JOIN bulletins b USING (massif_id, date_bulletin)
        WHERE r.massif_coherent
    """


def creer_vues(
    con: duckdb.DuckDBPyConnection,
    *,
    temporaire: bool = False,
    min_saisons_normale: int = MIN_SAISONS_NORMALE,
) -> tuple[str, ...]:
    """Pose les vues du bloc risque sur une base qui a `risque_journalier`.

    `temporaire=True` les cree en vues temporaires : c'est ce qui permet de
    lire un entrepot construit avant T6, ouvert en lecture seule, sans le
    reconstruire.
    """
    portee = "TEMP " if temporaire else ""
    for nom, sql in (
        ("risque_jour", _sql_risque_jour(min_saisons_normale)),
        ("risque_episode", _sql_risque_episode()),
        ("risque_saison", _sql_risque_saison()),
        ("risque_second_indice", _sql_risque_second_indice()),
    ):
        con.execute(f"CREATE OR REPLACE {portee}VIEW {nom} AS {sql}")
    return VUES


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

_TYPES: dict[str, pl.DataType] = {
    "BOOLEAN": pl.Boolean(),
    "TINYINT": pl.Int8(), "SMALLINT": pl.Int16(), "INTEGER": pl.Int32(),
    "BIGINT": pl.Int64(), "HUGEINT": pl.Int64(),
    "FLOAT": pl.Float64(), "DOUBLE": pl.Float64(),
    "DATE": pl.Date(), "TIMESTAMP": pl.Datetime("us"), "VARCHAR": pl.Utf8(),
}


def _polars_type(duck: str) -> pl.DataType:
    if duck.startswith("DECIMAL"):
        return pl.Float64()
    try:
        return _TYPES[duck]
    except KeyError:
        raise TypeError(f"type DuckDB sans correspondance polars : {duck}") from None


def _frame(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[object] = ()) -> pl.DataFrame:
    """Resultat DuckDB -> polars, au schema *declare* par DuckDB.

    Pas d'inference sur les valeurs : une colonne nulle de bout en bout (un
    `plus_long_episode` sur une saison sans episode) serait typee `Null` et
    casserait toute concatenation. `pyarrow` n'est pas une dependance du
    projet, d'ou la conversion explicite.
    """
    rows = con.execute(sql, list(params)).fetchall()
    schema = {d[0]: _polars_type(str(d[1])) for d in con.description}
    return pl.DataFrame(rows, schema=schema, orient="row", strict=False)


def _assurer_vues(con: duckdb.DuckDBPyConnection) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if not set(VUES) <= presentes:
        creer_vues(con, temporaire=True)


def _portee(fenetre: str) -> str:
    if fenetre != SAISON_COMPLETE and fenetre not in PAR_NOM:
        raise ValueError(
            f"fenetre inconnue : {fenetre!r} (attendu : "
            f"{', '.join([*PAR_NOM, SAISON_COMPLETE])})"
        )
    return fenetre


def _fenetre_comparable(fenetre: str) -> Fenetre:
    """La fenetre, si elle autorise une comparaison inter-saisons ; sinon refus.

    Refuser plutot que renvoyer un chiffre : sur `commune` ou la saison
    entiere, l'ecart entre 2016-2021 et 2021-2026 est pour moitie un artefact
    d'encodage, et un chiffre faux se lit exactement comme un chiffre juste.
    """
    _portee(fenetre)
    f = PAR_NOM.get(fenetre)
    if f is None or not f.comparable_entre_saisons:
        usage = f.usage if f else "lecture d'une saison prise isolement"
        raise ComparaisonRefusee(
            f"comparaison inter-saisons refusee sur {fenetre!r} ({usage}) : "
            f"seule la fenetre {DEFAUT.nom!r} ({DEFAUT.libelle}) l'autorise. "
            "Hors de cette fenetre, la sentinelle RISQUE1=-1 (jusqu'en juin 2021) "
            "fait ressortir les saisons anciennes plus haut a nivologie egale."
        )
    return f


def _filtres(
    massifs: Sequence[int] | None,
    saisons: Sequence[str] | None,
    conditions: list[str],
    params: list[object],
) -> str:
    if massifs is not None:
        conditions.append(f"massif_id IN ({', '.join('?' for _ in massifs) or 'NULL'})")
        params.extend(massifs)
    if saisons is not None:
        conditions.append(f"saison IN ({', '.join('?' for _ in saisons) or 'NULL'})")
        params.extend(saisons)
    return " WHERE " + " AND ".join(conditions) if conditions else ""


def serie_jour(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Risque du jour, variation depuis la veille, ecart a la normale (massif x jour)."""
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(
        con, f"SELECT * FROM risque_jour{where} ORDER BY massif_id, jour_validite", params
    )


def metriques_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Metriques massif x saison sur une portee.

    Lecture d'une saison, pas comparaison : toute portee est admise, et la
    colonne `comparable` dit si la ligne peut entrer dans une comparaison.
    Pour comparer, passer par `comparer_saisons()`.
    """
    _assurer_vues(con)
    params: list[object] = [_portee(fenetre)]
    where = _filtres(massifs, saisons, ["fenetre = ?"], params)
    return _frame(
        con, f"SELECT * FROM risque_saison{where} ORDER BY massif_id, saison", params
    )


def episodes(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Episodes >= 3, un par ligne, avec ce qui les borde."""
    _assurer_vues(con)
    params: list[object] = [_portee(fenetre)]
    where = _filtres(massifs, saisons, ["fenetre = ?"], params)
    return _frame(
        con, f"SELECT * FROM risque_episode{where} ORDER BY massif_id, debut", params
    )


def second_indice(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """`risque1` / `risque2` et leur localisation, pour la vue experte (massif x jour)."""
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(
        con, f"SELECT * FROM risque_second_indice{where} ORDER BY massif_id, jour_validite",
        params,
    )


def comparer_saisons(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = DEFAUT.nom,
    massifs: Sequence[int] | None = None,
) -> pl.DataFrame:
    """Une ligne par saison, sur la fenetre de comparaison ; refuse toute autre.

    Les jours de tous les massifs retenus sont mis en commun (moyenne ponderee
    par jour, pas moyenne de moyennes). Les saisons non comparables restent
    dans le resultat, etiquetees (`comparable`, `motif_exclusion`) : les
    retirer en silence les ferait redecouvrir plus tard.
    """
    f = _fenetre_comparable(fenetre)
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, None, [f"fenetre_{f.nom}"], params)
    return _frame(
        con,
        f"""
        SELECT
          saison,
          bool_and(saison_comparable)         AS comparable,
          any_value(motif_exclusion)          AS motif_exclusion,
          count(DISTINCT massif_id)           AS massifs,
          count(*)                            AS jours_couverts,
          count(risque_maxi)                  AS jours_avec_indice,
          round(avg(risque_maxi), 3)          AS risque_moyen,
          median(risque_maxi)                 AS risque_median,
          count(*) FILTER (risque_maxi >= 3)  AS jours_3_plus,
          count(*) FILTER (risque_maxi >= 4)  AS jours_4_plus,
          count(*) FILTER (risque_maxi = 5)   AS jours_5
        FROM risque_jour{where}
        GROUP BY saison
        ORDER BY saison
        """,
        params,
    )


def moyenne_pluriannuelle(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = DEFAUT.nom,
    massifs: Sequence[int] | None = None,
) -> pl.DataFrame:
    """Une ligne par massif, toutes saisons comparables confondues (spec 3.2).

    C'est la metrique d'accueil : moyenne de `risque_maxi` sur `coeur`, saisons
    comparables seulement, accompagnee des jours couverts et des jours >= 4.
    Les saisons ecartees sont comptees (`saisons_ecartees`), pas tues.
    """
    f = _fenetre_comparable(fenetre)
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, None, [f"fenetre_{f.nom}"], params)
    return _frame(
        con,
        f"""
        SELECT
          massif_id,
          any_value(massif_nom)                                         AS massif_nom,
          any_value(zone)                                               AS zone,
          count(DISTINCT saison) FILTER (saison_comparable)             AS saisons,
          count(DISTINCT saison) FILTER (NOT saison_comparable)         AS saisons_ecartees,
          count(*) FILTER (saison_comparable)                           AS jours_couverts,
          count(risque_maxi) FILTER (saison_comparable)                 AS jours_avec_indice,
          round(avg(risque_maxi) FILTER (saison_comparable), 3)         AS risque_moyen,
          median(risque_maxi) FILTER (saison_comparable)                AS risque_median,
          count(*) FILTER (saison_comparable AND risque_maxi >= 3)      AS jours_3_plus,
          count(*) FILTER (saison_comparable AND risque_maxi >= 4)      AS jours_4_plus,
          count(*) FILTER (saison_comparable AND risque_maxi = 5)       AS jours_5
        FROM risque_jour{where}
        GROUP BY massif_id
        ORDER BY massif_id
        """,
        params,
    )
