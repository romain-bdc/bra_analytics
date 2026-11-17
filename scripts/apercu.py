"""Capture de la carte d'accueil a 1200 x 630 (format Open Graph) -> templates/apercu.png.

`bra site` copie ce fichier dans `site/apercu.png` ; il sert d'image de lien (og:image) et
d'illustration de la reutilisation sur data.gouv.fr. A relancer quand la carte change :

    uv run python scripts/apercu.py

Chromium headless seul (le meme que les tests), aucune dependance Python ajoutee.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bra_analytics.site import generer

SORTIE = Path(__file__).parent.parent / "src" / "bra_analytics" / "templates" / "apercu.png"


def chromium() -> str:
    if os.environ.get("BRA_CHROMIUM"):
        return os.environ["BRA_CHROMIUM"]
    trouves = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
    trouve = trouves[0] if trouves else shutil.which("chromium") or shutil.which("chromium-browser")
    if trouve is None:
        raise SystemExit("Chromium headless introuvable : definir BRA_CHROMIUM")
    return trouve


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        generer("warehouse/bra.duckdb", site, allow_dirty=True)
        # Image de lien : le titre, la phrase qui dit ce que la couleur mesure, la carte en grand et
        # sa legende. Commandes, exports, textes
        # d'explication et reperes sont retires : ils ne se lisent pas a cette taille.
        page = site / "carte.html"
        cadrage = ("<style>.partage-nav,.lede details,.metriques,.echelle,.cote .toggle,.exports,.zoom,.reperes,"
                   ".tables,footer{display:none!important}"
                   ".wrap{padding:0 40px}header{padding:22px 0 4px}h1{font-size:36px}.lede{font-size:16px;margin-top:6px;max-width:none}"
                   ".vue{grid-template-columns:270px minmax(0,1fr)!important;column-gap:24px}"
                   ".vue>.cote{position:static;margin-top:120px;box-shadow:none}"
                   ".carte svg{height:510px!important;min-height:0!important}</style></html>")
        page.write_text(page.read_text(encoding="utf-8").replace("</html>", cadrage), encoding="utf-8")
        subprocess.run(
            [chromium(), "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,630",
             "--virtual-time-budget=8000", f"--screenshot={SORTIE}", f"file://{site / 'carte.html'}"],
            check=True, capture_output=True,
        )
    print(f"{SORTIE} ({SORTIE.stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    sys.exit(main())
