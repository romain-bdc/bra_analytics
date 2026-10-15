"""Controles de coherence sur l'entrepot construit.

L'objectif n'est pas de rejeter des donnees mais de rendre visibles les
anomalies : l'archive en contient de reelles (journees partielles, massif
retire en cours de serie, indices absents) qu'il vaut mieux constater que
decouvrir au milieu d'une analyse.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from .fetch import SLUG_TO_ID, slugify
from .massifs import BY_ID

# Echelle europeenne du risque d'avalanche : 1 (faible) a 5 (tres fort).
RISQUE_MIN, RISQUE_MAX = 1, 5

# Vitesse de vent au-dela de laquelle une valeur est une erreur de saisie. Sur
# les 36 massifs, les plus fortes valeurs plausibles sont 180-190 km/h (36
# echeances) ; viennent ensuite 400 et 530 km/h, isolees. Les metriques
# excluent ce qui sort de [0, VENT_MAX_KMH] sans le corriger.
VENT_MAX_KMH = 300


@dataclass
class Anomalie:
    controle: str
    gravite: str  # "erreur" (donnee incoherente) ou "signal" (fait a connaitre)
    lignes: int
    detail: str

    def __str__(self) -> str:
        marque = "!!" if self.gravite == "erreur" else "--"
        return f"{marque} {self.controle:<28} {self.lignes:>6} ligne(s)  {self.detail}"


def check_bulletins(df: pl.DataFrame) -> list[Anomalie]:
    anomalies: list[Anomalie] = []

    def add(nom: str, gravite: str, mask: pl.Expr, detail: str) -> None:
        n = df.filter(mask).height
        if n:
            anomalies.append(Anomalie(nom, gravite, n, detail))

    if not df.height:
        return [Anomalie("entrepot_vide", "erreur", 0, "aucun bulletin")]

    # --- incoherences franches ---
    for col in ("risque1", "risque2", "risque_maxi", "risque_maxi_j2"):
        add(
            f"{col}_hors_echelle", "erreur",
            pl.col(col).is_not_null() & ~pl.col(col).is_between(RISQUE_MIN, RISQUE_MAX),
            f"valeurs hors [{RISQUE_MIN}, {RISQUE_MAX}]",
        )

    add(
        "risque_maxi_incoherent", "erreur",
        pl.col("risque_maxi").is_not_null()
        & pl.col("risque1").is_not_null()
        & (pl.col("risque_maxi") < pl.col("risque1")),
        "risque_maxi < risque1",
    )
    add(
        "echeance_anterieure", "erreur",
        pl.col("date_echeance").is_not_null() & (pl.col("date_echeance") < pl.col("date_bulletin")),
        "echeance avant la redaction",
    )
    add(
        "massif_inconnu", "erreur",
        ~pl.col("massif_id").is_in(list(BY_ID)),
        "identifiant absent du referentiel",
    )
    add(
        "risque1_absent", "erreur",
        pl.col("risque_estime") & pl.col("risque1").is_null(),
        "estimation annoncee mais RISQUE1 vide",
    )
    add(
        "non_estime_avec_maxi", "signal",
        ~pl.col("risque_estime") & pl.col("risque_maxi").is_not_null(),
        "RISQUE1=-1 mais RISQUEMAXI renseigne : compte dans les moyennes",
    )
    add(
        "risque_non_estime", "signal",
        ~pl.col("risque_estime"),
        "bulletins sans estimation chiffree (hors saison, sous-neige)",
    )

    # Un identifiant connu peut porter un libelle qui n'est pas le sien : vu en
    # 2016 avec ID=3 (Mont-Blanc) et MASSIF="MOYENNE MONTAGNE", un bulletin
    # technique annoncant l'absence de BRA en moyenne montagne. On compare le
    # libelle du fichier a celui du referentiel, en tolerant les variantes de
    # graphie deja recensees (`Andorre (massif)`, `ORLU__ST_BARTHELEMY`...).
    incoherents = []
    for massif_id, nom_source in df.select("massif_id", "massif_nom_source").unique().iter_rows():
        if not nom_source:
            continue
        reference = BY_ID.get(massif_id)
        if reference is None:
            continue  # deja signale par `massif_inconnu`
        slug = slugify(nom_source)
        if slug == slugify(reference.nom) or SLUG_TO_ID.get(slug) == massif_id:
            continue
        incoherents.append((massif_id, nom_source, reference.nom))

    if incoherents:
        anomalies.append(Anomalie(
            "libelle_massif_incoherent", "erreur", len(incoherents),
            "ID et libelle se contredisent : "
            + ", ".join(f"ID={i} porte {src!r} au lieu de {ref!r}" for i, src, ref in incoherents[:3]),
        ))

    doublons = df.group_by(["massif_id", "date_bulletin"]).len().filter(pl.col("len") > 1).height
    if doublons:
        anomalies.append(Anomalie("cle_dupliquee", "erreur", doublons, "(massif_id, date_bulletin) non unique"))

    # --- faits a connaitre, pas des defauts ---
    add(
        "jour_validite_absent", "signal",
        pl.col("jour_validite").is_null(),
        "ni DATEECHEANCE ni DATEVALIDITE exploitables",
    )

    # Ecart entre `bulletins` et `risque_journalier` : la vue ne garde qu'une
    # redaction par jour couvert. Le build le journalise ligne a ligne ; on le
    # rappelle ici en volume pour qu'un `bra check` sur un entrepot deja
    # construit ne laisse pas l'ecart inexplique.
    couverts = (
        df.filter(pl.col("jour_validite").is_not_null())
        .group_by(["massif_id", "jour_validite"])
        .len()
    )
    surnumeraires = couverts.select((pl.col("len") - 1).sum()).item() or 0
    if surnumeraires:
        anomalies.append(Anomalie(
            "jour_couvert_multiple", "signal", int(surnumeraires),
            f"bulletins ecartes par risque_journalier ({couverts.height} jours-massif retenus)",
        ))
    add(
        "loc_sans_second_risque", "signal",
        pl.col("loc_type").is_not_null() & pl.col("risque2").is_null(),
        "distinction annoncee mais RISQUE2 vide",
    )
    add("amendement", "signal", pl.col("amendement"), "bulletins amendes")
    add(
        "vent_unique", "signal",
        pl.col("vent_altitude_basse_m").is_not_null() & pl.col("vent_altitude_haute_m").is_null(),
        "un seul vent (ALTITUDEVENT2=9999 avant 2024, Alpes du Sud) : pas de second vent",
    )
    add(
        "texte_stabilite_absent", "signal",
        pl.col("stabilite_texte").is_null(),
        "bloc stabilite vide",
    )
    return anomalies


def check_filles(frames: dict[str, pl.DataFrame]) -> list[Anomalie]:
    """Controles des tables filles : chaque sentinelle convertie au parsing
    reste comptee ici, et une valeur hors plage est une erreur.

    Le parser rend nulles les valeurs « non renseignees » (`-1`, `-2`) sans
    perdre la ligne ; ces comptes disent combien, pour qu'une serie trouee se
    lise comme telle et non comme une serie complete.
    """
    anomalies: list[Anomalie] = []

    def add(nom: str, gravite: str, n: int, detail: str) -> None:
        if n:
            anomalies.append(Anomalie(nom, gravite, n, detail))

    meteo = frames.get("meteo")
    if meteo is not None and meteo.height:
        valeurs = ["vent_bas_vitesse_kmh", "vent_haut_vitesse_kmh", "iso_0_m", "temps_sensible"]
        add("echeance_meteo_vide", "signal",
            meteo.filter(pl.all_horizontal(pl.col(c).is_null() for c in valeurs)).height,
            "echeances meteo sans aucune valeur (-1 avant 2024, attributs vides ensuite)")
        hors = pl.lit(False)
        for c in ("vent_bas_vitesse_kmh", "vent_haut_vitesse_kmh"):
            hors = hors | ~pl.col(c).is_between(0, VENT_MAX_KMH).fill_null(True)
        add("vent_hors_plage", "erreur", meteo.filter(hors).height,
            f"vitesse de vent hors [0, {VENT_MAX_KMH}] km/h : exclue des metriques")

    enn = frames.get("enneigement")
    if enn is not None and enn.height:
        releve = ["massif_id", "date_bulletin", "origine", "date_enneigement"]
        par_releve = enn.group_by(releve).agg(
            vide=pl.col("altitude_m").is_null().all(),
            sans=(pl.col("sans_enneigement_continu_nord").fill_null(False)
                  | pl.col("sans_enneigement_continu_sud").fill_null(False)).any(),
        )
        add("releve_enneigement_vide", "signal", par_releve.filter(pl.col("vide")).height,
            "releves d'enneigement non faits (paliers a -1)")
        add("sans_enneigement_continu", "signal", par_releve.filter(pl.col("sans")).height,
            "releves sans enneigement continu sur un versant (limite -1)")

    # Le journal du parser : chaque valeur sentinelle rendue nulle, y compris
    # sur une echeance ou un releve par ailleurs renseigne.
    conv = frames.get("conversions")
    if conv is not None and conv.height:
        par_champ = (
            conv.group_by("table_cible", "champ", "valeur_source")
            .agg(pl.col("valeurs").sum())
            .sort("table_cible", "champ", "valeur_source")
        )
        for t, c, v, n in par_champ.iter_rows():
            add(f"sentinelle {t}.{c}={v}", "signal", n, "valeur rendue nulle au parsing")

    nf = frames.get("neige_fraiche")
    if nf is not None and nf.height:
        add("neige_fraiche_non_observee", "signal",
            nf.filter(
                (pl.col("secteur1_libelle").is_not_null() & pl.col("secteur1_cumul_cm").is_null())
                | (pl.col("secteur2_libelle").is_not_null() & pl.col("secteur2_cumul_cm").is_null())
            ).height,
            "cumuls de secteur non observes (-2 ou -1 avant 2024)")
    return anomalies


def coverage_gaps(df: pl.DataFrame) -> pl.DataFrame:
    """Jours calendaires sans bulletin, par massif et saison.

    Un ecart n'est pas forcement une lacune d'ingestion : la diffusion s'arrete
    hors saison, et certaines journees d'archive sont reellement partielles.
    """
    if not df.height:
        return pl.DataFrame(schema={"saison": pl.Utf8, "massif_id": pl.Int32, "jours_manquants": pl.Int64})
    return (
        df.filter(pl.col("jour_validite").is_not_null())
        .group_by(["saison", "massif_id"])
        .agg(
            jours_couverts=pl.col("jour_validite").n_unique(),
            premier=pl.col("jour_validite").min(),
            dernier=pl.col("jour_validite").max(),
        )
        .with_columns(
            jours_calendaires=(pl.col("dernier") - pl.col("premier")).dt.total_days() + 1
        )
        .with_columns(jours_manquants=pl.col("jours_calendaires") - pl.col("jours_couverts"))
        .sort(["saison", "massif_id"])
    )


def report(df: pl.DataFrame, filles: dict[str, pl.DataFrame] | None = None) -> str:
    anomalies = check_bulletins(df) + (check_filles(filles) if filles else [])
    erreurs = [a for a in anomalies if a.gravite == "erreur"]
    signaux = [a for a in anomalies if a.gravite == "signal"]

    lignes = [f"{df.height} bulletins controles", ""]
    lignes.append("Erreurs :" if erreurs else "Erreurs : aucune")
    lignes += [f"  {a}" for a in erreurs]
    if signaux:
        lignes.append("")
        lignes.append("Signaux :")
        lignes += [f"  {a}" for a in signaux]
    return "\n".join(lignes)
