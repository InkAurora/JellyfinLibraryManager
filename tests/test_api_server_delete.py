import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from api_server import ApiError, JellyfinApi
from torrent_manager import TorrentManager


TORRENT_HASH = "a" * 40


class DeleteTorrentApiTests(unittest.TestCase):
    def setUp(self):
        self.events: list[str] = []
        self.session = object()
        self.tracked = {
            "id": 30,
            "infohash": TORRENT_HASH,
            "source_download_path": r"D:\Torrents\episode.mp4",
            "library_path": r"D:\Series\Show",
            "media_type": "series",
            "status": "added_to_library",
        }
        self.qb_torrent = {
            "hash": TORRENT_HASH,
            "content_path": r"D:\Torrents\episode.mp4",
            "save_path": r"D:\Torrents",
            "name": "episode.mp4",
        }
        self.api = JellyfinApi.__new__(JellyfinApi)
        self.api.torrent_manager = Mock()
        self.api._qb_session = Mock(side_effect=self._session)
        self.cleanup_plan = {
            "library_path": self.tracked["library_path"],
            "source_paths": [self.tracked["source_download_path"]],
            "linked_paths": [r"D:\Series\Show\Season 01\episode.mp4"],
            "video_links": [r"D:\Series\Show\Season 01\episode.mp4"],
            "sidecar_paths": [r"D:\Series\Show\Season 01\episode.nfo"],
        }

    def _session(self):
        self.events.append("session")
        return self.session

    def _tracked_torrents(self):
        self.events.append("tracked")
        return [self.tracked]

    def _qb_torrents(self, session):
        self.assertIs(session, self.session)
        self.events.append("qb_info")
        return [self.qb_torrent]

    def _plan(self, torrent, additional_source_paths=None):
        self.events.append("plan")
        return self.cleanup_plan

    def _remove_qb(self, session, infohash, delete_files=False):
        self.assertIs(session, self.session)
        self.events.append("qb_remove")
        return True

    def _update_status(self, torrent_id, status):
        self.assertEqual(torrent_id, self.tracked["id"])
        self.events.append(f"status:{status}")
        return True

    def _cleanup(self, torrent, additional_source_paths=None, cleanup_plan=None):
        self.assertIs(cleanup_plan, self.cleanup_plan)
        self.events.append("cleanup")
        return {
            "success": True,
            "removed_links": [r"D:\Series\Show\Season 01\episode.mp4"],
            "removed_sidecars": [r"D:\Series\Show\Season 01\episode.nfo"],
            "removed_library_root": False,
        }

    def _remove_db(self, infohash):
        self.events.append("db")
        return 1

    def test_delete_files_and_library_preflights_then_removes_in_order(self):
        self.api.torrent_manager.plan_torrent_library_cleanup.side_effect = self._plan
        self.api.torrent_manager.remove_torrent_library_files.side_effect = self._cleanup

        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info", side_effect=self._qb_torrents),
            patch("api_server.update_torrent_status", side_effect=self._update_status) as update_status,
            patch("api_server.qb_remove_torrent", side_effect=self._remove_qb) as remove_qb,
            patch("api_server.remove_torrent_from_database_by_infohash", side_effect=self._remove_db) as remove_db,
        ):
            status, payload = self.api._delete_torrent(
                TORRENT_HASH.upper(),
                {"delete_files": ["true"], "delete_library": ["true"]},
            )

        expected_sources = [self.qb_torrent["content_path"]]
        self.assertEqual(
            self.events,
            ["session", "tracked", "qb_info", "plan", "status:deletion_pending", "qb_remove", "cleanup", "db"],
        )
        self.api.torrent_manager.plan_torrent_library_cleanup.assert_called_once_with(
            self.tracked,
            additional_source_paths=expected_sources,
        )
        self.api.torrent_manager.remove_torrent_library_files.assert_called_once_with(
            self.tracked,
            additional_source_paths=expected_sources,
            cleanup_plan=self.cleanup_plan,
        )
        remove_qb.assert_called_once_with(self.session, TORRENT_HASH, delete_files=True)
        update_status.assert_called_once_with(self.tracked["id"], "deletion_pending")
        remove_db.assert_called_once_with(TORRENT_HASH)
        self.assertEqual(status, 200)
        self.assertTrue(payload["data"]["removed_library"])
        self.assertEqual(payload["data"]["removed_from_database"], 1)
        self.assertTrue(payload["data"]["delete_files"])

    def test_delete_without_library_cleanup_preserves_downloading_flow(self):
        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info") as qb_info,
            patch("api_server.update_torrent_status") as update_status,
            patch("api_server.qb_remove_torrent", side_effect=self._remove_qb) as remove_qb,
            patch("api_server.remove_torrent_from_database_by_infohash", side_effect=self._remove_db),
        ):
            status, payload = self.api._delete_torrent(
                TORRENT_HASH,
                {"delete_files": ["true"], "delete_library": ["false"]},
            )

        self.assertEqual(self.events, ["session", "tracked", "qb_remove", "db"])
        qb_info.assert_not_called()
        update_status.assert_not_called()
        self.api.torrent_manager.plan_torrent_library_cleanup.assert_not_called()
        self.api.torrent_manager.remove_torrent_library_files.assert_not_called()
        remove_qb.assert_called_once_with(self.session, TORRENT_HASH, delete_files=True)
        self.assertEqual(status, 200)
        self.assertFalse(payload["data"]["removed_library"])
        self.assertIsNone(payload["data"]["library_cleanup"])

    def test_qbittorrent_failure_does_not_mutate_library_or_database(self):
        self.api.torrent_manager.plan_torrent_library_cleanup.side_effect = self._plan

        def fail_qb(session, infohash, delete_files=False):
            self.events.append("qb_remove")
            return False

        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info", side_effect=self._qb_torrents),
            patch("api_server.update_torrent_status", side_effect=self._update_status) as update_status,
            patch("api_server.qb_remove_torrent", side_effect=fail_qb),
            patch("api_server.remove_torrent_from_database_by_infohash") as remove_db,
        ):
            with self.assertRaises(ApiError) as raised:
                self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            self.events,
            [
                "session",
                "tracked",
                "qb_info",
                "plan",
                "status:deletion_pending",
                "qb_remove",
                "status:added_to_library",
            ],
        )
        self.assertEqual(
            update_status.call_args_list,
            [call(self.tracked["id"], "deletion_pending"), call(self.tracked["id"], "added_to_library")],
        )
        self.api.torrent_manager.remove_torrent_library_files.assert_not_called()
        remove_db.assert_not_called()

    def test_imported_torrent_with_no_owned_links_returns_conflict_before_qb_delete(self):
        empty_plan = {
            "library_path": self.tracked["library_path"],
            "source_paths": [self.tracked["source_download_path"]],
            "linked_paths": [],
            "video_links": [],
            "sidecar_paths": [],
        }

        def plan_without_links(torrent, additional_source_paths=None):
            self.events.append("plan")
            return empty_plan

        self.api.torrent_manager.plan_torrent_library_cleanup.side_effect = plan_without_links

        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info", side_effect=self._qb_torrents),
            patch("api_server.os.path.lexists", return_value=True),
            patch("api_server.update_torrent_status") as update_status,
            patch("api_server.qb_remove_torrent") as remove_qb,
            patch("api_server.remove_torrent_from_database_by_infohash") as remove_db,
        ):
            with self.assertRaises(ApiError) as raised:
                self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("No related library links", raised.exception.message)
        self.assertEqual(self.events, ["session", "tracked", "qb_info", "plan"])
        update_status.assert_not_called()
        remove_qb.assert_not_called()
        self.api.torrent_manager.remove_torrent_library_files.assert_not_called()
        remove_db.assert_not_called()

    def test_status_marker_failure_stops_before_qb_and_library_mutation(self):
        self.api.torrent_manager.plan_torrent_library_cleanup.side_effect = self._plan

        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info", side_effect=self._qb_torrents),
            patch("api_server.update_torrent_status", return_value=False) as update_status,
            patch("api_server.qb_remove_torrent") as remove_qb,
            patch("api_server.remove_torrent_from_database_by_infohash") as remove_db,
        ):
            with self.assertRaises(ApiError) as raised:
                self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("mark torrent for library cleanup", raised.exception.message)
        self.assertEqual(self.events, ["session", "tracked", "qb_info", "plan"])
        update_status.assert_called_once_with(self.tracked["id"], "deletion_pending")
        remove_qb.assert_not_called()
        self.api.torrent_manager.remove_torrent_library_files.assert_not_called()
        remove_db.assert_not_called()

    def test_partial_retry_without_qb_item_prunes_metadata_root_and_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            series_root = Path(temp_dir) / "Series"
            library = series_root / "Show"
            season = library / "Season 01"
            season.mkdir(parents=True)
            (library / "tvshow.nfo").write_text("series", encoding="utf-8")
            (library / "folder.jpg").write_bytes(b"art")
            (season / "season.nfo").write_text("season", encoding="utf-8")

            tracked = dict(self.tracked)
            tracked.update(
                {
                    "status": "deletion_pending",
                    "library_path": str(library),
                    "source_download_path": str(Path(temp_dir) / "Torrents" / "episode.mp4"),
                }
            )
            (library / "track.json").write_text(json.dumps(tracked), encoding="utf-8")
            self.api.torrent_manager = TorrentManager()

            with (
                patch("api_server.get_tracked_torrents", return_value=[tracked]),
                patch("torrent_manager.get_tracked_torrents", return_value=[tracked]),
                patch("torrent_manager.get_series_folder", return_value=str(series_root)),
                patch("api_server.qb_get_torrent_info", return_value=[]),
                patch("api_server.update_torrent_status") as update_status,
                patch("api_server.qb_remove_torrent", return_value=True) as remove_qb,
                patch("api_server.remove_torrent_from_database_by_infohash", return_value=1) as remove_db,
            ):
                status, payload = self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        remove_qb.assert_called_once_with(self.session, TORRENT_HASH, delete_files=True)
        update_status.assert_not_called()
        remove_db.assert_called_once_with(TORRENT_HASH)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["removed_from_database"], 1)
        self.assertTrue(payload["data"]["removed_library"])
        self.assertTrue(payload["data"]["library_cleanup"]["success"])
        self.assertTrue(payload["data"]["library_cleanup"]["removed_library_root"])
        self.assertFalse(library.exists())

    def test_duplicate_hash_with_conflicting_library_paths_returns_conflict(self):
        conflicting = dict(self.tracked)
        conflicting.update({"id": 31, "library_path": r"D:\Series\Other Show"})

        def duplicate_rows():
            self.events.append("tracked")
            return [self.tracked, conflicting]

        with (
            patch("api_server.get_tracked_torrents", side_effect=duplicate_rows),
            patch("api_server.qb_get_torrent_info") as qb_info,
            patch("api_server.update_torrent_status") as update_status,
            patch("api_server.qb_remove_torrent") as remove_qb,
            patch("api_server.remove_torrent_from_database_by_infohash") as remove_db,
        ):
            with self.assertRaises(ApiError) as raised:
                self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("different library paths", raised.exception.message)
        self.assertEqual(self.events, ["session", "tracked"])
        qb_info.assert_not_called()
        update_status.assert_not_called()
        remove_qb.assert_not_called()
        self.api.torrent_manager.plan_torrent_library_cleanup.assert_not_called()
        self.api.torrent_manager.remove_torrent_library_files.assert_not_called()
        remove_db.assert_not_called()

    def test_library_cleanup_failure_keeps_database_row_and_returns_error(self):
        self.api.torrent_manager.plan_torrent_library_cleanup.side_effect = self._plan
        self.api.torrent_manager.remove_torrent_library_files.side_effect = lambda *args, **kwargs: (
            self.events.append("cleanup")
            or {"success": False, "error": "access denied"}
        )

        with (
            patch("api_server.get_tracked_torrents", side_effect=self._tracked_torrents),
            patch("api_server.qb_get_torrent_info", side_effect=self._qb_torrents),
            patch("api_server.update_torrent_status", side_effect=self._update_status) as update_status,
            patch("api_server.qb_remove_torrent", side_effect=self._remove_qb),
            patch("api_server.remove_torrent_from_database_by_infohash") as remove_db,
        ):
            with self.assertRaises(ApiError) as raised:
                self.api._delete_torrent(
                    TORRENT_HASH,
                    {"delete_files": ["true"], "delete_library": ["true"]},
                )

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("access denied", str(raised.exception.details))
        self.assertEqual(
            self.events,
            ["session", "tracked", "qb_info", "plan", "status:deletion_pending", "qb_remove", "cleanup"],
        )
        update_status.assert_called_once_with(self.tracked["id"], "deletion_pending")
        remove_db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
