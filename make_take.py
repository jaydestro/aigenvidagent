"""Record a narration take with Azure Speech and emit word timings, exact-span captions and data.js.

python make_take.py <take> <voiceShortName> --script <file> [--rate -3%] [--para-break 650]
       [--min-end S --max-end S] [--hold 3] [--tries 8] [--natural] [--max-gap 0.25] [--pron file] [--region eastus2]

Requires $env:SPK (Speech / AI Services key). Writes takes/<take>/{narration.wav,timing.json,data.js,meta.json}.
Script: paragraphs separated by blank lines. --natural rejects takes with unnatural in-sentence pauses.
"""
import argparse
import html, json, os, re, sys
import io
import wave
from fractions import Fraction

from render_options import finite_number, narration_fits

ROOT = os.path.dirname(os.path.abspath(__file__))
PRON = {}
paras = []
ALIAS_FALLBACK = {}
MAXGAP = 0.25
sp = None
cfg = None
ssml = ""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("voice")
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--script")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--rate")
    parser.add_argument("--region", default="eastus2")
    parser.add_argument("--tries", type=int, default=8)
    parser.add_argument("--min-end", type=float, default=0.0)
    parser.add_argument("--max-end", type=float, default=1e9)
    parser.add_argument("--hold", type=float, default=3.0)
    parser.add_argument("--para-break", type=int)
    parser.add_argument("--natural", action="store_true")
    parser.add_argument("--max-gap", type=float, default=0.25)
    parser.add_argument("--pron")
    values = list(sys.argv[1:] if argv is None else argv)
    if "--rate" in values:
        index = values.index("--rate")
        if index + 1 < len(values):
            values[index:index + 2] = ["--rate=" + values[index + 1]]
    args = parser.parse_args(values)
    narration_fits(0, args.min_end, args.max_end)
    finite_number(args.hold, "hold")
    finite_number(args.max_gap, "max-gap")
    if args.tries <= 0 or (args.para_break is not None and args.para_break < 0):
        raise ValueError("tries must be positive and para-break nonnegative")
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", args.locale):
        raise ValueError("locale must be a language tag such as en-US")
    return args


def esc(t):
    t = html.escape(t, quote=False)
    for term, spoken in PRON.items():
        e = html.escape(term, quote=False)
        t = t.replace(e, f'<sub alias="{html.escape(spoken)}">{e}</sub>')
    return t


def build_ssml(voice, locale="en-US", rate=None, para_break=None):
    sep = f' <break time="{para_break}ms"/> ' if para_break else " "
    body = sep.join(esc(para) for para in paras)
    if rate:
        body = f'<prosody rate="{html.escape(rate, quote=True)}">{body}</prosody>'
    return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{html.escape(locale, quote=True)}"><voice name="{html.escape(voice, quote=True)}">' + body + "</voice></speak>"


def synth():
    syn = sp.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    words = []
    syn.synthesis_word_boundary.connect(lambda e: words.append({"text": e.text, "offset": e.audio_offset / 1e7, "dur": e.duration.total_seconds(), "type": str(e.boundary_type)}))
    r = syn.speak_ssml_async(ssml).get()
    if r.reason != sp.ResultReason.SynthesizingAudioCompleted:
        raise SystemExit(f"synthesis failed: {r.cancellation_details.error_details}")
    return r.audio_data, words


def norm(s):
    return re.sub(r"[^0-9a-z]", "", s.lower())


ALIAS = {}


def match_target(bn, bi, target):
    acc, st, en = "", None, None
    while acc != target:
        if bi >= len(bn):
            return None
        n, s, e = bn[bi]
        if not target.startswith(acc + n):
            return None
        acc += n; bi += 1; st = s if st is None else st; en = e
    return bi, st, en


