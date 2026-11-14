"""Portable audition adapters. No authentication, installs or downloads are automatic.

Call providers(speech) before requesting access or consent. Cloud synthesis sends
the excerpt and pronunciation/delivery choices to the named service and can incur
charges. OpenAI catalogs are user-configured, not discovered from a voices API.
Piper requires an installed PATH executable and approved workspace model files.
"""

import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener
import wave

from .schema import BriefError, speech_configurations
from .storage import inside, load


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(NoRedirect()).open


def providers(speech):
    """Return offline auth, discovery, data and billing explanations for CLI intake."""
    result = []
    for config in speech_configurations(speech):
        provider = config["provider"]
        auth = config.get("auth", "key" if provider != "piper" else "none")
        descriptions = {
            "azure": {
                "key": "Resource key in SPK (no Entra RBAC). Legacy regional STS token in SPEECH_TOKEN is also accepted when SPK is absent; it is not an Entra token.",
                "entra": "Entra RBAC: Cognitive Services Speech User on this Speech resource and a Cognitive Services access token in AZURE_ACCESS_TOKEN; resource must be configured for Entra authentication. No login or role assignment is performed.",
                "speech_token": "Legacy Speech STS token in SPEECH_TOKEN, issued using the resource key; not an Entra token. Use a regional token with this regional endpoint.",
            },
            "openai": {
                "key": "OpenAI project API key in OPENAI_API_KEY with audio/speech access; Azure RBAC does not apply."
            },
            "elevenlabs": {
                "key": "ElevenLabs API key in ELEVENLABS_API_KEY with voices/models read and text-to-speech access; Azure RBAC does not apply."
            },
            "piper": {
                "none": "No cloud credentials. Runs only an installed piper executable from PATH with explicitly approved workspace model files; no downloads."
            },
        }
        discovery = {
            "azure": "live regional voices API",
            "elevenlabs": "live /v1/voices and /v1/models APIs",
            "openai": "user-configured voices and model; no live voice discovery endpoint",
            "piper": "local model configuration speaker catalog",
        }[provider]
        result.append(
            {
                "id": config["id"],
                "provider": provider,
                "model": config.get("model")
                or (
                    "service-managed"
                    if provider == "azure"
                    else config.get("model_path", "")
                ),
                "auth": auth,
                "auth_description": descriptions[provider][auth],
                "discovery": discovery,
                "cloud": provider != "piper",
                "data": "Excerpt, pronunciation substitutions, voice/model and delivery settings sent to "
                + provider
                if provider != "piper"
                else "Text and audio remain local",
                "billing": "Synthesis may incur service charges; truncating the WAV does not cap billed generation. Check the selected model/account pricing."
                if provider != "piper"
                else "No service charges; local compute and model license apply",
            }
        )
    return result


def identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value
    ):
        raise BriefError(f"Set a valid {field}")
    return value


def json_response(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise BriefError(
            "Voice service returned invalid JSON (response suppressed)"
        ) from None


def cloud_request(provider, suffix, body=None):
    host, credential, header = {
        "openai": (
            "https://api.openai.com",
            "OPENAI_API_KEY",
            "Authorization",
        ),
        "elevenlabs": (
            "https://api.elevenlabs.io",
            "ELEVENLABS_API_KEY",
            "xi-api-key",
        ),
    }[provider]
    secret = os.environ.get(credential)
    if not secret:
        raise BriefError(
            f"Set {credential} in the runtime environment; never put credentials in the brief"
        )
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "aigenvidagent-local",
    }
    headers[header] = "Bearer " + secret if provider == "openai" else secret
    try:
        with urlopen(
            Request(
                host + suffix,
                data=None
                if body is None
                else json.dumps(body).encode("utf-8"),
                headers=headers,
            ),
            timeout=30,
        ) as response:
            return response.read()
    except (URLError, OSError, ValueError):
        raise BriefError(
            f"{provider} request failed; check account access, credentials and network (details suppressed)"
        ) from None


def pcm_wav(data, rate=24000):
    if not data or len(data) % 2:
        raise BriefError("Speech returned empty or invalid 16-bit PCM audio")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(data)
    return stream.getvalue()


