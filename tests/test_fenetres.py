"""Fenetres de comparaison : bornes, appartenance, et perimetre des vues.

Deux choses sont verifiees ici. D'abord que les bornes se traduisent
correctement en dates et en SQL, annees bissextiles comprises. Ensuite, et
c'est le point qui a motive ces fenetres, que le tableau publie par
`saison_fenetre` ne laisse pas passer une ligne hors perimetre : en 2016 un
message technique diffuse sous `ID="3"` faisait compter douze massifs a une
chaine pyreneenne qui n'en a onze.
"""

from datetime import date

import duckdb
import pytest

from bra_analytics import fenetres
from bra_analytics.build import build, to_frames
from bra_analytics.massifs import libelle_coherent
from bra_analytics.parser import parse_file

from .conftest import FIXTURES, fixture


# --- bornes ------------------------------------------------------------------

def test_bornes_se_lisent_a_cheval_sur_deux_annees() -> None:
    """`debut` appartient a l'annee d'ouverture, `fin` a la suivante."""
    assert fenetres.COEUR.bornes(2023) == ("2023-12-15", "2024-04-15")
    assert fenetres.COMMUNE.bornes(2016) == ("2016-11-06", "2017-06-07")


def test_duree_suit_les_annees_bissextiles() -> None:
    """Fevrier 2024 compte 29 jours : la fenetre coeur y gagne un jour.

    C'est la raison pour laquelle la duree est calculee et non codee en dur :
    une constante de 122 jours ferait mentir la couverture une annee sur quatre.
    """
    con = duckdb.connect()
    try:
        duree = lambda f, an: con.execute(  # noqa: E731
            f"SELECT {f.sql_duree(str(an))}"
        ).fetchone()[0]
        assert duree(fenetres.COEUR, 2023) == 123   # fevrier 2024 : 29 jours
        assert duree(fenetres.COEUR, 2024) == 122   # fevrier 2025 : 28 jours
    finally:
        con.close()


@pytest.mark.parametrize(
    "jour, attendu",
    [
        (date(2023, 12, 14), False),  # veille de l'ouverture
        (date(2023, 12, 15), True),   # bornes incluses
        (date(2024, 2, 29), True),
        (date(2024, 4, 15), True),
        (date(2024, 4, 16), False),
    ],
)
def test_predicat_sql_inclut_ses_bornes(jour: date, attendu: bool) -> None:
    con = duckdb.connect()
    try:
        got = con.execute(
            f"SELECT {fenetres.COEUR.sql_predicat('jour', 'annee')} "
            "FROM (SELECT ? AS jour, 2023 AS annee)",
            [jour],
        ).fetchone()[0]
    finally:
        con.close()
    assert got is attendu


def test_coeur_est_strictement_incluse_dans_commune() -> None:
    """La fenetre de comparaison ne doit jamais deborder la fenetre de couverture."""
    for annee in (2016, 2023, 2024):
        c0, c1 = fenetres.COEUR.bornes(annee)
        m0, m1 = fenetres.COMMUNE.bornes(annee)
        assert m0 < c0 and c1 < m1


def test_seule_la_fenetre_coeur_autorise_la_comparaison() -> None:
    """`commune` couvre novembre, mai et juin : le `-1` y est massif.

    Le drapeau existe pour que la page et la CLI puissent afficher
    l'avertissement sans le recopier a deux endroits.
    """
    assert fenetres.COEUR.comparable_entre_saisons
    assert not fenetres.COMMUNE.comparable_entre_saisons
    assert fenetres.DEFAUT is fenetres.COEUR


def test_saisons_ecartees_sont_nommees_et_motivees() -> None:
    assert not fenetres.comparable("2015-2016")
    assert not fenetres.comparable("2019-2020")
    assert fenetres.comparable("2022-2023")
    for saison in ("2015-2016", "2019-2020"):
        assert fenetres.motif_exclusion(saison)


# --- perimetre : le bulletin technique de 2016 --------------------------------

def test_libelle_incoherent_repere_le_bulletin_technique() -> None:
    """`ID=3` (Mont-Blanc) portant `MASSIF="MOYENNE MONTAGNE"` est incoherent."""
    assert not libelle_coherent(3, "MOYENNE MONTAGNE")
    # Les variantes de graphie reelles restent coherentes.
    assert libelle_coherent(65, "ASPE-OSSAU")
    assert libelle_coherent(65, "Aspe Ossau")
    assert libelle_coherent(71, "Andorre (massif)")
    assert libelle_coherent(72, "ORLU__ST_BARTHELEMY")
    # Un libelle absent ne contredit rien.
    assert libelle_coherent(65, None)


