"""Verrouille chaque ecart de format releve dans docs/exploration.md.

Les fixtures sont des bulletins reels figes, un par epoque, dont seules les
images base64 ont ete retirees.
"""

from datetime import date, datetime

import pytest

from bra_analytics.parser import (
    ParseError,
    normalize_direction,
    parse_datetime,
    parse_file,
    parse_localisation,
    season_of,
)

from .conftest import fixture


def head(name: str) -> dict:
    parsed = parse_file(fixture(name))
    assert len(parsed) == 1
    return parsed[0].bulletin


# --------------------------------------------------------------------------
# Detection d'epoque
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("v1_2016_aspe_ossau.xml", 1),
        ("v2_2017_aspe_ossau.xml", 2),
        ("v3_2023_aspe_ossau.xml", 3),
        ("v4_2024_aspe_ossau.xml", 4),
        ("v5_2025_aspe_ossau.xml", 5),
        ("v6_2026_aspe_ossau.xml", 6),
    ],
)
def test_schema_version_detectee(name: str, version: int) -> None:
    assert head(name)["schema_version"] == version


def test_famille_de_format() -> None:
    assert head("v3_2023_aspe_ossau.xml")["format_famille"] == "legacy"
    assert head("v4_2024_aspe_ossau.xml")["format_famille"] == "moderne"


# --------------------------------------------------------------------------
# Racine encapsulante et attribut `nombre` mensonger
# --------------------------------------------------------------------------

def test_wrapper_bulletins_traverse() -> None:
    """De 2019 a 2023 la racine est <Bulletins>, pas BULLETINS_NEIGE_AVALANCHE."""
    assert head("v3_2023_aspe_ossau.xml")["massif_id"] == 65


def test_attribut_nombre_ignore() -> None:
    """`nombre="2"` alors qu'un seul bulletin est present : on suit les enfants reels."""
    parsed = parse_file(fixture("v3_2023_andorre_nombre2.xml"))
    assert len(parsed) == 1
    assert parsed[0].bulletin["massif_id"] == 71


# --------------------------------------------------------------------------
# Identite : l'ID prime sur le libelle
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "libelle"),
    [
        ("v3_2023_aspe_ossau.xml", "ASPE-OSSAU"),
        ("v4_2024_aspe_ossau.xml", "Aspe Ossau"),
        ("v4_2024_andorre.xml", "Andorre (massif)"),
    ],
)
def test_libelle_massif_varie_mais_id_stable(name: str, libelle: str) -> None:
    row = head(name)
    assert row["massif_nom_source"] == libelle
    assert row["massif_id"] in (65, 71)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def test_date_2016_utc_convertie_en_heure_locale() -> None:
    """2016 : `DATEDIFFUSION` porte une fraction a 7 chiffres et un suffixe Z."""
    row = head("v1_2016_aspe_ossau.xml")
    # 14:47:38.8909407Z en mars (heure d'hiver) -> 15:47:38 locale
    assert row["date_diffusion"] == datetime(2016, 3, 9, 15, 47, 38, 890940)


def test_date_bulletin_peut_preceder_le_dossier_source() -> None:
    """Fichier range dans BRA/2016/03/10/ mais date du 9 mars."""
    row = head("v1_2016_aspe_ossau.xml")
    assert row["jour_bulletin"] == date(2016, 3, 9)


def test_date_validite_absente_en_2016() -> None:
    assert head("v1_2016_aspe_ossau.xml")["date_validite"] is None
    assert head("v3_2023_aspe_ossau.xml")["date_validite"] is not None


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("2023-02-15T15:02:05", datetime(2023, 2, 15, 15, 2, 5)),
        ("2016-03-09T14:05:23.2144571Z", datetime(2016, 3, 9, 15, 5, 23, 214457)),
        ("2016-07-01T10:00:00Z", datetime(2016, 7, 1, 12, 0, 0)),  # heure d'ete : +2
        ("", None),
        (None, None),
        ("pas une date", None),
    ],
)
def test_parse_datetime(brut, attendu) -> None:
    assert parse_datetime(brut) == attendu


@pytest.mark.parametrize(
    ("moment", "saison"),
    [
        (datetime(2026, 2, 11), "2025-2026"),
        (datetime(2025, 12, 1), "2025-2026"),
        (datetime(2025, 10, 15), "2025-2026"),
        (datetime(2026, 5, 30), "2025-2026"),
        (datetime(2025, 8, 31), "2024-2025"),
    ],
)
def test_saison_bascule_en_septembre(moment, saison) -> None:
    assert season_of(moment)[1] == saison


