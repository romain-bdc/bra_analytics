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
   champs typés, sentinelle `RISQUE1="-1"` convertie en valeur nulle, dates ramenées à l'heure
   locale ;
3. **déduplique** sur `(massif_id, date_bulletin)` en retenant la diffusion la plus tardive —
   un même bulletin est souvent republié dans la journée ;
4. **enrichit** avec le référentiel des massifs et la saison nivologique ;
5. **écrit** six tables en Parquet partitionné par saison, puis crée la base DuckDB et ses vues.

L'opération est **idempotente** : `warehouse/` est reconstruit intégralement à chaque appel, sans
état résiduel. Sur les 11 saisons pyrénéennes (27 000 fichiers, 3,7 Go), elle prend environ 40 s
et produit 6,2 Mo de Parquet — les images embarquées, qui pèsent 93 % du XML ancien, sont écartées.

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
  2015-2016       414       11  2016-03-09  2016-04-24          2.52
  2016-2017      2445       11  2016-11-03  2017-06-13          2.31
  ...
  2019-2020      1563       11  2019-10-30  2020-03-25          2.16
  ...
  2025-2026      2205       10  2025-11-05  2026-06-07          2.19

  La colonne « risque moy. » porte sur la saison entiere : elle n'est
  pas comparable d'une saison a l'autre. Voir `bra fenetres`.

Ecartees du tableau (1 couple(s) saison/massif) — ID et libelle se contredisent :
  2015-2016  ID=3 (Mont-Blanc) porte MASSIF='MOYENNE MONTAGNE' — 1 bulletin(s)
```

Cette sortie se lit aussi comme un diagnostic. Deux faits d'archive y sautent aux yeux, et les
deux sont réels : une saison 2019-2020 qui s'arrête au 25 mars (confinement) et 10 massifs en
2025-2026 (le massif Andorre n'est plus diffusé). Le troisième — un bulletin technique de 2016
diffusé sous un identifiant alpin — est désormais écarté du tableau et listé en dessous : il
comptait auparavant pour un douzième massif pyrénéen et faisait démarrer la saison au 4 février.

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
  2016-2017        1341       11         0    122  99.9 %   2.386
  ...
  2025-2026        1220       10         0    122 100.0 %   2.573
```

