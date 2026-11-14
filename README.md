# aigenvidagent

aigenvidagent turns a confirmed brief into a narrated video built from code: keynotes,
launches, executive briefings, developer explainers and social stories. The coding
agent writes the actual HTML/SVG/WebGL scenes using the existing toolkit; the
Python CLI coordinates a **local Microsoft Agent Framework workflow** with
deterministic preparation, approvals, rendering and verification. It is not an
automatic film generator and does not require a separate model API key or a
Foundry deployment. Live speech discovery/synthesis needs separately configured
service access and consent; local setup, builds and unit tests do not.

## Start in Your Editor

1. Open the repository and select **aigenvidagent** in Copilot Chat. Other coding
    agents can start with [AGENTS.md](AGENTS.md).
2. **Choose the editor model first.** Use an available model with strong reasoning,
    scene coding, long-context instruction following and image inspection. The
    agent recommends only models actually exposed by the editor or supplied by
    you. If it cannot see the picker, you select and confirm; it never invents a
    model switch.
3. **Just give me a URL and I will create a video based on it.** Start with a
    public HTTPS page, run `/initialize` for an interview, or complete the
    [brief form](templates/prompt.md) and ask the agent to import it. It can generate
    a fresh editable form for you. JSON import uses [templates/brief.json](templates/brief.json).
4. Approve one storyboard option per final variant and listen to provider-aware
    voice auditions or your supplied narration. Confirm each variant's script,
    hook, tone, voice, model/provider, assets, format and captions. An optional
    short motion preview uses the prepared scene narration, not audition audio.
5. Run `/produce`. The agent authors/builds scenes, prepares a source-bound plan,
    and asks you to **reconfirm the total number of final variants** before render.

The reusable prompts live in [.github/prompts/initialize.prompt.md](.github/prompts/initialize.prompt.md)
and [.github/prompts/produce.prompt.md](.github/prompts/produce.prompt.md). They use
the shared [agent workflow](.github/agents/aigenvidagent.agent.md), not separate rules.
See the [production guide](docs/VIDEO-PROMPT-GUIDE.md) for all decisions and gates.

## Local Setup

Requirements: **Python 3.11+**, **Node.js 22+**, **ffmpeg and ffprobe on PATH**, and
**Playwright's bundled Chromium**. Edge is not required. Run commands from the
repository root. Choose a supported Python interpreter installed on your machine;
the examples select 3.11. Ask before installing missing prerequisites. The commands
below install project dependencies and a browser; they do not authenticate or
provision cloud resources. A coding agent must obtain consent before running them.

### Windows (PowerShell)

Install Python 3.11+ and Node 22+ using your approved installers. For ffmpeg, one
option when Chocolatey is already installed is `choco install ffmpeg --yes` in a
user-run elevated terminal. Do not have the agent trigger unattended elevation.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
.\.venv\Scripts\python.exe -m playwright install chromium
ffmpeg -version
ffprobe -version
node --version
```

### macOS (zsh/bash)

With Homebrew already installed and your approval, `brew install python@3.11
node@22 ffmpeg` supplies prerequisites. Ensure the installed Node 22 binary is on
PATH (Homebrew prints the required PATH adjustment for its installation prefix).

```sh
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
npm ci
./.venv/bin/python -m playwright install chromium
ffmpeg -version
ffprobe -version
node --version
```

### Linux (bash)

Use your distro's Python 3.11+ and venv packages and an approved Node 22+
distribution. On Debian/Ubuntu, `sudo apt-get update` followed by
`sudo apt-get install -y ffmpeg` supplies both media tools. Browser system
dependencies can require administrator approval; only Linux uses `--with-deps`.

```sh
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
npm ci
./.venv/bin/python -m playwright install --with-deps chromium
ffmpeg -version
ffprobe -version
node --version
```

No activation is necessary: all Python commands use the project interpreter
explicitly. Do not use global pip or update dependency versions to repair setup.
If your environment cannot access a registry URL in the existing lockfile, report
that dependency-access blocker rather than silently replacing the lockfile.

The main [requirements.txt](requirements.txt) includes the local Agent Framework
workflow and [requirements-render.txt](requirements-render.txt) for capture.
[requirements-azure.txt](requirements-azure.txt) is optional, needed only for the
Azure SDK utilities. Install it separately with approval using
`./.venv/bin/python -m pip install -r requirements-azure.txt` (Windows:
`.\.venv\Scripts\python.exe -m pip install -r requirements-azure.txt`).
Provider REST auditions need no optional SDK. Piper is installed separately;
nothing downloads models, installs SDKs or authenticates automatically.

## Build and Test Without Cloud Access

The portable build takes a project directory as its argument and writes its
`bundle.js` using esbuild's JavaScript API. It supports paths containing spaces
and does not rely on shell environment-variable expansion or a downloaded `npx`.

```sh
npm run build -- example
npm run build -- "scenes/my video"
npm run test:build
npm test
```

The second build requires agent-authored scenes in that project. `npm test` lists
the engine and build test files explicitly, avoiding shell glob differences.

Python tests, Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Python tests, macOS/Linux:

```sh
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

