"""Audit de disponibilite des champs, saison par saison (`bra audit`).

Le but est de savoir quelles metriques sont reellement calculables avant d'en
ecrire une seule. Le format XML a change six fois et plusieurs blocs sont
propres a une epoque (`sat1`/`sat2` depuis 2024, `tendances` jusqu'en 2023) :
une metrique qui suppose un champ partout produirait une serie silencieusement
tronquee.

Toutes les mesures portent sur les lignes `massif_coherent` : le message
technique de 2016 diffuse sous `ID="3"` n'est pas un bulletin, et le compter
ferait mentir les parts du Mont-Blanc. Les lignes ecartees sont comptees dans
le rapport, pas oubliees.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import polars as pl

from . import schema
from .quality import VENT_MAX_KMH

# Colonnes de cle ou de provenance : leur presence est garantie par
# construction, la mesurer n'apprendrait rien.
_HORS_AUDIT = {"massif_id", "date_bulletin", "saison", "saison_debut", "fichier_source"}


def _source(table: str) -> str:
    """Lignes d'une table restreintes aux bulletins `massif_coherent`.

    Les tables filles ne portent pas la colonne : on la reprend du bulletin
    parent par sa cle `(massif_id, date_bulletin)`, avec `format_famille` qui
    sert a separer les epoques quand un attribut change de sens.
    """
    if table == "bulletins":
        return "SELECT * FROM bulletins WHERE massif_coherent"
    return (
        f"SELECT t.*, b.format_famille FROM {table} t JOIN bulletins b "
        "USING (massif_id, date_bulletin) WHERE b.massif_coherent"
    )


def _frame(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pl.DataFrame:
    """Resultat DuckDB -> polars sans passer par pyarrow.

    `.pl()` exige pyarrow, dependance que rien d'autre ne justifie ici.
    """
    cur = con.execute(sql, params or [])
    noms = [d[0] for d in cur.description]
    return pl.DataFrame(cur.fetchall(), schema=noms, orient="row")


def _tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    presentes = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    return [t for t in schema.TABLES if t in presentes]


# Champs dont la valeur existe mais ne veut pas dire ce que son nom annonce,
# selon la famille de format : ces lignes ne comptent pas comme disponibles.
# Le seul cas mesure -- `SS241` / `SS242`, cumuls de deux secteurs ranges
# avant 2024 dans `cumul_min_cm` / `cumul_max_cm` -- est regle au parsing
# depuis octobre 2026 : les secteurs sont conserves et les bornes en sont
# derivees (`parser._extract_neige_fraiche`). Le mecanisme reste pour le
# prochain champ trompeur.
SEMANTIQUE_DIVERGENTE: dict[tuple[str, str], tuple[str, str]] = {}

# Avant 2024 `cumul_max_cm` est le plus fort de un ou deux secteurs nommes ;
# depuis, la borne haute d'une fourchette sur le massif. Les deux se lisent,
# mais ne mesurent pas la meme chose : rupture de serie a l'hiver 2023-2024.
FAMILLE_NEIGE_FRAICHE_HOMOGENE = "moderne"

_ENTIERS = (pl.Int8, pl.Int16, pl.Int32, pl.Int64)


def _compte_exploitable(table: str, champ: str) -> str:
    """Agregat SQL comptant les valeurs exploitables d'un champ.

    Exploitable = non nul, et pour un entier different de `-1` : la source
    emploie `-1` comme sentinelle. Le parser la convertit en nul partout ou
    son sens est etabli (indices, paliers et limites d'enneigement, meteo,
    neige fraiche) ; le filtre reste pour toute colonne ou elle subsisterait.
    Une colonne pleine de `-1` n'est pas une colonne disponible.
    """
    conds = [f'"{champ}" IS NOT NULL']
    if schema.TABLES[table][champ] in _ENTIERS:
        conds.append(f'"{champ}" <> -1')
    if (table, champ) in SEMANTIQUE_DIVERGENTE:
        famille, _ = SEMANTIQUE_DIVERGENTE[(table, champ)]
        conds.append(f"format_famille <> '{famille}'")
    return f"count(*) FILTER ({' AND '.join(conds)})"


def disponibilite(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Part de valeurs exploitables, par table, champ et saison.

    Exploitable : voir `_compte_exploitable` -- ni nul, ni `-1`, ni porteur
    d'un sens different de celui du champ (`SEMANTIQUE_DIVERGENTE`).
    Colonnes : `table`, `champ`, `saison`, `lignes`, `non_nulles` (valeurs
    exploitables), `part` (arrondie a 4 decimales pour que le rapport soit
    reproductible).
    """
    morceaux = []
    for table in _tables(con):
        champs = [c for c in schema.TABLES[table] if c not in _HORS_AUDIT]
        comptes = ", ".join(f'{_compte_exploitable(table, c)} AS "{c}"' for c in champs)
        large = _frame(
            con,
            f"SELECT saison, count(*) AS lignes, {comptes} "
            f"FROM ({_source(table)}) GROUP BY saison",
        )
        morceaux.append(
            large.unpivot(index=["saison", "lignes"], variable_name="champ",
                          value_name="non_nulles")
            .with_columns(table=pl.lit(table))
        )
    if not morceaux:
        return pl.DataFrame(schema={
            "table": pl.Utf8, "champ": pl.Utf8, "saison": pl.Utf8,
            "lignes": pl.Int64, "non_nulles": pl.Int64, "part": pl.Float64,
        })
    return (
        pl.concat(morceaux)
        .with_columns(part=(pl.col("non_nulles") / pl.col("lignes")).round(4))
        .select("table", "champ", "saison", "lignes", "non_nulles", "part")
        .sort("table", "champ", "saison")
    )


