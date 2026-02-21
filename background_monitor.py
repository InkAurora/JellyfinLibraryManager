"""
Background monitoring for torrent completion and automatic library management.
"""

import time
import threading
from typing import List, Dict, Any
from config import TORRENT_CHECK_INTERVAL
from torrent_manager import TorrentManager
from database import NotificationManager


class TorrentBackgroundMonitor:
    """Background thread for monitoring torrents and auto-adding completed ones to library."""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.check_interval = TORRENT_CHECK_INTERVAL  # Check every 30 seconds
        self.torrent_manager = TorrentManager()
        self.notification_manager = NotificationManager()
        
    def start_monitoring(self) -> None:
        """Start the background monitoring thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            print("🔄 Background torrent monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop the background monitoring thread."""
        if self.running:
            self.running = False
            if self.thread:
                self.thread.join(timeout=2)
            print("⏹️  Background torrent monitoring stopped")
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop that runs in the background."""
        while self.running:
            try:
                # Check for completed torrents and auto-add to library
                newly_completed = self.torrent_manager.auto_add_completed_torrents()
                
                # If any torrents were completed, save a notification
                if newly_completed:
                    self.notification_manager.save_completion_notifications(newly_completed)
                    
            except Exception as e:
                print(f"⚠️  Background monitor error during auto-add cycle: {e}")
            
            # Wait for the next check (with small intervals to allow clean shutdown)
            for _ in range(self.check_interval * 10):  # Check every 0.1s for shutdown
                if not self.running:
                    break
                time.sleep(0.1)


# Global background monitor instance
background_monitor = TorrentBackgroundMonitor()
