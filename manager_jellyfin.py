import os
import shutil
import msvcrt
import time
import glob
import requests
import threading
import feedparser
from typing import List, Tuple, Optional
from bs4 import BeautifulSoup

# ANSI color codes
CYAN = '\033[96m'      # Bright cyan for movie titles
YELLOW = '\033[93m'    # Yellow for symlink paths and season names
GREEN = '\033[92m'     # Green for target paths
RED = '\033[91m'       # Red for broken links
MAGENTA = '\033[95m'   # Magenta for anime titles
RESET = '\033[0m'      # Reset color

# Import readline with Windows compatibility
try:
    import readline
except ImportError:
    try:
        import pyreadline3 as readline
    except ImportError:
        try:
            import pyreadline as readline
        except ImportError:
            readline = None

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def display_menu_with_selection(options: List[str], selected_index: int, title: str = "🎬 JELLYFIN LIBRARY MANAGER"):
    """Display menu with highlighted selection."""
    clear_screen()
    print("=" * 50)
    print(title)
    print("=" * 50)
    
    for i, option in enumerate(options):
        if i == selected_index:
            print(f"➤ {option} ⬅")  # Highlighted option
        else:
            print(f"  {option}")
    
    print("=" * 50)
    print("💡 Use ↑↓ arrow keys to navigate, Enter to select, Esc to exit")

def navigate_menu(options: List[str], title: str = "🎬 JELLYFIN LIBRARY MANAGER") -> int:
    """Navigate menu with arrow keys. Returns selected index or -1 for exit."""
    selected_index = 0
    
    while True:
        display_menu_with_selection(options, selected_index, title)
        
        # Wait for key press using msvcrt
        key = msvcrt.getch()
        
        if key == b'\xe0':  # Arrow key prefix on Windows
            key = msvcrt.getch()  # Get the actual arrow key
            if key == b'H':  # Up arrow
                selected_index = (selected_index - 1) % len(options)
            elif key == b'P':  # Down arrow
                selected_index = (selected_index + 1) % len(options)
        elif key == b'\r':  # Enter key
            return selected_index
        elif key == b'\x1b':  # Escape key
            return -1

def is_video_file(file_path: str) -> bool:
    """Check if file has a video extension."""
    return file_path.lower().endswith(('.mkv', '.mp4', '.avi'))

def get_media_folder(movie_path: str) -> str:
    """Determine media folder based on movie's drive."""
    drive = os.path.splitdrive(movie_path)[0].upper()
    return r"C:\Media" if drive == "C:" else r"D:\Media"

def get_all_media_folders() -> List[str]:
    """Get all media folders to search."""
    return [r"C:\Media", r"D:\Media"]

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

def path_completer(text, state):
    """Path completion function for readline."""
    try:
        # Handle different path formats
        original_text = text
        add_quote = False
        
        if text.startswith('"'):
            # Remove leading quote for processing
            text = text[1:]
            add_quote = True
        
        # Expand user directory (~)
        text = os.path.expanduser(text)
        
        # Normalize path separators for Windows
        text = text.replace('/', os.sep)
        
        # If text is empty, start from current directory
        if not text:
            pattern = '*'
        # If text is just a drive letter, add separator
        elif len(text) == 2 and text[1] == ':':
            pattern = text + os.sep + '*'
        # If text ends with separator, look for contents of that directory
        elif text.endswith(os.sep):
            pattern = text + '*'
        else:
            # Look for files/folders that start with the given text
            pattern = text + '*'
        
        # Get matches using glob
        try:
            matches = glob.glob(pattern)
        except Exception:
            matches = []
        
        # Filter and format matches
        filtered_matches = []
        for match in matches:
            # Convert to absolute path
            match = os.path.abspath(match)
            
            if os.path.isdir(match):
                # Add separator for directories and ensure it's properly formatted
                if not match.endswith(os.sep):
                    match += os.sep
                filtered_matches.append(match)
            elif is_video_file(match):
                # Include video files only
                filtered_matches.append(match)
        
        # Sort matches (directories first, then files)
        filtered_matches.sort(key=lambda x: (not x.endswith(os.sep), x.lower()))
        
        # Add quotes back if the original text had them
        if add_quote:
            filtered_matches = ['"' + match + '"' if not match.startswith('"') else match 
                              for match in filtered_matches]
        
        # Return the match for the current state
        if state < len(filtered_matches):
            return filtered_matches[state]
        else:
            return None
            
    except Exception:
        return None

def setup_autocomplete():
    """Setup readline for path autocomplete."""
    if readline is None:
        return False
    
    try:
        readline.set_completer(path_completer)
        readline.parse_and_bind("tab: complete")
        # Set word delimiters (don't break on path separators)
        readline.set_completer_delims(' \t\n')
        return True
    except Exception:
        return False

def wait_for_enter():
    """Wait for Enter key press."""
    input("\n📱 Press Enter to continue...")

def handle_input_cancellation():
    """Handle input cancellation (Ctrl+C or EOF)."""
    print("\n❌ Input cancelled.")
    wait_for_enter()

def display_movies():
    """Display all movies in the library."""
    movies = list_movies()
    
    if not movies:
        clear_screen()
        print("\n📁 No movies found in your Jellyfin library.")
        wait_for_enter()
        return
    
    clear_screen()
    print(f"\n📚 Your Jellyfin Library ({len(movies)} movies):")
    print("=" * 60)
    
    for i, (name, symlink_path, target_path) in enumerate(movies, 1):
        status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
        # Use cyan color for movie title
        print(f"{i:3d}. {CYAN}{name}{RESET}")
        print(f"     📍 Symlink: {YELLOW}{symlink_path}{RESET}")
        if target_path != "BROKEN LINK":
            print(f"     🎬 Target:  {GREEN}{target_path}{RESET}")
        else:
            print(f"     🎬 Target:  {RED}BROKEN LINK{RESET}")
        print(f"     {status}")
        print()
    
    wait_for_enter()

