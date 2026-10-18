# bra-analytics

Pipeline d'ingestion, de parsing et d'agrégation des **Bulletins d'Estimation du Risque
d'Avalanche** (BRA) de Météo-France, publiés sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence).

Source : `https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA/AAAA/MM/JJ/xml/` (sans authentification).
Couverture : mars 2016 → juin 2026, 36 massifs (Alpes, Pyrénées, Corse).

Le format XML a **changé six fois** sur la période. La pipeline ramène ces variantes à un
schéma unique.

**Documentation**

- **[docs/glossaire.md](docs/glossaire.md)** — signification de chaque champ, avec sa
  correspondance XML, ses unités et ses pièges. Le point d'entrée pour exploiter le dataset.
- **[docs/exploration.md](docs/exploration.md)** — écarts constatés entre les données réelles et
  le descriptif technique officiel du 26/10/2023. À lire avant toute interprétation.

## Installation

```bash
uv sync --extra dev
```

## Utilisation

Les commandes s'enchaînent dans cet ordre : **récupérer**, **construire**, **vérifier**,
**consulter**, **comparer**.

### 1. `bra fetch` — récupérer le XML source

```bash
uv run bra fetch --seasons 2023 2024 2025 --massifs pyrenees
```

Parcourt l'archive jour par jour et télécharge les bulletins dans `data/raw/`, en reproduisant
l'arborescence de la source. Rien n'est parsé à ce stade.

Accepte `--massifs pyrenees|alpes|corse|all` ou une liste d'identifiants (`--massifs 65,67`), et
`--start/--end` à la place de `--seasons`. `--workers` règle le nombre de téléchargements
simultanés (6 par défaut).

Le cache rend l'opération **idempotente et reprenable** : relancer la commande ne retélécharge
que ce qui manque, ce qui permet d'interrompre puis de reprendre une ingestion longue.

### 2. `bra build` — construire l'entrepôt

```bash
uv run bra build
```

C'est l'étape de transformation. Elle lit tout le XML présent dans `data/raw/` et :

1. **parse** chaque fichier, en ramenant les six formats historiques à un schéma unique ;
2. **normalise** les valeurs — directions de vent harmonisées, `LOC1`/`LOC2` décomposés en
   champs typés, sentinelles converties en valeur nulle (`RISQUE1="-1"`, relevés d'enneigement
   et échéances météo vides, cumuls de neige fraîche non observés, `ALTITUDEVENT2="9999"` — le
   détail et l'indicateur `sans_enneigement_continu_*` sont au glossaire), secteurs de neige
   fraîche d'avant 2024 conservés, dates ramenées à l'heure locale ;
3. **déduplique** sur `(massif_id, date_bulletin)` en retenant la diffusion la plus tardive —
   un même bulletin est souvent republié dans la journée. Les tables filles (météo,
   enneigement, neige fraîche, historiques) sont lues dans **le même fichier** que la table
   `bulletins` : 1 409 clés de l'archive ont des diffusions dont ces blocs diffèrent (voir
   [exploration](docs/exploration.md)) ;
4. **enrichit** avec le référentiel des massifs et la saison nivologique ;
5. **écrit** six tables en Parquet partitionné par saison, puis crée la base DuckDB et ses vues.

L'opération est **idempotente** : `warehouse/` est reconstruit intégralement à chaque appel, sans
état résiduel. Sur les 36 massifs et 11 saisons (90 054 fichiers, 13,0 Go de XML), elle prend
environ **4 minutes** et culmine à **7 Go de mémoire**, pour 19 Mo de Parquet — les images
embarquées, qui pèsent 93 % du XML ancien, sont écartées. Sur les seules Pyrénées (27 006
fichiers, 3,7 Go) : 40 s et 6,2 Mo.

Options : `--out` pour changer le répertoire de sortie, `--db` pour le chemin de la base,
`--no-db` pour ne produire que les Parquet.

Un fichier illisible n'interrompt pas la construction : il est compté et listé en fin de rapport.

### 3. `bra check` — vérifier la cohérence

```bash
uv run bra check
```

