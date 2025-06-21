"""
Anime management module for the Jellyfin Library Manager.
"""

import os
import shutil
from typing import List, Tuple
from config import Colors
from utils import clear_screen, wait_for_enter, validate_directory, is_episode_file
from ui import MenuSystem
from file_utils import list_anime, create_anime_symlinks, remove_symlink_safely, cleanup_jellyfin_files
from anilist_api import interactive_anilist_search
from nyaa_api import nyaa_rss_search, navigate_nyaa_results, show_torrent_file_tree
from qbittorrent_api import qb_check_connection, qb_login, qb_add_torrent
from database import add_torrent_to_database


class AnimeManager:
    """Class to handle anime management operations."""
    
    def __init__(self):
        self.menu_system = MenuSystem()
    
    def display_anime(self) -> None:
        """Display all anime in the library grouped by anime name."""
        anime_list = list_anime()
        
        if not anime_list:
            self.menu_system.show_message("\n📺 No anime found in your library.")
            return
        
        clear_screen()
        print(f"\n📺 Your Anime Library ({len(anime_list)} series):")
        print("=" * 60)
        
        for i, (anime_name, seasons) in enumerate(anime_list, 1):
            # Count total episodes across all seasons
            total_episodes = 0
            broken_seasons = 0
            
            print(f"{i:3d}. {Colors.MAGENTA}{anime_name}{Colors.RESET}")
            
            for season_name, season_path, target_path in seasons:
                status = "❌ BROKEN" if target_path in ["BROKEN LINK", "ACCESS DENIED", "NO_SYMLINKS", "EMPTY"] else "✅ OK"
                
                if status == "❌ BROKEN":
                    broken_seasons += 1
                
                print(f"     📍 {Colors.YELLOW}{season_name}{Colors.RESET}: {status}")
                
                if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY", "NO_SYMLINKS", "EMPTY"]:
                    print(f"       🎬 Target: {Colors.GREEN}{target_path}{Colors.RESET}")
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
                    print(f"       🎬 Target: {Colors.RED}{target_path}{Colors.RESET}")
            
            # Summary for the anime
            if total_episodes > 0:
                print(f"     📊 Total Episodes: {total_episodes}")
            if broken_seasons > 0:
                print(f"     ⚠️  Broken Seasons: {broken_seasons}")
            print()
        
        wait_for_enter()
    
    def add_anime(self) -> None:
        """Add a new anime series to the library."""
        clear_screen()
        print("\n📺 Add New Anime Series")
        print("=" * 35)

        # Step 1: Ask user if they want to add from local files or download
        source_options = [
            "📁 Add from local files",
            "🌐 Download anime (via torrent)"
        ]
        source_choice = self.menu_system.navigate_menu(source_options, "Select anime source")
        if source_choice == -1:
            self.menu_system.show_message("\n❌ Cancelled.")
            return

        if source_choice == 0:
            self._add_anime_from_local_files()
        elif source_choice == 1:
            self._add_anime_via_download()
    
    def _add_anime_from_local_files(self) -> None:
        """Add anime from local files."""
        # Ask for anime name (for search/future use)
        anime_search_name = self.menu_system.get_user_input("Enter the anime name to search (or leave empty to skip search): ")
        
        if anime_search_name:
            print(f"🔎 Searching for '{anime_search_name}'...")
            print()
            import time
            time.sleep(1)

        # Setup autocomplete
        autocomplete_enabled = self.menu_system.setup_autocomplete()
        
        if autocomplete_enabled:
            print("💡 Use Tab for autocomplete when typing paths")
        print("💡 You can drag & drop a folder or type the path manually")
        print()
        
        anime_folder_path = self.menu_system.get_user_input("Enter the path to the anime episodes folder: ")
        if not anime_folder_path:
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
            self.menu_system.show_error(f"No video files (.mkv, .mp4, .avi) found in '{anime_folder_path}'.")
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
        anime_name = self.menu_system.get_user_input("Enter the name for this anime series: ")
        if not anime_name:
            self.menu_system.show_error("No anime name provided.")
            return
        
        # Ask for season number
        season_input = self.menu_system.get_user_input("Enter season number (leave empty for Season 01): ")
        
        # Default to season 1 if no input provided
        if not season_input:
            season_number = 1
        else:
            try:
                season_number = int(season_input)
                if season_number <= 0:
                    self.menu_system.show_error("Season number must be a positive integer.")
                    return
            except ValueError:
                self.menu_system.show_error("Invalid season number. Please enter a number or leave empty.")
                return
        
        # Check if anime already exists and handle accordingly
        from utils import get_anime_folder
        anime_base_folder = get_anime_folder()
        anime_main_folder = os.path.join(anime_base_folder, anime_name)
        season_str = f"{season_number:02d}"
        season_folder = os.path.join(anime_main_folder, f"Season {season_str}")
        
        if os.path.exists(season_folder):
            print(f"⚠️  Season {season_str} for anime '{anime_name}' already exists at '{season_folder}'.")
            
            action_options = ["⏭️  Skip", "🔄 Overwrite existing"]
            action_choice = self.menu_system.navigate_menu(action_options, f"Season {season_str} of '{anime_name}' already exists")
            
            if action_choice == 0:  # Skip
                self.menu_system.show_message("⏭️  Skipping.")
                return
            elif action_choice == 1:  # Overwrite
                if not remove_symlink_safely(season_folder):
                    return
                clear_screen()
                print(f"🗑️  Removed existing entry.")
            else:
                self.menu_system.show_message("❌ Cancelled.")
                return
        
        # Create anime directory structure and symlinks
        success, result, episode_files_linked, extras_linked = create_anime_symlinks(
            anime_folder_path, anime_name, season_number)
        
        if success:
            clear_screen()
            print(f"✅ Success: Anime symlinks created at 'D:/Anime/{anime_name}/'.")
            print(f"🔗 Main season contains {episode_files_linked} episode file symlinks")
            print(f"📺 Episodes found: {len(episode_files)}")
            print(f"🎯 Season: {season_str}")
            if extras_linked > 0:
                print(f"🎁 Extras linked: {extras_linked} video file(s) → Season 00")
            print("💡 The original files must remain in place for access to work.")
            wait_for_enter()
        else:
            clear_screen()
            print(f"❌ Error creating anime symlink: {result}")
            print("💡 Ensure script is run as administrator.")
            wait_for_enter()
    
    def _add_anime_via_download(self) -> None:
        """Add anime via torrent download."""
        # Interactive AniList search
        selected = interactive_anilist_search()
        if not selected:
            self.menu_system.show_message("❌ No anime selected or cancelled.")
            return
        
        title, year, aid = selected
        print(f"✅ Selected: {title} ({year}) [AniList ID: {aid}]")
        print("\nSearching nyaa.si for torrents (via RSS)...")
        
        nyaa_results = nyaa_rss_search(title, limit=100)
        if isinstance(nyaa_results, str):  # Error message
            self.menu_system.show_error(nyaa_results)
            return
        
        if not nyaa_results:
            self.menu_system.show_message("No torrents found for this anime on nyaa.si.")
            return
        
        # Use torrent selection to select a torrent
        anilist_info = {"title": title, "year": year, "id": aid}
        
        while True:
            selected_torrent = navigate_nyaa_results(nyaa_results, window_size=10)
            if selected_torrent == 'HOTKEY_MANUAL_SEARCH':
                custom_search = self.menu_system.get_user_input("Enter custom search term for nyaa.si: ")
                if not custom_search:
                    self.menu_system.show_message("❌ Cancelled custom search.")
                    continue
                nyaa_results = nyaa_rss_search(custom_search, limit=100)
                if isinstance(nyaa_results, str):
                    self.menu_system.show_error(nyaa_results)
                    return
                if not nyaa_results:
                    self.menu_system.show_message(f"No torrents found for '{custom_search}' on nyaa.si.")
                    continue
                continue  # Show new results
            if not selected_torrent:
                self.menu_system.show_message("❌ Cancelled.")
                return
            
            # Add AniList info to the selected torrent
            selected_torrent["anilist_info"] = anilist_info
            
            # Show file tree and get download confirmation
            page_url = selected_torrent['link']
            if page_url.endswith('.torrent'):
                import re
                m = re.search(r'/download/(\d+)\.torrent', page_url)
                if m:
                    page_url = f'https://nyaa.si/view/{m.group(1)}'
            
            download_requested = show_torrent_file_tree(page_url, rss_info=selected_torrent)
            
            if download_requested:
                if self._download_torrent(selected_torrent):
                    return  # Exit the torrent selection loop
            # If cancelled, continue the loop to show torrent list again
    
    def _download_torrent(self, selected_torrent: dict) -> bool:
        """Download a selected torrent."""
        # Show download confirmation
        clear_screen()
        print(f"📥 Download Torrent: {selected_torrent['title']}")
        print("=" * 60)
        print(f"🔗 Link: {selected_torrent['link']}")
        print(f"📊 Size: {selected_torrent['size']}")
        print(f"🌱 Seeds: {selected_torrent['seeds']}")
        print()
        
        if not self.menu_system.confirm_action("📥 Confirm Download"):
            return False
        
        clear_screen()
        print("🔄 Checking qBittorrent connection...")
        from config import QBITTORRENT_HOST, QBITTORRENT_URL
        print(f"🌐 Host: {QBITTORRENT_HOST}")
        print()
        
        # Check if qBittorrent is accessible
        if not qb_check_connection():
            self.menu_system.show_error(
                "Cannot connect to qBittorrent.\n"
                "💡 Make sure qBittorrent is running and Web UI is enabled.\n"
                f"💡 Check that Web UI is accessible at: {QBITTORRENT_URL}\n"
                "💡 Default Web UI settings:\n"
                "   - Port: 1337\n"
                "   - Username: admin\n"
                "   - Password: (usually empty)"
            )
            return False
        
        print("✅ qBittorrent is accessible!")
        print("🔄 Logging in...")
        
        # Try to connect to qBittorrent
        session = qb_login()
        if not session:
            self.menu_system.show_error(
                "Failed to authenticate with qBittorrent.\n"
                "💡 Check your qBittorrent Web UI credentials.\n"
                "💡 You may need to disable authentication or set proper credentials."
            )
            return False
        
        print("✅ Connected to qBittorrent successfully!")
        print(f"📥 Adding torrent: {selected_torrent['title'][:60]}...")
        print()
        
        # Ask for download location
        download_options = [
            "📁 Use default download location",
            "📂 Specify custom download path"
        ]
        location_choice = self.menu_system.navigate_menu(download_options, "📁 Download Location")
        
        download_path = None
        if location_choice == 1:  # Custom path
            download_path = self._get_custom_download_path()
            if download_path is None:  # Cancelled
                return False
        
        # Add torrent to qBittorrent
        clear_screen()
        print("📥 Adding torrent to qBittorrent...")
        if download_path:
            print(f"📁 Download location: {download_path}")
        else:
            print("📁 Using default download location")
        print()
        
        success = qb_add_torrent(session, selected_torrent['link'], download_path)
        
        if success:
            # Add torrent to tracking database
            torrent_db_info = selected_torrent.copy()
            torrent_db_info["download_path"] = download_path or "Default"
            
            torrent_id = add_torrent_to_database(torrent_db_info)
            clear_screen()
            print("✅ Torrent added successfully!")
            print(f"🎬 Title: {selected_torrent['title']}")
            print(f"📊 Size: {selected_torrent['size']}")
            if download_path:
                print(f"📁 Location: {download_path}")
            
            if torrent_id:
                print(f"🗃️  Database ID: #{torrent_id}")
                print("🗄️ Torrent added to tracking database")
                print("💡 You can monitor download progress in 'View tracked torrents'")
            else:
                print("⚠️  Warning: Could not save to tracking database")
            
            print()
            print("🔄 Torrent is now downloading in qBittorrent")
            
            # Show recent torrents
            from qbittorrent_api import qb_get_torrent_info
            print("\n🔄 Recent torrents in qBittorrent:")
            torrents = qb_get_torrent_info(session)
            if torrents:
                for i, torrent in enumerate(torrents[-3:], 1):  # Show last 3 torrents
                    state = torrent.get('state', 'unknown')
                    progress = torrent.get('progress', 0) * 100
                    print(f"  {i}. {torrent.get('name', 'Unknown')[:50]}...")
                    print(f"     State: {state} | Progress: {progress:.1f}%")
            
            wait_for_enter()
            return True
        else:
            self.menu_system.show_error(
                "Failed to add torrent to qBittorrent.\n"
                "💡 Check qBittorrent logs for more details."
            )
            return False
    
    def _get_custom_download_path(self) -> str:
        """Get custom download path from user."""
        clear_screen()
        print("📂 Custom Download Path")
        print("=" * 30)
        
        # Setup autocomplete for path input
        autocomplete_enabled = self.menu_system.setup_autocomplete()
        if autocomplete_enabled:
            print("💡 Use Tab for autocomplete when typing paths")
        
        download_path = self.menu_system.get_user_input("Enter download path (or leave empty for default): ")
        if not download_path:
            return None
        
        if not os.path.isdir(download_path):
            print(f"⚠️  Directory '{download_path}' does not exist.")
            create_options = ["❌ Cancel download", "📁 Create directory", "📂 Use default location"]
            create_choice = self.menu_system.navigate_menu(create_options, "Directory not found")
            
            if create_choice == 0:  # Cancel
                self.menu_system.show_message("❌ Download cancelled.")
                return None
            elif create_choice == 1:  # Create directory
                try:
                    os.makedirs(download_path, exist_ok=True)
                    clear_screen()
                    print(f"📁 Created directory: {download_path}")
                    return download_path
                except Exception as e:
                    self.menu_system.show_error(f"Failed to create directory: {e}")
                    return None
            else:  # Use default
                return None
        
        return download_path
    
    def remove_anime(self) -> None:
        """Remove an anime series or specific seasons from the library."""
        anime_list = list_anime()
        
        if not anime_list:
            self.menu_system.show_message("\n📺 No anime found in your library.")
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
        choice = self.menu_system.navigate_menu(anime_options, "🗑️  REMOVE ANIME")
        
        if choice == -1 or choice == len(anime_list):  # Esc pressed or Back selected
            return
        
        if 0 <= choice < len(anime_list):
            anime_name, seasons = anime_list[choice]
            
            # If only one season, skip season selection
            if len(seasons) == 1:
                self._remove_entire_anime(anime_name, seasons)
            else:
                self._remove_anime_with_season_selection(anime_name, seasons)
    
    def _remove_entire_anime(self, anime_name: str, seasons: list) -> None:
        """Remove an anime with only one season."""
        season_name, season_path, target_path = seasons[0]
        
        clear_screen()
        print(f"\n📺 Selected: {anime_name}")
        print(f"🎯 Season: {season_name}")
        print(f"📍 Path: {season_path}")
        if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"]:
            print(f"🎬 Target: {target_path}")
        
        # Confirm removal
        if not self.menu_system.confirm_action(f"❓ Remove '{anime_name}'?"):
            self.menu_system.show_message("⏭️  Cancelled.")
            return
        
        # Remove the entire anime folder
        anime_main_folder = os.path.dirname(season_path)
        
        # Safety check: Never remove the root anime folder
        from utils import get_anime_folder
        anime_base_folder = get_anime_folder()
        if os.path.abspath(anime_main_folder) == os.path.abspath(anime_base_folder):
            self.menu_system.show_error(f"Cannot remove root anime folder '{anime_base_folder}'.")
            return
        
        if remove_symlink_safely(anime_main_folder):
            clear_screen()
            print(f"✅ Removed anime '{anime_name}' from library.")

            # Check for associated torrent
            from database import TorrentDatabase
            from qbittorrent_api import qb_login, qb_remove_torrent
            torrent_db = TorrentDatabase()
            tracked_torrents = torrent_db.get_tracked_torrents()
            associated_torrent = None
            for torrent in tracked_torrents:
                if (
                    torrent.get("download_path") == target_path or
                    os.path.abspath(torrent.get("download_path", "")) == os.path.abspath(target_path)
                ):
                    associated_torrent = torrent
                    break

            if associated_torrent and associated_torrent.get("infohash") != "N/A":
                remove_options = [
                    "❌ No, keep torrent in qBittorrent",
                    "🗑️  Yes, remove torrent from qBittorrent (optionally delete files)"
                ]
                remove_choice = self.menu_system.navigate_menu(
                    remove_options,
                    f"🗑️  Also remove torrent '{associated_torrent.get('title', 'Unknown')}' from qBittorrent?"
                )
                if remove_choice == 1:
                    # Ask if user wants to delete files as well
                    delete_files_options = [
                        "❌ No, keep files on disk",
                        "🗑️  Yes, delete files from disk"
                    ]
                    delete_files_choice = self.menu_system.navigate_menu(
                        delete_files_options,
                        f"🗑️  Delete files for torrent '{associated_torrent.get('title', 'Unknown')}'?"
                    )
                    delete_files = delete_files_choice == 1
                    session = qb_login()
                    if session:
                        success = qb_remove_torrent(session, associated_torrent["infohash"], delete_files)
                        clear_screen()
                        if success:
                            print(f"🗑️  Removed torrent '{associated_torrent.get('title', 'Unknown')}' from qBittorrent.")
                        else:
                            print(f"❌ Failed to remove torrent from qBittorrent.")
                    else:
                        clear_screen()
                        print(f"❌ Could not connect to qBittorrent.")
                    wait_for_enter()
                    return  # Do not prompt for original folder deletion if torrent was handled

            # Fallback: Ask about original folder
            if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"] and os.path.exists(target_path):
                delete_options = ["❌ No, keep original folder", "🗑️  Yes, delete original folder"]
                delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
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

        wait_for_enter()
    
    def _remove_anime_with_season_selection(self, anime_name: str, seasons: list) -> None:
        """Remove anime with multiple seasons - show season selection."""
        season_options = []
        for season_name, season_path, target_path in seasons:
            status = "❌ BROKEN" if target_path in ["BROKEN LINK", "ACCESS DENIED"] else "✅ OK"
            season_options.append(f"{season_name} {status}")
        
        season_options.append("🗑️  Remove ALL seasons")
        season_options.append("🔙 Back to anime list")
        
        season_choice = self.menu_system.navigate_menu(season_options, f"🗑️  Remove from '{anime_name}'")
        
        if season_choice == -1 or season_choice == len(seasons) + 1:  # Esc or Back
            return
        elif season_choice == len(seasons):  # Remove ALL seasons
            self._remove_all_seasons(anime_name, seasons)
        elif 0 <= season_choice < len(seasons):  # Remove specific season
            self._remove_specific_season(anime_name, seasons, season_choice)
    
    def _remove_all_seasons(self, anime_name: str, seasons: list) -> None:
        """Remove all seasons of an anime."""
        # Confirm removal of entire anime
        if not self.menu_system.confirm_action(f"❓ Remove entire '{anime_name}' anime?", 
                                             ["❌ No, cancel", f"✅ Yes, remove all {len(seasons)} season(s)"]):
            self.menu_system.show_message("⏭️  Cancelled.")
            return
        
        # Remove the entire anime folder
        anime_main_folder = os.path.dirname(seasons[0][1])
        
        # Safety check: Never remove the root anime folder
        from utils import get_anime_folder
        anime_base_folder = get_anime_folder()
        if os.path.abspath(anime_main_folder) == os.path.abspath(anime_base_folder):
            self.menu_system.show_error(f"Cannot remove root anime folder '{anime_base_folder}'.")
            return
        
        if remove_symlink_safely(anime_main_folder):
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
                    delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                    
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
        
        wait_for_enter()
    
    def _remove_specific_season(self, anime_name: str, seasons: list, season_index: int) -> None:
        """Remove a specific season."""
        season_name, season_path, target_path = seasons[season_index]
        
        clear_screen()
        print(f"\n📺 Selected: {anime_name}")
        print(f"🎯 Season: {season_name}")
        print(f"📍 Path: {season_path}")
        if target_path not in ["BROKEN LINK", "ACCESS DENIED", "DIRECTORY"]:
            print(f"🎬 Target: {target_path}")
        
        # Confirm removal
        if not self.menu_system.confirm_action(f"❓ Remove '{season_name}' from '{anime_name}'?", 
                                             ["❌ No, cancel", f"✅ Yes, remove {season_name}"]):
            self.menu_system.show_message("⏭️  Cancelled.")
            return
        
        if remove_symlink_safely(season_path):
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
                from utils import get_anime_folder
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
                        delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                        
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
        
        wait_for_enter()


# Global instance for backward compatibility
_anime_manager = AnimeManager()


# Legacy functions for backward compatibility
def display_anime() -> None:
    """Display all anime in the library. (Legacy function)"""
    _anime_manager.display_anime()


def add_anime() -> None:
    """Add a new anime series to the library. (Legacy function)"""
    _anime_manager.add_anime()


def remove_anime() -> None:
    """Remove an anime series from the library. (Legacy function)"""
    _anime_manager.remove_anime()
