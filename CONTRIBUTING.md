# Contributing

Keep changes focused, preserve existing work, and add tests for changed behavior.
Discuss new dependencies, provider access and larger scope changes before adding
them. Do not commit generated projects, source archives, previews, media, private
assets or credentials. Third-party assets and voice models retain their own
licenses; the repository's [MIT license](LICENSE) does not grant those rights.

## Setup

Use Python 3.11+, Node 22+, ffmpeg/ffprobe on PATH and bundled Playwright Chromium.
See [platform prerequisites](README.md#local-setup). Ask before installing tools,
dependencies, models or optional integrations; never authenticate automatically.
No virtual-environment activation is needed.

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
.\.venv\Scripts\python.exe -m playwright install chromium
```

macOS/Linux:

```sh
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
npm ci
./.venv/bin/python -m playwright install chromium
```

On Linux, use `playwright install --with-deps chromium` when approved system
dependency installation is needed. Main requirements include renderer packages.
The optional [requirements-azure.txt](requirements-azure.txt) is only for Azure
SDK utilities, not required for offline tests or REST auditions.

## Tests

Run the JavaScript suite and example build on every platform:

```sh
npm test
npm run build -- example
```

Run the full Python suite, including offline browser capture and local Agent
Framework production. No credentials, paid services or model API are required.

Windows PowerShell:

```powershell
$env:AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
Remove-Item Env:AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION
```

macOS/Linux:

```sh
AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1 ./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

For focused checks, choose the affected suite or test:

```sh
npm run test:engine
npm run test:build
./.venv/bin/python -m unittest discover -s tests -p 'test_cli.py' -v
./.venv/bin/python -m unittest discover -s tests -p 'test_renderer.py' -v
AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1 ./.venv/bin/python -m unittest discover -s tests -p 'test_integration.py' -v
./.venv/bin/python -m unittest discover -s tests -p 'test_cli.py' -k duration -v
```

On Windows, use `.\.venv\Scripts\python.exe` and set the integration flag as
above. Renderer integration runs when ffmpeg/ffprobe and Chromium are available;
there is no separate renderer environment flag. Check skipped-test messages:
a missing prerequisite is not a successful browser/render check.
[CI](.github/workflows/tests.yml) enables offline integration on all three OSes.
The Linux job uses Ubuntu 24.04 to match the pinned Playwright version's
supported browser dependencies; Python 3.11 remains the CI baseline.

## Safety and Scope

Preserve locked scripts, inclusive finished-runtime bounds and final holds.
Keep one approved storyboard per explicit variant, source-bound approvals,
immutable runs, and video/SRT/thumbnail delivery even without burned captions.
Validate actual encoded media for renderer changes. Update docs when CLI,
configuration or provider contracts change.

Use synthetic local fixtures and mocked service responses. Never make paid
tests a contribution requirement. Live provider discovery or synthesis requires
separate consent per provider after explaining auth, data transfer and billing.
Do not add personal subscription defaults, owner identities, workstation paths
or credentials. Do not automate login to private sources.

GitHub handles code review. Do not run local code-review agents or delegate
reviews; run deterministic tests, builds and focused checks. Report commands,
results and skipped checks in the pull request. Do not commit or push on another
contributor's behalf without authorization.
