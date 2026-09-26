from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT
from .queue import Queue
from .storage import FILES, ID_RE, dumps, song_request

__version__ = "0.5.0"

MAX_SEED = 2**63


class JSONModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Submission(JSONModel):
    submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    title: StrictStr = Field(default="", max_length=200)
    style: StrictStr = Field(min_length=1, max_length=12000)
    lyrics: StrictStr = Field(min_length=1, max_length=60000)
    cot: Literal["full", "melody", "off"] = "full"
    seed_mode: Literal["random", "fixed"] = "random"
    seed: StrictStr | None = None
    candidate_count: StrictInt = Field(default=1, ge=1, le=4)
    cfg_scale: float | None = Field(default=None, ge=0, le=20, allow_inf_nan=False)
    source_id: StrictStr | None = None

    @field_validator("style", "lyrics")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("空白だけの入力は使用できません")
        return value

    @field_validator("seed")
    @classmethod
    def seed_range(cls, value):
        if value is not None and (not re.fullmatch(r"[0-9]{1,19}", value) or not 0 <= int(value) < MAX_SEED):
            raise ValueError("Seed は 0〜9223372036854775807 の整数です")
        return value


class Retry(JSONModel):
    submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class Favorite(JSONModel):
    favorite: StrictBool


class Empty(JSONModel):
    pass


def has_chords(abc):
    # Conservative guard for the native dialect; this does not edit any ABC.
    return bool(abc and re.search(r'"(?![\^_<>@])[^"\n]+"', abc))


