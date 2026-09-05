# Data Lens architecture

Data Lens is a filesystem Skill executed by its host agent. The host owns conversation, permissions, tool access, and user interaction. Data Lens owns analysis routing, optional cognitive-engine routing, deterministic helpers, method contracts, evidence boundaries, and deliverable validation.

```text
host natural analysis E0
  → targeted high-impact verification
  → at most two structurally different E1 candidates around the largest residual
  → direct discriminating measurement when available
  → preserve E0 and absorb only supported increments
  → escalate to inventory/contracts/ledgers only when scale, modality, claim strength, risk, or formal evaluation requires them
```

The architecture deliberately excludes a web UI, API server, background queue, project database, provider console, and automatic remote-model calls.

The default path is intentionally host-first. Small readable inputs do not pay the orchestration cost of the complete research chain. Evidence mode adds deterministic coverage and locators for large, repeated, cross-source, or multimodal inputs. Research grade retains the complete contracts and independent review for advanced claims, formal evaluations, and release boundaries. These are execution levels, not claim-strength shortcuts.

## Analysis and cognition layers

The primary route defines the object, analysis unit, and evidence lanes. For non-simple quantitative decision problems, the deep-analysis question compiler then separates measurement, descriptive, temporal, heterogeneity, mechanism, causal, predictive, and decision layers before method eligibility. Each layer keeps its own readiness and claim boundary; there is no aggregate depth label. Without verified evidence cards it can still route work, but it cannot allow evidence-dependent advanced claims.

The compiled plan also freezes the predictive, causal, and decision targets. Advanced findings must match that target and carry a compatible validation type plus verified derived `analysis_result` evidence. The result artifact echoes an `analysis_binding` for one executed component and the layer-specific forecast, identification, or utility design; the adoption compiler compares it field by field. The plan therefore controls the adoption chain instead of remaining advisory; plan readiness alone is never treated as an observed result, and one result cannot be relabelled across analytical layers.

The cognitive layer begins only after observable phenomena and scope are available. It helps the host widen the hypothesis space, identify a high-leverage question, and propose evidence that would distinguish explanations; it never upgrades claim strength by itself.

The cognitive router may abstain. Its first experimental engine, structural-contradiction analysis, tests whether visible problems are coupled by a shared constraint, feedback loop, heterogeneous response, or stage-dependent shift. Outputs remain semantic candidates and enter the existing deep-finding workflow. This adds a reasoning layer without creating a new primary route or a parallel adoption system.

An engine contributes only when it reconstructs the problem, identifies a concrete coupling carrier, produces a prediction that differs from the ordinary explanation, or states an observable priority switch. Structural importance and immediate action priority are carried as separate judgments so an easy experiment is not mistaken for the underlying mechanism.

Method provenance is internal by default. Reader artifacts show concrete phenomena, mechanisms, exceptions, actions, and validation signals rather than engine names, theoretical quotations, or specialist vocabulary.

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

## Capability readiness

The capability report separates dependency presence from workflow readiness:

- `installed`: the module or executable is visible in the current process;
- `wired`: Data Lens has a bounded entry point for it;
- `fixture_validated`: synthetic success, boundary, and failure behavior is covered;
- `production_ready`: a de-identified real-shape trial and required human review have completed.

The legacy-compatible `available` field means only `installed`. It must not be used by itself to claim that a capability is wired or production-ready.