[CI](.github/workflows/tests.yml) installs the main Python requirements, Node 22,
bundled Chromium and ffmpeg on Ubuntu, Windows and macOS. It enables
`AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1` for real browser capture, local Agent
Framework production, offline rendering, SRT and thumbnail checks, alongside
unit tests and the example build. No paid calls or cloud credentials are required.

## Production CLI

These are separate steps, not an unattended batch. On Windows use the prefix
below; on macOS/Linux substitute `./.venv/bin/python`. All IDs in CAPITALS are
placeholders: take voice IDs from the selected provider catalog and approval/run IDs from actual
CLI output, never copy invented IDs into a production command.

```powershell
.\.venv\Scripts\python.exe -m aigenvidagent initialize demo
.\.venv\Scripts\python.exe -m aigenvidagent initialize demo --url https://example.com
.\.venv\Scripts\python.exe -m aigenvidagent initialize demo --import brief.md
.\.venv\Scripts\python.exe -m aigenvidagent initialize demo --import brief.json --answers answers.json
.\.venv\Scripts\python.exe -m aigenvidagent export demo --format markdown --output projects/demo/brief-v01.md
.\.venv\Scripts\python.exe -m aigenvidagent export demo --format json --output projects/demo/brief-v01.json
.\.venv\Scripts\python.exe -m aigenvidagent providers demo
.\.venv\Scripts\python.exe -m aigenvidagent voices demo --refresh
.\.venv\Scripts\python.exe -m aigenvidagent preview demo --storyboards-only
.\.venv\Scripts\python.exe -m aigenvidagent preview demo --voices VOICE_ID_A VOICE_ID_B
```

The initialize commands above illustrate alternative entry routes. Resume reads
existing canonical state and asks only missing fields; conflicting imports need
an explicit decision. Fill the form before importing it. Approve storyboard and
audio, then let the agent author and build the actual scenes. Optionally request
an eight-second motion preview:

```powershell
npm run build -- scenes/demo
.\.venv\Scripts\python.exe -m aigenvidagent preview demo --voices VOICE_ID_A --video --start 0 --seconds 8
.\.venv\Scripts\python.exe -m aigenvidagent produce demo --prepare
```

JSON imports use the brief schema. Markdown imports contain exactly one fenced
JSON object, as produced by `export --format markdown`. For the human fill-in
form, the agent maps your answers to the schema and confirms the mapping before
importing. Free-form Markdown is not parsed as a brief.

URL intake archives readable public HTTPS text and creates an unlocked draft.
Check sources and claims, edit the draft, and approve the script before locking
it. For unreadable or authenticated pages, supply a permitted local text export;
do not automate login or fabricate missing content.

**Stop here for approval.** Inspect the prepared plan and reconfirm its total
variants and exact differences, runtime including final hold, format/captions,
voice, rights/privacy and any service cost. Only after explicit user approval:

```powershell
.\.venv\Scripts\python.exe -m aigenvidagent produce demo --approve APPROVAL_ID
.\.venv\Scripts\python.exe -m aigenvidagent verify demo --run RUN_ID
```

Plain `produce demo` is an alternative interactive approval path. Never pipe
automatic confirmations. Any source edit invalidates approval; prepare and approve
again. Failures or absent capabilities must be reported, not silently bypassed.

## State and Safety

Canonical state lives at `projects/<id>/brief.json`. Imported forms and exports
are inputs/handoff snapshots, not competing live briefs. Every revision gets a
new run; delivered files are never overwritten. Final variants live at
`out/<id>/<run>/variants/<id>/`: every variant includes `video.mp4`,
`captions.srt` and `thumbnail.jpg`, even with no burned-in captions. The brief
records exact duration OR an inclusive range (e.g. 90-110 seconds), including
the final silent hold. An impossible locked script is returned
to the user for a script/duration decision, never rewritten or accelerated.

