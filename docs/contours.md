# Contours des massifs

Donnée de référence de la carte d'accueil (tâche T3). La recherche qui a conduit à ce choix,
sources citées, est dans [`recherche-contours.md`](recherche-contours.md).

## Source retenue

| | |
|---|---|
| Producteur | **Météo-France** |
| Jeu de données | [Archive des Bulletins Avalanches](https://www.data.gouv.fr/datasets/archive-des-bulletins-avalanches), data.gouv.fr — celui-là même dont le repo ingère le XML |
| Ressource | `DONNEES_EXPERTISEES_Metadata_massifs.geojson` (« Définition des massifs existants dans le bulletin risque avalanche ») |
| URL figée | `https://static.data.gouv.fr/resources/archive-des-bulletins-avalanches/20260805-132200/donnees-expertisees-metadata-massifs-20240215.geojson` |
| Version | `Metadata_massif_DP_2024`, fichier daté du 15/02/2024, déposé le 05/08/2026 |
| Empreintes | sha256 `0300ea206b0eaa70dbef5182540dbb2d60e2db80cc52e543dbfd2f023758a882` ; sha1 `e623ac5e42ac83c595c40cd520b7de3740f47de5`, conforme au checksum déclaré par data.gouv.fr |
| Licence | **Licence Ouverte 2.0** (`lov2`), vérifiée le 06/10/2026 sur l'API `data.gouv.fr/api/1/datasets/archive-des-bulletins-avalanches/` |
| Copie versionnée | [`src/bra_analytics/geo/massifs_meteofrance_20240215.geojson`](../src/bra_analytics/geo/massifs_meteofrance_20240215.geojson), octets identiques au fichier source |

L'URL est épinglée sur le chemin horodaté et non sur l'URL « dernière version »
(`/api/1/datasets/r/7c7bc2d5-…`), qui suivra les remplacements : un découpage qui change sous les
pieds de l'interface décale les couleurs sans rien signaler.

## Raccordement

La propriété entière `code` **est** le `massif_id` du BRA : aucune table de correspondance.
`bra contours` le vérifie à chaque exécution et sort en erreur au moindre écart.

```
contours : 36 entites
  raccordement complet : 36 massifs, aucun contour en trop
```

Andorre (71) a son contour, bien que le massif ne soit plus diffusé en 2025-2026 : la carte doit
le montrer « non diffusé sur la période », pas l'effacer.

## Version web

`uv run bra contours` écrit [`src/bra_analytics/geo/massifs.web.geojson`](../src/bra_analytics/geo/massifs.web.geojson) :

- Douglas-Peucker à 0,001° (~100 m), coordonnées arrondies à 4 décimales (~10 m) ;
- 2 710 → 1 983 sommets, 60 Ko → 36 Ko ;
- seule la propriété `code` est conservée : les libellés viennent de `massifs.py`, qui fait foi.

Ce fichier généré est **versionné, par exception** à la règle qui écarte les pages HTML générées :
la page le charge sans réseau, et il ne dépend que du fichier d'origine — pas de l'entrepôt. Un
test (`test_version_web_versionnee_a_jour`) vérifie qu'il reste exactement ce que
`bra contours` produit : toute dérive fait échouer `pytest`.

La topologie entre massifs voisins n'est pas préservée : à cette tolérance, de fins interstices
peuvent séparer deux massifs. C'est acceptable pour une carte choroplèthe ; une tolérance plus
forte ne le serait plus.

## Contour de la France (fond de carte)

La carte dessine la silhouette de la France métropolitaine sous les massifs, pour les situer dans le
pays. Elle ne porte aucune donnée : jamais colorée, hors de toute interaction.

| | |
|---|---|
| Producteur | **IGN**, Admin Express (édition 2018), tracés simplifiés par [`gregoiredavid/france-geojson`](https://github.com/gregoiredavid/france-geojson) |
| Fichier | `metropole.geojson`, dernier commit `45daa2d069a8da3ec4efb6672388fc3dc02e36e2` (01/08/2018) |
| Empreinte | sha256 `d1f4aec3fbc274d4af3f5930302a342d3efe0ea1daf410fbeef535346167bf0c` |
| Licence | « Licence ouverte » d'Admin Express, telle que citée par le dépôt source (lien Etalab ; le dépôt n'a pas de fichier LICENSE). Version de la licence non précisée par le dépôt (le lien date de l'ère de la v1.0) : **non vérifiée à la source IGN**, à confirmer avant toute redistribution du fichier |
| Copie versionnée | `src/bra_analytics/geo/france_metropole_ign2018.geojson`, octets identiques au fichier source (600 Ko) |
| Version web | `src/bra_analytics/geo/france.web.geojson`, produite par `bra contours` : Douglas-Peucker à 0,01° (~1 km), 3 décimales, 600 Ko → 36 Ko |

Un test (`test_contour_de_la_france_versionne_a_jour_et_couvre_les_massifs`) vérifie que la version web
reste ce que `bra contours` produit et que les massifs tiennent dans l'emprise du pays. Le tracé est
celui de 2018 et très simplifié : suffisant pour un fond, pas pour un calcul. La frontière terrestre
avec l'Andorre et l'Espagne n'a pas de relation topologique avec les contours des massifs (sources
différentes) : de légers décalages sont attendus aux frontières.

## Attribution

La Licence Ouverte 2.0 impose de mentionner la source et la date de dernière mise à jour. Sur la
carte : **« Contours des massifs : Météo-France, Licence Ouverte 2.0 (version du 15/02/2024) »**,
à côté de l'attribution des données BRA (spec § 7), complétée de « contour de la France : IGN Admin Express 2018, Licence Ouverte ».

## Alternative écartée : micro-régions EAWS

Les [micro-régions EAWS](https://gitlab.com/eaws/eaws-regions), envisagées en premier, sont sous
**CC0 1.0** — la crainte d'une licence non affichée était infondée — et décrivent le même découpage,
retouché aux frontières (surfaces à ±6 %, centroïdes à moins de 0,8 km). Elles ont été écartées
pour deux raisons :

- **pas de contour pour le massif 71** (Andorre), dans aucune version du fichier ;
- identifiants `FR-01` … `FR-74` sur deux chiffres, à raccorder par `f"FR-{id:02d}"`, là où le
  fichier Météo-France porte l'entier.

Version de référence si elles devaient être reprises : commit `9f630cb1…` (tag `v8.5.0`), sha256
`87e0c5b1e498c7fe328b46296a854ff991ea67de7fae9be288ecb0ec225da0b0`.
