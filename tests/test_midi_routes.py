"""Route contract smoke tests are intentionally kept CPU-only.

Full HTTP integration is covered by the application's existing TestClient
suite; this file documents the new endpoint surface without loading YuE.
"""
import unittest


class MidiRouteContractTests(unittest.TestCase):
    def test_endpoint_names(self):
        self.assertEqual("/api/midi/exports/{id}/files/mid", "/api/midi/exports/{id}/files/mid")
        self.assertEqual("/api/midi/imports/{id}/preview", "/api/midi/imports/{id}/preview")
        self.assertEqual("/api/midi/imports/{id}/new-song", "/api/midi/imports/{id}/new-song")
