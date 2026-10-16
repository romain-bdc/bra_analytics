"""Score composite de severite de saison (spec section 5.5, tache T10).

Un score massif x saison qui melange trois composantes, chacune une *part de
jours* lue dans les blocs deja livres :

- risque     part des jours avec indice dont `risque_maxi >= 3` (T6) ;
- neige      part des jours observes avec une chute de neige fraiche de
             `SEUIL_CHUTE_CM` ou plus (T7) ;
- vent       part des jours avec vent fort (> `SEUIL_VENT_FORT_KMH`), prise sur
             la tranche d'altitude la plus exposee (T8). Par tranche, jamais par
             role bas / haut : decision 3-A.

Chaque part est ramenee sur [0, 1] entre deux ancres fixes (`ANCRES`), puis les
trois sont combinees par `POIDS` et mises sur 0-100. Les ancres sont les
percentiles 5 et 95 des 321 lignes massif x saison `comparable` de la fenetre
`coeur` (mesure du 16 octobre 2026, 36 massifs, neuf saisons) arrondis ; elles
sont **figees** ici et non recalculees a chaque lecture : un score recalcule sur
la distribution du moment changerait de valeur a chaque saison ajoutee, ce que
la regle de version interdit.

Regles qui encadrent le score (spec 5.5) :

- la formule et sa version sortent de `formule()` : l'interface les affiche sans
  les recopier ;
- la version est derivee des poids, ancres et definitions (`Formule.version`),
  de sorte qu'un changement de ponderation change la version sans qu'on ait a y
  penser, et elle voyage avec chaque valeur (colonne `version_score`) ;
- les composantes restent publiees a cote, brutes et normalisees, avec les
  jours qui les portent : une part sans son denominateur ne se lit pas ;
- fenetre `coeur` seule : le risque y est le seul comparable entre saisons
  (sentinelle `RISQUE1=-1`) ;
- aucune composante n'est imputee. Si l'une manque, le score est NULL et
  `composantes_manquantes` dit laquelle : etiqueter plutot que renormaliser en
  silence sur deux composantes.

La neige fraiche change de lecture a la saison 2023-2024 (`secteurs` puis
`fourchette`) : `lecture_neige` le dit, et `rupture_neige` marque une ligne qui
melangerait les deux.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

import duckdb
import polars as pl

from ..fenetres import DEFAUT
from .enneigement import SEUIL_CHUTE_CM
from .meteo import SEUIL_VENT_FORT_KMH
from .risque import SEUIL_EPISODE, _filtres, _frame

VUE = "score_saison"

COMPOSANTES: tuple[str, ...] = ("risque", "neige", "vent")

# Poids : le risque est le signal que le BRA porte lui-meme ; la neige fraiche
# (correlation 0,54 avec lui sur les lignes comparables) et le vent (0,14) le
# precisent sans le doubler. A VALIDER : la mesure borne le choix, elle ne le
# determine pas (voir le rapport de la tache).
POIDS: dict[str, float] = {"risque": 0.5, "neige": 0.3, "vent": 0.2}

# Ancres (0 -> borne basse, 1 -> borne haute) : p05 / p95 mesures sur les lignes
# comparables de `coeur` : risque 0,115 / 0,795 ; neige 0,017 / 0,123 ;
# vent 0,025 / 0,262.
ANCRES: dict[str, tuple[float, float]] = {
    "risque": (0.10, 0.80),
    "neige": (0.02, 0.12),
    "vent": (0.03, 0.26),
}

DEFINITIONS: dict[str, str] = {
    "risque": f"jours risque_maxi >= {SEUIL_EPISODE} / jours avec indice",
    "neige": f"jours de chute >= {SEUIL_CHUTE_CM} cm / jours observes",
    "vent": f"jours de vent > {SEUIL_VENT_FORT_KMH} km/h / jours avec vent, tranche la plus exposee",
}


@dataclass(frozen=True)
class Formule:
    numero: int
    poids: dict[str, float]
    ancres: dict[str, tuple[float, float]]
    definitions: dict[str, str]
    fenetre: str

    def __post_init__(self) -> None:
        if set(self.poids) != set(COMPOSANTES) or set(self.ancres) != set(COMPOSANTES):
            raise ValueError(f"poids et ancres doivent couvrir exactement {COMPOSANTES}")
        if abs(sum(self.poids.values()) - 1.0) > 1e-9:
            raise ValueError(f"les poids doivent sommer a 1 (somme : {sum(self.poids.values())})")
        for nom, (bas, haut) in self.ancres.items():
            if not bas < haut:
                raise ValueError(f"ancre {nom} : borne basse {bas} >= borne haute {haut}")

    @property
    def version(self) -> str:
        """`<numero>-<empreinte>` : l'empreinte couvre tout ce qui change la valeur."""
        corps = json.dumps(
            [self.numero, self.fenetre, self.poids, self.ancres, self.definitions],
            sort_keys=True,
        )
        return f"{self.numero}-{hashlib.sha1(corps.encode()).hexdigest()[:6]}"

    @property
    def texte(self) -> str:
        termes = " + ".join(
            f"{self.poids[c]:g} x {c}" for c in COMPOSANTES
        )
        return f"score = 100 x ({termes}), chaque composante ramenee sur [0, 1] entre ses ancres"


FORMULE = Formule(
    numero=1, poids=POIDS, ancres=ANCRES, definitions=DEFINITIONS, fenetre=DEFAUT.nom
)


