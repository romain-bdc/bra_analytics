"""Mecanisme transverse aux ecrans : attribution, etat dans l'URL, exports (T15).

Un seul endroit definit ce que tous les ecrans partagent, pour que l'ajout d'un
ecran ne recopie rien :

- le texte d'attribution (spec section 7) et la liste des ecrans, ici ;
- le comportement cote client (barre de navigation, pied, URL, exports CSV et
  PNG), dans `templates/partage.js`, insere dans chaque page par le marqueur
  `__PARTAGE__` (voir `gabarit.injecter`).

Pour brancher un ecran :

1. l'ajouter a `ECRANS` (identifiant, fichier de sortie, libelle) ;
2. mettre `"partage": partage.bloc(archive, genere)` dans son payload ;
3. dans le gabarit : le marqueur `__PARTAGE__` dans un `<script>`, un
   `<footer><span id="attribution"></span></footer>`, puis
   `PARTAGE.demarrer({ ecran: "<id>", ...D.partage })` ;
4. lire et ecrire l'etat par `PARTAGE.lire()` / `PARTAGE.ecrire({...})`, jamais
   par `location.hash` directement : l'ecriture conserve les cles des autres
   ecrans, c'est ce qui evite la reinitialisation en changeant d'ecran ;
5. a la fin de chaque fonction de trace, `PARTAGE.enregistrer(svg, {...})` avec
   les valeurs que la fonction vient de tracer.
"""

from __future__ import annotations

from typing import NamedTuple

ATTRIBUTION_DONNEES = "Données Météo-France, Licence Ouverte 2.0"
SOURCE_URL = "https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA/"
LICENCE_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence"


def attribution_contours(version: str) -> str:
    """Attribution des contours, exigee la ou la carte s'affiche (spec section 7)."""
    return (f"Contours des massifs : Météo-France, Licence Ouverte 2.0 (version du {version}) ; "
            "contour de la France : IGN Admin Express 2018, Licence Ouverte")


class Ecran(NamedTuple):
    id: str
    fichier: str  # nom de sortie par defaut : les pages se lisent cote a cote
    libelle: str


# L'ordre est celui de la barre de navigation.
ECRANS: tuple[Ecran, ...] = (
    Ecran("carte", "carte.html", "Carte"),
    Ecran("fiche", "fiche.html", "Fiche massif-saison"),
    Ecran("comparaison", "comparaison.html", "Comparaison"),
    Ecran("exploration", "exploration.html", "Exploration"),
)


def bloc(archive: str | None, genere: str, contours: str | None = None) -> dict:
    """Ce que `PARTAGE.demarrer` lit dans le payload : attribution et dates.

    `archive` est le dernier jour couvert (ISO) ; `contours` n'est renseigne que
    pour l'ecran qui affiche la carte.
    """
    return {
        "donnees": ATTRIBUTION_DONNEES,
        "archive": archive,
        "genere": genere,
        "contours": contours,
        "source_url": SOURCE_URL,
        "licence_url": LICENCE_URL,
    }
