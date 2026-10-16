# Glossaire des champs BRA

Signification de chaque champ du dataset, avec sa correspondance dans le XML source.

Trois niveaux de certitude sont distingués :

- **Documenté** — figure dans le *Descriptif technique des informations du bulletin avalanche*
  (Météo-France, 26/10/2023).
- **Observé** — établi en analysant les bulletins 2016-2026 : d'abord les 23 533 bulletins
  pyrénéens, puis les 77 488 bulletins des 36 massifs (octobre 2026). Un chiffre sans mention de
  périmètre porte sur les Pyrénées.
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

**Second axe temporel** — porté par la vue `risque_journalier`, pas par la table :

| Champ | Source | Type | Description |
|---|---|---|---|
| `jour_de_saison` | *(calculé)* | int | Rang du jour dans la saison **de ce massif** : 1 au premier `jour_validite` du couple massif × saison, puis +1 par jour calendaire |

> **`jour_de_saison` se compte massif par massif, pas depuis une date commune.** La diffusion
> n'ouvre pas le même jour partout : en 2015-2016, l'archive livre Aspe-Ossau dès le 10 mars et
> Couserans le 31 mars seulement ; chacun démarre à 1. C'est l'axe qui empêche une saison
> ouverte tardivement de paraître vide en décembre. L'axe calendaire reste celui par défaut.
>
> - Il compte des **jours calendaires**, pas des jours couverts : un trou d'archive avance le
>   compteur sans produire de ligne. Deux lignes consécutives peuvent donc porter 12 et 14.
> - Les jours **non estimés** (`RISQUE1=-1`) comptent : l'axe mesure la diffusion, pas
>   l'indice. Conséquence : avant juin 2021, le jour 1 tombe souvent sur un bulletin sans indice.
> - Il vaut `NULL` sur les lignes `massif_coherent = false`, et ces lignes ne fixent pas le
>   jour 1 de leur massif : sans cette règle, le message technique du 05/02/2016 diffusé sous
>   `ID="3"` avancerait de 35 jours le début de saison du Mont-Blanc.

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
> (cinq en mars 2020, une le 05/11/2023). Sur les 36 massifs elles sont quatorze : s'y ajoutent
> six en décembre 2018 et deux le 05/11/2023, en Alpes du Nord. Elles sont donc `risque_estime = false` **et** comptées
> dans les moyennes. Pour « ce que la source a refusé d'estimer », filtrer sur `risque_estime` ;
> pour « ce qui sort effectivement du calcul », sur `risque_maxi IS NULL`. La vue
> `saison_fenetre` publie les deux comptages séparément (`non_estimes`, `hors_moyenne`) et
> `bra check` signale le cas sous `non_estime_avec_maxi`.

> ### ⚠ Rupture de série : la fin du `-1` en juin 2021
>
> **La pratique du `RISQUE1="-1"` s'arrête au 11 juin 2021.** Elle court du 04/11/2016 au
> 11/06/2021 en jours couverts (`jour_validite`) — aucun cas avant, et après seulement quatre
> bulletins isolés : trois `-1` le 05/11/2023, et un `RISQUE1` vide le 09/01/2025 (Cerdagne-Canigou,
> écarté de `risque_journalier` par une rédaction plus tardive du même jour). Après cette date,
> les mêmes journées marginales (début et fin de saison, manteau insuffisant) reçoivent **un
> indice réel, généralement 1**.
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
> *(moyennes de `risque_maxi` pondérées par bulletin, saisons comparables uniquement ; mesure
> initiale sur les 11 massifs pyrénéens.)*
>
> Remesuré sur les **36 massifs** (octobre 2026, une ligne par jour-massif de
> `risque_journalier`) :
>
> | Portée | Moyenne 2016-2021 | Moyenne 2021-2026 | Écart |
> |---|---|---|---|
> | Saison entière | 2,451 | 2,083 | **0,368** |
> | Fenêtre `commune` | 2,451 | 2,097 | **0,354** |
> | Fenêtre `coeur` | 2,482 | 2,286 | **0,196** |
>
> **Une large part de l'écart apparent entre les deux époques est un artefact d'encodage : 70 %
> sur les Pyrénées, 47 % sur les 36 massifs.** Dans les deux cas la fenêtre `commune` n'en
> corrige presque rien : c'est `coeur` qui fait le travail. L'écart qui subsiste sur `coeur` n'est
> pas pour autant un signal nivologique : il mêle les saisons réelles et l'évolution des
> pratiques de rédaction.
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
| `sans_enneigement_continu_nord` / `_sud` | *(calculé)* | | Vrai si la limite vaut `-1` sur un relevé fait (voir § 4) |
| `vent_altitude_basse_m` | `<METEO @ALTITUDEVENT1>` | m | Altitude de référence du vent bas |
| `vent_altitude_haute_m` | `<METEO @ALTITUDEVENT2>` | m | Altitude du vent haut ; nulle s'il n'y a qu'un vent (`9999`) |

> **Un seul vent dans les Alpes du Sud jusqu'en 2023.** Les neuf massifs 13 et 16 à 23 portent
> `ALTITUDEVENT1="3000" ALTITUDEVENT2="9999"` et `FF2="-1"` : un vent unique, à 3000 m, dans la
> colonne « basse ». Depuis 2024 ils ont 2000 et 3000 m. `9999` est lu comme « pas de second
> vent » (altitude nulle) ; `bra check` compte ces bulletins sous `vent_unique`. Toute métrique
> de vent passe donc par l'altitude ou la tranche, jamais par le rôle bas / haut : le vent à
> 3000 m de ces massifs change de colonne en 2024, pas de tranche.

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

> **Échéance vide.** Avant 2024, des échéances entières arrivent à `-1` (19 822 sur les 36
> massifs, dont 244 en prévision) : vent, isothermes et temps sensible deviennent nuls, la ligne
> reste. Depuis, 4 454 échéances arrivent avec des attributs vides (142 en prévision). `bra check`
> compte les unes et les autres sous `echeance_meteo_vide`. Seul `-1` est converti ; une
> vitesse hors [0, 300] km/h (400 et 530 km/h, −5 km/h, isolées) est une **erreur** de
> `bra check`, conservée telle quelle et exclue des métriques.

> **Convention d'extraction (spec § 4.3, arrêtée le 15 octobre 2026) : prévision seule,
> valeur du jour sur 06 h et 12 h.** Pour un jour donné, la météo est lue dans le bulletin qui
> le couvre (`origine = 'prevision'`, échéance sur `jour_validite`) et jamais dans le bloc
> historique. Raisons mesurées : l'historique manque toute la saison 2015-2016 et 1 à 2 % des
> jours jusqu'en 2023, il ne porte plus `mer_nuages_m` depuis 2024, et il diffère à peine de la
> prévision (isotherme 0 °C : 32 à 37 m d'écart moyen, plus de 500 m dans 1,1 à 1,3 % des cas ;
> temps sensible identique dans 75 à 80 % des cas). Le préférer aurait mêlé deux horizons pour
> un gain de l'ordre de 35 m. Les heures diffèrent selon l'époque — 00 h, 06 h, 12 h de J
> jusqu'en 2023 ; 06 h, 12 h, 18 h de J et 00 h de J+1 ensuite — : la valeur du jour se calcule
> sur les seules échéances communes, **06 h et 12 h**.

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
| `altitude_m` | `<NIVEAU @ALTI>` | m | Altitude du palier (3 paliers par relevé) ; nulle si non relevé |
| `epaisseur_nord_cm` | `<NIVEAU @N>` | cm | Épaisseur en versant nord |
| `epaisseur_sud_cm` | `<NIVEAU @S>` | cm | Épaisseur en versant sud |
| `limite_nord_m` | `@LimiteNord` | m | Altitude d'enneigement continu, versant nord ; nulle si absente |
| `limite_sud_m` | `@LimiteSud` | m | Idem versant sud |
| `sans_enneigement_continu_nord` / `_sud` | *(calculé)* | | Vrai : pas d'enneigement continu ; nul : non relevé |

> **Un `-1` de limite n'est pas une lacune.** `LimiteNord` / `LimiteSud` valent `-1` dans deux
> cas. **Relevé non fait** : les trois paliers valent `ALTI="-1"` (1 878 relevés avant 2024) ;
> altitudes, épaisseurs et limites deviennent nulles, l'indicateur aussi (`bra check` :
> `releve_enneigement_vide`). **Relevé fait** : chaque limite `-1` accompagne une épaisseur nulle
> à tous les paliers (2 903 relevés du jour côté sud, aucun contre-exemple) ; il n'y a pas
> d'enneigement continu. La limite devient nulle — une altitude fictive fausserait toute
> moyenne — et `sans_enneigement_continu_*` vaut vrai (`bra check` :
> `sans_enneigement_continu`). Une métrique de date d'enneigement continu lit l'indicateur, pas
> la seule limite.