Distingue les **erreurs** (données incohérentes : indice hors échelle, clé dupliquée, échéance
antérieure à la rédaction, libellé de massif contredisant son identifiant) des **signaux** (faits
réels de l'archive : amendements, séries à trous) qu'il vaut mieux constater avant de les
découvrir en cours d'analyse. Affiche aussi les couples massif/saison à trous.

### 4. `bra info` — consulter le résumé

```bash
uv run bra info
```

Vue d'ensemble de ce que contient l'entrepôt : une ligne par saison, avec le nombre de bulletins,
le nombre de massifs couverts, les bornes temporelles et le risque moyen. C'est le moyen le plus
rapide de vérifier qu'une ingestion a bien produit ce qu'on attendait.

```
Bulletins par saison :
  saison            n  massifs  debut       fin          risque moy.
  2015-2016      1301       35  2016-03-09  2016-04-24          2.37
  2016-2017      7773       35  2016-11-03  2017-06-14          2.26
  2017-2018      7750       35  2017-11-02  2018-06-12          2.91
  2018-2019      8003       36  2018-10-29  2019-06-12          2.22
  2019-2020      5864       36  2019-10-30  2020-06-10          2.38
  ...
  2025-2026      7608       35  2025-11-03  2026-06-07          2.23

  La colonne « risque moy. » porte sur la saison entiere : elle n'est
  pas comparable d'une saison a l'autre. Voir `bra fenetres`.

Ecartees du tableau (1 couple(s) saison/massif) — ID et libelle se contredisent :
  2015-2016  ID=3 (Mont-Blanc) porte MASSIF='MOYENNE MONTAGNE' — 1 bulletin(s)
```

Cette sortie se lit aussi comme un diagnostic, et chacun de ses écarts est un fait d'archive :

- **35 massifs jusqu'en 2017-2018** : le massif 22 (Haut-Var Haut-Verdon) n'est diffusé qu'à
  partir du 22 novembre 2018 ;
- **35 massifs en 2025-2026** : le massif 71 (Andorre) n'est plus diffusé ;
- **2019-2020 court jusqu'au 10 juin** alors que l'estimation s'arrête fin mars (confinement) :
  Pyrénées et Corse cessent de publier (26 et 18 mars), les Alpes continuent sans indice et par
  intermittence jusqu'au 11 juin — d'où une saison longue mais trouée ;
- le bulletin technique de 2016 diffusé sous un identifiant alpin est écarté du tableau et listé
  en dessous : il comptait auparavant pour un douzième massif pyrénéen et faisait démarrer la
  saison au 4 février.

### 5. `bra fenetres` — comparer des saisons entre elles

```bash
uv run bra fenetres
```

Le « risque moyen » de `bra info` **ne se compare pas d'une saison à l'autre** : jusqu'en juin
2021 les journées sans enneigement portaient `RISQUE1="-1"` et sortaient des moyennes, depuis
elles reçoivent un indice réel et y entrent. À nivologie identique, les saisons anciennes
ressortent donc plus hautes. Cette commande publie, par saison et par fenêtre, ce qui rend une
comparaison légitime : nombre de bulletins, massifs actifs, non-estimés, couverture, indice moyen.

```
=== coeur  (15 decembre -> 15 avril) ===
  usage        : toute comparaison inter-saisons d'indice de risque
  justification: Aucune saison n'y emploie la sentinelle `RISQUE1=-1` : 0 bulletin non
                 estime sur chacune des saisons comparables. [...]

  saison      bulletins  massifs  non est.  jours   couv.  risque
  2016-2017        4260       35         0    122  99.8 %   2.349
  ...
  2025-2026        4263       35         0    122  99.8 %   2.568
```

Deux fenêtres, deux usages : `coeur` (15 déc → 15 avr) pour comparer des indices, `commune`
(6 nov → 7 juin) pour comparer des couvertures. Les bornes sont mesurées, pas choisies — le
détail du calcul est dans [le glossaire, § 8](docs/glossaire.md#8-fenêtres-de-comparaison-inter-saisons).

### 6. `bra audit` — mesurer ce que les champs permettent

```bash
uv run bra audit
```

Écrit [`docs/disponibilite.md`](docs/disponibilite.md) : part de valeurs non nulles par champ et
par saison, distribution de `loc_type`, altitudes de référence par massif, couverture de
l'enneigement, `sat1`/`sat2`, distributions des champs à seuil, bloc météo selon `origine`, et
sentinelles `-1` restées dans l'entrepôt. Chaque métrique de la spec y reçoit un statut
(calculable, sur un sous-ensemble de saisons, non calculable) **dérivé** de ces mesures. Le
document est déterministe : le relancer après chaque `bra build` et versionner le diff.

Deux commandes auxiliaires : `bra massifs` affiche le référentiel des 36 massifs ;
`bra contours` vérifie que les contours versionnés (Météo-France, Licence Ouverte 2.0) se
raccordent aux 36 identifiants et régénère leur version web — voir
[docs/contours.md](docs/contours.md).

### 7. `bra carte` — carte d'accueil des 36 massifs

```bash
uv run bra carte                      # écrit carte.html à la racine (non versionné)
uv run bra carte --out /tmp/carte.html
```

Page HTML autonome, à ouvrir directement dans un navigateur : aucun serveur, aucune bibliothèque
cartographique. Les contours versionnés (`geo/massifs.web.geojson`) sont embarqués et dessinés en
SVG. Chaque massif porte **une valeur**, sans sélecteur de saison :

- par défaut, l'**indice moyen sur la fenêtre `coeur`, saisons comparables seulement** — la
  métrique d'accueil de la spec § 3.2, lue telle quelle dans `moyenne_pluriannuelle()`. Le libellé
  dit « neuf saisons comparables sur onze », compté depuis l'entrepôt et `fenetres.py` ;
- le survol donne toujours les jours couverts (et la durée nominale de la fenêtre sur les saisons
  diffusées) et les jours de risque 4 ou 5 : une moyenne d'indices ordinaux n'est jamais affichée
  seule ;
- un sélecteur bascule sur les **jours à risque 3 ou plus** et le **maximum atteint** (repris de
  `risque_saison`) ; la métrique vit dans l'URL (`carte.html#risque_max`). La durée
  d'enneigement est annoncée mais pas calculée : elle dépend de T7 ;
- un massif diffusé une partie de la période est **hachuré par-dessus sa couleur** — Haut-Var
  Haut-Verdon (22) n'a que 7 saisons comparables sur 9, Andorre (71) 8 — et le survol nomme les
  saisons manquantes ; un massif sans aucun jour sur la période serait hachuré sur fond neutre,
  hors de la rampe, pour ne jamais se lire comme un zéro.

L'attribution des données (avec la date d'archive) et celle des contours (version du 15/02/2024)
figurent sous la carte. `--fragment` omet doctype et `<html>`, comme pour `bra dashboard`.

## Sortie

```
warehouse/
  bulletins/saison=2025-2026/data.parquet      1 ligne par bulletin
  meteo/saison=.../data.parquet                échéances météo (prévision + 7 jours écoulés)
  enneigement/…                                épaisseurs par altitude et versant
  neige_fraiche/…                              cumuls 24 h
  historique_risque/…                          risque max des 7 jours précédents
  tendances/…                                  tendances J+2 et J+3 (2016-2023 uniquement)
  conversions/…                                journal des sentinelles rendues nulles au parsing
  bra.duckdb                                   vues sur l'ensemble
```

La base DuckDB expose chaque table, plus des vues de travail :

| Vue | Grain | Usage |
|---|---|---|
| `risque_journalier` | 1 ligne / massif / **jour couvert** | séries temporelles, sur deux axes : `jour_validite` (calendaire) et `jour_de_saison` (rang depuis l'ouverture du massif) |
| `couverture` | 1 ligne / massif / saison | repérer les trous d'archive (hors lignes `massif_coherent = false`) |
| `profil_saison` | 1 ligne / massif / saison | profil d'une saison, massif par massif |
| `saison_fenetre` | 1 ligne / saison / fenêtre | **comparaisons inter-saisons** |
| `palier_tranche` | 1 ligne / valeur mesurée à une altitude | enneigement, neige fraîche et vent par tranche normée (< 1800, 1800–2400, ≥ 2400 m) |
| `risque_jour` | 1 ligne / massif / jour couvert | risque du jour, variation depuis la veille, écart à la normale |
| `risque_episode` | 1 ligne / épisode ≥ 3 / portée | épisodes, avec ce qui les rompt ou les tronque |
| `risque_saison` | 1 ligne / massif / saison / portée | métriques de risque de la spec § 5.1 |
| `risque_second_indice` | 1 ligne / massif / jour couvert | `risque1` / `risque2` / `loc_type`, vue experte |
| `enneigement_jour` | 1 ligne / massif / jour de relevé | limites d'enneigement continu et indicateur `sans_enneigement_continu_*` |
| `enneigement_palier` | 1 ligne / massif / jour / palier | épaisseur par tranche normée, palier retenu, écart à la normale |
| `enneigement_saison` | 1 ligne / massif / saison / tranche / portée | jours enneigés, maximum saisonnier et sa date |
| `enneigement_continu` | 1 ligne / massif / saison / versant | période d'enneigement continu |
| `neige_fraiche_jour` | 1 ligne / massif / jour | cumul de 24 h dédupliqué (une rédaction par jour), lu par le bloc météo |
| `neige_fraiche_episode` | 1 ligne / épisode de chute / portée | épisodes de chute, avec ce qui les borde |
| `neige_fraiche_saison` | 1 ligne / massif / saison / tranche / portée | cumul, jours de chute, plus forte chute, lecture du cumul |
| `meteo_jour` | 1 ligne / massif / jour couvert | **prévision** du jour (06 h et 12 h) : isotherme 0 °C, limite pluie-neige, temps sensible, motif de lacune |
| `meteo_vent_jour` | 1 ligne / massif / jour / altitude de vent | vent prévu par altitude et tranche normée |
| `meteo_vent_tranche_jour` | 1 ligne / massif / jour / tranche | vent prévu par tranche : le plus fort des vents de la tranche, altitudes réunies |
| `meteo_redoux` | 1 ligne / suite de jours à isotherme haut | épisodes de redoux, risque de la veille, pendant et du lendemain |
| `meteo_saison` | 1 ligne / massif / saison / portée | isotherme, variations en 24 h, limite pluie-neige, redoux |
| `meteo_vent_saison` | 1 ligne / massif / saison / portée / tranche | jours de vent fort |
| `meteo_temps_sensible` | 1 ligne / massif / saison / portée / code | répartition des codes de temps, avec libellés |
| `meteo_transport` | 1 ligne / massif / jour / tranche | indice de transport par le vent : vent prévu sur neige fraîche récente, pentes chargées |

Les quatre vues `risque_*` forment le bloc risque de la couche métriques ; leurs définitions,
et les fonctions Python qui les lisent (`bra_analytics.metriques.risque`), sont au
[glossaire, § 9](docs/glossaire.md#9-couche-métriques--bloc-risque). Les comparaisons
inter-saisons y refusent toute fenêtre autre que `coeur`. Les huit vues `meteo_*` forment le
bloc météo (`bra_analytics.metriques.meteo`, [glossaire, § 11](docs/glossaire.md#11-couche-métriques--bloc-météo)) :
c'est une **prévision**, et chaque ligne le dit (`origine = 'prevision'`).

Les sept vues `enneigement_*` et `neige_fraiche_*` forment le bloc enneigement
(`bra_analytics.metriques.enneigement`, [glossaire, § 10](docs/glossaire.md#10-couche-métriques--bloc-enneigement)).
L'enneigement du BRA y reste **indicatif** : aucune sortie ne le présente comme une mesure. Un
même jour de neige fraîche étant décrit par six bulletins, la vue retient la rédaction la plus
tardive et `bra build` journalise chaque ligne écartée (les répétitions identiques en `DEBUG`,
les valeurs révisées en `WARNING`). Les seuils (épaisseur, limite, chute) sont des paramètres
des fonctions de lecture ; une somme de neige fraîche à cheval sur l'hiver 2023-2024 est
refusée (`RuptureDeSerie`).

Partitionnement par saison nivologique (`2025-2026` = septembre 2025 → août 2026), dérivé de
`DATEBULLETIN` et non du chemin source — les deux divergent en 2016.

### Interroger

```bash
uv run python -c "import duckdb; print(duckdb.connect('warehouse/bra.duckdb', read_only=True).execute('SELECT saison, round(avg(risque_maxi),2) FROM bulletins GROUP BY 1 ORDER BY 1').df())"
```

```python
import polars as pl
df = pl.read_parquet("warehouse/bulletins/**/*.parquet")
```

## Points d'attention pour l'analyse

- **Indexer sur `jour_validite`, pas sur `jour_bulletin`.** Un BRA est rédigé vers 16 h pour le
  lendemain : le risque décrit porte sur l'échéance. Une série indexée sur la date de rédaction
  est décalée d'un jour. La vue `risque_journalier` applique déjà cette règle.
  `jour_validite` dérive de `DATEECHEANCE` et **non** de `DATEVALIDITE` : hors saison, cette
  dernière porte la date du prochain bulletin et fusionne des journées distinctes.
- **Un jour peut recevoir deux bulletins.** Le bulletin du soir couvre J+1 ; un amendement émis
  le lendemain matin (`amendement = true`) recouvre la journée en cours. Depuis 2023-2024 s'y
  ajoute la réédition : le même bulletin rediffusé une à deux heures plus tard avec un
  `DATEBULLETIN` déplacé, que la déduplication ne peut pas rapprocher puisque c'est la clé qui
  bouge. Les deux cas sont conservés dans `bulletins` et arbitrés dans `risque_journalier`
  (rédaction la plus tardive) : **635 lignes** sur 77 488, dont 162 portent un indice différent de
  celui retenu. `bra build` journalise chacune en `WARNING` et `bra check` en donne le total —
  l'écart entre les deux comptages n'est jamais silencieux.
- **`massif_id` est la seule clé stable.** Le libellé change de graphie selon l'époque
  (`ASPE-OSSAU` → `Aspe Ossau`, `ANDORRE` → `Andorre (massif)`). La colonne `massif_nom` porte
  le libellé normalisé du référentiel, `massif_nom_source` celui du fichier.
- **`risque_estime = false` signale un bulletin sans estimation chiffrée** (début et fin de
  saison, faute d'enneigement). La source y met `RISQUE1 = -1` ; la pipeline convertit cette
  sentinelle en valeur nulle pour ne pas fausser les moyennes. Cela concerne **14 487 bulletins
  sur 77 488, soit 18,7 % du corpus**, très concentrés : 14 482 d'entre eux tombent sur les cinq
  saisons 2016-2017 à 2020-2021, où ils pèsent 38,9 % des 37 225 bulletins. Filtrer sur
  `risque_estime` avant tout agrégat, ou s'appuyer sur `profil_saison` qui l'exclut déjà.
  Quatorze lignes font exception (six sur les Pyrénées) : `RISQUE1 = -1` y coexiste avec un
  `RISQUEMAXI` renseigné, si bien
  qu'elles sont non estimées **et** comptées dans les moyennes (`bra check` les signale sous
  `non_estime_avec_maxi`).
- **La pratique du `-1` s'arrête en juin 2021 : c'est une rupture de série.** Elle court du
  04/11/2016 au 11/06/2021 (jours couverts), avec pour seules exceptions ensuite quatre bulletins
  isolés (trois le 05/11/2023, un le 09/01/2025). Ensuite, les mêmes journées marginales
  reçoivent un indice réel, généralement 1, et entrent donc dans les moyennes. Conséquence : à
  nivologie identique une saison 2016-2021 ressort plus haute qu'une saison récente. Sur les
  36 massifs, l'écart apparent entre les deux époques passe de **0,368 point** sur la saison entière
  à **0,196** sur la fenêtre `coeur` : près de la moitié (47 %) est un artefact d'encodage. Sur les
  seules Pyrénées, où la mesure a d'abord été faite, la part montait à 70 % (0,327 → 0,098). Contrairement à la rupture de schéma de 2024, celle-ci
  est invisible dans la structure du fichier : aucun `schema_version` ne la signale.
- **Ne jamais comparer deux saisons sur leurs bornes brutes.** Utiliser la vue `saison_fenetre`,
  ou les booléens `fenetre_coeur` / `fenetre_commune` de `risque_journalier`. La fenêtre `coeur`
  (15 déc → 15 avr) est la seule sur laquelle aucune saison n'emploie la sentinelle ; `commune`
  (6 nov → 7 juin) sert aux couvertures et **pas** aux moyennes. Les saisons 2015-2016 (partielle)
  et 2019-2020 (Covid) sont étiquetées non comparables plutôt que supprimées. Voir
  [le glossaire, § 8](docs/glossaire.md#8-fenêtres-de-comparaison-inter-saisons).
- **Ne pas imputer les `-1` en 1 pour « réparer » la série.** Ce serait un choix analytique — il
  suppose que toute journée non estimée aurait porté l'indice 1 — pas une correction technique.
- **`risque1_evolution` est un second indice de risque**, pas un code d'évolution, malgré le nom
  de l'attribut source `EVOLURISQUE1`. `risque_maxi = max(risque1, risque1_evolution)`.
- **`loc_type`** indique si `risque1`/`risque2` se distinguent par altitude (`altitude_seuil_m`
  renseigné) ou par orientation (`loc1_secteur`/`loc2_secteur`).
- **Colonnes nulles par construction** avant 2024 : `sat1`, `sat2`, `risque_maxi_j2`,
  `risque_j2_libelle`, `stabilite_titre`. Et après 2023 : `producteur`, `tendances`.
  Filtrer sur `format_famille` ou `schema_version` pour les comparaisons inter-époques.
- **Le massif 71 (Andorre) disparaît en 2025-2026.** Une rupture de série n'est pas un bug.
- **Neige fraîche : rupture de série à l'hiver 2023-2024.** Avant, un cumul par secteur nommé
  (`secteur1_*`, `secteur2_*`, bornes dérivées) ; ensuite une fourchette sur le massif. Les deux
  se lisent, mais une comparaison qui enjambe l'hiver 2023-2024 doit l'annoncer.
- **Le vent se lit par altitude, pas par rôle bas / haut.** Jusqu'en 2023 les Alpes du Sud n'ont
  qu'un vent, à 3000 m, dans la colonne « basse » ; depuis 2024, 2000 et 3000 m.
- **Trous réels dans l'archive**, à ne pas confondre avec des défauts d'ingestion :
  l'estimation 2019-2020 s'arrête **fin mars 2020** (confinement) ; certaines journées sont
  partielles (07/02/2023 : 8 bulletins au lieu de 36), dix-sept sont absentes pour (presque) tous
  les massifs, les répertoires de la source étant vides ; 11 fichiers sur 90 065 annoncés sont
  corrompus côté serveur (page d'erreur servie sous un code HTTP 200), tous en 2021-2022. Le
  détail est dans [exploration.md, § 2 ter](docs/exploration.md).
- **Un bulletin usurpe un identifiant** : `ID=3` (Mont-Blanc) avec `MASSIF="MOYENNE MONTAGNE"`
  en 2016 — un message technique, pas un bulletin. L'écarter avec `WHERE massif_coherent`, la
  colonne qui compare l'`ID` au libellé source. **Un filtre sur `zone` ne convient pas** : la
  ligne hérite d'une zone alpine de son identifiant usurpé, donc un tel filtre la classe au lieu
  de l'écarter, et la laisserait passer sous un identifiant pyrénéen. Les vues de comparaison la
  filtrent déjà ; `bra info` et `bra check` la listent.
- **`schema_version` décrit la structure du fichier, pas la saison.** Un bulletin dégradé récent
  peut présenter les traits d'une époque ancienne (absence de bloc `BSH`, par exemple).
- **Les directions de vent sont harmonisées** en convention anglaise (`N`…`NW`, plus `VRB`),
  cohérente avec les orientations de la rose des pentes ; la source alterne entre convention
  anglaise (≤2023) et française (≥2024).

## Tests

```bash
uv run pytest
```

Les fixtures de `tests/fixtures/` sont des bulletins réels figés, un par époque, plus les cas
limites (doublon de publication, `nombre="2"` mensonger, décalage de date). Seules les images
base64 en ont été retirées : elles représentaient 93 % du poids sans valeur analytique.

## Données brutes

Le XML brut n'est **jamais versionné** (`.gitignore`). Il est mis en cache sous `data/raw/`,
reproduisant l'arborescence de la source, et reste reconstructible par `bra fetch`.

### 8. `bra fiche` — fiche massif-saison

```bash
uv run bra fiche                      # écrit fiche.html à la racine (non versionné)
```

Page HTML autonome (environ 4,5 Mo : 36 massifs × 11 saisons × quatre blocs). Massif, saison, axe
(calendrier ou `jour_de_saison`), tranche d'altitude et fenêtre des indicateurs vivent dans l'URL
(`fiche.html#m=65&s=2023-2024&a=rang`). Quatre graphes partagent le même axe aligné — risque avec
bande médiane et interquartile (fenêtre `coeur`, saisons comparables, au moins 5 saisons par case),
épaisseur de neige, isotherme 0 °C, vent — et chacun affiche sa couverture : une cellule par jour,
rouge quand la valeur manque. Une saison non comparable reste sélectionnable, avec son motif.


### 9. `bra comparaison` — comparaison de saisons

```bash
uv run bra comparaison                # écrit comparaison.html à la racine (non versionné)
```

Page HTML autonome (environ 1,5 Mo : risque et neige de 36 massifs × 11 saisons). Trois modes — une
saison contre les autres du même massif (bande médiane et interquartile de T11), deux à quatre
saisons choisies, un à quatre massifs sur une même saison — avec courbes superposées (le sélecteur
plafonne à quatre), tableau récapitulatif et classement des saisons en barres horizontales. L'état
vit dans l'URL (`comparaison.html#x=choix&m=65&c=2023-2024,2024-2025&k=jours_3_plus`).

- **Période égale** : par défaut, les séries comparables sont tronquées à leur période commune
  (du dernier premier jour couvert au premier dernier jour couvert, dans la fenêtre), annoncée dans
  le sous-titre de chaque bloc avec la série qui la raccourcit. Case décochée : chaque série garde
  toute sa fenêtre, les jours couverts restent affichés.
- **Classement** : une métrique d'indice (moyenne, jours ≥ 3, ≥ 4, maximum) est refusée hors de la
  fenêtre `coeur`, l'épaisseur de neige l'est sur la saison entière ; la matrice des refus est
  écrite une fois dans `comparaison.py` et voyage dans le payload.
- **Saison non comparable** : affichée, étiquetée avec son motif, valeurs lues sur la période
  commune des saisons comparables, jamais classée et ne fixant pas la période commune.
- Les tests de la page (`tests/test_comparaison.py`) la rendent dans Chromium headless
  (`BRA_CHROMIUM` pour indiquer le binaire) ; ils sont sautés si aucun n'est trouvé.

### 10. `bra exploration` — orientations et vent

```bash
uv run bra exploration                # écrit exploration.html à la racine (non versionné)
```

Page HTML autonome (environ 0,4 Mo : comptes en jours de 36 massifs × 11 saisons × 3 fenêtres).
Quatre blocs : rose des pentes, rose des vents, croisement vent × orientation et situations
typiques, pour un à quatre massifs sur une saison ou une à quatre saisons d'un massif, en roses ou
en barres par secteur — côte à côte, jamais superposées. L'état vit dans l'URL
(`exploration.html#x=saisons&m=65&c=2023-2024,2024-2025&f=coeur&k=ge3&t=haute&d=barres`).

- **Altitude** : chaque rose des pentes et chaque jeu de situations porte l'étiquette « non
  localisée en altitude » (T9) ; il n'y a pas de matrice altitude × orientation. Le vent, lui, a
  une altitude réelle : rose des vents et croisement se lisent par tranche, une à la fois.
- **Situations** : seulement depuis la saison qui en porte ; une saison antérieure l'écrit au lieu
  d'afficher un zéro.
- **Comparer des saisons** n'est permis que sur la fenêtre `coeur` ; le refus vient de
  `exploration.refus`, qui délègue à `risque.fenetre_comparable`. Une saison non comparable reste
  affichable, étiquetée avec son motif et en pointillé.
- Chaque graphe se résume à des lignes {secteur, jours, jours couverts} : roses et barres les
  dessinent, un export les reprendrait telles quelles.

### 11. Exports, URL partageable et attribution (T15)

Mécanisme commun à tous les écrans, défini une fois (`partage.py`, `templates/partage.js`) :

- **Exports** : sous chaque graphe, « Exporter CSV » (les valeurs que la trace vient d'employer,
  en format long, décimale au point ; trois lignes `#` d'en-tête portent l'attribution, la date
  d'archive et le lien — `comment="#"` dans pandas/polars) et « Exporter PNG » (titre et
  attribution ajoutés sous l'image).
- **URL** : tout l'état d'un écran est dans le fragment (`m` massif, `s` saison, `f` fenêtre,
  `t` tranche, `v` versant ; `mc` métrique de la carte). Chaque écran écrit ses clés sans effacer
  celles des autres, et la barre de navigation reporte le fragment complet d'un écran à l'autre.
- **Attribution** : « Données Météo-France, Licence Ouverte 2.0 », date de l'archive, date de
  génération ; sur la carte, les contours en plus (sous la carte et en pied).
- **Ajouter un écran** : voir l'en-tête de `partage.py`. `tests/test_partage.py` échoue tant qu'un
  gabarit n'est pas dans `ECRANS` et branché sur `PARTAGE.demarrer`.
