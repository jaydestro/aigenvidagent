# [Project ID] Video Brief

Fill in this form, or ask aigenvidagent to interview you. Leave unknown fields as
`[unresolved]`, not guessed defaults. Write `none` or `not applicable` explicitly.
The agent maps the completed form to the brief schema for your confirmation and
imports it into `projects/<id>/brief.json`, the single source of truth. Native
Markdown imports use exactly one fenced JSON object, not this prose form.

## Editor Model (First)
- Available editor model selected and confirmed by user: [unresolved]
- Needed capabilities: reasoning, scene coding, long context, image inspection
- If the editor's model list is unavailable: [ask user; never invent a switch]

## Goal
- Project ID and title: [unresolved]
- Audience, venue/channel and intended publication: [unresolved]
- Single takeaway and call to action: [unresolved]
- Deliverables and language/locale: [unresolved]
- Success criteria: [unresolved]

## Source URL (Optional)
- Just give me a URL and I will create a video based on it.
- Public HTTPS URL: [unresolved or none]
- Archive readable text with `initialize demo --url URL`; verify claims and
	approve the unlocked draft script before production.
- For unreadable/authenticated sources: [permitted local text export; no automated login]

## Format and Finished Runtime
- Orientation (choose explicitly): [portrait / landscape / optional square]
- Width x height, fps and safe areas: [unresolved]
- Duration mode: [exact / range]
- Exact FINISHED duration in seconds (exact mode only): [unresolved]
- Inclusive minimum and maximum FINISHED seconds (range mode only): [e.g. 90, 110]
- Final silent hold seconds (included in the duration above): [unresolved]
- Opening silence/transitions budget (also included): [unresolved]
- Burned-in captions: [yes / no]
- If yes: [static phrase text / spoken-word highlighting]
- If no: [none]; every variant still includes SRT + thumbnail.
- Audio: [narration only / narration plus licensed music]

## Tone
- Choose: [professional / executive / developer / casual friendly / custom]
- Custom delivery, warmth, pacing and examples: [unresolved or not applicable]
- Tone must not alter the locked words or force unnatural delivery.

## Locked Script
Status: [draft awaiting approval / locked by user]

[Full paragraph 1, exact punctuation and words]

[Full paragraph 2]

Do not change, shorten, reorder, rewrite or speed up a locked script. If it
cannot fit naturally in the finished runtime after the final hold, stop and ask
me to edit the words or approve a duration change. Do not silently fix it.

## Pronunciation and Speech
- Written term -> spoken pronunciation: [unresolved or none]
- Locale/accent and pronunciation references: [unresolved]
- Connected natural sentences; pauses only between sentences.
- Any pronunciation changes affect speech only, never caption wording.

## Voice Discovery and Auditions
- Route: [Azure / OpenAI / ElevenLabs / local Piper / supplied WAV]
- Provider configuration ID, model and locale (no credentials): [unresolved]
- Offline `providers PROJECT` auth/data/billing explanation shown: [pending]
- Consent for EACH cloud provider before discovery/auditions: [pending / approved / declined]
- Catalog date and IDs: [Azure/ElevenLabs live; OpenAI user-supplied; Piper local]
- Contextual shortlist and reasons: [from the selected provider catalog]
- Audio audition paths and selection: [pending]
- Selected provider/voice name(s): [pending audition approval]
- Prepared WAV, metadata and exact-script word/caption timing paths: [pending]
- Supplied narration: set `speech.narration_path` to the prepared take WAV.
- Auditions do not generate full takes or word timings. Use local alignment or
	imported timing; `make_take.py` is an optional Azure SDK utility only.

## Storyboard and Required Content
- Required sections in order: [unresolved]
- Exact on-screen labels: [unresolved]
- Diagram nodes, directions, relation labels and boundaries: [unresolved or none]
- Architecture/documentation URLs and access permission: [unresolved or none]

| Script paragraph/section | Audience must see | Exact labels/relations | Asset/source | Motion and timing budget | Avoid |
|---|---|---|---|---|---|
| [1] | [unresolved] | [unresolved] | [unresolved] | [unresolved] | [unresolved] |

## Visual Direction
- Style, palette, typography and visual references: [unresolved]
- Purposeful motion and scene transitions: [unresolved]
- Readability, viewing distance and caption safe area: [unresolved]
- Key labels readable for at least 1.5 seconds where feasible; no overlaps.

## Brand
- Exact product/company spellings: [unresolved]
- Official logo/brand document URLs and access permission: [unresolved or none]
- Palette/fonts, clear space and approved treatments: [unresolved]
- Never distort, recolor or combine logos without the owner's approval.

