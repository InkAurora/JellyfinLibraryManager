"""
IMDb integration for movie and series metadata discovery (API-key-less).
"""

import re
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup

from config import IMDB_FIND_BASE_URL, IMDB_SUGGEST_BASE_URL
from ui import MenuSystem
from utils import clear_screen


class IMDBAPI:
    """Class to handle IMDb interactions without API keys."""

    REQUEST_TIMEOUT_SECONDS = 10
    SUGGEST_BASE_URL = IMDB_SUGGEST_BASE_URL.rstrip("/")
    FIND_BASE_URL = IMDB_FIND_BASE_URL
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self):
        self.menu_system = MenuSystem()

    @staticmethod
    def _parse_year(value: Any) -> str:
        if value is None:
            return "Unknown"
        text = str(value).strip()
        if not text:
            return "Unknown"
        match = re.search(r"(19|20)\d{2}", text)
        return match.group(0) if match else "Unknown"

    @staticmethod
    def _is_allowed_type(media_type: str, type_label: str) -> bool:
        label = (type_label or "").strip().lower()
        if media_type == "movie":
            blocked = ["episode", "tv episode", "podcast"]
            return not any(token in label for token in blocked)
        if media_type == "series":
            allowed = ["tv series", "tv mini series", "tv miniseries", "series", "mini series"]
            return any(token in label for token in allowed)
        return True

    def _search_via_suggest(self, query: str, media_type: str, limit: int) -> List[Dict[str, Any]]:
        if not query:
            return []

        first = query.strip()[0].lower()
        if not first.isalnum():
            first = "_"

        encoded_query = requests.utils.quote(query.strip())
        url = f"{self.SUGGEST_BASE_URL}/{first}/{encoded_query}.json"
        response = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=self.REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()

        results: List[Dict[str, Any]] = []
        for item in payload.get("d", []):
            imdb_id = str(item.get("id", "") or "")
            if not imdb_id.startswith("tt"):
                continue

            title = str(item.get("l", "Unknown") or "Unknown")
            type_label = str(item.get("q", "") or "")
            if not self._is_allowed_type(media_type, type_label):
                continue

            year = self._parse_year(item.get("y"))
            subtitle = str(item.get("s", "") or "")

            results.append({
                "id": imdb_id,
                "title": title,
                "original_title": title,
                "year": year,
                "overview": subtitle,
                "media_type": media_type,
                "imdb_type": type_label or "Unknown",
                "rating": None,
                "votes": None
            })
            if len(results) >= limit:
                break
        return results

    def _search_via_find_page(self, query: str, media_type: str, limit: int) -> List[Dict[str, Any]]:
        params = {"q": query, "s": "tt"}
        response = requests.get(
            self.FIND_BASE_URL,
            params=params,
            headers=self.DEFAULT_HEADERS,
            timeout=self.REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_ids = set()

        # New IMDb UI often uses links containing /title/tt... in list rows.
        for link in soup.select('a[href*="/title/tt"]'):
            href = str(link.get("href", "") or "")
            id_match = re.search(r"/title/(tt\d+)/", href)
            if not id_match:
                continue
            imdb_id = id_match.group(1)
            if imdb_id in seen_ids:
                continue

            title = link.get_text(strip=True) or "Unknown"
            if not title:
                continue

            row_text = link.find_parent().get_text(" ", strip=True) if link.find_parent() else ""
            type_hint = row_text.lower()
            if media_type == "series":
                if "tv series" not in type_hint and "tv mini series" not in type_hint and "series" not in type_hint:
                    continue
            elif media_type == "movie":
                if "tv episode" in type_hint or "episode" in type_hint:
                    continue

            year = self._parse_year(row_text)
            seen_ids.add(imdb_id)
            results.append({
                "id": imdb_id,
                "title": title,
                "original_title": title,
                "year": year,
                "overview": "",
                "media_type": media_type,
                "imdb_type": "Unknown",
                "rating": None,
                "votes": None
            })
            if len(results) >= limit:
                break
        return results

    def search_movies(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Search IMDb for movies without API key."""
        if not query:
            return []
        try:
            results = self._search_via_suggest(query, "movie", limit)
            if results:
                return results
        except Exception:
            pass

        try:
            return self._search_via_find_page(query, "movie", limit)
        except Exception as e:
            print(f"❌ IMDb movie search error: {e}")
            return []

    def search_series(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Search IMDb for TV series without API key."""
        if not query:
            return []
        try:
            results = self._search_via_suggest(query, "series", limit)
            if results:
                return results
        except Exception:
            pass

        try:
            return self._search_via_find_page(query, "series", limit)
        except Exception as e:
            print(f"❌ IMDb series search error: {e}")
            return []

    def _interactive_select_from_results(self, results: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
        """Allow user to choose an IMDb metadata result."""
        if not results:
            return None

        options = []
        for item in results:
            name = item.get("title", "Unknown")
            year = item.get("year", "Unknown")
            imdb_id = item.get("id", "N/A")
            type_label = item.get("imdb_type", "Unknown")
            options.append(f"{name} ({year}) [IMDb {imdb_id}] [{type_label}]")
        options.append("🔙 Cancel")

        choice = self.menu_system.navigate_paginated_menu(options, title, page_size=12)
        if choice == -1 or choice == len(options) - 1:
            return None
        return results[choice]

    def _interactive_manual_metadata(self, media_type: str, prompt_label: str) -> Optional[Dict[str, Any]]:
        """Fallback manual metadata entry when IMDb lookup fails or is skipped."""
        title = self.menu_system.get_user_input(f"Enter {prompt_label} title: ")
        if not title:
            return None

        year_input = self.menu_system.get_user_input(f"Enter {prompt_label} year (optional): ")
        year = year_input.strip() if year_input else "Unknown"

        imdb_id = self.menu_system.get_user_input(
            f"Enter IMDb ID for this {prompt_label} (optional, e.g. tt1234567): "
        )
        imdb_id = (imdb_id or "").strip()
        if imdb_id and not imdb_id.startswith("tt"):
            imdb_id = ""

        return {
            "id": imdb_id or None,
            "title": title.strip(),
            "original_title": title.strip(),
            "year": year if year else "Unknown",
            "overview": "",
            "media_type": media_type,
            "imdb_type": "Manual",
            "rating": None,
            "votes": None
        }

    def interactive_movie_selection(self) -> Optional[Dict[str, Any]]:
        """Interactive IMDb movie search + selection."""
        query = self.menu_system.get_user_input("Enter movie name to search in IMDb: ")
        if not query:
            return None

        results = self.search_movies(query, limit=25)
        if not results:
            clear_screen()
            print(f"❌ No IMDb movie results found for '{query}'.")
            print("💡 Falling back to manual movie metadata entry.")
            return self._interactive_manual_metadata("movie", "movie")
        return self._interactive_select_from_results(results, "🎬 Select Movie Metadata (IMDb)")

    def interactive_series_selection(self) -> Optional[Dict[str, Any]]:
        """Interactive IMDb series search + selection."""
        query = self.menu_system.get_user_input("Enter series name to search in IMDb: ")
        if not query:
            return None

        results = self.search_series(query, limit=25)
        if not results:
            clear_screen()
            print(f"❌ No IMDb series results found for '{query}'.")
            print("💡 Falling back to manual series metadata entry.")
            return self._interactive_manual_metadata("series", "series")
        return self._interactive_select_from_results(results, "📺 Select Series Metadata (IMDb)")


_imdb_api = IMDBAPI()


def interactive_imdb_movie_selection() -> Optional[Dict[str, Any]]:
    """Interactive movie metadata selection via IMDb. (Legacy function)"""
    return _imdb_api.interactive_movie_selection()


def interactive_imdb_series_selection() -> Optional[Dict[str, Any]]:
    """Interactive series metadata selection via IMDb. (Legacy function)"""
    return _imdb_api.interactive_series_selection()
