"""Deduplication, schema stable entre epoques, et sortie Parquet/DuckDB."""

import logging
from datetime import timedelta

import duckdb
import polars as pl
import pytest

from bra_analytics import schema
from bra_analytics.build import (
    build,
    daily_collapse_discards,
    log_daily_collapse_discards,
    parse_all,
    to_frames,
    write_warehouse,
)
from bra_analytics.parser import parse_file

from .conftest import FIXTURES, fixture

ALL_FIXTURES = [
    "v1_2016_aspe_ossau.xml",
    "v2_2017_aspe_ossau.xml",
    "v3_2023_aspe_ossau.xml",
    "v3_2023_andorre_nombre2.xml",
    "v4_2024_aspe_ossau.xml",
    "v4_2024_andorre.xml",
    "v5_2025_aspe_ossau.xml",
    "v6_2026_aspe_ossau.xml",
]


def frames_from(names):
    parsed = [p for n in names for p in parse_file(fixture(n))]
    return to_frames(parsed)


def test_schema_identique_quelle_que_soit_l_epoque() -> None:
    """Une saison 2016 et une saison 2026 doivent produire les memes colonnes.

    C'est la condition pour concatener les partitions sans casse de type.
    """
    ancien = frames_from(["v1_2016_aspe_ossau.xml"])["bulletins"]
    moderne = frames_from(["v6_2026_aspe_ossau.xml"])["bulletins"]
    assert ancien.columns == moderne.columns
    assert ancien.dtypes == moderne.dtypes
    assert ancien.schema == pl.Schema(schema.BULLETINS)


def test_toutes_les_tables_respectent_le_schema() -> None:
    frames = frames_from(ALL_FIXTURES)
    for name, df in frames.items():
        assert df.schema == pl.Schema(schema.TABLES[name]), name


def test_concatenation_entre_epoques() -> None:
    """Le grief principal : empiler 2016 et 2026 sans conflit de type."""
    a = frames_from(["v1_2016_aspe_ossau.xml"])["bulletins"]
    b = frames_from(["v6_2026_aspe_ossau.xml"])["bulletins"]
    assert pl.concat([a, b]).height == 2


def test_deduplication_garde_la_diffusion_la_plus_tardive() -> None:
    """22/02/2023 : deux publications, AMENDEMENT="false" sur les deux."""
    frames = frames_from(["v3_2023_aspe_ossau_dup_1.xml", "v3_2023_aspe_ossau_dup_2.xml"])
    df = frames["bulletins"]
    assert df.height == 1
    assert df["fichier_source"][0] == "v3_2023_aspe_ossau_dup_2.xml"
    assert df["date_diffusion"][0].hour == 16


def test_deduplication_reportee_sur_les_tables_filles() -> None:
    frames = frames_from(["v3_2023_aspe_ossau_dup_1.xml", "v3_2023_aspe_ossau_dup_2.xml"])
    # 3 previsions + 21 historiques, une seule fois malgre les deux fichiers.
    assert frames["meteo"].height == 24
    assert frames["historique_risque"].height == 7


def test_amendement_ne_sert_pas_de_discriminant() -> None:
    """Les deux versions portent AMENDEMENT=false : la dedup ne peut s'y fier."""
    parsed = [p for n in ("v3_2023_aspe_ossau_dup_1.xml", "v3_2023_aspe_ossau_dup_2.xml")
              for p in parse_file(fixture(n))]
    assert {p.bulletin["amendement"] for p in parsed} == {False}


def test_massifs_distincts_non_dedupliques() -> None:
    frames = frames_from(["v4_2024_aspe_ossau.xml", "v4_2024_andorre.xml"])
    assert frames["bulletins"].height == 2


def test_referentiel_massif_joint() -> None:
    df = frames_from(["v3_2023_aspe_ossau.xml"])["bulletins"]
    assert df["massif_nom"][0] == "Aspe Ossau"   # libelle normalise
    assert df["massif_nom_source"][0] == "ASPE-OSSAU"  # libelle d'origine conserve
    assert df["zone"][0] == "Pyrenees"


def test_cles_etrangeres_coherentes() -> None:
    frames = frames_from(ALL_FIXTURES)
    cles = set(zip(frames["bulletins"]["massif_id"], frames["bulletins"]["date_bulletin"]))
    for name in ("meteo", "enneigement", "neige_fraiche", "historique_risque", "tendances"):
        df = frames[name]
        if df.height:
            assert set(zip(df["massif_id"], df["date_bulletin"])) <= cles, name


