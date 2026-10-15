"""Interface en ligne de commande : `bra fetch`, `bra build`, `bra info`, `bra audit`, `bra ui`."""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from .fenetres import DEFAUT, FENETRES, SAISON_COMPLETE, SAISONS_NON_COMPARABLES
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

    report, written = build(
        args.cache, args.out, None if args.no_db else args.db, replace=args.replace
    )
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
        # `massif_coherent` ecarte les lignes dont l'`ID` et le libelle `MASSIF`
        # se contredisent. Sans ce filtre, le message technique de 2016 diffuse
        # sous `ID="3"` (Mont-Blanc) comptait pour un douzieme massif pyreneen
        # et avancait le debut de la saison 2015-2016 au 4 fevrier.
        print("Bulletins par saison :")
        rows = con.execute(
            "SELECT saison, count(*) n, count(DISTINCT massif_id) massifs, "
            "min(jour_bulletin) du, max(jour_bulletin) au, "
            "round(avg(risque_maxi), 2) risque_moyen "
            "FROM bulletins WHERE massif_coherent GROUP BY saison ORDER BY saison"
        ).fetchall()
        print(f"  {'saison':<12}{'n':>7}{'massifs':>9}  {'debut':<12}{'fin':<12}{'risque moy.':>12}")
        for saison, n, massifs, debut, fin, moyen in rows:
            print(f"  {saison:<12}{n:>7}{massifs:>9}  {str(debut):<12}{str(fin):<12}{str(moyen):>12}")

        print(
            "\n  La colonne « risque moy. » porte sur la saison entiere : elle n'est"
            "\n  pas comparable d'une saison a l'autre. Voir `bra fenetres`."
        )

        # Ecartees, mais nommees : une ligne retiree en silence est une ligne
        # qu'on redecouvre au milieu d'une analyse.
        ecartees = con.execute(
            "SELECT saison, massif_id, any_value(massif_nom) AS attendu, "
            "any_value(massif_nom_source) AS lu, count(*) AS n "
            "FROM bulletins WHERE NOT massif_coherent GROUP BY saison, massif_id "
            "ORDER BY saison, massif_id"
        ).fetchall()
        if ecartees:
            print(f"\nEcartees du tableau ({len(ecartees)} couple(s) saison/massif) —"
                  " ID et libelle se contredisent :")
            for saison, mid, attendu, lu, n in ecartees:
                print(f"  {saison}  ID={mid} ({attendu}) porte MASSIF={lu!r} — {n} bulletin(s)")
    finally:
        con.close()
    return 0