def validate_video_file(file_path, error_prefix="❌ Error"):
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

def validate_directory(dir_path, error_prefix="❌ Error"):
    """Validate that a directory exists."""
    if not dir_path:
        print(f"{error_prefix}: No path provided.")
        return False
    
    dir_path = os.path.abspath(dir_path)
    
    if not os.path.isdir(dir_path):
        print(f"{error_prefix}: '{dir_path}' does not exist or is not a folder.")
        return False
    
    return True

def add_movie():
    """Add a new movie to the library."""
    clear_screen()
    print("\n➕ Add New Movie")
    print("=" * 30)
    
    # Setup autocomplete
    autocomplete_enabled = setup_autocomplete()
    
    if autocomplete_enabled:
        print("💡 Use Tab for autocomplete, arrow keys to navigate suggestions")
    print("💡 You can drag & drop a file or type the path manually")
    print()
    
    try:
        movie_path = input("Enter the path to the movie file: ").strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        handle_input_cancellation()
        return
    
    if not validate_video_file(movie_path):
        wait_for_enter()
        return
    
    # Convert to absolute path for processing
    movie_path = os.path.abspath(movie_path)
    
    # Check if movie already exists
    media_folders = get_all_media_folders()
    existing_symlink, existing_subfolder = find_existing_symlink(movie_path, media_folders)
    
    if existing_symlink:
        movie_name = os.path.splitext(os.path.basename(movie_path))[0]
        print(f"⚠️  Movie '{movie_name}' already exists at '{existing_symlink}'.")
        
        action_options = ["⏭️  Skip", "🔄 Overwrite existing"]
        action_choice = navigate_menu(action_options, f"Movie '{movie_name}' already exists")
        
        if action_choice == 0:  # Skip
            clear_screen()
            print("⏭️  Skipping.")
            wait_for_enter()
            return
        elif action_choice == 1:  # Overwrite
            shutil.rmtree(existing_subfolder, ignore_errors=True)
            clear_screen()
            print(f"🗑️  Removed existing subfolder '{existing_subfolder}'.")
        else:
            clear_screen()
            print("❌ Cancelled.")
            wait_for_enter()
            return
    
    # Create new symlink
    media_folder = get_media_folder(movie_path)
    movie_name = os.path.splitext(os.path.basename(movie_path))[0]
    subfolder = os.path.join(media_folder, movie_name)
    new_symlink = os.path.join(subfolder, os.path.basename(movie_path))
    
    try:
        os.makedirs(subfolder, exist_ok=True)
        os.symlink(movie_path, new_symlink)
        clear_screen()
        print(f"✅ Success: Symlink created at '{new_symlink}'.")
        print(f"🔗 The symlink points to: {movie_path}")
        print("💡 The original file must remain in place for Jellyfin to access it.")
        
        wait_for_enter()
                
    except Exception as e:
        clear_screen()
        print(f"❌ Error creating symlink: {e}")
        print("💡 Ensure script is run as administrator.")
        wait_for_enter()

def remove_movie():
    """Remove a movie from the library."""
    movies = list_movies()
    
    if not movies:
        clear_screen()
        print("\n📁 No movies found in your Jellyfin library.")
        wait_for_enter()
        return
    
    # Create menu options
    movie_options = []
    for i, (name, symlink_path, target_path) in enumerate(movies, 1):
        status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
        movie_options.append(f"{i:3d}. {name} {status}")
    
    movie_options.append("🔙 Back to main menu")
    
    # Navigate through movies
    choice = navigate_menu(movie_options, "🗑️  REMOVE MOVIE")
    
    if choice == -1 or choice == len(movies):  # Esc pressed or Back selected
        return
    
    if 0 <= choice < len(movies):
        movie_name, symlink_path, target_path = movies[choice]
        
        clear_screen()
        print(f"\n🎬 Selected: {movie_name}")
        print(f"📍 Symlink: {symlink_path}")
        if target_path != "BROKEN LINK":
            print(f"🎬 Target: {target_path}")
        
        # Confirm removal
        confirm_options = ["❌ No, cancel", "✅ Yes, remove from library"]
        confirm_choice = navigate_menu(confirm_options, f"❓ Remove '{movie_name}' from library?")
        
        if confirm_choice != 1:  # Not "Yes"
            clear_screen()
            print("⏭️  Cancelled.")
            wait_for_enter()
            return
        
        # Remove the subfolder (contains the symlink)
        subfolder = os.path.dirname(symlink_path)
        try:
            shutil.rmtree(subfolder, ignore_errors=True)
            clear_screen()
            print(f"✅ Removed movie '{movie_name}' from library.")
            
            # Ask about original file
            if target_path != "BROKEN LINK" and os.path.exists(target_path):
                delete_options = ["❌ No, keep original file", "🗑️  Yes, delete original file"]
                delete_choice = navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                
                if delete_choice == 1:  # Yes, delete
                    try:
                        os.remove(target_path)
                        clear_screen()
                        print(f"🗑️  Deleted original file '{target_path}'.")
                    except Exception as e:
                        clear_screen()
                        print(f"❌ Error deleting original file: {e}")
            
            wait_for_enter()
            
        except Exception as e:
            clear_screen()
            print(f"❌ Error removing movie: {e}")
            wait_for_enter()

def get_anime_folder() -> str:
    """Get the anime folder path."""
    return r"D:\Anime"

