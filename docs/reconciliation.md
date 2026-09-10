# Réconciliation : 27 006 fichiers → 23 267 jours-massif

Ce document rend compte, ligne à ligne, de l'écart entre le nombre de bulletins de l'entrepôt
et le nombre de points des séries du tableau de bord. Tout écart non justifié ici est un bug.

Chiffres établis sur le corpus pyrénéen complet (11 massifs, saisons 2015-2016 à 2025-2026),
entrepôt reconstruit le 2026-09-10.

## 1. Le symptôme

Avant correction, `bulletins` comptait **23 533** lignes et les séries du tableau de bord
**20 796** points : **2 737 jours-massif manquants**, sans qu'aucun compteur du build ne bouge.

## 2. Ce que l'écart n'était pas

L'hypothèse de départ attribuait l'essentiel de la perte à des `jour_validite` nuls sur les
bulletins `RISQUE1="-1"`, éliminés par le `WHERE jour_validite IS NOT NULL` de la vue.

```sql
SELECT count(*) FROM bulletins WHERE jour_validite IS NULL;
-- 0
```

**Aucun bulletin n'a de `jour_validite` nul**, ni avant ni après correction : `DATEECHEANCE` est
renseignée sur les 23 533 lignes du corpus. Le filtre sur les nuls n'a jamais rien écarté.
La perte venait entièrement du `row_number()` qui suit — mais les bulletins `-1` étaient bien
en cause, par un autre mécanisme.

## 3. Le mécanisme réel : `DATEVALIDITE` ne désigne pas le jour couvert

Le parser dérivait `jour_validite` de `DATEVALIDITE`, avec repli sur `DATEECHEANCE`. Les deux
attributs coïncident sur **la totalité des bulletins estimés** — 18 869 sur 18 869 — ce qui rend
la confusion indétectable en pleine saison :

```sql
SELECT risque_estime,
       date_diff('day', CAST(date_echeance AS DATE), CAST(date_validite AS DATE)) AS ecart,
       count(*)
FROM bulletins WHERE date_validite IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2;
```

| `risque_estime` | `DATEVALIDITE` − `DATEECHEANCE` | lignes |
|---|---|---|
| true | 0 j | 18 869 |
| false | 0 j | 1 733 |
| false | +1 j | 1 004 |
| false | +2 j | 988 |
| false | +3 j | 486 |
| false | +4 j | 38 |

Hors saison, `DATEVALIDITE` annonce la date du **prochain** bulletin — « valable jusqu'au… » —
et non le jour décrit. Le massif 64 rédige ainsi quatre bulletins consécutifs portant tous la
même `DATEVALIDITE` :

```sql
SELECT massif_id, jour_bulletin, date_echeance, date_validite, risque_estime
FROM bulletins WHERE massif_id = 64
  AND jour_validite BETWEEN DATE '2016-11-21' AND DATE '2016-11-24';
```

| massif | rédigé le | `DATEECHEANCE` | `DATEVALIDITE` | estimé |
|---|---|---|---|---|
| 64 | 2016-11-17 | 2016-11-18 18:00 | **2016-11-21** 18:00 | false |
| 64 | 2016-11-18 | 2016-11-19 18:00 | **2016-11-21** 18:00 | false |
| 64 | 2016-11-19 | 2016-11-20 18:00 | **2016-11-21** 18:00 | false |
| 64 | 2016-11-20 | 2016-11-21 18:00 | **2016-11-21** 18:00 | false |

Quatre jours d'archive s'écrasent sur un seul `(massif_id, jour_validite)`. La vue en retient un
et jette les trois autres, sans bruit. **2 471 bulletins** disparaissaient ainsi.

Le croisement avec `risque_estime` est net : la divergence ne touche **que** les bulletins non
estimés, ce qui explique la concentration de la perte sur 2016-2021, les cinq saisons où la
sentinelle `-1` est en usage.

| saison | non estimés | lignes divergentes |
|---|---|---|
| 2016-2017 | 941 | 634 |
| 2017-2018 | 933 | 621 |
| 2018-2019 | 977 | 587 |
| 2019-2020 | 509 | 224 |
| 2020-2021 | 887 | 450 |
| autres saisons | 3 | 0 |

**Correctif** : `reference = date_echeance or date_validite` (priorité inversée) dans
[parser.py](../src/bra_analytics/parser.py). `DATEECHEANCE` est renseignée partout et donne un
décalage J+1 régulier — 23 388 bulletins sur 23 533, le reste étant les amendements du jour même
(141) et quatre échéances à J+2.

