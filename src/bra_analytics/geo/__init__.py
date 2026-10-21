"""Contours geographiques des massifs BRA (carte d'accueil, T3).

Source retenue : le GeoJSON des massifs publie par Meteo-France dans le jeu
data.gouv.fr « Archive des Bulletins Avalanches », sous Licence Ouverte 2.0.
Sa propriete `code` est l'identifiant `massif_id` du BRA lui-meme : le
raccordement se fait sans table de correspondance. Les micro-regions EAWS,
envisagees d'abord, n'ont pas de contour pour le massif 71 (Andorre). Detail,
version epinglee et empreintes : docs/contours.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..massifs import BY_ID

ICI = Path(__file__).parent
# Fichier d'origine, tel que telecharge : jamais reecrit.
SOURCE = ICI / "massifs_meteofrance_20240215.geojson"
# Version allegee pour la page autonome, produite par `bra contours`.
WEB = ICI / "massifs.web.geojson"
# 0,001 degre ~ 100 m : 27 % de sommets en moins, invisible a l'echelle d'une
# carte des 36 massifs (mesure sur le fichier du 15/02/2024).
TOLERANCE = 0.001

# Contour de la France metropolitaine (IGN Admin Express, edition 2018, simplifie par
# gregoiredavid/france-geojson), pour situer les massifs dans le pays. Fichier d'origine
# tel que telecharge ; la version web est produite par `bra contours`. Source,
# empreinte et licence : docs/contours.md.
FRANCE_SOURCE = ICI / "france_metropole_ign2018.geojson"
FRANCE_WEB = ICI / "france.web.geojson"
# Une silhouette de fond n'a pas besoin de la precision des massifs : 0,01 degre ~ 1 km,
# coordonnees a 3 decimales (~100 m), 600 Ko -> 35 Ko.
TOLERANCE_FRANCE = 0.01


def charger(chemin: str | Path) -> dict:
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Raccordement:
    """Ecart entre les contours et le referentiel, dans les deux sens."""

    manquants: list[int]  # massifs du referentiel sans contour
    en_trop: list[int]  # contours sans massif au referentiel

    @property
    def complet(self) -> bool:
        return not self.manquants and not self.en_trop


def raccordement(geojson: dict) -> Raccordement:
    """Compare les codes des contours aux 36 massifs de `massifs.py`.

    Une entree sans correspondance est rendue, jamais ignoree : une region qui
    n'est pas un massif BRA colorerait la carte sans donnee derriere.
    """
    codes = {f["properties"]["code"] for f in geojson["features"]}
    return Raccordement(
        manquants=sorted(set(BY_ID) - codes),
        en_trop=sorted(codes - set(BY_ID)),
    )


# --------------------------------------------------------------------------
# Simplification pour le web
# --------------------------------------------------------------------------
#
# Douglas-Peucker en Python pur plutot que shapely : quelques centaines de
# kilo-octets de contours ne justifient pas une dependance compilee de plus
# (CLAUDE.md : toute dependance supplementaire se justifie). La topologie
# entre massifs voisins n'est pas preservee -- de fins interstices peuvent
# apparaitre a forte tolerance -- ce qui est acceptable pour colorer une carte.

Point = list[float]


def _distance(p: Point, a: Point, b: Point) -> float:
    """Distance du point `p` au segment `[a, b]`, en degres."""
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def _douglas_peucker(points: list[Point], tolerance: float) -> list[Point]:
    """Ligne ouverte simplifiee ; les extremites sont toujours conservees."""
    if len(points) < 3:
        return list(points)
    garder = [False] * len(points)
    garder[0] = garder[-1] = True
    pile = [(0, len(points) - 1)]
    while pile:
        debut, fin = pile.pop()
        loin, dmax = None, tolerance
        for i in range(debut + 1, fin):
            d = _distance(points[i], points[debut], points[fin])
            if d > dmax:
                loin, dmax = i, d
        if loin is not None:
            garder[loin] = True
            pile += [(debut, loin), (loin, fin)]
    return [p for p, g in zip(points, garder) if g]


def _simplifier_anneau(anneau: list[Point], tolerance: float, decimales: int) -> list[Point]:
    """Anneau ferme simplifie, jamais reduit sous trois sommets.

    Douglas-Peucker suppose deux extremites distinctes ; un anneau ferme n'en a
    qu'une. On le coupe donc au sommet le plus eloigne du premier, et l'on
    simplifie chaque moitie.
    """
    arrondi: list[Point] = []
    for x, y in anneau:
        p = [round(x, decimales), round(y, decimales)]
        if not arrondi or p != arrondi[-1]:
            arrondi.append(p)
    if len(arrondi) < 4:
        return arrondi
    sommets = arrondi[:-1] if arrondi[0] == arrondi[-1] else arrondi
    k = max(range(len(sommets)), key=lambda i: _distance(sommets[i], sommets[0], sommets[0]))
    moitie1 = _douglas_peucker(sommets[: k + 1], tolerance)
    moitie2 = _douglas_peucker(sommets[k:] + [sommets[0]], tolerance)
    garde = moitie1[:-1] + moitie2[:-1]
    if len(garde) < 3:
        # Tolerance trop forte pour ce polygone : on rajoute le sommet le plus
        # eloigne de la corde plutot que de rendre un segment.
        corde = (sommets[0], sommets[k])
        autre = max(
            (p for p in sommets if p not in garde),
            key=lambda p: _distance(p, *corde),
        )
        garde = sorted(garde + [autre], key=sommets.index)
    return garde + [garde[0]]


def simplifier(geojson: dict, tolerance: float, decimales: int = 4) -> dict:
    """Copie simplifiee d'un FeatureCollection de (Multi)Polygon.

    `tolerance` en degres (0,001 degre ~ 100 m en latitude). `decimales`
    arrondit les coordonnees : 4 decimales ~ 10 m, sous la precision d'une
    carte de massifs. L'objet d'origine n'est pas modifie.
    """
    def poly(rings: list) -> list:
        return [_simplifier_anneau(r, tolerance, decimales) for r in rings]

    features = []
    for f in geojson["features"]:
        g = f["geometry"]
        if g["type"] == "MultiPolygon":
            coords = [poly(p) for p in g["coordinates"]]
        elif g["type"] == "Polygon":
            coords = poly(g["coordinates"])
        else:
            raise ValueError(f"geometrie non surfacique : {g['type']}")
        features.append({
            "type": "Feature",
            "properties": dict(f["properties"]),
            "geometry": {"type": g["type"], "coordinates": coords},
        })
    return {"type": "FeatureCollection", "features": features}


def version_web(source: dict) -> dict:
    """Ce que la page embarque : contours simplifies, propriete `code` seule.

    Les libelles et la zone viennent de `massifs.py`, qui fait foi ; les
    garder ici en ferait une seconde source, a la graphie deja differente.
    """
    simple = simplifier(source, tolerance=TOLERANCE)
    for f in simple["features"]:
        f["properties"] = {"code": f["properties"]["code"]}
    return simple


def version_web_france(source: dict) -> dict:
    """Silhouette de la France pour la page : une seule entite, sans propriete.

    Le fichier d'origine est une `Feature` ; on l'enveloppe dans un
    `FeatureCollection` pour que `simplifier` et la page lisent le meme motif
    que pour les massifs.
    """
    if source.get("type") == "Feature":
        source = {"type": "FeatureCollection", "features": [source]}
    simple = simplifier(source, tolerance=TOLERANCE_FRANCE, decimales=3)
    for f in simple["features"]:
        f["properties"] = {}
    return simple
