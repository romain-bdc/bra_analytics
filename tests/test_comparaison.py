"""Ecran de comparaison (T13, spec section 6).

Deux niveaux. Le payload se teste en Python. Le comportement de la page -- la
troncature a periode egale, le refus de classer, les saisons etiquetees -- vit
dans le gabarit : il se teste en le rendant dans Chromium headless (`--dump-dom`)
et en lisant le DOM. Ces tests sont sautes si aucun Chromium n'est installe.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

import duckdb
import pytest

from bra_analytics import comparaison
from bra_analytics.build import build
from bra_analytics.dashboard import injecter
from bra_analytics.fenetres import DEFAUT, SAISON_COMPLETE, SAISONS_NON_COMPARABLES
from bra_analytics.metriques import risque
from bra_analytics.metriques.risque import ComparaisonRefusee

from .conftest import SERIES

ASPE = 65


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("comparaison")
    chemin = tmp / "bra.duckdb"
    source = tmp / "source"
    for bloc in ("risque", "enneigement"):
        shutil.copytree(SERIES / bloc, source, dirs_exist_ok=True)
    build(source, tmp / "warehouse", chemin)
    return chemin


@pytest.fixture(scope="module")
def data(db) -> dict:
    return comparaison.payload(db)


# --- payload ---------------------------------------------------------------------

def test_metrique_d_indice_refusee_hors_coeur() -> None:
    comparaison.verifier("risque_moyen", DEFAUT.nom)
    for fenetre in ("commune", SAISON_COMPLETE):
        with pytest.raises(ComparaisonRefusee):
            comparaison.verifier("risque_moyen", fenetre)


def test_neige_se_compare_sur_les_fenetres_nommees_seulement() -> None:
    comparaison.verifier("epaisseur_max", "commune")
    with pytest.raises(ComparaisonRefusee):
        comparaison.verifier("epaisseur_max", SAISON_COMPLETE)


def test_matrice_de_refus_voyage_dans_le_payload(data) -> None:
    """Le gabarit ne decide rien : il lit `refus`, ecrit une seule fois en Python."""
    for m in data["metriques"]:
        for f in data["fenetres"]:
            attendu = comparaison.refus(m["cle"], f["nom"])
            assert data["refus"][m["cle"]][f["nom"]] == attendu
            assert (attendu is None) == (
                (f["comparable"] if m["indice"] else f["comparable_enneigement"])
            )


def test_saisons_non_comparables_etiquetees_pas_supprimees(data) -> None:
    par_nom = {s["nom"]: s for s in data["saisons"]}
    for saison, motif in SAISONS_NON_COMPARABLES.items():
        if saison in par_nom:
            assert par_nom[saison]["comparable"] is False
            assert par_nom[saison]["motif"] == motif
    assert par_nom["2023-2024"]["comparable"] is True
    # Une saison ecartee garde ses series : elle est etiquetee, pas retiree.
    assert {s for s in par_nom if not par_nom[s]["comparable"]} <= set(data["series"][ASPE]) | {
        s for s in par_nom if s not in data["series"][ASPE]}


def test_bornes_de_fenetre_viennent_de_fenetres_py(data) -> None:
    coeur = next(f for f in data["fenetres"] if f["nom"] == DEFAUT.nom)
    assert coeur["debut"] == list(DEFAUT.debut) and coeur["fin"] == list(DEFAUT.fin)
    assert data["max_courbes"] == 4


def test_la_page_est_autonome(db, tmp_path) -> None:
    html = comparaison.render(db, tmp_path / "c.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "__DONNEES__" not in html and "__COMMUN__" not in html
    assert "<script src" not in html
    assert "Licence Ouverte 2.0" in html


# --- page, rendue dans Chromium ---------------------------------------------------

def _chromium() -> str | None:
    if os.environ.get("BRA_CHROMIUM"):
        return os.environ["BRA_CHROMIUM"]
    trouves = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    return trouves[0] if trouves else shutil.which("chromium") or shutil.which("chromium-browser")


chromium = pytest.mark.skipif(_chromium() is None, reason="Chromium headless absent (BRA_CHROMIUM)")


class _Dom(HTMLParser):
    """Attributs et texte par `id`, plus les elements portant `data-*` repetes."""

    def __init__(self) -> None:
        super().__init__()
        self.attrs: dict[str, dict] = {}
        self.texte: dict[str, str] = {}
        self.lignes: list[dict] = []
        self._pile: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        ident = a.get("id")
        if ident:
            self.attrs[ident] = a
            self.texte[ident] = ""
        if tag in ("g", "tr") and ("data-saison" in a or "data-id" in a):
            self.lignes.append({"tag": tag, **a, "texte": ""})
        if tag not in ("br", "meta", "link", "input", "option", "line", "rect", "path", "circle"):
            self._pile.append(ident)

    def handle_endtag(self, tag):
        if self._pile:
            self._pile.pop()

    def handle_data(self, d):
        for ident in self._pile:
            if ident:
                self.texte[ident] += d
        if self.lignes:
            self.lignes[-1]["texte"] += d


def _dom(html: str, fragment: str, tmp: Path) -> _Dom:
    page = tmp / "page.html"
    page.write_text(html, encoding="utf-8")
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=4000", "--dump-dom",
         f"file://{page}#{fragment}"],
        capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    dom = _Dom()
    dom.feed(sortie)
    return dom


def _serie_synthetique(debut: int, jusqu_au: date, depuis: date) -> dict:
    """Une saison : un indice 2 par jour de `depuis` a `jusqu_au`, '.' ailleurs."""
    origine = date(debut, 10, 1)
    n = 250
    cases = ["."] * n
    j = depuis
    while j <= jusqu_au:
        cases[(j - origine).days] = "2"
        j += timedelta(days=1)
    return {"origine": origine.isoformat(), "longueur": n, "risque": "".join(cases)}


@pytest.fixture(scope="module")
def synthetique(data) -> dict:
    """Aspe-Ossau sur cinq saisons ; 2022-2023 s'arrete le 31 mars, 2019-2020 le 20 mars."""
    d = dict(data)
    fin = {"2016-2017": (2017, 4, 30), "2018-2019": (2019, 4, 30), "2019-2020": (2020, 3, 20),
           "2021-2022": (2022, 4, 30), "2022-2023": (2023, 3, 31)}
    d["series"] = {ASPE: {
        s: _serie_synthetique(int(s[:4]), date(*f), date(int(s[:4]), 12, 1)) for s, f in fin.items()
    }}
    d["massifs"] = [m for m in data["massifs"] if m["id"] == ASPE]
    d["massifs"][0] = {**d["massifs"][0], "saisons": list(fin)}
    d["saisons"] = [s for s in data["saisons"] if s["nom"] in fin]
    d["bandes"] = {}
    return d


