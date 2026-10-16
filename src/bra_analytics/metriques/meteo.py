"""Bloc meteo de la couche metriques (spec section 5.3, tache T8).

Le bloc meteo du BRA est une **prevision** : chaque vue porte une colonne
`origine = 'prevision'`, et l'interface doit le dire la ou elle affiche une
serie (spec section 5.3), pas en note de bas de page.

Convention d'extraction (spec section 4.3, arretee le 15 octobre 2026,
glossaire section 3) : pour un jour couvert, la meteo se lit dans le bulletin
qui le couvre -- le *meme* que celui que `risque_journalier` retient --,
`origine = 'prevision'`, echeances de 06 h et 12 h de `jour_validite`, jamais
dans le bloc historique. Les heures d'echeance changent en 2024 (00/06/12 h de
J, puis 06/12/18 h de J et 00 h de J+1) : seules 06 h et 12 h sont communes
aux deux epoques, et une valeur du jour calculee sur d'autres heures melerait
deux definitions de part et d'autre de l'hiver 2023-2024.

Six vues, restreintes a `massif_coherent` et indexees sur `jour_validite` :

- `meteo_jour`            massif x jour couvert : isotherme 0 degC, limite
                          pluie-neige, temps sensible a 06 h et 12 h, valeur
                          du jour, variation en 24 h, motif de lacune ;
- `meteo_vent_jour`       massif x jour x altitude de vent, avec sa tranche ;
- `meteo_redoux`          une sequence de jours a isotherme haut par ligne,
                          avec le risque avant, pendant et apres ;
- `meteo_saison`          massif x saison x portee : isotherme, variations,
                          limite pluie-neige, redoux ;
- `meteo_vent_saison`     massif x saison x portee x tranche : jours de vent fort ;
- `meteo_temps_sensible`  massif x saison x portee x code : repartition des
                          codes de temps, avec libelles.

Les vues posees au build portent les seuils par defaut. Les fonctions de
lecture acceptent d'autres seuils : elles regenerent alors le meme SQL avec
les valeurs demandees, sans recopier la definition. Chaque sortie publie le
seuil qui l'a produite.

**Reste a faire** : l'indice de transport de neige par le vent (spec 5.3)
combine vent fort et neige fraiche recente ; il attend la vue de neige
fraiche dedupliquee du bloc enneigement (T7).
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import polars as pl

from ..fenetres import FENETRES, SAISON_COMPLETE, sql_exclusions
from ..quality import VENT_MAX_KMH
from ..tranches import TRANCHES
from ..tranches import sql_case as sql_case_tranche
from . import risque
from .risque import _filtres, _frame, _portee

# Echeances qui font la valeur du jour : les seules communes aux deux epoques
# de format (glossaire section 3). Une valeur du jour exige les deux : avec une
# seule, le "maximum du jour" de 2023 et celui de 2024 ne mesureraient pas la
# meme chose, et la serie changerait de definition en silence.
HEURES_JOUR: tuple[int, int] = (6, 12)

# Seuil de vent fort, en km/h, applique a la vitesse du jour d'une altitude de
# vent. 70 km/h est le 90e centile du vent haut en prevision (disponibilite.md
# section 7 : p50 30, p75 50, p90 70, p95 80) ; c'est entre le p95 (60) et le
# p99 (80) du vent bas. Un jour est "de vent fort" au-dessus *strictement* du
# seuil : les vitesses sont ecrites par pas de 5 km/h, et 70 tout rond reste
# dans les neuf dixiemes ordinaires.
SEUIL_VENT_FORT_KMH = 70

# Seuil d'isotherme 0 degC, en metres, des jours "de redoux marque". 3400 m est
# le 90e centile de l'isotherme en prevision (disponibilite.md section 7 :
# p50 2400, p75 3000, p90 3400, p95 3700) -- le meme rang que le seuil de
# vent. La distribution couvre la saison entiere, printemps compris : en plein
# hiver, depasser 3400 m est rare, et c'est ce qu'un redoux "marque" doit dire.
SEUIL_ISO0_M = 3400

# Duree minimale d'un episode de redoux, en jours couverts consecutifs. La
# spec demande un franchissement "maintenu au moins 24 h" : un jour seul ne
# l'atteste pas (06 h et 12 h n'en couvrent que six), deux jours consecutifs
# au-dessus a 06 h et 12 h l'attestent sur trente heures.
DUREE_MIN_REDOUX_JOURS = 2

VUES: tuple[str, ...] = (
    "meteo_jour", "meteo_vent_jour", "meteo_vent_tranche_jour", "meteo_redoux",
    "meteo_saison", "meteo_vent_saison", "meteo_temps_sensible",
)

ORIGINE = "prevision"

_H = tuple(f"{h:02d}h" for h in HEURES_JOUR)


def _fenetres(prefixe: str = "") -> str:
    return ", ".join(f"{prefixe}fenetre_{f.nom}" for f in FENETRES)


def _verifier_seuils(**seuils: int) -> None:
    """Les seuils entrent dans le SQL : entiers positifs seulement."""
    for nom, valeur in seuils.items():
        if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur <= 0:
            raise ValueError(f"{nom} doit etre un entier positif : {valeur!r}")


# --------------------------------------------------------------------------
# SQL des vues
# --------------------------------------------------------------------------

def _sql_jours_et_echeances() -> str:
    """CTE communes : les jours couverts, et les echeances de prevision du jour.

    `jours` reprend `risque_journalier` telle quelle : son arbitrage entre
    plusieurs bulletins couvrant un meme jour (redaction la plus tardive) est
    celui de la meteo. Le redefinir ici ferait lire le risque d'un jour dans
    une version et sa meteo dans une autre ; les bulletins qu'il ecarte sont
    deja journalises ligne a ligne par `log_daily_collapse_discards()`.
    """
    h0, h1 = HEURES_JOUR
    return f"""
        jours AS (
          SELECT saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
                 jour_de_saison, date_bulletin, format_famille, {_fenetres()}
          FROM risque_journalier
          WHERE massif_coherent
        ),
        echeances AS (
          -- Prevision seule, echeance sur le jour couvert, heures communes aux
          -- deux epoques. Jamais le bloc historique : il manque toute la
          -- saison 2015-2016 et 1 a 2 % des jours jusqu'en 2023.
          SELECT m.*, hour(m.echeance) AS heure
          FROM meteo m
          JOIN jours j
            ON j.massif_id = m.massif_id
           AND j.date_bulletin = m.date_bulletin
           AND CAST(m.echeance AS DATE) = j.jour_validite
          WHERE m.origine = '{ORIGINE}'
            AND hour(m.echeance) IN ({h0}, {h1})
            AND minute(m.echeance) = 0
        )"""


def _sql_meteo_jour() -> str:
    h0, h1 = HEURES_JOUR
    a, b = _H

    def par_heure(col: str, nom: str) -> str:
        return (f"any_value(e.{col}) FILTER (e.heure = {h0}) AS {nom}_{a}, "
                f"any_value(e.{col}) FILTER (e.heure = {h1}) AS {nom}_{b}")

    def les_deux(nom: str, expr: str) -> str:
        # Valeur du jour : seulement si les deux echeances sont renseignees.
        return (f"CASE WHEN {nom}_{a} IS NOT NULL AND {nom}_{b} IS NOT NULL "
                f"THEN {expr} END")

    return f"""
        WITH {_sql_jours_et_echeances()},
        blocs AS (
          SELECT massif_id, date_bulletin, count(*) AS echeances_prevision
          FROM meteo WHERE origine = '{ORIGINE}'
          GROUP BY massif_id, date_bulletin
        ),
        agg AS (
          SELECT
            j.saison, j.saison_debut, j.massif_id, j.massif_nom, j.zone,
            j.jour_validite, j.jour_de_saison, j.date_bulletin, j.format_famille,
            {_fenetres('j.')},
            any_value(coalesce(bl.echeances_prevision, 0)) AS echeances_prevision,
            count(e.echeance)                              AS echeances_jour,
            -- Echeance vide : `-1` partout avant 2024, attributs vides
            -- ensuite (glossaire section 3). La ligne existe, ses valeurs non.
            count(e.echeance) FILTER (
              e.iso_0_m IS NULL AND e.temps_sensible IS NULL
              AND e.vent_bas_vitesse_kmh IS NULL AND e.vent_haut_vitesse_kmh IS NULL
            )                                              AS echeances_vides,
            {par_heure('iso_0_m', 'iso0')},
            {par_heure('limite_pluie_neige_m', 'limite_pluie_neige')},
            {par_heure('temps_sensible', 'temps_sensible')},
            {par_heure('temps_sensible_libelle', 'temps_sensible_libelle')}
          FROM jours j
          LEFT JOIN echeances e USING (massif_id, date_bulletin)
          LEFT JOIN blocs bl USING (massif_id, date_bulletin)
          GROUP BY ALL
        ),
        jour AS (
          SELECT
            *,
            {les_deux('iso0', f'least(iso0_{a}, iso0_{b})')}    AS iso0_min_m,
            {les_deux('iso0', f'greatest(iso0_{a}, iso0_{b})')} AS iso0_max_m,
            {les_deux('iso0', f'(iso0_{a} + iso0_{b}) / 2.0')}  AS iso0_moyen_m,
            -- `-1` (temps sec) est rendu nul par le parser : une limite nulle
            -- dit "pas de precipitation prevue" *ou* "attribut absent", que
            -- l'entrepot ne distingue pas (disponibilite.md section 8). La
            -- plus basse des limites renseignees est donc la seule lecture
            -- possible ; elle ne suppose pas que les deux echeances en aient.
            least(limite_pluie_neige_{a}, limite_pluie_neige_{b}) AS limite_pluie_neige_min_m
          FROM agg
        )
        SELECT
          saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
          jour_de_saison, date_bulletin, format_famille, {_fenetres()},
          '{ORIGINE}' AS origine,
          echeances_prevision, echeances_jour, echeances_vides,
          CASE
            WHEN echeances_prevision = 0 THEN 'aucune echeance de prevision dans le bulletin'
            WHEN echeances_jour = 0 THEN 'echeances de prevision hors du jour couvert'
            WHEN echeances_jour < 2 THEN 'echeance de {h0:02d} h ou de {h1:02d} h absente'
            WHEN echeances_vides > 0 THEN 'echeance de {h0:02d} h ou de {h1:02d} h vide'
          END AS motif_lacune,
          iso0_{a} AS iso0_{a}_m, iso0_{b} AS iso0_{b}_m,
          iso0_min_m, iso0_max_m, iso0_moyen_m,
          lag(jour_validite) OVER w AS jour_precedent,
          -- Variation en 24 h de l'isotherme moyen du jour : entre deux jours
          -- couverts *consecutifs* seulement, comme les variations de risque.
          -- Un ecart de deux jours n'est pas une variation en 24 h.
          CASE WHEN date_diff('day', lag(jour_validite) OVER w, jour_validite) = 1
               THEN iso0_moyen_m - lag(iso0_moyen_m) OVER w END AS variation_iso0_24h_m,
          limite_pluie_neige_{a} AS limite_pluie_neige_{a}_m,
          limite_pluie_neige_{b} AS limite_pluie_neige_{b}_m,
          limite_pluie_neige_min_m,
          temps_sensible_{a}, temps_sensible_libelle_{a},
          temps_sensible_{b}, temps_sensible_libelle_{b}
        FROM jour
        WINDOW w AS (PARTITION BY massif_id, saison ORDER BY jour_validite)
    """


def _sql_meteo_vent_jour() -> str:
    h0, h1 = HEURES_JOUR
    a, b = _H
    valide = f"BETWEEN 0 AND {VENT_MAX_KMH}"
    # Le vent se lit par altitude, jamais par role bas / haut : jusqu'en 2023
    # les neuf massifs des Alpes du Sud n'ont qu'un vent, a 3000 m, dans la
    # colonne "basse" (`ALTITUDEVENT2="9999"`, altitude rendue nulle). Il entre
    # ici par son altitude et tombe en tranche haute, comme le vent a 3000 m de
    # ces massifs depuis 2024 qui, lui, est dans la colonne "haute".
    #
    # Un vent sans altitude n'a pas de ligne : on ne sait pas a quelle tranche
    # il appartient. Le seul bulletin concerne (Chablais, redige le
    # 11/06/2018, `jour_validite` au 01/11/2018) a ses echeances hors du jour
    # couvert : `meteo_jour` porte deja ce jour comme lacune.
    #
    # Une vitesse hors [0, VENT_MAX_KMH] est une erreur de `bra check` (400 et
    # -5 km/h en prevision) : conservee dans l'entrepot, exclue ici, et comptee
    # dans `vitesses_hors_plage` plutot que tue.
    return f"""
        WITH {_sql_jours_et_echeances()},
        vents AS (
          SELECT e.massif_id, e.date_bulletin, e.heure,
                 b.vent_altitude_basse_m AS altitude_m,
                 e.vent_bas_vitesse_kmh AS vitesse, e.vent_bas_direction AS direction
          FROM echeances e JOIN bulletins b USING (massif_id, date_bulletin)
          WHERE b.vent_altitude_basse_m IS NOT NULL
          UNION ALL
          SELECT e.massif_id, e.date_bulletin, e.heure,
                 b.vent_altitude_haute_m, e.vent_haut_vitesse_kmh, e.vent_haut_direction
          FROM echeances e JOIN bulletins b USING (massif_id, date_bulletin)
          WHERE b.vent_altitude_haute_m IS NOT NULL
        ),
        agg AS (
          SELECT
            j.saison, j.saison_debut, j.massif_id, j.massif_nom, j.zone,
            j.jour_validite, j.date_bulletin, j.format_famille, {_fenetres('j.')},
            v.altitude_m,
            any_value(CASE WHEN v.vitesse {valide} THEN v.vitesse END)
              FILTER (v.heure = {h0}) AS v0,
            any_value(CASE WHEN v.vitesse {valide} THEN v.vitesse END)
              FILTER (v.heure = {h1}) AS v1,
            any_value(v.direction) FILTER (v.heure = {h0}) AS d0,
            any_value(v.direction) FILTER (v.heure = {h1}) AS d1,
            count(*) FILTER (v.vitesse IS NOT NULL AND NOT (v.vitesse {valide}))
              AS vitesses_hors_plage
          FROM jours j
          JOIN vents v USING (massif_id, date_bulletin)
          GROUP BY ALL
        )
        SELECT
          saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
          date_bulletin, format_famille, {_fenetres()},
          '{ORIGINE}' AS origine,
          altitude_m,
          {sql_case_tranche('altitude_m')} AS tranche,
          v0 AS vitesse_{a}_kmh, d0 AS direction_{a},
          v1 AS vitesse_{b}_kmh, d1 AS direction_{b},
          vitesses_hors_plage,
          -- Vitesse du jour : la plus forte des deux echeances, a condition
          -- qu'elles soient toutes deux valides (meme regle que l'isotherme).
          CASE WHEN v0 IS NOT NULL AND v1 IS NOT NULL THEN greatest(v0, v1) END
            AS vitesse_max_kmh,
          -- Direction au maximum ; a egalite, celle de {h1:02d} h, la plus
          -- proche de l'apres-midi ou le vent transporte la neige.
          CASE WHEN v0 IS NOT NULL AND v1 IS NOT NULL
               THEN CASE WHEN v1 >= v0 THEN d1 ELSE d0 END END AS direction_au_max
        FROM agg
    """


def _sql_meteo_redoux(seuil_iso0_m: int, duree_min_jours: int) -> str:
    # Un redoux est une suite de jours couverts *consecutifs au calendrier* ou
    # l'isotherme 0 degC depasse le seuil aux deux echeances du jour
    # (`iso0_min_m > seuil`) : la lecture la plus prudente du "maintenu au
    # moins 24 h" de la spec. Le jour qui precede doit etre couvert et sous le
    # seuil pour que le franchissement a la hausse soit *observe*.
    #
    # Comme les episodes de risque (glossaire section 9) :
    # - un trou d'archive rompt la suite, qui n'est pas recollee
    #   (`rompu_par_trou`) ;
    # - un jour couvert sans valeur d'isotherme la borde sans la clore
    #   (`borde_sans_valeur`) ;
    # - une suite plus courte que la duree minimale reste dans la vue, avec
    #   `retenu = false` : elle n'est pas un episode, mais elle n'est pas tue.
    s = int(seuil_iso0_m)
    return f"""
        WITH base AS (
          SELECT
            massif_id, massif_nom, zone, saison, saison_debut, jour_validite,
            iso0_min_m, iso0_max_m, {_fenetres()},
            lag(jour_validite)  OVER w AS jour_prec,
            lag(iso0_min_m)     OVER w AS iso0_prec,
            lead(jour_validite) OVER w AS jour_suiv,
            lead(iso0_min_m)    OVER w AS iso0_suiv
          FROM meteo_jour
          WINDOW w AS (PARTITION BY massif_id, saison ORDER BY jour_validite)
        ),
        marques AS (
          SELECT *,
            coalesce(iso0_min_m > {s}, false) AS haut,
            coalesce(iso0_min_m > {s}, false)
              AND NOT coalesce(date_diff('day', jour_prec, jour_validite) = 1
                               AND iso0_prec > {s}, false) AS ouvre
          FROM base
        ),
        jours_haut AS (
          SELECT * FROM (
            SELECT *,
              sum(CAST(ouvre AS INTEGER)) OVER (
                PARTITION BY massif_id, saison ORDER BY jour_validite
                ROWS UNBOUNDED PRECEDING) AS sequence
            FROM marques
          ) WHERE haut
        ),
        sequences AS (
          SELECT
            massif_id, saison, sequence,
            any_value(massif_nom)  AS massif_nom,
            any_value(zone)        AS zone,
            any_value(saison_debut) AS saison_debut,
            min(jour_validite)     AS debut,
            max(jour_validite)     AS fin,
            count(*)               AS duree_jours,
            max(iso0_max_m)        AS iso0_max_m,
            arg_min(jour_prec, jour_validite) AS jour_prec,
            arg_min(iso0_prec, jour_validite) AS iso0_prec,
            arg_max(jour_suiv, jour_validite) AS jour_suiv,
            arg_max(iso0_suiv, jour_validite) AS iso0_suiv,
            {", ".join(f"arg_min(fenetre_{f.nom}, jour_validite) AS fenetre_{f.nom}"
                       for f in FENETRES)}
          FROM jours_haut
          GROUP BY massif_id, saison, sequence
        ),
        risque_pendant AS (
          SELECT s.massif_id, s.saison, s.sequence, max(r.risque_maxi) AS risque_max_pendant
          FROM sequences s
          JOIN risque_jour r
            ON r.massif_id = s.massif_id AND r.saison = s.saison
           AND r.jour_validite BETWEEN s.debut AND s.fin
          GROUP BY ALL
        )
        SELECT
          s.massif_id, s.massif_nom, s.zone, s.saison, s.saison_debut,
          '{ORIGINE}' AS origine,
          {s} AS seuil_iso0_m,
          {int(duree_min_jours)} AS duree_min_jours,
          s.debut, s.fin, s.duree_jours,
          s.duree_jours >= {int(duree_min_jours)} AS retenu,
          s.iso0_max_m,
          coalesce(date_diff('day', s.jour_prec, s.debut) = 1
                   AND s.iso0_prec IS NOT NULL, false)            AS franchissement_observe,
          coalesce(date_diff('day', s.jour_prec, s.debut) > 1, false)
            OR coalesce(date_diff('day', s.fin, s.jour_suiv) > 1, false) AS rompu_par_trou,
          coalesce(date_diff('day', s.jour_prec, s.debut) = 1 AND s.iso0_prec IS NULL, false)
            OR coalesce(date_diff('day', s.fin, s.jour_suiv) = 1
                        AND s.iso0_suiv IS NULL, false)            AS borde_sans_valeur,
          -- Risque de la veille et du lendemain : seulement s'ils sont des
          -- jours couverts, pas le dernier jour connu de part et d'autre d'un
          -- trou.
          rv.risque_maxi       AS risque_veille,
          p.risque_max_pendant AS risque_max_pendant,
          rl.risque_maxi       AS risque_lendemain,
          {", ".join(f"s.fenetre_{f.nom} AS debut_fenetre_{f.nom}" for f in FENETRES)}
        FROM sequences s
        LEFT JOIN risque_pendant p USING (massif_id, saison, sequence)
        LEFT JOIN risque_jour rv
          ON rv.massif_id = s.massif_id AND rv.jour_validite = s.debut - 1
        LEFT JOIN risque_jour rl
          ON rl.massif_id = s.massif_id AND rl.jour_validite = s.fin + 1
    """


def _portees(source: str) -> str:
    """Union saison entiere + une branche par fenetre, comme `risque_saison`."""
    branches = "\n".join(
        f"          UNION ALL BY NAME\n"
        f"          SELECT '{f.nom}' AS fenetre, {f.comparable_entre_saisons} AS fenetre_comparable,\n"
        # Une variation compte dans la fenetre si ses *deux* jours y sont :
        # la hausse du 14 au 15 decembre n'appartient pas a `coeur`.
        f"                 {f.sql_predicat('jour_precedent')} AS paire_dans_portee, *\n"
        f"          FROM {source} WHERE fenetre_{f.nom}"
        for f in FENETRES
    )
    return f"""
          SELECT '{SAISON_COMPLETE}' AS fenetre, false AS fenetre_comparable,
                 true AS paire_dans_portee, *
          FROM {source}
{branches}"""


def _sql_meteo_saison(seuil_iso0_m: int, duree_min_jours: int) -> str:
    s = int(seuil_iso0_m)
    redoux_portees = "\n".join(
        f"          UNION ALL BY NAME SELECT '{f.nom}' AS fenetre, * FROM redoux "
        f"WHERE debut_fenetre_{f.nom}"
        for f in FENETRES
    )
    return f"""
        WITH portees AS ({_portees('meteo_jour')}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()}),
        redoux AS ({_sql_meteo_redoux(s, duree_min_jours)}),
        redoux_portees AS (
          SELECT '{SAISON_COMPLETE}' AS fenetre, * FROM redoux
{redoux_portees}
        ),
        episodes AS (
          -- Un episode appartient a la portee ou il commence.
          SELECT fenetre, saison, massif_id,
                 count(*)                           AS episodes_redoux,
                 count(*) FILTER (rompu_par_trou)   AS redoux_rompus_par_trou,
                 count(*) FILTER (NOT franchissement_observe) AS redoux_sans_franchissement_observe,
                 sum(duree_jours)                   AS jours_en_redoux,
                 max(duree_jours)                   AS plus_long_redoux
          FROM redoux_portees WHERE retenu
          GROUP BY ALL
        ),
        stats AS (
          SELECT
            fenetre, saison, massif_id,
            any_value(saison_debut)                       AS saison_debut,
            any_value(massif_nom)                         AS massif_nom,
            any_value(zone)                               AS zone,
            any_value(fenetre_comparable)                 AS fenetre_comparable,
            '{ORIGINE}'                                   AS origine,
            count(*)                                      AS jours_couverts,
            count(*) FILTER (motif_lacune IS NULL)        AS jours_meteo_complete,
            count(iso0_moyen_m)                           AS jours_avec_iso0,
            min(iso0_min_m)                               AS iso0_min_m,
            min(jour_validite) FILTER (iso0_min_m = min_portee) AS date_iso0_min,
            max(iso0_max_m)                               AS iso0_max_m,
            min(jour_validite) FILTER (iso0_max_m = max_portee) AS date_iso0_max,
            round(avg(iso0_moyen_m), 0)                   AS iso0_moyen_m,
            median(iso0_moyen_m)                          AS iso0_median_m,
            {s}                                           AS seuil_iso0_m,
            count(*) FILTER (iso0_min_m > {s})            AS jours_iso0_au_dessus_seuil,
            count(*) FILTER (paire_dans_portee AND variation_iso0_24h_m IS NOT NULL)
                                                          AS paires_consecutives_iso0,
            count(*) FILTER (paire_dans_portee AND jour_precedent IS NOT NULL
                             AND variation_iso0_24h_m IS NULL) AS paires_ecartees_iso0,
            max(variation_iso0_24h_m) FILTER (paire_dans_portee) AS plus_forte_hausse_iso0_24h_m,
            min(variation_iso0_24h_m) FILTER (paire_dans_portee) AS plus_forte_baisse_iso0_24h_m,
            round(avg(abs(variation_iso0_24h_m)) FILTER (paire_dans_portee), 0)
                                                          AS amplitude_moyenne_iso0_24h_m,
            count(limite_pluie_neige_min_m)               AS jours_avec_limite_pluie_neige,
            min(limite_pluie_neige_min_m)                 AS limite_pluie_neige_min_m,
            median(limite_pluie_neige_min_m)              AS limite_pluie_neige_mediane_m
          FROM (
            SELECT *,
              min(iso0_min_m) OVER (PARTITION BY fenetre, saison, massif_id) AS min_portee,
              max(iso0_max_m) OVER (PARTITION BY fenetre, saison, massif_id) AS max_portee
            FROM portees
          )
          GROUP BY fenetre, saison, massif_id
        )
        SELECT
          st.* EXCLUDE (fenetre_comparable),
          st.fenetre_comparable AND x.motif_exclusion IS NULL AS comparable,
          x.motif_exclusion,
          {int(duree_min_jours)}                       AS duree_min_redoux_jours,
          coalesce(e.episodes_redoux, 0)               AS episodes_redoux,
          coalesce(e.redoux_rompus_par_trou, 0)        AS redoux_rompus_par_trou,
          coalesce(e.redoux_sans_franchissement_observe, 0) AS redoux_sans_franchissement_observe,
          coalesce(e.jours_en_redoux, 0)               AS jours_en_redoux,
          e.plus_long_redoux
        FROM stats st
        LEFT JOIN exclusions x USING (saison)
        LEFT JOIN episodes e USING (fenetre, saison, massif_id)
    """


def _sql_meteo_vent_tranche_jour() -> str:
    # Spec 5.3 : vent "massif x jour x tranche". Deux vents peuvent tomber dans
    # la meme tranche : 3000 et 4000 m (Haute-Tarentaise, Haute-Maurienne,
    # Vanoise, Mont-Blanc, Oisans), 2500 et 3500 m. La tranche retient alors,
    # pour le jour, la plus forte des deux vitesses et sa direction, et
    # `altitudes_vent` publie les altitudes qu'elle reunit : une tranche haute
    # a deux vents n'est pas comparable a une tranche haute a un seul. La
    # regle est ecrite ici une fois ; l'agregat saisonnier et les ecrans la
    # lisent au lieu de la recoder.
    return f"""
        SELECT
          saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
          date_bulletin, format_famille, {_fenetres()}, tranche,
          '{ORIGINE}'                                    AS origine,
          string_agg(DISTINCT CAST(altitude_m AS VARCHAR), '/'
                     ORDER BY CAST(altitude_m AS VARCHAR)) AS altitudes_vent,
          max(vitesse_max_kmh)                           AS vitesse_kmh,
          arg_max(direction_au_max, vitesse_max_kmh)     AS direction,
          sum(vitesses_hors_plage)                       AS vitesses_hors_plage
        FROM meteo_vent_jour
        WHERE tranche IS NOT NULL
        GROUP BY ALL
    """


def _sql_meteo_vent_saison(seuil_vent_kmh: int) -> str:
    v = int(seuil_vent_kmh)
    # La regle "deux vents dans une tranche" vit dans `meteo_vent_tranche_jour`.
    return f"""
        WITH par_jour AS (
          SELECT
            saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
            {_fenetres()}, tranche, vitesse_kmh, vitesses_hors_plage
          FROM meteo_vent_tranche_jour
        ),
        altitudes AS (
          SELECT saison, massif_id, tranche,
                 string_agg(DISTINCT CAST(altitude_m AS VARCHAR), '/'
                            ORDER BY CAST(altitude_m AS VARCHAR)) AS altitudes_vent
          FROM meteo_vent_jour WHERE tranche IS NOT NULL
          GROUP BY ALL
        ),
        portees AS (
          SELECT '{SAISON_COMPLETE}' AS fenetre, false AS fenetre_comparable, * FROM par_jour
          {"".join(f" UNION ALL BY NAME SELECT '{f.nom}' AS fenetre, {f.comparable_entre_saisons} AS fenetre_comparable, * FROM par_jour WHERE fenetre_{f.nom}" for f in FENETRES)}
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()})
        SELECT
          p.fenetre, p.saison, p.massif_id, p.tranche,
          any_value(p.saison_debut)                    AS saison_debut,
          any_value(p.massif_nom)                      AS massif_nom,
          any_value(p.zone)                            AS zone,
          '{ORIGINE}'                                  AS origine,
          any_value(p.fenetre_comparable) AND any_value(x.motif_exclusion) IS NULL AS comparable,
          any_value(x.motif_exclusion)                 AS motif_exclusion,
          any_value(a.altitudes_vent)                  AS altitudes_vent,
          {v}                                          AS seuil_vent_fort_kmh,
          count(*)                                     AS jours_avec_echeances,
          count(p.vitesse_kmh)                         AS jours_avec_vent,
          count(*) FILTER (p.vitesse_kmh > {v})        AS jours_vent_fort,
          max(p.vitesse_kmh)                           AS vitesse_max_kmh,
          median(p.vitesse_kmh)                        AS vitesse_mediane_kmh,
          sum(p.vitesses_hors_plage)                   AS vitesses_hors_plage
        FROM portees p
        LEFT JOIN altitudes a USING (saison, massif_id, tranche)
        LEFT JOIN exclusions x USING (saison)
        GROUP BY p.fenetre, p.saison, p.massif_id, p.tranche
    """


def _sql_meteo_temps_sensible() -> str:
    a, b = _H
    # La repartition se compte en echeances (deux par jour), pas en jours :
    # resumer un jour par un "pire" code supposerait un ordre entre brouillard,
    # averses et ciel couvert que la palette ne donne pas. Les codes hors
    # palette (5, 8, 9...) sont comptes avec un libelle nul (glossaire
    # section 7), pas ecartes.
    return f"""
        WITH echeances AS (
          SELECT saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
                 {_fenetres()}, temps_sensible_{a} AS code,
                 temps_sensible_libelle_{a} AS libelle
          FROM meteo_jour
          UNION ALL
          SELECT saison, saison_debut, massif_id, massif_nom, zone, jour_validite,
                 {_fenetres()}, temps_sensible_{b}, temps_sensible_libelle_{b}
          FROM meteo_jour
        ),
        portees AS (
          SELECT '{SAISON_COMPLETE}' AS fenetre, * FROM echeances
          {"".join(f" UNION ALL BY NAME SELECT '{f.nom}' AS fenetre, * FROM echeances WHERE fenetre_{f.nom}" for f in FENETRES)}
        ),
        comptes AS (
          SELECT fenetre, saison, massif_id, code,
                 any_value(saison_debut) AS saison_debut,
                 any_value(massif_nom) AS massif_nom, any_value(zone) AS zone,
                 any_value(libelle) AS libelle, count(*) AS echeances
          FROM portees WHERE code IS NOT NULL
          GROUP BY fenetre, saison, massif_id, code
        )
        SELECT
          fenetre, saison, saison_debut, massif_id, massif_nom, zone,
          '{ORIGINE}' AS origine,
          code AS temps_sensible, libelle AS temps_sensible_libelle,
          libelle IS NOT NULL AS dans_palette,
          echeances,
          sum(echeances) OVER (PARTITION BY fenetre, saison, massif_id) AS echeances_avec_code,
          round(echeances / sum(echeances) OVER (PARTITION BY fenetre, saison, massif_id), 4)
            AS part
        FROM comptes
    """


def creer_vues(
    con: duckdb.DuckDBPyConnection,
    *,
    temporaire: bool = False,
) -> tuple[str, ...]:
    """Pose les vues du bloc meteo, seuils par defaut.

    Requiert `risque_journalier`, `meteo`, `bulletins` et la vue `risque_jour`
    du bloc risque (risque avant et apres un redoux). `temporaire=True` les
    cree en vues temporaires, pour lire un entrepot construit avant T8 ouvert
    en lecture seule.
    """
    portee = "TEMP " if temporaire else ""
    for nom, sql in (
        ("meteo_jour", _sql_meteo_jour()),
        ("meteo_vent_jour", _sql_meteo_vent_jour()),
        ("meteo_vent_tranche_jour", _sql_meteo_vent_tranche_jour()),
        ("meteo_redoux", _sql_meteo_redoux(SEUIL_ISO0_M, DUREE_MIN_REDOUX_JOURS)),
        ("meteo_saison", _sql_meteo_saison(SEUIL_ISO0_M, DUREE_MIN_REDOUX_JOURS)),
        ("meteo_vent_saison", _sql_meteo_vent_saison(SEUIL_VENT_FORT_KMH)),
        ("meteo_temps_sensible", _sql_meteo_temps_sensible()),
    ):
        con.execute(f"CREATE OR REPLACE {portee}VIEW {nom} AS {sql}")
    return VUES


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def _assurer_vues(con: duckdb.DuckDBPyConnection) -> None:
    risque._assurer_vues(con)
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if not set(VUES) <= presentes:
        creer_vues(con, temporaire=True)


def _tranches(tranches: Sequence[str] | None, conditions: list[str], params: list[object]) -> None:
    if tranches is None:
        return
    connues = {t.nom for t in TRANCHES}
    inconnues = set(tranches) - connues
    if inconnues:
        raise ValueError(f"tranches inconnues : {sorted(inconnues)} (attendu : {sorted(connues)})")
    conditions.append(f"tranche IN ({', '.join('?' for _ in tranches) or 'NULL'})")
    params.extend(tranches)


def serie_jour(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Meteo prevue du jour (massif x jour couvert), lacunes etiquetees."""
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(
        con, f"SELECT * FROM meteo_jour{where} ORDER BY massif_id, jour_validite", params
    )


