"""Publication de `site/` sur la branche orpheline `gh-pages` (T19).

Le build se fait en local (13 Go de XML, 7 Go de memoire) : seul le resultat, quelques centaines
de Ko de HTML, part sur `origin`. Pages sert la branche telle quelle, sans Action ni secret.

Mecanique : un worktree temporaire sur `gh-pages`, contenu remplace en entier par celui de
`site/`, commit, push. Jamais de force-push : si `origin/gh-pages` a avance, le push echoue et
l'echec est rapporte tel quel. Uniquement `subprocess` + `git`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

BRANCHE = "gh-pages"


def _git(*args: str, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _sorti(r: subprocess.CompletedProcess) -> str:
    return r.stdout.strip()


def _existe(ref: str, depot: Path) -> bool:
    return _git("rev-parse", "--verify", "--quiet", ref, cwd=depot, check=False).returncode == 0


def _vider(dossier: Path) -> None:
    """Efface tout sauf `.git` (fichier de liaison du worktree)."""
    for p in dossier.iterdir():
        if p.name == ".git":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def _message(site: Path) -> str:
    v = json.loads((site / "version.json").read_text(encoding="utf-8"))
    court = (v.get("commit") or "inconnu")[:7]
    return f"site : archive jusqu'au {v.get('archive')}, depuis {court}"


def publier(site: str | Path = "site", dry_run: bool = False, depot: str | Path = ".", remote: str = "origin") -> dict[str, list[str]]:
    """Pousse `site/` sur `gh-pages` ; renvoie les fichiers `ajoutes`, `modifies`, `supprimes`.

    Sans changement, aucun commit : relancer ne pollue pas la branche.
    """
    site, depot = Path(site).resolve(), Path(depot).resolve()
    if not (site / "version.json").is_file():
        raise SystemExit(f"{site} absent ou incomplet : lancer `uv run bra site` d'abord")
    _git("fetch", remote, BRANCHE, cwd=depot, check=False)
    distante = f"{remote}/{BRANCHE}"
    existe = _existe(f"refs/remotes/{distante}", depot)

    tmp = Path(tempfile.mkdtemp(prefix="bra-gh-pages-"))
    wt = tmp / "wt"
    try:
        if existe:
            # Detache : la branche locale `gh-pages` n'a pas a exister ni a etre a jour.
            _git("worktree", "add", "--detach", str(wt), distante, cwd=depot)
        else:
            _git("worktree", "add", "--detach", str(wt), "HEAD", cwd=depot)
            _git("checkout", "--orphan", BRANCHE, cwd=wt)
            _git("rm", "-rf", "--quiet", ".", cwd=wt, check=False)
        _vider(wt)
        shutil.copytree(site, wt, dirs_exist_ok=True)
        _git("add", "--all", "--force", cwd=wt)
        etat = _sorti(_git("diff", "--cached", "--name-status", "--no-renames", cwd=wt))
        # version.json change a chaque generation : sans autre changement il ne justifie pas un commit.
        lignes = [l.split("\t", 1) for l in etat.splitlines() if l]
        bilan = {
            "ajoutes": [f for s, f in lignes if s == "A"],
            "modifies": [f for s, f in lignes if s == "M"],
            "supprimes": [f for s, f in lignes if s == "D"],
        }
        if not lignes or (existe and [f for _, f in lignes] == ["version.json"]):
            return {"ajoutes": [], "modifies": [], "supprimes": []}
        if dry_run:
            return bilan
        _git("commit", "--quiet", "-m", _message(site), cwd=wt)
        _git("push", remote, f"HEAD:refs/heads/{BRANCHE}", cwd=wt)
        return bilan
    finally:
        _git("worktree", "remove", "--force", str(wt), cwd=depot, check=False)
        _git("worktree", "prune", cwd=depot, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