# --------------------------------------------------------------------------
# Metriques de la spec (section 5) et champs dont elles dependent
# --------------------------------------------------------------------------

CALCULABLE = "calculable"
SOUS_ENSEMBLE = "sous-ensemble"
NON_CALCULABLE = "non calculable"


@dataclass(frozen=True)
class Metrique:
    """Une metrique de la spec, declaree une fois avec les champs qu'elle lit.

    `champs` sont des references `table.champ`. `indice` nomme, parmi eux,
    ceux qui doivent porter une valeur chiffree : un champ texte ne le peut pas,
    si rempli soit-il. Les autres champs peuvent etre des qualificatifs texte
    (`loc_type` qualifie le second indice sans le porter).
    """

    bloc: str
    nom: str
    champs: tuple[str, ...]
    indice: tuple[str, ...] = ()


_R = ("bulletins.risque_maxi",)
_ENN_EP = ("enneigement.altitude_m", "enneigement.epaisseur_nord_cm", "enneigement.epaisseur_sud_cm")
_ENN_LIM = ("enneigement.limite_nord_m", "enneigement.limite_sud_m")
_NF = ("neige_fraiche.cumul_max_cm",)
_ISO = ("meteo.iso_0_m",)
_VENT = (
    "meteo.vent_bas_vitesse_kmh", "meteo.vent_bas_direction",
    "meteo.vent_haut_vitesse_kmh", "meteo.vent_haut_direction",
    "bulletins.vent_altitude_basse_m", "bulletins.vent_altitude_haute_m",
)
_PENTES = tuple(f"bulletins.pente_{s}" for s in ("n", "ne", "e", "se", "s", "sw", "w", "nw"))

METRIQUES: tuple[Metrique, ...] = (
    # 5.1 Risque
    Metrique("risque", "Risque du jour", _R, indice=_R),
    Metrique("risque", "Jours ≥ 3 / ≥ 4 / = 5", _R, indice=_R),
    Metrique("risque", "Part de jours par niveau", _R, indice=_R),
    Metrique("risque", "Risque moyen", _R, indice=_R),
    Metrique("risque", "Risque médian", _R, indice=_R),
    Metrique("risque", "Maximum saisonnier", _R, indice=_R),
    Metrique("risque", "Première / dernière occurrence ≥ 3", _R, indice=_R),
    Metrique("risque", "Durée de saison BRA", ("bulletins.jour_validite",)),
    Metrique("risque", "Épisodes ≥ 3", _R, indice=_R),
    Metrique("risque", "Variations", _R, indice=_R),
    Metrique("risque", "Écart à la normale", _R, indice=_R),
    Metrique("risque", "Second indice",
             ("bulletins.risque1", "bulletins.risque2", "bulletins.loc_type"),
             indice=("bulletins.risque1", "bulletins.risque2")),
    # Prevue au cadrage, ecartee par la spec section 5.1 : on la garde ici pour que
    # l'audit dise pourquoi, plutot que de la faire disparaitre.
    Metrique("risque", "Indices naturel et accidentel",
             ("bulletins.naturel", "bulletins.accidentel"),
             indice=("bulletins.naturel", "bulletins.accidentel")),
    # 5.2 Enneigement
    Metrique("enneigement", "Limite d'enneigement", _ENN_LIM),
    Metrique("enneigement", "Épaisseur par tranche", _ENN_EP),
    Metrique("enneigement", "Date d'enneigement continu", _ENN_LIM),
    Metrique("enneigement", "Durée d'enneigement", _ENN_EP),
    Metrique("enneigement", "Maximum saisonnier d'épaisseur", _ENN_EP),
    Metrique("enneigement", "Neige fraîche cumulée", ("neige_fraiche.origine",) + _NF),
    Metrique("enneigement", "Épisodes de chute", _NF),
    Metrique("enneigement", "Anomalie d'enneigement", _ENN_EP),
    # 5.3 Meteo
    Metrique("meteo", "Isotherme 0 °C", _ISO),
    Metrique("meteo", "ISO 0 min / max / moyen", _ISO),
    Metrique("meteo", "Jours ISO 0 > seuil", _ISO),
    Metrique("meteo", "Amplitude ISO 0 en 24 h", _ISO),
    Metrique("meteo", "Vitesse et direction de vent", _VENT),
    Metrique("meteo", "Jours de vent fort", ("meteo.vent_haut_vitesse_kmh",)),
    Metrique("meteo", "Limite pluie / neige", ("meteo.limite_pluie_neige_m",)),
    Metrique("meteo", "Temps sensible", ("meteo.temps_sensible",)),
    Metrique("meteo", "Indice de transport par le vent", _VENT + _NF),
    Metrique("meteo", "Épisodes de redoux", _ISO + _R),
    # 5.4 Rose des pentes et situations typiques
    Metrique("rose", "Fréquence d'exposition", _PENTES),
    Metrique("rose", "Fréquence pondérée", _PENTES + _R),
    Metrique("rose", "Secteur dominant", _PENTES),
    Metrique("rose", "Concentration", _PENTES),
    Metrique("rose", "Saisonnalité", _PENTES),
    Metrique("rose", "Croisement vent × orientation",
             _PENTES + ("meteo.vent_haut_direction", "meteo.vent_bas_direction")),
    Metrique("rose", "Situations typiques", ("bulletins.sat1",)),
    # 5.5 Score composite
    Metrique("score", "Score composite",
             _R + _ENN_EP + ("meteo.vent_haut_vitesse_kmh",)),
)


