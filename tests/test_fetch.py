"""Ingestion : resolution des noms de massifs, cache, et suivi de redirection.

Aucun acces reseau : les reponses sont simulees via httpx.MockTransport.
"""

from datetime import date

import httpx
import pytest

from bra_analytics.fetch import (
    BraFetcher,
    daterange,
    massif_id_from_filename,
    season_days,
    slugify,
)

LISTING = """
<html><body><table>
<tr><td><a href="/meteofrance/data/BULLETIN/BRA/2026/02/11/xml/Aspe%20Ossau_20260211162100.xml">x</a></td></tr>
<tr><td><a href="/meteofrance/data/BULLETIN/BRA/2026/02/11/xml/Aravis_20260211161200.xml">x</a></td></tr>
<tr><td><a href="/meteofrance/data/BULLETIN/BRA/2026/02/11/xml/Capcir%20Puymorens_20260211161900.xml">x</a></td></tr>
</table></body></html>
"""

XML = b'<?xml version="1.0"?><BULLETINS_NEIGE_AVALANCHE ID="65" DATEBULLETIN="2026-02-11T16:00:00"/>'


@pytest.mark.parametrize(
    ("filename", "massif_id"),
    [
        ("ASPE-OSSAU_20230215150205.xml", 65),
        ("Aspe%20Ossau_20260211162100.xml", 65),
        ("Andorre%20%28massif%29_20240117160220.xml", 71),   # parentheses encodees
        ("ORLU__ST_BARTHELEMY_20230207150022.xml", 72),      # double underscore
        ("Orlu%20St-Barthelemy_20260211161900.xml", 72),
        ("Embrunnais%20Parpaillon_20240117163913.xml", 20),  # double n, jusqu'en 2025
        ("Embrunais%20Parpaillon_20260211163300.xml", 20),   # simple n, depuis 2026
        ("CERDAGNE-CANIGOU_20230215142300.xml", 74),
        ("Massif%20Inconnu_20260211161900.xml", None),
    ],
)
def test_resolution_du_massif_depuis_le_nom(filename, massif_id) -> None:
    assert massif_id_from_filename(filename) == massif_id


def test_slugify_neutralise_casse_espaces_et_tirets() -> None:
    assert slugify("ASPE-OSSAU") == slugify("Aspe Ossau") == slugify("Aspe%20Ossau") == "aspeossau"


def test_daterange_bornes_incluses() -> None:
    jours = list(daterange(date(2026, 2, 1), date(2026, 2, 3)))
    assert jours == [date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3)]


def test_saison_de_septembre_a_aout() -> None:
    jours = list(season_days(2025))
    assert jours[0] == date(2025, 9, 1)
    assert jours[-1] == date(2026, 8, 31)


def make_fetcher(tmp_path, handler) -> BraFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return BraFetcher(tmp_path, client=client)


def test_listing_extrait_les_noms(tmp_path) -> None:
    def handler(request):
        return httpx.Response(200, text=LISTING)

    with make_fetcher(tmp_path, handler) as fetcher:
        noms = fetcher.list_day(date(2026, 2, 11))
    assert "Aspe%20Ossau_20260211162100.xml" in noms
    assert len(noms) == 3


def test_filtre_par_massif(tmp_path) -> None:
    def handler(request):
        if request.url.path.endswith("/xml/"):
            return httpx.Response(200, text=LISTING)
        return httpx.Response(200, content=XML)

    with make_fetcher(tmp_path, handler) as fetcher:
        paths = fetcher.fetch_day(date(2026, 2, 11), massif_ids=[65])
    assert [p.name for p in paths] == ["Aspe Ossau_20260211162100.xml"]
    assert fetcher.stats.skipped == 2


