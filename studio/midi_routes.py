from __future__ import annotations

import json
from pathlib import Path

import asyncio
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
import re
from typing import Literal
from pydantic import Field, StrictInt, StrictStr, field_validator

from .app import JSONModel, has_chords
from .midi_service import MidiService, MAX_UPLOAD
from .midi_score import detect_sections


class ExportRequest(JSONModel):
    job_id: StrictStr
    submission_key: StrictStr = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")
    version_id: StrictStr | None = None
    voices: list[StrictStr] = Field(default_factory=lambda: ["Vocal", "Ins"], min_length=1, max_length=2)
    start_bar: StrictInt = Field(default=1, ge=1)
    end_bar: StrictInt | None = Field(default=None, ge=1)
    section: StrictStr | None = None
    section_id: StrictStr | None = None


class PreviewRequest(JSONModel):
    target_song_id: StrictStr
    target_version_id: StrictStr
    voice_map: dict[str, object]
    start_bar: StrictInt = Field(ge=1)
    end_bar: StrictInt = Field(ge=1)
    quantization: StrictStr = "none"
    transpose: StrictInt = Field(default=0, ge=-48, le=48)


class SaveRequest(JSONModel):
    preview_token: StrictStr
    expected_version_id: StrictStr
    confirmed: bool


class NewSongRequest(JSONModel):
    voice_map: dict[str, object]
    title: StrictStr = ""
    style: StrictStr = ""
    lyrics: StrictStr = ""
    seed: StrictStr = "0"
    bpm: StrictInt = Field(default=120, ge=1, le=999)
    meter_n: StrictInt = Field(default=4, ge=1, le=32)
    meter_d: StrictInt = Field(default=4, ge=1, le=32)
    key: StrictStr = "C"

    @field_validator("seed")
    @classmethod
    def valid_seed(cls, value):
        if not re.fullmatch(r"[0-9]{1,19}", value) or int(value) >= 2**63:
            raise ValueError("Seedは0〜9223372036854775807です")
        return value


class GenerateVersionRequest(JSONModel):
    submission_key: StrictStr = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    title: StrictStr = Field(default="", max_length=200)
    style: StrictStr = Field(min_length=1, max_length=12000)
    lyrics: StrictStr = Field(min_length=1, max_length=60000)
    cot: Literal["full", "melody"] | None = None
    seed_mode: Literal["random", "fixed"] = "random"
    seed: StrictStr | None = None
    candidate_count: StrictInt = Field(default=1, ge=1, le=4)
    cfg_scale: float | None = Field(default=None, ge=0, le=20, allow_inf_nan=False)

    @field_validator("style", "lyrics")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("StyleとLyricsは空白だけにできません")
        return value

    @field_validator("seed")
    @classmethod
    def valid_seed(cls, value):
        if value is not None and (not re.fullmatch(r"[0-9]{1,19}", value) or int(value) >= 2**63):
            raise ValueError("Seedは0〜9223372036854775807です")
        return value


