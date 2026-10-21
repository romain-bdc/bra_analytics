"""Ecran d'exploration (spec section 6, T14).

Meme motif que `fiche.py` et `comparaison.py` : un payload JSON construit ici,
insere dans `templates/exploration.html` par le marqueur `__DONNEES__`, tout
l'affichage cote client. Rien n'est recalcule : les comptes viennent des vues de
`metriques/pentes.py` (`rose_saison`, `croisement_vent`, `situations`), publies
en *jours* ; le gabarit en tire les frequences, et l'export de chaque graphe
est donc la donnee elle-meme, pas une reconstruction.

Trois faits d'archive commandent l'ecran :

- **La rose n'a pas d'altitude.** `<PENTE>` et `<SitAvalTyp>` n'en portent pas
  (T9, glossaire 12) : chaque rose et chaque jeu de situations est etiquete
  `ALTITUDE_LIBELLE`, et la matrice altitude x orientation n'existe pas. Seul
  le vent a une altitude reelle : le croisement vent x
  orientation se lit par tranche normee, jamais toutes tranches confondues.
- **Les situations typiques n'existent que depuis une saison.** `sat1` / `sat2`
  sont absents des formats anterieurs : une saison sans situation reste dans le
  selecteur et dit pourquoi (`situations_depuis`), elle n'affiche pas un zero.
- **Comparer des saisons suppose une fenetre comparable.** La frequence se rapporte
  aux jours avec `risque_maxi`, donc a un denominateur que la sentinelle
  `RISQUE1=-1` fait varier d'une epoque a l'autre. La regle est ecrite ici une
  fois, depuis `fenetres.py` (`refus`), et voyage dans le payload ; le gabarit ne
  recopie aucune borne.

Les roses se comparent cote a cote (petits multiples) ou par barres par
secteur, jamais superposees : deux polygones se masquent.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from . import partage
from .comparaison import MAX_COURBES, SEUIL_HAUT, SEUIL_TRES_HAUT, _fenetres_payload
from .gabarit import injecter
from .fenetres import DEFAUT, FIN_SENTINELLE, MOIS_FR, SAISON_COMPLETE
from .fiche import archive_et_saisons, fiche_massifs, saisons_payload
from .metriques import pentes, risque
from .metriques.risque import ComparaisonRefusee, _frame
from .tranches import TRANCHES

TEMPLATE = Path(__file__).parent / "templates" / "exploration.html"

ALTITUDE_LIBELLE = "non localisée en altitude"

# Une rose se lit a la fois en jours-toutes-conditions et restreinte aux jours
# de risque eleve (la lecture comparable de `pentes`, glossaire 12). Les seuils
# sont ceux de la comparaison ; les cles sont les suffixes des colonnes des vues.
CONDITIONS: tuple[dict, ...] = (
    {"cle": "toutes", "libelle": "tous les jours", "seuil": None},
    {"cle": "ge3", "libelle": f"jours à risque {SEUIL_HAUT} ou plus", "seuil": SEUIL_HAUT},
    {"cle": "ge4", "libelle": f"jours à risque {SEUIL_TRES_HAUT} ou plus", "seuil": SEUIL_TRES_HAUT},
)


def refus(fenetre: str) -> str | None:
    """Motif du refus de comparer des saisons sur `fenetre`, ou `None` si elle le permet.

    Meme definition que le classement de T13 : celle de `risque`.
    """
    try:
        risque.fenetre_comparable(fenetre)
    except ComparaisonRefusee as exc:
        return str(exc)
    return None


def _roses(df: pl.DataFrame) -> dict:
    """massif -> saison -> fenetre -> comptes en jours, dans l'ordre de `ORIENTATIONS`."""
    sortie: dict = {}
    for (fen, mid, saison), g in df.group_by(["fenetre", "massif_id", "saison"], maintain_order=True):
        par_o = {r["orientation"]: r for r in g.iter_rows(named=True)}
        premiere = next(iter(par_o.values()))
        sortie.setdefault(str(mid), {}).setdefault(saison, {})[fen] = {
            "c": premiere["jours_couverts"],
            "s": [par_o[o]["jours_signales"] for o in pentes.ORIENTATIONS],
            "c3": premiere["jours_ge3"],
            "s3": [par_o[o]["jours_signales_ge3"] for o in pentes.ORIENTATIONS],
            "c4": premiere["jours_ge4"],
            "s4": [par_o[o]["jours_signales_ge4"] for o in pentes.ORIENTATIONS],
        }
    return sortie


