"""Bloc rose des pentes et situations typiques (spec section 5.4, tache T9).

La rose (`<PENTE>`) et les situations typiques (`sat1` / `sat2`) sont un jeu
unique par bulletin : **aucune altitude n'y est attachee** (le parser ne lit
aucun attribut d'altitude sur `<PENTE>`, et `<SitAvalTyp>` n'en porte pas
non plus). La consigne de tranche d'altitude de la spec etait donc
inapplicable a la rose ; elle est corrigee en spec 3.1 et 5.4, comme pour le
risque. Toute sortie de ce module porte `altitude = 'non localisee'` : la
rose ne se lit pas "toutes altitudes", elle ne dit rien de l'altitude. Seul le
croisement avec le vent, dont les altitudes sont reelles, se ventile par
tranche normee.

Cinq vues, restreintes a `massif_coherent` et indexees sur `jour_validite` :

- `pente_jour`              massif x jour couvert : les huit orientations, leur
                            nombre, `sat1` / `sat2` avec libelles ;
- `pente_orientation_saison` massif x saison x portee x orientation : part des
                            jours ou le secteur est signale, toutes
                            conditions, puis restreinte aux jours >= 3 et >= 4 ;
- `pente_saison`            massif x saison x portee : secteur dominant,
                            concentration (nombre moyen de secteurs), jours
                            sans secteur ;
- `pente_mois_orientation`  massif x mois x portee x orientation : saisonnalite ;
- `pente_vent_saison`       massif x saison x portee x tranche x direction du
                            vent : jours ou la pente chargee par ce vent est
                            signalee dans la rose ;
- `pente_situation_saison`  massif x saison x portee x rang x code : situations
                            typiques, depuis la premiere saison qui en porte.

Denominateur : les jours couverts avec `risque_maxi IS NOT NULL`, comme toute
moyenne du repo. Une rose vide (aucun secteur signale) reste dans ce
denominateur : a risque 1 elle dit "aucune orientation particuliere", et elle
porte 8 086 des 62 388 jours (13 %). Huit jours seulement ont
une rose vide a risque >= 2 : `rose_vide_risque_ge2` les compte plutot que de
les ecarter. La frequence d'exposition depend donc du melange de risques de la
saison ; la frequence ponderee (>= 3, >= 4) est la lecture comparable.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import polars as pl

from ..fenetres import FENETRES, SAISON_COMPLETE, sql_exclusions
from ..tranches import TRANCHES
from . import meteo, risque
from .risque import _filtres, _frame, _portee

# Ordre de lecture d'une rose, convention anglaise comme le reste du repo.
ORIENTATIONS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

ALTITUDE = "non localisee"

# Libelles des codes `sat` : INFERES (glossaire 2.7), le descriptif officiel n'en
# fournit aucun. Le code 6 n'est pas un mecanisme d'avalanche : il est
# distingue par `est_situation_typique` pour ne pas entrer dans une analyse
# des mecanismes.
LIBELLES_SAT: dict[int, str] = {
    1: "Neige fraîche",
    2: "Neige soufflée / plaques à vent",
    3: "Couche fragile persistante",
    4: "Neige humide",
    5: "Avalanche de glissement",
    6: "Manteau insuffisant",
}
CODE_SANS_MECANISME = 6

VUES: tuple[str, ...] = (
    "pente_jour", "pente_orientation_saison", "pente_saison", "pente_mois_orientation",
    "pente_situation_saison",
)
# Posee a part : elle requiert le vent par tranche du bloc meteo.
VUE_VENT = "pente_vent_saison"


def _fenetres(prefixe: str = "") -> str:
    return ", ".join(f"{prefixe}fenetre_{f.nom}" for f in FENETRES)


def _portees(source: str) -> str:
    """Union saison entiere + une branche par fenetre, comme `risque_saison`."""
    branches = "\n".join(
        f"          UNION ALL BY NAME\n"
        f"          SELECT '{f.nom}' AS fenetre, {f.comparable_entre_saisons} AS fenetre_comparable, *\n"
        f"          FROM {source} WHERE fenetre_{f.nom}"
        for f in FENETRES
    )
    return f"""
          SELECT '{SAISON_COMPLETE}' AS fenetre, false AS fenetre_comparable, *
          FROM {source}
{branches}"""


def _colonne(s: str) -> str:
    return f"pente_{s.lower()}"


def _ordre(col: str = "orientation") -> str:
    cas = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(ORIENTATIONS, 1))
    return f"CASE {col} {cas} END"


# --------------------------------------------------------------------------
# SQL des vues
# --------------------------------------------------------------------------

def _sql_pente_jour() -> str:
    # La rose et `sat` vivent dans `bulletins`, pas dans `risque_journalier` :
    # la jointure sur (massif_id, date_bulletin) reprend le bulletin que
    # `risque_journalier` retient pour le jour, comme le bloc meteo. Redefinir
    # l'arbitrage ici ferait lire le risque d'un jour dans une version et sa
    # rose dans une autre.
    cols = ", ".join(f"b.{_colonne(s)}" for s in ORIENTATIONS)
    nombre = " + ".join(f"CAST(b.{_colonne(s)} AS INTEGER)" for s in ORIENTATIONS)
    libelles = " ".join(f"WHEN {c} THEN '{l}'" for c, l in LIBELLES_SAT.items())
    return f"""
        SELECT
          j.saison, j.saison_debut, j.massif_id, j.massif_nom, j.zone, j.jour_validite,
          j.jour_de_saison, j.date_bulletin, j.format_famille, {_fenetres('j.')},
          j.risque_maxi, {cols},
          {nombre}                                        AS nb_secteurs,
          j.sat1, CASE j.sat1 {libelles} END              AS sat1_libelle,
          j.sat2, CASE j.sat2 {libelles} END              AS sat2_libelle,
          '{ALTITUDE}'                                    AS altitude
        FROM risque_journalier j
        JOIN bulletins b USING (massif_id, date_bulletin)
        WHERE j.massif_coherent
    """


def _sql_pente_orientation_saison() -> str:
    union = "\n          UNION ALL\n".join(
        f"          SELECT fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone,\n"
        f"                 risque_maxi, '{s}' AS orientation, {_colonne(s)} AS signale\n"
        f"          FROM portees WHERE risque_maxi IS NOT NULL"
        for s in ORIENTATIONS
    )
    return f"""
        WITH portees AS ({_portees('pente_jour')}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()}),
        secteurs AS (
{union}
        )
        SELECT
          fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone,
          orientation, {_ordre()} AS ordre_orientation, '{ALTITUDE}' AS altitude,
          count(*)                                           AS jours_couverts,
          count(*) FILTER (signale)                          AS jours_signales,
          count(*) FILTER (signale) / count(*)::DOUBLE       AS frequence,
          count(*) FILTER (risque_maxi >= 3)                 AS jours_ge3,
          count(*) FILTER (risque_maxi >= 3 AND signale)     AS jours_signales_ge3,
          count(*) FILTER (risque_maxi >= 3 AND signale)
            / nullif(count(*) FILTER (risque_maxi >= 3), 0)::DOUBLE AS frequence_ge3,
          count(*) FILTER (risque_maxi >= 4)                 AS jours_ge4,
          count(*) FILTER (risque_maxi >= 4 AND signale)     AS jours_signales_ge4,
          count(*) FILTER (risque_maxi >= 4 AND signale)
            / nullif(count(*) FILTER (risque_maxi >= 4), 0)::DOUBLE AS frequence_ge4,
          any_value(motif_exclusion)                         AS motif_exclusion
        FROM secteurs LEFT JOIN exclusions USING (saison)
        GROUP BY fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone, orientation
    """


def _sql_pente_saison() -> str:
    return f"""
        WITH portees AS ({_portees('pente_jour')}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()}),
        jours AS (
          SELECT fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone,
                 count(*)                                          AS jours_couverts,
                 count(*) FILTER (nb_secteurs = 0)                 AS jours_sans_secteur,
                 -- Rose vide alors que le risque est >= 2 : incoherence d'archive,
                 -- comptee et gardee (8 jours sur 62 388).
                 count(*) FILTER (nb_secteurs = 0 AND risque_maxi >= 2) AS rose_vide_risque_ge2,
                 avg(nb_secteurs)                                  AS secteurs_moyens,
                 count(*) FILTER (risque_maxi >= 3)                AS jours_ge3,
                 avg(nb_secteurs) FILTER (risque_maxi >= 3)        AS secteurs_moyens_ge3
          FROM portees WHERE risque_maxi IS NOT NULL
          GROUP BY ALL
        ),
        orient AS (
          SELECT *, max(jours_signales) OVER (PARTITION BY fenetre, saison, massif_id) AS maximum
          FROM pente_orientation_saison
        ),
        dominant AS (
          -- A egalite, la premiere orientation dans l'ordre de lecture ; le
          -- nombre d'ex aequo est publie, car une rose entierement signalee
          -- n'a pas de secteur dominant (8 ex aequo).
          SELECT fenetre, saison, massif_id,
                 max(maximum)                                          AS jours_secteur_dominant,
                 arg_min(orientation, ordre_orientation) FILTER (jours_signales = maximum)
                                                                       AS secteur_dominant,
                 count(*) FILTER (jours_signales = maximum)            AS secteurs_ex_aequo
          FROM orient GROUP BY ALL
        )
        SELECT
          j.*, '{ALTITUDE}' AS altitude,
          CASE WHEN d.jours_secteur_dominant > 0 THEN d.secteur_dominant END AS secteur_dominant,
          d.jours_secteur_dominant, d.secteurs_ex_aequo,
          e.motif_exclusion
        FROM jours j
        JOIN dominant d USING (fenetre, saison, massif_id)
        LEFT JOIN exclusions e USING (saison)
    """


def _sql_pente_mois_orientation() -> str:
    union = "\n          UNION ALL\n".join(
        f"          SELECT fenetre, fenetre_comparable, saison, massif_id, massif_nom, zone,\n"
        f"                 month(jour_validite) AS mois, '{s}' AS orientation, {_colonne(s)} AS signale\n"
        f"          FROM portees WHERE risque_maxi IS NOT NULL"
        for s in ORIENTATIONS
    )
    return f"""
        WITH portees AS ({_portees('pente_jour')}
        ),
        secteurs AS (
{union}
        )
        SELECT
          fenetre, fenetre_comparable, massif_id, massif_nom, zone, mois, orientation,
          {_ordre()} AS ordre_orientation, '{ALTITUDE}' AS altitude,
          count(DISTINCT saison)                             AS nb_saisons,
          count(*)                                           AS jours_couverts,
          count(*) FILTER (signale)                          AS jours_signales,
          count(*) FILTER (signale) / count(*)::DOUBLE       AS frequence
        FROM secteurs
        GROUP BY fenetre, fenetre_comparable, massif_id, massif_nom, zone, mois, orientation
    """


def _sql_pente_vent_saison() -> str:
    # Une pente chargee est sous le vent : a l'oppose de la direction d'ou il
    # vient (meteo._OPPOSE, la meme table que l'indice de transport). C'est ici
    # que les tranches normees s'appliquent : l'altitude est celle du vent.
    charge = " ".join(
        f"WHEN '{d}' THEN p.{_colonne(o)}" for d, o in meteo._OPPOSE.items()
    )
    return f"""
        WITH portees AS ({_portees('pente_jour')}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()})
        SELECT
          p.fenetre, p.fenetre_comparable, p.saison, p.saison_debut, p.massif_id, p.massif_nom,
          p.zone, v.tranche, v.direction AS direction_vent,
          '{meteo.ORIGINE}'                                           AS origine_vent,
          string_agg(DISTINCT v.altitudes_vent, ' ; ')                AS altitudes_vent,
          count(*)                                                    AS jours_vent,
          count(*) FILTER (CASE v.direction {charge} END)             AS jours_pente_chargee_signalee,
          count(*) FILTER (CASE v.direction {charge} END) / count(*)::DOUBLE AS frequence,
          any_value(e.motif_exclusion)                                AS motif_exclusion
        FROM portees p
        JOIN meteo_vent_tranche_jour v USING (massif_id, jour_validite)
        LEFT JOIN exclusions e ON e.saison = p.saison
        WHERE p.risque_maxi IS NOT NULL AND v.direction IN ({', '.join(f"'{d}'" for d in meteo._OPPOSE)})
        GROUP BY p.fenetre, p.fenetre_comparable, p.saison, p.saison_debut, p.massif_id,
                 p.massif_nom, p.zone, v.tranche, v.direction
    """


def _sql_pente_situation_saison() -> str:
    libelles = " ".join(f"WHEN {c} THEN '{l}'" for c, l in LIBELLES_SAT.items())
    return f"""
        WITH portees AS ({_portees('pente_jour')}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()}),
        premiere AS (SELECT min(saison) AS saison FROM pente_jour WHERE sat1 IS NOT NULL),
        couverts AS (
          -- Jours ou la situation dominante est renseignee : avant la premiere
          -- saison qui en porte, il n'y en a pas et la vue n'a pas de ligne.
          SELECT fenetre, saison, massif_id, count(*) AS jours_couverts
          FROM portees WHERE risque_maxi IS NOT NULL AND sat1 IS NOT NULL
          GROUP BY ALL
        ),
        rangs AS (
          SELECT fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone,
                 1 AS rang, sat1 AS code
          FROM portees WHERE risque_maxi IS NOT NULL AND sat1 IS NOT NULL
          UNION ALL
          SELECT fenetre, fenetre_comparable, saison, saison_debut, massif_id, massif_nom, zone,
                 2, sat2
          FROM portees WHERE risque_maxi IS NOT NULL AND sat1 IS NOT NULL AND sat2 IS NOT NULL
        )
        SELECT
          r.fenetre, r.fenetre_comparable, r.saison, r.saison_debut, r.massif_id, r.massif_nom, r.zone,
          r.rang, CASE r.rang WHEN 1 THEN 'dominante' ELSE 'secondaire' END AS role,
          r.code, CASE r.code {libelles} END                AS libelle,
          r.code <> {CODE_SANS_MECANISME}                   AS est_situation_typique,
          'inferee (glossaire 2.7)'                         AS libelle_source,
          '{ALTITUDE}'                                      AS altitude,
          count(*)                                          AS jours,
          any_value(c.jours_couverts)                       AS jours_couverts,
          count(*) / any_value(c.jours_couverts)::DOUBLE    AS part,
          'depuis la saison ' || any_value(p.saison)        AS restriction,
          any_value(e.motif_exclusion)                      AS motif_exclusion
        FROM rangs r
        JOIN couverts c USING (fenetre, saison, massif_id)
        CROSS JOIN premiere p
        LEFT JOIN exclusions e ON e.saison = r.saison
        GROUP BY r.fenetre, r.fenetre_comparable, r.saison, r.saison_debut, r.massif_id,
                 r.massif_nom, r.zone, r.rang, r.code
    """


_SQL = {
    "pente_jour": _sql_pente_jour,
    "pente_orientation_saison": _sql_pente_orientation_saison,
    "pente_saison": _sql_pente_saison,
    "pente_mois_orientation": _sql_pente_mois_orientation,
    "pente_situation_saison": _sql_pente_situation_saison,
    VUE_VENT: _sql_pente_vent_saison,
}


def creer_vues(
    con: duckdb.DuckDBPyConnection,
    *,
    temporaire: bool = False,
) -> tuple[str, ...]:
    """Pose les vues du bloc.

    Requiert `risque_journalier` et `bulletins`. `pente_vent_saison` demande en
    plus le vent par tranche du bloc meteo : sans lui, le reste du bloc reste
    disponible. `temporaire=True` les cree en vues temporaires, pour lire un
    entrepot construit avant T9 ouvert en lecture seule.
    """
    portee = "TEMP " if temporaire else ""
    for nom in VUES:
        con.execute(f"CREATE OR REPLACE {portee}VIEW {nom} AS {_SQL[nom]()}")
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if "meteo_vent_tranche_jour" in presentes:
        con.execute(f"CREATE OR REPLACE {portee}VIEW {VUE_VENT} AS {_SQL[VUE_VENT]()}")
    return VUES


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def _assurer_vues(con: duckdb.DuckDBPyConnection) -> None:
    risque._assurer_vues(con)
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if "meteo" in {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}:
        meteo._assurer_vues(con)
        presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if not set(VUES) <= presentes:
        creer_vues(con, temporaire=True)


def _orientations(orientations: Sequence[str] | None, conditions: list[str], params: list[object]) -> None:
    if orientations is None:
        return
    inconnues = set(orientations) - set(ORIENTATIONS)
    if inconnues:
        raise ValueError(f"orientations inconnues : {sorted(inconnues)} (attendu : {list(ORIENTATIONS)})")
    conditions.append(f"orientation IN ({', '.join('?' for _ in orientations) or 'NULL'})")
    params.extend(orientations)


def _lire(
    con: duckdb.DuckDBPyConnection,
    vue: str,
    fenetre: str,
    massifs: Sequence[int] | None,
    saisons: Sequence[str] | None,
    extra: list[str],
    params: list[object],
    ordre: str,
) -> pl.DataFrame:
    _assurer_vues(con)
    params = [_portee(fenetre), *params]
    where = _filtres(massifs, saisons, ["fenetre = ?", *extra], params)
    return _frame(con, f"SELECT * FROM {vue}{where} ORDER BY {ordre}", params)


def rose_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    orientations: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Frequence d'exposition par orientation (massif x saison x orientation).

    Les frequences sont toujours accompagnees des jours dont elles sont tirees ;
    `frequence_ge3` / `frequence_ge4` sont la lecture ponderee, nulle quand la
    saison n'a aucun jour de ce niveau. La rose n'est pas localisee en altitude.
    """
    extra: list[str] = []
    params: list[object] = []
    _orientations(orientations, extra, params)
    return _lire(con, "pente_orientation_saison", fenetre, massifs, saisons, extra, params,
                 "massif_id, saison, ordre_orientation")


