"""Referentiel des massifs BRA.

L'identifiant numerique est la seule cle stable : le libelle `MASSIF` change de
graphie au fil des epoques (`ASPE-OSSAU` -> `Aspe Ossau`, `ANDORRE` ->
`Andorre (massif)`), et le nom de fichier suit ces variations. Voir
docs/exploration.md section 1.4.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple
from urllib.parse import unquote


class Massif(NamedTuple):
    id: int
    nom: str
    zone: str
    departement: str


# Source : descriptif technique Meteo-France du 26/10/2023, annexe 1.
# Les libelles sont normalises ici ; les variantes rencontrees dans les fichiers
# sont resolues par l'ID, jamais par comparaison de chaines.
MASSIFS: tuple[Massif, ...] = (
    Massif(1, "Chablais", "Alpes du Nord", "Haute-Savoie"),
    Massif(2, "Aravis", "Alpes du Nord", "Haute-Savoie"),
    Massif(3, "Mont-Blanc", "Alpes du Nord", "Haute-Savoie"),
    Massif(4, "Bauges", "Alpes du Nord", "Savoie"),
    Massif(5, "Beaufortain", "Alpes du Nord", "Savoie"),
    Massif(6, "Haute-Tarentaise", "Alpes du Nord", "Savoie"),
    Massif(7, "Chartreuse", "Alpes du Nord", "Isere"),
    Massif(8, "Belledonne", "Alpes du Nord", "Isere"),
    Massif(9, "Maurienne", "Alpes du Nord", "Savoie"),
    Massif(10, "Vanoise", "Alpes du Nord", "Savoie"),
    Massif(11, "Haute-Maurienne", "Alpes du Nord", "Savoie"),
    Massif(12, "Grandes-Rousses", "Alpes du Nord", "Isere"),
    Massif(13, "Thabor", "Alpes du Sud", "Hautes-Alpes"),
    Massif(14, "Vercors", "Alpes du Nord", "Isere"),
    Massif(15, "Oisans", "Alpes du Nord", "Isere"),
    Massif(16, "Pelvoux", "Alpes du Sud", "Hautes-Alpes"),
    Massif(17, "Queyras", "Alpes du Sud", "Hautes-Alpes"),
    Massif(18, "Devoluy", "Alpes du Sud", "Hautes-Alpes"),
    Massif(19, "Champsaur", "Alpes du Sud", "Hautes-Alpes"),
    Massif(20, "Embrunais Parpaillon", "Alpes du Sud", "Hautes-Alpes"),
    Massif(21, "Ubaye", "Alpes du Sud", "Alpes de Haute-Provence"),
    Massif(22, "Haut-Var Haut-Verdon", "Alpes du Sud", "Alpes de Haute-Provence"),
    Massif(23, "Mercantour", "Alpes du Sud", "Alpes Maritimes"),
    Massif(40, "Cinto Rotondo", "Corse", "Haute-Corse"),
    Massif(41, "Renoso Incudine", "Corse", "Corse du Sud"),
    Massif(64, "Pays-Basque", "Pyrenees", "Pyrenees-Atlantiques"),
    Massif(65, "Aspe Ossau", "Pyrenees", "Pyrenees-Atlantiques"),
    Massif(66, "Haute-Bigorre", "Pyrenees", "Hautes-Pyrenees"),
    Massif(67, "Aure Louron", "Pyrenees", "Hautes-Pyrenees"),
    Massif(68, "Luchonnais", "Pyrenees", "Haute-Garonne"),
    Massif(69, "Couserans", "Pyrenees", "Ariege"),
    Massif(70, "Haute-Ariege", "Pyrenees", "Ariege"),
    Massif(71, "Andorre", "Pyrenees", "Andorre"),
    Massif(72, "Orlu St-Barthelemy", "Pyrenees", "Ariege"),
    Massif(73, "Capcir Puymorens", "Pyrenees", "Pyrenees-Orientales"),
    Massif(74, "Cerdagne Canigou", "Pyrenees", "Pyrenees-Orientales"),
)

BY_ID: dict[int, Massif] = {m.id: m for m in MASSIFS}

PYRENEES: tuple[int, ...] = tuple(m.id for m in MASSIFS if m.zone == "Pyrenees")
ALPES: tuple[int, ...] = tuple(m.id for m in MASSIFS if m.zone.startswith("Alpes"))
CORSE: tuple[int, ...] = tuple(m.id for m in MASSIFS if m.zone == "Corse")


def zone_of(massif_id: int) -> str | None:
    m = BY_ID.get(massif_id)
    return m.zone if m else None


def nom_of(massif_id: int) -> str | None:
    m = BY_ID.get(massif_id)
    return m.nom if m else None


def slugify(name: str) -> str:
    """Reduit un libelle de massif a une cle comparable entre epoques.

    `ASPE-OSSAU`, `Aspe Ossau` et `Aspe%20Ossau` donnent tous `aspeossau`.
    """
    name = unquote(name)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", name.lower())


# Variantes de graphie qui ne se reduisent pas au meme slug que le libelle
# de reference. Constatees dans l'archive 2016-2026.
_ALIASES: dict[str, int] = {
    "andorremassif": 71,          # `Andorre (massif)` (2024-2025)
    "embrunnaisparpaillon": 20,   # double `n` jusqu'en 2025
    "orlustbarthelemy": 72,       # `ORLU__ST_BARTHELEMY` (double underscore)
    "hautearige": 70,
}

SLUG_TO_ID: dict[str, int] = {slugify(m.nom): m.id for m in MASSIFS} | _ALIASES


def libelle_coherent(massif_id: int | None, nom_source: str | None) -> bool:
    """L'`ID` du bulletin et son libelle `MASSIF` designent-ils le meme massif ?

    L'`ID` est la cle stable, mais il n'est pas infaillible : en 2016 un message
    technique (« les BRA ne sont pas produits sur les massifs de moyenne
    montagne ») est diffuse sous `ID="3"` -- le Mont-Blanc au referentiel --
    avec `MASSIF="MOYENNE MONTAGNE"`. La ligne herite alors d'un massif, d'une
    zone et d'un departement qui ne sont pas les siens : sa zone est une
    fiction, et un filtre de perimetre pose sur `zone` ne la retient ni ne
    l'ecarte pour la bonne raison.

    Un libelle absent est tenu pour coherent : rien ne contredit l'`ID`.
    """
    if nom_source is None or not nom_source.strip():
        return True
    reference = BY_ID.get(massif_id)
    if reference is None:
        return False  # ID hors referentiel : rien a quoi comparer
    slug = slugify(nom_source)
    return slug == slugify(reference.nom) or SLUG_TO_ID.get(slug) == massif_id
