# Data Lens Design

Data Lens is an agent-native evidence-grounded deep-analysis Skill. The host agent owns the user's actual decision question, task authorization, semantic interpretation, human confirmation, and user-facing explanation. Data Lens owns deterministic inventory, evidence routing, optional cognitive-engine routing, bounded extraction, evidence contracts, method manifests, validation, and reproducible reader artifacts.

## Processing model

The normal flow is:

```text
user question + supplied inputs
  -> inventory and scope
  -> deterministic facts and evidence units
  -> decision-relevant problem map
  -> optional cognitive engine
  -> candidate angles/findings
  -> adoption and human gates
  -> reader artifact
  -> independent validation + canonical run_manifest.json
```

Request success, analysis completion, artifact health, and release eligibility are separate states. A confirmed analysis can coexist with a failed artifact; a repaired artifact is published as a new version derived from the locked deterministic analysis, not by rewriting history.

## Cognitive layer

Primary routes define what is being analyzed and which professional methods are eligible. Cognitive engines are optional reasoning aids used after observable facts and scope exist. They expand candidate mechanisms, locate a potentially higher-leverage question, and propose evidence or action that could distinguish explanations. They do not create facts, establish causality, or bypass the existing finding workflow.

The first experimental engine checks whether several visible problems are genuinely coupled by a shared constraint, feedback loop, heterogeneous response, or stage-dependent driver. It can abstain or reject the structural interpretation. Reader artifacts translate any useful result into plain decision language and do not require theoretical quotations or terminology.

## Safety and reproducibility

- Source inputs are read-only. Every public file-writing CLI rejects resolved source/output collisions.
- JSON, CSV, and narrow OOXML post-processing use same-directory atomic replacement.
- A run directory has one writer at a time. Data Lens does not provide concurrent writers, a queue, or a project database.
- `run_manifest.json` binds sources, implementations, deterministic artifacts, ledgers, and deliverables by path and SHA-256. Reader artifacts omit private paths and full hashes.
- External tools have explicit time budgets. Timeout is a recorded failure, never an automatic retry; another attempt uses a new empty output directory unless a route explicitly implements resume.
- Dates are accepted only when they form a real calendar date. Spreadsheet adapters map versioned normalized headers and fail on missing or ambiguous required fields.

## Workbook boundary

Artifact authoring is separate from validation. Reader-facing Excel files use real table objects with non-empty unique headers. The hidden `_corpus_lens_validation` sheet records workbook locators and JSON Pointers, while the validator independently reads both sides and recomputes equality. OOXML package relationships, table references, table columns, and worksheet headers are checked before release. A narrow OOXML finalizer may set the validation sheet to hidden when the authoring API lacks visibility support; it does not rewrite business cells.

## Non-goals

Data Lens is not a web application, browser workbench, provider console, API service, background queue, or automatic remote-model orchestrator. It does not infer causality from descriptive changes, claim semantic review from extraction success, or restore the retired UI/provider architecture.
