# CLAUDE.md

Instructions permanentes pour travailler dans ce repo. À lire avant toute modification.

## Ce que fait ce repo

Pipeline d'ingestion et d'agrégation des Bulletins d'Estimation du Risque d'Avalanche de
Météo-France (mars 2016 → juin 2026 ; les 36 massifs du référentiel sont ingérés), et interface
d'analyse historique construite dessus.

Le parsing des six formats XML historiques, la déduplication, l'entrepôt Parquet et les vues
DuckDB sont faits et éprouvés. La couche métriques et les quatre écrans existent (voir « État de l'interface »).

## À lire avant d'écrire du code

Dans cet ordre, et sans sauter d'étape :

1. `README.md` — commandes et liste des pièges d'archive.
2. `docs/glossaire.md` — sens, unité et piège de chaque champ.
3. `docs/exploration.md` — écarts entre l'archive réelle et le descriptif technique officiel.

Ne jamais deviner la sémantique d'un champ : plusieurs portent un nom trompeur. `risque1_evolution`
est un **second indice de risque** et non un code d'évolution ; `naturel` et `accidentel` sont des
**textes rédigés** et non des indices chiffrés ; `enneigement` du BRA est une valeur **indicative**
rattachée à des altitudes de référence, pas une mesure.

## Commandes

```bash
uv sync --extra dev

uv run bra fetch --seasons 2023 2024 --massifs pyrenees   # télécharge le XML dans data/raw/
uv run bra build --replace                                # reconstruit warehouse/ + bra.duckdb
uv run bra check                                           # erreurs vs signaux, séries à trous
uv run bra info                                            # résumé par saison
uv run bra fenetres                                        # comparabilité saison par saison
uv run bra audit                                           # disponibilité champ × saison -> docs/disponibilite.md
uv run bra carte                                           # carte d'accueil des 36 massifs
uv run bra fiche                                           # fiche massif-saison (risque, neige, iso 0, vent)
uv run bra comparaison                                     # comparaison de saisons (courbes, tableau, classement)
uv run bra exploration                                     # rose des pentes, vent x orientation, situations
uv run bra site                                            # les quatre ecrans dans site/ (index.html = la carte) ; --serve pour les exposer en local
uv run bra contours                                        # raccordement + version web des contours
uv run bra ui                                              # interface web DuckDB
uv run pytest
```

`fetch` est idempotent et reprenable (cache sous `data/raw/`, 13 Go pour les 36 massifs). `build`
reconstruit intégralement l'entrepôt : environ 4 minutes et 7 Go de mémoire pour les 36 massifs. Après toute modification du parsing ou
d'une vue : `bra build --replace && bra check && pytest`.

## Règles de données — non négociables

Chacune vient d'un fait d'archive mesuré, documenté dans le glossaire ou le rapport d'exploration.
Les enfreindre ne produit pas une erreur, mais un chiffre faux.

- **Indexer sur `jour_validite`**, jamais sur `jour_bulletin`. Un BRA est rédigé vers 16 h pour le
  lendemain ; une série indexée sur la rédaction est décalée d'un jour.
- **Filtrer `massif_coherent`**, et jamais `zone`, pour écarter le bulletin technique de 2016
  diffusé sous un identifiant alpin : sa zone est une fiction héritée.
- **Avant toute moyenne, exiger `risque_maxi IS NOT NULL`.** `risque_estime = false` dit ce que la
  source a refusé d'estimer ; `risque_maxi IS NULL` dit ce qui sort effectivement du calcul. Les
  deux diffèrent sur quatorze lignes (six sur les Pyrénées), et confondre les deux fait diverger
  un tableau de la moyenne qu'il explique.
- **Toute comparaison inter-saisons d'indice se fait sur la fenêtre `coeur` et sur
  `comparable = true`.** La sentinelle `RISQUE1=-1` s'arrête en juin 2021 : hors de cette fenêtre,
  près de la moitié de l'écart apparent entre les deux époques (47 % sur 36 massifs, 70 % sur les
  Pyrénées) est un artefact d'encodage.
