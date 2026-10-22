"""Site statique : les quatre ecrans ecrits cote a cote dans un meme dossier.

Les pages se lient deja entre elles par leur nom de fichier (`partage.ECRANS`, barre de
navigation de `partage.js`) : il suffit donc de les ecrire au meme endroit pour obtenir un
site, sans serveur applicatif. `index.html` redirige vers la carte, l'ecran d'accueil (spec
§ 6), en conservant le fragment d'URL : l'etat des ecrans y vit (T15), et une redirection qui
le perd casse les liens partages.

La liste des ecrans vient de `partage.ECRANS`, jamais d'une liste recopiee ; chaque ecran est
un module du meme nom qui expose `render(db_path, out_path, standalone)`.
"""

from __future__ import annotations

import datetime as dt
import functools
import html
import http.server
import json
import shutil
import subprocess
from importlib import import_module
from pathlib import Path

import duckdb

from .partage import ECRANS

POLICES = Path(__file__).parent / "templates" / "polices"
URL_PUBLIQUE = "https://romain-bdc.github.io/bra_analytics/"
TITRE = "Historique du risque d'avalanche par massif depuis 2016"
DESCRIPTION = (
    "Bulletins d'estimation du risque d'avalanche de Météo-France, mars 2016 à juin 2026, "
    "36 massifs : carte, fiche massif-saison, comparaison de saisons et exploration."
)
DESCRIPTIONS = {
    "carte": "Carte des 36 massifs : risque moyen par saison, sur la fenêtre comparable. " + DESCRIPTION,
    "fiche": "Fiche d'un massif sur une saison : risque, neige, isotherme 0 °C et vent. " + DESCRIPTION,
    "comparaison": "Comparaison de saisons d'un massif : courbes, tableau et classement. " + DESCRIPTION,
    "exploration": "Rose des pentes, vent par orientation et situations typiques. " + DESCRIPTION,
}


def _meta(ecran_id: str, fichier: str) -> str:
    """Description et Open Graph : lus par data.gouv.fr et par les apercus de liens."""
    d = html.escape(DESCRIPTIONS[ecran_id], quote=True)
    t = html.escape(TITRE, quote=True)
    return (
        f'<meta name="description" content="{d}">\n'
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:url" content="{URL_PUBLIQUE}{fichier}">\n'
        f'<meta property="og:image" content="{URL_PUBLIQUE}apercu.png">\n'
    )


def _index(accueil: str) -> str:
    """Redirection vers l'accueil : script (fragment conserve) et meta refresh en repli."""
    t = html.escape(TITRE, quote=True)
    d = html.escape(DESCRIPTION, quote=True)
    return (
        '<!doctype html>\n<html lang="fr">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{t}</title>\n"
        f'<meta name="description" content="{d}">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:image" content="{URL_PUBLIQUE}apercu.png">\n'
        f'<meta http-equiv="refresh" content="0; url={accueil}">\n'
        f'<script>location.replace("{accueil}" + location.hash)</script>\n'
        f'<p><a href="{accueil}">{t}</a></p>\n</html>\n'
    )


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=Path(__file__).parent, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return r.stdout.strip()


def _version(db_path: str | Path, allow_dirty: bool) -> dict:
    """`commit` / `genere` / `archive` : une version publiee pointe vers un commit qui existe."""
    commit = _git("rev-parse", "HEAD")
    if commit is not None and _git("status", "--porcelain") and not allow_dirty:
        raise SystemExit("arbre de travail sale : committer avant de publier, ou relancer avec --allow-dirty")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        (archive,) = con.execute("SELECT max(jour_validite) FROM risque_journalier WHERE massif_coherent").fetchone()
    finally:
        con.close()
    return {
        "commit": commit,
        "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "archive": archive.isoformat() if archive else None,
    }


def _vider(out: Path) -> None:
    """Supprime l'ancien site ; refuse un dossier qui n'en est visiblement pas un."""
    if not out.exists():
        return
    cible, ici = out.resolve(), Path.cwd().resolve()
    if cible == ici or cible in ici.parents or (cible / ".git").exists():
        raise SystemExit(f"{out} n'est pas un dossier de site jetable : choisir un autre --out")
    shutil.rmtree(out)


def generer(
    db_path: str | Path = "warehouse/bra.duckdb",
    out_dir: str | Path = "site",
    allow_dirty: bool = False,
) -> list[Path]:
    """Reconstruit `out_dir` en entier ; renvoie les fichiers ecrits, ordre de navigation."""
    if not Path(db_path).exists():
        raise SystemExit(f"{db_path} absent : lancer `uv run bra build --replace` d'abord")
    version = _version(db_path, allow_dirty)
    out = Path(out_dir)
    _vider(out)
    out.mkdir(parents=True)
    ecrits = []
    for ecran in ECRANS:
        module = import_module(f".{ecran.id}", __package__)
        page = module.render(db_path, out / ecran.fichier, standalone=True)
        texte = page.read_text(encoding="utf-8")
        page.write_text(texte.replace("<title>", _meta(ecran.id, ecran.fichier) + "<title>", 1), encoding="utf-8")
        ecrits.append(page)
    # Les @font-face visent `polices/` en chemin relatif : le dossier voyage avec les pages.
    shutil.copytree(POLICES, out / "polices")
    accueil = out / "index.html"
    accueil.write_text(_index(ECRANS[0].fichier), encoding="utf-8")
    versionjson = out / "version.json"
    versionjson.write_text(json.dumps(version, indent=2) + "\n", encoding="utf-8")
    # Sans lui, Pages passe le contenu dans Jekyll.
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return [*ecrits, accueil, versionjson]


def servir(out_dir: str | Path, port: int = 8000) -> None:
    """Sert le dossier tel quel, en lecture seule (http.server de la bibliotheque standard)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"site servi sur http://127.0.0.1:{port}/ (Ctrl-C pour arreter)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
