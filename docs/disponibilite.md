# Disponibilité des champs, saison par saison

Document **généré** par `uv run bra audit` (tâche T2 de [`taches.md`](taches.md)). Ne pas l'éditer à la main : le relancer après tout `bra build`.

Il répond à une question préalable à toute métrique de la [spec](spec-interface.md) : le champ dont elle dépend existe-t-il sur toute la période ? Le format XML a changé six fois, et plusieurs blocs sont propres à une époque.

## Périmètre mesuré

- Dernier jour couvert intégré : **2026-06-08**.
- 77487 bulletins mesurés (`bulletins` après déduplication, `massif_coherent`). **1** ligne(s) écartée(s) parce que leur `ID` et leur libellé se contredisent — voir `bra info`.
- Les tables filles sont restreintes aux bulletins retenus, par leur clé.
- Une part se lit en % des lignes de la table pour la saison, et ne compte que les valeurs **exploitables** : ni nulles, ni `-1` (sentinelle de la source), ni porteuses d'un autre sens que celui du champ (§ 9). `0` = jamais exploitable, `100` = toujours, `—` = table vide cette saison-là. Une part non nulle s'affiche au moins à 0,1 %, pour qu'une présence rare ne passe pas pour une absence.

| saison | bulletins | massifs | zones |
|---|---|---|---|
| 2015-2016 | 1301 | 35 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2016-2017 | 7773 | 35 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2017-2018 | 7750 | 35 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2018-2019 | 8003 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2019-2020 | 5864 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2020-2021 | 7835 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2021-2022 | 7952 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2022-2023 | 7772 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2023-2024 | 7931 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2024-2025 | 7698 | 36 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |
| 2025-2026 | 7608 | 35 | Alpes du Nord, Alpes du Sud, Corse, Pyrenees |

## 1. Statut des métriques de la spec (§ 5)

Le statut est **dérivé** de la disponibilité mesurée plus bas, pas écrit à la main : chaque métrique est déclarée une fois dans `audit.py` avec les champs qu'elle lit.

- **calculable** : tous ses champs sont présents sur toutes les saisons ;
- **sous-ensemble** : sur une partie des saisons seulement, listées ;
- **non calculable** : aucune saison ne les réunit, ou la métrique attend un indice chiffré d'un champ texte.

« Présent » veut dire au moins une valeur exploitable dans la saison : un champ rare par nature (`sat2`, `altitude_seuil_m`) n'est pas un champ absent. La densité se lit dans les matrices du § 2. *Calculable* ne veut pas dire *comparable* : les règles de fenêtre (`coeur`, saisons comparables) s'appliquent en plus.

