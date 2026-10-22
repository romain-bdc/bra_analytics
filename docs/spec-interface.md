# Spécification — interface d'analyse des BRA historiques

Cible fonctionnelle et technique de l'interface, exprimée comme un **delta sur ce que le repo
contient déjà**. Les décisions de cadrage ont été arbitrées le 6 octobre 2026 ; trois d'entre
elles sont corrigées plus bas, parce que les données ne les permettent pas telles quelles.

Le découpage en tâches est dans [`taches.md`](taches.md). Les conventions de code et les règles
de données sont dans [`../CLAUDE.md`](../CLAUDE.md).

## 1. Objectif

Explorer dix ans d'archives BRA : choisir un massif et une saison, lire le risque, l'enneigement
et la météo associés, et comparer les saisons entre elles.

Le pari du produit est la profondeur historique, pas le temps réel. Le BRA du jour est publié
partout ; ce qui n'existe nulle part, c'est « cette saison est-elle anormale, et par rapport à
quoi ».

Trois usages visés, par ordre de priorité : le pratiquant qui prépare une sortie ou une saison ;
le professionnel qui veut du contexte historique chiffré ; le curieux ou le journaliste qui
cherche un chiffre ou un graphe partageable.

## 2. Ce qui existe déjà

| Couche | État | Où |
|---|---|---|
| Téléchargement de l'archive | Fait, idempotent et reprenable | `bra fetch` |
| Parsing des six formats XML | Fait, validé par fixtures par époque | `parser.py` |
| Normalisation, déduplication, enrichissement | Fait | `build.py` |
| Entrepôt Parquet partitionné par saison | Fait, 6 tables | `warehouse/` |
| Vues d'analyse DuckDB | Fait : `risque_journalier`, `couverture`, `profil_saison`, `saison_fenetre` | `build.py` |
| Méthodologie de comparaison inter-saisons | Fait, bornes mesurées | `fenetres.py`, glossaire § 8 |
| Contrôles de cohérence | Fait, erreurs vs signaux | `bra check` |
| Documentation des champs | Fait | `docs/glossaire.md` |
| Couverture géographique complète | Fait : 36 massifs, 77 488 bulletins | `bra fetch`, T1 |
| **Couche métriques** | **blocs risque (T6), enneigement (T7), météo (T8) et rose des pentes (T9) faits** ; score fait (T10) | `metriques/`, § 5 |
| **Les quatre écrans** | **partiellement : la fiche existe en germe** | § 6 |

Conséquence directe : la spec ne redécrit pas le socle. Elle décrit ce qui s'ajoute, et seulement
cela.

## 3. Décisions arrêtées, et ce que les données en font

Les sept décisions du 6 octobre, avec leur sort après lecture du code.

| Décision | Statut |
|---|---|
| Stocker les deux niveaux de risque, n'afficher que le max | **Déjà fait.** `risque1`, `risque1_evolution`, `risque2`, `risque_maxi` sont tous stockés, et `risque_maxi = max(risque1, risque1_evolution)` est vérifié |
| Deux axes temporels : calendaire et jours depuis le premier bulletin | **À faire.** Ajouter `jour_de_saison` à `risque_journalier` (§ 4) |
| Normalisation par défaut : nombre de jours | **Tenue.** Le nombre de jours couverts est déjà publié par `couverture` et `saison_fenetre` |
| Périmètre v1 : tout ce qui vient du BRA seul | **Tenue.** Aucune source externe n'est ingérée |
| Score composite retenu, hors carte d'accueil | **Tenue**, pondération fixée (v1, validée le 16 octobre 2026) |
| Réutilisation des données publiques | **Tenue.** Licence Ouverte 2.0, attribution à afficher (§ 7) |
| Tranches d'altitude fixes normées | **Corrigée** — voir 3.1 |
| Moyenne du risque sur dix saisons en page d'accueil | **Corrigée** — voir 3.2 |

