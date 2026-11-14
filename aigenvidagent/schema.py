"""Brief validation shared by onboarding and production."""

import math
import re


class BriefError(ValueError):
    pass


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value
    ):
        raise BriefError(
            "IDs must be 1-64 letters, digits, underscores or hyphens"
        )
    if value.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }:
        raise BriefError("Windows device names are not valid IDs")
    return value


def number(value, name, minimum=0):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < minimum
    ):
        raise BriefError(f"{name} must be a finite number >= {minimum}")
    return value


def duration_bounds(duration):
    if not isinstance(duration, dict):
        raise BriefError("duration must be an object")
    exact = duration.get("exact_s")
    low, high = duration.get("min_s"), duration.get("max_s")
    if exact is not None:
        if low is not None or high is not None:
            raise BriefError("Use exact_s OR min_s and max_s, not both")
        low = high = number(exact, "exact_s", 0.001)
    else:
        low = number(low, "min_s", 0.001)
        high = number(high, "max_s", 0.001)
    hold = number(duration.get("hold_s", 3), "hold_s")
    if low > high:
        raise BriefError("min_s must not exceed max_s")
    if hold >= low:
        raise BriefError(
            "Ending hold must be shorter than the minimum finished length"
        )
    return low, high, hold


def validate(brief, complete=False):
    if (
        not isinstance(brief, dict)
        or type(brief.get("schema_version")) is not int
        or brief.get("schema_version") != 1
    ):
        raise BriefError("schema_version must be 1")
    safe_id(brief.get("project_id"))
    for field in (
        "duration",
        "coding_model",
        "script",
        "speech",
        "style",
        "limits",
        "consents",
        "preview",
        "brand",
        "claims",
        "privacy",
        "music",
        "pronunciations",
        "onboarding",
    ):
        if field in brief and not isinstance(brief[field], dict):
            raise BriefError(f"{field} must be an object")
    for field in (
        "assets", "storyboard", "storyboard_options", "sources", "dependencies"
    ):
        if field in brief and not isinstance(brief[field], list):
            raise BriefError(f"{field} must be a list")
    if brief.get("duration") and any(
        brief["duration"].get(field) is not None
        for field in ("exact_s", "min_s", "max_s")
    ):
        duration_bounds(brief["duration"])
    elif complete:
        raise BriefError("duration is required")
    reject_secrets(brief)
    if "deliverables" in brief and (
        not isinstance(brief["deliverables"], list)
        or not {"video", "srt", "thumbnail"}.issubset(brief["deliverables"])
    ):
        raise BriefError(
            "Every variant must include video, srt and thumbnail deliverables"
        )
    if "variant_customization_prompt" in brief and not isinstance(
        brief["variant_customization_prompt"], str
    ):
        raise BriefError("variant_customization_prompt must be text")
    for decision in brief.get("consents", {}).get("optional_installs", []):
        if (
            not isinstance(decision, dict)
            or decision.get("scope") not in {"workspace", "user"}
            or decision.get("kind") not in {"skill", "mcp"}
            or not decision.get("name")
            or not isinstance(decision.get("consent"), bool)
        ):
            raise BriefError(
                "Optional install decisions require name, kind=skill|mcp, scope=workspace|user and boolean consent; nothing is installed automatically"
            )
    for field in ("max_retries", "max_preview_voices", "max_preview_seconds"):
        if field in brief.get("limits", {}):
            value = number(
                brief["limits"][field],
                field,
                0 if field == "max_retries" else 0.1,
            )
            if field != "max_preview_seconds" and not isinstance(value, int):
                raise BriefError(f"{field} must be an integer")
    preview = brief.get("preview", {})
    if preview:
        number(preview.get("start_s", 0), "preview.start_s")
        seconds = number(
            preview.get("duration_s", 8), "preview.duration_s", 0.1
        )
        if seconds > brief.get("limits", {}).get("max_preview_seconds", 10):
            raise BriefError("preview.duration_s exceeds max_preview_seconds")
    seen = set()
    if not isinstance(brief.get("variants", []), list):
        raise BriefError("variants must be an explicit list")
    for variant in brief.get("variants", []):
        if not isinstance(variant, dict):
            raise BriefError("Each variant must be an object")
        identity = safe_id(variant.get("id"))
        if identity.lower() in seen:
            raise BriefError("Duplicate variant ID")
        seen.add(identity.lower())
        if variant.get("orientation") not in {
            "landscape",
            "portrait",
            "square",
        }:
            raise BriefError(
                "variant orientation must be landscape, portrait or square"
            )
        for field in ("width", "height", "fps"):
            value = number(variant.get(field), field, 1)
            if not isinstance(value, int) or value > (
                120 if field == "fps" else 8192
            ):
                raise BriefError(f"Invalid variant {field}")
        width, height = variant["width"], variant["height"]
        if width % 2 or height % 2:
            raise BriefError("Variant dimensions must be even for H.264")
        orientation = (
            "square"
            if width == height
            else "landscape"
            if width > height
            else "portrait"
        )
        if variant["orientation"] != orientation:
            raise BriefError("Variant orientation does not match dimensions")
        if variant.get("captions") not in {"none", "static", "highlight"}:
            raise BriefError("captions must be none, static or highlight")
        if not variant.get("project_dir") or not variant.get("differences"):
            raise BriefError(
                "Each variant needs project_dir and explicit differences"
            )
        if "customizations" in variant and not isinstance(
            variant["customizations"], dict
        ):
            raise BriefError(
                "Each variant customizations must be an object: "
                "voice, style, hook, assets, colors, notes"
            )
        custom = variant.get("customizations", {})
        if "assets" in custom and not isinstance(custom["assets"], list):
            raise BriefError("Variant customization assets must be a list")
    speech = brief.get("speech", {})
    if not isinstance(speech, dict):
        raise BriefError("speech must be an object")
    speech_configurations(speech)
    provider_consents = brief.get("consents", {}).get("provider_samples", {})
    if not (
        isinstance(provider_consents, dict)
        and all(
            isinstance(key, str) and isinstance(value, bool)
            for key, value in provider_consents.items()
        )
        or isinstance(provider_consents, list)
        and all(isinstance(value, str) for value in provider_consents)
    ):
        raise BriefError(
            "consents.provider_samples must be provider IDs or an ID-to-boolean object"
        )
    style = brief.get("style", {})
    if not isinstance(style, dict) or style.get("preset") not in {
        None,
        "professional",
        "executive",
        "developer",
        "casual",
        "friendly",
        "custom",
    }:
        raise BriefError("Unknown style preset")
    if style.get("preset") == "custom" and not style.get("custom"):
        raise BriefError("Describe the custom style")
    for asset in brief.get("assets", []):
        if not isinstance(asset, dict) or not all(
            asset.get(field)
            for field in ("type", "purpose", "required_detail", "licensing")
        ):
            raise BriefError(
                "Assets need type, purpose, required_detail and licensing"
            )
        if not asset.get("path") and not asset.get("url"):
            raise BriefError("Assets need a local path or source URL")
        if asset.get("url"):
            from urllib.parse import urlsplit

            parsed = urlsplit(asset["url"])
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.query
                or parsed.username
                or parsed.fragment
            ):
                raise BriefError(
                    "Asset URLs must be public HTTPS references without credentials/query tokens; stage private assets locally"
                )
    if complete:
        for field in ("audience", "goal", "venue", "language"):
            if (
                not isinstance(brief.get(field), str)
                or not brief[field].strip()
            ):
                raise BriefError(f"{field} is required")
        model = brief.get("coding_model", {})
        if not model.get("name") or model.get("confirmed_by_user") is not True:
            raise BriefError(
                "Confirm the selected coding model during initialize"
            )
        if not style.get("preset"):
            raise BriefError("Choose a style")
        if not brief.get("variants"):
            raise BriefError("Provide an explicit variants list")
        if brief.get("script", {}).get("locked") is not True:
            raise BriefError("Lock the script before preparing production")
        if (
            not brief.get("storyboard")
            or brief.get("storyboard_approved") is not True
        ):
            raise BriefError(
                "Create and explicitly approve the sample storyboard first"
            )
        if any(
            variant.get("customizations") for variant in brief["variants"]
        ) and not brief.get("storyboard_options"):
            raise BriefError(
                "Preview and approve a storyboard OPTION for each "
                "customized variant before production"
            )
    return brief


