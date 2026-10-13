"""Parsing des BRA XML, toutes epoques confondues (2016 -> 2026).

Le format a change six fois sur la periode archivee. Ce module ramene ces
variantes a un enregistrement unique. Les ecarts traites sont documentes dans
docs/exploration.md ; les plus structurants :

- racine `<Bulletins>` encapsulante de 2019 a 2023, absente ailleurs, et dont
  l'attribut `nombre` est parfois faux (on itere sur les enfants reels) ;
- images embarquees en base64 jusqu'en 2023 (93 % du poids) : ignorees ;
- `LOC1`/`LOC2` polysemiques (altitude ou orientation) ;
- `EVOLURISQUE*` qui est un second indice de risque, pas un code d'evolution ;
- directions de vent en convention anglaise jusqu'en 2023, francaise ensuite ;
- `SS241`/`SS242` renommes `SS24Min`/`SS24Max` en 2024.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# Les orientations de pente (<PENTE NE=.. SW=..>) utilisent la convention
# anglaise a toutes les epoques. On aligne les directions de vent dessus pour
# que le dataset soit coherent avec lui-meme.
_DIRECTIONS = {
    "N": "N", "NE": "NE", "E": "E", "SE": "SE", "S": "S",
    "SW": "SW", "W": "W", "NW": "NW",
    "SO": "SW", "O": "W", "NO": "NW",
    "_": "VRB", "VRB": "VRB", "VAR": "VRB",
}

_ORIENTATIONS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "SO", "O", "NO"}

_LOC_ALTITUDE = re.compile(r"^\s*([<>])\s*(\d{3,4})\s*$")

# Palette `TEMPSSENSIBLE` du descriptif technique 2023. Les donnees contiennent
# des codes hors palette (-1, 5, 8..12, 15, 81) : on les conserve bruts dans
# `temps_sensible` et on laisse le libelle nul.
TEMPS_SENSIBLE = {
    0: "clair", 1: "peu nuageux", 2: "nuageux", 3: "tres nuageux", 4: "couvert",
    6: "voile", 7: "mer de nuages", 32: "brouillard", 38: "brouillard givrant",
    51: "pluie faible", 53: "pluie forte", 58: "pluie et neige melees",
    59: "pluie verglacante", 61: "neige faible", 63: "neige forte",
    70: "averses", 71: "rares averses", 77: "averses de pluie et neige melees",
    80: "averses de neige", 85: "averses de grele", 90: "orages",
    99: "orages violents",
}

PENTE_SECTEURS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class ParseError(Exception):
    """Le fichier n'est pas un BRA exploitable."""


@dataclass
class ParsedBulletin:
    """Un bulletin eclate en une ligne principale et ses tables filles."""

    bulletin: dict[str, Any]
    meteo: list[dict[str, Any]] = field(default_factory=list)
    enneigement: list[dict[str, Any]] = field(default_factory=list)
    neige_fraiche: list[dict[str, Any]] = field(default_factory=list)
    historique_risque: list[dict[str, Any]] = field(default_factory=list)
    tendances: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Conversions elementaires
# --------------------------------------------------------------------------

def _txt(value: str | None) -> str | None:
    """Texte nettoye, ou None si vide. Neutralise CDATA et entites deja decodees."""
    if value is None:
        return None
    cleaned = value.replace("\r\n", "\n").strip()
    return cleaned or None


def _bloc_texte(node: ET.Element, path: str) -> str | None:
    """Texte d'un bloc, descendants compris.

    `findtext` ne rend que le texte directement porte par l'element. Or certains
    bulletins enveloppent leur contenu dans du balisage HTML (`<h1>`), ce qui
    ferait ressortir un bloc vide. On concatene donc tout le texte de l'arbre.
    """
    element = node.find(path)
    if element is None:
        return None
    return _txt("".join(element.itertext()))


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _indice(value: str | None) -> int | None:
    """Indice de risque, toute valeur sous 1 valant « non estime ».

    Le descriptif 2023 annonce `RISQUE1` « toujours renseigne, valeur de 1 a 5 ».
    L'archive contredit ce point : les bulletins de debut et de fin de saison
    portent `-1` avec un commentaire du type « Pas d'enneigement ». Laisser cette
    sentinelle dans une colonne entiere fausserait toute moyenne, d'ou sa
    conversion en valeur nulle ; l'information est conservee par la colonne
    `risque_estime`.

    `0` suit la meme regle : un seul cas dans l'archive, l'avis de fin de
    saison du Chablais du 11/06/2018 (`RISQUE1="0"`, `RISQUEMAXI="/"`,
    « Rendez-vous debut novembre »). Hors de l'echelle, c'est un refus
    d'estimer, pas un indice.

    La regle vaut pour tous les champs d'indice, pas pour `RISQUE1` seul. Le
    seul autre `0` de l'archive est dans le bloc historique : la journee du
    16/04/2022 du Haut-Var/Haut-Verdon porte `RISQUEMAXI="0"` dans les huit
    bulletins rediges du 16 au 22/04/2022, alors que le BRA couvrant ce jour
    dit 1. Ces huit lignes de `historique_risque` deviennent nulles, comme les
    autres jours non renseignes de cette table.
    """
    parsed = _int(value)
    if parsed is not None and parsed < 1:
        return None
    return parsed


