"""Bloc enneigement de la couche metriques (spec section 5.2, tache T7).

L'enneigement du BRA est **indicatif** : une epaisseur rattachee a une
altitude de reference, estimee par le previsionniste, pas une mesure de
station. Aucune sortie de ce module ne l'appelle une mesure ; les colonnes
disent `epaisseur`, `limite`, `cumul`, et les seuils appliques voyagent avec
les chiffres qu'ils produisent.

Deux series journalieres, chacune dedupliquee, puis les metriques qui s'en
deduisent :

- `enneigement_jour`         massif x jour : limites d'enneigement continu,
                             indicateur `sans_enneigement_continu_*` ;
- `enneigement_palier`       massif x jour x palier : epaisseur par versant,
                             tranche normee, ecart a la normale ;
- `enneigement_saison`       massif x saison x tranche x portee : jours
                             enneiges, maximum saisonnier et sa date ;
- `enneigement_continu`      massif x saison x versant : periode
                             d'enneigement continu (limite sous un seuil) ;
- `neige_fraiche_jour`       massif x jour : cumul de 24 h, une redaction par
                             jour -- contrat consomme par le bloc meteo (T8) ;
- `neige_fraiche_episode`    un episode de chute par ligne et par portee ;
- `neige_fraiche_saison`     massif x saison x tranche x portee : cumul,
                             jours de chute, plus forte chute.

Trois arbitrages sont faits ici, et chacun est journalise ou etiquete :

- **une redaction par jour.** Un meme jour de neige fraiche figure dans le
  bloc historique de six bulletins successifs ; un releve d'enneigement du
  jour peut etre redige deux fois (reedition de 16 h a 18 h). On retient la
  redaction la plus tardive, comme `risque_journalier`, et
  `log_neige_fraiche_discards()` / `log_enneigement_discards()` rejouent le
  meme tri pour journaliser chaque ligne ecartee ;
- **un horizon par serie.** L'epaisseur et la limite se lisent sur le releve
  du jour (`origine = 'jour'`), la neige fraiche sur le bloc historique
  (`origine = 'historique'`) : jamais l'un pour combler l'autre ;
- **un palier par tranche.** Huit massifs ont deux paliers dans la tranche
  basse (1000 et 1500 m), cinq en avaient deux dans la tranche moyenne
  jusqu'en 2021 (1800 et 2100 m). Les metriques par tranche lisent le palier le
  plus haut de la tranche (`palier_retenu`) ; l'autre reste dans
  `enneigement_palier`, etiquete, et sa normale se calcule a part.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

import duckdb
import polars as pl

from ..fenetres import FENETRES, SAISON_COMPLETE, sql_exclusions
from ..tranches import MOYENNE, sql_case as sql_case_tranche
from .risque import (
    MIN_SAISONS_NORMALE as MIN_SAISONS_NORMALE_RISQUE,
    _filtres,
    _frame,
    _portee,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------

# Seuil de limite d'enneigement continu, en metres. Par defaut, le plancher de
# la tranche moyenne (1800 m, `tranches.py`) : une limite sous ce seuil dit
# que toute la tranche moyenne est enneigee en continu. Repris de `tranches.py`
# plutot que recopie, pour que les deux ne divergent pas. `disponibilite.md`
# section 7 ne publie pas de distribution de limite ; le choix est donc un
# choix de lecture, pas un quantile -- il est publie avec chaque ligne.
SEUIL_LIMITE_M: int = MOYENNE.min_m or 1800

# Seuil d'epaisseur d'un jour enneige, en cm. 1 cm : la frontiere que
# l'archive elle-meme trace -- une limite `-1` sur un releve fait accompagne
# une epaisseur nulle a tous les paliers (2 903 releves du jour cote sud,
# glossaire section 4). C'est aussi la convention usuelle d'un sol enneige.
SEUIL_EPAISSEUR_CM: int = 1

# Seuil d'un jour de chute, en cm de `cumul_max_cm` sur 24 h. 20 cm est le
# p95 des cumuls historiques de la famille moderne (disponibilite.md section 7 :
# p50 0, p75 3, p90 10, p95 20, p99 40, max 120 cm, n = 138 917, non
# dedupliques). Le p90 (10 cm) ferait d'un jour sur dix un "episode".
SEUIL_CHUTE_CM: int = 20

# Plus long trou d'observation qui ne rompt pas une periode d'enneigement
# continu, en jours. Un jour sans releve ne dit pas que la limite est
# remontee ; un mois sans releve ne dit plus rien. Sur les 36 massifs, 844 des
# 910 trous du releve du jour durent 1 a 3 jours ; les suivants en durent 5 a
# 50 (confinement de 2020, interruptions de diffusion). 0 rend la regle des
# episodes de risque (un trou rompt tout).
TROU_TOLERE_JOURS: int = 3

# Normale d'enneigement : meme seuil que le bloc risque, pour la meme raison
# (le 29 fevrier n'a qu'une saison comparable).
MIN_SAISONS_NORMALE: int = MIN_SAISONS_NORMALE_RISQUE

# Decalage des dates du bloc historique de neige fraiche moderne (2024+), en
# jours. Le bloc principal `NEIGEFRAICHE` et le bloc historique d'avant 2024
# datent une fenetre de 24 h du meme jour : le cumul historique du jour D vaut
# celui du bloc principal du jour D dans 53 602 paires non nulles sur 54 107.
# Le bloc historique moderne date la meme fenetre au lendemain : son jour D+1
# vaut le jour D du bloc principal dans 31 254 paires non nulles sur 31 254,
# et son jour D dans 3 437 sur 52 961 seulement. Quelques dates y portent
# d'ailleurs 06:00 -- la fin de la fenetre 06 UTC -> 06 UTC. Sans ce decalage,
# la serie glisserait d'un jour a l'hiver 2023-2024, en plus de changer de
# lecture.
DECALAGE_HISTORIQUE_MODERNE_JOURS: int = 1

# Lecture d'un cumul selon la famille de format (glossaire section 5) : avant
# 2024, le plus fort de un ou deux secteurs nommes ; depuis, la borne haute
# d'une fourchette sur le massif.
LECTURE_CUMUL = {"legacy": "secteurs", "moderne": "fourchette"}

VERSANTS: tuple[str, ...] = ("nord", "sud")

# Tri d'arbitrage entre redactions d'un meme jour, du plus prioritaire au
# moins prioritaire, toutes decroissantes. Ecrit une fois : le SQL des vues et
# le tri polars des journaux en derivent, pour qu'ils ne divergent pas.
ORDRE_REDACTION: tuple[str, ...] = ("date_bulletin", "date_diffusion")

VUES: tuple[str, ...] = (
    "enneigement_jour",
    "enneigement_palier",
    "enneigement_saison",
    "enneigement_continu",
    "neige_fraiche_jour",
    "neige_fraiche_episode",
    "neige_fraiche_saison",
)


class RuptureDeSerie(ValueError):
    """Agregat de neige fraiche demande a cheval sur la rupture de 2023-2024."""


def _order_by(*suivantes: str) -> str:
    return ", ".join(f"{c} DESC" for c in (*ORDRE_REDACTION, *suivantes))


def _sql_lecture(col: str = "format_famille") -> str:
    return "CASE " + " ".join(
        f"WHEN {col} = '{k}' THEN '{v}'" for k, v in LECTURE_CUMUL.items()
    ) + " END"


def _sql_fenetres(jour: str = "jour", annee: str = "saison_debut") -> str:
    return ",\n            ".join(
        f"{f.sql_predicat(jour, annee)} AS fenetre_{f.nom}" for f in FENETRES
    )


# --------------------------------------------------------------------------
# Series journalieres
# --------------------------------------------------------------------------

def _sql_releve_retenu() -> str:
    """Lignes `enneigement` du releve du jour, une redaction par massif et jour.

    Le releve du jour est date par la source du jour de redaction (le BRA
    redige le 10 decrit le manteau du 10) : on l'indexe sur cette date, qui
    est celle que decrit la valeur, comme `palier_tranche`. `jour_validite` du
    bulletin source est conserve pour la jointure avec le risque.

    Le bloc historique n'est pas lu : il manque toute la saison 2015-2016, et
    reecrit le releve du jour dans 1 a 3 % des paliers. Le melanger au releve
    du jour ferait changer d'horizon d'un jour a l'autre.
    """
    return f"""
        SELECT * EXCLUDE (rang) FROM (
          SELECT
            e.saison, b.saison_debut, e.massif_id, b.massif_nom, b.zone,
            CAST(e.date_enneigement AS DATE) AS jour,
            e.date_bulletin, b.date_diffusion, b.jour_validite, b.fichier_source,
            b.format_famille,
            e.altitude_m, e.epaisseur_nord_cm, e.epaisseur_sud_cm,
            e.limite_nord_m, e.limite_sud_m,
            e.sans_enneigement_continu_nord, e.sans_enneigement_continu_sud,
            -- `dense_rank` et non `row_number` : on choisit un releve, et l'on
            -- garde ses trois paliers.
            dense_rank() OVER (
              PARTITION BY e.massif_id, CAST(e.date_enneigement AS DATE)
              ORDER BY {_order_by()}
            ) AS rang
          FROM enneigement e
          JOIN bulletins b USING (massif_id, date_bulletin)
          WHERE e.origine = 'jour' AND b.massif_coherent
        ) WHERE rang = 1
    """


def _sql_enneigement_jour() -> str:
    return f"""
        WITH r AS ({_sql_releve_retenu()}),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()})
        SELECT
          r.saison, any_value(r.saison_debut) AS saison_debut, r.massif_id,
          any_value(r.massif_nom) AS massif_nom, any_value(r.zone) AS zone, r.jour,
          any_value(r.jour_validite) AS jour_validite,
          any_value(r.date_bulletin) AS date_bulletin,
          any_value(r.fichier_source) AS fichier_source,
          any_value(r.format_famille) AS format_famille,
          -- Releve non fait : les trois paliers a `ALTI="-1"` avant 2024,
          -- altitude rendue nulle par le parser.
          count(r.altitude_m) > 0 AS releve_fait,
          count(r.altitude_m)     AS paliers,
          any_value(r.limite_nord_m) AS limite_nord_m,
          any_value(r.limite_sud_m)  AS limite_sud_m,
          any_value(r.sans_enneigement_continu_nord) AS sans_enneigement_continu_nord,
          any_value(r.sans_enneigement_continu_sud)  AS sans_enneigement_continu_sud,
          any_value(e.motif_exclusion) IS NULL AS saison_comparable,
          any_value(e.motif_exclusion) AS motif_exclusion,
          {_sql_fenetres('r.jour', 'any_value(r.saison_debut)')}
        FROM r LEFT JOIN exclusions e USING (saison)
        GROUP BY r.saison, r.massif_id, r.jour
    """


def _sql_enneigement_palier(min_saisons_normale: int) -> str:
    # Normale : mediane de l'epaisseur au meme jour du calendrier, pour le meme
    # massif et le *meme palier* (altitude), sur les saisons comparables -- les
    # choix de l'ecart a la normale du risque, a ceci pres :
    # - meme palier plutot que meme tranche : cinq massifs passent de 2100 a
    #   2000 m dans la tranche moyenne en 2021 ; une normale par tranche
    #   melangerait deux altitudes ;
    # - toute la saison plutot que `coeur` : la fenetre corrige la sentinelle
    #   `RISQUE1=-1`, qui ne touche pas l'enneigement. Le seuil de saisons suffit
    #   a ecarter les dates trop peu couvertes (debut novembre, juin).
    versants = ",\n          ".join(
        f"median(epaisseur_{v}_cm) AS mediane_{v},\n"
        f"          count(DISTINCT saison) FILTER (epaisseur_{v}_cm IS NOT NULL) AS saisons_{v}"
        for v in VERSANTS
    )
    colonnes = ",\n          ".join(
        f"n.saisons_{v} AS saisons_normale_{v},\n"
        f"          CASE WHEN n.saisons_{v} >= {int(min_saisons_normale)} "
        f"THEN n.mediane_{v} END AS normale_{v}_cm,\n"
        f"          CASE WHEN p.saison_comparable AND n.saisons_{v} >= {int(min_saisons_normale)} "
        f"THEN p.epaisseur_{v}_cm - n.mediane_{v} END AS ecart_normale_{v}_cm"
        for v in VERSANTS
    )
    return f"""
        WITH r AS ({_sql_releve_retenu()}),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()}),
        p AS (
          SELECT
            r.saison, r.saison_debut, r.massif_id, r.massif_nom, r.zone, r.jour,
            r.jour_validite, r.date_bulletin, r.format_famille,
            r.altitude_m,
            {sql_case_tranche('r.altitude_m')} AS tranche,
            r.epaisseur_nord_cm, r.epaisseur_sud_cm,
            e.motif_exclusion IS NULL AS saison_comparable,
            e.motif_exclusion,
            {_sql_fenetres('r.jour', 'r.saison_debut')}
          FROM r LEFT JOIN exclusions e USING (saison)
          WHERE r.altitude_m IS NOT NULL
        ),
        normales AS (
          SELECT massif_id, altitude_m, strftime(jour, '%m-%d') AS jour_annee,
          {versants}
          FROM p
          WHERE saison_comparable
          GROUP BY massif_id, altitude_m, jour_annee
        )
        SELECT
          p.*,
          -- Le palier le plus haut de sa tranche : 1500 m plutot que 1000 m
          -- dans la tranche basse, 2100 m plutot que 1800 m dans la moyenne.
          -- Il donne a chaque tranche une altitude homogene entre massifs
          -- (1500 m en basse partout) et entre epoques (2100 puis 2000 m).
          p.tranche IS NOT NULL AND p.altitude_m = max(p.altitude_m) OVER (
            PARTITION BY p.massif_id, p.jour, p.tranche) AS palier_retenu,
          count(*) OVER (PARTITION BY p.massif_id, p.jour, p.tranche) AS paliers_dans_tranche,
          {colonnes}
        FROM p
        LEFT JOIN normales n
          ON n.massif_id = p.massif_id
         AND n.altitude_m = p.altitude_m
         AND n.jour_annee = strftime(p.jour, '%m-%d')
    """


def _sql_neige_fraiche_jour() -> str:
    # Un meme jour figure dans le bloc historique de six bulletins successifs.
    # On retient la redaction la plus tardive, comme `risque_journalier` ; le
    # dernier critere departage deux lignes d'un meme bulletin (jamais vu sur
    # l'archive, mais un `row_number` sans ordre total serait non
    # deterministe). `log_neige_fraiche_discards()` rejoue ce tri.
    #
    # Le bloc de prevision n'est pas lu : il melangerait un horizon prevu a un
    # horizon analyse. La saison 2015-2016, sans bloc historique, n'a donc pas
    # de neige fraiche.
    return f"""
        WITH n AS (
          SELECT
            n.saison, b.saison_debut, n.massif_id, b.massif_nom, b.zone,
            CAST(n.date_cumul AS DATE) - CASE WHEN b.format_famille = 'moderne'
              THEN {int(DECALAGE_HISTORIQUE_MODERNE_JOURS)} ELSE 0 END AS jour,
            n.date_cumul AS date_cumul_source,
            n.cumul_min_cm, n.cumul_max_cm,
            n.altitude_mesure_m AS altitude_m,
            n.secteur1_libelle, n.secteur1_cumul_cm,
            n.secteur2_libelle, n.secteur2_cumul_cm,
            b.format_famille,
            n.date_bulletin, b.date_diffusion, b.fichier_source
          FROM neige_fraiche n
          JOIN bulletins b USING (massif_id, date_bulletin)
          WHERE n.origine = 'historique' AND b.massif_coherent
        ),
        classees AS (
          SELECT *,
            row_number() OVER w AS rang,
            count(*) OVER (PARTITION BY massif_id, jour) AS redactions,
            -- `IS DISTINCT FROM` : un cumul observe puis non observe est une
            -- divergence, pas un accord.
            count(DISTINCT coalesce(CAST(cumul_max_cm AS VARCHAR), 'nul'))
              OVER (PARTITION BY massif_id, jour) > 1 AS redactions_divergentes
          FROM n
          WINDOW w AS (PARTITION BY massif_id, jour ORDER BY {_order_by('date_cumul_source')})
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()})
        SELECT
          c.saison, c.saison_debut, c.massif_id, c.massif_nom, c.zone, c.jour,
          c.cumul_min_cm, c.cumul_max_cm,
          c.altitude_m,
          {sql_case_tranche('c.altitude_m')} AS tranche,
          c.format_famille,
          {_sql_lecture('c.format_famille')} AS lecture_cumul,
          c.secteur1_libelle, c.secteur1_cumul_cm, c.secteur2_libelle, c.secteur2_cumul_cm,
          c.date_cumul_source, c.date_bulletin, c.fichier_source,
          c.redactions, c.redactions_divergentes,
          e.motif_exclusion IS NULL AS saison_comparable,
          e.motif_exclusion,
          {_sql_fenetres('c.jour', 'c.saison_debut')}
        FROM classees c LEFT JOIN exclusions e USING (saison)
        WHERE c.rang = 1
    """


# --------------------------------------------------------------------------
# Metriques saisonnieres
# --------------------------------------------------------------------------

def _portees(source: str, filtre: str = "true") -> str:
    """Les lignes de `source`, une fois par portee (saison entiere + fenetres)."""
    parts = [
        f"SELECT '{SAISON_COMPLETE}' AS fenetre, CAST(NULL AS BIGINT) AS jours_fenetre, * "
        f"FROM {source} WHERE {filtre}"
    ]
    parts += [
        f"SELECT '{f.nom}' AS fenetre, {f.sql_duree()} AS jours_fenetre, * "
        f"FROM {source} WHERE {filtre} AND fenetre_{f.nom}"
        for f in FENETRES
    ]
    return "\n          UNION ALL BY NAME\n          ".join(parts)


def _sql_enneigement_saison(seuil_epaisseur_cm: int) -> str:
    seuil = int(seuil_epaisseur_cm)
    par_versant = ",\n            ".join(
        f"count(epaisseur_{v}_cm) AS jours_observes_{v},\n"
        f"            count(*) FILTER (epaisseur_{v}_cm >= {seuil}) AS jours_enneiges_{v},\n"
        f"            max(epaisseur_{v}_cm) AS epaisseur_max_{v}_cm,\n"
        # Le premier jour au maximum ; `jours_au_max_*` dit s'il y en a d'autres.
        f"            min(jour) FILTER (epaisseur_{v}_cm = max_{v}) AS date_max_{v},\n"
        f"            count(*) FILTER (epaisseur_{v}_cm = max_{v}) AS jours_au_max_{v}"
        for v in VERSANTS
    )
    maxima = ", ".join(
        f"max(epaisseur_{v}_cm) OVER (PARTITION BY fenetre, saison, massif_id, tranche) AS max_{v}"
        for v in VERSANTS
    )
    return f"""
        WITH portees AS (
          {_portees('enneigement_palier', 'palier_retenu')}
        ),
        marquees AS (SELECT *, {maxima} FROM portees),
        spans AS (
          SELECT saison, massif_id,
                 date_diff('day', min(jour), max(jour)) + 1 AS jours_saison
          FROM enneigement_jour GROUP BY saison, massif_id
        ),
        stats AS (
          SELECT
            fenetre, saison, massif_id, tranche,
            any_value(saison_debut) AS saison_debut,
            any_value(massif_nom)   AS massif_nom,
            any_value(zone)         AS zone,
            -- Une portee nommee compare des periodes de meme duree ; la saison
            -- entiere, non (bornes brutes).
            fenetre <> '{SAISON_COMPLETE}' AND bool_and(saison_comparable) AS comparable,
            any_value(motif_exclusion) AS motif_exclusion,
            min(altitude_m) AS altitude_min_m,
            max(altitude_m) AS altitude_max_m,
            {seuil} AS seuil_epaisseur_cm,
            any_value(jours_fenetre) AS jours_fenetre,
            count(*) AS jours_releves,
            {par_versant}
          FROM marquees
          GROUP BY fenetre, saison, massif_id, tranche
        )
        SELECT
          s.* EXCLUDE (jours_fenetre),
          coalesce(s.jours_fenetre, sp.jours_saison) AS jours_periode,
          round(100.0 * s.jours_releves / coalesce(s.jours_fenetre, sp.jours_saison), 1)
            AS couverture_pct
        FROM stats s LEFT JOIN spans sp USING (saison, massif_id)
    """


def _sql_enneigement_continu(seuil_limite_m: int, trou_tolere_jours: int) -> str:
    # Periode d'enneigement continu : la plus longue suite de jours observes ou
    # la limite est sous le seuil. Etat d'un jour, par versant :
    # - `sous`   : limite < seuil ;
    # - `dessus` : limite >= seuil, ou `sans_enneigement_continu` vrai -- une
    #              limite nulle sur un releve fait n'est PAS une lacune ;
    # - inconnu  : releve non fait, ou indicateur nul. Le jour n'entre pas dans
    #              la suite, comme un trou d'archive.
    # Seul un jour `dessus` rompt une periode, ou un trou de plus de
    # `trou_tolere_jours` jours. Les jours non observes interieurs sont comptes.
    seuil, tolere = int(seuil_limite_m), int(trou_tolere_jours)
    etats = "\n          UNION ALL\n          ".join(
        f"SELECT saison, massif_id, jour, '{v}' AS versant,\n"
        f"            CASE WHEN limite_{v}_m < {seuil} THEN true\n"
        f"                 WHEN limite_{v}_m >= {seuil} OR sans_enneigement_continu_{v} THEN false\n"
        f"            END AS sous\n"
        f"          FROM enneigement_jour WHERE releve_fait"
        for v in VERSANTS
    )
    return f"""
        WITH etats AS (
          SELECT * FROM (
          {etats}
          ) WHERE sous IS NOT NULL
        ),
        suites AS (
          SELECT *,
            sum(CAST(sous AND NOT coalesce(prec_sous AND ecart - 1 <= {tolere}, false) AS INTEGER))
              OVER (PARTITION BY saison, massif_id, versant ORDER BY jour
                    ROWS UNBOUNDED PRECEDING) AS periode
          FROM (
            SELECT *,
              lag(sous) OVER w AS prec_sous,
              date_diff('day', lag(jour) OVER w, jour) AS ecart
            FROM etats
            WINDOW w AS (PARTITION BY saison, massif_id, versant ORDER BY jour)
          )
        ),
        periodes AS (
          SELECT saison, massif_id, versant, periode,
                 min(jour) AS debut, max(jour) AS fin, count(*) AS jours_sous_seuil
          FROM suites WHERE sous
          GROUP BY saison, massif_id, versant, periode
        ),
        bilan AS (
          SELECT saison, massif_id, versant,
                 count(*) AS jours_observes,
                 count(*) FILTER (sous) AS jours_sous_seuil_saison
          FROM etats GROUP BY saison, massif_id, versant
        ),
        plus_longue AS (
          SELECT saison, massif_id, versant,
                 count(*) AS periodes,
                 arg_max(debut, (date_diff('day', debut, fin), -epoch(debut))) AS debut,
                 arg_max(fin,   (date_diff('day', debut, fin), -epoch(debut))) AS fin,
                 arg_max(jours_sous_seuil, (date_diff('day', debut, fin), -epoch(debut)))
                   AS jours_observes_periode
          FROM periodes GROUP BY saison, massif_id, versant
        ),
        exclusions(saison, motif_exclusion) AS (VALUES {sql_exclusions()})
        SELECT
          b.saison, b.massif_id, b.versant,
          {seuil} AS seuil_limite_m,
          {tolere} AS trou_tolere_jours,
          p.debut AS debut_enneigement_continu,
          p.fin   AS fin_enneigement_continu,
          date_diff('day', p.debut, p.fin) + 1 AS duree_jours,
          p.jours_observes_periode,
          date_diff('day', p.debut, p.fin) + 1 - p.jours_observes_periode
            AS jours_non_observes_periode,
          coalesce(p.periodes, 0) AS periodes,
          b.jours_sous_seuil_saison,
          b.jours_observes,
          e.motif_exclusion IS NULL AS saison_comparable,
          e.motif_exclusion
        FROM bilan b
        LEFT JOIN plus_longue p USING (saison, massif_id, versant)
        LEFT JOIN exclusions e USING (saison)
    """


def _sql_neige_fraiche_episode(seuil_chute_cm: int) -> str:
    # Un episode de chute : une suite de jours *consecutifs au calendrier* a
    # `cumul_max_cm >= seuil`. Comme pour le risque, un trou d'archive rompt
    # l'episode (`rompu_par_trou`) et un jour present mais non observe le borde
    # (`borde_non_observe`) : on ne sait pas si la chute continuait. Les suites
    # se calculent dans chaque portee : une fenetre rogne l'episode qui
    # chevauche sa borne.
    seuil = int(seuil_chute_cm)
    return f"""
        WITH portees AS (
          {_portees('neige_fraiche_jour')}
        ),
        base AS (
          SELECT *,
            coalesce(cumul_max_cm >= {seuil}, false) AS chute,
            lag(jour) OVER w AS jour_prec, lag(cumul_max_cm) OVER w AS cumul_prec,
            lead(jour) OVER w AS jour_suiv, lead(cumul_max_cm) OVER w AS cumul_suiv
          FROM portees
          WINDOW w AS (PARTITION BY fenetre, saison, massif_id ORDER BY jour)
        ),
        numerotees AS (
          SELECT *,
            sum(CAST(chute AND NOT coalesce(date_diff('day', jour_prec, jour) = 1
                                            AND cumul_prec >= {seuil}, false) AS INTEGER))
              OVER (PARTITION BY fenetre, saison, massif_id ORDER BY jour
                    ROWS UNBOUNDED PRECEDING) AS episode
          FROM base
        )
        SELECT
          fenetre, saison, massif_id, episode,
          any_value(saison_debut) AS saison_debut,
          {seuil} AS seuil_chute_cm,
          min(jour) AS debut, max(jour) AS fin, count(*) AS duree_jours,
          sum(cumul_max_cm) AS cumul_max_cm,
          sum(cumul_min_cm) AS cumul_min_cm,
          max(cumul_max_cm) AS plus_forte_chute_cm,
          string_agg(DISTINCT tranche, ',' ORDER BY tranche) AS tranches,
          any_value(lecture_cumul) AS lecture_cumul,
          arg_min(coalesce(date_diff('day', jour_prec, jour) > 1, false), jour)
            OR arg_max(coalesce(date_diff('day', jour, jour_suiv) > 1, false), jour)
            AS rompu_par_trou,
          arg_min(coalesce(date_diff('day', jour_prec, jour) = 1 AND cumul_prec IS NULL, false), jour)
            OR arg_max(coalesce(date_diff('day', jour, jour_suiv) = 1 AND cumul_suiv IS NULL, false), jour)
            AS borde_non_observe
        FROM numerotees
        WHERE chute
        GROUP BY fenetre, saison, massif_id, episode
    """


def _sql_neige_fraiche_saison(seuil_chute_cm: int) -> str:
    seuil = int(seuil_chute_cm)
    return f"""
        WITH portees AS (
          {_portees('neige_fraiche_jour')}
        ),
        spans AS (
          SELECT saison, massif_id,
                 date_diff('day', min(jour), max(jour)) + 1 AS jours_saison
          FROM neige_fraiche_jour GROUP BY saison, massif_id
        ),
        marquees AS (
          SELECT *, max(cumul_max_cm) OVER (PARTITION BY fenetre, saison, massif_id, tranche) AS max_portee
          FROM portees
        ),
        stats AS (
          SELECT
            fenetre, saison, massif_id, tranche,
            any_value(saison_debut) AS saison_debut,
            any_value(massif_nom)   AS massif_nom,
            any_value(zone)         AS zone,
            fenetre <> '{SAISON_COMPLETE}' AND bool_and(saison_comparable) AS comparable,
            any_value(motif_exclusion) AS motif_exclusion,
            -- La rupture de serie de l'hiver 2023-2024 voyage avec le chiffre :
            -- une ligne ne melange jamais deux lectures sans le dire.
            string_agg(DISTINCT lecture_cumul, ',' ORDER BY lecture_cumul) AS lecture_cumul,
            count(DISTINCT lecture_cumul) > 1 AS rupture_de_serie,
            min(altitude_m) AS altitude_min_m,
            max(altitude_m) AS altitude_max_m,
            {seuil} AS seuil_chute_cm,
            any_value(jours_fenetre) AS jours_fenetre,
            count(*) AS jours_couverts,
            count(cumul_max_cm) AS jours_observes,
            -- Un jour non observe (`-2` d'avant 2024 : 15 a 21 % des lignes)
            -- ne compte pas zero : le cumul est un minorant, publie a cote.
            count(*) - count(cumul_max_cm) AS jours_non_observes,
            sum(cumul_max_cm) AS cumul_max_cm,
            sum(cumul_min_cm) AS cumul_min_cm,
            count(*) FILTER (cumul_max_cm >= {seuil}) AS jours_chute,
            max(cumul_max_cm) AS plus_forte_chute_cm,
            min(jour) FILTER (cumul_max_cm = max_portee) AS date_plus_forte_chute,
            count(*) FILTER (cumul_max_cm = max_portee) AS jours_au_max
          FROM marquees
          GROUP BY fenetre, saison, massif_id, tranche
        ),
        -- Un episode est rattache a la tranche de son premier jour.
        episodes AS (
          SELECT
            ep.fenetre, ep.saison, ep.massif_id,
            j.tranche,
            count(*) AS episodes_chute,
            count(*) FILTER (ep.rompu_par_trou) AS episodes_rompus_par_trou,
            count(*) FILTER (ep.borde_non_observe) AS episodes_bordes_non_observe,
            max(ep.duree_jours) AS plus_long_episode
          FROM ({_sql_neige_fraiche_episode(seuil)}) ep
          JOIN neige_fraiche_jour j
            ON j.massif_id = ep.massif_id AND j.jour = ep.debut
          GROUP BY ep.fenetre, ep.saison, ep.massif_id, j.tranche
        )
        SELECT
          s.* EXCLUDE (jours_fenetre),
          coalesce(e.episodes_chute, 0) AS episodes_chute,
          coalesce(e.episodes_rompus_par_trou, 0) AS episodes_rompus_par_trou,
          coalesce(e.episodes_bordes_non_observe, 0) AS episodes_bordes_non_observe,
          e.plus_long_episode,
          coalesce(s.jours_fenetre, sp.jours_saison) AS jours_periode,
          round(100.0 * s.jours_couverts / coalesce(s.jours_fenetre, sp.jours_saison), 1)
            AS couverture_pct
        FROM stats s
        LEFT JOIN episodes e
          ON e.fenetre = s.fenetre AND e.saison = s.saison AND e.massif_id = s.massif_id
         AND e.tranche IS NOT DISTINCT FROM s.tranche
        LEFT JOIN spans sp ON sp.saison = s.saison AND sp.massif_id = s.massif_id
    """


def creer_vues(
    con: duckdb.DuckDBPyConnection,
    *,
    temporaire: bool = False,
    min_saisons_normale: int = MIN_SAISONS_NORMALE,
    seuil_epaisseur_cm: int = SEUIL_EPAISSEUR_CM,
    seuil_limite_m: int = SEUIL_LIMITE_M,
    trou_tolere_jours: int = TROU_TOLERE_JOURS,
    seuil_chute_cm: int = SEUIL_CHUTE_CM,
) -> tuple[str, ...]:
    """Pose les vues du bloc enneigement sur une base qui a les tables brutes.

    `temporaire=True` les cree en vues temporaires : c'est ce qui permet de
    lire un entrepot construit avant T7, ouvert en lecture seule.
    """
    portee = "TEMP " if temporaire else ""
    for nom, sql in (
        ("enneigement_jour", _sql_enneigement_jour()),
        ("enneigement_palier", _sql_enneigement_palier(min_saisons_normale)),
        ("enneigement_saison", _sql_enneigement_saison(seuil_epaisseur_cm)),
        ("enneigement_continu", _sql_enneigement_continu(seuil_limite_m, trou_tolere_jours)),
        ("neige_fraiche_jour", _sql_neige_fraiche_jour()),
        ("neige_fraiche_episode", _sql_neige_fraiche_episode(seuil_chute_cm)),
        ("neige_fraiche_saison", _sql_neige_fraiche_saison(seuil_chute_cm)),
    ):
        con.execute(f"CREATE OR REPLACE {portee}VIEW {nom} AS {sql}")
    return VUES


# --------------------------------------------------------------------------
# Journal des redactions ecartees
# --------------------------------------------------------------------------

def _redactions(enfant: pl.DataFrame, bulletins: pl.DataFrame) -> pl.DataFrame:
    return enfant.join(
        bulletins.select(
            "massif_id", "date_bulletin", "date_diffusion", "massif_coherent",
            "format_famille", "fichier_source",
        ),
        on=["massif_id", "date_bulletin"],
        how="left",
    )


def neige_fraiche_discards(neige_fraiche: pl.DataFrame, bulletins: pl.DataFrame) -> pl.DataFrame:
    """Les lignes historiques de neige fraiche que `neige_fraiche_jour` laisse de cote.

    Rejoue l'arbitrage de la vue : meme jour (decalage moderne compris), meme
    tri (`ORDRE_REDACTION`, puis la date source). Toute evolution de l'un doit
    se repercuter dans l'autre ; le test d'accord entre journal et vue le
    verrouille. `identique` dit si la ligne ecartee porte le meme cumul que la
    ligne retenue -- une simple repetition -- ou une valeur differente.
    """
    cols = ["saison", "massif_id", "jour", "date_bulletin", "date_diffusion",
            "date_cumul", "altitude_mesure_m", "cumul_min_cm", "cumul_max_cm",
            "fichier_source"]
    vide = pl.DataFrame(schema={
        "saison": pl.Utf8, "massif_id": pl.Int32, "jour": pl.Date,
        "date_bulletin": pl.Datetime("us"), "date_diffusion": pl.Datetime("us"),
        "date_cumul": pl.Datetime("us"), "altitude_mesure_m": pl.Int32,
        "cumul_min_cm": pl.Int16, "cumul_max_cm": pl.Int16, "fichier_source": pl.Utf8,
        "cumul_max_retenu_cm": pl.Int16, "redaction_retenue": pl.Datetime("us"),
        "identique": pl.Boolean, "motif": pl.Utf8,
    })
    hist = neige_fraiche.filter(pl.col("origine") == "historique")
    if not hist.height:
        return vide
    df = _redactions(hist, bulletins).with_columns(
        jour=pl.col("date_cumul").dt.date()
        - pl.when(pl.col("format_famille") == "moderne")
        .then(pl.duration(days=DECALAGE_HISTORIQUE_MODERNE_JOURS))
        .otherwise(pl.duration(days=0))
    )
    hors = df.filter(~pl.col("massif_coherent").fill_null(False)).with_columns(
        cumul_max_retenu_cm=pl.lit(None, pl.Int16),
        redaction_retenue=pl.lit(None, pl.Datetime("us")),
        identique=pl.lit(None, pl.Boolean),
        motif=pl.lit("bulletin hors perimetre : ID et libelle se contredisent"),
    )
    ordre = [*ORDRE_REDACTION, "date_cumul"]
    classees = (
        df.filter(pl.col("massif_coherent").fill_null(False))
        .sort(ordre, descending=True, nulls_last=True)
        .with_columns(
            rang=pl.int_range(pl.len()).over(["massif_id", "jour"]),
            cumul_max_retenu_cm=pl.col("cumul_max_cm").first().over(["massif_id", "jour"]),
            redaction_retenue=pl.col("date_bulletin").first().over(["massif_id", "jour"]),
        )
        .filter(pl.col("rang") > 0)
        .with_columns(
            identique=pl.col("cumul_max_cm").eq_missing(pl.col("cumul_max_retenu_cm")),
            motif=pl.lit("jour deja decrit par une redaction plus tardive"),
        )
    )
    fin = [*cols, "cumul_max_retenu_cm", "redaction_retenue", "identique", "motif"]
    return pl.concat([hors.select(fin), classees.select(fin)]).sort(
        ["saison", "massif_id", "jour", "date_bulletin"]
    )


def enneigement_discards(enneigement: pl.DataFrame, bulletins: pl.DataFrame) -> pl.DataFrame:
    """Les lignes du releve du jour que `enneigement_jour` laisse de cote.

    Un releve est ecarte en bloc (ses trois paliers) quand un autre releve du
    meme massif, date du meme jour, a ete redige plus tard -- reedition de 16 h
    a 18 h, ou bulletin dont le releve porte la date de la veille.
    """
    cols = ["saison", "massif_id", "jour", "date_bulletin", "date_diffusion",
            "altitude_m", "epaisseur_nord_cm", "epaisseur_sud_cm",
            "limite_nord_m", "limite_sud_m", "fichier_source"]
    vide = pl.DataFrame(schema={
        "saison": pl.Utf8, "massif_id": pl.Int32, "jour": pl.Date,
        "date_bulletin": pl.Datetime("us"), "date_diffusion": pl.Datetime("us"),
        "altitude_m": pl.Int32, "epaisseur_nord_cm": pl.Int32, "epaisseur_sud_cm": pl.Int32,
        "limite_nord_m": pl.Int32, "limite_sud_m": pl.Int32, "fichier_source": pl.Utf8,
        "redaction_retenue": pl.Datetime("us"), "motif": pl.Utf8,
    })
    jour = enneigement.filter(pl.col("origine") == "jour")
    if not jour.height:
        return vide
    df = _redactions(jour, bulletins).with_columns(jour=pl.col("date_enneigement").dt.date())
    hors = df.filter(~pl.col("massif_coherent").fill_null(False)).with_columns(
        redaction_retenue=pl.lit(None, pl.Datetime("us")),
        motif=pl.lit("bulletin hors perimetre : ID et libelle se contredisent"),
    )
    # Le rang porte sur les redactions (bulletins), pas sur les lignes : c'est
    # le `dense_rank` de la vue.
    redac = (
        df.filter(pl.col("massif_coherent").fill_null(False))
        .select("massif_id", "jour", *ORDRE_REDACTION)
        .unique()
        .sort(list(ORDRE_REDACTION), descending=True, nulls_last=True)
        .with_columns(
            rang=pl.int_range(pl.len()).over(["massif_id", "jour"]),
            redaction_retenue=pl.col("date_bulletin").first().over(["massif_id", "jour"]),
        )
        .filter(pl.col("rang") > 0)
    )
    ecartees = df.join(
        redac.select("massif_id", "jour", "date_bulletin", "redaction_retenue"),
        on=["massif_id", "jour", "date_bulletin"],
        how="inner",
    ).with_columns(motif=pl.lit("releve deja donne par une redaction plus tardive"))
    fin = [*cols, "redaction_retenue", "motif"]
    return pl.concat([hors.select(fin), ecartees.select(fin)]).sort(
        ["saison", "massif_id", "jour", "date_bulletin", "altitude_m"]
    )


def log_neige_fraiche_discards(neige_fraiche: pl.DataFrame, bulletins: pl.DataFrame) -> tuple[int, int]:
    """Journalise chaque ligne de neige fraiche ecartee ; rend (ecartees, divergentes).

    Une ligne de journal par ligne perdue. Le niveau depend de ce qui est
    perdu : une repetition a l'identique de la valeur retenue (366 000 lignes
    environ sur l'archive, six redactions par jour) part en DEBUG ; une valeur
    differente, ou une ligne hors perimetre, part en WARNING. Les deux sont
    ecrites ligne a ligne -- c'est le volume, pas la trace, qui change.
    """
    discards = neige_fraiche_discards(neige_fraiche, bulletins)
    divergentes = 0
    for row in discards.iter_rows(named=True):
        identique = row["identique"] is True
        if not identique:
            divergentes += 1
        logger.log(
            logging.DEBUG if identique else logging.WARNING,
            "neige fraiche : redaction ecartee -- massif=%s jour=%s redige=%s "
            "cumul_max=%s retenu=%s (redige=%s) altitude=%s motif=%s source=%s",
            row["massif_id"], row["jour"], row["date_bulletin"], row["cumul_max_cm"],
            row["cumul_max_retenu_cm"], row["redaction_retenue"], row["altitude_mesure_m"],
            row["motif"], row["fichier_source"],
        )
    return discards.height, divergentes


def log_enneigement_discards(enneigement: pl.DataFrame, bulletins: pl.DataFrame) -> int:
    """Journalise en WARNING chaque ligne du releve du jour ecartee."""
    discards = enneigement_discards(enneigement, bulletins)
    for row in discards.iter_rows(named=True):
        logger.warning(
            "enneigement : releve ecarte -- massif=%s jour=%s redige=%s retenu=%s "
            "altitude=%s epaisseur_n=%s epaisseur_s=%s motif=%s source=%s",
            row["massif_id"], row["jour"], row["date_bulletin"], row["redaction_retenue"],
            row["altitude_m"], row["epaisseur_nord_cm"], row["epaisseur_sud_cm"],
            row["motif"], row["fichier_source"],
        )
    return discards.height


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def _assurer_vues(con: duckdb.DuckDBPyConnection) -> None:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if not set(VUES) <= presentes:
        creer_vues(con, temporaire=True)


def _source(vue: str, sql: str | None) -> str:
    """La vue posee avec les seuils par defaut, ou la requete aux seuils demandes."""
    return vue if sql is None else f"({sql})"


def _where(
    massifs: Sequence[int] | None,
    saisons: Sequence[str] | None,
    tranches: Sequence[str] | None,
    conditions: list[str],
    params: list[object],
) -> str:
    if tranches is not None:
        conditions.append(f"tranche IN ({', '.join('?' for _ in tranches) or 'NULL'})")
        params.extend(tranches)
    return _filtres(massifs, saisons, conditions, params)


def releves(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Limites d'enneigement continu et indicateur d'absence (massif x jour)."""
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(con, f"SELECT * FROM enneigement_jour{where} ORDER BY massif_id, jour", params)


def paliers(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Epaisseur par palier et par tranche, ecart a la normale (massif x jour x palier)."""
    _assurer_vues(con)
    params: list[object] = []
    where = _where(massifs, saisons, tranches, [], params)
    return _frame(
        con,
        f"SELECT * FROM enneigement_palier{where} ORDER BY massif_id, jour, altitude_m",
        params,
    )


def metriques_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
    seuil_epaisseur_cm: int | None = None,
) -> pl.DataFrame:
    """Jours enneiges et maximum saisonnier, massif x saison x tranche, sur une portee."""
    _assurer_vues(con)
    sql = None if seuil_epaisseur_cm is None else _sql_enneigement_saison(seuil_epaisseur_cm)
    params: list[object] = [_portee(fenetre)]
    where = _where(massifs, saisons, tranches, ["fenetre = ?"], params)
    return _frame(
        con,
        f"SELECT * FROM {_source('enneigement_saison', sql)}{where} "
        "ORDER BY massif_id, saison, tranche",
        params,
    )


def enneigement_continu(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    seuil_limite_m: int | None = None,
    trou_tolere_jours: int | None = None,
) -> pl.DataFrame:
    """Periode d'enneigement continu, massif x saison x versant."""
    _assurer_vues(con)
    sql = None
    if seuil_limite_m is not None or trou_tolere_jours is not None:
        sql = _sql_enneigement_continu(
            SEUIL_LIMITE_M if seuil_limite_m is None else seuil_limite_m,
            TROU_TOLERE_JOURS if trou_tolere_jours is None else trou_tolere_jours,
        )
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(
        con,
        f"SELECT * FROM {_source('enneigement_continu', sql)}{where} "
        "ORDER BY massif_id, saison, versant",
        params,
    )


def neige_fraiche(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Cumul de neige fraiche du jour, une redaction par jour (massif x jour)."""
    _assurer_vues(con)
    params: list[object] = []
    where = _filtres(massifs, saisons, [], params)
    return _frame(con, f"SELECT * FROM neige_fraiche_jour{where} ORDER BY massif_id, jour", params)


def episodes_chute(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    seuil_chute_cm: int | None = None,
) -> pl.DataFrame:
    """Episodes de chute, un par ligne."""
    _assurer_vues(con)
    sql = None if seuil_chute_cm is None else _sql_neige_fraiche_episode(seuil_chute_cm)
    params: list[object] = [_portee(fenetre)]
    where = _filtres(massifs, saisons, ["fenetre = ?"], params)
    return _frame(
        con,
        f"SELECT * FROM {_source('neige_fraiche_episode', sql)}{where} ORDER BY massif_id, debut",
        params,
    )


def neige_fraiche_saison(
    con: duckdb.DuckDBPyConnection,
    *,
    fenetre: str = SAISON_COMPLETE,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    tranches: Sequence[str] | None = None,
    seuil_chute_cm: int | None = None,
) -> pl.DataFrame:
    """Cumul, jours de chute, episodes et plus forte chute, massif x saison x tranche."""
    _assurer_vues(con)
    sql = None if seuil_chute_cm is None else _sql_neige_fraiche_saison(seuil_chute_cm)
    params: list[object] = [_portee(fenetre)]
    where = _where(massifs, saisons, tranches, ["fenetre = ?"], params)
    return _frame(
        con,
        f"SELECT * FROM {_source('neige_fraiche_saison', sql)}{where} "
        "ORDER BY massif_id, saison, tranche",
        params,
    )


def cumul_neige_fraiche(
    con: duckdb.DuckDBPyConnection,
    *,
    debut: date,
    fin: date,
    massifs: Sequence[int] | None = None,
) -> pl.DataFrame:
    """Neige fraiche cumulee sur une periode quelconque, massif x tranche.

    Refuse une periode a cheval sur la rupture de l'hiver 2023-2024 : avant,
    `cumul_max_cm` est le plus fort de un ou deux secteurs ; depuis, la borne
    haute d'une fourchette. Leur somme n'est le cumul de rien.
    """
    if fin < debut:
        raise ValueError(f"periode vide : {debut} -> {fin}")
    _assurer_vues(con)
    params: list[object] = [debut, fin]
    where = _filtres(massifs, None, ["jour BETWEEN ? AND ?"], params)
    lectures = con.execute(
        f"SELECT DISTINCT lecture_cumul FROM neige_fraiche_jour{where}", params
    ).fetchall()
    if len(lectures) > 1:
        raise RuptureDeSerie(
            f"periode {debut} -> {fin} a cheval sur la rupture de serie de l'hiver "
            "2023-2024 : cumuls par secteur nomme avant, fourchette sur le massif "
            "depuis. Les sommer additionnerait deux grandeurs differentes."
        )
    return _frame(
        con,
        f"""
        SELECT
          massif_id, tranche,
          any_value(massif_nom)              AS massif_nom,
          any_value(lecture_cumul)           AS lecture_cumul,
          CAST(? AS DATE)                    AS debut,
          CAST(? AS DATE)                    AS fin,
          date_diff('day', CAST(? AS DATE), CAST(? AS DATE)) + 1 AS jours_periode,
          count(*)                           AS jours_couverts,
          count(cumul_max_cm)                AS jours_observes,
          count(*) - count(cumul_max_cm)     AS jours_non_observes,
          sum(cumul_max_cm)                  AS cumul_max_cm,
          sum(cumul_min_cm)                  AS cumul_min_cm
        FROM neige_fraiche_jour{where}
        GROUP BY massif_id, tranche
        ORDER BY massif_id, tranche
        """,
        [debut, fin, debut, fin, *params],
    )


__all__ = [
    "RuptureDeSerie",
    "VUES",
    "creer_vues",
    "cumul_neige_fraiche",
    "enneigement_continu",
    "enneigement_discards",
    "episodes_chute",
    "log_enneigement_discards",
    "log_neige_fraiche_discards",
    "metriques_saison",
    "neige_fraiche",
    "neige_fraiche_discards",
    "neige_fraiche_saison",
    "paliers",
    "releves",
]
