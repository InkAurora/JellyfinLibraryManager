"""
User interface and menu system for the Jellyfin Library Manager.
"""

import os
import msvcrt
import sys
from typing import List, Optional, Callable, Any, Dict, Union
from config import APP_TITLE
from utils import clear_screen, wait_for_enter, is_video_file

# [REMOVED] Old readline imports - replaced with custom_autocomplete.py for better compatibility


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
    def navigate_paginated_menu(options: List[str], title: str = APP_TITLE, page_size: int = 12) -> int:
        """Navigate a long menu with paging keys. Returns selected index or -1 for exit."""
        if not options:
            return -1

        selected_index = 0
        top_index = 0
        total = len(options)

        def _adjust_window() -> None:
            nonlocal top_index
            if selected_index < top_index:
                top_index = selected_index
            elif selected_index >= top_index + page_size:
                top_index = selected_index - page_size + 1

            max_top = max(0, total - page_size)
            top_index = max(0, min(top_index, max_top))

        while True:
            _adjust_window()
            clear_screen()
            print("=" * 70)
            print(title)
            print("=" * 70)

            start = top_index
            end = min(top_index + page_size, total)
            print(f"Showing {start + 1}-{end} of {total}")
            print("-" * 70)

            for i in range(start, end):
                marker = "➤" if i == selected_index else " "
                print(f"{marker} {i + 1:>3}. {options[i]}")

            print("-" * 70)
            print("💡 ↑↓ move | PgUp/PgDn page | Home/End jump | Enter select | Esc back")

            key = msvcrt.getch()
            if key in (b'\x00', b'\xe0'):
                key = msvcrt.getch()
                if key == b'H':  # Up
                    selected_index = max(0, selected_index - 1)
                elif key == b'P':  # Down
                    selected_index = min(total - 1, selected_index + 1)
                elif key == b'I':  # Page Up
                    selected_index = max(0, selected_index - page_size)
                elif key == b'Q':  # Page Down
                    selected_index = min(total - 1, selected_index + page_size)
                elif key == b'G':  # Home
                    selected_index = 0
                elif key == b'O':  # End
                    selected_index = total - 1
            elif key == b'\r':  # Enter
                return selected_index
            elif key == b'\x1b':  # Escape
                return -1

    @staticmethod
    def navigate_search_results(
        items: List[Any],
        title: str,
        row_formatter: Callable[[Any], str],
        seeds_extractor: Callable[[Any], int],
        size_extractor: Callable[[Any], int],
        page_size: int = 12,
        extra_hotkeys: Optional[Dict[bytes, str]] = None,
        extra_hint: str = ""
    ) -> Union[int, str]:
        """
        Navigate search results with sorting/filter shortcuts.
        Returns original item index, -1 for cancel, or an extra hotkey token.
        """
        if not items:
            return -1

        sort_mode = "seeds_desc"
        hide_zero_seed = False
        selected_original_index = 0
        top_index = 0
        extra_hotkeys = extra_hotkeys or {}

        def _safe_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        def _build_visible() -> List[int]:
            visible_indices = []
            for idx, item in enumerate(items):
                if hide_zero_seed and _safe_int(seeds_extractor(item)) == 0:
                    continue
                visible_indices.append(idx)

            if sort_mode == "size_desc":
                visible_indices.sort(
                    key=lambda i: _safe_int(size_extractor(items[i])),
                    reverse=True
                )
            else:
                visible_indices.sort(
                    key=lambda i: _safe_int(seeds_extractor(items[i])),
                    reverse=True
                )
            return visible_indices

        while True:
            visible_indices = _build_visible()
            visible_count = len(visible_indices)

            if visible_count == 0:
                clear_screen()
                print("=" * 90)
                print(title)
                print("=" * 90)
                print("No results match the current filter.")
                print("💡 Press D to show zero-seed results again, S to change sort mode, Esc to cancel.")
                if extra_hint:
                    print(extra_hint)

                key = msvcrt.getch()
                lowered = key.lower() if isinstance(key, bytes) else key
                if lowered == b'd':
                    hide_zero_seed = not hide_zero_seed
                elif lowered == b's':
                    sort_mode = "size_desc" if sort_mode == "seeds_desc" else "seeds_desc"
                elif key == b'\x1b':
                    return -1
                elif key in extra_hotkeys:
                    return extra_hotkeys[key]
                continue

            if selected_original_index not in visible_indices:
                selected_original_index = visible_indices[0]

            selected_visible_index = visible_indices.index(selected_original_index)
            if selected_visible_index < top_index:
                top_index = selected_visible_index
            elif selected_visible_index >= top_index + page_size:
                top_index = selected_visible_index - page_size + 1
            top_index = max(0, min(top_index, max(0, visible_count - page_size)))

            clear_screen()
            print("=" * 90)
            print(title)
            print("=" * 90)
            sort_label = "Seeds DESC" if sort_mode == "seeds_desc" else "Size DESC"
            zero_seed_label = "Hidden" if hide_zero_seed else "Shown"
            start = top_index
            end = min(top_index + page_size, visible_count)
            print(f"Showing {start + 1}-{end} of {visible_count} (Total: {len(items)}) | Sort: {sort_label} | Zero-seed: {zero_seed_label}")
            print("-" * 90)

            for visible_i in range(start, end):
                original_i = visible_indices[visible_i]
                marker = "➤" if original_i == selected_original_index else " "
                print(f"{marker} {visible_i + 1:>3}. {row_formatter(items[original_i])}")

            print("-" * 90)
            print("💡 ↑↓ move | PgUp/PgDn page | Home/End jump | S sort | D hide/show 0 seeds | Enter select | Esc back")
            if extra_hint:
                print(extra_hint)

            key = msvcrt.getch()
            lowered = key.lower() if isinstance(key, bytes) else key

            if key in (b'\x00', b'\xe0'):
                key = msvcrt.getch()
                current_pos = visible_indices.index(selected_original_index)
                if key == b'H':  # Up
                    current_pos = max(0, current_pos - 1)
                elif key == b'P':  # Down
                    current_pos = min(visible_count - 1, current_pos + 1)
                elif key == b'I':  # Page Up
                    current_pos = max(0, current_pos - page_size)
                elif key == b'Q':  # Page Down
                    current_pos = min(visible_count - 1, current_pos + page_size)
                elif key == b'G':  # Home
                    current_pos = 0
                elif key == b'O':  # End
                    current_pos = visible_count - 1
                selected_original_index = visible_indices[current_pos]
            elif lowered == b's':
                sort_mode = "size_desc" if sort_mode == "seeds_desc" else "seeds_desc"
            elif lowered == b'd':
                hide_zero_seed = not hide_zero_seed
            elif key == b'\r':
                return selected_original_index
            elif key == b'\x1b':
                return -1
            elif key in extra_hotkeys:
                return extra_hotkeys[key]
    
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


def navigate_paginated_menu(options: List[str], title: str = APP_TITLE, page_size: int = 12) -> int:
    """Navigate long menu with paging keys. (Legacy function)"""
    return menu_system.navigate_paginated_menu(options, title, page_size)

# Note: Old readline-based autocomplete has been replaced with custom_autocomplete.py
# for better Windows compatibility and special character support.
