"""Referentiel des massifs BRA.

L'identifiant numerique est la seule cle stable : le libelle `MASSIF` change de
graphie au fil des epoques (`ASPE-OSSAU` -> `Aspe Ossau`, `ANDORRE` ->
`Andorre (massif)`), et le nom de fichier suit ces variations. Voir
docs/exploration.md section 1.4.
"""

from __future__ import annotations

from typing import NamedTuple


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
