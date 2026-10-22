# Spec — Publication publique des écrans sur GitHub Pages

Destinataire : Claude Code, travaillant dans ce repo. À lire après `CLAUDE.md`, dont toutes les
règles restent applicables.

## 1. Objectif

Rendre les quatre écrans (`carte`, `fiche`, `comparaison`, `exploration`) consultables
publiquement à une URL stable, pour les déclarer comme **réutilisation** du jeu « archive BRA »
sur data.gouv.fr.

- Hébergement : **GitHub Pages**, repo `romain-bdc/bra_analytics` rendu **public**.
- URL publique : **`https://romain-bdc.github.io/bra_analytics/`**. Elle est stable tant que
  ni le repo ni le compte ne sont renommés : GitHub redirige le code après un renommage, **pas**
  l'URL Pages. Décision prise : on ne renomme rien, et on n'achète pas de domaine pour l'instant.
- Rien ne change dans l'architecture : le front reste statique, sans serveur, sans framework.

## 2. Décisions déjà prises (ne pas rouvrir)

| Sujet | Décision | Raison |
| --- | --- | --- |
| Où se fait le build | **En local**, jamais en CI | `bra build` exige 13 Go de XML (3 h de fetch) et 7 Go de RAM, pour quelques centaines de Ko de HTML en sortie |
| Comment on déploie | Le site généré est poussé sur une branche orpheline **`gh-pages`** ; Pages sert cette branche (« Deploy from a branch », racine) | Aucune Action à maintenir, aucun secret ; `main` ne versionne toujours aucune page générée (règle de `CLAUDE.md` respectée) |
| Polices | **Auto-hébergées** dans le site ; plus aucun appel à `fonts.googleapis.com` / `fonts.gstatic.com` | Google Fonts transmet l'IP de chaque visiteur à Google sans consentement, ce qui est contraire au RGPD (LG München, 20 janvier 2022). IBM Plex est sous licence OFL : la redistribuer est autorisé |
| Point d'entrée | `index.html` redirige vers `carte.html` **en conservant le fragment d'URL** | L'état des écrans vit dans `#...` (T15) : une redirection qui le perd casse les liens partagés |

## 3. À trancher par Romain avant la mise en public

Claude Code **ne choisit pas** ces points ; il les présente et attend la réponse.

1. **Licence du code.** Il n'y a pas de fichier `LICENSE` aujourd'hui, et un repo public sans
   licence n'est pas réutilisable. Options usuelles : MIT (la plus permissive), Licence
   Ouverte 2.0 / etalab-2.0 (cohérente avec les données), EUPL-1.2 (copyleft européen).
2. **Résultat de l'audit de l'historique** (§ 4.1) s'il remonte quoi que ce soit.

## 4. Tâches

Découpage en PR. Chaque tâche suit le format de `docs/taches.md` et y est ajoutée sous un
« Lot 5 — Publication » (T16 à T20).

### T16. Audit avant passage en public

Le repo a toujours été privé : son historique n'a jamais été relu en vue d'une publication.

- Travailler sur un **clone complet**, pas un clone `--depth 1` : un clone superficiel ne voit
  pas l'historique.
- Secrets : lancer `gitleaks detect --source . --log-opts="--all"` (outil installé hors du repo,
  **pas** ajouté aux dépendances). À défaut, `git log --all -p` filtré sur `token|secret|password|api[_-]?key|BEGIN .*PRIVATE`.
- Fichiers lourds ou interdits jamais committés : `git rev-list --objects --all` croisé avec
  `git cat-file --batch-check`, et lister tout objet de plus de 1 Mo ainsi que tout `*.xml` hors
  de `tests/fixtures/` et `tests/series/`, `*.parquet`, `*.duckdb`, `*.html` généré.
- Données personnelles : adresses mail, chemins absolus de machine (`/Users/...`, `/home/...`)
  dans les docs et les journaux committés.
- **Ne réécrire aucun historique** (`filter-repo`, force-push) sans accord explicite : rapporter
  ce qui a été trouvé et s'arrêter.

**Fait quand** : un rapport (dans la description de PR, pas dans le repo) liste chaque contrôle
et son résultat ; aucune trouvaille ouverte ; le fichier `LICENSE` choisi par Romain est committé.

