"""Couche metriques (spec section 5) : un module par bloc.

Les metriques sont des vues DuckDB posees sur `risque_journalier`, plus les
fonctions qui les lisent. L'interface les consomme telles quelles et ne
recopie aucun SQL : une definition recopiee est une definition qui divergera.
"""
