"""HTTP regression checks; run outside a sandbox that blocks loopback sockets."""
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from studio.app import create_app
from studio.config import load_config
from studio.storage import Store
from studio.queue import Queue


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-http-")
        self.config = replace(load_config(), data_dir=Path(self.temp.name), engine="test",
                              allowed_hosts=("testserver", "localhost", "127.0.0.1"))

    def tearDown(self):
        self.temp.cleanup()

    def test_recovery_does_not_block_page_or_health(self):
        gate = threading.Event()
        original = Store.recover
        def slow_recovery(store):
            gate.wait(5)
            return original(store)
        with patch.object(Store, "recover", slow_recovery):
            with TestClient(create_app(self.config)) as client:
                try:
                    started = time.monotonic()
                    self.assertEqual(client.get("/").status_code, 200)
                    health = client.get("/api/health").json()
                    self.assertFalse(health["ready"])
                    self.assertEqual(client.get("/api/jobs").status_code, 503)
                    self.assertLess(time.monotonic() - started, 2)
                finally:
                    gate.set()

    def test_loading_generation_and_worker_failure_keep_http_responsive(self):
        gate = threading.Event()
        original = Queue._start_worker
        def slow_load(queue):
            queue.worker_state = "loading"
            gate.wait(5)
            return original(queue)
        app = create_app(self.config)
        with patch.object(Queue, "_start_worker", slow_load), TestClient(app) as client:
            self.assertTrue(app.state.queue.ready.wait(5))
            payload = {"submission_key": uuid.uuid4().hex, "title": "HTTP確認", "style": "__TEST_SLOW__",
                       "lyrics": "[Verse]\n確認用の歌詞", "candidate_count": 2}
            response = client.post("/api/jobs", json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            until = time.monotonic() + 5
            while client.get("/api/health").json()["worker_state"] != "loading" and time.monotonic() < until:
                time.sleep(.02)
            self.assertEqual(client.get("/api/health").json()["worker_state"], "loading")
            self.assertEqual(client.get("/").status_code, 200)
            gate.set()
            observed = set()
            until = time.monotonic() + 12
            while time.monotonic() < until:
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                observed.add(health.json()["worker_state"])
                self.assertEqual(client.get("/").status_code, 200)
                rows = client.get("/api/jobs").json()["jobs"]
                if all(j["status"] == "completed" for j in rows):
                    break
                time.sleep(.05)
            self.assertTrue(all(j["status"] == "completed" for j in rows))
            self.assertIn("generating", observed)
            for path in ("/static/app.js", "/static/style.css", "/static/mark.svg"):
                self.assertEqual(client.get(path).status_code, 200)
            self.assertEqual(client.post("/api/queue/pause", json={}, headers={"Origin": "https://elsewhere.invalid"}).status_code, 403)
            client.post("/api/jobs", json={**payload, "submission_key": uuid.uuid4().hex, "style": "__TEST_CRASH__", "candidate_count": 1})
            until = time.monotonic() + 5
            while client.get("/api/health").json()["worker_state"] != "error" and time.monotonic() < until:
                time.sleep(.03)
            self.assertEqual(client.get("/api/health").json()["worker_state"], "error")
            self.assertEqual(client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