def vent_jour(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Vent prevu du jour par altitude et tranche (massif x jour x altitude)."""
    _assurer_vues(con)
    params: list[object] = []
    conditions: list[str] = []
    _filtres(massifs, saisons, conditions, params)
    _tranches(tranches, conditions, params)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return _frame(
        con,
        f"SELECT * FROM meteo_vent_jour{where} ORDER BY massif_id, jour_validite, altitude_m",
        params,
    )


def vent_tranche_jour(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Vent prevu du jour par tranche (massif x jour x tranche) : le plus fort
    des vents de la tranche, sa direction, et les altitudes reunies."""
    _assurer_vues(con)
    params: list[object] = []
    conditions: list[str] = []
    _filtres(massifs, saisons, conditions, params)
    _tranches(tranches, conditions, params)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return _frame(
        con,
        f"SELECT * FROM meteo_vent_tranche_jour{where} ORDER BY massif_id, jour_validite, tranche",
        params,
    )


def metriques_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    seuil_iso0_m: int = SEUIL_ISO0_M,
    duree_min_redoux_jours: int = DUREE_MIN_REDOUX_JOURS,
) -> pl.DataFrame:
    """Isotherme, variations, limite pluie-neige et redoux (massif x saison).

    Les seuils sont ceux de la vue `meteo_saison` par defaut ; tout autre
    seuil regenere la meme definition avec la valeur demandee.
    """
    _verifier_seuils(seuil_iso0_m=seuil_iso0_m, duree_min_redoux_jours=duree_min_redoux_jours)
    _assurer_vues(con)
    params: list[object] = [_portee(fenetre)]
    where = _filtres(massifs, saisons, ["fenetre = ?"], params)
    sql = _sql_meteo_saison(seuil_iso0_m, duree_min_redoux_jours)
    return _frame(con, f"SELECT * FROM ({sql}){where} ORDER BY massif_id, saison", params)


