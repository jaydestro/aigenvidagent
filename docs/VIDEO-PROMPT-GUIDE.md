# Creating a product video with an AI agent

## 1. Set up a single prompt file

Keep all instructions in one document the agent reads at the start of every round. Put in it:

- the script;
- the rules;
- settled decisions;
- asset sources;
- a feedback log.

Update this file as decisions are made.

## 2. Define the goal and format

- Audience, venue, and the one takeaway viewers should leave with.
- Length range, for example 75–80 seconds.
- Aspect ratio, resolution and frame rate.
- Captions on or off. Caption text must match the narration exactly.
- Audio: narration only, or narration with music.
- Voice: a named voice, or a request for a few samples to choose from.

## 3. Lock the script

- Write the full narration, paragraph by paragraph.
- State: "Do not change, shorten, reorder or rewrite these words."
- List pronunciation notes separately, so the voice can be adjusted without changing the written words or captions. For example, "10x" is read as "ten times".
- Add a speech rule: "Every sentence must flow naturally, as a person would say it. Pauses only between sentences."

## 4. Write the storyboard

One row per paragraph:

| Paragraph | Audience should see | Avoid |
|---|---|---|
| 1 | | |

Give each point a single, clear visual idea. Visuals should change on the spoken words.

## 5. Set the visual direction

- Style, palette, typography and motion feel.
- Continuous, purposeful motion; nothing should look like a static slide.
- Text readable at viewing distance. Key labels stay on screen for at least 1.5 seconds.
- Ask for three to five visual directions before committing to one.

## 6. Specify brand, assets and data

- **Names:** the exact spelling of every product and company name.
- **Logos:** official logos only, with the download source. Follow each owner's rules: clear space, no recoloring, no combined lockups without approval. Check the visible size of the logo, not the size of the file.
- **Screen captures:** the real product screens to capture.
- **Data:** real data where viewers may notice, for example actual locations on a map.
- **Never fabricate:** the metrics, customer data and UI that must not be invented.

## 7. Set boundaries

- **Exclusions:** products, competitors and features that must never appear.
- **Claims:** list every number or claim in the script. Keep each one word for word, and mark it for verification before publishing.
- **Privacy:** hide account IDs, emails and keys in every frame, and use synthetic users and data in diagrams.

## 8. Require versioning

- Save each round as a new numbered version in its own folder.
- Never overwrite earlier versions.
- Snapshot the source before editing.

## 9. Define "done"

- [ ] Runtime within the target range
- [ ] Spoken words and captions match the script word for word
- [ ] No unnatural pauses inside sentences
- [ ] Key labels readable for at least 1.5 s; no overlapping elements
- [ ] Official logos only, correctly sized
- [ ] File plays cleanly from start to finish

## 10. Refine in rounds

1. Give feedback with timecodes, one item per line. For example: "0:16 – title too close to the icons."
2. Say what to keep as well as what to change.
3. To change the script, edit it in the prompt file and paste the full new version.
4. Ask the agent to confirm each item against the delivered file: the runtime, a script match, and stills of the changed moments.
5. Check that each fix did not create a new problem, for example an awkward pause added to correct a pronunciation.
6. If the pacing feels rushed, lengthen the video rather than speeding it up.
7. Record every settled decision in a "Confirmed decisions" table, and every round in the feedback log.

## 11. Get the most from the agent

- Use a design skill to set the audience, commit to one coherent style, and hold a quality bar.
- Split independent work (voice, data, rendering) across parallel subagents. Give each one a complete brief, a list of the files it may change, and the never-overwrite rule.
- Require the agent to check its own work: view frames from each scene, transcribe the narration, and compare it with the script.
- Use a high-capability model for planning, design and code; lighter models are fine for rendering and checks.
- Choose the voice from short samples and lock it. Have the agent reject recordings with unnatural pauses or the wrong length.

## 12. Prompt template

```markdown
# [Project] video prompt

## Goal
[Length range] video for [audience/venue]. Takeaway: [one sentence].

## Format
- [16:9, 1920x1080, 30 fps]
- Captions: [yes/no]; must match narration exactly
- Audio: [narration only / with music]
- Voice: [name], calm and natural

## Locked script (do not change, shorten, reorder or rewrite)
[Paragraph 1]

[Paragraph 2]

## Pronunciation (speech only)
- [term] is read as "[pronunciation]"

## Speech rule
Every sentence flows naturally; pauses only between sentences.

## Storyboard
| Paragraph | Audience should see | Avoid |
|---|---|---|

## Visual direction
- Style: [...]
- Continuous motion; no static slides
- Key labels on screen ≥ 1.5 s

## Brand
- Names: [exact spellings]
- Logos: official only, from [URLs]; follow owner rules

## Assets and data
- Capture: [...]
- Data source: [...]
- Never fabricate: [...]

## Exclusions
[...]

## Claims to verify
- [...]

## Privacy
Hide IDs, emails and keys; synthetic data in diagrams.

## Versioning
New numbered version each round; never overwrite.

## Done checklist
- [ ] Runtime in range
- [ ] Script and captions match word for word
- [ ] Natural speech, no in-sentence pauses
- [ ] Labels readable ≥ 1.5 s, no overlaps
- [ ] Official logos, correctly sized
- [ ] Plays cleanly

## Confirmed decisions
| Area | Decision |
|---|---|

## Feedback log
| Round | Feedback | Status |
|---|---|---|
```
