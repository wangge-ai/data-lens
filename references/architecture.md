# Data Lens architecture

Data Lens is a filesystem Skill executed by its host agent. The host owns conversation, permissions, tool access, and user interaction. Data Lens owns analysis routing, deterministic helpers, method contracts, evidence boundaries, and deliverable validation.

```text
SKILL.md
  → inventory and route
  → method eligibility
  → deterministic execution (Python or optional R)
  → optional retrieval and multimodal preparation
  → semantic candidate generation by the host agent
  → contract validation
  → evidence validation
  → adoption ledger
  → reader deliverables + run manifest
```

The architecture deliberately excludes a web UI, API server, background queue, project database, provider console, and automatic remote-model calls.

## Source of truth

- Source bytes remain read-only and authoritative.
- Deterministic artifacts are reproducible conveniences bound to source hashes and method versions.
- Vector indexes are rebuildable candidate locators.
- Semantic codings are candidates until contract and evidence validation pass.
- The adoption ledger is the only source of truth for which findings may appear as accepted analysis.

## Capability tiers

1. Core: standard-library inventory, sampling, evidence, validation, and reporting.
2. Optional Python: tabular, statistical, imaging, embedding, or export libraries detected at runtime.
3. Optional R: registered scripts through the R adapter.
4. Optional system tools: ffprobe, PDF renderers, OCR, and transcription tools.
5. Remote capabilities: disabled unless the user authorizes the exact external action.