def _vent(df: pl.DataFrame) -> dict:
    """massif -> saison -> fenetre -> tranche -> [[jours de vent, jours pente chargee signalee]] x 8 directions."""
    sortie: dict = {}
    for (fen, mid, saison, tranche), g in df.group_by(
        ["fenetre", "massif_id", "saison", "tranche"], maintain_order=True
    ):
        par_d = {r["direction_vent"]: r for r in g.iter_rows(named=True)}
        sortie.setdefault(str(mid), {}).setdefault(saison, {}).setdefault(fen, {})[tranche] = [
            [par_d[d]["jours_vent"], par_d[d]["jours_pente_chargee_signalee"]] if d in par_d else [0, 0]
            for d in pentes.ORIENTATIONS
        ]
    return sortie


def _situations(df: pl.DataFrame) -> dict:
    """massif -> saison -> fenetre -> {c: jours avec `sat1`, l: [[rang, code, jours]]}."""
    sortie: dict = {}
    for (fen, mid, saison), g in df.group_by(["fenetre", "massif_id", "saison"], maintain_order=True):
        sortie.setdefault(str(mid), {}).setdefault(saison, {})[fen] = {
            "c": g["jours_couverts"][0],
            "l": [[r["rang"], r["code"], r["jours"]] for r in g.iter_rows(named=True)],
        }
    return sortie


def payload(db_path: str | Path = "warehouse/bra.duckdb") -> dict:
    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"base absente : {db} (lancer `bra build`)")

    fenetres = _fenetres_payload()
    noms = [f["nom"] for f in fenetres]
    con = duckdb.connect(str(db), read_only=True)
    try:
        archive, toutes = archive_et_saisons(con)
        moyennes = risque.moyenne_pluriannuelle(con, fenetre=DEFAUT.nom)
        roses_df = pl.concat([pentes.rose_saison(con, fenetre=f) for f in noms])
        sit_df = pl.concat([pentes.situations(con, fenetre=f) for f in noms])
        try:
            vent_df = pl.concat([pentes.croisement_vent(con, fenetre=f) for f in noms])
        except ValueError:
            # Entrepot sans bloc meteo : l'ecran garde les roses et le dit.
            vent_df = None
        jours = _frame(
            con, "SELECT massif_id, saison, jour_validite FROM risque_journalier WHERE massif_coherent", []
        )
    finally:
        con.close()

    # Les massifs sont ceux de la fiche, avec les saisons qu'ils ont diffusees.
    series: dict = {}
    for r in jours.select("massif_id", "saison").unique().iter_rows():
        series.setdefault(r[0], {})[r[1]] = None
    massifs = fiche_massifs(series, jours, moyennes)
    premiere_situation = sit_df["saison"].min() if sit_df.height else None

    return {
        "genere": date.today().isoformat(),
        "archive_jusqu_au": archive.isoformat() if archive else None,
        "attribution": partage.ATTRIBUTION_DONNEES,
        "partage": partage.bloc(archive.isoformat() if archive else None, date.today().isoformat()),
        "altitude": ALTITUDE_LIBELLE,
        "orientations": list(pentes.ORIENTATIONS),
        "fenetre_defaut": DEFAUT.nom,
        "saison_complete": SAISON_COMPLETE,
        "fenetres": fenetres,
        "refus": {f["nom"]: refus(f["nom"]) for f in fenetres},
        "saisons": saisons_payload(toutes),
        "massifs": massifs,
        "tranches": [{"nom": t.nom, "libelle": t.libelle} for t in TRANCHES],
        "conditions": list(CONDITIONS),
        "max_courbes": MAX_COURBES,
        "fin_sentinelle": f"{MOIS_FR[FIN_SENTINELLE.month - 1]} {FIN_SENTINELLE.year}",
        "origine_vent": "prévision",
        "libelles_sat": {str(c): l for c, l in pentes.LIBELLES_SAT.items()},
        "code_sans_mecanisme": pentes.CODE_SANS_MECANISME,
        "situations_depuis": premiere_situation,
        "roses": _roses(roses_df),
        "vent": _vent(vent_df) if vent_df is not None else None,
        "situations": _situations(sit_df),
    }


def render(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_path: str | Path = "exploration.html",
    standalone: bool = True,
) -> Path:
    page = injecter(TEMPLATE, payload(db_path), standalone)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
