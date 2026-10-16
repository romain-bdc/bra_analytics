"""Fiche massif-saison (spec section 6, T11).

Meme motif que `dashboard.py` et `carte.py` : un payload JSON construit ici,
insere dans `templates/fiche.html` par le marqueur `__DONNEES__`, tout le
filtrage cote client. Aucun framework, aucune donnee chargee du reseau : seules les
polices viennent de Google Fonts, comme dans `dashboard.html` et `carte.html`, avec repli
sur les polices systeme hors ligne.

Rien n'est recalcule ici : les series viennent des vues de `metriques/`
(`serie_jour`, `paliers`, `vent_tranche_jour`), les indicateurs de leurs
`metriques_saison`. Seule la bande mediane / interquartile est calculee dans ce
module, parce qu'aucune metrique ne porte les quartiles ; elle reprend la
population de la normale de T6 (fenetre `coeur`, saisons comparables, indice
non nul, au moins `MIN_SAISONS_NORMALE` saisons) et un test verifie que sa
mediane egale `risque_jour.normale`.

Encodage : une serie par massif et par saison, ancree sur `origine`, le plus
ancien des jours de tous les blocs. L'axe `jour_de_saison` se lit depuis le
premier jour du *risque* (glossaire : le rang se compte massif par massif),
d'ou `decalage_rang`. Les bornes de fenetre ne sont pas recopiees : elles
voyagent dans le payload depuis `fenetres.py`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import polars as pl

from .dashboard import ABSENT, SANS_INDICE, injecter
from .fenetres import DEFAUT, FENETRES, SAISON_COMPLETE, SAISONS_NON_COMPARABLES, comparable
from .massifs import MASSIFS
from .metriques import enneigement, meteo, risque
from .tranches import TRANCHES

TEMPLATE = Path(__file__).parent / "templates" / "fiche.html"

# Annee bissextile de reference pour l'axe calendaire : le 29 fevrier y a sa case.
# Dans une saison non bissextile cette case n'existe pas et le trace la saute ;
# la supprimer de l'axe ferait perdre le 29 fevrier des saisons qui l'ont.
_REF_BISSEXTILE = 2024
# La diffusion commence le 21 octobre au plus tot et s'arrete le 15 juin au plus
# tard (docs/exploration.md) : l'axe va du 1er octobre au 30 juin.
_AXE_DEBUT = (10, 1)
_AXE_FIN = (6, 30)

VERSANTS = enneigement.VERSANTS

# Fenetres offertes aux indicateurs : `coeur` pour ce qui se compare, la saison
# entiere pour la lecture isolee. `commune` mesure ce que l'archive contient
# (dashboard.py) et n'a pas d'usage ici ; la laisser doublerait le poids des
# indicateurs pour une fenetre que la fiche n'offre pas.
FENETRES_FICHE = (DEFAUT.nom, SAISON_COMPLETE)


def axe_calendaire() -> list[str]:
    """Cases `mm-jj` de l'axe calendaire, du 1er octobre au 30 juin, 29 fevrier compris."""
    jour = date(_REF_BISSEXTILE - 1, *_AXE_DEBUT)
    fin = date(_REF_BISSEXTILE, *_AXE_FIN)
    axe = []
    while jour <= fin:
        axe.append(jour.strftime("%m-%d"))
        jour += timedelta(days=1)
    return axe


def _chaine(valeurs: dict[date, int | float | None], origine: date, longueur: int) -> str:
    """Serie numerique en une chaine `12,,13` : valeur vide = jour sans valeur.

    Un `null` JSON pese quatre caracteres par jour sans valeur ; la chaine vide
    n'en pese aucun, et ces series sont creuses (le vent haut a 3000 m, par
    exemple, manque sur une partie des saisons).
    """
    out = []
    for i in range(longueur):
        v = valeurs.get(origine + timedelta(days=i))
        out.append("" if v is None else str(int(round(v))))
    return ",".join(out)


