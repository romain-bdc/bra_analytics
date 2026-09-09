"""Interface en ligne de commande : `bra fetch`, `bra build`, `bra info`."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from .fetch import BraFetcher, season_days
from .massifs import ALPES, CORSE, MASSIFS, PYRENEES

_GROUPS = {"pyrenees": PYRENEES, "alpes": ALPES, "corse": CORSE}


def _parse_massifs(value: str | None) -> tuple[int, ...] | None:
    if not value or value.lower() in ("all", "tous"):
        return None
    ids: list[int] = []
    for token in value.split(","):
        token = token.strip().lower()
        if token in _GROUPS:
            ids.extend(_GROUPS[token])
        elif token.isdigit():
            ids.append(int(token))
        else:
            raise SystemExit(f"massif inconnu : {token!r} (groupes: {', '.join(_GROUPS)})")
    return tuple(dict.fromkeys(ids))


def _day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def cmd_fetch(args: argparse.Namespace) -> int:
    massifs = _parse_massifs(args.massifs)
    if args.seasons:
        days = [d for s in args.seasons for d in season_days(s)]
    elif args.start and args.end:
        from .fetch import daterange

        days = list(daterange(args.start, args.end))
    else:
        raise SystemExit("preciser --seasons ou --start/--end")

    today = date.today()
    days = [d for d in days if d <= today]

    print(f"{len(days)} jours a inspecter, massifs={massifs or 'tous'}", flush=True)
    with BraFetcher(args.cache, workers=args.workers) as fetcher:
        for index, day in enumerate(days, 1):
            fetcher.fetch_day(day, massifs)
            if index % 25 == 0 or index == len(days):
                s = fetcher.stats
                print(
                    f"  [{index}/{len(days)}] {day} telecharges={s.downloaded} "
                    f"cache={s.cached} ignores={s.skipped} jours_absents={s.missing_days} erreurs={s.errors}",
                    flush=True,
                )
        stats = fetcher.stats
    print(
        f"\ntermine : {stats.downloaded} telecharges, {stats.cached} deja en cache, "
        f"{stats.errors} erreurs, {stats.missing_days} jours absents"
    )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .build import build

    report, written = build(args.cache, args.out, None if args.no_db else args.db)
    print(report.summary())
    print("\nlignes ecrites :")
    for name, count in written.items():
        print(f"  {name:<20} {count}")
    if not args.no_db and written.get("bulletins"):
        print(f"\nbase DuckDB : {args.db}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    import duckdb

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")
    con = duckdb.connect(str(db), read_only=True)
    try:
        print("Bulletins par saison :")
        rows = con.execute(
            "SELECT saison, count(*) n, count(DISTINCT massif_id) massifs, "
            "min(jour_bulletin) du, max(jour_bulletin) au, "
            "round(avg(risque_maxi), 2) risque_moyen "
            "FROM bulletins GROUP BY saison ORDER BY saison"
        ).fetchall()
        print(f"  {'saison':<12}{'n':>7}{'massifs':>9}  {'debut':<12}{'fin':<12}{'risque moy.':>12}")
        for saison, n, massifs, debut, fin, moyen in rows:
            print(f"  {saison:<12}{n:>7}{massifs:>9}  {str(debut):<12}{str(fin):<12}{str(moyen):>12}")
    finally:
        con.close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    import polars as pl

    from .quality import coverage_gaps, report

    pattern = Path(args.out) / "bulletins" / "**" / "*.parquet"
    try:
        df = pl.read_parquet(pattern)
    except Exception as exc:  # entrepot absent ou vide
        raise SystemExit(f"entrepot illisible ({exc}) - lancer `bra build`")

    print(report(df))
    gaps = coverage_gaps(df).filter(pl.col("jours_manquants") > 0)
    if gaps.height:
        print(f"\nSeries a trous ({gaps.height} couples massif/saison) :")
        with pl.Config(tbl_rows=15):
            print(gaps.select("saison", "massif_id", "jours_couverts", "jours_manquants"))
    return 0


def cmd_massifs(args: argparse.Namespace) -> int:
    print(f"{'id':>4}  {'nom':<24}{'zone':<16}departement")
    for m in MASSIFS:
        print(f"{m.id:>4}  {m.nom:<24}{m.zone:<16}{m.departement}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bra", description=__doc__)
    parser.add_argument("--cache", default="data/raw", help="cache XML local (defaut: data/raw)")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="telecharger les archives")
    f.add_argument("--seasons", type=int, nargs="*", help="annees de debut de saison, ex: 2023 2024")
    f.add_argument("--start", type=_day, help="date de debut AAAA-MM-JJ")
    f.add_argument("--end", type=_day, help="date de fin AAAA-MM-JJ")
    f.add_argument("--massifs", default="pyrenees", help="ids, groupes (pyrenees/alpes/corse) ou 'all'")
    f.add_argument("--workers", type=int, default=6, help="telechargements simultanes (defaut: 6)")
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("build", help="construire l'entrepot Parquet")
    b.add_argument("--out", default="warehouse", help="repertoire de sortie")
    b.add_argument("--db", default="warehouse/bra.duckdb", help="base DuckDB")
    b.add_argument("--no-db", action="store_true", help="ne pas creer la base DuckDB")
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("info", help="resume de l'entrepot")
    i.add_argument("--db", default="warehouse/bra.duckdb")
    i.set_defaults(func=cmd_info)

    c = sub.add_parser("check", help="controler la coherence de l'entrepot")
    c.add_argument("--out", default="warehouse", help="repertoire de l'entrepot")
    c.set_defaults(func=cmd_check)

    m = sub.add_parser("massifs", help="lister le referentiel des massifs")
    m.set_defaults(func=cmd_massifs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
