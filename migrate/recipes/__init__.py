"""Recipes for opt-in domain-specific Notion -> Graphiti shaping.

A recipe is a callable invoked once per Notion item (database row or
page) that returns either a PlannedEpisode, a list of PlannedEpisodes,
or None. Returning None falls back to the migrator's default shape.

See README.md in this directory for the full contract.
"""
