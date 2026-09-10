# Glossaire des champs BRA

Signification de chaque champ du dataset, avec sa correspondance dans le XML source.

Trois niveaux de certitude sont distingués :

- **Documenté** — figure dans le *Descriptif technique des informations du bulletin avalanche*
  (Météo-France, 26/10/2023).
- **Observé** — établi en analysant les 23 533 bulletins pyrénéens 2016-2026.
- **Inféré** — déduit par corrélation, sans confirmation officielle. Signalé comme tel.

Les écarts entre le descriptif et les données sont détaillés dans [exploration.md](exploration.md).

---

## 1. Notions de base

### Qu'est-ce qu'un BRA

Un Bulletin d'Estimation du Risque d'Avalanche couvre **un massif** et **une échéance**. Il est
rédigé vers 16 h pour le lendemain, et diffusé de début novembre à fin mai.

**Le risque annoncé porte sur l'échéance, pas sur la date de rédaction.** Un bulletin rédigé le
11 février décrit le 12 février. Toute série temporelle doit s'indexer sur `jour_validite`.

Un bulletin peut être **amendé** en cours de journée : un bulletin du soir couvre J+1, un
amendement émis le lendemain matin recouvre la journée en cours.

### L'échelle de risque

Échelle européenne à 5 niveaux, commune à tous les services d'alerte européens (EAWS).

| Indice | Libellé | Signification |
|---|---|---|
| 1 | Faible | Déclenchement généralement possible seulement par forte surcharge, sur de rares pentes raides |
| 2 | Limité | Déclenchement possible par forte surcharge, surtout sur les pentes décrites |
| 3 | Marqué | Déclenchement possible par faible surcharge ; départs spontanés de taille moyenne possibles |
| 4 | Fort | Déclenchement probable par faible surcharge ; départs spontanés nombreux et volumineux |
| 5 | Très fort | Nombreuses avalanches spontanées de grande ampleur, y compris en terrain peu raide |

« Faible surcharge » = un skieur ou un randonneur seul ; « forte surcharge » = un groupe serré,
un engin de damage.

### La saison nivologique

`saison` court de septembre à août (`2025-2026` = septembre 2025 → août 2026). Cette bascule
en septembre place une campagne hivernale entière dans une seule saison, bulletins d'octobre
et de juin compris.

---

## 2. Table `bulletins`

Une ligne par bulletin. Clé : `(massif_id, date_bulletin)`.

### 2.1 Identification et partitionnement

| Champ | Source XML | Type | Description |
|---|---|---|---|
| `massif_id` | `@ID` | int | Identifiant du massif. **Seule clé stable** dans le temps |
| `massif_nom` | *(référentiel)* | str | Libellé normalisé, joint depuis `massifs.py` |
| `massif_nom_source` | `@MASSIF` | str | Libellé tel qu'écrit dans le fichier (varie selon l'époque) |
| `zone` | *(référentiel)* | str | `Alpes du Nord`, `Alpes du Sud`, `Pyrenees`, `Corse` |
| `saison` | *(calculé)* | str | Saison nivologique, ex. `2025-2026` |
| `saison_debut` | *(calculé)* | int | Année de début de saison, pour trier numériquement |
| `type_bulletin` | `@TYPEBULLETIN` | str | Toujours `BRA`. **Absent avant la saison 2016-2017** |
| `producteur` | `@PRODUCTEUR` | str | Centre rédacteur (`CDM651-PREVI`…). **Supprimé en 2024** |
| `fichier_source` | *(ingestion)* | str | Nom du fichier d'origine, pour remonter à la source |

> **Piège.** Le libellé du massif change de graphie (`ASPE-OSSAU` → `Aspe Ossau`,
> `ANDORRE` → `Andorre (massif)`). Ne jamais joindre sur le nom. Et l'`ID` lui-même n'est pas
> infaillible : un bulletin technique de 2016 porte `ID=3` (Mont-Blanc) sous le nom
> « MOYENNE MONTAGNE ». `bra check` le signale.

### 2.2 Dates