def align(words):
    bw = [x for x in words if "Word" in x["type"]]
    bn = []
    for x in bw:
        t = x["text"].split()[-1] if ">" in x["text"] else x["text"]
        if ">" in x["text"] and len(x["text"].split()) > 1 and bn and False:
            # SSML sub-alias artifacts can glue markup to the next word; the real word is the last token
            t = x["text"].split()[-1]
        bn.append((norm(t), x["offset"], x["offset"] + x["dur"]))
    tok, bi = [], 0
    for pi, para in enumerate(paras):
        for t in para.split():
            key = t.rstrip(".,")
            targets = ["".join(ALIAS.get(key, [norm(t)]))]
            if key in ALIAS_FALLBACK:
                targets.append("".join(ALIAS_FALLBACK[key]))
            m = None
            for target in targets:
                m = match_target(bn, bi, target)
                if m:
                    break
            if m is None:
                raise ValueError(f"align fail {t!r} vs {bn[bi][0] if bi < len(bn) else None!r}")
            bi, st, en = m
            tok.append((t, st, en, pi))
    assert bi == len(bn)
    return tok


def flow_ok(audio, tok):
    """Natural-flow gate: inside every sentence (not after , . or a paragraph end), adjacent words must be
    connected - both the word-boundary gap and any true silence (< -40 dB, 10 ms frames) between them
    must stay under MAXGAP seconds."""
    import numpy as np
    pcm = np.frombuffer(audio[44:], np.int16).astype(float) if audio[:4] == b"RIFF" else None
    worst = (0.0, "")
    for a, b in zip(tok, tok[1:]):
        if a[0][-1] in ".,;:" or a[3] != b[3]:
            continue
        gap = b[1] - a[2]
        sil = 0.0
        if pcm is not None:
            sr, run = 48000, 0.0
            t = max(a[1] + (a[2] - a[1]) * 0.6, 0)
            while t < b[1] + (b[2] - b[1]) * 0.3:
                s = pcm[int(t * sr):int((t + 0.01) * sr)]
                db = 20 * np.log10(np.sqrt((s ** 2).mean()) / 32768 + 1e-9) if len(s) else 0
                run = run + 0.01 if db < -40 else 0.0
                sil = max(sil, run)
                t += 0.01
        m = max(gap, sil)  # a 0.20-0.24 s dip is normal articulation (e.g. "globally and"); 0.4+ s reads as a pause
        if m > worst[0]:
            worst = (m, f"{a[0]} -> {b[0]}")
    return worst[0] <= MAXGAP, worst


def choose_take(args):
    for attempt in range(args.tries):
        audio, words = synth()
        tok = align(words)
        with wave.open(io.BytesIO(audio), "rb") as recording:
            end = Fraction(recording.getnframes(), recording.getframerate())
        if not tok or tok[-1][2] > float(end):
            raise ValueError("word timings exceed the actual narration audio")
        ok, worst = flow_ok(audio, tok) if args.natural else (True, (0, ""))
        print(args.name, "try", attempt, "narration end", round(float(end), 2), "| worst in-sentence break", round(worst[0], 2), worst[1], "| flow ok" if ok else "| flow FAIL", flush=True)
        if ok and narration_fits(end, args.min_end, args.max_end):
            return audio, float(end), tok, words
    raise ValueError("no take fits the strict min-end/max-end window and natural-flow gate")

# captions: sentence spans, split at the most balanced point (preferring commas) when > 92 chars
MAXC = 92


def split_span(span):
    txt = " ".join(c[0] for c in span)
    if len(txt) <= MAXC:
        return [span]
    mid, best_ = len(txt) / 2, None
    for k in range(1, len(span)):
        left = " ".join(c[0] for c in span[:k])
        sc = abs(len(left) - mid) - (25 if span[k - 1][0].endswith(",") else 0)
        if best_ is None or sc < best_[0]:
            best_ = (sc, k)
    return split_span(span[:best_[1]]) + split_span(span[best_[1]:])