### 3.1 Les tranches d'altitude ne s'appliquent pas au risque

La décision de normer l'altitude en trois tranches fixes (< 1800 m, 1800–2400 m, > 2400 m) reste
valable, mais **pas pour le risque**, et il faut cesser de l'y rattacher.

Un bulletin ne donne pas « un risque par altitude ». Il donne un indice unique, ou deux indices
distingués soit par altitude, soit par orientation, et c'est `loc_type` qui le dit :

- `loc_type = NULL` → un seul indice, aucune information d'altitude ;
- `loc_type = 'altitude'` → `risque1` sous `altitude_seuil_m`, `risque2` au-dessus ;
- `loc_type = 'orientation'` → `risque1` sur un versant, `risque2` sur l'autre, **aucune
  altitude**.

Il n'existe donc pas de règle d'affectation du risque vers des tranches fixes : sur la majorité
des bulletins il n'y a rien à affecter. Le risque reste publié comme `risque_maxi` par massif et
par jour, et le second indice reste disponible pour une vue experte.

En revanche, les tranches fixes s'appliquent pleinement aux trois blocs qui portent de vraies
altitudes : l'**enneigement** (trois paliers par relevé, avec épaisseur nord et sud), le **vent**
(deux altitudes par bulletin, `vent_altitude_basse_m` et `vent_altitude_haute_m`) et la **neige
fraîche** (`altitude_mesure_m`). Ces altitudes varient d'un massif et d'une époque à l'autre,
donc la normalisation y est nécessaire, et c'est là qu'une règle d'affectation explicite doit
être écrite (§ 4.2).

La première tâche de l'audit est de mesurer la distribution de `loc_type` par saison : elle décide
du périmètre réel de la vue experte.

### 3.2 La métrique d'accueil doit être calculée sur la fenêtre `coeur`

« Moyenne du risque sur dix saisons, une valeur par massif » est la bonne intention, mais la
moyenne brute sur dix saisons est **méthodologiquement fausse** sur ce corpus, et le repo l'a
déjà établi chiffres en main : la sentinelle `RISQUE1=-1` s'arrête au 11 juin 2021, si bien qu'une
moyenne qui couvre les deux époques mélange deux conventions d'encodage. L'écart mesuré est de
0,327 point sur la saison entière contre 0,098 sur la fenêtre `coeur` sur les Pyrénées — 70 % de
l'écart serait un artefact —, et 0,368 contre 0,196 sur les 36 massifs, soit 47 %.

La métrique d'accueil est donc définie ainsi, et pas autrement :

> Moyenne de `risque_maxi` sur la fenêtre `coeur` (15 décembre → 15 avril), restreinte aux saisons
> `comparable = true`, sur `massif_coherent`, avec `risque_maxi IS NOT NULL`.

Deux conséquences à assumer dans l'interface plutôt qu'à masquer. Les saisons 2015-2016
(partielle) et 2019-2020 (confinement) sont écartées : « dix ans » devient **neuf saisons
comparables sur onze**, et le libellé de l'écran doit le dire. Et la moyenne d'une échelle
ordinale ne se présente pas seule : le survol d'un massif affiche le nombre de jours couverts et
le nombre de jours de risque 4 ou 5, qui est le repère non ambigu.

### 3.3 Trois questions ouvertes sont tranchées par les données

Le doc de cadrage listait cinq points en attente de l'audit du XML. Le repo en résout trois.

- **Neige fraîche : champ dédié ou différence d'épaisseur ?** Résolu. La table `neige_fraiche`
  porte les cumuls 24 h de 06 UTC à 06 UTC (`cumul_min_cm`, `cumul_max_cm`), six échéances par
  bulletin dont quatre analyses passées. Le proxy par différence d'épaisseur est abandonné. Il
  reste à écrire la règle de déduplication : un même jour apparaît dans le bloc historique de
  plusieurs bulletins, on retient la rédaction la plus tardive, comme `risque_journalier` le fait
  déjà pour le risque.
