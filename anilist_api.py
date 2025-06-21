"""
AniList API integration for anime search functionality.
"""

import requests
import time
import threading
import msvcrt
from typing import List, Tuple, Optional, Union
from utils import clear_screen, wait_for_enter


class AniListAPI:
    """Class to handle AniList API interactions."""
    
    def __init__(self):
        self.api_url = "https://graphql.anilist.co"
        self.min_interval = 3.0  # Minimum interval between requests to avoid rate limit
        self.last_request_time = 0
    
    def search_anime(self, query: str, limit: int = 10) -> Union[List[Tuple[str, int, int]], str]:
        """Search AniList API for anime by name. Returns a list of (title, year, id) or error message."""
        graphql_query = {
            'query': '''
            query ($search: String, $perPage: Int) {
              Page(perPage: $perPage) {
                media(search: $search, type: ANIME) {
                  id
                  title { romaji english native }
                  startDate { year }
                }
              }
            }
            ''',
            'variables': {'search': query, 'perPage': limit}
        }
        
        try:
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_request_time < self.min_interval:
                time.sleep(self.min_interval - (current_time - self.last_request_time))
            
            response = requests.post(self.api_url, json=graphql_query, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            self.last_request_time = time.time()
            
            results = []
            for media in data['data']['Page']['media']:
                title = media['title']['english'] or media['title']['romaji'] or media['title']['native']
                year = media['startDate']['year'] if media['startDate'] else None
                results.append((title, year, media['id']))
            
            return results
        except Exception as e:
            return f"Error: {e}"
    
    def interactive_search(self) -> Optional[Tuple[str, int, int]]:
        """Interactive search for anime using AniList API with pause detection and improved UX."""
        prompt = "Type the anime name (Esc to cancel):"
        input_str = ''
        last_time = time.time()
        results = []
        search_thread = None
        last_query = ''
        min_pause = 0.5  # 0.5 seconds pause
        num_str = ''

        def do_search(query: str) -> None:
            nonlocal results
            results = self.search_anime(query)
            print("\n" + "=" * 30)
            if isinstance(results, str):
                print(results)
            elif results:
                for i, (title, year, aid) in enumerate(results, 1):
                    year_str = f"({year})" if year else "(Unknown Year)"
                    print(f"{i:2d}. {title} {year_str} [AniList ID: {aid}]")
            else:
                print("No results found.")
            print("\nContinue typing, or type number then Enter to select, Esc to cancel.")

        clear_screen()
        print(prompt)
        print()
        print(input_str, end='', flush=True)
        
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == '\r':  # Enter
                    print()
                    if num_str:
                        try:
                            idx = int(num_str) - 1
                            if results and not isinstance(results, str) and 0 <= idx < len(results):
                                return results[idx]
                        except Exception:
                            pass
                        num_str = ''
                    else:
                        break
                elif key == '\x1b':  # Esc
                    print("\n❌ Cancelled.")
                    wait_for_enter()
                    return None
                elif key == '\b':  # Backspace
                    if num_str:
                        num_str = num_str[:-1]
                    else:
                        input_str = input_str[:-1]
                elif key.isdigit():
                    num_str += key
                else:
                    input_str += key
                    num_str = ''
                
                clear_screen()
                print(prompt)
                print()
                print(input_str, end='', flush=True)
                if num_str:
                    print(f"\nSelected number: {num_str}")
                last_time = time.time()
            else:
                now = time.time()
                if input_str and (now - last_time > min_pause):
                    # Only search if input changed and enough time since last request
                    if (input_str != last_query) and (now - self.last_request_time > self.min_interval):
                        print("\n" + "=" * 30)
                        if search_thread is None or not search_thread.is_alive():
                            search_thread = threading.Thread(target=do_search, args=(input_str,))
                            search_thread.start()
                        last_query = input_str
                        last_time = now  # Prevent repeated searches
                time.sleep(0.05)
        
        # After Enter, let user pick from results if any (fallback)
        if results and not isinstance(results, str):
            print("\nSelect an anime by number, or press Enter to cancel:")
            try:
                sel = input().strip()
                if sel.isdigit():
                    idx = int(sel) - 1
                    if 0 <= idx < len(results):
                        return results[idx]
            except Exception:
                pass
        
        return None


# Global instance
_anilist_api = AniListAPI()


# Legacy functions for backward compatibility
def anilist_search(query: str, limit: int = 10) -> Union[List[Tuple[str, int, int]], str]:
    """Search AniList API for anime by name. (Legacy function)"""
    return _anilist_api.search_anime(query, limit)


def interactive_anilist_search() -> Optional[Tuple[str, int, int]]:
    """Interactive search for anime using AniList API. (Legacy function)"""
    return _anilist_api.interactive_search()
