"""Contours des massifs (T3) : raccordement au referentiel et simplification."""

from __future__ import annotations

import json

from bra_analytics import geo
from bra_analytics.massifs import BY_ID

from .conftest import fixture


def _mini() -> dict:
    return json.loads(fixture("contours_mini.geojson").read_text(encoding="utf-8"))


def test_raccordement_signale_les_manquants_et_les_entrees_en_trop() -> None:
    """Un contour sans massif au referentiel est signale, pas ignore ; un massif
    sans contour aussi."""
    r = geo.raccordement(_mini())
    assert r.en_trop == [99]
    assert r.manquants == sorted(set(BY_ID) - {64, 65})
    assert not r.complet


def _anneau(geojson: dict, code: int) -> list:
    f = next(f for f in geojson["features"] if f["properties"]["code"] == code)
    return f["geometry"]["coordinates"][0][0]


def test_simplifier_retire_les_points_quasi_alignes() -> None:
    """Le point (-0.95, 43.001) s'ecarte de 0,001 degre du segment qui le
    porte : sous une tolerance de 0,01 il disparait, l'anneau reste ferme."""
    simple = geo.simplifier(_mini(), tolerance=0.01, decimales=4)
    assert _anneau(simple, 64) == [
        [-1.0, 43.0], [-0.9, 43.0], [-0.9, 43.1], [-1.0, 43.1], [-1.0, 43.0]
    ]


def test_simplifier_ne_degenere_pas_un_anneau() -> None:
    """Une tolerance demesuree ne doit pas reduire un polygone a un segment :
    un anneau garde au moins quatre points (trois sommets, ferme)."""
    simple = geo.simplifier(_mini(), tolerance=10.0, decimales=4)
    for code in (64, 65, 99):
        anneau = _anneau(simple, code)
        assert len(anneau) >= 4
        assert anneau[0] == anneau[-1]


def test_simplifier_conserve_le_code_et_l_original() -> None:
    original = _mini()
    avant = json.dumps(original)
    simple = geo.simplifier(original, tolerance=0.01, decimales=4)
    assert json.dumps(original) == avant, "l'original ne doit pas etre modifie"
    assert [f["properties"]["code"] for f in simple["features"]] == [64, 65, 99]


def test_bra_contours_ecrit_la_version_web_et_signale_les_ecarts(tmp_path, capsys) -> None:
    """La commande ecrit le fichier simplifie meme incomplet, mais le dit et
    sort en erreur : un ecart de raccordement ne passe jamais en silence."""
    from bra_analytics.cli import main

    out = tmp_path / "massifs.web.geojson"
    code = main(["contours", "--source", str(fixture("contours_mini.geojson")),
                 "--out", str(out)])
    assert code == 1
    texte = capsys.readouterr().out
    assert "99" in texte and "71" in texte
    ecrit = json.loads(out.read_text(encoding="utf-8"))
    # Seul `code` est conserve : les libelles viennent de `massifs.py`.
    assert [f["properties"] for f in ecrit["features"]] == [
        {"code": 64}, {"code": 65}, {"code": 99}
    ]


def test_contours_versionnes_raccordes_aux_36_massifs() -> None:
    """Le fichier Meteo-France versionne couvre exactement le referentiel."""
    assert geo.raccordement(geo.charger(geo.SOURCE)).complet
