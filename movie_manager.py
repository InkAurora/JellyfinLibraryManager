"""
Movie management module for the Jellyfin Library Manager.
"""

import os
import shutil
from typing import List, Tuple
from config import Colors
from utils import clear_screen, wait_for_enter, get_media_folder, validate_video_file
from ui import MenuSystem
from file_utils import find_existing_symlink, list_movies, create_movie_symlink, remove_symlink_safely


class MovieManager:
    """Class to handle movie management operations."""
    
    def __init__(self):
        self.menu_system = MenuSystem()
    
    def display_movies(self) -> None:
        """Display all movies in the library."""
        movies = list_movies()
        
        if not movies:
            self.menu_system.show_message("\n📁 No movies found in your Jellyfin library.")
            return
        
        clear_screen()
        print(f"\n📚 Your Jellyfin Library ({len(movies)} movies):")
        print("=" * 60)
        
        for i, (name, symlink_path, target_path) in enumerate(movies, 1):
            status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
            # Use cyan color for movie title
            print(f"{i:3d}. {Colors.CYAN}{name}{Colors.RESET}")
            print(f"     📍 Symlink: {Colors.YELLOW}{symlink_path}{Colors.RESET}")
            if target_path != "BROKEN LINK":
                print(f"     🎬 Target:  {Colors.GREEN}{target_path}{Colors.RESET}")
            else:
                print(f"     🎬 Target:  {Colors.RED}BROKEN LINK{Colors.RESET}")
            print(f"     {status}")
            print()
        
        wait_for_enter()
    
    def add_movie(self) -> None:
        """Add a new movie to the library."""
        clear_screen()
        print("\n➕ Add New Movie")
        print("=" * 30)
        
        # Setup autocomplete
        autocomplete_enabled = self.menu_system.setup_autocomplete()
        
        if autocomplete_enabled:
            print("💡 Use Tab for autocomplete, arrow keys to navigate suggestions")
        print("💡 You can drag & drop a file or type the path manually")
        print()
        
        movie_path = self.menu_system.get_user_input("Enter the path to the movie file: ")
        if not movie_path:
            return
        
        if not validate_video_file(movie_path):
            wait_for_enter()
            return
        
        # Convert to absolute path for processing
        movie_path = os.path.abspath(movie_path)
        
        # Check if movie already exists
        from utils import get_all_media_folders
        media_folders = get_all_media_folders()
        existing_symlink, existing_subfolder = find_existing_symlink(movie_path, media_folders)
        
        if existing_symlink:
            movie_name = os.path.splitext(os.path.basename(movie_path))[0]
            print(f"⚠️  Movie '{movie_name}' already exists at '{existing_symlink}'.")
            
            action_options = ["⏭️  Skip", "🔄 Overwrite existing"]
            action_choice = self.menu_system.navigate_menu(action_options, f"Movie '{movie_name}' already exists")
            
            if action_choice == 0:  # Skip
                self.menu_system.show_message("⏭️  Skipping.")
                return
            elif action_choice == 1:  # Overwrite
                shutil.rmtree(existing_subfolder, ignore_errors=True)
                clear_screen()
                print(f"🗑️  Removed existing subfolder '{existing_subfolder}'.")
            else:
                self.menu_system.show_message("❌ Cancelled.")
                return
        
        # Create new symlink
        media_folder = get_media_folder(movie_path)
        success, result = create_movie_symlink(movie_path, media_folder)
        
        if success:
            clear_screen()
            print(f"✅ Success: Symlink created at '{result}'.")
            print(f"🔗 The symlink points to: {movie_path}")
            print("💡 The original file must remain in place for Jellyfin to access it.")
            wait_for_enter()
        else:
            clear_screen()
            print(f"❌ Error creating symlink: {result}")
            print("💡 Ensure script is run as administrator.")
            wait_for_enter()
    
    def remove_movie(self) -> None:
        """Remove a movie from the library."""
        movies = list_movies()
        
        if not movies:
            self.menu_system.show_message("\n📁 No movies found in your Jellyfin library.")
            return
        
        # Create menu options
        movie_options = []
        for i, (name, symlink_path, target_path) in enumerate(movies, 1):
            status = "❌ BROKEN" if target_path == "BROKEN LINK" else "✅ OK"
            movie_options.append(f"{i:3d}. {name} {status}")
        
        movie_options.append("🔙 Back to main menu")
        
        # Navigate through movies
        choice = self.menu_system.navigate_menu(movie_options, "🗑️  REMOVE MOVIE")
        
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
            if not self.menu_system.confirm_action(f"❓ Remove '{movie_name}' from library?"):
                self.menu_system.show_message("⏭️  Cancelled.")
                return
            
            # Remove the subfolder (contains the symlink)
            subfolder = os.path.dirname(symlink_path)
            
            if remove_symlink_safely(subfolder):
                clear_screen()
                print(f"✅ Removed movie '{movie_name}' from library.")
                
                # Ask about original file
                if target_path != "BROKEN LINK" and os.path.exists(target_path):
                    delete_options = ["❌ No, keep original file", "🗑️  Yes, delete original file"]
                    delete_choice = self.menu_system.navigate_menu(delete_options, f"🗑️  Also delete '{target_path}'?")
                    
                    if delete_choice == 1:  # Yes, delete
                        try:
                            os.remove(target_path)
                            clear_screen()
                            print(f"🗑️  Deleted original file '{target_path}'.")
                        except Exception as e:
                            clear_screen()
                            print(f"❌ Error deleting original file: {e}")
                
                wait_for_enter()


# Global instance for backward compatibility
_movie_manager = MovieManager()


# Legacy functions for backward compatibility
def display_movies() -> None:
    """Display all movies in the library. (Legacy function)"""
    _movie_manager.display_movies()


def add_movie() -> None:
    """Add a new movie to the library. (Legacy function)"""
    _movie_manager.add_movie()


def remove_movie() -> None:
    """Remove a movie from the library. (Legacy function)"""
    _movie_manager.remove_movie()
