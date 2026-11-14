"""Subtitle and thumbnail sidecars from approved local sources."""

import json
import re

from .schema import BriefError, number
from .storage import file_hash


def assignment(source, name):
    matches = list(
        re.finditer(r"(?m)^\s*window\." + name + r"\s*=\s*", source)
    )
    if len(matches) != 1:
        raise BriefError(
            f"Take requires exactly one JSON window.{name} timeline"
        )
    try:
        value, end = json.JSONDecoder().raw_decode(source[matches[0].end():])
    except ValueError as error:
        raise BriefError(f"Invalid JSON {name} timeline") from error
    trailing = source[matches[0].end() + end:]
    if not trailing.lstrip().startswith(";"):
        raise BriefError(f"Invalid {name} assignment terminator")
    if not isinstance(value, list) or not value:
        raise BriefError(f"Missing {name} timing")
    return value


def subtitle_text(data_path, script, duration, start=0, seconds=None):
    duration = number(duration, "subtitle duration", 0.001)
    start = number(start, "subtitle start")
    stop = (
        duration
        if seconds is None
        else min(duration, start + number(seconds, "subtitle seconds", 0.001))
    )
    if start >= stop:
        raise BriefError("Subtitle interval is outside the take")
    source = data_path.read_text(encoding="utf-8-sig")
    words = assignment(source, "WORDS")
    captions = assignment(source, "CAPTIONS")
    tokens = script.split()
    if any(not isinstance(row, list) or len(row) != 3 for row in words):
        raise BriefError("Invalid WORDS timing rows")
    if [row[0] for row in words] != tokens:
        raise BriefError("WORDS timing does not match the exact script tokens")
    previous = 0
    for text, begin, end in words:
        begin = number(begin, "word start")
        end = number(end, "word end", 0.001)
        if begin < previous or end <= begin or end > duration:
            raise BriefError(
                "WORDS timestamps must be monotonic within the take"
            )
        previous = end
    previous = 0
    caption_tokens = []
    for row in captions:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise BriefError("Invalid CAPTIONS timing row")
        begin = number(row.get("show"), "caption start")
        end = number(row.get("hide"), "caption end", 0.001)
        if begin < previous or end <= begin or end > duration:
            raise BriefError(
                "CAPTIONS timestamps must be monotonic within the take"
            )
        previous = end
        row_tokens = row["text"].split()
        offset = len(caption_tokens)
        if (
            not row_tokens
            or offset + len(row_tokens) > len(words)
            or begin > words[offset][1] + 0.05
            or end < words[offset + len(row_tokens) - 1][2] - 0.05
        ):
            raise BriefError(
                "Caption interval must cover its assigned script words"
            )
        caption_tokens.extend(row_tokens)
    if caption_tokens != tokens:
        raise BriefError(
            "CAPTIONS timing does not match the exact script tokens"
        )
    spans = list(re.finditer(r"\S+", script))
    cues = []
    offset = 0
    for caption in captions:
        count = len(caption["text"].split())
        selected = [
            index
            for index in range(offset, offset + count)
            if words[index][2] > start and words[index][1] < stop
        ]
        offset += count
        if not selected:
            continue
        first, last = selected[0], selected[-1]
        begin = max(caption["show"], start)
        end = min(caption["hide"], stop)
        if begin >= end:
            raise BriefError(
                "Caption interval does not cover its script words"
            )
        begin_ms, end_ms = (
            round((begin - start) * 1000),
            round((end - start) * 1000),
        )
        if end_ms <= begin_ms:
            raise BriefError("Word timing is too short for SRT milliseconds")
        text = script[spans[first].start():spans[last].end()]
        if re.search(r"\n\s*\n", text):
            raise BriefError(
                "Caption cues must not span script paragraph breaks"
            )
        cues.append(
            f"{len(cues) + 1}\n"
            f"{timestamp(begin_ms)} --> {timestamp(end_ms)}\n{text}\n"
        )
    if not cues:
        raise BriefError(
            "No timed script words in the selected preview interval"
        )
    return "\n".join(cues)


def timestamp(milliseconds):
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}"


def sidecars(output, subtitles, duration, thumbnail_s, command, root):
    captions = output.with_name("captions.srt")
    with captions.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(subtitles)
    moment = number(thumbnail_s, "thumbnail_s")
    if moment >= duration:
        raise BriefError("thumbnail_s must be inside the rendered clip")
    thumbnail = output.with_name("thumbnail.jpg")
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-ss",
            moment,
            "-i",
            output,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            thumbnail,
        ],
        root,
    )
    if not thumbnail.is_file() or thumbnail.stat().st_size == 0:
        raise BriefError("Thumbnail extraction returned no image")
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            thumbnail,
            "-f",
            "null",
            "-",
        ],
        root,
    )
    return {
        "srt": {
            "path": captions.relative_to(root).as_posix(),
            "sha256": file_hash(captions),
        },
        "thumbnail": {
            "path": thumbnail.relative_to(root).as_posix(),
            "sha256": file_hash(thumbnail),
        },
    }
