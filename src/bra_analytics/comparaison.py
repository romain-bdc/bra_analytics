"""Regles de comparaison entre saisons et entre massifs (spec section 6, T13).

L'ecran de comparaison a fusionne avec la fiche (« Fiche massif », `fiche.py`) :
les deux montraient le meme massif, les memes saisons, la meme courbe d'indice.
Ce module ne construit plus de page ; il fournit a la fiche ce qu'elle compare
et comment (`bloc()`), et garde les regles testables sans navigateur.

Il porte une decision et une seule qui lui soit propre : **quelle
metrique peut se classer sur quelle fenetre**. Elle est ecrite ici, depuis les
drapeaux de `fenetres.py`, et voyage dans le payload (`refus`) ; le gabarit
n'en recopie aucune.

- une metrique d'indice (moyenne, jours >= 3, maximum...) n'est comparable que
  sur la fenetre `coeur` (`risque.fenetre_comparable`) : hors d'elle, pres de
  la moitie de l'ecart entre les epoques est la sentinelle `RISQUE1=-1` ;
- l'epaisseur de neige se compare sur les fenetres nommees
  (`comparable_enneigement`) : ses releves sont lus de la meme facon a toutes
  les epoques. La saison entiere reste refusee : ses bornes varient d'une
  saison a l'autre.

**Troncature a periode egale.** Les saisons n'ont ni la meme ouverture ni la
meme fermeture, et une journee d'archive peut manquer. Comparer des comptes de
jours sur des periodes de longueur differente compare des durees. Le gabarit
calcule donc la *periode commune* des series comparees (du dernier premier jour
couvert au premier dernier jour couvert, dans la fenetre) et n'agrege que
dessus ; il l'annonce dans le sous-titre du graphe. Une saison non comparable
reste affichee avec son motif, mais n'entre pas dans le calcul de la periode
commune : le confinement de 2019-2020 la ferait tomber a la mi-mars pour tout
le monde.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .fenetres import DEFAUT, FENETRES, FIN_SENTINELLE, MOIS_FR, PAR_NOM, SAISON_COMPLETE
from .metriques import risque
from .metriques.risque import ComparaisonRefusee

# Courbes superposees sur le graphe d'indice de la fiche massif, saison lue comprise. La spec
# en permettait quatre ; a l'usage, quatre courbes en marches entre 1 et 5 se recouvrent
# trop pour se lire (choix du proprietaire, novembre 2026). Le plafond voyage dans le
# payload, le gabarit le lit.
MAX_COURBES = 3

# Seuils des deux metriques de comptage. Le premier est celui de `risque` (une
# seule definition) ; le second est le "4" litteral des vues de `risque.py`.
SEUIL_HAUT = risque.SEUIL_EPISODE
SEUIL_TRES_HAUT = 4

# En dessous, un rang ne dit rien : classer une saison contre elle seule.
MIN_SAISONS_CLASSEMENT = 2


@dataclass(frozen=True)
class Metrique:
    """Une metrique de classement. `indice` dit si elle derive de `risque_maxi`."""

    cle: str
    libelle: str
    description: str
    indice: bool
    unite: str
    # Echelle ordinale bornee 1..5 : l'axe du classement est gradue en niveaux,
    # pas depuis zero. Dit ici une fois ; le gabarit ne teste aucune cle.
    ordinal: bool = False


METRIQUES: tuple[Metrique, ...] = (
    Metrique(
        "risque_moyen", "Indice moyen",
        "moyenne de l'indice de risque sur les jours avec indice ; échelle ordinale, "
        "toujours lue avec son nombre de jours",
        True, "", ordinal=True,
    ),
    Metrique(
        "jours_3_plus", f"Jours à risque {SEUIL_HAUT} ou plus",
        f"jours à un indice d'au moins {SEUIL_HAUT} sur la période comparée", True, "j",
    ),
    Metrique(
        "jours_4_plus", f"Jours à risque {SEUIL_TRES_HAUT} ou plus",
        f"jours à un indice d'au moins {SEUIL_TRES_HAUT} sur la période comparée", True, "j",
    ),
    Metrique(
        "risque_max", "Indice maximal",
        "indice le plus haut publié sur la période comparée", True, "", ordinal=True,
    ),
    Metrique(
        "epaisseur_max", "Épaisseur de neige maximale",
        "épaisseur la plus forte relevée au palier de la tranche choisie, versant choisi ; "
        "valeur indicative rattachée à une altitude de référence qui change d'époque en époque",
        False, "cm",
    ),
)
PAR_CLE: dict[str, Metrique] = {m.cle: m for m in METRIQUES}


def refus(cle: str, fenetre: str) -> str | None:
    """Motif du refus de classer la metrique `cle` sur `fenetre`, ou `None` si elle est permise."""
    metrique = PAR_CLE[cle]
    try:
        verifier(metrique.cle, fenetre)
    except ComparaisonRefusee as exc:
        return str(exc)
    return None


def verifier(cle: str, fenetre: str) -> None:
    """Leve `ComparaisonRefusee` si `cle` ne se compare pas entre saisons sur `fenetre`.

    L'indice delegue a `risque` (une seule definition du refus) ; la neige
    lit `comparable_enneigement`, qui est son propre drapeau dans `fenetres.py`.
    """
    metrique = PAR_CLE[cle]
    if metrique.indice:
        risque.fenetre_comparable(fenetre)
        return
    f = PAR_NOM.get(fenetre)
    if f is None or not f.comparable_enneigement:
        raise ComparaisonRefusee(
            f"classement refusé sur {fenetre!r} : les bornes de la saison entière varient "
            f"d'une saison à l'autre, seules les fenêtres nommées comparent des périodes égales"
        )


def periode_commune(
    data: dict, massif_id: int, saisons: list[str], fenetre: str = DEFAUT.nom
) -> tuple[str, str] | None:
    """Periode commune (premier, dernier jour calendaire `mm-jj`) des series comparees.

    Meme regle que le gabarit, ecrite ici pour etre testable sans navigateur :
    dans la fenetre, du dernier premier jour couvert au premier dernier jour
    couvert, sur les seules saisons comparables (si aucune ne l'est, sur toutes).
    `None` si les series n'ont aucun jour commun.
    """
    axe = data["axe"]
    pos = {c: i for i, c in enumerate(axe)}
    f = next(x for x in data["fenetres"] if x["nom"] == fenetre)
    if f["debut"]:
        w0, w1 = pos[f"{f['debut'][0]:02d}-{f['debut'][1]:02d}"], pos[f"{f['fin'][0]:02d}-{f['fin'][1]:02d}"]
    else:
        w0, w1 = 0, len(axe) - 1
    comparable = {s["nom"]: s["comparable"] for s in data["saisons"]}
    base = [s for s in saisons if comparable[s]] or list(saisons)
    etendues = []
    for saison in base:
        e = data["series"][massif_id][saison]
        origine = date.fromisoformat(e["origine"])
        cases = [
            pos[(origine + timedelta(days=i)).strftime("%m-%d")]
            for i, c in enumerate(e["risque"]) if c != "."
        ]
        cases = [x for x in cases if w0 <= x <= w1]
        if not cases:
            return None
        etendues.append((min(cases), max(cases)))
    if not etendues:
        return None
    lo, hi = max(a for a, _ in etendues), min(b for _, b in etendues)
    return (axe[lo], axe[hi]) if lo <= hi else None


def fenetres_payload() -> list[dict]:
    """Toutes les fenetres nommees, puis la saison entiere : le classement les offre toutes."""
    return [
        {
            "nom": f.nom,
            "libelle": f.libelle,
            "debut": list(f.debut),
            "fin": list(f.fin),
            "usage": f.usage,
            "comparable": f.comparable_entre_saisons,
            "comparable_enneigement": f.comparable_enneigement,
        }
        for f in FENETRES
    ] + [{
        "nom": SAISON_COMPLETE, "libelle": "saison entière", "debut": None, "fin": None,
        "usage": "lecture d'une saison prise isolément",
        "comparable": False, "comparable_enneigement": False,
    }]


def bloc(fenetres: list[dict]) -> dict:
    """Ce que la fiche massif lit pour comparer : plafond, seuils, metriques et matrice de refus."""
    return {
        "max_courbes": MAX_COURBES,
        "seuil_haut": SEUIL_HAUT,
        "seuil_tres_haut": SEUIL_TRES_HAUT,
        "min_saisons_classement": MIN_SAISONS_CLASSEMENT,
        "fin_sentinelle": f"{MOIS_FR[FIN_SENTINELLE.month - 1]} {FIN_SENTINELLE.year}",
        "metriques": [
            {"cle": m.cle, "libelle": m.libelle, "description": m.description,
             "indice": m.indice, "unite": m.unite, "ordinal": m.ordinal}
            for m in METRIQUES
        ],
        # metrique -> fenetre -> motif du refus (None = permis).
        "refus": {m.cle: {f["nom"]: refus(m.cle, f["nom"]) for f in fenetres} for m in METRIQUES},
    }
