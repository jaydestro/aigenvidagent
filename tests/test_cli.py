import contextlib
import copy
from email.message import Message
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from aigenvidagent import production, sources
from aigenvidagent.cli import (
    export_brief,
    initialize,
    main,
    orient,
    parse_duration,
    preview,
    provider_metadata,
    provider_questions,
)
from aigenvidagent.schema import BriefError, duration_bounds, safe_id, validate
from aigenvidagent.storage import file_hash, inside, load, save
from test_workflow import ProjectFixture


class SchemaTests(unittest.TestCase):
    def test_exact_and_inclusive_range(self):
        self.assertEqual(
            duration_bounds({"exact_s": 90, "hold_s": 3}), (90, 90, 3)
        )
        self.assertEqual(
            duration_bounds({"min_s": 90, "max_s": 110, "hold_s": 3}),
            (90, 110, 3),
        )
        self.assertEqual(
            duration_bounds({"min_s": 90, "max_s": 90}), (90, 90, 3)
        )

    def test_invalid_duration(self):
        for duration in [
            None,
            {},
            {"exact_s": True},
            {"exact_s": 0},
            {"exact_s": -2},
            {"exact_s": float("nan")},
            {"exact_s": float("inf")},
            {"min_s": 110, "max_s": 90},
            {"min_s": 90},
            {"exact_s": 90, "min_s": 90},
            {"exact_s": 3, "hold_s": 3},
            {"exact_s": 90, "hold_s": -1},
            {"exact_s": "90"},
        ]:
            with (
                self.subTest(duration=duration),
                self.assertRaises(BriefError),
            ):
                duration_bounds(duration)

    def test_ids_and_duplicate_variants(self):
        for identity in [
            "../escape",
            "a/b",
            "a\\b",
            "",
            "..",
            "C:drive",
            "CON",
            "lpt1",
        ]:
            with (
                self.subTest(identity=identity),
                self.assertRaises(BriefError),
            ):
                safe_id(identity)
        with self.assertRaises(BriefError):
            validate(
                {
                    "schema_version": 1,
                    "project_id": "launch",
                    "variants": [{"id": "A"}, {"id": "a"}],
                }
            )

    def test_duration_input(self):
        self.assertEqual(parse_duration("90-110")["max_s"], 110)
        self.assertEqual(parse_duration("90 seconds")["exact_s"], 90)
        for text in (
            "NaN",
            "inf",
            "-3",
            "110-90",
            "0",
            "90-",
            "90;exit",
            "90-NaN",
        ):
            with self.subTest(text=text), self.assertRaises(BriefError):
                parse_duration(text)