def vent_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
    seuil_vent_fort_kmh: int = SEUIL_VENT_FORT_KMH,
) -> pl.DataFrame:
    """Jours de vent fort et vitesses par tranche (massif x saison x tranche)."""
    _verifier_seuils(seuil_vent_fort_kmh=seuil_vent_fort_kmh)
    _assurer_vues(con)
    params: list[object] = [_portee(fenetre)]
    conditions = ["fenetre = ?"]
    _filtres(massifs, saisons, conditions, params)
    _tranches(tranches, conditions, params)
    sql = _sql_meteo_vent_saison(seuil_vent_fort_kmh)
    return _frame(
        con,
        f"SELECT * FROM ({sql}) WHERE {' AND '.join(conditions)} "
        "ORDER BY massif_id, saison, tranche",
        params,
    )


def temps_sensible(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Repartition des codes de temps sensible, avec libelles (en echeances)."""
    _assurer_vues(con)
    params: list[object] = [_portee(fenetre)]
    where = _filtres(massifs, saisons, ["fenetre = ?"], params)
    return _frame(
        con,
        f"SELECT * FROM meteo_temps_sensible{where} "
        "ORDER BY massif_id, saison, echeances DESC, temps_sensible",
        params,
    )


def episodes_redoux(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    seuil_iso0_m: int = SEUIL_ISO0_M,
    duree_min_redoux_jours: int = DUREE_MIN_REDOUX_JOURS,
    retenus_seulement: bool = True,
) -> pl.DataFrame:
    """Episodes de redoux, avec le risque de la veille, pendant et du lendemain.

    `retenus_seulement=False` rend aussi les suites trop courtes pour etre un
    episode (`retenu = false`).
    """
    _verifier_seuils(seuil_iso0_m=seuil_iso0_m, duree_min_redoux_jours=duree_min_redoux_jours)
    _assurer_vues(con)
    params: list[object] = []
    conditions = ["retenu"] if retenus_seulement else []
    where = _filtres(massifs, saisons, conditions, params)
    sql = _sql_meteo_redoux(seuil_iso0_m, duree_min_redoux_jours)
    return _frame(con, f"SELECT * FROM ({sql}){where} ORDER BY massif_id, debut", params)
