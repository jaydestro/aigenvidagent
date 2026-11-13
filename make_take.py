"""Record a narration take with Azure Speech and emit word timings, exact-span captions and data.js.

python make_take.py <take> <voiceShortName> --script <file> [--rate -3%] [--para-break 650]
       [--min-end S --max-end S] [--hold 3] [--tries 8] [--natural] [--max-gap 0.25] [--pron file] [--region eastus2]

Requires $env:SPK (Speech / AI Services key). Writes takes/<take>/{narration.wav,timing.json,data.js,meta.json}.
Script: paragraphs separated by blank lines. --natural rejects takes with unnatural in-sentence pauses.
"""
import html, json, os, re, subprocess, sys
import azure.cognitiveservices.speech as sp

ROOT = os.path.dirname(os.path.abspath(__file__))
name, voice = sys.argv[1], sys.argv[2]


def arg(flag, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


tries = arg("--tries", 8, int)
rate = arg("--rate")
REGION = arg("--region", "eastus2")
out = os.path.join(ROOT, "takes", name)
os.makedirs(out, exist_ok=True)
SCRIPT = arg("--script", os.path.join(ROOT, "script.txt"))
src = open(SCRIPT, encoding="utf-8-sig").read().replace("\r\n", "\n").strip()
MIN_END = arg("--min-end", 0.0, float)
MAX_END = arg("--max-end", 1e9, float)
HOLD = arg("--hold", 3.0, float)
# pronunciation.json: {"written term": "how to say it"} - speech only; captions keep the written words
PRON_FILE = arg("--pron", os.path.join(os.path.dirname(os.path.abspath(SCRIPT)), "pronunciation.json"))
PRON = json.load(open(PRON_FILE, encoding="utf-8")) if os.path.exists(PRON_FILE) else {}
paras = [x.strip() for x in src.split("\n\n") if x.strip()]


def esc(t):
    t = html.escape(t, quote=False)
    for term, spoken in PRON.items():
        e = html.escape(term, quote=False)
        t = t.replace(e, f'<sub alias="{html.escape(spoken)}">{e}</sub>')
    return t


PARA_BREAK = int(sys.argv[sys.argv.index("--para-break") + 1]) if "--para-break" in sys.argv else None
sep = f' <break time="{PARA_BREAK}ms"/> ' if PARA_BREAK else " "
body = sep.join(esc(x) for x in paras)
if rate:
    body = f'<prosody rate="{rate}">{body}</prosody>'
ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US"><voice name="{voice}">' + body + "</voice></speak>"
cfg = sp.SpeechConfig(subscription=os.environ["SPK"], region=REGION)
cfg.set_speech_synthesis_output_format(sp.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)


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
# spoken forms from pronunciation.json; tried only if the written token does not match the word boundaries
ALIAS_FALLBACK = {k: [norm(w) for w in re.split(r"[\s-]+", v) if norm(w)] for k, v in PRON.items()}


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


best = None
NATURAL = "--natural" in sys.argv
MAXGAP = float(sys.argv[sys.argv.index("--max-gap") + 1]) if "--max-gap" in sys.argv else 0.25


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


for i in range(tries):
    audio, words = synth()
    wav = os.path.join(out, f"try{i}.wav")
    open(wav, "wb").write(audio)
    tok = align(words)
    end = tok[-1][2]
    ok, worst = flow_ok(audio, tok) if NATURAL else (True, (0, ""))
    print(name, "try", i, "narration end", round(end, 2), "| worst in-sentence break", round(worst[0], 2), worst[1], "| flow ok" if ok else "| flow FAIL", flush=True)
    if not ok:
        continue
    if best is None or abs(end - (MIN_END + MAX_END) / 2) < abs(best[1] - (MIN_END + MAX_END) / 2):
        best = (i, end, tok, words)
    if MIN_END <= end <= MAX_END:
        best = (i, end, tok, words)
        break
if best is None:
    raise SystemExit("no take passed the natural-flow gate")
i, end, tok, words = best
if end > MAX_END + 1.5:
    raise SystemExit(f"no take fits: best {end:.2f}")
os.replace(os.path.join(out, f"try{i}.wav"), os.path.join(out, "narration.wav"))
for f in os.listdir(out):
    if f.startswith("try"):
        os.remove(os.path.join(out, f))

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

dur = round(end + HOLD, 1)
para_start = [next(t[1] for t in tok if t[3] == k) for k in range(len(paras))]
WORDS = [[t[0], round(t[1], 3), round(t[2], 3)] for t in tok]
meta = {"name": name, "voice": voice, "rate": rate or "+0%", "para_break": PARA_BREAK, "narration_end": round(end, 3), "duration": dur, "para_start": [round(x, 3) for x in para_start]}
json.dump({"voice": voice, "ssml": ssml, "words": words}, open(os.path.join(out, "timing.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(meta, open(os.path.join(out, "meta.json"), "w"), indent=1)
with open(os.path.join(out, "data.js"), "w", encoding="utf-8") as f:
    f.write("window.WORDS=" + json.dumps(WORDS, ensure_ascii=False) + ";\n")
    f.write("window.CAPTIONS=" + json.dumps([{k: p_[k] for k in ("text", "show", "hide")} for p_ in phrases], ensure_ascii=False) + ";\n")
    f.write("window.META=" + json.dumps(meta) + ";\n")
print("KEPT", json.dumps(meta))
