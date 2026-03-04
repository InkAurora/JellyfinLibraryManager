"""
Series management module for the Jellyfin Library Manager.
"""

import os
import time
import msvcrt
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple
from config import Colors
from utils import clear_screen, wait_for_enter, validate_directory, is_episode_file, format_bytes
from ui import MenuSystem
from file_utils import list_series, create_series_symlinks, remove_symlink_safely
from imdb_api import interactive_imdb_series_selection
from qbittorrent_api import (
    qb_check_connection, qb_login, qb_add_torrent, qb_get_search_plugins,
    qb_start_search, qb_get_search_status, qb_get_search_results, qb_delete_search, qb_get_torrent_info
)
from database import add_torrent_to_database, get_tracked_torrents, remove_torrent_from_database_by_infohash
from custom_autocomplete import (
    get_series_folder_with_custom_autocomplete,
    get_download_path_with_custom_autocomplete
)


class SeriesManager:
    """Class to handle series management operations."""

    def __init__(self):
        self.menu_system = MenuSystem()

    def display_series(self) -> None:
        """Display all series in the library grouped by season."""
        series_list = list_series()

        if not series_list:
            self.menu_system.show_message("\n📺 No series found in your library.")
            return

        clear_screen()
        print(f"\n📺 Your Series Library ({len(series_list)} series):")
        print("=" * 60)

        for i, (series_name, seasons) in enumerate(series_list, 1):
            total_episodes = 0
            broken_seasons = 0
            print(f"{i:3d}. {Colors.MAGENTA}{series_name}{Colors.RESET}")

            for season_name, season_path, target_path in seasons:
                if os.path.exists(season_path):
                    episode_files = [
                        f for f in os.listdir(season_path)
                        if os.path.isfile(os.path.join(season_path, f)) and is_episode_file(f)
                    ]
                    total_episodes += len(episode_files)

                status = "❌ BROKEN" if target_path in ["BROKEN LINK", "ACCESS DENIED", "NO_SYMLINKS", "EMPTY"] else "✅ OK"
                if status == "❌ BROKEN":
                    broken_seasons += 1

                season_label = "Specials" if season_name == "Season 00" else season_name
                print(f"     📍 {Colors.YELLOW}{season_label}{Colors.RESET}: {status}")

            print(f"     📊 Total Episodes: {total_episodes}")
            if broken_seasons > 0:
                print(f"     ⚠️  Broken Seasons: {broken_seasons}")
            print()

        wait_for_enter()

    def add_series(self) -> None:
        """Add a new series to the library."""
        clear_screen()
        print("\n📺 Add New Series")
        print("=" * 35)

        source_options = [
            "📁 Add from local files",
            "🌐 Download series (qBittorrent Search API)"
        ]
        source_choice = self.menu_system.navigate_menu(source_options, "Select series source")
        if source_choice == -1:
            self.menu_system.show_message("\n❌ Cancelled.")
            return

        if source_choice == 0:
            self._add_series_from_local_files()
        elif source_choice == 1:
            self._add_series_via_download()

    def _add_series_from_local_files(self) -> None:
        """Add series from local files."""
        series_folder_path = get_series_folder_with_custom_autocomplete()

        if not series_folder_path or not series_folder_path.strip():
            print("❌ No folder path provided.")
            wait_for_enter()
            return

        series_folder_path = series_folder_path.strip()
        if not validate_directory(series_folder_path):
            wait_for_enter()
            return

        series_folder_path = os.path.abspath(series_folder_path)
        episode_files = [
            f for f in os.listdir(series_folder_path)
            if os.path.isfile(os.path.join(series_folder_path, f)) and is_episode_file(f)
        ]
        if not episode_files:
            self.menu_system.show_error(f"No video files found in '{series_folder_path}'.")
            return

        series_name = self.menu_system.get_user_input("Enter the name for this series: ")
        if not series_name:
            self.menu_system.show_error("No series name provided.")
            return

        season_input = self.menu_system.get_user_input("Enter season number (leave empty for Season 01): ")
        if not season_input:
            season_number = 1
        else:
            try:
                season_number = int(season_input)
                if season_number <= 0:
                    self.menu_system.show_error("Season number must be a positive integer.")
                    return
            except ValueError:
                self.menu_system.show_error("Invalid season number.")
                return

        success, result, episode_files_linked, extras_linked = create_series_symlinks(
            series_folder_path, series_name, season_number
        )
        if success:
            clear_screen()
            print(f"✅ Success: Series symlinks created at '{result}'.")
            print(f"🔗 Main season contains {episode_files_linked} episode file symlinks")
            if extras_linked > 0:
                print(f"🎁 Extras linked: {extras_linked} video file(s) -> Season 00")
            wait_for_enter()
        else:
            clear_screen()
            print(f"❌ Error creating series symlink: {result}")
            wait_for_enter()

    def _add_series_via_download(self) -> None:
        """Search and download series torrents via qBittorrent search API."""
        metadata = interactive_imdb_series_selection()
        if not metadata:
            self.menu_system.show_message("❌ No series metadata selected or cancelled.")
            return

        if not qb_check_connection():
            self.menu_system.show_error("Cannot connect to qBittorrent.")
            return

        session = qb_login()
        if not session:
            self.menu_system.show_error("Failed to authenticate with qBittorrent.")
            return

        plugins = qb_get_search_plugins(session)
        if not plugins:
            self.menu_system.show_error(
                "No qBittorrent search plugins available.\n"
                "💡 Enable and install search plugins in qBittorrent first."
            )
            return

        query = f"{metadata.get('title', '')} {metadata.get('year', '')}".strip()
        clear_screen()
        print(f"🔎 Searching qBittorrent for: {query}")
        search_id = qb_start_search(session, query, category="tv", plugins="enabled")
        if search_id is None:
            search_id = qb_start_search(session, query, category="all", plugins="enabled")
        if search_id is None:
            self.menu_system.show_error("Failed to start qBittorrent search.")
            return

        results = self._collect_search_results(session, search_id, query=query)
        qb_delete_search(session, search_id)
        if not results:
            self.menu_system.show_message("No torrent results found for this series.")
            return

        selected = self._select_search_result(results, f"📺 Select torrent for '{metadata.get('title', 'Series')}'")
        if not selected:
            self.menu_system.show_message("❌ Cancelled.")
            return

        self._download_selected_torrent(session, selected, metadata)

    def _show_search_progress(self, query: str, status: str, results: List[Dict[str, Any]], elapsed: int, wait_seconds: int) -> None:
        """Render live qBittorrent search progress with a rolling preview."""
        clear_screen()
        print(f"🔎 Searching qBittorrent for: {query}")
        print(f"⏳ Status: {status.upper()} | Elapsed: {elapsed}s/{wait_seconds}s | Results: {len(results)}")
        print("💡 Results update live while search is running.")
        print("💡 Press Esc to stop waiting and show current results.\n")

        if not results:
            print("No results yet...")
            return

        print(f"{'#':<3} {'Seeds':<7} Result")
        print("-" * 70)
        for i, item in enumerate(results[:8], 1):
            seeds = int(item.get("nbSeeders", 0) or 0)
            name = str(item.get("fileName", "Unknown"))
            short_name = name if len(name) <= 56 else name[:53] + "..."
            print(f"{i:<3} {seeds:<7} {short_name}")

    def _collect_search_results(self, session, search_id: int, wait_seconds: int = 30, query: str = "") -> List[Dict[str, Any]]:
        """Collect search results for a qBittorrent search job."""
        elapsed = 0
        best_results: List[Dict[str, Any]] = []
        previous_count = 0
        idle_seconds = 0
        status = "running"

        while elapsed < wait_seconds:
            status_items = qb_get_search_status(session, search_id)
            current_results = qb_get_search_results(session, search_id, limit=100, offset=0)

            if len(current_results) >= len(best_results):
                best_results = current_results

            current_count = len(best_results)
            if current_count > previous_count:
                previous_count = current_count
                idle_seconds = 0
            else:
                idle_seconds += 1

            status = "running"
            if status_items:
                status = str(status_items[0].get("status", "running")).lower()

            # Render every poll tick so the elapsed timer and preview stay visibly active.
            self._show_search_progress(query, status, best_results, elapsed, wait_seconds)

            is_running = status in ["running", "queued"]
            if status == "error":
                break

            # Allow extra idle time after non-running status so late result batches still appear.
            if not is_running and status in ["stopped", "finished"] and idle_seconds >= 5 and elapsed >= 5:
                break

            # Safety fallback when search status API is empty/unavailable.
            if not status_items and best_results and idle_seconds >= 8 and elapsed >= 10:
                break
            if not status_items and not best_results and elapsed >= 12:
                break

            # Sleep in short slices so Esc can cancel promptly.
            cancel_requested = False
            for _ in range(10):
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key in (b'\x00', b'\xe0') and msvcrt.kbhit():
                        msvcrt.getch()  # consume multi-byte key suffix
                    elif key == b'\x1b':  # Esc
                        cancel_requested = True
                        break
                time.sleep(0.1)
            if cancel_requested:
                break
            elapsed += 1

        self._show_search_progress(query, status, best_results, elapsed, wait_seconds)
        best_results.sort(key=lambda r: int(r.get("nbSeeders", 0) or 0), reverse=True)
        return best_results

    def _select_search_result(self, results: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
        """Show torrent results and return the selected one."""
        def _seeds(item: Dict[str, Any]) -> int:
            try:
                return int(item.get("nbSeeders", 0) or 0)
            except (TypeError, ValueError):
                return 0

        def _size(item: Dict[str, Any]) -> int:
            try:
                return int(item.get("fileSize", 0) or 0)
            except (TypeError, ValueError):
                return 0

        def _row(item: Dict[str, Any]) -> str:
            seeds = _seeds(item)
            raw_size = _size(item)
            try:
                size = format_bytes(int(raw_size))
            except (TypeError, ValueError):
                size = str(raw_size)
            name = str(item.get("fileName", "Unknown"))
            short_name = name if len(name) <= 90 else name[:87] + "..."
            return f"[S:{seeds:>4}] [Size:{size:>9}] {short_name}"

        choice = self.menu_system.navigate_search_results(
            items=results,
            title=title,
            row_formatter=_row,
            seeds_extractor=_seeds,
            size_extractor=_size,
            page_size=12
        )
        if choice == -1:
            return {}
        return results[choice]

    def _download_selected_torrent(self, session, selected: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        """Add selected torrent to qBittorrent and tracking database."""
        clear_screen()
        name = selected.get("fileName", "Unknown")
        print(f"📥 Download Torrent: {name}")
        print("=" * 60)
        print(f"🌱 Seeds: {selected.get('nbSeeders', 0)}")
        print(f"📊 Size: {selected.get('fileSize', 0)}")
        print()

        if not self.menu_system.confirm_action("📥 Confirm Download"):
            return

        download_options = [
            "📁 Use default download location",
            "📂 Specify custom download path"
        ]
        location_choice = self.menu_system.navigate_menu(download_options, "📁 Download Location")
        download_path = None
        if location_choice == 1:
            download_path = self._get_custom_download_path()
            if download_path is None:
                return

        torrent_link = selected.get("fileUrl") or selected.get("descrLink")
        if not torrent_link:
            self.menu_system.show_error("Selected result does not include a downloadable URL.")
            return

        success = qb_add_torrent(session, torrent_link, download_path)
        if not success:
            self.menu_system.show_error("Failed to add torrent to qBittorrent.")
            return

        infohash, source_category = self._resolve_torrent_identity(session, selected, torrent_link)
        torrent_info = {
            "title": name,
            "size": str(selected.get("fileSize", "Unknown")),
            "seeds": int(selected.get("nbSeeders", 0) or 0),
            "leechers": int(selected.get("nbLeechers", 0) or 0),
            "downloads": int(selected.get("nbDownloads", 0) or 0),
            "infohash": infohash,
            "category": source_category,
            "link": torrent_link,
            "download_path": download_path or "Default",
            "source_download_path": download_path or "Default",
            "library_path": "",
            "media_type": "series",
            "media_metadata": metadata
        }
        torrent_id = add_torrent_to_database(torrent_info)

        clear_screen()
        print("✅ Torrent added successfully!")
        print(f"📺 Series: {metadata.get('title', 'Unknown')}")
        if torrent_id:
            print(f"🗃️  Database ID: #{torrent_id}")
        wait_for_enter()

    def _resolve_torrent_identity(self, session, selected: Dict[str, Any], torrent_link: str) -> Tuple[str, str]:
        """Resolve stable infohash and normalized source category for DB storage."""
        direct_hash = str(
            selected.get("fileHash")
            or selected.get("infohash")
            or selected.get("hash")
            or ""
        ).strip()
        infohash = direct_hash if direct_hash and direct_hash.upper() != "N/A" else "N/A"

        site_url = str(selected.get("siteUrl") or selected.get("descrLink") or selected.get("fileUrl") or "").strip()
        if site_url:
            parsed = urlparse(site_url)
            host = parsed.netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            category = host or "qBittorrent Search"
        else:
            category = "qBittorrent Search"

        if infohash != "N/A":
            return infohash, category

        candidate_name = str(selected.get("fileName", "") or "").strip().lower()
        candidate_links = {
            str(torrent_link or "").strip(),
            str(selected.get("fileUrl", "") or "").strip(),
            str(selected.get("descrLink", "") or "").strip()
        }
        candidate_links = {c for c in candidate_links if c}

        # qB can take a moment before the newly added torrent appears in /torrents/info.
        for _ in range(10):
            torrents = qb_get_torrent_info(session)
            if torrents:
                # Strong match: URL appears in magnet/comment fields.
                for torrent in torrents:
                    torrent_hash = str(torrent.get("hash", "") or "").strip()
                    if not torrent_hash:
                        continue
                    magnet = str(torrent.get("magnet_uri", "") or "")
                    comment = str(torrent.get("comment", "") or "")
                    blob = f"{magnet}\n{comment}"
                    if any(link in blob for link in candidate_links):
                        return torrent_hash, category

                # Fallback: exact name match.
                name_matches = []
                if candidate_name:
                    for torrent in torrents:
                        torrent_name = str(torrent.get("name", "") or "").strip().lower()
                        torrent_hash = str(torrent.get("hash", "") or "").strip()
                        if torrent_hash and torrent_name == candidate_name:
                            name_matches.append(torrent_hash)
                    if len(name_matches) == 1:
                        return name_matches[0], category
            time.sleep(0.3)

        return "N/A", category

    def _get_custom_download_path(self) -> Optional[str]:
        """Get custom download path from user."""
        download_path = get_download_path_with_custom_autocomplete()
        if not download_path or not download_path.strip():
            return None
        download_path = download_path.strip()
        if not os.path.isdir(download_path):
            print(f"⚠️  Directory '{download_path}' does not exist.")
            create_options = ["❌ Cancel download", "📁 Create directory", "📂 Use default location"]
            create_choice = self.menu_system.navigate_menu(create_options, "Directory not found")

            if create_choice == 0:
                self.menu_system.show_message("❌ Download cancelled.")
                return None
            if create_choice == 1:
                try:
                    os.makedirs(download_path, exist_ok=True)
                    clear_screen()
                    print(f"📁 Created directory: {download_path}")
                    return download_path
                except Exception as e:
                    self.menu_system.show_error(f"Failed to create directory: {e}")
                    return None
            return None
        return download_path

    def remove_series(self) -> None:
        """Remove a series from the library."""
        series_list = list_series()
        if not series_list:
            self.menu_system.show_message("\n📺 No series found in your library.")
            return

        options = []
        for i, (series_name, seasons) in enumerate(series_list, 1):
            options.append(f"{i:3d}. {series_name} ({len(seasons)} season(s))")
        options.append("🔙 Back to main menu")

        choice = self.menu_system.navigate_menu(options, "🗑️  REMOVE SERIES")
        if choice == -1 or choice == len(options) - 1:
            return

        series_name, seasons = series_list[choice]
        first_season_path = seasons[0][1]
        series_main_folder = os.path.dirname(first_season_path)

        if not self.menu_system.confirm_action(f"❓ Remove '{series_name}' from library?"):
            self.menu_system.show_message("⏭️  Cancelled.")
            return

        if remove_symlink_safely(series_main_folder):
            for torrent in get_tracked_torrents():
                torrent_library_path = torrent.get("library_path", "")
                if os.path.abspath(torrent_library_path) == os.path.abspath(series_main_folder):
                    infohash = torrent.get("infohash")
                    if infohash and infohash != "N/A":
                        remove_torrent_from_database_by_infohash(infohash)
            clear_screen()
            print(f"✅ Removed series '{series_name}' from library.")
        else:
            clear_screen()
            print(f"❌ Failed to remove series '{series_name}'.")
        wait_for_enter()


_series_manager = SeriesManager()


def display_series() -> None:
    """Display all series in the library. (Legacy function)"""
    _series_manager.display_series()


def add_series() -> None:
    """Add a new series to the library. (Legacy function)"""
    _series_manager.add_series()


def remove_series() -> None:
    """Remove a series from the library. (Legacy function)"""
    _series_manager.remove_series()