def is_episode_file(file_path: str) -> bool:
    """Check if file has an episode/video extension."""
    return file_path.lower().endswith(('.mkv', '.mp4', '.avi'))

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
                if os.path.isdir(item_path) and item.startswith("Season "):
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
                                        if is_episode_file(target):
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

def display_anime():
    """Display all anime in the library grouped by anime name."""
    anime_list = list_anime()
    
    if not anime_list:
        clear_screen()
        print("\n📺 No anime found in your library.")
        wait_for_enter()
        return
    
    clear_screen()
    print(f"\n📺 Your Anime Library ({len(anime_list)} series):")
    print("=" * 60)
    
    for i, (anime_name, seasons) in enumerate(anime_list, 1):
        # Count total episodes across all seasons
        total_episodes = 0
        broken_seasons = 0
        
        print(f"{i:3d}. {MAGENTA}{anime_name}{RESET}")
        
        for season_name, season_path, target_path in seasons:
            status = "❌ BROKEN" if target_path in ["BROKEN LINK", "ACCESS DENIED", "NO_SYMLINKS", "EMPTY"] else "✅ OK"
            
            if status == "❌ BROKEN":
                broken_seasons += 1
            
            print(f"     📍 {YELLOW}{season_name}{RESET}: {status}")
            
            if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY", "NO_SYMLINKS", "EMPTY"]:
                print(f"       🎬 Target: {GREEN}{target_path}{RESET}")
                # Count episodes by looking at the symlinks in the season folder itself
                try:
                    if os.path.exists(season_path):
                        episode_count = len([f for f in os.listdir(season_path) 
                                           if os.path.isfile(os.path.join(season_path, f)) and is_episode_file(f)])
                        total_episodes += episode_count
                        print(f"       📺 Episodes: {episode_count}")
                except:
                    pass
            elif target_path == "DIRECTORY":
                print(f"       📂 Type: Directory")
            elif target_path == "NO_SYMLINKS":
                print(f"       ⚠️  No valid symlinks found")
            elif target_path == "EMPTY":
                print(f"       📂 Empty season folder")
            else:
                print(f"       🎬 Target: {RED}{target_path}{RESET}")
        
        # Summary for the anime
        if total_episodes > 0:
            print(f"     📊 Total Episodes: {total_episodes}")
        if broken_seasons > 0:
            print(f"     ⚠️  Broken Seasons: {broken_seasons}")
        print()
    
    wait_for_enter()

