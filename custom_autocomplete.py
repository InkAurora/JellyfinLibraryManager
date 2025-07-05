"""
Custom autocomplete system for file paths without readline dependency.
Handles spaces, square brackets, and other special characters seamlessly.
"""

import os
import msvcrt
import sys
from typing import List, Optional
from utils import is_video_file, clear_screen


class CustomAutocomplete:
    """Custom autocomplete system for file paths."""
    
    def __init__(self):
        self.suggestions = []
        self.current_suggestion_index = -1
        self.input_buffer = ""
        self.cursor_position = 0
        
    def get_real_time_suggestions(self, partial_path: str) -> List[str]:
        """Get file/directory suggestions in real-time using os.listdir"""
        if not partial_path:
            return []
            
        try:
            # Handle both absolute and relative paths
            if os.path.isabs(partial_path):
                if os.path.isdir(partial_path):
                    # If it's a complete directory, list its contents
                    base_dir = partial_path
                    search_pattern = ""
                else:
                    # Split into directory and partial filename
                    base_dir = os.path.dirname(partial_path)
                    search_pattern = os.path.basename(partial_path).lower()
            else:
                # Relative path from current directory
                if os.path.sep in partial_path:
                    base_dir = os.path.dirname(partial_path)
                    search_pattern = os.path.basename(partial_path).lower()
                else:
                    base_dir = os.getcwd()
                    search_pattern = partial_path.lower()
            
            # Ensure base directory exists
            if not base_dir:
                base_dir = os.getcwd()
            if not os.path.exists(base_dir):
                return []
            
            # Get all items in the directory
            all_items = []
            try:
                for item in os.listdir(base_dir):
                    item_path = os.path.join(base_dir, item)
                    if os.path.isdir(item_path):
                        all_items.append(item)  # Don't add separator here, we'll add it in the full path
                    elif is_video_file(item):
                        all_items.append(item)
            except PermissionError:
                return []
            
            # Filter based on search pattern
            if search_pattern:
                matches = [item for item in all_items 
                          if item.lower().startswith(search_pattern)]
            else:
                matches = all_items
            
            # Return full paths
            full_matches = []
            for match in matches:
                full_path = os.path.join(base_dir, match)
                # Normalize path separators
                full_path = os.path.normpath(full_path)
                # Add separator for directories
                if os.path.isdir(full_path):
                    full_path += os.sep
                full_matches.append(full_path)
            
            return sorted(full_matches)  # Sort for consistent ordering
                
        except Exception:
            return []
    
    def display_suggestions(self, suggestions: List[str], title: str = "➕ Add New Movie", prompt: str = "Enter the path to the movie file: ", max_display: int = 8):
        """Display suggestions with full screen redraw"""
        from utils import clear_screen
        
        # Clear entire screen and redraw everything
        clear_screen()
        
        # Redraw the header
        print(title)
        print("=" * 30)
        print("💡 Use Tab for autocomplete, arrow keys to navigate")
        print("💡 Type file path - supports spaces and special characters!")
        print("💡 Real-time suggestions appear as you type")
        print()
        
        # Show the input line first
        print(f"{prompt}{self.input_buffer}")
        print()
        
        # Then show suggestions below
        if suggestions:
            print(f"💡 Found {len(suggestions)} matches:")
            
            for i, suggestion in enumerate(suggestions[:max_display]):
                # Determine if it's a directory or file
                is_directory = suggestion.endswith(os.sep) or os.path.isdir(suggestion)
                icon = "📁" if is_directory else "📄"
                filename = os.path.basename(suggestion.rstrip(os.sep))
                if is_directory:
                    filename += os.sep
                print(f"  {icon} {filename}")
            
            if len(suggestions) > max_display:
                print(f"  ... and {len(suggestions) - max_display} more")
        
        # Position cursor back at the end of input line
        # Calculate lines to go back up
        lines_to_go_up = 2  # Start with blank line after input + suggestions header
        if suggestions:
            lines_to_go_up += len(suggestions[:max_display]) + 1  # suggestions + "Found X matches" line
            if len(suggestions) > max_display:
                lines_to_go_up += 1  # "... and X more" line
        
        # Move cursor back to input line
        print(f'\033[{lines_to_go_up}A', end='')
        # Move to end of the input text
        print(f'\033[{len(prompt + self.input_buffer)}C', end='')
        
        # Adjust cursor position if needed
        if self.cursor_position < len(self.input_buffer):
            chars_to_move_back = len(self.input_buffer) - self.cursor_position
            print(f'\033[{chars_to_move_back}D', end='')
        
        sys.stdout.flush()
    
    def clear_screen_from_cursor(self):
        """Clear screen from current cursor position downward"""
        # Move cursor to beginning of line
        print('\r', end='')
        # Clear from cursor to end of screen
        print('\033[J', end='')
        sys.stdout.flush()
    
    def redraw_input_line(self, prompt: str, input_text: str, cursor_pos: int):
        """Redraw the input line with cursor at correct position"""
        # Clear the entire line first
        print('\r' + ' ' * 120, end='')  # Clear line with spaces
        # Redraw the line
        print(f'\r{prompt}{input_text}', end='')
        
        # Move cursor to correct position
        if cursor_pos < len(input_text):
            move_back = len(input_text) - cursor_pos
            print(f'\033[{move_back}D', end='')
        
        sys.stdout.flush()
    
    def find_common_prefix(self, paths: List[str]) -> str:
        """Find the longest common prefix among a list of paths"""
        if not paths:
            return ""
        if len(paths) == 1:
            return paths[0]
        
        # Normalize all paths first (handle different path separators, case sensitivity)
        normalized_paths = []
        for path in paths:
            # Normalize path separators and case for Windows
            normalized = os.path.normpath(path).lower()
            normalized_paths.append((normalized, path))
        
        # Start with the first path
        common_normalized = normalized_paths[0][0]
        common_original = normalized_paths[0][1]
        
        # Compare with each subsequent path
        for normalized, original in normalized_paths[1:]:
            # Find common characters from the beginning
            new_common_normalized = ""
            new_common_original = ""
            min_length = min(len(common_normalized), len(normalized))
            
            for i in range(min_length):
                if common_normalized[i] == normalized[i]:
                    new_common_normalized += common_normalized[i]
                    new_common_original += common_original[i]
                else:
                    break
            
            common_normalized = new_common_normalized
            common_original = new_common_original
            
            # If we have no common prefix, stop
            if not common_normalized:
                break
        
        # Ensure we don't cut off in the middle of a filename/directory name
        # Find the last path separator to avoid partial names
        if common_original and not common_original.endswith(os.sep):
            last_sep = common_original.rfind(os.sep)
            if last_sep > 0:  # Don't cut off drive letters on Windows (C:\)
                # Check if there are characters after the last separator
                partial_name = common_original[last_sep + 1:]
                if partial_name:
                    # Only keep the partial name if all paths start with it
                    all_match_partial = True
                    for path in paths:
                        path_after_sep = path[last_sep + 1:] if len(path) > last_sep else ""
                        if not path_after_sep.lower().startswith(partial_name.lower()):
                            all_match_partial = False
                            break
                    
                    if not all_match_partial:
                        # Cut off the partial name, keep up to the separator
                        common_original = common_original[:last_sep + 1]
        
        return common_original

    def handle_tab_completion(self, current_input: str) -> str:
        """Handle tab completion and return completed text"""
        suggestions = self.get_real_time_suggestions(current_input)
        
        if not suggestions:
            return current_input
        
        if len(suggestions) == 1:
            # Single match - complete it
            completed_path = suggestions[0]
            # If it's a directory and doesn't end with separator, add one
            if os.path.isdir(completed_path) and not completed_path.endswith(os.sep):
                completed_path += os.sep
            return completed_path
        else:
            # Multiple matches - find common prefix
            common_prefix = self.find_common_prefix(suggestions)
            
            # Only use the common prefix if it's longer than what the user has typed
            if len(common_prefix) > len(current_input):
                # If the common prefix represents a directory, add separator
                if os.path.isdir(common_prefix) and not common_prefix.endswith(os.sep):
                    common_prefix += os.sep
                return common_prefix
            
            # If no useful common prefix, show suggestions
            self.display_suggestions(suggestions)
            return current_input
    
    def get_input_with_autocomplete(self, prompt: str, title: str = "➕ Add New Movie", subtitle: str = "💡 Esc to exit if empty, or clear input if not empty") -> Optional[str]:
        """Main input function with real-time autocomplete"""
        from utils import clear_screen
        
        # Initialize state
        self.input_buffer = ""
        self.cursor_position = 0
        
        # Show initial screen
        clear_screen()
        print(title)
        print("=" * 30)
        print("💡 Use Tab for autocomplete, arrow keys to navigate")
        print("💡 Type file path - supports spaces and special characters!")
        print(subtitle)
        print()
        
        print(f"{prompt}", end='')
        sys.stdout.flush()
        
        last_suggestions_shown = False
        
        while True:
            try:
                char = msvcrt.getch()
                
                # Handle special keys
                if char == b'\x08':  # Backspace
                    if self.cursor_position > 0:
                        # Remove character before cursor
                        self.input_buffer = self.input_buffer[:self.cursor_position-1] + self.input_buffer[self.cursor_position:]
                        self.cursor_position -= 1
                        
                        # Clear suggestions area if shown
                        if last_suggestions_shown:
                            self.clear_screen_from_cursor()
                            last_suggestions_shown = False
                        
                        self.redraw_input_line(prompt, self.input_buffer, self.cursor_position)
                
                elif char == b'\r':  # Enter
                    print()  # New line after input
                    return self.input_buffer if self.input_buffer.strip() else None
                
                elif char == b'\t':  # Tab - autocomplete
                    # Get completion
                    suggestions = self.get_real_time_suggestions(self.input_buffer)
                    if suggestions:
                        if len(suggestions) == 1:
                            # Single match - complete it
                            completed_path = suggestions[0]
                            
                            # If it's a directory and doesn't end with separator, add one
                            if os.path.isdir(completed_path) and not completed_path.endswith(os.sep):
                                completed_path += os.sep
                            
                            self.input_buffer = completed_path
                            self.cursor_position = len(self.input_buffer)
                            
                            # Redraw with full screen to clear suggestions
                            clear_screen()
                            print(title)
                            print("=" * 30)
                            print("💡 Use Tab for autocomplete, arrow keys to navigate")
                            print("💡 Type file path - supports spaces and special characters!")
                            print(subtitle)
                            print()
                            print(f"{prompt}{self.input_buffer}", end='')
                            sys.stdout.flush()
                            last_suggestions_shown = False
                        else:
                            # Multiple matches - find common prefix
                            common_prefix = self.find_common_prefix(suggestions)
                            
                            # Only use the common prefix if it's longer than what the user has typed
                            if len(common_prefix) > len(self.input_buffer):
                                # If the common prefix represents a directory, add separator
                                if os.path.isdir(common_prefix) and not common_prefix.endswith(os.sep):
                                    common_prefix += os.sep
                                
                                self.input_buffer = common_prefix
                                self.cursor_position = len(self.input_buffer)
                                
                                # Redraw with full screen to clear suggestions
                                clear_screen()
                                print(title)
                                print("=" * 30)
                                print("💡 Use Tab for autocomplete, arrow keys to navigate")
                                print("💡 Type file path - supports spaces and special characters!")
                                print(subtitle)
                                print()
                                print(f"{prompt}{self.input_buffer}", end='')
                                sys.stdout.flush()
                                last_suggestions_shown = False
                            else:
                                # No useful common prefix - show suggestions
                                self.display_suggestions(suggestions, title, prompt)
                                last_suggestions_shown = True
                
                elif char == b'\xe0':  # Extended key (arrows, etc.)
                    extended_char = msvcrt.getch()
                    
                    if extended_char == b'K':  # Left arrow
                        if self.cursor_position > 0:
                            self.cursor_position -= 1
                            print('\033[D', end='')  # Move cursor left
                            sys.stdout.flush()
                    
                    elif extended_char == b'M':  # Right arrow
                        if self.cursor_position < len(self.input_buffer):
                            self.cursor_position += 1
                            print('\033[C', end='')  # Move cursor right
                            sys.stdout.flush()
                    
                    elif extended_char == b'H':  # Up arrow - move to beginning
                        move_left = self.cursor_position
                        self.cursor_position = 0
                        if move_left > 0:
                            print(f'\033[{move_left}D', end='')
                            sys.stdout.flush()
                    
                    elif extended_char == b'P':  # Down arrow - move to end
                        move_right = len(self.input_buffer) - self.cursor_position
                        self.cursor_position = len(self.input_buffer)
                        if move_right > 0:
                            print(f'\033[{move_right}C', end='')
                            sys.stdout.flush()
                
                elif char == b'\x1b':  # Escape
                    if not self.input_buffer:
                        # If input is empty, exit to menu
                        print("\n")  # New line
                        return None
                    else:
                        # If input has content, clear it
                        self.input_buffer = ""
                        self.cursor_position = 0
                        if last_suggestions_shown:
                            self.clear_screen_from_cursor()
                            last_suggestions_shown = False
                        self.redraw_input_line(prompt, self.input_buffer, self.cursor_position)
                
                elif char >= b' ' and char <= b'~':  # Printable ASCII
                    # Insert character at cursor position
                    char_str = char.decode('utf-8', errors='ignore')
                    self.input_buffer = self.input_buffer[:self.cursor_position] + char_str + self.input_buffer[self.cursor_position:]
                    self.cursor_position += 1
                    
                    # Clear suggestions if shown
                    if last_suggestions_shown:
                        self.clear_screen_from_cursor()
                        last_suggestions_shown = False
                    
                    self.redraw_input_line(prompt, self.input_buffer, self.cursor_position)
                    
                    # Show real-time suggestions as user types (but not too aggressively)
                    if len(self.input_buffer) >= 3 and self.input_buffer.count(os.sep) > 0:  # Start suggesting after we have a path
                        suggestions = self.get_real_time_suggestions(self.input_buffer)
                        if suggestions and len(suggestions) <= 10:  # Only show if manageable number
                            self.display_suggestions(suggestions, title, prompt, max_display=6)
                            last_suggestions_shown = True
                            
            except (EOFError, KeyboardInterrupt):
                if last_suggestions_shown:
                    self.clear_screen_from_cursor()
                print()
                return None


def get_movie_file_with_custom_autocomplete() -> str:
    """Get movie file path using custom autocomplete system"""
    autocomplete = CustomAutocomplete()
    
    return autocomplete.get_input_with_autocomplete(
        "Enter the path to the movie file: ",
        "➕ Add New Movie",
        "💡 Real-time suggestions appear as you type"
    )


def get_anime_folder_with_custom_autocomplete() -> str:
    """Get anime folder path using custom autocomplete system"""
    autocomplete = CustomAutocomplete()
    
    return autocomplete.get_input_with_autocomplete(
        "Enter the path to the anime episodes folder: ",
        "➕ Add New Anime",
        "💡 Real-time suggestions appear as you type"
    )


def get_download_path_with_custom_autocomplete() -> str:
    """Get download path using custom autocomplete system"""
    autocomplete = CustomAutocomplete()
    
    return autocomplete.get_input_with_autocomplete(
        "Enter download path (or leave empty for default): ",
        "📁 Download Location",
        "💡 Leave empty for default download location"
    )
