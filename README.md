# Keyframe

Keyframe is an AI agent and toolkit for producing polished, narrated videos for high-profile moments:

- keynotes, launches and executive briefings
- customer stories, investor and board updates
- event openers, social and web promos

Videos can run from 15 seconds to 10 minutes.

Every frame is rendered from code, so every word, caption and visual lands exactly on time and can be revised and verified.

## How it works

```
script.txt ──► narration take (Azure Speech, word timings) ──► exact-span captions
                       │
                       ▼
 scenes (HTML/SVG/WebGL keyed to spoken words) ──► frame capture (Edge) ──► MP4 (H.264 + AAC)
                                                                    │
                                    verify: stills, speech-to-text, script match, frame count
```

## Use the agent

1. Open this folder in VS Code.
2. In Copilot Chat, select the **Keyframe** agent (`.github/agents/keyframe.agent.md`).
3. Describe the video: audience, venue, length, script or topic, brand, and assets. The agent runs intake, writes the prompt file, builds, verifies and delivers versioned outputs.

To use Keyframe in every workspace, copy `.github/agents/keyframe.agent.md` into your VS Code user prompts folder.

## Run the example

Prerequisites:

- Node.js
- Python 3, plus `pip install azure-cognitiveservices-speech playwright pillow numpy`
- ffmpeg on PATH
- Microsoft Edge
- Azure CLI signed in to a subscription with an Azure AI Services or Speech resource

```powershell
npm install
# Speech key (read at runtime, never stored)
$env:SPK = (az cognitiveservices account keys list -n <resource> -g <group> --subscription <subscription-id> --query key1 -o tsv)

python make_take.py example "en-US-Ava:DragonHDLatestNeural" --script example/script.txt --rate "-3%" --para-break 650 --hold 2.5 --tries 8 --natural
npx esbuild example/main.js --bundle --format=iife --outfile=example/bundle.js
python capture.py example --stills 2,8,14      # review frames in out/stills
python tools_sheet.py example 3                 # contact sheet -> out/example-sheet.png
python capture.py example                       # full render -> out/example.mp4
```

## Start a new video

1. Copy `example/` to a new folder, for example `launch-video/`.
2. Write `launch-video/script.txt`, with paragraphs separated by blank lines.
3. Add pronunciations to `launch-video/pronunciation.json`. These affect speech only; captions keep the written words.
4. Set `config.json` to `{"take":"launch-video"}` and point `index.html` at `../takes/launch-video/data.js`.
5. Record the take, then build scenes in `main.js` using `E.cue('word')` and `E.P[i]` (paragraph starts).
6. Copy `templates/prompt.md` into the project and fill it in. It is the source of truth for the agent.

## Layout

```
.github/agents/keyframe.agent.md   the loadable agent
docs/VIDEO-PROMPT-GUIDE.md         how to write the prompt and refine
templates/prompt.md                fill-in prompt template
core/engine.js                     deterministic frame engine: tracks, word cues, captions, drift, float
core/geo.js                        globes and maps (d3-geo, Natural Earth)
core/shared.css                    caption styles and shared components
make_take.py                       narration take with length and natural-flow gates
capture.py                         stills or full render via Playwright + ffmpeg
tools_sheet.py, stt_check.py       contact sheets and speech-to-text check
example/                           a 3-beat starter video
```

## Rules the agent follows

- The locked script is never changed without the user.
- Every round is a new version; nothing delivered is overwritten.
- Official logos and real data only; brand owners' rules are respected.
- Speech flows naturally, with pauses only between sentences.
- No personal data on screen.
- Nothing is called done until it is verified on the rendered file.
