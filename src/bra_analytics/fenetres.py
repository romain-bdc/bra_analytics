"""Fenetres saisonnieres de comparaison.

Comparer deux saisons suppose de comparer des periodes equivalentes. Deux
obstacles s'y opposent dans l'archive BRA, et ils n'appellent pas la meme
fenetre.

**Les saisons n'ont pas les memes bornes.** La diffusion commence entre le
21 octobre et le 6 novembre selon l'annee, et s'arrete entre le 7 et le
15 juin. Une volumetrie comparee sur les spans bruts compare des durees
differentes. -> `COMMUNE`, intersection des spans reels.

**Les journees marginales n'ont pas le meme encodage selon l'epoque.** Du
04/11/2016 au 11/06/2021, un jour sans enneigement recoit `RISQUE1="-1"`, que
la pipeline convertit en valeur nulle : ces jours sortent des moyennes. Apres
juin 2021 la meme journee recoit un indice reel, generalement 1, et pese donc
dans la moyenne. A nivologie identique, les saisons 2016-2021 ressortent plus
hautes que les suivantes -- l'ecart mesure entre les deux groupes passe de
0,37 point sur la saison entiere a 0,20 sur `COEUR` sur les 36 massifs (de
0,33 a 0,10 sur les seules Pyrenees). -> `COEUR`, restreinte a
la periode ou aucune saison n'utilise la sentinelle.

`COMMUNE` **ne corrige pas** le second obstacle : elle couvre novembre, mai et
juin, ou le `-1` est massif. Elle sert a mesurer ce que l'archive contient,
jamais a comparer des moyennes de risque.

Les bornes sont mesurees, pas choisies : voir `justification` sur chaque
fenetre, et `bra fenetres` qui republie la mesure depuis l'entrepot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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
    # L'obstacle qui rend une fenetre non comparable pour le risque -- la
    # sentinelle `RISQUE1=-1` des journees marginales avant juin 2021 -- ne
    # touche pas l'enneigement : ses releves sont lus de la meme facon a toutes
    # les epoques. La comparabilite se declare donc par bloc.
    comparable_enneigement: bool

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
# Mesuree d'abord sur les 11 massifs pyreneens (6 novembre -> 7 juin), puis
# remesuree sur les 36 massifs (octobre 2026) : l'intersection devient 4 novembre
# -> 7 juin, les Alpes ouvrant plus tot en 2025-2026. La borne du 6 novembre est
# conservee : elle reste incluse dans le span de chaque saison, et la deplacer
# ferait bouger toutes les couvertures deja publiees sans rien corriger.
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
        "2019-2020. Pyrenees : ouverture la plus tardive le 6 novembre "
        "(2025-2026), fermeture la plus precoce le 7 juin (2023-2024). Sur les "
        "36 massifs l'intersection s'elargit a 4 novembre -> 7 juin : la "
        "fenetre reste incluse dans toutes les saisons."
    ),
    comparable_entre_saisons=False,
    comparable_enneigement=True,
)

# Bornes calees sur la pratique du `-1`, mesuree saison par saison -- sur les
# Pyrenees d'abord, puis sur les 36 massifs, qui donnent les memes dates :
#
#   saison       dernier -1 d'automne   premier -1 de printemps
#   2016-2017    12 decembre            28 avril
#   2017-2018    11 decembre            27 avril
#   2018-2019    13 decembre            30 avril
#   2019-2020    12 decembre            (estimation interrompue fin mars)
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
    comparable_enneigement=True,
)

FENETRES: tuple[Fenetre, ...] = (COEUR, COMMUNE)
PAR_NOM: dict[str, Fenetre] = {f.nom: f for f in FENETRES}

# Fenetre par defaut de toute comparaison inter-saisons.
DEFAUT = COEUR

# Dernier jour ou la sentinelle `RISQUE1=-1` apparait dans l'archive (11/06/2021) :
# les ecrans en tirent leur mention "avant juin 2021" au lieu de la recopier.
FIN_SENTINELLE = date(2021, 6, 11)

# Nom conventionnel de la saison entiere, la ou une fenetre est attendue.
SAISON_COMPLETE = "saison_complete"


# Saisons ecartees des comparaisons inter-saisons. Elles restent dans
# l'entrepot et dans les vues : c'est le libelle qui les ecarte, pas un filtre.
# Une saison supprimee en silence est une saison qu'on redecouvre plus tard.
# Les motifs sont du texte affiche (carte, tableau de bord, vue
# `saison_fenetre`) : accentues, a la difference des commentaires.
SAISONS_NON_COMPARABLES: dict[str, str] = {
    "2015-2016": (
        "saison partielle : l'archive démarre le 10 mars 2016, soit après "
        "l'ouverture des deux fenêtres"
    ),
    "2019-2020": (
        "estimation interrompue fin mars 2020 (confinement) : Pyrénées et "
        "Corse s'arrêtent (26 et 18 mars), les Alpes publient sans indice "
        "jusqu'au 11 juin ; tronquée sur les deux fenêtres"
    ),
}


def comparable(saison: str) -> bool:
    return saison not in SAISONS_NON_COMPARABLES


def motif_exclusion(saison: str) -> str | None:
    return SAISONS_NON_COMPARABLES.get(saison)


def _litteral(texte: str) -> str:
    """Chaine Python -> litteral texte SQL.

    `repr()` ne convient pas : sur une chaine contenant une apostrophe il rend
    des guillemets doubles, que SQL lit comme un identifiant de colonne et non
    comme du texte. Les motifs d'exclusion sont rediges en francais, donc
    pleins d'apostrophes.
    """
    return "'" + texte.replace("'", "''") + "'"


def sql_exclusions() -> str:
    """Saisons non comparables et leur motif, en litteral `VALUES` SQL.

    Ecrit une seule fois ici : les vues de `build.py` et de la couche
    metriques le lisent, aucune ne recopie la liste.
    """
    return ", ".join(
        f"({_litteral(saison)}, {_litteral(motif)})"
        for saison, motif in SAISONS_NON_COMPARABLES.items()
    )


def sql_fenetres_comparables_enneigement() -> str:
    """Noms des fenetres ou l'enneigement se compare entre saisons, en liste SQL."""
    return ", ".join(f"'{f.nom}'" for f in FENETRES if f.comparable_enneigement)