def _est_texte(ref: str) -> bool:
    table, champ = ref.split(".")
    return schema.TABLES[table][champ] == pl.Utf8


def statuts(dispo: pl.DataFrame, metriques: tuple[Metrique, ...] = METRIQUES) -> pl.DataFrame:
    """Statut de chaque metrique, derive de la disponibilite mesuree.

    - `calculable` : tous ses champs sont presents sur toutes les saisons ;
    - `sous-ensemble` : ils le sont sur une partie des saisons, listees ;
    - `non calculable` : aucune saison ne les reunit, ou la metrique attend un
      indice chiffre d'un champ texte.

    Un champ est tenu pour present sur une saison des qu'il y porte une valeur
    exploitable (voir `disponibilite`). Le seuil est volontairement bas : un champ rare par nature
    (`sat2`, `altitude_seuil_m`) n'est pas un champ absent, et la part mesuree
    reste publiee a cote pour qui veut juger de sa densite.
    """
    toutes = sorted(dispo.filter(pl.col("table") == "bulletins")["saison"].unique().to_list())
    presents = {
        (t, c, s)
        for t, c, s in dispo.filter(pl.col("non_nulles") > 0)
        .select("table", "champ", "saison").iter_rows()
    }
    lignes = []
    for m in metriques:
        textes = [r for r in m.indice if _est_texte(r)]
        if textes:
            statut, saisons = NON_CALCULABLE, []
            motif = "champ texte rédigé, pas un indice chiffré : " + ", ".join(textes)
        else:
            saisons = [
                s for s in toutes
                if all((*r.split("."), s) in presents for r in m.champs)
            ]
            if saisons == toutes:
                statut, motif = CALCULABLE, None
            elif saisons:
                manquants = sorted({
                    r for r in m.champs
                    if any((*r.split("."), s) not in presents for s in toutes)
                })
                statut = SOUS_ENSEMBLE
                motif = "absent sur une partie des saisons : " + ", ".join(manquants)
                raisons = [
                    SEMANTIQUE_DIVERGENTE[tuple(r.split("."))][1]
                    for r in manquants if tuple(r.split(".")) in SEMANTIQUE_DIVERGENTE
                ]
                if raisons:
                    motif += " (" + " ; ".join(raisons) + ")"
            else:
                statut, motif = NON_CALCULABLE, "aucune saison ne réunit ses champs"
        lignes.append({
            "bloc": m.bloc, "metrique": m.nom, "statut": statut,
            "saisons": ", ".join(saisons), "champs": ", ".join(m.champs), "motif": motif,
        })
    return pl.DataFrame(lignes, schema={
        "bloc": pl.Utf8, "metrique": pl.Utf8, "statut": pl.Utf8,
        "saisons": pl.Utf8, "champs": pl.Utf8, "motif": pl.Utf8,
    })


# --------------------------------------------------------------------------
# Mesures ciblees : ce qui fonde les tranches normees et les seuils
# --------------------------------------------------------------------------

