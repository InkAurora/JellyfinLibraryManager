import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from episode_naming import (
    detect_episode_numbers,
    is_extra_video,
    is_extras_folder,
    is_specials_name,
    plan_episode_link_names,
    season_number_in_name,
)
from torrent_manager import TorrentManager


def edgerunners_files() -> list[str]:
    return [f"Cyberpunk Edgerunners 2 - {number:02d} [2160p WEB-DL DV HDR10].mkv" for number in range(1, 11)]


class EpisodeNumberTests(unittest.TestCase):
    def test_number_in_show_title_is_not_the_episode(self):
        numbers = detect_episode_numbers(edgerunners_files())
        self.assertEqual(sorted(numbers.values()), list(range(1, 11)))

    def test_common_release_styles(self):
        cases = {
            "Frieren.Beyond.Journeys.End.S02E07.The.Divine.Revolte.1080p.CR.WEB-DL.MULTi.AAC2.0.H.264-VARYG.mkv": 7,
            "[sam] Grand Blue S2 - 03v2 [WEB 1080p EAC-3] [FF495825].mkv": 3,
            "[Anime Time] JoJo's Bizarre Adventure Stardust Crusaders - 48.mkv": 48,
            "Mob Psycho 100 - 05 [1080p].mkv": 5,
            "Show 2x04 Title.mkv": 4,
            "Show Ep 09.mkv": 9,
        }
        for file_name, episode in cases.items():
            with self.subTest(file_name=file_name):
                self.assertEqual(detect_episode_numbers([file_name])[file_name], episode)

    def test_varying_number_without_separator(self):
        files = [f"[Anime Time] {number:02d}. Title {number} (2000).mkv" for number in (1, 2, 3)]
        self.assertEqual([detect_episode_numbers(files)[name] for name in files], [1, 2, 3])

    def test_unknown_single_file_keeps_none(self):
        self.assertIsNone(detect_episode_numbers(["Kaiju No 8.mkv"])["Kaiju No 8.mkv"])

    def test_link_names_use_show_and_season(self):
        sources = [os.path.join("D:\\Torrents", "Edgerunners 2", name) for name in edgerunners_files()]
        names = plan_episode_link_names(sources, "Cyberpunk  Edgerunners 2", 1)
        self.assertEqual(names[sources[0]], "Cyberpunk Edgerunners 2 S01E01.mkv")
        self.assertEqual(names[sources[9]], "Cyberpunk Edgerunners 2 S01E10.mkv")

    def test_duplicate_episode_numbers_keep_release_names(self):
        sources = [
            os.path.join("D:\\Torrents", "A", "Show - 01.mkv"),
            os.path.join("D:\\Torrents", "B", "Other - 01.mkv"),
        ]
        names = plan_episode_link_names(sources, "Show", 0)
        self.assertEqual(names, {source: os.path.basename(source) for source in sources})


class NameClassTests(unittest.TestCase):
    def test_extras(self):
        for name in ("OP 01.mkv", "ED 02 Last Train Home.mkv", "OP1 Title.mkv", "[Grp] Show - NCOP1 [1080p].mkv",
                     "Show - ED.mkv", "Show NCED 02.mkv", "Preview 03.mkv"):
            with self.subTest(name=name):
                self.assertTrue(is_extra_video(name))
        for name in ("Fullmetal Alchemist - 01 - Ed and Al.mkv", "Ed and Al 01.mkv", "Cowboy Bebop - 17.mkv"):
            with self.subTest(name=name):
                self.assertFalse(is_extra_video(name))

    def test_extras_folders(self):
        for name in ("Extras", "NCOP", "NCED", "OP&ED", "Menus", "Creditless OP"):
            with self.subTest(name=name):
                self.assertTrue(is_extras_folder(name))
        self.assertFalse(is_extras_folder("Season 2"))

    def test_specials_need_a_whole_word(self):
        self.assertTrue(is_specials_name("Specials"))
        self.assertTrue(is_specials_name("Show - OVA 2.mkv"))
        self.assertTrue(is_specials_name("Show - SP1.mkv"))
        for name in ("SPY x FAMILY", "Spice and Wolf", "Space Dandy", "Nova"):
            with self.subTest(name=name):
                self.assertFalse(is_specials_name(name))

    def test_season_numbers(self):
        cases = {
            "Show S02E01.mkv": 2,
            "[sam] Grand Blue S2 - 01v2.mkv": 2,
            "Season 3": 3,
            "Show 2nd Season": 2,
            "Show.S02.1080p": 2,
            "Show 1x05.mkv": 1,
            "Show S00E01.mkv": 0,
        }
        for name, season in cases.items():
            with self.subTest(name=name):
                self.assertEqual(season_number_in_name(name), season)
        for name in ("Cyberpunk Edgerunners 2 [2160p WEB-DL DV HDR10]", "Show DTS5.1", "SPY x FAMILY"):
            with self.subTest(name=name):
                self.assertIsNone(season_number_in_name(name))


class TorrentSortTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.anime_root = self.base / "Anime"
        self.anime_root.mkdir()
        self.manager = TorrentManager()

    def make_torrent(self, folder: str, files: list[str]) -> Path:
        download = self.base / "Torrents" / folder
        for relative in files:
            path = download / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
        return download

    def sort(self, title: str, download: Path) -> dict[str, str]:
        torrent = {"media_type": "anime", "media_metadata": {"title": title}}
        with patch("torrent_manager.get_anime_folder", return_value=str(self.anime_root)), \
                patch("torrent_manager.probe_video_duration", return_value=24 * 60):
            structure = self.manager.sort_torrent_files_for_jellyfin(torrent, str(download))
        return {
            os.path.relpath(entry["source"], download): os.path.relpath(entry["target"], structure["root"])
            for folder in structure["folders"]
            for entry in folder["files"]
        }

    def test_edgerunners_2_gets_clean_episode_names(self):
        download = self.make_torrent("Cyberpunk Edgerunners 2 [2160p WEB-DL DV HDR10]", edgerunners_files())
        targets = self.sort("Cyberpunk: Edgerunners 2", download)
        self.assertEqual(targets[edgerunners_files()[0]], os.path.join("Season 01", "Cyberpunk Edgerunners 2 S01E01.mkv"))
        self.assertEqual(len(set(targets.values())), 10)

    def test_openings_and_endings_go_to_extras(self):
        download = self.make_torrent("JoJo", [
            os.path.join("Season 1", "[Anime Time] JoJo - 01.mkv"),
            os.path.join("Season 1", "OP 01.mkv"),
            os.path.join("Season 3", "OP 01.mkv"),
            os.path.join("NCOP", "Creditless Opening 1.mkv"),
        ])
        targets = self.sort("JoJo", download)
        self.assertEqual(targets[os.path.join("Season 1", "[Anime Time] JoJo - 01.mkv")], os.path.join("Season 01", "JoJo S01E01.mkv"))
        self.assertEqual(targets[os.path.join("Season 1", "OP 01.mkv")], os.path.join("extras", "Season 1 - OP 01.mkv"))
        self.assertEqual(targets[os.path.join("Season 3", "OP 01.mkv")], os.path.join("extras", "Season 3 - OP 01.mkv"))
        self.assertEqual(targets[os.path.join("NCOP", "Creditless Opening 1.mkv")], os.path.join("extras", "NCOP - Creditless Opening 1.mkv"))

    def test_show_name_with_sp_is_not_specials(self):
        download = self.make_torrent("Spy x Family", [os.path.join("Spy x Family", "Spy x Family - 01.mkv")])
        targets = self.sort("SPY x FAMILY", download)
        self.assertEqual(targets[os.path.join("Spy x Family", "Spy x Family - 01.mkv")], os.path.join("Season 01", "SPY x FAMILY S01E01.mkv"))

    def test_torrent_folder_season_is_used_when_files_have_none(self):
        download = self.make_torrent("Frieren S02 [1080p]", ["Frieren - 01.mkv", "Frieren - 02.mkv"])
        targets = self.sort("Frieren", download)
        self.assertEqual(targets["Frieren - 02.mkv"], os.path.join("Season 02", "Frieren S02E02.mkv"))

    def link_into_library(self, download: Path) -> list[tuple[str, str]]:
        created = []

        def fake_symlink(source, target):
            Path(target).write_bytes(b"link")
            created.append((str(source), str(target)))

        torrent = {"title": "Show", "media_type": "anime", "media_metadata": {"title": "Show"}}
        with patch("torrent_manager.get_anime_folder", return_value=str(self.anime_root)), \
                patch("torrent_manager.probe_video_duration", return_value=24 * 60), \
                patch("torrent_manager.os.symlink", side_effect=fake_symlink), \
                patch.object(TorrentManager, "_write_tracking_file"):
            self.assertTrue(self.manager.add_completed_torrent_to_library(torrent, str(download)))
        return created

    def test_taken_clean_name_falls_back_to_release_name(self):
        download = self.make_torrent("Show", ["Show - 01.mkv"])
        season = self.anime_root / "Show" / "Season 01"
        season.mkdir(parents=True)
        (season / "Show S01E01.mkv").write_bytes(b"another release")

        created = self.link_into_library(download)

        self.assertEqual(created, [(str(download / "Show - 01.mkv"), str(season / "Show - 01.mkv"))])

    def test_free_clean_name_is_linked(self):
        download = self.make_torrent("Show", ["Show - 01.mkv"])

        created = self.link_into_library(download)

        season = self.anime_root / "Show" / "Season 01"
        self.assertEqual(created, [(str(download / "Show - 01.mkv"), str(season / "Show S01E01.mkv"))])


if __name__ == "__main__":
    unittest.main()
