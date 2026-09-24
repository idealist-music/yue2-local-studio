"""Small, dependency-free Standard MIDI File codec for YuE native scores.

This module intentionally accepts only PPQ Type 0/1 files and the event
families that can be represented by the native two-voice ABC dialect.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

MAX_BYTES = 8 * 1024 * 1024
MAX_TRACKS = 32
MAX_EVENTS = 500_000
MAX_NOTES = 50_000
# Checked against real elapsed MIDI time after parsing. This generous guard
# only prevents integer/resource abuse before tempo metadata is available.
MAX_TICKS = 60 * 60 * 240 * 32767
MAX_SECONDS = 60 * 60


class MidiError(ValueError):
    pass


@dataclass
class MidiNote:
    channel: int
    pitch: int
    velocity: int
    start: int
    end: int
    track: int = 0


@dataclass
class MidiTrack:
    name: str = ""
    notes: list[MidiNote] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    end_tick: int = 0
    is_conductor: bool = False


@dataclass
class MidiFile:
    fmt: int
    ppq: int
    tracks: list[MidiTrack]
    tempo: list[tuple[int, int]] = field(default_factory=list)
    meters: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    keys: list[tuple[int, int, int]] = field(default_factory=list)
    markers: list[tuple[int, str]] = field(default_factory=list)
    losses: list[str] = field(default_factory=list)

    @property
    def notes(self):
        return [note for track in self.tracks for note in track.notes]


def _u32(data, offset):
    if offset + 4 > len(data):
        raise MidiError("MIDIヘッダーが途中で終わっています")
    return struct.unpack_from(">I", data, offset)[0], offset + 4


def _vlq(data, offset):
    value = 0
    for _ in range(4):
        if offset >= len(data):
            raise MidiError("可変長イベントが途中で終わっています")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7f)
        if not byte & 0x80:
            return value, offset
    raise MidiError("MIDIの可変長値が長すぎます")


def _put_vlq(value):
    if value < 0 or value > 0x0fffffff:
        raise MidiError("MIDI tickが範囲外です")
    result = [value & 0x7f]
    value >>= 7
    while value:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    return bytes(reversed(result))


def _text(raw):
    return raw.decode("utf-8", errors="replace")[:200]


def parse(data: bytes) -> MidiFile:
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_BYTES:
        raise MidiError("MIDIは8 MiB以内のSMFを指定してください")
    data = bytes(data)
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("MThdヘッダーがありません。RMIDや破損ファイルは使用できません")
    header_len = struct.unpack_from(">I", data, 4)[0]
    if header_len != 6 or len(data) < 14 + header_len:
        raise MidiError("MIDIヘッダー長が不正です")
    fmt, count, division = struct.unpack_from(">HHH", data, 8)
    if fmt not in (0, 1):
        raise MidiError("Type 0 または Type 1 MIDIだけを使用できます")
    if division & 0x8000:
        raise MidiError("SMPTE分周MIDIはABCへ変換できません")
    if not 1 <= division <= 32767 or count < 1 or count > MAX_TRACKS:
        raise MidiError("MIDIのトラック数またはPPQが不正です")
    offset = 14
    tracks = []
    tempo, meters, keys, markers = [], [], [], []
    total_events = 0
    for track_index in range(count):
        if offset + 8 > len(data) or data[offset:offset + 4] != b"MTrk":
            raise MidiError("MTrkチャンクがありません")
        length = struct.unpack_from(">I", data, offset + 4)[0]
        offset += 8
        end = offset + length
        if end > len(data):
            raise MidiError("MTrkチャンクの長さが不正です")
        tick = 0
        status = None
        active = {}
        track = MidiTrack()
        while offset < end:
            delta, offset = _vlq(data, offset)
            tick += delta
            if tick > MAX_TICKS:
                raise MidiError("MIDIの長さが上限を超えています")
            if offset >= end:
                raise MidiError("MIDIイベントが途中で終わっています")
            byte = data[offset]
            if byte & 0x80:
                status = byte
                offset += 1
            elif status is None:
                raise MidiError("running statusの開始が不正です")
            if status == 0xff:
                if offset >= end:
                    raise MidiError("メタイベントが不正です")
                kind = data[offset]; offset += 1
                size, offset = _vlq(data, offset)
                if offset + size > end:
                    raise MidiError("メタイベントの長さが不正です")
                payload = data[offset:offset + size]; offset += size
                track.events.append({"tick": tick, "type": "meta", "kind": kind})
                if kind == 0x2f:
                    track.end_tick = tick
                elif kind == 0x03:
                    track.name = _text(payload)
                elif kind == 0x51 and len(payload) == 3:
                    tempo.append((tick, int.from_bytes(payload, "big")))
                elif kind == 0x58 and len(payload) >= 2:
                    meters.append((tick, payload[0], payload[1], payload[2] if len(payload) > 2 else 24, payload[3] if len(payload) > 3 else 8))
                elif kind == 0x59 and len(payload) >= 2:
                    keys.append((tick, struct.unpack("b", payload[:1])[0], payload[1]))
                elif kind == 0x06:
                    markers.append((tick, _text(payload)))
                continue
            if status in (0xf0, 0xf7):
                size, offset = _vlq(data, offset)
                if offset + size > end:
                    raise MidiError("SysExイベントの長さが不正です")
                offset += size
                track.events.append({"tick": tick, "type": "sysex"})
                track.events[-1]["loss"] = "SysEx"
                continue
            command, channel = status & 0xf0, status & 0x0f
            width = 1 if command in (0xc0, 0xd0) else 2
            if command not in (0x80, 0x90, 0xa0, 0xb0, 0xc0, 0xd0, 0xe0):
                raise MidiError(f"未対応のMIDIステータス 0x{status:02x}")
            if offset + width > end:
                raise MidiError("MIDIチャンネルイベントが途中で終わっています")
            first = data[offset]; second = data[offset + 1] if width == 2 else None
            offset += width
            total_events += 1
            if total_events > MAX_EVENTS:
                raise MidiError("MIDIイベント数が上限を超えています")
            if command in (0x80, 0x90):
                key = (channel, first)
                is_on = command == 0x90 and second != 0
                if is_on:
                    active.setdefault(key, []).append((tick, second, track_index))
                else:
                    pending = active.get(key, [])
                    if not pending:
                        raise MidiError("対応するnote-onのないnote-offがあります")
                    start, velocity, owner = pending.pop(0)
                    track.notes.append(MidiNote(channel, first, velocity, start, tick, owner))
                    if len(track.notes) > MAX_NOTES:
                        raise MidiError("ノート数が上限を超えています")
                    if not pending:
                        active.pop(key, None)
            elif command in (0xa0, 0xb0, 0xc0, 0xd0, 0xe0):
                track.events.append({"tick": tick, "type": "control", "channel": channel, "command": command})
        if offset != end:
            raise MidiError("MTrk境界を読み取れませんでした")
        if active:
            raise MidiError("note-onに対応しないMIDIノートがあります")
        track.is_conductor = (track_index == 0 and not track.notes and
                              any(event.get("type") == "meta" and event.get("kind") in (0x03, 0x06, 0x51, 0x58, 0x59)
                                  for event in track.events))
        tracks.append(track)
    if offset != len(data):
        raise MidiError("MIDI末尾に不正なデータがあります")
    max_tick = max([track.end_tick for track in tracks] + [note.end for note in [n for track in tracks for n in track.notes]])
    tempo_events = [(0, 500000)] + sorted(tempo)
    collapsed = {}
    for tick, micros in tempo_events:
        collapsed[tick] = micros
    timeline = sorted(collapsed.items())
    elapsed = 0.0
    for index, (tick, micros) in enumerate(timeline):
        if tick >= max_tick:
            break
        next_tick = min(timeline[index + 1][0] if index + 1 < len(timeline) else max_tick, max_tick)
        if next_tick > tick:
            elapsed += (next_tick - tick) * micros / division / 1_000_000
    if elapsed > MAX_SECONDS:
        raise MidiError("MIDIの実時間が60分を超えています")
    losses = []
    if any(e.get("loss") == "SysEx" for t in tracks for e in t.events): losses.append("SysEx")
    if any(e.get("command") in (0xa0, 0xb0, 0xc0, 0xd0, 0xe0) for t in tracks for e in t.events):
        losses.append("program/velocity以外のチャンネルイベント")
    return MidiFile(fmt, division, tracks, tempo, meters, keys, markers, losses)


def _meta(kind, payload=b""):
    return b"\xff" + bytes([kind]) + _put_vlq(len(payload)) + payload


def _track(events, end_tick=None):
    body = bytearray(); previous = 0
    for tick, payload in sorted(events, key=lambda e: (e[0], e[1][0] == 0x90 if e[1] else False)):
        body += _put_vlq(tick - previous); body += payload; previous = tick
    end_tick = max(previous, int(end_tick or 0))
    body += _put_vlq(end_tick - previous) + _meta(0x2f)
    return b"MTrk" + struct.pack(">I", len(body)) + body


def write(midi: MidiFile) -> bytes:
    if midi.fmt not in (0, 1) or not 1 <= midi.ppq <= 32767:
        raise MidiError("出力MIDIの形式またはPPQが不正です")
    tracks = []
    conductor = []
    for tick, micros in midi.tempo:
        conductor.append((tick, _meta(0x51, int(micros).to_bytes(3, "big"))))
    for tick, n, d, clocks, notes in midi.meters:
        conductor.append((tick, _meta(0x58, bytes((n, d, clocks, notes)))))
    for tick, sf, minor in midi.keys:
        conductor.append((tick, _meta(0x59, struct.pack("bb", sf, minor))))
    for tick, marker in midi.markers:
        raw = marker.encode("utf-8")[:200]
        conductor.append((tick, _meta(0x06, raw)))
    conductor_end = max([tick for tick, _ in conductor] + [track.end_tick for track in midi.tracks])
    tracks.append(_track(conductor, conductor_end))
    for source in (track for track in midi.tracks if not track.is_conductor):
        events = []
        if source.name:
            events.append((0, _meta(0x03, source.name.encode("utf-8")[:200])))
        for note in sorted(source.notes, key=lambda n: (n.start, n.pitch, n.end)):
            events.append((note.start, bytes((0x90 | note.channel, note.pitch, max(1, min(127, note.velocity))))))
            events.append((note.end, bytes((0x80 | note.channel, note.pitch, 0))))
        tracks.append(_track(events, source.end_tick))
    fmt = 1 if len(tracks) > 1 else 0
    return b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), midi.ppq) + b"".join(tracks)


def sha256(data):
    return hashlib.sha256(data).hexdigest()
