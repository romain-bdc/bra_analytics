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
  En réalité **4 250 bulletins sur les 23 533 du corpus, soit 18,1 %**, portent `-1`, avec un
  commentaire du type « Information neige et avalanche rédigée à partir d'informations réduites »
  et un résumé « Pas d'enneigement ». Ces bulletins se concentrent en novembre (1 572), mai
  (1 345), décembre (566), juin (497) : début et fin de saison. `RISQUEMAXI` y est vide.

  C'est une **sentinelle, pas une mesure** : laissée telle quelle dans une colonne entière, elle
  fausse toute moyenne. Le même `-1` sert de « sans objet » pour `PLUIENEIGE` et `MERNUAGES`
  (documenté) et apparaît aussi sur `TEMPSSENSIBLE`.

  La sentinelle n'est en usage que sur **cinq saisons, 2016-2017 à 2020-2021 : 4 247 bulletins
  sur les 11 240 de ces saisons, soit 37,8 %**. Les trois restants sont isolés (un en 2015-2016,
  un en 2023-2024, un en 2024-2025) et les saisons 2021-2022, 2022-2023 et 2025-2026 n'en
  comptent aucun. Ces bulletins portent aussi une `DATEVALIDITE` trompeuse, cause d'une perte
  silencieuse de 2 471 jours-massif (§ 2).

  > **Dénominateur.** Sauf mention contraire, tout pourcentage de ce document se rapporte au
  > corpus complet — **23 533 bulletins**, 11 massifs pyrénéens, saisons 2015-2016 à 2025-2026,
  > après déduplication. Les versions antérieures de ce document annonçaient ici « 4 247 sur
  > 12 488 (34 % du corpus 2016-2022) » et, au § 2 bis, « 4 250 (18 % du corpus) » : deux
  > dénominateurs différents pour un même fait, dont l'un — 12 488 — ne correspond ni à un
  > nombre de bulletins ni à un nombre de fichiers de l'archive. Seuls les deux comptages
  > ci-dessus, 4 250 / 23 533 et 4 247 / 11 240, sont vérifiables par requête.
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
- **`DATEVALIDITE` ne désigne pas le jour couvert.** Le jour décrit par le bulletin est porté par
  `DATEECHEANCE`. Les deux attributs coïncident sur la totalité des bulletins estimés — 18 869
  sur 18 869 — ce qui rend la confusion indétectable en pleine saison. Hors saison ils divergent
  de 1 à 4 jours : `DATEVALIDITE` y annonce la date du **prochain** bulletin (« valable
  jusqu'au… »). Le massif 64 rédige les 17, 18, 19 et 20 novembre 2016 quatre bulletins portant
  tous `DATEVALIDITE="2016-11-21"`, pour des `DATEECHEANCE` régulièrement espacées.
  Indexer sur `DATEVALIDITE` écrase ces journées les unes sur les autres : **2 471 jours-massif
  disparaissaient ainsi**, silencieusement, d'une vue agrégée à la journée.
  `DATEECHEANCE` est renseignée sur les 23 533 bulletins.
- **Rééditions non signalées.** Le 22/02/2023, Aspe-Ossau a deux fichiers, même `DATEBULLETIN`,
  `AMENDEMENT="false"` **pour les deux** ; seul `DATEDIFFUSION` diffère. Contenu métier
  (`RESUME`, `STABILITE`, `QUALITE`) strictement identique — seules les images ont été regénérées.
  **`AMENDEMENT` est donc inexploitable pour détecter les révisions** : dédupliquer sur
  `(ID, DATEBULLETIN)` en gardant le `DATEDIFFUSION` maximal.
- **Toutes les rediffusions ne sont pas identiques.** Sur les 90 054 fichiers, 10 522 clés
  `(ID, DATEBULLETIN)` sont diffusées par plusieurs fichiers ; pour **1 453** d'entre elles, les
  blocs `METEO`, `ENNEIGEMENT`, `NEIGEFRAICHE`, `TENDANCES` ou `BSH` diffèrent d'une diffusion à
  l'autre (décompte indépendant par `ElementTree`, 16/10/2026). Jusqu'au correctif de T8, `bra
  build` prenait ces blocs dans le premier fichier lu, et non dans celui que la table `bulletins`
  retient : **1 409 clés** associaient le risque d'une version aux tables filles d'une autre —
  `BSH` dans 1 104 cas, `METEO` dans 230 (dont 217 sur les échéances de 06 h et 12 h du jour
  couvert), `NEIGEFRAICHE` 163, `ENNEIGEMENT` 66, `TENDANCES` 63. Dans 34 de ces cas, la rediffusion
  déplace `DATEECHEANCE` d'un jour (Cinto Rotondo et Renoso-Incudine, 06/04/2026 : la version de
  16 h 00 prévoit le 7, la réédition de 16 h 21 le 6).
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

