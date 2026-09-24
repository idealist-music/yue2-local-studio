from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {"completed", "truncated", "failed", "interrupted", "cancelled", "reviewed"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
FILES = {"flac": ("audio.flac", "audio/flac"), "wav": ("preview.wav", "audio/wav"),
         "abc": ("score.abc", "text/plain; charset=utf-8"),
         "request": ("request.json", "application/json"),
         "config": ("config.json", "application/json"), "result": ("result.json", "application/json")}


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def write_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def song_request(job):
    req = {"style": job["style"], "lyrics": job["lyrics"], "cot": job["cot"], "seed": int(job["seed"])}
    if job["cfg_scale"] is not None:
        req["cfg_scale"] = job["cfg_scale"]
    if job.get("abc") is not None:
        req["abc"] = job["abc"]
    return req


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "studio.sqlite3"

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        if self.path.is_file() and self.path.stat().st_size:
            backup_dir = self.root / "backups"
            backup_dir.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"midi-schema-{stamp}.sqlite3"
            source_db = sqlite3.connect(self.path)
            target_db = sqlite3.connect(backup_path)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
                source_db.close()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS submissions(
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, group_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, group_id TEXT NOT NULL, candidate_index INTEGER NOT NULL,
                    candidate_count INTEGER NOT NULL, title TEXT NOT NULL, style TEXT NOT NULL,
                    lyrics TEXT NOT NULL, cot TEXT NOT NULL, seed TEXT NOT NULL, cfg_scale REAL,
                    source_id TEXT, abc TEXT, runtime TEXT NOT NULL, engine TEXT NOT NULL,
                    status TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    duration REAL, truncated TEXT, error_code TEXT, error TEXT);
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at, candidate_index);
                INSERT OR IGNORE INTO meta VALUES ('paused','false');
                INSERT OR IGNORE INTO meta VALUES ('pause_reason','');
                CREATE TABLE IF NOT EXISTS covers(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS motifs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS score_versions(
                    id TEXT PRIMARY KEY, song_id TEXT NOT NULL, parent_version_id TEXT,
                    source_job_id TEXT, created_at TEXT NOT NULL, abc_sha256 TEXT NOT NULL,
                    abc_path TEXT NOT NULL, conditions_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL, edit_summary_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready');
                CREATE INDEX IF NOT EXISTS score_versions_song ON score_versions(song_id,created_at);
                CREATE TABLE IF NOT EXISTS score_heads(song_id TEXT PRIMARY KEY,current_version_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS midi_exports(
                    id TEXT PRIMARY KEY, source_version_id TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
                    submission_key TEXT, input_sha256 TEXT, updated_at TEXT NOT NULL,
                    error_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS midi_imports(
                    id TEXT PRIMARY KEY, upload_sha256 TEXT NOT NULL, source_export_id TEXT,
                    target_song_id TEXT, target_version_id TEXT, state TEXT NOT NULL,
                    selection_json TEXT NOT NULL, analysis_json TEXT NOT NULL,
                    result_version_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    error_json TEXT NOT NULL, submission_key TEXT);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
            export_columns = {r[1] for r in db.execute("PRAGMA table_info(midi_exports)")}
            for name, definition in (("state", "TEXT NOT NULL DEFAULT 'ready'"), ("submission_key", "TEXT"),
                                     ("input_sha256", "TEXT"), ("updated_at", "TEXT"), ("error_json", "TEXT NOT NULL DEFAULT '{}'")):
                if name not in export_columns:
                    db.execute(f"ALTER TABLE midi_exports ADD COLUMN {name} {definition}")
            db.execute("UPDATE midi_exports SET updated_at=created_at WHERE updated_at IS NULL")
            import_columns = {r[1] for r in db.execute("PRAGMA table_info(midi_imports)")}
            if "submission_key" not in import_columns:
                db.execute("ALTER TABLE midi_imports ADD COLUMN submission_key TEXT")
            for name, definition in (("task", "TEXT NOT NULL DEFAULT 'generate'"), ("cover_id", "TEXT"),
                                     ("cover", "TEXT"), ("motif_id", "TEXT"), ("motif", "TEXT"),
                                     ("score_version_id", "TEXT"), ("midi_import_id", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_cover ON jobs(cover_id,created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_motif ON jobs(motif_id,created_at)")
            columns = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
            if "score_version_id" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN score_version_id TEXT")
            if "midi_import_id" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN midi_import_id TEXT")

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        result["favorite"] = bool(result["favorite"])
        result["runtime"] = json.loads(result["runtime"])
        result["truncated"] = json.loads(result["truncated"] or "{}")
        result["cover"] = json.loads(result.get("cover") or "null")
        result["motif"] = json.loads(result.get("motif") or "null")
        return result

    def get(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM jobs ORDER BY created_at DESC, candidate_index")]

    def queue_state(self):
        with self.connect() as db:
            meta = dict(db.execute("SELECT key,value FROM meta"))
            counts = dict(db.execute("SELECT status,count(*) FROM jobs GROUP BY status"))
        return {"paused": meta["paused"] == "true", "reason": meta["pause_reason"], "counts": counts}

    def pause(self, paused, reason=""):
        with self.connect() as db:
            db.execute("UPDATE meta SET value=? WHERE key='paused'", ("true" if paused else "false",))
            db.execute("UPDATE meta SET value=? WHERE key='pause_reason'", (reason,))

    def submit(self, key, fingerprint, spec, runtime, seeds):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM submissions WHERE key=?", (key,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("同じ送信キーで条件が変更されています。新しい送信として実行してください")
                rows = db.execute("SELECT * FROM jobs WHERE group_id=? ORDER BY candidate_index", (old["group_id"],))
                return [self.decode(r) for r in rows], True
            group = uuid.uuid4().hex
            created = now()
            for index, seed in enumerate(seeds, 1):
                cover = spec.get("cover")
                if cover and spec.get("task", "generate") == "generate":
                    cover = {**cover, "generation_request": song_request({**spec, "seed": seed, "cfg_scale": spec.get("cfg_scale")})}
                db.execute("""INSERT INTO jobs(id,group_id,candidate_index,candidate_count,title,style,lyrics,
                    cot,seed,cfg_scale,source_id,abc,runtime,engine,status,created_at,task,cover_id,cover,motif_id,motif,score_version_id,midi_import_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uuid.uuid4().hex, group, index, len(seeds), spec["title"], spec["style"], spec["lyrics"],
                     spec["cot"], str(seed), spec.get("cfg_scale"), spec.get("source_id"), spec.get("abc"),
                     dumps(runtime), runtime["engine"], "queued", created, spec.get("task", "generate"),
                     spec.get("cover_id"), dumps(cover), spec.get("motif_id"), dumps(spec.get("motif")),
                     spec.get("score_version_id"), spec.get("midi_import_id")))
            db.execute("INSERT INTO submissions VALUES(?,?,?)", (key, fingerprint, group))
            return [self.decode(r) for r in db.execute("SELECT * FROM jobs WHERE group_id=? ORDER BY candidate_index", (group,))], False

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()[0] == "true":
                return None
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,candidate_index,rowid LIMIT 1").fetchone()
            if not row:
                return None
            stage_status = "transcribing" if row["task"] in ("transcribe", "motif_transcribe") else ("planning" if row["task"] == "motif_plan" else ("clipping" if row["task"] == "motif_clip" else "running"))
            db.execute("UPDATE jobs SET status=?,started_at=? WHERE id=?", (stage_status, now(), row["id"]))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def finish(self, job_id, status, *, duration=None, truncated=None, error_code=None, error=None):
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status=?,finished_at=?,duration=?,truncated=?,error_code=?,error=?
                          WHERE id=?""", (status, now(), duration, dumps(truncated or {}), error_code, error, job_id))

    def cancel(self, job_id):
        with self.connect() as db:
            return db.execute("UPDATE jobs SET status='cancelled',finished_at=? WHERE id=? AND status='queued'",
                              (now(), job_id)).rowcount == 1

    def favorite(self, job_id, value):
        with self.connect() as db:
            return db.execute("UPDATE jobs SET favorite=? WHERE id=?", (int(value), job_id)).rowcount == 1

    def job_dir(self, job_id):
        if not ID_RE.fullmatch(job_id):
            raise ValueError("不正な曲IDです")
        path = self.root / "jobs" / job_id
        if path.is_symlink() or path.resolve().parent != (self.root / "jobs").resolve():
            raise ValueError("保存先が不正です")
        return path

    def artifact(self, job_id, kind):
        directory = self.job_dir(job_id)
        if kind == "conditions":
            path, mime = directory / "conditions.json", "application/json"
        elif kind in FILES:
            filename, mime = FILES[kind]
            path = directory / "artifacts" / filename
        else:
            raise ValueError("不明な成果物です")
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise FileNotFoundError("成果物がありません")
        return path, mime

    def inspect_result(self, job):
        """Reconcile a complete native receipt, including hashes and exact request."""
        directory = self.job_dir(job["id"]) / "artifacts"
        if directory.is_symlink():
            raise ValueError("成果物ディレクトリがシンボリックリンクです")
        manifest = directory / "result.json"
        if not manifest.is_file():
            return None
        if manifest.is_symlink():
            raise ValueError("result.json がシンボリックリンクです")
        result = json.loads(manifest.read_text(encoding="utf-8"))
        if result.get("status") != "complete":
            return None
        artifacts = result.get("artifacts", {})
        audio_name = "preview.wav" if job["engine"] == "test" else "audio.flac"
        required = {audio_name, "request.json", "config.json"}
        if job["engine"] != "test":
            required |= {"latent.npy", "semantic.npy", "prefix.npy", "plan.json", "plan_manifest.json", "abc_tokens.npy"}
            if job["cot"] != "off":
                required.add("score.abc")
        if not required <= artifacts.keys():
            raise ValueError("成果物の一覧が不完全です")
        for name, info in artifacts.items():
            p = directory / name
            if Path(name).name != name or p.is_symlink() or not p.is_file() or p.stat().st_size != info["bytes"]:
                raise ValueError(f"成果物が欠落または破損しています: {name}")
            digest = hashlib.sha256()
            with p.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != info["sha256"]:
                raise ValueError(f"成果物のハッシュが一致しません: {name}")
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        expected = song_request(job)
        if any(request.get(k) != v for k, v in expected.items()):
            raise ValueError("保存済み生成条件がキューの条件と一致しません")
        for key in ("abc", "cfg_scale"):
            if key not in expected and request.get(key) is not None:
                raise ValueError("保存済み生成条件に未指定の設定があります")
        duration = result["audio_seconds"]
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("音声の長さが不正です")
        flags = result.get("truncated")
        if not isinstance(flags, dict) or not {"abc", "semantic"} <= flags.keys() or any(type(v) is not bool for v in flags.values()):
            raise ValueError("打ち切り状態が不正です")
        return {"duration": duration, "truncated": flags,
                "status": "truncated" if any(flags.values()) else "completed"}

    def recover(self):
        pending = False
        for job in self.list():
            status = job["status"]
            if job.get("task") in ("transcribe", "motif_transcribe", "motif_clip", "motif_plan"):
                if status in ("transcribing", "clipping", "planning"):
                    self.finish(job["id"], "interrupted", error_code="server_stopped", error="採譜中にサーバーが終了しました。採譜を再実行してください")
                pending = pending or status in ("transcribing", "clipping", "planning", "queued")
                continue
            if status in ("running", "queued", "interrupted"):
                pending = pending or status in ("running", "queued")
                try:
                    receipt = self.inspect_result(job)
                    if receipt:
                        self.finish(job["id"], **receipt)
                        continue
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.finish(job["id"], "interrupted", error_code="artifact_error", error=str(exc))
                    continue
                output = self.job_dir(job["id"]) / "artifacts"
                if status == "running" or (status == "queued" and output.exists()):
                    self.finish(job["id"], "interrupted", error_code="server_stopped",
                                error="サーバーまたはワーカーが終了しました。新しいジョブとして再生成できます")
        if pending:
            self.pause(True, "前回の未実行キューを保持しています。内容を確認してキューを再開してください")

    def get_motif(self, motif_id):
        if not ID_RE.fullmatch(motif_id):
            raise ValueError("不正なMotif IDです")
        with self.connect() as db:
            row = db.execute("SELECT data FROM motifs WHERE id=?", (motif_id,)).fetchone()
        if not row:
            raise ValueError("Motifプロジェクトが見つかりません")
        return json.loads(row[0])

    def save_motif(self, data):
        with self.connect() as db:
            db.execute("INSERT INTO motifs(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       (data["id"], dumps(data)))

    def list_motifs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM motifs ORDER BY rowid DESC")]

    def score_version_dir(self, version_id):
        if not ID_RE.fullmatch(version_id):
            raise ValueError("不正な譜面版IDです")
        root = self.root / "score_versions"
        root.mkdir(exist_ok=True)
        path = root / version_id
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise ValueError("譜面保存先が不正です")
        return path

    def create_score_version(self, *, song_id, abc, conditions, validation, edit_summary=None,
                             parent_version_id=None, source_job_id=None, expected_head=None):
        version_id = uuid.uuid4().hex
        directory = self.score_version_dir(version_id)
        directory.mkdir()
        path = directory / "score.abc"
        write_bytes_atomic(path, abc.encode("utf-8"))
        digest = hashlib.sha256(abc.encode("utf-8")).hexdigest()
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if expected_head is not None:
                    row = db.execute("SELECT current_version_id FROM score_heads WHERE song_id=?", (song_id,)).fetchone()
                    if not row or row[0] != expected_head:
                        raise ValueError("譜面版が更新されています。最新の版を読み直してください")
                db.execute("INSERT INTO score_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (version_id, song_id, parent_version_id, source_job_id, now(), digest,
                            str(path.relative_to(self.root)), dumps(conditions), dumps(validation),
                            dumps(edit_summary or {}), "ready"))
                if expected_head is None:
                    db.execute("INSERT INTO score_heads(song_id,current_version_id) VALUES(?,?) ON CONFLICT(song_id) DO UPDATE SET current_version_id=excluded.current_version_id",
                               (song_id, version_id))
                else:
                    changed = db.execute("UPDATE score_heads SET current_version_id=? WHERE song_id=? AND current_version_id=?",
                                         (version_id, song_id, expected_head)).rowcount
                    if changed != 1:
                        raise ValueError("譜面版が更新されています。最新の版を読み直してください")
        except Exception:
            try:
                path.unlink()
                path.parent.rmdir()
            except OSError:
                pass
            raise
        return self.get_score_version(version_id)

    def get_score_version(self, version_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM score_versions WHERE id=?", (version_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        path = self.root / result["abc_path"]
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("譜面スナップショットがありません")
        abc = path.read_text(encoding="utf-8")
        if hashlib.sha256(abc.encode()).hexdigest() != result["abc_sha256"]:
            raise ValueError("譜面スナップショットのハッシュが一致しません")
        result.update(abc=abc, conditions=json.loads(result.pop("conditions_json")),
                      validation=json.loads(result.pop("validation_json")),
                      edit_summary=json.loads(result.pop("edit_summary_json")))
        return result

    def list_score_versions(self, song_id):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM score_versions WHERE song_id=? ORDER BY created_at DESC", (song_id,))]
        return [self.get_score_version(version_id) for version_id in ids]

    def create_midi_export(self, export_id, version_id, metadata, *, state="queued", submission_key=None, input_sha256=None):
        with self.connect() as db:
            timestamp = now()
            db.execute("INSERT INTO midi_exports(id,source_version_id,metadata_json,created_at,state,submission_key,input_sha256,updated_at,error_json) VALUES(?,?,?,?,?,?,?,?,?)",
                       (export_id, version_id, dumps(metadata), timestamp, state, submission_key, input_sha256, timestamp, dumps({})))

    def find_midi_export(self, version_id, submission_key, input_sha256):
        if not submission_key:
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM midi_exports WHERE source_version_id=? AND submission_key=? AND input_sha256=? ORDER BY created_at DESC LIMIT 1",
                             (version_id, submission_key, input_sha256)).fetchone()
        return self._decode_midi_export(row)

    def update_midi_export(self, export_id, **values):
        fields = {"metadata_json", "state", "error_json"}
        values = {k: (dumps(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in values.items() if k in fields}
        values["updated_at"] = now()
        with self.connect() as db:
            db.execute(f"UPDATE midi_exports SET {','.join(f'{k}=?' for k in values)} WHERE id=?", (*values.values(), export_id))

    @staticmethod
    def _decode_midi_export(row):
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        result["error"] = json.loads(result.pop("error_json") or "{}")
        return result

    def get_midi_export(self, export_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM midi_exports WHERE id=?", (export_id,)).fetchone()
        if not row:
            return None
        return self._decode_midi_export(row)

    def recover_midi_tasks(self):
        """Mark CPU operations interrupted by process restart without touching GPU jobs."""
        timestamp = now()
        with self.connect() as db:
            db.execute("UPDATE midi_exports SET state='interrupted',updated_at=?,error_json=? WHERE state IN ('queued','converting')",
                       (timestamp, dumps({"code": "process_interrupted"})))
            db.execute("UPDATE midi_imports SET state='interrupted',updated_at=?,error_json=? WHERE state IN ('uploaded','analyzing')",
                       (timestamp, dumps({"code": "process_interrupted"})))

    def create_midi_import(self, import_id, upload_sha256, *, source_export_id=None, state="uploaded", selection=None, analysis=None, submission_key=None):
        timestamp = now()
        with self.connect() as db:
            db.execute("INSERT INTO midi_imports(id,upload_sha256,source_export_id,target_song_id,target_version_id,state,selection_json,analysis_json,result_version_id,created_at,updated_at,error_json,submission_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (import_id, upload_sha256, source_export_id, None, None, state,
                        dumps(selection or {}), dumps(analysis or {}), None, timestamp, timestamp, dumps({}), submission_key))

    def find_midi_import(self, upload_sha256, submission_key):
        if not submission_key:
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM midi_imports WHERE upload_sha256=? AND submission_key=? ORDER BY created_at DESC LIMIT 1",
                             (upload_sha256, submission_key)).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("selection_json", "analysis_json", "error_json"):
            result[key[:-5]] = json.loads(result.pop(key))
        return result

    def get_midi_import(self, import_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM midi_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("selection_json", "analysis_json", "error_json"):
            result[key[:-5]] = json.loads(result.pop(key))
        return result

    def update_midi_import(self, import_id, **values):
        fields = {"state", "source_export_id", "target_song_id", "target_version_id", "selection_json", "analysis_json", "result_version_id", "error_json"}
        values = {k: (dumps(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in values.items() if k in fields}
        values["updated_at"] = now()
        assignments = ",".join(f"{k}=?" for k in values)
        with self.connect() as db:
            db.execute(f"UPDATE midi_imports SET {assignments} WHERE id=?", (*values.values(), import_id))


def write_bytes_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
