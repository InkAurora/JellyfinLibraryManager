"""
qBittorrent Web API integration for the Jellyfin Library Manager.
"""

import time
import requests
from typing import Optional, List, Dict, Any
from config import QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD


class QBittorrentAPI:
    """Class to handle qBittorrent Web API interactions."""

    REQUEST_TIMEOUT_SECONDS = 5
    REQUEST_MAX_RETRIES = 2
    REQUEST_RETRY_BACKOFF_SECONDS = 0.5
    HEALTHCHECK_TIMEOUT_SECONDS = 1
    HEALTHCHECK_MAX_RETRIES = 0
    
    def __init__(self, host: str = None, username: str = None, password: str = None):
        self.host = host or QBITTORRENT_URL
        self.username = username or QBITTORRENT_USERNAME
        self.password = password or QBITTORRENT_PASSWORD
        self.session = None

    def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Perform a qBittorrent request with timeout and minimal retry/backoff."""
        timeout = kwargs.pop('timeout', self.REQUEST_TIMEOUT_SECONDS)
        max_retries = kwargs.pop('max_retries', self.REQUEST_MAX_RETRIES)
        backoff_seconds = kwargs.pop('backoff_seconds', self.REQUEST_RETRY_BACKOFF_SECONDS)
        session = kwargs.pop('session', None)
        request_session = session or self.session

        if request_session is None:
            raise RuntimeError("No active qBittorrent session")

        last_exception = None
        url = f"{self.host}{endpoint}"

        for attempt in range(max_retries + 1):
            try:
                response = request_session.request(method=method, url=url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < max_retries:
                    time.sleep(backoff_seconds * (2 ** attempt))

        raise last_exception

    def _request_without_session_with_retry(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Perform a qBittorrent request without session (for health checks) with retry/backoff."""
        timeout = kwargs.pop('timeout', self.REQUEST_TIMEOUT_SECONDS)
        max_retries = kwargs.pop('max_retries', self.REQUEST_MAX_RETRIES)
        backoff_seconds = kwargs.pop('backoff_seconds', self.REQUEST_RETRY_BACKOFF_SECONDS)

        last_exception = None
        url = f"{self.host}{endpoint}"

        for attempt in range(max_retries + 1):
            try:
                response = requests.request(method=method, url=url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < max_retries:
                    time.sleep(backoff_seconds * (2 ** attempt))

        raise last_exception
    
    def login(self) -> bool:
        """Login to qBittorrent API and return success status."""
        if not self.check_connection():
            self.session = None
            return False

        self.session = requests.Session()
        try:
            response = self._request_with_retry(
                "POST",
                "/api/v2/auth/login",
                data={'username': self.username, 'password': self.password}
            )
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
            
            response = self._request_with_retry("POST", "/api/v2/torrents/add", data=data)
            return response.text == "Ok."
        except Exception as e:
            print(f"❌ Error adding torrent: {e}")
            return False
    
    def get_torrent_info(self) -> List[Dict[str, Any]]:
        """Get list of torrents from qBittorrent."""
        if not self.session:
            return []
        
        try:
            response = self._request_with_retry("GET", "/api/v2/torrents/info")
            return response.json()
        except Exception as e:
            print(f"❌ Error getting torrent info: {e}")
            return []
    
    def check_connection(self) -> bool:
        """Check if qBittorrent is accessible."""
        try:
            self._request_without_session_with_retry(
                "GET",
                "/api/v2/app/version",
                timeout=self.HEALTHCHECK_TIMEOUT_SECONDS,
                max_retries=self.HEALTHCHECK_MAX_RETRIES
            )
            return True
        except:
            return False
    
    def logout(self) -> None:
        """Logout from qBittorrent API."""
        if self.session:
            try:
                self._request_with_retry("POST", "/api/v2/auth/logout")
            except:
                pass
            finally:
                self.session = None
    
    def remove_torrent(self, infohash: str, delete_files: bool = False) -> bool:
        """Remove a torrent from qBittorrent by infohash. Optionally delete files."""
        if not self.session:
            return False
        
        try:
            data = {
                'hashes': infohash,
                'deleteFiles': 'true' if delete_files else 'false'
            }
            self._request_with_retry("POST", "/api/v2/torrents/delete", data=data)
            return True
        except Exception as e:
            print(f"❌ Error removing torrent: {e}")
            return False


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


def qb_remove_torrent(session: requests.Session, infohash: str, delete_files: bool = False) -> bool:
    """Remove a torrent from qBittorrent by infohash. Optionally delete files."""
    api = QBittorrentAPI()
    api.session = session
    return api.remove_torrent(infohash, delete_files)