## Assets and Rights
List every image, screen capture, video clip, music track and data source.
Unknown rights block use. Do not include passwords, signed URLs or tokens.

| Asset ID/type | Local path or source URL | Intended beat/use | License/permission evidence and publication scope | Attribution | Trim in/out seconds | Native audio / redaction |
|---|---|---|---|---|---|---|
| [unresolved] | [unresolved] | [unresolved] | [unresolved] | [unresolved] | [not applicable if still] | [unresolved] |

- Music: [none / licensed track with evidence above]
- Music trim, looping permission, fades, mix level and ducking: [unresolved or none]
- Private capture/download authorization: [unresolved or none]
- Never fabricate these UI screens, metrics, customer data or diagrams: [unresolved]

## Claims and Boundaries
| Exact claim | Authoritative source | Verification status / owner |
|---|---|---|
| [unresolved or none] | [unresolved] | [pending] |

- Excluded products, competitors, topics and unsupported claims: [unresolved]
- Privacy: IDs, emails, credentials and personal data to remove: [unresolved]
- Approved synthetic replacements/redaction and publication scope: [unresolved]
- Confidential material and permitted processors/tools: [unresolved]

## Optional Tool Consent
No installation or authentication is implied by completing this form.

| Skill/MCP/tool | Exact capability and source/package | Network/data access | Workspace or user scope and exact path | Proposed command | User approval |
|---|---|---|---|---|---|
| [none unless requested] | [unresolved] | [unresolved] | [unresolved] | [unresolved] | [pending] |

- Python dependencies belong in this project's `.venv`, not global Python.
- No model API, Foundry deployment or MCP server is needed for local orchestration.

## Preview Decisions
- Storyboard shown and approved for source revision: [pending]
- One storyboard option per final variant, with its explicit customizations: [pending]
- Audio auditions heard and approved for source revision: [pending]
- Optional short video preview: [requested / explicitly waived / undecided]
- Video preview start/seconds (e.g. 0 / 8) and output path: [unresolved]
- Video preview decision and source revision: [pending or explicit waiver]

## Final Variants (Reconfirm Before Rendering)
- TOTAL number of final videos, not preview clips: [unresolved]
- Ask and approve every variant's script/hook, tone, voice, model/provider,
  assets, format and captions, even if unchanged. Do not multiply combinations.

| Variant ID | Provider/model/voice | Orientation/dimensions | Caption mode (none/static/highlight) | Tone | Script/hook, assets and other approved differences |
|---|---|---|---|---|---|
| [unresolved] | [from provider catalog] | [unresolved] | [unresolved] | [unresolved] | [base or specifics] |

- Record supported overrides in `variants[].customizations`; keep additional
	decisions in `differences`/`customizations.notes` and implement them in scenes
	and prepared takes. A changed narration script requires a new approved brief.

- Prepared approval ID and source digest (from CLI, never invented): [pending]
- User reconfirmation of this exact total and prepared plan: [pending]
- Editing any source invalidates approvals; prepare and approve again.

## Versioning and Delivery
- Canonical state: `projects/<id>/brief.json`
- New immutable run outputs: `out/<id>/<run>/variants/<id>/video.mp4`
- Every variant also includes `captions.srt` and `thumbnail.jpg`, even with no burned captions.
- Snapshot sources and allocate a new run before revisions; never overwrite.
- Exported briefs are versioned handoff snapshots, not the live brief.

## Done Checklist
- [ ] Finished runtime meets exact/range request INCLUDING final hold
- [ ] Correct variant count, dimensions, fps and caption treatment
- [ ] One approved storyboard option, SRT and thumbnail for EVERY variant
- [ ] Spoken words, captions and requested subtitles preserve the locked script
- [ ] Natural connected speech and correct pronunciation, without hidden speed changes
- [ ] Every required section, label, relation and approved asset appears
- [ ] Licensed music/footage trimmed and mixed correctly; attribution included
- [ ] No personal data, secrets, missing assets, overlaps or cropped labels
- [ ] Official logos and brand treatments checked on rendered frames
- [ ] Actual encoded runtime/frame count, audio and full decode checked
- [ ] Verification evidence saved; unavailable checks explicitly reported

## Confirmed Decisions and Feedback
| Area | Confirmed decision | Source revision / evidence |
|---|---|---|
| [unresolved] | [unresolved] | [pending] |

| Run/timecode | Requested change | Preserve | Status/evidence |
|---|---|---|---|
| [none yet] | | | |