Deux fenêtres, deux usages : `coeur` (15 déc → 15 avr) pour comparer des indices, `commune`
(6 nov → 7 juin) pour comparer des couvertures. Les bornes sont mesurées, pas choisies — le
détail du calcul est dans [le glossaire, § 8](docs/glossaire.md#8-fenêtres-de-comparaison-inter-saisons).

Une commande auxiliaire, `bra massifs`, affiche le référentiel des 36 massifs.

## Sortie

```
warehouse/
  bulletins/saison=2025-2026/data.parquet      1 ligne par bulletin
  meteo/saison=.../data.parquet                échéances météo (prévision + 7 jours écoulés)
  enneigement/…                                épaisseurs par altitude et versant
  neige_fraiche/…                              cumuls 24 h
  historique_risque/…                          risque max des 7 jours précédents
  tendances/…                                  tendances J+2 et J+3 (2016-2023 uniquement)
  bra.duckdb                                   vues sur l'ensemble
```

La base DuckDB expose chaque table, plus trois vues de travail :

| Vue | Grain | Usage |
|---|---|---|
| `risque_journalier` | 1 ligne / massif / **jour couvert** | séries temporelles |
| `couverture` | 1 ligne / massif / saison | repérer les trous d'archive |
| `profil_saison` | 1 ligne / massif / saison | profil d'une saison, massif par massif |
| `saison_fenetre` | 1 ligne / saison / fenêtre | **comparaisons inter-saisons** |

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
  (rédaction la plus tardive) : **265 lignes** sur 23 533, dont 48 portent un indice différent de
  celui retenu. `bra build` journalise chacune en `WARNING` et `bra check` en donne le total —
  l'écart entre les deux comptages n'est jamais silencieux.
- **`massif_id` est la seule clé stable.** Le libellé change de graphie selon l'époque
  (`ASPE-OSSAU` → `Aspe Ossau`, `ANDORRE` → `Andorre (massif)`). La colonne `massif_nom` porte
  le libellé normalisé du référentiel, `massif_nom_source` celui du fichier.
- **`risque_estime = false` signale un bulletin sans estimation chiffrée** (début et fin de
  saison, faute d'enneigement). La source y met `RISQUE1 = -1` ; la pipeline convertit cette
<<<<<<< HEAD
  sentinelle en valeur nulle pour ne pas fausser les moyennes. Cela concerne **4 250 bulletins
  sur 23 533, soit 18,1 % du corpus**, très concentrés : 4 247 d'entre eux tombent sur les cinq
  saisons 2016-2017 à 2020-2021, où ils pèsent 37,8 % des 11 240 bulletins. Filtrer sur
  `risque_estime` avant tout agrégat, ou s'appuyer sur `profil_saison` qui l'exclut déjà.
=======
  sentinelle en valeur nulle pour ne pas fausser les moyennes. Cela concerne ~34 % des bulletins
  2016-2022 : filtrer sur `risque_estime` avant tout agrégat, ou s'appuyer sur `profil_saison`
  qui l'exclut déjà.
  Six lignes font exception : `RISQUE1 = -1` y coexiste avec un `RISQUEMAXI` renseigné, si bien
  qu'elles sont non estimées **et** comptées dans les moyennes (`bra check` les signale sous
  `non_estime_avec_maxi`).
- **La pratique du `-1` s'arrête en juin 2021 : c'est une rupture de série.** Elle court du
  04/11/2016 au 14/06/2021, sans aucun cas avant ni après. Ensuite, les mêmes journées marginales
  reçoivent un indice réel, généralement 1, et entrent donc dans les moyennes. Conséquence : à
  nivologie identique une saison 2016-2021 ressort plus haute qu'une saison récente, et **70 % de
  l'écart apparent entre les deux époques est un artefact d'encodage** (0,327 point sur la saison
  entière, 0,098 sur la fenêtre `coeur`). Contrairement à la rupture de schéma de 2024, celle-ci
  est invisible dans la structure du fichier : aucun `schema_version` ne la signale.
- **Ne jamais comparer deux saisons sur leurs bornes brutes.** Utiliser la vue `saison_fenetre`,
  ou les booléens `fenetre_coeur` / `fenetre_commune` de `risque_journalier`. La fenêtre `coeur`
  (15 déc → 15 avr) est la seule sur laquelle aucune saison n'emploie la sentinelle ; `commune`
  (6 nov → 7 juin) sert aux couvertures et **pas** aux moyennes. Les saisons 2015-2016 (partielle)
  et 2019-2020 (Covid) sont étiquetées non comparables plutôt que supprimées. Voir
  [le glossaire, § 8](docs/glossaire.md#8-fenêtres-de-comparaison-inter-saisons).
- **Ne pas imputer les `-1` en 1 pour « réparer » la série.** Ce serait un choix analytique — il
  suppose que toute journée non estimée aurait porté l'indice 1 — pas une correction technique.
>>>>>>> a8e009e (Comparer les saisons sur des fenetres mesurees plutot que sur leurs bornes brutes)
- **`risque1_evolution` est un second indice de risque**, pas un code d'évolution, malgré le nom
  de l'attribut source `EVOLURISQUE1`. `risque_maxi = max(risque1, risque1_evolution)`.
- **`loc_type`** indique si `risque1`/`risque2` se distinguent par altitude (`altitude_seuil_m`
  renseigné) ou par orientation (`loc1_secteur`/`loc2_secteur`).
- **Colonnes nulles par construction** avant 2024 : `sat1`, `sat2`, `risque_maxi_j2`,
  `risque_j2_libelle`, `stabilite_titre`. Et après 2023 : `producteur`, `tendances`.
  Filtrer sur `format_famille` ou `schema_version` pour les comparaisons inter-époques.
- **Le massif 71 (Andorre) disparaît en 2025-2026.** Une rupture de série n'est pas un bug.
- **Trous réels dans l'archive**, à ne pas confondre avec des défauts d'ingestion :
  la saison 2019-2020 s'arrête au **26 mars 2020** (confinement) ; certaines journées sont
  partielles (07/02/2023 : 8 bulletins au lieu de 36) ; 2 fichiers sur 27 006 sont corrompus
  côté serveur (réponse « 500 » servie sous un code HTTP 200).
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
