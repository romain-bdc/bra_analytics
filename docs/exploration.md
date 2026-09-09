# BRA — Rapport d'exploration des archives XML

Échantillon : 33 fichiers, massifs pyrénéens (ID 64–74), 11 dates réparties de mars 2016 à
février 2026, plus 2 mois de listings complets (février 2023, février 2026).
Source : `https://files.data.gouv.fr/meteofrance/data/BULLETIN/BRA/AAAA/MM/JJ/xml/`.
Référence : *Descriptif technique des informations du bulletin avalanche*, Météo-France,
version du 26/10/2023 (`descriptif_bulletinrisqueavalanche_formatxml_20231026_309.pdf`).

## 0. Le constat qui structure tout

**Le descriptif 2023 ne décrit pas les archives 2016–2023.** Publié le 26/10/2023, il documente
le format entré en service à la saison 2023-2024. Les bulletins antérieurs — soit 8 des
11 saisons disponibles — suivent des schémas différents, dont un changement de racine.
Le document est donc une spécification *du présent*, pas *de l'archive*.

L'échantillon fait apparaître **6 signatures structurelles distinctes** :

| Époque | Saisons | Fichiers | Traits distinctifs |
|---|---|---|---|
| A | 2016 | ~67–71 Ko | racine `BULLETINS_NEIGE_AVALANCHE`, pas de `BSH`, pas de `DATEVALIDITE` |
| B | 2017–2018 | ~208–232 Ko | apparition de `BSH` (historique 7 j) |
| C | 2019–2023 | ~180–200 Ko | wrapper `<Bulletins>`, ajout `<DateValidite>` |
| D | 2024 | ~12 Ko | racine à plat, images externalisées, `SitAvalTyp`, `RisqueJ2` |
| E | 2025 | ~14 Ko | ajout `TITRE` + `TEXTESANSTITRE` dans `STABILITE` |
| F | 2026 | ~13 Ko | ajout `<a href>` dans `TexteMeta/LienDocumentation` |

Le passage C→D (saison 2023-2024) est la vraie rupture ; A→B→C et D→E→F sont des retouches.

## 1. Écarts avec le descriptif technique 2023

### 1.1 Structurels (le doc décrit D/E/F uniquement)

- **Racine.** Le doc montre `<BULLETINS_NEIGE_AVALANCHE>` comme racine. De 2019 à 2023 la racine
  réelle est `<Bulletins nombre="N">` qui l'encapsule. Un parser calé sur le doc échoue sur 5 saisons.
- **`nombre` est mensonger.** `ANDORRE_20230215142300.xml` porte `nombre="2"` pour **un seul**
  enfant. Ne jamais s'en servir : itérer sur les enfants réels.
- **Images.** Le doc annonce des *noms de fichiers* PNG (`ImageRisque`, `ImagePente`…). Avant 2024
  les images sont **embarquées en base64** dans des balises `<Content>` et représentent **93 % du
  poids** des fichiers (171 Ko sur 184 Ko). C'est ce qui explique le rapport 15:1 entre époques.
- **`TENDANCES`/`TENDANCE`** (2 éléments, attributs `DATE`/`VALEUR`) existe de 2016 à 2023 et n'est
  **pas documenté** ; il disparaît en 2024.
- **`PRODUCTEUR`** (ex. `CDM651-PREVI`, `CDM661`, `CDM311-PREVI`) est présent jusqu'en 2023,
  non documenté, et supprimé en 2024.
- **`STABILITE`.** Le doc ne prévoit que `TEXTE`. Depuis 2025 le bloc contient aussi `TITRE` et
  `TEXTESANSTITRE` (le titre dupliqué en tête de `TEXTE`).
- **`SitAvalTyp`, `RisqueJ2`, `CommentaireRisqueJ2`, `RISQUEMAXIJ2`, `DATE_RISQUE_J2`,
  `TexteMeta`** n'existent qu'à partir de 2024 : nuls sur 8 saisons.

### 1.2 Sémantiques (pièges de parsing)

