# Generation record

- Date: 2026-09-03
- Source selection: all 72 dated MHTML files from 2026-05-06 through 2026-08-27.
- Host model policy: both candidates used the host's configured default model without a per-candidate override.
- Isolation: candidates ran in separate projectless tasks and were forbidden to read one another, prior reports, run directories, or the rubric.
- Base task: [`../prompts/kazike.txt`](../prompts/kazike.txt)
- Candidate A difference: explicitly used no Skill.
- Candidate B difference: invoked the installed Data Lens 0.8.1 Skill and followed its reader-output rule.
- Blind mapping: A/B identity was not given to the evaluator and was revealed only after `evaluation.md` and `scores.json` were saved.

The full article bodies are not redistributed. Both candidate reports and the blind evaluation are preserved without substantive editing.

Post-evaluation note: the final 0.8.1 Skill added rules for preserving strong native-host findings and capturing same-article counterevidence. The published candidate and score remain those of the pre-adjustment snapshot; they were not regenerated after the rules changed.