def add_anime():
    """Add a new anime series to the library."""
    clear_screen()
    print("\n📺 Add New Anime Series")
    print("=" * 35)

    # Step 1: Ask user if they want to add from local files or download
    source_options = [
        "📁 Add from local files",
        "🌐 Download anime (via torrent)"
    ]
    source_choice = navigate_menu(source_options, "Select anime source")
    if source_choice == -1:
        print("\n❌ Cancelled.")
        wait_for_enter()
        return

    if source_choice == 0:
        # Local files: ask for anime name (for search/future use)
        try:
            anime_search_name = input("Enter the anime name to search (or leave empty to skip search): ").strip()
        except (EOFError, KeyboardInterrupt):
            handle_input_cancellation()
            return
        
        if anime_search_name:
            print(f"🔎 Searching for '{anime_search_name}'...")
            print()
            time.sleep(1)

        # Setup autocomplete
        autocomplete_enabled = setup_autocomplete()
        
        if autocomplete_enabled:
            print("💡 Use Tab for autocomplete when typing paths")
        print("💡 You can drag & drop a folder or type the path manually")
        print()
        
        try:
            anime_folder_path = input("Enter the path to the anime episodes folder: ").strip().strip('"')
        except (EOFError, KeyboardInterrupt):
            handle_input_cancellation()
            return
        
        if not validate_directory(anime_folder_path):
            wait_for_enter()
            return
        
        # Convert to absolute path for processing
        anime_folder_path = os.path.abspath(anime_folder_path)
        
        # Check if folder contains episode files
        episode_files = [f for f in os.listdir(anime_folder_path) 
                        if os.path.isfile(os.path.join(anime_folder_path, f)) and is_episode_file(f)]
        
        if not episode_files:
            print(f"❌ Error: No video files (.mkv, .mp4, .avi) found in '{anime_folder_path}'.")
            wait_for_enter()
            return
        
        print(f"✅ Found {len(episode_files)} episode(s) in the folder.")
        
        # Check for subfolders that might contain extras
        extras_folders = []
        for item in os.listdir(anime_folder_path):
            item_path = os.path.join(anime_folder_path, item)
            if os.path.isdir(item_path):
                # Check if this subfolder contains video files
                video_files_in_subfolder = [f for f in os.listdir(item_path) 
                                          if os.path.isfile(os.path.join(item_path, f)) and is_episode_file(f)]
                if video_files_in_subfolder:
                    extras_folders.append((item, item_path, len(video_files_in_subfolder)))
        
        if extras_folders:
            print(f"🎁 Found {len(extras_folders)} extras folder(s):")
            for folder_name, folder_path, video_count in extras_folders:
                print(f"   - '{folder_name}' ({video_count} video file(s))")
            print("💡 Video files from these folders will be linked individually to Season 00")
        
        # Ask for anime name
        try:
            anime_name = input("Enter the name for this anime series: ").strip()
        except (EOFError, KeyboardInterrupt):
            handle_input_cancellation()
            return
        
        if not anime_name:
            print("❌ No anime name provided.")
            wait_for_enter()
            return
        
        # Ask for season number
        try:
            season_input = input("Enter season number (leave empty for Season 01): ").strip()
        except (EOFError, KeyboardInterrupt):
            handle_input_cancellation()
            return
        
        # Default to season 1 if no input provided
        if not season_input:
            season_number = 1
        else:
            try:
                season_number = int(season_input)
                if season_number <= 0:
                    print("❌ Season number must be a positive integer.")
                    wait_for_enter()
                    return
            except ValueError:
                print("❌ Invalid season number. Please enter a number or leave empty.")
                wait_for_enter()
                return
        
        # Determine the final anime path structure (always with season)
        anime_base_folder = get_anime_folder()
        anime_main_folder = os.path.join(anime_base_folder, anime_name)
        season_str = f"{season_number:02d}"  # Format with leading zero
        season_folder = os.path.join(anime_main_folder, f"Season {season_str}")
        anime_symlink = season_folder
        
        # Check if anime already exists
        if os.path.exists(anime_symlink):
            print(f"⚠️  Season {season_str} for anime '{anime_name}' already exists at '{anime_symlink}'.")
            
            action_options = ["⏭️  Skip", "🔄 Overwrite existing"]
            action_choice = navigate_menu(action_options, f"Season {season_str} of '{anime_name}' already exists")
            
            if action_choice == 0:  # Skip
                clear_screen()
                print("⏭️  Skipping.")
                wait_for_enter()
                return
            elif action_choice == 1:  # Overwrite
                try:
                    if os.path.islink(anime_symlink):
                        os.remove(anime_symlink)
                    elif os.path.isdir(anime_symlink):
                        shutil.rmtree(anime_symlink)
                    clear_screen()
                    print(f"🗑️  Removed existing entry.")
                except Exception as e:
                    clear_screen()
                    print(f"❌ Error removing existing entry: {e}")
                    wait_for_enter()
                    return
            else:
                clear_screen()
                print("❌ Cancelled.")
                wait_for_enter()
                return
        
        # Create anime directory structure and symlinks
        try:
            # Create all necessary parent directories
            parent_dir = os.path.dirname(anime_symlink)
            os.makedirs(parent_dir, exist_ok=True)
            
            # Create symlinks for individual episode files in the main season (excluding extras folders)
            episode_files_linked = 0
            for episode_file in episode_files:
                source_file = os.path.join(anime_folder_path, episode_file)
                target_file = os.path.join(anime_symlink, episode_file)
                
                try:
                    # Create the season folder if it doesn't exist
                    os.makedirs(anime_symlink, exist_ok=True)
                    os.symlink(source_file, target_file)
                    episode_files_linked += 1
                except Exception as e:
                    print(f"⚠️  Warning: Could not create symlink for episode '{episode_file}': {e}")
            
            extras_linked = 0
            
            # Create Season 00 symlinks for individual video files from extras folders
            for folder_name, folder_path, video_count in extras_folders:
                extras_season_folder = os.path.join(anime_main_folder, "Season 00")
                
                try:
                    os.makedirs(extras_season_folder, exist_ok=True)
                    
                    # Get all video files from the extras folder
                    video_files = [f for f in os.listdir(folder_path) 
                                 if os.path.isfile(os.path.join(folder_path, f)) and is_episode_file(f)]
                    
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
            
            clear_screen()
            print(f"✅ Success: Anime symlinks created at 'D:/Anime/{anime_name}/'.")
            print(f"🔗 Main season contains {episode_files_linked} episode file symlinks")
            print(f"📺 Episodes found: {len(episode_files)}")
            print(f"🎯 Season: {season_str}")
            if extras_linked > 0:
                print(f"🎁 Extras linked: {extras_linked} video file(s) → Season 00")
            print("💡 The original files must remain in place for access to work.")
            
            wait_for_enter()
                    
        except Exception as e:
            clear_screen()
            print(f"❌ Error creating anime symlink: {e}")
            print("💡 Ensure script is run as administrator.")
            wait_for_enter()
    elif source_choice == 1:
        # Download via torrent: interactive AniList search
        selected = interactive_anilist_search()
        if not selected:
            print("❌ No anime selected or cancelled.")
            wait_for_enter()
            return
        title, year, aid = selected
        print(f"✅ Selected: {title} ({year}) [AniList ID: {aid}]")
        print("\nSearching nyaa.si for torrents (via RSS)...")
        nyaa_results = nyaa_rss_search(title, limit=50)  # Use RSS-based search
        if isinstance(nyaa_results, str):  # Error message
            print(nyaa_results)
            wait_for_enter()
            return
        if not nyaa_results:
            print("No torrents found for this anime on nyaa.si.")
            wait_for_enter()
            return
        # Use fake scroll to select a torrent
        while True:
            selected_torrent = navigate_nyaa_results(nyaa_results, window_size=10)
            if not selected_torrent:
                print("❌ Cancelled.")
                wait_for_enter()
                return
            # Show file tree, allow Esc to return to torrent list
            # Get the torrent page URL from the magnet/download link
            page_url = selected_torrent['link']
            if page_url.endswith('.torrent'):
                import re
                m = re.search(r'/download/(\d+)\.torrent', page_url)
                if m:
                    page_url = f'https://nyaa.si/view/{m.group(1)}'
            show_torrent_file_tree(page_url, rss_info=selected_torrent)
            # After Esc, return to torrent list for reselection