- **`LOC1`/`LOC2` sont polysémiques.** Ils portent soit une **altitude** (`<2200`, `>2200`), soit
  une **orientation** (`S` / `N`). Observé dans les deux régimes, avant et après 2024. Le doc le
  mentionne mais nomme les deux champs `LOC1` dans sa liste descriptive (coquille) ; il annonce
  `« E »/« O »` alors que l'échantillon ne montre que `S`/`N`.
- **`EVOLURISQUE1` n'est pas un code d'évolution** mais **le second indice de risque de la
  journée**. `RISQUE1="1" EVOLURISQUE1="2" RISQUEMAXI="2"` : `RISQUEMAXI = max(RISQUE1, EVOLURISQUE1)`.
  Le libellé « évolution temporelle du risque1 » induit en erreur sur le type.
- **Directions de vent : deux conventions.** Jusqu'en 2023 convention **anglaise** (`NW`, `W`, `SW`)
  avec `_` pour variable ; à partir de 2024 convention **française** (`NO`, `O`, `SO`) avec `Vrb`.
  Le doc décrit `"_"` dans le texte mais utilise `Vrb` dans son propre exemple : il est
  contradictoire, et c'est `Vrb` qui correspond au format qu'il documente.
- **`TEMPSSENSIBLE` déborde la palette documentée.** Observé : `-1, 5, 8, 9, 10, 11, 12, 15, 81`
  absents de la table du doc. `-1` est vraisemblablement « non renseigné ».
- **`VIGILANCE`** : le doc dit « vide ». Valeur `JAUNE` observée en 2016.
- **`RISQUE1 = "-1"` : risque non estimé.** Le doc affirme « toujours renseigné, valeur de 1 à 5 ».
  En réalité **4 247 bulletins sur 12 488** (34 % du corpus 2016-2022) portent `-1`, avec un
  commentaire du type « Information neige et avalanche rédigée à partir d'informations réduites »
  et un résumé « Pas d'enneigement ». Ces bulletins se concentrent en novembre (1 571), mai
  (1 345), décembre (566), juin (497) : début et fin de saison. `RISQUEMAXI` y est vide.
  C'est une **sentinelle, pas une mesure** : laissée telle quelle dans une colonne entière, elle
  fausse toute moyenne. Le même `-1` sert de « sans objet » pour `PLUIENEIGE` et `MERNUAGES`
  (documenté) et apparaît aussi sur `TEMPSSENSIBLE`.
- **`SS241`/`SS242`** (avant 2024) sont renommés **`SS24Min`/`SS24Max`** (2024+). Même sémantique,
  attribut différent — silence du doc sur l'ancien nom.
- **`SECTEURSS1`/`SECTEURSS2`** sur `NEIGEFRAICHE` et **`ALTITUDEVENT1/2`** sur `BSH/METEO`
  existent avant 2024 puis disparaissent.
- **`MERNUAGES`, `ISO-10`, `TEMPSSENSIBLEJ`** disparaissent de `BSH/METEO/ECHEANCE` en 2024.
  Note : l'attribut `ISO-10` contient un tiret — piège si on mappe les attributs sur des
  identifiants Python.

### 1.3 Cardinalités réelles vs annoncées

| Chemin | Doc 2023 | ≤2023 | ≥2024 |
|---|---|---|---|
| `METEO/ECHEANCE` | 4 | **3** | 4 |
| `BSH/METEO/ECHEANCE` | 28 | **21** | 28 |
| `NEIGEFRAICHE/NEIGE24H` | 6 | 6 | 6 |
| `ENNEIGEMENT/NIVEAU` | 3 | 3 | 3 |
| `BSH/{ENNEIGEMENTS,NEIGEFRAICHE,RISQUES}` | 7 | 7 | 7 |
| `TENDANCES/TENDANCE` | absent du doc | 2 | 0 |

Le doc se contredit par ailleurs : « 4 éléments – soirée, nuit, matin, après-midi, soir » énumère
cinq libellés pour quatre éléments.

### 1.4 Référentiel des massifs