### T17. Polices auto-hébergées

- Récupérer les `woff2` depuis le paquet npm **`@ibm/plex`** (version épinglée et notée dans la
  doc) : IBM Plex Sans 400, 500, 600 et IBM Plex Mono 400, 500, sous-ensemble **latin** seulement.
  Ce sont les graisses demandées aujourd'hui par l'URL Google Fonts des quatre gabarits ;
  vérifier qu'aucune autre n'est employée dans le CSS avant de figer la liste.
- Les versionner sous `src/bra_analytics/templates/polices/`, avec le texte de la licence OFL
  (`OFL.txt`) à côté. Ce sont des actifs sources, pas des sorties générées : la règle « ne pas
  versionner le généré » ne s'applique pas.
- Un seul bloc `@font-face`, dans un fichier partagé, inséré par un marqueur de gabarit au même
  titre que `__COMMUN__` et `__PARTAGE__`, au lieu d'être recopié dans quatre gabarits.
  `font-display: swap`. Chemins **relatifs** (`polices/...`) : le site est servi sous
  `/bra_analytics/`, pas à la racine du domaine, donc un chemin absolu `/polices/` casserait.
- Retirer des quatre gabarits les trois lignes `<link>` vers `fonts.googleapis.com` et
  `fonts.gstatic.com`.
- Les piles de repli `system-ui` / `ui-monospace` déjà en place restent : une page générée en
  local et ouverte hors du dossier du site s'affiche sans les polices, sans erreur.

**Fait quand** : `grep -r "googleapis\|gstatic" src/` ne renvoie rien ; un test vérifie
qu'aucune page générée ne contient ces domaines ; dans Chromium headless (comme
`tests/test_partage.py`), `document.fonts.check('500 14px "IBM Plex Sans"')` est vrai sur une
page servie depuis `site/`.

### T18. Commande `bra site`

```bash
uv run bra site                 # -> site/ (dossier entièrement reconstruit)
uv run bra site --out autre/
```

Assemble le site complet, prêt à servir, depuis `warehouse/bra.duckdb` :

```
site/
  index.html           redirection vers carte.html, fragment conservé
  carte.html
  fiche.html
  comparaison.html
  exploration.html
  polices/*.woff2, OFL.txt
  version.json         { "commit": <sha de main>, "genere": <ISO>, "archive": <dernier jour couvert> }
  .nojekyll            sans lui, Pages passe le contenu dans Jekyll
```

- Réutiliser les `render()` existants des quatre écrans avec `standalone=True` ; la liste des
  fichiers vient de `partage.ECRANS`, **jamais** d'une liste recopiée (même règle que
  `fenetres.py` : une liste recopiée divergera).
- `index.html` : `<meta http-equiv="refresh">` vers `carte.html` en repli sans JavaScript, et
  `location.replace("carte.html" + location.hash)` en script. Il porte aussi le
  `<title>` et la `<meta name="description">` que data.gouv.fr et les aperçus de liens liront.
- Chaque page reçoit `<meta name="description">` et les balises Open Graph minimales
  (`og:title`, `og:description`, `og:image` pointant vers la capture de T20).
- **Idempotente** : `site/` est supprimé puis reconstruit, sans état résiduel. Refuser de
  tourner si `warehouse/bra.duckdb` est absent, avec un message qui dit quoi lancer.
- `site/` s'ajoute au `.gitignore`.
- `version.json` refuse un arbre de travail sale (`git status --porcelain` non vide) sauf
  `--allow-dirty` : une version publiée doit pointer vers un commit qui existe.

**Fait quand** : tests sur une base construite à partir des fixtures : les cinq pages existent ;
tout lien de navigation (`a[data-ecran]`) pointe vers un fichier présent dans `site/` ;
`index.html#m=68&s=2023-2024` aboutit sur `carte.html#m=68&s=2023-2024` ; deux exécutions
successives produisent le même arbre, à `genere` près.

### T19. Commande `bra publier`

```bash
uv run bra publier --dry-run    # montre ce qui changerait, ne pousse rien
uv run bra publier              # commit + push sur gh-pages
```

