"""Telechargement incremental des archives BRA depuis files.data.gouv.fr.

Deux pieges de l'archive sont traites ici :

- `files.data.gouv.fr` repond **302** vers un bucket OVH S3. Sans suivi de
  redirection on recupere 138 octets de HTML nommes `.xml` : l'echec est
  silencieux. On suit les redirections et on valide le prologue XML.
- Le dossier de date ne correspond pas toujours a `DATEBULLETIN` (vu en 2016).
  Le cache local reproduit donc l'arborescence *source* ; le partitionnement
  metier est recalcule au moment du build, depuis le contenu.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote

import httpx
from threading import Lock

# `slugify` et `SLUG_TO_ID` appartiennent au referentiel, pas au telechargement :
# ils sont definis dans `massifs` et repris ici pour les appelants historiques.
from .massifs import SLUG_TO_ID, slugify

BASE_URL = "https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA"

_HREF = re.compile(r'href="[^"]*/xml/([^"]+\.xml)"', re.IGNORECASE)

# Les BRA anterieurs a 2024 sont prefixes d'un BOM UTF-8.
_BOM = b"\xef\xbb\xbf"


def massif_id_from_filename(filename: str) -> int | None:
    """Devine l'ID de massif d'apres le nom de fichier.

    Sert uniquement a filtrer les telechargements. L'identification faisant foi
    reste l'attribut `ID` du XML : les noms de fichiers changent de graphie
    entre epoques et comportent des irregularites.
    """
    stem = unquote(filename).rsplit(".", 1)[0]
    stem = re.sub(r"_?\d{14}$", "", stem)
    return SLUG_TO_ID.get(slugify(stem))


def daterange(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def season_days(season_start: int) -> Iterator[date]:
    """Jours d'une saison nivologique : 1er septembre -> 31 aout suivant."""
    return daterange(date(season_start, 9, 1), date(season_start + 1, 8, 31))


@dataclass
class FetchStats:
    listed: int = 0
    downloaded: int = 0
    cached: int = 0
    skipped: int = 0
    missing_days: int = 0
    errors: int = 0


class BraFetcher:
    """Client d'ingestion avec cache disque.

    Le cache rend l'ingestion idempotente : un fichier deja present n'est pas
    retelecharge. Les archives sont immuables, sauf reedition d'un bulletin qui
    cree un *nouveau* nom de fichier (horodatage de diffusion different).
    """

    def __init__(
        self,
        cache_dir: str | Path = "data/raw",
        *,
        timeout: float = 60.0,
        workers: int = 6,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.workers = max(1, workers)
        self._client = client or httpx.Client(
            follow_redirects=True,  # indispensable : 302 vers le bucket OVH
            timeout=timeout,
            # Le pool doit suivre le nombre de workers, sinon ils se bloquent
            # mutuellement en attendant une connexion libre.
            limits=httpx.Limits(max_connections=self.workers * 2,
                                max_keepalive_connections=self.workers),
            headers={"User-Agent": "bra-analytics/0.1 (open data BRA)"},
        )
        self._lock = Lock()
        self.stats = FetchStats()

    def __enter__(self) -> BraFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def list_day(self, day: date) -> list[str]:
        """Noms de fichiers publies pour une journee. Liste vide si le jour manque."""
        url = f"{BASE_URL}/{day:%Y/%m/%d}/xml/"
        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            self.stats.errors += 1
            return []
        if response.status_code == 404:
            self.stats.missing_days += 1
            return []
        if response.status_code >= 400:
            self.stats.errors += 1
            return []
        names = sorted(set(_HREF.findall(response.text)))
        self.stats.listed += len(names)
        return names

    def fetch_file(self, day: date, filename: str) -> Path | None:
        """Telecharge un fichier s'il n'est pas deja en cache. Rend son chemin local."""
        target = self.cache_dir / f"{day:%Y/%m/%d}" / unquote(filename)
        if target.exists() and target.stat().st_size > 0:
            with self._lock:
                self.stats.cached += 1
            return target

        url = f"{BASE_URL}/{day:%Y/%m/%d}/xml/{filename}"
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            with self._lock:
                self.stats.errors += 1
            return None

        payload = response.content
        # Garde-fou : une redirection non suivie renvoie une page HTML courte
        # portant tout de meme l'extension .xml. Les fichiers anterieurs a 2024
        # commencent par un BOM UTF-8, qu'il faut ecarter avant le test.
        if not payload.lstrip().removeprefix(_BOM).lstrip()[:5].startswith(b"<?xml"):
            with self._lock:
                self.stats.errors += 1
            return None

        target.parent.mkdir(parents=True, exist_ok=True)
        # Ecriture atomique : un fichier partiel serait pris pour un cache valide
        # au prochain passage.
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        with self._lock:
            self.stats.downloaded += 1
        return target

    def fetch_day(self, day: date, massif_ids: Iterable[int] | None = None) -> list[Path]:
        """Telecharge une journee, filtree sur des massifs si demande."""
        wanted = set(massif_ids) if massif_ids is not None else None
        retenus = []
        for name in self.list_day(day):
            if wanted is not None:
                guessed = massif_id_from_filename(name)
                # Un nom non reconnu est telecharge malgre le filtre : mieux vaut
                # un fichier en trop qu'une lacune due a une graphie inedite.
                if guessed is not None and guessed not in wanted:
                    self.stats.skipped += 1
                    continue
            retenus.append(name)

        if not retenus:
            return []
        if self.workers == 1:
            resultats = [self.fetch_file(day, name) for name in retenus]
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                resultats = list(pool.map(lambda n: self.fetch_file(day, n), retenus))
        return [p for p in resultats if p is not None]

    def fetch_range(
        self,
        start: date,
        end: date,
        massif_ids: Iterable[int] | None = None,
        *,
        progress: bool = False,
    ) -> list[Path]:
        paths: list[Path] = []
        for day in daterange(start, end):
            got = self.fetch_day(day, massif_ids)
            paths.extend(got)
            if progress and got:
                print(f"  {day} : {len(got)} fichiers", flush=True)
        return paths