- Le doc annonce **36 massifs**. Les listings donnent **35** en 2026 : **le massif 71 (Andorre) a
  disparu de toute la saison 2025-2026** (vérifié sur 7 dates de février 2026). Il est présent
  jusqu'en 2025 inclus.
- **Le nom du massif n'est pas une clé.** Il change de graphie au fil des époques, alors que l'`ID`
  reste stable :

  | ID | ≤2023 | 2024–2025 | 2026 |
  |---|---|---|---|
  | 65 | `ASPE-OSSAU` | `Aspe Ossau` | `Aspe Ossau` |
  | 67 | `AURE-LOURON` | `Aure Louron` | `Aure Louron` |
  | 71 | `ANDORRE` | `Andorre (massif)` | *absent* |
  | 73 | `CAPCIR-PUYMORENS` | `Capcir Puymorens` | `Capcir Puymorens` |

  Le doc liste « Andorre » (sans parenthèses) et « Embrunnais Parpaillon » ; les données donnent
  `Andorre (massif)` et, en 2026, `Embrunais Parpaillon` (un seul `n`) — l'orthographe du massif 20
  change entre 2025 et 2026. Le doc contient aussi une coquille : massif 15 Oisans, département « 3sère ».
- Les **noms de fichiers** suivent ces variations, avec espaces URL-encodés (`%20`), parenthèses
  (`%28`/`%29`) et des irrégularités (`ORLU__ST_BARTHELEMY` à double underscore).
  **Conclusion : indexer sur `ID`, jamais sur le nom de fichier ni sur `MASSIF`.**

## 2. Pièges d'archive (hors périmètre du doc)

- **Le dossier de date ≠ la date du bulletin.** Dans `BRA/2016/03/10/xml/`, deux fichiers portent
  `DATEBULLETIN="2016-03-09"`. Le partitionnement doit dériver de `DATEBULLETIN`, pas du chemin.
- **Le timestamp du nom de fichier ≠ `DATEDIFFUSION`.** Toujours en 2016 :
  `ANDORRE_20160310144702.xml` déclare `DATEDIFFUSION="2016-03-09T14:05:23.2144571Z"`.
- **Formats de date hétérogènes.** 2016 : fraction de seconde à 7 chiffres **et suffixe `Z` (UTC)**.
  2017+ : datetime naïf, heure locale. Le même champ change de fuseau — `fromisoformat` seul ne suffit pas.
- **`DATEVALIDITE` absent en 2016** (attribut et élément `<DateValidite>` apparaissent en 2017 et 2019).
- **Rééditions non signalées.** Le 22/02/2023, Aspe-Ossau a deux fichiers, même `DATEBULLETIN`,
  `AMENDEMENT="false"` **pour les deux** ; seul `DATEDIFFUSION` diffère. Contenu métier
  (`RESUME`, `STABILITE`, `QUALITE`) strictement identique — seules les images ont été regénérées.
  **`AMENDEMENT` est donc inexploitable pour détecter les révisions** : dédupliquer sur
  `(ID, DATEBULLETIN)` en gardant le `DATEDIFFUSION` maximal.
- **Trous de données réels.** Le 07/02/2023 ne contient que 8 fichiers (Pyrénées orientales et
  Corse) : Alpes et Pyrénées occidentales manquantes. Un jour manquant n'est pas une anomalie de
  pipeline.
- **Volumétrie irrégulière** : 31 à 60 fichiers/jour selon les jours, contre 35–36 attendus.
- **BOM UTF-8.** Les fichiers antérieurs à 2024 commencent par `EF BB BF` avant le prologue
  `<?xml`. `ElementTree` le tolère, mais tout contrôle d'intégrité qui teste le premier octet
  (« le contenu commence-t-il par `<?xml` ? ») rejette à tort l'intégralité des archives 2016-2023.
- **Redirection HTTP.** `files.data.gouv.fr` répond **302** vers un bucket OVH S3
  (`meteofrance.s3.sbg.io.cloud.ovh.net`). Sans `-L` / `follow_redirects`, on récupère 138 octets
  de HTML au lieu du XML — l'erreur est silencieuse car le fichier existe et porte l'extension `.xml`.
