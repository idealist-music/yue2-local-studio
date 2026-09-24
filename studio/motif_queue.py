"""Motif stage handlers owned by the existing Queue manager thread."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from .motif_abc import analyze, integrate, validate
from .storage import now, write_json


class MotifQueue:
    def __init__(self, queue):
        self.queue = queue

    @property
    def store(self):
        return self.queue.store

    def _project(self, job):
        return self.store.get_motif(job["motif_id"])

    def _save(self, project):
        project["updated_at"] = now()
        self.store.save_motif(project)

    def _revision_dir(self, project):
        revision = str(project["revision"])
        path = self.store.root / "motifs" / project["id"] / "revisions" / revision
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clip(self, job, directory):
        project = self._project(job)
        source = self.store.root / "motifs" / project["id"] / "source" / project["source"]["filename"]
        interval = project["conditions"]
        start, end = float(interval["start"]), float(interval["end"])
        duration = float(project["source"]["duration"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration and end - start <= 60):
            raise ValueError("invalid_interval: 音源区間は0.1〜60秒、音源の範囲内で指定してください")
        target = self._revision_dir(project) / "source_clip.wav"
        command = ["/usr/bin/ffmpeg", "-nostdin", "-y", "-i", str(source), "-af",
                   f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS", "-c:a", "pcm_s16le", str(target)]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as exc:
            raise ValueError("ffmpeg_missing: FFmpegが見つかりません") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("ffmpeg_timeout: 音源の切り出しがタイムアウトしました") from exc
        if proc.returncode or not target.is_file() or target.stat().st_size == 0:
            raise ValueError("ffmpeg_failed: 音源区間の切り出しに失敗しました")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        project.setdefault("stage", {})["clip"] = {"job_id": job["id"], "status": "completed", "sha256": digest,
                                                      "filename": "source_clip.wav", "created_at": now()}
        self._save(project)
        self.store.finish(job["id"], "completed")

    def transcribe(self, job, directory):
        project = self._project(job)
        rev = self._revision_dir(project)
        clip = rev / "source_clip.wav"
        if not clip.is_file():
            raise ValueError("audio_invalid: 採譜対象のsource_clipがありません")
        settings = self.queue.covers.transcription_config()
        self.queue._terminate()
        self.queue.worker_state = "transcribing"
        self.queue.process = subprocess.Popen([settings["python"], "-B", "-u", str(self.queue.config.root if hasattr(self.queue.config, "root") else Path(__file__).parents[1] / "transcribe_worker.py")],
                                              cwd=Path(__file__).parents[1], env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1, start_new_session=True)
        self.queue.stderr_thread = __import__("threading").Thread(target=self.queue._stderr, args=(self.queue.process,), daemon=True)
        self.queue.stderr_thread.start()
        self.queue._send({"job_id": job["id"], "settings": settings, "audio": str(clip), "output": str(directory / "transcription")})
        event = self.queue._read()
        if event.get("type") == "error":
            raise ValueError(f"transcription_failed: {event.get('summary', '採譜に失敗しました')}")
        if event.get("type") != "completed":
            raise ValueError("worker_protocol: 採譜ワーカーの応答が不正です")
        if self.queue.process.wait(timeout=30) != 0:
            raise ValueError("transcription_failed: 採譜ワーカーが異常終了しました")
        self.queue._terminate()
        abc_path = directory / "transcription" / "score.abc"
        abc = abc_path.read_text(encoding="utf-8") if abc_path.is_file() else ""
        if not abc.strip():
            raise ValueError("transcription_empty: 採譜結果が空です")
        self.queue.covers.prepare(abc, "melody")
        motif_path = rev / "motif_score.abc"
        motif_path.write_text(abc, encoding="utf-8")
        analysis = analyze(abc, self.queue.covers, project.get("conditions", {}).get("lyrics", ""))
        project.setdefault("stage", {})["transcribe"] = {"job_id": job["id"], "status": "awaiting_review", "sha256": hashlib.sha256(abc.encode()).hexdigest(), "warnings": event.get("warnings", []), "analysis": analysis}
        self._save(project)
        self.store.finish(job["id"], "awaiting_review")
        self.queue.worker_state, self.queue.worker_info = "not_started", {}

    def plan(self, job, directory):
        project = self._project(job)
        rev = self._revision_dir(project)
        self.queue._start_worker()
        self.queue.worker_state = "planning"
        self.queue._send({"type": "plan", "job_id": job["id"], "style": job["style"], "lyrics": job["lyrics"], "seed": int(job["seed"]), "output": str(rev / "base_plan")})
        # The persistent worker acknowledges every request with ``started``
        # before doing the model work.  Keep reading until the terminal plan
        # event; treating the acknowledgement as a protocol failure sends
        # SIGTERM to a healthy planner and makes YuE report
        # ``Cancelled before prefill``.
        while True:
            event = self.queue._read()
            if event.get("job_id") != job["id"]:
                raise ValueError("worker_protocol: 基本プランのジョブIDが一致しません")
            if event.get("type") == "started":
                continue
            if event.get("type") == "error":
                raise ValueError(f"plan_invalid: {event.get('summary', '基本プランに失敗しました')}")
            if event.get("type") == "plan_completed":
                break
            raise ValueError("worker_protocol: 基本プランの応答が不正です")
        score = rev / "base_plan" / "score.abc"
        if not score.is_file():
            raise ValueError("plan_invalid: score.abcがありません")
        analysis = analyze(score.read_text(encoding="utf-8"), self.queue.covers, job["lyrics"])
        project.setdefault("stage", {})["plan"] = {"job_id": job["id"], "status": "awaiting_review", "analysis": analysis, "path": "base_plan"}
        self._save(project)
        self.store.finish(job["id"], "awaiting_review")
        self.queue._terminate()
        self.queue.worker_state = "not_started"

    def prepare(self, project, *, section, voice, transform, seed):
        rev = self._revision_dir(project)
        base = (rev / "base_plan" / "score.abc").read_text(encoding="utf-8")
        motif = (rev / "motif_score.abc").read_text(encoding="utf-8")
        edited, manifest = integrate(base, motif, self.queue.covers, section=section, voice=voice, transform=transform, seed=seed)
        validation = validate(edited, self.queue.covers, base_abc=base, lyrics=project["conditions"].get("lyrics", ""))
        (rev / "edited_score.abc").write_text(edited, encoding="utf-8")
        write_json(rev / "edit_manifest.json", manifest)
        write_json(rev / "validation.json", validation)
        project.setdefault("stage", {})["prepare"] = {"status": "awaiting_review", "manifest": "edit_manifest.json", "validation": "validation.json"}
        project["edit"] = {"section": section, "voice": voice, "transform": transform}
        self._save(project)
        return project

    def render(self, job, directory):
        project = self._project(job)
        rev = self._revision_dir(project)
        edited = (rev / "edited_score.abc").read_text(encoding="utf-8")
        job["abc"] = edited
        self.queue._start_worker()
        self.queue.worker_state = "generating"
        from .storage import song_request
        self.queue._send({"type": "generate", "job_id": job["id"], "request": song_request(job), "output": str(directory / "artifacts")})
        while not self.queue.stopping.is_set():
            event = self.queue._read()
            if event.get("type") == "completed":
                receipt = self.store.inspect_result(job)
                if not receipt:
                    raise ValueError("save_failed: 最終成果物がありません")
                self.store.finish(job["id"], **receipt)
                write_json(directory / "motif.json", project)
                self.queue.worker_state = "ready"
                return
            if event.get("type") == "error":
                raise ValueError(event.get("summary", "生成に失敗しました"))
        raise ValueError("interrupted: 生成を中断しました")
