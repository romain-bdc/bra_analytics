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

import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import polars as pl

from . import schema
from .massifs import BY_ID
from .parser import ParseError, ParsedBulletin, parse_file


@dataclass
class BuildReport:
    files_seen: int = 0
    files_failed: int = 0
    bulletins_parsed: int = 0
    bulletins_kept: int = 0
    duplicates_dropped: int = 0
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

    kept = set(zip(df["massif_id"].to_list(), df["date_bulletin"].to_list())) if df.height else set()

    children: dict[str, list[dict]] = {
        "meteo": [], "enneigement": [], "neige_fraiche": [],
        "historique_risque": [], "tendances": [],
    }
    seen_keys: set[tuple] = set()
    for item in parsed:
        key = (item.bulletin["massif_id"], item.bulletin["date_bulletin"])
        # Les tables filles suivent la deduplication de la table mere : on ne
        # garde que la premiere occurrence retenue pour la cle.
        if key not in kept or key in seen_keys:
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

    frames = {"bulletins": df}
    for name, rows in children.items():
        frames[name] = _frame(rows, schema.TABLES[name])
    return frames


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
        con.execute(
            """
            CREATE OR REPLACE VIEW risque_journalier AS
            SELECT * EXCLUDE (rang) FROM (
              SELECT
                saison,
                massif_id,
                massif_nom,
                zone,
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
        # Couverture : ce qui manque compte autant que ce qui est present.
        # L'archive comporte des journees partielles (07/02/2023 : 8 bulletins
        # sur 36) et le massif 71 disparait en 2025-2026.
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
