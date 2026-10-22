"""`bra publier` : branche orpheline, idempotence, nettoyage du worktree, sur un remote nu local."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bra_analytics.publier import BRANCHE, publier


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def depot(tmp_path):
    nu = tmp_path / "origin.git"
    git("init", "--bare", "-b", "main", str(nu), cwd=tmp_path)
    d = tmp_path / "depot"
    git("init", "-b", "main", str(d), cwd=tmp_path)
    git("config", "user.email", "t@example.org", cwd=d)
    git("config", "user.name", "Test", cwd=d)
    (d / "code.py").write_text("x = 1\n")
    git("add", ".", cwd=d)
    git("commit", "-m", "initial", cwd=d)
    git("remote", "add", "origin", str(nu), cwd=d)
    return d, nu


def ecrire_site(d: Path, pages: dict[str, str], genere: str = "2026-01-01T00:00:00") -> Path:
    site = d / "site"
    if site.exists():
        for p in sorted(site.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    site.mkdir(exist_ok=True)
    (site / "version.json").write_text(json.dumps({"commit": "abcdef1234567", "genere": genere, "archive": "2026-06-01"}))
    (site / ".nojekyll").write_text("")
    for nom, texte in pages.items():
        (site / nom).write_text(texte)
    return site


def test_premier_appel_cree_la_branche_orpheline(depot):
    d, nu = depot
    site = ecrire_site(d, {"index.html": "a", "carte.html": "b"})
    bilan = publier(site, depot=d)
    assert sorted(bilan["ajoutes"]) == [".nojekyll", "carte.html", "index.html", "version.json"]
    # orpheline : un seul commit, qui est sa propre racine, sans lien avec main
    assert git("rev-list", "--count", BRANCHE, cwd=nu) == "1"
    assert git("rev-list", "--max-parents=0", BRANCHE, cwd=nu) == git("rev-parse", BRANCHE, cwd=nu)
    assert git("log", "-1", "--format=%s", BRANCHE, cwd=nu) == "site : archive jusqu'au 2026-06-01, depuis abcdef1"
    assert "code.py" not in git("ls-tree", "-r", "--name-only", BRANCHE, cwd=nu)


def test_second_appel_sans_changement_ne_commit_pas(depot):
    d, nu = depot
    site = ecrire_site(d, {"index.html": "a"})
    publier(site, depot=d)
    avant = git("rev-parse", BRANCHE, cwd=nu)
    # seule la date de generation change
    ecrire_site(d, {"index.html": "a"}, genere="2026-02-02T00:00:00")
    bilan = publier(site, depot=d)
    assert bilan == {"ajoutes": [], "modifies": [], "supprimes": []}
    assert git("rev-parse", BRANCHE, cwd=nu) == avant


def test_ajoutes_modifies_supprimes_et_dry_run(depot):
    d, nu = depot
    site = ecrire_site(d, {"index.html": "a", "vieux.html": "v"})
    publier(site, depot=d)
    avant = git("rev-parse", BRANCHE, cwd=nu)
    site = ecrire_site(d, {"index.html": "a2", "nouveau.html": "n"}, genere="2026-03-03T00:00:00")
    bilan = publier(site, dry_run=True, depot=d)
    assert bilan["ajoutes"] == ["nouveau.html"]
    assert sorted(bilan["modifies"]) == ["index.html", "version.json"]
    assert bilan["supprimes"] == ["vieux.html"]
    assert git("rev-parse", BRANCHE, cwd=nu) == avant  # le dry-run ne pousse rien
    publier(site, depot=d)
    assert git("rev-list", "--count", BRANCHE, cwd=nu) == "2"
    assert "vieux.html" not in git("ls-tree", "-r", "--name-only", BRANCHE, cwd=nu)


def test_worktree_nettoye_apres_une_erreur(depot):
    d, nu = depot
    site = ecrire_site(d, {"index.html": "a"})
    git("remote", "set-url", "origin", str(nu) + "-inexistant", cwd=d)  # le push echoue
    with pytest.raises(subprocess.CalledProcessError):
        publier(site, depot=d)
    # seul le worktree principal reste
    assert len(git("worktree", "list", cwd=d).splitlines()) == 1


def test_refuse_sans_site_construit(depot):
    d, _ = depot
    with pytest.raises(SystemExit, match="bra site"):
        publier(d / "site", depot=d)
