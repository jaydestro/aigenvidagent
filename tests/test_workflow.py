import asyncio
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from aigenvidagent import production
from aigenvidagent.deliverables import subtitle_text
from aigenvidagent.schema import BriefError
from aigenvidagent.storage import Store, file_hash, load, save
from aigenvidagent.workflow import execute_graph


class DeliverableTests(unittest.TestCase):
    def test_exact_repeated_words_and_clipped_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.js"
            path.write_text(
                'window.WORDS=[["Go,",0,0.2],["go!",0.2,0.5]];\n'
                'window.CAPTIONS=[{"text":"Go, go!","show":0,"hide":0.6}];\n',
                encoding="utf-8",
            )
            text = subtitle_text(path, "Go,  go!", 1)
            self.assertIn("00:00:00,000 --> 00:00:00,600\nGo,  go!", text)
            preview = subtitle_text(
                path, "Go,  go!", 1, start=0.3, seconds=0.1
            )
            self.assertEqual(
                preview, "1\n00:00:00,000 --> 00:00:00,100\ngo!\n"
            )
            with self.assertRaisesRegex(BriefError, "exact script"):
                subtitle_text(path, "Go, stop!", 1)
            path.write_text(
                'window.WORDS=[["Go,",0,0.2],["go!",0.2,0.5]];\n'
                'window.CAPTIONS=[{"text":"Go, go!","show":0,"hide":0.1}];\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BriefError, "cover"):
                subtitle_text(path, "Go, go!", 1)
            path.write_text("window.TAKE={};", encoding="utf-8")
            with self.assertRaisesRegex(BriefError, "timeline"):
                subtitle_text(path, "Go, go!", 1)


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "templates").mkdir()
        shutil.copy2(
            Path(__file__).resolve().parents[1] / "templates/brief.json",
            self.root / "templates/brief.json",
        )
        self.store = Store(self.root)
        for path, text in {
            "scene/index.html": '<script src="main.js"></script>',
            "scene/main.js": "window.READY=true;",
            "core/engine.js": "export const value = 1;",
            "tools/build.mjs": "console.log('build');",
            "capture.py": "pass",
            "make_take.py": "pass",
            "scene/script.txt": "Welcome. This is the locked script.",
            "takes/take/data.js": 'window.WORDS=[["Welcome.",0,0.1],["This",0.1,0.2],["is",0.2,0.3],["the",0.3,0.4],["locked",0.4,0.5],["script.",0.5,0.6]];\nwindow.CAPTIONS=[{"text":"Welcome. This is the locked script.","show":0,"hide":0.7}];',
            "assets/logo.txt": "licensed asset",
        }.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        save(self.root / "scene/config.json", {"take": "take"})
        save(self.root / "takes/take/meta.json", {"duration": 3})
        with wave.open(
            str(self.root / "takes/take/narration.wav"), "wb"
        ) as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 8000)
        self.brief = self.store.template("launch")
        self.brief.update(
            {
                "coding_model": {
                    "name": "user-selected-model",
                    "confirmed_by_user": True,
                },
                "audience": "Developers",
                "goal": "Demonstrate the product",
                "venue": "Conference",
                "duration": {"exact_s": 3, "hold_s": 1},
                "storyboard": [{"beat": 1, "visual": "Product"}],
                "storyboard_approved": True,
                "script": {
                    "path": "scene/script.txt",
                    "locked": True,
                    "sha256": file_hash(self.root / "scene/script.txt"),
                },
                "variants": [
                    {
                        "id": "base",
                        "project_dir": "scene",
                        "orientation": "landscape",
                        "width": 640,
                        "height": 360,
                        "fps": 30,
                        "captions": "highlight",
                        "differences": "Base version",
                    }
                ],
                "assets": [
                    {
                        "type": "image",
                        "path": "assets/logo.txt",
                        "purpose": "Logo",
                        "required_detail": "Exact logo",
                        "licensing": "Owned",
                    }
                ],
            }
        )
        self.brief["speech"]["narration_path"] = "takes/take/narration.wav"
        self.store.save_brief(self.brief)

    def fake_process(self, argv, **kwargs):
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["check"], True)
        if "--output" in argv:
            self.capture_duration = (
                float(argv[argv.index("--seconds") + 1])
                if "--seconds" in argv
                else 3
            )
            Path(argv[argv.index("--output") + 1]).write_bytes(
                b"mocked mp4 data"
            )
        if argv[0] == "ffmpeg" and "-n" in argv:
            Path(argv[-1]).write_bytes(b"mocked thumbnail")
        probe = {
            "format": {"duration": str(getattr(self, "capture_duration", 3))},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 640,
                    "height": 360,
                    "nb_read_frames": str(
                        round(getattr(self, "capture_duration", 3) * 30)
                    ),
                },
                {"codec_type": "audio"},
            ],
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(probe), "")


