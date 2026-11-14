"""Approval-bound staging, rendering and media verification."""

import asyncio
from fractions import Fraction
import math
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .schema import (
    BriefError,
    duration_bounds,
    number,
    safe_id,
    storyboard_context,
    validate,
)
from .storage import digest, file_hash, inside, load, save
from .workflow import execute_graph
from .deliverables import sidecars, subtitle_text


EXCLUDED = {"node_modules", ".git", ".venv", "__pycache__", "out", "projects"}


def command(argv, root):
    try:
        return subprocess.run(
            [str(value) for value in argv],
            cwd=root,
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BriefError(
            f"Command failed: {Path(str(argv[0])).name}; check local build/capture prerequisites"
        ) from error


def collect(root, relative, files):
    path = inside(root, relative)
    if not path.exists():
        raise BriefError(f"Missing source: {relative}")
    if path.is_file():
        files[path.relative_to(root).as_posix()] = file_hash(path)
    else:
        for child in sorted(path.iterdir()):
            if child.name not in EXCLUDED:
                collect(root, child.relative_to(root).as_posix(), files)


def source_plan(store, brief, require_sample_approval=True):
    validate(brief, complete=True)
    root = store.root
    minimum, maximum, hold = duration_bounds(brief["duration"])
    script = inside(root, brief["script"].get("path", ""))
    if (
        not script.is_file()
        or not script.read_text(encoding="utf-8-sig").strip()
    ):
        raise BriefError(
            "Missing narration script; author script.txt, then lock it during initialize"
        )
    if file_hash(script) != brief["script"].get("sha256"):
        raise BriefError(
            "Locked script changed; reinitialize and explicitly relock the script"
        )
    options = brief.get("storyboard_options", [])
    if options:
        context = storyboard_context(brief, file_hash(script))
        if (
            brief.get("storyboard_context") != context
            or sorted(row.get("variant_id", "") for row in options)
            != sorted(row["id"] for row in brief["variants"])
            or any(
                row.get("context_hash") != context or not row.get("beats")
                for row in options
            )
        ):
            raise BriefError(
                "Storyboard options are stale or incomplete; preview each variant and approve again"
            )
    speech = brief.get("speech", {})
    if require_sample_approval and not speech.get("narration_path"):
        approval = speech.get("sample_approval", {})
        if (
            approval.get("approved") is not True
            or approval.get("voice") != speech.get("voice")
            or not speech.get("voice")
        ):
            raise BriefError(
                "Approve a real voice sample via speech.sample_approval, or set speech.narration_path for prepared pre-recorded narration"
            )
        sample_path = inside(root, approval.get("manifest_path", ""))
        sample_record = load(sample_path)
        from .speech import sample_context

        if sample_record.get("context_hash") != sample_context(store, brief):
            raise BriefError(
                "Voice sample is stale for this script/locale/style/pronunciation; preview and approve again"
            )
        sample = next(
            (
                row
                for row in sample_record.get("samples", [])
                if row["voice"] == speech["voice"]
            ),
            None,
        )
        if (
            not sample
            or file_hash(inside(root, sample["path"])) != sample["sha256"]
        ):
            raise BriefError(
                "Approved voice sample is missing or changed; preview again"
            )
    files = {}
    collect(root, script.relative_to(root).as_posix(), files)
    for option in options:
        if option.get("path"):
            collect(root, option["path"], files)
    for source in brief.get("sources", []):
        collect(root, source["path"], files)
    if require_sample_approval and not speech.get("narration_path"):
        collect(root, sample_path.relative_to(root).as_posix(), files)
        collect(root, sample["path"], files)
    for shared in ("core", "tools/build.mjs", "capture.py", "make_take.py"):
        collect(root, shared, files)
    for shared in ("render_options.py", "package.json", "package-lock.json"):
        if inside(root, shared).is_file():
            collect(root, shared, files)
    for dependency in brief.get("dependencies", []):
        if not isinstance(dependency, str) or any(
            part in EXCLUDED for part in Path(dependency).parts
        ):
            raise BriefError(
                "dependencies must name local source/assets, never node_modules, out or project state"
            )
        collect(root, dependency, files)
    for asset in brief.get("assets", []):
        if asset.get("path"):
            collect(root, asset["path"], files)
        elif not asset.get("reference_only", False):
            raise BriefError(
                "Download required URL assets into the workspace and set path before production; URLs are not fetched"
            )
    music = brief.get("music", {})
    if music.get("choice") != "none" and not music.get("path"):
        raise BriefError("Selected music needs a licensed, staged local file")
    if music.get("path"):
        if not music.get("licensing"):
            raise BriefError("Music needs licensing information")
        collect(root, music["path"], files)
    variants = []
    for variant in brief["variants"]:
        for asset in variant.get("customizations", {}).get("assets", []):
            relative = asset if isinstance(asset, str) else asset.get("path")
            if not relative:
                raise BriefError(
                    "Variant assets must be staged workspace files before production"
                )
            collect(root, relative, files)
        relative = variant["project_dir"]
        if any(
            part in EXCLUDED for part in Path(relative).parts
        ) or relative in {"", "."}:
            raise BriefError(
                "project_dir must be a dedicated scene folder, not project state or workspace root"
            )
        scene = inside(root, relative)
        for required in ("index.html", "main.js", "config.json"):
            if not (scene / required).is_file():
                raise BriefError(
                    f"Missing scene {relative}/{required}. A coding agent must author real scenes before produce"
                )
        collect(root, relative, files)
        config = load(scene / "config.json")
        take = safe_id(config.get("take"))
        take_relative = f"takes/{take}"
        take_path = inside(root, take_relative)
        if not (take_path / "meta.json").is_file():
            raise BriefError(
                f"Missing narration metadata in {take_relative}; prepare a take with make_take.py before produce"
            )
        meta = load(take_path / "meta.json")
        voice = variant.get("customizations", {}).get("voice") or variant.get(
            "voice"
        )
        if voice and voice != meta.get("voice"):
            raise BriefError(
                "Prepared take voice does not match the explicit variant voice"
            )
        narration = take_path / "narration.wav"
        if not narration.is_file() or not (take_path / "data.js").is_file():
            raise BriefError(
                f"Missing narration/data.js in {take_relative}; prepare a take with make_take.py or stage pre-recorded narration"
            )
        supplied = brief.get("speech", {}).get("narration_path")
        if supplied and inside(root, supplied) != narration:
            raise BriefError(
                "speech.narration_path must match the prepared scene's takes/<take>/narration.wav"
            )
        total = number(meta.get("duration"), "take duration", 0.001)
        subtitle_text(
            take_path / "data.js",
            script.read_text(encoding="utf-8-sig"),
            total,
        )
        thumbnail_s = number(
            config.get("thumbnail_s", min(total / 2, 1)), "thumbnail_s"
        )
        if thumbnail_s >= total:
            raise BriefError("thumbnail_s must be inside the take")
        if (Fraction(str(total)) * variant["fps"]).denominator != 1:
            raise BriefError(
                "Finished duration must represent a whole number of frames at the variant fps"
            )
        if not minimum <= total <= maximum:
            raise BriefError(
                f"Take duration {total} is outside inclusive finished bounds {minimum}-{maximum}, including hold"
            )
        import wave

        try:
            with wave.open(str(narration), "rb") as audio:
                audio_seconds = audio.getnframes() / audio.getframerate()
        except (OSError, EOFError, wave.Error) as error:
            raise BriefError(
                "Prepared narration must be a readable PCM WAV"
            ) from error
        if audio_seconds > total - hold + 0.05:
            raise BriefError(
                "Prepared narration leaves insufficient ending hold; regenerate the take"
            )
        collect(root, take_relative, files)
        variants.append(
            {
                **variant,
                "duration_s": total,
                "take": take,
                "thumbnail_s": thumbnail_s,
            }
        )
    return {
        "brief_hash": digest(brief),
        "files": files,
        "variants": variants,
        "script_path": brief["script"]["path"],
    }


def prepare(store, identity):
    brief = store.brief(identity)
    content = {
        "schema_version": 1,
        "project_id": identity,
        "nonce": uuid.uuid4().hex,
        "steps": [
            "approval_gate",
            "stage_sources",
            "build_and_capture_each_explicit_variant",
            "verify_outputs",
        ],
        "policy": {
            "automatic_retries": 0,
            "speech_calls_during_production": False,
            "overwrite_outputs": False,
        },
        **source_plan(store, brief),
    }
    approval = digest(content)
    plan = {**content, "approval_id": approval}
    save(
        store.project(identity) / "approvals" / f"{approval}.json",
        plan,
        exclusive=True,
    )
    return plan


def approval_gate(store, identity, approval):
    safe_id(approval)
    path = inside(store.root, f"projects/{identity}/approvals/{approval}.json")
    plan = load(path)
    content = {
        key: value for key, value in plan.items() if key != "approval_id"
    }
    if (
        digest(content) != approval
        or plan.get("approval_id") != approval
        or plan.get("project_id") != identity
    ):
        raise BriefError(
            "Approval plan was altered or belongs to another project; prepare again"
        )
    current = source_plan(store, store.brief(identity))
    if any(
        plan[field] != current[field]
        for field in ("brief_hash", "files", "variants")
    ):
        raise BriefError(
            "Stale approval: brief, script, scene, assets or tools changed; run produce --prepare again"
        )
    return plan


def stage_sources(store, identity, plan, prefix="out"):
    run_id = uuid.uuid4().hex
    run = inside(store.root, f"{prefix}/{identity}/{run_id}")
    run.mkdir(parents=True, exist_ok=False)
    workspace = run / "workspace"
    workspace.mkdir()
    for relative, expected in plan["files"].items():
        source = inside(store.root, relative)
        destination = inside(workspace, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if file_hash(destination) != expected:
            raise BriefError("Source changed during staging; prepare again")
    result = {
        "run_id": run_id,
        "project_id": identity,
        "approval_id": plan.get("approval_id"),
        "plan": plan,
        "outputs": [],
        "status": "staged",
    }
    save(run / "run.json", result, exclusive=True)
    return result


def render_variants(store, record, preview=None):
    prefix = "previews" if preview else "out"
    run = inside(
        store.root, f"{prefix}/{record['project_id']}/{record['run_id']}"
    )
    workspace = run / "workspace"
    try:
        for variant in record["plan"]["variants"]:
            scene = inside(workspace, variant["project_dir"])
            subtitles = subtitle_text(
                inside(workspace, f"takes/{variant['take']}/data.js"),
                inside(workspace, record["plan"]["script_path"]).read_text(
                    encoding="utf-8-sig"
                ),
                variant["duration_s"],
                preview["start_s"] if preview else 0,
                preview["duration_s"] if preview else None,
            )
            command(
                ["node", store.root / "tools/build.mjs", scene], store.root
            )
            output = run / "variants" / variant["id"] / "video.mp4"
            output.parent.mkdir(parents=True, exist_ok=False)
            argv = [
                sys.executable,
                store.root / "capture.py",
                variant["project_dir"],
                "--root",
                workspace,
                "--output",
                output,
                "--width",
                variant["width"],
                "--height",
                variant["height"],
                "--fps",
                variant["fps"],
                "--duration",
                variant["duration_s"],
                "--captions",
                variant["captions"],
                "--browser",
                "chromium",
            ]
            if preview:
                argv.extend(
                    [
                        "--start",
                        preview["start_s"],
                        "--seconds",
                        preview["duration_s"],
                    ]
                )
            command(argv, store.root)
            if not output.is_file() or output.stat().st_size == 0:
                raise BriefError(
                    "Capture returned without a nonempty video.mp4"
                )
            duration = (
                preview["duration_s"] if preview else variant["duration_s"]
            )
            moment = (
                min(
                    max(variant["thumbnail_s"] - preview["start_s"], 0),
                    duration / 2,
                )
                if preview
                else variant["thumbnail_s"]
            )
            artifacts = sidecars(
                output, subtitles, duration, moment, command, store.root
            )
            record["outputs"].append(
                {
                    "variant": variant["id"],
                    "path": output.relative_to(store.root).as_posix(),
                    "sha256": file_hash(output),
                    "width": variant["width"],
                    "height": variant["height"],
                    "fps": variant["fps"],
                    "artifacts": artifacts,
                    "start_s": preview["start_s"] if preview else 0,
                    "duration_s": preview["duration_s"]
                    if preview
                    else variant["duration_s"],
                }
            )
        record["status"] = "rendered"
        save(run / "run.json", record)
        return record
    except Exception:
        record["status"] = "failed"
        save(run / "run.json", record)
        raise


def _verify_record(store, record, prefix="out"):
    if record.get("status") not in {"rendered", "verified"} or not record.get(
        "outputs"
    ):
        raise BriefError("Run has no complete rendered outputs to verify")
    if len(record["outputs"]) != len(record["plan"]["variants"]):
        raise BriefError("Run is missing variant outputs")
    if sorted(row["variant"] for row in record["outputs"]) != sorted(
        row["id"] for row in record["plan"]["variants"]
    ):
        raise BriefError("Run variant output identities do not match the plan")
    for output in record["outputs"]:
        path = inside(store.root, output["path"])
        expected = f"{prefix}/{record['project_id']}/{record['run_id']}/variants/{safe_id(output['variant'])}/video.mp4"
        if output["path"] != expected or file_hash(path) != output["sha256"]:
            raise BriefError("Rendered output path/hash changed")
        for kind, filename in (
            ("srt", "captions.srt"),
            ("thumbnail", "thumbnail.jpg"),
        ):
            artifact = output.get("artifacts", {}).get(kind, {})
            relative = str(Path(expected).with_name(filename)).replace(
                "\\", "/"
            )
            artifact_path = inside(store.root, relative)
            if (
                artifact.get("path") != relative
                or not artifact_path.is_file()
                or not artifact_path.stat().st_size
                or file_hash(artifact_path) != artifact.get("sha256")
            ):
                raise BriefError(f"Missing or changed {kind} sidecar")
        variant = next(
            row
            for row in record["plan"]["variants"]
            if row["id"] == output["variant"]
        )
        workspace = path.parents[2] / "workspace"
        expected_srt = subtitle_text(
            inside(workspace, f"takes/{variant['take']}/data.js"),
            inside(workspace, record["plan"]["script_path"]).read_text(
                encoding="utf-8-sig"
            ),
            variant["duration_s"],
            output.get("start_s", 0),
            output["duration_s"],
        )
        if (
            path.with_name("captions.srt").read_text(encoding="utf-8")
            != expected_srt
        ):
            raise BriefError("SRT does not match approved script/timing")
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-xerror",
                "-i",
                path.with_name("thumbnail.jpg"),
                "-f",
                "null",
                "-",
            ],
            store.root,
        )
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-xerror",
                "-i",
                path,
                "-f",
                "null",
                "-",
            ],
            store.root,
        )
        result = command(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                path,
            ],
            store.root,
        )
        import json

        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        video = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if not video or not any(
            stream.get("codec_type") == "audio" for stream in streams
        ):
            raise BriefError("Output must contain video and narration audio")
        actual = float(probe["format"]["duration"])
        if not math.isfinite(actual) or abs(
            actual - output["duration_s"]
        ) > max(0.1, 1 / output["fps"]):
            raise BriefError(
                "Rendered duration does not match approved finished length"
            )
        if (video.get("width"), video.get("height")) != (
            output["width"],
            output["height"],
        ):
            raise BriefError(
                "Rendered dimensions do not match approved variant"
            )
        frames = int(video.get("nb_read_frames", video.get("nb_frames", -1)))
        if abs(frames - round(output["duration_s"] * output["fps"])) > 1:
            raise BriefError(
                "Rendered frame count does not match approved fps/duration"
            )
    record["status"] = "verified"
    save(
        inside(
            store.root,
            f"{prefix}/{record['project_id']}/{record['run_id']}/verification.json",
        ),
        {
            "status": "verified",
            "outputs": record["outputs"],
            "checks": [
                "sha256",
                "duration",
                "dimensions",
                "frames",
                "audio_stream",
                "script_exact_srt",
                "decoded_thumbnail",
                "full_video_decode",
            ],
            "limitations": "Media integrity only; no visual correctness, speech transcription or claims verification.",
        },
    )
    return record