- **`RISQUE1 = "-1"` : 4 250 bulletins sur 23 533, soit 18,1 % du corpus.** Détaillé en 1.2,
  qui donne aussi la concentration saisonnière (37,8 % sur 2016-2017 → 2020-2021) et fixe le
  dénominateur employé partout ici. C'est de loin l'écart le plus lourd de conséquence : sans
  neutralisation, toute moyenne de risque est fausse.
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

## 2 ter. Constats issus des 36 massifs (90 054 fichiers, 11 saisons)

Extension aux Alpes et à la Corse (tâche T1, 6-7 octobre 2026). Sauf mention contraire, les
chiffres de ce paragraphe portent sur les 36 massifs ; ceux des paragraphes précédents restent
pyrénéens.

**Volumétrie et coût.**

| Étape | Mesure |
|---|---|
| `bra fetch --massifs alpes,corse`, 11 saisons | 63 035 fichiers téléchargés en 2 h 56 min (6 workers) ; cache de 3,9 à 13,0 Go |
| Reprise (même commande, relancée) | 13 fichiers récupérés en 12 min : échecs transitoires du premier passage |
| Cache final | **90 054 fichiers**, 13,0 Go |
| `bra build --replace` | **4 min**, **7 Go de mémoire** au pic, 19 Mo de Parquet |
| Bulletins après déduplication | **77 488** (12 565 publications redondantes écartées, 14 %) |
| `risque_journalier` | 76 853 jours-massif ; 635 bulletins écartés par la collapse quotidienne, dont 162 à indice différent, tous journalisés |

Le pic mémoire est neuf : 40 s et quelques centaines de Mo sur les Pyrénées. Le build charge tout
le corpus parsé avant d'écrire ; à 36 massifs il reste sous 8 Go, mais un ajout de saisons le
rapprochera des limites d'une machine modeste.

**Fichiers en erreur à la source.** Neuf fichiers annoncés par le listing ne sont pas
téléchargeables, à chaque tentative : le serveur sert une page HTML d'erreur sous un code 200,
comme pour les deux cas pyrénéens. Tous tombent en 2021-2022 — la même période :

```
BEAUFORTAIN_20210314142752   VANOISE_20210426135903       HAUTE-TARENTAISE_20211130143037
PELVOUX_20211202153619       VERCORS_20220101142303       VANOISE_20220113141624
MERCANTOUR_20220405142047    BELLEDONNE_20220516140631    VERCORS_20221202150136
```

S'y ajoute un fichier valide mais vide : `ARAVIS_20190328145058.xml` ne contient que
`<Bulletins nombre="0"/>`, seul fichier Aravis du jour. `bra build` le compte en erreur de
parsing ; c'est un jour sans bulletin, pas un défaut de la pipeline.

**Massifs absents.** Le massif **22 (Haut-Var Haut-Verdon) n'est diffusé qu'à partir du
22 novembre 2018** : absent des listings de la source avant cette date (vérifié au 15/01/2018),
il donne 35 massifs aux saisons 2015-2016 à 2017-2018. Le massif 71 manque en 2025-2026 (§ 1.4).

**2019-2020 : l'arrêt n'est pas le même partout.** L'estimation s'arrête fin mars dans toutes les
zones, mais la diffusion non :

| Zone | Dernier jour couvert | Jours-massif après le 26/03/2020 | dont non estimés |
|---|---|---|---|
| Pyrénées | 26/03/2020 | 0 | — |
| Corse | 18/03/2020 | 0 | — |
| Alpes du Nord | 11/06/2020 | 434 | 434 |
| Alpes du Sud | 11/06/2020 | 243 | 243 |

