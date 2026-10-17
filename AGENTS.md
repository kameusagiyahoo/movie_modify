# Movie Modify agent development guidance

Movie Modify is a local-first video editor. Preserve the separation between
media adapters, cut analysis, 360-degree viewing, editing UI and renderer.
Never upload family footage, audio or transcripts to a third-party API.

## Japanese prose

The upstream yomiyasu Agent Skill is vendored in
\`.agents/skills/yomiyasu/SKILL.md\` for use by Codex.

When requested to revise Japanese writing, or while drafting significant
Japanese README, UI help, specifications or PR text, explicitly load
\`/yomiyasu\` or \`$yomiyasu:yomiyasu\` and follow its checks.
Review the output before committing. Preserve technical facts, quantities,
negations, conditions and whether a feature is implemented or planned.

This skill is developer-only. It does not automatically change video edits,
subtitles or transcripts, and does not require a runtime cloud API.
For ordinary code edits, skip writing refinement unless it is relevant.
Keep project-specific rules outside the vendor directory.
