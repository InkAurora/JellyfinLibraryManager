"""
Database management for torrent tracking in the Jellyfin Library Manager.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from utils import get_anime_folder


class TorrentDatabase:
    """Class to manage the torrent tracking database."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self._get_default_db_path()
    
    def _get_default_db_path(self) -> str:
        """Get the default path to the torrent database file."""
        anime_folder = get_anime_folder()
        return os.path.join(anime_folder, "torrent_database.json")
    
    def load(self) -> Dict[str, Any]:
        """Load the torrent database from file."""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"torrents": [], "last_updated": None}
        except Exception as e:
            print(f"⚠️  Warning: Could not load torrent database: {e}")
            return {"torrents": [], "last_updated": None}
    
    def save(self, db_data: Dict[str, Any]) -> bool:
        """Save the torrent database to file."""
        try:
            # Ensure the anime folder exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            
            db_data["last_updated"] = datetime.now().isoformat()
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(db_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Error saving torrent database: {e}")
            return False
    
    def add_torrent(self, torrent_info: Dict[str, Any]) -> Optional[int]:
        """Add a torrent to the tracking database."""
        db_data = self.load()
        
        # Create torrent entry
        torrent_entry = {
            "id": len(db_data["torrents"]) + 1,
            "title": torrent_info.get("title", "Unknown"),
            "size": torrent_info.get("size", "Unknown"),
            "seeds": torrent_info.get("seeds", 0),
            "leechers": torrent_info.get("leechers", 0),
            "downloads": torrent_info.get("downloads", 0),
            "infohash": torrent_info.get("infohash", "N/A"),
            "category": torrent_info.get("category", "N/A"),
            "link": torrent_info.get("link", "N/A"),
            "download_path": torrent_info.get("download_path", "Default"),
            "added_date": datetime.now().isoformat(),
            "status": "added",
            "anilist_info": torrent_info.get("anilist_info", {})
        }
        
        db_data["torrents"].append(torrent_entry)
        
        if self.save(db_data):
            return torrent_entry["id"]
        return None
    
    def get_tracked_torrents(self) -> List[Dict[str, Any]]:
        """Get all tracked torrents from the database."""
        db_data = self.load()
        return db_data.get("torrents", [])
    
    def update_torrent_status(self, torrent_id: int, status: str) -> bool:
        """Update the status of a tracked torrent."""
        db_data = self.load()
        
        for torrent in db_data["torrents"]:
            if torrent["id"] == torrent_id:
                torrent["status"] = status
                torrent["status_updated"] = datetime.now().isoformat()
                break
        
        return self.save(db_data)
    
    def get_torrent_by_id(self, torrent_id: int) -> Optional[Dict[str, Any]]:
        """Get a torrent by its ID."""
        torrents = self.get_tracked_torrents()
        for torrent in torrents:
            if torrent["id"] == torrent_id:
                return torrent
        return None
    
    def remove_torrents_by_infohash(self, infohash: str) -> int:
        """Remove all torrents from the database that match the given infohash. Returns number removed."""
        db_data = self.load()
        before = len(db_data["torrents"])
        db_data["torrents"] = [t for t in db_data["torrents"] if t.get("infohash") != infohash]
        removed = before - len(db_data["torrents"])
        self.save(db_data)
        return removed


class NotificationManager:
    """Class to manage completion notifications."""
    
    def __init__(self, notifications_path: Optional[str] = None):
        self.notifications_path = notifications_path or self._get_default_notifications_path()
    
    def _get_default_notifications_path(self) -> str:
        """Get the default path to the notifications file."""
        anime_folder = get_anime_folder()
        return os.path.join(anime_folder, "torrent_notifications.json")
    
    def save_completion_notifications(self, completed_torrents: List[Dict[str, Any]]) -> None:
        """Save notification about completed torrents for later display."""
        try:
            notifications = []
            if os.path.exists(self.notifications_path):
                try:
                    with open(self.notifications_path, 'r', encoding='utf-8') as f:
                        notifications = json.load(f)
                except:
                    notifications = []
            
            # Add new notifications
            for torrent in completed_torrents:
                anilist_info = torrent.get('anilist_info', {})
                anime_title = anilist_info.get('title', 'Unknown Anime')
                
                notification = {
                    'timestamp': datetime.now().timestamp(),
                    'anime_title': anime_title,
                    'torrent_title': torrent.get('title', 'Unknown'),
                    'torrent_id': torrent.get('id'),
                    'message': f"'{anime_title}' has been automatically added to your anime library!"
                }
                notifications.append(notification)
            
            # Keep only recent notifications (last 24 hours)
            current_time = datetime.now().timestamp()
            notifications = [n for n in notifications if current_time - n['timestamp'] < 86400]
            
            # Save notifications
            os.makedirs(os.path.dirname(self.notifications_path), exist_ok=True)
            with open(self.notifications_path, 'w', encoding='utf-8') as f:
                json.dump(notifications, f, indent=2)
                
        except Exception as e:
            pass  # Silently handle errors
    
    def get_pending_notifications(self) -> List[Dict[str, Any]]:
        """Get and clear pending completion notifications."""
        try:
            if not os.path.exists(self.notifications_path):
                return []
            
            with open(self.notifications_path, 'r', encoding='utf-8') as f:
                notifications = json.load(f)
            
            # Clear the notifications file after reading
            with open(self.notifications_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            
            return notifications
            
        except Exception as e:
            return []


# Global instances for backward compatibility
_torrent_db = TorrentDatabase()
_notification_manager = NotificationManager()


def get_torrent_db_path() -> str:
    """Get the path to the torrent database file. (Legacy function)"""
    return _torrent_db.db_path


def load_torrent_database() -> Dict[str, Any]:
    """Load the torrent database from file. (Legacy function)"""
    return _torrent_db.load()


def save_torrent_database(db_data: Dict[str, Any]) -> bool:
    """Save the torrent database to file. (Legacy function)"""
    return _torrent_db.save(db_data)


def add_torrent_to_database(torrent_info: Dict[str, Any]) -> Optional[int]:
    """Add a torrent to the tracking database. (Legacy function)"""
    return _torrent_db.add_torrent(torrent_info)


def get_tracked_torrents() -> List[Dict[str, Any]]:
    """Get all tracked torrents from the database. (Legacy function)"""
    return _torrent_db.get_tracked_torrents()


def update_torrent_status(torrent_id: int, status: str) -> bool:
    """Update the status of a tracked torrent. (Legacy function)"""
    return _torrent_db.update_torrent_status(torrent_id, status)


def get_pending_notifications() -> List[Dict[str, Any]]:
    """Get and clear pending completion notifications. (Legacy function)"""
    return _notification_manager.get_pending_notifications()
