import os
import unittest

from api_server import ApiRequestHandler, LibraryManagerHttpServer


class ApiServerRuntimeTests(unittest.TestCase):
    def test_handler_uses_persistent_http_connections(self):
        self.assertEqual(ApiRequestHandler.protocol_version, "HTTP/1.1")

    def test_windows_listener_does_not_reuse_an_occupied_port(self):
        self.assertEqual(LibraryManagerHttpServer.allow_reuse_address, os.name != "nt")


if __name__ == "__main__":
    unittest.main()