| Champ | Source XML | Type | Description |
|---|---|---|---|
| `date_bulletin` | `@DATEBULLETIN` | datetime | Date et heure de **rédaction** (en général J à 16 h) |
| `jour_bulletin` | *(calculé)* | date | Jour de rédaction |
| `date_echeance` | `@DATEECHEANCE` | datetime | Fin de la période couverte (en général J+1 à 18 h) |
| `date_validite` | `@DATEVALIDITE` | datetime | Fin de validité. **Absent en 2016** |
| `jour_validite` | *(calculé)* | date | **Jour décrit par le bulletin.** Repli sur l'échéance si la validité manque |
| `date_diffusion` | `@DATEDIFFUSION` | datetime | Publication effective. Sert à arbitrer les rééditions |
| `amendement` | `@AMENDEMENT` | bool | Bulletin de rectification |

> **Pièges.** Les dates 2016 portent un suffixe `Z` (UTC) et une fraction à 7 chiffres ; elles
> sont converties en heure locale française. `amendement` **ne permet pas de repérer les
> rééditions** : deux publications du même bulletin le portent à `false`.

### 2.3 Estimation du risque

Bloc `<CARTOUCHERISQUE><RISQUE>`, le cœur analytique du bulletin.

| Champ | Source XML | Type | Description |
|---|---|---|---|
| `risque_maxi` | `@RISQUEMAXI` | 1-5 | **Indice retenu pour la journée.** Le champ à utiliser par défaut |
| `risque1` | `@RISQUE1` | 1-5 | Indice principal, ou indice de la tranche basse en cas de distinction |
| `risque1_evolution` | `@EVOLURISQUE1` | 1-5 | **Second indice de la journée** (voir avertissement) |
| `risque2` | `@RISQUE2` | 1-5 | Indice de la seconde zone, si distinction |
| `risque2_evolution` | `@EVOLURISQUE2` | 1-5 | Second indice de la seconde zone |
| `risque_estime` | *(calculé)* | bool | `false` quand aucune estimation chiffrée n'est produite |
| `risque_commentaire` | `@COMMENTAIRE` | str | Formulation textuelle des indices |
| `avis` | `<AVIS>` | str | Vide, `FORT RISQUE D'AVALANCHE` ou `TRES FORT RISQUE D'AVALANCHE` |
| `vigilance` | `<VIGILANCE>` | str | Vide, `JAUNE` ou `ORANGE` (vigilance météo associée) |

> **`EVOLURISQUE1` n'est pas un code d'évolution.** Malgré son nom et le libellé du descriptif
> (« évolution temporelle du risque1 »), il contient **un second indice de risque** sur la même
> échelle 1-5, correspondant à l'évolution attendue dans la journée. On vérifie que
> `risque_maxi = max(risque1, risque1_evolution)`.

> **`risque_estime = false` concerne 18 % du corpus.** La source encode l'absence d'estimation
> par `RISQUE1="-1"`, là où le descriptif annonce « toujours renseigné, valeur de 1 à 5 ». Cela
> correspond aux bulletins de début et de fin de saison, quand le manteau est insuffisant. Ces
> lignes ont `risque1` et `risque_maxi` à `NULL` : **sans filtrer sur `risque_estime`, toute
> moyenne est faussée.**
>
> **Six lignes font exception** : `RISQUE1="-1"` y coexiste avec un `RISQUEMAXI` renseigné
> (cinq en mars 2020, une le 05/11/2023). Elles sont donc `risque_estime = false` **et** comptées
> dans les moyennes. Pour « ce que la source a refusé d'estimer », filtrer sur `risque_estime` ;
> pour « ce qui sort effectivement du calcul », sur `risque_maxi IS NULL`. La vue
> `saison_fenetre` publie les deux comptages séparément (`non_estimes`, `hors_moyenne`) et
> `bra check` signale le cas sous `non_estime_avec_maxi`.

