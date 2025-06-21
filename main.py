"""
Main application entry point for the Jellyfin Library Manager.
"""

from utils import clear_screen, wait_for_enter
from ui import navigate_menu
from movie_manager import display_movies, add_movie, remove_movie
from anime_manager import display_anime, add_anime, remove_anime
from torrent_display import display_tracked_torrents_with_auto_refresh
from anilist_api import interactive_anilist_search
from background_monitor import background_monitor
from plugin_loader import load_plugins


class JellyfinLibraryManager:
    """Main application class for the Jellyfin Library Manager."""
    
    def __init__(self):
        self.running = True
        self.plugins = []
        self.main_options = [
            "1. 📚 List movies in library",
            "2. ➕ Add new movie to library", 
            "3. 🗑️  Remove movie from library",
            "4. 📺 List anime in library",
            "5. ➕ Add new anime to library",
            "6. 🗑️  Remove anime from library",
            "7. 📋 View tracked torrents",
            "8. 🚪 Exit"
        ]
    
    def start(self) -> None:
        """Start the application."""
        clear_screen()
        print("🎬 Welcome to Jellyfin Library Manager!")
        print("💡 Use arrow keys to navigate, Enter to select, Esc to exit")
        
        # Start background torrent monitoring
        background_monitor.start_monitoring()
        
        # Load plugins
        self.plugins = load_plugins(app_context=self)
        
        # Use wait_for_enter for initial prompt
        wait_for_enter()
        
        self.main_loop()
    
    def main_loop(self) -> None:
        """Main application loop."""
        while self.running:
            try:
                choice = navigate_menu(self.main_options)

                if choice == -1 or choice == 7:  # Exit
                    self.exit_application()
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
                elif choice == 6:  # View tracked torrents
                    display_tracked_torrents_with_auto_refresh()

            except KeyboardInterrupt:
                self.exit_application()
            except Exception as e:
                clear_screen()
                print(f"❌ An error occurred: {e}")
                wait_for_enter()
    
    def exit_application(self) -> None:
        """Clean exit of the application."""
        background_monitor.stop_monitoring()
        clear_screen()
        print("👋 Goodbye!")
        self.running = False


def main() -> None:
    """Main function to start the application."""
    app = JellyfinLibraryManager()
    app.start()


if __name__ == "__main__":
    main()
