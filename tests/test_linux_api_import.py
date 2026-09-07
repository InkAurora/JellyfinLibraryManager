import os
import unittest


@unittest.skipIf(os.name == "nt", "Linux API regression")
class LinuxApiImportTests(unittest.TestCase):
    def test_api_import_does_not_require_windows_console(self):
        import api_server

        self.assertTrue(hasattr(api_server, "JellyfinApi"))

    def test_interactive_anilist_search_has_clear_platform_error(self):
        from anilist_api import AniListAPI

        with self.assertRaisesRegex(RuntimeError, "requires a Windows console"):
            AniListAPI().interactive_search()

    def test_interactive_nyaa_browsing_has_clear_platform_error(self):
        from nyaa_api import NyaaAPI

        with self.assertRaisesRegex(RuntimeError, "requires a Windows console"):
            NyaaAPI().navigate_results([{"title": "test"}])

    def test_interactive_imdb_search_has_clear_platform_error(self):
        from imdb_api import IMDBAPI

        with self.assertRaisesRegex(RuntimeError, "requires a Windows console"):
            IMDBAPI().interactive_movie_selection()


if __name__ == "__main__":
    unittest.main()
