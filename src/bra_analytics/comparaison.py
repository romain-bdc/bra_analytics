"""Ecran de comparaison (spec section 6, T13).

Meme motif que `fiche.py` : un payload JSON construit ici, insere dans
`templates/comparaison.html` par le marqueur `__DONNEES__`, tout le calcul
d'affichage cote client. Les series (risque, neige) et la bande mediane sont
celles de la fiche, produites par les memes fonctions : rien n'est recopie.

Ce module porte une decision et une seule qui lui soit propre : **quelle
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
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from .dashboard import injecter
from .fenetres import DEFAUT, FENETRES, PAR_NOM, SAISON_COMPLETE
from .fiche import (
    _bandes,
    _series,
    _tableau,
    archive_et_saisons,
    axe_calendaire,
    fiche_massifs,
    saisons_payload,
)
from .metriques import risque
from .metriques.risque import ComparaisonRefusee
from .tranches import TRANCHES

TEMPLATE = Path(__file__).parent / "templates" / "comparaison.html"

# Au-dela de quatre courbes superposees, la lecture devient impossible (spec 6) :
# le plafond voyage dans le payload, le gabarit le lit.
MAX_COURBES = 4

# Blocs lus pour la comparaison : le risque et la neige. L'isotherme et le vent
# n'ont pas de metrique de classement ici.
BLOCS = ("neige",)


@dataclass(frozen=True)
class Metrique:
    """Une metrique de classement. `indice` dit si elle derive de `risque_maxi`."""

    cle: str
    libelle: str
    description: str
    indice: bool
    unite: str


METRIQUES: tuple[Metrique, ...] = (
    Metrique(
        "risque_moyen", "Indice moyen",
        "moyenne de l'indice de risque sur les jours avec indice ; échelle ordinale, "
        "toujours lue avec son nombre de jours",
        True, "",
    ),
    Metrique(
        "jours_3_plus", "Jours à risque 3 ou plus",
        "jours à un indice de 3, 4 ou 5 sur la période comparée", True, "j",
    ),
    Metrique(
        "jours_4_plus", "Jours à risque 4 ou 5",
        "jours à un indice de 4 ou 5 sur la période comparée", True, "j",
    ),
    Metrique(
        "risque_max", "Indice maximal",
        "indice le plus haut publié sur la période comparée", True, "",
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


def _fenetres_payload() -> list[dict]:
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


def payload(db_path: str | Path = "warehouse/bra.duckdb") -> dict:
    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    con = duckdb.connect(str(db), read_only=True)
    try:
        series, jours = _series(con, BLOCS)
        moyennes = risque.moyenne_pluriannuelle(con, fenetre=DEFAUT.nom)
        archive, toutes = archive_et_saisons(con)
    finally:
        con.close()

    axe = axe_calendaire()
    jours = jours.with_columns(pl.col("jour_validite").dt.strftime("%m-%d").alias("jour_annee"))
    bandes = _tableau(_bandes(jours, "jour_annee"), "jour_annee", axe)
    massifs = fiche_massifs(series, jours, moyennes)

    for per_massif in series.values():
        for e in per_massif.values():
            e["origine"] = e["origine"].isoformat()
            # La comparaison se lit sur l'axe calendaire : le rang n'y sert pas.
            e.pop("decalage_rang", None)

    fenetres = _fenetres_payload()
    return {
        "genere": date.today().isoformat(),
        "archive_jusqu_au": archive.isoformat() if archive else None,
        "axe": axe,
        "fenetre_defaut": DEFAUT.nom,
        "saison_complete": SAISON_COMPLETE,
        "fenetres": fenetres,
        "saisons": saisons_payload(toutes),
        "massifs": massifs,
        "tranches": [{"nom": t.nom, "libelle": t.libelle} for t in TRANCHES],
        "min_saisons_bande": risque.MIN_SAISONS_NORMALE,
        "max_courbes": MAX_COURBES,
        "metriques": [
            {"cle": m.cle, "libelle": m.libelle, "description": m.description,
             "indice": m.indice, "unite": m.unite}
            for m in METRIQUES
        ],
        # metrique -> fenetre -> motif du refus (None = permis).
        "refus": {m.cle: {f["nom"]: refus(m.cle, f["nom"]) for f in fenetres} for m in METRIQUES},
        "series": series,
        "bandes": bandes,
        "attribution": "Données Météo-France, Licence Ouverte 2.0",
    }


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "comparaison.html",
    standalone: bool = True,
) -> Path:
    page = injecter(TEMPLATE, payload(db_path), standalone)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