---

## 5. Table `neige_fraiche`

Cumuls de neige fraîche sur 24 h, de 06 UTC à 06 UTC.

| Champ | Source XML | Unité | Description |
|---|---|---|---|
| `origine` | *(calculé)* | | `prevision` ou `historique` |
| `date_cumul` | `@DATE` | | Jour du cumul |
| `altitude_mesure_m` | `@ALTITUDESS` | m | Altitude de référence de la mesure |
| `secteur1_libelle` / `secteur2_libelle` | `@SECTEURSS1` / `@SECTEURSS2` | | Secteurs nommés *(≤ 2023)* : `massif` seul, ou `Nord`/`Sud`, `Ouest`/`Est`… |
| `secteur1_cumul_cm` / `secteur2_cumul_cm` | `@SS241` / `@SS242` | cm | Cumul de chaque secteur *(≤ 2023)* |
| `cumul_min_cm` | `@SS24Min`, ou dérivé | cm | Borne basse ; avant 2024, le plus faible des secteurs |
| `cumul_max_cm` | `@SS24Max`, ou dérivé | cm | Borne haute ; avant 2024, le plus fort des secteurs |

Six échéances par bulletin : 4 analyses passées + 2 prévisions.

> **Deux lectures, une rupture de série à l'hiver 2023-2024** (décision du 15 octobre 2026).
> Jusqu'en 2023, le bloc nomme un ou deux secteurs (`SECTEURSS1` / `SECTEURSS2`) et `SS241` /
> `SS242` sont le cumul de **chacun** — pas un minimum et un maximum. Six massifs ont deux
> secteurs sur 81 à 88 % de leurs lignes : Haute-Tarentaise, Haute-Maurienne, Queyras, Ubaye,
> Haute-Bigorre, Cerdagne-Canigou ; les autres n'en ont qu'un (`massif`). Le parser conserve
> les secteurs et en dérive les bornes (secteur unique, ou un seul des deux secteurs observé :
> min = max). Depuis 2024, `SS24Min` /
> `SS24Max` sont une fourchette sur le massif, égale dans 66 % des lignes. Les deux se lisent,
> mais ne mesurent pas la même chose : une comparaison qui enjambe l'hiver 2023-2024 l'annonce.

> **Valeurs négatives.** `-1` signale l'absence de second secteur ; `-2` (15 à 21 % des lignes
> 2016-2023 dans chaque massif, à toutes les positions du bloc, disparu en 2024) est lu comme
> **non observé** — *inféré*, aucun descriptif de l'ancien format ne le documente. Les deux
> deviennent nuls ; `bra check` compte les cumuls de secteur non observés
> (`neige_fraiche_non_observee`). Mesure : [`disponibilite.md`](disponibilite.md) § 9.

> **Un même cumul, deux dates selon le bloc depuis 2024.** Le bloc historique moderne date une
> fenêtre de 24 h au lendemain du bloc principal (31 254 paires non nulles sur 31 254) ; avant
> 2024, les deux blocs portent la même date. `date_cumul` reste la date écrite dans le XML ; la
> vue `neige_fraiche_jour` recale le bloc moderne et dédoublonne les six rédactions d'un même
> jour (§ 10).

### Tranches d'altitude normées — vue `palier_tranche`

Les altitudes de référence varient d'un massif et d'une époque à l'autre. La vue
`palier_tranche` rattache chaque palier d'enneigement, de neige fraîche et de vent à l'une des
trois tranches définies une fois dans `src/bra_analytics/tranches.py` :

| Tranche | Bornes |
|---|---|
| `basse` | < 1800 m |
| `moyenne` | 1800 m ≤ altitude < 2400 m |
| `haute` | ≥ 2400 m |

Une ligne par valeur mesurée à une altitude, toutes sources confondues (`source` :
`enneigement`, `neige_fraiche`, `vent_bas`, `vent_haut`). `jour` est la date que décrit la
valeur — relevé, cumul ou échéance —, pas `jour_validite`.

> **Bornes fermées à gauche, et pas « > 2400 m ».** Les paliers d'enneigement tombent pile sur
> les bornes : 1500/1800/2400 m (ou 1500/1800/2100) jusqu'en 2020-2021, 1500/2000/2500 m ensuite.
> Fermées à gauche, les deux époques ont chacune un palier par tranche.

> **Pièges.**
> - Une tranche sans palier **n'a pas de ligne** : rien n'est interpolé. Avant 2021, seuls 6
>   massifs pyrénéens sur 11 ont un palier en tranche `haute`.
> - Neige fraîche et vent ont **une** altitude de référence par bulletin : une seule tranche
>   par construction. La neige fraîche est mesurée à 1800 m, donc en tranche `moyenne` ; la
>   tranche `basse` n'a jamais de neige fraîche.
> - Un relevé non fait (paliers à `ALTI="-1"` avant 2024, altitude rendue nulle par le parser)
>   garde sa ligne avec `tranche` nulle.
> - Un bulletin sans second vent (`ALTITUDEVENT2="9999"`, Alpes du Sud jusqu'en 2023) n'a pas de
>   palier `vent_haut` : son vent unique, à 3000 m, entre par `vent_bas` et tombe en tranche
>   `haute`, comme le vent à 3000 m de ces massifs après 2024.
> - L'enneigement reste **indicatif** : la tranche ne transforme pas un palier en mesure.

---

## 6. Tables `historique_risque` et `tendances`

### `historique_risque`

Rappel du risque maximal des 7 jours précédents (bloc `BSH`), utile pour reconstituer une série
sans dépendre de la complétude de l'archive.

| Champ | Source XML | Description |
|---|---|---|
| `date_risque` | `@DATE` | Jour concerné |
| `risque_maxi` | `@RISQUEMAXI` | Indice retenu ce jour-là |

> **Piège.** Une valeur hors échelle y est lue comme non estimée, par la même règle que
> `RISQUE1` (§ 2.3). L'archive en compte sept : `RISQUEMAXI="0"` pour la journée du 16/04/2022
> dans les sept bulletins Haut-Var/Haut-Verdon rédigés du 16 au 22/04/2022 (huit fichiers, celui
> du 22 étant diffusé deux fois), alors que le BRA couvrant ce jour dit 1. Ces lignes restent
> dans la table, avec un `risque_maxi` nul.

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

### `conversions` — journal du parser

Une ligne par bulletin retenu, table, champ et valeur source : chaque sentinelle que le parser
rend nulle y est comptée (`valeurs`), y compris sur une échéance ou un relevé par ailleurs
renseigné. `bra check` l'agrège en signaux `sentinelle <table>.<champ>=<valeur>` : une valeur
devenue nulle sans trace serait une ligne écartée en silence.

| Champ | Description |
|---|---|
| `table_cible`, `champ` | Où la valeur a été rendue nulle |
| `valeur_source` | Valeur lue dans le XML (`-1`, `-2`, `9999`…) |
| `valeurs` | Nombre de valeurs converties dans ce bulletin |

La règle météo convertit tout `-1` d'un champ, pas seulement les échéances entièrement vides :
un `FF2="-1"` à côté d'un `ISO0` renseigné (second vent absent) ou un `ISO-10="-1"` isolé
(6 665 valeurs avant 2024) est aussi une valeur non renseignée.

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

> **Codes hors palette.** Les données contiennent aussi `5`, `8`, `9`, `10`, `11`, `12`, `15` et
> `81`, absents du descriptif. Ils sont conservés bruts dans `temps_sensible`, avec
> `temps_sensible_libelle` à `NULL`. `-1` (« non renseigné », le plus souvent sur une échéance
> entièrement vide) est rendu nul par le parser, comme les autres valeurs météo à `-1` (§ 3).

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

**`commune` est l'intersection des spans réels**, hors saisons écartées : sur les Pyrénées,
l'ouverture la plus tardive est le 6 novembre (2025-2026), la fermeture la plus précoce le 7 juin
(2023-2024). Remesurée sur les 36 massifs, l'intersection s'élargit à **4 novembre → 7 juin** —
les Alpes ouvrent plus tôt en 2025-2026. La borne du 6 novembre est conservée : elle reste incluse
dans chaque saison, et la déplacer ferait bouger toutes les couvertures publiées sans rien
corriger.

> **`commune` ne corrige pas le problème du `-1`.** Elle couvre novembre, mai et juin, où la
> sentinelle est massive : 845 bulletins non estimés en 2016-2017 contre 0 en 2022-2023. Une
> moyenne comparée sur cette fenêtre reproduit l'artefact presque intégralement (écart 0,327 →
> 0,308 sur les Pyrénées, 0,368 → 0,354 sur les 36 massifs). Elle sert à mesurer ce que
> l'archive contient, jamais à comparer des indices.

