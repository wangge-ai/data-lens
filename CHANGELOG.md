# Changelog

## 0.8.1 — 2026-09-03

### General deep analysis

- Reframed Data Lens around problem discovery, cross-source synthesis, competing explanations, structural constraints, stage changes, and testable decisions rather than spreadsheet-first analysis.
- Added an experimental cognitive-engine router and contradiction-analysis method. The engine can abstain and must preserve the host's ordinary explanation before proposing a structurally different candidate.
- Added evidence-gated deep finding compilation and bounded synthesis while keeping internal contracts and ledgers out of the reader-facing report.
- Added scope classification for mixed directories, ChatLab/WeChat export profiling, and nested project coverage.

### Public evaluation

- Added `evals/` with exact base prompts, a blind scoring rubric, full candidate outputs, evaluator reports, and reveal mappings.
- In two same-condition article-corpus comparisons, Data Lens 0.8.1 scored 88.5 vs 83.5 and 89 vs 81. These are positive repeated signals on article corpora, not evidence of universal superiority.
- Kept the earlier market-case loss in the README so the public record does not contain only wins.
- Updated the method rules after evaluation to preserve strong native-host findings and to distinguish body-text counts from markup or container-character counts.

### Reliability and compatibility

- Added atomic JSON/CSV and optional-method publication, source/output collision protection, explicit timeout records, and safer local index replacement.
- Extended workbook, PDF, OCR, video, transcription, sampling, run-manifest, and operational-output validation.
- Kept Python standard-library execution as the default and optional runtimes as explicit, non-installing capabilities.
- Preserved Codex, Claude Code, and WorkBuddy/CodeBuddy compatibility.

### Project boundary

- Data Lens remains an agent-native filesystem Skill. This repository contains no Web UI, API server, background service, project database, or provider console.

### Known limits

- Cognitive-engine methods remain experimental and execute through the host agent; unit tests validate contracts and refusal cases, not semantic superiority.
- The current public same-condition comparison covers two article corpora. A private 509-file mixed-business baseline exists locally, but no comparable Data Lens 0.8.1 rerun is published.