class Azure:
    def __init__(self, config, request):
        self.config = config
        self.request = request

    def voices(self, root, locale):
        rows = json_response(
            self.request(self.config, "/cognitiveservices/voices/list")
        )
        if not isinstance(rows, list):
            raise BriefError("Azure returned an invalid voice catalog")
        return [
            {
                "voice_id": identifier(row.get("ShortName"), "Azure voice ID"),
                "locale": row["Locale"],
                "styles": row.get("StyleList", []),
                "gender": row.get("Gender"),
                "context": row.get("VoiceTag", {}),
                "catalog_source": "live",
            }
            for row in rows
            if isinstance(row, dict)
            and (
                row.get("Locale") == locale
                or locale in row.get("SecondaryLocaleList", [])
            )
        ]

    def synthesize(self, root, row, text, pronunciations):
        excerpt = html.escape(text)
        if pronunciations:
            pattern = "|".join(
                re.escape(written)
                for written in sorted(pronunciations, key=len, reverse=True)
            )
            excerpt = "".join(
                html.escape(part)
                if index % 2 == 0
                else f'<sub alias="{html.escape(pronunciations[part], quote=True)}">{html.escape(part)}</sub>'
                for index, part in enumerate(re.split(f"({pattern})", text))
            )
        if self.config.get("style"):
            excerpt = f'<mstts:express-as style="{html.escape(self.config["style"], quote=True)}">{excerpt}</mstts:express-as>'
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" '
            f'xml:lang="{html.escape(self.config["locale"], quote=True)}">'
            f'<voice name="{html.escape(row["voice_id"], quote=True)}">{excerpt}</voice></speak>'
        )
        return self.request(
            self.config, "/cognitiveservices/v1", ssml.encode("utf-8")
        )


class OpenAI:
    def __init__(self, config):
        self.config = config

    def voices(self, root, locale):
        identifier(self.config.get("model"), "OpenAI model")
        if self.config.get("instructions") and self.config["model"] in {
            "tts-1",
            "tts-1-hd",
        }:
            raise BriefError("This OpenAI model does not support instructions")
        catalog = self.config.get("voices")
        if not isinstance(catalog, list) or not catalog:
            raise BriefError(
                "OpenAI requires a user-configured speech.voices catalog and model; no live voice discovery endpoint exists"
            )
        result = []
        for voice in catalog:
            entry = {"id": voice} if isinstance(voice, str) else voice
            if not isinstance(entry, dict):
                raise BriefError(
                    "OpenAI configured voices must be IDs or objects with id and optional locale"
                )
            identity = identifier(
                entry.get("id"), "configured OpenAI voice ID"
            )
            if entry.get("locale", locale) == locale:
                result.append(
                    {
                        "voice_id": identity,
                        "locale": locale,
                        "styles": [],
                        "catalog_source": "configured",
                    }
                )
        return result

    def synthesize(self, root, row, text, pronunciations):
        body = {
            "model": self.config["model"],
            "voice": row["voice_id"],
            "input": spoken_text(text, pronunciations),
            "response_format": "wav",
        }
        if self.config.get("instructions"):
            if self.config["model"] in {"tts-1", "tts-1-hd"}:
                raise BriefError(
                    "This OpenAI model does not support instructions"
                )
            body["instructions"] = self.config["instructions"]
        return cloud_request("openai", "/v1/audio/speech", body)


class ElevenLabs:
    def __init__(self, config):
        self.config = config

    def voices(self, root, locale):
        model = identifier(self.config.get("model"), "ElevenLabs model")
        models = json_response(cloud_request("elevenlabs", "/v1/models"))
        if not isinstance(models, list):
            raise BriefError("ElevenLabs returned an invalid model catalog")
        supported = [
            row
            for row in models
            if isinstance(row, dict)
            and row.get("can_do_text_to_speech") is True
        ]
        selected = next(
            (row for row in supported if row.get("model_id") == model), None
        )
        if selected is None:
            raise BriefError(
                "Select an available ElevenLabs text-to-speech model: "
                + ", ".join(
                    identifier(row.get("model_id"), "ElevenLabs model ID")
                    for row in supported
                )
            )
        language = locale.split("-")[0].lower()
        if selected.get("languages") and not any(
            row.get("language_id") == language for row in selected["languages"]
        ):
            raise BriefError(
                "Selected ElevenLabs model does not support the requested locale"
            )
        catalog = json_response(cloud_request("elevenlabs", "/v1/voices"))
        if not isinstance(catalog, dict) or not isinstance(
            catalog.get("voices"), list
        ):
            raise BriefError("ElevenLabs returned an invalid voice catalog")
        return [
            {
                "voice_id": identifier(
                    row.get("voice_id"), "ElevenLabs voice ID"
                ),
                "display_name": row.get("name"),
                "locale": locale,
                "locale_source": "model language support; audition accent separately",
                "styles": [],
                "catalog_source": "live",
                "models": [entry["model_id"] for entry in supported],
            }
            for row in catalog["voices"]
            if isinstance(row, dict)
        ]

    def synthesize(self, root, row, text, pronunciations):
        audio = cloud_request(
            "elevenlabs",
            "/v1/text-to-speech/"
            + quote(row["voice_id"], safe="")
            + "?output_format=pcm_24000",
            {
                "text": spoken_text(text, pronunciations),
                "model_id": self.config["model"],
            },
        )
        return pcm_wav(audio)