@chromium
def test_troncature_a_periode_egale_par_defaut_et_annoncee(synthetique, tmp_path) -> None:
    html = injecter(comparaison.TEMPLATE, synthetique)
    dom = _dom(html, "x=saison&m=65&s=2021-2022", tmp_path)
    for ident in ("sous-courbes", "sous-table", "sous-rang"):
        assert dom.attrs[ident]["data-tronque"] == "1"
        # 2022-2023 s'arrete le 31 mars : c'est elle qui raccourcit la periode commune.
        assert dom.attrs[ident]["data-periode"] == "12-15..03-31"
        assert "tronquée à période égale" in dom.texte[ident]
        assert "2022-2023 s'arrête le 31 mars" in dom.texte[ident]
    # 2019-2020 (non comparable, arretee le 20 mars) ne fixe pas la periode.
    ligne = {l["data-id"]: l for l in dom.lignes if l["tag"] == "tr"}
    assert ligne["2022-2023"]["texte"].count("107") >= 1     # 15 dec -> 31 mars = 107 jours
    assert ligne["2016-2017"]["texte"].count("107") >= 1


@chromium
def test_sans_troncature_chaque_serie_garde_sa_fenetre(synthetique, tmp_path) -> None:
    html = injecter(comparaison.TEMPLATE, synthetique)
    dom = _dom(html, "x=saison&m=65&s=2021-2022&p=0", tmp_path)
    assert dom.attrs["sous-courbes"]["data-tronque"] == "0"
    assert "Troncature désactivée" in dom.texte["sous-courbes"]
    ligne = {l["data-id"]: l for l in dom.lignes if l["tag"] == "tr"}
    assert "122" in ligne["2016-2017"]["texte"]               # 15 dec -> 15 avr, toute la fenetre
    assert "107" in ligne["2022-2023"]["texte"]


