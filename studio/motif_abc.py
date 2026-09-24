"""Small, deterministic ABC index/editor used by Motif Song.

The native YuE ABC parser remains the authority.  This module only adds
section spans and performs conservative, whole-bar substitutions; unsupported
notation is rejected instead of being guessed at.
"""
from __future__ import annotations

import hashlib
import re
from fractions import Fraction

from .storage import dumps

SECTION_RE = re.compile(r"^%\s*(intro|verse|chorus|bridge|outro|pre-chorus|interlude)(?:\s+(\d+))?\s*$", re.I)
VOICE_RE = re.compile(r"^V:\s*(Vocal|Ins)\b", re.I)


def _tools(covers):
    return covers.tools()


def _groups(text):
    lines = text.splitlines(keepends=True)
    header = []
    groups = []
    section = None
    current = {"Vocal": [], "Ins": []}
    current_start = None
    active_voice = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = SECTION_RE.match(stripped)
        if match:
            if any(current.values()):
                groups.append({"section": section, "voices": current, "line": current_start})
                current = {"Vocal": [], "Ins": []}
            active_voice = None
            section = match.group(1).casefold()
            if match.group(2):
                section += " " + match.group(2)
            header.append((index, line))
            continue
        voice = VOICE_RE.match(stripped)
        if voice:
            name = voice.group(1).title()
            if "clef=" in stripped.lower() or "name=" in stripped.lower():
                header.append((index, line))
                active_voice = None
                continue
            active_voice = name
            if current_start is None:
                current_start = index
        elif active_voice and section is not None and stripped and not stripped.startswith("%"):
            # YuE emits the voice selector on its own line and places the
            # following ABC music line underneath it.
            current[active_voice].append((index, line))
        elif current_start is None:
            header.append((index, line))
    if any(current.values()):
        groups.append({"section": section, "voices": current, "line": current_start})
    return lines, groups


def _music(line):
    return line.split("\n", 1)[0].strip()


def _section_index(abc, covers, lyrics=""):
    tools = _tools(covers)
    score = tools.parse_abc(abc)
    lines, groups = _groups(abc)
    candidates = []
    bar = 0
    for group in groups:
        # Vocal and Ins each describe the same time grid.  Sum within each
        # voice, then take the larger total so a sparse/rest voice does not
        # shorten the section span.
        count = max((sum(_bar_count(line) for _, line in entries)
                     for entries in group["voices"].values()), default=0)
        count = max(1, count)
        start = bar
        bar += count
        if group["section"]:
            candidates.append({"id": f"{group['section']}@{len([x for x in candidates if x['section'] == group['section']]) + 1}",
                               "section": group["section"], "start_bar": start, "end_bar": bar,
                               "confidence": "medium", "reason": "ABCの明示コメント"})
    lyric_sections = []
    for m in re.finditer(r"(?im)^\s*\[(intro|verse|chorus|bridge|outro|pre-chorus|interlude)(?:\s+(\d+))?\]\s*$", lyrics or ""):
        name = m.group(1).casefold() + ((" " + m.group(2)) if m.group(2) else "")
        lyric_sections.append(name)
    names = [x["section"] for x in candidates]
    confidence = "high" if candidates and lyric_sections and names == lyric_sections else ("medium" if candidates else "low")
    if confidence == "high":
        for item in candidates:
            item["confidence"] = "high"
            item["reason"] = "ABCコメントとLyricsタグの順序・回数が一致"
    elif lyric_sections and candidates and names != lyric_sections:
        for item in candidates:
            item["confidence"] = "low"
            item["reason"] = "ABCコメントとLyricsタグの順序または回数が一致しない"
    return score, candidates, {"confidence": confidence, "lyrics_sections": lyric_sections}


def analyze(abc, covers, lyrics=""):
    if len(abc.encode("utf-8")) > 256 * 1024:
        raise ValueError("ABCはUTF-8で256 KiB以内にしてください")
    score, sections, alignment = _section_index(abc, covers, lyrics)
    return {"sections": sections, "alignment": alignment,
            "voices": {name: len(voice.notes) for name, voice in score.voices.items()},
            "bpm": score.bpm, "duration_quarters": str(score.voices["Vocal"].time)}


