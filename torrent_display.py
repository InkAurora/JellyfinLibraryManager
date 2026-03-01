"""
Torrent display and monitoring module for the Jellyfin Library Manager.
"""

import time
import msvcrt
import threading
from typing import List, Dict, Any, Optional, Tuple
from config import Colors
from utils import clear_screen, wait_for_enter, format_bytes, format_speed, format_eta, get_current_timestamp
from ui import MenuSystem
from torrent_manager import sync_torrents_with_qbittorrent


class TorrentDisplay:
    """Class to handle torrent display and monitoring functionality."""
    
    def __init__(self):
        self.menu_system = MenuSystem()
        self._sync_result: Optional[Tuple] = None
        self._sync_in_progress = False
        self._sync_lock = threading.Lock()

    def _run_sync_in_background(self) -> None:
        """Run sync_torrents_with_qbittorrent in a background thread and cache the result."""
        try:
            result = sync_torrents_with_qbittorrent()
        except Exception as e:
            result = (None, str(e))
        with self._sync_lock:
            self._sync_result = result
            self._sync_in_progress = False

    def _show_loading_screen(self) -> None:
        """Show a loading screen while waiting for the first sync result."""
        clear_screen()
        print(f"🔄 Auto-refreshing every 5s | Connecting...")
        print("💡 Press 'R' to refresh now, 'Esc' to return to main menu")
        print("🤖 Background monitoring: Active - completed torrents auto-added to library")
        print()
        print("⏳ Fetching torrent status from qBittorrent...")

    def display_tracked_torrents_with_auto_refresh(self) -> None:
        """Display tracked torrents with auto-refresh every 5 seconds."""
        last_refresh = 0
        refresh_interval = 5  # seconds
        exit_requested = False

        # Show loading screen immediately so the terminal doesn't appear frozen
        self._show_loading_screen()

        while not exit_requested:
            current_time = time.time()

            # Check for user input (non-blocking) — always processed, even during sync
            while msvcrt.kbhit():
                key = msvcrt.getch()
                if key in (b'\x00', b'\xe0'):
                    # Consume the second byte of a multi-byte key sequence
                    if msvcrt.kbhit():
                        msvcrt.getch()
                elif key == b'\x1b':  # Esc key
                    exit_requested = True
                    break
                elif key in (b'r', b'R'):  # Manual refresh
                    last_refresh = 0  # Force refresh on next iteration

            if exit_requested:
                break

            # Kick off a background sync when the interval has elapsed and none is running
            with self._sync_lock:
                sync_pending = self._sync_in_progress

            should_refresh = (current_time - last_refresh) >= refresh_interval
            if should_refresh and not sync_pending:
                with self._sync_lock:
                    self._sync_in_progress = True
                    self._sync_result = None  # Clear stale result while fetching
                threading.Thread(target=self._run_sync_in_background, daemon=True).start()
                last_refresh = time.time()  # Reset timer using time AFTER starting sync

            # Render display whenever a fresh sync result is available
            with self._sync_lock:
                result_ready = self._sync_result is not None
                if result_ready:
                    cached_result = self._sync_result

            if result_ready:
                synced_torrents, error = cached_result
                try:
                    self._render_display(synced_torrents, error)
                except Exception as e:
                    clear_screen()
                    print(f"⚠️  Display render error: {e}")
                    print("💡 Press 'R' to refresh now, 'Esc' to return to main menu")
                with self._sync_lock:
                    self._sync_result = None  # Mark result as consumed

            # Small delay to prevent excessive CPU usage
            time.sleep(0.1)
    
    def _render_display(self, synced_torrents, error) -> None:
        """Render the torrent display with pre-fetched sync results."""
        clear_screen()

        # Get current time for display
        current_time = get_current_timestamp()
        print(f"🔄 Auto-refreshing every 5s | Last update: {current_time}")
        print("💡 Press 'R' to refresh now, 'Esc' to return to main menu")
        print("🤖 Background monitoring: Active - completed torrents auto-added to library")
        print()

        if error:
            print(f"❌ Error syncing with qBittorrent: {error}")
            print("💡 Make sure qBittorrent is running and Web UI is accessible.")
            return

        if not synced_torrents:
            print("📋 No torrents tracked yet.")
            print("💡 Torrents will appear here after downloading via the script.")
            return

        self._show_torrent_status_compact(synced_torrents)
    
    def _show_torrent_status_compact(self, synced_torrents: List[Dict[str, Any]]) -> None:
        """Show compact torrent status for auto-refresh view."""
        # Separate torrents by status
        downloading = [t for t in synced_torrents if t.get('found_in_qb') and t.get('qb_status') in ['downloading', 'stalledDL', 'queuedDL', 'allocating']]
        seeding = [t for t in synced_torrents if t.get('found_in_qb') and t.get('qb_status') in ['uploading', 'stalledUP', 'queuedUP']]
        completed = [t for t in synced_torrents if t.get('found_in_qb') and t.get('qb_status') in ['pausedUP']]
        paused = [t for t in synced_torrents if t.get('found_in_qb') and t.get('qb_status') in ['pausedDL']]
        error_torrents = [t for t in synced_torrents if t.get('found_in_qb') and t.get('qb_status') in ['error', 'missingFiles']]
        not_found = [t for t in synced_torrents if not t.get('found_in_qb')]
        library_added = [t for t in synced_torrents if t.get('status') == 'added_to_library']
        
        print(f"📋 Tracked Torrents Progress ({len(synced_torrents)} total)")
        print("=" * 80)
        
        # Show downloading torrents first (most important)
        if downloading:
            print(f"\n📥 DOWNLOADING ({len(downloading)}):")
            for torrent in downloading:
                progress = torrent.get('qb_progress', 0)
                speed_dl = torrent.get('qb_speed_dl', 0)
                eta = torrent.get('qb_eta', 0)
                
                print(f"  {Colors.GREEN}▶{Colors.RESET} {torrent['title'][:55]}")
                print(f"    Progress: {Colors.GREEN}{progress:.1f}%{Colors.RESET} | Speed: {format_speed(speed_dl)} | ETA: {format_eta(eta)}")
                print(f"    Size: {format_bytes(torrent.get('qb_size', 0))} | Downloaded: {format_bytes(torrent.get('qb_downloaded', 0))}")
                print(f"    🗃️  ID: #{torrent['id']} | Status: {torrent.get('qb_status', 'unknown')}")
                print()
        
        # # Show library-added torrents (most important for completed ones)
        # if library_added:
        #     print(f"\n🎬 ADDED TO LIBRARY ({len(library_added)}):")
        #     for torrent in library_added:
        #         anilist_info = torrent.get('anilist_info', {})
        #         anime_title = anilist_info.get('title', 'Unknown')
                
        #         print(f"  {Colors.MAGENTA}📚{Colors.RESET} {anime_title}")
        #         print(f"    Original: {torrent['title'][:45]}")
        #         print(f"    🗃️  ID: #{torrent['id']} | Status: Added to anime library")
        #         print()
        
        # # Show completed torrents
        # if completed:
        #     print(f"\n✅ COMPLETED ({len(completed)}):")
        #     for torrent in completed:
        #         ratio = torrent.get('qb_ratio', 0)
        #         speed_up = torrent.get('qb_speed_up', 0)
                
        #         print(f"  {Colors.GREEN}✓{Colors.RESET} {torrent['title'][:55]}")
        #         print(f"    Size: {format_bytes(torrent.get('qb_size', 0))} | Ratio: {ratio:.2f}")
        #         if speed_up > 0:
        #             print(f"    Upload Speed: {format_speed(speed_up)}")
        #         print(f"    🗃️  ID: #{torrent['id']} | Path: {torrent.get('qb_save_path', 'Unknown')}")
        #         print()
        
        # # Show seeding torrents
        # if seeding:
        #     print(f"\n🌱 SEEDING ({len(seeding)}):")
        #     for torrent in seeding:
        #         ratio = torrent.get('qb_ratio', 0)
        #         speed_up = torrent.get('qb_speed_up', 0)
                
        #         print(f"  {Colors.YELLOW}↗{Colors.RESET} {torrent['title'][:55]}")
        #         print(f"    Ratio: {ratio:.2f} | Upload Speed: {format_speed(speed_up)}")
        #         print(f"    🗃️  ID: #{torrent['id']}")
        #         print()
        
        # Show paused torrents (limited to save space)
        if paused:
            print(f"\n⏸️  PAUSED ({len(paused)}):")
            for torrent in paused[:3]:  # Limit to first 3 to save space
                progress = torrent.get('qb_progress', 0)
                print(f"  {Colors.YELLOW}⏸{Colors.RESET} {torrent['title'][:55]}")
                print(f"    Progress: {progress:.1f}% | Status: {torrent.get('qb_status', 'unknown')}")
                print(f"    🗃️  ID: #{torrent['id']}")
                print()
            if len(paused) > 3:
                print(f"  ... and {len(paused) - 3} more paused torrents")
                print()
        
        # Show error torrents (limited to save space)
        if error_torrents:
            print(f"\n❌ ERRORS ({len(error_torrents)}):")
            for torrent in error_torrents[:2]:  # Limit to first 2 to save space
                print(f"  {Colors.RED}✗{Colors.RESET} {torrent['title'][:55]}")
                print(f"    Status: {torrent.get('qb_status', 'unknown')}")
                print(f"    🗃️  ID: #{torrent['id']}")
                print()
            if len(error_torrents) > 2:
                print(f"  ... and {len(error_torrents) - 2} more error torrents")
                print()
        
        # Show not found torrents (collapsed)
        if not_found:
            print(f"\n🔍 NOT FOUND IN QBITTORRENT: {len(not_found)} torrents")
            print("    (May have been removed from qBittorrent)")
            print()
        
        # Summary
        total_downloading = len(downloading)
        total_completed = len(completed)
        total_seeding = len(seeding)
        total_library_added = len(library_added)
        
        print("=" * 80)
        print(f"📊 Summary: {total_downloading} downloading, {total_completed} completed, {total_seeding} seeding, {total_library_added} in library")
        print("💡 This view shows only torrents added via this script")


# Global instance for backward compatibility
_torrent_display = TorrentDisplay()


# Legacy functions for backward compatibility
def display_tracked_torrents_with_auto_refresh() -> None:
    """Display tracked torrents with auto-refresh. (Legacy function)"""
    _torrent_display.display_tracked_torrents_with_auto_refresh()
