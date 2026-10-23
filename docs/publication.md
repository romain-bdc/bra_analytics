# Publication sur GitHub Pages et data.gouv.fr

Procédure de mise en ligne des quatre écrans et de déclaration de la réutilisation. Spec :
`docs/spec-publication.md`. URL publique : **https://romain-bdc.github.io/bra_analytics/**
(stable tant que ni le repo ni le compte ne sont renommés).

## Mise en ligne initiale (une fois, à la main)

1. **Passer le repo en public** : Settings → General → Danger Zone → Change visibility.
   L'audit de l'historique (T16) est fait et la licence MIT est dans `LICENSE`.
2. **Construire et publier** (la branche `gh-pages` doit exister avant l'étape suivante) :

   ```bash
   uv run bra site
   uv run bra publier --dry-run     # relire la liste
   uv run bra publier
   ```

3. **Activer Pages** : Settings → Pages → Source « Deploy from a branch », branche `gh-pages`,
   dossier `/ (root)`. Cocher « Enforce HTTPS ».
4. **Vérifier** `https://romain-bdc.github.io/bra_analytics/` : les quatre écrans, la navigation,
   un lien avec fragment (`.../#m=68&s=2023-2024` doit aboutir sur la carte avec l'état conservé),
   et, dans l'onglet réseau du navigateur, **aucune requête vers un domaine tiers**.
5. **Ajouter l'URL publique** en tête du `README.md` et dans la description du repo GitHub.
6. **Déclarer la réutilisation** sur data.gouv.fr (voir plus bas), d'abord en brouillon.

## Republier après une mise à jour de l'archive

```bash
uv run bra fetch --seasons <saison>      # si de nouveaux bulletins existent
uv run bra build --replace && uv run bra check && uv run bra site && uv run bra publier
```

`bra site` refuse un arbre de travail sale (`version.json` doit pointer vers un commit qui
existe) ; `bra publier` ne crée aucun commit si rien n'a changé et ne force jamais le push.

Image de lien (`apercu.png`) : si la carte change, relancer `uv run python scripts/apercu.py`
et committer `src/bra_analytics/templates/apercu.png`. `bra site` la copie dans `site/`.

## Brouillon de la réutilisation data.gouv.fr

« Publier une réutilisation » depuis la page du jeu de données. Créer en **brouillon** pour
relecture.

- **Titre** : Historique du risque d'avalanche par massif depuis 2016
- **Type** : Visualisation
- **URL** : https://romain-bdc.github.io/bra_analytics/
- **Image** : `apercu.png` (1200 × 630, capture de la carte d'accueil)
- **Jeux de données associés** : l'archive des Bulletins d'Estimation du Risque d'Avalanche
  (qui porte aussi les contours des massifs) ; le contour IGN Admin Express si le jeu est
  référencé sur data.gouv.fr.
- **Description** :

  > Quatre écrans pour lire l'archive des Bulletins d'Estimation du Risque d'Avalanche (BRA) de
  > Météo-France, de mars 2016 à juin 2026, sur les 36 massifs du référentiel.
  >
  > - **Carte** : l'indice de risque moyen de chaque massif sur les saisons comparables.
  > - **Fiche massif-saison** : risque, enneigement indicatif, isotherme 0 °C et vent d'un massif sur une saison.
  > - **Comparaison** : courbes, tableau et classement de plusieurs saisons d'un massif.
  > - **Exploration** : rose des pentes, vent par orientation, situations typiques.
  >
  > Limites qui conditionnent la lecture : toute comparaison d'indice entre saisons se fait sur
  > la fenêtre « cœur » et sur les saisons comparables, car la valeur sentinelle `RISQUE1=-1`
  > s'arrête en juin 2021 et crée, hors de cette fenêtre, un écart d'encodage ; l'estimation de la
  > saison 2019-2020 s'arrête fin mars (confinement) ; le massif 22 (Haut-Var Haut-Verdon)
  > n'apparaît qu'en novembre 2018 et le massif 71 (Andorre) disparaît en 2025-2026. Un niveau de
  > risque est ordinal : les moyennes sont toujours données avec leur nombre de jours.
  >
  > Les pages sont statiques, sans serveur ni traceur, polices auto-hébergées. Code (licence MIT) :
  > https://github.com/romain-bdc/bra_analytics. Définition de chaque champ :
  > `docs/glossaire.md` dans ce dépôt.
  >
  > Données Météo-France, Licence Ouverte 2.0.
