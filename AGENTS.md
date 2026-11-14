# aigenvidagent Coding-Agent Entry Point

Read [.github/agents/aigenvidagent.agent.md](.github/agents/aigenvidagent.agent.md) for the
production workflow and [README.md](README.md) for setup and commands. The same
workflow is portable to coding agents outside VS Code; prompt entrypoints are
optional conveniences, not a model API requirement.

- Confirm an actually available editor model first. Never claim a model switch.
- Ask consent before installing/configuring tools or authenticating. Use project
  `.venv` for Python; optional skills/MCP require scope and location approval.
- Read `projects/<id>/brief.json` before asking only missing questions. Import
  the comprehensive template once; exports are handoff snapshots.
- Never rewrite or speed up a locked script. Exact or inclusive-range runtime includes hold.
- Offer URL-first intake: archive public HTTPS text and approve the draft script.
  Request local exports for unreadable/authenticated sources; never automate login.
- Explain provider auth/data/billing before network access; obtain consent per cloud
  provider. Use live Azure/ElevenLabs catalogs, user-supplied OpenAI voices/models,
  approved installed Piper, or supplied WAV with exact-script timings.
- Approve one storyboard option per explicit variant and its script/hook, tone,
  voice, model/provider, assets, format and captions. Approve prepared audio;
  optional video previews use scene narration, not audition samples.
- Author actual scenes; the CLI does not create a complete film for you.
- Reconfirm total variants and current source-bound plan before final rendering.
  Source edits invalidate approvals. Every revision gets a new immutable run.
- Deliver video, SRT and thumbnail for EVERY variant, even without burned captions.
- No subagents or local code reviews. GitHub handles reviews. Run deterministic
  tests/builds/media verification; never claim an unexecuted check passed.
- Respect explicit file ownership when contributors work concurrently. Do not
  revert or reformat other contributors' changes. Do not commit unless asked.

Validation: `npm test`, `npm run build -- example`, and the project-venv equivalent
of `python -m unittest discover -s tests -p "test_*.py" -v`. Enable offline browser
integration with `AIGENVIDAGENT_RUN_CAPTURE_INTEGRATION=1`; see
[CONTRIBUTING.md](CONTRIBUTING.md). No paid calls are required. Live voice/speech
checks need separate authorization. Do not install dependencies without consent.
