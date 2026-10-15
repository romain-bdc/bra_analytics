"""Tranches d'altitude normees (T5) : vue `palier_tranche`.

Les bornes sont fermees a gauche : [0, 1800), [1800, 2400), [2400, +inf).
Les paliers d'enneigement de l'archive tombent exactement sur ces bornes
(1500/1800/2400 avant 2021, 1500/2000/2500 ensuite) : fermer a gauche donne un
palier par tranche aux deux epoques.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from bra_analytics.build import build

from .conftest import FIXTURES


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tranches")
    db = tmp / "bra.duckdb"
    build(FIXTURES, tmp / "warehouse", db)
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


def _paliers(con, source: str, massif: int, jour: date) -> list[tuple]:
    return con.execute(
        "SELECT DISTINCT altitude_m, tranche FROM palier_tranche "
        "WHERE source = ? AND massif_id = ? AND jour = ? ORDER BY altitude_m",
        [source, massif, jour],
    ).fetchall()


def test_paliers_sur_les_bornes(con) -> None:
    """Aspe-Ossau, releve du 09/03/2016 : paliers 1500 / 1800 / 2400 (XML,
    NIVEAU ALTI). `jour` est la date que decrit la valeur, pas la validite."""
    assert _paliers(con, "enneigement", 65, date(2016, 3, 9)) == [
        (1500, "basse"), (1800, "moyenne"), (2400, "haute"),
    ]


def _par_bulletin(con, massif: int, jour: date) -> dict[int, list[tuple]]:
    """Paliers d'enneigement d'un jour, par heure de redaction du bulletin."""
    rows = con.execute(
        "SELECT hour(date_bulletin), altitude_m, tranche FROM palier_tranche "
        "WHERE source = 'enneigement' AND massif_id = ? AND jour = ? "
        "ORDER BY 1, 2", [massif, jour],
    ).fetchall()
    out: dict[int, list[tuple]] = {}
    for h, alt, tr in rows:
        out.setdefault(h, []).append((alt, tr))
    return out


def test_tranche_absente_reste_vide(con) -> None:
    """Couserans, bulletin du soir : paliers 1500 / 1800 / 2100. Rien au-dessus
    de 2400 m -- la tranche haute n'a pas de ligne, rien n'est interpole."""
    soir = _par_bulletin(con, 69, date(2016, 3, 31))[16]
    assert sorted({tr for _, tr in soir}) == ["basse", "moyenne"]
    assert sorted({alt for alt, _ in soir}) == [1500, 1800, 2100]


def test_releve_vide_sans_tranche_mais_visible(con) -> None:
    """Couserans, amendement du matin : `ALTI="-1"` sur les trois paliers,
    releve non fait. Le parser rend l'altitude nulle ; la ligne reste dans la
    vue, sans tranche -- un `CASE` naif sur `-1` l'aurait rangee en basse."""
    matin = _par_bulletin(con, 69, date(2016, 3, 31))[6]
    assert matin and all(alt is None and tr is None for alt, tr in matin)


def test_massif_dont_les_paliers_tombent_dans_une_seule_tranche(con) -> None:
    """Neige fraiche d'Aspe-Ossau, 2015-2016 : une seule altitude de mesure,
    1800 m (XML, ALTITUDESS). Tous ses paliers tombent en tranche moyenne ; les
    tranches basse et haute n'ont aucune donnee, et l'audit doit le dire plutot
    que de laisser croire a une comparaison possible sur ces tranches.

    Aucun bulletin de l'archive (Pyrenees, Corse, Alpes 2016-2018) n'a ses
    trois paliers d'enneigement dans une meme tranche : c'est la neige fraiche
    et le vent, une altitude chacun, qui donnent le cas reel.
    """
    from bra_analytics import audit

    conc = audit.concentration_tranches(con)
    ligne = lambda src: conc.filter(  # noqa: E731
        (conc["source"] == src) & (conc["massif_id"] == 65) & (conc["saison"] == "2015-2016")
    ).row(0, named=True)

    nf = ligne("neige_fraiche")
    assert (nf["altitudes"], nf["tranches"], nf["n_tranches"]) == ("1800", "moyenne", 1)
    enn = ligne("enneigement")
    assert (enn["tranches"], enn["n_tranches"]) == ("basse, moyenne, haute", 3)


def _vents(con, massif: int, jour: date) -> list[tuple]:
    return con.execute(
        "SELECT DISTINCT source, altitude_m, tranche FROM palier_tranche "
        "WHERE source LIKE 'vent_%' AND massif_id = ? AND jour = ? ORDER BY altitude_m",
        [massif, jour],
    ).fetchall()


def test_vent_a_3000_m_en_tranche_haute_aux_deux_epoques(con) -> None:
    """Queyras : jusqu'en 2023 un seul vent, a 3000 m, porte par `FF1`
    (`ALTITUDEVENT2="9999"`) ; depuis 2024, 2000 et 3000 m. Le vent a 3000 m
    change de colonne mais pas de tranche : la serie haute est continue, et
    aucune altitude fictive n'apparait."""
    assert _vents(con, 17, date(2023, 1, 15)) == [("vent_bas", 3000, "haute")]
    assert _vents(con, 17, date(2024, 1, 15)) == [
        ("vent_bas", 2000, "moyenne"), ("vent_haut", 3000, "haute"),
    ]