def cmd_fenetres(args: argparse.Namespace) -> int:
    """Publie, par saison et par fenetre, ce qui rend deux saisons comparables."""
    import duckdb

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    portees = [(f.nom, f) for f in FENETRES] + [(SAISON_COMPLETE, None)]
    con = duckdb.connect(str(db), read_only=True)
    try:
        for nom, fenetre in portees:
            titre = f"{nom}" + (f"  ({fenetre.libelle})" if fenetre else "")
            print(f"\n=== {titre} ===")
            if fenetre:
                print(f"  usage        : {fenetre.usage}")
                print(f"  justification: {fenetre.justification}")
                if not fenetre.comparable_entre_saisons:
                    print("  /!\\ ne pas comparer de moyennes de risque sur cette fenetre :"
                          " elle couvre les mois ou le `-1` est massif")
            else:
                print("  usage        : lecture d'une saison prise isolement")
                print("  /!\\ non comparable entre saisons : bornes et encodage des journees"
                      "\n       marginales varient d'une saison a l'autre")
            rows = con.execute(
                "SELECT saison, comparable, bulletins, massifs_actifs, non_estimes, "
                "jours_fenetre, couverture_pct, risque_moyen, motif_exclusion "
                "FROM saison_fenetre WHERE fenetre = ? ORDER BY saison",
                [nom],
            ).fetchall()
            print(f"\n  {'saison':<11}{'bulletins':>10}{'massifs':>9}{'non est.':>10}"
                  f"{'jours':>7}{'couv.':>8}{'risque':>8}")
            for saison, comparable, n, m, ne, jf, cv, rm, motif in rows:
                # L'asterisque ne marque que l'exclusion propre a la saison. Le
                # fait qu'une *fenetre* interdise la comparaison est annonce une
                # fois en tete : le repeter sur chaque ligne noierait le signal.
                marque = "*" if motif else " "
                print(f"  {saison:<11}{n:>10}{m:>9}{ne:>10}{jf:>7}"
                      f"{str(cv) + ' %':>8}{str(rm):>8} {marque}")
        print("\n* saison ecartee des comparaisons inter-saisons, quelle que soit"
              " la fenetre :")
        for saison, motif in SAISONS_NON_COMPARABLES.items():
            print(f"    {saison} — {motif}")
        print(f"\nFenetre par defaut des comparaisons inter-saisons : {DEFAUT.nom}"
              f" ({DEFAUT.libelle}).")
    finally:
        con.close()
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Interface web locale de DuckDB : editeur SQL, explorateur de tables, graphiques."""
    import duckdb

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    con = duckdb.connect(str(db), read_only=True)
    try:
        try:
            con.execute("INSTALL ui")
            con.execute("LOAD ui")
        except duckdb.Error as exc:  # premiere utilisation sans reseau
            raise SystemExit(
                f"extension `ui` indisponible ({exc}).\n"
                "Elle se telecharge au premier lancement : verifier la connexion reseau."
            ) from exc

        con.execute("SET ui_local_port = ?", [args.port])
        con.execute("CALL start_ui_server()")
        url = f"http://localhost:{args.port}/"

        if not args.no_browser:
            import webbrowser

            webbrowser.open(url)

        print(f"DuckDB UI : {url}", flush=True)
        print(f"base      : {db} (lecture seule)")
        print("\nvues de travail : risque_journalier, couverture, profil_saison")
        print("Ctrl-C pour arreter.", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\narret.")
    finally:
        con.close()
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import render

    out = render(args.db, args.out, args.zone, standalone=not args.fragment)
    print(f"tableau de bord : {out} ({out.stat().st_size / 1024:.0f} Ko)")
    if args.fragment:
        print("fragment sans doctype : a inserer dans un hote qui fournit le squelette HTML.")
    else:
        print("page autonome : ouvrir directement dans un navigateur, aucun serveur requis.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    import polars as pl

    from .quality import coverage_gaps, report

    pattern = Path(args.out) / "bulletins" / "**" / "*.parquet"
    try:
        df = pl.read_parquet(pattern)
    except Exception as exc:  # entrepot absent ou vide
        raise SystemExit(f"entrepot illisible ({exc}) - lancer `bra build`")

    filles = {}
    for table in ("meteo", "enneigement", "neige_fraiche"):
        chemin = Path(args.out) / table / "**" / "*.parquet"
        try:
            filles[table] = pl.read_parquet(chemin)
        except Exception:  # table absente d'un entrepot partiel
            continue
    print(report(df, filles))
    gaps = coverage_gaps(df).filter(pl.col("jours_manquants") > 0)
    if gaps.height:
        print(f"\nSeries a trous ({gaps.height} couples massif/saison) :")
        with pl.Config(tbl_rows=15):
            print(gaps.select("saison", "massif_id", "jours_couverts", "jours_manquants"))
    return 0


def cmd_contours(args: argparse.Namespace) -> int:
    """Raccorde les contours au referentiel et ecrit leur version web."""
    import json

    from . import geo

    source = geo.charger(args.source)
    r = geo.raccordement(source)
    print(f"contours : {len(source['features'])} entites, source {args.source}")
    if r.manquants:
        print(f"  massifs sans contour : {', '.join(map(str, r.manquants))}")
    if r.en_trop:
        print(f"  contours hors referentiel : {', '.join(map(str, r.en_trop))}")
    if r.complet:
        print(f"  raccordement complet : {len(source['features'])} massifs, "
              "aucun contour en trop")

    simple = geo.version_web(source)
    out = Path(args.out)
    out.write_text(json.dumps(simple, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"version web : {out} ({out.stat().st_size / 1024:.0f} Ko)")
    # Un ecart est signale par le code de sortie, pas seulement affiche.
    return 0 if r.complet else 1


def cmd_audit(args: argparse.Namespace) -> int:
    """Disponibilite champ x saison, ecrite dans `docs/disponibilite.md`."""
    import duckdb

    from .audit import rapport

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")
    con = duckdb.connect(str(db), read_only=True)
    try:
        texte = rapport(con)
    finally:
        con.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(texte, encoding="utf-8")
    print(f"audit de disponibilite : {out}")
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
    b.add_argument(
        "--replace",
        action="store_true",
        help="recreer entierement les repertoires de tables, au lieu de ne purger "
             "que les partitions",
    )
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("info", help="resume de l'entrepot")
    i.add_argument("--db", default="warehouse/bra.duckdb")
    i.set_defaults(func=cmd_info)

    fen = sub.add_parser(
        "fenetres", help="comparabilite des saisons, fenetre par fenetre"
    )
    fen.add_argument("--db", default="warehouse/bra.duckdb")
    fen.set_defaults(func=cmd_fenetres)

    c = sub.add_parser("check", help="controler la coherence de l'entrepot")
    c.add_argument("--out", default="warehouse", help="repertoire de l'entrepot")
    c.set_defaults(func=cmd_check)

    u = sub.add_parser("ui", help="ouvrir l'interface web DuckDB")
    u.add_argument("--db", default="warehouse/bra.duckdb")
    u.add_argument("--port", type=int, default=4213, help="port d'ecoute (defaut: 4213)")
    u.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    u.set_defaults(func=cmd_ui)

    d = sub.add_parser("dashboard", help="generer le tableau de bord HTML statique")
    d.add_argument("--db", default="warehouse/bra.duckdb")
    d.add_argument("--out", default="dashboard.html", help="fichier de sortie")
    d.add_argument("--zone", default="Pyrenees", help="zone a representer (defaut: Pyrenees)")
    d.add_argument("--fragment", action="store_true",
                   help="omettre doctype et <html> (page destinee a etre hebergee)")
    d.set_defaults(func=cmd_dashboard)

    from . import geo

    g = sub.add_parser("contours", help="raccorder et simplifier les contours des massifs")
    g.add_argument("--source", default=str(geo.SOURCE), help="GeoJSON d'origine")
    g.add_argument("--out", default=str(geo.WEB), help="GeoJSON simplifie")
    g.set_defaults(func=cmd_contours)

    a = sub.add_parser("audit", help="disponibilite des champs saison par saison")
    a.add_argument("--db", default="warehouse/bra.duckdb")
    a.add_argument("--out", default="docs/disponibilite.md", help="document de sortie")
    a.set_defaults(func=cmd_audit)

    m = sub.add_parser("massifs", help="lister le referentiel des massifs")
    m.set_defaults(func=cmd_massifs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
