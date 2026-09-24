"""CPU-only MIDI export/import orchestration."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
import zipfile
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from .midi_codec import MidiError, parse as parse_midi
from .midi_score import export_abc, import_midi, serialize_edited, new_abc_from_midi, load_score
from .storage import now, write_bytes_atomic, write_json

MAX_UPLOAD = 8 * 1024 * 1024


class MidiService:
    def __init__(self, config, store, covers):
        self.config, self.store, self.covers = config, store, covers
        self._cpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="midi-cpu")
        # Queue bootstrap owns schema creation. Recovery is retried lazily by
        # MIDI operations (and explicitly after Store.initialize in Queue).
        self._recovery_pending = True

    def _recover_midi_tasks(self):
        if not self._recovery_pending:
            return
        try:
            self.store.recover_midi_tasks()
        except sqlite3.OperationalError:
            # Queue bootstrap creates/migrates the SQLite schema asynchronously.
            # Retry before the first MIDI operation instead of breaking app startup.
            return
        self._recovery_pending = False

    def _tools(self):
        return self.covers.tools()

    def version_for_job(self, job_id):
        self._recover_midi_tasks()
        job = self.store.get(job_id)
        if not job:
            raise ValueError("曲が見つかりません")
        versions = self.store.list_score_versions(job_id)
        if versions:
            return versions[0]
        try:
            abc_path, _ = self.store.artifact(job_id, "abc")
            abc = abc_path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise ValueError("この曲には保存済みABCがありません。Coverで採譜するかMIDIから新規作成してください") from exc
        return self.store.create_score_version(song_id=job_id, abc=abc,
            conditions={k: job.get(k) for k in ("title", "style", "lyrics", "seed", "cot", "cfg_scale")},
            validation={"source": "job artifact"}, source_job_id=job_id,
            edit_summary={"kind": "initial_snapshot"})

    def export(self, version, *, voices, start_bar, end_bar, section=None, submission_key=None):
        self._recover_midi_tasks()
        input_sha256 = hashlib.sha256(json.dumps({"version": version["id"], "abc": version["abc_sha256"],
                                                  "voices": voices, "start_bar": start_bar, "end_bar": end_bar,
                                                  "section": section}, sort_keys=True).encode()).hexdigest()
        existing = self.store.find_midi_export(version["id"], submission_key, input_sha256)
        if existing:
            return existing["id"], existing["metadata"]
        export_id = uuid.uuid4().hex
        root = self.store.root / "midi" / "exports" / export_id
        root.mkdir(parents=True, exist_ok=False)
        metadata = {"export_id": export_id, "version_id": version["id"], "voices": voices,
                    "start_bar": start_bar, "end_bar": end_bar, "section": section, "state": "queued"}
        self.store.create_midi_export(export_id, version["id"], metadata, state="queued", submission_key=submission_key, input_sha256=input_sha256)
        try:
            self.store.update_midi_export(export_id, state="converting")
            midi, sidecar = export_abc(self._tools(), version["abc"], voices=voices,
                                       start_bar=start_bar, end_bar=end_bar, section=section,
                                       version_id=version["id"], song_id=version["song_id"],
                                       source=version.get("conditions"))
            return self._write_export(version, midi, sidecar, export_id, root, metadata, input_sha256)
        except Exception as exc:
            self.store.update_midi_export(export_id, state="failed", error_json={"code": "export_failed", "message": str(exc)})
            raise

    def _write_export(self, version, midi, sidecar, export_id, root, metadata, input_sha256):
        sidecar["export_id"] = export_id
        sidecar["midi"]["midi_sha256"] = hashlib.sha256(midi).hexdigest()
        if len(json.dumps(sidecar, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
            root.rmdir()
            raise ValueError("sidecar.jsonが256 KiBを超えるため、この範囲のMIDIを書き出せません")
        write_bytes_atomic(root / "score.mid", midi)
        write_bytes_atomic(root / "source.abc", version["abc"].encode())
        write_json(root / "sidecar.json", sidecar)
        (root / "README.txt").write_text(
            "YuE2 native ABCから書き出したMIDIです。MIDI編集後はsidecar.jsonと一緒に取り込んでください。\n"
            f"export_id={export_id}\n", encoding="utf-8")
        with zipfile.ZipFile(root / "bundle.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in ("score.mid", "source.abc", "sidecar.json", "README.txt"):
                bundle.write(root / name, arcname=name)
        metadata.update({"state": "ready", "sidecar": sidecar})
        self.store.update_midi_export(export_id, state="ready", metadata_json=metadata)
        return export_id, metadata

    async def export_async(self, version, *, voices, start_bar, end_bar, section=None, submission_key=None):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._cpu_executor, lambda: self.export(version, voices=voices, start_bar=start_bar, end_bar=end_bar, section=section, submission_key=submission_key))

    def export_file(self, export_id, kind):
        if not __import__("re").fullmatch(r"[0-9a-f]{32}", export_id):
            raise ValueError("不正なエクスポートIDです")
        record = self.store.get_midi_export(export_id)
        if not record:
            raise ValueError("MIDIエクスポートがありません")
        if record.get("state") != "ready":
            raise ValueError(f"MIDIエクスポートはまだ利用できません: {record.get('state')}")
        names = {"mid": "score.mid", "abc": "source.abc", "sidecar": "sidecar.json", "readme": "README.txt", "bundle": "bundle.zip"}
        if kind not in names:
            raise ValueError("不明なMIDI成果物です")
        path = self.store.root / "midi" / "exports" / export_id / names[kind]
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("MIDI成果物がありません")
        return path

    def upload(self, data, filename, sidecar=None, submission_key=None):
        self._recover_midi_tasks()
        if len(data) > MAX_UPLOAD or len(data) < 14:
            raise ValueError("MIDIは8 MiB以内で指定してください")
        digest = hashlib.sha256(data).hexdigest()
        existing = self.store.find_midi_import(digest, submission_key)
        if existing:
            return existing["id"], existing.get("analysis", {})
        import_id = uuid.uuid4().hex
        root = self.store.root / "midi" / "imports" / import_id
        root.mkdir(parents=True, exist_ok=False)
        write_bytes_atomic(root / "input.mid", data)
        self.store.create_midi_import(import_id, digest, state="uploaded", submission_key=submission_key)
        self.store.update_midi_import(import_id, state="analyzing")
        try:
            midi = parse_midi(data)
        except (OSError, ValueError) as exc:
            self.store.update_midi_import(import_id, state="failed", error_json={"code": "midi_invalid", "message": str(exc)})
            raise
        if sidecar is not None:
            if not isinstance(sidecar, dict) or len(json.dumps(sidecar, ensure_ascii=False)) > 256 * 1024:
                raise ValueError("sidecar.jsonが不正または大きすぎます")
            write_json(root / "sidecar.json", sidecar)
        candidates = []
        for i, track in enumerate(midi.tracks):
            for channel in sorted({n.channel for n in track.notes}):
                notes = [n for n in track.notes if n.channel == channel]
                overlapping = sum(1 for left in notes for right in notes if left is not right and left.start < right.start < left.end)
                candidates.append({"track": i, "channel": channel, "name": track.name, "notes": len(notes),
                                   "range": [min((n.pitch for n in notes), default=None), max((n.pitch for n in notes), default=None)],
                                   "overlaps": overlapping, "role": "unselected"})
        analysis = {"format": midi.fmt, "ppq": midi.ppq, "tracks": [{"index": i, "name": t.name, "notes": len(t.notes),
                    "channels": sorted({n.channel for n in t.notes}), "range": [min((n.pitch for n in t.notes), default=None), max((n.pitch for n in t.notes), default=None)]}
                    for i, t in enumerate(midi.tracks)], "losses": midi.losses}
        analysis["candidates"] = candidates
        self.store.update_midi_import(import_id, state="awaiting_review", analysis_json=analysis)
        return import_id, analysis

    async def upload_async(self, data, filename, sidecar=None, submission_key=None):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._cpu_executor, lambda: self.upload(data, filename, sidecar=sidecar, submission_key=submission_key))

    def attach_sidecar(self, import_id, sidecar):
        """Validate sidecar against server-held export/version and uploaded MIDI."""
        record = self.store.get_midi_import(import_id)
        if not record:
            raise ValueError("MIDI取り込みが見つかりません")
        if not isinstance(sidecar, dict) or sidecar.get("schema_version") != 1:
            raise ValueError("schema_version=1 のsidecar.jsonが必要です")
        required = {"export_id", "source", "scope", "midi", "score", "boundaries", "conversion"}
        if not required <= sidecar.keys():
            raise ValueError("sidecar.jsonの必須フィールドが不足しています")
        source = sidecar["source"]
        version_id = source.get("version_id")
        version = self.store.get_score_version(version_id) if isinstance(version_id, str) else None
        if not version or version["abc_sha256"] != source.get("abc_sha256") or source.get("snapshot_sha256") != version["abc_sha256"]:
            raise ValueError("sidecarの譜面版またはABCハッシュがサーバー記録と一致しません")
        data = self.import_file(import_id)
        midi = parse_midi(data)
        if sidecar["midi"].get("ppq") != midi.ppq:
            raise ValueError("sidecarとMIDIのPPQが一致しません")
        warnings = []
        if sidecar["midi"].get("midi_sha256") != hashlib.sha256(data).hexdigest():
            warnings.append("midi_hash_changed: DAW編集後のMIDIとして差分を受理します")
        export_id = sidecar.get("export_id")
        if export_id:
            export = self.store.get_midi_export(export_id)
            if not export or export["source_version_id"] != version_id:
                raise ValueError("export_idと譜面版の組み合わせが一致しません")
            expected_sidecar = export["metadata"].get("sidecar", {})
            for field in ("source", "scope"):
                if sidecar.get(field) != expected_sidecar.get(field):
                    raise ValueError(f"server exportのsidecar {field} が一致しません")
        scope = sidecar["scope"]
        for key in ("voices", "start_bar", "end_bar", "start_beat", "length_beats", "origin_beat"):
            if key not in scope:
                raise ValueError("sidecarの範囲情報が不足しています")
        root = self.store.root / "midi" / "imports" / import_id
        write_json(root / "sidecar.json", sidecar)
        analysis = record["analysis"]
        analysis["sidecar"] = {"validated": True, "export_id": export_id, "warnings": warnings,
                                "source_version_id": version_id, "scope": scope}
        self.store.update_midi_import(import_id, state="awaiting_review", source_export_id=export_id, analysis_json=analysis)
        return {"validated": True, "warnings": warnings, "analysis": analysis}

    def import_file(self, import_id):
        path = self.store.root / "midi" / "imports" / import_id / "input.mid"
        if not path.is_file() or path.is_symlink():
            raise ValueError("MIDIアップロードがありません")
        return path.read_bytes()

    def preview(self, import_id, *, target_song_id, target_version_id, voice_map, start_bar, end_bar, quantization, transpose=0):
        record = self.store.get_midi_import(import_id)
        version = self.store.get_score_version(target_version_id)
        if not version or version["song_id"] != target_song_id:
            raise ValueError("対象曲と譜面版が一致しません")
        sidecar_meta = (record or {}).get("analysis", {}).get("sidecar") if record else None
        sidecar = None
        sidecar_path = self.store.root / "midi" / "imports" / import_id / "sidecar.json"
        if sidecar_meta and sidecar_path.is_file():
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if sidecar_meta and sidecar_meta.get("validated"):
            scope = sidecar["scope"]
            if start_bar != scope["start_bar"] or end_bar != scope["end_bar"]:
                raise ValueError("sidecar付きMIDIは記録された小節範囲と一致する場合だけ適用できます")
        data = self.import_file(import_id)
        normalized_map = {}
        for voice, value in voice_map.items():
            if value == "ignore":
                continue
            if isinstance(value, dict):
                if not isinstance(value.get("track"), int):
                    raise ValueError("track割当が不正です")
                normalized_map[voice] = (value["track"], value.get("channel"))
            else:
                normalized_map[voice] = (value, None)
        try:
            edits, analysis = import_midi(self._tools(), version["abc"], data, voice_map=normalized_map,
                                          start_bar=start_bar, end_bar=end_bar, quantization=quantization, transpose=transpose)
            if sidecar and sidecar_meta and sidecar_meta.get("validated") and target_version_id == sidecar_meta.get("source_version_id"):
                crossing = sidecar.get("boundaries", {}).get("crossing_notes", [])
                for item in crossing:
                    voice = item.get("voice")
                    if voice in edits:
                        original_onset = Fraction(item["onset"])
                        original_duration = Fraction(item["duration"])
                        scope = sidecar["scope"]
                        range_start = Fraction(scope["start_beat"])
                        range_end = range_start + Fraction(scope["length_beats"])
                        clipped_onset = max(original_onset, range_start)
                        clipped_end = min(original_onset + original_duration, range_end)
                        matching_index = next((index for index, note in enumerate(edits[voice])
                                               if Fraction(note["onset"]) == clipped_onset
                                               and int(note["pitch"]) == int(item["pitch"]) + transpose
                                               and Fraction(note["duration"]) == clipped_end - clipped_onset), None)
                        if matching_index is None:
                            raise ValueError("境界横断音がMIDI上で変更されています。再接続を中止しました")
                        if transpose:
                            raise ValueError("移調を指定した境界横断音は安全に元区間へ再接続できません")
                        # Replace the clipped event; appending would create an overlap.
                        edits[voice][matching_index] = {"onset": item["onset"], "pitch": item["pitch"], "duration": item["duration"]}
                if crossing:
                    analysis["boundary_policy"] = "reconnect_unchanged_boundary_events"
                    analysis.setdefault("warnings", []).append("境界を横断する元音符は、元の正規化イベントへ再接続しました")
            edited = serialize_edited(self._tools(), version["abc"], edits, start_bar=start_bar, end_bar=end_bar)
            before_score, _ = load_score(self._tools(), version["abc"])
            after_score, _ = load_score(self._tools(), edited)
            bars = before_score.voices["Vocal"].bars
            range_start, range_end = bars[start_bar - 1][0], bars[end_bar - 1][0] + bars[end_bar - 1][1]
            diff = []
            changed_bars = set()
            for voice in ("Vocal", "Ins"):
                before = [(n[0], n[1], n[2]) for n in before_score.voices[voice].notes if range_start <= n[0] < range_end]
                after = [(n[0], n[1], n[2]) for n in after_score.voices[voice].notes if range_start <= n[0] < range_end]
                for index in range(max(len(before), len(after))):
                    old = before[index] if index < len(before) else None; new = after[index] if index < len(after) else None
                    if old != new:
                        beat = (new or old)[0]
                        bar_number = next((bar_index + 1 for bar_index, (bar_start, bar_length, _) in enumerate(bars) if bar_start <= beat < bar_start + bar_length), start_bar)
                        changed_bars.add(bar_number)
                        diff.append({"voice": voice, "bar": bar_number, "beat": str(beat),
                                     "original": None if old is None else {"pitch": old[1], "duration": str(old[2])},
                                     "edited": None if new is None else {"pitch": new[1], "duration": str(new[2])}})
            analysis["note_diff"] = diff
            analysis["changed_bars"] = sorted(changed_bars)
        except (OSError, ValueError) as exc:
            self.store.update_midi_import(import_id, state="failed", error_json={"code": "preview_invalid", "message": str(exc)})
            raise
        token = uuid.uuid4().hex
        root = self.store.root / "midi" / "imports" / import_id
        write_bytes_atomic(root / "edited.abc", edited.encode())
        write_json(root / "preview.json", {"token": token, "target_version_id": target_version_id,
                                            "selection": {"voice_map": voice_map, "start_bar": start_bar, "end_bar": end_bar,
                                                           "quantization": quantization, "transpose": transpose}, "analysis": analysis})
        self.store.update_midi_import(import_id, state="awaiting_review", target_song_id=target_song_id,
                                      target_version_id=target_version_id, selection_json={"voice_map": voice_map, "start_bar": start_bar,
                                      "end_bar": end_bar, "quantization": quantization, "transpose": transpose}, analysis_json=analysis)
        return {"preview_token": token, "analysis": analysis, "edited_abc": edited,
                "changed_bars": analysis.get("changed_bars", []), "warnings": ["音声はこのABCから全曲再生成されます"]}

    def save(self, import_id, *, preview_token, expected_version_id, submission=None):
        record = self.store.get_midi_import(import_id)
        if record and record["state"] == "saved" and record.get("result_version_id"):
            existing = self.store.get_score_version(record["result_version_id"])
            if existing:
                return existing
        root = self.store.root / "midi" / "imports" / import_id
        preview = json.loads((root / "preview.json").read_text(encoding="utf-8"))
        if preview["token"] != preview_token or preview["target_version_id"] != expected_version_id:
            raise ValueError("プレビューが古いか条件が一致しません")
        parent = self.store.get_score_version(expected_version_id)
        if not parent:
            raise ValueError("対象譜面版がありません")
        edited = (root / "edited.abc").read_text(encoding="utf-8")
        version = self.store.create_score_version(song_id=parent["song_id"], abc=edited,
            conditions=parent["conditions"], validation={"midi_import_id": import_id},
            edit_summary=preview["analysis"], parent_version_id=parent["id"], expected_head=expected_version_id)
        self.store.update_midi_import(import_id, state="saved", result_version_id=version["id"])
        return version

    def save_new_song(self, import_id, *, voice_map, title, style, lyrics, seed, bpm, meter, key):
        existing_record = self.store.get_midi_import(import_id)
        if existing_record and existing_record["state"] == "saved" and existing_record.get("result_version_id"):
            existing = self.store.get_score_version(existing_record["result_version_id"])
            if existing:
                return existing
        data = self.import_file(import_id)
        abc, validation = new_abc_from_midi(self._tools(), data, voice_map=voice_map, bpm=bpm, meter=meter, key=key)
        song_id = uuid.uuid4().hex
        version = self.store.create_score_version(song_id=song_id, abc=abc,
            conditions={"title": title, "style": style, "lyrics": lyrics, "seed": seed, "cot": "melody"},
            validation=validation, edit_summary={"kind": "midi_standalone", "import_id": import_id})
        self.store.update_midi_import(import_id, state="saved", target_song_id=song_id,
                                      result_version_id=version["id"], analysis_json={"new_song": validation})
        return version