**`coeur` est calée sur la pratique du `-1`, mesurée saison par saison :**

| Saison | Dernier `-1` d'automne | Premier `-1` de printemps |
|---|---|---|
| 2016-2017 | 12 décembre | 28 avril |
| 2017-2018 | 11 décembre | 27 avril |
| 2018-2019 | **13 décembre** | 30 avril |
| 2019-2020 | 12 décembre | *(estimation interrompue fin mars)* |
| 2020-2021 | 11 décembre | 30 avril |

Mesuré sur les Pyrénées, puis remesuré sur les 36 massifs : **les dates sont identiques**.
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
| 2019-2020 | estimation interrompue fin mars 2020 (confinement) : Pyrénées et Corse s'arrêtent (26 et 18 mars), les Alpes publient sans indice jusqu'au 11 juin ; tronquée sur les deux fenêtres |

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

---

## 9. Couche métriques — bloc risque

Les métriques de la spec § 5.1, définies une fois dans
[`src/bra_analytics/metriques/risque.py`](../src/bra_analytics/metriques/risque.py) et posées en
vues par `bra build`. Toutes partent de `risque_journalier`, restreinte à `massif_coherent`, et
s'indexent sur `jour_validite`. L'interface les lit telles quelles ; elle ne recopie aucun SQL.

| Vue | Grain | Contenu |
|---|---|---|
| `risque_jour` | massif × jour couvert | risque du jour, variation depuis la veille, écart à la normale |
| `risque_episode` | un épisode ≥ 3 × portée | début, fin, durée, niveau maximal, ce qui le borde |
| `risque_saison` | massif × saison × portée | comptes par seuil, parts, moyenne, médiane, maximum, occurrences ≥ 3, épisodes, variations, durée de saison |
| `risque_second_indice` | massif × jour couvert | `risque1`, `risque1_evolution`, `risque2`, `risque2_evolution`, `loc_type`, `altitude_seuil_m`, secteurs — vue experte |

Une **portée** est l'une des fenêtres du § 8 (`coeur`, `commune`) ou la saison entière
(`saison_complete`) ; la colonne s'appelle `fenetre`, comme dans `saison_fenetre`. Une ligne de
`risque_saison` porte `comparable` et `motif_exclusion` : vrai seulement sur `coeur`, hors
saisons écartées.

Les vues sont créées au build. Sur un entrepôt construit avant elles, les fonctions de lecture
les posent en vues temporaires, sans écrire dans la base :

```python
import duckdb
from bra_analytics.metriques import risque

con = duckdb.connect("warehouse/bra.duckdb", read_only=True)
risque.metriques_saison(con, fenetre="coeur", massifs=[65])  # massif × saison
risque.comparer_saisons(con)                                  # une ligne par saison, coeur seulement
risque.moyenne_pluriannuelle(con)                             # métrique d'accueil (spec § 3.2)
```

### Définitions

| Métrique | Colonnes | Définition |
|---|---|---|
| Risque du jour | `risque_jour.risque_maxi` | l'indice retenu, une ligne par jour couvert ; un trou n'a pas de ligne |
| Jours ≥ 3 / ≥ 4 / = 5 | `jours_3_plus`, `jours_4_plus`, `jours_5` | comptes sur la portée |
| Part par niveau | `jours_niveau_k`, `part_niveau_k` | part des jours **avec indice** ; les parts somment à 1 |
| Risque moyen | `risque_moyen`, avec `jours_avec_indice` | moyenne de `risque_maxi IS NOT NULL` ; jamais publiée sans ses jours |
| Risque médian | `risque_median` | médiane usuelle : vaut x,5 quand le nombre de jours est pair et que les deux valeurs centrales diffèrent |
| Maximum saisonnier | `risque_max`, `date_max`, `jours_au_max` | `date_max` est le **premier** jour au maximum ; `jours_au_max` dit s'il y en a d'autres |
| Première / dernière occurrence ≥ 3 | `premier_jour_3_plus`, `dernier_jour_3_plus` | |
| Durée de saison | `premier_jour`, `dernier_jour`, `jours_calendaires`, `jours_manquants` | reprises de `couverture`, donc toujours celles de la saison entière |
| Couverture de la portée | `jours_couverts`, `jours_periode`, `couverture_pct` | une fenêtre se rapporte à sa durée nominale, la saison entière à son span observé |
| Épisodes ≥ 3 | `episodes`, `episodes_rompus_par_trou`, `episodes_bordes_sans_indice`, `episodes_tronques_par_fenetre`, `duree_mediane_episode`, `plus_long_episode`, `plus_long_episode_debut` | voir ci-dessous |
| Variations | `hausses_1_plus`, `hausses_2_plus`, `baisses_1_plus`, `baisses_2_plus`, `paires_consecutives`, `paires_ecartees` | entre deux jours couverts consécutifs, tous deux avec indice |
| Écart à la normale | `risque_jour.normale`, `saisons_normale`, `ecart_normale` | voir ci-dessous |

Les jours sans indice (`jours_sans_indice`) et les jours que la source a refusé d'estimer
(`jours_non_estimes`) sont publiés à part. Les deux diffèrent sur les quatorze lignes du § 2.3 :
non estimées mais dotées d'un `RISQUEMAXI`, elles comptent comme des jours avec indice, dans la
moyenne comme dans les parts, les épisodes et les variations.

### Épisodes ≥ 3

Un épisode est une suite de jours couverts **consécutifs au calendrier** à `risque_maxi ≥ 3`.
Il est défini une seule fois, sur la saison entière ; une fenêtre ne fait que le rogner.

> **Un trou d'archive rompt un épisode.** Une suite interrompue par un jour sans bulletin n'est
> pas recollée : elle donne deux épisodes, chacun marqué `rompu_par_trou`, et leur nombre est
> publié à côté du compte. Sur les 36 massifs, **369 épisodes sur 3 791 (9,7 %)** sont rompus par
> un trou sur la saison entière, **314 sur 3 011** sur `coeur`.
>
> Le compte porte sur des **épisodes**, pas sur des trous : un même trou entre deux suites ≥ 3
> marque les deux. Il marque aussi l'épisode qui commence juste après lui, même si le dernier
> jour couvert avant le trou était sous 3 — on ne sait pas ce que disait le jour manquant.

Ce qui borde un épisode, de part et d'autre :

