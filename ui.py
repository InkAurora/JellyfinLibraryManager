"""
User interface and menu system for the Jellyfin Library Manager.
"""

import os
import msvcrt
from typing import List, Optional
from config import APP_TITLE
from utils import clear_screen, wait_for_enter
from file_utils import path_completer

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


class MenuSystem:
    """Class to handle menu navigation and user interface."""
    
    @staticmethod
    def display_menu_with_selection(options: List[str], selected_index: int, title: str = APP_TITLE) -> None:
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
    
    @staticmethod
    def navigate_menu(options: List[str], title: str = APP_TITLE) -> int:
        """Navigate menu with arrow keys. Returns selected index or -1 for exit."""
        selected_index = 0
        
        while True:
            MenuSystem.display_menu_with_selection(options, selected_index, title)
            
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
    
    @staticmethod
    def setup_autocomplete() -> bool:
        """Setup readline for path autocomplete."""
        if readline is None:
            return False
        
        try:
            readline.set_completer(path_completer)
            readline.parse_and_bind("tab: complete")
            # Set word delimiters (exclude spaces to handle paths with spaces)
            # Only use tab and newline as delimiters
            readline.set_completer_delims('\t\n')
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_user_input(prompt: str, strip_quotes: bool = True) -> Optional[str]:
        """Get user input with error handling."""
        try:
            user_input = input(prompt).strip()
            if strip_quotes:
                user_input = user_input.strip('"')
            return user_input
        except (EOFError, KeyboardInterrupt):
            from utils import handle_input_cancellation
            handle_input_cancellation()
            return None
    
    @staticmethod
    def confirm_action(message: str, options: List[str] = None) -> bool:
        """Show confirmation dialog and return True if confirmed."""
        if options is None:
            options = ["❌ No, cancel", "✅ Yes, confirm"]
        
        choice = MenuSystem.navigate_menu(options, message)
        return choice == 1  # True if "Yes" option is selected
    
    @staticmethod
    def show_message(message: str, wait: bool = True) -> None:
        """Show a message to the user."""
        clear_screen()
        print(message)
        if wait:
            wait_for_enter()
    
    @staticmethod
    def show_error(error_message: str, wait: bool = True) -> None:
        """Show an error message to the user."""
        clear_screen()
        print(f"❌ Error: {error_message}")
        if wait:
            wait_for_enter()
    
    @staticmethod
    def show_success(success_message: str, wait: bool = True) -> None:
        """Show a success message to the user."""
        clear_screen()
        print(f"✅ Success: {success_message}")
        if wait:
            wait_for_enter()
    
    @staticmethod
    def show_warning(warning_message: str, wait: bool = True) -> None:
        """Show a warning message to the user."""
        clear_screen()
        print(f"⚠️  Warning: {warning_message}")
        if wait:
            wait_for_enter()


# Global menu system instance
menu_system = MenuSystem()


# Legacy functions for backward compatibility
def display_menu_with_selection(options: List[str], selected_index: int, title: str = APP_TITLE) -> None:
    """Display menu with highlighted selection. (Legacy function)"""
    menu_system.display_menu_with_selection(options, selected_index, title)


def navigate_menu(options: List[str], title: str = APP_TITLE) -> int:
    """Navigate menu with arrow keys. (Legacy function)"""
    return menu_system.navigate_menu(options, title)


def setup_autocomplete() -> bool:
    """Setup readline for path autocomplete. (Legacy function)"""
    return menu_system.setup_autocomplete()
