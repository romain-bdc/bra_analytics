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


def disponibilite(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Part de valeurs non nulles, par table, champ et saison.

    Colonnes : `table`, `champ`, `saison`, `lignes`, `non_nulles`, `part`
    (arrondie a 4 decimales pour que le rapport soit reproductible).
    """
    morceaux = []
    for table in _tables(con):
        champs = [c for c in schema.TABLES[table] if c not in _HORS_AUDIT]
        comptes = ", ".join(f'count("{c}") AS "{c}"' for c in champs)
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
# Metriques de la spec (§ 5) et champs dont elles dependent
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
    # Prevue au cadrage, ecartee par la spec § 5.1 : on la garde ici pour que
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
    non nulle. Le seuil est volontairement bas : un champ rare par nature
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

# Altitudes de reference par source. Elles fondent les tranches normees de la
# spec § 4.2 : si celles d'un massif tombent toutes dans une tranche, la
# comparaison entre massifs sur cette tranche n'a pas de sens.
_ALTITUDES = {
    "enneigement": f"SELECT saison, massif_id, altitude_m AS alt FROM ({_source('enneigement')})",
    "neige_fraiche": (
        f"SELECT saison, massif_id, altitude_mesure_m AS alt FROM ({_source('neige_fraiche')})"
    ),
    "vent_bas": f"SELECT saison, massif_id, vent_altitude_basse_m AS alt FROM ({_source('bulletins')})",
    "vent_haut": f"SELECT saison, massif_id, vent_altitude_haute_m AS alt FROM ({_source('bulletins')})",
}


def altitudes_reference(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Altitudes distinctes par massif, saison et source.

    Colonnes : `massif_id`, `saison`, `source`, `altitudes` (valeurs triees,
    jointes par `/`), `lignes` (lignes non nulles mesurees).
    """
    requetes = "\nUNION ALL\n".join(
        f"SELECT '{nom}' AS source, * FROM ({sql})" for nom, sql in _ALTITUDES.items()
    )
    return _frame(
        con,
        f"""
        SELECT massif_id, saison, source,
               -- tri numerique : un tri texte placerait 900 apres 1500
               array_to_string(list_sort(list_distinct(list(alt))), '/') AS altitudes,
               count(*) AS lignes
        FROM ({requetes})
        WHERE alt IS NOT NULL
        GROUP BY ALL
        ORDER BY massif_id, saison, source
        """,
    )


def meteo_par_origine(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Part non nulle de chaque champ meteo, par saison et `origine`.

    Colonnes : `saison`, `origine`, `champ`, `lignes`, `part`.
    """
    champs = [c for c in schema.METEO if c not in _HORS_AUDIT | {"origine", "rang", "echeance"}]
    comptes = ", ".join(f'count("{c}") AS "{c}"' for c in champs)
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


def ecarts_meteo(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Champs renseignes en prevision mais jamais dans l'historique, par saison.

    La convention d'extraction (spec § 4.3) prefere l'historique a la
    prevision pour un meme jour : elle n'est tenable que pour les champs que
    l'historique porte effectivement. Colonnes : `saison`, `champ`.
    """
    parts = meteo_par_origine(con)
    prev = parts.filter((pl.col("origine") == "prevision") & (pl.col("part") > 0))
    hist = parts.filter((pl.col("origine") == "historique") & (pl.col("part") > 0))
    return (
        prev.join(hist, on=["saison", "champ"], how="anti")
        .select("saison", "champ")
        .sort("saison", "champ")
    )


def _quantiles(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Distributions des champs dont les seuils par defaut restent a fixer.

    `quantile_disc` plutot que `quantile_cont` : les valeurs sont entieres, et
    un quantile interpole (37,5 km/h) n'a jamais ete ecrit dans un bulletin.
    """
    # `cumul_max_cm` n'est un maximum que depuis 2024 : avant, `SS242` porte le
    # cumul d'un second secteur, `-1` quand il n'y en a pas (voir § 9 du
    # rapport). Sa distribution ne se lit donc que sur la famille moderne.
    series = (
        ("vent_haut_vitesse_kmh", "meteo", "prevision", "origine = 'prevision'", "km/h"),
        ("vent_bas_vitesse_kmh", "meteo", "prevision", "origine = 'prevision'", "km/h"),
        ("iso_0_m", "meteo", "prevision", "origine = 'prevision'", "m"),
        ("cumul_max_cm", "neige_fraiche", "historique, moderne",
         "origine = 'historique' AND format_famille = 'moderne'", "cm"),
    )
    lignes = []
    for champ, table, libelle, filtre, unite in series:
        n, q = con.execute(
            f"SELECT count({champ}), quantile_disc({champ}, [0.5, 0.75, 0.9, 0.95, 0.99, 1.0]) "
            f"FROM ({_source(table)}) WHERE {filtre} AND {champ} IS NOT NULL"
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
    """`2016-2017 → 2019-2020, 2022-2023` : runs contigus dans l'ordre des saisons."""
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

    dispo = disponibilite(con)
    saisons = sorted(dispo.filter(pl.col("table") == "bulletins")["saison"].unique().to_list())
    st = statuts(dispo)

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
        "- Une part se lit en % des lignes de la table pour la saison : `0` = jamais "
        "renseigné, `100` = toujours, `—` = table vide cette saison-là. Une part non "
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
        "« Présent » veut dire au moins une valeur non nulle dans la saison : un champ "
        "rare par nature (`sat2`, `altitude_seuil_m`) n'est pas un champ absent. La "
        "densité se lit dans les matrices du § 2. *Calculable* ne veut pas dire "
        "*comparable* : les règles de fenêtre (`coeur`, saisons comparables) "
        "s'appliquent en plus.\n"
    )
    lignes_st = []
    for row in st.iter_rows(named=True):
        portee = row["saisons"] if row["statut"] == SOUS_ENSEMBLE else ""
        lignes_st.append((row["bloc"], row["metrique"], f"**{row['statut']}**",
                          _plages(portee.split(", "), saisons) if portee else "",
                          row["motif"]))
    s.append(_md(["bloc", "métrique", "statut", "saisons", "motif"], lignes_st) + "\n")

    s.append("## 2. Part de valeurs non nulles, champ × saison (%)\n")
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
        "Elles fondent les tranches normées (< 1800 m, 1800–2400 m, > 2400 m, spec § 4.2). "
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
    sat = con.execute(
        "SELECT saison, count(*), count(sat1), count(sat2) FROM bulletins "
        "WHERE massif_coherent AND saison_debut >= 2023 GROUP BY 1 ORDER BY 1"
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
        "bulletin. Prévision météo à toutes échéances confondues ; neige fraîche sur "
        "l'historique, non dédupliquée (un même jour figure dans plusieurs bulletins), "
        "et sur la seule famille `moderne` : avant 2024 la colonne n'est pas un "
        "maximum (§ 9).\n"
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
    mpo = meteo_par_origine(con)
    champs_m = mpo["champ"].unique(maintain_order=True).to_list()
    parts = {(sa, o, c): p for sa, o, c, _, p in mpo.iter_rows()}
    lignes_m = []
    for sa in saisons:
        for o in ("prevision", "historique"):
            if any((sa, o, c) in parts for c in champs_m):
                lignes_m.append((sa, o, *(_pct(parts.get((sa, o, c))) for c in champs_m)))
    s.append(_md(["saison", "origine", *[f"`{c}`" for c in champs_m]], lignes_m) + "\n")
    ecarts = ecarts_meteo(con)
    if ecarts.height:
        s.append("Champs renseignés en prévision mais **jamais** dans l'historique :\n")
        s.append(_md(["saison", "champ"], ecarts.rows()) + "\n")
    else:
        s.append("Aucun champ renseigné en prévision n'est absent de l'historique.\n")
    s.append(
        "> **Limite de la mesure.** `-1` vaut « sans objet » pour `PLUIENEIGE` (temps sec) "
        "et `MERNUAGES` (pas de mer de nuages), et le parser le convertit en nul. Pour "
        "ces deux champs, l'entrepôt ne distingue donc pas un attribut absent d'une "
        "valeur sans objet : une part basse y décrit la météo autant que le format. "
        "Le XML 2024 en donne un cas : `MERNUAGES` figure dans la prévision et plus "
        "dans le bloc `BSH`, sans que l'écart soit visible ici quand la prévision dit "
        "`-1`.\n"
    )

    s.append("## 9. Sentinelles `-1` restées dans l'entrepôt\n")
    s.append(
        "La pipeline ne convertit en nul que le `-1` de `RISQUE1`, `PLUIENEIGE` et "
        "`MERNUAGES`. Ailleurs il reste une valeur, et une somme ou une moyenne le "
        "compte. Nombre de `-1` par champ et par saison (lignes `massif_coherent`) :\n"
    )
    sent = sentinelles(con)
    if sent.height:
        cles = sent.select("table", "champ").unique(maintain_order=True).rows()
        n_par = {(t, c, sa): n for t, c, sa, _, n in sent.iter_rows()}
        s.append(_md(
            ["champ", *saisons],
            [(f"`{t}.{c}`", *(n_par.get((t, c, sa), 0) for sa in saisons)) for t, c in cles],
        ) + "\n")
    else:
        s.append("Aucun `-1` résiduel.\n")
    nf = con.execute(
        f"""
        SELECT format_famille, count(*),
               count(*) FILTER (cumul_max_cm = -1),
               count(*) FILTER (cumul_max_cm < cumul_min_cm)
        FROM ({_source('neige_fraiche')}) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    s.append(
        "### `neige_fraiche` : `SS241` / `SS242` ne sont pas un minimum et un maximum\n\n"
        "Le glossaire (§ 5) et le parser tiennent `SS241`/`SS242` (≤ 2023) pour les "
        "ancêtres de `SS24Min`/`SS24Max` (≥ 2024). Les données le contredisent :\n"
    )
    s.append(_md(
        ["famille", "lignes", "`cumul_max_cm = -1`", "`cumul_max_cm < cumul_min_cm`"], nf
    ) + "\n")
    s.append(
        "Le XML legacy porte sur `NEIGEFRAICHE` deux attributs `SECTEURSS1` / "
        "`SECTEURSS2` (`massif` / vide, `Ouest` / `Est`, `Nord` / `Sud`…) : `SS241` et "
        "`SS242` y sont **les cumuls de deux secteurs**, et `SS242=-1` signifie « pas de "
        "second secteur ». *Inféré* de la structure du fichier ; aucun descriptif ne "
        "documente l'ancien format. Conséquence : avant 2024, `cumul_max_cm` n'est pas "
        "un maximum, et toute métrique de neige fraîche (spec § 5.2) doit attendre "
        "qu'une règle de parsing soit arrêtée.\n"
    )
    return "\n".join(s)


_ENTIERS = (pl.Int8, pl.Int16, pl.Int32, pl.Int64)


def sentinelles(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Valeurs `-1` restees dans les colonnes numeriques, par table et saison.

    La pipeline convertit en nul le `-1` de `RISQUE1`, `PLUIENEIGE` et
    `MERNUAGES`. Ailleurs il passe tel quel, et une somme ou une moyenne le
    compte comme une valeur. Seules les lignes non nulles sont rendues.
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