- un jour couvert à < 3 : fin franche ;
- un jour sans bulletin : `rompu_par_trou` ;
- un jour couvert **sans indice** : `borde_sans_indice`. Ce n'est pas un trou d'archive, mais pas
  une fin franche non plus — on ne sait pas si l'épisode continuait. Le cas suit la pratique du
  `-1` : 113 épisodes sur la saison entière, dont 55 en 2017-2018 (premier `-1` de printemps le
  27 avril, au lendemain d'épisodes encore à 3) ; sur `coeur`, 3, tous en 2019-2020 ;
- le premier ou le dernier jour de la saison : fin de série, rien à signaler.

Sur une fenêtre, une bordure ne compte que du côté où la fenêtre n'a pas rogné l'épisode : un trou
du 13 décembre ne rompt rien dans `coeur`, qui ouvre le 15 — l'épisode y est déjà
`tronque_par_fenetre` (230 épisodes sur `coeur`).

### Variations

Une variation ne se calcule qu'entre deux jours couverts **consécutifs**, tous deux avec indice :
un écart de deux jours n'est pas une hausse en 24 h. `risque_jour.variation` est nulle sinon. Les
paires qui enjambent un trou ou touchent un jour sans indice sont comptées dans
`paires_ecartees` plutôt qu'oubliées. Sur une fenêtre, une paire n'entre que si ses **deux** jours
y sont : la hausse du 14 au 15 décembre n'appartient pas à `coeur`.

Sur les 36 massifs, saison entière : 6 507 hausses d'un niveau ou plus, dont 344 de deux, sur
61 408 paires consécutives ; 15 052 paires écartées, presque toutes à cause du `-1` d'avant 2021.
Sur `coeur` : 4 748 et 263 hausses, 42 295 paires, 649 écartées.

### Écart à la normale

`ecart_normale = risque_maxi − normale`, où `normale` est la médiane de `risque_maxi` **au même
jour du calendrier** (mois-jour), pour le même massif, sur les saisons comparables.

- **Fenêtre `coeur` seulement.** C'est une comparaison inter-saisons d'indice : hors de `coeur`,
  les journées `-1` d'avant juin 2021 sortent de la médiane alors que les mêmes journées récentes
  y entrent à 1. Hors `coeur`, `normale` et `ecart_normale` sont nuls.
- **Même jour du calendrier, pas même `jour_de_saison`.** L'ouverture de la diffusion varie de
  deux semaines d'une saison à l'autre : un même rang tomberait à des dates nivologiquement
  différentes.
- **Saisons comparables seulement**, et la saison lue entre dans sa propre normale quand elle est
  comparable. Une saison non comparable reçoit une normale mais pas d'écart, avec son
  `motif_exclusion`.
- **Au moins `MIN_SAISONS_NORMALE` saisons (5).** `saisons_normale` est toujours publié ; en
  dessous du seuil, `normale` est nulle. Seul le 29 février est concerné — une saison comparable
  seulement, 2023-2024 : sa « normale » serait la valeur du jour elle-même. Partout ailleurs sur
  `coeur`, la normale repose sur 6 à 9 saisons.
- La médiane est la médiane usuelle : 1 234 écarts sur 38 736 sont des demi-entiers, quand le
  nombre de saisons est pair et que les deux valeurs centrales diffèrent.

### Comparaisons inter-saisons

`comparer_saisons()` et `moyenne_pluriannuelle()` **refusent de s'exécuter** hors de `coeur` :
elles lèvent `ComparaisonRefusee` au lieu de renvoyer un chiffre, parce qu'un chiffre faux se lit
exactement comme un chiffre juste. `comparer_saisons()` met en commun les jours des massifs
retenus (moyenne pondérée par jour, pas moyenne de moyennes) et rend aussi les saisons non
comparables, étiquetées. `moyenne_pluriannuelle()` ne retient que les saisons comparables et
compte les autres dans `saisons_ecartees`.

`risque_saison` publie aussi `risque_moyen` sur `commune` et la saison entière, pour lire une
saison isolément ; ces lignes portent `comparable = false`.

### Couverture

`couverture` est restreinte à `massif_coherent` depuis T6 : le message technique du 05/02/2016
diffusé sous `ID="3"` ouvrait la saison 2015-2016 du Mont-Blanc au 5 février, avec 45 jours
manquants fictifs. Elle s'ouvre désormais au 11 mars (35 jours couverts, 11 manquants).

---

## 10. Couche métriques — bloc enneigement

Les métriques de la spec § 5.2, définies une fois dans
[`src/bra_analytics/metriques/enneigement.py`](../src/bra_analytics/metriques/enneigement.py) et
posées en vues par `bra build`, comme le bloc risque (§ 9). Toutes sont restreintes à
`massif_coherent`. L'interface les lit telles quelles ; elle ne recopie aucun SQL.

> **L'enneigement du BRA est indicatif.** Une épaisseur est l'estimation du prévisionniste à une
> altitude de référence, pas une mesure de station. Aucune colonne du bloc ne s'appelle
> « mesure » (un test le vérifie), et les seuils appliqués voyagent avec les chiffres qu'ils
> produisent (`seuil_epaisseur_cm`, `seuil_limite_m`, `seuil_chute_cm`). Comparer un massif à
> lui-même dans le temps est solide ; comparer deux massifs à altitude nominale égale l'est
> beaucoup moins (spec § 5.2).

| Vue | Grain | Contenu |
|---|---|---|
| `enneigement_jour` | massif × jour | limites d'enneigement continu, `sans_enneigement_continu_*`, `releve_fait` |
| `enneigement_palier` | massif × jour × palier | épaisseur nord / sud, tranche, `palier_retenu`, écart à la normale |
| `enneigement_saison` | massif × saison × tranche × portée | jours enneigés, maximum saisonnier et sa date, couverture |
| `enneigement_continu` | massif × saison × versant | période d'enneigement continu : début, fin, durée, jours non observés |
| `neige_fraiche_jour` | massif × jour | cumul de 24 h, une rédaction par jour — **contrat consommé par le bloc météo (T8)** |
| `neige_fraiche_episode` | un épisode de chute × portée | début, fin, durée, cumul, plus forte chute, ce qui le borde |
| `neige_fraiche_saison` | massif × saison × tranche × portée | cumul, jours de chute, épisodes, plus forte chute, lecture du cumul |

Une **portée** est, comme au § 9, `coeur`, `commune` ou `saison_complete` (colonne `fenetre`).
Sur un entrepôt construit avant T7, les fonctions de lecture posent les vues en vues
temporaires, sans écrire dans la base :

```python
import datetime as dt
import duckdb
from bra_analytics.metriques import enneigement

con = duckdb.connect("warehouse/bra.duckdb", read_only=True)
enneigement.metriques_saison(con, fenetre="coeur", massifs=[65], tranches=["moyenne"])
enneigement.enneigement_continu(con, massifs=[65], seuil_limite_m=1500)
enneigement.neige_fraiche_saison(con, fenetre="commune", seuil_chute_cm=10)
enneigement.cumul_neige_fraiche(con, debut=dt.date(2025, 1, 1), fin=dt.date(2025, 1, 31))
```

Les seuils se passent aux fonctions de lecture, qui recalculent sans toucher aux vues ; les vues
portent les valeurs par défaut.

### Deux séries journalières, une rédaction par jour

**Neige fraîche : bloc historique seul, rédaction la plus tardive.** Un même jour figure dans le
bloc `BSH` de six bulletins successifs. `neige_fraiche_jour` en retient un, celui du bulletin
rédigé le plus tard (`ORDER BY date_bulletin DESC, date_diffusion DESC`, comme
`risque_journalier`) ; `redactions` dit combien le décrivaient, `redactions_divergentes` s'ils
n'étaient pas d'accord. Sur les 36 massifs : **444 570 lignes historiques → 78 172 jours**.
`log_neige_fraiche_discards()` rejoue le même tri au build et journalise **chaque** ligne
écartée, 366 398 en tout : les **2 222** dont la valeur diffère de la ligne retenue (révision,
ou cumul observé puis non observé) en `WARNING`, les répétitions à l'identique en `DEBUG` —
ligne à ligne dans les deux cas, seul le volume change. Le tri est écrit une fois
(`ORDRE_REDACTION`) et la vue comme le journal en dérivent ; un test vérifie que lignes gardées
et écartées partitionnent exactement le bloc historique.

Le bloc de **prévision** n'est jamais lu : il mêlerait un horizon prévu à un horizon analysé.
La saison 2015-2016, sans bloc `BSH`, n'a donc pas de neige fraîche. À l'inverse, le bloc
historique comble les trous d'archive : un jour sans bulletin reste décrit par les six suivants,
et aucun épisode de chute n'est rompu par un trou sur les 36 massifs.

**Épaisseur et limite : relevé du jour seul, même règle.** `enneigement_jour` et
`enneigement_palier` lisent `origine = 'jour'`, indexé sur la date du relevé (le BRA rédigé le
10 décrit le manteau du 10) ; `jour_validite` du bulletin source est conservé pour la jointure
avec le risque. Un relevé rédigé deux fois — réédition de 16 h à 18 h, ou bulletin du matin qui
redonne le relevé de la veille — garde la rédaction la plus tardive :
**232 461 lignes → 230 400**, les **2 061** écartées (687 relevés de trois paliers) journalisées
en `WARNING` par `log_enneigement_discards()`.

Le bloc historique d'enneigement **n'est pas lu**, et c'est un choix : il manque toute la
saison 2015-2016, et réécrit le relevé du jour dans 1 à 3 % des paliers (1 794 épaisseurs nord
sur 158 055 avant 2024, 2 087 sur 69 711 depuis). Le mêler au relevé du jour changerait
d'horizon d'un jour à l'autre. Ce qu'il apporterait en plus : 3 090 jours-massifs, pour
l'essentiel la semaine qui précède l'ouverture de la diffusion et les trous d'archive.

### Recalage du bloc historique moderne

Le bloc principal `NEIGEFRAICHE` et le bloc historique d'avant 2024 datent une fenêtre de 24 h
du **même** jour : le cumul historique du jour J y vaut celui du bloc principal du jour J dans
53 602 paires non nulles sur 54 107. Le bloc historique **moderne** (2024+) date la même
fenêtre **au lendemain** : son jour J+1 vaut le jour J du bloc principal dans
**31 254 paires non nulles sur 31 254**, et son jour J dans 3 437 sur 52 961 seulement. Quelques
dates y portent d'ailleurs `06:00`, la fin de la fenêtre 06 UTC → 06 UTC. Les deux blocs
historiques couvrent ainsi les mêmes six fenêtres (J−6 à J−1 du jour de rédaction), étiquetées
différemment.

`neige_fraiche_jour` ramène le bloc moderne à la convention commune
(`DECALAGE_HISTORIQUE_MODERNE_JOURS = 1`) et garde la date source dans `date_cumul_source`.
Sans ce recalage, la série glisserait d'un jour à l'hiver 2023-2024, en plus d'y changer de
lecture. *Inféré* : que `jour` soit le **début** de la fenêtre (06 UTC du jour → 06 UTC du
lendemain) se lit sur les `06:00` du bloc moderne, aucun descriptif ne le dit.

### Contrat de `neige_fraiche_jour`

La vue que consomme l'indice de transport par le vent (T8, spec § 5.3). Garanties :

- **une ligne par `(massif_id, jour)`**, sur les seuls bulletins `massif_coherent` ;
- `jour` suit la convention du bloc principal (voir ci-dessus), pas `jour_validite` : la
  fenêtre de 24 h décrite commence ce jour-là ;
- un cumul **nul n'est pas zéro** : c'est un cumul non observé (`-2` d'avant 2024, 15 à 21 % des
  lignes) ; ne jamais le remplacer par 0 dans une somme sans le compter ;
- `lecture_cumul` (`secteurs` avant 2024, `fourchette` depuis) et `format_famille` portent la
  rupture de série ; un calcul qui enjambe l'hiver 2023-2024 doit l'annoncer ou la refuser ;
- l'altitude peut changer **en cours de saison** : les Alpes du Sud passent de 1800 à 2500 m
  en fin de saison depuis 2024 (791 jours en tranche `haute`, tous les autres en `moyenne`).
  Pour 27 couples massif × saison (massifs 13, 16, 17…), `neige_fraiche_saison` répartit donc
  le cumul de la saison sur **deux lignes de tranche**, et un épisode de chute peut enjamber le
  changement. Le cumul d'une saison entière est la somme des deux lignes ; comparer la seule
  tranche `moyenne` de ces massifs à celle des autres sous-estime leur saison.

| Colonne | Description |
|---|---|
| `saison`, `saison_debut`, `massif_id`, `massif_nom`, `zone` | identification (saison du bulletin source) |
| `jour` | jour de la fenêtre de 24 h, convention du bloc principal |
| `cumul_min_cm`, `cumul_max_cm` | bornes du cumul (§ 5) ; nulles si non observé |
| `altitude_m`, `tranche` | altitude de référence et tranche normée |
| `format_famille`, `lecture_cumul` | `legacy` / `secteurs` ou `moderne` / `fourchette` |
| `secteur1_libelle` … `secteur2_cumul_cm` | secteurs nommés d'avant 2024, tels que lus |
| `date_cumul_source` | date écrite dans le XML, avant recalage |
| `date_bulletin`, `fichier_source` | rédaction retenue |
| `redactions`, `redactions_divergentes` | combien de bulletins décrivaient ce jour, et s'ils divergeaient |
| `saison_comparable`, `motif_exclusion` | saisons écartées du § 8, étiquetées |
| `fenetre_coeur`, `fenetre_commune` | appartenance du jour aux fenêtres, lue sur `jour` |

### Définitions

| Métrique (spec § 5.2) | Colonnes | Définition |
|---|---|---|
| Limite d'enneigement | `enneigement_jour.limite_nord_m`, `limite_sud_m`, `sans_enneigement_continu_*` | limite nulle + indicateur vrai = pas d'enneigement continu ; limite et indicateur nuls = non relevé |
| Épaisseur par tranche | `enneigement_palier.epaisseur_nord_cm`, `epaisseur_sud_cm`, `tranche`, `palier_retenu` | une ligne par palier ; rien n'est interpolé |
| Date d'enneigement continu | `enneigement_continu.debut_enneigement_continu`, `fin_…`, `duree_jours`, `jours_non_observes_periode` | voir ci-dessous |
| Durée d'enneigement | `enneigement_saison.jours_enneiges_nord` / `_sud`, avec `jours_observes_*`, `jours_releves` | jours où l'épaisseur du palier retenu atteint `seuil_epaisseur_cm` |
| Maximum saisonnier | `epaisseur_max_nord_cm`, `date_max_nord`, `jours_au_max_nord` (et `_sud`) | `date_max` est le **premier** jour au maximum |
| Neige fraîche cumulée | `neige_fraiche_saison.cumul_max_cm`, `cumul_min_cm`, `jours_non_observes` ; `cumul_neige_fraiche()` sur une période quelconque | somme sur les jours observés : un minorant, publié avec ses jours non observés |
| Épisodes de chute | `jours_chute`, `episodes_chute`, `episodes_rompus_par_trou`, `episodes_bordes_non_observe`, `plus_long_episode`, `plus_forte_chute_cm`, `date_plus_forte_chute` | un épisode = jours **consécutifs au calendrier** à `cumul_max_cm ≥ seuil_chute_cm` ; un jour présent mais non observé le borde, un trou le rompt ; une fenêtre rogne l'épisode qui chevauche sa borne |
| Anomalie d'enneigement | `enneigement_palier.normale_nord_cm`, `saisons_normale_nord`, `ecart_normale_nord_cm` (et `_sud`) | voir ci-dessous |

### Paramètres

| Constante | Défaut | Justification | Effet mesuré (36 massifs) |
|---|---|---|---|
| `SEUIL_EPAISSEUR_CM` | 1 cm | la frontière que l'archive trace elle-même : une limite `-1` sur relevé fait accompagne une épaisseur nulle à tous les paliers (§ 4) ; convention usuelle d'un sol enneigé | `coeur`, saisons comparables, médiane des jours enneigés nord : 99 j en basse, 121 en moyenne et haute (sur 122) ; à 30 cm : 57, 120, 121 |
| `SEUIL_LIMITE_M` | 1800 m | le plancher de la tranche `moyenne` (`tranches.py`) : sous ce seuil, toute la tranche moyenne est enneigée en continu ; [`disponibilite.md`](disponibilite.md) § 7 ne publie pas de distribution de limite | durée médiane de la période nord : 135,5 j ; 71,5 à 1500 m, 164 à 2000 m |
| `TROU_TOLERE_JOURS` | 3 jours | 844 des 910 trous du relevé du jour durent 1 à 3 jours, les autres 5 à 50 | à 0 (règle des épisodes de risque), 251 débuts sur 784 changent ; à 7, aucun |
| `SEUIL_CHUTE_CM` | 20 cm | p95 de `cumul_max_cm` historique moderne ([`disponibilite.md`](disponibilite.md) § 7 : p50 0, p75 3, p90 10, p95 20, p99 40, max 120 cm) ; au p90, un jour sur dix serait une chute | `coeur`, saisons comparables : médiane de 6 jours de chute par massif-saison avant 2024, 8 depuis ; 1 103 et 696 épisodes |
| `MIN_SAISONS_NORMALE` | 5 | repris du bloc risque (§ 9) | normale publiée sur 208 094 paliers-jours sur 230 400 |
| `DECALAGE_HISTORIQUE_MODERNE_JOURS` | 1 | voir le recalage ci-dessus | 31 254 paires sur 31 254 |

### Palier retenu

Huit massifs ont deux paliers dans la tranche `basse` (1000 et 1500 m), un en avait jusqu'en
2021 (1200 et 1500 m), cinq en avaient deux dans la tranche `moyenne` (1800 et 2100 m). Une
métrique par tranche lit un seul palier : **le plus haut de la tranche** (`palier_retenu`).
Il donne à chaque tranche une altitude homogène — 1500 m en `basse` pour tous les massifs,
2100 puis 2000 m en `moyenne` — et `enneigement_saison` publie `altitude_min_m` /
`altitude_max_m` pour qu'un changement de palier en cours de série se voie. L'autre palier
n'est pas écarté : il reste dans `enneigement_palier` (21 337 lignes `palier_retenu = false`),
avec sa propre normale.

### Enneigement continu

« Premier jour à partir duquel la limite reste sous un seuil » se lit ici comme le début de la
**plus longue période** où la limite reste sous `seuil_limite_m`, par versant. État d'un jour :

- **sous** : limite < seuil ;
- **au-dessus** : limite ≥ seuil, **ou** `sans_enneigement_continu` vrai — une limite nulle sur
  un relevé fait n'est pas une lacune, c'est l'absence d'enneigement continu ;
- **inconnu** : relevé non fait, ou indicateur nul. Le jour n'entre pas dans la suite.

Seul un jour au-dessus rompt une période, ou un trou de plus de `trou_tolere_jours` jours sans
état connu. Les jours non observés intérieurs sont publiés (`jours_non_observes_periode`) ;
`periodes` dit en combien de morceaux la saison se découpe. À égalité de durée, la période la
plus précoce l'emporte.

### Écart à la normale

`ecart_normale_nord_cm = epaisseur_nord_cm − normale_nord_cm` (et `_sud`), où la normale est la
médiane de l'épaisseur **au même jour du calendrier**, pour le même massif et le **même palier**,
sur les saisons comparables. Les choix du bloc risque (§ 9), à deux différences près :

- **même palier, pas même tranche** : cinq massifs passent de 2100 à 2000 m dans la tranche
  moyenne en 2021 ; une normale par tranche mêlerait deux altitudes ;
- **toute la saison, pas `coeur`** : la fenêtre corrige la sentinelle `RISQUE1=-1`, qui ne
  touche pas l'enneigement. Le seuil de saisons suffit à écarter les dates trop peu couvertes.

Une saison non comparable reçoit une normale mais pas d'écart ; `saisons_normale_*` est toujours
publié. Sur les 36 massifs : 208 094 paliers-jours ont une normale, 190 328 un écart.

### Rupture de série de la neige fraîche

Avant 2024, `cumul_max_cm` est le plus fort de un ou deux secteurs nommés ; depuis, la borne
haute d'une fourchette sur le massif (§ 5). La rupture voyage avec le chiffre :

- chaque ligne de `neige_fraiche_jour`, `neige_fraiche_episode` et `neige_fraiche_saison`
  porte `lecture_cumul` ; `neige_fraiche_saison` y ajoute `rupture_de_serie`, vrai si la ligne
  mêle les deux (impossible à l'intérieur d'une saison : 2023-2024 est entièrement moderne) ;
- `cumul_neige_fraiche()` **refuse** une période à cheval sur l'hiver 2023-2024 et lève
  `RuptureDeSerie` au lieu de sommer deux grandeurs différentes.

L'écart se voit dans les distributions dédupliquées : p95 de 16 cm avant 2024, 20 cm depuis ;
médiane de 6 jours ≥ 20 cm par massif-saison sur `coeur` avant, 8 depuis. Ce n'est pas un
signal nivologique tant que la lecture change en même temps — et les 15 à 21 % de jours non
observés d'avant 2024 tirent les cumuls anciens vers le bas.

### Comparaisons

`enneigement_saison` et `neige_fraiche_saison` portent `comparable` et `motif_exclusion` :
vrai sur une **fenêtre nommée** (`coeur` ou `commune`) hors saisons écartées, jamais sur la
saison entière, dont les bornes brutes ne se comparent pas. À la différence du risque,
`commune` est admise : elle ne corrige pas le `-1`, mais le `-1` ne touche pas l'enneigement,
et la durée d'enneigement est une « durée de saison », l'usage même de `commune` (§ 8). La
règle est déclarée une fois, par fenêtre, dans `fenetres.py` (`comparable_enneigement`), et le
SQL du bloc la lit. Pour la
neige fraîche, `comparable` ne lève pas la rupture de 2023-2024 : `lecture_cumul` le dit.

## 11. Couche métriques — bloc météo

Les métriques de la spec § 5.3, définies une fois dans
[`src/bra_analytics/metriques/meteo.py`](../src/bra_analytics/metriques/meteo.py) et posées en
vues par `bra build`, après le bloc risque. Toutes partent des jours couverts de
`risque_journalier`, restreinte à `massif_coherent`, et s'indexent sur `jour_validite`.

**C'est une prévision.** Chaque vue porte `origine = 'prevision'` sur chaque ligne ; l'interface
le dit là où elle affiche une série (spec § 5.3).

| Vue | Grain | Contenu |
|---|---|---|
| `meteo_jour` | massif × jour couvert | isotherme 0 °C, limite pluie-neige et temps sensible à 06 h et 12 h, valeur du jour, variation en 24 h, `motif_lacune` |
| `meteo_vent_jour` | massif × jour × altitude de vent | vitesse et direction à 06 h et 12 h, vitesse du jour, direction au maximum, `tranche` |
| `meteo_vent_tranche_jour` | massif × jour × tranche | le plus fort des vents de la tranche, sa direction, `altitudes_vent` réunies |
| `meteo_redoux` | une suite de jours à isotherme haut | début, fin, durée, `retenu`, ce qui la borde, risque de la veille, pendant et du lendemain |
| `meteo_saison` | massif × saison × portée | isotherme min / max / moyen avec jours, jours au-dessus du seuil, variations, limite pluie-neige, redoux |
| `meteo_vent_saison` | massif × saison × portée × tranche | jours avec vent, jours de vent fort, vitesse max et médiane, altitudes réunies |
| `meteo_temps_sensible` | massif × saison × portée × code | échéances par code, libellé, part |
| `meteo_transport` | massif × jour × tranche | vent prévu, neige fraîche des trois jours précédents, pentes chargées, `transport` |

```python
import duckdb
from bra_analytics.metriques import meteo

con = duckdb.connect("warehouse/bra.duckdb", read_only=True)
meteo.serie_jour(con, massifs=[65], saisons=["2024-2025"])        # massif × jour
meteo.vent_saison(con, fenetre="coeur", tranches=["haute"], seuil_vent_fort_kmh=80)
meteo.episodes_redoux(con, seuil_iso0_m=3000)                      # redoux et risque
```

Sur un entrepôt construit avant T8, les fonctions posent les vues en vues temporaires, sans
écrire dans la base.

### Convention d'extraction appliquée

- **Le bulletin du jour est celui du risque.** `meteo_jour` reprend le `date_bulletin` que
  `risque_journalier` retient pour le jour : quand deux bulletins couvrent une journée, la météo
  et le risque viennent de la même rédaction. Les bulletins écartés le sont déjà ligne à ligne par
  `log_daily_collapse_discards()` ; la météo n'ajoute aucun arbitrage.
- **Prévision seule, 06 h et 12 h du jour couvert** (§ 3). Le 00 h de J (format ancien), le 18 h
  de J et le 00 h de J+1 (format moderne) n'entrent dans aucune valeur.
- **Une valeur du jour exige les deux échéances.** Avec une seule, le « maximum du jour » ne
  mesurerait pas la même chose d'un jour à l'autre. Exception : la limite pluie-neige (ci-dessous).
- **Aucun jour couvert n'est retiré.** `meteo_jour` a exactement les lignes de
  `risque_journalier` (`massif_coherent`) ; un jour sans valeur porte son `motif_lacune` :
  aucune échéance de prévision, échéances hors du jour couvert, échéance de 06 h ou 12 h absente
  ou vide.

### Définitions

| Métrique | Colonnes | Définition |
|---|---|---|
| Isotherme 0 °C du jour | `iso0_06h_m`, `iso0_12h_m`, `iso0_min_m`, `iso0_max_m`, `iso0_moyen_m` | min, max et moyenne des deux échéances, nuls si l'une manque |
| ISO 0 min / max / moyen | `meteo_saison.iso0_min_m`, `date_iso0_min`, `iso0_max_m`, `date_iso0_max`, `iso0_moyen_m`, `iso0_median_m`, avec `jours_avec_iso0` | la plus basse et la plus haute échéance de la portée ; moyenne et médiane des moyennes du jour |
| Jours ISO 0 > seuil | `jours_iso0_au_dessus_seuil`, `seuil_iso0_m` | jours où l'isotherme dépasse **strictement** le seuil **aux deux** échéances (`iso0_min_m > seuil`) |
| Variation ISO 0 en 24 h | `meteo_jour.variation_iso0_24h_m` ; `paires_consecutives_iso0`, `paires_ecartees_iso0`, `plus_forte_hausse_iso0_24h_m`, `plus_forte_baisse_iso0_24h_m`, `amplitude_moyenne_iso0_24h_m` | différence des moyennes du jour entre deux jours couverts **consécutifs** ; nulle par-dessus un trou, comptée dans `paires_ecartees_iso0` |
| Vent par tranche | `meteo_vent_tranche_jour` (sur `meteo_vent_jour`) | une ligne par **altitude** de vent dans `meteo_vent_jour`, rattachée à sa tranche (`tranches.py`) ; vitesse du jour = la plus forte des deux échéances, si les deux sont valides ; direction au maximum, celle de 12 h à égalité. `meteo_vent_tranche_jour` ramène à une ligne par tranche : deux vents dans une même tranche (3000 et 4000 m) → le plus fort, altitudes publiées |
| Jours de vent fort | `meteo_vent_saison.jours_vent_fort`, `seuil_vent_fort_kmh`, `altitudes_vent` | jours où la vitesse du jour d'une altitude de la tranche dépasse **strictement** le seuil |
| Limite pluie / neige | `limite_pluie_neige_06h_m`, `_12h_m`, `limite_pluie_neige_min_m` ; `jours_avec_limite_pluie_neige`, `limite_pluie_neige_min_m`, `limite_pluie_neige_mediane_m` | la plus basse des limites renseignées du jour |
| Temps sensible | `meteo_temps_sensible` | comptes en **échéances** (deux par jour), pas en jours ; `dans_palette` faux pour les codes hors palette (§ 7), comptés avec un libellé nul |
| Épisodes de redoux | `meteo_redoux` ; `episodes_redoux`, `redoux_rompus_par_trou`, `redoux_sans_franchissement_observe`, `jours_en_redoux`, `plus_long_redoux` | voir ci-dessous |
| Indice de transport par le vent | `meteo_transport` ; `transport_vent()` | voir ci-dessous |

> **Indice de transport par le vent.** Un jour et une tranche sont « de transport » quand le vent
> prévu du jour (`meteo_vent_tranche_jour`) dépasse **strictement 50 km/h** et que les trois
> fenêtres de neige fraîche qui précèdent le jour (`neige_fraiche_jour`, J-3 à J-1, closes le
> matin du jour) cumulent **au moins 15 cm**. Seuils (paramètres de `transport_vent()`) : 50 km/h
> est le p75 du vent haut prévu ([`disponibilite.md`](disponibilite.md) § 7), appliqué à toutes
> les tranches — leur p75 va de 20 km/h (basse) à 60 km/h (haute), si bien que la tranche basse
> reste presque toujours sous le seuil ; 15 cm est le p75 de la **somme sur trois jours**, la
> grandeur testée, mesurée sur la série moderne (p50 2, p75 15, p90 31 cm ; 11 et 30 avant 2024).
>
> La fenêtre du jour lui-même n'entre pas : elle s'achève le lendemain matin, après les échéances
> de 06 h et 12 h — un choix prudent, qui ignore la neige tombant le jour même. L'alignement
> hérite de la convention « `jour` = début de la fenêtre 06 UTC → 06 UTC », elle-même *inférée*
> (§ 10). `pentes_chargees` est le secteur opposé à la direction du vent (vent de NW → pentes SE) ;
> `VRB` n'en charge aucune.
>
> Une fenêtre non observée (`-2` d'avant 2024) ne peut qu'ajouter de la neige : la somme observée
> est un minorant. L'indice est donc **faux** si le vent est sous le seuil, **vrai** si la neige
> observée atteint déjà le sien, et **nul** seulement sinon — 4,5 % des jours avant 2024, 0,2 %
> depuis. Cet écart d'époque compte : avant 2024 quelques jours de transport sont indéterminés
> plutôt que comptés, et la neige se lit par secteurs (`lecture_cumul`), une comparaison qui
> enjambe l'hiver 2023-2024 doit l'annoncer. Sur les 36 massifs : 5 573 jours de transport en
> tranche haute, 1 394 en moyenne, 229 en basse ; pentes chargées d'abord au SE, au S et à l'E.
> C'est une **prévision** croisée avec une neige indicative, pas une observation de corniches.

> **Le vent se lit par altitude, jamais par rôle.** Le vent unique à 3000 m des Alpes du Sud
> (§ 2.9, colonne « basse » jusqu'en 2023, « haute » ensuite) tombe en tranche haute aux deux
> époques. Un vent sans altitude n'a pas de ligne : le seul bulletin concerné (Chablais, rédigé
> le 11/06/2018, `jour_validite` au 01/11/2018) a de toute façon ses échéances hors du jour
> couvert.

> **Deux vents dans une même tranche.** 3000 et 4000 m, ou 2500 et 3500 m, tombent tous deux en
> tranche haute (Mont-Blanc, Haute-Tarentaise, Vanoise, Haute-Maurienne, Oisans), et
> certains massifs changent d'altitudes de vent en cours de saison. La tranche retient alors, pour
> le jour, la plus forte des vitesses ; `altitudes_vent` publie les altitudes réunies
> (`3000/4000`, `2500/3000/3500/4000`) : une tranche haute à deux vents a mécaniquement plus de
> jours de vent fort qu'une tranche à un seul. La comparaison solide reste celle d'un massif à
> lui-même.

> **Vitesses hors plage.** Une vitesse hors [0, `VENT_MAX_KMH`] (300 km/h) est exclue — la
> vitesse du jour devient nulle — et comptée dans `vitesses_hors_plage`. Les deux cas de la
> prévision (400 km/h à 18 h, −5 km/h à 00 h) tombent hors des échéances de 06 h et 12 h.

> **Limite pluie-neige.** `-1` (temps sec) est rendu nul par le parser : une limite nulle dit
> « pas de précipitation prévue » ou « attribut absent », indiscernables (`disponibilite.md` § 8).
> D'où la plus basse des limites renseignées, sans exiger les deux échéances.

### Seuils

Paramétrables dans chaque fonction de lecture ; les vues posées au build portent les valeurs par
défaut, et chaque sortie publie le seuil qui l'a produite. Les deux seuils sont au **90e
centile** de la prévision, toutes échéances confondues (`disponibilite.md` § 7).

| Constante | Défaut | Justification |
|---|---|---|
| `SEUIL_VENT_FORT_KMH` | 70 km/h | p90 du vent haut (p95 80, p99 100) ; entre p95 (60) et p99 (80) du vent bas |
| `SEUIL_ISO0_M` | 3400 m | p90 de l'isotherme 0 °C (p75 3000, p95 3700) |
| `DUREE_MIN_REDOUX_JOURS` | 2 jours | « au moins 24 h » : deux jours consécutifs au-dessus à 06 h et 12 h l'attestent sur trente heures, un jour seul sur six |

Sur l'entrepôt des 36 massifs, saison entière : 7 103 jours de vent fort en tranche haute
(10,7 % des jours avec vent), 1 126 en tranche moyenne (2,3 %), 237 en tranche basse (1,4 %) ;
au seuil « ≥ 70 », ce serait 10 927, 1 894 et 370 : les vitesses s'écrivent par pas de 5 km/h,
et le choix entre « > » et « ≥ » déplace la tranche haute d'un tiers.

### Épisodes de redoux

Un épisode est une suite de jours couverts **consécutifs au calendrier** où l'isotherme dépasse
le seuil aux deux échéances, d'au moins `DUREE_MIN_REDOUX_JOURS` jours. Il est défini sur la
saison entière et appartient à la portée où il commence (`debut_fenetre_coeur`…).

- **Franchissement à la hausse.** Il n'est *observé* que si la veille est couverte et sous le
  seuil ; sinon (début de saison, trou, veille sans valeur) l'épisode est compté et
  `franchissement_observe` est faux.
- **Un trou d'archive rompt un épisode**, comme pour le risque (§ 9) : deux suites séparées par
  un jour sans bulletin ne sont pas recollées, chacune est `rompu_par_trou`.
- **Une suite plus courte que la durée minimale reste dans la vue**, avec `retenu = false`.
- **Risque avant et après** : `risque_veille` (jour précédant le début), `risque_max_pendant`,
  `risque_lendemain` (jour suivant la fin), lus dans `risque_jour` ; nuls si ces jours ne sont pas
  couverts.

Sur les 36 massifs, aux seuils par défaut : **1 186 épisodes**, dont 36 rompus par un trou et 15
sans franchissement observé ; durée moyenne 3,8 jours, 29 au plus. **285** commencent dans
`coeur` : risque moyen 2,17 la veille, 2,15 au plus fort, 1,84 le lendemain ; sur les 278 dont la
veille et le lendemain sont couverts, le risque monte 23 fois, reste égal 153 fois et baisse 102
fois. Au seuil de 3000 m : 2 767 épisodes ; avec une durée minimale d'un jour : 2 345.

> Ces comptes viennent de l'entrepôt construit avant le correctif de `to_frames` (exploration,
> rééditions) : 217 jours y lisent les échéances de 06 h et 12 h d'une autre diffusion que la
> retenue. Une reconstruction les déplacera à la marge.

### Couverture

Sur l'entrepôt des 36 massifs, 76 796 jours couverts sur 76 852 ont une valeur d'isotherme. Les
56 autres : 27 jours dont les échéances de prévision tombent hors du jour couvert (bulletins mal
datés de 2016-2017 à 2020-2021, et les deux rééditions du 06/04/2026 que le correctif de
`to_frames` rétablit), 29 jours dont l'échéance de 06 h ou 12 h est vide (2022-2023 à
2025-2026).

