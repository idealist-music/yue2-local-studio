"""Server-owned cover sources and immutable generation snapshots; no model imports."""
import asyncio
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from .config import ROOT
from .storage import ID_RE, dumps, now, write_json

MAX_AUDIO = 100 * 1024 * 1024
MAX_ABC = 256 * 1024
AUDIO_TYPES = {".wav", ".flac", ".mp3", ".ogg"}


class Covers:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.lock = threading.RLock()
        self._tools = None

    def tools(self):
        with self.lock:
            if self._tools is None:
                path = Path(self.config.abc_tools) if self.config.abc_tools else Path(self.config.python).parent.parent.parent / "skills/yue2-music/scripts/abc_tools.py"
                if not path.is_file():
                    raise ValueError("公式ABC検証ヘルパーがありません。config.local.json の abc_tools を設定してください")
                name = "studio_abc_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                # Read-only import: never create a pycache in the existing YuE environment.
                source = path.read_bytes()
                exec(compile(source, str(path), "exec"), module.__dict__)
                module.studio_source_sha256 = hashlib.sha256(source).hexdigest()
                self._tools = module
            return self._tools

    def prepare(self, abc, mode):
        if not abc.strip() or len(abc.encode("utf-8")) > MAX_ABC:
            raise ValueError("ABCは空にできません。UTF-8で256 KiB以内にしてください")
        tools = self.tools()
        try:
            before = tools.parse_abc(abc)
            if not any(v.notes for v in before.voices.values()):
                raise ValueError("ABCにメロディの音符がありません")
            used = tools.strip_chords(abc) if mode == "melody" else abc
            after = tools.parse_abc(used)
            check = tools.compare(before, after)
            check.update(original_chords=sum(len(v.chords) for v in before.voices.values()),
                         used_chords=sum(len(v.chords) for v in after.voices.values()),
                         abc_tools_sha256=tools.studio_source_sha256,
                         used_sha256=hashlib.sha256(used.encode()).hexdigest())
            return used, check
        except ValueError as exc:
            raise ValueError(f"対応するYuE2 native ABC形式を確認してください: {exc}") from exc

    def directory(self, cover_id):
        if not ID_RE.fullmatch(cover_id):
            raise ValueError("不正なカバーIDです")
        root = self.store.root / "covers"
        root.mkdir(exist_ok=True)
        path = root / cover_id
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise ValueError("不正なカバー保存先です")
        return path

    def get(self, cover_id):
        self.directory(cover_id)
        with self.store.connect() as db:
            row = db.execute("SELECT data FROM covers WHERE id=?", (cover_id,)).fetchone()
        if not row:
            raise ValueError("カバーが見つかりません")
        return json.loads(row[0])

    def save(self, data):
        with self.store.connect() as db:
            db.execute("INSERT INTO covers VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                       (data["id"], dumps(data)))

    def create(self, *, source=None, abc=None, audio=None, preview=None, filename=None, audio_info=None):
        cover_id = uuid.uuid4().hex
        directory = self.directory(cover_id)
        directory.mkdir()
        if abc is not None:
            # Keep raw source even when it needs manual correction to native ABC.
            (directory / "original.abc").write_bytes(abc.encode())
        if audio:
            shutil.copyfile(audio, directory / ("source" + Path(audio).suffix.lower()))
        if preview:
            shutil.copyfile(preview, directory / "preview.wav")
        data = {"id": cover_id, "created_at": now(), "source_id": source["id"] if source else None,
                "title": (source["title"] if source else filename or "")[:180],
                "style": source["style"] if source else "", "lyrics": source["lyrics"] if source else "",
                "seed": source["seed"] if source else "", "cot": "melody", "cfg_scale": source.get("cfg_scale") if source else None,
                "original_abc": abc, "abc": abc or "", "warnings": [], "revision": 0,
                "audio_name": "source" + Path(audio).suffix.lower() if audio else None,
                "filename": filename, "audio_info": audio_info, "transcription": None}
        data["source_conditions"] = {k: source[k] for k in ("title", "style", "lyrics", "seed", "cot")} if source else None
        if audio:
            digest = hashlib.sha256()
            with Path(audio).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            data["audio_sha256"] = digest.hexdigest()
        self.save(data)
        return data

    def public(self, data):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE cover_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (data["id"],)).fetchone()
        job = self.store.decode(row)
        status = "awaiting_review" if data["original_abc"] is not None else "needs_transcription"
        if job:
            status = job["status"]
        result = {**data, "status": status, "job_id": job["id"] if job else None,
                  "error": job["error"] if job else None, "files": {}}
        for kind in ("source", "preview", "original"):
            try:
                self.file(data, kind)
                result["files"][kind] = f"/api/covers/{data['id']}/files/{kind}"
            except (OSError, ValueError):
                pass
        if data["abc"]:
            result["files"]["edited"] = f"/api/covers/{data['id']}/files/edited"
        return result

    def file(self, data, kind):
        name = {"source": data["audio_name"], "preview": "preview.wav", "original": data.get("original_name", "original.abc")}.get(kind)
        if not name or Path(name).name != name:
            raise ValueError("ファイルがありません")
        directory = self.directory(data["id"])
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file():
            raise FileNotFoundError("ファイルがありません")
        return path

    def transcription_config(self):
        python, model = self.config.sheetsage_python, self.config.sheetsage_model
        if not python or not model or not Path(python).is_file() or not (Path(model) / "config.json").is_file():
            raise ValueError("SheetSage2未設定です。専用環境とモデルを用意し sheetsage_python / sheetsage_model を設定してください（README-COVERS.md）")
        if Path(python).parent.parent.resolve() == Path(self.config.python).parent.parent.resolve():
            raise ValueError("SheetSage2はYuE2と別のPython環境が必要です")
        return {"python": python, "model": model, "device": self.config.device, "melody_only": True}