# --------------------------------------------------------------------------
# LOC1/LOC2 polysemiques
# --------------------------------------------------------------------------

def test_loc_orientation() -> None:
    """2017 : RISQUE1=3 en versant Sud, RISQUE2=2 en versant Nord."""
    row = head("v2_2017_aspe_ossau.xml")
    assert row["loc_type"] == "orientation"
    assert row["loc1_secteur"] == "S"
    assert row["loc2_secteur"] == "N"
    assert row["altitude_seuil_m"] is None
    assert (row["risque1"], row["risque2"]) == (3, 2)


def test_loc_altitude() -> None:
    """2024 : distinction altitudinale a 2400 m."""
    row = head("v4_2024_andorre.xml")
    assert row["loc_type"] == "altitude"
    assert row["altitude_seuil_m"] == 2400
    assert row["loc1_secteur"] is None


@pytest.mark.parametrize(
    ("loc", "altitude", "attendu"),
    [
        ("<2200", "2200", ("altitude", 2200, None)),
        (">2200", "2200", ("altitude", 2200, None)),
        ("&lt;2100", "2100", ("altitude", 2100, None)),  # deja decode par ElementTree
        ("S", "", ("orientation", None, "S")),
        ("N", "", ("orientation", None, "N")),
        ("O", "", ("orientation", None, "W")),
        ("", "", (None, None, None)),
        (None, None, (None, None, None)),
        ("", "2000", ("altitude", 2000, None)),  # repli sur ALTITUDE seul
    ],
)
def test_parse_localisation(loc, altitude, attendu) -> None:
    if loc == "&lt;2100":
        loc = "<2100"
    assert parse_localisation(loc, altitude) == attendu


# --------------------------------------------------------------------------
# EVOLURISQUE = second indice, pas un code
# --------------------------------------------------------------------------

def test_evolurisque_est_un_indice() -> None:
    row = head("v6_2026_aspe_ossau.xml")
    assert row["risque1"] == 3
    assert row["risque1_evolution"] == 2
    assert row["risque_maxi"] == max(row["risque1"], row["risque1_evolution"])


# --------------------------------------------------------------------------
# Directions de vent : deux conventions
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("NW", "NW"), ("W", "W"), ("SW", "SW"),      # convention anglaise (<= 2023)
        ("NO", "NW"), ("O", "W"), ("SO", "SW"),      # convention francaise (>= 2024)
        ("_", "VRB"), ("Vrb", "VRB"),                # variable, deux notations
        ("N", "N"), ("", None), (None, None),
    ],
)
def test_normalize_direction(brut, attendu) -> None:
    assert normalize_direction(brut) == attendu


def test_directions_harmonisees_entre_epoques() -> None:
    """Les deux conventions doivent produire le meme vocabulaire en sortie."""
    autorise = {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "VRB", None}
    for name in ("v3_2023_aspe_ossau.xml", "v6_2026_aspe_ossau.xml"):
        for row in parse_file(fixture(name))[0].meteo:
            assert row["vent_bas_direction"] in autorise
            assert row["vent_haut_direction"] in autorise


# --------------------------------------------------------------------------
# Renommages d'attributs et cardinalites
# --------------------------------------------------------------------------

def test_ss24_min_max_renommes_en_2024() -> None:
    """SS241/SS242 (<=2023) et SS24Min/SS24Max (>=2024) alimentent les memes colonnes."""
    for name in ("v3_2023_aspe_ossau.xml", "v6_2026_aspe_ossau.xml"):
        rows = parse_file(fixture(name))[0].neige_fraiche
        prevision = [r for r in rows if r["origine"] == "prevision"]
        assert len(prevision) == 6
        assert all(r["cumul_min_cm"] is not None for r in prevision)


def test_cardinalite_meteo_par_epoque() -> None:
    """3 echeances de prevision jusqu'en 2023, 4 ensuite ; BSH 21 puis 28."""
    ancien = parse_file(fixture("v3_2023_aspe_ossau.xml"))[0].meteo
    moderne = parse_file(fixture("v6_2026_aspe_ossau.xml"))[0].meteo
    assert len([r for r in ancien if r["origine"] == "prevision"]) == 3
    assert len([r for r in ancien if r["origine"] == "historique"]) == 21
    assert len([r for r in moderne if r["origine"] == "prevision"]) == 4
    assert len([r for r in moderne if r["origine"] == "historique"]) == 28


def test_bsh_absent_en_2016() -> None:
    parsed = parse_file(fixture("v1_2016_aspe_ossau.xml"))[0]
    assert parsed.historique_risque == []
    assert all(r["origine"] == "prevision" for r in parsed.meteo)


