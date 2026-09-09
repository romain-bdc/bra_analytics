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
