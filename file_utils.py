"""
File system utilities for the Jellyfin Library Manager.
"""

import os
import glob
import shutil
from typing import List, Tuple, Optional
from utils import is_video_file, get_all_media_folders, get_anime_folder
from config import JELLYFIN_CLEANUP_EXTENSIONS


def find_existing_symlink(movie_path: str, media_folders: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Find if movie symlink exists in any subfolder of media_folders."""
    movie_name = os.path.splitext(os.path.basename(movie_path))[0]
    for media_folder in media_folders:
        if not os.path.exists(media_folder):
            continue
        for root, _, files in os.walk(media_folder):
            for file in files:
                if os.path.splitext(file)[0] == movie_name and os.path.islink(os.path.join(root, file)):
                    return os.path.join(root, file), root
    return None, None


def list_movies() -> List[Tuple[str, str, str]]:
    """List all movies in the Jellyfin library. Returns list of (name, symlink_path, target_path)."""
    movies = []
    media_folders = get_all_media_folders()
    
    for media_folder in media_folders:
        if not os.path.exists(media_folder):
            continue
        
        for root, dirs, files in os.walk(media_folder):
            for file in files:
                file_path = os.path.join(root, file)
                if is_video_file(file) and os.path.islink(file_path):
                    try:
                        target = os.readlink(file_path)
                        movie_name = os.path.splitext(file)[0]
                        movies.append((movie_name, file_path, target))
                    except OSError:
                        # Broken symlink
                        movie_name = os.path.splitext(file)[0]
                        movies.append((movie_name, file_path, "BROKEN LINK"))
    
    return sorted(movies, key=lambda x: x[0].lower())


def list_anime() -> List[Tuple[str, List[Tuple[str, str, str]]]]:
    """List all anime in the library grouped by anime name. Returns list of (anime_name, [(season_name, season_path, target_path)])."""
    anime_dict = {}
    anime_folder = get_anime_folder()
    
    if not os.path.exists(anime_folder):
        return []
    
    # First, collect all seasons
    for anime_name in os.listdir(anime_folder):
        anime_path = os.path.join(anime_folder, anime_name)
        if os.path.isdir(anime_path) and not os.path.islink(anime_path):
            seasons = []
            
            # Check for season folders
            for item in os.listdir(anime_path):
                item_path = os.path.join(anime_path, item)
                if os.path.isdir(item_path) and (item.startswith("Season ") or item == "Movies"):
                    try:
                        season_contents = os.listdir(item_path)
                        if season_contents:
                            # Look for any symlink in the season folder
                            found_symlink = False
                            target = None
                            
                            for content_item in season_contents:
                                content_item_path = os.path.join(item_path, content_item)
                                if os.path.islink(content_item_path):
                                    try:
                                        target = os.readlink(content_item_path)
                                        # For individual episode symlinks, get the parent directory
                                        if is_video_file(target):
                                            if item == "Season 00":
                                                # For Season 00 (extras), go up one more level to get the main anime folder
                                                target = os.path.dirname(os.path.dirname(target))
                                            else:
                                                # For regular seasons, get the parent directory
                                                target = os.path.dirname(target)
                                        found_symlink = True
                                        break
                                    except OSError:
                                        continue
                            
                            if found_symlink:
                                seasons.append((item, item_path, target))
                            else:
                                # No valid symlinks found
                                seasons.append((item, item_path, "NO_SYMLINKS"))
                        else:
                            # Empty season folder
                            seasons.append((item, item_path, "EMPTY"))
                    except PermissionError:
                        seasons.append((item, item_path, "ACCESS DENIED"))
            
            # If we found seasons, add to the dictionary
            if seasons:
                # Sort seasons by name
                seasons.sort(key=lambda x: x[0])
                anime_dict[anime_name] = seasons
        elif os.path.islink(anime_path):
            # Handle old-style direct symlinks
            try:
                target = os.readlink(anime_path)
                anime_dict[anime_name] = [("Direct Link", anime_path, target)]
            except OSError:
                anime_dict[anime_name] = [("Direct Link", anime_path, "BROKEN LINK")]
    
    # Convert to sorted list
    return sorted(anime_dict.items(), key=lambda x: x[0].lower())


def cleanup_jellyfin_files(target_path: str) -> None:
    """Helper function to clean up Jellyfin files from a folder."""
    try:
        cleaned_files = []
        for file in os.listdir(target_path):
            file_path = os.path.join(target_path, file)
            if os.path.isfile(file_path) and file.lower().endswith(JELLYFIN_CLEANUP_EXTENSIONS):
                os.remove(file_path)
                cleaned_files.append(file)
        
        if cleaned_files:
            from utils import clear_screen
            clear_screen()
            print(f"🧹 Cleaned up {len(cleaned_files)} Jellyfin files from original folder:")
            for file in cleaned_files:
                print(f"   - {file}")
        else:
            from utils import clear_screen
            clear_screen()
            print("✅ No Jellyfin files to clean up in original folder.")
            
    except Exception as e:
        from utils import clear_screen
        clear_screen()
        print(f"❌ Error cleaning up Jellyfin files: {e}")


def create_movie_symlink(movie_path: str, media_folder: str) -> Tuple[bool, str]:
    """Create a symlink for a movie in the media library."""
    try:
        movie_name = os.path.splitext(os.path.basename(movie_path))[0]
        subfolder = os.path.join(media_folder, movie_name)
        new_symlink = os.path.join(subfolder, os.path.basename(movie_path))
        
        os.makedirs(subfolder, exist_ok=True)
        os.symlink(movie_path, new_symlink)
        
        return True, new_symlink
    except Exception as e:
        return False, str(e)


def create_anime_symlinks(anime_folder_path: str, anime_name: str, season_number: int) -> Tuple[bool, str, int, int]:
    """Create symlinks for an anime series."""
    try:
        # Check if folder contains episode files
        episode_files = [f for f in os.listdir(anime_folder_path) 
                        if os.path.isfile(os.path.join(anime_folder_path, f)) and is_video_file(f)]
        
        if not episode_files:
            return False, f"No video files found in '{anime_folder_path}'", 0, 0
        
        # Check for subfolders that might contain extras
        extras_folders = []
        for item in os.listdir(anime_folder_path):
            item_path = os.path.join(anime_folder_path, item)
            if os.path.isdir(item_path):
                # Check if this subfolder contains video files
                video_files_in_subfolder = [f for f in os.listdir(item_path) 
                                          if os.path.isfile(os.path.join(item_path, f)) and is_video_file(f)]
                if video_files_in_subfolder:
                    extras_folders.append((item, item_path, len(video_files_in_subfolder)))
        
        # Determine the final anime path structure
        anime_base_folder = get_anime_folder()
        anime_main_folder = os.path.join(anime_base_folder, anime_name)
        season_str = f"{season_number:02d}"
        season_folder = os.path.join(anime_main_folder, f"Season {season_str}")
        
        # Create all necessary parent directories
        os.makedirs(season_folder, exist_ok=True)
        
        # Create symlinks for individual episode files
        episode_files_linked = 0
        for episode_file in episode_files:
            source_file = os.path.join(anime_folder_path, episode_file)
            target_file = os.path.join(season_folder, episode_file)
            
            try:
                os.symlink(source_file, target_file)
                episode_files_linked += 1
            except Exception as e:
                print(f"⚠️  Warning: Could not create symlink for episode '{episode_file}': {e}")
        
        # Create Season 00 symlinks for individual video files from extras folders
        extras_linked = 0
        for folder_name, folder_path, video_count in extras_folders:
            extras_season_folder = os.path.join(anime_main_folder, "Season 00")
            
            try:
                os.makedirs(extras_season_folder, exist_ok=True)
                
                # Get all video files from the extras folder
                video_files = [f for f in os.listdir(folder_path) 
                             if os.path.isfile(os.path.join(folder_path, f)) and is_video_file(f)]
                
                # Create symlinks for each video file directly in Season 00
                for video_file in video_files:
                    source_file = os.path.join(folder_path, video_file)
                    # Use folder name as prefix to avoid conflicts
                    target_filename = f"{folder_name} - {video_file}"
                    extras_symlink = os.path.join(extras_season_folder, target_filename)
                    
                    try:
                        os.symlink(source_file, extras_symlink)
                        extras_linked += 1
                    except Exception as e:
                        print(f"⚠️  Warning: Could not create symlink for '{video_file}': {e}")
                
            except Exception as e:
                print(f"⚠️  Warning: Could not process extras folder '{folder_name}': {e}")
        
        return True, season_folder, episode_files_linked, extras_linked
        
    except Exception as e:
        return False, str(e), 0, 0


def remove_symlink_safely(path: str) -> bool:
    """Safely remove a symlink or directory."""
    try:
        if os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"❌ Error removing path '{path}': {e}")
        return False


# [REMOVED] Old readline-based autocomplete functions have been replaced 
# with custom_autocomplete.py for better Windows compatibility and special character support.
