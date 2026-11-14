"""Capture deterministic scene frames with bundled Playwright Chromium."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction

from render_options import finite_number, frame_count, validate_finish


ROOT = Path(__file__).resolve().parent


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("project", nargs="?", default="example")
    result.add_argument("--root", type=Path, default=ROOT)
    result.add_argument("--output", type=Path)
    result.add_argument("--width", type=int, default=1920)
    result.add_argument("--height", type=int, default=1080)
    result.add_argument("--fps", type=int, default=30)
    result.add_argument("--duration")
    result.add_argument("--captions", choices=("none", "static", "highlight"), default="static")
    result.add_argument("--browser", choices=("chromium",), default="chromium")
    result.add_argument("--start", default="0")
    result.add_argument("--seconds")
    result.add_argument("--stills")
    return result


def within(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path must remain inside root: {relative}")
    return path


def audio_duration(path):
    with wave.open(str(path), "rb") as audio:
        return Fraction(audio.getnframes(), audio.getframerate())


def audio_has_signal(path):
    with wave.open(str(path), "rb") as audio:
        silent_byte = 128 if audio.getsampwidth() == 1 else 0
        while frames := audio.readframes(65536):
            if any(sample != silent_byte for sample in frames):
                return True
    return False


def options(argv=None):
    args = parser().parse_args(argv)
    args.root = args.root.resolve()
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        raise ValueError("width and height must be positive even integers")
    if args.fps <= 0:
        raise ValueError("fps must be positive")
    args.scene = within(args.root, args.project)
    args.url = (args.scene / "index.html").as_uri()
    if not (args.scene / "index.html").is_file():
        raise ValueError("project index.html does not exist")
    args.meta = {}
    args.audio = None
    config = args.scene / "config.json"
    if config.exists():
        take = json.loads(config.read_text(encoding="utf-8"))["take"]
        take_dir = within(args.root, Path("takes") / take)
        args.meta = json.loads((take_dir / "meta.json").read_text(encoding="utf-8"))
        args.audio = take_dir / "narration.wav"
    args.total = args.duration if args.duration is not None else str(args.meta.get("duration", 90))
    finite_number(args.total, "duration")
    if Fraction(args.total) <= 0:
        raise ValueError("duration must be positive")
    frame_count(args.total, args.fps)
    finite_number(args.start, "start")
    args.start = Fraction(args.start)
    args.seconds = Fraction(args.seconds) if args.seconds is not None else Fraction(args.total) - args.start
    finite_number(args.seconds, "seconds")
    if args.seconds <= 0 or args.start + args.seconds > Fraction(args.total):
        raise ValueError("preview interval must be positive and within total duration")
    args.frames = frame_count(args.seconds, args.fps)
    args.stills = [finite_number(value, "still time") for value in args.stills.split(",")] if args.stills is not None else None
    if args.stills is not None and any(value >= float(args.total) for value in args.stills):
        raise ValueError("still time must be within total duration")
    if args.stills is None:
        if args.audio is None:
            raise ValueError("project config.json with a take is required for a full render")
        actual = audio_duration(args.audio)
        end = args.meta.get("narration_end", float(actual))
        legacy_hold = max(
            Fraction(0),
            Fraction(str(args.meta.get("duration", end))) - Fraction(str(end)),
        )
        hold = args.meta.get("hold", legacy_hold)
        validate_finish(args.total, actual, end, hold)
    args.output = (args.output or args.root / "out" / f"{args.scene.name}.mp4").resolve()
    return args


def render_frame(page, timestamp, errors):
    page.evaluate("async timestamp => { await window.render(timestamp); await document.fonts.ready; }", float(timestamp))
    if errors:
        raise RuntimeError("page errors: " + "; ".join(errors))


def encode_command(args, output):
    start, seconds = str(float(args.start)), str(float(args.seconds))
    normalization = "loudnorm=I=-16:TP=-1.5:LRA=11," if audio_has_signal(args.audio) else ""
    return ["ffmpeg", "-v", "error", "-n", "-f", "image2pipe", "-framerate", str(args.fps),
            "-c:v", "mjpeg", "-i", "-", "-i", str(args.audio), "-filter_complex",
            f"[1:a]apad,atrim=start={start}:duration={seconds},asetpts=PTS-STARTPTS,{normalization}aresample=48000[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "15",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-colorspace", "bt709", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-t", seconds, str(output)]


def capture(args, playwright_factory=None):
    if playwright_factory is None:
        from playwright.sync_api import sync_playwright
        playwright_factory = sync_playwright
    reserved = False
    temporary = None
    try:
        if args.stills is None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb"):
                reserved = True
            with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix=".mp4", delete=False) as handle:
                temporary = Path(handle.name)
            temporary.unlink()
        with playwright_factory() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--allow-file-access-from-files", "--force-color-profile=srgb", "--hide-scrollbars"])
            try:
                page = browser.new_page(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                config = {"width": args.width, "height": args.height, "fps": args.fps, "duration": float(args.total), "captions": args.captions}
                page.add_init_script("window.AIGENVIDAGENT_RENDER = " + json.dumps(config) + ";")
                page.goto(args.url)
                page.wait_for_function("window.READY === true", timeout=120000)
                page.evaluate("async () => { await document.fonts.ready; }")
                if errors:
                    raise RuntimeError("page errors: " + "; ".join(errors))
                if args.stills is not None:
                    directory = args.root / "out" / "stills"
                    directory.mkdir(parents=True, exist_ok=True)
                    for timestamp in args.stills:
                        render_frame(page, timestamp, errors)
                        target = directory / f"{args.scene.name}-{timestamp:05.1f}.png"
                        image = page.screenshot(type="png")
                        with target.open("xb") as handle:
                            handle.write(image)
                    return
                with tempfile.TemporaryFile() as diagnostics:
                    encoder = subprocess.Popen(encode_command(args, temporary), stdin=subprocess.PIPE, stderr=diagnostics)
                    try:
                        for frame in range(args.frames):
                            render_frame(page, args.start + Fraction(frame, args.fps), errors)
                            encoder.stdin.write(page.screenshot(type="jpeg", quality=96))
                        encoder.stdin.close()
                        returncode = encoder.wait()
                    except BaseException:
                        encoder.terminate()
                        encoder.wait()
                        raise
                    if returncode:
                        diagnostics.seek(0)
                        raise RuntimeError("ffmpeg failed: " + diagnostics.read().decode("utf-8", errors="replace"))
                if errors:
                    raise RuntimeError("page errors: " + "; ".join(errors))
                temporary.replace(args.output)
                reserved = False
            finally:
                browser.close()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if reserved:
            args.output.unlink(missing_ok=True)


def main(argv=None):
    try:
        args = options(argv)
        capture(args)
        print("capture complete", args.output if args.stills is None else "stills")
        return 0
    except Exception as error:
        print(f"capture: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