- **Problème type d'avalanche : structuré ou NLP ?** Résolu, à une restriction près. Les champs
  `sat1` et `sat2` (situations avalancheuses typiques) sont structurés et numériques, mais
  **n'existent que depuis 2024**. La métrique entre donc en v1 sur 2024+ uniquement, explicitement
  étiquetée. Le chantier NLP sur le texte libre reste hors périmètre.
- **Enneigement : BRA seul ou SAFRAN/CROCUS ?** Résolu pour la v1. La table `enneigement` existe
  avec ses trois paliers ; sa couverture par saison reste à mesurer dans l'audit, mais le recours
  à SAFRAN n'est plus un préalable.

Les deux points ouverts demandaient les distributions réelles : les **seuils par défaut** (vent
fort, épisode de chute, altitude de redoux) et la **pondération du score composite**. Le second
est fixé (v1, glossaire § 13, validée le 16 octobre 2026).

## 4. Compléments au modèle de données

### 4.1 `jour_de_saison`

Ajouté à la vue `risque_journalier`, calculé **par massif et par saison** comme le nombre de jours
depuis le premier `jour_validite` de ce couple — et non depuis une date calendaire commune,
puisque la diffusion ne commence pas le même jour partout.

Il porte le second axe temporel : l'axe calendaire reste celui par défaut, celui-ci sert à ce
qu'une saison ouverte tardivement ne paraisse pas vide en décembre.

### 4.2 Tranche d'altitude normée

Une vue dérivée rattache chaque relevé d'enneigement, de vent et de neige fraîche à l'une des
trois tranches fixes. La règle d'affectation est explicite : **chaque palier est rattaché à la
tranche qui contient son altitude**, et une tranche sans palier pour un massif donné reste nulle
plutôt que d'être interpolée.

**Bornes arrêtées le 6 octobre 2026, au vu de l'audit** : fermées à gauche, < 1800 m,
1800–2400 m, **≥ 2400 m**. Les paliers d'enneigement tombent pile sur 1800 et 2400 m avant 2021
(1500/1800/2400) ; fermer la tranche haute à droite (« > 2400 m ») la laissait vide jusqu'au
passage aux paliers 1500/2000/2500. Définies une fois dans `tranches.py`, vue `palier_tranche`.

C'est une approximation, et elle doit être mesurée avant d'être exploitée : si les altitudes de
référence d'un massif tombent presque toutes dans une seule tranche, la comparaison entre massifs
sur cette tranche n'a pas de sens, et seule la comparaison d'un massif à lui-même dans le temps
reste solide. L'audit produit la distribution des altitudes de référence par massif et par saison.

### 4.3 Convention d'extraction météo

Le bloc météo contient une prévision à plusieurs échéances (`origine = 'prevision'`) et un rappel
des sept jours écoulés (`origine = 'historique'`).

