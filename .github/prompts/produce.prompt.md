---
description: "Produce a versioned aigenvidagent video from canonical state, preview decisions and a newly confirmed render plan."
agent: "aigenvidagent"
argument-hint: "Project ID and any timecoded revision feedback"
---

Follow [the aigenvidagent workflow](../agents/aigenvidagent.agent.md). Read canonical state
and confirm the editor model first if missing or changed. Resolve only missing
decisions, explicitly including orientation, caption treatment, finished runtime
including hold (exact or inclusive range), tone, asset rights and total final
variants. Confirm each variant's script/hook, tone, voice, model/provider, assets,
format and captions. Match one approved storyboard option to each variant.
Explain provider auth/data/billing offline and obtain per-provider consent before
network calls. Use Azure/ElevenLabs live catalogs, OpenAI user-supplied catalog,
approved local Piper, or supplied WAV. Require prepared full narration and
exact-script timing; auditions do not supply production timings. Obtain audio
approval; offer a short video preview using prepared scene narration or record its
explicit waiver. Author and build real JavaScript scenes with the existing
toolkit. Prepare a new source-bound plan, show the actual approval ID and total
variants, and ask the user to reconfirm before rendering. Never rewrite/speed a
locked script, bypass stale approvals or overwrite an earlier run. Verify actual
encoded files with deterministic checks. Deliver video + SRT + thumbnail for
EVERY variant, including no burned captions; report paths, results and limitations.
