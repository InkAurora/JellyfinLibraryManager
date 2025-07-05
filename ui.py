"""
User interface and menu system for the Jellyfin Library Manager.
"""

import os
import msvcrt
import sys
from typing import List, Optional
from config import APP_TITLE
from utils import clear_screen, wait_for_enter, is_video_file
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


def show_directory_hint(current_path: str) -> None:
    """Show a helpful directory listing hint for the current path."""
    try:
        if not current_path:
            base_path = os.getcwd()
        elif current_path.endswith(os.sep):
            base_path = current_path
        else:
            base_path = os.path.dirname(current_path) if os.sep in current_path else os.getcwd()
        
        if os.path.isdir(base_path):
            items = []
            try:
                for item in os.listdir(base_path):
                    item_path = os.path.join(base_path, item)
                    if os.path.isdir(item_path):
                        items.append(f"📁 {item}/")
                    elif is_video_file(item):
                        items.append(f"🎬 {item}")
                
                if items:
                    print(f"\n💡 Available in '{base_path}':")
                    for item in items[:10]:  # Show first 10 items
                        print(f"   {item}")
                    if len(items) > 10:
                        print(f"   ... and {len(items) - 10} more items")
                    print()
            except (OSError, PermissionError):
                pass
    except Exception:
        pass