---

## 12. Couche métriques — rose des pentes et situations typiques

Module `metriques/pentes.py` (spec § 5.4, T9). Vues restreintes à `massif_coherent`, indexées sur
`jour_validite`, lisant la rose et `sat1` / `sat2` dans le bulletin que `risque_journalier` retient
pour le jour.

> **La rose n'a pas d'altitude.** `<PENTE>` est un jeu unique de huit booléens par bulletin, sans
> attribut d'altitude, et `<SitAvalTyp>` n'en a pas non plus. Toute sortie porte
> `altitude = 'non localisee'`. Ce n'est pas « toutes altitudes confondues » : le bulletin ne dit
> pas à quelle altitude la rose s'applique. Seul le croisement avec le vent se ventile par tranche,
> parce que l'altitude du vent est réelle.

| Vue | Maille | Contenu |
|---|---|---|
| `pente_jour` | massif × jour couvert | huit orientations, `nb_secteurs`, `sat1` / `sat2` avec libellés |
| `pente_orientation_saison` | massif × saison × portée × orientation | `jours_signales` / `jours_couverts` → `frequence` ; même chose restreinte aux jours ≥ 3 (`_ge3`) et ≥ 4 (`_ge4`) |
| `pente_saison` | massif × saison × portée | `secteur_dominant`, `secteurs_ex_aequo`, `secteurs_moyens` (concentration), `jours_sans_secteur`, `rose_vide_risque_ge2` |
| `pente_mois_orientation` | massif × mois × portée × orientation | saisonnalité, `nb_saisons` et `jours_couverts` |
| `pente_vent_saison` | massif × saison × portée × tranche × direction du vent | jours où la pente chargée par ce vent (opposée à sa direction) est signalée dans la rose |
| `pente_situation_saison` | massif × saison × portée × rang × code | `jours`, `part`, `libelle`, `restriction` ; `rang` 1 = `sat1`, 2 = `sat2` |

