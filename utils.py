"""
Utility functions for the Jellyfin Library Manager.
"""

import os
import time
from typing import Optional
from config import VIDEO_EXTENSIONS


def format_bytes(bytes_val: int) -> str:
    """Convert bytes to human readable format."""
    if bytes_val == 0:
        return "0 B"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def format_speed(bytes_per_sec: int) -> str:
    """Convert bytes per second to human readable format."""
    return f"{format_bytes(bytes_per_sec)}/s"


def format_eta(seconds: int) -> str:
    """Convert seconds to human readable ETA."""
    if seconds <= 0 or seconds == 8640000:  # 8640000 is qBittorrent's "infinity"
        return "∞"
    
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        return f"{days}d {hours}h"


def is_video_file(file_path: str) -> bool:
    """Check if file has a video extension."""
    return file_path.lower().endswith(VIDEO_EXTENSIONS)


def is_episode_file(file_path: str) -> bool:
    """Check if file has an episode/video extension."""
    return file_path.lower().endswith(VIDEO_EXTENSIONS)


def parse_size(size_str: str) -> int:
    """Parse size string like '1.2 GiB' or '700 MiB' to bytes for sorting."""
    try:
        size_str = size_str.strip().upper()
        parts = size_str.split()
        if len(parts) < 2:
            return 0
        
        num = float(parts[0])
        unit = parts[1]
        
        multipliers = {
            'G': 1024 ** 3, 'GIB': 1024 ** 3, 'GB': 1024 ** 3,
            'M': 1024 ** 2, 'MIB': 1024 ** 2, 'MB': 1024 ** 2,
            'K': 1024, 'KIB': 1024, 'KB': 1024
        }
        
        for prefix, multiplier in multipliers.items():
            if unit.startswith(prefix):
                return int(num * multiplier)
        
        return int(num)
    except (ValueError, IndexError):
        return 0


def validate_video_file(file_path: str, error_prefix: str = "❌ Error") -> bool:
    """Validate that a file exists and is a video file."""
    if not file_path:
        print(f"{error_prefix}: No path provided.")
        return False
    
    file_path = os.path.abspath(file_path)
    
    if not os.path.isfile(file_path):
        print(f"{error_prefix}: '{file_path}' does not exist or is not a file.")
        return False
    
    if not is_video_file(file_path):
        print(f"{error_prefix}: '{file_path}' is not a supported video file (.mkv, .mp4, .avi).")
        return False
    
    return True


def validate_directory(dir_path: str, error_prefix: str = "❌ Error") -> bool:
    """Validate that a directory exists."""
    if not dir_path:
        print(f"{error_prefix}: No path provided.")
        return False
    
    dir_path = os.path.abspath(dir_path)
    
    if not os.path.isdir(dir_path):
        print(f"{error_prefix}: '{dir_path}' does not exist or is not a folder.")
        return False
    
    return True


def get_current_timestamp() -> str:
    """Get current timestamp as formatted string."""
    return time.strftime("%H:%M:%S")


def wait_for_enter() -> None:
    """Wait for Enter key press."""
    input("\n📱 Press Enter to continue...")


def handle_input_cancellation() -> None:
    """Handle input cancellation (Ctrl+C or EOF)."""
    print("\n❌ Input cancelled.")
    wait_for_enter()


def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def get_media_folder(movie_path: str) -> str:
    """Determine media folder based on movie's drive."""
    from config import MEDIA_FOLDERS
    drive = os.path.splitdrive(movie_path)[0].upper()
    return MEDIA_FOLDERS[0] if drive == "C:" else MEDIA_FOLDERS[1]


def get_anime_folder() -> str:
    """Get the anime folder path."""
    from config import ANIME_FOLDER
    return ANIME_FOLDER


def get_all_media_folders() -> list:
    """Get all media folders to search."""
    from config import MEDIA_FOLDERS
    return MEDIA_FOLDERS
