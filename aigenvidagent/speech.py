"""Consent-gated, provider-portable voice auditions and real WAV samples."""

import io
import os
import re
from urllib.error import URLError
from urllib.request import Request
import uuid
import wave

from .schema import (
    BriefError,
    authorized_resource,
    number,
    speech_configurations,
)
from .storage import digest, file_hash, inside, load, save
from .voice_providers import Piper, adapter, providers, urlopen


def sample_context(store, brief):
    configuration = {
        key: value
        for key, value in brief["speech"].items()
        if key not in {"voice", "sample_approval", "narration_path"}
    }
    script = inside(store.root, brief.get("script", {}).get("path", ""))
    local_files = {}
    for config in speech_configurations(brief["speech"]):
        if config["provider"] == "piper":
            for path in Piper(config).files(store.root):
                local_files[path.relative_to(store.root).as_posix()] = (
                    file_hash(path)
                )
    return digest(
        {
            "speech": configuration,
            "language": brief.get("language"),
            "script_sha256": file_hash(script),
            "pronunciations": brief.get("pronunciations", {}),
            "style": brief.get("style", {}),
            "local_models": local_files,
        }
    )


def request(speech, suffix, body=None):
    authorized_resource(speech.get("resource_id"))
    expected = os.environ.get("AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID", "")
    if not expected:
        raise BriefError(
            "Set AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID in the environment "
            "before Azure requests"
        )
    if speech["resource_id"].split("/")[2].lower() != expected.lower():
        raise BriefError(
            "Azure resource subscription does not match "
            "AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID"
        )
    region = speech.get("region", "")
    if not isinstance(region, str) or not re.fullmatch(
        r"[a-z][a-z0-9]{1,39}", region
    ):
        raise BriefError("Set speech.region before voice discovery")
    endpoint = f"https://{region}.tts.speech.microsoft.com"
    if speech.get("endpoint", "").rstrip("/") not in {"", endpoint}:
        raise BriefError(
            f"Speech endpoint must be the verified regional endpoint {endpoint}"
        )
    headers = {
        "User-Agent": "aigenvidagent-local",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
    }
    auth = speech.get("auth", "key")
    if not isinstance(auth, str) or auth not in {
        "key",
        "entra",
        "speech_token",
    }:
        raise BriefError("speech.auth must be key, entra or speech_token")
    if auth == "entra" and os.environ.get("AZURE_ACCESS_TOKEN"):
        headers["Authorization"] = (
            "Bearer aad#"
            + speech["resource_id"]
            + "#"
            + os.environ["AZURE_ACCESS_TOKEN"]
        )
    elif auth == "key" and os.environ.get("SPK"):
        headers["Ocp-Apim-Subscription-Key"] = os.environ["SPK"]
    elif auth in {"key", "speech_token"} and os.environ.get("SPEECH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["SPEECH_TOKEN"]
    else:
        raise BriefError(
            "Set runtime environment credentials for speech.auth: "
            "key uses SPK, entra uses AZURE_ACCESS_TOKEN, "
            "speech_token uses SPEECH_TOKEN; credentials are never saved"
        )
    try:
        with urlopen(
            Request(endpoint + suffix, data=body, headers=headers), timeout=30
        ) as response:
            return response.read()
    except (URLError, OSError, ValueError):
        raise BriefError(
            "Speech service request failed; check region, credentials "
            "and network (credentials suppressed)"
        ) from None


def voices(store, identity, refresh=False, *, provider_ids=None):
    brief = store.brief(identity)
    speech = brief.get("speech", {})
    configurations = speech_configurations(speech)
    descriptions = {row["id"]: row for row in providers(speech)}
    if provider_ids is not None:
        configurations = [
            config for config in configurations if config["id"] in provider_ids
        ]
    context = digest(
        {"configurations": configurations, "language": brief.get("language")}
    )
    if any(config["provider"] == "piper" for config in configurations):
        refresh = True
    cache = store.project(identity) / "voices.json"
    if cache.exists() and not refresh:
        cached = load(cache)
        if cached.get("context_hash") == context:
            return cached["voices"]
    selected = []
    for config in configurations:
        locale = config.get("locale") or brief.get("language")
        config = {**config, "locale": locale}
        rows = adapter(config, request).voices(store.root, locale)
        if not rows:
            raise BriefError(
                f"{config['provider']} returned no voices supporting {locale}; check the locale/catalog"
            )
        for row in rows:
            name = (
                f"{config['id']}/{row['voice_id']}"
                if "providers" in speech
                else row["voice_id"]
            )
            if any(previous["name"] == name for previous in selected):
                raise BriefError("Voice catalog contains duplicate IDs")
            selected.append(
                {
                    **row,
                    "name": name,
                    "provider_id": config["id"],
                    "provider": config["provider"],
                    "model": descriptions[config["id"]]["model"],
                    "auth": descriptions[config["id"]]["auth"],
                    "auth_description": descriptions[config["id"]][
                        "auth_description"
                    ],
                    "data": descriptions[config["id"]]["data"],
                    "billing": descriptions[config["id"]]["billing"],
                }
            )
    save(cache, {"context_hash": context, "voices": selected})
    return selected


def samples(store, identity, selected, seconds=8):
    brief = store.brief(identity)
    speech = brief["speech"]
    configurations = {
        config["id"]: config for config in speech_configurations(speech)
    }
    limits = brief.get("limits", {})
    seconds = number(seconds, "preview seconds", 0.1)
    if seconds > number(
        limits.get("max_preview_seconds", 10), "max_preview_seconds", 0.1
    ):
        raise BriefError("Preview exceeds max_preview_seconds")
    if (
        not selected
        or any(not isinstance(voice, str) for voice in selected)
        or len(selected) != len(set(selected))
        or len(selected) > limits.get("max_preview_voices", 3)
    ):
        raise BriefError("Select distinct voices within max_preview_voices")
    chosen_ids = set()
    for voice in selected:
        identity_part = (
            voice.split("/", 1)[0]
            if "providers" in speech
            else next(iter(configurations))
        )
        if identity_part not in configurations or (
            "providers" in speech and "/" not in voice
        ):
            raise BriefError(
                "Use a configured provider-id/voice-id from voices"
            )
        chosen_ids.add(identity_part)
    consent = brief.get("consents", {})
    decisions = consent.get("provider_samples", {})
    descriptions = {row["id"]: row for row in providers(speech)}
    pending = []
    for provider_id in sorted(chosen_ids):
        description = descriptions[provider_id]
        approved = (
            provider_id in decisions
            if isinstance(decisions, list)
            else decisions.get(provider_id) is True
        )
        if description["cloud"] and (
            consent.get("speech_samples") is not True
            or ("providers" in speech and not approved)
            or (
                isinstance(decisions, dict)
                and decisions.get(provider_id) is False
            )
        ):
            pending.append(
                f"{provider_id} ({description['provider']}): "
                f"{description['auth_description']} {description['data']}. {description['billing']}"
            )
    if pending:
        raise BriefError(
            "Speech sample consent required. "
            + " ".join(pending)
            + " After agreeing to data transfer and billing, set consents.speech_samples=true; "
            "with speech.providers also explicitly approve each selected cloud provider ID in consents.provider_samples."
        )
    if not brief.get("storyboard"):
        raise BriefError(
            "Create a sample storyboard during initialize before audio preview"
        )
    available = {
        row["name"]: row
        for row in voices(store, identity, provider_ids=chosen_ids)
    }
    for voice in selected:
        if voice not in available:
            raise BriefError(
                f"Voice {voice} was not discovered for this locale; run voices --refresh"
            )
        config = configurations[available[voice]["provider_id"]]
        if (
            config.get("style")
            and config["style"] not in available[voice]["styles"]
        ):
            raise BriefError(f"Voice {voice} does not support requested style")
    script = inside(store.root, brief.get("script", {}).get("path", ""))
    if not script.is_file():
        raise BriefError("Author a script before generating audio samples")
    text = " ".join(
        script.read_text(encoding="utf-8-sig").split()[
            : max(1, int(seconds * 2))
        ]
    )
    if not text:
        raise BriefError("Script is empty")
    context_hash = sample_context(store, brief)
    for provider_id in chosen_ids:
        config = configurations[provider_id]
        if config["provider"] in {"openai", "elevenlabs"}:
            credential = (
                "OPENAI_API_KEY"
                if config["provider"] == "openai"
                else "ELEVENLABS_API_KEY"
            )
            if not os.environ.get(credential):
                raise BriefError(
                    f"Set {credential} in the runtime environment before generating samples"
                )
        elif config["provider"] == "piper":
            Piper(config).executable()
    folder = inside(
        store.root, f"previews/{identity}/speech-{uuid.uuid4().hex}"
    )
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for index, voice in enumerate(selected):
        row = available[voice]
        config = configurations[row["provider_id"]]
        config = {
            **config,
            "locale": config.get("locale") or brief["language"],
        }
        audio = adapter(config, request).synthesize(
            store.root, row, text, brief.get("pronunciations", {})
        )
        output = folder / f"sample-{index + 1}.wav"
        try:
            with (
                wave.Wave_read(io.BytesIO(audio)) as source,
                wave.Wave_write(str(output)) as target,
            ):
                target.setparams(source.getparams())
                target.writeframes(
                    source.readframes(int(source.getframerate() * seconds))
                )
            with wave.open(str(output), "rb") as check:
                if check.getnframes() == 0:
                    raise BriefError("Speech returned empty audio")
        except (wave.Error, EOFError) as error:
            raise BriefError(
                "Speech did not return valid WAV audio"
            ) from error
        results.append(
            {
                "voice": voice,
                "voice_id": row["voice_id"],
                "provider": row["provider"],
                "provider_id": row["provider_id"],
                "model": row["model"],
                "path": output.relative_to(store.root).as_posix(),
                "sha256": file_hash(output),
            }
        )
    record = {
        "excerpt": text,
        "samples": results,
        "max_seconds": seconds,
        "selected_voice": None,
        "context_hash": context_hash,
        "provider_consents": {
            provider_id: {
                **descriptions[provider_id],
                "approved": True,
            }
            for provider_id in sorted(chosen_ids)
        },
        "manifest_path": (folder / "samples.json")
        .relative_to(store.root)
        .as_posix(),
    }
    save(folder / "samples.json", record, exclusive=True)
    return record