```python
from bra_analytics.metriques import pentes

pentes.rose_saison(con, fenetre="coeur", massifs=[65])           # massif × saison × orientation
pentes.resume_saison(con, fenetre="coeur")                       # dominant, concentration
pentes.croisement_vent(con, fenetre="coeur", tranches=["haute"]) # par tranche de vent
pentes.situations(con, massifs=[65])                             # depuis 2023-2024
```

- **Dénominateur** : les jours couverts avec `risque_maxi IS NOT NULL`, comme toute moyenne du repo.
  Chaque fréquence est publiée avec les jours dont elle est tirée. Les fréquences pondérées sont
  nulles, et non 0 %, quand la saison n'a aucun jour de ce niveau.
- **Rose vide** : 8 094 jours sur 62 388 n'ont aucun secteur signalé, dont 8 086 à risque 1 (la rose
  dit alors « aucune orientation particulière »). Ils restent dans le dénominateur. Huit jours ont une
  rose vide à risque ≥ 2 (sept à 2, un à 3) : incohérence d'archive, comptée dans
  `rose_vide_risque_ge2`, jamais écartée.
- **Rose pleine** : 22 485 jours (36 %) signalent les huit secteurs. Le secteur dominant est donc un
  signal faible : `secteurs_ex_aequo` le dit, et 113 des 392 couples massif × saison de `coeur` ont
  au moins un ex aequo. À égalité le secteur retenu est le premier dans l'ordre N, NE, E, SE, S, SW,
  W, NW.