def remove_anime():
    """Remove an anime series or specific seasons from the library."""
    anime_list = list_anime()
    
    if not anime_list:
        clear_screen()
        print("\n📺 No anime found in your library.")
        wait_for_enter()
        return
    
    # Create menu options for anime selection
    anime_options = []
    for i, (anime_name, seasons) in enumerate(anime_list, 1):
        season_count = len(seasons)
        broken_count = sum(1 for _, _, target in seasons if target in ["BROKEN LINK", "ACCESS DENIED"])
        status = f"({season_count} season(s)" + (f", {broken_count} broken" if broken_count > 0 else "") + ")"
        anime_options.append(f"{i:3d}. {anime_name} {status}")
    
    anime_options.append("🔙 Back to main menu")
    
    # Navigate through anime
    choice = navigate_menu(anime_options, "🗑️  REMOVE ANIME")
    
    if choice == -1 or choice == len(anime_list):  # Esc pressed or Back selected
        return
    
    if 0 <= choice < len(anime_list):
        anime_name, seasons = anime_list[choice]
        
        # If only one season, skip season selection
        if len(seasons) == 1:
            season_name, season_path, target_path = seasons[0]
            
            clear_screen()
            print(f"\n📺 Selected: {anime_name}")
            print(f"🎯 Season: {season_name}")
            print(f"📍 Path: {season_path}")
            if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"]:
                print(f"🎬 Target: {target_path}")
            
            # Confirm removal
            confirm_options = ["❌ No, cancel", "✅ Yes, remove anime"]
            confirm_choice = navigate_menu(confirm_options, f"❓ Remove '{anime_name}'?")
            
            if confirm_choice != 1:
                clear_screen()
                print("⏭️  Cancelled.")
                wait_for_enter()
                return
            
            # Remove the entire anime folder
            anime_main_folder = os.path.dirname(season_path)
            
            # Safety check: Never remove the root anime folder
            anime_base_folder = get_anime_folder()
            if os.path.abspath(anime_main_folder) == os.path.abspath(anime_base_folder):
                clear_screen()
                print(f"❌ Error: Cannot remove root anime folder '{anime_base_folder}'.")
                wait_for_enter()
                return
            
            try:
                shutil.rmtree(anime_main_folder)
                clear_screen()
                print(f"✅ Removed anime '{anime_name}' from library.")
                
                # Ask about original folder
                if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"] and os.path.exists(target_path):
                    delete_options = ["❌ No, keep original folder", "🗑️  Yes, delete original folder"]
                    delete_choice = navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                    
                    if delete_choice == 1:
                        try:
                            shutil.rmtree(target_path)
                            clear_screen()
                            print(f"🗑️  Deleted original folder '{target_path}'.")
                        except Exception as e:
                            clear_screen()
                            print(f"❌ Error deleting original folder: {e}")
                    else:
                        # Clean up Jellyfin files
                        cleanup_jellyfin_files(target_path)
                
            except Exception as e:
                clear_screen()
                print(f"❌ Error removing anime: {e}")
            
            wait_for_enter()
            return
        
        # Multiple seasons - show season selection menu
        season_options = []
        for season_name, season_path, target_path in seasons:
            status = "❌ BROKEN" if target_path in ["BROKEN LINK", "ACCESS DENIED"] else "✅ OK"
            season_options.append(f"{season_name} {status}")
        
        season_options.append("🗑️  Remove ALL seasons")
        season_options.append("🔙 Back to anime list")
        
        season_choice = navigate_menu(season_options, f"🗑️  Remove from '{anime_name}'")
        
        if season_choice == -1 or season_choice == len(seasons) + 1:  # Esc or Back
            return
        elif season_choice == len(seasons):  # Remove ALL seasons
            # Confirm removal of entire anime
            confirm_options = ["❌ No, cancel", f"✅ Yes, remove all {len(seasons)} season(s)"]
            confirm_choice = navigate_menu(confirm_options, f"❓ Remove entire '{anime_name}' anime?")
            
            if confirm_choice != 1:
                clear_screen()
                print("⏭️  Cancelled.")
                wait_for_enter()
                return
            
            # Remove the entire anime folder
            anime_main_folder = os.path.dirname(seasons[0][1])
            
            # Safety check: Never remove the root anime folder
            anime_base_folder = get_anime_folder()
            if os.path.abspath(anime_main_folder) == os.path.abspath(anime_base_folder):
                clear_screen()
                print(f"❌ Error: Cannot remove root anime folder '{anime_base_folder}'.")
                wait_for_enter()
                return
            
            try:
                shutil.rmtree(anime_main_folder)
                clear_screen()
                print(f"✅ Removed entire anime '{anime_name}' from library.")
                
                # Ask about original folders
                original_folders = set()
                for _, _, target_path in seasons:
                    if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"] and os.path.exists(target_path):
                        original_folders.add(target_path)
                
                if original_folders:
                    for target_path in original_folders:
                        delete_options = ["❌ No, keep original folder", "🗑️  Yes, delete original folder"]
                        delete_choice = navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                        
                        if delete_choice == 1:
                            try:
                                shutil.rmtree(target_path)
                                clear_screen()
                                print(f"🗑️  Deleted original folder '{target_path}'.")
                            except Exception as e:
                                clear_screen()
                                print(f"❌ Error deleting original folder: {e}")
                        else:
                            # Clean up Jellyfin files
                            cleanup_jellyfin_files(target_path)
                else:
                    # No original folders found to handle
                    clear_screen()
                    print("ℹ️  No original folders to handle.")
                
            except Exception as e:
                clear_screen()
                print(f"❌ Error removing anime: {e}")
            
            wait_for_enter()
            
        elif 0 <= season_choice < len(seasons):  # Remove specific season
            season_name, season_path, target_path = seasons[season_choice]
            
            clear_screen()
            print(f"\n📺 Selected: {anime_name}")
            print(f"🎯 Season: {season_name}")
            print(f"📍 Path: {season_path}")
            if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"]:
                print(f"🎬 Target: {target_path}")
            
            # Confirm removal
            confirm_options = ["❌ No, cancel", f"✅ Yes, remove {season_name}"]
            confirm_choice = navigate_menu(confirm_options, f"❓ Remove '{season_name}' from '{anime_name}'?")
            
            if confirm_choice != 1:
                clear_screen()
                print("⏭️  Cancelled.")
                wait_for_enter()
                return
            
            try:
                # Remove the specific season
                if os.path.islink(season_path):
                    os.remove(season_path)
                elif os.path.isdir(season_path):
                    shutil.rmtree(season_path)
                
                # Check if this was the last season
                anime_main_folder = os.path.dirname(season_path)
                remaining_seasons = []
                if os.path.exists(anime_main_folder):
                    for item in os.listdir(anime_main_folder):
                        item_path = os.path.join(anime_main_folder, item)
                        if os.path.isdir(item_path) and item.startswith("Season"):
                            remaining_seasons.append(item)
                
                # If no seasons left, remove the main anime folder
                if not remaining_seasons:
                    # Safety check: Never remove the root anime folder
                    anime_base_folder = get_anime_folder()
                    if os.path.abspath(anime_main_folder) == os.path.abspath(anime_base_folder):
                        clear_screen()
                        print(f"✅ Removed {season_name} from '{anime_name}'.")
                        print(f"❌ Error: Cannot remove root anime folder '{anime_base_folder}'.")
                        wait_for_enter()
                        return
                    
                    try:
                        shutil.rmtree(anime_main_folder)
                        clear_screen()
                        print(f"✅ Removed {season_name} from '{anime_name}'.")
                        print(f"🗑️  No seasons remaining - removed main anime folder.")
                        
                        # Only ask about original folder when removing the last season
                        if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"] and os.path.exists(target_path):
                            delete_options = ["❌ No, keep original folder", "🗑️  Yes, delete original folder"]
                            delete_choice = navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                            
                            if delete_choice == 1:
                                try:
                                    shutil.rmtree(target_path)
                                    clear_screen()
                                    print(f"🗑️  Deleted original folder '{target_path}'.")
                                except Exception as e:
                                    clear_screen()
                                    print(f"❌ Error deleting original folder: {e}")
                            else:
                                # Clean up Jellyfin files
                                cleanup_jellyfin_files(target_path)
                        
                    except Exception as e:
                        clear_screen()
                        print(f"✅ Removed {season_name} from '{anime_name}'.")
                        print(f"⚠️  Warning: Could not remove empty main folder: {e}")
                else:
                    clear_screen()
                    print(f"✅ Removed {season_name} from '{anime_name}'.")
                    print(f"📁 {len(remaining_seasons)} season(s) remaining: {', '.join(remaining_seasons)}")
                
                # Don't ask about original folder when other seasons remain
                
            except Exception as e:
                clear_screen()
                print(f"❌ Error removing season: {e}")
            
            wait_for_enter()