def _mesure(value: str | None) -> int | None:
    """Mesure altimetrique, `-1` valant « sans objet ».

    Documente pour `PLUIENEIGE` (temps sec) et `MERNUAGES` (pas de mer de nuages).
    """
    parsed = _int(value)
    if parsed is not None and parsed < 0:
        return None
    return parsed


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    value = value.strip().lower()
    if value in ("true", "1", "oui"):
        return True
    if value in ("false", "0", "non"):
        return False
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """Datetime naif (heure locale France).

    Trois formes coexistent dans l'archive :
    - `2016-03-09T14:05:23.2144571Z` : fraction a 7 chiffres + UTC (2016) ;
    - `2023-02-15T15:02:05` : naif, heure locale (2017+) ;
    - vide ou absent (`DATEVALIDITE` n'existe pas en 2016).

    Le suffixe `Z` est converti en heure locale France pour rester comparable
    aux autres millesimes. La conversion utilise l'offset saisonnier (CET/CEST)
    car les BRA sont diffuses en heure legale francaise.
    """
    value = (value or "").strip()
    if not value:
        return None

    is_utc = value.endswith("Z")
    if is_utc:
        value = value[:-1]

    # `fromisoformat` refuse les fractions a 7 chiffres avant Python 3.11+
    # et reste fragile : on tronque a la microseconde.
    if "." in value:
        head, _, frac = value.partition(".")
        value = f"{head}.{frac[:6]}" if frac[:6].isdigit() else head

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if is_utc:
        # Heure legale francaise : UTC+1 l'hiver, UTC+2 du dernier dimanche de
        # mars au dernier dimanche d'octobre. La saison BRA est majoritairement
        # hivernale, mais mars/avril/octobre existent dans l'archive.
        offset = 2 if _is_summer_time(parsed) else 1
        parsed = parsed + timedelta(hours=offset)
    return parsed


def _last_sunday(year: int, month: int) -> date:
    day = monthrange(year, month)[1]
    d = date(year, month, day)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _is_summer_time(dt: datetime) -> bool:
    """Heure d'ete europeenne : dernier dimanche de mars 01:00 UTC -> octobre."""
    start = _last_sunday(dt.year, 3)
    end = _last_sunday(dt.year, 10)
    return start <= dt.date() < end


def normalize_direction(value: str | None) -> str | None:
    """Direction de vent ramenee a la convention anglaise, `VRB` si variable."""
    if value is None:
        return None
    key = value.strip().upper()
    if not key:
        return None
    return _DIRECTIONS.get(key)


def parse_localisation(loc: str | None, altitude: str | None) -> tuple[str | None, int | None, str | None]:
    """Decompose `LOC1`/`LOC2`, qui melangent altitude et orientation.

    Renvoie `(type, seuil_altitude, secteur)` avec type dans
    `{"altitude", "orientation", None}`.

    - `"<2200"` -> `("altitude", 2200, None)`
    - `"S"`     -> `("orientation", None, "S")`
    - `""`      -> `(None, None, None)`

    L'attribut `ALTITUDE` du meme element porte la meme borne ; il sert de
    repli quand `LOC` est vide mais qu'une distinction altitudinale existe.
    """
    raw = (loc or "").strip()
    alt = _int(altitude)

    if raw:
        match = _LOC_ALTITUDE.match(raw)
        if match:
            return "altitude", int(match.group(2)), None
        key = raw.upper()
        if key in _ORIENTATIONS:
            return "orientation", None, _DIRECTIONS.get(key, key)

    if alt is not None:
        return "altitude", alt, None
    return None, None, None


def season_of(moment: datetime | date | None) -> tuple[int | None, str | None]:
    """Saison nivologique : `(annee_de_depart, libelle)`.

    Les BRA courent de novembre a mai. Une bascule en septembre place
    l'integralite d'une campagne hivernale dans la meme saison, y compris les
    bulletins d'octobre et ceux de mai/juin.
    """
    if moment is None:
        return None, None
    year = moment.year
    start = year if moment.month >= 9 else year - 1
    return start, f"{start}-{start + 1}"