- **Mélange de risques** : la fréquence d'exposition dépend de la part de jours à risque 1 (rose
  souvent vide) de la saison. La lecture comparable entre saisons est la fréquence pondérée ≥ 3,
  sur `coeur` et `comparable = true`. Sur `coeur`, moyenne des fréquences ≥ 3 : N 0,95, NE 0,96, E 0,92,
  NW 0,90, W 0,76, SE 0,73, S 0,65, SW 0,64.
- **Vent** : le croisement lit `meteo_vent_tranche_jour` (prévision seule, § 3 et § 11), et ignore les
  directions variables (`VRB`), qui ne chargent aucune pente. Il ne filtre pas sur la vitesse :
  c'est la direction qui est croisée avec la rose, pas l'intensité (voir `meteo_transport` pour le
  vent fort sur neige fraîche).
- **Situations** : libellés **inférés** (§ 2.7), publiés avec `libelle_source`. Le code 6 (manteau
  insuffisant) a `est_situation_typique = false`. `sat1` n'existe qu'à partir de 2023-2024 : avant,
  la vue n'a pas de ligne, pas des lignes nulles ; `restriction` le rappelle sur chaque ligne.
  `sat2`, renseigné sur 60 % des jours, est rapporté aux jours où `sat1` l'est.

## 13. Couche métriques — score composite