def register_cover_routes(app, config, queue, get_job, public_job, submit):
    from fastapi import HTTPException, Request
    from fastapi.responses import FileResponse, Response
    from pydantic import Field, StrictStr, StrictBool
    # Avoid a module cycle: route schemas reuse the normal submission validation.
    from .app import JSONModel, Submission, Retry
    covers, store = queue.covers, queue.store

    class Source(JSONModel):
        source_id: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")

    class Edit(JSONModel):
        abc: StrictStr = Field(max_length=MAX_ABC)
        title: StrictStr = Field(default="", max_length=200)
        style: StrictStr = Field(default="", max_length=12000)
        lyrics: StrictStr = Field(default="", max_length=60000)
        seed: StrictStr = Field(default="", max_length=19)
        cot: Literal["melody", "full"] = "melody"
        cfg_scale: float | None = Field(default=None, ge=0, le=20, allow_inf_nan=False)
        revision: int = Field(ge=0)

    class Prepare(JSONModel):
        abc: StrictStr = Field(min_length=1, max_length=MAX_ABC)
        cot: Literal["melody", "full"] = "melody"

    class Generate(Submission):
        cot: Literal["melody", "full"] = "melody"
        abc: StrictStr = Field(min_length=1, max_length=MAX_ABC)
        reviewed: StrictBool
        revision: int = Field(ge=0)

    def get(cover_id):
        try:
            return covers.get(cover_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    def prepared(abc, mode):
        try:
            return covers.prepare(abc, mode)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/covers/config")
    def cover_config():
        try:
            settings = covers.transcription_config()
            note, configured = "専用ワーカーの起動時に依存関係・API・モデルを確認します", True
        except ValueError as exc:
            settings, note, configured = None, str(exc), False
        return {"transcription_configured": configured, "transcription": settings, "note": note,
                "max_audio_bytes": MAX_AUDIO, "max_abc_bytes": MAX_ABC, "audio_extensions": sorted(AUDIO_TYPES)}

    @app.get("/api/covers")
    def list_covers():
        with store.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM covers ORDER BY rowid DESC")]
        return {"covers": [{k: d[k] for k in ("id", "title", "created_at")} for d in rows]}

    @app.get("/api/covers/setup")
    def setup_instructions():
        return FileResponse(ROOT / "README-COVERS.md", media_type="text/plain; charset=utf-8", filename="README-COVERS.md")

    @app.post("/api/covers/from-song", status_code=201)
    def from_song(body: Source):
        source = get_job(body.source_id)
        if source.get("task") == "transcribe":
            raise HTTPException(422, "採譜ジョブはカバー編集画面から開いてください")
        abc, audio = None, None
        try:
            path, _ = store.artifact(source["id"], "abc")
            abc = path.read_bytes().decode("utf-8")
            if not abc.strip():
                abc = None
        except (OSError, ValueError):
            # An externally supplied score is still usable even if output saving failed.
            abc = source.get("abc") or None
        for kind in ("flac", "wav"):
            try:
                audio, _ = store.artifact(source["id"], kind)
                break
            except (OSError, ValueError):
                pass
        if abc is None and audio is None:
            raise HTTPException(422, "元曲に利用できるABC・音源がありません")
        return covers.public(covers.create(source=source, abc=abc, audio=audio))

    @app.post("/api/covers/upload", status_code=201)
    async def upload(request: Request, filename: str):
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_TYPES | {".abc"} or len(filename) > 240:
            raise HTTPException(422, "WAV / FLAC / MP3 / OGG / ABCファイルを選択してください")
        limit = MAX_ABC if suffix == ".abc" else MAX_AUDIO
        staging = store.root / "uploads"
        staging.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cover-", dir=staging) as temp:
            path = Path(temp) / ("input" + suffix)
            total = 0
            with path.open("xb") as out:
                async for block in request.stream():
                    total += len(block)
                    if total > limit:
                        raise HTTPException(413, "アップロード上限を超えています（音源100 MiB / ABC256 KiB）")
                    await asyncio.to_thread(out.write, block)
            if not total:
                raise HTTPException(422, "空のファイルは使用できません")

            def finish_upload():
                if suffix == ".abc":
                    try:
                        abc = path.read_bytes().decode("utf-8-sig")
                    except UnicodeError as exc:
                        raise HTTPException(422, "ABCはUTF-8で保存してください") from exc
                    prepared(abc, "melody")
                    return covers.public(covers.create(abc=abc, filename=Path(filename).name))
                preview = Path(temp) / "preview.wav"
                try:
                    proc = subprocess.run([config.python, "-B", str(ROOT / "audio_probe.py"), str(path), str(preview)],
                                          capture_output=True, text=True, timeout=60)
                    if proc.returncode:
                        raise ValueError(proc.stderr[-1500:])
                    info = json.loads(proc.stdout)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(422, f"音源を読み取れません: {exc}") from exc
                return covers.public(covers.create(audio=path, preview=preview, filename=Path(filename).name, audio_info=info))
            return await asyncio.to_thread(finish_upload)

    @app.get("/api/covers/{cover_id}")
    def detail(cover_id: str):
        return covers.public(get(cover_id))

    @app.put("/api/covers/{cover_id}")
    def edit(cover_id: str, body: Edit):
        with covers.lock:
            data = get(cover_id)
            if data["revision"] != body.revision:
                raise HTTPException(409, "別画面で更新されています。カバーを開き直してください")
            # Drafts may be temporarily invalid; generation validates them strictly.
            data.update(body.model_dump(exclude={"revision"}))
            data["revision"] += 1
            covers.save(data)
            return covers.public(data)

    @app.post("/api/covers/{cover_id}/transcribe", status_code=202)
    def transcribe(cover_id: str, body: Retry):
        with covers.lock:
            data = get(cover_id)
            if data["original_abc"] is not None:
                raise HTTPException(409, "保存済みABCがあります。再採譜せず編集・生成してください")
            if covers.public(data)["status"] in ("queued", "transcribing", "running"):
                # A retry with the same key is resolved by the normal submissions table below.
                with store.connect() as db:
                    old = db.execute("SELECT group_id FROM submissions WHERE key=?", (body.submission_key,)).fetchone()
                if not old:
                    raise HTTPException(409, "この音源の処理は登録済みです")
            try:
                settings = covers.transcription_config()
                covers.file(data, "source")
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc
            spec = {"title": data["title"] + " · 採譜", "style": data["style"], "lyrics": data["lyrics"],
                    "cot": "melody", "seed": "0", "seed_mode": "fixed", "candidate_count": 1,
                    "source_id": data["source_id"], "task": "transcribe", "cover_id": cover_id,
                    "cover": {"id": cover_id, "transcription": settings}}
            return submit(spec, body.submission_key, {"transcribe": cover_id, "settings": settings})

    @app.post("/api/covers/{cover_id}/prepare")
    def prepare(cover_id: str, body: Prepare):
        get(cover_id)
        used, check = prepared(body.abc, body.cot)
        return {"abc": used, "validation": check}

    @app.post("/api/covers/{cover_id}/generate", status_code=202)
    def generate(cover_id: str, body: Generate):
        with covers.lock:
            data = get(cover_id)
            if not body.reviewed:
                raise HTTPException(422, "ABCと警告を確認し、確認済みにチェックしてください")
            if data["original_abc"] is None:
                raise HTTPException(409, "まず採譜を成功させてABCを確認してください")
            if data["revision"] != body.revision:
                raise HTTPException(409, "別画面で更新されています。カバーを開き直してください")
            if body.seed_mode == "fixed" and body.seed is None:
                raise HTTPException(422, "固定値のSeedが必要です")
            used, check = prepared(body.abc, body.cot)
            spec = body.model_dump(exclude={"submission_key", "reviewed", "revision"})
            spec.update(abc=used, source_id=data["source_id"], cover_id=cover_id,
                        cover={**data, "edited_abc": body.abc, "used_abc": used, "validation": check,
                               "reviewed": True, "reviewed_at": now()})
            identity = body.model_dump(exclude={"submission_key"})
            identity["cover_id"] = cover_id
            # Timestamp in the snapshot is not part of idempotency identity.
            result = submit(spec, body.submission_key, identity)
            # Transcription itself is complete; remove its already-reviewed item
            # from the queue without altering the original completion timestamp.
            with store.connect() as db:
                db.execute("UPDATE jobs SET status='reviewed' WHERE cover_id=? AND task='transcribe' AND status='awaiting_review'", (cover_id,))
            return result

    @app.api_route("/api/covers/{cover_id}/files/{kind}", methods=["GET", "HEAD"])
    def file(cover_id: str, kind: str, download: bool = False):
        data = get(cover_id)
        if kind in ("edited", "melody"):
            text = prepared(data["abc"], "melody")[0] if kind == "melody" else data["abc"]
            return Response(text, media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{cover_id}-{kind}.abc"'})
        try:
            path = covers.file(data, kind)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc
        mime = "text/plain; charset=utf-8" if kind == "original" else {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}[path.suffix]
        return FileResponse(path, media_type=mime, filename=path.name if download else None)