def test_frames_vides_gardent_leur_schema() -> None:
    frames = to_frames([])
    assert frames["bulletins"].height == 0
    assert frames["bulletins"].schema == pl.Schema(schema.BULLETINS)


# --------------------------------------------------------------------------
# Ecriture
# --------------------------------------------------------------------------

def test_partitionnement_par_saison(tmp_path) -> None:
    frames = frames_from(ALL_FIXTURES)
    write_warehouse(frames, tmp_path)
    saisons = sorted(p.name for p in (tmp_path / "bulletins").iterdir())
    assert saisons == [
        "saison=2015-2016", "saison=2016-2017", "saison=2022-2023",
        "saison=2023-2024", "saison=2024-2025", "saison=2025-2026",
    ]
    assert (tmp_path / "bulletins" / "saison=2025-2026" / "data.parquet").exists()


def test_relecture_parquet(tmp_path) -> None:
    frames = frames_from(ALL_FIXTURES)
    write_warehouse(frames, tmp_path)
    relu = pl.read_parquet(tmp_path / "bulletins" / "**" / "*.parquet")
    assert relu.height == frames["bulletins"].height
    assert set(relu["saison"].unique()) == set(frames["bulletins"]["saison"].unique())


def test_build_complet(tmp_path) -> None:
    """Chaine complete : fixtures -> Parquet -> DuckDB interrogeable."""
    out = tmp_path / "warehouse"
    db = tmp_path / "bra.duckdb"
    report, written = build(FIXTURES, out, db)

    nb_fixtures = len(list(FIXTURES.glob("*.xml")))
    assert report.files_failed == 0
    assert report.files_seen == nb_fixtures
    # Deux paires de publications redondantes : 22/02/2023 et 31/03/2016 au soir.
    assert report.duplicates_dropped == 2
    assert report.bulletins_kept == nb_fixtures - report.duplicates_dropped
    assert written["bulletins"] == report.bulletins_kept

    con = duckdb.connect(str(db), read_only=True)
    try:
        (total,) = con.execute("SELECT count(*) FROM bulletins").fetchone()
        assert total == report.bulletins_kept
        rows = con.execute(
            "SELECT DISTINCT saison FROM risque_journalier "
            "WHERE massif_id = 65 ORDER BY saison"
        ).fetchall()
        assert [r[0] for r in rows] == [
            "2015-2016", "2016-2017", "2022-2023", "2023-2024", "2024-2025", "2025-2026"
        ]
        (mini, maxi) = con.execute(
            "SELECT min(risque_maxi), max(risque_maxi) FROM risque_journalier"
        ).fetchone()
        assert 1 <= mini <= maxi <= 5
    finally:
        con.close()


def test_fichier_illisible_ne_casse_pas_le_build(tmp_path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "bon.xml").write_bytes(fixture("v6_2026_aspe_ossau.xml").read_bytes())
    (source / "mauvais.xml").write_text("<html>302 Found</html>")

    report, written = build(source, tmp_path / "out", None)
    assert report.files_seen == 2
    assert report.files_failed == 1
    assert written["bulletins"] == 1
    assert report.failures[0][0] == "mauvais.xml"


# --------------------------------------------------------------------------
# Amendement en cours de journee
# --------------------------------------------------------------------------

def test_amendement_conserve_le_bulletin_du_soir_est_deduplique() -> None:
    """L'amendement du matin survit ; les deux copies du bulletin du soir fusionnent."""
    frames = frames_from([
        "v1_2016_couserans_amendement_matin.xml",
        "v1_2016_couserans_soir_dup_1.xml",
        "v1_2016_couserans_soir_dup_2.xml",
    ])
    df = frames["bulletins"]
    assert df.height == 2
    assert sorted(d.hour for d in df["date_bulletin"]) == [6, 16]


