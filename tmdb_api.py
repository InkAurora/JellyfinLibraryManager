"""
TMDB API integration for movie and series metadata discovery.
"""

from typing import List, Dict, Any, Optional
import requests
from config import TMDB_API_KEY, TMDB_BASE_URL, TMDB_LANGUAGE
from ui import MenuSystem
from utils import clear_screen


class TMDBAPI:
    """Class to handle TMDB API interactions."""

    REQUEST_TIMEOUT_SECONDS = 8

    def __init__(self):
        self.api_key = TMDB_API_KEY
        self.base_url = TMDB_BASE_URL.rstrip("/")
        self.language = TMDB_LANGUAGE
        self.menu_system = MenuSystem()

    def is_configured(self) -> bool:
        """Return True if TMDB API key is configured."""
        return bool(self.api_key and self.api_key.strip())

    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a TMDB GET request and return JSON payload."""
        request_params = {
            "api_key": self.api_key,
            "language": self.language
        }
        request_params.update(params)
        response = requests.get(
            f"{self.base_url}{endpoint}",
            params=request_params,
            timeout=self.REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def search_movies(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search TMDB for movies."""
        if not self.is_configured() or not query:
            return []
        try:
            payload = self._request("/search/movie", {"query": query, "include_adult": "false"})
            results = []
            for item in payload.get("results", [])[:limit]:
                release_date = item.get("release_date", "") or ""
                year = release_date[:4] if len(release_date) >= 4 else "Unknown"
                results.append({
                    "id": item.get("id"),
                    "title": item.get("title", "Unknown"),
                    "original_title": item.get("original_title", ""),
                    "year": year,
                    "overview": item.get("overview", ""),
                    "media_type": "movie"
                })
            return results
        except Exception as e:
            print(f"❌ TMDB movie search error: {e}")
            return []

    def search_series(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search TMDB for TV series."""
        if not self.is_configured() or not query:
            return []
        try:
            payload = self._request("/search/tv", {"query": query, "include_adult": "false"})
            results = []
            for item in payload.get("results", [])[:limit]:
                first_air_date = item.get("first_air_date", "") or ""
                year = first_air_date[:4] if len(first_air_date) >= 4 else "Unknown"
                results.append({
                    "id": item.get("id"),
                    "title": item.get("name", "Unknown"),
                    "original_title": item.get("original_name", ""),
                    "year": year,
                    "overview": item.get("overview", ""),
                    "media_type": "series"
                })
            return results
        except Exception as e:
            print(f"❌ TMDB series search error: {e}")
            return []

    def _interactive_select_from_results(self, results: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
        """Allow user to choose a metadata result from menu options."""
        if not results:
            return None
        options = []
        for item in results:
            name = item.get("title", "Unknown")
            year = item.get("year", "Unknown")
            options.append(f"{name} ({year}) [TMDB #{item.get('id', 'N/A')}]")
        options.append("🔙 Cancel")

        choice = self.menu_system.navigate_menu(options, title)
        if choice == -1 or choice == len(options) - 1:
            return None
        return results[choice]

    def _interactive_manual_metadata(self, media_type: str, prompt_label: str) -> Optional[Dict[str, Any]]:
        """Fallback manual metadata entry when TMDB is unavailable or skipped."""
        title = self.menu_system.get_user_input(f"Enter {prompt_label} title: ")
        if not title:
            return None

        year_input = self.menu_system.get_user_input(f"Enter {prompt_label} year (optional): ")
        year = year_input.strip() if year_input else "Unknown"

        return {
            "id": None,
            "title": title.strip(),
            "original_title": title.strip(),
            "year": year if year else "Unknown",
            "overview": "",
            "media_type": media_type
        }

    def interactive_movie_selection(self) -> Optional[Dict[str, Any]]:
        """Interactive TMDB movie search + selection."""
        if not self.is_configured():
            clear_screen()
            print("⚠️  TMDB API key is not configured.")
            print("💡 Falling back to manual movie metadata entry.")
            return self._interactive_manual_metadata("movie", "movie")

        query = self.menu_system.get_user_input("Enter movie name to search in TMDB: ")
        if not query:
            return None

        results = self.search_movies(query, limit=15)
        if not results:
            clear_screen()
            print(f"❌ No TMDB movie results found for '{query}'.")
            return self._interactive_manual_metadata("movie", "movie")
        return self._interactive_select_from_results(results, "🎬 Select Movie Metadata")

    def interactive_series_selection(self) -> Optional[Dict[str, Any]]:
        """Interactive TMDB series search + selection."""
        if not self.is_configured():
            clear_screen()
            print("⚠️  TMDB API key is not configured.")
            print("💡 Falling back to manual series metadata entry.")
            return self._interactive_manual_metadata("series", "series")

        query = self.menu_system.get_user_input("Enter series name to search in TMDB: ")
        if not query:
            return None

        results = self.search_series(query, limit=15)
        if not results:
            clear_screen()
            print(f"❌ No TMDB series results found for '{query}'.")
            return self._interactive_manual_metadata("series", "series")
        return self._interactive_select_from_results(results, "📺 Select Series Metadata")


_tmdb_api = TMDBAPI()


def interactive_tmdb_movie_selection() -> Optional[Dict[str, Any]]:
    """Interactive movie metadata selection via TMDB. (Legacy function)"""
    return _tmdb_api.interactive_movie_selection()


def interactive_tmdb_series_selection() -> Optional[Dict[str, Any]]:
    """Interactive series metadata selection via TMDB. (Legacy function)"""
    return _tmdb_api.interactive_series_selection()
