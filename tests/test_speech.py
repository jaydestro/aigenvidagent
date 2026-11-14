import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import traceback
import unittest
from unittest.mock import patch
from urllib.error import URLError
import wave

from aigenvidagent import production, speech, voice_providers
from aigenvidagent.cli import main, preview
from aigenvidagent.schema import BriefError, authorized_resource, validate
from aigenvidagent.storage import load, save
from test_workflow import ProjectFixture


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


def wav_bytes(seconds=1):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * int(seconds * 24000))
    return stream.getvalue()


class SpeechTests(ProjectFixture):
    def configure(self, configuration):
        self.brief["speech"] = configuration
        validate(self.brief)
        self.store.save_brief(self.brief)

    def mock_http(self, mock, payloads):
        def respond(request, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            payload = payloads[request.full_url]
            if isinstance(payload, Exception):
                raise payload
            response = unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value = (
                payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode()
            )
            return response

        mock.side_effect = respond

    def local_config(self):
        folder = self.root / "models"
        folder.mkdir(exist_ok=True)
        (folder / "sample.onnx").write_bytes(b"mock model")
        save(
            folder / "sample.onnx.json",
            {"language": {"code": "fr_FR"}, "speaker_id_map": {"speaker": 0}},
        )
        return {
            "id": "offline",
            "provider": "piper",
            "model_path": "models/sample.onnx",
            "model_approved": True,
            "locale": "fr-FR",
        }

    def test_provider_auth_descriptions_are_available_offline(self):
        self.configure(
            {
                "providers": [
                    {"id": "az", "provider": "azure", "auth": "entra"},
                    {
                        "id": "oa",
                        "provider": "openai",
                        "model": "user-tts-model",
                        "voices": ["configured-voice"],
                    },
                    {
                        "id": "el",
                        "provider": "elevenlabs",
                        "model": "user-model",
                    },
                    {"id": "pc", "provider": "piper"},
                ]
            }
        )
        with patch("aigenvidagent.voice_providers.urlopen") as remote:
            found = speech.providers(self.brief["speech"])
        remote.assert_not_called()
        self.assertIn("Speech User", found[0]["auth_description"])
        self.assertIn("OPENAI_API_KEY", found[1]["auth_description"])
        self.assertIn("ELEVENLABS_API_KEY", found[2]["auth_description"])
        self.assertFalse(found[3]["cloud"])
        self.assertIn("no live", found[1]["discovery"])

    def test_openai_configured_catalog_and_wav_request_without_azure(self):
        self.configure(
            {
                "provider": "openai",
                "model": "user-tts-model",
                "voices": ["configured-voice"],
                "locale": "fr-FR",
            }
        )
        with (
            patch.dict(
                os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=True
            ),
            patch("aigenvidagent.voice_providers.urlopen") as remote,
            patch("aigenvidagent.speech.request") as azure,
        ):
            found = speech.voices(self.store, "launch", refresh=True)
            remote.assert_not_called()
            self.assertEqual(found[0]["catalog_source"], "configured")
            self.mock_http(
                remote,
                {"https://api.openai.com/v1/audio/speech": wav_bytes(2)},
            )
            record = speech.samples(
                self.store, "launch", ["configured-voice"], seconds=1
            )
            request = remote.call_args.args[0]
            self.assertEqual(
                request.get_header("Authorization"), "Bearer runtime-secret"
            )
            self.assertEqual(
                json.loads(request.data),
                {
                    "model": "user-tts-model",
                    "voice": "configured-voice",
                    "input": "Welcome. This",
                    "response_format": "wav",
                },
            )
            azure.assert_not_called()
        sample = record["samples"][0]
        self.assertEqual(
            (sample["provider"], sample["model"]), ("openai", "user-tts-model")
        )
        with wave.open(str(self.root / sample["path"])) as audio:
            self.assertEqual(audio.getnframes(), 24000)
        self.assertNotIn(
            "runtime-secret", (self.root / record["manifest_path"]).read_text()
        )
        self.assertEqual(
            record["provider_consents"]["openai"]["approved"], True
        )

    def test_openai_requires_catalog_and_model_and_rejects_unsupported_instructions(
        self,
    ):
        for config in (
            {"provider": "openai", "model": "user-model"},
            {"provider": "openai", "voices": ["configured-voice"]},
        ):
            self.configure(config)
            with (
                patch("aigenvidagent.voice_providers.urlopen") as remote,
                self.assertRaises(BriefError),
            ):
                speech.voices(self.store, "launch", refresh=True)
            remote.assert_not_called()
        self.configure(
            {
                "provider": "openai",
                "model": "tts-1",
                "voices": ["configured-voice"],
                "instructions": "Warm",
            }
        )
        with (
            patch("aigenvidagent.voice_providers.urlopen") as remote,
            self.assertRaisesRegex(BriefError, "instructions"),
        ):
            speech.samples(self.store, "launch", ["configured-voice"])
        remote.assert_not_called()

    def test_elevenlabs_live_catalog_model_validation_and_pcm_output(self):
        self.configure(
            {
                "provider": "elevenlabs",
                "model": "configured-model",
                "locale": "fr-FR",
            }
        )
        payloads = {
            "https://api.elevenlabs.io/v1/models": [
                {
                    "model_id": "configured-model",
                    "can_do_text_to_speech": True,
                    "languages": [{"language_id": "fr"}],
                },
                {"model_id": "not-tts", "can_do_text_to_speech": False},
            ],
            "https://api.elevenlabs.io/v1/voices": {
                "voices": [{"voice_id": "live-voice", "name": "Live Voice"}]
            },
            "https://api.elevenlabs.io/v1/text-to-speech/live-voice?output_format=pcm_24000": b"\0\0"
            * 48000,
        }
        with (
            patch.dict(
                os.environ,
                {"ELEVENLABS_API_KEY": "runtime-secret"},
                clear=True,
            ),
            patch("aigenvidagent.voice_providers.urlopen") as remote,
        ):
            self.mock_http(remote, payloads)
            found = speech.voices(self.store, "launch", refresh=True)
            self.assertEqual(found[0]["models"], ["configured-model"])
            self.assertEqual(found[0]["catalog_source"], "live")
            record = speech.samples(
                self.store, "launch", ["live-voice"], seconds=1
            )
            self.assertEqual(remote.call_count, 3)
            request = remote.call_args.args[0]
            self.assertEqual(
                request.get_header("Xi-api-key"), "runtime-secret"
            )
            self.assertEqual(
                json.loads(request.data)["model_id"], "configured-model"
            )
            with wave.open(
                str(self.root / record["samples"][0]["path"])
            ) as audio:
                self.assertEqual(
                    (audio.getframerate(), audio.getnframes()), (24000, 24000)
                )
            self.brief["speech"]["model"] = "not-tts"
            self.store.save_brief(self.brief)
            with self.assertRaisesRegex(BriefError, "configured-model"):
                speech.voices(self.store, "launch", refresh=True)

    def test_local_piper_real_wav_mocked_process_and_no_cloud_consent(self):
        config = self.local_config()
        self.configure(config)
        self.brief["consents"]["speech_samples"] = False
        self.store.save_brief(self.brief)

        def run(argv, **kwargs):
            self.assertIs(kwargs["shell"], False)
            self.assertIs(kwargs["check"], True)
            self.assertEqual(kwargs["input"], "Welcome. This\n")
            self.assertEqual(kwargs["cwd"], self.root)
            self.assertNotIn("SPK", kwargs["env"])
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertEqual(
                argv[argv.index("-m") + 1],
                str(self.root / "models/sample.onnx"),
            )
            Path(argv[argv.index("-f") + 1]).write_bytes(wav_bytes(2))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with (
            patch.dict(
                os.environ,
                {"SPK": "runtime-secret", "OPENAI_API_KEY": "runtime-secret"},
            ),
            patch(
                "aigenvidagent.voice_providers.shutil.which",
                return_value=str(self.root / "piper.exe"),
            ),
            patch(
                "aigenvidagent.voice_providers.subprocess.run", side_effect=run
            ) as process,
            patch("aigenvidagent.voice_providers.urlopen") as remote,
            patch("aigenvidagent.speech.request") as azure,
        ):
            found = speech.voices(self.store, "launch")
            record = speech.samples(
                self.store, "launch", [found[0]["name"]], seconds=1
            )
            process.assert_called_once()
            remote.assert_not_called()
            azure.assert_not_called()
        with wave.open(str(self.root / record["samples"][0]["path"])) as audio:
            self.assertEqual(audio.getnframes(), 24000)
        context = record["context_hash"]
        (self.root / config["model_path"]).write_bytes(b"changed model")
        self.assertNotEqual(
            context, speech.sample_context(self.store, self.brief)
        )

    def test_local_missing_model_approval_paths_and_shell_configuration(self):
        config = self.local_config()
        for change, message in (
            ({"model_path": ""}, "model_path"),
            ({"model_path": "models/missing.onnx"}, "installed"),
            ({"model_path": "../outside.onnx"}, "workspace"),
            (
                {"model_path": str(self.root / "models/sample.onnx")},
                "workspace",
            ),
            ({"model_approved": False}, "Approve"),
        ):
            self.configure({**config, **change})
            with (
                patch("aigenvidagent.voice_providers.subprocess.run") as process,
                self.assertRaisesRegex(BriefError, message),
            ):
                speech.voices(self.store, "launch", refresh=True)
            process.assert_not_called()
        with self.assertRaisesRegex(BriefError, "fixed"):
            self.configure({**config, "command": "piper && download"})

    def test_multi_provider_consent_qualified_names_and_production_approval(
        self,
    ):
        self.configure(
            {
                "providers": [
                    {
                        "id": "first",
                        "provider": "openai",
                        "model": "model-one",
                        "voices": ["voice"],
                    },
                    {
                        "id": "second",
                        "provider": "openai",
                        "model": "model-two",
                        "voices": ["voice"],
                    },
                ]
            }
        )
        selected = ["first/voice", "second/voice"]
        with patch("aigenvidagent.voice_providers.urlopen") as remote:
            found = speech.voices(self.store, "launch")
            self.assertEqual([row["name"] for row in found], selected)
            with self.assertRaisesRegex(BriefError, "provider_samples"):
                speech.samples(self.store, "launch", selected)
            self.brief["consents"]["provider_samples"] = {"first": True}
            self.store.save_brief(self.brief)
            with self.assertRaisesRegex(BriefError, "second"):
                speech.samples(self.store, "launch", selected)
            remote.assert_not_called()
            self.brief["consents"]["provider_samples"] = ["first", "second"]
            self.store.save_brief(self.brief)
            self.mock_http(
                remote,
                {"https://api.openai.com/v1/audio/speech": wav_bytes(1)},
            )
            with patch.dict(
                os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=True
            ):
                record = speech.samples(
                    self.store, "launch", selected, seconds=1
                )
        self.assertEqual(
            [row["model"] for row in record["samples"]],
            ["model-one", "model-two"],
        )
        self.brief["speech"].update(
            {
                "voice": "second/voice",
                "sample_approval": {
                    "approved": True,
                    "voice": "second/voice",
                    "manifest_path": record["manifest_path"],
                },
            }
        )
        production.source_plan(self.store, self.brief)
        self.brief["speech"]["providers"][1]["model"] = "new-model"
        with self.assertRaisesRegex(BriefError, "stale"):
            production.source_plan(self.store, self.brief)

    def test_local_selection_does_not_discover_unselected_cloud(self):
        local = self.local_config()
        self.configure(
            {"providers": [{"id": "cloud", "provider": "azure"}, local]}
        )
        with (
            patch("aigenvidagent.speech.request") as azure,
            patch("aigenvidagent.voice_providers.subprocess.run") as process,
            patch(
                "aigenvidagent.voice_providers.shutil.which",
                return_value=str(self.root / "piper.exe"),
            ),
        ):

            def write_wav(argv, **kwargs):
                Path(argv[argv.index("-f") + 1]).write_bytes(wav_bytes(1))

            process.side_effect = write_wav
            speech.samples(
                self.store, "launch", ["offline/speaker"], seconds=1
            )
            azure.assert_not_called()

    def test_unknown_provider_secrets_and_offline_resource_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            authorized_resource(self.brief["speech"]["resource_id"])
            validate(self.brief)
        for configuration in (
            {"provider": "unknown"},
            {"provider": []},
            {"provider": "azure", "auth": "unknown"},
            {"providers": []},
            {"providers": None},
            {"providers": [{"id": "same"}, {"id": "same"}]},
            {"provider": "openai", "api_key": "runtime-secret"},
            {"provider": "openai", "OPENAI_API_KEY": "runtime-secret"},
            {"provider": "elevenlabs", "token": "runtime-secret"},
        ):
            with (
                self.subTest(configuration=configuration),
                self.assertRaises(BriefError),
            ):
                self.configure(configuration)

    def test_cloud_auth_missing_credentials_and_errors_suppress_tokens(self):
        for provider in ("openai", "elevenlabs"):
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("aigenvidagent.voice_providers.urlopen") as remote,
                self.assertRaisesRegex(BriefError, "environment"),
            ):
                voice_providers.cloud_request(provider, "/v1/models")
            remote.assert_not_called()
            with (
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "runtime-secret",
                        "ELEVENLABS_API_KEY": "runtime-secret",
                    },
                    clear=True,
                ),
                patch(
                    "aigenvidagent.voice_providers.urlopen",
                    side_effect=URLError("runtime-secret"),
                ),
            ):
                try:
                    voice_providers.cloud_request(provider, "/v1/models")
                except BriefError:
                    self.assertNotIn("runtime-secret", traceback.format_exc())
                else:
                    self.fail("Expected sanitized network error")

    def test_cli_voices_and_preview_route_provider_without_azure(self):
        self.configure(
            {
                "providers": [
                    {
                        "id": "configured",
                        "provider": "openai",
                        "model": "user-model",
                        "voices": ["voice"],
                        "locale": "fr-FR",
                    }
                ]
            }
        )
        self.brief["consents"]["provider_samples"] = {"configured": True}
        self.store.save_brief(self.brief)
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch.dict(
                os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=True
            ),
            patch("aigenvidagent.voice_providers.urlopen") as remote,
            patch("aigenvidagent.speech.request") as azure,
        ):
            self.assertEqual(
                main(["voices", "launch", "--refresh"], root=self.root), 0
            )
            found = json.loads(output.getvalue())
            self.assertEqual(found[0]["name"], "configured/voice")
            remote.assert_not_called()
            output.seek(0)
            output.truncate()
            self.mock_http(
                remote,
                {"https://api.openai.com/v1/audio/speech": wav_bytes(1)},
            )
            self.assertEqual(
                main(
                    [
                        "preview",
                        "launch",
                        "--voices",
                        "configured/voice",
                        "--seconds",
                        "1",
                    ],
                    root=self.root,
                ),
                0,
            )
            record = json.loads(output.getvalue())
            self.assertTrue(
                (self.root / record["samples"][0]["path"]).is_file()
            )
            azure.assert_not_called()

    def test_candidates_across_three_services_preserve_provider_and_model(
        self,
    ):
        azure_config = {
            **self.brief["speech"],
            "id": "regional",
            "provider": "azure",
        }
        self.configure(
            {
                "providers": [
                    azure_config,
                    {
                        "id": "project",
                        "provider": "openai",
                        "model": "user-tts-model",
                        "voices": ["configured-voice"],
                    },
                    {
                        "id": "studio",
                        "provider": "elevenlabs",
                        "model": "user-studio-model",
                    },
                ]
            }
        )
        selected = [
            "regional/" + self.rows[0]["ShortName"],
            "project/configured-voice",
            "studio/live-voice",
        ]
        with (
            patch("aigenvidagent.speech.urlopen") as azure,
            patch("aigenvidagent.voice_providers.urlopen") as remote,
        ):
            with self.assertRaises(BriefError) as error:
                speech.samples(self.store, "launch", selected, seconds=1)
            for provider in ("azure", "openai", "elevenlabs"):
                self.assertIn(provider, str(error.exception))
            self.assertIn("charges", str(error.exception))
            azure.assert_not_called()
            remote.assert_not_called()
            self.brief["consents"]["provider_samples"] = [
                "regional",
                "project",
                "studio",
            ]
            self.store.save_brief(self.brief)
            self.mock_http(
                azure,
                {
                    "https://eastus2.tts.speech.microsoft.com/cognitiveservices/voices/list": self.rows,
                    "https://eastus2.tts.speech.microsoft.com/cognitiveservices/v1": wav_bytes(
                        1
                    ),
                },
            )
            self.mock_http(
                remote,
                {
                    "https://api.openai.com/v1/audio/speech": wav_bytes(1),
                    "https://api.elevenlabs.io/v1/models": [
                        {
                            "model_id": "user-studio-model",
                            "can_do_text_to_speech": True,
                        }
                    ],
                    "https://api.elevenlabs.io/v1/voices": {
                        "voices": [{"voice_id": "live-voice"}]
                    },
                    "https://api.elevenlabs.io/v1/text-to-speech/live-voice?output_format=pcm_24000": b"\0\0"
                    * 24000,
                },
            )
            with patch.dict(
                os.environ,
                {
                    "SPK": "runtime-secret",
                    "OPENAI_API_KEY": "runtime-secret",
                    "ELEVENLABS_API_KEY": "runtime-secret",
                },
            ):
                record = speech.samples(
                    self.store, "launch", selected, seconds=1
                )
        self.assertEqual([row["voice"] for row in record["samples"]], selected)
        self.assertEqual(
            [row["provider"] for row in record["samples"]],
            ["azure", "openai", "elevenlabs"],
        )
        self.assertEqual(
            [row["model"] for row in record["samples"]],
            ["service-managed", "user-tts-model", "user-studio-model"],
        )

    def test_legacy_speech_token_is_not_used_for_entra(self):
        config = self.brief["speech"]
        with (
            patch.dict(
                os.environ,
                {
                    "AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
                    "SPEECH_TOKEN": "legacy-secret",
                },
                clear=True,
            ),
            patch("aigenvidagent.speech.urlopen") as remote,
        ):
            remote.return_value.__enter__.return_value.read.return_value = (
                b"[]"
            )
            speech.request(
                {**config, "auth": "speech_token"},
                "/cognitiveservices/voices/list",
            )
            self.assertEqual(
                remote.call_args.args[0].get_header("Authorization"),
                "Bearer legacy-secret",
            )
            remote.reset_mock()
            with self.assertRaisesRegex(BriefError, "AZURE_ACCESS_TOKEN"):
                speech.request(
                    {**config, "auth": "entra"},
                    "/cognitiveservices/voices/list",
                )
            remote.assert_not_called()

    def test_missing_subscription_blocks_before_network_even_with_key(self):
        with (
            patch.dict(os.environ, {"SPK": "runtime-secret"}, clear=True),
            patch("aigenvidagent.speech.urlopen") as remote,
            self.assertRaisesRegex(
                BriefError, "AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID"
            ),
        ):
            speech.request(
                self.brief["speech"], "/cognitiveservices/voices/list"
            )
        remote.assert_not_called()

    def test_missing_piper_executable_and_process_errors_are_clear(self):
        self.configure(self.local_config())
        with (
            patch("aigenvidagent.voice_providers.shutil.which", return_value=None),
            self.assertRaisesRegex(BriefError, "PATH"),
        ):
            speech.samples(self.store, "launch", ["speaker"], seconds=1)
        with (
            patch(
                "aigenvidagent.voice_providers.shutil.which",
                return_value=str(self.root / "piper.exe"),
            ),
            patch(
                "aigenvidagent.voice_providers.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    1, ["piper"], stderr="runtime-secret"
                ),
            ),
        ):
            try:
                speech.samples(self.store, "launch", ["speaker"], seconds=1)
            except BriefError:
                self.assertNotIn("runtime-secret", traceback.format_exc())
            else:
                self.fail("Expected sanitized local process error")

    def test_entra_auth_and_explicit_subscription_guard(self):
        with (
            patch.dict(
                os.environ,
                {
                    "AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
                    "AZURE_ACCESS_TOKEN": "runtime-secret",
                },
                clear=True,
            ),
            patch("aigenvidagent.speech.urlopen") as open_url,
        ):
            open_url.return_value.__enter__.return_value.read.return_value = (
                b"[]"
            )
            speech.request(
                {**self.brief["speech"], "auth": "entra"},
                "/cognitiveservices/voices/list",
            )
            self.assertEqual(
                open_url.call_args.args[0].get_header("Authorization"),
                "Bearer aad#"
                + self.brief["speech"]["resource_id"]
                + "#runtime-secret",
            )
            open_url.reset_mock()
            with patch.dict(
                os.environ, {"AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID": "different"}
            ):
                with self.assertRaisesRegex(BriefError, "subscription"):
                    speech.request(
                        self.brief["speech"], "/cognitiveservices/voices/list"
                    )
            open_url.assert_not_called()

    def setUp(self):
        super().setUp()
        environment = patch.dict(
            os.environ, {"AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID": SUBSCRIPTION}
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.brief["speech"].update(
            {
                "resource_id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/demo/providers/Microsoft.CognitiveServices/accounts/speech",
                "region": "eastus2",
                "locale": "fr-FR",
            }
        )
        self.brief["language"] = "fr-FR"
        self.brief["consents"]["speech_samples"] = True
        self.store.save_brief(self.brief)
        self.rows = [
            {
                "ShortName": "fr-FR-DynamicOneNeural",
                "Locale": "fr-FR",
                "StyleList": ["friendly"],
                "VoiceTag": {"ContentCategories": ["Conversation"]},
            },
            {
                "ShortName": "en-US-DynamicMultiNeural",
                "Locale": "en-US",
                "SecondaryLocaleList": ["fr-FR"],
            },
            {"ShortName": "de-DE-OtherNeural", "Locale": "de-DE"},
        ]

    def fake_service(self, configuration, suffix, body=None):
        return (
            json.dumps(self.rows).encode()
            if suffix.endswith("/list")
            else wav_bytes(2)
        )

    def test_dynamic_locale_voices_refresh_cache_and_actual_wav_samples(self):
        with patch(
            "aigenvidagent.speech.request", side_effect=self.fake_service
        ) as service:
            found = speech.voices(self.store, "launch", refresh=True)
            self.assertEqual(
                [row["name"] for row in found],
                [row["ShortName"] for row in self.rows[:2]],
            )
            speech.voices(self.store, "launch")
            self.assertEqual(service.call_count, 1)
            result = speech.samples(
                self.store, "launch", [row["name"] for row in found], seconds=1
            )
            self.assertEqual(len(result["samples"]), 2)
            self.assertEqual(service.call_count, 3)
            self.assertIn(b'xml:lang="fr-FR"', service.call_args.args[2])
            for sample in result["samples"]:
                with wave.open(str(self.root / sample["path"])) as audio:
                    self.assertEqual(audio.getnframes(), 24000)
            self.assertIsNone(result["selected_voice"])
            self.assertNotIn(
                "SPK",
                json.dumps(load(self.store.project("launch") / "brief.json")),
            )

    def test_explicit_consent_blocks_before_discovery_or_synthesis(self):
        self.brief["consents"]["speech_samples"] = False
        self.store.save_brief(self.brief)
        with (
            patch("aigenvidagent.speech.request") as service,
            self.assertRaisesRegex(BriefError, "consent"),
        ):
            speech.samples(self.store, "launch", ["unknown"])
        service.assert_not_called()

    def test_voice_limits_unknown_voice_style_and_empty_audio(self):
        with patch("aigenvidagent.speech.request", side_effect=self.fake_service):
            for selected, seconds in (
                (["unknown"], 1),
                (["a"] * 4, 1),
                (["a", "a"], 1),
                (["a"], float("nan")),
                (["a"], 11),
            ):
                with (
                    self.subTest(selected=selected, seconds=seconds),
                    self.assertRaises(BriefError),
                ):
                    speech.samples(self.store, "launch", selected, seconds)
            self.brief["speech"]["style"] = "unsupported"
            self.store.save_brief(self.brief)
            with self.assertRaisesRegex(BriefError, "style"):
                speech.samples(
                    self.store, "launch", [self.rows[0]["ShortName"]]
                )
        self.brief["speech"]["style"] = ""
        self.store.save_brief(self.brief)
        with (
            patch(
                "aigenvidagent.speech.request",
                side_effect=lambda configuration, suffix, body=None: (
                    json.dumps(self.rows).encode()
                    if suffix.endswith("/list")
                    else wav_bytes(0)
                ),
            ),
            self.assertRaisesRegex(BriefError, "empty"),
        ):
            speech.samples(self.store, "launch", [self.rows[0]["ShortName"]])

    def test_https_endpoint_subscription_and_no_credential_persistence(self):
        configuration = self.brief["speech"]
        with (
            patch.dict(os.environ, {"SPK": "runtime-secret"}),
            patch("aigenvidagent.speech.urlopen") as open_url,
        ):
            open_url.return_value.__enter__.return_value.read.return_value = (
                b"[]"
            )
            self.assertEqual(
                speech.request(
                    configuration, "/cognitiveservices/voices/list"
                ),
                b"[]",
            )
            request = open_url.call_args.args[0]
            self.assertEqual(
                request.full_url,
                "https://eastus2.tts.speech.microsoft.com/cognitiveservices/voices/list",
            )
            self.assertEqual(
                request.get_header("Ocp-apim-subscription-key"),
                "runtime-secret",
            )
            self.assertEqual(open_url.call_args.kwargs["timeout"], 30)
            for changes in (
                {"endpoint": "https://attacker.example"},
                {
                    "resource_id": configuration["resource_id"].replace(
                        SUBSCRIPTION, "other"
                    )
                },
                {"region": "eastus2/../../evil"},
            ):
                with (
                    self.subTest(changes=changes),
                    self.assertRaises(BriefError),
                ):
                    speech.request(
                        {**configuration, **changes},
                        "/cognitiveservices/voices/list",
                    )
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(BriefError, "environment"),
        ):
            speech.request(configuration, "/cognitiveservices/voices/list")
        with (
            patch.dict(os.environ, {"SPK": "runtime-secret"}),
            patch(
                "aigenvidagent.speech.urlopen",
                side_effect=URLError("runtime-secret"),
            ),
        ):
            with self.assertRaises(BriefError) as error:
                speech.request(configuration, "/cognitiveservices/voices/list")
            self.assertNotIn("runtime-secret", str(error.exception))

    def test_storyboard_required_before_speech(self):
        self.brief["storyboard"] = []
        self.store.save_brief(self.brief)
        with (
            patch("aigenvidagent.speech.request") as service,
            self.assertRaisesRegex(BriefError, "storyboard"),
        ):
            speech.samples(self.store, "launch", [self.rows[0]["ShortName"]])
        service.assert_not_called()

    def test_sample_approval_binds_script_locale_and_pronunciations(self):
        with patch("aigenvidagent.speech.request", side_effect=self.fake_service):
            record = speech.samples(
                self.store, "launch", [self.rows[0]["ShortName"]]
            )
        self.brief["speech"].update(
            {
                "narration_path": "",
                "voice": self.rows[0]["ShortName"],
                "sample_approval": {
                    "approved": True,
                    "voice": self.rows[0]["ShortName"],
                    "manifest_path": record["manifest_path"],
                },
            }
        )
        production.source_plan(self.store, self.brief)
        self.brief["pronunciations"] = {"product": "new pronunciation"}
        with self.assertRaisesRegex(BriefError, "stale"):
            production.source_plan(self.store, self.brief)

    def test_invalid_video_preview_fails_before_billable_speech(self):
        with (
            patch("aigenvidagent.speech.request") as service,
            self.assertRaisesRegex(BriefError, "exceeds"),
        ):
            preview(
                self.store,
                "launch",
                [self.rows[0]["ShortName"]],
                video=True,
                start=2,
                seconds=2,
            )
        service.assert_not_called()

    def test_actual_video_preview_argv_is_short_and_separate_from_full_render(
        self,
    ):
        with (
            patch("aigenvidagent.speech.request", side_effect=self.fake_service),
            patch(
                "aigenvidagent.production.subprocess.run",
                side_effect=self.fake_process,
            ) as process,
        ):
            result = preview(
                self.store,
                "launch",
                [self.rows[0]["ShortName"]],
                video=True,
                start=0,
                seconds=3,
            )
        capture = process.call_args_list[1].args[0]
        self.assertEqual(capture[capture.index("--start") + 1], "0")
        self.assertEqual(capture[capture.index("--seconds") + 1], "3")
        self.assertIn("previews", capture[capture.index("--output") + 1])
        self.assertIn("video_run_id", result)
        self.assertFalse((self.store.project("launch") / "approvals").exists())


if __name__ == "__main__":
    unittest.main()
