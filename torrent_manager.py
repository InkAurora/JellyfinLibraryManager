"""
Torrent management module for the Jellyfin Library Manager.
"""

import json
import os
import re
import shutil
import threading
from typing import List, Dict, Any, Tuple, Optional
from qbittorrent_api import qb_check_connection, qb_login, qb_get_torrent_info, qb_get_torrent_files
from database import get_tracked_torrents, update_torrent_status, update_torrent_paths, remove_torrent_from_database_by_infohash
from utils import (
    is_episode_file,
    is_video_file,
    get_all_media_folders,
    get_anime_folder,
    get_series_folder,
    get_media_folder,
)
from file_utils import create_movie_symlink
from ffprobe_utils import probe_video_duration


_library_file_lock = threading.RLock()


def sanitize_filename(name: str) -> str:
    """Replace forbidden characters in a single filename or folder name with a space."""
    forbidden = r'[\\/:*?"<>|]'
    return re.sub(forbidden, ' ', name).strip()


class TorrentManager:
    """Class to handle torrent management operations."""
    
    def __init__(self):
        self.last_import_error = ""

    def _write_tracking_file(self, torrent: Dict[str, Any], download_path: str, library_path: str) -> None:
        """Persist track.json for a completed torrent library entry."""
        track_path = os.path.join(library_path, "track.json")
        try:
            track_torrent = torrent.copy()
            track_torrent["source_download_path"] = download_path
            track_torrent["download_path"] = download_path
            track_torrent["library_path"] = library_path
            with _library_file_lock:
                with open(track_path, "w", encoding="utf-8") as file_handle:
                    json.dump(track_torrent, file_handle, indent=2)
        except Exception as e:
            print(f"⚠️  Warning: Could not save tracking info: {e}")

    def _collect_video_files(self, download_path: str) -> List[str]:
        """Collect video files from a completed torrent path."""
        if os.path.isfile(download_path):
            return [download_path] if is_video_file(download_path) else []

        if not os.path.isdir(download_path):
            return []

        video_files = []
        for root, _, files in os.walk(download_path):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if is_video_file(file_path):
                    video_files.append(file_path)
        return video_files

    def _normalize_qb_path(self, path: Any) -> str:
        """Normalize qBittorrent paths and drop placeholder values."""
        normalized_path = str(path or "").strip().strip('"')
        if not normalized_path or normalized_path.lower() == "unknown":
            return ""
        return os.path.abspath(os.path.normpath(normalized_path))

    def _resolve_completed_torrent_path(self, torrent: Dict[str, Any]) -> str:
        """Resolve the on-disk root path for a completed torrent."""
        candidate_paths: List[str] = []
        content_path = self._normalize_qb_path(torrent.get("qb_content_path"))
        save_path = self._normalize_qb_path(torrent.get("qb_save_path"))
        torrent_name = str(torrent.get("qb_name", "") or "").strip()

        if content_path:
            candidate_paths.append(content_path)
        if save_path and torrent_name:
            candidate_paths.append(os.path.abspath(os.path.join(save_path, torrent_name)))

        seen = set()
        for candidate in candidate_paths:
            if candidate in seen:
                continue
            seen.add(candidate)
            if os.path.exists(candidate):
                return candidate

        return ""

    def _resolve_torrent_file_paths(self, torrent: Dict[str, Any]) -> List[str]:
        """Resolve absolute file paths for a torrent via qBittorrent's file list."""
        infohash = str(torrent.get("infohash", "") or "").strip()
        save_path = self._normalize_qb_path(torrent.get("qb_save_path"))
        content_path = self._normalize_qb_path(torrent.get("qb_content_path"))
        if not infohash or not save_path:
            return []

        session = qb_login()
        if not session:
            return []

        resolved_paths: List[str] = []
        for qb_file in qb_get_torrent_files(session, infohash):
            relative_name = str(qb_file.get("name", "") or "").strip().replace("/", os.sep)
            if not relative_name:
                continue

            candidate_paths: List[str] = []
            if content_path:
                if os.path.isdir(content_path):
                    candidate_paths.append(os.path.join(content_path, relative_name))
                elif os.path.isfile(content_path):
                    candidate_paths.append(content_path)
                else:
                    candidate_paths.append(os.path.join(os.path.dirname(content_path), relative_name))
            candidate_paths.append(os.path.join(save_path, relative_name))

            for candidate in candidate_paths:
                normalized_candidate = os.path.abspath(os.path.normpath(candidate))
                if os.path.isfile(normalized_candidate):
                    resolved_paths.append(normalized_candidate)
                    break

        unique_paths: List[str] = []
        seen = set()
        for resolved_path in resolved_paths:
            if resolved_path in seen:
                continue
            seen.add(resolved_path)
            unique_paths.append(resolved_path)
        return unique_paths

    def _select_primary_movie_file_from_candidates(self, download_path: str, candidate_files: List[str]) -> Optional[str]:
        """Select the main movie file from a torrent-specific file list."""
        video_files = [
            os.path.abspath(file_path)
            for file_path in candidate_files
            if file_path and os.path.isfile(file_path) and is_video_file(file_path)
        ]
        if not video_files:
            return None

        sort_root = download_path if download_path else os.path.dirname(video_files[0])
        return min(video_files, key=lambda file_path: self._get_movie_candidate_sort_key(file_path, sort_root))

    def _resolve_primary_movie_source_path(self, torrent: Dict[str, Any]) -> str:
        """Resolve the primary movie file for a completed torrent."""
        resolved_torrent_path = self._resolve_completed_torrent_path(torrent)
        torrent_file_paths = self._resolve_torrent_file_paths(torrent)
        if torrent_file_paths:
            movie_file = self._select_primary_movie_file_from_candidates(
                resolved_torrent_path or self._normalize_qb_path(torrent.get("qb_save_path")),
                torrent_file_paths,
            )
            if movie_file:
                return movie_file

        if resolved_torrent_path:
            movie_file = self._select_primary_movie_file(resolved_torrent_path)
            if movie_file:
                return movie_file

        return ""

    def _get_movie_candidate_sort_key(self, file_path: str, download_path: str) -> Tuple[int, int, int, int, str]:
        """Build a deterministic sort key for selecting a primary movie file."""
        file_name = os.path.basename(file_path).lower()
        if os.path.isdir(download_path):
            rel_path = os.path.relpath(file_path, download_path)
            depth = max(0, rel_path.count(os.sep))
        else:
            depth = 0

        extra_pattern = re.compile(
            r'(^|[\W_])(sample|trailer|teaser|featurette|extras?|behind[\W_]*the[\W_]*scenes|interview|deleted[\W_]*scenes?|clip|preview)([\W_]|$)',
            re.IGNORECASE,
        )
        is_extra = 1 if extra_pattern.search(file_name) else 0

        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0

        ext = os.path.splitext(file_name)[1]
        ext_rank = {'.mkv': 0, '.mp4': 1, '.avi': 2}.get(ext, 3)
        return (is_extra, depth, -file_size, ext_rank, file_name)

    def _select_primary_movie_file(self, download_path: str) -> Optional[str]:
        """Select the most likely main movie file from a completed torrent."""
        video_files = self._collect_video_files(download_path)
        if not video_files:
            return None
        return min(video_files, key=lambda file_path: self._get_movie_candidate_sort_key(file_path, download_path))

    def add_completed_movie_to_library(self, torrent: Dict[str, Any], download_path: str) -> Optional[str]:
        """Add a completed movie torrent to the movie library and return its library folder."""
        self.last_import_error = ""
        try:
            movie_file = self._select_primary_movie_file(download_path)
            if not movie_file:
                self.last_import_error = f"No movie file found for completed torrent '{torrent.get('title', 'Unknown')}'."
                print(f"⚠️  Warning: No movie file found for completed torrent '{torrent.get('title', 'Unknown')}'.")
                return None

            media_folder = get_media_folder(movie_file)
            movie_name = os.path.splitext(os.path.basename(movie_file))[0]
            movie_folder = os.path.join(media_folder, movie_name)
            symlink_path = os.path.join(movie_folder, os.path.basename(movie_file))

            if os.path.exists(symlink_path):
                if not os.path.islink(symlink_path):
                    self.last_import_error = f"Existing movie library entry is not a symlink: '{symlink_path}'."
                    print(f"⚠️  Warning: Existing movie library entry is not a symlink: '{symlink_path}'.")
                    return None
                try:
                    existing_target = os.readlink(symlink_path)
                except OSError as e:
                    self.last_import_error = f"Could not inspect existing movie symlink '{symlink_path}': {e}"
                    print(f"⚠️  Warning: Could not inspect existing movie symlink '{symlink_path}': {e}")
                    return None
                if os.path.abspath(existing_target) != os.path.abspath(movie_file):
                    self.last_import_error = f"Existing movie symlink points to a different file: '{symlink_path}'."
                    print(f"⚠️  Warning: Existing movie symlink points to a different file: '{symlink_path}'.")
                    return None
            else:
                success, result = create_movie_symlink(movie_file, media_folder)
                if not success:
                    self.last_import_error = f"Could not create movie symlink for '{movie_file}': {result}"
                    print(f"⚠️  Warning: Could not create movie symlink for '{movie_file}': {result}")
                    return None
                symlink_path = result
                movie_folder = os.path.dirname(result)

            self._write_tracking_file(torrent, download_path, movie_folder)
            return movie_folder
        except Exception as e:
            self.last_import_error = f"Error adding completed movie torrent to library: {e}"
            print(f"❌ Error adding completed movie torrent to library: {e}")
            return None
    
    def sync_torrents_with_qbittorrent(self) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Sync tracked torrents with current qBittorrent status."""
        # Check if qBittorrent is accessible
        if not qb_check_connection():
            return None, "qBittorrent not accessible"
        
        # Login to qBittorrent
        session = qb_login()
        if not session:
            return None, "Failed to authenticate with qBittorrent"
        
        # Get all torrents from qBittorrent
        qb_torrents = qb_get_torrent_info(session)
        if not qb_torrents:
            return [], "No torrents found in qBittorrent"
        
        # Get tracked torrents from database
        tracked_torrents = get_tracked_torrents()
        
        # Match tracked torrents with qBittorrent torrents by hash
        synced_torrents = []
        for tracked in tracked_torrents:
            # Find matching torrent in qBittorrent by infohash
            qb_match = None
            for qb_torrent in qb_torrents:
                if qb_torrent.get('hash', '').lower() == tracked.get('infohash', '').lower():
                    qb_match = qb_torrent
                    break
            
            # Combine tracked info with qBittorrent status
            synced_torrent = tracked.copy()
            if qb_match:
                synced_torrent.update({
                    'qb_status': qb_match.get('state', 'unknown'),
                    'qb_progress': qb_match.get('progress', 0) * 100,
                    'qb_downloaded': qb_match.get('downloaded', 0),
                    'qb_size': qb_match.get('size', 0),
                    'qb_speed_dl': qb_match.get('dlspeed', 0),
                    'qb_speed_up': qb_match.get('upspeed', 0),
                    'qb_eta': qb_match.get('eta', 0),
                    'qb_ratio': qb_match.get('ratio', 0),
                    'qb_name': qb_match.get('name', 'Unknown'),
                    'qb_save_path': qb_match.get('save_path', 'Unknown'),
                    'qb_content_path': qb_match.get('content_path', ''),
                    'found_in_qb': True
                })
            else:
                synced_torrent.update({
                    'found_in_qb': False,
                    'qb_status': 'not_found'
                })
            
            synced_torrents.append(synced_torrent)
        
        return synced_torrents, None
    
    def sort_torrent_files_for_jellyfin(self, torrent: Dict[str, Any], download_path: str) -> Optional[Dict[str, Any]]:
        """
        Sorts and organizes the torrent's files into a folder structure compatible with Jellyfin, using pattern matching and ffprobe.
        Supports episodic anime and series media types.
        """
        media_type = torrent.get("media_type", "anime")
        media_metadata = torrent.get("media_metadata", torrent.get("anilist_info", {}))
        media_title = sanitize_filename(media_metadata.get("title", "Unknown"))
        if media_type == "series":
            library_base_folder = get_series_folder()
        else:
            library_base_folder = get_anime_folder()
        library_main_folder = os.path.join(library_base_folder, media_title)
        file_structure = {'root': library_main_folder, 'folders': []}
        # Helper regexes
        season_regex = re.compile(r'(season[ _-]?(\d+)|s(\d{1,2}))(?!\d)', re.IGNORECASE)
        episode_season_regex = re.compile(r'(^|[^\d])(\d{1,2})[xX]\d{1,3}([^\d]|$)')
        specials_regex = re.compile(r'(special|extra|ova|sp|nced|ncop|s00)', re.IGNORECASE)
        # Walk torrent folders, or treat a single-file torrent as a one-item folder.
        folder_map = {}
        if os.path.isfile(download_path):
            walk_root = os.path.dirname(download_path)
            walk_entries = [(walk_root, [], [os.path.basename(download_path)])]
        else:
            walk_root = download_path
            walk_entries = os.walk(download_path)

        for root, dirs, files in walk_entries:
            rel_root = os.path.relpath(root, walk_root)
            # Only sanitize each part, skip empty or '.'
            rel_parts = [part for part in rel_root.split(os.sep) if part and part != '.']
            for file in files:
                if not is_episode_file(file):
                    continue
                file_path = os.path.join(root, file)
                # ffprobe: check if movie
                duration = probe_video_duration(file_path)
                # For anime only: files longer than 40 minutes go to Movies
                if media_type == "anime" and duration and duration > 40 * 60:
                    movies_folder = os.path.join(library_main_folder, 'Movies')
                    folder_map.setdefault(movies_folder, []).append({'source': file_path, 'target': os.path.join(movies_folder, file)})
                    continue
                # Find best matching folder for season/specials
                best_folder = None
                best_type = None
                best_season = None
                # Check all parent folders, deepest first
                for i in range(len(rel_parts), 0, -1):
                    folder_name = rel_parts[i-1]
                    # Season
                    season_match = season_regex.search(folder_name)
                    if season_match:
                            season_num = season_match.group(2) or season_match.group(3)
                            if season_num:
                                season_folder = os.path.join(library_main_folder, f'Season {int(season_num):02d}')
                                best_folder = season_folder
                                best_type = 'season'
                                best_season = int(season_num)
                                break
                    # Specials
                    if specials_regex.search(folder_name):
                        specials_folder = os.path.join(library_main_folder, 'Season 00')
                        best_folder = specials_folder
                        best_type = 'specials'
                        break
                # If not found by folder, try file name
                if not best_folder:
                    episode_season_match = episode_season_regex.search(file)
                    if episode_season_match:
                        best_season = int(episode_season_match.group(2))
                        best_folder = os.path.join(library_main_folder, f'Season {best_season:02d}')
                        best_type = 'season'
                    # Season in file name
                    season_match = season_regex.search(file)
                    if not best_folder and season_match:
                        season_num = season_match.group(2) or season_match.group(3)
                        if season_num:
                            best_folder = os.path.join(library_main_folder, f'Season {int(season_num):02d}')
                            best_type = 'season'
                            best_season = int(season_num)
                    # Specials in file name
                    elif specials_regex.search(file):
                        best_folder = os.path.join(library_main_folder, 'Season 00')
                        best_type = 'specials'
                # Default to Season 01
                if not best_folder:
                    best_folder = os.path.join(library_main_folder, 'Season 01')
                    best_type = 'season'
                    best_season = 1
                folder_map.setdefault(best_folder, []).append({'source': file_path, 'target': os.path.join(best_folder, file)})
        # Build file_structure
        for folder, files in folder_map.items():
            file_structure['folders'].append({'path': folder, 'files': files})
        return file_structure

    def add_completed_torrent_to_library(self, torrent: Dict[str, Any], download_path: str) -> bool:
        """Add a completed episodic torrent to the library using media metadata."""
        self.last_import_error = ""
        try:
            file_structure = self.sort_torrent_files_for_jellyfin(torrent, download_path)
            if not file_structure:
                self.last_import_error = "Could not build Jellyfin file structure."
                return False
            linked_or_existing_files = 0
            failed_links: List[str] = []
            # Create folders and symlinks as described in the file structure
            for folder in file_structure['folders']:
                try:
                    os.makedirs(folder['path'], exist_ok=True)
                except Exception as e:
                    self.last_import_error = f"Error creating folder '{folder['path']}': {e}"
                    print(f"❌ Error creating folder '{folder['path']}': {e}")
                    return False
                for file_entry in folder['files']:
                    if os.path.exists(file_entry['target']):
                        linked_or_existing_files += 1
                        continue
                    try:
                        os.symlink(file_entry['source'], file_entry['target'])
                        linked_or_existing_files += 1
                    except Exception as e:
                        failed_links.append(f"{file_entry['target']}: {e}")
                        print(f"⚠️  Warning: Could not create symlink for '{file_entry['target']}': {e}")
            if failed_links:
                self.last_import_error = f"Could not create {len(failed_links)} symlink(s). First error: {failed_links[0]}"
                return False
            if linked_or_existing_files == 0:
                self.last_import_error = "No media files were linked to the library."
                print("⚠️  Warning: No media files were linked to the library.")
                return False
            media_main_folder = file_structure['root']
            self._write_tracking_file(torrent, download_path, media_main_folder)
            return True
        except Exception as e:
            self.last_import_error = f"Error adding completed torrent to library: {e}"
            print(f"❌ Error adding completed torrent to library: {e}")
            return False
    
    def _auto_add_skip(self, torrent: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {
            "id": torrent.get("id"),
            "title": torrent.get("title", "Unknown"),
            "status": torrent.get("status"),
            "media_type": torrent.get("media_type"),
            "qb_status": torrent.get("qb_status"),
            "found_in_qb": torrent.get("found_in_qb"),
            "reason": reason,
        }

    def auto_add_completed_torrents_report(self) -> Dict[str, Any]:
        """Check for completed torrents and report added/skipped items."""
        # Get tracked torrents with qBittorrent sync
        synced_torrents, error = self.sync_torrents_with_qbittorrent()
        report: Dict[str, Any] = {
            "added": [],
            "skipped": [],
            "error": error,
            "total_tracked": len(synced_torrents or []),
        }

        if error or not synced_torrents:
            return report
        
        # Find newly completed torrents
        completed_torrents: List[Dict[str, Any]] = []
        
        for torrent in synced_torrents:
            # Check if torrent is completed/seeding and not already processed
            completed_states = ['completedDL', 'uploading', 'stalledUP', 'queuedUP']

            if torrent.get('status') == 'added_to_library':
                continue
            if not torrent.get('found_in_qb'):
                report["skipped"].append(self._auto_add_skip(torrent, "not found in qBittorrent"))
                continue
            if torrent.get('qb_status') not in completed_states:
                report["skipped"].append(self._auto_add_skip(torrent, f"qBittorrent status is {torrent.get('qb_status', 'unknown')}"))
                continue

            media_type = torrent.get("media_type", "anime")
            if media_type not in ["anime", "series", "movie"]:
                report["skipped"].append(self._auto_add_skip(torrent, f"unsupported media type: {media_type}"))
                continue

            media_metadata = torrent.get("media_metadata", torrent.get("anilist_info", {}))
            if not media_metadata:
                report["skipped"].append(self._auto_add_skip(torrent, "missing metadata payload"))
                continue
            if not media_metadata.get('title'):
                report["skipped"].append(self._auto_add_skip(torrent, "metadata title missing"))
                continue

            # Try to add to library
            library_path = ""
            source_download_path = self._resolve_completed_torrent_path(torrent)
            if media_type == "movie":
                source_download_path = self._resolve_primary_movie_source_path(torrent)
                if not source_download_path:
                    report["skipped"].append(self._auto_add_skip(torrent, "could not resolve completed movie path"))
                    continue
                movie_library_path = self.add_completed_movie_to_library(torrent, source_download_path)
                success = movie_library_path is not None
                if movie_library_path:
                    library_path = movie_library_path
            else:
                if not source_download_path:
                    report["skipped"].append(self._auto_add_skip(torrent, "could not resolve completed torrent path"))
                    continue
                success = self.add_completed_torrent_to_library(torrent, source_download_path)
                if success:
                    media_title = sanitize_filename(media_metadata.get('title', 'Unknown'))
                    if media_type == "series":
                        library_path = os.path.join(get_series_folder(), media_title)
                    else:
                        library_path = os.path.join(get_anime_folder(), media_title)

            if success:
                completed_torrents.append(torrent)
                update_torrent_paths(torrent['id'], source_download_path=source_download_path, library_path=library_path)
                # Update torrent status in database
                update_torrent_status(torrent['id'], 'added_to_library')
            else:
                error_detail = self.last_import_error or "library import failed"
                report["skipped"].append(self._auto_add_skip(torrent, error_detail))

        report["added"] = completed_torrents
        return report

    def auto_add_completed_torrents(self) -> List[Dict[str, Any]]:
        """Check for completed torrents and automatically add them to the library."""
        report = self.auto_add_completed_torrents_report()
        added = report.get("added", [])
        return added if isinstance(added, list) else []

    @staticmethod
    def _canonical_cleanup_path(path: Any) -> str:
        """Normalize filesystem paths, including Windows extended-length symlink targets."""
        raw_path = str(path or "").strip().strip('"')
        if not raw_path or raw_path.lower() in {"default", "unknown", "n/a"}:
            return ""
        if raw_path.startswith("\\\\?\\UNC\\"):
            raw_path = "\\\\" + raw_path[8:]
        elif raw_path.startswith("\\\\?\\"):
            raw_path = raw_path[4:]
        return os.path.normcase(os.path.abspath(os.path.normpath(raw_path)))

    @classmethod
    def _is_same_or_child_cleanup_path(cls, path: Any, parent: Any) -> bool:
        normalized_path = cls._canonical_cleanup_path(path)
        normalized_parent = cls._canonical_cleanup_path(parent)
        if not normalized_path or not normalized_parent:
            return False
        try:
            return os.path.commonpath([normalized_path, normalized_parent]) == normalized_parent
        except (OSError, ValueError):
            return False

    @staticmethod
    def _resolve_library_symlink_target(link_path: str) -> str:
        target = os.readlink(link_path)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(link_path), target)
        return target

    @staticmethod
    def _is_episode_sidecar(file_name: str, video_stem: str) -> bool:
        """Match Jellyfin-generated files that belong to one linked video."""
        normalized_name = file_name.lower()
        normalized_stem = video_stem.lower()
        if not normalized_name.startswith(normalized_stem):
            return False

        suffix = normalized_name[len(normalized_stem):]
        if suffix in {".nfo", ".trickplay", ".chapters.xml"}:
            return True

        extension = os.path.splitext(normalized_name)[1]
        if suffix.startswith("-") and extension in {".jpg", ".jpeg", ".png", ".webp", ".bif"}:
            return True
        if suffix.startswith(".") and extension in {
            ".nfo", ".jpg", ".jpeg", ".png", ".webp", ".bif",
            ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt",
        }:
            return True
        return False

    @staticmethod
    def _remove_cleanup_path(path: str) -> None:
        if os.path.islink(path):
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    @staticmethod
    def _contains_library_video(path: str) -> bool:
        if not os.path.isdir(path):
            return False
        for root, _, files in os.walk(path):
            for file_name in files:
                candidate = os.path.join(root, file_name)
                if is_video_file(file_name) and (os.path.isfile(candidate) or os.path.islink(candidate)):
                    return True
        return False

    @staticmethod
    def _is_jellyfin_metadata_name(name: str, is_directory: bool = False) -> bool:
        normalized = name.lower()
        if normalized == "track.json":
            return True
        if is_directory and normalized.endswith(".trickplay"):
            return True
        return os.path.splitext(normalized)[1] in {
            ".nfo", ".jpg", ".jpeg", ".png", ".webp", ".bif",
        }

    def _contains_only_jellyfin_metadata(self, path: str, allow_season_folders: bool = False) -> bool:
        if not os.path.isdir(path):
            return False
        for root, dirs, files in os.walk(path):
            retained_dirs = []
            for directory in dirs:
                directory_path = os.path.join(root, directory)
                if os.path.islink(directory_path) or getattr(os.path, "isjunction", lambda _: False)(directory_path):
                    return False
                if self._is_jellyfin_metadata_name(directory, is_directory=True):
                    continue
                if allow_season_folders and root == path and directory.lower().startswith("season "):
                    retained_dirs.append(directory)
                    continue
                return False
            dirs[:] = retained_dirs
            if any(not self._is_jellyfin_metadata_name(file_name) for file_name in files):
                return False
        return True

    def _validated_torrent_library_path(self, torrent: Dict[str, Any]) -> str:
        library_path = self._canonical_cleanup_path(torrent.get("library_path"))
        if not library_path:
            return ""

        media_type = str(torrent.get("media_type", "") or "").lower()
        if media_type == "series":
            roots = [get_series_folder()]
        elif media_type == "anime":
            roots = [get_anime_folder()]
        elif media_type == "movie":
            roots = get_all_media_folders()
        else:
            roots = []

        normalized_roots = [self._canonical_cleanup_path(root) for root in roots]
        if not normalized_roots or not any(
            library_path != root and self._is_same_or_child_cleanup_path(library_path, root)
            for root in normalized_roots
            if root
        ):
            raise ValueError("Tracked library path is outside configured library folders")
        if os.path.lexists(library_path) and os.path.islink(library_path):
            raise ValueError("Tracked library path cannot be a symlink")
        if os.path.lexists(library_path) and getattr(os.path, "isjunction", lambda _: False)(library_path):
            raise ValueError("Tracked library path cannot be a junction")

        real_library_path = self._canonical_cleanup_path(os.path.realpath(library_path))
        real_roots = [self._canonical_cleanup_path(os.path.realpath(root)) for root in normalized_roots if root]
        if not any(
            real_library_path != root and self._is_same_or_child_cleanup_path(real_library_path, root)
            for root in real_roots
            if root
        ):
            raise ValueError("Tracked library path resolves outside configured library folders")

        track_path = os.path.join(library_path, "track.json")
        if os.path.lexists(track_path) and (
            os.path.islink(track_path) or getattr(os.path, "isjunction", lambda _: False)(track_path)
        ):
            raise ValueError("Library tracking file cannot be a symlink or junction")
        return library_path

    def _torrent_cleanup_source_paths(
        self,
        torrent: Dict[str, Any],
        additional_source_paths: Optional[List[str]] = None,
    ) -> List[str]:
        authoritative_candidates = [
            self._canonical_cleanup_path(candidate)
            for candidate in (additional_source_paths or [])
        ]
        authoritative_candidates = [candidate for candidate in authoritative_candidates if candidate]
        candidates = authoritative_candidates or [
            torrent.get("source_download_path"),
            torrent.get("download_path"),
            torrent.get("qb_content_path"),
        ]
        source_paths: List[str] = []
        for candidate in candidates:
            normalized = self._canonical_cleanup_path(candidate)
            if normalized and os.path.dirname(normalized) == normalized:
                raise ValueError("Torrent source path cannot be a filesystem root")
            if normalized and normalized not in source_paths:
                source_paths.append(normalized)
        return source_paths

    def plan_torrent_library_cleanup(
        self,
        torrent: Dict[str, Any],
        additional_source_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Find only library links and sidecars owned by one tracked torrent."""
        library_path = self._validated_torrent_library_path(torrent)
        source_paths = self._torrent_cleanup_source_paths(torrent, additional_source_paths)
        linked_paths: List[str] = []
        video_links: List[str] = []
        sidecar_paths = set()

        removed_hash = str(torrent.get("infohash", "") or "").strip().lower()
        if library_path and source_paths:
            for sibling in get_tracked_torrents():
                sibling_hash = str(sibling.get("infohash", "") or "").strip().lower()
                if not sibling_hash or sibling_hash == removed_hash:
                    continue
                sibling_sources = self._torrent_cleanup_source_paths(sibling)
                if any(
                    self._is_same_or_child_cleanup_path(source, sibling_source)
                    or self._is_same_or_child_cleanup_path(sibling_source, source)
                    for source in source_paths
                    for sibling_source in sibling_sources
                ):
                    raise ValueError("Torrent source path overlaps another tracked torrent")

        if library_path and os.path.isdir(library_path) and source_paths:
            for root, dirs, files in os.walk(library_path):
                for entry_name in list(dirs) + files:
                    entry_path = os.path.join(root, entry_name)
                    if not os.path.islink(entry_path):
                        continue
                    try:
                        target_path = self._resolve_library_symlink_target(entry_path)
                    except OSError:
                        continue
                    if not any(self._is_same_or_child_cleanup_path(target_path, source) for source in source_paths):
                        continue
                    linked_paths.append(entry_path)
                    if is_video_file(entry_name):
                        video_links.append(entry_path)
                dirs[:] = [
                    directory
                    for directory in dirs
                    if not os.path.islink(os.path.join(root, directory))
                    and not getattr(os.path, "isjunction", lambda _: False)(os.path.join(root, directory))
                ]

            for video_link in video_links:
                parent = os.path.dirname(video_link)
                video_stem = os.path.splitext(os.path.basename(video_link))[0]
                try:
                    sibling_names = os.listdir(parent)
                except OSError:
                    continue
                has_unowned_same_stem_video = any(
                    is_video_file(sibling_name)
                    and os.path.splitext(sibling_name)[0].lower() == video_stem.lower()
                    and os.path.join(parent, sibling_name) not in video_links
                    for sibling_name in sibling_names
                )
                if has_unowned_same_stem_video:
                    continue
                for sibling_name in sibling_names:
                    sibling_path = os.path.join(parent, sibling_name)
                    if sibling_path == video_link:
                        continue
                    if self._is_episode_sidecar(sibling_name, video_stem):
                        sidecar_paths.add(sibling_path)

        return {
            "library_path": library_path,
            "source_paths": source_paths,
            "linked_paths": sorted(set(linked_paths)),
            "video_links": sorted(set(video_links)),
            "sidecar_paths": sorted(sidecar_paths),
        }

    def _remaining_tracked_torrents_for_library(
        self,
        torrent: Dict[str, Any],
        library_path: str,
    ) -> List[Dict[str, Any]]:
        removed_hash = str(torrent.get("infohash", "") or "").strip().lower()
        return [
            tracked
            for tracked in get_tracked_torrents()
            if str(tracked.get("infohash", "") or "").strip().lower() != removed_hash
            and self._canonical_cleanup_path(tracked.get("library_path")) == library_path
        ]

    def _refresh_tracking_file_after_torrent_removal(self, torrent: Dict[str, Any], library_path: str) -> bool:
        track_path = os.path.join(library_path, "track.json")
        if not os.path.isfile(track_path):
            return False

        removed_hash = str(torrent.get("infohash", "") or "").strip().lower()
        try:
            with open(track_path, "r", encoding="utf-8") as file_handle:
                tracking_payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            tracking_payload = {}

        tracked_hash = str(tracking_payload.get("infohash", "") or "").strip().lower()
        if tracked_hash and tracked_hash != removed_hash:
            return False

        remaining = self._remaining_tracked_torrents_for_library(torrent, library_path)
        if not remaining:
            os.remove(track_path)
            return True

        def torrent_id(item: Dict[str, Any]) -> int:
            try:
                return int(item.get("id", 0))
            except (TypeError, ValueError):
                return 0

        replacement = max(remaining, key=torrent_id).copy()
        temp_path = f"{track_path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as file_handle:
                json.dump(replacement, file_handle, indent=2)
            os.replace(temp_path, track_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return True

    def remove_torrent_library_files(
        self,
        torrent: Dict[str, Any],
        additional_source_paths: Optional[List[str]] = None,
        cleanup_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Remove one torrent's links/sidecars without deleting sibling Series episodes."""
        report: Dict[str, Any] = {
            "success": False,
            "removed_links": [],
            "removed_sidecars": [],
            "removed_season_folders": [],
            "removed_library_root": False,
            "tracking_file_updated": False,
        }
        try:
            plan = cleanup_plan or self.plan_torrent_library_cleanup(torrent, additional_source_paths)
            library_path = self._validated_torrent_library_path(torrent)
            if plan.get("library_path") != library_path:
                raise ValueError("Library cleanup plan does not match tracked library path")

            with _library_file_lock:
                for link_path in plan["linked_paths"]:
                    if not os.path.lexists(link_path):
                        continue
                    if not os.path.islink(link_path):
                        raise ValueError("Planned library link changed before cleanup")
                    target_path = self._resolve_library_symlink_target(link_path)
                    if not any(
                        self._is_same_or_child_cleanup_path(target_path, source_path)
                        for source_path in plan["source_paths"]
                    ):
                        raise ValueError("Planned library link target changed before cleanup")

                for path in sorted(
                    set(plan["linked_paths"] + plan["sidecar_paths"]),
                    key=lambda candidate: candidate.count(os.sep),
                    reverse=True,
                ):
                    if not os.path.lexists(path):
                        continue
                    self._remove_cleanup_path(path)
                    if path in plan["linked_paths"]:
                        report["removed_links"].append(path)
                    else:
                        report["removed_sidecars"].append(path)

                if library_path and os.path.isdir(library_path):
                    remaining_torrents = self._remaining_tracked_torrents_for_library(torrent, library_path)
                    if plan["linked_paths"]:
                        season_paths = {
                            os.path.dirname(video_link)
                            for video_link in plan["video_links"]
                            if os.path.basename(os.path.dirname(video_link)).lower().startswith("season ")
                        }
                        for season_path in sorted(season_paths, key=lambda candidate: candidate.count(os.sep), reverse=True):
                            if (
                                os.path.isdir(season_path)
                                and not self._contains_library_video(season_path)
                                and self._contains_only_jellyfin_metadata(season_path)
                            ):
                                shutil.rmtree(season_path)
                                report["removed_season_folders"].append(season_path)

                    if (
                        not remaining_torrents
                        and not self._contains_library_video(library_path)
                        and self._contains_only_jellyfin_metadata(library_path, allow_season_folders=True)
                    ):
                        shutil.rmtree(library_path)
                        report["removed_library_root"] = True

                    if os.path.isdir(library_path):
                        report["tracking_file_updated"] = self._refresh_tracking_file_after_torrent_removal(
                            torrent,
                            library_path,
                        )

            report["success"] = True
            return report
        except Exception as exc:
            report["error"] = str(exc)
            return report

    def remove_torrent_and_library_entry(self, torrent: Dict[str, Any]) -> bool:
        """Remove one torrent's library files and its database entry."""
        report = self.remove_torrent_library_files(torrent)
        if not report.get("success"):
            return False
        infohash = torrent.get("infohash")
        if infohash:
            remove_torrent_from_database_by_infohash(infohash)
        return True

    def set_sort_torrent_files_for_jellyfin(self, func):
        """
        Allow plugins to override the file sorting logic for Jellyfin.
        Pass a function with the same signature as sort_torrent_files_for_jellyfin.
        """
        self.sort_torrent_files_for_jellyfin = func.__get__(self, self.__class__)


# Global instance for backward compatibility
_torrent_manager = TorrentManager()


# Legacy functions for backward compatibility
def sync_torrents_with_qbittorrent() -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Sync tracked torrents with current qBittorrent status. (Legacy function)"""
    return _torrent_manager.sync_torrents_with_qbittorrent()


def add_completed_torrent_to_library(torrent: Dict[str, Any], download_path: str) -> bool:
    """Add a completed torrent to the anime library. (Legacy function)"""
    return _torrent_manager.add_completed_torrent_to_library(torrent, download_path)


def auto_add_completed_torrents() -> List[Dict[str, Any]]:
    """Check for completed torrents and auto-add them to library. (Legacy function)"""
    return _torrent_manager.auto_add_completed_torrents()