def test_colonne_massif_coherent_marque_la_ligne_hors_perimetre() -> None:
    parsed = parse_file(fixture("anomalie_2016_moyenne_montagne.xml"))
    df = to_frames(parsed)["bulletins"]
    assert df.height == 1
    assert df["massif_coherent"].to_list() == [False]
    # La ligne herite d'une zone alpine par son ID usurpe : un filtre pose sur
    # `zone` la classerait dans les Alpes au lieu de l'ecarter.
    assert df["zone"].to_list() == ["Alpes du Nord"]


def test_bulletin_technique_reste_dans_bulletins() -> None:
    """L'ecarter des vues ne veut pas dire le supprimer de l'entrepot."""
    parsed = [p for n in ("anomalie_2016_moyenne_montagne.xml",
                          "v1_2016_aspe_ossau.xml") for p in parse_file(fixture(n))]
    df = to_frames(parsed)["bulletins"]
    assert sorted(df["massif_id"].to_list()) == [3, 65]


def test_saison_fenetre_ecarte_la_ligne_hors_perimetre(tmp_path) -> None:
    """Le compte de massifs de `saison_fenetre` ne doit pas inclure l'`ID=3`.

    C'est la regression qui a rendu ces fenetres necessaires : sur l'archive
    complete, `bra info` annoncait 12 massifs en 2015-2016 et faisait demarrer
    la saison au 4 fevrier, deux artefacts d'un seul bulletin technique.

    On ne teste pas l'absence de l'ID 3 : le Mont-Blanc est un vrai massif, et
    la fixture `v1_2016_mont_blanc.xml` le fait figurer legitimement en
    2015-2016. Seule la ligne usurpee doit disparaitre.
    """
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(FIXTURES, out, db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        actifs, premier = con.execute(
            "SELECT massifs_actifs, premier_jour FROM saison_fenetre "
            "WHERE saison = '2015-2016' AND fenetre = ?", [fenetres.SAISON_COMPLETE]
        ).fetchone()
        # Aspe-Ossau, Couserans, Mont-Blanc -- pas de quatrieme massif fantome.
        assert actifs == 3
        # Premier vrai bulletin : Aspe-Ossau, echeance du 10/03. Le message
        # technique du 05/02 n'avance plus la saison.
        assert str(premier) == "2016-03-10"

        # La vue reste interrogeable pour chaque portee attendue.
        portees = {f for (f,) in con.execute(
            "SELECT DISTINCT fenetre FROM saison_fenetre").fetchall()}
        assert portees == {f.nom for f in fenetres.FENETRES} | {fenetres.SAISON_COMPLETE}
    finally:
        con.close()


def test_couverture_ecarte_la_ligne_hors_perimetre(tmp_path) -> None:
    """Le message technique du 05/02/2016 diffuse sous `ID="3"` ne doit pas
    avancer le debut de saison du Mont-Blanc dans `couverture` : sur l'entrepot
    complet il y ajoutait 45 jours manquants fictifs."""
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(FIXTURES, out, db)
    c = duckdb.connect(str(db), read_only=True)
    try:
        premier, couverts = c.execute(
            "SELECT premier_jour, jours_couverts FROM couverture "
            "WHERE massif_id = 3 AND saison = '2015-2016'").fetchone()
        (attendu,) = c.execute(
            "SELECT min(jour_validite) FROM risque_journalier "
            "WHERE massif_id = 3 AND saison = '2015-2016' AND massif_coherent").fetchone()
    finally:
        c.close()
    assert premier == attendu
    assert couverts == 1


def test_couverture_se_rapporte_aux_massifs_actifs(tmp_path) -> None:
    """Le denominateur suit les massifs reellement diffuses, pas un effectif fige.

    Andorre (ID 71) n'est plus diffuse en 2025-2026 : rapporter la saison a
    onze massifs la plafonnerait a 91 % alors qu'elle est complete.
    """
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(FIXTURES, out, db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT saison, massifs_actifs, massifs_presents FROM saison_fenetre "
            "WHERE fenetre = ?", [fenetres.SAISON_COMPLETE]
        ).fetchall()
    finally:
        con.close()
    assert rows
    for saison, actifs, presents in rows:
        assert actifs >= presents >= 1, saison


def test_non_estimes_et_hors_moyenne_sont_deux_comptages(tmp_path) -> None:
    """Six bulletins de l'archive sont non estimes tout en portant un RISQUEMAXI.

    `non_estimes` decrit ce que la source a refuse d'estimer ; `hors_moyenne`
    ce qui sort effectivement du calcul. Les confondre ferait diverger le
    tableau de la moyenne qu'il explique.
    """
    out, db = tmp_path / "warehouse", tmp_path / "bra.duckdb"
    build(FIXTURES, out, db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        cols = {c for (c,) in con.execute(
            "SELECT column_name FROM duckdb_columns WHERE table_name = 'saison_fenetre'"
        ).fetchall()}
    finally:
        con.close()
    assert {"non_estimes", "hors_moyenne"} <= cols