def register_midi_routes(app, config, queue, get_job, public_job, submit):
    service = MidiService(config, queue.store, queue.covers)
    app.state.midi = service

    def get_import(import_id):
        item = queue.store.get_midi_import(import_id)
        if not item:
            raise HTTPException(404, "MIDI取り込みが見つかりません")
        return item

    @app.get("/api/jobs/{job_id}/score-versions")
    def versions(job_id: str):
        get_job(job_id)
        try:
            if not queue.store.list_score_versions(job_id):
                service.version_for_job(job_id)
            rows = queue.store.list_score_versions(job_id)
        except ValueError as exc:
            return {"versions": [], "guide": {"kind": "cover_or_midi_new_song", "message": str(exc)}}
        return {"versions": [{k: v for k, v in row.items() if k not in ("abc", "conditions")} for row in rows], "guide": None}

    @app.get("/api/score-versions/{version_id}")
    def version(version_id: str):
        try:
            row = queue.store.get_score_version(version_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not row:
            raise HTTPException(404, "譜面版が見つかりません")
        return row

    @app.get("/api/score-versions/{version_id}/sections")
    def sections(version_id: str):
        row = queue.store.get_score_version(version_id)
        if not row:
            raise HTTPException(404, "譜面版が見つかりません")
        try:
            return {"sections": detect_sections(queue.covers.tools(), row["abc"])}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/midi/exports", status_code=202)
    async def exports(body: ExportRequest):
        get_job(body.job_id)
        try:
            version = queue.store.get_score_version(body.version_id) if body.version_id else service.version_for_job(body.job_id)
            if not version or version["song_id"] != body.job_id:
                raise ValueError("対象曲と譜面版が一致しません")
            if body.section and body.section_id and body.section.lower() != body.section_id.split("@", 1)[0].lower():
                raise ValueError("section名とsection_idの指定が矛盾しています")
            if (body.section or body.section_id) and (body.end_bar is not None or body.start_bar != 1):
                raise ValueError("検出済みセクションを使う場合、手動の開始・終了小節は指定できません")
            section = body.section_id or body.section
            if body.section and not body.section_id:
                candidates = [item for item in detect_sections(queue.covers.tools(), version["abc"]) if item["name"] == body.section.lower()]
                if len(candidates) != 1:
                    raise ValueError("同名セクションが複数あります。section_idを指定してください")
                section = candidates[0]["id"]
            export_id, metadata = await service.export_async(version, voices=body.voices, start_bar=body.start_bar, end_bar=body.end_bar, section=section,
                                                             submission_key=body.submission_key)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"export_id": export_id, "status": metadata.get("state", "ready"), "metadata": metadata}

    @app.get("/api/midi/exports/{export_id}")
    def export_detail(export_id: str):
        record = queue.store.get_midi_export(export_id)
        if not record:
            raise HTTPException(404, "MIDIエクスポートが見つかりません")
        if record.get("state") != "ready":
            return {"export_id": export_id, "status": record.get("state"), "error": record.get("error", {})}
        path = queue.store.root / "midi" / "exports" / export_id / "sidecar.json"
        if not path.is_file():
            raise HTTPException(404, "MIDIエクスポートが見つかりません")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "ready"
        return payload

    @app.get("/api/midi/exports/{export_id}/files/{kind}")
    def export_file(export_id: str, kind: str):
        try:
            path = service.export_file(export_id, kind)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc
        media = {"mid": "audio/midi", "abc": "text/plain; charset=utf-8", "sidecar": "application/json", "readme": "text/plain", "bundle": "application/zip"}[kind]
        return FileResponse(path, media_type=media, filename=path.name)

    @app.post("/api/midi/imports", status_code=202)
    async def imports(request: Request, filename: str = "score.mid", submission_key: str = ""):
        if len(filename) > 240 or Path(filename).suffix.lower() not in {".mid", ".midi"}:
            raise HTTPException(422, "MIDIファイルを指定してください")
        data = await request.body()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "MIDIは8 MiB以内です")
        try:
            import_id, analysis = await service.upload_async(data, filename, submission_key=submission_key)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        record = queue.store.get_midi_import(import_id)
        return {"import_id": import_id, "status": record.get("state", "awaiting_review"), "analysis": analysis}

    @app.get("/api/midi/imports/{import_id}")
    def import_detail(import_id: str):
        return get_import(import_id)

    @app.post("/api/midi/imports/{import_id}/sidecar")
    async def sidecar(import_id: str, request: Request):
        get_import(import_id)
        try:
            data = await request.json()
            if not isinstance(data, dict) or len(json.dumps(data, ensure_ascii=False)) > 256 * 1024:
                raise ValueError("sidecar.jsonが不正です")
            return service.attach_sidecar(import_id, data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "received"}

    @app.post("/api/midi/imports/{import_id}/preview")
    def preview(import_id: str, body: PreviewRequest):
        get_import(import_id)
        try:
            return service.preview(import_id, target_song_id=body.target_song_id, target_version_id=body.target_version_id,
                                   voice_map=body.voice_map, start_bar=body.start_bar, end_bar=body.end_bar,
                                   quantization=body.quantization, transpose=body.transpose)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/midi/imports/{import_id}/save")
    def save(import_id: str, body: SaveRequest):
        get_import(import_id)
        if not body.confirmed:
            raise HTTPException(409, "保存確認が必要です")
        try:
            version = service.save(import_id, preview_token=body.preview_token, expected_version_id=body.expected_version_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"status": "saved", "version_id": version["id"], "version": {k: v for k, v in version.items() if k != "abc"}}

    @app.post("/api/midi/imports/{import_id}/new-song", status_code=201)
    def new_song(import_id: str, body: NewSongRequest):
        get_import(import_id)
        try:
            voice_map = {}
            for voice, value in body.voice_map.items():
                if isinstance(value, dict):
                    voice_map[voice] = (value.get("track"), value.get("channel"))
                else:
                    voice_map[voice] = value
            version = service.save_new_song(import_id, voice_map=voice_map, title=body.title,
                                            style=body.style, lyrics=body.lyrics, seed=body.seed,
                                            bpm=body.bpm, meter=(body.meter_n, body.meter_d), key=body.key)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "saved", "song_id": version["song_id"], "version_id": version["id"], "cot": "melody"}

    @app.post("/api/score-versions/{version_id}/generate", status_code=202)
    def generate_version(version_id: str, body: GenerateVersionRequest):
        with queue.store.lifecycle_lock:
            return generate_version_locked(version_id, body)

    def generate_version_locked(version_id: str, body: GenerateVersionRequest):
        try:
            version = queue.store.get_score_version(version_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not version:
            raise HTTPException(404, "譜面版が見つかりません")
        requested_cot = body.cot
        if requested_cot is None:
            requested_cot = "full" if has_chords(version["abc"]) else "melody"
        if requested_cot == "melody" and has_chords(version["abc"]):
            raise HTTPException(422, "コード付きABCはfullで生成してください")
        if requested_cot not in ("full", "melody"):
            raise HTTPException(422, "譜面版の生成cotはfullまたはmelodyです")
        if body.seed_mode == "fixed" and body.seed is None:
            raise HTTPException(422, "固定Seedを指定してください")
        spec = {"title": body.title or version["conditions"].get("title", ""), "style": body.style,
                "lyrics": body.lyrics, "cot": requested_cot, "seed_mode": body.seed_mode,
                "seed": body.seed, "candidate_count": body.candidate_count, "cfg_scale": body.cfg_scale,
                "source_id": version["song_id"], "abc": version["abc"], "score_version_id": version_id}
        try:
            return submit(spec, body.submission_key, {"score_version_id": version_id, "abc_sha256": version["abc_sha256"], "style": body.style, "lyrics": body.lyrics, "seed_mode": body.seed_mode, "seed": body.seed, "cot": requested_cot})
        except HTTPException:
            raise