def anilist_search(query: str, limit: int = 10):
    """Search AniList API for anime by name. Returns a list of (title, year, id)."""
    url = "https://graphql.anilist.co"
    graphql_query = {
        'query': '''
        query ($search: String, $perPage: Int) {
          Page(perPage: $perPage) {
            media(search: $search, type: ANIME) {
              id
              title { romaji english native }
              startDate { year }
            }
          }
        }
        ''',
        'variables': {'search': query, 'perPage': limit}
    }
    try:
        response = requests.post(url, json=graphql_query, timeout=5)
        response.raise_for_status()
        data = response.json()
        results = []
        for media in data['data']['Page']['media']:
            title = media['title']['english'] or media['title']['romaji'] or media['title']['native']
            year = media['startDate']['year']
            results.append((title, year, media['id']))
        return results
    except Exception as e:
        return f"Error: {e}"

def interactive_anilist_search():
    """Interactive search for anime using AniList API with pause detection and improved UX. Selection by number + Enter."""
    prompt = "Type the anime name (searches after 2s pause, Esc to cancel):"
    input_str = ''
    last_time = time.time()
    results = []
    search_thread = None
    last_query = ''
    min_pause = 2.0  # 2 seconds pause
    min_interval = 3.0  # Minimum interval between requests to avoid rate limit
    last_request_time = 0
    num_str = ''

    def do_search(query):
        nonlocal results, last_request_time
        results = anilist_search(query)
        last_request_time = time.time()
        print("\n" + "=" * 30)
        if isinstance(results, str):
            print(results)
        elif results:
            for i, (title, year, aid) in enumerate(results, 1):
                print(f"{i:2d}. {title} ({year}) [AniList ID: {aid}]")
        else:
            print("No results found.")
        print("\nContinue typing, or type number then Enter to select, Esc to cancel.")

    clear_screen()
    print(prompt)
    print()
    print(input_str, end='', flush=True)
    while True:
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key == '\r':  # Enter
                print()
                if num_str:
                    try:
                        idx = int(num_str) - 1
                        if results and not isinstance(results, str) and 0 <= idx < len(results):
                            return results[idx]
                    except Exception:
                        pass
                    num_str = ''
                else:
                    break
            elif key == '\x1b':  # Esc
                print("\n❌ Cancelled.")
                wait_for_enter()
                return None
            elif key == '\b':  # Backspace
                if num_str:
                    num_str = num_str[:-1]
                else:
                    input_str = input_str[:-1]
            elif key.isdigit():
                num_str += key
            else:
                input_str += key
                num_str = ''
            clear_screen()
            print(prompt)
            print()
            print(input_str, end='', flush=True)
            if num_str:
                print(f"\nSelected number: {num_str}")
            last_time = time.time()
        else:
            now = time.time()
            if input_str and (now - last_time > min_pause):
                # Only search if input changed and enough time since last request
                if (input_str != last_query) and (now - last_request_time > min_interval):
                    print("\n" + "=" * 30)
                    if search_thread is None or not search_thread.is_alive():
                        search_thread = threading.Thread(target=do_search, args=(input_str,))
                        search_thread.start()
                    last_query = input_str
                    last_time = now  # Prevent repeated searches
            time.sleep(0.05)
    # After Enter, let user pick from results if any (fallback)
    if results and not isinstance(results, str):
        print("\nSelect an anime by number, or press Enter to cancel:")
        try:
            sel = input().strip()
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(results):
                    return results[idx]
        except Exception:
            pass
    return None