def altitudes_reference(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Altitudes distinctes par massif, saison et source.

    Lues dans la vue `palier_tranche`, qui porte seule la correspondance
    source -> colonne d'altitude : la recopier ici ferait deux definitions a
    tenir d'accord. Les sentinelles `-1` restent dans la liste, pour etre vues.
    Colonnes : `massif_id`, `saison`, `source`, `altitudes` (valeurs triees,
    jointes par `/`), `lignes` (paliers mesures).
    """
    return _frame(
        con,
        """
        SELECT massif_id, saison, source,
               -- tri numerique : un tri texte placerait 900 apres 1500
               array_to_string(list_sort(list_distinct(list(altitude_m))), '/') AS altitudes,
               count(*) AS lignes
        FROM palier_tranche
        WHERE massif_coherent AND altitude_m IS NOT NULL
        GROUP BY ALL
        ORDER BY massif_id, saison, source
        """,
    )


def meteo_par_origine(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Part de valeurs exploitables de chaque champ meteo, par saison et `origine`.

    Exploitable au sens de `disponibilite` : ni nul, ni `-1`.
    Colonnes : `saison`, `origine`, `champ`, `lignes`, `part`.
    """
    champs = [c for c in schema.METEO if c not in _HORS_AUDIT | {"origine", "rang", "echeance"}]
    comptes = ", ".join(f'{_compte_exploitable("meteo", c)} AS "{c}"' for c in champs)
    large = _frame(
        con,
        f"SELECT saison, origine, count(*) AS lignes, {comptes} "
        f"FROM ({_source('meteo')}) GROUP BY saison, origine",
    )
    return (
        large.unpivot(index=["saison", "origine", "lignes"], variable_name="champ",
                      value_name="non_nulles")
        .with_columns(part=(pl.col("non_nulles") / pl.col("lignes")).round(4))
        .select("saison", "origine", "champ", "lignes", "part")
        .sort("saison", "origine", "champ")
    )


# Un champ que l'historique porte deux fois moins souvent que la prevision ne
# soutient pas la convention : la serie extraite serait trouee de moitie.
DENSITE_HISTORIQUE_MIN = 0.5


def ecarts_meteo(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Champs que l'historique ne porte pas aussi bien que la prevision.

    La convention d'extraction (spec section 4.3) prefere l'historique a la
    prevision pour un meme jour : elle n'est tenable que pour les champs que
    l'historique porte effectivement. Un champ est en ecart quand sa part dans
    l'historique est inferieure a `DENSITE_HISTORIQUE_MIN` fois sa part en
    prevision -- absent ou simplement trop rare. Colonnes : `saison`,
    `champ`, `part_prevision`, `part_historique`.
    """
    parts = meteo_par_origine(con)
    prev = (
        parts.filter((pl.col("origine") == "prevision") & (pl.col("part") > 0))
        .select("saison", "champ", part_prevision="part")
    )
    hist = (
        parts.filter(pl.col("origine") == "historique")
        .select("saison", "champ", part_historique="part")
    )
    return (
        prev.join(hist, on=["saison", "champ"], how="left")
        .with_columns(pl.col("part_historique").fill_null(0.0))
        .filter(pl.col("part_historique") < DENSITE_HISTORIQUE_MIN * pl.col("part_prevision"))
        .sort("saison", "champ")
    )


def _quantiles(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Distributions des champs dont les seuils par defaut restent a fixer.

    `quantile_disc` plutot que `quantile_cont` : les valeurs sont entieres, et
    un quantile interpole (37,5 km/h) n'a jamais ete ecrit dans un bulletin.

    La sentinelle `-1` est ecartee comme dans `_compte_exploitable` : sur les
    36 massifs elle occupe 40 053 des 255 535 vitesses de vent haut en
    prevision (15,7 %). Les quantiles publies n'en bougent pas (30/50/70 km/h
    avec ou sans), mais `n` annoncait un echantillon qu'il n'avait pas.
    """
    # Un seuil se cale sur une serie homogene : `cumul_max_cm` change de sens
    # a l'hiver 2023-2024 (`FAMILLE_NEIGE_FRAICHE_HOMOGENE`).
    famille = FAMILLE_NEIGE_FRAICHE_HOMOGENE
    series = (
        # Un vent hors plage est une erreur de saisie (`bra check`,
        # `vent_hors_plage`) : exclu ici comme des metriques.
        ("vent_haut_vitesse_kmh", "meteo", "prevision",
         f"origine = 'prevision' AND vent_haut_vitesse_kmh <= {VENT_MAX_KMH}", "km/h"),
        ("vent_bas_vitesse_kmh", "meteo", "prevision",
         f"origine = 'prevision' AND vent_bas_vitesse_kmh <= {VENT_MAX_KMH}", "km/h"),
        ("iso_0_m", "meteo", "prevision", "origine = 'prevision'", "m"),
        ("cumul_max_cm", "neige_fraiche", f"historique, famille {famille}",
         f"origine = 'historique' AND format_famille = '{famille}'", "cm"),
    )
    lignes = []
    for champ, table, libelle, filtre, unite in series:
        n, q = con.execute(
            f"SELECT count({champ}), quantile_disc({champ}, [0.5, 0.75, 0.9, 0.95, 0.99, 1.0]) "
            f"FROM ({_source(table)}) WHERE {filtre} AND {champ} IS NOT NULL "
            f"AND {champ} <> -1"
        ).fetchone()
        lignes.append((f"`{table}.{champ}`", libelle, unite, n,
                       *(q or [None] * 6)))
    return lignes


# --------------------------------------------------------------------------
# Rendu Markdown
# --------------------------------------------------------------------------

def _md(entetes: list[str], lignes: list[tuple]) -> str:
    def cell(v: object) -> str:
        if v is None:
            return "—"
        return str(v).replace("|", "\\|")

    out = ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)]
    out += ["| " + " | ".join(cell(v) for v in ligne) + " |" for ligne in lignes]
    return "\n".join(out)


def _pct(part: float | None) -> str:
    if part is None:
        return "—"
    if part == 0:
        return "0"
    if part == 1:
        return "100"
    # Ni 0 ni 100 affiches pour une part qui ne l'est pas : 0,04 % de
    # presence n'est pas une absence, et c'est souvent l'information utile.
    return f"{max(min(part * 100, 99.9), 0.1):.1f}".replace(".", ",")


def _matrice(dispo: pl.DataFrame, table: str, saisons: list[str]) -> str:
    sous = dispo.filter(pl.col("table") == table)
    parts = {(c, s): p for c, s, p in sous.select("champ", "saison", "part").iter_rows()}
    champs = [c for c in schema.TABLES[table] if c not in _HORS_AUDIT]
    lignes = [(f"`{c}`", *(_pct(parts.get((c, s))) for s in saisons)) for c in champs]
    return _md(["champ", *saisons], lignes)


def _plages(saisons: list[str], toutes: list[str]) -> str:
    """Runs contigus de saisons : `2016-2017 -> 2019-2020, 2022-2023`.

    Le rendu Markdown remplace `->` par une fleche.
    """
    rang = {s: i for i, s in enumerate(toutes)}
    runs: list[list[str]] = []
    for s in sorted(saisons, key=rang.__getitem__):
        if runs and rang[s] == rang[runs[-1][-1]] + 1:
            runs[-1].append(s)
        else:
            runs.append([s])
    return ", ".join(r[0] if len(r) == 1 else f"{r[0]} → {r[-1]}" for r in runs)


