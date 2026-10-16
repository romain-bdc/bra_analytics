"""Construction de l'entrepot Parquet a partir du cache XML.

Sortie : `warehouse/<table>/saison=<AAAA-AAAA>/data.parquet`, plus une base
DuckDB exposant chaque table en vue.

La deduplication est la piece sensible. Un meme bulletin peut etre publie
plusieurs fois dans la journee, avec `AMENDEMENT="false"` sur *toutes* les
versions (constate le 22/02/2023) : l'attribut ne permet pas de reperer la
revision. On retient donc, par `(massif_id, date_bulletin)`, la version de
`date_diffusion` la plus tardive.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import polars as pl

from . import schema
from .fenetres import FENETRES, SAISON_COMPLETE, sql_exclusions
from .massifs import BY_ID, libelle_coherent
from .parser import ParseError, ParsedBulletin, parse_file
from .tranches import sql_case as sql_case_tranche

logger = logging.getLogger(__name__)


@dataclass
class BuildReport:
    files_seen: int = 0
    files_failed: int = 0
    bulletins_parsed: int = 0
    bulletins_kept: int = 0
    duplicates_dropped: int = 0
    daily_collapse_dropped: int = 0
    neige_fraiche_dropped: int = 0
    neige_fraiche_divergent: int = 0
    enneigement_dropped: int = 0
    seasons: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    stray_dirs: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"fichiers lus          : {self.files_seen}",
            f"fichiers en erreur    : {self.files_failed}",
            f"bulletins parses      : {self.bulletins_parsed}",
            f"doublons ecartes      : {self.duplicates_dropped}",
            f"bulletins conserves   : {self.bulletins_kept}",
            f"  dont ecartes par la collapse quotidienne : {self.daily_collapse_dropped}"
            f" (journalises en WARNING ; {self.bulletins_kept - self.daily_collapse_dropped}"
            f" lignes dans risque_journalier)",
            f"neige fraiche historique ecartee : {self.neige_fraiche_dropped}"
            f" (une redaction par jour ; dont {self.neige_fraiche_divergent} de valeur"
            f" differente, en WARNING, les autres en DEBUG)",
            f"releves d'enneigement ecartes : {self.enneigement_dropped}"
            f" lignes (redaction plus tardive du meme jour, en WARNING)",
            f"saisons               : {', '.join(self.seasons) or '-'}",
        ]
        if self.stray_dirs:
            lines.append(
                "repertoires etrangers contenant des Parquet (non supprimes) : "
                + ", ".join(self.stray_dirs)
            )
        if self.failures:
            lines.append("echecs (10 premiers) :")
            lines += [f"  - {name} : {msg}" for name, msg in self.failures[:10]]
        return "\n".join(lines)


def iter_xml_files(root: str | Path) -> list[Path]:
    return sorted(Path(root).rglob("*.xml"))


def _frame(rows: Sequence[dict], cols: dict) -> pl.DataFrame:
    """DataFrame au schema impose, meme sans lignes."""
    if not rows:
        return pl.DataFrame(schema=cols)
    # `strict=False` laisse polars caster les entiers vers les largeurs voulues.
    return pl.DataFrame(rows, schema=cols, strict=False)


def parse_all(paths: Iterable[Path], report: BuildReport | None = None) -> list[ParsedBulletin]:
    report = report or BuildReport()
    parsed: list[ParsedBulletin] = []
    for path in paths:
        report.files_seen += 1
        try:
            parsed.extend(parse_file(path))
        except ParseError as exc:
            report.files_failed += 1
            report.failures.append((path.name, str(exc)))
    report.bulletins_parsed += len(parsed)
    return parsed


def to_frames(parsed: Sequence[ParsedBulletin], report: BuildReport | None = None) -> dict[str, pl.DataFrame]:
    """Assemble les tables et deduplique sur `(massif_id, date_bulletin)`."""
    report = report or BuildReport()

    bulletins = []
    for item in parsed:
        row = dict(item.bulletin)
        massif = BY_ID.get(row["massif_id"])
        row["massif_nom"] = massif.nom if massif else None
        row["zone"] = massif.zone if massif else None
        # Marque des la construction, pas seulement dans le rapport `bra check` :
        # les vues de comparaison ont besoin de l'ecarter, et un controle qui ne
        # laisse pas de colonne ne peut pas etre filtre.
        row["massif_coherent"] = libelle_coherent(
            row["massif_id"], row.get("massif_nom_source")
        )
        bulletins.append(row)

    df = _frame(bulletins, schema.BULLETINS)

    if df.height:
        before = df.height
        # Tri stable : diffusion la plus tardive en tete, le nom de fichier
        # departageant les rares cas ou `date_diffusion` est identique.
        df = (
            df.sort(
                ["massif_id", "date_bulletin", "date_diffusion", "fichier_source"],
                descending=[False, False, True, True],
                nulls_last=True,
            )
            .unique(subset=["massif_id", "date_bulletin"], keep="first", maintain_order=True)
            .sort(["saison", "massif_id", "date_bulletin"])
        )
        report.duplicates_dropped += before - df.height
        report.bulletins_kept += df.height
        report.seasons = sorted(s for s in df["saison"].unique().to_list() if s)

    # Cle retenue -> fichier dont la table mere a garde la version. Les tables
    # filles doivent venir de ce fichier-la : quand deux diffusions d'une meme
    # cle different, prendre la premiere lue (ordre des chemins, donc la plus
    # ancienne) associait le risque d'une version a la meteo, l'enneigement et
    # la neige fraiche d'une autre. Constate sur Cinto Rotondo, 06/04/2026 : la
    # reedition de 16 h 21 couvre le 6 avril, la version de 16 h 00 le 7 ; la
    # table `meteo` portait les echeances du 7 sous un bulletin du 6.
    kept: dict[tuple, str | None] = (
        dict(zip(
            zip(df["massif_id"].to_list(), df["date_bulletin"].to_list()),
            df["fichier_source"].to_list(),
        ))
        if df.height else {}
    )

    children: dict[str, list[dict]] = {
        "meteo": [], "enneigement": [], "neige_fraiche": [],
        "historique_risque": [], "tendances": [], "conversions": [],
    }
    seen_keys: set[tuple] = set()
    for item in parsed:
        key = (item.bulletin["massif_id"], item.bulletin["date_bulletin"])
        # Les tables filles suivent la deduplication de la table mere : on ne
        # garde que les lignes du fichier retenu pour la cle, une seule fois
        # (un meme fichier peut figurer dans deux repertoires du cache).
        if key not in kept or key in seen_keys:
            continue
        # `fichier_source` est toujours renseigne par `parse_file` ; un bulletin
        # sans source (appel direct de `parse_bulletin_element`) ne peut pas
        # etre rattache a sa version, et le premier lu gagnerait sans le dire.
        if kept[key] is None or item.bulletin.get("fichier_source") is None:
            raise ValueError(f"bulletin sans fichier source pour la cle {key}")
        if item.bulletin["fichier_source"] != kept[key]:
            continue
        seen_keys.add(key)
        header = {
            "massif_id": item.bulletin["massif_id"],
            "date_bulletin": item.bulletin["date_bulletin"],
            "saison": item.bulletin["saison"],
        }
        for name, rows in (
            ("meteo", item.meteo),
            ("enneigement", item.enneigement),
            ("neige_fraiche", item.neige_fraiche),
            ("historique_risque", item.historique_risque),
            ("tendances", item.tendances),
        ):
            children[name].extend({**header, **row} for row in rows)
        children["conversions"].extend(
            {**header, "table_cible": t, "champ": c, "valeur_source": v, "valeurs": n}
            for (t, c, v), n in sorted(item.conversions.items())
        )

    frames = {"bulletins": df}
    for name, rows in children.items():
        frames[name] = _frame(rows, schema.TABLES[name])
    return frames


# Colonnes retenues pour identifier une ligne ecartee dans le journal.
DISCARD_COLS = [
    "saison", "massif_id", "jour_validite", "jour_bulletin", "date_bulletin",
    "date_diffusion", "amendement", "risque_maxi", "risque_estime", "fichier_source",
]


def daily_collapse_discards(df: pl.DataFrame) -> pl.DataFrame:
    """Les bulletins que la vue `risque_journalier` laisse de cote.

    La vue ramene le corpus a une ligne par `(massif_id, jour_validite)` : elle
    ecarte les bulletins sans jour couvert, puis, quand un jour est couvert
    plusieurs fois, tous ceux qui ne sont pas la redaction la plus tardive.
    L'arbitrage est legitime -- un jour couvert deux fois l'est par une
    reedition ou par un amendement -- mais une vue SQL est une projection : elle
    ne peut rien journaliser. La perte est donc invisible, et c'est ainsi que
    2 471 bulletins mal dates ont pu disparaitre sans qu'aucun compteur bouge.

    On rejoue donc ici, au build, exactement le meme arbitrage que la vue, pour
    que chaque ligne perdue laisse une trace. Toute evolution de la clause
    `ORDER BY` de `risque_journalier` doit etre repercutee ici, sinon le journal
    decrit un arbitrage qui n'est plus celui de la vue.
    """
    vide = pl.DataFrame(
        schema={**{c: schema.BULLETINS[c] for c in DISCARD_COLS}, "motif": pl.Utf8}
    )
    if not df.height:
        return vide

    sans_jour = df.filter(pl.col("jour_validite").is_null()).with_columns(
        motif=pl.lit("jour_validite absent : ni DATEECHEANCE ni DATEVALIDITE exploitable")
    )
    # `int_range().over()` suit l'ordre des lignes dans le groupe : le tri
    # prealable reproduit le `ORDER BY date_bulletin DESC, date_diffusion DESC`
    # de la vue, donc le rang 0 est la ligne que la vue retient.
    collisions = (
        df.filter(pl.col("jour_validite").is_not_null())
        .sort(["date_bulletin", "date_diffusion"], descending=True, nulls_last=True)
        .with_columns(rang=pl.int_range(pl.len()).over(["massif_id", "jour_validite"]))
        .filter(pl.col("rang") > 0)
        .with_columns(motif=pl.lit("jour deja couvert par une redaction plus tardive"))
    )
    return (
        pl.concat([sans_jour.select(*DISCARD_COLS, "motif"),
                   collisions.select(*DISCARD_COLS, "motif")])
        .sort(["saison", "massif_id", "jour_validite", "date_bulletin"])
    )


def log_daily_collapse_discards(df: pl.DataFrame) -> int:
    """Journalise en WARNING chaque ligne ecartee par la collapse quotidienne.

    Une ligne de journal par bulletin perdu, pas un resume : le but est qu'un
    ecart entre `count(*) FROM bulletins` et `count(*) FROM risque_journalier`
    soit toujours imputable ligne a ligne.
    """
    discards = daily_collapse_discards(df)
    for row in discards.iter_rows(named=True):
        logger.warning(
            "collapse quotidienne : bulletin ecarte -- massif=%s jour_couvert=%s "
            "redige=%s diffuse=%s amendement=%s risque_maxi=%s estime=%s "
            "motif=%s source=%s",
            row["massif_id"], row["jour_validite"], row["date_bulletin"],
            row["date_diffusion"], row["amendement"], row["risque_maxi"],
            row["risque_estime"], row["motif"], row["fichier_source"],
        )
    return discards.height


def write_warehouse(
    frames: dict[str, pl.DataFrame],
    out_dir: str | Path,
    *,
    replace: bool = False,
) -> dict[str, int]:
    """Ecrit chaque table en Parquet partitionne par saison.

    Le partitionnement est materialise en repertoires `saison=...` : DuckDB et
    polars lisent l'arborescence en poussant le filtre de partition.

    Les partitions du build precedent sont purgees avant ecriture. Sans cela,
    une partition devenue obsolete -- perimetre reduit par `--massifs`, cache
    source ampute, saison retiree -- survivrait a la reconstruction et serait
    relue par le glob `**/*.parquet`, faisant diverger l'entrepot du rapport de
    build sans qu'aucune erreur ne le signale.

    Seuls les repertoires `saison=*` des tables connues sont supprimes : rien
    d'autre n'est touche dans `out_dir`.

    `replace=True` va plus loin et vide entierement le repertoire de chaque
    table connue. Cela couvre un residu que la purge par partition laisse
    passer : un fichier Parquet depose hors partition, qu'un glob
    `**/*.parquet` relirait sans qu'il appartienne a aucune saison. Les
    repertoires ne correspondant a aucune table connue ne sont jamais
    supprimes, meme avec `replace` : ils sont seulement signales.
    """
    out = Path(out_dir)
    written: dict[str, int] = {}
    for name, df in frames.items():
        table_dir = out / name
        if replace:
            if table_dir.exists():
                shutil.rmtree(table_dir)
        else:
            for obsolete in sorted(table_dir.glob("saison=*")):
                if obsolete.is_dir():
                    shutil.rmtree(obsolete)
        table_dir.mkdir(parents=True, exist_ok=True)
        if not df.height:
            written[name] = 0
            continue
        for (saison,), part in df.group_by(["saison"], maintain_order=True):
            label = saison or "inconnue"
            part_dir = table_dir / f"saison={label}"
            part_dir.mkdir(parents=True, exist_ok=True)
            part.write_parquet(part_dir / "data.parquet", compression="zstd")
        written[name] = df.height
    return written


def create_duckdb(warehouse: str | Path, db_path: str | Path) -> Path:
    """Cree une base DuckDB exposant l'entrepot en vues, plus une vue d'analyse."""
    warehouse = Path(warehouse).resolve()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        for name in schema.TABLES:
            pattern = warehouse / name / "**" / "*.parquet"
            if not list((warehouse / name).rglob("*.parquet")):
                continue
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true, union_by_name = true)"
            )

        # Vue de travail : une ligne par massif et par jour couvert.
        #
        # Deux precautions :
        # - l'indexation se fait sur `jour_validite` (l'echeance du bulletin) et
        #   non sur la date de redaction, sinon la serie est decalee d'un jour ;
        # - un jour peut recevoir un bulletin du soir puis un amendement le
        #   lendemain matin (constate le 31/03/2016). On retient la redaction la
        #   plus tardive, qui est l'information valide en dernier ressort.
        #
        # Cette vue est reductrice : sur les 36 massifs elle passe de 77 488
        # bulletins a 76 853 lignes (23 533 a 23 268 sur les Pyrenees). `log_daily_collapse_discards()` journalise au build chaque
        # ligne ainsi ecartee -- l'`ORDER BY` ci-dessous et le tri de cette
        # fonction doivent rester identiques.
        #
        # `jour_de_saison` est le second axe temporel : jours depuis le premier
        # jour couvert du couple massif x saison, et non depuis une date
        # commune, puisque la diffusion n'ouvre pas le meme jour partout. Il ne
        # se calcule que sur les lignes `massif_coherent` : le message
        # technique du 05/02/2016 diffuse sous `ID="3"` avancerait sinon de
        # 35 jours le debut de saison du Mont-Blanc. Les jours non estimes
        # comptent : l'axe mesure la diffusion, pas l'indice.
        con.execute(
            """
            CREATE OR REPLACE VIEW risque_journalier AS
            SELECT
              * EXCLUDE (rang),
              -- Deux gardes, deux roles : celle du `min` empeche une ligne
              -- usurpee de fixer le jour 1 de son massif ; celle du `CASE`
              -- exterieur lui refuse un rang, puisqu'elle n'est d'aucun massif.
              CASE WHEN massif_coherent THEN date_diff(
                'day',
                min(CASE WHEN massif_coherent THEN jour_validite END)
                  OVER (PARTITION BY massif_id, saison),
                jour_validite
              ) + 1 END AS jour_de_saison
            FROM (
              SELECT
                saison,
                saison_debut,
                massif_id,
                massif_nom,
                zone,
                massif_coherent,
                jour_validite,
                jour_bulletin,
                date_bulletin,
                risque_maxi,
                risque_estime,
                risque1,
                risque1_evolution,
                risque2,
                loc_type,
                altitude_seuil_m,
                sat1,
                sat2,
                enneigement_limite_nord_m,
                enneigement_limite_sud_m,
                schema_version,
                format_famille,
                """
            # Appartenance aux fenetres de comparaison, portee par la ligne
            # plutot que laissee a chaque requete : une borne recopiee a la main
            # dans un notebook est une borne qui divergera de la definition.
            + ",\n".join(
                f"                {f.sql_predicat()} AS fenetre_{f.nom}" for f in FENETRES
            )
            + ",\n"
            + """
                row_number() OVER (
                    PARTITION BY massif_id, jour_validite
                    ORDER BY date_bulletin DESC, date_diffusion DESC
                ) AS rang
              FROM bulletins
              WHERE jour_validite IS NOT NULL
            )
            WHERE rang = 1
            """
        )
        # Une ligne par saison et par fenetre : le tableau de reference des
        # comparaisons inter-saisons.
        #
        # `massifs_actifs` se compte sur la saison entiere, et sert de
        # denominateur a la couverture. Le compter sur un effectif constant de
        # 11 ferait plafonner 2025-2026 a 91 % alors que le massif 71 (Andorre)
        # n'est simplement plus diffuse : la saison est complete sur les
        # massifs qui existent.
        #
        # Les saisons non comparables ne sont pas filtrees mais etiquetees.
        # `bra check` a montre qu'une lacune signalee se traite ; une lacune
        # supprimee se redecouvre au milieu d'une analyse.
        motifs = sql_exclusions()
        portees = "\n              UNION ALL BY NAME\n".join(
            f"              (SELECT '{f.nom}' AS fenetre, {f.comparable_entre_saisons} "
            f"AS comparable_entre_saisons, {f.sql_duree()} AS jours_fenetre, * "
            f"FROM base WHERE fenetre_{f.nom})"
            for f in FENETRES
        )
        con.execute(
            f"""
            CREATE OR REPLACE VIEW saison_fenetre AS
            WITH base AS (
              SELECT * FROM risque_journalier WHERE massif_coherent
            ),
            actifs AS (
              SELECT saison, count(DISTINCT massif_id) AS massifs_actifs
              FROM base GROUP BY saison
            ),
            exclusions(saison, motif_exclusion) AS (VALUES {motifs}),
            portee AS (
              -- La saison entiere n'a pas de duree nominale : sa couverture se
              -- rapporte au span observe, calcule plus bas.
              (SELECT '{SAISON_COMPLETE}' AS fenetre, false AS comparable_entre_saisons,
                      CAST(NULL AS BIGINT) AS jours_fenetre, * FROM base)
              UNION ALL BY NAME
{portees}
            )
            SELECT
                p.saison,
                p.fenetre,
                p.comparable_entre_saisons AND e.motif_exclusion IS NULL AS comparable,
                e.motif_exclusion,
                count(*)                                        AS bulletins,
                a.massifs_actifs,
                count(DISTINCT p.massif_id)                     AS massifs_presents,
                -- Deux comptages voisins, volontairement distincts. Six
                -- bulletins de l'archive portent `RISQUE1=-1` -- la source
                -- refuse d'estimer -- tout en publiant un `RISQUEMAXI` reel :
                -- ils sont non estimes *et* comptes dans la moyenne. Confondre
                -- les deux colonnes ferait diverger ce tableau de la moyenne
                -- qu'il est cense expliquer.
                count(*) FILTER (NOT p.risque_estime)           AS non_estimes,
                count(*) FILTER (p.risque_maxi IS NULL)         AS hors_moyenne,
                min(p.jour_validite)                            AS premier_jour,
                max(p.jour_validite)                            AS dernier_jour,
                coalesce(
                    any_value(p.jours_fenetre),
                    date_diff('day', min(p.jour_validite), max(p.jour_validite)) + 1
                )                                               AS jours_fenetre,
                round(100.0 * count(*) / (a.massifs_actifs * coalesce(
                    any_value(p.jours_fenetre),
                    date_diff('day', min(p.jour_validite), max(p.jour_validite)) + 1
                )), 1)                                          AS couverture_pct,
                round(avg(p.risque_maxi), 3)                    AS risque_moyen
            FROM portee p
            JOIN actifs a USING (saison)
            LEFT JOIN exclusions e USING (saison)
            GROUP BY p.saison, p.fenetre, p.comparable_entre_saisons,
                     e.motif_exclusion, a.massifs_actifs
            ORDER BY p.saison, p.fenetre
            """
        )

        # Couverture : ce qui manque compte autant que ce qui est present.
        # L'archive comporte des journees partielles (07/02/2023 : 8 bulletins
        # sur 36) et le massif 71 disparait en 2025-2026.
        #
        # Restreinte a `massif_coherent` : sans ce filtre, le message technique
        # du 05/02/2016 diffuse sous `ID="3"` ouvrait la saison 2015-2016 du
        # Mont-Blanc un mois trop tot, avec 45 jours manquants fictifs. La ligne
        # reste dans `risque_journalier`, et `bra info` la liste.
        con.execute(
            """
            CREATE OR REPLACE VIEW couverture AS
            SELECT
                saison,
                massif_id,
                any_value(massif_nom)                  AS massif_nom,
                any_value(zone)                        AS zone,
                count(*)                               AS jours_couverts,
                min(jour_validite)                     AS premier_jour,
                max(jour_validite)                     AS dernier_jour,
                date_diff('day', min(jour_validite), max(jour_validite)) + 1
                                                       AS jours_calendaires,
                date_diff('day', min(jour_validite), max(jour_validite)) + 1 - count(*)
                                                       AS jours_manquants
            FROM risque_journalier
            WHERE massif_coherent
            GROUP BY saison, massif_id
            """
        )

        # Profil saisonnier par massif : la table de depart d'une analyse de
        # tendance. `jours_risque_fort` suit la convention europeenne (indice
        # 4 "fort" et 5 "tres fort").
        con.execute(
            """
            CREATE OR REPLACE VIEW profil_saison AS
            SELECT
                saison,
                massif_id,
                any_value(massif_nom)                          AS massif_nom,
                any_value(zone)                                AS zone,
                count(*)                                       AS jours,
                round(avg(risque_maxi), 3)                     AS risque_moyen,
                max(risque_maxi)                               AS risque_max,
                count(*) FILTER (risque_maxi >= 4)             AS jours_risque_fort,
                count(*) FILTER (risque_maxi = 3)              AS jours_risque_marque,
                count(*) FILTER (risque_maxi <= 2)             AS jours_risque_faible,
                round(avg(enneigement_limite_nord_m), 0)       AS limite_neige_nord_moy,
                count(DISTINCT format_famille)                 AS familles_de_format
            FROM risque_journalier
            WHERE risque_maxi IS NOT NULL
            GROUP BY saison, massif_id
            """
        )

        # Paliers d'altitude rattaches aux tranches normees (spec section 4.2). Un
        # format long : une ligne par valeur mesuree a une altitude, quelle que
        # soit sa source. Une tranche sans palier n'a pas de ligne -- rien n'est
        # interpole -- et un palier non releve (altitude rendue nulle par le
        # parser) garde sa ligne avec une tranche nulle : il reste visible, il
        # n'entre dans aucune tranche.
        #
        # `jour` est la date que decrit la valeur (releve, cumul, echeance),
        # pas `jour_validite` : le bloc historique d'un bulletin decrit les
        # sept jours precedents.
        #
        # Neige fraiche : avant 2024, `cumul_min_cm` / `cumul_max_cm` sont
        # derives des cumuls de un ou deux secteurs nommes ; depuis, une
        # fourchette sur le massif. La vue les transmet avec `format_famille` :
        # une comparaison qui enjambe l'hiver 2023-2024 doit l'annoncer.
        #
        # Les jointures sur `bulletins` ne perdent aucune ligne : `to_frames()`
        # ne conserve une ligne fille que pour une cle retenue dans la table
        # mere, donc toute ligne fille a son bulletin.
        presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
        if {"enneigement", "neige_fraiche", "meteo"} <= presentes:
            con.execute(
                f"""
                CREATE OR REPLACE VIEW palier_tranche AS
                WITH b AS (
                  SELECT massif_id, date_bulletin, massif_coherent, format_famille,
                         vent_altitude_basse_m, vent_altitude_haute_m
                  FROM bulletins
                ),
                paliers AS (
                  SELECT 'enneigement' AS source, e.saison, e.massif_id, e.date_bulletin,
                         e.origine, CAST(e.date_enneigement AS DATE) AS jour,
                         e.altitude_m, e.epaisseur_nord_cm, e.epaisseur_sud_cm
                  FROM enneigement e
                  UNION ALL BY NAME
                  SELECT 'neige_fraiche' AS source, n.saison, n.massif_id, n.date_bulletin,
                         n.origine, CAST(n.date_cumul AS DATE) AS jour,
                         n.altitude_mesure_m AS altitude_m, n.cumul_min_cm, n.cumul_max_cm
                  FROM neige_fraiche n
                  UNION ALL BY NAME
                  SELECT 'vent_bas' AS source, m.saison, m.massif_id, m.date_bulletin,
                         m.origine, CAST(m.echeance AS DATE) AS jour,
                         b.vent_altitude_basse_m AS altitude_m,
                         m.vent_bas_vitesse_kmh AS vent_vitesse_kmh,
                         m.vent_bas_direction AS vent_direction
                  FROM meteo m JOIN b USING (massif_id, date_bulletin)
                  UNION ALL BY NAME
                  SELECT 'vent_haut' AS source, m.saison, m.massif_id, m.date_bulletin,
                         m.origine, CAST(m.echeance AS DATE) AS jour,
                         b.vent_altitude_haute_m AS altitude_m,
                         m.vent_haut_vitesse_kmh AS vent_vitesse_kmh,
                         m.vent_haut_direction AS vent_direction
                  FROM meteo m JOIN b USING (massif_id, date_bulletin)
                  -- Pas de second vent (`ALTITUDEVENT2="9999"` avant 2024 dans
                  -- les Alpes du Sud) : il n'y a pas de palier a rattacher. Les
                  -- lignes `meteo` restent, et `bra check` compte exactement ces
                  -- bulletins (`vent_unique`) ; leur seul vent, a 3000 m, entre
                  -- par `vent_bas` et tombe en tranche haute comme apres 2024.
                  -- Un bulletin sans aucune altitude de vent (Chablais,
                  -- 11/06/2018) n'est pas un bulletin a vent unique : ses
                  -- lignes restent, sans tranche.
                  WHERE NOT (b.vent_altitude_haute_m IS NULL
                             AND b.vent_altitude_basse_m IS NOT NULL)
                )
                SELECT
                  p.source, p.saison, p.massif_id, p.date_bulletin, p.origine, p.jour,
                  p.altitude_m,
                  {sql_case_tranche('p.altitude_m')} AS tranche,
                  p.epaisseur_nord_cm, p.epaisseur_sud_cm,
                  p.cumul_min_cm, p.cumul_max_cm,
                  p.vent_vitesse_kmh, p.vent_direction,
                  b.format_famille, b.massif_coherent
                FROM paliers p JOIN b USING (massif_id, date_bulletin)
                """
            )

        # Couche metriques, bloc risque (spec section 5.1). Import local : le
        # module s'appuie lui-meme sur `build` pour ses litteraux SQL.
        from .metriques.risque import creer_vues as creer_vues_risque

        creer_vues_risque(con)

        # Couche metriques, bloc enneigement (spec section 5.2). Les journaux
        # de ses deduplications sont ecrits par `build()`, sur les frames.
        if {"enneigement", "neige_fraiche"} <= presentes:
            from .metriques.enneigement import creer_vues as creer_vues_enneigement

            creer_vues_enneigement(con)

        con.execute("CHECKPOINT")
    finally:
        con.close()
    return db_path


def stray_parquet_dirs(out_dir: str | Path) -> list[str]:
    """Repertoires de `out_dir` contenant des Parquet sans etre une table connue.

    Un glob trop large les relirait. Ils ne sont jamais supprimes
    automatiquement : le repertoire de sortie peut contenir des exports que
    l'utilisateur y a places lui-meme.
    """
    out = Path(out_dir)
    if not out.exists():
        return []
    return sorted(
        d.name for d in out.iterdir()
        if d.is_dir() and d.name not in schema.TABLES and any(d.rglob("*.parquet"))
    )


def build(
    raw_dir: str | Path = "data/raw",
    out_dir: str | Path = "warehouse",
    db_path: str | Path | None = "warehouse/bra.duckdb",
    *,
    replace: bool = False,
) -> tuple[BuildReport, dict[str, int]]:
    report = BuildReport()
    paths = iter_xml_files(raw_dir)
    parsed = parse_all(paths, report)
    frames = to_frames(parsed, report)
    report.daily_collapse_dropped = log_daily_collapse_discards(frames["bulletins"])
    from .metriques.enneigement import log_enneigement_discards, log_neige_fraiche_discards

    report.neige_fraiche_dropped, report.neige_fraiche_divergent = log_neige_fraiche_discards(
        frames["neige_fraiche"], frames["bulletins"]
    )
    report.enneigement_dropped = log_enneigement_discards(
        frames["enneigement"], frames["bulletins"]
    )
    report.stray_dirs = stray_parquet_dirs(out_dir)
    written = write_warehouse(frames, out_dir, replace=replace)
    if db_path is not None:
        if written.get("bulletins"):
            create_duckdb(out_dir, db_path)
        elif Path(db_path).exists():
            # Une base laissee par un build precedent pointerait sur des
            # partitions qui viennent d'etre purgees.
            Path(db_path).unlink()
    return report, written
