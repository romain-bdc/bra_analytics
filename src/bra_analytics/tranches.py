"""Tranches d'altitude normees.

Les altitudes de reference du BRA varient d'un massif et d'une epoque a
l'autre : paliers d'enneigement 1500/1800/2400 (ou 1200/1500/1800,
1500/1800/2100) jusqu'en 2020-2021, puis 1500/2000/2500 ; neige fraiche
mesuree a 1800 m ; vent bas a 1000, 1500 ou 2000 m, vent haut a 2000 ou
3000 m. Trois tranches fixes les ramenent a une grille commune (spec § 4.2).

**Bornes fermees a gauche** : [0, 1800), [1800, 2400), [2400, +inf). Les
paliers de l'archive tombent pile sur 1800 et 2400. La spec ecrivait
« > 2400 m » ; fermer a droite aurait range 1800 et 2400 dans la meme tranche
avant 2021 et laisse la tranche haute vide jusqu'au changement de paliers,
rendant toute serie de la tranche haute incomparable de part et d'autre de
2021. Fermees a gauche, les deux epoques donnent un palier par tranche
(mesure : `bra audit`, § 4).

Un palier est rattache a la tranche qui contient son altitude. Une tranche
sans palier reste vide : **aucune interpolation**. Une altitude `-1`
(sentinelle de la source) ou nulle n'appartient a aucune tranche.

Comme les bornes de fenetre dans `fenetres.py`, ces bornes sont definies ici
une seule fois ; le SQL est genere a partir d'elles.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tranche:
    """Intervalle d'altitude [min_m, max_m), borne absente = ouvert."""

    nom: str
    min_m: int | None
    max_m: int | None

    @property
    def libelle(self) -> str:
        if self.min_m is None:
            return f"< {self.max_m} m"
        if self.max_m is None:
            return f"≥ {self.min_m} m"
        return f"{self.min_m}–{self.max_m} m"


BASSE = Tranche("basse", None, 1800)
MOYENNE = Tranche("moyenne", 1800, 2400)
HAUTE = Tranche("haute", 2400, None)

TRANCHES: tuple[Tranche, ...] = (BASSE, MOYENNE, HAUTE)


def sql_case(col: str) -> str:
    """Expression SQL rendant le nom de la tranche de `col`, ou NULL.

    La garde `> 0` ecarte la sentinelle `-1` des paliers d'enneigement
    (2016-2023), qui sinon tomberait dans la tranche basse.
    """
    branches = []
    for t in TRANCHES:
        conds = [f"{col} > 0"]
        if t.min_m is not None:
            conds.append(f"{col} >= {t.min_m}")
        if t.max_m is not None:
            conds.append(f"{col} < {t.max_m}")
        branches.append(f"WHEN {' AND '.join(conds)} THEN '{t.nom}'")
    return "CASE " + " ".join(branches) + " END"
