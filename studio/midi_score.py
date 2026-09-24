"""Native YuE ABC and MIDI bridge.

The installed official abc_tools parser remains authoritative. This module
only maps its normalized Fraction events to SMF ticks and back.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction

from .midi_codec import MidiFile, MidiNote, MidiError, parse as parse_midi, write as write_midi, sha256

PPQ = 15360
VOICES = ("Vocal", "Ins")


@dataclass(frozen=True)
class ScoreNote:
    voice: str
    onset: Fraction
    pitch: int
    duration: Fraction


def _fraction(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(value)


def load_score(tools, abc):
    try:
        score = tools.parse_abc(abc)
    except Exception as exc:
        raise ValueError(f"YuE native ABCを解析できません: {exc}") from exc
    notes = []
    for voice in VOICES:
        for onset, pitch, duration in score.voices[voice].notes:
            notes.append(ScoreNote(voice, _fraction(onset), int(pitch), _fraction(duration)))
    return score, notes


def normalize_notes(notes):
    return [{"voice": n.voice, "onset": str(n.onset), "pitch": n.pitch, "duration": str(n.duration)}
            for n in sorted(notes, key=lambda x: (x.onset, x.voice, x.pitch, x.duration))]


def _ticks(value, ppq=PPQ):
    result = value * ppq
    if result.denominator != 1:
        raise ValueError(f"MIDI tickへ正確に変換できない拍位置です: {value}")
    return int(result)


def _sections(score, abc):
    """Recover each section through all following Vocal groups."""
    lines = abc.splitlines()
    result, pending, active, bar_index = [], None, None, 0
    occurrences = {}
    def finish(end_bar):
        nonlocal active
        if not active:
            return
        name, start = active
        occurrences[name] = occurrences.get(name, 0) + 1
        result.append({"id": f"{name}@{occurrences[name]}", "name": name,
                       "start_bar": start, "end_bar": end_bar, "confidence": "explicit"})
        active = None
    for index, line in enumerate(lines):
        if line.startswith("% "):
            if active:
                finish(bar_index)
            name = line[2:].strip().lower()
            pending = name if name in {"intro", "verse", "chorus", "bridge", "outro"} else pending
        elif line == "V: Vocal":
            start = bar_index + 1
            music = ""
            cursor = index + 1
            while cursor < len(lines) and lines[cursor].startswith(("M:", "K:")):
                cursor += 1
            if cursor < len(lines):
                music = lines[cursor]
            count = _raw_bar_count(music)
            if pending:
                active = (pending, start)
                pending = None
            bar_index += count
    finish(bar_index)
    return result


def detect_sections(tools, abc):
    score, _ = load_score(tools, abc)
    return _sections(score, abc)


def _raw_bar_count(music):
    if not music.endswith("|"):
        return 0
    count = 0
    for part in music[:-1].split("|"):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"Z([2-4])?", part)
        count += int(match.group(1) or 1) if match else 1
    return count


def _timeline(score, start, end):
    bars = score.voices["Vocal"].bars
    effective = bars[0][2]
    for beat, _length, value in bars:
        if beat <= start:
            effective = value
        if beat >= end:
            break
    meter = [(start, effective[0], effective[1], 24, 8)]
    last = effective
    for beat, _length, value in bars:
        if start < beat < end and value != last:
            meter.append((beat, value[0], value[1], 24, 8))
            last = value
    keys = []
    for beat, key in score.voices["Vocal"].keys:
        if beat < end:
            if beat >= start:
                keys.append((beat, key))
            elif not keys:
                keys.append((start, key))
    return meter, keys


def export_abc(tools, abc, *, voices=VOICES, start_bar=1, end_bar=None, section=None, source=None, version_id=None,
               song_id=None, job_id=None):
    score, all_notes = load_score(tools, abc)
    bars = score.voices["Vocal"].bars
    if not bars:
        raise ValueError("ABCに小節がありません")
    sections = _sections(score, abc)
    if section:
        candidates = [item for item in sections if item["id"] == section.lower() or item["name"] == section.lower()]
        if not candidates:
            raise ValueError(f"指定セクションがABCから検出できません: {section}")
        if start_bar == 1 and end_bar is None:
            start_bar, end_bar = candidates[0]["start_bar"], candidates[0]["end_bar"]
    if end_bar is None:
        end_bar = len(bars)
    if not 1 <= start_bar <= end_bar <= len(bars):
        raise ValueError("小節範囲が不正です")
    start = bars[start_bar - 1][0]
    end = bars[end_bar - 1][0] + bars[end_bar - 1][1]
    selected = [n for n in all_notes if n.voice in voices and n.onset < end and n.onset + n.duration > start]
    tracks = []
    channel_by_voice = {"Vocal": 0, "Ins": 1}
    for voice in voices:
        midi_notes = []
        for note in selected:
            if note.voice != voice:
                continue
            on = max(note.onset, start)
            off = min(note.onset + note.duration, end)
            midi_notes.append(MidiNote(channel_by_voice[voice], note.pitch, 100, _ticks(on - start), _ticks(off - start), channel_by_voice[voice]))
        from .midi_codec import MidiTrack
        tracks.append(MidiTrack(name=voice, notes=midi_notes, end_tick=_ticks(end - start)))
    bpm = int(score.bpm)
    meter_map, key_map = _timeline(score, start, end)
    tempos = [(0, int(60_000_000 / bpm))]
    meters = [(_ticks(beat - start), n, d, clocks, notes) for beat, n, d, clocks, notes in meter_map]
    keys = [(_ticks(beat - start), _key_signature(key), 1 if key.endswith("m") else 0) for beat, key in key_map]
    # A conductor track must end at the requested musical range even if all
    # selected voices are rests.
    midi = MidiFile(1, PPQ, tracks, tempo=tempos, meters=meters, keys=keys,
                    markers=_section_markers(sections, bars, start, end))
    data = write_midi(midi)
    sidecar = build_sidecar(abc, score, all_notes, midi, data, start_bar, end_bar, voices,
                            source=source, version_id=version_id, song_id=song_id, job_id=job_id)
    sidecar["score"]["sections"] = sections
    sidecar["score"]["chords"] = [[str(beat), chord] for beat, chord in score.voices["Vocal"].chords]
    sidecar["score"]["meter_map"] = [[str(beat), value[0], value[1]] for beat, _, value in bars]
    sidecar["score"]["key_map"] = [[str(beat), key] for beat, key in score.voices["Vocal"].keys]
    sidecar["score"]["source_normalized_notes"] = normalize_notes(all_notes)
    sidecar["boundaries"] = _boundaries(all_notes, start, end, abc, score)
    return data, sidecar


def _key_signature(key):
    # The official helper's key table is the authoritative spelling; this
    # maps its standard major/minor names to SMF fifths.
    major = {"Cb": -7, "Gb": -6, "Db": -5, "Ab": -4, "Eb": -3, "Bb": -2, "F": -1,
             "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7}
    if key.endswith("m"):
        relative = {"Abm": -7, "Ebm": -6, "Bbm": -5, "Fm": -4, "Cm": -3, "Gm": -2, "Dm": -1,
                    "Am": 0, "Em": 1, "Bm": 2, "F#m": 3, "C#m": 4, "G#m": 5, "D#m": 6, "A#m": 7}
        return relative.get(key, 0)
    return major.get(key, 0)


def _section_markers(sections, bars, start, end):
    markers = []
    # Sections contain bar numbers; callers have already parsed the source.
    # The bar timeline is reconstructed by the caller's score and injected by
    # converting the first bar of each explicit section below.
    # This helper remains deliberately small so malformed comments never alter
    # musical timing.
    for item in sections:
        index = item["start_bar"] - 1
        if index < 0 or index >= len(bars):
            continue
        beat = bars[index][0]
        if start <= beat < end:
            markers.append((_ticks(beat - start), item["name"]))
    return markers


def _boundaries(notes, start, end, abc, score):
    crossing = []
    for note in notes:
        if note.onset < start < note.onset + note.duration or note.onset < end < note.onset + note.duration:
            crossing.append({"voice": note.voice, "onset": str(note.onset), "pitch": note.pitch,
                             "duration": str(note.duration), "clip_start": str(max(note.onset, start)),
                             "clip_end": str(min(note.onset + note.duration, end))})
    tie_fragments = []
    for line_index, voice in score.music_lines.items():
        line = abc.splitlines()[line_index]
        if "-" in line:
            tie_fragments.append({"voice": voice, "line": line_index + 1, "text": line})
    return {"crossing_notes": crossing, "tie_fragments": tie_fragments}


def build_sidecar(abc, score, notes, midi, midi_bytes, start_bar, end_bar, voices,
                  *, source=None, version_id=None, song_id=None, job_id=None):
    bars = score.voices["Vocal"].bars
    start = bars[start_bar - 1][0]
    end = bars[end_bar - 1][0] + bars[end_bar - 1][1]
    origin = {"song_id": song_id, "job_id": job_id, "version_id": version_id,
              "abc_sha256": sha256(abc.encode("utf-8")), "snapshot_sha256": sha256(abc.encode("utf-8"))}
    selected = [n for n in notes if n.voice in voices and n.onset < end and n.onset + n.duration > start]
    source = source or {}
    return {"schema_version": 1, "export_id": None, "converter_version": "stdlib-midi-1",
            "source": origin, "scope": {"voices": list(voices), "start_bar": start_bar, "end_bar": end_bar,
            "start_beat": str(start), "length_beats": str(end - start), "total_beats": str(bars[-1][0] + bars[-1][1]), "origin_beat": str(start)},
            "midi": {"ppq": midi.ppq, "type": midi.fmt, "midi_sha256": sha256(midi_bytes),
                     "track_channel_map": {str(i + 1): {"voice": voice, "channel": {"Vocal": 0, "Ins": 1}[voice]} for i, voice in enumerate(voices)}},
            "score": {"normalized_notes": normalize_notes(selected), "bars": len(bars), "meter_map": [],
                      "tempo_map": [[0, score.bpm]], "key_map": [], "sections": [], "chords": [],
                      "lyrics": source.get("lyrics"), "style": source.get("style"), "seed": source.get("seed"),
                      "lyric_alignment_status": "unverified"},
            "boundaries": {"crossing_notes": [], "tie_fragments": []},
            "conversion": {"quantization": "none", "tick_error": {"max": "0", "sum": "0"}, "unsupported_events": [], "losses": midi.losses}}


_KEY_ACCIDENTALS = {
    "Cb": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1, "F": -1},
    "Gb": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1, "C": -1},
    "Db": {"B": -1, "E": -1, "A": -1, "D": -1, "G": -1}, "Ab": {"B": -1, "E": -1, "A": -1, "D": -1},
    "Eb": {"B": -1, "E": -1, "A": -1}, "Bb": {"B": -1, "E": -1}, "F": {"B": -1},
    "C": {}, "G": {"F": 1}, "D": {"F": 1, "C": 1}, "A": {"F": 1, "C": 1, "G": 1},
    "E": {"F": 1, "C": 1, "G": 1, "D": 1}, "B": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1},
    "F#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1}, "C#": {"F": 1, "C": 1, "G": 1, "D": 1, "A": 1, "E": 1, "B": 1},
}


def _abc_note(pitch, duration, unit, key="C", tie=False):
    # Native parser's octave convention is C=60 and lower-case C=72.
    flat = key in {"Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F"} or (key.endswith("m") and key[:-1] in {"Ab", "Eb", "Bb", "F", "C", "G", "D"})
    names = [("C", 0), ("_D" if flat else "^C", 1), ("D", 2), ("_E" if flat else "^D", 3), ("E", 4), ("F", 5),
             ("_G" if flat else "^F", 6), ("G", 7), ("_A" if flat else "^G", 8), ("A", 9), ("_B" if flat else "^A", 10), ("B", 11)]
    octave, pc = divmod(pitch - 60, 12)
    token, _ = names[pc]
    letter = token[-1].upper()
    written_acc = -1 if token.startswith("_") else (1 if token.startswith("^") else 0)
    minor_relative = {"Am": "C", "Em": "G", "Bm": "D", "F#m": "A", "C#m": "E", "G#m": "B", "D#m": "F#", "A#m": "C#",
                      "Dm": "F", "Gm": "Bb", "Cm": "Eb", "Fm": "Ab", "Bbm": "Db", "Ebm": "Gb", "Abm": "Cb"}
    base_acc = _KEY_ACCIDENTALS.get(minor_relative.get(key, key), {}).get(letter, 0)
    # Explicit ABC accidentals are absolute for the written pitch. Always
    # reset the local accidental state so same-letter notes in another octave
    # cannot inherit an earlier accidental unexpectedly.
    prefix = {0: "=", 1: "^", 2: "^^", -1: "_", -2: "__"}.get(written_acc)
    if prefix is None:
        raise ValueError(f"キー {key} でピッチ {pitch} を表記できません")
    token = prefix + letter
    if octave >= 1:
        token = token.lower() + ("'" * (octave - 1))
    elif octave < 0:
        token += "," * (-octave)
    units = Fraction(duration, unit * 4)
    if units.denominator != 1 or int(units) not in {1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48}:
        raise ValueError(f"音価 {duration} をnative ABCへ変換できません")
    return token + ("" if int(units) == 1 else str(int(units))) + ("-" if tie else "")


def _split_units(duration, unit):
    value = duration / (unit * 4)
    if value.denominator != 1 or value <= 0:
        raise ValueError(f"音価 {duration} をnative ABCへ変換できません")
    remaining, parts = int(value), []
    allowed = (48, 32, 24, 16, 12, 8, 6, 4, 3, 2, 1)
    while remaining:
        part = next((candidate for candidate in allowed if candidate <= remaining), None)
        if part is None:
            raise ValueError(f"音価 {duration} はYuE2許容倍率へ分割できません")
        parts.append(part); remaining -= part
    return parts


def _bar_tokens(notes, bar_start, bar_length, unit, *, chords=(), key="C"):
    local = sorted((n for n in notes if n.onset < bar_start + bar_length and n.onset + n.duration > bar_start), key=lambda n: n.onset)
    tokens, cursor = [], bar_start
    chords = sorted((beat, name) for beat, name in chords if bar_start <= beat < bar_start + bar_length)
    chord_index = 0
    for note in local:
        onset = max(note.onset, bar_start)
        if onset > cursor:
            rest_points = [cursor] + [beat for beat, _ in chords if cursor < beat < onset] + [onset]
            for rest_start, rest_end in zip(rest_points, rest_points[1:]):
                while chord_index < len(chords) and chords[chord_index][0] <= rest_start:
                    tokens.append(f'"{chords[chord_index][1]}"'); chord_index += 1
                for part in _split_units(rest_end - rest_start, unit):
                    tokens.append("z" + ("" if part == 1 else str(part)))
            cursor = onset
        end = min(note.onset + note.duration, bar_start + bar_length)
        split_points = [beat for beat, _ in chords if onset < beat < end]
        points = [onset] + split_points + [end]
        for index, point in enumerate(points[:-1]):
            segment_end = points[index + 1]
            while chord_index < len(chords) and chords[chord_index][0] <= point:
                tokens.append(f'"{chords[chord_index][1]}"'); chord_index += 1
            parts = _split_units(segment_end - point, unit)
            for part_index, part in enumerate(parts):
                is_last = part_index == len(parts) - 1
                continuation = segment_end < note.onset + note.duration or not is_last
                tokens.append(_abc_note(note.pitch, unit * 4 * part, unit, key, tie=continuation))
            cursor = segment_end
    if cursor < bar_start + bar_length:
        rest = bar_start + bar_length - cursor
        while chord_index < len(chords) and chords[chord_index][0] <= cursor:
            tokens.append(f'"{chords[chord_index][1]}"'); chord_index += 1
        for part in _split_units(rest, unit):
            tokens.append("z" + ("" if part == 1 else str(part)))
    while chord_index < len(chords):
        tokens.append(f'"{chords[chord_index][1]}"'); chord_index += 1
    return "".join(tokens)


def serialize_edited(tools, abc, edits, *, start_bar, end_bar, voices=VOICES):
    """Write selected full bars, preserving headers and section lines.

    `edits` is a mapping voice -> normalized note dictionaries. Unselected
    bars are left byte-for-byte intact by replacing only the corresponding
    bar text in each native music line.
    """
    score, original = load_score(tools, abc)
    bars = score.voices["Vocal"].bars
    if not 1 <= start_bar <= end_bar <= len(bars):
        raise ValueError("小節範囲が不正です")
    unit = score.unit
    selected_start, selected_end = bars[start_bar - 1][0], bars[end_bar - 1][0] + bars[end_bar - 1][1]
    for voice in VOICES:
        changes = [beat for beat, _ in score.voices[voice].keys if selected_start < beat < selected_end]
        if changes:
            raise ValueError("対象範囲内の調変更は初期版では編集できません")
    if any(bars[index][2] != bars[start_bar - 1][2] for index in range(start_bar - 1, end_bar)):
        raise ValueError("対象範囲内の拍子変更は初期版では編集できません")
    parsed = {voice: [ScoreNote(voice, Fraction(x["onset"]), int(x["pitch"]), Fraction(x["duration"])) for x in values]
              for voice, values in edits.items()}
    lines = abc.splitlines()
    # Rebuild each music line from the official parser's bar sequence. This
    # keeps comments and all headers, while edited bars use normalized notes.
    cursor_by_voice = {v: 0 for v in VOICES}
    def physical(raw):
        match = re.fullmatch(r"Z([2-4])?", raw.strip())
        return ["Z"] * int(match.group(1) or 1) if match else [raw.strip()]

    def compressed(values):
        output = []
        index = 0
        while index < len(values):
            if values[index] == "Z":
                end = index
                while end < len(values) and values[end] == "Z" and end - index < 4:
                    end += 1
                count = end - index
                output.append("Z" if count == 1 else f"Z{count}")
                index = end
            else:
                output.append(values[index]); index += 1
        return output

    def key_at(voice, beat):
        current = score.voices[voice].key
        for position, value in score.voices[voice].keys:
            if position <= beat: current = value
        return current

    for line_index, voice in score.music_lines.items():
        line = lines[line_index]
        raw_bars = [part.strip() for part in line[:-1].split("|")]
        physical_bars = [bar for raw in raw_bars for bar in physical(raw)]
        start_index = cursor_by_voice[voice]
        current_bars = score.voices[voice].bars[start_index:start_index + len(physical_bars)]
        selected_here = any(bar_start < selected_end and bar_start + bar_length > selected_start for bar_start, bar_length, _ in current_bars)
        if not selected_here:
            cursor_by_voice[voice] += len(physical_bars)
            continue
        output = []
        for raw, (bar_start, bar_length, _meter) in zip(physical_bars, current_bars):
            if voice in parsed and bar_start < selected_end and bar_start + bar_length > selected_start:
                chords = score.voices["Vocal"].chords if voice == "Vocal" else ()
                output.append(_bar_tokens(parsed[voice], bar_start, bar_length, unit, chords=chords, key=key_at(voice, bar_start)))
            else:
                output.append(raw)
        lines[line_index] = "|".join(compressed(output)) + "|"
        cursor_by_voice[voice] += len(physical_bars)
    result = "\n".join(lines) + ("\n" if abc.endswith("\n") else "")
    try:
        after = tools.parse_abc(result)
    except Exception as exc:
        raise ValueError(f"編集後ABCの検証に失敗しました: {exc}") from exc
    if after.voices["Vocal"].bars != score.voices["Vocal"].bars or after.voices["Ins"].bars != score.voices["Ins"].bars:
        raise ValueError("編集後ABCの小節・拍子グリッドが変化しました")
    if after.voices["Vocal"].chords != score.voices["Vocal"].chords:
        raise ValueError("編集後ABCでコード位置が変化しました")
    for voice in VOICES:
        before_notes = score.voices[voice].notes
        after_notes = after.voices[voice].notes
        if voice not in parsed:
            if before_notes != after_notes:
                raise ValueError(f"未変更声部 {voice} が変化しました")
            continue
        before_out = [n for n in before_notes if n[0] < selected_start or n[0] >= selected_end]
        after_out = [n for n in after_notes if n[0] < selected_start or n[0] >= selected_end]
        if before_out != after_out:
            raise ValueError(f"{voice}の対象範囲外の音符が変化しました")
        expected_in = sorted((n.onset, n.pitch, n.duration) for n in parsed[voice] if selected_start <= n.onset < selected_end)
        actual_in = sorted((n[0], n[1], n[2]) for n in after_notes if selected_start <= n[0] < selected_end)
        if expected_in != actual_in:
            raise ValueError(f"{voice}の編集後正規化音符が希望値と一致しません")
    return result


def import_midi(tools, abc, midi_bytes, *, voice_map, start_bar, end_bar, quantization="none", transpose=0):
    midi = parse_midi(midi_bytes)
    if any(tick > 0 for tick, _ in midi.tempo) or any(tick > 0 for tick, *_ in midi.meters) or any(tick > 0 for tick, *_ in midi.keys):
        raise ValueError("MIDI途中のtempo/meter/key変更はnative ABCへ安全に保持できないため取り込みを中止しました")
    score, original = load_score(tools, abc)
    bars = score.voices["Vocal"].bars
    if not 1 <= start_bar <= end_bar <= len(bars):
        raise ValueError("小節範囲が不正です")
    ppq = midi.ppq
    start_tick = 0
    selected_start = bars[start_bar - 1][0]
    selected_end = bars[end_bar - 1][0] + bars[end_bar - 1][1]
    length = selected_end - selected_start
    midi_length = max([track.end_tick for track in midi.tracks] + [0])
    expected_ticks = length * ppq
    if expected_ticks.denominator != 1 or midi_length != int(expected_ticks):
        raise ValueError(f"MIDI終端長 {midi_length}/{ppq} と対象範囲長 {expected_ticks} が一致しません。休符補完・倍率調整・切り詰めを明示してください")
    edits = {}
    changes = []
    if not voice_map:
        raise ValueError("VocalまたはInsに少なくとも1トラックを割り当ててください")
    grid = {"none": None, "1/8": Fraction(1, 2), "1/16": Fraction(1, 4), "1/32": Fraction(1, 8), "1/64": Fraction(1, 16)}.get(quantization)
    if quantization not in {"none", "1/8", "1/16", "1/32", "1/64"}:
        raise ValueError("対応していない量子化指定です")
    for voice, assignment in voice_map.items():
        if isinstance(assignment, tuple):
            track_index, channel = assignment
        else:
            track_index, channel = assignment, None
        if voice not in VOICES or not isinstance(track_index, int) or not 0 <= track_index < len(midi.tracks):
            raise ValueError("MIDIトラック割当が不正です")
        if channel is not None and (not isinstance(channel, int) or not 0 <= channel <= 15):
            raise ValueError("MIDIチャンネル割当が不正です")
        selected_notes = [n for n in midi.tracks[track_index].notes if channel is None or n.channel == channel]
        if channel is None and len({n.channel for n in selected_notes}) > 1:
            raise ValueError("track内に複数チャンネルがあります。track×channelを明示してください")
        selected_notes.sort(key=lambda n: (n.start, n.end, n.pitch))
        if any(left.start < right.start < left.end for left, right in zip(selected_notes, selected_notes[1:])):
            raise ValueError(f"{voice}に同時発音する多声ノートがあります。単旋律トラックを選択してください")
        result = []
        max_shift = Fraction(0); total_shift = Fraction(0); changed = 0
        for note in selected_notes:
            if note.channel == 9:
                raise ValueError("ドラムチャンネルはnative ABCへ変換できません")
            onset = Fraction(note.start - start_tick, ppq)
            duration = Fraction(note.end - note.start, ppq)
            if duration <= 0:
                raise ValueError("ゼロ長のMIDIノートがあります")
            if grid:
                def snap(value):
                    quotient = value / grid
                    floor = quotient.numerator // quotient.denominator
                    upper = floor + 1
                    return (floor * grid if quotient - floor < upper - quotient else upper * grid)
                snapped_onset = snap(onset); snapped_end = snap(onset + duration)
                if snapped_end <= snapped_onset:
                    raise ValueError("量子化でゼロ長ノートが発生しました")
                shift = abs(snapped_onset - onset) + abs(snapped_end - (onset + duration))
                max_shift = max(max_shift, shift); total_shift += shift; changed += int(shift != 0)
                changes.append({"voice": voice, "from": [str(onset), str(duration)], "to": [str(snapped_onset), str(snapped_end - snapped_onset)], "shift": str(shift)})
                onset, duration = snapped_onset, snapped_end - snapped_onset
            onset += selected_start
            if onset < selected_start or onset >= selected_end or onset + duration > selected_end:
                raise ValueError("MIDIノートが指定小節範囲外です")
            pitch = note.pitch + transpose
            if not 0 <= pitch <= 127:
                raise ValueError(f"移調後の音高 {pitch} がMIDI範囲外です")
            result.append({"onset": str(onset), "pitch": pitch, "duration": str(duration)})
        edits[voice] = result
    return edits, {"changes": changes, "changed_notes": changed, "max_shift": str(max_shift),
                   "total_shift": str(total_shift), "losses": midi.losses, "ppq": ppq,
                   "range_length": str(length), "estimated_length": str(length), "transpose": transpose, "boundary_policy": "reject"}


def new_abc_from_midi(tools, midi_bytes, *, voice_map, bpm=120, meter=(4, 4), key="C"):
    """Create a chord-free complete native ABC from an explicitly mapped MIDI."""
    midi = parse_midi(midi_bytes)
    if any(tick > 0 for tick, _ in midi.tempo) or any(tick > 0 for tick, *_ in midi.meters) or any(tick > 0 for tick, *_ in midi.keys):
        raise ValueError("MIDI途中のtempo/meter/key変更は新規native ABCへ安全に保持できないため拒否しました")
    initial_meters = {(n, d) for tick, n, d, *_ in midi.meters if tick == 0}
    if initial_meters and initial_meters != {meter}:
        raise ValueError(f"MIDIの初期拍子 {sorted(initial_meters)} と指定拍子 {meter} が一致しません")
    if not isinstance(bpm, int) or not 1 <= bpm <= 999:
        raise ValueError("テンポは1〜999の整数で指定してください")
    if meter not in {(4, 4), (3, 4), (6, 8), (2, 4)}:
        raise ValueError("初期MIDI新規曲は4/4、3/4、6/8、2/4だけを使用できます")
    unit = Fraction(1, 32)
    bar_length = Fraction(4 * meter[0], meter[1])
    mapped = {}
    last = Fraction(0)
    for voice, assignment in voice_map.items():
        if voice not in VOICES:
            raise ValueError("VocalまたはInsを割り当ててください")
        track, channel = assignment if isinstance(assignment, tuple) else (assignment, None)
        if not isinstance(track, int) or not 0 <= track < len(midi.tracks):
            raise ValueError("MIDIトラック割当が不正です")
        notes = [n for n in midi.tracks[track].notes if channel is None or n.channel == channel]
        if channel is None and len({n.channel for n in notes}) > 1:
            raise ValueError("複数チャンネルのtrackはchannelを明示してください")
        if any(n.channel == 9 for n in notes):
            raise ValueError("ドラムチャンネルはnative ABCへ変換できません")
        converted = []
        for note in notes:
            onset = Fraction(note.start, midi.ppq)
            duration = Fraction(note.end - note.start, midi.ppq)
            if duration <= 0:
                raise ValueError("ゼロ長MIDIノートがあります")
            converted.append(ScoreNote(voice, onset, note.pitch, duration))
            last = max(last, onset + duration)
        mapped[voice] = converted
    if not mapped or last <= 0:
        raise ValueError("VocalまたはInsの音符を1つ以上割り当ててください")
    # Preserve the SMF end-of-track, including a deliberate trailing rest.
    midi_eot = max((track.end_tick for track in midi.tracks), default=0)
    last = max(last, Fraction(midi_eot, midi.ppq))
    bar_count = last // bar_length
    if last % bar_length:
        bar_count += 1
    lines = ["X:1", "T:", f"M:{meter[0]}/{meter[1]}", "L:1/32", f"Q:1/4={bpm}",
             'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
             'V: Ins clef=treble name="Ins Melody" snm="Inst."', f"K:{key}"]
    for index in range(int(bar_count)):
        start = index * bar_length
        lines += ["V: Vocal", _bar_tokens(mapped.get("Vocal", []), start, bar_length, unit, key=key) + "|",
                  "V: Ins", _bar_tokens(mapped.get("Ins", []), start, bar_length, unit, key=key) + "|"]
    result = "\n".join(lines) + "\n"
    try:
        parsed_score = tools.parse_abc(result)
    except Exception as exc:
        raise ValueError(f"MIDIから作成したABCの検証に失敗しました: {exc}") from exc
    for voice in VOICES:
        expected = sorted((note.onset, note.pitch, note.duration) for note in mapped.get(voice, []))
        actual = sorted(tuple(note) for note in parsed_score.voices[voice].notes)
        if expected != actual:
            raise ValueError(f"新規ABCの{voice}正規化音符が元MIDIと一致しません")
    return result, {"bpm": bpm, "meter": list(meter), "key": key, "bars": int(bar_count), "cot": "melody",
                    "warnings": ["コードなしの新規native ABCです", "歌詞対応は未検証です"]}