class CliTests(ProjectFixture):
    def quiet(self, *args, **kwargs):
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return main(*args, root=self.root, **kwargs)

    def test_noninteractive_draft_does_not_read_input_and_export_roundtrip(
        self,
    ):
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch(
                "builtins.input", side_effect=AssertionError("must not prompt")
            ),
        ):
            self.assertEqual(self.quiet(["initialize", "draft"]), 0)
        brief = self.store.brief("draft")
        self.assertFalse(brief["onboarding"]["complete"])
        self.assertEqual(
            self.quiet(
                [
                    "export",
                    "draft",
                    "--format",
                    "json",
                    "--output",
                    "exports/draft.json",
                ]
            ),
            0,
        )
        self.assertEqual(load(self.root / "exports/draft.json"), brief)
        self.assertEqual(
            self.quiet(
                [
                    "export",
                    "draft",
                    "--format",
                    "markdown",
                    "--output",
                    "exports/draft.md",
                ]
            ),
            0,
        )
        self.assertIn(
            '"privacy"', (self.root / "exports/draft.md").read_text()
        )
        self.assertEqual(
            self.quiet(
                [
                    "export",
                    "draft",
                    "--format",
                    "json",
                    "--output",
                    "exports/draft.json",
                ]
            ),
            2,
        )

    def test_answers_import_preserves_fields_locks_script_and_never_renders(
        self,
    ):
        answers = copy.deepcopy(self.brief)
        answers["coding_model"] = {
            "name": "Actual editor selection",
            "confirmed_by_user": True,
        }
        answers["duration"] = {"min_s": 3, "max_s": 4, "hold_s": 1}
        answers["consents"]["optional_installs"] = [
            {
                "name": "example-skill",
                "kind": "skill",
                "scope": "workspace",
                "consent": False,
            }
        ]
        answers["custom_notes"] = "Preserve additional interview details"
        save(self.root / "answers.json", answers)
        with patch("aigenvidagent.production.subprocess.run") as process:
            self.assertEqual(
                self.quiet(
                    [
                        "initialize",
                        "launch",
                        "--answers",
                        "answers.json",
                    ]
                ),
                0,
            )
        process.assert_not_called()
        restored = self.store.brief("launch")
        self.assertTrue(restored["onboarding"]["complete"])
        self.assertEqual(restored["custom_notes"], answers["custom_notes"])
        self.assertFalse((self.root / "out").exists())
        self.assertEqual(
            restored["script"]["sha256"],
            file_hash(self.root / "scene/script.txt"),
        )

    def test_resume_first_model_confirmation_then_file_choice_and_interrupt(
        self,
    ):
        prompts = []
        responses = iter(["Selected model", "yes", "interview", "Designers"])

        def reader(prompt):
            prompts.append(prompt)
            try:
                return next(responses)
            except StopIteration as error:
                raise EOFError() from error

        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(EOFError),
        ):
            initialize(self.store, "draft", interactive=True, reader=reader)
        self.assertIn("Selected coding model", prompts[0])
        self.assertIn("Confirm this", prompts[1])
        self.assertIn("Interview or", prompts[2])
        draft = self.store.brief("draft")
        self.assertEqual(draft["audience"], "Designers")
        self.assertEqual(draft["onboarding"]["next_question"], "goal")
        save(self.root / "resume.json", {"goal": "Make a decision"})
        self.assertEqual(
            self.quiet(["initialize", "draft", "--answers", "resume.json"]), 0
        )
        self.assertEqual(self.store.brief("draft")["audience"], "Designers")

    def test_interactive_resume_preserves_question_after_model_confirmation(
        self,
    ):
        draft = self.store.template("draft")
        draft["audience"] = "Saved audience"
        draft["onboarding"]["next_question"] = "goal"
        self.store.save_brief(draft)
        prompts = []
        answers = iter(["Selected model", "yes", "interview", "New goal"])

        def reader(prompt):
            prompts.append(prompt)
            try:
                return next(answers)
            except StopIteration as error:
                raise EOFError() from error

        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(EOFError),
        ):
            initialize(self.store, "draft", interactive=True, reader=reader)
        self.assertIn("Goal", prompts[3])
        self.assertEqual(
            self.store.brief("draft")["audience"], "Saved audience"
        )

    def test_interactive_file_import_does_not_erase_current_model_confirmation(
        self,
    ):
        answers = iter(
            [
                "Current editor model",
                "yes",
                "file",
                "templates/brief.json",
            ]
        )
        with contextlib.redirect_stdout(io.StringIO()):
            brief = initialize(
                self.store,
                "launch",
                interactive=True,
                reader=lambda prompt: next(answers),
            )
        self.assertEqual(
            brief["coding_model"],
            {"name": "Current editor model", "confirmed_by_user": True},
        )

    def test_import_identity_path_secret_and_nonfinite_rejection(self):
        for content in (
            {"project_id": "other"},
            {"speech": {"api_key": "never-save"}},
            {"duration": {"exact_s": float("nan")}},
        ):
            (self.root / "bad.json").write_text(json.dumps(content))
            self.assertEqual(
                self.quiet(["initialize", "launch", "--answers", "bad.json"]),
                2,
            )
            self.assertNotIn(
                "never-save",
                (self.store.project("launch") / "brief.json").read_text(),
            )
        with self.assertRaises(BriefError):
            inside(self.root, "../escape")
        with self.assertRaises(BriefError):
            export_brief(self.store, "launch", "json", "../escaped.json")
        (self.root / "bad.json").write_text('{"goal":"a","goal":"b"}')
        self.assertEqual(
            self.quiet(["initialize", "launch", "--answers", "bad.json"]), 2
        )

    def test_noninteractive_plain_produce_never_hangs_or_approves(self):
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("aigenvidagent.production.subprocess.run") as process,
        ):
            self.assertEqual(self.quiet(["produce", "launch"]), 2)
            self.assertEqual(self.quiet(["produce", "launch", "--prepare"]), 0)
        process.assert_not_called()

    def test_plain_produce_orientation_captions_count_differences_before_approval(
        self,
    ):
        prompts = []
        answers = iter(
            [
                "portrait",
                "none",
                "2",
                "one",
                "scene",
                "First opening",
                "two",
                "scene",
                "Second opening",
                "yes",
                "",
            ]
        )

        def reader(prompt):
            prompts.append(prompt)
            return next(answers)

        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("aigenvidagent.production.subprocess.run") as process,
        ):
            result = orient(self.store, "launch", reader)
        process.assert_not_called()
        self.assertEqual(result["status"], "awaiting approval")
        self.assertIn("Orientation", prompts[0])
        self.assertIn("Captions", prompts[1])
        self.assertIn("Total number", prompts[2])
        brief = self.store.brief("launch")
        self.assertEqual(len(brief["variants"]), 2)
        self.assertEqual(
            [row["differences"] for row in brief["variants"]],
            ["First opening", "Second opening"],
        )

    def test_invalid_variants_and_install_scopes(self):
        for field, value in (
            ("width", 0),
            ("height", 361),
            ("fps", float("nan")),
            ("captions", "karaoke"),
            ("orientation", "portrait"),
        ):
            brief = copy.deepcopy(self.brief)
            brief["variants"][0][field] = value
            with self.subTest(field=field), self.assertRaises(BriefError):
                validate(brief)
        duplicate = copy.deepcopy(self.brief)
        duplicate["variants"].append(
            {
                **duplicate["variants"][0],
                "id": "BASE",
            }
        )
        with self.assertRaisesRegex(BriefError, "Duplicate"):
            validate(duplicate)
        self.brief["consents"]["optional_installs"] = [
            {"name": "tool", "kind": "mcp", "scope": "system", "consent": True}
        ]
        with self.assertRaisesRegex(BriefError, "scope"):
            validate(self.brief)

    def test_storyboard_before_samples_and_explicit_relock(self):
        self.brief["storyboard"] = []
        self.store.save_brief(self.brief)
        self.assertEqual(
            self.quiet(
                [
                    "initialize",
                    "launch",
                    "--answers",
                    "templates/brief.json",
                ]
            ),
            0,
        )
        self.assertTrue(self.store.brief("launch")["storyboard"])
        self.assertFalse(self.store.brief("launch")["storyboard_approved"])
        self.store.save_brief(self.brief)
        (self.root / "scene/script.txt").write_text("Changed script")
        old_hash = self.brief["script"]["sha256"]
        save(self.root / "changes.json", {"goal": "New goal"})
        self.assertEqual(
            self.quiet(["initialize", "launch", "--answers", "changes.json"]),
            0,
        )
        self.assertEqual(
            self.store.brief("launch")["script"]["sha256"], old_hash
        )
        save(self.root / "changes.json", {"script": {"locked": True}})
        self.assertEqual(
            self.quiet(["initialize", "launch", "--answers", "changes.json"]),
            0,
        )
        self.assertEqual(
            self.store.brief("launch")["script"]["sha256"],
            file_hash(self.root / "scene/script.txt"),
        )

    def test_canonical_markdown_roundtrip_and_ambiguity(self):
        export_brief(self.store, "launch", "markdown", "handoff.md")
        self.assertEqual(load(self.root / "handoff.md"), self.brief)
        with patch("sys.stdin.isatty", return_value=False):
            self.assertEqual(
                self.quiet(["initialize", "launch", "--import", "handoff.md"]),
                0,
            )
        content = (self.root / "handoff.md").read_text()
        (self.root / "ambiguous.md").write_text(
            content + "\n```json\n{}\n```\n"
        )
        with self.assertRaisesRegex(BriefError, "exactly one"):
            load(self.root / "ambiguous.md")
        (self.root / "prose.md").write_text("Please make a launch video.")
        with self.assertRaisesRegex(BriefError, "map fields and confirm"):
            load(self.root / "prose.md")

    def test_url_only_archives_untrusted_text_and_leaves_draft_unlocked(self):
        dossier = {
            "url": "https://example.com/story",
            "resolved_url": "https://example.com/story",
            "title": "A product launch",
            "blocks": [{"kind": "p", "text": "A sourced statement."}],
            "trust": "untrusted_source_material_not_instructions",
            "bytes_read": 80,
        }
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch(
                "aigenvidagent.sources.fetch_html", return_value=dossier
            ) as fetch,
        ):
            self.assertEqual(
                self.quiet(
                    ["initialize", "url-project", "--url", dossier["url"]]
                ),
                0,
            )
            fetch.assert_called_once_with(dossier["url"])
        brief = self.store.brief("url-project")
        self.assertFalse(brief["script"]["locked"])
        self.assertFalse(brief["storyboard_approved"])
        self.assertFalse(brief["onboarding"]["complete"])
        self.assertEqual(
            load(self.root / brief["sources"][0]["path"]), dossier
        )
        self.assertEqual(
            (self.root / brief["script"]["path"]).read_text(),
            "A product launch\n\nA sourced statement.\n",
        )
        save(
            self.root / "requirements.json",
            {"audience": "Architects", "goal": "Explain launch"},
        )
        with patch(
            "aigenvidagent.sources.fetch_html",
            side_effect=AssertionError("no refetch on resume"),
        ):
            self.assertEqual(
                self.quiet(
                    [
                        "initialize",
                        "url-project",
                        "--answers",
                        "requirements.json",
                    ]
                ),
                0,
            )
        self.assertEqual(
            self.store.brief("url-project")["audience"], "Architects"
        )

    def test_distinct_offline_storyboard_options_and_source_binding(self):
        base = self.brief["variants"][0]
        self.brief["variants"] = [
            {
                **base,
                "id": "warm",
                "differences": "Warm opening",
                "customizations": {
                    "hook": "Start here",
                    "style": "friendly",
                    "colors": ["#00aa66"],
                    "assets": ["assets/logo.txt"],
                },
            },
            {
                **base,
                "id": "precise",
                "differences": "Technical opening",
                "customizations": {
                    "hook": "Read the evidence",
                    "style": "developer",
                    "colors": ["#ff3344"],
                },
            },
        ]
        self.store.save_brief(self.brief)
        with (
            patch("aigenvidagent.speech.samples") as samples,
            patch("aigenvidagent.speech.voices") as voices,
        ):
            result = preview(self.store, "launch", storyboards_only=True)
            samples.assert_not_called()
            voices.assert_not_called()
        first, second = result["storyboard_options"]
        self.assertEqual(
            [first["label"], second["label"]],
            ["OPTION warm", "OPTION precise"],
        )
        self.assertNotEqual(first["beats"], second["beats"])
        self.assertEqual(first["beats"][0]["headline"], "Start here")
        self.assertTrue((self.root / second["path"]).is_file())
        prepared = self.store.brief("launch")
        self.assertFalse(prepared["storyboard_approved"])
        prepared["storyboard_approved"] = True
        production.source_plan(self.store, prepared)
        prepared["variants"][0]["customizations"]["hook"] = "Changed"
        with self.assertRaisesRegex(BriefError, "stale"):
            production.source_plan(self.store, prepared)

    def test_prepared_video_preview_without_new_speech(self):
        with (
            patch("aigenvidagent.speech.samples") as samples,
            patch(
                "aigenvidagent.production.subprocess.run",
                side_effect=self.fake_process,
            ),
        ):
            result = preview(self.store, "launch", video=True, seconds=0.5)
            samples.assert_not_called()
        self.assertIn("video_run_id", result)
        self.assertFalse((self.root / "out").exists())

    def test_provider_metadata_and_named_consent_are_offline(self):
        metadata = provider_metadata(self.store.template("draft"))
        self.assertIsNone(metadata["selected"])
        descriptions = json.dumps(metadata)
        for expected in (
            "OPENAI_API_KEY",
            "ELEVENLABS_API_KEY",
            "Cognitive Services Speech User",
            "SPK",
            "piper",
            "supplied WAV",
        ):
            self.assertIn(expected, descriptions)
        answers = iter(
            [
                "openai",
                '[{"id":"chosen","provider":"openai","model":"configured-model","voices":["configured-voice"]}]',
                "yes",
            ]
        )
        brief = self.store.template("draft")
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("aigenvidagent.voice_providers.urlopen") as remote,
        ):
            provider_questions(self.store, brief, lambda prompt: next(answers))
            remote.assert_not_called()
        self.assertEqual(brief["consents"]["provider_samples"], ["chosen"])
        self.assertTrue(brief["consents"]["speech_samples"])
        self.store.save_brief(brief)
        with patch("aigenvidagent.voice_providers.urlopen") as remote:
            self.assertEqual(self.quiet(["providers", "draft"]), 0)
            remote.assert_not_called()

    def test_interrupted_provider_consent_resumes_without_replacing_config(
        self,
    ):
        brief = self.store.template("draft")
        brief["speech"] = {
            "route": "openai",
            "providers": [
                {
                    "id": "named",
                    "provider": "openai",
                    "model": "configured-model",
                    "voices": ["configured-voice"],
                }
            ],
        }
        prompts = []

        def interrupt(prompt):
            prompts.append(prompt)
            raise EOFError()

        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(EOFError),
        ):
            provider_questions(self.store, brief, interrupt)
        self.assertIn("Consent to samples from named", prompts[0])
        restored = self.store.brief("draft")
        self.assertEqual(restored["onboarding"]["next_question"], "speech")
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("aigenvidagent.voice_providers.urlopen") as remote,
        ):
            provider_questions(self.store, restored, lambda prompt: "yes")
            remote.assert_not_called()
        self.assertEqual(restored["consents"]["provider_samples"], ["named"])


