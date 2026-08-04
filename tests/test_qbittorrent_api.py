import unittest
from unittest.mock import Mock, patch

from qbittorrent_api import QBittorrentAPI


class QBittorrentLoginTests(unittest.TestCase):
    def login_with_response(self, status_code: int, text: str):
        api = QBittorrentAPI(
            host="http://localhost:1337",
            username="admin",
            password="test-password",
        )
        response = Mock(status_code=status_code, text=text)

        with (
            patch.object(api, "check_connection", return_value=True),
            patch.object(api, "_request_with_retry", return_value=response),
        ):
            success = api.login()

        return api, success

    def test_login_accepts_204_no_content(self):
        api, success = self.login_with_response(204, "")

        self.assertTrue(success)
        self.assertIsNotNone(api.session)

    def test_login_accepts_legacy_ok_body(self):
        api, success = self.login_with_response(200, "Ok.")

        self.assertTrue(success)
        self.assertIsNotNone(api.session)

    def test_login_rejects_failure_body(self):
        api, success = self.login_with_response(200, "Fails.")

        self.assertFalse(success)
        self.assertIsNone(api.session)


if __name__ == "__main__":
    unittest.main()
