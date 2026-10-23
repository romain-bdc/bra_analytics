# Contours des massifs — recherche de sources (T3)

Recherche menée le 6 octobre 2026 contre les sources primaires (sites de diffusion, dépôt
GitLab, API data.gouv.fr, fichiers téléchargés et hachés). Chaque affirmation porte sa source.
Les sections distinguent **Vérifié** (observé directement, commande ou fichier à l'appui) et
**Déduit** (raisonnement à partir des faits vérifiés, non confirmé par la source).

Les fichiers téléchargés sont restés hors du repo, dans le scratchpad de session ; aucun n'est
versionné par ce document.

## Résumé

| Question | Réponse |
| --- | --- |
| Versions EAWS | Pas de répertoire versionné sur `regions.avalanches.org` : les versions sont les **tags git** `vX.Y.Z` du dépôt `gitlab.com/eaws/eaws-regions` et les **paquets npm** du même numéro. Dernière : **v8.5.0** (21 août 2026). |
| URL épinglée | `https://gitlab.com/eaws/eaws-regions/-/raw/9f630cb1458e4931abadbe6acb965957dafa8a7a/public/micro-regions/FR_micro-regions.geojson.json` (commit du tag v8.5.0) |
| Raccordement des identifiants | 35 entités `FR-01` … `FR-74`, identifiants **sur deux chiffres**. **Manque `FR-71` (Andorre).** Aucun `FR-*` en trop, aucun suffixe ni sous-région. |
| Licence EAWS | **Trouvée : CC0 1.0** (`LICENSE` à la racine du dépôt, et `"license": "CC0-1.0"` dans le `package.json` de chaque paquet de données). Couvre le dépôt entier, données comprises. |
| Repli Météo-France | **Existe, et couvre les 36 massifs** : `Metadata_massifs.geojson` dans le jeu « Archive des Bulletins Avalanches » sur data.gouv.fr, **Licence Ouverte 2.0**, propriété `code` entière = `massif_id` du BRA. |

## 1. Micro-régions EAWS

### 1.1 Où et comment les versions sont publiées

**Vérifié.**

- `https://regions.avalanches.org/micro-regions/` renvoie une **404** (page d'erreur GitLab). Il
  n'existe pas d'index par répertoire. Même chose pour `…/micro-regions/latest/` et
  `…/micro-regions/latest/micro-regions_names/fr.json`.
- La seule page d'index est la racine `https://regions.avalanches.org/`, titrée
  « eaws-regions – geodata of avalanche warning regions ». Il s'agit d'une arborescence générée
  par `tree -H` dans le job `pages` du CI
  ([.gitlab-ci.yml](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/.gitlab-ci.yml)), et
  `regions.avalanches.org` est un CNAME vers `eaws.gitlab.io` (GitLab Pages). Les liens de
  l'arborescence sont relatifs et préfixés par `../`.
- L'arborescence ne contient **aucun répertoire de version**. Les seuls répertoires présents sont
  `micro-regions/`, `micro-regions/latest/`, `micro-regions_elevation/` (+ `latest/`),
  `micro-regions_elevation_properties/`, `micro-regions_names/`, `micro-regions_properties/`,
  `outline/`, `outline_properties/`, `pbf/`, `pmtiles/`, `schema/`, `states/` (+ `latest/`). Le
  site ne sert donc que l'état du **dernier tag** publié : le job `pages` ne tourne que sur
  `if: "$CI_COMMIT_TAG"`.
- `latest/` n'est **pas** un alias de version. C'est un sous-ensemble filtré à la date de build
  par [`build.mjs`](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/build.mjs) et
  [`filterFeature.mjs`](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/filterFeature.mjs), qui
  ne gardent que les entités dont `start_date` ≤ aujourd'hui < `end_date`. Le README parle de
  `valid_from`/`valid_until`, mais le code lit `start_date`/`end_date`. Le fichier `latest/` est en
  outre réécrit en JSON compact (`JSON.stringify` sans indentation).
- Les versions sont les **tags git** du dépôt
  ([API tags](https://gitlab.com/api/v4/projects/25330421/repository/tags)) : 34 tags, de `v6.0.0`
  (28/11/2023) à **`v8.5.0` (21/08/2026, commit `9f630cb1458e4931abadbe6acb965957dafa8a7a`)**. Le
  site sert le build de ce dernier tag (`last-modified: Fri, 21 Aug 2026` sur
  `FR_micro-regions.geojson.json`). Il n'y a aucune « release » GitLab : l'API releases renvoie
  `[]`.
- Pour chaque tag, le CI publie des **paquets npm** dans le registre GitLab, et pas sur npmjs.org
  (`registry.npmjs.org/@eaws/micro-regions` → « Not found »). Voir le
  [README](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/README.md) (« For each git tag, we
  build and publish NPM packages to the GitLab Registry ») et le
  [registre](https://gitlab.com/eaws/eaws-regions/-/packages). `@eaws/micro-regions@8.5.0`
  contient à la fois le fichier complet et `latest/`. Tarball :
  `https://gitlab.com/api/v4/projects/25330421/packages/npm/@eaws/micro-regions/-/@eaws/micro-regions-8.5.0.tgz`,
  shasum `cf7c6c0fb601bc27c827d0a76ac09095141a4b90`.
- Le `package.json` servi sur le site
  (`https://regions.avalanches.org/micro-regions/package.json`) porte `"version": "1.0.0"`, une
  valeur fixe, car le CI ne fait `npm version $CI_COMMIT_TAG` qu'au moment de publier. Ce champ
  n'indique donc **pas** la version servie.

### 1.2 URL épinglées

**Vérifié** : toutes ces URL répondent, et les empreintes ont été calculées sur les fichiers
téléchargés.

Épingler sur le **SHA du commit** plutôt que sur le nom du tag : un tag git peut être déplacé, pas
un SHA. Les deux formes renvoient aujourd'hui des octets identiques.

| Fichier | URL épinglée (commit du tag v8.5.0) | Octets | sha256 |
| --- | --- | --- | --- |
| Micro-régions FR | `https://gitlab.com/eaws/eaws-regions/-/raw/9f630cb1458e4931abadbe6acb965957dafa8a7a/public/micro-regions/FR_micro-regions.geojson.json` | 84 297 | `87e0c5b1e498c7fe328b46296a854ff991ea67de7fae9be288ecb0ec225da0b0` |
| Variante altitude | `https://gitlab.com/eaws/eaws-regions/-/raw/9f630cb1458e4931abadbe6acb965957dafa8a7a/public/micro-regions_elevation/FR_micro-regions_elevation.geojson.json` | 86 984 | `bed8c68ae84687a01a26b8206843a53ec3281c0507dc42ad28d77ffcb7c1ebd3` |
| Libellés FR | `https://gitlab.com/eaws/eaws-regions/-/raw/9f630cb1458e4931abadbe6acb965957dafa8a7a/public/micro-regions_names/fr.json` | 25 722 | `05e6b441d4dc03f06990b98a9adaf0e8c4517d70d86fb91bf656b7c9000f1c06` |

Forme par tag, équivalente aujourd'hui : remplacer le SHA par `v8.5.0`.

Le fichier `latest/` cité dans `docs/taches.md`, téléchargé depuis
`https://regions.avalanches.org/micro-regions/latest/FR_micro-regions.geojson.json` :

- **74 578 octets**, sha256
  **`d2d9b2954d06664f40dcc677109507613f389b54e1bd516751c216d7cafb469d`** ;
- **octet pour octet identique** à `package/latest/FR_micro-regions.geojson.json` du tarball npm
  `@eaws/micro-regions@8.5.0`, qui en est donc la forme épinglée ;
- n'existe **pas** dans git (`latest/` est un produit du build). Le seul moyen de l'épingler est
  le tarball npm.

Les **35 entités** de `latest/` sont strictement égales (comparaison Python des listes
`features`) à celles du fichier complet. Seule l'indentation diffère, et aucune entité FR ne porte
de date de validité. Le choix entre les deux fichiers est donc indifférent pour le contenu.
L'URL git est la plus simple à épingler.

Historique du fichier FR
([commits](https://gitlab.com/api/v4/projects/25330421/repository/commits?path=public/micro-regions/FR_micro-regions.geojson.json)) :
créé le 12/04/2021 (« Add files for France »), passé aux identifiants à zéro initial le 10/01/2022
(« Change FR IDs again to leading 0 »), puis inchangé jusqu'au 31/03/2026. Ce jour-là, deux
commits modifient les géométries : « FR: update borders with ES-AR » et « FR: fix duplicate nodes
and artifacts ». Ces commits entrent dans `v8.3.2`, et le fichier est identique de `v8.3.2` à
`v8.5.0`, sha256 `87e0c5b1…` aux trois tags. Il diffère de `v8.3.1` (sha256 `cdb132d0…`).

### 1.3 Contenu du fichier FR

**Vérifié** sur le fichier `latest/` (74 578 octets) ; le fichier complet donne le même résultat.

- `FeatureCollection`, `name: "FR_micro-regions"`, `crs: urn:ogc:def:crs:OGC:1.3:CRS84`
  (lon/lat WGS84).
- **35 entités**, toutes de type **`MultiPolygon`**. Chacune ne compte qu'**un seul polygone** :
  pas d'enclave ni de massif en plusieurs morceaux.
- Clés de propriétés : **`id` seulement**.
- 1 913 sommets au total. Le fichier fait 75 Ko : il est léger. La simplification prévue par T3
  n'est pas indispensable à ce volume.
- Identifiants (35) :

```
FR-01 FR-02 FR-03 FR-04 FR-05 FR-06 FR-07 FR-08 FR-09 FR-10 FR-11 FR-12
FR-13 FR-14 FR-15 FR-16 FR-17 FR-18 FR-19 FR-20 FR-21 FR-22 FR-23
FR-40 FR-41
FR-64 FR-65 FR-66 FR-67 FR-68 FR-69 FR-70 FR-72 FR-73 FR-74
```

Variante `_elevation` (`latest/`, 77 064 octets, sha256 `e86e34c5…`, identique au `latest/` du
paquet npm `@eaws/micro-regions_elevation@8.5.0`) :

- mêmes 35 identifiants, mêmes types de géométrie ;
- propriétés `id`, `elevation`, `threshold`, `elevation line_visualization` ;
- **pour la France, aucune subdivision par altitude** : les 35 entités portent
  `elevation: "low_high"` et `threshold: null`. Une ancienne version en avait (« low », seuil 0,
  commit `2e4d4bbf` d'avril 2021) ; elle a été remplacée par `low_high` le 12/12/2022 (commit
  `604d6942`) ;
- ses géométries ne sont **pas** strictement égales à celles du fichier `micro-regions`
  (comparaison Python). Pour une carte simple, le fichier `micro-regions` suffit.

Libellés `micro-regions_names/fr.json` : 705 clés, dont 36 commençant par `FR` (`FR` = « France »
et les 35 micro-régions, sans `FR-71`). Plusieurs graphies sont fautives : `FR-68` =
« Louchonnais » pour le Luchonnais, `FR-20` = « Embrunals-Parpaillon ». **Ne pas utiliser ces
libellés** ; le référentiel `massifs.py` reste la source des noms.

### 1.4 Raccordement aux 36 identifiants du référentiel

**Vérifié** : comparaison avec `MASSIFS` dans `src/bra_analytics/massifs.py`.

- **Manquant : `71` (Andorre).** Il ne figure dans aucune version du fichier FR. Le fichier
  d'origine (avril 2021) avait 34 entités sans propriété `id` ; dès le commit suivant, et jusqu'à
  aujourd'hui, il en a 35, sans 71.
- **En trop : aucun.** Les 35 `FR-*` correspondent tous à un massif du référentiel.
- **Suffixes, sous-régions : aucun.** Aucun identifiant de la forme `FR-nn-x`.
- **Format de l'identifiant : `FR-` + numéro sur deux chiffres** (`FR-01` … `FR-09`). Le raccord
  avec `massif_id` (entier) se fait par `int(id.removeprefix("FR-"))`, ou par
  `f"FR-{massif_id:02d}"`, et pas par `f"FR-{massif_id}"`. `docs/taches.md` écrit
  « `FR-<massif_id>` » : c'est vrai pour les identifiants ≥ 10, faux pour 1 à 9.
- Andorre a son propre jeu chez EAWS
  (`https://regions.avalanches.org/micro-regions/latest/AD_micro-regions.geojson.json`), avec
  trois entités `AD-01`, `AD-02` et `AD-03` (« North Zone », « Center Area », « South Zone »). C'est
  le découpage du service andorran, pas le massif BRA 71.

**Déduit.** L'absence de `FR-71` s'explique sans doute ainsi : EAWS cartographie chaque territoire
par le service qui y fait autorité, et l'Andorre relève du service andorran (`AD-*`). Le dépôt ne
le dit nulle part. Conséquence pour l'écran : le massif 71, présent dans les BRA jusqu'en
2024-2025 (cf. `CLAUDE.md`), n'a **aucun contour** dans le jeu EAWS. Il doit apparaître comme
« sans contour » et non disparaître.

**Vérifié** (indice de provenance). Les propriétés du fichier FR d'origine (commit `13299556`,
12/04/2021) contenaient `aws_ID` (numéro de massif), `aws_1: "MF"` et `url_1` pointant vers
`meteofrance.com/…/bulletin-avalanches/…/OPP67`.
**Déduit** : les géométries FR d'EAWS ont été reprises d'un découpage Météo-France. Le dépôt ne
cite pas sa source géographique.

## 2. Dépôt source et licence

### 2.1 Dépôt

**Vérifié** ([API projet](https://gitlab.com/api/v4/projects/eaws%2Feaws-regions)).

- `https://gitlab.com/eaws/eaws-regions`, projet n° 25330421, public, créé le 22/03/2021, branche
  `master`. Description : « http://regions.avalanches.org/ – geodata of avalanche warning
  regions ». Groupe `eaws` : « European Avalanche Warning Services »
  ([groupe](https://gitlab.com/groups/eaws)).
- Le champ `license` de l'API projet vaut `null` : GitLab n'a pas détecté de licence. Le fichier
  `LICENSE` existe pourtant à la racine (§ 2.2).

### 2.2 Déclarations de licence, citées verbatim

**Vérifié.**

1. **[`LICENSE`](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/LICENSE)** à la racine du
   dépôt (7 048 octets). Il commence par :

   > Creative Commons Legal Code
   >
   > CC0 1.0 Universal

   Son sha256 (`a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499`) est
   **identique** à celui du texte canonique
   `https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt` : c'est le CC0 1.0 non
   modifié.

2. **[`package.json`](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/package.json)** à la
   racine du dépôt :

   > `"license": "CC0-1.0",`

3. **`package.json` de chaque paquet de données**, servi sur le site de diffusion lui-même. Par
   exemple `https://regions.avalanches.org/micro-regions/package.json` :

   > ```
   > "name": "@eaws/micro-regions",
   > "description": "geodata of avalanche warning regions",
   > "homepage": "https://gitlab.com/eaws/eaws-regions/",
   > "author": "https://gitlab.com/eaws",
   > "license": "CC0-1.0"
   > ```

   La même ligne `"license": "CC0-1.0"` figure dans
   `https://regions.avalanches.org/micro-regions_elevation/package.json`,
   `…/micro-regions_names/package.json`, `…/micro-regions_properties/package.json` et
   `…/pmtiles/package.json`.

4. **README** ([README.md](https://gitlab.com/eaws/eaws-regions/-/raw/v8.5.0/README.md)) : aucune
   mention de licence.

5. **Page d'index de `regions.avalanches.org`** : aucune occurrence de « licen », « CC0 » ou
   « copyright » dans le HTML. C'est le constat de `docs/taches.md` (« elle n'est pas affichée sur
   le site de diffusion »), qui n'est vrai que pour la page HTML : le site sert aussi les
   `package.json` qui déclarent CC0-1.0.

6. **Site institutionnel `www.avalanches.org`**, [Imprint](https://www.avalanches.org/imprint/) :

   > All contents, the layout, any sound and video sequences, etc. are protected by copyright and
   > other intellectual property laws. All these rights are reserved to the province of Tyrol.

   Cette mention vise le site `www.avalanches.org`, édité par l'Office of the Tyrolean Provincial
   Government. Elle ne vise pas `regions.avalanches.org`, qui est un site GitLab Pages distinct
   construit depuis le dépôt sous CC0. La même page ajoute : « Separate licenses and terms of use
   apply for "Open Government Data". »

### 2.3 Verdict licence

- **Vérifié.** Une licence est trouvée : **CC0 1.0 Universal**. Elle est déclarée par le fichier
  `LICENSE` du dépôt, qui contient code et données sans distinction, ce qui en fait une licence
  sur l'ensemble du dépôt. Elle est aussi déclarée, **explicitement pour les données**, dans le
  `package.json` de chaque paquet de géodonnées (« geodata of avalanche warning regions »).
- **Réserve, tirée du texte même du CC0** (§ 4.c, dans le `LICENSE`) :

  > Affirmer disclaims responsibility for clearing rights of other persons that may apply to the
  > Work or any use thereof

  Le déclarant renonce à ses propres droits, sans garantir qu'aucun tiers n'en détient. Si les
  géométries FR viennent de Météo-France (déduction du § 1.4), les droits éventuels de
  Météo-France ne sont pas levés par le CC0 d'EAWS. **Déduit** : Météo-France publie lui-même ce
  découpage sous Licence Ouverte 2.0 (§ 3). Le risque pratique se réduit alors à une obligation
  d'attribution, que l'on remplit en citant les deux sources.
- Ce document n'est pas un avis juridique. Il remplace l'hypothèse « licence non affichée » de
  `docs/taches.md` par un fait vérifiable : CC0 déclaré, avec la réserve ci-dessus.

### 2.4 Contact pour une question de licence

**Vérifié.**

- **Issue tracker** : `https://gitlab.com/eaws/eaws-regions/-/issues`, actif. 34 tickets, le
  dernier ouvert le 07/10/2025 ; les URL de ticket prennent la forme
  `https://gitlab.com/eaws/eaws-regions/-/work_items/34`. Aucun ticket existant ne contient
  « licen » ni « copyright » (recherche via l'API issues).
- **Mainteneurs actifs**, d'après les commits récents : Simon Legner (commits FR de mars 2026) et
  Norbert Lanzanasto (traductions, correctifs). La liste des membres du projet n'est pas lisible
  sans authentification (API `members` → 401).
- **Contact institutionnel EAWS** ([Imprint](https://www.avalanches.org/imprint/)) : Office of the
  Tyrolean Provincial Government, `post@tirol.gv.at`, +43 512 508.
- **Déduit** : le canal le plus direct est un ticket sur le dépôt, qui laisse en outre une trace
  publique de la réponse.

## 3. Repli : contours publiés par Météo-France

### 3.1 Le fichier

**Vérifié** ([API dataset](https://www.data.gouv.fr/api/1/datasets/6a732e24879142b3792bfa28/)).

- Jeu de données : **« Archive des Bulletins Avalanches »** (sigle BRA), producteur
  **Météo-France**, `https://www.data.gouv.fr/datasets/archive-des-bulletins-avalanches`, créé le
  05/08/2026. Licence : **`lov2` = « Licence Ouverte / Open Licence version 2.0 »**
  ([API licences](https://www.data.gouv.fr/api/1/datasets/licenses/) ; texte :
  https://www.etalab.gouv.fr/licence-ouverte-open-licence).
- Ressource : **`DONNEES_EXPERTISEES_Metadata_massifs.geojson`**, décrite comme « Définition des
  massifs existants dans le bulletin risque avalanche au format GeoJSON. »
  - URL du fichier :
    `https://static.data.gouv.fr/resources/archive-des-bulletins-avalanches/20260805-132200/donnees-expertisees-metadata-massifs-20240215.geojson`
    (le chemin contient l'horodatage de dépôt, ce qui le rend de fait figé) ;
  - URL « dernière version » : `https://www.data.gouv.fr/api/1/datasets/r/7c7bc2d5-d317-483f-b792-a1742e70bdba`.
    Elle redirige aujourd'hui vers l'URL ci-dessus et suivra les remplacements ; ne pas l'épingler ;
  - format **GeoJSON** (`application/geo+json`), **72 353 octets** ; sha1
    `e623ac5e42ac83c595c40cd520b7de3740f47de5`, conforme au checksum déclaré par data.gouv.fr ;
    sha256 `0300ea206b0eaa70dbef5182540dbb2d60e2db80cc52e543dbfd2f023758a882` ;
  - `name: "Metadata_massif_DP_2024"`, `crs` CRS84. Le suffixe `20240215` du nom de fichier
    suggère une version du 15/02/2024 (**déduit**).
- Le même jeu contient l'archive XML (`https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA`)
  et le descriptif technique PDF : c'est la source que le repo ingère déjà.

### 3.2 Contenu et raccordement

**Vérifié.**

- **36 entités**, toutes `MultiPolygon` à un seul polygone, 2 710 sommets.
- Propriétés : `code` (entier), `title`, `title_shor`, `mountain` (« Alpes du Nord », « Alpes du
  Sud », « Corse », « Pyrenees »), `Departemen`, `Dep2`, `lon_center`, `lat_center`.
- **`code` couvre exactement les 36 `massif_id` du référentiel** : 1 à 23, 40, 41 et 64 à 74,
  **y compris 71** (« Andorre (massif) »). Aucun manquant, aucun en trop. La numérotation est celle
  du BRA, en entier : raccord direct, sans préfixe ni zéro.
- Comparaison géométrique avec EAWS sur les 35 massifs communs (calcul planaire en degrés,
  indicatif) : rapport de surfaces EAWS/Météo-France compris entre 0,936 (Haute-Ariège, 70) et
  1,038 (Grandes-Rousses, 12), écart de centroïde entre 0,03 et 0,76 km. **Déduit** : c'est le
  même découpage, avec des retouches de frontière côté EAWS (cf. commit « FR: update borders with
  ES-AR »).
- Clause d'attribution de la Licence Ouverte 2.0
  ([LO.md](https://github.com/etalab/Licence-Ouverte/blob/master/LO.md)) :

  > mentionner la paternité de l'« Information » : sa source (a minima le nom du « Concédant ») et
  > la date de la dernière mise à jour de l'« Information » réutilisée.

### 3.3 Ce qui n'a pas été vérifié

- `https://meteo.data.gouv.fr/` répond 200 mais ne sert qu'une coquille JavaScript de 574 octets.
  Son catalogue n'a pas pu être lu sans navigateur. Le jeu ci-dessus a été trouvé par l'API de
  `www.data.gouv.fr`, qui est le dépôt effectif.
- Un shapefile **SAFRAN/S2M** (réanalyse) distinct n'a pas été trouvé : les recherches API
  « massifs safran », « S2M » et « contours massifs » renvoient 0 résultat. Le fichier trouvé est
  celui des **massifs du BRA**, ce qui correspond mieux au besoin.
- Le descriptif technique PDF et la page Confluence Météo-France citée par le jeu de données n'ont
  pas été lus pour confirmer l'origine des géométries.

## 4. Conséquences pour T3

**Déduit.** Ce sont des recommandations à trancher, pas des faits de source.

- Le fichier Météo-France remplit les quatre conditions de « Fait quand » mieux que le jeu EAWS :
  il couvre **36/36** identifiants (EAWS 35/36, sans Andorre) ; sa licence est explicite et
  attachée au jeu de données lui-même ; sa clé est l'entier `massif_id` ; son producteur est
  l'émetteur du BRA. Le « repli » de `docs/taches.md` est donc, à l'examen, la meilleure source
  primaire.
- Si EAWS reste retenu : épingler sur le SHA `9f630cb1…`, raccorder par `f"FR-{id:02d}"`,
  signaler le massif 71 comme « sans contour », ignorer `fr.json` pour les libellés, et citer CC0
  avec la réserve du § 2.3.
- Dans les deux cas, enregistrer à côté du fichier versionné : l'URL figée, le sha256, la date de
  téléchargement et la mention d'attribution.
- Trois affirmations des documents existants sont démenties ou nuancées par cette recherche :
  - identifiants « `FR-<massif_id>` » (anciens documents de spec) : ils sont en
    réalité sur deux chiffres ;
  - licence « pas affichée sur le site de diffusion » (mêmes deux passages) : CC0 est déclaré ;
  - variante `_elevation` « qui subdivise par tranche d'altitude » (`taches.md` T3) : ce n'est pas
    le cas pour la France.

  Ce document ne modifie pas ces fichiers.
