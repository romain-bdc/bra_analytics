"""Generation du tableau de bord statique.

L'entrepot tient dans quelques dizaines de kilo-octets une fois encode : une
chaine par massif, un caractere par jour calendaire. La page embarque donc la
serie complete et recalcule ses agregats cote client, ce qui evite un serveur
et garde le filtrage instantane.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .fenetres import DEFAUT, FENETRES, SAISON_COMPLETE, SAISONS_NON_COMPARABLES
from .massifs import MASSIFS

COMMUN = Path(__file__).parent / "templates" / "commun.js"
TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"

# Un caractere par jour, dans la chaine `serie` de chaque massif.
ABSENT = "."  # aucun bulletin ce jour-la
SANS_INDICE = "0"  # bulletin publie sans estimation chiffree (risque_estime = false)


# Les lignes dont l'`ID` et le libelle `MASSIF` se contredisent n'appartiennent
# a aucun massif reel : leur zone est heritee d'un identifiant usurpe. Les
# retenir sur un filtre de zone ferait entrer un bulletin technique alpin de
# 2016 dans le perimetre pyreneen.
PERIMETRE = "zone = ? AND massif_coherent"


def _series(con, zone: str) -> tuple[date, list[dict]]:
    """Encode `risque_journalier` en une chaine par massif, alignee sur un jour zero commun."""
    bounds = con.execute(
        f"SELECT min(jour_validite), max(jour_validite) FROM risque_journalier WHERE {PERIMETRE}",
        [zone],
    ).fetchone()
    if bounds[0] is None:
        raise SystemExit(f"aucune donnee pour la zone {zone!r}")
    jour0, jourN = bounds
    span = (jourN - jour0).days + 1

    rows = con.execute(
        "SELECT massif_id, any_value(massif_nom), jour_validite, risque_maxi "
        f"FROM risque_journalier WHERE {PERIMETRE} "
        "GROUP BY massif_id, jour_validite, risque_maxi",
        [zone],
    ).fetchall()

    noms: dict[int, str] = {}
    grilles: dict[int, list[str]] = {}
    for massif_id, nom, jour, risque in rows:
        noms.setdefault(massif_id, nom)
        grille = grilles.setdefault(massif_id, [ABSENT] * span)
        grille[(jour - jour0).days] = SANS_INDICE if risque is None else str(risque)

    referentiel = {m.id: m for m in MASSIFS}
    massifs = []
    for massif_id in sorted(grilles):
        meta = referentiel.get(massif_id)
        massifs.append(
            {
                "id": massif_id,
                "nom": noms[massif_id],
                "departement": meta.departement if meta else "",
                "serie": "".join(grilles[massif_id]),
            }
        )
    return jour0, massifs


def payload(db_path: str | Path = "warehouse/bra.duckdb", zone: str = "Pyrenees") -> dict:
    import duckdb

    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    con = duckdb.connect(str(db), read_only=True)
    try:
        jour0, massifs = _series(con, zone)
        zones = con.execute(
            "SELECT zone, count(*) FROM risque_journalier GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        formats = con.execute(
            f"SELECT format_famille, count(*) FROM risque_journalier WHERE {PERIMETRE} "
            "GROUP BY 1 ORDER BY 1",
            [zone],
        ).fetchall()
        # Couverture et effectif de massifs par saison et par fenetre : la page
        # les affiche au survol, pour qu'une moyenne ne soit jamais lue sans ce
        # sur quoi elle est calculee.
        portees = con.execute(
            "SELECT fenetre, saison, comparable, bulletins, massifs_actifs, "
            "non_estimes, hors_moyenne, jours_fenetre, couverture_pct, motif_exclusion "
            "FROM saison_fenetre ORDER BY fenetre, saison"
        ).fetchall()
    finally:
        con.close()

    span = len(massifs[0]["serie"])
    stats: dict[str, dict[str, dict]] = {}
    for fen, saison, comparable, n, m_act, non_est, hors_moy, jours, couv, motif in portees:
        stats.setdefault(fen, {})[saison] = {
            "comparable": bool(comparable),
            "bulletins": n,
            "massifs_actifs": m_act,
            "non_estimes": non_est,
            "hors_moyenne": hors_moy,
            "jours": jours,
            "couverture": couv,
            "motif": motif,
        }
    return {
        "genere": date.today().isoformat(),
        "zone": zone,
        "jour0": jour0.isoformat(),
        "jourN": (jour0 + timedelta(days=span - 1)).isoformat(),
        "massifs": massifs,
        "formats": [{"nom": f, "jours": n} for f, n in formats],
        "hors_zone": [{"zone": z, "jours": n} for z, n in zones if z != zone],
        # Les bornes voyagent avec la page : elles sont definies une seule fois,
        # dans `fenetres.py`, et ni le SQL ni le JavaScript ne les recopient.
        "fenetres": [
            {
                "nom": f.nom,
                "libelle": f.libelle,
                "debut": list(f.debut),
                "fin": list(f.fin),
                "usage": f.usage,
                "justification": f.justification,
                "comparable": f.comparable_entre_saisons,
            }
            for f in FENETRES
        ]
        + [
            {
                "nom": SAISON_COMPLETE,
                "libelle": "saison entiere",
                "debut": None,
                "fin": None,
                "usage": "lecture d'une saison prise isolement",
                "justification": (
                    "Bornes et encodage des journees marginales varient d'une "
                    "saison a l'autre."
                ),
                "comparable": False,
            }
        ],
        "fenetre_defaut": DEFAUT.nom,
        "saisons_exclues": SAISONS_NON_COMPARABLES,
        "stats": stats,
    }


# Le gabarit ne porte ni doctype ni <html> : sous cette forme il s'insere tel quel
# dans un hote qui fournit deja le squelette. Le fichier autonome le reconstitue.
ENTETE = (
    "<!doctype html>\n"
    '<html lang="fr">\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)


def injecter(gabarit: Path, data: dict, standalone: bool = True) -> str:
    """Insere le payload dans un gabarit par son marqueur `__DONNEES__`.

    Partage par tous les ecrans (tableau de bord, carte d'accueil) : c'est le
    motif de l'interface, et il n'existe qu'une fois.
    """
    html = gabarit.read_text(encoding="utf-8")
    if "__DONNEES__" not in html:
        raise SystemExit(f"gabarit sans marqueur __DONNEES__ : {gabarit}")
    # separators compact : le payload represente l'essentiel du poids de la page.
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dans une chaine JSON fermerait la balise hote.
    blob = blob.replace("</", "<\\/")
    # Les aides JavaScript partagees entre ecrans passent en premier : elles ne
    # contiennent pas `__DONNEES__`, et un `__COMMUN__` apparaissant dans une
    # donnee ne doit jamais etre remplace.
    if "__COMMUN__" in html:
        html = html.replace("__COMMUN__", COMMUN.read_text(encoding="utf-8"), 1)
    page = html.replace("__DONNEES__", blob)
    if standalone:
        page = ENTETE + page + "</html>\n"
    return page


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "dashboard.html",
    zone: str = "Pyrenees",
    standalone: bool = True,
) -> Path:
    page = injecter(TEMPLATE, payload(db_path, zone), standalone)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