def _bandes(serie: pl.DataFrame, cle: str) -> pl.DataFrame:
    """Mediane et quartiles de `risque_maxi` par case, sur la population de la normale de T6.

    `cle` est la colonne qui indexe la case (`jour_annee` pour l'axe
    calendaire, `jour_de_saison` pour l'axe par rang). Une case sous
    `MIN_SAISONS_NORMALE` saisons reste vide : pas de bande plutot qu'une bande
    sur deux saisons. Les quartiles sont ceux de l'ordinal -- le niveau observe
    de rang inferieur pour Q1, de rang superieur pour Q3 -- et non une
    interpolation entre deux niveaux qui n'existe pas.
    """
    pop = serie.filter(
        pl.col(f"fenetre_{DEFAUT.nom}") & pl.col("saison_comparable") & pl.col("risque_maxi").is_not_null()
    )
    return (
        pop.group_by(["massif_id", cle])
        .agg(
            pl.col("saison").n_unique().alias("saisons"),
            pl.col("risque_maxi").quantile(0.25, "lower").alias("q1"),
            pl.col("risque_maxi").median().alias("mediane"),
            pl.col("risque_maxi").quantile(0.75, "higher").alias("q3"),
        )
        .filter(pl.col("saisons") >= risque.MIN_SAISONS_NORMALE)
    )


def _tableau(bandes: pl.DataFrame, cle: str, cases: list) -> dict[int, dict]:
    """Une bande par massif : trois listes alignees sur `cases`, `None` hors population."""
    out: dict[int, dict] = {}
    for (massif_id,), g in bandes.group_by(["massif_id"]):
        index = {r[cle]: r for r in g.iter_rows(named=True)}
        out[int(massif_id)] = {
            champ: [
                (None if (r := index.get(c)) is None else (r[champ] if champ == "mediane" else int(r[champ])))
                for c in cases
            ]
            for champ in ("q1", "mediane", "q3")
        }
    return out


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _lignes(df: pl.DataFrame, champs: tuple[str, ...]) -> dict[tuple, dict]:
    """Indexe un DataFrame metrique par (massif, saison[, tranche]) en ne gardant que `champs`."""
    # Une colonne renommee par une metrique doit casser ici, pas disparaitre de la page.
    manquantes = [c for c in champs if c not in df.columns]
    if manquantes:
        raise ValueError(f"colonnes absentes de la metrique : {manquantes}")
    cles = [c for c in ("massif_id", "saison", "tranche", "versant") if c in df.columns]
    return {
        tuple(r[c] for c in cles): {c: _iso(r[c]) for c in champs}
        for r in df.iter_rows(named=True)
    }


CHAMPS_RISQUE = (
    "comparable", "motif_exclusion", "jours_couverts", "jours_periode", "jours_avec_indice",
    "jours_sans_indice", "jours_non_estimes", "risque_moyen", "risque_median", "risque_max", "date_max",
    "jours_au_max", "jours_3_plus", "jours_4_plus", "jours_5", "episodes", "plus_long_episode",
    "couverture_pct",
)
CHAMPS_NEIGE = (
    "jours_observes_nord", "jours_enneiges_nord", "epaisseur_max_nord_cm", "date_max_nord",
    "jours_observes_sud", "jours_enneiges_sud", "epaisseur_max_sud_cm", "date_max_sud",
    "altitude_max_m",
)
CHAMPS_METEO = (
    "jours_avec_iso0", "iso0_min_m", "date_iso0_min", "iso0_max_m", "date_iso0_max", "iso0_moyen_m",
    "jours_iso0_au_dessus_seuil", "seuil_iso0_m", "episodes_redoux", "jours_en_redoux", "plus_long_redoux",
)
CHAMPS_VENT = ("jours_avec_vent", "jours_vent_fort", "vitesse_max_kmh", "vitesse_mediane_kmh", "altitudes_vent")
CHAMPS_CONTINU = ("seuil_limite_m", "debut_enneigement_continu", "fin_enneigement_continu", "duree_jours", "jours_observes")