- **Les bornes de fenêtre sont définies une seule fois, dans `fenetres.py`.** Aucun SQL, aucun
  JavaScript, aucun notebook ne les recopie — une borne recopiée est une borne qui divergera.
- **Un niveau de risque est ordinal.** Une moyenne ne se présente jamais seule : elle s'accompagne
  du nombre de jours couverts, et d'un compte de jours par seuil quand c'est l'information utile.
- **`massif_id` est la seule clé stable.** Le libellé change de graphie selon l'époque.
- **Ne pas imputer les `-1` en 1** pour « réparer » la série : ce serait un choix analytique
  déguisé en correction technique.
- **Étiqueter plutôt que supprimer.** Une saison non comparable reste dans l'entrepôt et dans les
  vues, avec son motif. Une lacune supprimée en silence est une lacune qu'on redécouvre au milieu
  d'une analyse.
- **Aucune ligne écartée en silence.** Tout arbitrage qui perd des lignes se journalise ligne à
  ligne, comme `log_daily_collapse_discards()` le fait pour `risque_journalier`. Si l'`ORDER BY`
  d'une vue change, le journal qui le rejoue doit changer avec lui.

## Règles de code

- Python ≥ 3.11, `from __future__ import annotations`, annotations de types partout.
- Dépendances : `polars`, `duckdb`, `httpx`, `pytest`. Toute dépendance supplémentaire se justifie
  explicitement. Pas de pandas, pas de framework web, pas d'ORM.
- Schémas **déclarés** dans `schema.py`, jamais inférés : sur les époques anciennes des colonnes
  sont nulles de bout en bout et polars les typerait en `Null`, ce qui casse la concaténation
  entre saisons.
- Commentaires et docstrings en français **sans accents** (ASCII), comme le code existant. Les
  documents markdown, eux, sont accentués.
- Un commentaire explique *pourquoi*, et cite le fait d'archive qui l'impose quand il y en a un.
  C'est le style du repo ; le conserver vaut mieux que de le résumer.
- Commandes idempotentes, relançables de zéro, sans état résiduel.
- Tests : `pytest`, fixtures = bulletins réels figés (un par époque, plus les cas limites). Toute
  règle de parsing ou d'arbitrage nouvelle arrive avec sa fixture.

## Ne pas faire

- Versionner `data/`, `warehouse/`, les pages HTML générées, les Parquet, les XML (sauf `tests/fixtures/`, bulletins
  isolés partagés par tous les tests, et `tests/series/`, suites de jours consécutifs que seuls
  les tests de métriques lisent : les mêler aux fixtures changerait les saisons vues par tous).
- Introduire un serveur applicatif ou une base serveur. Le front est statique, le moteur est
  DuckDB sur Parquet, et le volume — quelques dizaines de mégaoctets — ne justifie rien d'autre.
  Une base serveur ne se discutera que le jour où l'alerting mail apportera des écritures
  concurrentes, et elle cohabitera alors avec les Parquet au lieu de les remplacer.
- Présenter une anomalie d'archive comme un bug : l'estimation 2019-2020 s'arrête fin mars
  (confinement), le massif 22 (Haut-Var Haut-Verdon) n'apparaît qu'en novembre 2018, le massif 71
  (Andorre) disparaît en 2025-2026, certaines journées sont partielles ou absentes pour tous les
  massifs. Ces faits s'affichent, ils ne se corrigent pas.
- Comparer deux saisons sur leurs bornes brutes.

## État de l'interface

Quatre écrans statiques existent : `bra carte`, `bra fiche`, `bra comparaison`, `bra exploration`
(le tableau de bord Pyrénées, première visualisation, a été retiré).

Le motif est à conserver. Chaque module d'écran construit un payload JSON, `gabarit.py` l'insère
dans le gabarit `templates/<écran>.html` par le marqueur `__DONNEES__` (la fiche encode la série
de chaque massif en une chaîne d'un caractère par jour calendaire) ; tout le filtrage se fait
côté client, sans serveur. Les nouveaux écrans étendent ce motif. Ils n'introduisent pas de
framework : à 36 massifs sur dix ans, la série complète pèse environ 130 Ko avant compression,
ce qui tient largement dans une page.