def cleanup_jellyfin_files(target_path):
    """Helper function to clean up Jellyfin files from a folder."""
    try:
        cleaned_files = []
        for file in os.listdir(target_path):
            file_path = os.path.join(target_path, file)
            if os.path.isfile(file_path) and file.lower().endswith(('.nfo', '.jpg', '.jpeg')):
                os.remove(file_path)
                cleaned_files.append(file)
        
        if cleaned_files:
            clear_screen()
            print(f"🧹 Cleaned up {len(cleaned_files)} Jellyfin files from original folder:")
            for file in cleaned_files:
                print(f"   - {file}")
        else:
            clear_screen()
            print("✅ No Jellyfin files to clean up in original folder.")
            
    except Exception as e:
        clear_screen()
        print(f"❌ Error cleaning up Jellyfin files: {e}")

def nyaa_rss_search(anime_name, limit=50):
    """Search nyaa.si RSS for torrents matching the anime name. Returns a list of dicts with title, seeds, size, and link."""
    import urllib.parse
    rss_url = f"https://nyaa.si/?page=rss&q={urllib.parse.quote(anime_name)}&s=seeders&o=desc"
    
    try:
        feed = feedparser.parse(rss_url)
        results = []
        for entry in feed.entries[:limit]:
            # Extract all available fields from the RSS entry with error handling
            try:
                result = {
                    'title': getattr(entry, 'title', 'N/A'),
                    'link': getattr(entry, 'link', 'N/A'),
                    'seeds': int(getattr(entry, 'nyaa_seeders', 0) or 0),
                    'size': getattr(entry, 'nyaa_size', 'Unknown'),
                    'leechers': int(getattr(entry, 'nyaa_leechers', 0) or 0),
                    'downloads': int(getattr(entry, 'nyaa_downloads', 0) or 0),
                    'infohash': getattr(entry, 'nyaa_infohash', 'N/A'),
                    'category': getattr(entry, 'nyaa_category', 'N/A'),
                    'categoryId': getattr(entry, 'nyaa_categoryid', 'N/A'),
                    'published': getattr(entry, 'published', 'N/A'),
                    'guid': getattr(entry, 'guid', 'N/A')
                }
                results.append(result)
            except (ValueError, AttributeError, TypeError) as e:
                # Skip entries with parsing errors but continue with others
                continue
        return results
    except Exception as e:
        return f"Error fetching RSS feed: {e}"

def parse_size(size_str):
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

def sort_torrents(results, sort_by):
    """Sort torrent results by seeds or size."""
    if sort_by == 'seeds':
        return sorted(results, key=lambda x: x['seeds'], reverse=True)
    else:
        return sorted(results, key=lambda x: parse_size(x['size']), reverse=True)

def navigate_nyaa_results(results, window_size=10):
    """Allow user to scroll through nyaa.si results with up/down keys and select one by number after Enter. Hotkey 's' switches sort between seeds/size. Preview selected item by number."""
    if not results:
        return None
    start_idx = 0
    max_idx = len(results) - 1
    num_str = ''
    sort_by = 'seeds'  # or 'size'
    while True:
        # Sort results by current sort key
        sorted_results = sort_torrents(results, sort_by)
        clear_screen()
        print(f"Navigate with ↑↓, type number then Enter to select, 's' to sort by {'size' if sort_by == 'seeds' else 'seeds'}, Esc to cancel\n")
        print(f"{'#':<2} {'Seeds':<6} {'Size':<10} Title")
        print("-" * 60)
        for i in range(window_size):
            idx = start_idx + i
            if idx > max_idx:
                break
            torrent = sorted_results[idx]
            title = torrent['title']
            if len(title) > 100:
                title = title[:97] + '...'
            print(f"{idx+1:<2} {torrent['seeds']:<6} {torrent['size']:<10} {title}")
        if num_str:
            print(f"\nSelected number: {num_str}")
            try:
                idx = int(num_str) - 1
                if 0 <= idx <= max_idx:
                    preview = sorted_results[idx]
                    print("\nPreview:")
                    print(f"Title: {preview['title']}")
                    print(f"Seeds: {preview['seeds']}")
                    print(f"Size: {preview['size']}")
                    print(f"Link: {preview['link']}")
            except Exception:
                pass
        key = msvcrt.getch()
        if key == b'\xe0':  # Arrow key prefix
            key = msvcrt.getch()
            if key == b'P':  # Down
                if start_idx + window_size <= max_idx:
                    start_idx += 1
            elif key == b'H':  # Up
                if start_idx > 0:
                    start_idx -= 1
        elif key == b'\x1b':  # Esc
            return None
        elif key == b's':
            sort_by = 'size' if sort_by == 'seeds' else 'seeds'
            start_idx = 0
        elif key.isdigit():
            num_str += key.decode()
        elif key == b'\r':  # Enter
            if num_str:
                idx = int(num_str) - 1
                if 0 <= idx <= max_idx:
                    return sorted_results[idx]
                else:
                    num_str = ''  # Invalid, reset
            # If Enter with no number, do nothing
        else:
            num_str = ''  # Reset on any other key

