"""
Nyaa.si API integration for torrent search functionality.
"""

import requests
import urllib.parse
import feedparser
import msvcrt
from typing import List, Dict, Any, Optional, Union
from bs4 import BeautifulSoup
from utils import clear_screen, parse_size
from ui import MenuSystem


class NyaaAPI:
    """Class to handle Nyaa.si RSS feed integration."""
    
    def __init__(self):
        self.base_url = "https://nyaa.si"
        self.rss_url = f"{self.base_url}/?page=rss"
    
    def search_torrents(self, anime_name: str, limit: int = 50) -> Union[List[Dict[str, Any]], str]:
        """Search nyaa.si RSS for torrents matching the anime name."""
        rss_url = f"{self.rss_url}&q={urllib.parse.quote(anime_name)}&s=seeders&o=desc"
        
        try:
            feed = feedparser.parse(rss_url)
            results = []
            
            for entry in feed.entries[:limit]:
                try:
                    result = {
                        'title': getattr(entry, 'title', 'N/A'),
                        'link': getattr(entry, 'link', 'N/A'),
                        'seeds': int(getattr(entry, 'nyaa_seeders', 0) or 0),
                        'size': getattr(entry, 'nyaa_size', 'Unknown'),
                        'leechers': int(getattr(entry, 'nyaa_leechers', 0) or 0),
                        'downloads': int(getattr(entry, 'nyaa_downloads', 0) or 0),
                        'infohash': getattr(entry, 'nyaa_infohash', 'N/A'),
                        'category': getattr(entry, 'nyaa_category', 'N/A'),
                        'categoryId': getattr(entry, 'nyaa_categoryid', 'N/A'),
                        'published': getattr(entry, 'published', 'N/A'),
                        'guid': getattr(entry, 'guid', 'N/A')
                    }
                    results.append(result)
                except (ValueError, AttributeError, TypeError):
                    # Skip entries with parsing errors but continue with others
                    continue
            
            return results
        except Exception as e:
            return f"Error fetching RSS feed: {e}"
    
    def sort_torrents(self, results: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """Sort torrent results by seeds or size."""
        if sort_by == 'seeds':
            return sorted(results, key=lambda x: x['seeds'], reverse=True)
        else:
            return sorted(results, key=lambda x: parse_size(x['size']), reverse=True)
    
    def navigate_results(self, results: List[Dict[str, Any]], window_size: int = 10) -> Union[Optional[Dict[str, Any]], str]:
        """Allow user to navigate nyaa.si results with shortcuts and select one."""
        if not results:
            return None

        def _seeds(item: Dict[str, Any]) -> int:
            try:
                return int(item.get("seeds", 0) or 0)
            except (TypeError, ValueError):
                return 0

        def _size(item: Dict[str, Any]) -> int:
            return parse_size(str(item.get("size", "0")))

        def _row(item: Dict[str, Any]) -> str:
            title = str(item.get("title", "N/A"))
            short_title = title if len(title) <= 90 else title[:87] + "..."
            return f"[S:{_seeds(item):>4}] [Size:{str(item.get('size', 'Unknown')):>10}] {short_title}"

        choice = MenuSystem.navigate_search_results(
            items=results,
            title="🔎 Nyaa Search Results",
            row_formatter=_row,
            seeds_extractor=_seeds,
            size_extractor=_size,
            page_size=window_size,
            extra_hotkeys={b'/': 'HOTKEY_MANUAL_SEARCH'},
            extra_hint="💡 Press / for custom search."
        )

        if choice == -1:
            return None
        if isinstance(choice, str):
            return choice
        return results[choice]
    
    def get_torrent_file_list(self, torrent_page_url: str) -> List[str]:
        """Scrape the torrent page to get the file list, preserving folder structure."""
        try:
            resp = requests.get(torrent_page_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            file_tree = []
            
            # --- Extract torrent info ---
            info_lines = []
            # Title
            title_tag = soup.find('h3')
            if title_tag:
                info_lines.append(f"Title: {title_tag.get_text(strip=True)}")
            
            # Info table (contains size, date, seeders, leechers, downloads, etc.)
            info_table = soup.find('table', class_='torrent-info')
            if info_table:
                for row in info_table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) == 2:
                        key = cols[0].get_text(strip=True)
                        val = cols[1].get_text(strip=True)
                        info_lines.append(f"{key}: {val}")
            else:
                # Fallback: extract info from sidebar
                sidebar = soup.find('div', class_='panel-body')
                if sidebar:
                    # Handle various formats for extracting torrent info
                    for div in sidebar.find_all('div', recursive=False):
                        b_tag = div.find('b')
                        if b_tag:
                            key = b_tag.get_text(strip=True).rstrip(':')
                            val = b_tag.next_sibling
                            if val:
                                val = val.strip().lstrip(':').strip()
                            else:
                                val = div.get_text(strip=True).replace(b_tag.get_text(strip=True), '').strip()
                            info_lines.append(f"{key}: {val}")
            
            # --- File list extraction ---
            file_list_div = soup.find('div', class_='torrent-file-list')
            if not file_list_div:
                return info_lines + ["No file list found."]
            
            def parse_ul(ul, prefix=""):
                items = []
                for li in ul.find_all('li', recursive=False):
                    folder_a = li.find('a', class_='folder')
                    sub_ul = li.find('ul', recursive=False)
                    if folder_a and sub_ul:
                        folder_name = folder_a.get_text(strip=True)
                        items.append(prefix + folder_name + "/")
                        items.extend(parse_ul(sub_ul, prefix + "    "))
                    else:
                        file_name = li.get_text(strip=True, separator=' ')
                        size_span = li.find('span', class_='file-size')
                        if size_span:
                            file_name = file_name.replace(size_span.text, '').strip()
                            file_name += f" ({size_span.text.strip()})"
                        items.append(prefix + file_name)
                return items
            
            root_ul = file_list_div.find('ul', recursive=False)
            if root_ul:
                file_tree.extend(parse_ul(root_ul))
            
            # Add info at the top
            file_tree = info_lines + [""] + file_tree
            return file_tree
        except Exception as e:
            return [f"Error: {e}"]
    
    def show_torrent_file_tree(self, torrent_page_url: str, rss_info: Optional[Dict[str, Any]] = None) -> bool:
        """Show the file tree for a torrent, allow Esc to return or 'd' to download."""
        file_tree = self.get_torrent_file_list(torrent_page_url)
        clear_screen()
        print("Torrent Info:")
        
        if rss_info:
            print(f"Title: {rss_info.get('title', 'N/A')}")
            print(f"Size: {rss_info.get('size', 'N/A')}")
            print(f"Category: {rss_info.get('category', 'N/A')}")
            print(f"Seeders: {rss_info.get('seeds', 'N/A')}")
            print(f"Leechers: {rss_info.get('leechers', 'N/A')}")
            print(f"Downloads: {rss_info.get('downloads', 'N/A')}")
            print(f"InfoHash: {rss_info.get('infohash', 'N/A')}")
            print(f"Date: {rss_info.get('published', 'N/A')}")
            print(f"Link: {rss_info.get('link', 'N/A')}")
            print(f"GUID: {rss_info.get('guid', 'N/A')}")
            print()
        else:
            print("No RSS info found.\n")
        
        # Avoid printing the title again if it's the first line in file_tree
        if file_tree and file_tree[0].strip().startswith('Title:'):
            file_tree = file_tree[1:]
        
        for line in file_tree:
            print(line)
        
        print("\n" + "=" * 60)
        print("📥 DOWNLOAD OPTIONS")
        print("=" * 60)
        print("Press 'd' to download this torrent")
        print("Press Esc to return to torrent list")
        
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b'\x1b':  # Esc
                    return False  # Don't download
                elif key.lower() == b'd':  # Download
                    return True   # Download requested
            import time
            time.sleep(0.05)


# Global instance
_nyaa_api = NyaaAPI()


# Legacy functions for backward compatibility
def nyaa_rss_search(anime_name: str, limit: int = 50) -> Union[List[Dict[str, Any]], str]:
    """Search nyaa.si RSS for torrents matching the anime name. (Legacy function)"""
    return _nyaa_api.search_torrents(anime_name, limit)


def sort_torrents(results: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
    """Sort torrent results by seeds or size. (Legacy function)"""
    return _nyaa_api.sort_torrents(results, sort_by)


def navigate_nyaa_results(results: List[Dict[str, Any]], window_size: int = 10) -> Union[Optional[Dict[str, Any]], str]:
    """Allow user to scroll through nyaa.si results. (Legacy function)"""
    return _nyaa_api.navigate_results(results, window_size)


def get_torrent_file_list(torrent_page_url: str) -> List[str]:
    """Scrape the torrent page to get the file list. (Legacy function)"""
    return _nyaa_api.get_torrent_file_list(torrent_page_url)


def show_torrent_file_tree(torrent_page_url: str, rss_info: Optional[Dict[str, Any]] = None) -> bool:
    """Show the file tree for a torrent. (Legacy function)"""
    return _nyaa_api.show_torrent_file_tree(torrent_page_url, rss_info)