def test_vue_journaliere_une_ligne_par_jour_couvert(tmp_path) -> None:
    """`risque_journalier` est indexee sur l'echeance, une ligne par massif et jour."""
    frames = frames_from([
        "v1_2016_couserans_amendement_matin.xml",
        "v1_2016_couserans_soir_dup_1.xml",
        "v1_2016_couserans_soir_dup_2.xml",
    ])
    out = tmp_path / "warehouse"
    write_warehouse(frames, out)
    db = tmp_path / "bra.duckdb"
    from bra_analytics.build import create_duckdb

    create_duckdb(out, db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT jour_validite, count(*) FROM risque_journalier GROUP BY 1 ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    # Deux jours couverts (le 31/03 par l'amendement, le 01/04 par le bulletin du soir),
    # une seule ligne chacun.
    assert [(str(d), n) for d, n in rows] == [("2016-03-31", 1), ("2016-04-01", 1)]


def test_vues_analytiques(tmp_path) -> None:
    """`couverture` et `profil_saison` doivent etre interrogeables des le build."""
    out = tmp_path / "warehouse"
    db = tmp_path / "bra.duckdb"
    build(FIXTURES, out, db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        couverture = con.execute(
            "SELECT jours_couverts, jours_manquants FROM couverture "
            "WHERE massif_id = 65 AND saison = '2022-2023'"
        ).fetchall()
        # Deux bulletins (15/02 et 22/02) sur une fenetre de 8 jours calendaires.
        assert couverture == [(2, 6)]

        profil = con.execute(
            "SELECT saison, jours, risque_moyen FROM profil_saison "
            "WHERE massif_id = 65 ORDER BY saison"
        ).fetchall()
        assert len(profil) == 6
        assert all(1 <= row[2] <= 5 for row in profil)
    finally:
        con.close()


# --------------------------------------------------------------------------
# Idempotence de la construction
# --------------------------------------------------------------------------

def _empreinte(warehouse) -> list[tuple[str, bytes]]:
    import hashlib

    return sorted(
        (str(p.relative_to(warehouse)), hashlib.md5(p.read_bytes()).digest())
        for p in warehouse.rglob("*.parquet")
    )


def test_build_reproductible(tmp_path) -> None:
    """Deux constructions sur la meme source donnent des fichiers identiques."""
    out = tmp_path / "warehouse"
    build(FIXTURES, out, None)
    premiere = _empreinte(out)
    build(FIXTURES, out, None)
    assert _empreinte(out) == premiere


def test_partitions_obsoletes_purgees(tmp_path) -> None:
    """Une saison absente de la nouvelle source ne doit pas survivre au rebuild.

    Sans purge, la partition d'un build precedent restait sur disque et etait
    relue par le glob `**/*.parquet` : l'entrepot divergeait silencieusement du
    rapport de build.
    """
    source = tmp_path / "raw"
    source.mkdir()
    out = tmp_path / "warehouse"

    (source / "a.xml").write_bytes(fixture("v6_2026_aspe_ossau.xml").read_bytes())
    build(source, out, None)
    assert [p.name for p in (out / "bulletins").glob("saison=*")] == ["saison=2025-2026"]

    # Nouvelle source, saison differente.
    (source / "a.xml").unlink()
    (source / "b.xml").write_bytes(fixture("v3_2023_aspe_ossau.xml").read_bytes())
    report, _ = build(source, out, None)

    assert [p.name for p in (out / "bulletins").glob("saison=*")] == ["saison=2022-2023"]
    assert pl.read_parquet(out / "bulletins" / "**" / "*.parquet").height == report.bulletins_kept


def test_purge_limitee_aux_partitions(tmp_path) -> None:
    """La purge ne touche qu'aux repertoires `saison=*` des tables connues."""
    out = tmp_path / "warehouse"
    build(FIXTURES, out, None)
    temoin = out / "bulletins" / "NOTES.md"
    temoin.write_text("ne pas supprimer")
    autre = out / "export_maison"
    autre.mkdir()
    (autre / "x.csv").write_text("a,b")

    build(FIXTURES, out, None)
    assert temoin.exists()
    assert (autre / "x.csv").exists()


def test_base_duckdb_orpheline_supprimee(tmp_path) -> None:
    """Sans donnees, la base d'un build precedent pointerait dans le vide."""
    source = tmp_path / "raw"
    source.mkdir()
    out = tmp_path / "warehouse"
    db = tmp_path / "bra.duckdb"

    (source / "a.xml").write_bytes(fixture("v6_2026_aspe_ossau.xml").read_bytes())
    build(source, out, db)
    assert db.exists()

    (source / "a.xml").unlink()
    build(source, out, db)
    assert not db.exists()


def test_replace_supprime_les_parquet_hors_partition(tmp_path) -> None:
    """Un Parquet depose hors partition serait relu par un glob `**/*.parquet`.

    La purge par defaut ne retire que les repertoires `saison=*` et le laisse
    donc en place ; `--replace` vide la table entiere.
    """
    source = tmp_path / "raw"
    source.mkdir()
    (source / "a.xml").write_bytes(fixture("v6_2026_aspe_ossau.xml").read_bytes())
    out = tmp_path / "warehouse"
    build(source, out, None)

    intrus = out / "bulletins" / "vieux.parquet"
    intrus.write_bytes((out / "bulletins" / "saison=2025-2026" / "data.parquet").read_bytes())

    build(source, out, None)
    assert intrus.exists(), "le defaut ne purge que les partitions"
    assert pl.read_parquet(out / "bulletins" / "**" / "*.parquet").height == 2

    build(source, out, None, replace=True)
    assert not intrus.exists()
    assert pl.read_parquet(out / "bulletins" / "**" / "*.parquet").height == 1


def test_replace_preserve_les_repertoires_etrangers(tmp_path) -> None:
    """`replace` ne vide que les tables connues, jamais le reste de la sortie."""
    out = tmp_path / "warehouse"
    build(FIXTURES, out, None)
    export = out / "export_maison"
    export.mkdir()
    (export / "x.csv").write_text("a,b")

    build(FIXTURES, out, None, replace=True)
    assert (export / "x.csv").exists()


def test_repertoires_etrangers_signales(tmp_path) -> None:
    """Un repertoire inconnu contenant des Parquet est signale, pas supprime."""
    source = tmp_path / "raw"
    source.mkdir()
    (source / "a.xml").write_bytes(fixture("v6_2026_aspe_ossau.xml").read_bytes())
    out = tmp_path / "warehouse"
    build(source, out, None)

    fantome = out / "table_disparue" / "saison=2020-2021"
    fantome.mkdir(parents=True)
    (fantome / "data.parquet").write_bytes(
        (out / "bulletins" / "saison=2025-2026" / "data.parquet").read_bytes()
    )

    report, _ = build(source, out, None, replace=True)
    assert report.stray_dirs == ["table_disparue"]
    assert "table_disparue" in report.summary()
    assert (fantome / "data.parquet").exists()


# --------------------------------------------------------------------------
# Collapse quotidienne : ce que `risque_journalier` ecarte doit se voir
# --------------------------------------------------------------------------

def _reedition(nom: str = "v6_2026_aspe_ossau.xml") -> pl.DataFrame:
    """Un bulletin et sa reedition deux heures plus tard, meme echeance.

    Cas reel apparu en 2023-2024 : `DATEBULLETIN` passe de 16:00 a 18:00, donc
    la dedup sur `(massif_id, date_bulletin)` ne les rapproche pas -- c'est la
    cle elle-meme qui bouge. Seule l'echeance les reunit.
    """
    df = frames_from([nom])["bulletins"]
    tardive = df.with_columns(
        date_bulletin=pl.col("date_bulletin") + timedelta(hours=2),
        date_diffusion=pl.col("date_diffusion") + timedelta(hours=2),
    )
    return pl.concat([df, tardive])


def test_collapse_ecarte_la_redaction_la_plus_ancienne() -> None:
    """Deux bulletins pour un meme jour couvert : le plus ancien est ecarte."""
    deux = _reedition()
    assert deux.height == 2
    assert deux["jour_validite"].n_unique() == 1

    ecartees = daily_collapse_discards(deux)
    assert ecartees.height == 1
    # C'est bien la premiere redaction qui saute, pas la derniere.
    assert ecartees["date_bulletin"][0] == deux["date_bulletin"].min()
    assert ecartees["motif"][0].startswith("jour deja couvert")


def test_collapse_ne_signale_rien_sans_collision() -> None:
    """Sans jour couvert deux fois, aucune ligne n'est perdue -- donc aucun bruit."""
    frames = frames_from(ALL_FIXTURES)
    assert daily_collapse_discards(frames["bulletins"]).height == 0


def test_collapse_laisse_exactement_une_ligne_par_jour_couvert() -> None:
    """L'invariant de la vue : ce qui reste apres retrait des ecartees est unique.

    Verrouille l'accord entre l'arbitrage Python de `daily_collapse_discards`
    et celui du `row_number()` de `risque_journalier`. Les deux doivent trier
    a l'identique ; si l'un derive, le journal decrit un arbitrage qui n'est
    plus celui de la vue.
    """
    corpus = pl.concat([
        _reedition("v6_2026_aspe_ossau.xml"),
        _reedition("v4_2024_andorre.xml"),
        frames_from(["v3_2023_aspe_ossau.xml"])["bulletins"],
    ])
    ecartees = daily_collapse_discards(corpus)
    assert ecartees.height == 2

    restantes = corpus.join(
        ecartees.select("massif_id", "date_bulletin"),
        on=["massif_id", "date_bulletin"],
        how="anti",
    )
    assert restantes.height == corpus.height - ecartees.height
    assert restantes.select("massif_id", "jour_validite").is_duplicated().sum() == 0
    # La ligne retenue pour chaque jour est la redaction la plus tardive.
    for (massif, jour), groupe in corpus.group_by(["massif_id", "jour_validite"]):
        gardee = restantes.filter(
            (pl.col("massif_id") == massif) & (pl.col("jour_validite") == jour)
        )
        assert gardee.height == 1
        assert gardee["date_bulletin"][0] == groupe["date_bulletin"].max()


def test_chaque_ligne_ecartee_produit_un_avertissement(caplog) -> None:
    """Aucune perte silencieuse : une ligne de journal par bulletin perdu.

    Une vue SQL est une projection, elle ne peut rien journaliser -- c'est ce
    qui a permis a 2 471 bulletins mal dates de disparaitre sans qu'aucun
    compteur ne bouge.
    """
    deux = _reedition()
    with caplog.at_level(logging.WARNING, logger="bra_analytics.build"):
        perdues = log_daily_collapse_discards(deux)

    assert perdues == 1
    avertissements = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avertissements) == 1
    trace = avertissements[0].getMessage()
    # Le journal doit permettre de retrouver la ligne exacte, pas seulement d'en
    # connaitre le nombre.
    assert "collapse quotidienne" in trace
    assert "massif=65" in trace
    assert "jour_couvert=2026-02-12" in trace
    assert "v6_2026_aspe_ossau.xml" in trace


def test_le_rapport_de_build_compte_les_lignes_ecartees(tmp_path) -> None:
    """Le total apparait dans `bra build`, pas seulement dans le journal."""
    source = tmp_path / "raw"
    source.mkdir()
    for nom in ("v3_2023_aspe_ossau.xml", "v6_2026_aspe_ossau.xml"):
        (source / nom).write_bytes(fixture(nom).read_bytes())

    report, _ = build(source, tmp_path / "warehouse", None)
    assert report.daily_collapse_dropped == 0
    assert "collapse quotidienne" in report.summary()


# --------------------------------------------------------------------------
# Second axe temporel : jour_de_saison
# --------------------------------------------------------------------------

def _jours_de_saison(tmp_path) -> dict[tuple[int, str], int | None]:
    db = tmp_path / "bra.duckdb"
    build(FIXTURES, tmp_path / "warehouse", db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT massif_id, jour_validite, jour_de_saison FROM risque_journalier"
        ).fetchall()
    finally:
        con.close()
    return {(m, str(j)): n for m, j, n in rows}


def test_jour_de_saison_part_du_premier_jour_du_massif(tmp_path) -> None:
    """Un massif ouvert tard demarre a 1, pas au decalage calendaire de la saison.

    En 2015-2016 l'archive livre Aspe-Ossau des le 10/03 et Couserans le 31/03
    seulement. Compte depuis une date commune, Couserans demarrerait a 22.
    """
    jours = _jours_de_saison(tmp_path)
    assert jours[(65, "2016-03-10")] == 1
    assert jours[(69, "2016-03-31")] == 1
    assert jours[(69, "2016-04-01")] == 2
    # Saison suivante : le compte repart de 1 pour chaque couple massif x saison.
    assert jours[(64, "2016-11-04")] == 1


def test_jour_de_saison_ignore_le_bulletin_technique_de_2016(tmp_path) -> None:
    """Le message technique du 05/02/2016 usurpe `ID="3"` : il ne doit pas
    avancer le premier jour du Mont-Blanc.

    Compte avec lui, le vrai premier bulletin du Mont-Blanc (11/03/2016)
    porterait le jour 36. La ligne usurpee n'appartient a aucun massif : elle
    n'a pas de jour de saison.
    """
    jours = _jours_de_saison(tmp_path)
    assert jours[(3, "2016-03-11")] == 1
    assert jours[(3, "2016-02-05")] is None
