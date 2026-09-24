"""GPU-free queue and persistence checks for YuE2 Local Studio."""
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
import uuid

from studio.config import Config, PIPELINE_DEFAULTS
from studio.queue import Queue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="yue2-studio-test-")
        self.config = Config(sys.executable, "test", "test", "cpu", dict(PIPELINE_DEFAULTS),
                             Path(self.temp.name), engine="test")
        self.queue = Queue(self.config)
        self.queue.start()
        self.assertTrue(self.queue.ready.wait(5))
        self.store = self.queue.store

    def tearDown(self):
        self.queue.close()
        self.temp.cleanup()

    def add(self, key, style="normal", count=1, seeds=None):
        spec = {"title": key, "style": style, "lyrics": "[Verse]\n保持する歌詞", "cot": "full",
                "cfg_scale": None, "source_id": None, "abc": None}
        return self.store.submit(key * 16, style, spec, self.config.runtime(),
                                 seeds or list(range(10, 10 + count)))[0]

    def wait_terminal(self, job_id, expected=None):
        for _ in range(200):
            job = self.store.get(job_id)
            if job["status"] not in {"queued", "running"}:
                if expected:
                    self.assertEqual(job["status"], expected)
                return job
            time.sleep(0.03)
        self.fail("ジョブが終了しませんでした")

    def test_candidates_are_serial_and_pipeline_is_reused(self):
        jobs = self.add("a", "__TEST_SLOW__", 3)
        self.queue.wake.set()
        running_max = 0
        for _ in range(300):
            rows = self.store.list()
            running_max = max(running_max, sum(row["status"] == "running" for row in rows))
            if all(row["status"] == "completed" for row in rows):
                break
            time.sleep(0.03)
        self.assertEqual(running_max, 1)
        self.assertEqual([self.store.get(row["id"])["status"] for row in jobs], ["completed"] * 3)
        pids = []
        for row in jobs:
            config = json.loads((self.store.job_dir(row["id"]) / "artifacts" / "config.json").read_text())
            pids.append(config["pid"])
            self.assertEqual(config["pipeline_loads"], 1)
        self.assertEqual(len(set(pids)), 1)

    def test_idempotency_and_waiting_cancel(self):
        spec = {"title": "same", "style": "normal", "lyrics": "保持", "cot": "full",
                "cfg_scale": None, "source_id": None, "abc": None}
        first, reused = self.store.submit("b" * 16, "same", spec, self.config.runtime(), [1, 2])
        again, reused_again = self.store.submit("b" * 16, "same", spec, self.config.runtime(), [1, 2])
        self.assertFalse(reused); self.assertTrue(reused_again)
        self.assertEqual([x["id"] for x in first], [x["id"] for x in again])
        self.assertTrue(self.store.cancel(first[0]["id"]))
        self.assertFalse(self.store.cancel(first[0]["id"]))
        self.queue.wake.set()
        self.wait_terminal(first[1]["id"])
        self.assertEqual(self.store.get(first[0]["id"])["status"], "cancelled")

    def test_worker_errors_and_truncation_remain_distinct(self):
        for style, status, code in (("__TEST_OOM__", "failed", "cuda_oom"),
                                    ("__TEST_SAVE_FAILURE__", "failed", "save_failed"),
                                    ("__TEST_TRUNCATED__", "truncated", None)):
            job = self.add(uuid.uuid4().hex[:8], style)[0]
            self.queue.wake.set()
            row = self.wait_terminal(job["id"], status)
            self.assertEqual(row["error_code"], code)
            self.assertEqual(row["lyrics"], "[Verse]\n保持する歌詞")
            if status == "failed":
                self.assertTrue(self.store.queue_state()["paused"])
                self.store.pause(False)

    def test_restart_marks_running_interrupted_and_keeps_queue(self):
        self.queue.pause()
        jobs = self.add("restart", count=2)
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (jobs[0]["id"],))
        self.queue.close()
        restored = Queue(self.config)
        restored.start()
        self.assertTrue(restored.ready.wait(5))
        try:
            self.assertEqual(restored.store.get(jobs[0]["id"])["status"], "interrupted")
            self.assertEqual(restored.store.get(jobs[1]["id"])["status"], "queued")
            self.assertTrue(restored.store.queue_state()["paused"])
        finally:
            restored.close()


if __name__ == "__main__":
    unittest.main()