def verify_record(store, record, prefix="out"):
    try:
        result = _verify_record(store, record, prefix)
        save(
            inside(
                store.root,
                f"{prefix}/{record['project_id']}/{record['run_id']}/run.json",
            ),
            result,
        )
        return result
    except Exception:
        record["status"] = "failed"
        run = inside(
            store.root, f"{prefix}/{record['project_id']}/{record['run_id']}"
        )
        save(run / "run.json", record)
        (run / "verification.json").unlink(missing_ok=True)
        raise


def produce(store, identity, approval):
    def gate(_message):
        plan = approval_gate(store, identity, approval)
        try:
            save(
                store.project(identity)
                / "approvals"
                / f"{approval}.used.json",
                {"used": True},
                exclusive=True,
            )
        except FileExistsError as error:
            raise BriefError(
                "Approval already consumed; prepare a new run, including after a failed render"
            ) from error
        return plan

    return asyncio.run(
        execute_graph(
            {},
            gate,
            lambda plan: stage_sources(store, identity, plan),
            lambda record: render_variants(store, record),
            lambda record: verify_record(store, record),
        )
    )


def verify(store, identity, run_id):
    safe_id(run_id)
    return verify_record(
        store, load(inside(store.root, f"out/{identity}/{run_id}/run.json"))
    )