def _indicateurs(con: duckdb.DuckDBPyConnection) -> dict:
    """massif -> saison -> fenetre -> blocs d'indicateurs, tels que les metriques les publient."""
    out: dict[int, dict[str, dict]] = {}

    def place(massif_id: int, saison: str, *chemin: str, valeur) -> None:
        d = out.setdefault(int(massif_id), {}).setdefault(saison, {})
        for k in chemin[:-1]:
            d = d.setdefault(k, {})
        d[chemin[-1]] = valeur

    for fen in FENETRES_FICHE:
        for (mid, saison), v in _lignes(risque.metriques_saison(con, fenetre=fen), CHAMPS_RISQUE).items():
            place(mid, saison, fen, "risque", valeur=v)
        for (mid, saison, tranche), v in _lignes(enneigement.metriques_saison(con, fenetre=fen), CHAMPS_NEIGE).items():
            place(mid, saison, fen, "neige", tranche, valeur=v)
        for (mid, saison), v in _lignes(meteo.metriques_saison(con, fenetre=fen), CHAMPS_METEO).items():
            place(mid, saison, fen, "meteo", valeur=v)
        for (mid, saison, tranche), v in _lignes(meteo.vent_saison(con, fenetre=fen), CHAMPS_VENT).items():
            place(mid, saison, fen, "vent", tranche, valeur=v)
    # La periode d'enneigement continu se lit sur la saison entiere, pas sur une fenetre.
    for (mid, saison, versant), v in _lignes(enneigement.enneigement_continu(con), CHAMPS_CONTINU).items():
        place(mid, saison, "continu", versant, valeur=v)
    return out


def _series(con: duckdb.DuckDBPyConnection) -> tuple[dict[int, dict[str, dict]], pl.DataFrame]:
    """massif -> saison -> series encodees, plus la serie de risque (pour les bandes)."""
    jours = risque.serie_jour(con)
    snow = enneigement.paliers(con).filter(pl.col("palier_retenu") & pl.col("tranche").is_not_null())
    iso0 = meteo.serie_jour(con)
    vent = meteo.vent_tranche_jour(con)

    # Premier et dernier jour de chaque bloc, par massif et saison.
    def etendue(df: pl.DataFrame, col: str) -> pl.DataFrame:
        return df.group_by(["massif_id", "saison"]).agg(
            pl.col(col).min().alias("d0"), pl.col(col).max().alias("d1")
        )

    etendues = pl.concat(
        [
            etendue(jours, "jour_validite"),
            etendue(snow, "jour"),
            etendue(iso0, "jour_validite"),
            etendue(vent, "jour_validite"),
        ]
    ).group_by(["massif_id", "saison"]).agg(pl.col("d0").min(), pl.col("d1").max())
    bornes = {(r["massif_id"], r["saison"]): (r["d0"], r["d1"]) for r in etendues.iter_rows(named=True)}

    out: dict[int, dict[str, dict]] = {}

    def entree(mid: int, saison: str) -> dict:
        d0, d1 = bornes[(mid, saison)]
        return out.setdefault(int(mid), {}).setdefault(
            saison, {"origine": d0, "longueur": (d1 - d0).days + 1}
        )

    for (mid, saison), g in jours.group_by(["massif_id", "saison"]):
        e = entree(mid, saison)
        premier = g["jour_validite"].min()
        grille = [ABSENT] * e["longueur"]
        for jour, r in zip(g["jour_validite"], g["risque_maxi"]):
            grille[(jour - e["origine"]).days] = SANS_INDICE if r is None else str(r)
        e["risque"] = "".join(grille)
        # jour_de_saison = 1 au premier jour du risque : la case d'indice `decalage_rang` du bloc.
        e["decalage_rang"] = (premier - e["origine"]).days

    for (mid, saison, tranche), g in snow.group_by(["massif_id", "saison", "tranche"]):
        e = entree(mid, saison)
        for versant in VERSANTS:
            e.setdefault("neige", {}).setdefault(tranche, {})[versant] = _chaine(
                dict(zip(g["jour"], g[f"epaisseur_{versant}_cm"])), e["origine"], e["longueur"]
            )
        # Altitude du palier lu : elle change d'epoque en epoque (2100 puis 2000 m en moyenne).
        e.setdefault("altitudes_neige", {})[tranche] = sorted(set(g["altitude_m"]))

    for (mid, saison), g in iso0.group_by(["massif_id", "saison"]):
        e = entree(mid, saison)
        e["iso0"] = {
            nom: _chaine(dict(zip(g["jour_validite"], g[col])), e["origine"], e["longueur"])
            for nom, col in (("min", "iso0_min_m"), ("max", "iso0_max_m"), ("moyen", "iso0_moyen_m"))
        }

    for (mid, saison, tranche), g in vent.group_by(["massif_id", "saison", "tranche"]):
        e = entree(mid, saison)
        e.setdefault("vent", {})[tranche] = _chaine(
            dict(zip(g["jour_validite"], g["vitesse_kmh"])), e["origine"], e["longueur"]
        )
        e.setdefault("altitudes_vent", {})[tranche] = sorted(
            {a for a in g["altitudes_vent"] if a is not None}
        )

    return out, jours


