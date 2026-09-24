from __future__ import annotations

from collections import deque
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback

from .config import ROOT
from .covers import Covers
from .storage import Store, now, song_request, write_json
from .motif_queue import MotifQueue


class WorkerFailure(Exception):
    def __init__(self, code, summary, *, interrupted=False):
        super().__init__(summary)
        self.code, self.summary, self.interrupted = code, summary, interrupted


class Queue:
    def __init__(self, config):
        self.config = config
        self.store = Store(config.data_dir)
        self.covers = Covers(config, self.store)
        self.motifs = MotifQueue(self)
        self.lock_file = None
        self.process = None
        self.thread = None
        self.stderr_thread = None
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.control = threading.RLock()
        self.log_lock = threading.Lock()
        self.active_id = None
        self.worker_info = {}
        self.logs = deque(maxlen=100)
        self.ready = threading.Event()
        self.phase = "starting"
        self.worker_state = "not_started"
        self.last_error = None

    def start(self):
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = (self.config.data_dir / "studio.lock").open("a+")
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("同じデータ保存先のアプリが既に起動しています") from None
        try:
            self.thread = threading.Thread(target=self._bootstrap, name="studio-queue", daemon=True)
            self.thread.start()
        except BaseException:
            self.lock_file.close()
            self.lock_file = None
            raise

    def _bootstrap(self):
        try:
            self.store.initialize()
            # MIDI operation tables are created by initialize(); recover only
            # after that point so app/TestClient startup cannot race SQLite
            # schema creation.
            self.store.recover_midi_tasks()
            self.phase = "recovering"
            self.store.recover()
            self.phase = "ready"
            self.ready.set()
            self._loop()
        except Exception:
            self.last_error = "保存データの初期化に失敗しました。ログを確認してください"
            self.phase = "error"
            self.log(traceback.format_exc())

    def health(self):
        # No SQLite, filesystem access, pipe reads, joins or logging locks.
        proc = self.process
        state = self.worker_state
        if proc is not None and proc.poll() is not None:
            state = "error"
        return {"status": "ok", "service": "YuE2 Local Studio", "pid": os.getpid(),
                "queue_state": self.phase, "ready": self.ready.is_set() and self.phase == "ready",
                "worker_state": state, "active_id": self.active_id,
                "error": self.last_error, "engine": self.config.engine}

    def log(self, text, job_id=None):
        line = f"{now()} {text.rstrip()}\n"
        with self.log_lock:
            self.logs.append(line.rstrip())
            try:
                with (self.config.data_dir / "logs" / "worker.log").open("a", encoding="utf-8") as f:
                    f.write(line)
                if job_id:
                    with (self.config.data_dir / "logs" / f"{job_id}.log").open("a", encoding="utf-8") as f:
                        f.write(line)
            except OSError:
                # Even a full disk must not stop draining the child's stderr pipe.
                pass

    def _stderr(self, proc):
        for line in iter(proc.stderr.readline, ""):
            self.log(line, self.active_id)

    def _send(self, data):
        self.process.stdin.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def _read(self):
        line = self.process.stdout.readline()
        if not line:
            raise WorkerFailure("worker_exited", "生成ワーカーが異常終了しました。ログを確認してキューを再開してください", interrupted=True)
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str) or "job_id" not in event:
                raise ValueError("Invalid worker event")
            return event
        except ValueError as exc:
            self.log(f"通信エラー: {exc}: {line[:200]}", self.active_id)
            raise WorkerFailure("worker_protocol", "ワーカーから不正な応答を受信しました", interrupted=True) from exc

    def _start_worker(self):
        if self.process is not None:
            if self.process.poll() is not None:
                raise WorkerFailure("worker_exited", "待機中のワーカーが終了しました。キューを再開してください", interrupted=True)
            return
        self.worker_state = "loading"
        python = self.config.python if self.config.engine == "yue2" else sys.executable
        script = ROOT / ("worker.py" if self.config.engine == "yue2" else "tests/fake_worker.py")
        cache = self.config.data_dir / "runtime-cache"
        cache.mkdir(exist_ok=True)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   CUDA_CACHE_PATH=str(cache / "cuda"), TRITON_CACHE_DIR=str(cache / "triton"))
        self.process = subprocess.Popen([python, "-B", "-u", str(script)], cwd=ROOT, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1,
                                        start_new_session=True)
        self.stderr_thread = threading.Thread(target=self._stderr, args=(self.process,), daemon=True)
        self.stderr_thread.start()
        self._send({"type": "init", "job_id": None, "runtime": self.config.runtime()})
        event = self._read()
        if event["type"] == "error":
            raise WorkerFailure(event["code"], event["summary"])
        if event["type"] != "ready":
            raise WorkerFailure("worker_protocol", "ワーカーの初期化応答が不正です", interrupted=True)
        self.worker_info = event
        self.worker_state = "ready"
        self.last_error = None
        self.log(f"ワーカー準備完了: PID={event['pid']}, pipeline_loads={event['pipeline_loads']}", self.active_id)

    def _terminate(self):
        proc = self.process
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
        if self.stderr_thread:
            self.stderr_thread.join(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
        self.process = None

    def _run(self, job):
        self.active_id = job["id"]
        try:
            if job["runtime"] != self.config.runtime():
                raise WorkerFailure("config_changed", "登録時と現在のモデル設定が異なります。元の設定で再起動してください")
            directory = self.store.job_dir(job["id"])
            directory.mkdir(exist_ok=False)
            write_json(directory / "conditions.json", {"studio": "YuE2 Local Studio", "job": job,
                                                       "generation_request": song_request(job)})
            if job.get("task") == "transcribe":
                self._transcribe(job, directory)
                return
            if job.get("task") in ("motif_clip", "motif_transcribe", "motif_plan", "motif_render"):
                if job["task"] == "motif_clip":
                    self.motifs.clip(job, directory)
                elif job["task"] == "motif_transcribe":
                    self.motifs.transcribe(job, directory)
                elif job["task"] == "motif_plan":
                    self.motifs.plan(job, directory)
                else:
                    self.motifs.render(job, directory)
                return
            if job.get("cover"):
                snapshot = job["cover"]
                write_json(directory / "cover.json", snapshot)
                for name, key in (("original.abc", "original_abc"), ("edited.abc", "edited_abc"), ("used.abc", "used_abc")):
                    (directory / name).write_bytes(snapshot[key].encode("utf-8"))
            self._start_worker()
            self.worker_state = "generating"
            self.log(f"生成開始: {job['candidate_index']}/{job['candidate_count']} seed={job['seed']}", job["id"])
            self._send({"type": "generate", "job_id": job["id"], "request": song_request(job),
                        "output": str(directory / "artifacts")})
            while not self.stopping.is_set():
                event = self._read()
                if event["job_id"] != job["id"]:
                    raise WorkerFailure("worker_protocol", "ワーカーの曲IDが一致しません", interrupted=True)
                if event["type"] == "completed":
                    receipt = self.store.inspect_result(job)
                    if not receipt:
                        raise WorkerFailure("save_failed", "完了応答に対応する成果物がありません")
                    self.store.finish(job["id"], **receipt)
                    self.worker_state = "ready"
                    self.log(f"生成完了: {receipt['status']} {receipt['duration']:.2f}秒", job["id"])
                    return
                if event["type"] == "error":
                    raise WorkerFailure(event["code"], event["summary"], interrupted=event["code"] == "interrupted")
                if event["type"] != "started":
                    raise WorkerFailure("worker_protocol", "不明なワーカーイベントです", interrupted=True)
            raise WorkerFailure("server_stopped", "サーバー終了により生成を中断しました", interrupted=True)
        except Exception as exc:
            self.log(traceback.format_exc(), job["id"])
            failure = exc if isinstance(exc, WorkerFailure) else WorkerFailure(
                "save_failed" if isinstance(exc, (OSError, ValueError)) else "worker_error",
                "保存処理またはワーカー処理に失敗しました。詳細ログを確認してください")
            self.store.pause(True, failure.summary)
            # Pause before publishing the terminal job state.  API clients
            # may observe the failed row immediately after finish(); making
            # the safety state visible first avoids a transient false
            # "queue running" result and prevents another claim race.
            self.store.finish(job["id"], "interrupted" if failure.interrupted or self.stopping.is_set() else "failed",
                              error_code=failure.code, error=failure.summary)
            self.worker_state = "error"
            self.last_error = failure.summary
            self._terminate()
        finally:
            self.active_id = None

    def _transcribe(self, job, directory):
        # The same single queue owns both processes. Reap YuE before loading SheetSage.
        self._terminate()
        settings = self.covers.transcription_config()
        if settings != job["cover"]["transcription"]:
            raise WorkerFailure("config_changed", "採譜環境が登録時から変わりました。再登録してください")
        data = self.covers.get(job["cover_id"])
        audio = self.covers.file(data, "source")
        self.worker_state = "transcribing"
        self.worker_info = {"kind": "sheetsage2", "settings": settings}
        self.log("YuEワーカー終了・GPU解放後、SheetSage2採譜を開始", job["id"])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        self.process = subprocess.Popen([settings["python"], "-B", "-u", str(ROOT / "transcribe_worker.py")],
                                        cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, start_new_session=True)
        self.stderr_thread = threading.Thread(target=self._stderr, args=(self.process,), daemon=True)
        self.stderr_thread.start()
        self._send({"job_id": job["id"], "settings": settings, "audio": str(audio), "output": str(directory / "transcription")})
        event = self._read()
        if event["job_id"] != job["id"]:
            raise WorkerFailure("worker_protocol", "採譜ワーカーのジョブIDが不一致です")
        if event["type"] == "error":
            raise WorkerFailure("transcription_failed", event["summary"])
        if event["type"] != "completed":
            raise WorkerFailure("worker_protocol", "採譜ワーカーの応答が不正です")
        try:
            code = self.process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise WorkerFailure("transcription_exit", "採譜ワーカーが終了せずGPUを解放できませんでした") from exc
        if code or self.stopping.is_set():
            raise WorkerFailure("transcription_exit", "採譜ワーカーが正常終了しませんでした")
        self._terminate()
        abc = (directory / "transcription/score.abc").read_bytes().decode("utf-8")
        self.covers.prepare(abc, "melody")
        with self.covers.lock:
            data = self.covers.get(job["cover_id"])
            original_name = f"original-{job['id']}.abc"
            target = self.covers.directory(data["id"]) / original_name
            with target.open("xb") as out:
                out.write(abc.encode())
            data.update(original_abc=abc, original_name=original_name, abc=abc, warnings=event.get("warnings", []),
                        transcription={"job_id": job["id"], "settings": settings}, revision=data["revision"] + 1)
            self.covers.save(data)
        self.store.finish(job["id"], "awaiting_review")
        self.worker_state = "not_started"
        self.worker_info = {}
        self.log("採譜完了・GPU解放済み。ABCの確認待ち（自動生成はしません）", job["id"])

    def _loop(self):
        try:
            while not self.stopping.is_set():
                with self.control:
                    if self.process is not None and self.process.poll() is not None:
                        self.worker_state = "error"
                        self.last_error = "待機中のワーカーが終了しました"
                        self.store.pause(True, "待機中のワーカーが終了しました。キュー再開で再起動できます")
                        self._terminate()
                    job = self.store.claim()
                    if job:
                        self.active_id = job["id"]
                if job:
                    self._run(job)
                else:
                    self.wake.wait(0.3)
                    self.wake.clear()
        except Exception:
            self.phase = "error"
            self.last_error = "キュー管理処理が停止しました"
            self.log(traceback.format_exc(), self.active_id)
            self.store.pause(True, "キュー管理処理が停止しました。ログを確認してアプリを再起動してください")
        finally:
            self._terminate()

    def resume(self):
        with self.control:
            if not self.thread or not self.thread.is_alive():
                raise ValueError("キュー管理処理が停止しています。アプリを再起動してください")
            if self.active_id:
                raise ValueError("実行中の曲が終わってから再開してください")
            self._terminate()
            self.worker_state = "not_started"
            self.last_error = None
            self.store.pause(False)
            self.wake.set()

    def pause(self):
        with self.control:
            self.store.pause(True, "キューを一時停止しています。実行中の曲は最後まで生成します")

    def status(self):
        with self.log_lock:
            logs = list(self.logs)
        return {**self.store.queue_state(), "active_id": self.active_id,
                "worker": self.worker_info, "worker_alive": self.process is not None and self.process.poll() is None,
                "engine": self.config.engine, "logs": logs}

    def close(self):
        self.phase = "stopping"
        self.stopping.set()
        self.wake.set()
        if self.thread:
            # The worker can be created by the queue thread after close() has
            # started. Re-read self.process while joining; capturing it once
            # allowed a late worker to block _read() beyond TestClient shutdown.
            deadline = time.monotonic() + 10
            while self.thread.is_alive() and time.monotonic() < deadline:
                proc = self.process
                if proc and proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                self.thread.join(timeout=0.2)
            proc = self.process
            if self.thread.is_alive() and proc and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.thread.join(timeout=2)
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None
