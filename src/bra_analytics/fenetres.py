"""Fenetres saisonnieres de comparaison.

Comparer deux saisons suppose de comparer des periodes equivalentes. Deux
obstacles s'y opposent dans l'archive BRA, et ils n'appellent pas la meme
fenetre.

**Les saisons n'ont pas les memes bornes.** La diffusion commence entre le
21 octobre et le 6 novembre selon l'annee, et s'arrete entre le 7 et le
15 juin. Une volumetrie comparee sur les spans bruts compare des durees
differentes. -> `COMMUNE`, intersection des spans reels.

**Les journees marginales n'ont pas le meme encodage selon l'epoque.** Du
04/11/2016 au 14/06/2021, un jour sans enneigement recoit `RISQUE1="-1"`, que
la pipeline convertit en valeur nulle : ces jours sortent des moyennes. Apres
juin 2021 la meme journee recoit un indice reel, generalement 1, et pese donc
dans la moyenne. A nivologie identique, les saisons 2016-2021 ressortent plus
hautes que les suivantes -- l'ecart mesure entre les deux groupes passe de
0,32 point sur la saison entiere a 0,09 sur `COEUR`. -> `COEUR`, restreinte a
la periode ou aucune saison n'utilise la sentinelle.

`COMMUNE` **ne corrige pas** le second obstacle : elle couvre novembre, mai et
juin, ou le `-1` est massif. Elle sert a mesurer ce que l'archive contient,
jamais a comparer des moyennes de risque.

Les bornes sont mesurees, pas choisies : voir `justification` sur chaque
fenetre, et `bra fenetres` qui republie la mesure depuis l'entrepot.
"""

from __future__ import annotations

from dataclasses import dataclass

MOIS_FR = (
    "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
)


@dataclass(frozen=True)
class Fenetre:
    """Une fenetre saisonniere, en (mois, jour) relatifs a la saison nivologique.

    `debut` se lit dans l'annee d'ouverture de la saison, `fin` dans l'annee
    suivante. Pour la saison 2023-2024, (11, 6) -> (4, 15) donne
    2023-11-06 -> 2024-04-15.
    """

    nom: str
    debut: tuple[int, int]
    fin: tuple[int, int]
    usage: str
    justification: str
    comparable_entre_saisons: bool

    @property
    def libelle(self) -> str:
        m0, j0 = self.debut
        m1, j1 = self.fin
        return f"{j0} {MOIS_FR[m0 - 1]} -> {j1} {MOIS_FR[m1 - 1]}"

    def bornes(self, saison_debut: int) -> tuple[str, str]:
        """Bornes datees (incluses) de la fenetre pour une saison donnee."""
        return (
            f"{saison_debut:04d}-{self.debut[0]:02d}-{self.debut[1]:02d}",
            f"{saison_debut + 1:04d}-{self.fin[0]:02d}-{self.fin[1]:02d}",
        )

    def sql_duree(self, annee: str = "saison_debut") -> str:
        """Duree nominale de la fenetre en jours, pour DuckDB.

        C'est le denominateur de la couverture : rapporter les bulletins au
        span *observe* ferait afficher 100 % a une saison tronquee, qui est
        toujours complete sur ce qu'elle contient.
        """
        return (
            f"date_diff('day', make_date({annee}, {self.debut[0]}, {self.debut[1]}), "
            f"make_date({annee} + 1, {self.fin[0]}, {self.fin[1]})) + 1"
        )

    def sql_predicat(self, jour: str = "jour_validite", annee: str = "saison_debut") -> str:
        """Predicat SQL isolant la fenetre, pour DuckDB."""
        return (
            f"{jour} BETWEEN make_date({annee}, {self.debut[0]}, {self.debut[1]}) "
            f"AND make_date({annee} + 1, {self.fin[0]}, {self.fin[1]})"
        )


# Intersection des spans reels des saisons exploitables, mesuree sur
# `jour_validite` -- le jour couvert, qui est le grain de toute analyse.
#
# Attention au decalage d'un jour si l'on rapproche ces bornes de celles lues
# sur `jour_bulletin` : un BRA est redige la veille pour le lendemain. Les
# memes saisons donnent 5 novembre -> 6 juin en date de redaction.
COMMUNE = Fenetre(
    nom="commune",
    debut=(11, 6),
    fin=(6, 7),
    usage="couverture, volumetrie, duree de saison, disponibilite des champs",
    justification=(
        "Intersection des spans reels de `jour_validite`, hors 2015-2016 et "
        "2019-2020. Ouverture la plus tardive : 6 novembre (2025-2026). "
        "Fermeture la plus precoce : 7 juin (2023-2024)."
    ),
    comparable_entre_saisons=False,
)

# Bornes calees sur la pratique du `-1`, mesuree saison par saison :
#
#   saison       dernier -1 d'automne   premier -1 de printemps
#   2016-2017    12 decembre            28 avril
#   2017-2018    11 decembre            27 avril
#   2018-2019    13 decembre            30 avril
#   2019-2020    12 decembre            (interrompue au 26 mars)
#   2020-2021    11 decembre            30 avril
#
# L'intervalle sans aucune sentinelle, toutes saisons confondues, court donc
# du 14 decembre au 26 avril. `COEUR` s'y inscrit avec une marge de 1 jour a
# l'ouverture et de 11 jours a la fermeture, ce qui absorbe une annee ou la
# pratique s'etendrait un peu plus loin que celles observees.
COEUR = Fenetre(
    nom="coeur",
    debut=(12, 15),
    fin=(4, 15),
    usage="toute comparaison inter-saisons d'indice de risque",
    justification=(
        "Aucune saison n'y emploie la sentinelle `RISQUE1=-1` : 0 bulletin non "
        "estime sur chacune des saisons comparables. Le dernier -1 d'automne "
        "tombe au plus tard le 13 decembre (2018-2019), le premier -1 de "
        "printemps au plus tot le 27 avril (2017-2018)."
    ),
    comparable_entre_saisons=True,
)

FENETRES: tuple[Fenetre, ...] = (COEUR, COMMUNE)
PAR_NOM: dict[str, Fenetre] = {f.nom: f for f in FENETRES}

# Fenetre par defaut de toute comparaison inter-saisons.
DEFAUT = COEUR

# Nom conventionnel de la saison entiere, la ou une fenetre est attendue.
SAISON_COMPLETE = "saison_complete"


# Saisons ecartees des comparaisons inter-saisons. Elles restent dans
# l'entrepot et dans les vues : c'est le libelle qui les ecarte, pas un filtre.
# Une saison supprimee en silence est une saison qu'on redecouvre plus tard.
SAISONS_NON_COMPARABLES: dict[str, str] = {
    "2015-2016": (
        "saison partielle : l'archive demarre le 10 mars 2016, soit apres "
        "l'ouverture des deux fenetres"
    ),
    "2019-2020": (
        "interrompue le 26 mars 2020 (confinement) : tronquee sur les deux "
        "fenetres"
    ),
}


def comparable(saison: str) -> bool:
    return saison not in SAISONS_NON_COMPARABLES


def motif_exclusion(saison: str) -> str | None:
    return SAISONS_NON_COMPARABLES.get(saison)