@chromium
def test_classement_refuse_une_metrique_d_indice_hors_coeur(synthetique, tmp_path) -> None:
    html = injecter(comparaison.TEMPLATE, synthetique)
    refuse = _dom(html, "x=saison&m=65&k=risque_moyen&f=commune", tmp_path)
    assert refuse.attrs["refus"]["data-refus"] == "1"
    assert "Classement refusé" in refuse.texte["refus"]
    assert not [l for l in refuse.lignes if l["tag"] == "g"]    # aucune barre
    accepte = _dom(html, "x=saison&m=65&k=risque_moyen&f=coeur", tmp_path)
    assert accepte.attrs["refus"]["data-refus"] == "0"
    assert [l for l in accepte.lignes if l["tag"] == "g"]


@chromium
def test_saison_non_comparable_etiquetee_et_jamais_classee(synthetique, tmp_path) -> None:
    html = injecter(comparaison.TEMPLATE, synthetique)
    dom = _dom(html, "x=saison&m=65&k=jours_3_plus&f=coeur&s=2021-2022", tmp_path)
    barres = {l["data-saison"]: l for l in dom.lignes if l["tag"] == "g"}
    assert set(barres) == {"2016-2017", "2018-2019", "2019-2020", "2021-2022", "2022-2023"}
    assert barres["2019-2020"]["data-comparable"] == "0"
    assert barres["2019-2020"]["data-rang"] == ""
    assert all(barres[s]["data-rang"] != "" for s in barres if s != "2019-2020")
    ligne = {l["data-id"]: l for l in dom.lignes if l["tag"] == "tr"}
    assert "non comparable" in ligne["2019-2020"]["texte"]
    assert SAISONS_NON_COMPARABLES["2019-2020"] in ligne["2019-2020"]["texte"]


@chromium
def test_selecteur_borne_a_quatre_courbes(synthetique, tmp_path) -> None:
    html = injecter(comparaison.TEMPLATE, synthetique)
    toutes = "2016-2017,2018-2019,2019-2020,2021-2022,2022-2023"
    dom = _dom(html, f"x=choix&m=65&c={toutes}", tmp_path)
    assert len([l for l in dom.lignes if l["tag"] == "tr"]) == 4
    assert dom.texte["puces-saisons"].count("×") == 4
    assert "disabled" in dom.attrs["ajout-saison"]


@chromium
def test_tableau_egal_aux_metriques_sans_troncature(db, tmp_path) -> None:
    """Le gabarit agrege a partir des series : sur la fenetre entiere, il doit retrouver T6."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        coeur = risque.metriques_saison(con, fenetre=DEFAUT.nom, massifs=[ASPE])
    finally:
        con.close()
    html = injecter(comparaison.TEMPLATE, comparaison.payload(db))
    dom = _dom(html, "x=saison&m=65&p=0", tmp_path)

    class Cellules(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.rows: dict[str, dict[str, str]] = {}
            self._id = self._c = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "tr" and "data-id" in a:
                self._id = a["data-id"]
                self.rows[self._id] = {}
            if tag == "td" and "data-c" in a:
                self._c = a["data-c"]

        def handle_data(self, d):
            if self._id and self._c:
                self.rows[self._id][self._c] = d
                self._c = None

    # --dump-dom ne renvoie pas le parseur : on relit le DOM serialise une seconde fois.
    page = tmp_path / "p.html"
    page.write_text(html, encoding="utf-8")
    sortie = subprocess.run(
        [_chromium(), "--no-sandbox", "--disable-gpu", "--virtual-time-budget=4000", "--dump-dom",
         f"file://{page}#x=saison&m=65&p=0"], capture_output=True, text=True, timeout=120, check=True,
    ).stdout
    c = Cellules()
    c.feed(sortie)
    assert coeur.height > 0 and dom.lignes
    for r in coeur.iter_rows(named=True):
        ligne = c.rows[r["saison"]]
        assert int(ligne["couverts"]) == r["jours_couverts"]
        assert int(ligne["avec"]) == r["jours_avec_indice"]
        assert int(ligne["n3"]) == r["jours_3_plus"] and int(ligne["n4"]) == r["jours_4_plus"]
        assert float(ligne["moyenne"].replace(",", ".")) == pytest.approx(r["risque_moyen"], abs=0.005)
