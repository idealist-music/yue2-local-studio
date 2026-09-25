"""Deletion API and storage safety checks; all data lives in a temporary directory."""
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient

from studio.app import create_app
from studio.config import load_config


class SongDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio-delete-")
        self.config = replace(load_config(), data_dir=Path(self.temp.name), engine="test",
                              allowed_hosts=("testserver", "localhost", "127.0.0.1"))
        self.app = create_app(self.config)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.assertTrue(self.app.state.queue.ready.wait(5))
        self.queue = self.app.state.queue
        self.store = self.queue.store
        self.store.pause(True)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()

    def add_job(self, *, status="completed", title="Temporary song"):
        spec = {"title": title, "style": "test", "lyrics": "[Verse]\ntest", "cot": "full",
                "cfg_scale": None, "source_id": None, "abc": None}
        jobs, _ = self.store.submit(uuid.uuid4().hex, "test", spec, self.config.runtime(), [42])
        job = jobs[0]
        if status != "queued":
            self.store.finish(job["id"], status, error_code="test_error" if status == "failed" else None,
                              error="temporary test failure" if status == "failed" else None)
        folder = self.store.job_dir(job["id"])
        folder.mkdir(exist_ok=True)
        (folder / "conditions.json").write_text("{}", encoding="utf-8")
        (self.config.data_dir / "logs" / f"{job['id']}.log").write_text("temporary log", encoding="utf-8")
        return job

    def test_preview_then_cancel_leaves_song_untouched(self):
        job = self.add_job(title="Keep on cancel")
        preview = self.client.get(f"/api/jobs/{job['id']}/deletion")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["title"], "Keep on cancel")
        # Cancel is a client-only dialog operation: no DELETE request is sent.
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").status_code, 200)
        self.assertTrue(self.store.job_dir(job["id"]).exists())
        self.assertEqual(self.client.get("/api/jobs").json()["jobs"][0]["id"], job["id"])

    def test_failed_job_and_owned_records_files_are_deleted(self):
        job = self.add_job(status="failed", title="Failed temporary generation")
        version = self.store.create_score_version(song_id=job["id"], abc="X:1\nK:C\nC D E F|\n",
                                                  conditions={}, validation={})
        export_id = uuid.uuid4().hex
        self.store.create_midi_export(export_id, version["id"], {}, state="ready")
        export_dir = self.config.data_dir / "midi" / "exports" / export_id
        export_dir.mkdir(parents=True)
        (export_dir / "export.mid").write_bytes(b"temporary")
        import_id = uuid.uuid4().hex
        self.store.create_midi_import(import_id, hashlib.sha256(b"temporary").hexdigest(), state="saved")
        with self.store.connect() as db:
            db.execute("UPDATE midi_imports SET target_song_id=? WHERE id=?", (job["id"], import_id))
        import_dir = self.config.data_dir / "midi" / "imports" / import_id
        import_dir.mkdir(parents=True)
        (import_dir / "input.mid").write_bytes(b"temporary")
        shared_log = self.config.data_dir / "logs" / "worker.log"
        shared_log.write_text("shared", encoding="utf-8")

        preview = self.client.get(f"/api/jobs/{job['id']}/deletion")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["item_kind"], "job")
        self.assertEqual((preview.json()["score_versions"], preview.json()["midi_exports"], preview.json()["midi_imports"]), (1, 1, 1))
        response = self.client.delete(f"/api/jobs/{job['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}").status_code, 404)
        self.assertFalse(self.store.job_dir(job["id"]).exists())
        self.assertFalse((self.config.data_dir / "logs" / f"{job['id']}.log").exists())
        self.assertFalse(version["id"] and (self.config.data_dir / "score_versions" / version["id"]).exists())
        self.assertFalse(export_dir.exists())
        self.assertFalse(import_dir.exists())
        self.assertTrue(shared_log.exists())
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM score_versions WHERE song_id=?", (job["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM midi_exports WHERE id=?", (export_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM midi_imports WHERE id=?", (import_id,)).fetchone()[0], 0)

    def test_queued_and_active_jobs_are_refused(self):
        queued = self.add_job(status="queued", title="Queued")
        self.assertEqual(self.client.get(f"/api/jobs/{queued['id']}/deletion").status_code, 409)
        self.assertEqual(self.client.delete(f"/api/jobs/{queued['id']}").status_code, 409)
        self.assertIsNotNone(self.store.get(queued["id"]))
        self.assertTrue(self.store.job_dir(queued["id"]).exists())

        active = self.add_job(status="completed", title="Active")
        with self.queue.control:
            self.queue.active_id = active["id"]
        try:
            self.assertEqual(self.client.get(f"/api/jobs/{active['id']}/deletion").status_code, 409)
            self.assertEqual(self.client.delete(f"/api/jobs/{active['id']}").status_code, 409)
            self.assertIsNotNone(self.store.get(active["id"]))
        finally:
            with self.queue.control:
                self.queue.active_id = None

    def test_shared_score_reference_and_cover_motif_are_preserved(self):
        original = self.add_job(title="Original")
        other = self.add_job(title="Other")
        version = self.store.create_score_version(song_id=original["id"], abc="X:1\nK:C\nC D E F|\n",
                                                  conditions={}, validation={})
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET score_version_id=? WHERE id=?", (version["id"], other["id"]))
        cover = self.queue.covers.create(source=original, abc="X:1\nK:C\nC D E F|\n")
        motif_id = uuid.uuid4().hex
        motif_dir = self.config.data_dir / "motifs" / motif_id
        motif_dir.mkdir(parents=True)
        (motif_dir / "source.wav").write_bytes(b"user source")
        self.store.save_motif({"id": motif_id, "source_id": original["id"]})

        blocked = self.client.delete(f"/api/jobs/{original['id']}")
        self.assertEqual(blocked.status_code, 409)
        self.assertIsNotNone(self.store.get(original["id"]))
        self.assertTrue((self.config.data_dir / "covers" / cover["id"] / "original.abc").exists())
        self.assertTrue((motif_dir / "source.wav").exists())
        self.assertIsNotNone(self.store.get_score_version(version["id"]))

    def test_partial_filesystem_failure_rolls_back_database_and_files(self):
        job = self.add_job(title="Rollback")
        log_path = self.config.data_dir / "logs" / f"{job['id']}.log"
        from pathlib import Path as ConcretePath
        original_rename = ConcretePath.rename
        def fail_log_rename(path, target):
            if path == log_path:
                raise OSError("simulated filesystem error")
            return original_rename(path, target)
        with patch.object(ConcretePath, "rename", fail_log_rename):
            response = self.client.delete(f"/api/jobs/{job['id']}")
        self.assertEqual(response.status_code, 500, response.text)
        self.assertIsNotNone(self.store.get(job["id"]))
        self.assertTrue(self.store.job_dir(job["id"]).exists())
        self.assertTrue(log_path.exists())
        self.assertFalse((self.config.data_dir / ".deleting" / job["id"]).exists())


if __name__ == "__main__":
    unittest.main()
