"""
Torrent management module for the Jellyfin Library Manager.
"""

import os
import re
from typing import List, Dict, Any, Tuple, Optional
from qbittorrent_api import qb_check_connection, qb_login, qb_get_torrent_info
from database import get_tracked_torrents, update_torrent_status, update_torrent_paths, remove_torrent_from_database_by_infohash
from utils import is_episode_file, get_anime_folder
from file_utils import create_anime_symlinks
from ffprobe_utils import probe_video_duration


def sanitize_filename(name: str) -> str:
    """Replace forbidden characters in a single filename or folder name with a space."""
    forbidden = r'[\\/:*?"<>|]'
    return re.sub(forbidden, ' ', name).strip()


class TorrentManager:
    """Class to handle torrent management operations."""
    
    def __init__(self):
        pass
    
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
        Only the anime title is sanitized for forbidden characters.
        """
        anilist_info = torrent.get('anilist_info', {})
        anime_title = sanitize_filename(anilist_info.get('title', 'Unknown Anime'))
        anime_base_folder = get_anime_folder()
        anime_main_folder = os.path.join(anime_base_folder, anime_title)
        file_structure = {'root': anime_main_folder, 'folders': []}
        # Helper regexes
        season_regex = re.compile(r'(season[ _-]?(\d+)|s(\d{1,2}))(?!\d)', re.IGNORECASE)
        specials_regex = re.compile(r'(special|extra|ova|sp|nced|ncop|s00)', re.IGNORECASE)
        # Walk the torrent directory
        folder_map = {}
        for root, dirs, files in os.walk(download_path):
            rel_root = os.path.relpath(root, download_path)
            # Only sanitize each part, skip empty or '.'
            rel_parts = [part for part in rel_root.split(os.sep) if part and part != '.']
            for file in files:
                if not is_episode_file(file):
                    continue
                file_path = os.path.join(root, file)
                # ffprobe: check if movie
                duration = probe_video_duration(file_path)
                # Files longer than 40 minutes go to Movies
                if duration and duration > 40 * 60:
                    movies_folder = os.path.join(anime_main_folder, 'Movies')
                    folder_map.setdefault(movies_folder, []).append({'source': file_path, 'target': os.path.join(movies_folder, file)})
                    continue
                # Find best matching folder for season/specials
                best_folder = None
                best_type = None
                best_season = None
                # Check all parent folders, deepest first
                parts = rel_root.split(os.sep)
                for i in range(len(rel_parts), 0, -1):
                    folder_name = rel_parts[i-1]
                    # Season
                    season_match = season_regex.search(folder_name)
                    if season_match:
                        season_num = season_match.group(2) or season_match.group(3)
                        if season_num:
                            season_folder = os.path.join(anime_main_folder, f'Season {int(season_num):02d}')
                            best_folder = season_folder
                            best_type = 'season'
                            best_season = int(season_num)
                            break
                    # Specials
                    if specials_regex.search(folder_name):
                        specials_folder = os.path.join(anime_main_folder, 'Season 00')
                        best_folder = specials_folder
                        best_type = 'specials'
                        break
                # If not found by folder, try file name
                if not best_folder:
                    # Season in file name
                    season_match = season_regex.search(file)
                    if season_match:
                        season_num = season_match.group(2) or season_match.group(3)
                        if season_num:
                            best_folder = os.path.join(anime_main_folder, f'Season {int(season_num):02d}')
                            best_type = 'season'
                            best_season = int(season_num)
                    # Specials in file name
                    elif specials_regex.search(file):
                        best_folder = os.path.join(anime_main_folder, 'Season 00')
                        best_type = 'specials'
                # Default to Season 01
                if not best_folder:
                    best_folder = os.path.join(anime_main_folder, 'Season 01')
                    best_type = 'season'
                    best_season = 1
                folder_map.setdefault(best_folder, []).append({'source': file_path, 'target': os.path.join(best_folder, file)})
        # Build file_structure
        for folder, files in folder_map.items():
            file_structure['folders'].append({'path': folder, 'files': files})
        return file_structure

    def add_completed_torrent_to_library(self, torrent: Dict[str, Any], download_path: str) -> bool:
        """Add a completed torrent to the anime library using AniList info."""
        try:
            file_structure = self.sort_torrent_files_for_jellyfin(torrent, download_path)
            if not file_structure:
                return False
            linked_or_existing_files = 0
            # Create folders and symlinks as described in the file structure
            for folder in file_structure['folders']:
                try:
                    os.makedirs(folder['path'], exist_ok=True)
                except Exception as e:
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
                        print(f"⚠️  Warning: Could not create symlink for '{file_entry['target']}': {e}")
            if linked_or_existing_files == 0:
                print("⚠️  Warning: No media files were linked to the library.")
                return False
            # Write tracking info to track.json in the anime main folder
            import json
            anime_main_folder = file_structure['root']
            track_path = os.path.join(anime_main_folder, "track.json")
            try:
                track_torrent = torrent.copy()
                track_torrent.setdefault("source_download_path", download_path)
                track_torrent.setdefault("download_path", download_path)
                track_torrent["library_path"] = anime_main_folder
                with open(track_path, "w", encoding="utf-8") as f:
                    json.dump(track_torrent, f, indent=2)
            except Exception as e:
                print(f"⚠️  Warning: Could not save tracking info: {e}")
            return True
        except Exception as e:
            print(f"❌ Error adding completed torrent to library: {e}")
            return False
    
    def auto_add_completed_torrents(self) -> List[Dict[str, Any]]:
        """Check for completed torrents and automatically add them to the anime library."""
        # Get tracked torrents with qBittorrent sync
        synced_torrents, error = self.sync_torrents_with_qbittorrent()
        
        if error or not synced_torrents:
            return []
        
        # Find newly completed torrents
        completed_torrents = []
        
        for torrent in synced_torrents:
            # Check if torrent is completed/seeding and not already processed
            completed_states = ['completedDL', 'uploading', 'stalledUP', 'queuedUP']
            
            if (torrent.get('found_in_qb') and 
                torrent.get('qb_status') in completed_states and 
                torrent.get('status') != 'added_to_library'):
                
                # Get AniList info for proper naming
                anilist_info = torrent.get('anilist_info', {})
                if not anilist_info.get('title'):
                    continue
                
                # Additional safety check - only process torrents that were added via this script
                if not torrent.get('anilist_info'):
                    continue
                
                # Get the download path from qBittorrent
                download_path = torrent.get('qb_save_path', '')
                torrent_name = torrent.get('qb_name', '')
                
                if not download_path or not torrent_name:
                    continue
                
                # Construct the full path to the torrent's folder
                # qb_save_path is the base download directory (e.g., "C:\Torrents")
                # qb_name is the torrent folder name (e.g., "Domestic Girlfriend S01 1080p...")
                full_torrent_path = os.path.join(download_path, torrent_name)
                
                if not os.path.exists(full_torrent_path):
                    continue
                
                # Try to add to library
                success = self.add_completed_torrent_to_library(torrent, full_torrent_path)
                
                if success:
                    completed_torrents.append(torrent)
                    anilist_info = torrent.get('anilist_info', {})
                    anime_title = sanitize_filename(anilist_info.get('title', 'Unknown Anime'))
                    library_path = os.path.join(get_anime_folder(), anime_title)
                    update_torrent_paths(torrent['id'], source_download_path=full_torrent_path, library_path=library_path)
                    # Update torrent status in database
                    update_torrent_status(torrent['id'], 'added_to_library')
        
        return completed_torrents

    def remove_torrent_and_library_entry(self, torrent: Dict[str, Any]) -> bool:
        """Remove torrent files/folders and database entry by infohash."""
        try:
            # Remove files/folders
            anilist_info = torrent.get('anilist_info', {})
            anime_title = sanitize_filename(anilist_info.get('title', 'Unknown Anime'))
            anime_base_folder = get_anime_folder()
            anime_main_folder = os.path.join(anime_base_folder, anime_title)
            if os.path.exists(anime_main_folder):
                import shutil
                shutil.rmtree(anime_main_folder, ignore_errors=True)
            # Remove from database
            infohash = torrent.get('infohash')
            if infohash:
                remove_torrent_from_database_by_infohash(infohash)
            return True
        except Exception:
            return False

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