**Arrêtée le 15 octobre 2026, au vu de l'audit : prévision seule, valeur du jour calculée sur
les échéances de 06 h et 12 h.** La convention envisagée d'abord — préférer l'historique quand il
existe — mêlait deux horizons : l'historique manque toute la saison 2015-2016 et 1 à 2 % des jours
jusqu'en 2023, ne porte plus `mer_nuages_m` depuis 2024, et ne diffère presque pas de la
prévision (isotherme 0 °C : 32 à 37 m d'écart moyen). Les heures d'échéance changent en 2024
(00/06/12 h de J, puis 06/12/18 h de J et 00 h de J+1) : seules 06 h et 12 h sont communes aux
deux époques. Mesures et justification : [`glossaire.md`](glossaire.md) § 3.

Le vent se lit par altitude ou par tranche, jamais par rôle bas / haut : jusqu'en 2023 les
Alpes du Sud n'ont qu'un vent, à 3000 m, porté par la colonne « basse » (glossaire § 2.9).

## 5. Couche métriques

Quatre blocs. Les métriques sont des vues DuckDB ou des fonctions de la couche métriques, jamais
du SQL recopié dans l'interface. Chacune est accompagnée de sa couverture.

### 5.1 Risque

| Métrique | Définition | Maille |
|---|---|---|
| Risque du jour | `risque_maxi` | massif × jour |
| Jours ≥ 3 / ≥ 4 / = 5 | Comptes par seuil sur la période filtrée | massif × saison |
| Part de jours par niveau | Répartition 1-5 en part des jours couverts | massif × saison |
| Risque moyen | Moyenne, **fenêtre `coeur` uniquement** pour toute comparaison | massif × saison |
| Risque médian | Médiane, préférable à la moyenne sur une échelle ordinale | massif × saison |
| Maximum saisonnier | Niveau le plus haut atteint, avec sa date | massif × saison |
| Première / dernière occurrence ≥ 3 | Dates encadrant la période exposée | massif × saison |
| Durée de saison BRA | Premier et dernier bulletin, jours couverts — déjà dans `couverture` | massif × saison |
| Épisodes ≥ 3 | Suites de **jours couverts consécutifs** ≥ 3 : nombre, durée médiane, plus long | massif × saison |
| Variations | Hausses ≥ 1 et ≥ 2 niveaux entre deux **jours consécutifs couverts** | massif × saison |
| Écart à la normale | `risque_maxi` moins la médiane des saisons comparables à la même date | massif × jour |
| Second indice | `risque1` / `risque2` et `loc_type`, vue experte | massif × jour |

Deux pièges de calcul à traiter explicitement, et non à découvrir à l'usage. Un **trou d'archive
rompt un épisode** : une suite de jours ≥ 3 interrompue par un jour sans bulletin ne doit pas être
recollée, et le nombre d'épisodes rompus par un trou doit être publié à côté du compte. De même,
une **variation ne se calcule qu'entre deux jours réellement consécutifs** : un écart de deux
jours n'est pas une hausse en 24 h.

La métrique « indices naturel et accidentel en séries séparées », prévue au cadrage, **n'est pas
réalisable** : `naturel` et `accidentel` sont des textes rédigés, pas des indices chiffrés. Elle
sort du périmètre v1.

### 5.2 Enneigement

| Métrique | Définition | Maille |
|---|---|---|
| Limite d'enneigement | `limite_nord_m`, `limite_sud_m` | massif × jour |
| Épaisseur par tranche | `epaisseur_nord_cm` / `epaisseur_sud_cm` par tranche normée | massif × jour × tranche |
| Date d'enneigement continu | Premier jour à partir duquel la limite reste sous un seuil choisi | massif × saison |
| Durée d'enneigement | Jours au-dessus d'un seuil d'épaisseur à une tranche donnée | massif × saison |
| Maximum saisonnier | Épaisseur maximale et sa date | massif × saison × tranche |
| Neige fraîche cumulée | Somme de `cumul_max_cm`, `origine = 'historique'`, dédupliqué | massif × période |
| Épisodes de chute | Jours où `cumul_max_cm` dépasse un seuil ; plus forte chute | massif × saison |
| Anomalie d'enneigement | Écart à la médiane des saisons comparables à la même date | massif × jour |

L'enneigement du BRA est **indicatif** et rattaché à des altitudes de référence qui varient d'un
massif à l'autre. L'interface doit orienter vers la comparaison d'un massif à lui-même dans le
temps, qui est solide, plutôt que vers la comparaison entre massifs à altitude nominale égale,
qui l'est beaucoup moins.

### 5.3 Météo

| Métrique | Définition | Maille |
|---|---|---|
| Isotherme 0 °C | `iso_0_m`, échéance du jour de validité | massif × jour |
| ISO 0 min / max / moyen | Agrégats sur la période filtrée | massif × saison |
| Jours ISO 0 > seuil | Compteur de redoux marqués, seuil paramétrable | massif × saison |
| Amplitude ISO 0 en 24 h | Variation entre deux jours consécutifs couverts | massif × jour |
| Vitesse et direction de vent | Par tranche normée, convention de direction anglaise | massif × jour × tranche |
| Jours de vent fort | Au-dessus d'un seuil paramétrable | massif × saison |
| Limite pluie / neige | `limite_pluie_neige_m` | massif × jour |
| Temps sensible | Répartition des codes, avec libellés | massif × saison |
| Indice de transport par le vent | Vent fort et neige fraîche récente combinés, par direction | massif × jour |
| Épisodes de redoux | ISO 0 franchissant un seuil à la hausse ≥ 24 h, avec le risque avant et après | massif × saison |

Les deux dernières sont les plus utiles de ce bloc : elles disent quelque chose que l'utilisateur
ne peut pas calculer de tête, là où les autres ne font que republier le bulletin.

Le bloc météo est une **prévision**. L'interface doit le dire là où les séries sont affichées, et
pas dans une note de bas de page.

### 5.4 Rose des pentes et situations typiques

| Métrique | Définition | Maille |
|---|---|---|
| Fréquence d'exposition | Part des jours où chaque secteur est signalé (`pente_*`) | massif × saison × orientation |
| Fréquence pondérée | Idem, restreinte aux jours ≥ 3 ou ≥ 4 | massif × saison × orientation |
| Secteur dominant | Orientation la plus signalée sur la période | massif × saison |
| Concentration | Nombre moyen de secteurs signalés par jour : risque diffus ou localisé | massif × saison |
| Saisonnalité | Fréquence par secteur et par mois | massif × mois × orientation |
| Croisement vent × orientation | Orientations exposées face aux directions de vent dominantes | massif × période |
| Situations typiques | Répartition de `sat1` / `sat2`, **depuis 2023-2024 uniquement** (première saison qui en porte, mesurée par l'audit) | massif × saison |

**Correction (16 octobre 2026) : la rose n'a pas d'altitude.** `<PENTE>` est un jeu unique de huit
booléens par bulletin, sans attribut d'altitude, comme `<SitAvalTyp>` ; la consigne « une tranche à
la fois » ne pouvait pas s'appliquer, faute de donnée à ventiler (même cas que § 3.1 pour le risque).
Rose, secteur dominant, concentration, saisonnalité et situations typiques sont donc publiés par massif
× saison, étiquetés `altitude = 'non localisee'`, sans prétendre à une tranche. Seul le croisement
vent × orientation se ventile par tranche, parce que les altitudes de vent, elles, sont réelles.

Pour comparer deux saisons, deux roses côte à côte ou un graphe en barres par
secteur, jamais deux couches superposées sur la même rose.

### 5.5 Score composite

Score de « sévérité de saison » mélangeant risque, enneigement et vent. Retenu, mais **pas comme
métrique d'accueil**, et encadré par trois règles : sa formule est affichée là où le score est
montré, ses composantes restent consultables séparément, et sa version est tracée — sinon un
changement de pondération rend silencieusement incomparables deux captures prises à six mois
d'intervalle.

Sa pondération a été fixée sur les distributions réelles (glossaire § 13) ; sa version se dérive des poids et des ancres.

## 6. Écrans

Quatre écrans, une barre de filtres persistante en haut (massif, saison, période, tranche
d'altitude). Les filtres ne se réinitialisent jamais entre les écrans et vivent dans l'URL, pour
que tout état soit partageable.

```
Accueil (carte)  →  Fiche massif-saison  →  Comparaison de saisons
                                         →  Exploration orientations et vent
```

**Accueil.** Carte des 36 massifs colorée par la moyenne `coeur` sur les saisons comparables, une
valeur par massif, sans sélecteur de saison. Le survol donne le nombre de jours couverts et le
nombre de jours de risque 4 ou 5. Un sélecteur permet de basculer sur une métrique simple
(jours ≥ 3, maximum atteint, durée d'enneigement).

**Fiche massif-saison.** La page centrale : indicateurs clés groupés en haut (risque, neige,
isotherme et vent), série temporelle du risque sur la bande médiane et interquartile des autres
saisons, puis enneigement, ISO 0 et vent sur le même axe temporel aligné. Enneigement et ISO 0
portent en pointillés la moyenne des autres saisons comparables, qui remplace le faisceau de
traits gris, illisible une fois la bande présente.

**Comparaison.** Les trois modes : une saison contre les autres du même massif ; deux à quatre
saisons explicitement choisies, superposées, avec tableau récapitulatif ; N massifs sur une même
saison. Plus le classement des saisons sur une métrique choisie, en barres horizontales, qui est
la vue partageable par excellence — celle qui produit la phrase « 2024-25 est la deuxième saison
la plus avalancheuse des dix dernières années en Haute-Bigorre ». Au-delà de quatre courbes
superposées, c'est illisible : brider le sélecteur.

**Exploration.** Rose des pentes (non localisée en altitude, § 5.4) et croisement vent × orientation par tranche de vent. La matrice altitude × orientation n'existe pas : la rose n'a pas d'altitude.

Tous reprennent le motif existant : un payload JSON construit en Python, inséré dans un gabarit
via `__DONNEES__`, et tout le filtrage côté client. Pas de serveur, pas de framework.

## 7. Règles transversales

Chaque graphe expose son export — CSV des données, PNG de l'image — et affiche la couverture de
données sous-jacente. Chaque page indique la date du dernier bulletin intégré, sans quoi
l'utilisateur ne sait pas s'il regarde une saison à jour.

Toute comparaison de saisons est tronquée à période égale par défaut, et le signale dans le
sous-titre du graphe et non en note de bas de page.

L'attribution est obligatoire et visible : **données Météo-France, Licence Ouverte 2.0**, avec la
date de l'archive utilisée. Là où la carte s'affiche s'y ajoute celle des contours :
**contours des massifs Météo-France, Licence Ouverte 2.0, version du 15/02/2024**
([`contours.md`](contours.md)).

Le vocabulaire reste descriptif. « Au-dessus de la médiane des neuf saisons comparables » est
correct ; « tendance au réchauffement » ne l'est pas — dix saisons ne sont pas un signal
climatique, et les critères d'émission du risque ont eux-mêmes évolué sur la période.

## 8. Hors périmètre v1

L'alerting mail hebdomadaire, qui partage le pipeline mais pas l'interface, et qui sera le premier
besoin d'écritures concurrentes. L'API publique. Le temps réel via l'API Bulletin Avalanche.
Les sources externes : observations de stations, AROME, SAFRAN/CROCUS. L'extraction NLP du texte
libre. Les sous-massifs et les points de mesure.

## 9. Risques

Les **contours géographiques des massifs** sont résolus (T3, [`contours.md`](contours.md)) :
le GeoJSON publié par Météo-France dans le jeu data.gouv.fr de l'archive BRA, sous **Licence
Ouverte 2.0**, versionné dans le repo. Sa propriété `code` est le `massif_id` lui-même et couvre
les 36 massifs, Andorre comprise. Les micro-régions EAWS, d'abord envisagées, sont sous CC0 —
la crainte d'une licence non affichée était infondée — mais n'ont pas de contour pour le
massif 71 ; elles restent documentées comme alternative. L'attribution des contours s'ajoute à
celle des données (§ 7).

La **couverture incomplète** est résolue (T1) : les 36 massifs sont ingérés — 90 054 fichiers,
13 Go de XML, trois heures de téléchargement, quatre minutes de build pour 19 Mo de Parquet.

Les deux autres sont des restrictions de série à étiqueter, pas à corriger : `sat1` / `sat2`
n'existent que depuis 2024, et la table `tendances` s'arrête en 2023 avec une sémantique
non documentée — à ne pas exploiter analytiquement sans l'avoir confirmée.
