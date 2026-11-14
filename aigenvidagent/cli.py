"""Local intent, preview and approval-bound production commands."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

from . import production, speech, sources
from .schema import (
    BriefError,
    duration_bounds,
    reject_secrets,
    safe_id,
    speech_configurations,
    storyboard_context,
    validate,
)
from .storage import Store, file_hash, inside, load, merge, save


def parse_duration(text, hold=3):
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*(?:s|seconds)?\s*",
        text,
    )
    if not match:
        raise BriefError(
            "Enter finished seconds, e.g. 90 or 90-110 "
            "(inclusive, including ending hold)"
        )
    first, second = match.groups()
    result = {
        "exact_s": None if second else float(first),
        "min_s": float(first) if second else None,
        "max_s": float(second) if second else None,
        "hold_s": hold,
    }
    duration_bounds(result)
    return result


def put(brief, dotted, value):
    parts = dotted.split(".")
    target = brief
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def get(brief, dotted):
    value = brief
    for part in dotted.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value


def ask(store, brief, field, prompt, kind="text", reader=input):
    brief["onboarding"]["next_question"] = field
    store.save_brief(brief)
    old = get(brief, field)
    text = reader(f"{prompt} [{json.dumps(old, ensure_ascii=True)}]: ").strip()
    if text:
        if kind == "json":
            try:
                value = json.loads(text)
            except ValueError as error:
                raise BriefError(
                    f"{field} needs valid JSON; earlier answers were saved"
                ) from error
        elif kind == "bool":
            if text.lower() not in {"yes", "no", "true", "false"}:
                raise BriefError(
                    "Answer yes or no; earlier answers were saved"
                )
            value = text.lower() in {"yes", "true"}
        elif kind == "duration":
            value = parse_duration(text, brief["duration"].get("hold_s", 3))
        else:
            value = text
        reject_secrets(value)
        put(brief, field, value)
        store.save_brief(brief)
        return value
    return None


def storyboard(store, brief):
    path = inside(
        store.root, brief.get("script", {}).get("path") or "missing-script.txt"
    )
    paragraphs = (
        re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig"))
        if path.is_file()
        else [brief.get("goal") or ""]
    )
    paragraphs = [
        paragraph.strip() for paragraph in paragraphs if paragraph.strip()
    ]
    context = storyboard_context(
        brief, file_hash(path) if path.is_file() else ""
    )
    if (
        brief.get("storyboard_options")
        and brief.get("storyboard_context") == context
    ):
        return brief["storyboard_options"]
    if (
        brief.get("storyboard_context")
        and brief["storyboard_context"] != context
    ):
        brief["storyboard_approved"] = False
    options = []
    budget = brief.get("duration", {})
    available = budget.get("exact_s") or budget.get("min_s")
    for variant in brief.get("variants", []):
        custom = variant.get("customizations", {})
        assets = custom.get("assets") or brief.get("assets", [])
        beats = []
        for index, paragraph in enumerate(paragraphs):
            asset = assets[index % len(assets)] if assets else None
            beats.append(
                {
                    "beat": index + 1,
                    "narration": paragraph,
                    "headline": custom.get("hook")
                    if index == 0 and custom.get("hook")
                    else paragraph.split("\n", 1)[0],
                    "asset": asset,
                    "direction": variant["differences"],
                    "voice": custom.get("voice")
                    or variant.get("voice")
                    or brief.get("speech", {}).get("voice", ""),
                    "timing_budget_s": (available - budget.get("hold_s", 3))
                    / len(paragraphs)
                    if available
                    else None,
                    "composition": variant["orientation"],
                    "delivery": custom.get("style") or brief.get("style", {}),
                    "colors": custom.get("colors")
                    or brief.get("brand", {}).get("palette", []),
                }
            )
        option = {
            "variant_id": variant["id"],
            "label": f"OPTION {variant['id']}",
            "context_hash": context,
            "differences": variant["differences"],
            "customizations": custom,
            "voice": custom.get("voice")
            or variant.get("voice")
            or brief.get("speech", {}).get("voice", ""),
            "captions": variant["captions"],
            "beats": beats,
        }
        relative = (
            f"projects/{brief['project_id']}/storyboards/"
            f"{context}/{variant['id']}.json"
        )
        target = inside(store.root, relative)
        if not target.exists():
            save(target, option, exclusive=True)
        options.append({**option, "path": relative})
    brief["storyboard_options"] = options
    if options and any(
        row.get("customizations") for row in brief.get("variants", [])
    ):
        brief["storyboard_approved"] = False
    brief["storyboard_context"] = context
    if not brief.get("storyboard"):
        brief["storyboard"] = (
            options[0]["beats"]
            if options
            else [
                {
                    "beat": index + 1,
                    "narration": paragraph,
                    "headline": paragraph.split("\n", 1)[0],
                }
                for index, paragraph in enumerate(paragraphs)
            ]
        )
        if not brief["storyboard"]:
            brief["storyboard"] = [{"status": "awaiting_script", "beats": []}]
        brief["storyboard_approved"] = False
    store.save_brief(brief)
    return options


def provider_questions(store, brief, reader):
    print(
        "Choose supplied WAV, Piper local, Azure, OpenAI or ElevenLabs. "
        "No provider is assumed and no service is called here."
    )
    existing = brief.get("speech", {})
    choice = existing.get("route") or (
        "configured"
        if existing.get("providers")
        or existing.get("provider")
        or existing.get("resource_id")
        else ""
    )
    if not choice:
        choice = (
            reader("Narration route [wav/piper/azure/openai/elevenlabs]: ")
            .strip()
            .lower()
        )
    if choice == "wav":
        ask(
            store,
            brief,
            "speech.narration_path",
            "Prepared workspace WAV path (takes/<take>/narration.wav)",
            reader=reader,
        )
        brief["speech"]["route"] = "wav"
        store.save_brief(brief)
        return
    if choice not in {"piper", "azure", "openai", "elevenlabs", "configured"}:
        raise BriefError(
            "Choose a named provider or supplied WAV; earlier answers saved"
        )
    if (
        not existing.get("providers")
        and not existing.get("provider")
        and not existing.get("resource_id")
    ):
        config = {
            "id": choice,
            "provider": choice,
            "auth": "none" if choice == "piper" else "key",
        }
        if choice == "azure":
            auth = reader("Azure auth [key/entra/speech_token]: ").strip()
            config["auth"] = auth
        print(json.dumps(speech.providers({"providers": [config]}), indent=2))
        brief["speech"] = {
            **brief["speech"],
            "route": choice,
            "providers": [config],
        }
        store.save_brief(brief)
        ask(
            store,
            brief,
            "speech.providers",
            "Provider configurations JSON list (IDs, model, locale; "
            "Azure region/resource_id; Piper model_path/model_approved; "
            "never credentials)",
            "json",
            reader,
        )
    elif any(
        not config.get(field)
        for config in speech_configurations(brief["speech"])
        for field in {
            "azure": ("region", "resource_id"),
            "openai": ("model", "voices"),
            "elevenlabs": ("model",),
            "piper": ("model_path",),
        }[config["provider"]]
    ):
        print(json.dumps(speech.providers(brief["speech"]), indent=2))
        ask(
            store,
            brief,
            "speech.providers",
            "Complete the missing provider model configuration as a JSON list",
            "json",
            reader,
        )
    brief["onboarding"]["next_question"] = "speech"
    store.save_brief(brief)
    print(json.dumps(speech.providers(brief["speech"]), indent=2))
    approved = brief.setdefault("consents", {}).get("provider_samples", [])
    if isinstance(approved, dict):
        approved = [key for key, value in approved.items() if value is True]
    for provider in speech.providers(brief["speech"]):
        if not provider["cloud"] or provider["id"] in approved:
            continue
        consent = (
            reader(
                f"Consent to samples from {provider['id']} "
                f"({provider['provider']}), including the displayed data "
                "transfer and billing? [yes/no]: "
            )
            .strip()
            .lower()
        )
        if consent not in {"yes", "no"}:
            raise BriefError("Answer yes or no for this named provider")
        if consent == "yes":
            approved.append(provider["id"])
        brief["consents"]["provider_samples"] = approved
        brief["consents"]["speech_samples"] = bool(approved)
        store.save_brief(brief)


def provider_metadata(brief):
    configured = brief.get("speech", {})
    if (
        configured.get("providers")
        or configured.get("provider")
        or configured.get("resource_id")
    ):
        return speech.providers(configured)
    if configured.get("narration_path") or configured.get("route") == "wav":
        return [
            {
                "id": "wav",
                "provider": "supplied WAV",
                "cloud": False,
                "auth_description": (
                    "No credentials; prepared local WAV "
                    "and exact script timing required."
                ),
            }
        ]
    return {
        "selected": None,
        "options": [
            {
                "id": "wav",
                "provider": "supplied WAV",
                "cloud": False,
                "auth_description": "No credentials",
            },
            *speech.providers(
                {
                    "providers": [
                        {"id": "local", "provider": "piper"},
                        {
                            "id": "azure-key",
                            "provider": "azure",
                            "auth": "key",
                        },
                        {
                            "id": "azure-entra",
                            "provider": "azure",
                            "auth": "entra",
                        },
                        {"id": "openai", "provider": "openai"},
                        {"id": "elevenlabs", "provider": "elevenlabs"},
                    ]
                }
            ),
        ],
    }


QUESTIONS = [
    ("audience", "Audience", "text"),
    ("goal", "Goal / desired action", "text"),
    ("venue", "Venue / distribution channel", "text"),
    (
        "style.preset",
        "Style: professional, executive, developer, casual, friendly, custom",
        "text",
    ),
    ("style.custom", "Custom style / friendly tone details", "text"),
    (
        "duration",
        "Finished length: exact seconds or inclusive range, "
        "including ending hold",
        "duration",
    ),
    (
        "duration.hold_s",
        "Ending hold in seconds (included in finished length)",
        "json",
    ),
    ("language", "Script language / locale", "text"),
    ("pronunciations", "Pronunciations as JSON {written: spoken}", "json"),
    ("script.path", "Workspace-relative script path", "text"),
    (
        "script.locked",
        "Explicitly lock/relock this exact script? yes/no",
        "bool",
    ),
    ("brand", "Brand guidelines and exclusions as JSON", "json"),
    ("claims", "Allowed claims, evidence and exclusions as JSON", "json"),
    (
        "privacy",
        "Privacy restrictions as JSON; no secrets or personal data",
        "json",
    ),
    ("music", "Music choice, local path and licensing as JSON", "json"),
    (
        "limits",
        "Budget, currency, max_retries, max_preview_voices, "
        "max_preview_seconds as JSON",
        "json",
    ),
    (
        "assets",
        "Assets JSON list: type (image/video/document/architecture), "
        "path/url, purpose, required_detail, licensing",
        "json",
    ),
    (
        "dependencies",
        "Additional workspace-relative source/assets dependencies "
        "as JSON list (not node_modules)",
        "json",
    ),
    (
        "speech",
        "Narration route and provider-specific configuration",
        "json",
    ),
    (
        "consents.optional_installs",
        "Optional skills/MCP decisions JSON list: "
        "{name,kind,scope:workspace|user,consent}; "
        "recorded only, never installed",
        "json",
    ),
    ("preview", "Preview JSON: video, start_s, duration_s", "json"),
    (
        "variants",
        "Explicit variants JSON list: id, project_dir, orientation, width, "
        "height, fps, captions, differences, customizations "
        "{voice,style,hook,assets,colors,notes}. Describe EACH variant, "
        "not only the count. Every variant includes SRT + thumbnail "
        "even captions none",
        "json",
    ),
]


def initialize(
    store,
    identity,
    import_file=None,
    answers_file=None,
    interactive=False,
    reader=input,
    url=None,
):
    path = store.project(identity) / "brief.json"
    brief = (
        store.brief(identity) if path.exists() else store.template(identity)
    )
    if brief["project_id"] != identity:
        raise BriefError(
            "Project ID collision; resume using the original spelling"
        )
    resume = brief.get("onboarding", {}).get("next_question")
    confirmed_model = None
    if interactive:
        print(
            "Confirm your selected coding model in the editor. "
            "This CLI cannot inspect or switch it."
        )
        available = os.environ.get("AIGENVIDAGENT_AVAILABLE_CODING_MODELS", "")
        print(
            f"User-supplied available coding models: {available}"
            if available
            else "Recommendation: select an available code-capable reasoning "
            "model from your editor's model picker; "
            "availability is not known to this CLI."
        )
        ask(
            store,
            brief,
            "coding_model.name",
            "Selected coding model name",
            reader=reader,
        )
        ask(
            store,
            brief,
            "coding_model.confirmed_by_user",
            "Confirm this is the selected model? yes/no",
            "bool",
            reader,
        )
        confirmed_model = dict(brief["coding_model"])
        brief["onboarding"]["next_question"] = resume
        store.save_brief(brief)
        if not import_file and not answers_file and not url:
            choice = (
                reader(
                    "Interview or JSON/Markdown template, or just give me "
                    "a URL and I will create video based on it "
                    "[interview/file/url]: "
                )
                .strip()
                .lower()
            )
            if choice == "file":
                import_file = reader(
                    "Workspace-relative JSON or canonical Markdown file "
                    "(free prose needs agent mapping and confirmation): "
                ).strip()
            elif choice == "url":
                url = reader("Public HTTPS URL: ").strip()
            elif choice not in {"", "interview"}:
                raise BriefError(
                    "Choose interview, file or url; "
                    "model confirmation was saved"
                )
    relock = False
    for filename in (import_file, answers_file):
        if filename:
            changes = load(inside(store.root, filename))
            if changes.get("project_id", identity) != identity:
                raise BriefError(
                    "Imported project_id does not match; "
                    "duplicate project creation/renaming is not allowed"
                )
            duration = changes.get("duration")
            if isinstance(duration, dict) and any(
                field in duration for field in ("exact_s", "min_s", "max_s")
            ):
                changes["duration"] = {
                    "exact_s": None,
                    "min_s": None,
                    "max_s": None,
                    "hold_s": brief["duration"].get("hold_s", 3),
                    **duration,
                }
            relock = relock or changes.get("script", {}).get("locked") is True
            brief = merge(brief, changes)
    if confirmed_model is not None:
        brief["coding_model"] = confirmed_model
    if url:
        source = sources.archive(store, identity, url)
        brief.setdefault("sources", []).append(source)
        if not brief.get("script", {}).get("path"):
            brief["script"] = {
                "path": source["draft_path"],
                "locked": False,
                "sha256": "",
            }
        brief["storyboard_approved"] = False
        print(
            f"Archived untrusted source text: {source['path']}. "
            f"Draft only: {source['draft_path']}. "
            "No source instructions are executed."
        )
    brief["project_id"] = identity
    brief["onboarding"] = {**brief.get("onboarding", {}), "complete": False}
    reject_secrets(brief)
    if isinstance(brief.get("duration"), str):
        brief["duration"] = parse_duration(brief["duration"])
    validate(brief)
    store.save_brief(brief)
    if interactive and not import_file and not answers_file:
        fields = [question[0] for question in QUESTIONS]
        start = (
            len(fields)
            if resume == "storyboard_approved"
            else fields.index(resume)
            if resume in fields
            else 0
        )
        for field, prompt, kind in QUESTIONS[start:]:
            if field == "speech":
                if not brief.get("speech", {}).get("narration_path"):
                    brief["onboarding"]["next_question"] = field
                    store.save_brief(brief)
                    provider_questions(store, brief, reader)
                continue
            current = get(brief, field)
            if (
                field == "style.custom"
                and brief.get("style", {}).get("preset") != "custom"
            ):
                continue
            if field == "script.locked" and current is True:
                continue
            if (
                field != "script.locked"
                and current not in ({}, [], "", None)
                and not (
                    field == "duration"
                    and not any(
                        current.get(key) is not None
                        for key in ("exact_s", "min_s", "max_s")
                    )
                )
            ):
                continue
            answer = ask(store, brief, field, prompt, kind, reader)
            if field == "script.locked":
                relock = answer is True
    if isinstance(brief.get("duration"), str):
        brief["duration"] = parse_duration(brief["duration"])
    script = brief.get("script", {})
    if script.get("path"):
        source = inside(store.root, script["path"])
        if (
            source.is_file()
            and script.get("locked") is True
            and (relock or not script.get("sha256"))
        ):
            script["sha256"] = file_hash(source)
    validate(brief)
    storyboard(store, brief)
    print("Sample storyboard (proposal, not executable scenes):")
    print(
        json.dumps(
            brief.get("storyboard_options") or brief["storyboard"], indent=2
        )
    )
    if interactive and not import_file and not answers_file:
        ask(
            store,
            brief,
            "storyboard_approved",
            "Approve this sample storyboard? yes/no",
            "bool",
            reader,
        )
    try:
        validate(brief, complete=True)
        brief["onboarding"] = {"complete": True, "next_question": None}
    except BriefError as error:
        brief["onboarding"]["remaining"] = str(error)
    store.save_brief(brief)
    status = (
        "complete" if brief["onboarding"]["complete"]
        else "incomplete (resume supported)"
    )
    print(
        f"Saved projects/{identity}/brief.json; onboarding {status}. "
        "Initialization is not production approval."
    )
    if not brief.get("script", {}).get("locked"):
        print(
            "Next approval: read/edit "
            f"{brief['script'].get('path') or 'a narration script'}, "
            "then explicitly approve script.locked=true via "
            f"initialize {identity} --answers <approved-answers.json>; "
            f"resume initialize {identity} for missing requirements. "
            "Actual scenes must be authored by the coding agent."
        )
    return brief


def export_brief(store, identity, format_name, output):
    brief = store.brief(identity)
    path = inside(store.root, output)
    if path == store.project(identity) / "brief.json":
        raise BriefError("Export must not overwrite live brief state")
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        save(path, brief, exclusive=True)
    else:
        text = (
            f"# {identity} Video Brief\n\n"
            "Initialization is not render approval.\n\n"
            "## Complete Brief\n\n```json\n"
            f"{json.dumps(brief, indent=2)}\n```\n"
        )
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    return {"output": output}


def orient(store, identity, reader=input):
    brief = store.brief(identity)
    orientation = reader("Orientation [landscape/portrait/square]: ").strip()
    captions = reader("Captions [none/static/highlight]: ").strip()
    count_text = reader(
        "Total number of explicit variants (no Cartesian expansion): "
    ).strip()
    if not count_text.isdigit() or not 1 <= int(count_text) <= 20:
        raise BriefError("Enter 1-20 variants")
    dimensions = {
        "landscape": (1920, 1080),
        "portrait": (1080, 1920),
        "square": (1080, 1080),
    }
    if orientation not in dimensions or captions not in {
        "none",
        "static",
        "highlight",
    }:
        raise BriefError("Invalid orientation or captions")
    width, height = dimensions[orientation]
    variants = []
    for index in range(int(count_text)):
        print(f"Variant {index + 1}/{count_text}")
        variants.append(
            {
                "id": reader("Unique variant ID: ").strip(),
                "project_dir": reader("Authored scene directory: ").strip(),
                "orientation": orientation,
                "width": width,
                "height": height,
                "fps": 30,
                "captions": captions,
                "differences": reader(
                    "Each variant's exact customizations: voice, style, "
                    "hook, assets, colors and other differences (or base): "
                ).strip(),
            }
        )
    candidate = {**brief, "variants": variants}
    validate(candidate)
    print(json.dumps(variants, indent=2))
    if (
        reader(
            f"Confirm exactly {len(variants)} variants "
            "and these differences? [yes/no]: "
        )
        .strip()
        .lower()
        != "yes"
    ):
        raise BriefError("Variant selection cancelled; brief unchanged")
    store.save_brief(candidate)
    plan = production.prepare(store, identity)
    print(f"Prepared approval ID: {plan['approval_id']}")
    confirmation = reader(
        "To render, type that exact approval ID (blank cancels): "
    ).strip()
    if confirmation != plan["approval_id"]:
        return {
            "approval_id": plan["approval_id"],
            "status": "awaiting approval",
        }
    return production.produce(store, identity, confirmation)


def preview(
    store,
    identity,
    voices=None,
    video=False,
    start=0,
    seconds=8,
    storyboards_only=False,
):
    from .schema import number

    number(start, "preview start")
    number(seconds, "preview seconds", 0.1)
    brief = store.brief(identity)
    if seconds > brief.get("limits", {}).get("max_preview_seconds", 10):
        raise BriefError("Preview exceeds max_preview_seconds")
    options = storyboard(store, brief)
    record = {
        "storyboard_options": options,
        "note": (
            "Storyboard proposals only; scene authoring and approval "
            "are separate. Every final variant requires SRT and thumbnail."
        ),
    }
    if storyboards_only and (voices or video):
        raise BriefError("--storyboards-only cannot request audio or video")
    if storyboards_only or not voices and not video:
        return record
    plan = None
    if video:
        source = brief
        plan = production.source_plan(
            store, source, require_sample_approval=False
        )
        if any(
            start + seconds > variant["duration_s"]
            for variant in plan["variants"]
        ):
            raise BriefError("Video preview exceeds finished length")
        from fractions import Fraction

        if any(
            (Fraction(str(seconds)) * variant["fps"]).denominator != 1
            for variant in plan["variants"]
        ):
            raise BriefError(
                "Preview seconds must represent a whole number of frames "
                "for every variant"
            )
    if voices:
        record.update(speech.samples(store, identity, voices, seconds))
    if video:
        staged = production.stage_sources(
            store, identity, plan, prefix="previews"
        )
        rendered = production.render_variants(
            store, staged, {"start_s": start, "duration_s": seconds}
        )
        production.verify_record(store, rendered, prefix="previews")
        record["video_run_id"] = rendered["run_id"]
        record["video_note"] = (
            "Video uses the prepared scene narration, "
            "not the voice comparison samples."
        )
    return record


def parser():
    result = argparse.ArgumentParser(
        prog="python -m aigenvidagent",
        description=(
            "Local MAF video workflow; authored scenes "
            "and prepared narration required for rendering."
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "initialize",
        "export",
        "voices",
        "providers",
        "preview",
        "produce",
        "verify",
    ):
        sub = commands.add_parser(name)
        sub.add_argument("project", type=safe_id)
        if name == "initialize":
            sub.add_argument("--import", dest="import_file")
            sub.add_argument("--answers")
            sub.add_argument(
                "--url",
                help=(
                    "Public readable HTTPS page; archive text "
                    "and create an unlocked draft"
                ),
            )
        elif name == "export":
            sub.add_argument(
                "--format", choices=("json", "markdown"), required=True
            )
            sub.add_argument("--output", required=True)
        elif name == "voices":
            sub.add_argument("--refresh", action="store_true")
        elif name == "providers":
            pass
        elif name == "preview":
            sub.add_argument("--voices", nargs="+")
            sub.add_argument("--storyboards-only", action="store_true")
            sub.add_argument("--video", action="store_true")
            sub.add_argument("--start", type=float, default=0)
            sub.add_argument("--seconds", type=float, default=8)
        elif name == "produce":
            group = sub.add_mutually_exclusive_group()
            group.add_argument("--prepare", action="store_true")
            group.add_argument("--approve")
        else:
            sub.add_argument("--run", required=True)
    return result


def main(argv=None, root=None):
    arguments = parser().parse_args(argv)
    store = Store(root or Path(__file__).resolve().parents[1])
    try:
        if arguments.command == "initialize":
            initialize(
                store,
                arguments.project,
                arguments.import_file,
                arguments.answers,
                interactive=sys.stdin.isatty() and not arguments.answers,
                url=arguments.url,
            )
        elif arguments.command == "export":
            print(
                json.dumps(
                    export_brief(
                        store,
                        arguments.project,
                        arguments.format,
                        arguments.output,
                    ),
                    indent=2,
                )
            )
        elif arguments.command == "providers":
            print(
                json.dumps(
                    provider_metadata(store.brief(arguments.project)), indent=2
                )
            )
        elif arguments.command == "voices":
            print(
                json.dumps(
                    speech.voices(store, arguments.project, arguments.refresh),
                    indent=2,
                )
            )
        elif arguments.command == "preview":
            print(
                json.dumps(
                    preview(
                        store,
                        arguments.project,
                        arguments.voices,
                        arguments.video,
                        arguments.start,
                        arguments.seconds,
                        arguments.storyboards_only,
                    ),
                    indent=2,
                )
            )
        elif arguments.command == "produce":
            if arguments.prepare:
                result = production.prepare(store, arguments.project)
                print(json.dumps(result, indent=2))
                print(
                    "Approval required: python -m aigenvidagent produce "
                    f"{arguments.project} --approve {result['approval_id']}"
                )
            elif arguments.approve:
                print(
                    json.dumps(
                        production.produce(
                            store, arguments.project, arguments.approve
                        ),
                        indent=2,
                    )
                )
            elif sys.stdin.isatty():
                print(json.dumps(orient(store, arguments.project), indent=2))
            else:
                raise BriefError(
                    "Noninteractive produce needs --prepare or --approve ID; "
                    "initialize is not production permission"
                )
        else:
            print(
                json.dumps(
                    production.verify(store, arguments.project, arguments.run),
                    indent=2,
                )
            )
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "Paused; onboarding answers already saved. "
            "Resume initialize with the same project ID.",
            file=sys.stderr,
        )
        return 130
    except Exception as error:
        print(f"aigenvidagent: {error}", file=sys.stderr)
        return 2
