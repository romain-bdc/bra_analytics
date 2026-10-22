"""Site statique : les quatre ecrans ecrits cote a cote dans un meme dossier.

Les pages se lient deja entre elles par leur nom de fichier (`partage.ECRANS`, barre de
navigation de `partage.js`) : il suffit donc de les ecrire au meme endroit pour obtenir un
site, sans serveur applicatif. `index.html` est la carte, l'ecran d'accueil (spec § 6) ; c'est
une copie et non une redirection, pour rester lisible depuis un simple `file://`.

La liste des ecrans vient de `partage.ECRANS` ; chaque ecran est un module du meme nom qui
expose `render(db_path, out_path, standalone)`.
"""

from __future__ import annotations

import functools
import http.server
from importlib import import_module
from pathlib import Path

from .partage import ECRANS


def generer(db_path: str | Path = "warehouse/bra.duckdb", out_dir: str | Path = "site") -> list[Path]:
    """Ecrit chaque ecran et `index.html` ; renvoie les fichiers ecrits, ordre de navigation."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for ecran in ECRANS:
        module = import_module(f".{ecran.id}", __package__)
        ecrits.append(module.render(db_path, out / ecran.fichier, standalone=True))
    accueil = out / "index.html"
    accueil.write_text((out / ECRANS[0].fichier).read_text(encoding="utf-8"), encoding="utf-8")
    return [*ecrits, accueil]


def servir(out_dir: str | Path, port: int = 8000) -> None:
    """Sert le dossier tel quel, en lecture seule (http.server de la bibliotheque standard)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"site servi sur http://127.0.0.1:{port}/ (Ctrl-C pour arreter)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