def _bar_count(line):
    # ``Z``/``Z2``.../``Z4`` are whole-bar rests.  The numeric suffix is a
    # compressed number of physical bars, not a duration within one bar.
    # Count the same chunks that the editor will later serialize so both
    # voices retain an identical physical measure grid.
    return len(_bar_chunks(line))


def _expand_rest_chunk(chunk):
    """Expand one compressed whole-bar rest into physical-bar chunks."""
    body = chunk.strip()
    if body.endswith("|"):
        body = body[:-1].rstrip()
    # Keep any chord annotation attached to the first expanded bar.  This
    # preserves code onset information while still exposing the remaining
    # physical rest bars to the voice-grid logic.
    match = re.fullmatch(r'((?:"[^"]*")*)Z([1-4])?', body)
    if not match:
        return [chunk.strip()]
    prefix = match.group(1)
    count = int(match.group(2) or "1")
    return [prefix + "Z|"] + ["Z|"] * (count - 1)


def _bar_chunks(line):
    """Return a music line split at physical bar boundaries.

    The ABC helper has already rejected unsupported notation. Keeping the
    delimiter on each chunk makes a chunk valid music text and allows us to
    replace only a selected prefix of a section while retaining later bars.
    """
    # The voice selector is on the preceding line in native YuE ABC.  Return
    # music bodies only so a Vocal motif can be inserted into an Ins target
    # without introducing an invalid ``V:`` token into the music stream.
    body = line[line.find("V:") + 2:].strip() if "V:" in line else line.strip()
    chunks = []
    start = 0
    for match in re.finditer(r"\|", body):
        chunks.extend(_expand_rest_chunk(body[start:match.end()]))
        start = match.end()
    if body[start:].strip():
        chunks.extend(_expand_rest_chunk(body[start:].strip()))
    return chunks


def _group_bar_count(group):
    """Return a section's physical span, using the fullest voice grid."""
    counts = [sum(_bar_count(line) for _, line in entries)
              for entries in group["voices"].values() if entries]
    return max(counts, default=0)


def _replace_voice_line(line, replacement):
    prefix = line[:line.find("V:") + 2] if "V:" in line else "V: Vocal "
    return prefix + " " + replacement.strip() + "\n"