## 4. Les collisions restantes sont réelles

Après correction, **265 lignes** partagent encore un `(massif_id, jour_validite)`. Elles ne sont
pas un défaut : un jour peut légitimement être couvert deux fois.

```sql
WITH r AS (
  SELECT *,
         count(*) OVER w AS grp,
         count(DISTINCT jour_bulletin) OVER w AS jours_de_redaction,
         row_number() OVER (PARTITION BY massif_id, jour_validite
                            ORDER BY date_bulletin DESC, date_diffusion DESC) AS rang
  FROM bulletins
  WINDOW w AS (PARTITION BY massif_id, jour_validite))
SELECT CASE WHEN jours_de_redaction > 1 THEN 'amendement du lendemain matin'
            ELSE 'réédition le même jour' END AS motif,
       count(*) FILTER (rang > 1) AS lignes_écartées
FROM r WHERE grp > 1 GROUP BY 1;
```

| motif | lignes écartées | dont valeur de risque différente |
|---|---|---|
| réédition le même jour (`DATEBULLETIN` déplacé) | 159 | 4 |
| amendement du lendemain matin | 106 | 44 |

**Cinq exemples**, trois amendements et deux rééditions :

| massif | jour couvert | `DATEBULLETIN` | amendement | `risque_maxi` | fichier |
|---|---|---|---|---|---|
| 68 | 2016-03-31 | 2016-03-30 16:00 | false | 3 | `LUCHONNAIS_20160330135201.xml` |
| 68 | 2016-03-31 | 2016-03-31 06:00 | **true** | 3 | `LUCHONNAIS_20160331070701.xml` |
| 74 | 2017-01-16 | 2017-01-15 16:00 | false | 3 | `CERDAGNE-CANIGOU_20170115162855.xml` |
| 74 | 2017-01-16 | 2017-01-16 09:00 | **true** | 3 | `CERDAGNE-CANIGOU_20170116083739.xml` |
| 67 | 2022-03-16 | 2022-03-15 16:00 | false | 3 | `AURE-LOURON_20220315151212.xml` |
| 67 | 2022-03-16 | 2022-03-16 10:00 | **true** | 3 | `AURE-LOURON_20220316092746.xml` |
| 67 | 2023-12-06 | 2023-12-05 **16:00** | false | 2 | `Aure Louron_20231205162407.xml` |
| 67 | 2023-12-06 | 2023-12-05 **18:00** | false | 2 | `Aure Louron_20231205174358.xml` |
| 71 | 2024-12-03 | 2024-12-02 **17:00** | false | 1 | `Andorre (massif)_20241202172100.xml` |
| 71 | 2024-12-03 | 2024-12-02 **18:00** | false | 1 | `Andorre (massif)_20241202175100.xml` |

Les deux motifs sont distincts :

- **Amendement** (toutes saisons) : le bulletin du soir couvre J+1, un amendement émis le
  lendemain matin recouvre la journée en cours. Deux jours de rédaction, deux bulletins, un seul
  jour couvert. Dans **44 cas sur 106 l'amendement corrige l'indice** — la collapse n'est donc pas
  un dédoublonnage mais un arbitrage éditorial, et retenir la rédaction la plus tardive est le
  comportement voulu.
