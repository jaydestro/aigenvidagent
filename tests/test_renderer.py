import contextlib
from fractions import Fraction
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import wave

import capture
import make_take

from render_options import frame_count, narration_fits, validate_finish


class DurationTests(unittest.TestCase):
    def test_exact_frames(self):
        self.assertEqual(frame_count("21.3", 30), 639)
        self.assertEqual(frame_count("0.1", 30), 3)
        with self.assertRaises(ValueError):
            frame_count("0.11", 30)

    def test_strict_narration_window(self):
        self.assertFalse(narration_fits(9.999, 10, 12))
        self.assertTrue(narration_fits(10, 10, 12))
        self.assertTrue(narration_fits(12, 10, 12))
        self.assertFalse(narration_fits(12.001, 10, 12))
        with self.assertRaises(ValueError):
            narration_fits(10, 12, 10)

    def test_finished_film_includes_hold_and_audio(self):
        self.assertEqual(validate_finish(13, 10, 10, 3), 13)
        for values in [(12.9, 10, 10, 3), (13, 13.1, 10, 3)]:
            with self.assertRaises(ValueError):
                validate_finish(*values)
        with self.assertRaises(ValueError):
            validate_finish(1, Fraction(48001, 48000), 1, 0)
        self.assertFalse(narration_fits(Fraction(48001, 48000), 0, 1))


