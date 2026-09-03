# Generation record

- Date: 2026-09-03
- Source selection: 18 canonical dated articles; same-title HTML, Markdown, and MHTML files counted once.
- Host model policy: both candidates used the host's configured default model without a per-candidate override.
- Isolation: candidates ran in separate projectless tasks and were forbidden to read one another, prior reports, run directories, or the rubric.
- Base task: [`../prompts/xiaobei.txt`](../prompts/xiaobei.txt)
- Candidate A difference: invoked the installed Data Lens 0.8.1 Skill and followed its reader-output rule.
- Candidate B difference: explicitly used no Skill.
- Blind mapping: A/B identity was not given to the evaluator and was revealed only after `evaluation.md` and `scores.json` were saved.

The full article bodies are not redistributed. The candidate outputs are preserved exactly except that one local source path in candidate B was replaced with `<SOURCE_DIR>` before publication.

Post-evaluation note: the final 0.8.1 Skill added rules for preserving strong native-host findings and separating body-text counts from markup or container-character counts. The published candidate and score remain those of the pre-adjustment snapshot; they were not regenerated after the rules changed.