def integrate(base_abc, motif_abc, covers, *, section, voice="Vocal", seed="0", transform=None,
              target_start=None, target_end=None):
    """Insert a complete motif into the first confirmed target slot.

    The initial editor intentionally requires equal whole-bar spans.  This
    keeps meter, ties, code onsets and untouched text exact; callers can ask
    for another slot when a time ratio cannot be represented by native L.
    """
    transform = transform or {}
    tools = _tools(covers)
    base_score = tools.parse_abc(base_abc)
    motif_score = tools.parse_abc(motif_abc)
    # The conservative serializer preserves each complete source bar.  A
    # different meter would make a direct replacement invalid; time scaling
    # belongs to a later explicit transform and must never be guessed here.
    base_meter = base_score.voices[voice].time_signature if hasattr(base_score.voices[voice], "time_signature") else base_score.voices[voice].meter
    motif_meter = motif_score.voices[voice].time_signature if hasattr(motif_score.voices[voice], "time_signature") else motif_score.voices[voice].meter
    if base_meter != motif_meter:
        raise ValueError("grid_unrepresentable: モチーフと基本プランの拍子が異なるため、時間変換の確認が必要です")
    base_lines, base_groups = _groups(base_abc)
    motif_lines, motif_groups = _groups(motif_abc)
    motif_groups = [g for g in motif_groups if g["voices"].get(voice)]
    if not motif_groups:
        raise ValueError("モチーフの採用声部に音符がありません")
    # A voice containing only Z/z rests is not an audible motif source.  Do
    # not silently accept it merely because it has serialized ABC lines.
    if not getattr(motif_score.voices.get(voice), "notes", None):
        raise ValueError("モチーフの採用声部に音符がありません")
    motif_lines_for_voice = [line for g in motif_groups for _, line in g["voices"][voice]]
    if not motif_lines_for_voice:
        raise ValueError("モチーフの採用声部に音符がありません")
    targets = [g for g in base_groups if g["section"] and g["section"].split(" ", 1)[0] == section.casefold()]
    if not targets:
        raise ValueError(f"指定セクションがABCにありません: {section}")
    target = targets[0]
    target_lines = target["voices"].get(voice) or []
    if target_start is not None or target_end is not None:
        start = int(target_start or target["line"] or 0)
        target = next((g for g in base_groups if g["line"] == start), target)
        target_lines = target["voices"].get(voice) or []
    source_total = sum(_bar_count(x) for x in motif_lines_for_voice)
    target_total = sum(_bar_count(x) for _, x in target_lines)
    source_total = source_total or len(motif_lines_for_voice)
    target_total = target_total or len(target_lines)
    if not source_total or not target_total:
        raise ValueError("grid_unrepresentable: モチーフまたは対象セクションに小節がありません")
    # A motif is a short phrase.  Use at most the first eight complete bars
    # and place it in the first matching number of target bars.  The rest of
    # the target section remains byte-for-byte unchanged.
    source_bars = min(source_total, 8)
    target_bars = min(source_bars, target_total)
    source_chunks = [chunk for line in motif_lines_for_voice for chunk in _bar_chunks(line)]
    target_chunks = [(idx, chunk) for idx, line in target_lines for chunk in _bar_chunks(line)]
    if len(source_chunks) < source_bars or len(target_chunks) < target_bars:
        raise ValueError("grid_unrepresentable: 小節境界を正しく分割できません")
    replacement = source_chunks[:target_bars]
    target_prefix = target_chunks[:target_bars]
    if transform.get("octave"):
        # Pitch editing is deliberately deferred to the native parser unless
        # a caller supplied an explicit confirmed transform.  Keep manifest.
        raise ValueError("この版ではオクターブ変換前にABC範囲の再確認が必要です")
    output = list(base_lines)
    changed = []
    # Rebuild only the lines containing the selected prefix.  If a line has
    # unselected trailing bars, append those original chunks unchanged.
    by_line = {}
    for pos, (idx, chunk) in enumerate(target_chunks):
        if pos >= target_bars:
            break
        by_line.setdefault(idx, []).append((pos, chunk))
    source_pos = 0
    for idx, original in target_lines:
        chunks = _bar_chunks(original)
        rebuilt = []
        for chunk in chunks:
            if source_pos < target_bars:
                rebuilt.append(replacement[source_pos])
                source_pos += 1
            else:
                rebuilt.append(chunk)
        if idx in by_line:
            output[idx] = "".join(rebuilt) + "\n"
            changed.append(idx)
    edited = "".join(output)
    tools.parse_abc(edited)
    target_bar = sum(_group_bar_count(g) or 1
                     for g in base_groups[:base_groups.index(target)])
    manifest = {"algorithm_version": "motif-abc-v1", "seed": str(seed),
                "section": target["section"], "voice": voice,
                "source_bars": source_bars, "target_bars": target_bars,
                # Section indexes are zero-based (the same convention as
                # analyze().  Keep the manifest aligned with start_bar.
                "changed_lines": changed, "changed_bar_range": [target_bar, target_bar + target_bars - 1],
                "transform": transform, "warnings": ["初版は同一小節数の厳密配置のみ対応"]}
    manifest["base_sha256"] = hashlib.sha256(base_abc.encode()).hexdigest()
    manifest["motif_sha256"] = hashlib.sha256(motif_abc.encode()).hexdigest()
    manifest["edited_sha256"] = hashlib.sha256(edited.encode()).hexdigest()
    return edited, manifest


def validate(abc, covers, *, base_abc=None, lyrics="", declared=None):
    tools = _tools(covers)
    score = tools.parse_abc(abc)
    if not any(v.notes for v in score.voices.values()):
        raise ValueError("ABCに音符がありません")
    report = tools.report(score)
    result = {"valid": True, "report": report, "estimated_seconds": float(report.get("nominal_duration_seconds", 0) or 0),
              "warnings": []}
    if base_abc is not None:
        base = tools.parse_abc(base_abc)
        if base.bpm != score.bpm or base.voices["Vocal"].time != score.voices["Vocal"].time:
            raise ValueError("基本プランと編集後ABCの拍子・テンポ・曲長が一致しません")
    return result
