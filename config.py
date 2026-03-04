"""
Configuration settings for the Jellyfin Library Manager.
"""

# qBittorrent API configuration
QBITTORRENT_HOST = "localhost:1337"
QBITTORRENT_URL = f"http://{QBITTORRENT_HOST}"
QBITTORRENT_USERNAME = "admin"
QBITTORRENT_PASSWORD = ""

# Media folder paths
MEDIA_FOLDERS = [r"C:\Media", r"D:\Media"]
ANIME_FOLDER = r"D:\Anime"
SERIES_FOLDER = r"D:\Series"

# Metadata provider configuration
# Supported: "imdb"
METADATA_PROVIDER = "imdb"

# IMDb integration (API-key-less)
IMDB_FIND_BASE_URL = "https://www.imdb.com/find/"
IMDB_SUGGEST_BASE_URL = "https://v2.sg.media-imdb.com/suggestion"

# ANSI color codes for console output
class Colors:
    CYAN = '\033[96m'      # Bright cyan for movie titles
    YELLOW = '\033[93m'    # Yellow for symlink paths and season names
    GREEN = '\033[92m'     # Green for target paths
    RED = '\033[91m'       # Red for broken links
    MAGENTA = '\033[95m'   # Magenta for anime titles
    RESET = '\033[0m'      # Reset color

# Video file extensions
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi')

# Background monitoring settings
TORRENT_CHECK_INTERVAL = 30  # seconds
NOTIFICATION_RETENTION_HOURS = 24

# Jellyfin cleanup file types
JELLYFIN_CLEANUP_EXTENSIONS = ('.nfo', '.jpg', '.jpeg')

# Application settings
APP_TITLE = "🎬 JELLYFIN LIBRARY MANAGER"
