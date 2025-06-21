"""
qBittorrent Web API integration for the Jellyfin Library Manager.
"""

import requests
from typing import Optional, List, Dict, Any
from config import QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD


class QBittorrentAPI:
    """Class to handle qBittorrent Web API interactions."""
    
    def __init__(self, host: str = None, username: str = None, password: str = None):
        self.host = host or QBITTORRENT_URL
        self.username = username or QBITTORRENT_USERNAME
        self.password = password or QBITTORRENT_PASSWORD
        self.session = None
    
    def login(self) -> bool:
        """Login to qBittorrent API and return success status."""
        self.session = requests.Session()
        try:
            response = self.session.post(f"{self.host}/api/v2/auth/login", 
                                      data={'username': self.username, 'password': self.password})
            if response.text == "Ok.":
                return True
            else:
                self.session = None
                return False
        except Exception as e:
            print(f"❌ Error connecting to qBittorrent: {e}")
            self.session = None
            return False
    
    def add_torrent(self, torrent_url: str, download_path: Optional[str] = None) -> bool:
        """Add torrent to qBittorrent via URL."""
        if not self.session:
            return False
        
        try:
            data = {'urls': torrent_url}
            if download_path:
                data['savepath'] = download_path
            
            response = self.session.post(f"{self.host}/api/v2/torrents/add", data=data)
            return response.text == "Ok."
        except Exception as e:
            print(f"❌ Error adding torrent: {e}")
            return False
    
    def get_torrent_info(self) -> List[Dict[str, Any]]:
        """Get list of torrents from qBittorrent."""
        if not self.session:
            return []
        
        try:
            response = self.session.get(f"{self.host}/api/v2/torrents/info")
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"❌ Error getting torrent info: {e}")
            return []
    
    def check_connection(self) -> bool:
        """Check if qBittorrent is accessible."""
        try:
            response = requests.get(f"{self.host}/api/v2/app/version", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def logout(self) -> None:
        """Logout from qBittorrent API."""
        if self.session:
            try:
                self.session.post(f"{self.host}/api/v2/auth/logout")
            except:
                pass
            finally:
                self.session = None


# Global instance for backward compatibility
_qb_api = QBittorrentAPI()


def qb_login(username: str = None, password: str = None) -> Optional[requests.Session]:
    """Login to qBittorrent API and return session. (Legacy function)"""
    api = QBittorrentAPI(username=username, password=password)
    if api.login():
        return api.session
    return None


def qb_add_torrent(session: requests.Session, torrent_url: str, download_path: Optional[str] = None) -> bool:
    """Add torrent to qBittorrent via URL. (Legacy function)"""
    api = QBittorrentAPI()
    api.session = session
    return api.add_torrent(torrent_url, download_path)


def qb_get_torrent_info(session: requests.Session) -> List[Dict[str, Any]]:
    """Get list of torrents from qBittorrent. (Legacy function)"""
    api = QBittorrentAPI()
    api.session = session
    return api.get_torrent_info()


def qb_check_connection() -> bool:
    """Check if qBittorrent is accessible. (Legacy function)"""
    return _qb_api.check_connection()
