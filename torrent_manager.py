"""
Torrent management module for the Jellyfin Library Manager.
"""

import os
from typing import List, Dict, Any, Tuple, Optional
from qbittorrent_api import qb_check_connection, qb_login, qb_get_torrent_info
from database import get_tracked_torrents, update_torrent_status
from utils import is_episode_file, get_anime_folder
from file_utils import create_anime_symlinks


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
    
    def add_completed_torrent_to_library(self, torrent: Dict[str, Any], download_path: str) -> bool:
        """Add a completed torrent to the anime library using AniList info."""
        try:
            anilist_info = torrent.get('anilist_info', {})
            anime_title = anilist_info.get('title', 'Unknown Anime')
            
            # Check if download path exists
            if not os.path.exists(download_path):
                return False
            
            # Find episode files in the torrent's download folder
            episode_files = []
            source_folder = download_path
            
            # Check if it's a single file (rare case)
            if os.path.isfile(download_path):
                if is_episode_file(download_path):
                    episode_files.append(os.path.basename(download_path))
                    source_folder = os.path.dirname(download_path)
            else:
                # This is a directory - check ONLY files in this specific directory
                try:
                    items_in_torrent_folder = os.listdir(download_path)
                    for item in items_in_torrent_folder:
                        item_path = os.path.join(download_path, item)
                        if os.path.isfile(item_path) and is_episode_file(item):
                            episode_files.append(item)
                except PermissionError:
                    return False
            
            if not episode_files:
                return False
            
            # Create anime library structure
            anime_base_folder = get_anime_folder()
            anime_main_folder = os.path.join(anime_base_folder, anime_title)
            season_folder = os.path.join(anime_main_folder, "Season 01")  # Default to Season 01
            
            # Create directory structure
            try:
                os.makedirs(season_folder, exist_ok=True)
            except Exception as e:
                return False
            
            # Create individual symlinks for each episode file
            episode_files_linked = 0
            
            for episode_file in episode_files:
                # Build source path (from torrent download folder)
                source_file = os.path.join(source_folder, episode_file)
                # Build target path (in anime library)
                target_file = os.path.join(season_folder, episode_file)
                
                # Skip if symlink already exists
                if os.path.exists(target_file):
                    continue
                
                try:
                    os.symlink(source_file, target_file)
                    episode_files_linked += 1
                except Exception as e:
                    pass  # Continue trying other files even if one fails
            
            return episode_files_linked > 0
        
        except Exception as e:
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
                    # Update torrent status in database
                    update_torrent_status(torrent['id'], 'added_to_library')
        
        return completed_torrents


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
