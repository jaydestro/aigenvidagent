"""Opt-in OFFLINE real capture/ffmpeg integration; never calls Speech or Azure.

AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1 enables browser tests when Chromium is
installed and ffmpeg/node are on PATH. All generated media lives in an
exclusive temporary directory.
"""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

from aigenvidagent import production
from aigenvidagent.deliverables import sidecars
from aigenvidagent.schema import BriefError
from aigenvidagent.storage import Store, file_hash, load, save


class OfflineCaptureIntegration(unittest.TestCase):
    def test_real_ffmpeg_sidecar_extraction_without_browser(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("Local prerequisite missing: ffmpeg")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            video = root / "video.mp4"
            production.command(
                [
                    "ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64:r=10:d=0.5", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", video,
                ],
                root,
            )
            subtitles = "1\n00:00:00,000 --> 00:00:00,400\nGo, go!\n"
            artifacts = sidecars(
                video, subtitles, 0.5, 0.2, production.command, root
            )
            self.assertEqual((root / "captions.srt").read_text(), subtitles)
            thumbnail = root / artifacts["thumbnail"]["path"]
            self.assertEqual(thumbnail.read_bytes()[:2], b"\xff\xd8")
            self.assertEqual(
                file_hash(thumbnail), artifacts["thumbnail"]["sha256"]
            )
            with self.assertRaises(FileExistsError):
                sidecars(video, subtitles, 0.5, 0.2, production.command, root)

    def test_real_maf_production_sidecars_offline(self):
        if os.environ.get("AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION") != "1":
            self.skipTest(
                "Set AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1 for local production integration"
            )
        for tool in ("node", "ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                self.skipTest(f"Local prerequisite missing: {tool}")
        if importlib.util.find_spec("playwright") is None:
            self.skipTest("Local prerequisite missing: Playwright")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as browser:
            if not Path(browser.chromium.executable_path).exists():
                self.skipTest("Local prerequisite missing: bundled Chromium")
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(
            prefix="aigenvidagent-integration-", dir=repository
        ) as temporary:
            root = Path(temporary).resolve()
            for relative in (
                "tools/build.mjs",
                "capture.py",
                "make_take.py",
                "render_options.py",
                "templates/brief.json",
                "core/engine.js",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repository / relative, target)
            scene = root / "scene"
            scene.mkdir()
            (scene / "index.html").write_text(
                '<html><body><p>Go, go!</p><script src="bundle.js"></script></body></html>',
                encoding="utf-8",
            )
            (scene / "main.js").write_text(
                "window.READY=true;window.render=(time)=>{document.body.style.background=time<0.5?'#ff0000':'#00ff00';};",
                encoding="utf-8",
            )
            (scene / "script.txt").write_text("Go,  go!\n", encoding="utf-8")
            save(scene / "config.json", {"take": "test", "thumbnail_s": 0.5})
            take = root / "takes/test"
            take.mkdir(parents=True)
            save(
                take / "meta.json",
                {"duration": 1, "narration_end": 0.5, "hold": 0.25},
            )
            (take / "data.js").write_text(
                'window.WORDS=[["Go,",0,0.2],["go!",0.2,0.5]];\nwindow.CAPTIONS=[{"text":"Go, go!","show":0,"hide":0.6}];\n',
                encoding="utf-8",
            )
            with wave.open(str(take / "narration.wav"), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 8000)
            store = Store(root)
            brief = store.template("offline")
            brief.update(
                {
                    "coding_model": {
                        "name": "synthetic-test",
                        "confirmed_by_user": True,
                    },
                    "audience": "Test audience",
                    "goal": "Test media integrity",
                    "venue": "Local fixture",
                    "duration": {"exact_s": 1, "hold_s": 0.25},
                    "script": {
                        "path": "scene/script.txt",
                        "locked": True,
                        "sha256": file_hash(scene / "script.txt"),
                    },
                    "storyboard": [
                        {"narration": "Go, go!", "visual": "Red then green"}
                    ],
                    "storyboard_approved": True,
                    "variants": [
                        {
                            "id": "wide",
                            "project_dir": "scene",
                            "orientation": "landscape",
                            "width": 320,
                            "height": 180,
                            "fps": 10,
                            "captions": "none",
                            "differences": "Wide, no burned captions",
                        },
                        {
                            "id": "tall",
                            "project_dir": "scene",
                            "orientation": "portrait",
                            "width": 180,
                            "height": 320,
                            "fps": 10,
                            "captions": "static",
                            "differences": "Tall with static captions",
                        },
                    ],
                }
            )
            brief["speech"]["narration_path"] = "takes/test/narration.wav"
            store.save_brief(brief)
            plan = production.prepare(store, "offline")
            record = production.produce(store, "offline", plan["approval_id"])
            self.assertEqual(record["status"], "verified")
            self.assertEqual(len(record["outputs"]), 2)
            for output in record["outputs"]:
                srt = root / output["artifacts"]["srt"]["path"]
                thumbnail = root / output["artifacts"]["thumbnail"]["path"]
                self.assertIn("Go,  go!", srt.read_text())
                self.assertEqual(thumbnail.read_bytes()[:2], b"\xff\xd8")
                pixel = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(thumbnail),
                        "-vf",
                        "scale=1:1",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                ).stdout
                self.assertEqual(len(pixel), 3)
                self.assertGreater(pixel[1], 100)
                self.assertGreater(pixel[1], pixel[0])
            thumbnail.unlink()
            with self.assertRaisesRegex(BriefError, "thumbnail"):
                production.verify(store, "offline", record["run_id"])
            self.assertEqual(
                load(root / f"out/offline/{record['run_id']}/run.json")[
                    "status"
                ],
                "failed",
            )
            self.assertFalse(
                (
                    root / f"out/offline/{record['run_id']}/verification.json"
                ).exists()
            )

    def test_real_capture_and_ffmpeg_offline(self):
        if os.environ.get("AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION") != "1":
            self.skipTest(
                "OFFLINE real capture integration is opt-in: AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1"
            )
        for tool in ("node", "ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                self.skipTest(f"OFFLINE capture prerequisite missing: {tool}")
        if importlib.util.find_spec("playwright") is None:
            self.skipTest(
                "OFFLINE capture prerequisite missing: Playwright in project .venv"
            )
        root = Path(__file__).resolve().parents[1]
        builder = root / "tools/build.mjs"
        if not builder.is_file() or "--root" not in (
            root / "capture.py"
        ).read_text(encoding="utf-8"):
            self.skipTest(
                "Local build/capture entry points are unavailable"
            )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as browser:
            if not Path(browser.chromium.executable_path).exists():
                self.skipTest(
                    "OFFLINE capture prerequisite missing: installed Chromium"
                )
        with tempfile.TemporaryDirectory(
            prefix="aigenvidagent-offline-"
        ) as temporary:
            workspace = Path(temporary)
            scene = workspace / "scene"
            scene.mkdir()
            take = workspace / "takes/test"
            take.mkdir(parents=True)
            with wave.open(str(take / "narration.wav"), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 8000)
            (take / "meta.json").write_text(json.dumps({"duration": 1}))
            (take / "data.js").write_text("window.TAKE={};")
            (scene / "config.json").write_text(json.dumps({"take": "test"}))
            (scene / "main.js").write_text(
                "window.READY=true; window.render=(time)=>{document.body.style.background=time<0.5?'#ff0000':'#00ff00';};"
            )
            (scene / "index.html").write_text(
                '<html><body><script src="bundle.js"></script></body></html>'
            )
            subprocess.run(
                ["node", str(builder), str(scene)],
                cwd=root,
                shell=False,
                check=True,
                capture_output=True,
                timeout=60,
            )
            output = workspace / "capture.mp4"
            subprocess.run(
                [
                    sys.executable,
                    str(root / "capture.py"),
                    "scene",
                    "--root",
                    str(workspace),
                    "--output",
                    str(output),
                    "--width",
                    "320",
                    "--height",
                    "180",
                    "--fps",
                    "10",
                    "--duration",
                    "1",
                    "--captions",
                    "none",
                    "--browser",
                    "chromium",
                ],
                cwd=root,
                shell=False,
                check=True,
                capture_output=True,
                timeout=120,
            )
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-count_frames",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(output),
                ],
                shell=False,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            probe = json.loads(result.stdout)
            video = next(
                stream
                for stream in probe["streams"]
                if stream["codec_type"] == "video"
            )
            self.assertEqual((video["width"], video["height"]), (320, 180))
            self.assertEqual(int(video["nb_read_frames"]), 10)
            self.assertAlmostEqual(
                float(probe["format"]["duration"]), 1, delta=0.1
            )
            self.assertTrue(
                any(
                    stream["codec_type"] == "audio"
                    for stream in probe["streams"]
                )
            )


if __name__ == "__main__":
    unittest.main()