def test_tendances_presentes_avant_2024_absentes_ensuite() -> None:
    assert len(parse_file(fixture("v3_2023_aspe_ossau.xml"))[0].tendances) == 2
    assert parse_file(fixture("v6_2026_aspe_ossau.xml"))[0].tendances == []


# --------------------------------------------------------------------------
# Champs apparus ou disparus
# --------------------------------------------------------------------------

def test_champs_modernes_nuls_sur_les_anciennes_epoques() -> None:
    ancien = head("v3_2023_aspe_ossau.xml")
    for champ in ("sat1", "risque_maxi_j2", "risque_j2_libelle", "date_risque_j2"):
        assert ancien[champ] is None, champ

    moderne = head("v4_2024_andorre.xml")
    assert moderne["sat1"] is not None
    assert moderne["risque_maxi_j2"] == 3


def test_producteur_disparait_en_2024() -> None:
    assert head("v3_2023_aspe_ossau.xml")["producteur"] == "CDM651-PREVI"
    assert head("v4_2024_aspe_ossau.xml")["producteur"] is None


def test_titre_de_stabilite_isole_depuis_2025() -> None:
    """Avant 2025 le titre est fondu dans TEXTE ; ensuite il a sa balise."""
    assert head("v3_2023_aspe_ossau.xml")["stabilite_titre"] is None
    assert head("v5_2025_aspe_ossau.xml")["stabilite_titre"] is not None
    # Le corps ne doit jamais etre vide, quelle que soit l'epoque.
    for name in ("v1_2016_aspe_ossau.xml", "v3_2023_aspe_ossau.xml", "v6_2026_aspe_ossau.xml"):
        assert head(name)["stabilite_texte"]


def test_avis_et_vigilance_non_vides_en_2016() -> None:
    """Le descriptif 2023 annonce VIGILANCE toujours vide : faux sur l'archive."""
    row = head("v1_2016_aspe_ossau.xml")
    assert row["avis"] == "FORT RISQUE D'AVALANCHE"
    assert row["vigilance"] == "JAUNE"


def test_rose_des_pentes() -> None:
    row = head("v3_2023_aspe_ossau.xml")
    assert row["pente_n"] is True
    assert all(isinstance(row[f"pente_{s}"], bool) for s in ("n", "ne", "e", "se", "s", "sw", "w", "nw"))


def test_images_base64_non_remontees() -> None:
    """Aucune colonne ne doit contenir de charge base64."""
    row = head("v3_2023_aspe_ossau.xml")
    for value in row.values():
        if isinstance(value, str):
            assert "base64" not in value.lower() or len(value) < 200


# --------------------------------------------------------------------------
# Erreurs
# --------------------------------------------------------------------------

def test_fichier_invalide(tmp_path) -> None:
    bad = tmp_path / "casse.xml"
    bad.write_text("<html>302 Found</html>")  # la reponse non redirigee de data.gouv
    with pytest.raises(ParseError):
        parse_file(bad)


def test_xml_malforme(tmp_path) -> None:
    bad = tmp_path / "tronque.xml"
    bad.write_text('<?xml version="1.0"?><BULLETINS_NEIGE_AVALANCHE ID="65"')
    with pytest.raises(ParseError):
        parse_file(bad)


# --------------------------------------------------------------------------
# Echeance vs redaction, et amendement en cours de journee
# --------------------------------------------------------------------------

def test_jour_validite_est_l_echeance_pas_la_redaction() -> None:
    """Le risque annonce porte sur J+1 : indexer sur la redaction decale la serie."""
    row = head("v6_2026_aspe_ossau.xml")
    assert row["jour_bulletin"] == date(2026, 2, 11)
    assert row["jour_validite"] == date(2026, 2, 12)


def test_jour_validite_tient_meme_sans_datevalidite() -> None:
    """`DATEVALIDITE` n'existe pas en 2016 : `DATEECHEANCE` suffit a dater le jour couvert."""
    row = head("v1_2016_aspe_ossau.xml")
    assert row["date_validite"] is None
    assert row["jour_validite"] == date(2016, 3, 10)