- **Couverture** : mars 2016 → juin 2026. La première saison est incomplète (démarre en mars 2016).
  L'archive est saisonnière (novembre → mai) : les mois 06–10 sont vides ou marginaux.

## 2 bis. Constats issus du corpus complet (27 006 fichiers, 11 saisons)

L'échantillon de 33 fichiers n'avait pas fait apparaître les points suivants, tous confirmés
sur l'intégralité des Pyrénées 2016-2026.

- **`RISQUE1 = "-1"` : 4 250 bulletins (18 % du corpus).** Détaillé en 1.2. C'est de loin
  l'écart le plus lourd de conséquence : sans neutralisation, toute moyenne de risque est fausse.
- **Un bulletin technique usurpe un identifiant de massif.** `MOYENNE_MONTAGNE_20161104143704.xml`
  porte `ID="3"` (Mont-Blanc au référentiel) avec `MASSIF="MOYENNE MONTAGNE"`, et pour tout
  contenu : « LES BULLETINS DE RISQUE AVALANCHE NE SONT PAS PRODUITS SUR LES MASSIFS DE MOYENNE
  MONTAGNE ». L'`ID` est donc une clé fiable mais **pas infaillible** : un contrôle croisé
  ID ↔ libellé est nécessaire.
- **Les blocs de texte peuvent contenir du balisage HTML.** Le même fichier enveloppe son texte
  dans un `<h1>`. Une extraction par `findtext` (texte direct de l'élément) rend alors une
  chaîne vide : il faut concaténer le texte des descendants.
- **Dates malformées.** Toujours ce fichier :
  `DATEDIFFUSION="2016-02-04T15:00:24.1234567Z.6378518Z"` — deux suffixes `Z` concaténés.
- **`TYPEBULLETIN` absent sur toute la saison 2015-2016** (415 bulletins).
- **Interruption Covid.** La saison 2019-2020 s'arrête au **26 mars 2020**, avec deux journées
  partielles juste avant (24/03 : 4 massifs, 25/03 : 7). Le confinement du 17 mars 2020 a
  interrompu la production. Ce n'est pas une lacune d'ingestion.
- **Fichiers corrompus à la source.** 2 fichiers sur 27 006 sont annoncés par le listing mais
  renvoient un corps « 500 Internal Server Error » **sous un code HTTP 200** :
  `HAUTE-BIGORRE_20211116144624.xml` et `COUSERANS_20220526132925.xml`. Le contrôle du prologue
  XML est indispensable — le code HTTP ne suffit pas à valider une réponse.
- **Volumétrie.** 27 006 fichiers / 3,7 Go de XML brut pour les 11 massifs pyrénéens ;
  après dédoublonnage, **23 533 bulletins**, soit 3 473 fichiers redondants (12,9 %).

## 3. Conséquences retenues pour le parser

1. Détecter la racine (`Bulletins` wrapper ou non) et itérer sur les enfants réels.
2. Clé métier = `(massif_id, date_bulletin)` ; dédup par `date_diffusion` max.
3. Ignorer totalement les `<Content>` base64 (93 % du poids, aucune valeur analytique).
4. Normaliser `LOC1`/`LOC2` en trois colonnes : type (`altitude`/`orientation`/`aucune`),
   seuil d'altitude, secteur.
5. Renommer `EVOLURISQUE*` en `risque*_evolution` **typé comme un indice**, pas comme un code.
6. Harmoniser les directions de vent sur une convention unique + valeur `VRB`.
7. Fallback d'attributs par époque : `SS24Min` ← `SS241`, etc.
8. Parser les dates avec gestion explicite du `Z` et des fractions de seconde.
9. Extraire les textes par concaténation des descendants, jamais par le seul texte direct.
10. Contrôler la cohérence entre `ID` et libellé de massif plutôt que de faire confiance à l'un
    des deux isolément.
11. Valider le prologue XML de toute réponse HTTP : le code 200 ne garantit rien.
12. Saison = novembre→mai, dérivée de `DATEBULLETIN` (`season_start = year if month >= 9 else year - 1`).
