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

from .massifs import MASSIFS

TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"

# Un caractere par jour, dans la chaine `serie` de chaque massif.
ABSENT = "."  # aucun bulletin ce jour-la
SANS_INDICE = "0"  # bulletin publie sans estimation chiffree (risque_estime = false)


def _series(con, zone: str) -> tuple[date, list[dict]]:
    """Encode `risque_journalier` en une chaine par massif, alignee sur un jour zero commun."""
    bounds = con.execute(
        "SELECT min(jour_validite), max(jour_validite) FROM risque_journalier WHERE zone = ?",
        [zone],
    ).fetchone()
    if bounds[0] is None:
        raise SystemExit(f"aucune donnee pour la zone {zone!r}")
    jour0, jourN = bounds
    span = (jourN - jour0).days + 1

    rows = con.execute(
        "SELECT massif_id, any_value(massif_nom), jour_validite, risque_maxi "
        "FROM risque_journalier WHERE zone = ? "
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
            "SELECT format_famille, count(*) FROM risque_journalier WHERE zone = ? "
            "GROUP BY 1 ORDER BY 1",
            [zone],
        ).fetchall()
    finally:
        con.close()

    span = len(massifs[0]["serie"])
    return {
        "genere": date.today().isoformat(),
        "zone": zone,
        "jour0": jour0.isoformat(),
        "jourN": (jour0 + timedelta(days=span - 1)).isoformat(),
        "massifs": massifs,
        "formats": [{"nom": f, "jours": n} for f, n in formats],
        "hors_zone": [{"zone": z, "jours": n} for z, n in zones if z != zone],
    }


# Le gabarit ne porte ni doctype ni <html> : sous cette forme il s'insere tel quel
# dans un hote qui fournit deja le squelette. Le fichier autonome le reconstitue.
ENTETE = (
    "<!doctype html>\n"
    '<html lang="fr">\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "dashboard.html",
    zone: str = "Pyrenees",
    standalone: bool = True,
) -> Path:
    data = payload(db_path, zone)
    html = TEMPLATE.read_text(encoding="utf-8")
    if "__DONNEES__" not in html:
        raise SystemExit(f"gabarit sans marqueur __DONNEES__ : {TEMPLATE}")
    # separators compact : le payload represente l'essentiel du poids de la page.
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dans une chaine JSON fermerait la balise hote.
    blob = blob.replace("</", "<\\/")
    page = html.replace("__DONNEES__", blob)
    if standalone:
        page = ENTETE + page + "</html>\n"
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