def spoken_text(text, pronunciations):
    if not pronunciations:
        return text
    pattern = "|".join(
        re.escape(written)
        for written in sorted(pronunciations, key=len, reverse=True)
    )
    return re.sub(pattern, lambda match: pronunciations[match.group()], text)


class Piper:
    def __init__(self, config):
        self.config = config

    def files(self, root):
        path = self.config.get("model_path")
        if not path:
            raise BriefError(
                "Piper requires an existing workspace-relative model_path; no model is downloaded"
            )
        model = inside(root, path)
        sidecar = inside(root, path + ".json")
        if (
            model.suffix != ".onnx"
            or not model.is_file()
            or not sidecar.is_file()
        ):
            raise BriefError(
                "Piper model_path must name an installed .onnx model with its .onnx.json configuration"
            )
        if self.config.get("model_approved") is not True:
            raise BriefError(
                "Approve the local Piper model and its license with model_approved=true before use"
            )
        return model, sidecar

    def voices(self, root, locale):
        model, sidecar = self.files(root)
        self.executable()
        config = load(sidecar)
        actual_locale = (
            config.get("language", {}).get("code", "").replace("_", "-")
        )
        if actual_locale and actual_locale.lower() != locale.lower():
            return []
        speakers = config.get("speaker_id_map") or {model.stem: 0}
        if not isinstance(speakers, dict) or any(
            type(value) is not int or value < 0 for value in speakers.values()
        ):
            raise BriefError("Piper model has an invalid speaker_id_map")
        return [
            {
                "voice_id": identifier(name, "Piper speaker ID"),
                "speaker_id": speaker,
                "locale": actual_locale or locale,
                "styles": [],
                "catalog_source": "local",
            }
            for name, speaker in speakers.items()
        ]

    def executable(self):
        executable = shutil.which("piper")
        if not executable or Path(executable).suffix.lower() not in {
            "",
            ".exe",
        }:
            raise BriefError(
                "Piper executable is not installed on PATH; install/configure it separately with approval"
            )
        return str(Path(executable).resolve())

    def synthesize(self, root, row, text, pronunciations):
        model, sidecar = self.files(root)
        executable = self.executable()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOME",
                "USERPROFILE",
                "LANG",
                "LC_ALL",
            }
        }
        try:
            with tempfile.TemporaryDirectory(
                prefix="aigenvidagent-piper-"
            ) as temporary:
                output = Path(temporary) / "sample.wav"
                subprocess.run(
                    [
                        executable,
                        "-m",
                        str(model),
                        "-c",
                        str(sidecar),
                        "-f",
                        str(output),
                        "-s",
                        str(row["speaker_id"]),
                    ],
                    input=spoken_text(text, pronunciations) + "\n",
                    text=True,
                    encoding="utf-8",
                    env=environment,
                    cwd=root,
                    shell=False,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                if not output.is_file():
                    raise BriefError("Piper did not write WAV audio")
                return output.read_bytes()
        except (OSError, subprocess.SubprocessError):
            raise BriefError(
                "Local Piper synthesis failed (process output suppressed)"
            ) from None


def adapter(config, azure_request):
    if config["provider"] == "azure":
        return Azure(config, azure_request)
    return {"openai": OpenAI, "elevenlabs": ElevenLabs, "piper": Piper}[
        config["provider"]
    ](config)
