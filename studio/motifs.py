"""Motif Song API and project storage."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import Field, StrictStr

from .motif_abc import analyze, validate
from .storage import ID_RE, dumps, now

MAX_AUDIO = 100 * 1024 * 1024
MAX_ABC = 256 * 1024
AUDIO_TYPES = {".wav", ".flac", ".mp3", ".ogg"}


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def register_motif_routes(app, config, queue, get_job, public_job, submit):
    from .app import JSONModel, Submission
    store = queue.store

    class Source(JSONModel):
        source_job_id: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
        submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    class UploadMeta(JSONModel):
        submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
        title: StrictStr = Field(default="", max_length=200)
        style: StrictStr = Field(default="", max_length=12000)
        lyrics: StrictStr = Field(default="", max_length=60000)

    class Conditions(JSONModel):
        expected_revision: int = Field(ge=0)
        title: StrictStr = Field(default="", max_length=200)
        start: float = Field(ge=0)
        end: float = Field(gt=0)
        style: StrictStr = Field(min_length=1, max_length=12000)
        lyrics: StrictStr = Field(min_length=1, max_length=60000)
        seed: StrictStr = Field(default="0", max_length=19)
        purpose: Literal["Vocal", "Ins"] = "Vocal"
        sections: list[Literal["Chorus", "Verse", "Intro", "Bridge", "Outro"]] = Field(default_factory=lambda: ["Chorus"])
        transform: dict = Field(default_factory=dict)

    class Stage(JSONModel):
        expected_revision: int = Field(ge=0)
        submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    class Prepare(JSONModel):
        expected_revision: int = Field(ge=0)
        section: Literal["chorus", "verse", "intro", "bridge", "outro"]
        voice: Literal["Vocal", "Ins"] = "Vocal"
        seed: StrictStr = "0"
        transform: dict = Field(default_factory=dict)

    class Validate(JSONModel):
        expected_revision: int = Field(ge=0)
        abc: StrictStr = Field(min_length=1, max_length=MAX_ABC)
        declared_edit_ranges: list = Field(default_factory=list)

    class Review(JSONModel):
        expected_revision: int = Field(ge=0)
        confirmation: bool
        edited_sha256: StrictStr
        warnings_acknowledged: bool = False

    class Generate(JSONModel):
        expected_revision: int = Field(ge=0)
        submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    def project(motif_id):
        try:
            return store.get_motif(motif_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    def directory(motif_id):
        if not ID_RE.fullmatch(motif_id):
            raise HTTPException(404, "Motifが見つかりません")
        root = store.root / "motifs"
        root.mkdir(exist_ok=True)
        path = root / motif_id
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise HTTPException(400, "保存先が不正です")
        return path

    def public(data):
        result = dict(data)
        result["files"] = {}
        rev = str(data["revision"])
        root = directory(data["id"])
        mapping = {"source": root / "source" / data["source"]["filename"],
                   "clip": root / "revisions" / rev / "source_clip.wav",
                   "motif": root / "revisions" / rev / "motif_score.abc",
                   "base": root / "revisions" / rev / "base_plan" / "score.abc",
                   "edited": root / "revisions" / rev / "edited_score.abc",
                   "manifest": root / "revisions" / rev / "edit_manifest.json",
                   "validation": root / "revisions" / rev / "validation.json"}
        for kind, path in mapping.items():
            if path.is_file():
                result["files"][kind] = f"/api/motifs/{data['id']}/files/{rev}/{kind}"
        return result

    def update(data, body):
        if data["revision"] != body.expected_revision:
            raise HTTPException(409, "別画面で更新されています。Motifを開き直してください")
        data["revision"] += 1
        return data

    def enqueue(data, task, key, spec, identity):
        fingerprint = hashlib.sha256(dumps({"task": task, "motif": data["id"], "revision": data["revision"], **identity}).encode()).hexdigest()
        try:
            jobs, reused = store.submit(key, fingerprint, {**spec, "task": task, "motif_id": data["id"], "motif": {"id": data["id"], "revision": data["revision"], "source": data["source"]}}, config.runtime(), [int(spec.get("seed", "0"))])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        queue.wake.set()
        return {"reused": reused, "job": public_job(jobs[0]), "project": public(data)}

    @app.get("/api/motifs/config")
    def motif_config():
        configured = bool(config.sheetsage_python and config.sheetsage_model and Path(config.sheetsage_python).is_file() and Path(config.sheetsage_model, "config.json").is_file())
        return {"configured": configured, "ffmpeg": Path("/usr/bin/ffmpeg").is_file(), "max_audio_bytes": MAX_AUDIO,
                "max_clip_seconds": 60, "max_motif_bars": 8, "audio_extensions": sorted(AUDIO_TYPES)}

    @app.get("/api/motifs")
    def list_motifs():
        return {"motifs": [public(x) for x in store.list_motifs()]}

    @app.post("/api/motifs/from-song", status_code=201)
    def from_song(body: Source):
        source = get_job(body.source_job_id)
        audio = None
        for kind in ("flac", "wav"):
            try:
                audio, _ = store.artifact(source["id"], kind)
                break
            except (OSError, ValueError):
                pass
        if audio is None:
            raise HTTPException(422, "元曲に利用できる音源がありません")
        info = {"duration": source.get("duration") or 0}
        if not info["duration"]:
            raise HTTPException(422, "元曲の音源長を取得できません")
        motif_id = uuid.uuid4().hex
        root = directory(motif_id); (root / "source").mkdir(parents=True)
        target = root / "source" / ("source" + Path(audio).suffix.lower())
        shutil.copyfile(audio, target)
        data = {"schema_version": 1, "id": motif_id, "created_at": now(), "updated_at": now(), "revision": 0,
                "source": {"type": "song", "job_id": source["id"], "filename": target.name, "sha256": _hash(target), "duration": info["duration"]},
                "conditions": {"title": (source["title"] + " · Motif Song")[:200], "style": source["style"], "lyrics": source["lyrics"], "seed": source["seed"], "start": 0, "end": min(30, info["duration"]), "purpose": "Vocal", "sections": ["Chorus"], "transform": {}}, "stage": {}, "review": None}
        store.save_motif(data)
        return public(data)

    @app.post("/api/motifs/upload", status_code=201)
    async def upload(request: Request, filename: str, submission_key: str):
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_TYPES or len(filename) > 240:
            raise HTTPException(422, "WAV / FLAC / MP3 / OGGファイルを選択してください")
        motif_id = uuid.uuid4().hex
        root = directory(motif_id); (root / "source").mkdir(parents=True)
        target = root / "source" / ("source" + suffix)
        total = 0
        with target.open("xb") as out:
            async for block in request.stream():
                total += len(block)
                if total > MAX_AUDIO:
                    raise HTTPException(413, "音源100 MiB以内で指定してください")
                await asyncio.to_thread(out.write, block)
        if not total:
            raise HTTPException(422, "空のファイルは使用できません")
        preview = root / "source" / "preview.wav"
        proc = await asyncio.to_thread(subprocess.run, [config.python, "-B", str(Path(__file__).parents[1] / "audio_probe.py"), str(target), str(preview)], capture_output=True, text=True, timeout=60)
        if proc.returncode:
            raise HTTPException(422, "音源を読み取れません")
        try:
            info = json.loads(proc.stdout)
            duration = float(info["duration"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "音源の長さを取得できません") from exc
        # Duration is filled by the probe in the clip stage if unavailable.
        data = {"schema_version": 1, "id": motif_id, "created_at": now(), "updated_at": now(), "revision": 0,
                "source": {"type": "upload", "filename": target.name, "sha256": _hash(target), "duration": duration},
                "conditions": {"title": Path(filename).stem[:200], "style": "", "lyrics": "", "seed": "0", "start": 0, "end": min(30, duration), "purpose": "Vocal", "sections": ["Chorus"], "transform": {}}, "stage": {}, "review": None}
        store.save_motif(data)
        return public(data)

    @app.get("/api/motifs/{motif_id}")
    def detail(motif_id: str):
        return public(project(motif_id))

    @app.put("/api/motifs/{motif_id}")
    def edit(motif_id: str, body: Conditions):
        data = project(motif_id); update(data, body)
        if not body.start < body.end:
            raise HTTPException(422, "開始時刻は終了時刻より前にしてください")
        data["conditions"].update(body.model_dump(exclude={"expected_revision"}))
        data["stage"] = {}; data["review"] = None
        store.save_motif(data)
        return public(data)

    @app.post("/api/motifs/{motif_id}/clip", status_code=202)
    def clip(motif_id: str, body: Stage):
        data = project(motif_id)
        if data["revision"] != body.expected_revision:
            raise HTTPException(409, "条件が更新されています")
        if not data["conditions"].get("style") or not data["conditions"].get("lyrics"):
            raise HTTPException(422, "Style と Lyrics を入力してください")
        return enqueue(data, "motif_clip", body.submission_key, {"title": data["conditions"]["title"], "style": data["conditions"]["style"], "lyrics": data["conditions"]["lyrics"], "cot": "full", "seed": data["conditions"].get("seed", "0"), "candidate_count": 1}, {"start": data["conditions"]["start"], "end": data["conditions"]["end"]})

    @app.post("/api/motifs/{motif_id}/transcribe", status_code=202)
    def transcribe(motif_id: str, body: Stage):
        data = project(motif_id)
        if data["revision"] != body.expected_revision or data.get("stage", {}).get("clip", {}).get("status") != "completed":
            raise HTTPException(409, "先に音源区間を切り出してください")
        return enqueue(data, "motif_transcribe", body.submission_key, {"title": data["conditions"]["title"], "style": data["conditions"]["style"], "lyrics": data["conditions"]["lyrics"], "cot": "full", "seed": data["conditions"].get("seed", "0"), "candidate_count": 1}, {"clip": data["stage"]["clip"]})

    @app.post("/api/motifs/{motif_id}/plan", status_code=202)
    def plan(motif_id: str, body: Stage):
        data = project(motif_id)
        if data["revision"] != body.expected_revision or data.get("stage", {}).get("transcribe", {}).get("status") != "awaiting_review":
            raise HTTPException(409, "モチーフ採譜の確認が必要です")
        return enqueue(data, "motif_plan", body.submission_key, {"title": data["conditions"]["title"], "style": data["conditions"]["style"], "lyrics": data["conditions"]["lyrics"], "cot": "full", "seed": data["conditions"].get("seed", "0"), "candidate_count": 1}, {"motif": data["stage"]["transcribe"]})

    @app.post("/api/motifs/{motif_id}/prepare")
    def prepare(motif_id: str, body: Prepare):
        data = project(motif_id)
        if data["revision"] != body.expected_revision or data.get("stage", {}).get("plan", {}).get("status") != "awaiting_review":
            raise HTTPException(409, "基本プランの確認が必要です")
        data = queue.motifs.prepare(data, section=body.section, voice=body.voice, transform=body.transform, seed=body.seed)
        return public(data)

    @app.post("/api/motifs/{motif_id}/validate")
    def validate_route(motif_id: str, body: Validate):
        data = project(motif_id)
        if data["revision"] != body.expected_revision:
            raise HTTPException(409, "条件が更新されています")
        rev = directory(motif_id) / "revisions" / str(data["revision"])
        base = rev / "base_plan" / "score.abc"
        try:
            result = validate(body.abc, queue.covers, base_abc=base.read_text(encoding="utf-8"), lyrics=data["conditions"].get("lyrics", ""))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        (rev / "edited_score.abc").write_text(body.abc, encoding="utf-8")
        (rev / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        data["stage"]["prepare"] = {"status": "awaiting_review", "validation": "validation.json"}
        store.save_motif(data)
        return public(data)

    @app.post("/api/motifs/{motif_id}/review")
    def review(motif_id: str, body: Review):
        data = project(motif_id)
        if data["revision"] != body.expected_revision or not body.confirmation:
            raise HTTPException(409, "ABCと警告の確認が必要です")
        rev = directory(motif_id) / "revisions" / str(data["revision"])
        edited = rev / "edited_score.abc"
        if not edited.is_file() or _hash(edited) != body.edited_sha256:
            raise HTTPException(409, "編集済みABCが変更されています。再確認してください")
        data["review"] = body.model_dump(); data["review"]["status"] = "reviewed"
        store.save_motif(data); return public(data)

    @app.post("/api/motifs/{motif_id}/generate", status_code=202)
    def generate(motif_id: str, body: Generate):
        data = project(motif_id)
        if data["revision"] != body.expected_revision or data.get("review", {}).get("status") != "reviewed":
            raise HTTPException(409, "編集済みABCの確認が必要です")
        rev = directory(motif_id) / "revisions" / str(data["revision"])
        edited = rev / "edited_score.abc"
        if not edited.is_file():
            raise HTTPException(409, "編集済みABCがありません")
        conditions = data["conditions"]
        return enqueue(data, "motif_render", body.submission_key, {"title": conditions["title"], "style": conditions["style"], "lyrics": conditions["lyrics"], "cot": "full", "seed": conditions.get("seed", "0"), "abc": edited.read_text(encoding="utf-8"), "candidate_count": 1}, {"edited_sha256": _hash(edited)})

    @app.api_route("/api/motifs/{motif_id}/files/{revision}/{kind}", methods=["GET", "HEAD"])
    def files(motif_id: str, revision: str, kind: str):
        data = project(motif_id); root = directory(motif_id) / "revisions" / revision
        mapping = {"source_clip": root / "source_clip.wav", "motif": root / "motif_score.abc", "base": root / "base_plan" / "score.abc", "edited": root / "edited_score.abc", "manifest": root / "edit_manifest.json", "validation": root / "validation.json"}
        if kind == "source": path = directory(motif_id) / "source" / data["source"]["filename"]
        else: path = mapping.get(kind)
        if path is None or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(directory(motif_id).resolve()):
            raise HTTPException(404, "成果物が見つかりません")
        mime = "application/json" if path.suffix == ".json" else ("text/plain; charset=utf-8" if path.suffix == ".abc" else "audio/wav")
        return FileResponse(path, media_type=mime)