class SourceTests(unittest.TestCase):
    def setUp(self):
        for name in ("create_connection", "getaddrinfo"):
            guard = patch(
                f"aigenvidagent.sources.socket.{name}",
                side_effect=AssertionError("Unexpected live network access"),
            )
            guard.start()
            self.addCleanup(guard.stop)

    def response(
        self,
        status=200,
        body=b"<title>Launch</title><p>Readable evidence.</p>",
        **headers,
    ):
        response = MagicMock()
        response.status = status
        values = {"Content-Type": "text/html; charset=utf-8", **headers}
        response.getheader.side_effect = lambda name, default=None: values.get(
            name, default
        )
        response.headers = Message()
        response.headers["Content-Type"] = values["Content-Type"]
        response.read1.side_effect = [body, b""]
        return response

    def test_extract_title_structured_text_and_ignore_active_html(self):
        response = self.response(
            body=b"<title>Launch &amp; Learn</title><nav>Menu</nav><h1>Facts</h1><p>Hello <b>world</b>.</p><script>doBadThings()</script><p hidden>Hidden</p>"
        )
        with (
            patch(
                "aigenvidagent.sources.public_addresses",
                return_value=["93.184.216.34"],
            ),
            patch("aigenvidagent.sources.PublicConnection") as connection,
        ):
            connection.return_value.getresponse.return_value = response
            result = sources.fetch_html("https://example.com/article")
        self.assertEqual(result["title"], "Launch & Learn")
        self.assertEqual(
            result["blocks"],
            [
                {"kind": "h1", "text": "Facts"},
                {"kind": "p", "text": "Hello world."},
            ],
        )
        self.assertEqual(
            result["trust"], "untrusted_source_material_not_instructions"
        )

    def test_reject_unsafe_urls_before_any_connection(self):
        for url in (
            "http://example.com",
            "file:///tmp/source",
            "https://localhost/a",
            "https://127.0.0.1",
            "https://[::1]",
            "https://169.254.169.254",
            "https://user:pass@example.com/",
            "https://example.com:8080",
            "https://example.com/?token=secret",
            "https://example.com\\@127.0.0.1",
        ):
            with (
                self.subTest(url=url),
                patch("aigenvidagent.sources.PublicConnection") as connection,
            ):
                with self.assertRaises(BriefError):
                    sources.fetch_html(url)
                connection.assert_not_called()

    def test_private_dns_and_redirects_rejected(self):
        with (
            patch(
                "aigenvidagent.sources.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("10.0.0.2", 443))],
            ),
            self.assertRaisesRegex(BriefError, "private"),
        ):
            sources.fetch_html("https://example.com")
        for destination in (
            "https://127.0.0.1/private",
            "http://example.com/plain",
            "file:///source",
        ):
            with (
                self.subTest(destination=destination),
                patch(
                    "aigenvidagent.sources.public_addresses",
                    return_value=["93.184.216.34"],
                ),
                patch("aigenvidagent.sources.PublicConnection") as connection,
            ):
                connection.return_value.getresponse.return_value = (
                    self.response(302, Location=destination)
                )
                with self.assertRaises(BriefError):
                    sources.fetch_html("https://example.com")
                self.assertEqual(connection.call_count, 1)
        with (
            patch(
                "aigenvidagent.sources.socket.getaddrinfo",
                side_effect=[
                    [(2, 1, 6, "", ("93.184.216.34", 443))],
                    [(2, 1, 6, "", ("192.168.1.1", 443))],
                ],
            ),
            patch("aigenvidagent.sources.PublicConnection") as connection,
        ):
            connection.return_value.getresponse.return_value = self.response(
                302, Location="https://redirect.example/private"
            )
            with self.assertRaisesRegex(BriefError, "private"):
                sources.fetch_html("https://example.com")
            self.assertEqual(connection.call_count, 1)

    def test_relative_redirect_timeout_cap_and_non_html(self):
        with (
            patch(
                "aigenvidagent.sources.public_addresses",
                return_value=["93.184.216.34"],
            ),
            patch("aigenvidagent.sources.PublicConnection") as connection,
        ):
            connection.return_value.getresponse.side_effect = [
                self.response(302, Location="/article"),
                self.response(),
            ]
            self.assertEqual(
                sources.fetch_html("https://example.com/start")[
                    "resolved_url"
                ],
                "https://example.com/article",
            )
        for response in (
            self.response(**{"Content-Length": str(sources.MAX_BYTES + 1)}),
            self.response(**{"Content-Type": "application/octet-stream"}),
            self.response(body=b"a" * (sources.MAX_BYTES + 1)),
        ):
            with (
                patch(
                    "aigenvidagent.sources.public_addresses",
                    return_value=["93.184.216.34"],
                ),
                patch("aigenvidagent.sources.PublicConnection") as connection,
            ):
                connection.return_value.getresponse.return_value = response
                with self.assertRaises(BriefError):
                    sources.fetch_html("https://example.com")
        with (
            patch(
                "aigenvidagent.sources.public_addresses",
                return_value=["93.184.216.34"],
            ),
            patch(
                "aigenvidagent.sources.PublicConnection", side_effect=TimeoutError()
            ),
            self.assertRaisesRegex(BriefError, "timed out"),
        ):
            sources.fetch_html("https://example.com")

    def test_tls_connection_uses_validated_ip_with_original_hostname(self):
        context = MagicMock()
        with patch(
            "aigenvidagent.sources.ssl.create_default_context", return_value=context
        ):
            connection = sources.PublicConnection(
                "example.com", "93.184.216.34", 3
            )
        with patch("aigenvidagent.sources.socket.create_connection") as create:
            connection.connect()
            create.assert_called_once_with(("93.184.216.34", 443), 3)
            context.wrap_socket.assert_called_once_with(
                create.return_value, server_hostname="example.com"
            )

    def test_dns_timeout_and_redirect_limit_are_bounded(self):
        import queue

        with (
            patch("aigenvidagent.sources.queue.Queue") as results,
            patch("aigenvidagent.sources.threading.Thread"),
        ):
            results.return_value.get.side_effect = queue.Empty()
            with self.assertRaisesRegex(BriefError, "timed out"):
                sources.public_addresses("example.com", timeout=0.01)
        with (
            patch(
                "aigenvidagent.sources.public_addresses",
                return_value=["93.184.216.34"],
            ),
            patch("aigenvidagent.sources.PublicConnection") as connection,
        ):
            connection.return_value.getresponse.return_value = self.response(
                302, Location="/loop"
            )
            with self.assertRaisesRegex(BriefError, "redirect limit"):
                sources.fetch_html("https://example.com")
            self.assertEqual(connection.call_count, sources.MAX_REDIRECTS + 1)


if __name__ == "__main__":
    unittest.main()