def windows_autocomplete_input(prompt: str) -> Optional[str]:
    """Custom input function with better Windows autocomplete support."""
    print(prompt, end='', flush=True)
    
    current_input = ""
    cursor_pos = 0
    
    def redraw_line():
        """Redraw the entire screen with header and input line at correct cursor position."""
        from utils import clear_screen
        
        # Clear the entire screen
        clear_screen()
        
        # Redraw the movie addition header
        print("➕ Add New Movie")
        print("=" * 30)
        print("💡 Use Tab for autocomplete, arrow keys to navigate suggestions")
        print("💡 You can drag & drop a file or type the path manually")
        print()
        
        # Print prompt and input
        print(prompt + current_input, end='')
        # Move cursor to correct position
        if cursor_pos < len(current_input):
            # Move cursor back to the correct position
            chars_to_move_back = len(current_input) - cursor_pos
            print('\b' * chars_to_move_back, end='')
        print('', end='', flush=True)
    
    def clear_suggestions():
        """Clear suggestions by redrawing the screen with just the header and input."""
        from utils import clear_screen
        
        # Clear the entire screen
        clear_screen()
        
        # Redraw the movie addition header
        print("➕ Add New Movie")
        print("=" * 30)
        print("💡 Use Tab for autocomplete, arrow keys to navigate suggestions")
        print("💡 You can drag & drop a file or type the path manually")
        print()
        
        # Redraw the input line
        print(prompt + current_input, end='')
        # Position cursor correctly
        if cursor_pos < len(current_input):
            chars_to_move_back = len(current_input) - cursor_pos
            print('\b' * chars_to_move_back, end='')
        print('', end='', flush=True)
    
    def show_suggestions(candidates):
        """Show suggestions by redrawing the entire screen with header."""
        from utils import clear_screen
        
        # Clear the entire screen
        clear_screen()
        
        # Redraw the movie addition header
        print("➕ Add New Movie")
        print("=" * 30)
        print("💡 Use Tab for autocomplete, arrow keys to navigate suggestions")
        print("💡 You can drag & drop a file or type the path manually")
        print()
        
        # Show the input line with cursor positioned correctly
        print(prompt + current_input, end='')
        
        # Show suggestions below
        print()  # Move to next line for suggestions
        print(f"📁 Found {len(candidates)} matches:")
        for i, candidate in enumerate(candidates[:8]):  # Show first 8
            # Clean up display - remove quotes and show just the filename
            display_path = candidate
            if display_path.startswith('"') and display_path.endswith('"'):
                display_path = display_path[1:-1]
            elif display_path.startswith('"'):
                display_path = display_path[1:]
            
            display_name = os.path.basename(display_path)
            if os.path.isdir(display_path):
                print(f"  📁 {display_name}/")
            else:
                print(f"  📄 {display_name}")
        
        if len(candidates) > 8:
            print(f"  ... and {len(candidates) - 8} more")
        
        # Move cursor back to the input line where it should be
        # Calculate lines: suggestions + "Found X matches" line + blank line
        lines_to_go_up = len(candidates[:8]) + 2  # +2 for "Found X matches" and blank line  
        if len(candidates) > 8:
            lines_to_go_up += 1  # +1 for "... and X more" line
        
        # Move cursor up to the input line
        print(f'\033[{lines_to_go_up}A', end='')
        # Move cursor to the correct position within the input
        print(f'\033[{len(prompt) + cursor_pos}C', end='')
        print('', end='', flush=True)
    
    while True:
        try:
            # Get a single character
            char = msvcrt.getch()
            
            if char == b'\r':  # Enter
                clear_suggestions()  # Clean up before returning
                print()  # New line
                result = current_input.strip()
                if result.startswith('"') and result.endswith('"'):
                    result = result[1:-1]
                return result if result else ""
            elif char == b'\x08':  # Backspace
                if cursor_pos > 0:
                    current_input = current_input[:cursor_pos-1] + current_input[cursor_pos:]
                    cursor_pos -= 1
                    clear_suggestions()  # Clear suggestions when input changes
                    redraw_line()
            elif char == b'\t':  # Tab - autocomplete
                # Get completion candidates
                candidates = []
                state = 0
                while True:
                    candidate = path_completer(current_input, state)
                    if candidate is None:
                        break
                    candidates.append(candidate)
                    state += 1
                
                if candidates:
                    if len(candidates) == 1:
                        # Single match - complete it
                        completion = candidates[0]
                        
                        # Smart quoting: only quote if needed and not already quoted properly
                        if ' ' in completion:
                            # If it has spaces but isn't quoted, quote it
                            if not (completion.startswith('"') and completion.endswith('"')):
                                # If it's a directory (ends with \), don't close the quote yet
                                if completion.endswith(os.sep) and not completion.startswith('"'):
                                    completion = '"' + completion
                                elif not completion.endswith(os.sep) and not completion.startswith('"'):
                                    completion = '"' + completion + '"'
                        
                        current_input = completion
                        cursor_pos = len(current_input)
                        clear_suggestions()  # Clear any existing suggestions
                        redraw_line()
                    else:
                        # Multiple matches - find common prefix
                        # Remove quotes from candidates for prefix calculation
                        unquoted_candidates = []
                        for cand in candidates:
                            if cand.startswith('"') and cand.endswith('"'):
                                unquoted_candidates.append(cand[1:-1])
                            elif cand.startswith('"'):
                                unquoted_candidates.append(cand[1:])
                            else:
                                unquoted_candidates.append(cand)
                        
                        common = os.path.commonprefix(unquoted_candidates)
                        
                        # Remove quotes from current input for comparison
                        current_unquoted = current_input
                        if current_unquoted.startswith('"'):
                            if current_unquoted.endswith('"') and len(current_unquoted) > 1:
                                current_unquoted = current_unquoted[1:-1]
                            else:
                                current_unquoted = current_unquoted[1:]
                        
                        if len(common) > len(current_unquoted):
                            # We can complete to a common prefix
                            if ' ' in common:
                                # Add quote at start if needed
                                if common.endswith(os.sep):
                                    current_input = '"' + common  # Leave open for further completion
                                else:
                                    current_input = '"' + common + '"'  # Close quote for files
                            else:
                                current_input = common
                            cursor_pos = len(current_input)
                            clear_suggestions()  # Clear any existing suggestions
                            redraw_line()
                        else:
                            # Show matches using the new suggestion system
                            show_suggestions(candidates)
                else:
                    # No matches - try to show directory contents
                    if current_input:
                        base_path = os.path.dirname(current_input) if os.path.dirname(current_input) else "."
                        if os.path.exists(base_path):
                            try:
                                items = []
                                for item in os.listdir(base_path):
                                    if item.lower().startswith(os.path.basename(current_input).lower()):
                                        full_path = os.path.join(base_path, item)
                                        if os.path.isdir(full_path):
                                            items.append(f"📁 {item}/")
                                        else:
                                            items.append(f"📄 {item}")
                                
                                if items:
                                    # Clear previous suggestions
                                    clear_suggestions()
                                    
                                    print()
                                    print(f"💡 Matches in '{base_path}':")
                                    lines_printed = 1
                                    for item in items[:6]:
                                        print(f"  {item}")
                                        lines_printed += 1
                                    if len(items) > 6:
                                        print(f"  ... and {len(items) - 6} more")
                                        lines_printed += 1
                                    
                                    last_suggestions_lines = lines_printed
                                    
                                    # Move cursor back to input line
                                    print('\033[{}A'.format(lines_printed), end='')
                                    print('\r' + prompt + current_input, end='')
                                    if cursor_pos < len(current_input):
                                        chars_to_move_back = len(current_input) - cursor_pos
                                        print('\b' * chars_to_move_back, end='')
                                    print('', end='', flush=True)
                            except (OSError, PermissionError):
                                pass
            elif char == b'\x1b':  # Escape
                clear_suggestions()  # Clean up before returning
                print()
                return None
            elif char == b'\xe0':  # Extended key prefix (arrow keys, function keys, etc.)
                extended = msvcrt.getch()  # Get the actual key code
                if extended == b'K':  # Left arrow
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        print('\b', end='', flush=True)
                elif extended == b'M':  # Right arrow
                    if cursor_pos < len(current_input):
                        cursor_pos += 1
                        print(current_input[cursor_pos-1], end='', flush=True)
                elif extended == b'H':  # Up arrow - move to beginning
                    while cursor_pos > 0:
                        cursor_pos -= 1
                        print('\b', end='', flush=True)
                elif extended == b'P':  # Down arrow - move to end
                    while cursor_pos < len(current_input):
                        print(current_input[cursor_pos], end='', flush=True)
                        cursor_pos += 1
                # Ignore other extended keys
            else:
                # Regular character
                try:
                    char_str = char.decode('utf-8')
                    if ord(char_str) >= 32:  # Printable character
                        # Insert character at cursor position
                        current_input = current_input[:cursor_pos] + char_str + current_input[cursor_pos:]
                        cursor_pos += 1
                        clear_suggestions()  # Clear suggestions when input changes
                        redraw_line()
                except UnicodeDecodeError:
                    continue
                    
        except (EOFError, KeyboardInterrupt):
            clear_suggestions()  # Clean up before returning
            print()
            return None


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
            # Configure tab completion
            readline.parse_and_bind("tab: complete")
            # Set completion display matches hook to show partial completions
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-ignore-case on")
            # Set word delimiters (exclude spaces to handle paths with spaces)
            readline.set_completer_delims('\t\n')
            # Enable automatic quote insertion for paths with spaces
            readline.parse_and_bind("set completion-query-items 50")
            # Configure the completion behavior
            if hasattr(readline, 'set_completion_display_matches_hook'):
                readline.set_completion_display_matches_hook(None)
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_user_input(prompt: str, strip_quotes: bool = True, use_autocomplete: bool = False) -> Optional[str]:
        """Get user input with error handling and optional autocomplete."""
        try:
            if use_autocomplete and os.name == 'nt':
                # Use custom Windows autocomplete
                user_input = windows_autocomplete_input(prompt)
                if user_input is None:
                    return None
            else:
                # Standard input
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
