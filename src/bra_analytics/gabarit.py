"""Insertion des payloads dans les gabarits d'ecran.

Motif commun a tous les ecrans : un payload JSON construit cote Python est insere
dans un gabarit HTML par le marqueur `__DONNEES__`, et tout le filtrage se fait
cote client, sans serveur. Ce module ne porte que ce motif et l'encodage d'un jour
par caractere (`ABSENT`, `SANS_INDICE`) lu par la fiche.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import partage

COMMUN = Path(__file__).parent / "templates" / "commun.js"
PARTAGE = Path(__file__).parent / "templates" / "partage.js"

# Un caractere par jour, dans la chaine `serie` de chaque massif.
ABSENT = "."  # aucun bulletin ce jour-la
SANS_INDICE = "0"  # bulletin publie sans estimation chiffree (risque_estime = false)


# Le gabarit ne porte ni doctype ni <html> : sous cette forme il s'insere tel quel
# dans un hote qui fournit deja le squelette. Le fichier autonome le reconstitue.
ENTETE = (
    "<!doctype html>\n"
    '<html lang="fr">\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)


def injecter(gabarit: Path, data: dict, standalone: bool = True) -> str:
    """Insere le payload dans un gabarit par son marqueur `__DONNEES__`.

    Partage par tous les ecrans : c'est le
    motif de l'interface, et il n'existe qu'une fois.
    """
    html = gabarit.read_text(encoding="utf-8")
    if "__DONNEES__" not in html:
        raise SystemExit(f"gabarit sans marqueur __DONNEES__ : {gabarit}")
    # separators compact : le payload represente l'essentiel du poids de la page.
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # `</script>` dans une chaine JSON fermerait la balise hote.
    blob = blob.replace("</", "<\\/")
    # Les aides JavaScript partagees entre ecrans passent en premier : elles ne
    # contiennent pas `__DONNEES__`, et un `__COMMUN__` apparaissant dans une
    # donnee ne doit jamais etre remplace.
    # Meme raison : `partage.js` ne porte que le marqueur `__ECRANS__`, remplace
    # ici avant que le moindre payload entre dans la page.
    if "__PARTAGE__" in html:
        ecrans = json.dumps([e._asdict() for e in partage.ECRANS], ensure_ascii=False)
        js = PARTAGE.read_text(encoding="utf-8").replace("__ECRANS__", ecrans)
        html = html.replace("__PARTAGE__", js, 1)
    if "__COMMUN__" in html:
        html = html.replace("__COMMUN__", COMMUN.read_text(encoding="utf-8"), 1)
    page = html.replace("__DONNEES__", blob)
    if standalone:
        page = ENTETE + page + "</html>\n"
    return page