- **Réédition** (2023-2024 et après, 159 lignes sur 3 saisons) : le même bulletin est rediffusé
  une à deux heures plus tard avec un `DATEBULLETIN` déplacé (16:00 → 18:00). La déduplication
  sur `(massif_id, date_bulletin)` ne peut pas les rapprocher, puisque c'est justement la clé qui
  bouge ; seule l'échéance les réunit. C'est la variante « `DATEBULLETIN` mobile » du phénomène
  déjà décrit au 22/02/2023 dans [exploration.md](exploration.md#2-pièges-darchive-hors-périmètre-du-doc).

## 5. Table de passage

### Après correction (état courant)

| étape | lignes | delta | justification |
|---|---|---|---|
| fichiers XML du cache | 27 006 | | `data/raw`, 11 massifs, 11 saisons |
| − doublons de publication | 23 533 | −3 473 | même `(massif_id, date_bulletin)`, `date_diffusion` maximale retenue |
| **table `bulletins`** | **23 533** | | |
| − amendements du lendemain | 23 427 | −106 | jour déjà couvert, rédaction plus tardive retenue |
| − rééditions le même jour | 23 268 | −159 | idem, `DATEBULLETIN` déplacé |
| **vue `risque_journalier`** | **23 268** | | |
| − hors zone Pyrénées | 23 267 | −1 | ID=3, bulletin technique « MOYENNE MONTAGNE » (zone Alpes du Nord) |
| **séries du tableau de bord** | **23 267** | | |

### Avant correction — les 2 737 lignes de l'écart constaté

| poste | lignes | statut |
|---|---|---|
| bulletins hors saison mal datés (`DATEVALIDITE` lue comme jour couvert) | 2 471 | **bug, corrigé** |
| collisions réelles (amendements + rééditions) | 265 | comportement voulu, désormais journalisé |
| bulletin technique hors zone Pyrénées (ID=3) | 1 | comportement voulu |
| **total** | **2 737** | |

**Écart résiduel inexpliqué : 0.** La somme est exacte, non arrondie.

Le découpage 2 508 / 229 initialement supposé était arithmétiquement juste mais mal attribué :
les 2 508 lignes des saisons 2016-2021 se décomposent en 2 471 mal datées **plus 37 collisions
réelles** tombant dans la même fenêtre (15 en 2016-2017, 16 en 2017-2018, 6 en 2020-2021) ;
les 229 restantes sont les 228 collisions des autres saisons plus le bulletin hors zone.

### Effet par saison

| saison | bulletins | jours-massif avant | après | récupérés |
|---|---|---|---|---|
| 2015-2016 | 415 | 411 | 411 | 0 |
| 2016-2017 | 2 445 | 1 814 | 2 430 | **+616** |
| 2017-2018 | 2 430 | 1 804 | 2 414 | **+610** |
| 2018-2019 | 2 431 | 1 844 | 2 431 | **+587** |
| 2019-2020 | 1 563 | 1 345 | 1 563 | **+218** |
| 2020-2021 | 2 371 | 1 925 | 2 365 | **+440** |
| 2021-2022 | 2 451 | 2 416 | 2 416 | 0 |
| 2022-2023 | 2 378 | 2 366 | 2 366 | 0 |
| 2023-2024 | 2 437 | 2 369 | 2 369 | 0 |
| 2024-2025 | 2 407 | 2 354 | 2 354 | 0 |
| 2025-2026 | 2 205 | 2 149 | 2 149 | 0 |
| **total** | **23 533** | **20 797** | **23 268** | **+2 471** |

Les saisons 2018-2019 et 2019-2020 deviennent sans collision : leurs pertes étaient
intégralement dues au mauvais champ de date.

## 6. Plus de perte silencieuse

Une vue SQL est une projection : elle ne peut rien journaliser. C'est ce qui a permis à 2 471
bulletins de disparaître sans qu'aucun compteur ne bouge. Le build rejoue donc l'arbitrage de la
vue et **journalise en `WARNING` chaque ligne écartée**, une ligne de journal par bulletin perdu :

```
collapse quotidienne : bulletin ecarte -- massif=68 jour_couvert=2016-03-31 \
  redige=2016-03-30 16:00:00 diffuse=2016-03-30 15:42:26.602679 amendement=False \
  risque_maxi=3 estime=True motif=jour deja couvert par une redaction plus tardive \
  source=LUCHONNAIS_20160330135201.xml
```

Le rapport de `bra build` en donne le total :

```
bulletins conserves   : 23533
  dont ecartes par la collapse quotidienne : 265 (journalises en WARNING ; 23268 lignes dans risque_journalier)
```

et `bra check` le rappelle sur un entrepôt déjà construit :

```
-- jour_couvert_multiple           265 ligne(s)  bulletins ecartes par risque_journalier (23268 jours-massif retenus)
```

Deux motifs sont journalisés : `jour_validite absent` (aujourd'hui 0 ligne) et
`jour deja couvert par une redaction plus tardive`. Ils couvrent exactement les deux clauses
réductrices de la vue — le `WHERE jour_validite IS NOT NULL` et le `WHERE rang = 1`.

> **Attention.** `daily_collapse_discards()` réplique l'`ORDER BY` de `risque_journalier`.
> Toute modification de l'un doit être répercutée sur l'autre, faute de quoi le journal décrit
> un arbitrage qui n'est plus celui de la vue.
