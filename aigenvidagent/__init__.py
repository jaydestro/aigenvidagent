"""Local, approval-gated video production workflows.

Run with the workspace .venv interpreter using ``python -m aigenvidagent``.
``initialize launch --answers answers.json`` imports partial answers without
prompting; plain initialize interviews on a TTY, otherwise saves a resumable
draft. Paths are workspace-relative. Export refuses existing destinations.

The coding agent must author scene/index.html, main.js, config.json and a
prepared takes/<take>/{narration.wav,meta.json,data.js} before rendering.
Set speech.narration_path to that WAV for supplied/pre-recorded narration.
Full-length narration synthesis is deliberately not automatic.

For Speech comparisons, configure speech.resource_id/region/locale and provide
SPK or a regional Speech STS token in SPEECH_TOKEN at runtime. Explicitly grant
consents.speech_samples, run voices --refresh, then preview --voices NAME ... .
Approve a sample by importing speech.voice and speech.sample_approval with
approved=true, voice and the returned manifest_path. Listen before approving.
No credentials, provider/model inference or optional installs are performed.

After storyboard approval and script lock, produce --prepare writes a bound
plan. Only produce --approve ID runs the four-node Agent Framework graph.
Approval IDs are single-use, including failed attempts. Every run gets a fresh
out/<project>/<run>/variants/<variant>/video.mp4 and a staged source workspace.
Verification checks media integrity, not visual quality or spoken claims.
"""