def test_redirection_suivie(tmp_path) -> None:
    """files.data.gouv.fr repond 302 vers un bucket S3 ; sans suivi on obtient du HTML."""
    def handler(request):
        if request.url.host == "files.data.gouv.fr" and request.url.path.endswith(".xml"):
            return httpx.Response(302, headers={"location": "https://bucket.example/fichier.xml"})
        if request.url.host == "bucket.example":
            return httpx.Response(200, content=XML)
        return httpx.Response(200, text=LISTING)

    with make_fetcher(tmp_path, handler) as fetcher:
        path = fetcher.fetch_file(date(2026, 2, 11), "Aspe%20Ossau_20260211162100.xml")
    assert path is not None
    assert path.read_bytes().startswith(b"<?xml")


def test_reponse_html_rejetee(tmp_path) -> None:
    """Une redirection non suivie renvoie du HTML sous une extension .xml."""
    def handler(request):
        return httpx.Response(200, text="<html><head><title>302 Found</title></head></html>")

    with make_fetcher(tmp_path, handler) as fetcher:
        path = fetcher.fetch_file(date(2026, 2, 11), "Aspe%20Ossau_20260211162100.xml")
    assert path is None
    assert fetcher.stats.errors == 1


def test_cache_evite_un_second_telechargement(tmp_path) -> None:
    appels = {"n": 0}

    def handler(request):
        appels["n"] += 1
        return httpx.Response(200, content=XML)

    with make_fetcher(tmp_path, handler) as fetcher:
        fetcher.fetch_file(date(2026, 2, 11), "Aspe%20Ossau_20260211162100.xml")
        fetcher.fetch_file(date(2026, 2, 11), "Aspe%20Ossau_20260211162100.xml")

    assert appels["n"] == 1
    assert fetcher.stats.downloaded == 1
    assert fetcher.stats.cached == 1


def test_jour_absent_comptabilise(tmp_path) -> None:
    def handler(request):
        return httpx.Response(404)

    with make_fetcher(tmp_path, handler) as fetcher:
        assert fetcher.list_day(date(2016, 1, 1)) == []
        assert fetcher.stats.missing_days == 1


def test_nom_de_fichier_decode_dans_le_cache(tmp_path) -> None:
    def handler(request):
        return httpx.Response(200, content=XML)

    with make_fetcher(tmp_path, handler) as fetcher:
        path = fetcher.fetch_file(date(2026, 2, 11), "Aspe%20Ossau_20260211162100.xml")
    assert path.name == "Aspe Ossau_20260211162100.xml"
    assert path.parent == tmp_path / "2026/02/11"


def test_bom_utf8_accepte(tmp_path) -> None:
    """Les BRA anterieurs a 2024 commencent par un BOM UTF-8 avant le prologue."""
    def handler(request):
        return httpx.Response(200, content=b"\xef\xbb\xbf" + XML)

    with make_fetcher(tmp_path, handler) as fetcher:
        path = fetcher.fetch_file(date(2017, 2, 14), "ASPE-OSSAU_20170214145313.xml")
    assert path is not None
    assert fetcher.stats.errors == 0


def test_telechargement_concurrent(tmp_path) -> None:
    """Le mode concurrent doit rendre les memes fichiers que le mode sequentiel."""
    def handler(request):
        if request.url.path.endswith("/xml/"):
            return httpx.Response(200, text=LISTING)
        return httpx.Response(200, content=XML)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    fetcher = BraFetcher(tmp_path, workers=4, client=client)
    with fetcher:
        paths = fetcher.fetch_day(date(2026, 2, 11))
    assert len(paths) == 3
    assert fetcher.stats.downloaded == 3
    assert all(p.read_bytes().startswith(b"<?xml") for p in paths)


def test_aucun_fichier_partiel_laisse(tmp_path) -> None:
    """L'ecriture passe par un fichier temporaire renomme."""
    def handler(request):
        if request.url.path.endswith("/xml/"):
            return httpx.Response(200, text=LISTING)
        return httpx.Response(200, content=XML)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with BraFetcher(tmp_path, workers=3, client=client) as fetcher:
        fetcher.fetch_day(date(2026, 2, 11))
    assert list(tmp_path.rglob("*.part")) == []