Les Alpes publient, après le confinement, des bulletins sans indice et **par intermittence** :
690 jours-massif manquent en avril dans leur span. D'où une saison qui court jusqu'en juin dans
`bra info`, mais trouée — et toujours non comparable.

**Journées absentes pour tous les massifs.** Les 2 492 jours-massif manquants à l'intérieur des
spans se répartissent ainsi, selon le nombre de massifs absents le même jour :

| Massifs absents le même jour | Jours | Jours-massif |
|---|---|---|
| 1 | 50 | 50 |
| 2 à 9 | 105 | 484 |
| 10 à 29 | 64 | 1 361 |
| 30 à 36 | 17 | 597 |

Les dix-sept journées quasi totales correspondent à des **répertoires de la source vides** (le
bulletin du jour J se trouve dans le répertoire de J−1) : 12 au 20/03/2016 (début de l'archive),
29/04/2019, 15/02/2020 (30 massifs), 12, 13, 14 et 17/12/2020, 4 et 5/02/2025. Les manques de 10
à 29 massifs sont pour l'essentiel l'intermittence alpine de 2019-2020 ; les manques isolés, des
jours sans fichier pour un massif donné.

**Un avis de fin de saison daté de novembre.** `CHABLAIS_20180611132845.xml`
(`TYPEBULLETIN="INA"`) annonce « Rendez-vous début novembre » avec `RISQUE1="0"`,
`RISQUEMAXI="/"` et une `DATEECHEANCE` au 01/11/2018, **143 jours** après sa rédaction ; tous les
autres bulletins couvrent J à J+3. Seul `0` de l'archive, il produisait l'unique erreur
`risque1_hors_echelle` : il est désormais lu comme non estimé, au même titre que `-1`. Son jour
fictif du 01/11/2018 est écarté, et journalisé, par la collapse quotidienne au profit du vrai
bulletin de 2018-2019.

**`INA` n'est pas une anomalie.** `TYPEBULLETIN` vaut `BRA` (61 156), `INA` (14 482), `AMENDEMENT`
(548) ou manque (1 302, saison 2015-2016). `INA` — « Information Neige et Avalanche » — est le
bulletin réduit des journées marginales, celui qui porte `RISQUE1="-1"`.

**Ce qui ne change pas.** Les dates de la pratique du `-1` sont **identiques** sur les 36 massifs
et sur les Pyrénées : la fenêtre `coeur` tient, sans aucun bulletin non estimé sur les saisons
comparables. L'intersection des spans s'élargit à 4 novembre → 7 juin ; `commune` (6 novembre)
reste incluse dans chaque saison. En revanche la part de l'écart inter-époques imputable à
l'encodage tombe de 70 % à **47 %** (glossaire § 2.3).

## 3. Conséquences retenues pour le parser

1. Détecter la racine (`Bulletins` wrapper ou non) et itérer sur les enfants réels.
2. Clé métier = `(massif_id, date_bulletin)` ; dédup par `date_diffusion` max.
3. Jour couvert = `DATEECHEANCE`, **jamais** `DATEVALIDITE` : hors saison, cette dernière porte
   la date du prochain bulletin et fusionne des journées distinctes.
4. Ignorer totalement les `<Content>` base64 (93 % du poids, aucune valeur analytique).
5. Normaliser `LOC1`/`LOC2` en trois colonnes : type (`altitude`/`orientation`/`aucune`),
   seuil d'altitude, secteur.
6. Renommer `EVOLURISQUE*` en `risque*_evolution` **typé comme un indice**, pas comme un code.
7. Harmoniser les directions de vent sur une convention unique + valeur `VRB`.
8. Fallback d'attributs par époque : `SS24Min` ← `SS241`, etc.
9. Parser les dates avec gestion explicite du `Z` et des fractions de seconde.
10. Extraire les textes par concaténation des descendants, jamais par le seul texte direct.
11. Contrôler la cohérence entre `ID` et libellé de massif plutôt que de faire confiance à l'un
    des deux isolément.
12. Valider le prologue XML de toute réponse HTTP : le code 200 ne garantit rien.
13. Saison = novembre→mai, dérivée de `DATEBULLETIN` (`season_start = year if month >= 9 else year - 1`).
