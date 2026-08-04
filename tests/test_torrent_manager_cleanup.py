import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from torrent_manager import TorrentManager


BUNDLE_HASH = "1" * 40
EPISODE_HASH = "2" * 40


def canonical(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


class TorrentLibraryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.base = Path(self.temp_dir.name)
        self.series_root = self.base / "Series"
        self.library = self.series_root / "House of the Dragon"
        self.season = self.library / "Season 03"
        self.season.mkdir(parents=True)
        self.source_root = self.base / "Torrents"
        self.fake_links: dict[str, str] = {}

    def torrent(self, infohash: str, source: Path, torrent_id: int) -> dict:
        return {
            "id": torrent_id,
            "title": f"torrent-{torrent_id}",
            "infohash": infohash,
            "source_download_path": str(source),
            "download_path": str(source),
            "library_path": str(self.library),
            "media_type": "series",
            "media_metadata": {"title": "House of the Dragon"},
        }

    def add_fake_link(self, library_path: Path, target_path: Path) -> None:
        library_path.parent.mkdir(parents=True, exist_ok=True)
        library_path.touch()
        self.fake_links[canonical(library_path)] = str(target_path)

    def add_episode_sidecars(self, video_path: Path) -> set[Path]:
        stem = video_path.stem
        nfo = video_path.with_suffix(".nfo")
        thumb = video_path.with_name(f"{stem}-thumb.jpg")
        subtitle = video_path.with_name(f"{stem}.en.srt")
        trickplay = video_path.with_name(f"{stem}.trickplay")
        nfo.write_text("episode metadata", encoding="utf-8")
        thumb.write_bytes(b"art")
        subtitle.write_text("subtitle", encoding="utf-8")
        trickplay.mkdir()
        (trickplay / "320 - 0.jpg").write_bytes(b"frame")
        return {nfo, thumb, subtitle, trickplay}

    @contextmanager
    def patched_library(self, tracked_torrents: list[dict]):
        real_islink = os.path.islink
        real_readlink = os.readlink

        def fake_islink(path):
            return canonical(path) in self.fake_links or real_islink(path)

        def fake_readlink(path):
            target = self.fake_links.get(canonical(path))
            if target is not None:
                return target
            return real_readlink(path)

        with ExitStack() as stack:
            stack.enter_context(patch("torrent_manager.get_series_folder", return_value=str(self.series_root)))
            stack.enter_context(patch("torrent_manager.get_tracked_torrents", return_value=tracked_torrents))
            stack.enter_context(patch("torrent_manager.os.path.islink", side_effect=fake_islink))
            stack.enter_context(patch("torrent_manager.os.readlink", side_effect=fake_readlink))
            yield

    def write_track(self, torrent: dict) -> Path:
        track_path = self.library / "track.json"
        track_path.write_text(json.dumps(torrent), encoding="utf-8")
        return track_path

    def test_bundle_cleanup_preserves_sibling_and_rewrites_tracking(self):
        bundle_source = self.source_root / "House.Of.The.Dragon.S03"
        episode_source = self.source_root / "House.Of.The.Dragon.S03E03" / "E03.mp4"
        bundle = self.torrent(BUNDLE_HASH, bundle_source, 29)
        episode = self.torrent(EPISODE_HASH, episode_source, 30)

        episode_one = self.season / "House.Of.The.Dragon.S03E01.mkv"
        episode_two = self.season / "House.Of.The.Dragon.S03E02.mkv"
        episode_three = self.season / "House.Of.The.Dragon.S03E03.mp4"
        self.add_fake_link(episode_one, bundle_source / episode_one.name)
        self.add_fake_link(episode_two, bundle_source / episode_two.name)
        self.add_fake_link(episode_three, episode_source)
        removed_sidecars = self.add_episode_sidecars(episode_one) | self.add_episode_sidecars(episode_two)
        preserved_sidecars = self.add_episode_sidecars(episode_three)

        season_nfo = self.season / "season.nfo"
        series_nfo = self.library / "tvshow.nfo"
        folder_art = self.library / "folder.jpg"
        season_nfo.write_text("season", encoding="utf-8")
        series_nfo.write_text("series", encoding="utf-8")
        folder_art.write_bytes(b"poster")
        track_path = self.write_track(bundle)

        with self.patched_library([bundle, episode]):
            report = TorrentManager().remove_torrent_library_files(bundle)

        self.assertTrue(report["success"])
        self.assertEqual(
            {canonical(path) for path in report["removed_links"]},
            {canonical(episode_one), canonical(episode_two)},
        )
        self.assertEqual(
            {canonical(path) for path in report["removed_sidecars"]},
            {canonical(path) for path in removed_sidecars},
        )
        self.assertFalse(episode_one.exists())
        self.assertFalse(episode_two.exists())
        self.assertTrue(episode_three.exists())
        for path in removed_sidecars:
            self.assertFalse(path.exists(), path)
        for path in preserved_sidecars | {season_nfo, series_nfo, folder_art}:
            self.assertTrue(path.exists(), path)
        self.assertTrue(self.season.is_dir())
        self.assertTrue(self.library.is_dir())
        self.assertFalse(report["removed_library_root"])
        self.assertTrue(report["tracking_file_updated"])

        refreshed_track = json.loads(track_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed_track["infohash"], EPISODE_HASH)
        self.assertEqual(canonical(refreshed_track["source_download_path"]), canonical(episode_source))
        self.assertEqual(canonical(refreshed_track["library_path"]), canonical(self.library))

    def test_single_episode_cleanup_preserves_bundle(self):
        bundle_source = self.source_root / "House.Of.The.Dragon.S03"
        episode_source = self.source_root / "House.Of.The.Dragon.S03E03" / "E03.mp4"
        bundle = self.torrent(BUNDLE_HASH, bundle_source, 29)
        episode = self.torrent(EPISODE_HASH, episode_source, 30)

        episode_one = self.season / "House.Of.The.Dragon.S03E01.mkv"
        episode_two = self.season / "House.Of.The.Dragon.S03E02.mkv"
        episode_three = self.season / "House.Of.The.Dragon.S03E03.mp4"
        self.add_fake_link(episode_one, bundle_source / episode_one.name)
        self.add_fake_link(episode_two, bundle_source / episode_two.name)
        self.add_fake_link(episode_three, episode_source)
        bundle_sidecars = self.add_episode_sidecars(episode_one) | self.add_episode_sidecars(episode_two)
        episode_sidecars = self.add_episode_sidecars(episode_three)
        track_path = self.write_track(episode)

        with self.patched_library([bundle, episode]):
            report = TorrentManager().remove_torrent_library_files(episode)

        self.assertTrue(report["success"])
        self.assertEqual({canonical(path) for path in report["removed_links"]}, {canonical(episode_three)})
        self.assertFalse(episode_three.exists())
        for path in episode_sidecars:
            self.assertFalse(path.exists(), path)
        for path in {episode_one, episode_two} | bundle_sidecars:
            self.assertTrue(path.exists(), path)
        refreshed_track = json.loads(track_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed_track["infohash"], BUNDLE_HASH)

    def test_last_torrent_cleanup_removes_whole_library_root(self):
        episode_source = self.source_root / "House.Of.The.Dragon.S03E03" / "E03.mp4"
        episode = self.torrent(EPISODE_HASH, episode_source, 30)
        episode_three = self.season / "House.Of.The.Dragon.S03E03.mp4"
        self.add_fake_link(episode_three, episode_source)
        self.add_episode_sidecars(episode_three)
        (self.season / "season.nfo").write_text("season", encoding="utf-8")
        (self.library / "tvshow.nfo").write_text("series", encoding="utf-8")
        self.write_track(episode)

        with self.patched_library([episode]):
            report = TorrentManager().remove_torrent_library_files(episode)

        self.assertTrue(report["success"])
        self.assertTrue(report["removed_library_root"])
        self.assertEqual(
            {canonical(path) for path in report["removed_season_folders"]},
            {canonical(self.season)},
        )
        self.assertFalse(self.library.exists())

    def test_unknown_manual_file_prevents_last_library_root_removal(self):
        episode_source = self.source_root / "House.Of.The.Dragon.S03E03" / "E03.mp4"
        episode = self.torrent(EPISODE_HASH, episode_source, 30)
        episode_three = self.season / "House.Of.The.Dragon.S03E03.mp4"
        self.add_fake_link(episode_three, episode_source)
        episode_sidecars = self.add_episode_sidecars(episode_three)
        manual_file = self.season / "keep-me.txt"
        manual_file.write_text("not Jellyfin metadata", encoding="utf-8")
        track_path = self.write_track(episode)

        with self.patched_library([episode]):
            report = TorrentManager().remove_torrent_library_files(episode)

        self.assertTrue(report["success"])
        self.assertFalse(report["removed_library_root"])
        self.assertEqual(report["removed_season_folders"], [])
        self.assertTrue(self.library.is_dir())
        self.assertTrue(self.season.is_dir())
        self.assertTrue(manual_file.exists())
        self.assertFalse(episode_three.exists())
        self.assertFalse(track_path.exists())
        for path in episode_sidecars:
            self.assertFalse(path.exists(), path)

    def test_plan_uses_path_boundaries_not_string_prefixes(self):
        selected_source = self.source_root / "House.Of.The.Dragon.S03"
        prefix_sibling_source = self.source_root / "House.Of.The.Dragon.S030" / "E01.mkv"
        selected = self.torrent(BUNDLE_HASH, selected_source, 29)
        sibling_link = self.season / "House.Of.The.Dragon.S030E01.mkv"
        self.add_fake_link(sibling_link, prefix_sibling_source)

        with self.patched_library([selected]):
            plan = TorrentManager().plan_torrent_library_cleanup(selected)

        self.assertEqual(plan["linked_paths"], [])
        self.assertEqual(plan["sidecar_paths"], [])
        self.assertTrue(sibling_link.exists())

    def test_plan_rejects_library_path_outside_configured_root(self):
        torrent = self.torrent(BUNDLE_HASH, self.source_root / "bundle", 29)
        torrent["library_path"] = str(self.base / "Not Series" / "House of the Dragon")

        with self.patched_library([torrent]):
            with self.assertRaisesRegex(ValueError, "outside configured library folders"):
                TorrentManager().plan_torrent_library_cleanup(torrent)

    def test_plan_rejects_configured_library_root_itself(self):
        torrent = self.torrent(BUNDLE_HASH, self.source_root / "bundle", 29)
        torrent["library_path"] = str(self.series_root)

        with self.patched_library([torrent]):
            with self.assertRaisesRegex(ValueError, "outside configured library folders"):
                TorrentManager().plan_torrent_library_cleanup(torrent)

    def test_plan_rejects_source_overlapping_sibling_torrent(self):
        broad_source = self.source_root / "House.Of.The.Dragon.S03"
        sibling_source = broad_source / "House.Of.The.Dragon.S03E03.mp4"
        selected = self.torrent(BUNDLE_HASH, broad_source, 29)
        sibling = self.torrent(EPISODE_HASH, sibling_source, 30)

        with self.patched_library([selected, sibling]):
            with self.assertRaisesRegex(ValueError, "overlaps another tracked torrent"):
                TorrentManager().plan_torrent_library_cleanup(selected)

    def test_plan_rejects_overlapping_source_owned_by_different_library(self):
        broad_source = self.source_root / "Shared.Download"
        sibling_source = broad_source / "episode.mp4"
        selected = self.torrent(BUNDLE_HASH, broad_source, 29)
        sibling = self.torrent(EPISODE_HASH, sibling_source, 30)
        sibling["library_path"] = str(self.series_root / "Another Show")
        sibling["media_metadata"] = {"title": "Another Show"}

        with self.patched_library([selected, sibling]):
            with self.assertRaisesRegex(ValueError, "overlaps another tracked torrent"):
                TorrentManager().plan_torrent_library_cleanup(selected)


if __name__ == "__main__":
    unittest.main()