def payload(db_path: str | Path = "warehouse/bra.duckdb") -> dict:
    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    con = duckdb.connect(str(db), read_only=True)
    try:
        series, jours = _series(con)
        indicateurs = _indicateurs(con)
        moyennes = risque.moyenne_pluriannuelle(con, fenetre=DEFAUT.nom)
        (archive,) = con.execute(
            "SELECT max(jour_validite) FROM risque_journalier WHERE massif_coherent"
        ).fetchone()
        toutes = [r[0] for r in con.execute(
            "SELECT DISTINCT saison FROM risque_journalier WHERE massif_coherent ORDER BY 1"
        ).fetchall()]
    finally:
        con.close()

    axe = axe_calendaire()
    jours = jours.with_columns(pl.col("jour_validite").dt.strftime("%m-%d").alias("jour_annee"))
    rang_max = int(jours["jour_de_saison"].max())
    bandes = {
        "calendaire": _tableau(_bandes(jours, "jour_annee"), "jour_annee", axe),
        "rang": _tableau(_bandes(jours, "jour_de_saison"), "jour_de_saison", list(range(1, rang_max + 1))),
    }

    # Dernier bulletin integre, massif par massif : le massif 71 s'arrete avant l'archive.
    derniers = {
        r["massif_id"]: r["d"].isoformat()
        for r in jours.group_by("massif_id").agg(pl.col("jour_validite").max().alias("d")).iter_rows(named=True)
    }
    referentiel = {m.id: m for m in MASSIFS}
    massifs = []
    for mid in sorted(series):
        meta = referentiel.get(mid)
        moy = moyennes.filter(pl.col("massif_id") == mid)
        repere = moy.row(0, named=True) if moy.height else None
        massifs.append({
            "id": mid,
            "nom": meta.nom if meta else str(mid),
            "zone": meta.zone if meta else "",
            "departement": meta.departement if meta else "",
            "saisons": sorted(series[mid]),
            "dernier_bulletin": derniers.get(mid),
            # Repere de la fiche : la moyenne d'accueil du massif (T6, T12), avec ses jours.
            "repere": None if repere is None else {
                "risque_moyen": repere["risque_moyen"],
                "jours_avec_indice": repere["jours_avec_indice"],
                "saisons": repere["saisons"],
            },
        })

    for per_massif in series.values():
        for e in per_massif.values():
            e["origine"] = e["origine"].isoformat()

    return {
        "genere": date.today().isoformat(),
        "archive_jusqu_au": archive.isoformat() if archive else None,
        "axe": axe,
        "rang_max": rang_max,
        "saisons": [
            {"nom": s, "comparable": comparable(s), "motif": SAISONS_NON_COMPARABLES.get(s)}
            for s in toutes
        ],
        "massifs": massifs,
        "fenetre_defaut": DEFAUT.nom,
        "saison_complete": SAISON_COMPLETE,
        "fenetres": [
            {
                "nom": f.nom,
                "libelle": f.libelle,
                "debut": list(f.debut),
                "fin": list(f.fin),
                "usage": f.usage,
                "comparable": f.comparable_entre_saisons,
                "comparable_enneigement": f.comparable_enneigement,
            }
            for f in FENETRES
            if f.nom in FENETRES_FICHE
        ]
        + [{
            "nom": SAISON_COMPLETE, "libelle": "saison entiere", "debut": None, "fin": None,
            "usage": "lecture d'une saison prise isolement",
            "comparable": False, "comparable_enneigement": False,
        }],
        "tranches": [{"nom": t.nom, "libelle": t.libelle} for t in TRANCHES],
        "seuil_vent_fort_kmh": meteo.SEUIL_VENT_FORT_KMH,
        "min_saisons_bande": risque.MIN_SAISONS_NORMALE,
        "series": series,
        "bandes": bandes,
        "indicateurs": indicateurs,
        "attribution": "Données Météo-France, Licence Ouverte 2.0",
    }


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "fiche.html",
    standalone: bool = True,
) -> Path:
    page = injecter(TEMPLATE, payload(db_path), standalone)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