def storyboard_context(brief, script_hash):
    from .storage import digest

    return digest({
        "script_sha256": script_hash, "variants": brief.get("variants", []),
        "style": brief.get("style", {}), "assets": brief.get("assets", []),
        "brand": brief.get("brand", {}), "duration": brief.get("duration", {}),
        "speech": {
            key: value for key, value in brief.get("speech", {}).items()
            if key != "sample_approval"
        },
        "pronunciations": brief.get("pronunciations", {}),
        "claims": brief.get("claims", {}), "privacy": brief.get("privacy", {}),
        "language": brief.get("language"), "goal": brief.get("goal"),
        "audience": brief.get("audience"), "sources": brief.get("sources", []),
    })


def authorized_resource(resource):
    pattern = (
        r"/subscriptions/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
        r"/resourceGroups/[a-z0-9_.()-]+"
        r"/providers/Microsoft.CognitiveServices/accounts/[a-z0-9_-]+"
    )
    if not isinstance(resource, str) or not re.fullmatch(
        pattern, resource, re.IGNORECASE
    ):
        raise BriefError(
            "Speech resource_id must be a structurally valid "
            "Cognitive Services account resource ID"
        )


def speech_configurations(speech):
    if not isinstance(speech, dict):
        raise BriefError("speech must be an object")
    configured = speech.get("providers")
    if "providers" in speech and (
        not isinstance(configured, list) or not configured
    ):
        raise BriefError("speech.providers must be a nonempty list")
    result = []
    seen = set()
    for entry in configured if configured is not None else [speech]:
        if not isinstance(entry, dict):
            raise BriefError("Each speech provider must be an object")
        reject_secrets(entry)
        provider = entry.get("provider", "azure")
        if not isinstance(provider, str) or provider not in {
            "azure",
            "openai",
            "elevenlabs",
            "piper",
        }:
            raise BriefError(
                "Unknown speech provider; choose azure, openai, "
                "elevenlabs or piper"
            )
        identity = safe_id(entry.get("id", provider))
        if identity.lower() in seen:
            raise BriefError("Speech provider IDs must be unique")
        seen.add(identity.lower())
        auth = entry.get("auth", "none" if provider == "piper" else "key")
        allowed = (
            {"key", "entra", "speech_token"}
            if provider == "azure"
            else {"none"}
            if provider == "piper"
            else {"key"}
        )
        if not isinstance(auth, str) or auth not in allowed:
            raise BriefError("Unsupported speech provider auth mode")
        for field in (
            "model",
            "model_path",
            "locale",
            "style",
            "instructions",
            "region",
            "endpoint",
            "resource_id",
        ):
            if field in entry and not isinstance(entry[field], str):
                raise BriefError(f"speech.{field} must be a string")
        if "voices" in entry and (
            not isinstance(entry["voices"], list)
            or any(
                not isinstance(voice, (str, dict)) for voice in entry["voices"]
            )
        ):
            raise BriefError(
                "speech.voices must be a configured list of "
                "voice IDs or objects"
            )
        if provider == "azure" and entry.get("resource_id"):
            authorized_resource(entry["resource_id"])
        if provider != "azure" and entry.get("endpoint"):
            raise BriefError(
                "Custom speech endpoints are not supported; "
                "credentials use fixed provider hosts"
            )
        if entry.get("style") and provider != "azure":
            raise BriefError(
                "speech.style is supported only by Azure; "
                "use OpenAI instructions where supported"
            )
        if provider == "azure" and entry.get("model") not in {
            None,
            "",
            "standard",
        }:
            raise BriefError(
                "Azure REST auditions use service-managed "
                "standard voice models"
            )
        if "model_approved" in entry and not isinstance(
            entry["model_approved"], bool
        ):
            raise BriefError("model_approved must be boolean")
        if provider == "piper" and any(
            field in entry for field in ("executable", "command", "args")
        ):
            raise BriefError(
                "Piper runs only the fixed piper executable from PATH; "
                "shell commands/arguments are not accepted"
            )
        result.append(
            {
                **entry,
                "provider": provider,
                "id": identity,
                "auth": auth,
                "locale": entry.get("locale") or speech.get("locale", ""),
            }
        )
    return result


def reject_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if re.sub(r"[^a-z]", "", key.lower()) in {
                "apikey",
                "key",
                "token",
                "password",
                "secret",
                "subscriptionkey",
                "authorization",
                "connectionstring",
                "accesstoken",
                "clientsecret",
                "speechkey",
                "spk",
                "bearertoken",
                "openaiapikey",
                "elevenlabsapikey",
                "azureaccesstoken",
                "speechtoken",
                "credential",
                "credentials",
                "headers",
                "privatekey",
                "accesskey",
            }:
                raise BriefError(
                    "Do not persist secrets; use runtime environment "
                    "variables for provider credentials"
                )
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