def resume_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Secteur dominant et concentration (massif x saison)."""
    return _lire(con, "pente_saison", fenetre, massifs, saisons, [], [], "massif_id, saison")


def saisonnalite(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    orientations: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Frequence d'exposition par mois (massif x mois x orientation), saisons cumulees.

    `nb_saisons` et `jours_couverts` disent sur quoi la frequence repose.
    """
    extra: list[str] = []
    params: list[object] = []
    _orientations(orientations, extra, params)
    return _lire(con, "pente_mois_orientation", fenetre, massifs, None, extra, params,
                 "massif_id, mois, ordre_orientation")


def croisement_vent(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Vent prevu x rose : part des jours, par direction de vent, ou la pente
    qu'il charge est signalee. Seul croisement ventile par tranche normee."""
    _assurer_vues(con)
    if VUE_VENT not in {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}:
        raise ValueError("croisement vent x orientation indisponible : l'entrepot n'a pas de bloc meteo")
    extra: list[str] = []
    params: list[object] = []
    if tranches is not None:
        inconnues = set(tranches) - {t.nom for t in TRANCHES}
        if inconnues:
            raise ValueError(f"tranches inconnues : {sorted(inconnues)} (attendu : {sorted(t.nom for t in TRANCHES)})")
        extra.append(f"tranche IN ({', '.join('?' for _ in tranches) or 'NULL'})")
        params.extend(tranches)
    return _lire(con, VUE_VENT, fenetre, massifs, saisons, extra, params,
                 "massif_id, saison, tranche, direction_vent")


def situations(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Situations avalancheuses typiques (massif x saison x rang x code).

    Uniquement les saisons qui en portent ; `restriction` le dit sur chaque
    ligne, et `libelle` est inferee (`libelle_source`). Le code 6 est marque
    `est_situation_typique = false`.
    """
    return _lire(con, "pente_situation_saison", fenetre, massifs, saisons, [], [],
                 "massif_id, saison, rang, code")