class WorkflowTests(ProjectFixture):
    def test_real_sdk_graph_order_and_gate_failure(self):
        def step(name):
            return lambda message: {"steps": message["steps"] + [name]}

        result = asyncio.run(
            execute_graph(
                {"steps": []},
                *[
                    step(name)
                    for name in ("gate", "stage", "render", "verify")
                ],
            )
        )
        self.assertEqual(
            result["steps"], ["gate", "stage", "render", "verify"]
        )

        def reject(message):
            raise BriefError("approval rejected")

        with self.assertRaises(Exception):
            asyncio.run(
                execute_graph(
                    {}, reject, step("stage"), step("render"), step("verify")
                )
            )

    def test_real_maf_production_argv_staging_and_exclusive_runs(self):
        plan = production.prepare(self.store, "launch")
        self.assertFalse((self.root / "out").exists())
        with patch(
            "aigenvidagent.production.subprocess.run", side_effect=self.fake_process
        ) as process:
            record = production.produce(
                self.store, "launch", plan["approval_id"]
            )
            self.assertEqual(record["status"], "verified")
            self.assertEqual(
                load(self.root / f"out/launch/{record['run_id']}/run.json")[
                    "status"
                ],
                "verified",
            )
            self.assertEqual(process.call_count, 7)
            build, capture = [
                call.args[0] for call in process.call_args_list[:2]
            ]
            probe = process.call_args_list[-1].args[0]
            workspace = (
                self.root / "out/launch" / record["run_id"] / "workspace"
            )
            self.assertEqual(
                build,
                [
                    "node",
                    str(self.root / "tools/build.mjs"),
                    str(workspace / "scene"),
                ],
            )
            self.assertEqual(
                capture[capture.index("--root") + 1], str(workspace)
            )
            self.assertEqual(capture[capture.index("--duration") + 1], "3")
            self.assertEqual(
                capture[capture.index("--captions") + 1], "highlight"
            )
            self.assertEqual(
                capture[capture.index("--browser") + 1], "chromium"
            )
            self.assertEqual(capture[capture.index("--width") + 1], "640")
            self.assertEqual(capture[2], "scene")
            output = self.root / record["outputs"][0]["path"]
            self.assertEqual(
                output,
                self.root
                / "out/launch"
                / record["run_id"]
                / "variants/base/video.mp4",
            )
            self.assertEqual(probe[0], "ffprobe")
            self.assertTrue((workspace / "core/engine.js").is_file())
            self.assertTrue((workspace / "takes/take/narration.wav").is_file())
            self.assertFalse((workspace / "node_modules").exists())
            with self.assertRaises(Exception):
                production.produce(self.store, "launch", plan["approval_id"])
            second = production.prepare(self.store, "launch")
            another = production.produce(
                self.store, "launch", second["approval_id"]
            )
            self.assertNotEqual(record["run_id"], another["run_id"])
            self.assertEqual(output.read_bytes(), b"mocked mp4 data")

    def test_stale_scene_assets_take_tools_and_script_stop_before_subprocess(
        self,
    ):
        for relative in (
            "scene/main.js",
            "assets/logo.txt",
            "takes/take/data.js",
            "core/engine.js",
            "tools/build.mjs",
            "capture.py",
            "scene/script.txt",
        ):
            with self.subTest(relative=relative):
                source = self.root / relative
                original = source.read_bytes()
                plan = production.prepare(self.store, "launch")
                source.write_bytes(original + b" changed")
                with (
                    patch("aigenvidagent.production.subprocess.run") as process,
                    self.assertRaises(Exception),
                ):
                    production.produce(
                        self.store, "launch", plan["approval_id"]
                    )
                process.assert_not_called()
                source.write_bytes(original)

    def test_brief_change_tampered_approval_unknown_approval(self):
        plan = production.prepare(self.store, "launch")
        self.brief["goal"] = "Changed"
        self.store.save_brief(self.brief)
        with self.assertRaisesRegex(BriefError, "Stale"):
            production.approval_gate(self.store, "launch", plan["approval_id"])
        self.store.save_brief(
            {
                **self.brief,
                "goal": "Demonstrate the product",
            }
        )
        plan["variants"][0]["width"] = 1280
        save(
            self.store.project("launch")
            / "approvals"
            / f"{plan['approval_id']}.json",
            plan,
        )
        with self.assertRaisesRegex(BriefError, "altered"):
            production.approval_gate(self.store, "launch", plan["approval_id"])
        with self.assertRaises(BriefError):
            production.approval_gate(self.store, "launch", "unknown")

    def test_missing_scene_narration_and_unlocked_script_fail_early(self):
        for relative in (
            "scene/main.js",
            "takes/take/narration.wav",
            "takes/take/meta.json",
        ):
            source = self.root / relative
            contents = source.read_bytes()
            source.unlink()
            with (
                self.subTest(relative=relative),
                patch("aigenvidagent.production.subprocess.run") as process,
                self.assertRaises(BriefError),
            ):
                production.prepare(self.store, "launch")
            process.assert_not_called()
            source.write_bytes(contents)
        self.brief["script"]["locked"] = False
        self.store.save_brief(self.brief)
        with self.assertRaisesRegex(BriefError, "Lock"):
            production.prepare(self.store, "launch")

    def test_hold_and_finished_bounds(self):
        save(self.root / "takes/take/meta.json", {"duration": 4})
        with self.assertRaisesRegex(BriefError, "inclusive"):
            production.prepare(self.store, "launch")
        save(self.root / "takes/take/meta.json", {"duration": 3})
        self.brief["duration"] = {"min_s": 3, "max_s": 4, "hold_s": 2.8}
        self.store.save_brief(self.brief)
        with self.assertRaisesRegex(BriefError, "hold"):
            production.prepare(self.store, "launch")

    def test_failed_capture_is_not_verified_and_approval_consumed(self):
        plan = production.prepare(self.store, "launch")
        with patch(
            "aigenvidagent.production.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["node"]),
        ):
            with self.assertRaises(Exception):
                production.produce(self.store, "launch", plan["approval_id"])
        records = list((self.root / "out/launch").glob("*/run.json"))
        self.assertEqual(load(records[0])["status"], "failed")
        self.assertFalse(
            list((self.root / "out/launch").glob("*/verification.json"))
        )

    def test_output_hash_and_media_duration_gate(self):
        plan = production.prepare(self.store, "launch")
        with patch(
            "aigenvidagent.production.subprocess.run", side_effect=self.fake_process
        ):
            record = production.produce(
                self.store, "launch", plan["approval_id"]
            )
            output = self.root / record["outputs"][0]["path"]
            output.write_bytes(b"modified")
            with self.assertRaisesRegex(BriefError, "hash"):
                production.verify(self.store, "launch", record["run_id"])
        record["outputs"][0]["sha256"] = file_hash(output)
        record["status"] = "rendered"
        record["outputs"][0]["duration_s"] = 99
        with (
            patch(
                "aigenvidagent.production.subprocess.run",
                side_effect=self.fake_process,
            ),
            self.assertRaisesRegex(BriefError, "duration"),
        ):
            production.verify_record(self.store, record)

    def test_dependency_escape_and_no_voice_approval(self):
        for dependency in ("../escape", "node_modules", ".venv", "C:/outside"):
            candidate = copy.deepcopy(self.brief)
            candidate["dependencies"] = [dependency]
            with (
                self.subTest(dependency=dependency),
                self.assertRaises(BriefError),
            ):
                production.source_plan(self.store, candidate)
        self.brief["speech"]["narration_path"] = ""
        with self.assertRaisesRegex(BriefError, "sample"):
            production.source_plan(self.store, self.brief)

    def test_missing_timing_fails_before_capture_and_sidecars_required(self):
        timeline = self.root / "takes/take/data.js"
        original = timeline.read_text()
        timeline.write_text("window.TAKE={};")
        with patch("aigenvidagent.production.subprocess.run") as process:
            with self.assertRaisesRegex(BriefError, "timeline"):
                production.prepare(self.store, "launch")
            process.assert_not_called()
        timeline.write_text(original)
        self.brief["variants"][0]["captions"] = "none"
        self.store.save_brief(self.brief)
        plan = production.prepare(self.store, "launch")
        with patch(
            "aigenvidagent.production.subprocess.run", side_effect=self.fake_process
        ):
            record = production.produce(
                self.store, "launch", plan["approval_id"]
            )
            output = record["outputs"][0]
            self.assertEqual(set(output["artifacts"]), {"srt", "thumbnail"})
            (self.root / output["artifacts"]["srt"]["path"]).unlink()
            with self.assertRaisesRegex(BriefError, "srt"):
                production.verify(self.store, "launch", record["run_id"])
            self.assertEqual(
                load(self.root / f"out/launch/{record['run_id']}/run.json")[
                    "status"
                ],
                "failed",
            )


if __name__ == "__main__":
    unittest.main()
