"""
Backward-compatibility shim for legacy TMDB imports.

The project now uses IMDb (API-key-less) for movie/series metadata selection.
"""

from typing import Optional, Dict, Any

from imdb_api import (
    IMDBAPI,
    interactive_imdb_movie_selection,
    interactive_imdb_series_selection,
)


class TMDBAPI(IMDBAPI):
    """
    Legacy class alias kept for compatibility.
    Internally delegates to IMDb integration.
    """


_tmdb_api = TMDBAPI()


def interactive_tmdb_movie_selection() -> Optional[Dict[str, Any]]:
    """Legacy function alias to IMDb movie metadata selection."""
    return interactive_imdb_movie_selection()


def interactive_tmdb_series_selection() -> Optional[Dict[str, Any]]:
    """Legacy function alias to IMDb series metadata selection."""
    return interactive_imdb_series_selection()
