# bra-analytics

Pipeline d'ingestion, de parsing et d'agrégation des **Bulletins d'Estimation du Risque
d'Avalanche** (BRA) de Météo-France, publiés sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence).

Source : `https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA/AAAA/MM/JJ/xml/` (sans authentification).
Couverture : mars 2016 → juin 2026, 36 massifs (Alpes, Pyrénées, Corse).

Le format XML a **changé six fois** sur la période. La pipeline ramène ces variantes à un
schéma unique. Les écarts constatés — y compris avec le descriptif technique officiel du
26/10/2023 — sont recensés dans **[docs/exploration.md](docs/exploration.md)**, à lire avant
toute interprétation des données.

## Installation

```bash
uv sync --extra dev
```

## Utilisation

```bash
uv run bra fetch --seasons 2023 2024 2025 --massifs pyrenees
```

```bash
uv run bra build
```

```bash
uv run bra info
```

```bash
uv run bra check
```

`check` distingue les **erreurs** (données incohérentes : indice hors échelle, clé dupliquée,
échéance antérieure à la rédaction) des **signaux** (faits réels de l'archive : amendements,
séries à trous) qu'il vaut mieux constater avant de les découvrir en cours d'analyse.

`fetch` accepte `--massifs pyrenees|alpes|corse|all` ou une liste d'identifiants (`--massifs 65,67`),
et `--start/--end` à la place de `--seasons`. Le cache local rend l'ingestion idempotente :
relancer la commande ne retélécharge que ce qui manque.

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
| `profil_saison` | 1 ligne / massif / saison | comparaisons inter-saisons |

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
- **Un jour peut recevoir deux bulletins.** Le bulletin du soir couvre J+1 ; un amendement émis
  le lendemain matin (`amendement = true`) recouvre la journée en cours. Les deux sont conservés
  dans `bulletins` et arbitrés dans `risque_journalier` (rédaction la plus tardive).
- **`massif_id` est la seule clé stable.** Le libellé change de graphie selon l'époque
  (`ASPE-OSSAU` → `Aspe Ossau`, `ANDORRE` → `Andorre (massif)`). La colonne `massif_nom` porte
  le libellé normalisé du référentiel, `massif_nom_source` celui du fichier.
- **`risque_estime = false` signale un bulletin sans estimation chiffrée** (début et fin de
  saison, faute d'enneigement). La source y met `RISQUE1 = -1` ; la pipeline convertit cette
  sentinelle en valeur nulle pour ne pas fausser les moyennes. Cela concerne ~34 % des bulletins
  2016-2022 : filtrer sur `risque_estime` avant tout agrégat, ou s'appuyer sur `profil_saison`
  qui l'exclut déjà.
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
  en 2016 — un message technique, pas un bulletin. `bra check` le signale ; l'écarter avec
  `WHERE massif_id IN (SELECT id FROM massifs_pyrenees)` ou par le contrôle de cohérence.
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