Optional skills and MCP integrations require a proposal stating exact capability,
package/source, data access, configuration path, and workspace or user scope,
followed by consent. No MCP server implementation or provider deployment is
required. No silent global installation or automatic authentication is permitted.

Private/generated projects, previews, media, takes, output, logs, `.venv`, caches,
`.env` secrets and local MCP configuration are ignored. Safe environment examples,
intentional tests/fixtures and reusable templates remain eligible for tracking.
Ignore rules do not untrack previously committed secrets: remove and rotate any
exposed credential. Only publish licensed assets, verified claims, approved brand
artwork and privacy-safe frames. GitHub handles code review; local work uses
deterministic tests, builds and encoded-media checks, not review subagents.

## Narration Providers

Run `providers demo` before network access. It reports authentication, discovery,
data transfer and billing for each configured provider without contacting it.
Approve each cloud provider before discovery or auditions. Cloud synthesis sends
text, pronunciation and delivery choices to that service and may incur charges;
clipping an audition WAV does not cap billed generation. Never store credentials
in the brief or repository.

| Route | Catalog and configuration | Runtime access |
| --- | --- | --- |
| Azure | Live regional voices; resource ID, region and locale | Explicit `AIGENVIDAGENT_AZURE_SUBSCRIPTION_ID` matching the resource; key in `SPK`, or Entra with **Cognitive Services Speech User** on the resource and `AZURE_ACCESS_TOKEN` |
| OpenAI | User-supplied `model` and `voices`; no live voice catalog | `OPENAI_API_KEY` with audio/speech access |
| ElevenLabs | Live voices and models; selected TTS model and locale | `ELEVENLABS_API_KEY` with voices/models read and TTS access |
| Piper | Installed executable on PATH, workspace `.onnx` plus `.onnx.json`, approved model/license (`model_approved=true`) | Local only; no cloud credentials or downloads |
| Supplied WAV | Prepared local narration and exact-script timings | No provider credentials |

Azure also accepts a legacy regional Speech STS token in `SPEECH_TOKEN` with
`auth=speech_token`; this is not an Entra token. Configure Entra support on the
Speech resource separately. Key-based access does not use Entra RBAC.
For `speech.providers`, use catalog `name` values (`provider-id/voice-id`) in
audition commands; do not invent voice IDs or substitute stale catalogs.

**Production needs a prepared take.** Each scene's `config.json` selects
`takes/<take>/`, containing `narration.wav`, `meta.json` and `data.js` with JSON
`window.WORDS` and `window.CAPTIONS` timelines matching the exact locked script.
Set `speech.narration_path` to that WAV for supplied narration. Locally align or
import prepared timings and approve the audio before production. Audition
adapters do not automatically generate full narration or word timings.
The optional Azure SDK utility `make_take.py` can prepare Azure takes; it is not
a synthesis path for OpenAI, ElevenLabs or Piper. Never use rate changes to force
a locked script into its runtime.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for virtual-environment setup, focused and
full tests, offline browser integration, and contribution safety. GitHub handles
code review; no paid-service tests are required. Licensed under [MIT](LICENSE).

## Toolkit

- [core/engine.js](core/engine.js): deterministic tracks, word cues, captions and motion.
- [core/geo.js](core/geo.js): globe/map helpers; [core/shared.css](core/shared.css): shared styles.
- [example/main.js](example/main.js): a scene-authoring reference, not a finished production template.
- [capture.py](capture.py): low-level still/segment/full frame capture and media encoding.
- [make_take.py](make_take.py): Azure Speech SDK narration and word-timing utility.
- [tools_sheet.py](tools_sheet.py), [stt_check.py](stt_check.py): supplementary evidence tools.

For renderer integration consult `capture.py --help`: supported controls include
`--root`, `--output`, `--width`, `--height`, `--fps`, `--duration`, `--captions
none|static|highlight`, `--browser chromium`, `--start`, and `--seconds`. Prefer the
production CLI's versioned outputs; low-level capture needs an explicit fresh
output path. Author scenes in a dedicated directory such as `scenes/demo`, outside
generated `projects/` state. Adapt example resource paths to that location.