def write_take(args, out, src, end, tok, words, audio):
    phrases, sent = [], []
    for j, tk in enumerate(tok):
        sent.append(tk)
        nxt = tok[j + 1] if j + 1 < len(tok) else None
        if tk[0].endswith(".") or nxt is None or nxt[3] != tk[3]:
            for s_ in split_span(sent):
                phrases.append({"text": " ".join(c[0] for c in s_), "start": s_[0][1], "end": s_[-1][2]})
            sent = []
    assert " ".join(p_["text"] for p_ in phrases) == " ".join(src.split())
    for j, p_ in enumerate(phrases):
        nxt = phrases[j + 1]["start"] if j + 1 < len(phrases) else 999
        p_["show"] = round(max(0.0, p_["start"] - 0.08), 3)
        p_["hide"] = round(min(nxt - 0.08, p_["end"] + 0.6) if j + 1 < len(phrases) else p_["end"] + 0.3, 3)

    finish = (Fraction(str(end)) + Fraction(str(args.hold))) * 10
    dur = -(-finish.numerator // finish.denominator) / 10
    para_start = [next(t[1] for t in tok if t[3] == k) for k in range(len(paras))]
    WORDS = [[t[0], round(t[1], 3), round(t[2], 3)] for t in tok]
    meta = {"name": args.name, "voice": args.voice, "rate": args.rate or "+0%", "para_break": args.para_break, "locale": args.locale, "hold": args.hold, "narration_end": end, "duration": dur, "para_start": [round(x, 3) for x in para_start]}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "narration.wav"), "wb") as handle:
        handle.write(audio)
    with open(os.path.join(out, "timing.json"), "w", encoding="utf-8") as handle:
        json.dump({"voice": args.voice, "ssml": ssml, "words": words}, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1)
    with open(os.path.join(out, "data.js"), "w", encoding="utf-8") as handle:
        handle.write("window.WORDS=" + json.dumps(WORDS, ensure_ascii=False) + ";\n")
        handle.write("window.CAPTIONS=" + json.dumps([{k: p_[k] for k in ("text", "show", "hide")} for p_ in phrases], ensure_ascii=False) + ";\n")
        handle.write("window.META=" + json.dumps(meta) + ";\n")
    print("KEPT", json.dumps(meta))


def main(argv=None):
    global PRON, paras, ALIAS_FALLBACK, MAXGAP, sp, cfg, ssml
    try:
        args = parse_args(argv)
        root = os.path.abspath(args.root)
        out = os.path.abspath(os.path.join(root, "takes", args.name))
        if os.path.commonpath([os.path.join(root, "takes"), out]) != os.path.join(root, "takes"):
            raise ValueError("take must remain inside root/takes")
        script = args.script or os.path.join(root, "script.txt")
        with open(script, encoding="utf-8-sig") as handle:
            src = handle.read().replace("\r\n", "\n").strip()
        if not src:
            raise ValueError("script must not be empty")
        pron_file = args.pron or os.path.join(os.path.dirname(os.path.abspath(script)), "pronunciation.json")
        PRON = {}
        if os.path.exists(pron_file):
            with open(pron_file, encoding="utf-8") as handle:
                PRON = json.load(handle)
        paras = [para.strip() for para in src.split("\n\n") if para.strip()]
        ALIAS_FALLBACK = {key: [norm(word) for word in re.split(r"[\s-]+", value) if norm(word)] for key, value in PRON.items()}
        MAXGAP = args.max_gap
        ssml = build_ssml(args.voice, args.locale, args.rate, args.para_break)
        import azure.cognitiveservices.speech as sp
        cfg = sp.SpeechConfig(subscription=os.environ["SPK"], region=args.region)
        cfg.set_speech_synthesis_output_format(sp.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
        audio, end, tok, words = choose_take(args)
        write_take(args, out, src, end, tok, words, audio)
        return 0
    except Exception as error:
        print(f"make_take: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