- Prend le contenu de `site/` (construit par `bra site`, jamais reconstruit implicitement) et
  le pousse sur la branche **orpheline** `gh-pages` de `origin`.
- Mécanique : `git worktree add` dans un dossier temporaire sur `gh-pages` (création de la
  branche orpheline si elle n'existe pas), remplacement intégral du contenu par celui de
  `site/`, commit, push, retrait du worktree, même en cas d'erreur (`try/finally`).
  Uniquement `subprocess` + `git` : aucune dépendance nouvelle.
- Message de commit : `site : archive jusqu'au <archive>, depuis <commit court>`.
- **Aucun commit si rien n'a changé** : relancer la commande ne pollue pas la branche.
- **Jamais de force-push.**

**Fait quand** : le `--dry-run` liste les fichiers ajoutés, modifiés, supprimés ; un test sur un
dépôt git temporaire (remote nu local) vérifie : création de la branche orpheline au premier
appel, absence de commit au second appel sans changement, worktree nettoyé après une erreur.

### T20. Mise en ligne et déclaration data.gouv.fr

Étapes manuelles pour Romain, préparées par Claude Code dans `docs/publication.md` :

1. Passer le repo en public (Settings → General → Danger Zone), **après** T16.
2. Settings → Pages → Source : « Deploy from a branch », branche `gh-pages`, dossier `/ (root)`.
   Cocher « Enforce HTTPS ».
3. `bra site && bra publier`, puis vérifier `https://romain-bdc.github.io/bra_analytics/` :
   les quatre écrans, la navigation, un lien avec fragment, et dans l'onglet réseau du
   navigateur aucune requête vers un domaine tiers.
4. Capture d'écran de la carte d'accueil à 1200 × 630 (format Open Graph) : produite par un
   script Playwright headless qui ouvre `site/carte.html`, et copiée dans `site/apercu.png` par
   `bra site`. Elle sert aussi d'image pour data.gouv.fr.
5. Ajouter l'URL publique en tête du `README.md` et dans la description du repo GitHub.
6. Déclarer la réutilisation sur data.gouv.fr (« Publier une réutilisation » depuis la page du
   jeu de données) : Claude Code rédige dans `docs/publication.md` un brouillon de chaque champ.
   - **Titre** : décrit l'usage, pas le nom du site, par exemple « Historique du risque
     d'avalanche par massif depuis 2016 ».
   - **Type** : Visualisation.
   - **URL** : `https://romain-bdc.github.io/bra_analytics/`.
   - **Description** : ton neutre et méthodologique, un texte promotionnel pouvant être
     supprimé. Couverture (mars 2016 → juin 2026, 36 massifs), ce que chaque écran montre,
     les limites qui conditionnent la lecture (fenêtre `coeur`, saisons non comparables, fin
     de la sentinelle `RISQUE1=-1` en juin 2021, arrêt de mars 2020), lien vers le code et le
     glossaire.
   - **Jeux de données associés** : l'archive BRA, qui porte aussi les contours ; le contour
     IGN Admin Express si le jeu est référencé sur data.gouv.fr.
   - **Image** : la capture de l'étape 4.
   - Créer d'abord en **brouillon** pour relecture.

**Fait quand** : l'URL publique sert les quatre écrans sans requête tierce ; la réutilisation
est en ligne sur data.gouv.fr ; le README porte le lien ; `docs/publication.md` décrit la
procédure de republication (`bra build --replace && bra check && bra site && bra publier`).

## 5. Ordre et découpage

```
T16 (audit, LICENSE)  ──┐
T17 (polices)  ─────────┼──> T18 (bra site) ──> T19 (bra publier) ──> T20 (mise en ligne)
```

T16 et T17 sont indépendantes. Une PR par tâche, à part T20 qui est surtout manuelle.

## 6. Hors périmètre

Nom de domaine personnalisé (l'URL github.io est retenue ; si un domaine est pris plus tard,
seuls un fichier `CNAME` dans `site/` et l'URL data.gouv.fr changent), mesure d'audience,
déploiement par GitHub Actions, publication des Parquet comme jeu de données data.gouv.fr
(intéressant, mais c'est un autre chantier : schéma documenté, versionnement, mise à jour).