| bloc | métrique | statut | saisons | motif |
|---|---|---|---|---|
| risque | Risque du jour | **calculable** |  | — |
| risque | Jours ≥ 3 / ≥ 4 / = 5 | **calculable** |  | — |
| risque | Part de jours par niveau | **calculable** |  | — |
| risque | Risque moyen | **calculable** |  | — |
| risque | Risque médian | **calculable** |  | — |
| risque | Maximum saisonnier | **calculable** |  | — |
| risque | Première / dernière occurrence ≥ 3 | **calculable** |  | — |
| risque | Durée de saison BRA | **calculable** |  | — |
| risque | Épisodes ≥ 3 | **calculable** |  | — |
| risque | Variations | **calculable** |  | — |
| risque | Écart à la normale | **calculable** |  | — |
| risque | Second indice | **calculable** |  | — |
| risque | Indices naturel et accidentel | **non calculable** |  | champ texte rédigé, pas un indice chiffré : bulletins.naturel, bulletins.accidentel |
| enneigement | Limite d'enneigement | **calculable** |  | — |
| enneigement | Épaisseur par tranche | **calculable** |  | — |
| enneigement | Date d'enneigement continu | **calculable** |  | — |
| enneigement | Durée d'enneigement | **calculable** |  | — |
| enneigement | Maximum saisonnier d'épaisseur | **calculable** |  | — |
| enneigement | Neige fraîche cumulée | **sous-ensemble** | 2023-2024 → 2025-2026 | absent sur une partie des saisons : neige_fraiche.cumul_max_cm (avant 2024, SS242 est le cumul d'un second secteur, pas un maximum) |
| enneigement | Épisodes de chute | **sous-ensemble** | 2023-2024 → 2025-2026 | absent sur une partie des saisons : neige_fraiche.cumul_max_cm (avant 2024, SS242 est le cumul d'un second secteur, pas un maximum) |
| enneigement | Anomalie d'enneigement | **calculable** |  | — |
| meteo | Isotherme 0 °C | **calculable** |  | — |
| meteo | ISO 0 min / max / moyen | **calculable** |  | — |
| meteo | Jours ISO 0 > seuil | **calculable** |  | — |
| meteo | Amplitude ISO 0 en 24 h | **calculable** |  | — |
| meteo | Vitesse et direction de vent | **calculable** |  | — |
| meteo | Jours de vent fort | **calculable** |  | — |
| meteo | Limite pluie / neige | **calculable** |  | — |
| meteo | Temps sensible | **calculable** |  | — |
| meteo | Indice de transport par le vent | **sous-ensemble** | 2023-2024 → 2025-2026 | absent sur une partie des saisons : neige_fraiche.cumul_max_cm (avant 2024, SS242 est le cumul d'un second secteur, pas un maximum) |
| meteo | Épisodes de redoux | **calculable** |  | — |
| rose | Fréquence d'exposition | **calculable** |  | — |
| rose | Fréquence pondérée | **calculable** |  | — |
| rose | Secteur dominant | **calculable** |  | — |
| rose | Concentration | **calculable** |  | — |
| rose | Saisonnalité | **calculable** |  | — |
| rose | Croisement vent × orientation | **calculable** |  | — |
| rose | Situations typiques | **sous-ensemble** | 2023-2024 → 2025-2026 | absent sur une partie des saisons : bulletins.sat1 |
| score | Score composite | **calculable** |  | — |

## 2. Part de valeurs exploitables, champ × saison (%)

Champs comptés à 0 sur une famille de format parce qu'ils y portent autre chose que ce que leur nom annonce :

- `neige_fraiche.cumul_min_cm` (famille `legacy`) : avant 2024, SS241 est le cumul du premier secteur, pas un minimum.
- `neige_fraiche.cumul_max_cm` (famille `legacy`) : avant 2024, SS242 est le cumul d'un second secteur, pas un maximum.

### `bulletins`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `jour_bulletin` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `jour_validite` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `massif_nom` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `zone` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `massif_nom_source` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `massif_coherent` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `type_bulletin` | 0 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `producteur` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 0 | 0 | 0 |
| `amendement` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `date_diffusion` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `date_echeance` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `date_validite` | 0 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `risque1` | 100 | 61,4 | 61,5 | 60,3 | 59,7 | 62,3 | 100 | 100 | 99,9 | 99,9 | 100 |
| `risque1_evolution` | 33,1 | 12,6 | 13,2 | 12,1 | 9,7 | 10,1 | 11,7 | 7,9 | 10,4 | 13,2 | 11,7 |
| `risque2` | 27,1 | 25,3 | 24,3 | 22,7 | 18,9 | 35,1 | 38,4 | 47,6 | 46,1 | 47,3 | 51,1 |
| `risque2_evolution` | 2,0 | 1,5 | 1,9 | 0,9 | 1,5 | 0,9 | 5,2 | 4,7 | 3,0 | 2,2 | 3,5 |
| `risque_maxi` | 100 | 61,4 | 61,5 | 60,4 | 59,8 | 62,3 | 100 | 100 | 100 | 99,9 | 100 |
| `loc_type` | 27,1 | 25,3 | 24,3 | 22,8 | 18,9 | 35,1 | 38,4 | 47,6 | 46,1 | 47,3 | 51,1 |
| `altitude_seuil_m` | 26,1 | 24,7 | 23,7 | 22,2 | 18,1 | 34,7 | 36,9 | 46,3 | 44,4 | 46,5 | 50,5 |
| `loc1_secteur` | 1,1 | 0,6 | 0,5 | 0,6 | 0,8 | 0,4 | 1,5 | 1,4 | 1,8 | 0,8 | 0,6 |
| `loc2_secteur` | 1,1 | 0,6 | 0,5 | 0,6 | 0,8 | 0,4 | 1,5 | 1,4 | 1,8 | 0,8 | 0,6 |
| `risque_estime` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `risque_commentaire` | 99,0 | 98,1 | 98,8 | 98,4 | 97,1 | 99,0 | 97,9 | 97,0 | 100 | 99,9 | 100 |
| `risque_maxi_j2` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 99,9 | 99,9 | 99,9 |
| `date_risque_j2` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 | 100 | 100 |
| `risque_j2_libelle` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 99,9 | 100 | 100 |
| `risque_j2_commentaire` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 | 99,9 | 100 |
| `pente_n` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_ne` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_e` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_se` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_s` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_sw` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_w` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_nw` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `pente_commentaire` | 14,0 | 49,8 | 48,7 | 50,0 | 52,1 | 52,6 | 15,6 | 17,3 | 19,8 | 23,4 | 20,2 |
| `resume` | 0 | 99,9 | 99,9 | 100 | 100 | 99,9 | 100 | 100 | 100 | 100 | 100 |
| `accidentel` | 100 | 61,4 | 61,5 | 60,3 | 59,7 | 62,3 | 100 | 100 | 100 | 99,9 | 100 |
| `naturel` | 100 | 61,4 | 61,5 | 60,3 | 59,7 | 62,3 | 100 | 100 | 100 | 99,9 | 100 |
| `avis` | 0,3 | 3,5 | 8,8 | 2,7 | 5,3 | 3,6 | 4,1 | 2,8 | 3,4 | 2,8 | 7,4 |
| `vigilance` | 0,3 | 2,4 | 5,9 | 2,0 | 3,8 | 2,3 | 3,4 | 1,7 | 0 | 0,5 | 1,3 |
| `stabilite_titre` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 98,7 | 98,6 |
| `stabilite_texte` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 99,9 | 100 |
| `qualite_texte` | 99,5 | 87,5 | 86,8 | 87,2 | 81,3 | 87,2 | 99,0 | 99,4 | 100 | 99,9 | 100 |
| `meteo_commentaire` | 15,8 | 17,2 | 17,1 | 17,9 | 33,5 | 33,1 | 33,8 | 40,8 | 98,1 | 94,0 | 95,9 |
| `sat1` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 100 | 99,9 | 100 |
| `sat2` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 59,4 | 59,8 | 61,7 |
| `enneigement_limite_nord_m` | 99,5 | 98,4 | 98,5 | 99,1 | 98,3 | 97,2 | 96,3 | 97,4 | 98,9 | 97,2 | 99,0 |
| `enneigement_limite_sud_m` | 97,9 | 94,4 | 97,5 | 97,9 | 97,0 | 95,4 | 93,3 | 94,7 | 96,4 | 94,6 | 97,4 |
| `vent_altitude_basse_m` | 100 | 100 | 99,9 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `vent_altitude_haute_m` | 100 | 100 | 99,9 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `schema_version` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `format_famille` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |

### `meteo`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `origine` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `rang` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `echeance` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `vent_bas_vitesse_kmh` | 99,8 | 99,2 | 98,4 | 98,5 | 96,2 | 99,1 | 98,4 | 97,5 | 99,0 | 99,7 | 99,5 |
| `vent_bas_direction` | 99,8 | 99,2 | 98,4 | 98,3 | 96,1 | 99,1 | 98,3 | 97,5 | 98,9 | 99,7 | 99,5 |
| `vent_haut_vitesse_kmh` | 77,1 | 76,2 | 76,7 | 73,7 | 70,8 | 74,4 | 73,8 | 73,2 | 99,0 | 99,7 | 99,5 |
| `vent_haut_direction` | 77,1 | 76,2 | 76,7 | 73,6 | 70,7 | 74,4 | 73,8 | 73,2 | 99,0 | 99,7 | 99,5 |
| `iso_0_m` | 99,8 | 99,2 | 98,4 | 98,5 | 96,7 | 99,2 | 98,5 | 97,8 | 99,0 | 99,7 | 99,5 |
| `iso_moins10_m` | 0 | 99,0 | 97,9 | 98,0 | 96,3 | 98,6 | 98,0 | 96,7 | 0 | 0 | 0 |
| `limite_pluie_neige_m` | 26,8 | 19,0 | 31,2 | 21,5 | 25,4 | 26,5 | 21,5 | 26,9 | 32,8 | 28,7 | 28,2 |
| `temps_sensible` | 99,8 | 99,2 | 98,4 | 98,5 | 96,7 | 99,1 | 98,5 | 97,8 | 99,0 | 99,7 | 99,5 |
| `temps_sensible_libelle` | 64,3 | 72,5 | 59,3 | 68,4 | 64,4 | 64,8 | 69,4 | 65,2 | 99,0 | 99,7 | 95,8 |
| `mer_nuages_m` | 0,9 | 1,2 | 2,1 | 1,4 | 1,1 | 1,6 | 2,1 | 2,6 | 0,1 | 0,2 | 0,1 |

### `enneigement`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `origine` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `date_enneigement` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `limite_nord_m` | 99,5 | 98,5 | 98,1 | 98,9 | 97,9 | 97,5 | 96,5 | 97,4 | 99,2 | 98,3 | 98,8 |
| `limite_sud_m` | 97,9 | 94,9 | 96,9 | 97,8 | 96,6 | 95,8 | 93,6 | 94,6 | 98,8 | 98,0 | 98,6 |
| `altitude_m` | 99,5 | 99,6 | 99,6 | 99,5 | 99,5 | 99,7 | 99,4 | 99,6 | 100 | 100 | 100 |
| `epaisseur_nord_cm` | 99,5 | 99,6 | 99,6 | 99,5 | 99,5 | 99,7 | 99,4 | 99,6 | 99,3 | 98,7 | 98,9 |
| `epaisseur_sud_cm` | 99,5 | 99,6 | 99,6 | 99,5 | 99,5 | 99,7 | 99,4 | 99,6 | 99,3 | 98,7 | 98,9 |

### `neige_fraiche`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `origine` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `date_cumul` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `altitude_mesure_m` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `cumul_min_cm` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 99,8 | 99,8 | 99,6 |
| `cumul_max_cm` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 99,8 | 99,8 | 99,6 |

### `historique_risque`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `date_risque` | — | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| `risque_maxi` | — | 65,1 | 62,0 | 61,5 | 60,7 | 63,7 | 97,9 | 98,7 | 98,2 | 97,5 | 98,6 |

### `tendances`

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `date_tendance` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | — | — | — |
| `valeur` | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | — | — | — |

## 3. Localisation du risque : `loc_type`

Décide du périmètre de la vue experte sur le second indice (spec § 3.1). `NULL` = indice unique, aucune information d'altitude.

| saison | bulletins | NULL | altitude | orientation | % avec distinction |
|---|---|---|---|---|---|
| 2015-2016 | 1301 | 948 | 339 | 14 | 27,1 |
| 2016-2017 | 7773 | 5804 | 1920 | 49 | 25,3 |
| 2017-2018 | 7750 | 5870 | 1840 | 40 | 24,3 |
| 2018-2019 | 8003 | 6179 | 1777 | 47 | 22,8 |
| 2019-2020 | 5864 | 4755 | 1063 | 46 | 18,9 |
| 2020-2021 | 7835 | 5083 | 2721 | 31 | 35,1 |
| 2021-2022 | 7952 | 4897 | 2936 | 119 | 38,4 |
| 2022-2023 | 7772 | 4071 | 3595 | 106 | 47,6 |
| 2023-2024 | 7931 | 4274 | 3518 | 139 | 46,1 |
| 2024-2025 | 7698 | 4056 | 3578 | 64 | 47,3 |
| 2025-2026 | 7608 | 3721 | 3844 | 43 | 51,1 |

Distribution de `altitude_seuil_m` quand `loc_type = 'altitude'` :

| altitude_seuil_m | bulletins |
|---|---|
| 0 | 4 |
| 1300 | 6 |
| 1400 | 11 |
| 1500 | 81 |
| 1600 | 151 |
| 1700 | 244 |
| 1800 | 2136 |
| 1900 | 316 |
| 2000 | 5395 |
| 2100 | 1267 |
| 2200 | 5445 |
| 2300 | 2827 |
| 2400 | 3502 |
| 2500 | 2388 |
| 2600 | 948 |
| 2700 | 716 |
| 2800 | 641 |
| 2900 | 45 |
| 3000 | 668 |
| 3100 | 36 |
| 3200 | 184 |
| 3300 | 40 |
| 3400 | 47 |
| 3500 | 26 |
| 3600 | 6 |
| 4000 | 1 |

## 4. Altitudes de référence par massif

Elles fondent les tranches normées (< 1800 m, 1800–2400 m, ≥ 2400 m, spec § 4.2 ; § 10 ci-dessous). Une ligne par jeu d'altitudes distinct ; les saisons qui le partagent sont regroupées. Sources : `enneigement.altitude_m` (paliers d'épaisseur), `neige_fraiche.altitude_mesure_m`, `bulletins.vent_altitude_basse_m` / `vent_altitude_haute_m`.

| massif | nom | source | altitudes (m) | saisons |
|---|---|---|---|---|
| 1 | Chablais | enneigement | -1/1000/1500/2000 | 2015-2016 → 2022-2023 |
| 1 | Chablais | enneigement | 1000/1500/2000 | 2023-2024 → 2025-2026 |
| 1 | Chablais | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 1 | Chablais | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 1 | Chablais | vent_haut | 2500 | 2015-2016 → 2025-2026 |
| 2 | Aravis | enneigement | -1/1000/1500/2000 | 2015-2016 → 2022-2023 |
| 2 | Aravis | enneigement | 1000/1500/2000 | 2023-2024 → 2025-2026 |
| 2 | Aravis | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 2 | Aravis | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 2 | Aravis | vent_haut | 2500 | 2015-2016 → 2025-2026 |
| 3 | Mont-Blanc | enneigement | -1/1500/2000/2500 | 2015-2016 → 2022-2023 |
| 3 | Mont-Blanc | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 3 | Mont-Blanc | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 3 | Mont-Blanc | vent_bas | 2000 | 2015-2016 → 2023-2024, 2025-2026 |
| 3 | Mont-Blanc | vent_bas | 2000/3000 | 2024-2025 |
| 3 | Mont-Blanc | vent_haut | 3000 | 2016-2017 → 2023-2024 |
| 3 | Mont-Blanc | vent_haut | 3000/4000 | 2024-2025 |
| 3 | Mont-Blanc | vent_haut | 4000 | 2015-2016, 2025-2026 |
| 4 | Bauges | enneigement | -1/1000/1500/2000 | 2021-2022 → 2022-2023 |
| 4 | Bauges | enneigement | -1/1500/1800/2100 | 2016-2017 → 2020-2021 |
| 4 | Bauges | enneigement | 1000/1500/2000 | 2023-2024 → 2025-2026 |
| 4 | Bauges | enneigement | 1500/1800/2100 | 2015-2016 |
| 4 | Bauges | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 4 | Bauges | neige_fraiche | 1800/2500 | 2016-2017 |
| 4 | Bauges | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 4 | Bauges | vent_haut | 2000 | 2015-2016 → 2025-2026 |
| 5 | Beaufortain | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 5 | Beaufortain | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 5 | Beaufortain | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 5 | Beaufortain | neige_fraiche | 1800/2500 | 2016-2017 |
| 5 | Beaufortain | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 5 | Beaufortain | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 6 | Haute-Tarentaise | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 6 | Haute-Tarentaise | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 6 | Haute-Tarentaise | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 6 | Haute-Tarentaise | neige_fraiche | 1800/2500 | 2016-2017 |
| 6 | Haute-Tarentaise | vent_bas | 2500 | 2025-2026 |
| 6 | Haute-Tarentaise | vent_bas | 2500/3000 | 2024-2025 |
| 6 | Haute-Tarentaise | vent_bas | 3000 | 2015-2016 → 2023-2024 |
| 6 | Haute-Tarentaise | vent_haut | 3500 | 2025-2026 |
| 6 | Haute-Tarentaise | vent_haut | 3500/4000 | 2024-2025 |
| 6 | Haute-Tarentaise | vent_haut | 4000 | 2015-2016 → 2023-2024 |
| 7 | Chartreuse | enneigement | -1/1000/1500/2000 | 2016-2017 → 2022-2023 |
| 7 | Chartreuse | enneigement | 1000/1500/2000 | 2015-2016, 2023-2024 → 2025-2026 |
| 7 | Chartreuse | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 7 | Chartreuse | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 7 | Chartreuse | vent_haut | 2000 | 2015-2016 → 2025-2026 |
| 8 | Belledonne | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 8 | Belledonne | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 8 | Belledonne | neige_fraiche | 1800 | 2017-2018 → 2025-2026 |
| 8 | Belledonne | neige_fraiche | 1800/2500 | 2015-2016 |
| 8 | Belledonne | neige_fraiche | 1800/3000 | 2016-2017 |
| 8 | Belledonne | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 8 | Belledonne | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 9 | Maurienne | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 9 | Maurienne | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 9 | Maurienne | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 9 | Maurienne | neige_fraiche | 1800/2500 | 2016-2017 |
| 9 | Maurienne | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 9 | Maurienne | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 10 | Vanoise | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 10 | Vanoise | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 10 | Vanoise | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 10 | Vanoise | neige_fraiche | 1800/2500 | 2016-2017 |
| 10 | Vanoise | vent_bas | 2500 | 2025-2026 |
| 10 | Vanoise | vent_bas | 2500/3000 | 2024-2025 |
| 10 | Vanoise | vent_bas | 3000 | 2015-2016 → 2023-2024 |
| 10 | Vanoise | vent_haut | 3500 | 2025-2026 |
| 10 | Vanoise | vent_haut | 3500/4000 | 2024-2025 |
| 10 | Vanoise | vent_haut | 4000 | 2015-2016 → 2023-2024 |
| 11 | Haute-Maurienne | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 11 | Haute-Maurienne | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 11 | Haute-Maurienne | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2025-2026 |
| 11 | Haute-Maurienne | neige_fraiche | 1800/2500 | 2016-2017 |
| 11 | Haute-Maurienne | vent_bas | 2500 | 2025-2026 |
| 11 | Haute-Maurienne | vent_bas | 2500/3000 | 2024-2025 |
| 11 | Haute-Maurienne | vent_bas | 3000 | 2015-2016 → 2023-2024 |
| 11 | Haute-Maurienne | vent_haut | 3500 | 2025-2026 |
| 11 | Haute-Maurienne | vent_haut | 3500/4000 | 2024-2025 |
| 11 | Haute-Maurienne | vent_haut | 4000 | 2015-2016 → 2023-2024 |
| 12 | Grandes-Rousses | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 12 | Grandes-Rousses | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 12 | Grandes-Rousses | neige_fraiche | 1800 | 2017-2018 → 2025-2026 |
| 12 | Grandes-Rousses | neige_fraiche | 1800/2500 | 2015-2016 |
| 12 | Grandes-Rousses | neige_fraiche | 1800/3000 | 2016-2017 |
| 12 | Grandes-Rousses | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 12 | Grandes-Rousses | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 13 | Thabor | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 13 | Thabor | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 13 | Thabor | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 13 | Thabor | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 13 | Thabor | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 13 | Thabor | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 13 | Thabor | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 13 | Thabor | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 14 | Vercors | enneigement | -1/1000/1500/2000 | 2016-2017 → 2022-2023 |
| 14 | Vercors | enneigement | 1000/1500/2000 | 2015-2016, 2023-2024 → 2025-2026 |
| 14 | Vercors | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 14 | Vercors | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 14 | Vercors | vent_haut | 2000 | 2015-2016 → 2025-2026 |
| 15 | Oisans | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 15 | Oisans | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 15 | Oisans | neige_fraiche | 1800 | 2017-2018 → 2025-2026 |
| 15 | Oisans | neige_fraiche | 1800/2500 | 2015-2016 |
| 15 | Oisans | neige_fraiche | 1800/2500/3000 | 2016-2017 |
| 15 | Oisans | vent_bas | 2000/2500 | 2019-2020 |
| 15 | Oisans | vent_bas | 2500 | 2015-2016 → 2018-2019, 2020-2021 → 2025-2026 |
| 15 | Oisans | vent_haut | 3000/3500 | 2019-2020 |
| 15 | Oisans | vent_haut | 3500 | 2015-2016 → 2018-2019, 2020-2021 → 2025-2026 |
| 16 | Pelvoux | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 16 | Pelvoux | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 16 | Pelvoux | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 16 | Pelvoux | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 16 | Pelvoux | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 16 | Pelvoux | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 16 | Pelvoux | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 16 | Pelvoux | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 17 | Queyras | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 17 | Queyras | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 17 | Queyras | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 17 | Queyras | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 17 | Queyras | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 17 | Queyras | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 17 | Queyras | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 17 | Queyras | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 18 | Devoluy | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 18 | Devoluy | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 18 | Devoluy | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 18 | Devoluy | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 18 | Devoluy | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 18 | Devoluy | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 18 | Devoluy | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 18 | Devoluy | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 19 | Champsaur | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 19 | Champsaur | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 19 | Champsaur | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 19 | Champsaur | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 19 | Champsaur | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 19 | Champsaur | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 19 | Champsaur | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 19 | Champsaur | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 20 | Embrunais Parpaillon | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 20 | Embrunais Parpaillon | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 20 | Embrunais Parpaillon | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 20 | Embrunais Parpaillon | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 20 | Embrunais Parpaillon | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 20 | Embrunais Parpaillon | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 20 | Embrunais Parpaillon | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 20 | Embrunais Parpaillon | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 21 | Ubaye | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 21 | Ubaye | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 21 | Ubaye | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 21 | Ubaye | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 21 | Ubaye | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 21 | Ubaye | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 21 | Ubaye | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 21 | Ubaye | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 22 | Haut-Var Haut-Verdon | enneigement | -1/1500/2000/2500 | 2018-2019 → 2022-2023 |
| 22 | Haut-Var Haut-Verdon | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 22 | Haut-Var Haut-Verdon | neige_fraiche | 1800 | 2018-2019 → 2019-2020 |
| 22 | Haut-Var Haut-Verdon | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 22 | Haut-Var Haut-Verdon | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 22 | Haut-Var Haut-Verdon | vent_bas | 3000 | 2018-2019 → 2022-2023 |
| 22 | Haut-Var Haut-Verdon | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 22 | Haut-Var Haut-Verdon | vent_haut | 9999 | 2018-2019 → 2022-2023 |
| 23 | Mercantour | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 23 | Mercantour | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 23 | Mercantour | neige_fraiche | 1800 | 2015-2016 → 2019-2020 |
| 23 | Mercantour | neige_fraiche | 1800/2500 | 2020-2021 → 2025-2026 |
| 23 | Mercantour | vent_bas | 2000 | 2023-2024 → 2025-2026 |
| 23 | Mercantour | vent_bas | 3000 | 2015-2016 → 2022-2023 |
| 23 | Mercantour | vent_haut | 3000 | 2023-2024 → 2025-2026 |
| 23 | Mercantour | vent_haut | 9999 | 2015-2016 → 2022-2023 |
| 40 | Cinto Rotondo | enneigement | -1/1000/1500/2000 | 2016-2017 → 2022-2023 |
| 40 | Cinto Rotondo | enneigement | 1000/1500/2000 | 2015-2016, 2023-2024 → 2025-2026 |
| 40 | Cinto Rotondo | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 40 | Cinto Rotondo | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 40 | Cinto Rotondo | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 41 | Renoso Incudine | enneigement | -1/1000/1500/2000 | 2016-2017 → 2022-2023 |
| 41 | Renoso Incudine | enneigement | 1000/1500/2000 | 2015-2016, 2023-2024 → 2025-2026 |
| 41 | Renoso Incudine | neige_fraiche | 1800 | 2015-2016 → 2025-2026 |
| 41 | Renoso Incudine | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 41 | Renoso Incudine | vent_haut | 2000 | 2015-2016 → 2025-2026 |
| 64 | Pays-Basque | enneigement | -1/1000/1500/2000 | 2021-2022 → 2022-2023 |
| 64 | Pays-Basque | enneigement | -1/1200/1500/1800 | 2016-2017 → 2019-2020 |
| 64 | Pays-Basque | enneigement | 1000/1500/2000 | 2023-2024 → 2025-2026 |
| 64 | Pays-Basque | enneigement | 1200/1500/1800 | 2015-2016, 2020-2021 |
| 64 | Pays-Basque | neige_fraiche | 1800 | 2015-2016 → 2021-2022, 2023-2024 → 2025-2026 |
| 64 | Pays-Basque | neige_fraiche | 1800/2400 | 2022-2023 |
| 64 | Pays-Basque | vent_bas | 1000 | 2015-2016 → 2025-2026 |
| 64 | Pays-Basque | vent_haut | 2000 | 2015-2016 → 2025-2026 |
| 65 | Aspe Ossau | enneigement | -1/1500/1800/2400 | 2016-2017 → 2019-2020 |
| 65 | Aspe Ossau | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 65 | Aspe Ossau | enneigement | 1500/1800/2400 | 2015-2016, 2020-2021 |
| 65 | Aspe Ossau | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 65 | Aspe Ossau | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2021-2022, 2023-2024 → 2025-2026 |
| 65 | Aspe Ossau | neige_fraiche | 1800/2400 | 2022-2023 |
| 65 | Aspe Ossau | neige_fraiche | 1800/2500 | 2016-2017 |
| 65 | Aspe Ossau | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 65 | Aspe Ossau | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 66 | Haute-Bigorre | enneigement | -1/1500/1800/2400 | 2016-2017 → 2020-2021 |
| 66 | Haute-Bigorre | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 66 | Haute-Bigorre | enneigement | 1500/1800/2400 | 2015-2016 |
| 66 | Haute-Bigorre | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 66 | Haute-Bigorre | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2021-2022, 2023-2024 → 2025-2026 |
| 66 | Haute-Bigorre | neige_fraiche | 1800/2400 | 2022-2023 |
| 66 | Haute-Bigorre | neige_fraiche | 1800/2500 | 2016-2017 |
| 66 | Haute-Bigorre | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 66 | Haute-Bigorre | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 67 | Aure Louron | enneigement | -1/1500/1800/2400 | 2016-2017 → 2020-2021 |
| 67 | Aure Louron | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 67 | Aure Louron | enneigement | 1500/1800/2400 | 2015-2016 |
| 67 | Aure Louron | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 67 | Aure Louron | neige_fraiche | 1800 | 2015-2016, 2017-2018 → 2021-2022, 2023-2024 → 2025-2026 |
| 67 | Aure Louron | neige_fraiche | 1800/2400 | 2022-2023 |
| 67 | Aure Louron | neige_fraiche | 1800/2500 | 2016-2017 |
| 67 | Aure Louron | vent_bas | 1500 | 2015-2016 → 2025-2026 |
| 67 | Aure Louron | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 68 | Luchonnais | enneigement | -1/1500/1800/2100 | 2015-2016 → 2020-2021 |
| 68 | Luchonnais | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 68 | Luchonnais | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 68 | Luchonnais | neige_fraiche | 1800 | 2016-2017 → 2021-2022, 2023-2024 → 2025-2026 |
| 68 | Luchonnais | neige_fraiche | 1800/2400 | 2015-2016, 2022-2023 |
| 68 | Luchonnais | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 68 | Luchonnais | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 69 | Couserans | enneigement | -1/1500/1800/2100 | 2015-2016 → 2020-2021 |
| 69 | Couserans | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 69 | Couserans | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 69 | Couserans | neige_fraiche | 1800 | 2016-2017 → 2021-2022, 2023-2024 → 2025-2026 |
| 69 | Couserans | neige_fraiche | 1800/2400 | 2015-2016 |
| 69 | Couserans | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 69 | Couserans | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 69 | Couserans | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 70 | Haute-Ariege | enneigement | -1/1500/1800/2100 | 2015-2016 → 2020-2021 |
| 70 | Haute-Ariege | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 70 | Haute-Ariege | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 70 | Haute-Ariege | neige_fraiche | 1800 | 2016-2017 → 2021-2022, 2023-2024 → 2025-2026 |
| 70 | Haute-Ariege | neige_fraiche | 1800/2400 | 2015-2016 |
| 70 | Haute-Ariege | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 70 | Haute-Ariege | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 70 | Haute-Ariege | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 71 | Andorre | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 71 | Andorre | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2024-2025 |
| 71 | Andorre | neige_fraiche | 1800 | 2015-2016 → 2021-2022, 2023-2024 → 2024-2025 |
| 71 | Andorre | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 71 | Andorre | vent_bas | 2000 | 2015-2016 → 2024-2025 |
| 71 | Andorre | vent_haut | 3000 | 2015-2016 → 2024-2025 |
| 72 | Orlu St-Barthelemy | enneigement | -1/1500/1800/2100 | 2015-2016 → 2020-2021 |
| 72 | Orlu St-Barthelemy | enneigement | -1/1500/2000/2500 | 2021-2022 → 2022-2023 |
| 72 | Orlu St-Barthelemy | enneigement | 1500/2000/2500 | 2023-2024 → 2025-2026 |
| 72 | Orlu St-Barthelemy | neige_fraiche | 1800 | 2016-2017 → 2021-2022, 2023-2024 → 2025-2026 |
| 72 | Orlu St-Barthelemy | neige_fraiche | 1800/2400 | 2015-2016 |
| 72 | Orlu St-Barthelemy | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 72 | Orlu St-Barthelemy | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 72 | Orlu St-Barthelemy | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 73 | Capcir Puymorens | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 73 | Capcir Puymorens | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 73 | Capcir Puymorens | neige_fraiche | 1800 | 2015-2016 → 2021-2022, 2023-2024 → 2025-2026 |
| 73 | Capcir Puymorens | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 73 | Capcir Puymorens | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 73 | Capcir Puymorens | vent_haut | 3000 | 2015-2016 → 2025-2026 |
| 74 | Cerdagne Canigou | enneigement | -1/1500/2000/2500 | 2016-2017 → 2022-2023 |
| 74 | Cerdagne Canigou | enneigement | 1500/2000/2500 | 2015-2016, 2023-2024 → 2025-2026 |
| 74 | Cerdagne Canigou | neige_fraiche | 1800 | 2015-2016 → 2021-2022, 2023-2024 → 2025-2026 |
| 74 | Cerdagne Canigou | neige_fraiche | 1800/2400/2500 | 2022-2023 |
| 74 | Cerdagne Canigou | vent_bas | 2000 | 2015-2016 → 2025-2026 |
| 74 | Cerdagne Canigou | vent_haut | 3000 | 2015-2016 → 2025-2026 |

## 5. Couverture de la table `enneigement`

Part des bulletins qui portent au moins un relevé d'épaisseur. Décide si la v1 tient sans SAFRAN (spec § 3.3).

| saison | bulletins | % avec relevé du jour | % avec historique |
|---|---|---|---|
| 2015-2016 | 1301 | 100 | 0 |
| 2016-2017 | 7773 | 100 | 91,4 |
| 2017-2018 | 7750 | 100 | 93,9 |
| 2018-2019 | 8003 | 100 | 96,5 |
| 2019-2020 | 5864 | 100 | 96,3 |
| 2020-2021 | 7835 | 100 | 96,9 |
| 2021-2022 | 7952 | 100 | 99,1 |
| 2022-2023 | 7772 | 100 | 98,3 |
| 2023-2024 | 7931 | 100 | 100 |
| 2024-2025 | 7698 | 100 | 100 |
| 2025-2026 | 7608 | 100 | 100 |

## 6. Situations avalancheuses typiques : `sat1` / `sat2`

| saison | bulletins | % sat1 | % sat2 |
|---|---|---|---|
| 2023-2024 | 7931 | 100 | 59,3 |
| 2024-2025 | 7698 | 99,9 | 59,8 |
| 2025-2026 | 7608 | 100 | 61,6 |

Répartition des codes, toutes saisons (libellés inférés : glossaire § 2.7) :

| code | sat1 | sat2 |
|---|---|---|
| 1 | 3002 | 1294 |
| 2 | 9103 | 3198 |
| 3 | 1905 | 3735 |
| 4 | 5422 | 3517 |
| 5 | 1087 | 2111 |
| 6 | 2717 | 148 |

## 7. Distributions pour les seuils encore ouverts

Base des valeurs par défaut de vent fort, d'épisode de chute et de redoux (spec § 3.3). Quantiles **discrets** : chaque valeur a été écrite dans un bulletin. La sentinelle `-1` est écartée (§ 9) : `n` compte les valeurs exploitables. Prévision météo à toutes échéances confondues ; neige fraîche sur l'historique, non dédupliquée (un même jour figure dans plusieurs bulletins), et sur la seule famille `moderne` : avant 2024 la colonne n'est pas un maximum (§ 9).

| champ | lignes retenues | unité | n | p50 | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|---|---|
| `meteo.vent_haut_vitesse_kmh` | prevision | km/h | 215482 | 30 | 50 | 70 | 80 | 100 | 170 |
| `meteo.vent_bas_vitesse_kmh` | prevision | km/h | 255294 | 15 | 30 | 45 | 60 | 80 | 400 |
| `meteo.iso_0_m` | prevision | m | 255312 | 2400 | 3000 | 3400 | 3700 | 4100 | 5100 |
| `neige_fraiche.cumul_max_cm` | historique, hors legacy | cm | 138956 | 0 | 3 | 10 | 20 | 40 | 120 |

## 8. Bloc météo selon `origine` (spec § 4.3)

La convention d'extraction préfère l'historique (analyse) à la prévision pour un même jour. Elle n'est tenable que pour les champs que l'historique porte.

| saison | origine | `iso_0_m` | `iso_moins10_m` | `limite_pluie_neige_m` | `mer_nuages_m` | `temps_sensible` | `temps_sensible_libelle` | `vent_bas_direction` | `vent_bas_vitesse_kmh` | `vent_haut_direction` | `vent_haut_vitesse_kmh` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2015-2016 | prevision | 99,8 | 0 | 26,8 | 0,9 | 99,8 | 64,3 | 99,8 | 99,8 | 77,1 | 77,1 |
| 2016-2017 | prevision | 99,9 | 99,6 | 19,4 | 0,7 | 99,9 | 73,6 | 99,9 | 99,9 | 77,0 | 77,0 |
| 2016-2017 | historique | 99,1 | 98,9 | 18,9 | 1,3 | 99,1 | 72,4 | 99,1 | 99,1 | 76,1 | 76,1 |
| 2017-2018 | prevision | 99,9 | 99,0 | 32,5 | 1,4 | 99,9 | 60,2 | 99,9 | 99,9 | 76,9 | 76,9 |
| 2017-2018 | historique | 98,1 | 97,7 | 31,1 | 2,2 | 98,1 | 59,2 | 98,1 | 98,1 | 76,6 | 76,6 |
| 2018-2019 | prevision | 99,9 | 99,2 | 22,4 | 1,1 | 99,9 | 69,2 | 99,9 | 99,9 | 75,2 | 75,2 |
| 2018-2019 | historique | 98,3 | 97,8 | 21,3 | 1,4 | 98,3 | 68,3 | 98,1 | 98,2 | 73,3 | 73,5 |
| 2019-2020 | prevision | 99,9 | 99,7 | 27,4 | 0,8 | 99,9 | 65,3 | 99,9 | 99,9 | 73,2 | 73,2 |
| 2019-2020 | historique | 96,2 | 95,8 | 25,2 | 1,2 | 96,2 | 64,3 | 95,5 | 95,7 | 70,3 | 70,5 |
| 2020-2021 | prevision | 99,8 | 99,0 | 27,7 | 1,0 | 99,8 | 65,0 | 99,8 | 99,8 | 74,9 | 74,9 |
| 2020-2021 | historique | 99,1 | 98,5 | 26,4 | 1,7 | 99,0 | 64,8 | 99,0 | 99,0 | 74,3 | 74,4 |
| 2021-2022 | prevision | 99,8 | 99,1 | 22,5 | 1,5 | 99,8 | 71,0 | 99,8 | 99,8 | 75,0 | 75,0 |
| 2021-2022 | historique | 98,3 | 97,9 | 21,3 | 2,1 | 98,3 | 69,2 | 98,1 | 98,2 | 73,7 | 73,7 |
| 2022-2023 | prevision | 99,8 | 98,6 | 28,5 | 2,0 | 99,8 | 67,4 | 99,8 | 99,8 | 74,8 | 74,8 |
| 2022-2023 | historique | 97,5 | 96,4 | 26,7 | 2,7 | 97,5 | 64,9 | 97,1 | 97,2 | 72,9 | 72,9 |
| 2023-2024 | prevision | 99,8 | 0 | 32,9 | 1,1 | 99,8 | 99,6 | 99,7 | 99,8 | 99,8 | 99,8 |
| 2023-2024 | historique | 98,9 | 0 | 32,8 | 0 | 98,9 | 98,9 | 98,8 | 98,9 | 98,9 | 98,9 |
| 2024-2025 | prevision | 99,9 | 0 | 30,0 | 1,5 | 99,9 | 99,9 | 99,9 | 99,9 | 99,9 | 99,9 |
| 2024-2025 | historique | 99,7 | 0 | 28,5 | 0 | 99,7 | 99,7 | 99,6 | 99,6 | 99,6 | 99,6 |
| 2025-2026 | prevision | 99,8 | 0 | 29,3 | 1,0 | 99,8 | 96,9 | 99,8 | 99,8 | 99,8 | 99,8 |
| 2025-2026 | historique | 99,5 | 0 | 28,1 | 0 | 99,5 | 95,6 | 99,5 | 99,5 | 99,5 | 99,5 |

Champs que l'historique porte moins de 50,0 % aussi souvent que la prévision — la convention ne tient pas pour eux :

| saison | champ | % prévision | % historique |
|---|---|---|---|
| 2015-2016 | `iso_0_m` | 99,8 | 0 |
| 2015-2016 | `limite_pluie_neige_m` | 26,8 | 0 |
| 2015-2016 | `mer_nuages_m` | 0,9 | 0 |
| 2015-2016 | `temps_sensible` | 99,8 | 0 |
| 2015-2016 | `temps_sensible_libelle` | 64,3 | 0 |
| 2015-2016 | `vent_bas_direction` | 99,8 | 0 |
| 2015-2016 | `vent_bas_vitesse_kmh` | 99,8 | 0 |
| 2015-2016 | `vent_haut_direction` | 77,1 | 0 |
| 2015-2016 | `vent_haut_vitesse_kmh` | 77,1 | 0 |
| 2023-2024 | `mer_nuages_m` | 1,1 | 0 |
| 2024-2025 | `mer_nuages_m` | 1,5 | 0 |
| 2025-2026 | `mer_nuages_m` | 1,0 | 0 |

> **Limite de la mesure.** `-1` vaut « sans objet » pour `PLUIENEIGE` (temps sec) et `MERNUAGES` (pas de mer de nuages), et le parser le convertit en nul. Pour ces deux champs, l'entrepôt ne distingue donc pas un attribut absent d'une valeur sans objet : une part basse y décrit la météo autant que le format. Depuis 2024, `MERNUAGES` figure dans la prévision et plus dans le bloc `BSH` : l'écart ressort ci-dessus grâce aux rares jours où la prévision annonce une mer de nuages, mais il est invisible bulletin par bulletin quand elle dit `-1`.

## 9. Sentinelles `-1` restées dans l'entrepôt

La pipeline ne convertit en nul que le `-1` de `RISQUE1`, `PLUIENEIGE` et `MERNUAGES`. Ailleurs il reste une valeur, et une somme ou une moyenne le compte. Nombre de `-1` par champ et par saison (lignes `massif_coherent`) :

| champ | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `bulletins.enneigement_limite_nord_m` | 7 | 122 | 116 | 75 | 101 | 218 | 292 | 204 | 68 | 204 | 57 |
| `bulletins.enneigement_limite_sud_m` | 28 | 434 | 195 | 166 | 174 | 360 | 532 | 409 | 263 | 405 | 180 |
| `enneigement.altitude_m` | 21 | 768 | 648 | 957 | 711 | 567 | 1215 | 747 | 0 | 0 | 0 |
| `enneigement.epaisseur_nord_cm` | 21 | 768 | 648 | 957 | 711 | 567 | 1215 | 747 | 0 | 0 | 0 |
| `enneigement.epaisseur_sud_cm` | 21 | 777 | 651 | 957 | 711 | 567 | 1215 | 747 | 0 | 0 | 0 |
| `enneigement.limite_nord_m` | 21 | 2523 | 3363 | 2067 | 2889 | 4503 | 6696 | 4722 | 204 | 612 | 171 |
| `enneigement.limite_sud_m` | 84 | 8733 | 5505 | 4173 | 4623 | 7677 | 12198 | 9981 | 789 | 1215 | 540 |
| `meteo.iso_0_m` | 7 | 1350 | 2895 | 2786 | 4539 | 1547 | 2847 | 4001 | 0 | 0 | 0 |
| `meteo.iso_moins10_m` | 0 | 1728 | 3728 | 3730 | 5064 | 2587 | 3774 | 6026 | 0 | 0 | 0 |
| `meteo.temps_sensible` | 7 | 1332 | 2883 | 2798 | 4548 | 1619 | 2811 | 3968 | 0 | 0 | 0 |
| `meteo.vent_bas_vitesse_kmh` | 7 | 1386 | 2883 | 2874 | 5127 | 1571 | 3114 | 4610 | 0 | 0 | 0 |
| `meteo.vent_haut_vitesse_kmh` | 895 | 41010 | 41068 | 49028 | 39731 | 46756 | 49536 | 49295 | 0 | 0 | 0 |
| `neige_fraiche.cumul_max_cm` | 6468 | 73974 | 74746 | 78529 | 57500 | 77321 | 79269 | 77089 | 0 | 0 | 1 |
| `neige_fraiche.cumul_min_cm` | 42 | 415 | 331 | 425 | 250 | 347 | 616 | 434 | 0 | 0 | 1 |

### `neige_fraiche` : `SS241` / `SS242` ne sont pas un minimum et un maximum

Le glossaire (§ 5) et le parser tiennent `SS241`/`SS242` (≤ 2023) pour les ancêtres de `SS24Min`/`SS24Max` (≥ 2024). Les données le contredisent :

| famille | lignes | `cumul_max_cm = -1` | `cumul_max_cm < cumul_min_cm` |
|---|---|---|---|
| legacy | 630648 | 524896 | 455021 |
| moderne | 278844 | 1 | 194 |

Le XML legacy porte sur `NEIGEFRAICHE` deux attributs `SECTEURSS1` / `SECTEURSS2` (`massif` / vide, `Ouest` / `Est`, `Nord` / `Sud`…) : `SS241` et `SS242` y sont **les cumuls de deux secteurs**, et `SS242=-1` signifie « pas de second secteur ». *Inféré* de la structure du fichier ; aucun descriptif ne documente l'ancien format. Conséquence : avant 2024, `cumul_max_cm` n'est pas un maximum, et toute métrique de neige fraîche (spec § 5.2) doit attendre qu'une règle de parsing soit arrêtée.

## 10. Tranches d'altitude normées (vue `palier_tranche`)

Bornes fermées à gauche, définies une fois dans `tranches.py` : **basse** < 1800 m, **moyenne** 1800–2400 m, **haute** ≥ 2400 m. Les paliers de l'archive tombent pile sur 1800 et 2400 m : fermées à gauche, les deux époques de paliers d'enneigement (1500/1800/2400 puis 1500/2000/2500) donnent chacune un palier par tranche. Une altitude `-1` n'entre dans aucune tranche.

### Couples massif × saison dont tous les paliers tombent dans une seule tranche

Pour ces couples, la comparaison entre massifs n'a de sens que sur la tranche occupée ; sur les deux autres il n'y a rien à comparer. Neige fraîche et vent ont **une** altitude de référence par bulletin : une seule tranche par construction, sauf changement d'altitude en cours de saison.

| source | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 | part |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enneigement | 0/35 | 0/35 | 0/35 | 0/36 | 0/36 | 0/36 | 0/36 | 0/36 | 0/36 | 0/36 | 0/35 | 0 % |
| neige_fraiche | 28/35 | 23/35 | 35/35 | 36/36 | 36/36 | 27/36 | 27/36 | 16/36 | 27/36 | 27/36 | 26/35 | 78,6 % |
| vent_bas | 35/35 | 35/35 | 35/35 | 36/36 | 35/36 | 36/36 | 36/36 | 36/36 | 36/36 | 35/36 | 35/35 | 99,5 % |
| vent_haut | 35/35 | 35/35 | 35/35 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 35/35 | 100 % |

### Massifs disposant d'au moins un palier, par tranche

Une case vide est une tranche sans aucune donnée pour cette source et cette saison : aucune valeur n'y est interpolée.

| source | tranche | 2015-2016 | 2016-2017 | 2017-2018 | 2018-2019 | 2019-2020 | 2020-2021 | 2021-2022 | 2022-2023 | 2023-2024 | 2024-2025 | 2025-2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| enneigement | basse | 35 | 35 | 35 | 36 | 36 | 36 | 36 | 36 | 36 | 36 | 35 |
| enneigement | moyenne | 35 | 35 | 35 | 36 | 36 | 36 | 36 | 36 | 36 | 36 | 35 |
| enneigement | haute | 23 | 23 | 23 | 24 | 24 | 24 | 28 | 28 | 28 | 28 | 27 |
| neige_fraiche | basse | — | — | — | — | — | — | — | — | — | — | — |
| neige_fraiche | moyenne | 35 | 35 | 35 | 36 | 36 | 36 | 36 | 36 | 36 | 36 | 35 |
| neige_fraiche | haute | 7 | 12 | — | — | — | 9 | 9 | 20 | 9 | 9 | 9 |
| vent_bas | basse | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 |
| vent_bas | moyenne | 15 | 15 | 15 | 15 | 16 | 15 | 15 | 15 | 24 | 24 | 23 |
| vent_bas | haute | 12 | 12 | 12 | 13 | 13 | 13 | 13 | 13 | 4 | 5 | 4 |
| vent_haut | basse | — | — | — | — | — | — | — | — | — | — | — |
| vent_haut | moyenne | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| vent_haut | haute | 30 | 30 | 30 | 31 | 31 | 31 | 31 | 31 | 31 | 31 | 30 |