def create_app(config):
    queue = Queue(config)
    store = queue.store
    index_html = (ROOT / "static" / "index.html").read_bytes().replace(
        b"@@VERSION@@", __version__.encode("ascii"))

    @asynccontextmanager
    async def lifespan(app):
        # Recovery runs in the queue thread, outside the HTTP startup path.
        queue.start()
        try:
            yield
        finally:
            # Queue.close() performs bounded joins and process termination.
            # Calling it directly avoids waiting on the shared asyncio
            # executor during ASGI shutdown, where a pending sync endpoint
            # can otherwise prevent the lifespan task from completing.
            queue.close()

    async def require_ready(request: Request):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health" and not queue.health()["ready"]:
            raise HTTPException(503, queue.last_error or "保存データを復旧しています。しばらくして再試行してください")

    app = FastAPI(title="YuE2 Local Studio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(require_ready)])
    app.state.queue = queue
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts), www_redirect=False)

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
                return JSONResponse({"detail": "同一オリジンから操作してください"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "外部サイトからの操作は受け付けません"}, status_code=403)
            upload = request.method == "POST" and request.url.path in ("/api/covers/upload", "/api/motifs/upload", "/api/midi/imports")
            expected_type = "application/octet-stream" if upload else "application/json"
            empty_delete = request.method == "DELETE" and not request.headers.get("content-type") and not await request.body()
            if not empty_delete and request.headers.get("content-type", "").split(";")[0].strip() != expected_type:
                return JSONResponse({"detail": "application/json が必要です"}, status_code=415)
            if not upload and len(await request.body()) > 1024 * 1024:
                return JSONResponse({"detail": "入力は全体で1 MiB以内にしてください。切り捨ては行いません"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "media-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def get_job(job_id):
        if not ID_RE.fullmatch(job_id):
            raise HTTPException(404, "曲が見つかりません")
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "曲が見つかりません")
        return job

    def public(job, *, detail=False):
        data = {k: v for k, v in job.items() if k not in ("abc", "runtime", "style", "lyrics", "cover")}
        available = {}
        for kind in FILES:
            try:
                store.artifact(job["id"], kind)
                available[kind] = f"/api/jobs/{job['id']}/files/{kind}"
            except (OSError, ValueError):
                pass
        available["conditions"] = f"/api/jobs/{job['id']}/files/conditions"
        data["files"] = available
        data["has_chords"] = False
        if "abc" in available:
            path, _ = store.artifact(job["id"], "abc")
            data["has_chords"] = has_chords(path.read_bytes().decode("utf-8"))
        if detail:
            data.update(style=job["style"], lyrics=job["lyrics"], runtime=job["runtime"],
                        uses_score=job["abc"] is not None)
            source = store.get(job["source_id"]) if job["source_id"] else None
            data["source_title"] = source["title"] if source else None
            data["cover"] = job.get("cover")
        return data

    def submit(spec, key, identity):
        fingerprint = hashlib.sha256(dumps(identity).encode()).hexdigest()
        first_seed = int(spec["seed"]) if spec["seed_mode"] == "fixed" else secrets.randbelow(MAX_SEED)
        seeds = [(first_seed + n) % MAX_SEED for n in range(spec["candidate_count"])]
        try:
            jobs, reused = store.submit(key, fingerprint, spec, config.runtime(), seeds)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        queue.wake.set()
        return {"group_id": jobs[0]["group_id"], "jobs": [public(j) for j in jobs], "reused": reused}

    @app.get("/api/health")
    async def health():
        return queue.health()

    @app.get("/api/status")
    def status():
        return queue.status()

    @app.get("/api/jobs")
    def jobs(q: str = "", favorites: bool = False):
        rows = store.list()
        return {"jobs": [public(j) for j in rows if j.get("task") not in ("motif_clip", "motif_transcribe", "motif_plan") and (not favorites or j["favorite"]) and q.casefold() in j["title"].casefold()]}

    @app.get("/api/jobs/{job_id}")
    def detail(job_id: str):
        return public(get_job(job_id), detail=True)

    @app.get("/api/jobs/{job_id}/deletion")
    def deletion_preview(job_id: str):
        try:
            with queue.control:
                if queue.active_id == job_id:
                    raise ValueError("実行中のジョブは削除できません。完了後に再試行してください")
                return store.deletion_preview(job_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            raise HTTPException(500, "削除対象の確認に失敗しました。保存先とDBを確認してください") from exc

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str):
        try:
            with queue.control:
                if queue.active_id == job_id:
                    raise ValueError("実行中のジョブは削除できません。完了後に再試行してください")
                return store.delete_job(job_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            raise HTTPException(500, "削除処理に失敗しました。保存データを確認してください") from exc

    @app.post("/api/jobs", status_code=202)
    def create(body: Submission):
        spec = body.model_dump(exclude={"submission_key"})
        if body.seed_mode == "fixed" and body.seed is None:
            raise HTTPException(422, "固定値のSeedを指定してください")
        identity = dict(spec)
        if body.source_id:
            get_job(body.source_id)
            try:
                path, _ = store.artifact(body.source_id, "abc")
                abc = path.read_bytes().decode("utf-8")
            except (OSError, ValueError) as exc:
                raise HTTPException(422, "元曲の保存済み譜面を読み込めません") from exc
            if body.cot == "off":
                raise HTTPException(422, "譜面の使用中は off を選べません")
            if has_chords(abc) and body.cot != "full":
                raise HTTPException(422, "コード付き譜面は full で使用してください。melody はコードを取り除きません")
            spec["abc"] = abc
            identity["abc_sha256"] = hashlib.sha256(abc.encode()).hexdigest()
        return submit(spec, body.submission_key, identity)

    @app.post("/api/jobs/{job_id}/regenerate", status_code=202)
    def regenerate(job_id: str, body: Retry):
        old = get_job(job_id)
        if old["runtime"] != config.runtime():
            raise HTTPException(409, "元曲と現在のモデル設定が異なります。同条件で再生成するには元の設定で起動してください")
        if old.get("task") == "transcribe":
            raise HTTPException(422, "採譜はカバー編集画面から再実行してください")
        spec = {k: old[k] for k in ("title", "style", "lyrics", "cot", "seed", "cfg_scale", "source_id", "abc", "cover_id", "cover")}
        spec.update(seed_mode="fixed", candidate_count=1)
        return submit(spec, body.submission_key, {"regenerate": job_id})

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, body: Empty):
        get_job(job_id)
        if not store.cancel(job_id):
            raise HTTPException(409, "待機中のジョブのみキャンセルできます")
        return {"status": "cancelled"}

    @app.patch("/api/jobs/{job_id}/favorite")
    def favorite(job_id: str, body: Favorite):
        get_job(job_id)
        store.favorite(job_id, body.favorite)
        return {"favorite": body.favorite}

    @app.post("/api/queue/resume")
    def resume(body: Empty):
        try:
            queue.resume()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return queue.status()

    @app.post("/api/queue/pause")
    def pause(body: Empty):
        queue.pause()
        return queue.status()

    @app.get("/api/jobs/{job_id}/logs")
    def logs(job_id: str):
        get_job(job_id)
        path = config.data_dir / "logs" / f"{job_id}.log"
        if not path.is_file():
            return {"text": "ログはまだありません"}
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 64000))
            return {"text": f.read().decode("utf-8", errors="replace")}

    @app.api_route("/api/jobs/{job_id}/files/{kind}", methods=["GET", "HEAD"])
    def file(job_id: str, kind: str, download: bool = False):
        job = get_job(job_id)
        if kind in ("cover", "original-abc", "edited-abc", "used-abc") and job.get("cover") and job["task"] != "transcribe":
            from fastapi.responses import Response
            if kind == "cover":
                return JSONResponse(job["cover"], headers={"Content-Disposition": f'attachment; filename="{job_id}-cover.json"'})
            key = {"original-abc": "original_abc", "edited-abc": "edited_abc", "used-abc": "used_abc"}[kind]
            return Response(job["cover"][key], media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{job_id}-{kind}.abc"'})
        if kind == "conditions":
            return JSONResponse({"studio": "YuE2 Local Studio", "job": job, "generation_request": song_request(job)},
                                headers={"Content-Disposition": f'attachment; filename="{job_id}-conditions.json"'})
        try:
            path, mime = store.artifact(job_id, kind)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "成果物が見つかりません") from exc
        return FileResponse(path, media_type=mime, filename=f"{job_id}-{path.name}" if download else None)

    @app.get("/api/diagnostics")
    def diagnostics():
        return {"runtime": config.runtime(), "data_dir": str(config.data_dir), "host": config.host,
                "port": config.port, "python_exists": Path(config.python).is_file(),
                "queue": queue.status(), "running_cancel_supported": False,
                "note": "設定の変更は config.local.json を編集してアプリを再起動してください。モデル取得はオフライン専用です"}

    @app.get("/")
    async def index():
        return HTMLResponse(index_html, headers={"Cache-Control": "no-store"})

    from .covers import register_cover_routes
    register_cover_routes(app, config, queue, get_job, public, submit)
    from .motifs import register_motif_routes
    register_motif_routes(app, config, queue, get_job, public, submit)
    from .midi_routes import register_midi_routes
    register_midi_routes(app, config, queue, get_job, public, submit)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app