def test_jour_validite_suit_l_echeance_et_non_la_validite() -> None:
    """Hors saison, `DATEVALIDITE` porte la date du *prochain* bulletin.

    Le bulletin du 03/11/2016 couvre le 04 (`DATEECHEANCE`) mais se declare
    valable jusqu'au 07 (`DATEVALIDITE`), faute de bulletin d'ici la. Prendre
    `DATEVALIDITE` pour jour couvert empile plusieurs journees sur la meme cle
    `(massif_id, jour_validite)` : c'est ce qui faisait disparaitre 2 471
    bulletins de `risque_journalier` (docs/reconciliation.md).
    """
    row = head("v2_2016_pays_basque_risque_non_estime.xml")
    assert row["jour_bulletin"] == date(2016, 11, 3)
    assert row["date_echeance"] == datetime(2016, 11, 4, 18, 0)
    assert row["date_validite"] == datetime(2016, 11, 7, 18, 0)
    # L'echeance gagne : le bulletin decrit le 4, pas le 7.
    assert row["jour_validite"] == date(2016, 11, 4)


def test_echeance_et_validite_concordent_en_pleine_saison() -> None:
    """Le piege est invisible en saison : les deux attributs y sont egaux.

    C'est ce qui a rendu l'erreur durable -- 18 869 bulletins estimes sur
    18 869 portent la meme date des deux cotes.
    """
    row = head("v3_2023_aspe_ossau.xml")
    assert row["date_echeance"] == row["date_validite"]
    assert row["jour_validite"] == date(2023, 2, 16)


def test_amendement_matinal_est_un_bulletin_distinct() -> None:
    """31/03/2016 : bulletin du soir pour J+1, puis amendement a 06:00 pour J.

    Les deux portent la meme date de redaction *calendaire* mais des heures et
    des echeances differentes : ce sont deux bulletins, pas un doublon.
    """
    matin = head("v1_2016_couserans_amendement_matin.xml")
    soir = head("v1_2016_couserans_soir_dup_1.xml")

    assert matin["amendement"] is True
    assert soir["amendement"] is False
    assert matin["jour_bulletin"] == soir["jour_bulletin"] == date(2016, 3, 31)
    assert matin["date_bulletin"].hour == 6
    assert soir["date_bulletin"].hour == 16
    # L'amendement couvre la journee en cours, le bulletin du soir le lendemain.
    assert matin["jour_validite"] == date(2016, 3, 31)
    assert soir["jour_validite"] == date(2016, 4, 1)


# --------------------------------------------------------------------------
# Sentinelle `-1` : risque non estime
# --------------------------------------------------------------------------

def test_risque_moins_un_devient_nul() -> None:
    """`RISQUE1="-1"` marque un bulletin sans estimation chiffree.

    Le descriptif 2023 annonce RISQUE1 « toujours renseigne, valeur de 1 a 5 ».
    L'archive porte `-1` en debut et fin de saison, faute d'enneigement.
    Conserver la sentinelle dans une colonne entiere fausserait les moyennes.
    """
    row = head("v2_2016_pays_basque_risque_non_estime.xml")
    assert row["risque_estime"] is False
    assert row["risque1"] is None
    assert row["risque_maxi"] is None
    assert "enneigement" in (row["resume"] or "").lower()


def test_risque_estime_vrai_dans_le_cas_normal() -> None:
    row = head("v6_2026_aspe_ossau.xml")
    assert row["risque_estime"] is True
    assert row["risque1"] == 3


def test_sentinelles_meteo_neutralisees() -> None:
    """`PLUIENEIGE`/`MERNUAGES` valent -1 pour « sans objet »."""
    for row in parse_file(fixture("v3_2023_aspe_ossau.xml"))[0].meteo:
        for champ in ("limite_pluie_neige_m", "mer_nuages_m"):
            assert row[champ] is None or row[champ] >= 0


# --------------------------------------------------------------------------
# Bulletin technique aberrant (2016)
# --------------------------------------------------------------------------

def test_texte_enveloppe_dans_du_html_est_recupere() -> None:
    """Certains blocs enveloppent leur contenu dans du balisage (<h1>).

    `findtext` ne rendrait que le texte direct de l'element, donc rien.
    """
    row = head("anomalie_2016_moyenne_montagne.xml")
    assert row["stabilite_texte"] is not None
    assert "MOYENNE MONTAGNE" in row["stabilite_texte"]
    assert "<h1>" not in row["stabilite_texte"]


def test_date_de_diffusion_malformee_toleree() -> None:
    """`DATEDIFFUSION="2016-02-04T15:00:24.1234567Z.6378518Z"` : double suffixe Z."""
    row = head("anomalie_2016_moyenne_montagne.xml")
    assert row["date_diffusion"] is not None
    assert row["date_diffusion"].date() == date(2016, 2, 4)


def test_typebulletin_absent_avant_2017() -> None:
    assert head("v1_2016_aspe_ossau.xml")["type_bulletin"] is None
    assert head("v3_2023_aspe_ossau.xml")["type_bulletin"] == "BRA"