def rapport(con: duckdb.DuckDBPyConnection) -> str:
    """Document `docs/disponibilite.md`, deterministe pour un entrepot donne.

    Aucune horodatation de generation : la seule date publiee est celle du
    dernier jour couvert, qui ne change qu'avec les donnees.
    """
    from .massifs import BY_ID
    from .tranches import TRANCHES

    dispo = disponibilite(con)
    saisons = sorted(dispo.filter(pl.col("table") == "bulletins")["saison"].unique().to_list())
    statuts_metriques = statuts(dispo)

    total, ecartes, dernier = con.execute(
        "SELECT count(*), count(*) FILTER (NOT massif_coherent), "
        "max(jour_validite) FILTER (massif_coherent) FROM bulletins"
    ).fetchone()
    par_saison = con.execute(
        "SELECT saison, count(*), count(DISTINCT massif_id), "
        "string_agg(DISTINCT zone, ', ' ORDER BY zone) "
        "FROM bulletins WHERE massif_coherent GROUP BY 1 ORDER BY 1"
    ).fetchall()

    s: list[str] = []
    s.append("# Disponibilité des champs, saison par saison\n")
    s.append(
        "Document **généré** par `uv run bra audit` (tâche T2 de [`taches.md`](taches.md)). "
        "Ne pas l'éditer à la main : le relancer après tout `bra build`.\n\n"
        "Il répond à une question préalable à toute métrique de la "
        "[spec](spec-interface.md) : le champ dont elle dépend existe-t-il sur toute la "
        "période ? Le format XML a changé six fois, et plusieurs blocs sont propres à une "
        "époque.\n"
    )
    s.append("## Périmètre mesuré\n")
    s.append(
        f"- Dernier jour couvert intégré : **{dernier}**.\n"
        f"- {total - ecartes} bulletins mesurés (`bulletins` après déduplication, "
        f"`massif_coherent`). **{ecartes}** ligne(s) écartée(s) parce que leur `ID` et "
        "leur libellé se contredisent — voir `bra info`.\n"
        "- Les tables filles sont restreintes aux bulletins retenus, par leur clé.\n"
        "- Une part se lit en % des lignes de la table pour la saison, et ne compte que "
        "les valeurs **exploitables** : ni nulles, ni `-1` (sentinelle de la source), ni "
        "porteuses d'un autre sens que celui du champ (§ 9). `0` = jamais exploitable, "
        "`100` = toujours, `—` = table vide cette saison-là. Une part non "
        "nulle s'affiche au moins à 0,1 %, pour qu'une présence rare ne passe pas pour "
        "une absence.\n"
    )
    s.append(_md(["saison", "bulletins", "massifs", "zones"], par_saison) + "\n")

    s.append("## 1. Statut des métriques de la spec (§ 5)\n")
    s.append(
        "Le statut est **dérivé** de la disponibilité mesurée plus bas, pas écrit à la "
        "main : chaque métrique est déclarée une fois dans `audit.py` avec les champs "
        "qu'elle lit.\n\n"
        "- **calculable** : tous ses champs sont présents sur toutes les saisons ;\n"
        "- **sous-ensemble** : sur une partie des saisons seulement, listées ;\n"
        "- **non calculable** : aucune saison ne les réunit, ou la métrique attend un "
        "indice chiffré d'un champ texte.\n\n"
        "« Présent » veut dire au moins une valeur exploitable dans la saison : un champ "
        "rare par nature (`sat2`, `altitude_seuil_m`) n'est pas un champ absent. La "
        "densité se lit dans les matrices du § 2. *Calculable* ne veut pas dire "
        "*comparable* : les règles de fenêtre (`coeur`, saisons comparables) "
        "s'appliquent en plus.\n"
    )
    lignes_st = []
    for row in statuts_metriques.iter_rows(named=True):
        portee = row["saisons"] if row["statut"] == SOUS_ENSEMBLE else ""
        lignes_st.append((row["bloc"], row["metrique"], f"**{row['statut']}**",
                          _plages(portee.split(", "), saisons) if portee else "",
                          row["motif"]))
    s.append(_md(["bloc", "métrique", "statut", "saisons", "motif"], lignes_st) + "\n")

    s.append("## 2. Part de valeurs exploitables, champ × saison (%)\n")
    if SEMANTIQUE_DIVERGENTE:
        s.append(
            "Champs comptés à 0 sur une famille de format parce qu'ils y portent autre "
            "chose que ce que leur nom annonce :\n\n"
            + "\n".join(
                f"- `{t}.{c}` (famille `{fam}`) : {raison}."
                for (t, c), (fam, raison) in SEMANTIQUE_DIVERGENTE.items()
            )
            + "\n"
        )
    for table in _tables(con):
        s.append(f"### `{table}`\n")
        s.append(_matrice(dispo, table, saisons) + "\n")

    s.append("## 3. Localisation du risque : `loc_type`\n")
    s.append(
        "Décide du périmètre de la vue experte sur le second indice (spec § 3.1). "
        "`NULL` = indice unique, aucune information d'altitude.\n"
    )
    loc = con.execute(
        "SELECT saison, count(*), "
        "count(*) FILTER (loc_type IS NULL), count(*) FILTER (loc_type = 'altitude'), "
        "count(*) FILTER (loc_type = 'orientation') "
        "FROM bulletins WHERE massif_coherent GROUP BY 1 ORDER BY 1"
    ).fetchall()
    s.append(_md(
        ["saison", "bulletins", "NULL", "altitude", "orientation", "% avec distinction"],
        [(sa, n, a, b, c, _pct((b + c) / n)) for sa, n, a, b, c in loc],
    ) + "\n")
    seuils = con.execute(
        "SELECT altitude_seuil_m, count(*) FROM bulletins "
        "WHERE massif_coherent AND loc_type = 'altitude' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    s.append("Distribution de `altitude_seuil_m` quand `loc_type = 'altitude'` :\n")
    s.append(_md(["altitude_seuil_m", "bulletins"], seuils) + "\n")

    s.append("## 4. Altitudes de référence par massif\n")
    s.append(
        "Elles fondent les tranches normées ("
        + ", ".join(t.libelle for t in TRANCHES)
        + ", spec § 4.2 ; § 10 ci-dessous). "
        "Une ligne par jeu d'altitudes distinct ; les saisons qui le partagent sont "
        "regroupées. Sources : `enneigement.altitude_m` (paliers d'épaisseur), "
        "`neige_fraiche.altitude_mesure_m`, `bulletins.vent_altitude_basse_m` / "
        "`vent_altitude_haute_m`.\n"
    )
    alt = altitudes_reference(con)
    groupes = (
        alt.group_by("massif_id", "source", "altitudes", maintain_order=True)
        .agg(pl.col("saison"))
        .sort("massif_id", "source", "altitudes")
    )
    s.append(_md(
        ["massif", "nom", "source", "altitudes (m)", "saisons"],
        [(m, BY_ID[m].nom if m in BY_ID else "?", src, a, _plages(ss, saisons))
         for m, src, a, ss in groupes.iter_rows()],
    ) + "\n")

    s.append("## 5. Couverture de la table `enneigement`\n")
    s.append(
        "Part des bulletins qui portent au moins un relevé d'épaisseur. Décide si la v1 "
        "tient sans SAFRAN (spec § 3.3).\n"
    )
    enn = con.execute(
        f"""
        SELECT b.saison, count(*),
               count(*) FILTER (e.n_jour > 0), count(*) FILTER (e.n_hist > 0)
        FROM ({_source('bulletins')}) b
        LEFT JOIN (
          SELECT massif_id, date_bulletin,
                 count(*) FILTER (origine = 'jour') AS n_jour,
                 count(*) FILTER (origine = 'historique') AS n_hist
          FROM enneigement GROUP BY 1, 2
        ) e USING (massif_id, date_bulletin)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    s.append(_md(
        ["saison", "bulletins", "% avec relevé du jour", "% avec historique"],
        [(sa, n, _pct(j / n), _pct(h / n)) for sa, n, j, h in enn],
    ) + "\n")

    s.append("## 6. Situations avalancheuses typiques : `sat1` / `sat2`\n")
    # Les saisons ou `sat1` existe se lisent dans la mesure, pas dans une
    # annee recopiee : si la source l'etendait a d'autres saisons, la table
    # suivrait.
    saisons_sat = sorted(
        dispo.filter((pl.col("table") == "bulletins") & (pl.col("champ") == "sat1")
                     & (pl.col("non_nulles") > 0))["saison"].to_list()
    )
    sat = con.execute(
        "SELECT saison, count(*), count(sat1), count(sat2) FROM bulletins "
        "WHERE massif_coherent AND list_contains(?, saison) GROUP BY 1 ORDER BY 1",
        [saisons_sat],
    ).fetchall()
    s.append(_md(
        ["saison", "bulletins", "% sat1", "% sat2"],
        [(sa, n, _pct(a / n), _pct(b / n)) for sa, n, a, b in sat],
    ) + "\n")
    codes = con.execute(
        "SELECT code, count(*) FILTER (rang = 1), count(*) FILTER (rang = 2) FROM ("
        "  SELECT sat1 AS code, 1 AS rang FROM bulletins WHERE massif_coherent AND sat1 IS NOT NULL"
        "  UNION ALL"
        "  SELECT sat2, 2 FROM bulletins WHERE massif_coherent AND sat2 IS NOT NULL"
        ") GROUP BY 1 ORDER BY 1"
    ).fetchall()
    s.append("Répartition des codes, toutes saisons (libellés inférés : glossaire § 2.7) :\n")
    s.append(_md(["code", "sat1", "sat2"], codes) + "\n")

    s.append("## 7. Distributions pour les seuils encore ouverts\n")
    s.append(
        "Base des valeurs par défaut de vent fort, d'épisode de chute et de redoux "
        "(spec § 3.3). Quantiles **discrets** : chaque valeur a été écrite dans un "
        "bulletin. La sentinelle `-1` est écartée (§ 9) : `n` compte les valeurs "
        "exploitables. Prévision météo à toutes échéances confondues ; neige fraîche sur "
        "l'historique, non dédupliquée (un même jour figure dans plusieurs bulletins), "
        "et sur la seule famille `moderne` : avant 2024 la colonne est le plus fort "
        "de un ou deux secteurs, pas la borne d'une fourchette (rupture de série, "
        "§ 9).\n"
    )
    s.append(_md(
        ["champ", "lignes retenues", "unité", "n", "p50", "p75", "p90", "p95", "p99", "max"],
        _quantiles(con),
    ) + "\n")

    s.append("## 8. Bloc météo selon `origine` (spec § 4.3)\n")
    s.append(
        "La convention d'extraction préfère l'historique (analyse) à la prévision pour un "
        "même jour. Elle n'est tenable que pour les champs que l'historique porte.\n"
    )
    parts_meteo = meteo_par_origine(con)
    champs_m = parts_meteo["champ"].unique(maintain_order=True).to_list()
    parts = {(sa, o, c): p for sa, o, c, _, p in parts_meteo.iter_rows()}
    lignes_m = []
    for sa in saisons:
        for o in ("prevision", "historique"):
            if any((sa, o, c) in parts for c in champs_m):
                lignes_m.append((sa, o, *(_pct(parts.get((sa, o, c))) for c in champs_m)))
    s.append(_md(["saison", "origine", *[f"`{c}`" for c in champs_m]], lignes_m) + "\n")
    ecarts = ecarts_meteo(con)
    if ecarts.height:
        s.append(
            "Champs que l'historique porte moins de "
            f"{_pct(DENSITE_HISTORIQUE_MIN)} % aussi souvent que la prévision — la "
            "convention ne tient pas pour eux :\n"
        )
        s.append(_md(
            ["saison", "champ", "% prévision", "% historique"],
            [(sa, f"`{c}`", _pct(pp), _pct(ph)) for sa, c, pp, ph in ecarts.rows()],
        ) + "\n")
    else:
        s.append(
            "Tout champ porté par la prévision l'est au moins à "
            f"{_pct(DENSITE_HISTORIQUE_MIN)} % aussi souvent par l'historique.\n"
        )
    s.append(
        "> **Limite de la mesure.** `-1` vaut « sans objet » pour `PLUIENEIGE` (temps sec) "
        "et `MERNUAGES` (pas de mer de nuages), et le parser le convertit en nul. Pour "
        "ces deux champs, l'entrepôt ne distingue donc pas un attribut absent d'une "
        "valeur sans objet : une part basse y décrit la météo autant que le format. "
        "Depuis 2024, `MERNUAGES` figure dans la prévision et plus dans le bloc `BSH` : "
        "l'écart ressort ci-dessus grâce aux rares jours où la prévision annonce une mer "
        "de nuages, mais il est invisible bulletin par bulletin quand elle dit `-1`.\n"
    )

    s.append("## 9. Sentinelles `-1` restées dans l'entrepôt\n")
    s.append(
        "Le parser convertit en nul le `-1` des indices, des paliers et limites "
        "d'enneigement, de la météo et de la neige fraîche (glossaire § 3 à 5 ; "
        "`bra check` compte chaque conversion). Là où il subsiste, il reste une "
        "valeur, et une somme ou une moyenne le compte. Nombre de `-1` par champ et "
        "par saison (lignes `massif_coherent`) :\n"
    )
    sent = sentinelles(con)
    if sent.height:
        cles = sent.select("table", "champ").unique(maintain_order=True).rows()
        sentinelles_par = {(t, c, sa): n for t, c, sa, _, n in sent.iter_rows()}
        s.append(_md(
            ["champ", *saisons],
            [(f"`{t}.{c}`", *(sentinelles_par.get((t, c, sa), 0) for sa in saisons))
             for t, c in cles],
        ) + "\n")
    else:
        s.append("Aucun `-1` résiduel.\n")
    nf = con.execute(
        f"""
        SELECT format_famille, count(*),
               count(*) FILTER (secteur1_libelle IS NOT NULL AND secteur2_libelle IS NULL),
               count(*) FILTER (secteur2_libelle IS NOT NULL),
               count(*) FILTER (
                 (secteur1_libelle IS NOT NULL AND secteur1_cumul_cm IS NULL)
                 OR (secteur2_libelle IS NOT NULL AND secteur2_cumul_cm IS NULL)),
               count(*) FILTER (cumul_max_cm IS NULL)
        FROM ({_source('neige_fraiche')}) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    s.append(
        "### `neige_fraiche` : deux lectures, une rupture de série à l'hiver 2023-2024\n\n"
        "Jusqu'en 2023, `NEIGEFRAICHE` nomme un ou deux secteurs (`SECTEURSS1` / "
        "`SECTEURSS2` : `massif` seul, ou `Nord` / `Sud`, `Ouest` / `Est`…) et `SS241` / "
        "`SS242` sont le cumul de chacun. Le parser conserve les secteurs "
        "(`secteur1_*`, `secteur2_*`) et en dérive `cumul_min_cm` / `cumul_max_cm` ; "
        "depuis 2024, `SS24Min` / `SS24Max` sont une fourchette sur le massif. Une "
        "valeur négative n'est pas un cumul : `-1` signale l'absence de second "
        "secteur, `-2` une valeur non observée (*inféré* : aucun descriptif de "
        "l'ancien format). Les deux deviennent nulles.\n"
    )
    s.append(_md(
        ["famille", "lignes", "un secteur", "deux secteurs",
         "secteur non observé", "`cumul_max_cm` nul"], nf
    ) + "\n")

    if "palier_tranche" in {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}:
        s.append(_section_tranches(con, saisons))
    return "\n".join(s)


def _section_tranches(con: duckdb.DuckDBPyConnection, saisons: list[str]) -> str:
    """§ 10 : ce que les tranches normees permettent de comparer (T5)."""
    from .tranches import HAUTE, MOYENNE, TRANCHES

    s = ["## 10. Tranches d'altitude normées (vue `palier_tranche`)\n"]
    s.append(
        "Bornes fermées à gauche, définies une fois dans `tranches.py` : "
        + ", ".join(f"**{t.nom}** {t.libelle}" for t in TRANCHES)
        + f". Les paliers de l'archive tombent pile sur {MOYENNE.min_m} et {HAUTE.min_m} m : "
        "fermées à gauche, "
        "les deux époques de paliers d'enneigement (1500/1800/2400 puis 1500/2000/2500) "
        "donnent chacune un palier par tranche. Une altitude `-1` n'entre dans aucune "
        "tranche.\n"
    )
    conc = concentration_tranches(con)
    resume = (
        conc.group_by("source", "saison")
        .agg(couples=pl.len(), une_seule=(pl.col("n_tranches") == 1).sum())
        .sort("source", "saison")
    )
    s.append(
        "### Couples massif × saison dont tous les paliers tombent dans une seule tranche\n\n"
        "Pour ces couples, la comparaison entre massifs n'a de sens que sur la tranche "
        "occupée ; sur les deux autres il n'y a rien à comparer. Neige fraîche et vent "
        "ont **une** altitude de référence par bulletin : une seule tranche par "
        "construction, sauf changement d'altitude en cours de saison.\n"
    )
    srcs = resume["source"].unique(maintain_order=True).to_list()
    # (source, saison) -> (couples massif x saison, dont a tranche unique)
    comptes = {(src, sa): (n, u) for src, sa, n, u in resume.iter_rows()}
    lignes = []
    for src in srcs:
        presents = [comptes[(src, sa)] for sa in saisons if (src, sa) in comptes]
        total_couples = sum(n for n, _ in presents)
        total_uniques = sum(u for _, u in presents)
        cells = [
            f"{comptes[(src, sa)][1]}/{comptes[(src, sa)][0]}" if (src, sa) in comptes else None
            for sa in saisons
        ]
        part = _pct(total_uniques / total_couples) if total_couples else "—"
        lignes.append((src, *cells, f"{part} %"))
    s.append(_md(["source", *saisons, "part"], lignes) + "\n")

    couverts = _frame(
        con,
        "SELECT source, tranche, saison, count(DISTINCT massif_id) AS massifs "
        "FROM palier_tranche WHERE massif_coherent AND tranche IS NOT NULL "
        "GROUP BY ALL",
    )
    massifs_par = {(src, tr, sa): m for src, tr, sa, m in couverts.iter_rows()}
    s.append(
        "### Massifs disposant d'au moins un palier, par tranche\n\n"
        "Une case vide est une tranche sans aucune donnée pour cette source et cette "
        "saison : aucune valeur n'y est interpolée.\n"
    )
    s.append(_md(
        ["source", "tranche", *saisons],
        [(src, t.nom, *(massifs_par.get((src, t.nom, sa)) for sa in saisons))
         for src in srcs for t in TRANCHES],
    ) + "\n")
    return "\n".join(s)


def sentinelles(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Valeurs `-1` restees dans les colonnes numeriques, par table et saison.

    Garde-fou : le parser convertit les sentinelles dont le sens est etabli ;
    un `-1` qui reapparait ici est une regle a ecrire. Seules les lignes non
    nulles sont rendues.
    Colonnes : `table`, `champ`, `saison`, `lignes`, `sentinelles`.
    """
    morceaux = []
    for table in _tables(con):
        champs = [
            c for c, t in schema.TABLES[table].items()
            if t in _ENTIERS and c not in _HORS_AUDIT
        ]
        if not champs:
            continue
        comptes = ", ".join(f'count(*) FILTER ("{c}" = -1) AS "{c}"' for c in champs)
        large = _frame(
            con,
            f"SELECT saison, count(*) AS lignes, {comptes} "
            f"FROM ({_source(table)}) GROUP BY saison",
        )
        morceaux.append(
            large.unpivot(index=["saison", "lignes"], variable_name="champ",
                          value_name="sentinelles")
            .with_columns(table=pl.lit(table))
        )
    if not morceaux:
        return pl.DataFrame(schema={"table": pl.Utf8, "champ": pl.Utf8, "saison": pl.Utf8,
                                    "lignes": pl.Int64, "sentinelles": pl.Int64})
    return (
        pl.concat(morceaux)
        .filter(pl.col("sentinelles") > 0)
        .select("table", "champ", "saison", "lignes", "sentinelles")
        .sort("table", "champ", "saison")
    )


def concentration_tranches(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Tranches normees couvertes par les paliers de chaque massif et saison.

    Spec section 4.2 : si les altitudes de reference d'un massif tombent toutes dans
    une tranche, la comparaison entre massifs sur les autres tranches n'a pas
    de sens. Colonnes : `source`, `massif_id`, `saison`, `altitudes`,
    `tranches` (dans l'ordre basse -> haute), `n_tranches`. Les altitudes
    sentinelles (sans tranche) sont exclues du compte.
    """
    from .tranches import TRANCHES

    ordre = " ".join(f"WHEN '{t.nom}' THEN {i}" for i, t in enumerate(TRANCHES))
    return _frame(
        con,
        f"""
        SELECT source, massif_id, saison,
               array_to_string(list_sort(list_distinct(list(altitude_m))), '/') AS altitudes,
               array_to_string(
                 list_transform(
                   list_sort(list_distinct(list(CASE tranche {ordre} END))),
                   i -> ['{"', '".join(t.nom for t in TRANCHES)}'][i + 1]
                 ), ', ') AS tranches,
               count(DISTINCT tranche) AS n_tranches
        FROM palier_tranche
        WHERE massif_coherent AND tranche IS NOT NULL
        GROUP BY ALL
        ORDER BY source, massif_id, saison
        """,
    )
