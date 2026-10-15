"""Schemas explicites des tables du entrepot.

Les types sont declares plutot qu'inferes : sur les epoques anciennes des
colonnes entieres sont nulles de bout en bout (`sat1`, `risque_maxi_j2`...) et
polars les typerait en `Null`, ce qui casserait la concatenation entre saisons.
"""

from __future__ import annotations

import polars as pl

from .parser import PENTE_SECTEURS

BULLETINS: dict[str, pl.DataType] = {
    # cle metier
    "massif_id": pl.Int32,
    "date_bulletin": pl.Datetime("us"),
    "jour_bulletin": pl.Date,
    "jour_validite": pl.Date,
    "saison": pl.Utf8,
    "saison_debut": pl.Int32,
    # identite
    "massif_nom": pl.Utf8,
    "zone": pl.Utf8,
    "massif_nom_source": pl.Utf8,
    # `ID` et libelle `MASSIF` se recoupent-ils ? Faux = la ligne herite d'un
    # massif, d'une zone et d'un departement qui ne sont pas les siens.
    "massif_coherent": pl.Boolean,
    "type_bulletin": pl.Utf8,
    "producteur": pl.Utf8,
    "amendement": pl.Boolean,
    # dates
    "date_diffusion": pl.Datetime("us"),
    "date_echeance": pl.Datetime("us"),
    "date_validite": pl.Datetime("us"),
    # risques
    "risque1": pl.Int8,
    "risque1_evolution": pl.Int8,
    "risque2": pl.Int8,
    "risque2_evolution": pl.Int8,
    "risque_maxi": pl.Int8,
    "loc_type": pl.Utf8,
    "altitude_seuil_m": pl.Int32,
    "loc1_secteur": pl.Utf8,
    "loc2_secteur": pl.Utf8,
    "risque_estime": pl.Boolean,
    "risque_commentaire": pl.Utf8,
    # tendance J+2 (2024+)
    "risque_maxi_j2": pl.Int8,
    "date_risque_j2": pl.Datetime("us"),
    "risque_j2_libelle": pl.Utf8,
    "risque_j2_commentaire": pl.Utf8,
    # rose des pentes
    **{f"pente_{s.lower()}": pl.Boolean for s in PENTE_SECTEURS},
    "pente_commentaire": pl.Utf8,
    # textes
    "resume": pl.Utf8,
    "accidentel": pl.Utf8,
    "naturel": pl.Utf8,
    "avis": pl.Utf8,
    "vigilance": pl.Utf8,
    "stabilite_titre": pl.Utf8,
    "stabilite_texte": pl.Utf8,
    "qualite_texte": pl.Utf8,
    "meteo_commentaire": pl.Utf8,
    # situations avalancheuses typiques (2024+)
    "sat1": pl.Int8,
    "sat2": pl.Int8,
    # enneigement du jour
    "enneigement_limite_nord_m": pl.Int32,
    "enneigement_limite_sud_m": pl.Int32,
    "vent_altitude_basse_m": pl.Int32,
    "vent_altitude_haute_m": pl.Int32,
    # provenance
    "schema_version": pl.Int8,
    "format_famille": pl.Utf8,
    "fichier_source": pl.Utf8,
}

_KEY: dict[str, pl.DataType] = {
    "massif_id": pl.Int32,
    "date_bulletin": pl.Datetime("us"),
    "saison": pl.Utf8,
}

METEO: dict[str, pl.DataType] = {
    **_KEY,
    "origine": pl.Utf8,          # "prevision" (J+1) ou "historique" (7 jours ecoules)
    "rang": pl.Int16,
    "echeance": pl.Datetime("us"),
    "vent_bas_vitesse_kmh": pl.Int16,
    "vent_bas_direction": pl.Utf8,
    "vent_haut_vitesse_kmh": pl.Int16,
    "vent_haut_direction": pl.Utf8,
    "iso_0_m": pl.Int32,
    "iso_moins10_m": pl.Int32,
    "limite_pluie_neige_m": pl.Int32,
    "temps_sensible": pl.Int16,
    "temps_sensible_libelle": pl.Utf8,
    "mer_nuages_m": pl.Int32,
}

ENNEIGEMENT: dict[str, pl.DataType] = {
    **_KEY,
    "origine": pl.Utf8,
    "date_enneigement": pl.Datetime("us"),
    "limite_nord_m": pl.Int32,
    "limite_sud_m": pl.Int32,
    "altitude_m": pl.Int32,
    "epaisseur_nord_cm": pl.Int32,
    "epaisseur_sud_cm": pl.Int32,
}

NEIGE_FRAICHE: dict[str, pl.DataType] = {
    **_KEY,
    "origine": pl.Utf8,
    "date_cumul": pl.Datetime("us"),
    "altitude_mesure_m": pl.Int32,
    # Format ancien (<= 2023) uniquement : les secteurs nommes et leur cumul.
    "secteur1_libelle": pl.Utf8,
    "secteur1_cumul_cm": pl.Int16,
    "secteur2_libelle": pl.Utf8,
    "secteur2_cumul_cm": pl.Int16,
    "cumul_min_cm": pl.Int16,
    "cumul_max_cm": pl.Int16,
}

HISTORIQUE_RISQUE: dict[str, pl.DataType] = {
    **_KEY,
    "date_risque": pl.Datetime("us"),
    "risque_maxi": pl.Int8,
}

TENDANCES: dict[str, pl.DataType] = {
    **_KEY,
    "date_tendance": pl.Datetime("us"),
    "valeur": pl.Utf8,
}

TABLES: dict[str, dict[str, pl.DataType]] = {
    "bulletins": BULLETINS,
    "meteo": METEO,
    "enneigement": ENNEIGEMENT,
    "neige_fraiche": NEIGE_FRAICHE,
    "historique_risque": HISTORIQUE_RISQUE,
    "tendances": TENDANCES,
}