def get_torrent_file_list(torrent_page_url):
    """Scrape the torrent page to get the file list, preserving folder structure and file sizes. Also returns torrent info at the top."""
    try:
        resp = requests.get(torrent_page_url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        file_tree = []
        # --- Extract torrent info ---
        info_lines = []
        # Title
        title_tag = soup.find('h3')
        if title_tag:
            info_lines.append(f"Title: {title_tag.get_text(strip=True)}")
        # Info table (contains size, date, seeders, leechers, downloads, etc.)
        info_table = soup.find('table', class_='torrent-info')
        if info_table:
            for row in info_table.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) == 2:
                    key = cols[0].get_text(strip=True)
                    val = cols[1].get_text(strip=True)
                    info_lines.append(f"{key}: {val}")
        else:
            # Fallback: extract info from sidebar <div class='panel-body'>
            sidebar = soup.find('div', class_='panel-body')
            if sidebar:
                # Handle <div><b>Key:</b> Value</div> pairs
                for div in sidebar.find_all('div', recursive=False):
                    b_tag = div.find('b')
                    if b_tag:
                        key = b_tag.get_text(strip=True).rstrip(':')
                        val = b_tag.next_sibling
                        if val:
                            val = val.strip().lstrip(':').strip()
                        else:
                            val = div.get_text(strip=True).replace(b_tag.get_text(strip=True), '').strip()
                        info_lines.append(f"{key}: {val}")
                # Handle <dl><dt>Key</dt><dd>Value</dd></dl> pairs
                for dl in sidebar.find_all('dl'):
                    dt_tags = dl.find_all('dt')
                    dd_tags = dl.find_all('dd')
                    for dt, dd in zip(dt_tags, dd_tags):
                        key = dt.get_text(strip=True)
                        val = dd.get_text(strip=True)
                        info_lines.append(f"{key}: {val}")
        # --- File list extraction ---
        file_list_div = soup.find('div', class_='torrent-file-list')
        if not file_list_div:
            return info_lines + ["No file list found."]
        def parse_ul(ul, prefix=""):
            items = []
            for li in ul.find_all('li', recursive=False):
                folder_a = li.find('a', class_='folder')
                sub_ul = li.find('ul', recursive=False)
                if folder_a and sub_ul:
                    folder_name = folder_a.get_text(strip=True)
                    items.append(prefix + folder_name + "/")
                    items.extend(parse_ul(sub_ul, prefix + "    "))
                else:
                    file_name = li.get_text(strip=True, separator=' ')
                    size_span = li.find('span', class_='file-size')
                    if size_span:
                        file_name = file_name.replace(size_span.text, '').strip()
                        file_name += f" ({size_span.text.strip()})"
                    items.append(prefix + file_name)
            return items
        root_ul = file_list_div.find('ul', recursive=False)
        if root_ul:
            file_tree.extend(parse_ul(root_ul))
        # Add any additional info at the top
        file_tree = info_lines + [""] + file_tree
        return file_tree
    except Exception as e:
        return [f"Error: {e}"]

def show_torrent_file_tree(torrent_page_url, rss_info=None):
    """Show the file tree for a torrent, with RSS info at the top, allow Esc to return."""
    import msvcrt
    file_tree = get_torrent_file_list(torrent_page_url)
    clear_screen()
    print("Torrent Info:")
    if rss_info:
        print(f"Title: {rss_info.get('title', 'N/A')}")
        print(f"Size: {rss_info.get('size', 'N/A')}")
        print(f"Category: {rss_info.get('category', 'N/A')}")
        print(f"Seeders: {rss_info.get('seeds', 'N/A')}")
        print(f"Leechers: {rss_info.get('leechers', 'N/A')}")
        print(f"Downloads: {rss_info.get('downloads', 'N/A')}")
        print(f"InfoHash: {rss_info.get('infohash', 'N/A')}")
        print(f"Date: {rss_info.get('published', 'N/A')}")
        print(f"Link: {rss_info.get('link', 'N/A')}")
        print(f"GUID: {rss_info.get('guid', 'N/A')}")
        print()
    else:
        print("No RSS info found.\n")
    # Avoid printing the title again if it's the first line in file_tree
    if file_tree and file_tree[0].strip().startswith('Title:'):
        file_tree = file_tree[1:]
    for line in file_tree:
        print(line)
    print("\nTorrent File List (Esc to return)")
    while True:
        if msvcrt.kbhit():
            key = msvcrt.getch()
            if key == b'\x1b':  # Esc
                return
        time.sleep(0.05)

def main():
    """Main program loop."""
    clear_screen()
    print("🎬 Welcome to Jellyfin Library Manager!")
    print("💡 Use arrow keys to navigate, Enter to select, Esc to exit")
    
    # Use wait_for_enter for initial prompt
    wait_for_enter()
    
    main_options = [
        "1. 📚 List movies in library",
        "2. ➕ Add new movie to library", 
        "3. 🗑️  Remove movie from library",
        "4. 📺 List anime in library",
        "5. ➕ Add new anime to library",
        "6. 🗑️  Remove anime from library",
        "7. 🔍 Search anime on AniList",
        "8. 🚪 Exit"
    ]
    
    while True:
        try:
            choice = navigate_menu(main_options)
            
            if choice == -1 or choice == 7:  # Exit
                clear_screen()
                print("👋 Goodbye!")
                break
            elif choice == 0:  # List movies
                display_movies()
            elif choice == 1:  # Add movie
                add_movie()
            elif choice == 2:  # Remove movie
                remove_movie()
            elif choice == 3:  # List anime
                display_anime()
            elif choice == 4:  # Add anime
                add_anime()
            elif choice == 5:  # Remove anime
                remove_anime()
            elif choice == 6:  # Search anime
                interactive_anilist_search()
                
        except KeyboardInterrupt:
            clear_screen()
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            clear_screen()
            print(f"❌ An error occurred: {e}")
            wait_for_enter()

if __name__ == "__main__":
    main()