# --------------------------------------------------------------------------
# Localisation de la racine
# --------------------------------------------------------------------------

def iter_bulletin_elements(root: ET.Element):
    """Rend les elements `BULLETINS_NEIGE_AVALANCHE` quelle que soit l'epoque.

    De 2019 a 2023 ils sont encapsules dans `<Bulletins nombre="N">`, dont
    l'attribut `nombre` est parfois faux (vu : `nombre="2"` pour un seul
    enfant). On ignore l'attribut et on itere sur les enfants reels.
    """
    if root.tag == "BULLETINS_NEIGE_AVALANCHE":
        yield root
        return
    found = root.findall("BULLETINS_NEIGE_AVALANCHE")
    if not found:
        found = root.findall(".//BULLETINS_NEIGE_AVALANCHE")
    yield from found


def detect_schema_version(node: ET.Element) -> int:
    """Numero d'epoque (1 a 6), deduit de marqueurs structurels et non de la date.

    1: 2016 (pas de BSH)               4: 2024 (images externalisees)
    2: 2017-2018 (BSH)                 5: 2025 (STABILITE/TITRE)
    3: 2019-2023 (<DateValidite>)      6: 2026 (LienDocumentation/a)
    """
    modern = node.find("STABILITE/SitAvalTyp") is not None or node.find("CARTOUCHERISQUE/ImageRisque") is not None
    if modern:
        if node.find("TexteMeta/LienDocumentation/a") is not None:
            return 6
        if node.find("STABILITE/TITRE") is not None:
            return 5
        return 4
    if node.find("BSH") is None:
        return 1
    if node.find("DateValidite") is not None:
        return 3
    return 2


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def _attr_fallback(el: ET.Element | None, *names: str) -> str | None:
    """Premier attribut renseigne parmi `names` (gere les renommages d'epoque)."""
    if el is None:
        return None
    for name in names:
        value = el.get(name)
        if value is not None and value.strip():
            return value
    return None


def _extract_meteo(node: ET.Element, path: str, origine: str) -> list[dict[str, Any]]:
    rows = []
    for idx, ech in enumerate(node.findall(path)):
        code = _int(ech.get("TEMPSSENSIBLE"))
        rows.append({
            "origine": origine,
            "rang": idx,
            "echeance": parse_datetime(ech.get("DATE")),
            "vent_bas_vitesse_kmh": _int(ech.get("FF1")),
            "vent_bas_direction": normalize_direction(ech.get("DD1")),
            "vent_haut_vitesse_kmh": _int(ech.get("FF2")),
            "vent_haut_direction": normalize_direction(ech.get("DD2")),
            "iso_0_m": _int(ech.get("ISO0")),
            "iso_moins10_m": _int(ech.get("ISO-10")),
            "limite_pluie_neige_m": _mesure(ech.get("PLUIENEIGE")),
            "temps_sensible": code,
            "temps_sensible_libelle": TEMPS_SENSIBLE.get(code) if code is not None else None,
            "mer_nuages_m": _mesure(ech.get("MERNUAGES")),
        })
    return rows


def _extract_enneigement(node: ET.Element, path: str, origine: str) -> list[dict[str, Any]]:
    rows = []
    for enn in node.findall(path):
        moment = parse_datetime(enn.get("DATE"))
        limite_n = _int(enn.get("LimiteNord"))
        limite_s = _int(enn.get("LimiteSud"))
        for niveau in enn.findall("NIVEAU"):
            rows.append({
                "origine": origine,
                "date_enneigement": moment,
                "limite_nord_m": limite_n,
                "limite_sud_m": limite_s,
                "altitude_m": _int(niveau.get("ALTI")),
                "epaisseur_nord_cm": _int(niveau.get("N")),
                "epaisseur_sud_cm": _int(niveau.get("S")),
            })
    return rows


def _extract_neige_fraiche(node: ET.Element, path: str, origine: str) -> list[dict[str, Any]]:
    parent = node.find(path)
    if parent is None:
        return []
    altitude = _int(parent.get("ALTITUDESS"))
    rows = []
    for neige in parent.findall("NEIGE24H"):
        rows.append({
            "origine": origine,
            "date_cumul": parse_datetime(neige.get("DATE")),
            "altitude_mesure_m": altitude,
            # Renomme en 2024 : SS241/SS242 -> SS24Min/SS24Max.
            "cumul_min_cm": _int(_attr_fallback(neige, "SS24Min", "SS241")),
            "cumul_max_cm": _int(_attr_fallback(neige, "SS24Max", "SS242")),
        })
    return rows


