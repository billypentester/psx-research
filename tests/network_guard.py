"""Test base class that makes any real network connection fail the test."""

import unittest
from unittest.mock import patch


class NoNetworkTestCase(unittest.TestCase):
    def setUp(self):
        def refuse(*args, **kwargs):
            raise AssertionError("a real network connection was attempted")

        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            patcher = patch(target, side_effect=refuse)
            patcher.start()
            self.addCleanup(patcher.stop)
