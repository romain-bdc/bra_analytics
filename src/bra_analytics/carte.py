"""Carte d'accueil : les 36 massifs, une valeur par massif (spec section 6, T12).

Meme motif que `dashboard.py` : un payload JSON construit ici, insere dans le
gabarit `templates/carte.html` par le marqueur `__DONNEES__`, et tout le reste
cote client. La page dessine elle-meme les contours en SVG : pas de
bibliotheque cartographique, et aucune donnee chargee du reseau (seules les
polices le sont, comme pour le tableau de bord ; hors ligne, la page retombe
sur les polices du systeme).

Rien n'est recalcule ici. La valeur par defaut est la metrique d'accueil de T6,
`moyenne_pluriannuelle()` -- moyenne de `risque_maxi` sur `coeur`, saisons
comparables, `massif_coherent`, `risque_maxi IS NOT NULL` (spec 3.2) -- et le
maximum atteint vient de `metriques_saison()`. Les bornes de la fenetre et la
liste des saisons ecartees voyagent dans le payload depuis `fenetres.py` : le
gabarit n'en recopie aucune.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from . import geo, partage
from .dashboard import injecter
from .fenetres import DEFAUT, SAISONS_NON_COMPARABLES, comparable
from .massifs import MASSIFS
from .metriques import risque

TEMPLATE = Path(__file__).parent / "templates" / "carte.html"

# Date de la version des contours, citee par l'attribution (docs/contours.md).
# Elle suit le nom du fichier versionne : changer de fichier, c'est changer
# cette date.
VERSION_CONTOURS = "15/02/2024"

_NOMBRES = (
    "zero", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
    "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
)


def _en_lettres(n: int) -> str:
    # Accord au feminin (« une saison ») ; au-dela de seize, les chiffres.
    return _NOMBRES[n] if 0 <= n < len(_NOMBRES) else str(n)


def libelle_saisons(comparables: int, total: int) -> str:
    """« neuf saisons comparables sur onze », et non « dix ans ».

    Spec 3.2 : deux saisons sont ecartees (2015-2016 partielle, 2019-2020
    confinement), et le libelle de l'ecran doit le dire plutot que d'arrondir
    la periode.
    """
    pluriel = "s" if comparables > 1 else ""
    return (f"{_en_lettres(comparables)} saison{pluriel} comparable{pluriel} "
            f"sur {_en_lettres(total)}")


def diffusion(presentes: list[str], comparables: list[str]) -> tuple[str, list[str]]:
    """Statut de diffusion d'un massif sur les saisons comparables, et ce qui manque.

    `partielle` n'est pas une anomalie a corriger : le massif 22 (Haut-Var
    Haut-Verdon) n'est diffuse qu'a partir de novembre 2018, le massif 71
    (Andorre) cesse de l'etre en 2025-2026. La carte le montre au lieu de
    laisser lire sa moyenne comme celle des autres.
    """
    manquantes = [s for s in comparables if s not in presentes]
    if not presentes:
        return "absente", manquantes
    return ("partielle" if manquantes else "complete"), manquantes


# Metriques proposees par le selecteur. La duree d'enneigement figure dans la
# spec mais depend des regles de parsing de l'enneigement (T7), non construites :
# elle est annoncee comme indisponible plutot qu'approchee.
METRIQUES: tuple[dict, ...] = (
    {
        "cle": "risque_moyen",
        "libelle": "Indice moyen",
        "description": "moyenne de l'indice de risque sur les jours avec indice",
        "echelle": "continue",
        "disponible": True,
    },
    # Rapporte aux saisons diffusees, pas en compte brut : le Haut-Var (diffuse
    # depuis novembre 2018) et Andorre (absente en 2025-2026) ont moins de
    # saisons comparables que les autres, et un compte brut les ferait paraitre
    # moins exposes qu'ils ne le sont. Le compte brut reste au survol.
    {
        "cle": "jours_3_plus_par_saison",
        "libelle": "Jours à risque 3 ou plus, par saison",
        "description": "nombre moyen de jours à un indice de 3, 4 ou 5 par saison diffusée",
        "echelle": "continue",
        "disponible": True,
    },
    {
        "cle": "risque_max",
        "libelle": "Maximum atteint",
        "description": "indice le plus haut publié sur la période",
        "echelle": "niveaux",
        "disponible": True,
    },
    {
        "cle": "duree_enneigement",
        "libelle": "Durée d'enneigement",
        "description": "",
        "echelle": "continue",
        "disponible": False,
        "motif": (
            "pas encore calculée : elle dépend des règles de lecture de "
            "l'enneigement (tâche T7), qui ne sont pas construites"
        ),
    },
)


def _saisons(con: duckdb.DuckDBPyConnection) -> tuple[list[str], list[str]]:
    """Saisons de l'entrepot, et celles qui entrent dans une comparaison.

    Le drapeau vient de `fenetres.comparable()`, seule definition des saisons
    ecartees ; l'entrepot ne fournit que la liste des saisons presentes.
    """
    toutes = [r[0] for r in con.execute(
        "SELECT DISTINCT saison FROM risque_journalier WHERE massif_coherent ORDER BY 1"
    ).fetchall()]
    return toutes, [s for s in toutes if comparable(s)]


def _maximum(saisons: pl.DataFrame) -> dict[int, dict]:
    """Maximum atteint sur les saisons comparables, depuis `risque_saison` (coeur).

    `jours_au_max` est la somme sur les saisons ou ce maximum est atteint ;
    `date_max` le premier de ces jours.
    """
    out: dict[int, dict] = {}
    retenues = saisons.filter(pl.col("comparable") & pl.col("risque_max").is_not_null())
    for (massif_id,), g in retenues.group_by(["massif_id"]):
        maxi = g["risque_max"].max()
        au_max = g.filter(pl.col("risque_max") == maxi)
        out[int(massif_id)] = {
            "risque_max": int(maxi),
            "jours_au_max": int(au_max["jours_au_max"].sum()),
            "date_max": au_max["date_max"].min().isoformat(),
        }
    return out


def payload(db_path: str | Path = "warehouse/bra.duckdb") -> dict:
    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    con = duckdb.connect(str(db), read_only=True)
    try:
        toutes, comparables = _saisons(con)
        moyennes = risque.moyenne_pluriannuelle(con, fenetre=DEFAUT.nom)
        saisons = risque.metriques_saison(con, fenetre=DEFAUT.nom)
        (archive,) = con.execute(
            "SELECT max(jour_validite) FROM risque_journalier WHERE massif_coherent"
        ).fetchone()
    finally:
        con.close()

    par_massif = {r["massif_id"]: r for r in moyennes.iter_rows(named=True)}
    maxima = _maximum(saisons)
    # Saisons comparables ou le massif a au moins un jour couvert dans `coeur`,
    # et jours nominaux de ces saisons : le denominateur de sa couverture.
    presence: dict[int, list[str]] = {}
    nominal: dict[int, int] = {}
    for r in saisons.filter(pl.col("comparable")).sort("saison").iter_rows(named=True):
        presence.setdefault(r["massif_id"], []).append(r["saison"])
        nominal[r["massif_id"]] = nominal.get(r["massif_id"], 0) + r["jours_periode"]

    massifs = []
    for m in MASSIFS:
        mp = par_massif.get(m.id)
        presentes = presence.get(m.id, [])
        statut, manquantes = diffusion(presentes, comparables)
        # Un massif sans jour dans la periode n'a pas de valeur : `None`, et non
        # zero. Un zero est un compte observe (diffuse, jamais a 5) ; une absence
        # n'est pas une mesure.
        avec = mp is not None and mp["jours_couverts"] > 0
        mx = maxima.get(m.id, {})
        massifs.append({
            "id": m.id,
            "nom": m.nom,
            "zone": m.zone,
            "departement": m.departement,
            "diffusion": statut,
            "saisons": mp["saisons"] if avec else 0,
            "saisons_presentes": presentes,
            "saisons_manquantes": manquantes,
            "jours_couverts": mp["jours_couverts"] if avec else 0,
            "jours_periode": nominal.get(m.id, 0),
            "jours_avec_indice": mp["jours_avec_indice"] if avec else 0,
            "risque_moyen": mp["risque_moyen"] if avec else None,
            "jours_3_plus": mp["jours_3_plus"] if avec else None,
            "jours_3_plus_par_saison": (
                round(mp["jours_3_plus"] / mp["saisons"], 1) if avec and mp["saisons"] else None
            ),
            "jours_4_plus": mp["jours_4_plus"] if avec else None,
            "jours_5": mp["jours_5"] if avec else None,
            "risque_max": mx.get("risque_max"),
            "jours_au_max": mx.get("jours_au_max"),
            "date_max": mx.get("date_max"),
        })

    contours = geo.charger(geo.WEB)
    r = geo.raccordement(contours)
    if not r.complet:
        # Un contour sans massif colorerait la carte sans donnee derriere ; un
        # massif sans contour disparaitrait. Les deux se voient ici, pas a l'ecran.
        raise SystemExit(f"contours non raccordes : manquants {r.manquants}, en trop {r.en_trop}")

    return {
        "genere": date.today().isoformat(),
        "archive_jusqu_au": archive.isoformat() if archive else None,
        # La fenetre voyage avec la page : definie une seule fois dans
        # `fenetres.py`, ni le SQL ni le JavaScript ne la recopient.
        "fenetre": {
            "nom": DEFAUT.nom,
            "libelle": DEFAUT.libelle,
            "debut": list(DEFAUT.debut),
            "fin": list(DEFAUT.fin),
            "usage": DEFAUT.usage,
        },
        "saisons": toutes,
        "saisons_comparables": comparables,
        "saisons_ecartees": {s: SAISONS_NON_COMPARABLES[s] for s in toutes if not comparable(s)},
        "libelle_saisons": libelle_saisons(len(comparables), len(toutes)),
        "metriques": list(METRIQUES),
        "metrique_defaut": METRIQUES[0]["cle"],
        "massifs": massifs,
        "contours": contours,
        "attribution": {
            "donnees": partage.ATTRIBUTION_DONNEES,
            "contours": partage.attribution_contours(VERSION_CONTOURS),
        },
        "partage": partage.bloc(
            archive.isoformat() if archive else None,
            date.today().isoformat(),
            partage.attribution_contours(VERSION_CONTOURS),
        ),
    }


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "carte.html",
    standalone: bool = True,
) -> Path:
    page = injecter(TEMPLATE, payload(db_path), standalone)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out