> ### ⚠ Rupture de série : la fin du `-1` en juin 2021
>
> **La pratique du `RISQUE1="-1"` s'arrête au 14 juin 2021.** Elle court du 04/11/2016 au
> 14/06/2021 — aucun cas avant, aucun après. Après cette date, les mêmes journées marginales
> (début et fin de saison, manteau insuffisant) reçoivent **un indice réel, généralement 1**.
>
> Cette rupture n'affecte pas le parsing : les deux encodages se lisent sans ambiguïté. Elle
> affecte **l'interprétation**, et c'est une rupture de série au même titre que la rupture de
> schéma de 2024 — à ceci près qu'elle est invisible dans la structure du fichier, donc
> qu'aucun `schema_version` ne la signale.
>
> Conséquence directe : à nivologie identique, une saison 2016-2021 ressort **plus haute** qu'une
> saison 2021-2026, parce que ses journées à faible risque sont exclues de la moyenne alors que
> celles des saisons récentes y entrent. Mesuré sur les saisons comparables :
>
> | Portée | Moyenne 2016-2021 | Moyenne 2021-2026 | Écart |
> |---|---|---|---|
> | Saison entière | 2,339 | 2,012 | **0,327** |
> | Fenêtre `commune` | 2,339 | 2,031 | **0,308** |
> | Fenêtre `coeur` | 2,356 | 2,258 | **0,098** |
>
> *(moyennes de `risque_maxi` pondérées par bulletin, saisons comparables uniquement.)*
>
> **70 % de l'écart apparent entre les deux époques est un artefact d'encodage.** Et la fenêtre
> `commune` n'en corrige presque rien : c'est `coeur` qui fait le travail.
>
> **Ne pas imputer les `-1` en 1 pour « réparer » la série.** Ce serait un choix analytique — il
> suppose que toute journée non estimée aurait porté l'indice 1 — et non une correction
> technique. Le contournement retenu est une restriction de période, pas une imputation : voir
> § 8.

### 2.4 Localisation du risque

Un bulletin peut distinguer deux niveaux de risque, soit par altitude, soit par orientation.

| Champ | Source XML | Type | Description |
|---|---|---|---|
| `loc_type` | *(calculé)* | str | `altitude`, `orientation`, ou `NULL` si indice unique |
| `altitude_seuil_m` | `@ALTITUDE` | int | Altitude de séparation, en mètres |
| `loc1_secteur` | `@LOC1` | str | Secteur concerné par `risque1` — observé : `E`, `S` |
| `loc2_secteur` | `@LOC2` | str | Secteur concerné par `risque2` — observé : `N`, `W` |

Lecture :

- `loc_type = 'altitude'`, `altitude_seuil_m = 2200` → `risque1` **en dessous** de 2200 m,
  `risque2` **au-dessus**.
- `loc_type = 'orientation'`, `loc1_secteur = 'S'`, `loc2_secteur = 'N'` → `risque1` en versant
  sud, `risque2` en versant nord.

> **Piège.** Dans le XML, `LOC1` et `LOC2` mélangent les deux natures : ils contiennent soit
> `<2200` / `>2200`, soit `S` / `N`. Le parser les décompose en champs typés.

### 2.5 Tendance à J+2 *(depuis 2024 uniquement)*

| Champ | Source XML | Type | Description |
|---|---|---|---|
| `risque_maxi_j2` | `@RISQUEMAXIJ2` | 1-5 | Indice prévu au surlendemain |
| `date_risque_j2` | `@DATE_RISQUE_J2` | datetime | Jour concerné |
| `risque_j2_libelle` | `<RisqueJ2>` | str | Libellé, ex. `Indice de risque limité` |
| `risque_j2_commentaire` | `<CommentaireRisqueJ2>` | str | Facteur principal de l'évolution |

