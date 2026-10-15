# Tâches — interface d'analyse des BRA

Séquence de travail pour [`spec-interface.md`](spec-interface.md). Les conventions sont dans
[`../CLAUDE.md`](../CLAUDE.md) : les règles de données y sont non négociables, et une tâche qui
les enfreint n'est pas finie même si elle tourne.

Chaque tâche porte ses critères d'acceptation. L'ordre compte : le lot 0 peut invalider une partie
du lot 2, donc il passe en premier. Ne pas démarrer une tâche dont une dépendance n'est pas close.

Convention de travail : une tâche = une branche, et sa définition de fini inclut toujours
`uv run pytest` au vert et `uv run bra check` sans erreur nouvelle.

---

## Lot 0 — Mesurer avant de construire

### T1. Étendre la couverture aux Alpes et à la Corse

Le warehouse ne contient que les 11 massifs pyrénéens. L'écran d'accueil en demande 36.

- `bra fetch` sur les Alpes puis la Corse, saison par saison, en mesurant au passage la durée,
  le volume de cache et le nombre de fichiers en erreur.
- `bra build --replace`, puis `bra check` et `bra info`.
- Mettre à jour les chiffres du README (volumétrie, durée de build, nombre de bulletins).

**Fait quand** : `bra info` montre les 36 massifs du référentiel sur les saisons où ils sont
diffusés ; les écarts de couverture sont expliqués, pas seulement constatés ; les chiffres du
README correspondent à l'entrepôt reconstruit.

**Attention** : le fetch est long et reprenable — l'interrompre est sans conséquence, le relancer
ne retélécharge que ce qui manque. Ne pas paralléliser au-delà de ce que la source tolère.

### T2. Audit de disponibilité champ × saison

Le but est de savoir quelles métriques sont réellement calculables avant d'en écrire une seule.
C'est la tâche qui peut invalider une partie de la spec, et c'est pour cela qu'elle est ici.

Produire un tableau de la part de valeurs non nulles par champ et par saison, et en particulier :

- la distribution de `loc_type` (`NULL` / `altitude` / `orientation`), qui décide du périmètre de
  la vue experte sur le second indice ;
- la distribution de `altitude_seuil_m` quand `loc_type = 'altitude'` ;
- les altitudes de référence de `enneigement.altitude_m`, de `neige_fraiche.altitude_mesure_m` et
  des deux altitudes de vent, par massif et par saison — elles fondent les tranches normées ;
- la couverture de la table `enneigement` par saison, qui décide si la v1 tient sans SAFRAN ;
- la couverture de `sat1` / `sat2` depuis 2024 ;
- les distributions nécessaires aux seuils encore ouverts : `vent_haut_vitesse_kmh`,
  `cumul_max_cm`, `iso_0_m` ;
- la disponibilité des champs du bloc météo selon `origine`, pour valider ou invalider la
  convention d'extraction de la spec § 4.3.

**Fait quand** : le tableau est produit par une commande (`bra audit` ou une extension de
`bra check`), reproductible, et écrit dans `docs/disponibilite.md` ; chaque métrique de la spec
§ 5 y est marquée calculable, calculable sur un sous-ensemble d'époques, ou non calculable.

### T3. Contours géographiques des massifs

Dépendance externe de l'écran d'accueil. La source est identifiée : les **micro-régions EAWS**
(European Avalanche Warning Services), dont le jeu français est exactement le découpage des
massifs BRA, avec des identifiants de la forme `FR-<massif_id>` — `FR-68` pour le Luchonnais,
`FR-22` pour le Haut-Var Haut-Verdon — qui se raccordent donc directement au référentiel de
`massifs.py` sans table de correspondance.

```
https://regions.avalanches.org/micro-regions/latest/FR_micro-regions.geojson.json
```

Géométries en `MultiPolygon`, propriétés réduites à `{"id": "FR-nn"}`. Deux variantes existent à
côté : un fichier `_elevation` qui subdivise par tranche d'altitude, et des fichiers de libellés
multilingues sous `micro-regions_names/` (dont `fr.json`).

- Télécharger le fichier et le versionner dans le repo — c'est une donnée de référence stable,
  pas une dépendance réseau à l'exécution.
- **Épingler une version plutôt que `latest`** : un découpage qui change sous les pieds de
  l'interface décale les couleurs sans rien signaler. Le chemin `micro-regions/` expose les
  versions publiées.
- Vérifier le raccordement : les 36 identifiants du référentiel doivent être présents, et toute
  entrée `FR-*` sans correspondance dans `massifs.py` doit être signalée plutôt qu'ignorée — le
  jeu EAWS peut contenir des régions qui ne sont pas des massifs BRA.
- Simplifier les géométries pour l'usage web (le fichier brut est lourd pour une page autonome),
  en conservant le fichier d'origine à côté.