def wav_bytes(seconds=1, sample_rate=48000):
    samples = int(seconds * sample_rate)
    pcm = b"".join(struct.pack("<h", int(8000 * math.sin(
        2 * math.pi * (440 if index < sample_rate // 2 else 880)
        * index / sample_rate))) for index in range(samples))
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm)
    return result.getvalue()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="aigenvidagent test # ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "scene").mkdir()
        (self.root / "takes" / "take").mkdir(parents=True)
        (self.root / "scene" / "index.html").write_text("<html></html>")
        (self.root / "scene" / "config.json").write_text(json.dumps({"take": "take"}))
        self.audio = wav_bytes()
        (self.root / "takes" / "take" / "narration.wav").write_bytes(self.audio)
        self.meta = {"duration": 1.2, "narration_end": 1, "hold": 0.2}
        self.write_meta()

    def write_meta(self):
        (self.root / "takes" / "take" / "meta.json").write_text(json.dumps(self.meta))

    def args(self, *extra):
        return capture.options(["scene", "--root", str(self.root), *extra])

    def browser(self, jpeg=b"jpeg"):
        page = mock.Mock()
        page.screenshot.return_value = jpeg
        browser = mock.Mock()
        browser.new_page.return_value = page
        playwright = mock.MagicMock()
        playwright.__enter__.return_value.chromium.launch.return_value = browser
        return page, browser, mock.Mock(return_value=playwright)

    def test_imports_do_not_parse_arguments_import_services_or_write(self):
        program = """
import sys
class NoServices:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('azure', 'playwright', 'numpy'):
            raise RuntimeError('service import at module load: ' + fullname)
sys.meta_path.insert(0, NoServices())
sys.argv = []
import capture, make_take
"""
        result = subprocess.run([sys.executable, "-c", program],
                                cwd=capture.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_root_uri_options_and_preview(self):
        args = self.args("--width", "1080", "--height", "1920",
                         "--fps", "30", "--duration", "1.2",
                         "--captions", "highlight", "--browser", "chromium",
                         "--start", "0.5", "--seconds", "0.5")
        self.assertEqual(args.frames, 15)
        self.assertEqual(args.start, Fraction(1, 2))
        self.assertIn("%23", args.url)
        self.assertEqual(args.url, (self.root / "scene" / "index.html").as_uri())
        command = capture.encode_command(args, self.root / "test.mp4")
        self.assertIn("atrim=start=0.5:duration=0.5", command[command.index("-filter_complex") + 1])
        self.assertNotIn("-y", command)

    def test_invalid_args_and_audio_cut_are_rejected(self):
        for extra in [("--duration", "1.19"), ("--duration", "1.1"),
                      ("--width", "101"), ("--fps", "0"),
                      ("--start", "1", "--seconds", "0.3"),
                      ("--seconds", "0"), ("--duration", "nan")]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.args(*extra)
        self.meta["duration"] = 0.9
        self.meta["hold"] = 0
        self.meta["narration_end"] = 0.8
        self.write_meta()
        with self.assertRaisesRegex(ValueError, "cut narration"):
            self.args()

    def test_silent_wav_skips_loudness_normalization(self):
        args = self.args()
        command = capture.encode_command(args, self.root / "voiced.mp4")
        self.assertIn("loudnorm=", command[command.index("-filter_complex") + 1])
        with wave.open(str(args.audio), "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 48000)
        command = capture.encode_command(args, self.root / "silent.mp4")
        self.assertNotIn("loudnorm=", command[command.index("-filter_complex") + 1])

    def test_legacy_defaults_and_stills_without_audio(self):
        self.assertEqual(capture.parser().parse_args([]).project, "example")
        args = self.args()
        self.assertEqual((args.width, args.height, args.fps, args.frames), (1920, 1080, 30, 36))
        (self.root / "scene" / "config.json").unlink()
        self.assertEqual(self.args("--stills", "3,20").stills, [3, 20])

    def test_existing_output_is_never_overwritten(self):
        args = self.args("--output", str(self.root / "existing.mp4"))
        args.output.write_bytes(b"delivered")
        _, _, factory = self.browser()
        with self.assertRaises(FileExistsError):
            capture.capture(args, factory)
        self.assertEqual(args.output.read_bytes(), b"delivered")
        factory.assert_not_called()

    def test_browser_failure_cleans_reserved_output(self):
        args = self.args()
        _, _, factory = self.browser()
        factory.side_effect = RuntimeError("no browser")
        with self.assertRaisesRegex(RuntimeError, "no browser"):
            capture.capture(args, factory)
        self.assertFalse(args.output.exists())

    def test_page_error_is_fatal_and_cleans_output(self):
        args = self.args()
        page, browser, factory = self.browser()
        handlers = {}
        page.on.side_effect = lambda name, callback: handlers.update({name: callback})
        page.goto.side_effect = lambda url: handlers["pageerror"]("broken scene")
        with self.assertRaisesRegex(RuntimeError, "broken scene"):
            capture.capture(args, factory)
        browser.close.assert_called_once()
        self.assertFalse(args.output.exists())

    def test_console_error_is_fatal(self):
        args = self.args()
        page, _, factory = self.browser()
        handlers = {}
        page.on.side_effect = lambda name, callback: handlers.update({name: callback})
        page.goto.side_effect = lambda url: handlers["console"](SimpleNamespace(type="error", text="failed font"))
        with self.assertRaisesRegex(RuntimeError, "failed font"):
            capture.capture(args, factory)
        self.assertFalse(args.output.exists())

    def test_ffmpeg_failure_cleans_output(self):
        args = self.args("--seconds", "0.1")
        page, browser, factory = self.browser()
        encoder = mock.Mock()
        encoder.wait.return_value = 7
        with mock.patch.object(capture.subprocess, "Popen", return_value=encoder):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                capture.capture(args, factory)
        self.assertEqual(page.screenshot.call_count, 3)
        browser.close.assert_called_once()
        self.assertFalse(args.output.exists())
        self.assertEqual(list(args.output.parent.iterdir()), [])

    def test_render_failure_terminates_encoder_and_cleans_output(self):
        args = self.args()
        page, _, factory = self.browser()
        page.evaluate.side_effect = [None, RuntimeError("render rejected")]
        encoder = mock.Mock()
        with mock.patch.object(capture.subprocess, "Popen", return_value=encoder):
            with self.assertRaisesRegex(RuntimeError, "render rejected"):
                capture.capture(args, factory)
        encoder.terminate.assert_called_once()
        encoder.wait.assert_called_once()
        self.assertFalse(args.output.exists())

    def test_capture_injects_config_before_navigation_and_awaits_frames(self):
        args = self.args("--start", "0.5", "--seconds", "0.1")
        page, _, factory = self.browser()
        encoder = mock.Mock()
        encoder.wait.return_value = 0
        def start_encoder(command, **kwargs):
            Path(command[-1]).write_bytes(b"mp4")
            return encoder
        with mock.patch.object(capture.subprocess, "Popen", side_effect=start_encoder):
            capture.capture(args, factory)
        calls = [call[0] for call in page.mock_calls]
        self.assertLess(calls.index("add_init_script"), calls.index("goto"))
        frames = [call.args[1] for call in page.evaluate.call_args_list if len(call.args) == 2]
        self.assertEqual(frames, [0.5, 0.5 + 1 / 30, 0.5 + 2 / 30])
        self.assertIn("await window.render", page.evaluate.call_args.args[0])
        launch = factory.return_value.__enter__.return_value.chromium.launch.call_args.kwargs
        self.assertNotIn("channel", launch)
        self.assertFalse(any("d3d11" in value for value in launch["args"]))

    def test_main_reports_nonzero_without_service(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(capture.main(["missing", "--root", str(self.root)]), 1)
            self.assertEqual(make_take.main(["take", "voice", "--min-end", "4", "--max-end", "3"]), 1)

    def test_make_take_args_locale_and_legacy_negative_rate(self):
        args = make_take.parse_args(["take", "voice", "--root", str(self.root), "--rate", "-3%"])
        self.assertEqual(args.locale, "en-US")
        self.assertEqual(args.rate, "-3%")
        with mock.patch.multiple(make_take, PRON={}, paras=["Go, go again!"], create=True):
            self.assertIn('xml:lang="fr-FR"', make_take.build_ssml("voice", "fr-FR"))
            self.assertIn('xml:lang="en-US"', make_take.build_ssml("voice"))
        for extra in [("--min-end", "2", "--max-end", "1"), ("--hold", "-1"),
                      ("--tries", "0"), ("--max-end", "nan")]:
            with self.assertRaises(ValueError):
                make_take.parse_args(["take", "voice", *extra])

    def test_actual_wav_duration_controls_strict_take_selection(self):
        args = make_take.parse_args(["take", "voice", "--min-end", "1.01", "--max-end", "2", "--tries", "1"])
        with mock.patch.object(make_take, "synth", return_value=(self.audio, [])), \
             mock.patch.object(make_take, "align", return_value=[("Go.", 0, 0.5, 0)]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "strict"):
                make_take.choose_take(args)
            args.min_end = args.max_end = 1
            self.assertEqual(make_take.choose_take(args)[1], 1)
            args.max_end = 0.99
            args.min_end = 0
            with self.assertRaisesRegex(ValueError, "strict"):
                make_take.choose_take(args)

    def test_take_metadata_preserves_final_hold_without_rounding_down(self):
        args = make_take.parse_args(["take", "voice", "--hold", "0.24"])
        with mock.patch.multiple(make_take, paras=["Go."], ssml="ssml", create=True), \
             contextlib.redirect_stdout(io.StringIO()):
            make_take.write_take(args, str(self.root / "new_take"), "Go.", 1.01,
                                 [("Go.", 0, 1, 0)], [], self.audio)
        meta = json.loads((self.root / "new_take" / "meta.json").read_text())
        self.assertEqual(meta["duration"], 1.3)
        self.assertGreaterEqual(meta["duration"], meta["narration_end"] + meta["hold"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_real_encoding_frame_count_preview_audio_and_final_hold(self):
        jpeg = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64",
                               "-frames:v", "1", "-c:v", "mjpeg", "-threads", "1", "-f", "image2pipe", "-"],
                              capture_output=True, check=True).stdout
        for start, seconds, expected_frames in [("0.5", "0.5", 15), ("0", "1.2", 36)]:
            with self.subTest(start=start):
                args = self.args("--width", "64", "--height", "64", "--start", start, "--seconds", seconds,
                                 "--output", str(self.root / f"clip-{start}.mp4"))
                _, _, factory = self.browser(jpeg)
                capture.capture(args, factory)
                probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                                        "-show_format", "-of", "json", str(args.output)],
                                       capture_output=True, text=True, check=True)
                info = json.loads(probe.stdout)
                video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
                audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
                self.assertEqual(int(video["nb_read_frames"]), expected_frames)
                self.assertEqual((video["width"], video["height"]), (64, 64))
                self.assertAlmostEqual(float(info["format"]["duration"]), float(seconds), places=3)
                self.assertAlmostEqual(float(audio["duration"]), float(seconds), places=3)
                if start == "0.5":
                    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(args.output), "-t", seconds,
                                          "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                                         capture_output=True, check=True).stdout
                    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
                    self.assertEqual(len(samples), 24000)
                    crossings = sum(left < 0 <= right for left, right in zip(samples, samples[1:]))
                    self.assertTrue(420 <= crossings <= 460, crossings)

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright Python and bundled Chromium required")
    def test_real_browser_portrait_pixels_and_async_render(self):
        from playwright.sync_api import sync_playwright
        (self.root / "core").mkdir()
        for name in ("engine.js", "shared.css"):
            shutil.copyfile(capture.ROOT / "core" / name, self.root / "core" / name)
        (self.root / "scene" / "index.html").write_text('''<!doctype html>
<style>html,body{margin:0;background:black}#stage{width:1920px;height:1080px;background:red}</style>
<div id="stage"></div><script src="../core/engine.js"></script>
<script>E.afterRender=async(t)=>{await Promise.resolve();const stage=document.getElementById('stage');stage.dataset.done='yes';stage.style.background=t>=0.5?'blue':'red'};E.ready();</script>''')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.add_init_script('window.AIGENVIDAGENT_RENDER={width:1080,height:1920,duration:1.2}')
            page.goto((self.root / "scene" / "index.html").as_uri())
            page.wait_for_function("window.READY === true")
            result = page.evaluate('''() => {
              const stage = document.getElementById('stage');
              const bounds = stage.getBoundingClientRect();
              return {left:bounds.left,right:bounds.right,top:bounds.top,bottom:bounds.bottom,done:stage.dataset.done};
            }''')
            self.assertEqual(result, {"left": 0, "right": 1080, "top": 656.25, "bottom": 1263.75, "done": "yes"})
            self.assertGreater(len(page.screenshot(type="png")), 1000)
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.add_init_script('window.AIGENVIDAGENT_RENDER={width:1920,height:1080,duration:1.2}')
            page.reload()
            page.wait_for_function("window.READY === true")
            self.assertEqual(page.evaluate("document.getElementById('stage').getBoundingClientRect().width"), 1920)
            browser.close()
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            output = self.root / "real-preview.mp4"
            result = subprocess.run([sys.executable, str(capture.ROOT / "capture.py"), "scene", "--root", str(self.root),
                                     "--output", str(output), "--width", "64", "--height", "96", "--fps", "30",
                                     "--duration", "1.2", "--captions", "none", "--browser", "chromium",
                                     "--start", "0.5", "--seconds", "0.1"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams",
                                              "-show_format", "-of", "json", str(output)],
                                             capture_output=True, text=True, check=True).stdout)
            video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"], int(video["nb_read_frames"])), (64, 96, 3))
            self.assertAlmostEqual(float(info["format"]["duration"]), 0.1, places=3)
            pixels = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
                                     "-vf", "crop=2:2:32:48,format=rgb24", "-f", "rawvideo", "-"],
                                    capture_output=True, check=True).stdout
            self.assertLess(pixels[0], 20)
            self.assertGreater(pixels[2], 200)


if __name__ == "__main__":
    unittest.main()