> Le libellé change de formulation : `risque limité` jusqu'en 2024-2025, `Indice de risque
> limité` depuis 2025-2026. Un bulletin (Cerdagne Canigou, 08/01/2025) est tronqué à la source
> (`Indice de`). Préférer `risque_maxi_j2`, qui est numérique et stable.

### 2.6 Rose des pentes

Orientations les plus dangereuses, issues de `<PENTE>`.

| Champ | Type | Description |
|---|---|---|
| `pente_n`, `pente_ne`, `pente_e`, `pente_se`, `pente_s`, `pente_sw`, `pente_w`, `pente_nw` | bool | `true` = orientation concernée |
| `pente_commentaire` | str | Texte affiché sous la rose |

Ces huit champs sont indépendants : plusieurs peuvent être vrais simultanément.

### 2.7 Situations avalancheuses typiques *(depuis 2024 uniquement)*

`sat1` est la situation dominante, `sat2` une situation secondaire éventuelle. Le descriptif
indique « valeur de 1 à 6 » **sans fournir les libellés**. La correspondance ci-dessous est
**inférée** par analyse du vocabulaire des textes de stabilité associés, et recoupe la typologie
standard EAWS des cinq *avalanche problems*.

| Code | Situation *(inférée)* | Indices ayant permis l'inférence |
|---|---|---|
| 1 | Neige fraîche | « neige fraîche » 6× plus fréquent que la moyenne |
| 2 | Neige soufflée / plaques à vent | « plaque » dans 94 % des textes, « vent » dans 55 % |
| 3 | Couche fragile persistante | « persistant » ×3,5, « neige ancienne » ×4,9 |
| 4 | Neige humide | « humide » dans 79 % des textes, « printanier » ×2,5 |
| 5 | Avalanche de glissement | « glissement » ×11,3, « regel » ×11,7 |
| 6 | Manteau insuffisant *(pas une situation typique)* | Risque moyen **1,01** contre 1,76-3,07 ailleurs ; titres « Massif déneigé », « Très peu de neige » ; `sat2` renseigné dans 34 cas sur 956 |

> Le code 6 ne décrit pas un mécanisme d'avalanche mais l'absence de manteau exploitable. À
> traiter à part dans toute analyse des mécanismes.

### 2.8 Textes rédigés

| Champ | Source XML | Description |
|---|---|---|
| `resume` | `<RESUME>` | Synthèse départs spontanés + déclenchements skieurs. Remplace `accidentel`/`naturel` |
| `accidentel` | `<ACCIDENTEL>` | Risque de déclenchement par un skieur |
| `naturel` | `<NATUREL>` | Risque de départ spontané |
| `stabilite_titre` | `<STABILITE><TITRE>` | Titre de la situation nivologique. **Balise dédiée depuis 2025** ; avant, fondu dans le texte |
| `stabilite_texte` | `<STABILITE><TEXTESANSTITRE>` ou `<TEXTE>` | Description de la stabilité du manteau |
| `qualite_texte` | `<QUALITE><TEXTE>` | Qualité de la neige, enneigement skiable, état de surface |
| `meteo_commentaire` | `<METEO><COMMENTAIRE>` | Complément aux conditions météo |

> Certains blocs enveloppent leur contenu dans du balisage HTML (`<h1>`). Le parser concatène le
> texte de tous les descendants, jamais le seul texte direct de l'élément.

### 2.9 Enneigement et vent (niveau bulletin)

| Champ | Source XML | Unité | Description |
|---|---|---|---|
| `enneigement_limite_nord_m` | `<ENNEIGEMENT @LimiteNord>` | m | Altitude d'enneigement continu en versant nord |
| `enneigement_limite_sud_m` | `<ENNEIGEMENT @LimiteSud>` | m | Idem versant sud |
| `vent_altitude_basse_m` | `<METEO @ALTITUDEVENT1>` | m | Altitude de référence du vent bas |
| `vent_altitude_haute_m` | `<METEO @ALTITUDEVENT2>` | m | Altitude de référence du vent haut |

### 2.10 Provenance

| Champ | Type | Description |
|---|---|---|
| `schema_version` | 1-6 | Époque de format détectée **d'après la structure du fichier**, pas d'après sa date |
| `format_famille` | str | `legacy` (versions 1-3, ≤2023) ou `moderne` (versions 4-6, ≥2024) |

> Un bulletin dégradé récent peut présenter les traits d'une époque ancienne (absence de bloc
> `BSH`). `schema_version` décrit le fichier, pas la saison.

---

## 3. Table `meteo`

Prévisions météo par échéance. Clé étrangère : `(massif_id, date_bulletin)`.

| Champ | Source XML | Unité | Description |
|---|---|---|---|
| `origine` | *(calculé)* | | `prevision` (J+1) ou `historique` (7 jours écoulés, bloc `BSH`) |
| `rang` | *(calculé)* | | Position de l'échéance dans la séquence |
| `echeance` | `@DATE` | | Moment de la prévision |
| `vent_bas_vitesse_kmh` | `@FF1` | km/h | Vent à l'altitude basse |
| `vent_bas_direction` | `@DD1` | | Direction, convention anglaise + `VRB` |
| `vent_haut_vitesse_kmh` | `@FF2` | km/h | Vent à l'altitude haute |
| `vent_haut_direction` | `@DD2` | | Idem |
| `iso_0_m` | `@ISO0` | m | Altitude de l'isotherme 0 °C |
| `iso_moins10_m` | `@ISO-10` | m | Altitude de l'isotherme −10 °C *(≤2023)* |
| `limite_pluie_neige_m` | `@PLUIENEIGE` | m | Limite pluie-neige, `-1` si temps sec |
| `temps_sensible` | `@TEMPSSENSIBLE` | code | Code de temps (voir §7) |
| `temps_sensible_libelle` | *(calculé)* | | Libellé, `NULL` si le code est hors palette |
| `mer_nuages_m` | `@MERNUAGES` | m | Altitude de la mer de nuages, `-1` sinon |

**Cardinalités :** 3 échéances de prévision jusqu'en 2023, 4 ensuite ; 21 puis 28 échéances
d'historique (3 puis 4 par jour sur 7 jours).

> **Directions de vent.** La source alterne entre convention anglaise (`NW`, `W`, `SW`, variable
> noté `_`) jusqu'en 2023 et française (`NO`, `O`, `SO`, variable noté `Vrb`) ensuite. Le dataset
> les harmonise en **convention anglaise** — celle qu'utilise déjà la rose des pentes à toutes
> les époques. Valeurs possibles : `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`, `VRB`.

---

## 4. Table `enneigement`

Épaisseurs de neige hors piste, par altitude et par versant.

| Champ | Source XML | Unité | Description |
|---|---|---|---|
| `origine` | *(calculé)* | | `jour` ou `historique` |
| `date_enneigement` | `@DATE` | | Date de la mesure |
| `altitude_m` | `<NIVEAU @ALTI>` | m | Altitude du palier (3 paliers par relevé) |
| `epaisseur_nord_cm` | `<NIVEAU @N>` | cm | Épaisseur en versant nord |
| `epaisseur_sud_cm` | `<NIVEAU @S>` | cm | Épaisseur en versant sud |
| `limite_nord_m` | `@LimiteNord` | m | Altitude d'enneigement continu, versant nord |
| `limite_sud_m` | `@LimiteSud` | m | Idem versant sud |

---

## 5. Table `neige_fraiche`

Cumuls de neige fraîche sur 24 h, de 06 UTC à 06 UTC.

| Champ | Source XML | Unité | Description |
|---|---|---|---|
| `origine` | *(calculé)* | | `prevision` ou `historique` |
| `date_cumul` | `@DATE` | | Jour du cumul |
| `altitude_mesure_m` | `@ALTITUDESS` | m | Altitude de référence de la mesure |
| `cumul_min_cm` | `@SS24Min` / `@SS241` | cm | Borne basse de la fourchette |
| `cumul_max_cm` | `@SS24Max` / `@SS242` | cm | Borne haute |

Six échéances par bulletin : 4 analyses passées + 2 prévisions.

> Les attributs ont été renommés en 2024 (`SS241`/`SS242` → `SS24Min`/`SS24Max`). Le parser
> accepte les deux.

---

## 6. Tables `historique_risque` et `tendances`

### `historique_risque`

Rappel du risque maximal des 7 jours précédents (bloc `BSH`), utile pour reconstituer une série
sans dépendre de la complétude de l'archive.

| Champ | Source XML | Description |
|---|---|---|
| `date_risque` | `@DATE` | Jour concerné |
| `risque_maxi` | `@RISQUEMAXI` | Indice retenu ce jour-là |

### `tendances` *(2016-2023 uniquement)*

Évolution attendue au-delà de l'échéance. Bloc **absent du descriptif technique** et supprimé
en 2024.

| Champ | Source XML | Description |
|---|---|---|
| `date_tendance` | `@DATE` | Jour concerné |
| `valeur` | `@VALEUR` | Code d'évolution |

Valeurs observées, par fréquence : `0` (18 259), `-2` (8 726), `-1` (3 038), `1` (2 943).
La sémantique n'est pas documentée ; l'amplitude suggère une variation d'indice, `0` valant
stabilité. **Inféré, à confirmer avant tout usage analytique.**

---

## 7. Codes de temps sensible

Palette documentée dans le descriptif technique.

| Code | Libellé | Code | Libellé |
|---|---|---|---|
| 0 | clair | 51 | pluie faible |
| 1 | peu nuageux | 53 | pluie forte |
| 2 | nuageux | 58 | pluie et neige mêlées |
| 3 | très nuageux | 59 | pluie verglaçante |
| 4 | couvert | 61 | neige faible |
| 6 | voilé | 63 | neige forte |
| 7 | mer de nuages | 70 | averses |
| 32 | brouillard | 71 | rares averses |
| 38 | brouillard givrant | 77 | averses de pluie et neige mêlées |
| | | 80 | averses de neige |
| | | 85 | averses de grêle |
| | | 90 | orages |
| | | 99 | orages violents |

> **Codes hors palette.** Les données contiennent aussi `-1`, `5`, `8`, `9`, `10`, `11`, `12`,
> `15` et `81`, absents du descriptif. Ils sont conservés bruts dans `temps_sensible`, avec
> `temps_sensible_libelle` à `NULL`. `-1` signifie vraisemblablement « non renseigné ».

---

## 8. Fenêtres de comparaison inter-saisons

Deux saisons ne se comparent pas sur leurs bornes brutes. Deux obstacles s'y opposent, et ils
n'appellent pas la même réponse.

1. **Les saisons n'ont pas la même durée.** La diffusion commence entre le 21 octobre et le
   6 novembre, s'arrête entre le 7 et le 15 juin.
2. **Les journées marginales changent d'encodage en juin 2021** (voir § 2.3). C'est le problème
   lourd : il déplace les moyennes.

D'où deux fenêtres nommées, définies une seule fois dans
[`src/bra_analytics/fenetres.py`](../src/bra_analytics/fenetres.py) et reprises telles quelles
par le SQL, la CLI et le tableau de bord.

| Fenêtre | Bornes | Usage | Comparaison de moyennes |
|---|---|---|---|
| `coeur` | **15 décembre → 15 avril** | toute comparaison inter-saisons d'indice de risque | **oui** |
| `commune` | **6 novembre → 7 juin** | couverture, volumétrie, durée de saison, disponibilité des champs | **non** |
| `saison_complete` | bornes réelles de la saison | lecture d'une saison prise isolément | **non** |

Les bornes se lisent sur `jour_validite` — la journée couverte, grain de toute analyse. Un BRA
étant rédigé la veille pour le lendemain, les mêmes fenêtres se lisent **5 novembre → 6 juin** et
**14 décembre → 14 avril** en date de rédaction. Ne pas mélanger les deux lectures.

### Pourquoi ces bornes-là

**`commune` est l'intersection des spans réels**, hors saisons écartées : l'ouverture la plus
tardive est le 6 novembre (2025-2026), la fermeture la plus précoce le 7 juin (2023-2024).

> **`commune` ne corrige pas le problème du `-1`.** Elle couvre novembre, mai et juin, où la
> sentinelle est massive : 845 bulletins non estimés en 2016-2017 contre 0 en 2022-2023. Une
> moyenne comparée sur cette fenêtre reproduit l'artefact presque intégralement (écart 0,327 →
> 0,308). Elle sert à mesurer ce que l'archive contient, jamais à comparer des indices.

**`coeur` est calée sur la pratique du `-1`, mesurée saison par saison :**

| Saison | Dernier `-1` d'automne | Premier `-1` de printemps |
|---|---|---|
| 2016-2017 | 12 décembre | 28 avril |
| 2017-2018 | 11 décembre | 27 avril |
| 2018-2019 | **13 décembre** | 30 avril |
| 2019-2020 | 12 décembre | *(interrompue au 26 mars)* |
| 2020-2021 | 11 décembre | 30 avril |

L'intervalle exempt de toute sentinelle, toutes saisons confondues, court donc du **14 décembre
au 26 avril**. `coeur` s'y inscrit avec une marge d'un jour à l'ouverture et de onze jours à la
fermeture. Résultat vérifié : **0 bulletin non estimé sur chacune des saisons comparables**, pour
une couverture de 96,9 % à 100 %.

### Saisons écartées

Écartées des comparaisons, mais **nommées et conservées** dans l'entrepôt — une saison retirée en
silence est une saison qu'on redécouvre au milieu d'une analyse. La colonne `comparable` de
`saison_fenetre` porte le drapeau, `motif_exclusion` la raison.

| Saison | Motif |
|---|---|
| 2015-2016 | saison partielle : l'archive démarre le 10 mars 2016, après l'ouverture des deux fenêtres |
| 2019-2020 | interrompue le 26 mars 2020 (confinement) : tronquée sur les deux fenêtres |

### Vue `saison_fenetre`

Une ligne par saison et par portée. C'est le tableau de référence de toute comparaison.

| Colonne | Description |
|---|---|
| `fenetre` | `coeur`, `commune` ou `saison_complete` |
| `comparable` | la saison entre-t-elle dans une comparaison sur cette fenêtre |
| `motif_exclusion` | raison de l'exclusion, `NULL` si la saison est comparable |
| `bulletins` | jours-massifs couverts dans la fenêtre |
| `massifs_actifs` | massifs réellement diffusés **sur la saison** — dénominateur de la couverture |
| `massifs_presents` | massifs présents dans la fenêtre |
| `non_estimes` | bulletins que la source a refusé d'estimer (`risque_estime = false`) |
| `hors_moyenne` | bulletins effectivement exclus du calcul (`risque_maxi IS NULL`) |
| `jours_fenetre` | durée **nominale** de la fenêtre, années bissextiles comprises |
| `couverture_pct` | `bulletins / (massifs_actifs × jours_fenetre)` |
| `risque_moyen` | moyenne de `risque_maxi` sur la fenêtre |

> **La couverture se rapporte aux massifs actifs, pas à un effectif figé.** Andorre (ID 71) n'est
> plus diffusé en 2025-2026 : rapporter cette saison à onze massifs la plafonnerait à 91 % alors
> qu'elle est complète sur les dix massifs qui existent.

> **`jours_fenetre` est calculé, pas codé en dur.** La fenêtre `coeur` compte 123 jours les
> années bissextiles et 122 les autres.

`risque_journalier` porte par ailleurs un booléen `fenetre_coeur` et `fenetre_commune` par ligne :
filtrer dessus plutôt que de recopier des bornes dans une requête, qui divergeraient de la
définition.

```sql
SELECT saison, risque_moyen, couverture_pct, massifs_actifs
FROM saison_fenetre
WHERE fenetre = 'coeur' AND comparable
ORDER BY saison;
```

En ligne de commande : `bra fenetres` republie ce tableau, mesures et justifications comprises.

### Périmètre : le bulletin technique de 2016

Un message technique (« les BRA ne sont pas produits sur les massifs de moyenne montagne ») est
diffusé le 04/11/2016 sous `ID="3"` — le Mont-Blanc au référentiel — avec
`MASSIF="MOYENNE MONTAGNE"`. La ligne hérite donc d'un massif, d'une zone et d'un département qui
ne sont pas les siens.

**Un filtre posé sur `zone` ne l'écarte pas pour la bonne raison** : il la classe dans les Alpes,
et la laisserait passer si le même incident se reproduisait sous un identifiant pyrénéen. Le
filtre correct est la colonne `massif_coherent`, qui compare l'`ID` au libellé `MASSIF` en
tolérant les variantes de graphie recensées. Toutes les vues de comparaison la filtrent.

Sans elle, `bra info` comptait **12 massifs** en 2015-2016 sur une chaîne qui en a onze, et
faisait démarrer la saison au **4 février** au lieu du 9 mars. `bra info` liste désormais les
lignes écartées au lieu de les faire disparaître.
