"""Workspace confinement and serializable project state."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .schema import BriefError, safe_id


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or candidate.drive
        or ".." in candidate.parts
        or ":" in str(relative)
        or "\\" in str(relative)
    ):
        raise BriefError(
            f"Use a workspace-relative forward-slash path: {relative}"
        )
    unresolved = root / candidate
    current = unresolved
    while current != root:
        is_junction = False
        if os.name == "nt":
            try:
                is_junction = (
                    current.lstat().st_reparse_tag
                    == stat.IO_REPARSE_TAG_MOUNT_POINT
                )
            except FileNotFoundError:
                pass
        if current.is_symlink() or is_junction:
            raise BriefError(
                "Links/junctions are not allowed in production paths: "
                f"{relative}"
            )
        current = current.parent
    resolved = unresolved.resolve()
    if not resolved.is_relative_to(root):
        raise BriefError("Path escapes workspace")
    return resolved


def load(path):
    def invalid(value):
        raise BriefError(f"Non-finite JSON value: {value}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BriefError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        if Path(path).suffix.lower() in {".md", ".markdown"}:
            fences = re.findall(
                r"(?ms)^```json[ \t]*\r?\n(.*?)^```[ \t]*$", text
            )
            if len(fences) != 1 or len(re.findall(r"(?m)^```", text)) != 2:
                raise BriefError(
                    "Markdown import requires exactly one fenced json object; "
                    "for free prose, ask the agent to map fields "
                    "and confirm before importing"
                )
            text = fences[0]
        return json.loads(
            text,
            parse_constant=invalid,
            object_pairs_hook=unique,
        )
    except (OSError, ValueError) as error:
        raise BriefError(f"Cannot load {path}: {error}") from error


def save(path, value, exclusive=False):
    path = Path(path)
    payload = (
        json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    else:
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def merge(base, changes):
    result = copy.deepcopy(base)
    if not isinstance(changes, dict):
        raise BriefError("Import/answers must contain a JSON object")
    for key, value in changes.items():
        result[key] = (
            merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else copy.deepcopy(value)
        )
    return result


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def project(self, identity):
        return inside(self.root, f"projects/{safe_id(identity)}")

    def brief(self, identity):
        return load(self.project(identity) / "brief.json")

    def save_brief(self, brief):
        save(self.project(brief["project_id"]) / "brief.json", brief)

    def template(self, identity):
        result = load(inside(self.root, "templates/brief.json"))
        result["project_id"] = safe_id(identity)
        return result