- **Confirmer la licence auprès de l'EAWS avant toute mise en ligne publique.** Elle n'est pas
  affichée sur le site de diffusion, et une carte publique sans licence vérifiée est un risque
  juridique, pas un détail. Tant que ce point n'est pas tranché, la carte reste en local.

Deux replis, dans cet ordre : chercher le shapefile des massifs SAFRAN/S2M côté Météo-France
(`meteo.data.gouv.fr`), qui serait sous Licence Ouverte et donc sans ambiguïté ; sinon, grille de
massifs groupés par chaîne, qui perd la géographie mais conserve le classement spatial.

**Fait quand** : un GeoJSON versionné est dans le repo, sa version et sa source documentées, les
36 identifiants raccordés et les écarts listés, la licence tranchée par écrit — ou le repli acté
dans la spec.

**Résolution (6 octobre 2026)** : repli acté, mais pas celui qui était écrit. Aucun shapefile
SAFRAN/S2M n'a été trouvé ; c'est le GeoJSON des massifs joint par Météo-France au jeu
data.gouv.fr de l'archive BRA elle-même (Licence Ouverte 2.0) qui a été retenu. Il couvre
les 36 identifiants, Andorre comprise, par leur `massif_id` entier. Le jeu EAWS est sous CC0 mais n'a pas de `FR-71`, et ses identifiants
sont sur deux chiffres (`FR-01`, pas `FR-1`) ; sa variante `_elevation` ne subdivise pas les
massifs français. Voir [`contours.md`](contours.md) et [`recherche-contours.md`](recherche-contours.md).

---

## Lot 1 — Modèle

### T4. `jour_de_saison` dans `risque_journalier`

Second axe temporel. Calculé par massif **et** par saison depuis le premier `jour_validite` du
couple, pas depuis une date calendaire commune.

**Fait quand** : la colonne existe dans la vue ; un test vérifie qu'un massif ouvrant tardivement
démarre bien à 1 et non à un décalage calendaire ; la documentation du champ est ajoutée au
glossaire.

**Dépend de** : rien.

### T5. Tranches d'altitude normées

Vue dérivée rattachant chaque palier d'enneigement, de vent et de neige fraîche à l'une des trois
tranches fixes (< 1800 m, 1800–2400 m, > 2400 m), par appartenance directe de l'altitude du
palier. Une tranche sans palier reste nulle — **ne pas interpoler**.

**Bornes arrêtées** (6 octobre 2026, au vu de T2) : fermées à gauche, la tranche haute est
**≥ 2400 m** et non « > 2400 m » — voir spec § 4.2.

**Fait quand** : la vue existe ; un test couvre un massif dont les paliers tombent tous dans une
seule tranche ; la part de couples massif × saison dans ce cas est publiée, parce qu'elle borne la
validité des comparaisons entre massifs.

**Dépend de** : T2 (distribution des altitudes de référence).

---

## Lot 2 — Couche métriques

Un bloc par tâche, dans cet ordre : le risque d'abord, parce qu'il est le socle et qu'il se
vérifie à la main contre quelques bulletins PDF.

### T6. Bloc risque

Les métriques de la spec § 5.1. Deux pièges à traiter explicitement, pas à découvrir :

- un trou d'archive **rompt** un épisode, et le nombre d'épisodes rompus par un trou est publié à
  côté du compte ;
- une variation ne se calcule qu'entre deux jours réellement consécutifs.

Ne pas implémenter « indices naturel et accidentel » : ce sont des textes, pas des indices.

**Fait quand** : chaque métrique est testée sur une fixture ; les comptes d'un massif et d'une
saison sont vérifiés à la main contre les bulletins PDF correspondants ; toute moyenne renvoyée
est accompagnée du nombre de jours couverts ; les comparaisons inter-saisons refusent de
s'exécuter hors fenêtre `coeur` plutôt que de renvoyer un chiffre faux.

**Dépend de** : T2, T4.

### T7. Bloc enneigement

Métriques de la spec § 5.2, avec la règle de déduplication de la neige fraîche : un même jour
apparaît dans le bloc historique de plusieurs bulletins, on retient la rédaction la plus tardive,
et chaque ligne écartée est journalisée.

**Fait quand** : la déduplication est testée sur un jour couvert par plusieurs bulletins ; les
métriques sont calculées par tranche normée ; aucune sortie ne présente l'enneigement comme une
mesure.

**Dépend de** : T2, T5.

**Règles de parsing arrêtées le 15 octobre 2026** (glossaire § 4 et § 5) : secteurs de neige
fraîche d'avant 2024 conservés et bornes dérivées, `-2` lu comme non observé, relevés vides et
limites `-1` convertis avec l'indicateur `sans_enneigement_continu_*`. La rupture de série de
l'hiver 2023-2024 sur la neige fraîche est à annoncer par toute métrique qui l'enjambe.

### T8. Bloc météo

Métriques de la spec § 5.3. Commencer par trancher la convention d'extraction (§ 4.3) à la lumière
de T2, et la journaliser.