def formule() -> dict[str, object]:
    """Formule, version et parametres, tels que l'interface les affiche."""
    f = FORMULE
    return {
        "version": f.version,
        "texte": f.texte,
        "fenetre": f.fenetre,
        "composantes": [
            {
                "nom": c,
                "poids": f.poids[c],
                "ancre_basse": f.ancres[c][0],
                "ancre_haute": f.ancres[c][1],
                "definition": f.definitions[c],
            }
            for c in COMPOSANTES
        ],
    }


def normaliser(composante: str, valeur: float | None) -> float | None:
    """Part de jours -> [0, 1] entre les ancres de la composante, bornee."""
    if valeur is None:
        return None
    bas, haut = FORMULE.ancres[composante]
    return min(1.0, max(0.0, (valeur - bas) / (haut - bas)))


def calculer(risque: float | None, neige: float | None, vent: float | None) -> float | None:
    """Score 0-100 depuis les trois parts de jours ; None si l'une manque."""
    n = {c: normaliser(c, v) for c, v in zip(COMPOSANTES, (risque, neige, vent))}
    if any(v is None for v in n.values()):
        return None
    return round(100 * sum(FORMULE.poids[c] * n[c] for c in COMPOSANTES), 1)  # type: ignore[operator]


# --------------------------------------------------------------------------
# Vue
# --------------------------------------------------------------------------

def _norm_sql(c: str) -> str:
    bas, haut = FORMULE.ancres[c]
    return f"least(1.0, greatest(0.0, (part_{c} - {bas}) / {haut - bas}))"


def _sql_score() -> str:
    f = FORMULE
    fen = f"'{f.fenetre}'"
    manquantes = " || ".join(
        f"CASE WHEN part_{c} IS NULL THEN '{c},' ELSE '' END" for c in COMPOSANTES
    )
    score = " + ".join(f"{f.poids[c]} * n_{c}" for c in COMPOSANTES)
    return f"""
        WITH r AS (
          SELECT saison, massif_id, saison_debut, massif_nom, zone, comparable,
                 motif_exclusion, jours_avec_indice AS jours_risque,
                 jours_3_plus / nullif(jours_avec_indice, 0) AS part_risque
          FROM risque_saison WHERE fenetre = {fen}
        ),
        n AS (
          -- Une seule tranche aujourd'hui ; la somme reste juste s'il y en a plus.
          SELECT saison, massif_id, bool_and(comparable) AS comparable_neige,
                 sum(jours_observes) AS jours_neige,
                 sum(jours_chute) / nullif(sum(jours_observes), 0) AS part_neige,
                 string_agg(DISTINCT lecture_cumul, ',' ORDER BY lecture_cumul) AS lecture_neige,
                 bool_or(rupture_de_serie) AS rupture_neige
          FROM neige_fraiche_saison WHERE fenetre = {fen}
          GROUP BY saison, massif_id
        ),
        v AS (
          -- La tranche la plus exposee : le vent se lit par altitude, pas par role.
          SELECT saison, massif_id, bool_and(comparable) AS comparable_vent,
                 max_by(jours_avec_vent, jours_vent_fort / nullif(jours_avec_vent, 0)) AS jours_vent,
                 max(jours_vent_fort / nullif(jours_avec_vent, 0)) AS part_vent,
                 max_by(tranche, jours_vent_fort / nullif(jours_avec_vent, 0)) AS tranche_vent
          FROM meteo_vent_saison WHERE fenetre = {fen}
          GROUP BY saison, massif_id
        ),
        j AS (
          SELECT r.*, n.jours_neige, n.part_neige, n.lecture_neige, n.rupture_neige,
                 v.jours_vent, v.part_vent, v.tranche_vent,
                 r.comparable AND coalesce(n.comparable_neige, false)
                              AND coalesce(v.comparable_vent, false) AS comparable_score
          FROM r LEFT JOIN n USING (saison, massif_id) LEFT JOIN v USING (saison, massif_id)
        ),
        c AS (
          SELECT *, {", ".join(f"{_norm_sql(c)} AS n_{c}" for c in COMPOSANTES)},
                 {manquantes} AS manquantes
          FROM j
        )
        SELECT
          saison, massif_id, saison_debut, massif_nom, zone,
          '{f.version}' AS version_score,
          comparable_score AS comparable,
          motif_exclusion,
          CASE WHEN manquantes = '' THEN round(100 * ({score}), 1) END AS score,
          nullif(rtrim(manquantes, ','), '') AS composantes_manquantes,
          part_risque, part_neige, part_vent,
          n_risque, n_neige, n_vent,
          jours_risque, jours_neige, jours_vent, tranche_vent,
          lecture_neige, coalesce(rupture_neige, false) AS rupture_neige
        FROM c
    """


def creer_vues(con: duckdb.DuckDBPyConnection, *, temporaire: bool = False) -> tuple[str, ...]:
    """Pose `score_saison`, au-dessus des vues risque, neige fraiche et vent."""
    portee = "TEMP " if temporaire else ""
    con.execute(f"CREATE OR REPLACE {portee}VIEW {VUE} AS {_sql_score()}")
    return (VUE,)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def scores(
    con: duckdb.DuckDBPyConnection,
    *,
    massifs: Sequence[int] | None = None,
    saisons: Sequence[str] | None = None,
    comparables_seulement: bool = False,
) -> pl.DataFrame:
    """Score massif x saison sur la fenetre `coeur`, composantes et version comprises.

    Les lignes non comparables restent, avec leur motif : `comparables_seulement`
    est a l'appelant qui compare.
    """
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    if VUE not in presentes:
        creer_vues(con, temporaire=True)
    conditions = ["comparable"] if comparables_seulement else []
    params: list[object] = []
    where = _filtres(massifs, saisons, conditions, params)
    return _frame(con, f"SELECT * FROM {VUE}{where} ORDER BY massif_id, saison", params)
