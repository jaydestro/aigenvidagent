"""Capture a version page frame-by-frame in headless Edge and encode it with the narration.

python capture.py <project>                 -> out/<project>.mp4
python capture.py <project> --stills 3,20   -> out/stills/<project>-003.0.png ...
"""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
FPS, DUR = 30, 90.0
ver = sys.argv[1]
AUDIO = None  # set from <project>/config.json -> takes/<take>/narration.wav
cfgp = os.path.join(ROOT, ver, "config.json")
if os.path.exists(cfgp):
    import json
    take = json.load(open(cfgp))["take"]
    meta = json.load(open(os.path.join(ROOT, "takes", take, "meta.json")))
    DUR = float(meta["duration"])
    AUDIO = os.path.join(ROOT, "takes", take, "narration.wav")
if AUDIO is None and "--stills" not in sys.argv:
    raise SystemExit(f"{ver}/config.json with a 'take' is required for a full render")
stills = None
if "--stills" in sys.argv:
    stills = [float(x) for x in sys.argv[sys.argv.index("--stills") + 1].split(",")]
os.makedirs(os.path.join(ROOT, "out", "stills"), exist_ok=True)
url = "file:///" + os.path.join(ROOT, ver, "index.html").replace("\\", "/")

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True,
                          args=["--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist",
                                "--allow-file-access-from-files", "--force-color-profile=srgb", "--hide-scrollbars"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(url)
    pg.wait_for_function("window.READY === true", timeout=120000)
    if errs:
        print("PAGE ERRORS:", *errs[:10], sep="\n  ")
    cdp = pg.context.new_cdp_session(pg)

    def shot(fmt="png", q=None):
        args = {"format": fmt, "captureBeyondViewport": False, "optimizeForSpeed": fmt != "png"}
        if q:
            args["quality"] = q
        import base64
        return base64.b64decode(cdp.send("Page.captureScreenshot", args)["data"])

    if stills is not None:
        for t in stills:
            pg.evaluate(f"window.render({t})")
            open(os.path.join(ROOT, "out", "stills", f"{ver}-{t:05.1f}.png"), "wb").write(shot())
        print("stills done", len(stills), "errors:", len(errs))
        b.close()
        sys.exit(0)

    out = os.path.join(ROOT, "out", f"{ver}.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
           "-i", AUDIO,
           "-filter_complex", f"[1:a]apad=whole_dur={DUR},atrim=0:{DUR},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(DUR), out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    st = time.time()
    n = int(FPS * DUR)
    for f in range(n):
        pg.evaluate(f"window.render({f / FPS})")
        enc.stdin.write(shot("jpeg", 96))
        if f % 300 == 0:
            print(ver, "frame", f, f"{time.time() - st:.0f}s", flush=True)
    enc.stdin.close()
    enc.wait()
    print(ver, "done", out, enc.returncode, f"{time.time() - st:.0f}s", "errors:", len(errs))
    b.close()
