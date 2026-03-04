"""
Movie management module for the Jellyfin Library Manager.
"""

import os
import shutil
import time
from typing import List, Tuple, Dict, Any, Optional
from config import Colors
from utils import clear_screen, wait_for_enter, get_media_folder, validate_video_file, format_bytes
from ui import MenuSystem
from file_utils import find_existing_symlink, list_movies, create_movie_symlink, remove_symlink_safely
from custom_autocomplete import get_movie_file_with_custom_autocomplete, get_download_path_with_custom_autocomplete
from qbittorrent_api import (
    qb_check_connection, qb_login, qb_add_torrent, qb_get_search_plugins,
    qb_start_search, qb_get_search_status, qb_get_search_results, qb_delete_search
)
from database import add_torrent_to_database
from tmdb_api import interactive_tmdb_movie_selection


class MovieManager:
    """Class to handle movie management operations."""
    
    def __init__(self):
        self.menu_system = MenuSystem()
    
    def display_movies(self) -> None:
        """Display all movies in the library."""
        movies = list_movies()
        
        if not movies:
            self.menu_system.show_message("\n📁 No movies found in your Jellyfin library.")
            return
        
        clear_screen()
        print(f"\n📚 Your Jellyfin Library ({len(movies)} movies):")
        print("=" * 60)
        
        for i, (name, symlink_path, target_path) in enumerate(movies, 1):
            status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
            # Use cyan color for movie title
            print(f"{i:3d}. {Colors.CYAN}{name}{Colors.RESET}")
            print(f"     📍 Symlink: {Colors.YELLOW}{symlink_path}{Colors.RESET}")
            if target_path != "BROKEN LINK":
                print(f"     🎬 Target:  {Colors.GREEN}{target_path}{Colors.RESET}")
            else:
                print(f"     🎬 Target:  {Colors.RED}BROKEN LINK{Colors.RESET}")
            print(f"     {status}")
            print()
        
        wait_for_enter()
    
    def add_movie(self) -> None:
        """Add a new movie to the library."""
        source_options = [
            "📁 Add from local file",
            "🌐 Download movie (qBittorrent Search API)"
        ]
        source_choice = self.menu_system.navigate_menu(source_options, "🎬 Add New Movie")
        if source_choice == -1:
            self.menu_system.show_message("\n❌ Cancelled.")
            return
        if source_choice == 0:
            self._add_movie_from_local_file()
        elif source_choice == 1:
            self._add_movie_via_download()

    def _add_movie_from_local_file(self) -> None:
        """Add a local movie file to the library."""
        # Use the new custom autocomplete system
        movie_path = get_movie_file_with_custom_autocomplete()
        
        if not movie_path or not movie_path.strip():
            print("❌ No file path provided.")
            wait_for_enter()
            return
        
        # Clean up the path (no quotes needed with custom system)
        movie_path = movie_path.strip()
        
        if not validate_video_file(movie_path):
            wait_for_enter()
            return
        
        # Convert to absolute path for processing
        movie_path = os.path.abspath(movie_path)
        
        # Check if movie already exists
        from utils import get_all_media_folders
        media_folders = get_all_media_folders()
        existing_symlink, existing_subfolder = find_existing_symlink(movie_path, media_folders)
        
        if existing_symlink:
            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            print(f"⚠️  Movie '{movie_name}' already exists at '{existing_symlink}'.")
            
            action_options = ["⏭️  Skip", "🔄 Overwrite existing"]
            action_choice = self.menu_system.navigate_menu(action_options, f"Movie '{movie_name}' already exists")
            
            if action_choice == 0:  # Skip
                self.menu_system.show_message("⏭️  Skipping.")
                return
            elif action_choice == 1:  # Overwrite
                shutil.rmtree(existing_subfolder, ignore_errors=True)
                clear_screen()
                print(f"🗑️  Removed existing subfolder '{existing_subfolder}'.")
            else:
                self.menu_system.show_message("❌ Cancelled.")
                return
        
        # Create new symlink
        media_folder = get_media_folder(movie_path)
        success, result = create_movie_symlink(movie_path, media_folder)
        
        if success:
            clear_screen()
            print(f"✅ Success: Symlink created at '{result}'.")
            print(f"🔗 The symlink points to: {movie_path}")
            print("💡 The original file must remain in place for Jellyfin to access it.")
            wait_for_enter()
        else:
            clear_screen()
            print(f"❌ Error creating symlink: {result}")
            print("💡 Ensure script is run as administrator.")
            wait_for_enter()

    def _add_movie_via_download(self) -> None:
        """Search and download movie torrents via qBittorrent search API."""
        metadata = interactive_tmdb_movie_selection()
        if not metadata:
            self.menu_system.show_message("❌ No movie metadata selected or cancelled.")
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
        search_id = qb_start_search(session, query, category="movies", plugins="enabled")
        if search_id is None:
            search_id = qb_start_search(session, query, category="all", plugins="enabled")
        if search_id is None:
            self.menu_system.show_error("Failed to start qBittorrent search.")
            return

        results = self._collect_search_results(session, search_id, query=query)
        qb_delete_search(session, search_id)
        if not results:
            self.menu_system.show_message("No torrent results found for this movie.")
            return

        selected = self._select_search_result(results, f"🎬 Select torrent for '{metadata.get('title', 'Movie')}'")
        if not selected:
            self.menu_system.show_message("❌ Cancelled.")
            return

        self._download_selected_torrent(session, selected, metadata)

    def _show_search_progress(self, query: str, status: str, results: List[Dict[str, Any]], elapsed: int, wait_seconds: int) -> None:
        """Render live qBittorrent search progress with a rolling preview."""
        clear_screen()
        print(f"🔎 Searching qBittorrent for: {query}")
        print(f"⏳ Status: {status.upper()} | Elapsed: {elapsed}s/{wait_seconds}s | Results: {len(results)}")
        print("💡 Results update live while search is running.\n")

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

            time.sleep(1)
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

        torrent_info = {
            "title": name,
            "size": str(selected.get("fileSize", "Unknown")),
            "seeds": int(selected.get("nbSeeders", 0) or 0),
            "leechers": int(selected.get("nbLeechers", 0) or 0),
            "downloads": int(selected.get("nbDownloads", 0) or 0),
            "infohash": selected.get("fileHash", "N/A"),
            "category": selected.get("siteUrl", "qBittorrent Search"),
            "link": torrent_link,
            "download_path": download_path or "Default",
            "source_download_path": download_path or "Default",
            "library_path": "",
            "media_type": "movie",
            "media_metadata": metadata
        }
        torrent_id = add_torrent_to_database(torrent_info)

        clear_screen()
        print("✅ Torrent added successfully!")
        print(f"🎬 Movie: {metadata.get('title', 'Unknown')}")
        if torrent_id:
            print(f"🗃️  Database ID: #{torrent_id}")
        wait_for_enter()

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
            elif create_choice == 1:
                try:
                    os.makedirs(download_path, exist_ok=True)
                    clear_screen()
                    print(f"📁 Created directory: {download_path}")
                    return download_path
                except Exception as e:
                    self.menu_system.show_error(f"Failed to create directory: {e}")
                    return None
            else:
                return None

        return download_path
    
    def remove_movie(self) -> None:
        """Remove a movie from the library."""
        movies = list_movies()
        
        if not movies:
            self.menu_system.show_message("\n📁 No movies found in your Jellyfin library.")
            return
        
        # Create menu options
        movie_options = []
        for i, (name, symlink_path, target_path) in enumerate(movies, 1):
            status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
            movie_options.append(f"{i:3d}. {name} {status}")
        
        movie_options.append("🔙 Back to main menu")
        
        # Navigate through movies
        choice = self.menu_system.navigate_menu(movie_options, "🗑️  REMOVE MOVIE")
        
        if choice == -1 or choice == len(movies):  # Esc pressed or Back selected
            return
        
        if 0 <= choice < len(movies):
            movie_name, symlink_path, target_path = movies[choice]
            
            clear_screen()
            print(f"\n🎬 Selected: {movie_name}")
            print(f"📍 Symlink: {symlink_path}")
            if target_path != "BROKEN LINK":
                print(f"🎬 Target: {target_path}")
            
            # Confirm removal
            if not self.menu_system.confirm_action(f"❓ Remove '{movie_name}' from library?"):
                self.menu_system.show_message("⏭️  Cancelled.")
                return
            
            # Remove the subfolder (contains the symlink)
            subfolder = os.path.dirname(symlink_path)
            
            if remove_symlink_safely(subfolder):
                clear_screen()
                print(f"✅ Removed movie '{movie_name}' from library.")
                
                # Ask about original file
                if target_path != "BROKEN LINK" and os.path.exists(target_path):
                    delete_options = ["❌ No, keep original file", "🗑️  Yes, delete original file"]
                    delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                    
                    if delete_choice == 1:  # Yes, delete
                        try:
                            os.remove(target_path)
                            clear_screen()
                            print(f"🗑️  Deleted original file '{target_path}'.")
                        except Exception as e:
                            clear_screen()
                            print(f"❌ Error deleting original file: {e}")
                
                wait_for_enter()


# Global instance for backward compatibility
_movie_manager = MovieManager()


# Legacy functions for backward compatibility
def display_movies() -> None:
    """Display all movies in the library. (Legacy function)"""
    _movie_manager.display_movies()


def add_movie() -> None:
    """Add a new movie to the library. (Legacy function)"""
    _movie_manager.add_movie()


def remove_movie() -> None:
    """Remove a movie from the library. (Legacy function)"""
    _movie_manager.remove_movie()