Module `metriques/score.py`, vue `score_saison` (massif × saison, fenêtre `coeur` seule). Spec § 5.5.
La formule, sa version et ses paramètres sortent de `score.formule()` : l'interface les affiche
sans les recopier.

| Composante | Part de jours | Source | Ancres (0 → 1) | Poids |
|---|---|---|---|---|
| `risque` | jours `risque_maxi >= 3` / jours avec indice | `risque_saison` | 0,10 → 0,80 | 0,5 |
| `neige` | jours de chute ≥ 20 cm / jours observés | `neige_fraiche_saison` | 0,02 → 0,12 | 0,3 |
| `vent` | jours de vent > 70 km/h / jours avec vent, tranche la plus exposée | `meteo_vent_saison` | 0,03 → 0,26 | 0,2 |

`score = 100 × (0,5·n_risque + 0,3·n_neige + 0,2·n_vent)`, chaque `n_*` étant la part ramenée
sur [0, 1] entre ses ancres et bornée.

- **Ancres** : percentiles 5 et 95 des 321 lignes `comparable` de `coeur` (36 massifs, neuf
  saisons, mesure du 16 octobre 2026), arrondis. Figées : recalculées à chaque lecture, elles
  feraient bouger le score à chaque saison ajoutée. Mesure faite sur ces neuf saisons ; une
  saison de plus ne les déplace pas, et une dérive de la distribution se traite par une
  nouvelle version, à la main.
- **Poids** : 0,5 / 0,3 / 0,2, validés par le propriétaire le 16 octobre 2026. La mesure les
  borne sans les déterminer.
- **Vent, tranche la plus exposée** : à part égale entre tranches, la plus haute l'emporte.
  « Par altitude et non par rôle » est la décision 3-A du 15 octobre 2026 (T8).
- **Version** : `<numéro>-<empreinte>`, l'empreinte couvrant poids, ancres, définitions et fenêtre.
  Changer l'un d'eux change la version ; elle est portée par chaque ligne (`version_score`).
- **Composante manquante** : le score est NULL et `composantes_manquantes` dit laquelle. Aucune
  imputation, aucune renormalisation sur deux composantes. Sur `coeur`, 35 lignes sur 392 n'ont
  pas de neige fraîche.
- **Rupture de lecture** : la neige fraîche passe de `secteurs` à `fourchette` en 2023-2024
  (§ 2) ; `lecture_neige` et `rupture_neige` le disent sur chaque ligne.
- **Lignes non comparables** : conservées, avec `comparable = false` et `motif_exclusion`.
- **Corrélations** (lignes comparables) : risque–neige 0,54 ; risque–vent 0,14 ; neige–vent 0,19.
  Distribution du score : p5 10, médiane 41, p95 79.