def parse_bulletin_element(node: ET.Element, source: str | None = None) -> ParsedBulletin:
    """Convertit un element `BULLETINS_NEIGE_AVALANCHE` en enregistrement plat."""
    massif_id = _int(node.get("ID"))
    if massif_id is None:
        raise ParseError(f"attribut ID absent ({source})")

    date_bulletin = parse_datetime(node.get("DATEBULLETIN"))
    if date_bulletin is None:
        raise ParseError(f"DATEBULLETIN absente ou illisible ({source})")

    # Le risque annonce porte sur l'echeance (J+1 en regle generale), pas sur la
    # date de redaction. Une serie indexee sur `jour_bulletin` est decalee d'un
    # jour.
    #
    # Le jour couvert est porte par `DATEECHEANCE`, pas par `DATEVALIDITE`. Les
    # deux coincident sur la totalite des bulletins estimes (18 869 sur 18 869),
    # ce qui rend la confusion facile et sans consequence visible en pleine
    # saison. Elles divergent hors saison : `DATEVALIDITE` y annonce la date du
    # *prochain* bulletin -- « valable jusqu'au... » -- et non le jour decrit.
    # Le massif 64 redige ainsi les 17, 18, 19 et 20 novembre 2016 quatre
    # bulletins portant tous `DATEVALIDITE="2016-11-21"`, pour des `DATEECHEANCE`
    # regulierement espacees du 18 au 21. Prendre `DATEVALIDITE` en premier
    # ecrase ces quatre jours en un seul et fait disparaitre 2 471 bulletins de
    # la vue journaliere.
    #
    # `DATEECHEANCE` est renseignee sur les 23 533 bulletins du corpus ; le
    # repli sur `DATEVALIDITE` n'est donc jamais emprunte aujourd'hui, il ne
    # couvre qu'une archive future qui omettrait l'attribut.
    date_validite = parse_datetime(node.get("DATEVALIDITE") or node.findtext("DateValidite"))
    date_echeance = parse_datetime(node.get("DATEECHEANCE"))
    reference = date_echeance or date_validite

    version = detect_schema_version(node)
    saison_debut, saison = season_of(date_bulletin)

    risque = node.find("CARTOUCHERISQUE/RISQUE")
    ra = risque.attrib if risque is not None else {}
    # `-1` (ou, une fois, `0`) marque un bulletin sans estimation chiffree :
    # hors saison, sous-neige, avis de fin de saison. Meme regle que `_indice`.
    risque_estime = _indice(ra.get("RISQUE1")) is not None
    loc1_type, loc1_alt, loc1_secteur = parse_localisation(ra.get("LOC1"), ra.get("ALTITUDE"))
    loc2_type, loc2_alt, loc2_secteur = parse_localisation(ra.get("LOC2"), ra.get("ALTITUDE"))

    pente = node.find("CARTOUCHERISQUE/PENTE")
    pa = pente.attrib if pente is not None else {}

    sat = node.find("STABILITE/SitAvalTyp")

    # `TEXTESANSTITRE` n'existe que depuis 2025 ; avant, le titre est fondu
    # dans `TEXTE`. On expose les deux et on laisse le titre nul si absent.
    stabilite_titre = _bloc_texte(node, "STABILITE/TITRE")
    stabilite_texte = _bloc_texte(node, "STABILITE/TEXTESANSTITRE") or _bloc_texte(node, "STABILITE/TEXTE")

    enneigement_jour = node.find("ENNEIGEMENT")

    bulletin = {
        # --- cle et partitionnement ---
        "massif_id": massif_id,
        "date_bulletin": date_bulletin,
        "jour_bulletin": date_bulletin.date(),
        "jour_validite": reference.date() if reference else None,
        "saison": saison,
        "saison_debut": saison_debut,
        # --- identite ---
        "massif_nom_source": _txt(node.get("MASSIF")),
        "type_bulletin": _txt(node.get("TYPEBULLETIN")),
        "producteur": _txt(node.get("PRODUCTEUR")),  # disparait en 2024
        "amendement": _bool(node.get("AMENDEMENT")),
        # --- dates ---
        "date_diffusion": parse_datetime(node.get("DATEDIFFUSION")),
        "date_echeance": date_echeance,
        "date_validite": date_validite,
        # --- risques ---
        "risque1": _indice(ra.get("RISQUE1")),
        # Second indice de la journee, malgre le nom de l'attribut.
        "risque1_evolution": _indice(ra.get("EVOLURISQUE1")),
        "risque2": _indice(ra.get("RISQUE2")),
        "risque2_evolution": _indice(ra.get("EVOLURISQUE2")),
        "risque_maxi": _indice(ra.get("RISQUEMAXI")),
        "loc_type": loc1_type or loc2_type,
        "altitude_seuil_m": loc1_alt or loc2_alt,
        "loc1_secteur": loc1_secteur,
        "loc2_secteur": loc2_secteur,
        "risque_estime": risque_estime,
        "risque_commentaire": _txt(ra.get("COMMENTAIRE")),
        # --- J+2 (2024+) ---
        "risque_maxi_j2": _indice(ra.get("RISQUEMAXIJ2")),
        "date_risque_j2": parse_datetime(ra.get("DATE_RISQUE_J2")),
        "risque_j2_libelle": _bloc_texte(node, "CARTOUCHERISQUE/RisqueJ2"),
        "risque_j2_commentaire": _bloc_texte(node, "CARTOUCHERISQUE/CommentaireRisqueJ2"),
        # --- rose des pentes ---
        **{f"pente_{s.lower()}": _bool(pa.get(s)) for s in PENTE_SECTEURS},
        "pente_commentaire": _txt(pa.get("COMMENTAIRE")),
        # --- textes ---
        "resume": _bloc_texte(node, "CARTOUCHERISQUE/RESUME"),
        "accidentel": _bloc_texte(node, "CARTOUCHERISQUE/ACCIDENTEL"),
        "naturel": _bloc_texte(node, "CARTOUCHERISQUE/NATUREL"),
        "avis": _bloc_texte(node, "CARTOUCHERISQUE/AVIS"),
        "vigilance": _bloc_texte(node, "CARTOUCHERISQUE/VIGILANCE"),
        "stabilite_titre": stabilite_titre,
        "stabilite_texte": stabilite_texte,
        "qualite_texte": _bloc_texte(node, "QUALITE/TEXTE"),
        "meteo_commentaire": _bloc_texte(node, "METEO/COMMENTAIRE"),
        # --- situations avalancheuses typiques (2024+) ---
        "sat1": _indice(sat.get("SAT1")) if sat is not None else None,
        "sat2": _indice(sat.get("SAT2")) if sat is not None else None,
        # --- enneigement du jour ---
        "enneigement_limite_nord_m": _int(enneigement_jour.get("LimiteNord")) if enneigement_jour is not None else None,
        "enneigement_limite_sud_m": _int(enneigement_jour.get("LimiteSud")) if enneigement_jour is not None else None,
        "vent_altitude_basse_m": _int(_attr_fallback(node.find("METEO"), "ALTITUDEVENT1")),
        "vent_altitude_haute_m": _int(_attr_fallback(node.find("METEO"), "ALTITUDEVENT2")),
        # --- provenance ---
        "schema_version": version,
        "format_famille": "moderne" if version >= 4 else "legacy",
        "fichier_source": source,
    }

    parsed = ParsedBulletin(bulletin=bulletin)
    parsed.meteo = _extract_meteo(node, "METEO/ECHEANCE", "prevision")
    parsed.meteo += _extract_meteo(node, "BSH/METEO/ECHEANCE", "historique")
    parsed.enneigement = _extract_enneigement(node, "ENNEIGEMENT", "jour")
    parsed.enneigement += _extract_enneigement(node, "BSH/ENNEIGEMENTS/ENNEIGEMENT", "historique")
    parsed.neige_fraiche = _extract_neige_fraiche(node, "NEIGEFRAICHE", "prevision")
    parsed.neige_fraiche += _extract_neige_fraiche(node, "BSH/NEIGEFRAICHE", "historique")

    for r in node.findall("BSH/RISQUES/RISQUE"):
        parsed.historique_risque.append({
            "date_risque": parse_datetime(r.get("DATE")),
            "risque_maxi": _indice(r.get("RISQUEMAXI")),
        })

    # `TENDANCES` existe de 2016 a 2023 et n'est pas documente ; absent en 2024+.
    for t in node.findall("TENDANCES/TENDANCE"):
        parsed.tendances.append({
            "date_tendance": parse_datetime(t.get("DATE")),
            "valeur": _txt(t.get("VALEUR")),
        })

    return parsed


def parse_file(path: str | Path) -> list[ParsedBulletin]:
    """Parse un fichier BRA. Rend une liste : un fichier peut contenir N bulletins."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ParseError(f"XML invalide : {path.name} ({exc})") from exc

    results = [parse_bulletin_element(node, source=path.name) for node in iter_bulletin_elements(root)]
    if not results:
        raise ParseError(f"aucun bulletin dans {path.name}")
    return results
