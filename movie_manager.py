"""
Movie management module for the Jellyfin Library Manager.
"""

import json
import os
import shutil
import time
import msvcrt
from urllib.parse import parse_qs, urlparse
from typing import List, Tuple, Dict, Any, Optional
from config import Colors
from utils import clear_screen, wait_for_enter, get_media_folder, validate_video_file, format_bytes
from ui import MenuSystem
from file_utils import find_existing_symlink, list_movies, create_movie_symlink, remove_symlink_safely
from custom_autocomplete import get_movie_file_with_custom_autocomplete, get_download_path_with_custom_autocomplete
from qbittorrent_api import (
    qb_check_connection, qb_login, qb_add_torrent, qb_get_search_plugins,
    qb_start_search, qb_get_search_status, qb_get_search_results, qb_delete_search, qb_get_torrent_info,
    qb_remove_torrent
)
from database import add_torrent_to_database, TorrentDatabase
from imdb_api import interactive_imdb_movie_selection


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
        metadata = interactive_imdb_movie_selection()
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

        preexisting_hashes = {
            str(torrent.get("hash", "") or "").strip().lower()
            for torrent in qb_get_torrent_info(session)
            if str(torrent.get("hash", "") or "").strip()
        }

        success = qb_add_torrent(session, torrent_link, download_path)
        if not success:
            self.menu_system.show_error("Failed to add torrent to qBittorrent.")
            return

        infohash, source_category = self._resolve_torrent_identity(session, selected, torrent_link, preexisting_hashes)
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
            "media_type": "movie",
            "media_metadata": metadata
        }
        torrent_id = add_torrent_to_database(torrent_info) if infohash != "N/A" else None

        clear_screen()
        print("✅ Torrent added successfully!")
        print(f"🎬 Movie: {metadata.get('title', 'Unknown')}")
        if torrent_id:
            print(f"🗃️  Database ID: #{torrent_id}")
        else:
            print("⚠️  Warning: Could not resolve a valid infohash, so this torrent was not added to the tracking database.")
        wait_for_enter()

    def _extract_infohash_from_link(self, torrent_link: str) -> str:
        """Extract a btih infohash directly from a magnet link when available."""
        parsed = urlparse(str(torrent_link or "").strip())
        if parsed.scheme.lower() != "magnet":
            return ""

        for xt_value in parse_qs(parsed.query).get("xt", []):
            xt_value = str(xt_value or "").strip()
            if xt_value.lower().startswith("urn:btih:"):
                return xt_value.split(":")[-1].strip()
        return ""

    def _to_int(self, value: Any) -> int:
        """Convert provider values to ints without raising on bad metadata."""
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _match_qb_torrent_hash(
        self,
        torrents: List[Dict[str, Any]],
        candidate_name: str,
        candidate_size: int,
        candidate_links: set[str],
        known_hashes: set[str]
    ) -> str:
        """Best-effort match for the torrent that was just added to qBittorrent."""
        candidates = []
        for torrent in torrents:
            torrent_hash = str(torrent.get("hash", "") or "").strip()
            normalized_hash = torrent_hash.lower()
            if not torrent_hash or normalized_hash in known_hashes:
                continue
            candidates.append(torrent)

            magnet = str(torrent.get("magnet_uri", "") or "")
            comment = str(torrent.get("comment", "") or "")
            blob = f"{magnet}\n{comment}"
            if candidate_links and any(link in blob for link in candidate_links):
                return torrent_hash

        exact_name_matches = [
            torrent for torrent in candidates
            if str(torrent.get("name", "") or "").strip().lower() == candidate_name
        ]
        if len(exact_name_matches) == 1:
            return str(exact_name_matches[0].get("hash", "") or "").strip()
        if exact_name_matches and candidate_size > 0:
            best_match = min(
                exact_name_matches,
                key=lambda torrent: abs(self._to_int(torrent.get("size", 0)) - candidate_size)
            )
            return str(best_match.get("hash", "") or "").strip()

        exact_size_matches = [
            torrent for torrent in candidates
            if self._to_int(torrent.get("size", 0)) == candidate_size and candidate_size > 0
        ]
        if len(exact_size_matches) == 1:
            return str(exact_size_matches[0].get("hash", "") or "").strip()

        if len(candidates) == 1:
            return str(candidates[0].get("hash", "") or "").strip()

        return ""

    def _resolve_torrent_identity(self, session, selected: Dict[str, Any], torrent_link: str, preexisting_hashes: Optional[set[str]] = None) -> Tuple[str, str]:
        """Resolve stable infohash and normalized source category for DB storage."""
        direct_hash = str(
            selected.get("fileHash")
            or selected.get("infohash")
            or selected.get("hash")
            or self._extract_infohash_from_link(torrent_link)
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
        candidate_size = self._to_int(selected.get("fileSize", 0))
        candidate_links = {
            str(torrent_link or "").strip(),
            str(selected.get("fileUrl", "") or "").strip(),
            str(selected.get("descrLink", "") or "").strip()
        }
        candidate_links = {c for c in candidate_links if c}
        known_hashes = {hash_value for hash_value in (preexisting_hashes or set()) if hash_value}

        # qB can take a moment before the newly added torrent appears in /torrents/info.
        for _ in range(20):
            torrents = qb_get_torrent_info(session)
            if torrents:
                matched_hash = self._match_qb_torrent_hash(torrents, candidate_name, candidate_size, candidate_links, known_hashes)
                if matched_hash:
                    return matched_hash, category

                if known_hashes:
                    matched_hash = self._match_qb_torrent_hash(torrents, candidate_name, candidate_size, candidate_links, set())
                    if matched_hash:
                        return matched_hash, category
            time.sleep(0.5)

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

    def _normalize_path(self, path_value: Optional[str]) -> str:
        """Normalize a filesystem path for comparisons."""
        if not isinstance(path_value, str) or not path_value.strip():
            return ""
        return os.path.abspath(path_value)

    def _find_associated_torrent_by_track_json(self, library_folder: str, tracked_torrents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Try to match a tracked movie torrent using the library track.json file."""
        track_path = os.path.join(library_folder, "track.json")
        if not os.path.exists(track_path):
            return None

        try:
            with open(track_path, "r", encoding="utf-8") as file_handle:
                track_data = json.load(file_handle)
        except Exception:
            return None

        track_infohash = str(track_data.get("infohash", "") or "").strip().lower()
        candidate_paths = {
            self._normalize_path(track_data.get("library_path")),
            self._normalize_path(track_data.get("source_download_path")),
            self._normalize_path(track_data.get("download_path")),
        }
        candidate_paths.discard("")

        for torrent in tracked_torrents:
            torrent_infohash = str(torrent.get("infohash", "") or "").strip().lower()
            if track_infohash and torrent_infohash == track_infohash:
                return torrent

            for path_key in ("library_path", "source_download_path", "download_path"):
                torrent_path = self._normalize_path(torrent.get(path_key))
                if torrent_path and torrent_path in candidate_paths:
                    return torrent

        return None

    def _find_associated_torrent(self, library_folder: str, target_path: str) -> Optional[Dict[str, Any]]:
        """Best-effort match for a tracked movie torrent."""
        tracked_torrents = [
            torrent for torrent in TorrentDatabase().get_tracked_torrents()
            if torrent.get("media_type") == "movie"
        ]

        associated_torrent = self._find_associated_torrent_by_track_json(library_folder, tracked_torrents)
        if associated_torrent:
            return associated_torrent

        candidate_paths = {self._normalize_path(library_folder)}
        normalized_target = self._normalize_path(target_path)
        if normalized_target:
            candidate_paths.add(normalized_target)
            candidate_paths.add(self._normalize_path(os.path.dirname(normalized_target)))
        candidate_paths.discard("")

        for torrent in tracked_torrents:
            for path_key in ("library_path", "source_download_path", "download_path"):
                torrent_path = self._normalize_path(torrent.get(path_key))
                if torrent_path and torrent_path in candidate_paths:
                    return torrent

        return None

    def _get_downloading_torrents(self) -> List[Dict[str, Any]]:
        """Get tracked movie torrents that are still downloading in qBittorrent."""
        downloading_torrents: List[Dict[str, Any]] = []
        tracked_torrents = [
            torrent for torrent in TorrentDatabase().get_tracked_torrents()
            if torrent.get("media_type") == "movie"
        ]
        qb_torrents: List[Dict[str, Any]] = []

        if qb_check_connection():
            session = qb_login()
            if session:
                qb_torrents = qb_get_torrent_info(session)

        active_states = {"completedDL", "uploading", "stalledUP", "queuedUP"}
        for tracked in tracked_torrents:
            tracked_hash = str(tracked.get("infohash", "") or "").strip().lower()
            if not tracked_hash or tracked_hash == "n/a":
                continue

            for qb_torrent in qb_torrents:
                qb_hash = str(qb_torrent.get("hash", "") or "").strip().lower()
                if qb_hash != tracked_hash:
                    continue

                if qb_torrent.get("state") not in active_states:
                    downloading_torrents.append({**tracked, **qb_torrent})
                break

        return downloading_torrents

    def _remove_downloading_torrent(self, downloading_torrents: List[Dict[str, Any]]) -> None:
        """Remove an active movie torrent directly from qBittorrent and the local database."""
        torrent_titles = [
            f"{torrent.get('title', torrent.get('name', 'Unknown'))} [{torrent.get('state', 'unknown')}]"
            for torrent in downloading_torrents
        ]
        torrent_titles.append("🔙 Back")

        torrent_choice = self.menu_system.navigate_menu(torrent_titles, "Select downloading movie torrent to remove")
        if torrent_choice == -1 or torrent_choice == len(torrent_titles) - 1:
            return

        selected_torrent = downloading_torrents[torrent_choice]
        torrent_title = selected_torrent.get("title", selected_torrent.get("name", "Unknown"))
        confirm = self.menu_system.confirm_action(
            f"Remove downloading torrent '{torrent_title}'?",
            ["❌ No", "🗑️  Yes"]
        )
        if not confirm:
            return

        session = qb_login()
        success = False
        if session:
            infohash = selected_torrent.get("hash") or selected_torrent.get("infohash")
            success = qb_remove_torrent(session, infohash, delete_files=True)

        infohash = str(selected_torrent.get("infohash", "") or "").strip()
        if infohash and infohash != "N/A":
            TorrentDatabase().remove_torrents_by_infohash(infohash)

        clear_screen()
        if success:
            print(f"🗑️  Removed downloading torrent '{torrent_title}'.")
        else:
            print("❌ Failed to remove torrent.")
        wait_for_enter()

    def _prompt_delete_original_movie(self, target_path: str) -> None:
        """Optionally delete the original movie source after library removal."""
        normalized_target = self._normalize_path(target_path)
        if not normalized_target or not os.path.exists(normalized_target):
            return

        delete_options = ["❌ No, keep original file", "🗑️  Yes, delete original file"]
        delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{normalized_target}'?")
        if delete_choice != 1:
            return

        try:
            if os.path.isdir(normalized_target):
                shutil.rmtree(normalized_target)
            else:
                os.remove(normalized_target)
            clear_screen()
            print(f"🗑️  Deleted original file '{normalized_target}'.")
        except Exception as e:
            clear_screen()
            print(f"❌ Error deleting original file: {e}")
    
    def remove_movie(self) -> None:
        """Remove a movie from the library."""
        movies = list_movies()
        downloading_torrents = self._get_downloading_torrents()

        if not movies and not downloading_torrents:
            self.menu_system.show_message("\n📁 No movies found in your Jellyfin library.")
            return

        # Create menu options
        movie_options = []
        for i, (name, symlink_path, target_path) in enumerate(movies, 1):
            status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
            movie_options.append(f"{i:3d}. {name} {status}")

        if downloading_torrents:
            movie_options.append("⬇️  Remove downloading torrents...")
        movie_options.append("🔙 Back to main menu")

        # Navigate through movies
        choice = self.menu_system.navigate_menu(movie_options, "🗑️  REMOVE MOVIE OR TORRENT")

        if choice == -1 or choice == len(movie_options) - 1:  # Esc pressed or Back selected
            return

        if downloading_torrents and choice == len(movie_options) - 2:
            self._remove_downloading_torrent(downloading_torrents)
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
            associated_torrent = self._find_associated_torrent(subfolder, target_path)

            if remove_symlink_safely(subfolder):
                clear_screen()
                print(f"✅ Removed movie '{movie_name}' from library.")

                if associated_torrent:
                    infohash = str(associated_torrent.get("infohash", "") or "").strip()
                    if infohash and infohash != "N/A":
                        TorrentDatabase().remove_torrents_by_infohash(infohash)

                    torrent_title = associated_torrent.get("title", associated_torrent.get("name", "Unknown"))
                    if infohash and infohash != "N/A":
                        remove_options = [
                            "❌ No, keep torrent in qBittorrent",
                            "🗑️  Yes, remove torrent from qBittorrent (optionally delete files)"
                        ]
                        remove_choice = self.menu_system.navigate_menu(
                            remove_options,
                            f"🗑️  Also remove torrent '{torrent_title}' from qBittorrent?"
                        )
                        if remove_choice == 1:
                            delete_files_options = [
                                "❌ No, keep files on disk",
                                "🗑️  Yes, delete files from disk"
                            ]
                            delete_files_choice = self.menu_system.navigate_menu(
                                delete_files_options,
                                f"🗑️  Delete files for torrent '{torrent_title}'?"
                            )
                            delete_files = delete_files_choice == 1
                            session = qb_login()
                            success = False
                            if session:
                                success = qb_remove_torrent(session, infohash, delete_files)
                            clear_screen()
                            if success:
                                print(f"🗑️  Removed torrent '{torrent_title}' from qBittorrent.")
                            else:
                                print("❌ Failed to remove torrent from qBittorrent.")
                        else:
                            clear_screen()
                            print(f"✅ Removed movie '{movie_name}' from library.")
                            print(f"❌ Kept torrent '{torrent_title}' in qBittorrent.")

                if target_path != "BROKEN LINK":
                    self._prompt_delete_original_movie(target_path)

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