Les deux métriques à soigner sont l'indice de transport de neige par le vent et les épisodes de
redoux : ce sont les seules que l'utilisateur ne peut pas calculer de tête.

**Fait quand** : la convention retenue est documentée dans le glossaire avec sa justification ;
les séries ne mélangent jamais deux horizons de prévision ; les seuils sont paramétrables et leurs
valeurs par défaut justifiées par les distributions de T2.

**Dépend de** : T2, T5.

**Convention arrêtée le 15 octobre 2026** (spec § 4.3, glossaire § 3) : prévision seule, valeur
du jour sur les échéances de 06 h et 12 h ; vent lu par altitude ou tranche ; échéances vides et
`ALTITUDEVENT2="9999"` convertis au parsing ; vents hors [0, 300] km/h signalés par `bra check`
et exclus des métriques. Reste à construire la vue journalière et les métriques.

### T9. Bloc rose des pentes et situations typiques

Métriques de la spec § 5.4. `sat1` / `sat2` sont restreints à 2024+ et étiquetés comme tels.

**Fait quand** : les fréquences sont calculées par tranche d'altitude ; une sortie toutes altitudes
confondues est impossible par construction ; les codes `sat` sont traduits par leurs libellés du
glossaire.

**Dépend de** : T2, T5.

### T10. Score composite versionné

Pondération entre risque, enneigement et vent, fixée sur les distributions de T2. La version du
score est stockée avec la valeur.

**Fait quand** : la formule et sa version sont exposées par l'API de la couche métriques, de sorte
que l'interface puisse les afficher sans les recopier ; un changement de pondération change la
version.

**Dépend de** : T6, T7, T8.

---

## Lot 3 — Écrans

### T11. Fiche massif-saison

L'écran central, et celui qui existe déjà en germe dans `bra dashboard` : l'étendre plutôt que le
réécrire. Indicateurs clés, série du risque sur fond des autres saisons avec bande médiane et
interquartile, puis enneigement, ISO 0 et vent sur le même axe aligné.

**Fait quand** : un massif et une saison se lisent de bout en bout sans requête manuelle ; le
basculement entre axe calendaire et `jour_de_saison` fonctionne ; la couverture de données est
visible sur chaque graphe ; la page reste autonome, sans serveur.

**Dépend de** : T6, T7, T8.

### T12. Carte d'accueil

36 massifs colorés par la moyenne `coeur` sur les saisons comparables, une valeur par massif, sans
sélecteur de saison. Survol : jours couverts et jours de risque 4 ou 5. Sélecteur de métrique
simple en complément.

**Fait quand** : le libellé dit explicitement « neuf saisons comparables sur onze » plutôt que
« dix ans » ; la moyenne n'est jamais affichée sans son repère de survol ; les massifs non
diffusés sur la période sont distingués des massifs à zéro.

**Dépend de** : T1, T3, T6.

### T13. Écran de comparaison

Les trois modes de la spec § 6, plus le classement des saisons en barres horizontales. Sélecteur
bridé à quatre courbes superposées.

**Fait quand** : la troncature à période égale est appliquée par défaut et annoncée dans le
sous-titre ; le classement refuse une métrique d'indice hors fenêtre `coeur` ; une saison non
comparable apparaît étiquetée et non supprimée.

**Dépend de** : T6, T11.

### T14. Écran d'exploration

Rose des pentes, rose des vents, matrice altitude × orientation. Comparaison par roses côte à
côte ou barres par secteur, jamais par superposition.

**Fait quand** : chaque rose porte sa tranche d'altitude ; la matrice 8 × 3 est lisible ; les
situations typiques sont affichées avec leur restriction d'époque.

**Dépend de** : T9, T11.

---

## Lot 4 — Finitions

### T15. Exports, état partageable et attribution

- Export CSV des données et PNG de l'image sur chaque graphe.
- État complet des filtres dans l'URL ; aucune réinitialisation entre écrans.
- Attribution « données Météo-France, Licence Ouverte 2.0 » et date de l'archive intégrée,
  visibles sur chaque page ; sur la carte, attribution des contours en plus (spec § 7).

**Fait quand** : une URL collée dans un autre navigateur reproduit exactement le même écran ;
chaque graphe exporte les données qui le composent, pas une reconstruction ; l'attribution est
présente sur les quatre écrans.

**Dépend de** : T11 à T14.

---

## Ce qui reste volontairement hors de cette liste

L'alerting mail, l'API publique, le temps réel, les sources externes (observations de stations,
AROME, SAFRAN/CROCUS), l'extraction NLP du texte libre, les sous-massifs.

Le piège à éviter est de construire les 36 massifs et les quatre écrans avant d'avoir vérifié que
les champs existent sur toute la période. T2 est la seule tâche qui peut invalider la moitié de la
spec, donc elle passe avant tout le reste.
