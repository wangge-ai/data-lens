# Changelog

## 0.9.0-dev.12 — 2026-09-05

- Repaired the two-case forward-test failures without adding a new gate: ordinary evidence-mode runs now reuse the existing E0 retention table for one advisory final-reader pass, and repeated-table guidance explicitly preserves reconciliation chains, later regime shifts, and decision-relevant data-quality exclusions.
- Added deterministic `coverage_summary` output keyed by family and analysis unit so reader-facing row counts come from computed facts rather than prose-time inference; unlike analysis units are no longer compared as adjacent coverage snapshots.
- Added a canonical run-manifest builder for reports produced outside the built-in renderer. It binds the existing six file groups, three status axes, methods and deliverables in the schema already consumed by `validate-manifest`.
- Added inventory-only signature probing, source/output collision protection, and format detection that stores classifications rather than raw header bytes.
- Completed a clean 859-file real-business rebuild with independent recomputation and desktop, mobile, keyboard, offline, and A4 rendering checks. Private inputs and run artifacts are not included in this repository.
- Hardened the existing public-tree check after a release audit found that secondary-drive local workspace paths were not covered by the previous user-home rule.
- No new baseline, frozen contract, hash gate, or release gate was added.

## 0.9.0-dev.11 — Internal snapshot

- Revalidated the current renderer on a real 18-article report, compacted the mobile reading navigation into a page-local horizontal strip while restoring 44-pixel touch targets and a three-column header summary, and added optional `--asset-root` packaging for existing relative gallery images.
- Kept the existing report structure, palette, contracts, and release checks unchanged. No new hash, baseline, frozen contract, or gate was added.

## 0.9.0-dev.10 — Internal snapshot

- Added one lightweight reader-edit pass that reuses the existing E0 retention mapping, restores omitted native findings or evidence-backed replacements, and preserves a single first stop point when the user requests one or later actions depend on its result.
- Kept incremental assessment outcomes in internal artifacts while removing `no_increment` and other evaluation-process language from rendered reader reports. No new hash, frozen contract, baseline mechanism, or gate was added.

## 0.9.0-dev.9 — Internal snapshot

- Wired Windows R discovery through explicit `--rscript`, `DATA_LENS_RSCRIPT`, `PATH`, and standard installations; `capabilities`, `probe`, and execution now agree and expose the active Python/R runtimes. Windows `C.UTF-8` inheritance is sanitized for R, with real UTF-8 path/header regression coverage.
- Added an experimental `mgcv` forward-holdout linear-versus-smooth trend competition method that can refute a Codex quantitative shape explanation while preserving predictive, mechanism, and causal boundaries.
- Added an explicit-local-model PaddleOCR backend to the existing image/PDF evidence chain, normalizing v2/v3 line polygons without claiming table structure or semantic review.
- Strengthened local Whisper handling with bounded ineligible states, probe failure ledgers, timestamp validation, quality-risk signals, and deterministic playback-review samples.
- Recast the default architecture as host-first E0 analysis plus targeted verification and at most two residual E1 candidates. Full inventory/contract/ledger orchestration is reserved for evidence or research-grade conditions rather than every ordinary analysis.
- DuckDB remains deliberately deferred because the repository and current fixtures show neither large cross-file inputs nor measured memory/query pressure; no dependency was installed.

## 0.9.0-dev.8 — Internal snapshot

- Final synthesis now receives every retained native-host finding with a stable E0 reference. Reader-report rendering requires an internal carry-forward map at the publication boundary, preventing a new Skill mechanism from silently displacing stronger raw-host findings while still allowing evidence-backed supersession.
- Added host-neutral semantic conformance probes for the five failures exposed by the Open Bandit run: post-selection causal claims, invented entity identity, significance calibration, mechanism-test directness, and E0 preservation. Dimensions are reported separately and a passing single-host probe cannot be presented as cross-host analytical stability.

## 0.9.0-dev.7 — Internal snapshot

- 增加 WorkBuddy/CodeBuddy 专用 ZIP 生成器，向分发副本注入其要求的双语简介、版本和作者元数据，同时保留能通过 Codex 校验的中性源 `SKILL.md`；兼容性检查覆盖生成结果，但不再把目录兼容冒充跨宿主实测。

### Uncertainty-aware deep data execution

- Added honest split-sample subgroup discovery and confirmation with an explicit unit-overlap audit; discovery rank can no longer stand in for estimation-sample confirmation.
- Added deterministic circular-block bootstrap intervals for paired rolling-origin loss differences. A point improvement whose interval crosses zero now keeps the baseline and reports `uncertain_difference`.
- Added offline logged-policy evaluation for logging, uniform, and explicit-probability policies with IPS, SNIPS, and optional doubly robust values, plus independent-unit effective sample size, maximum importance-weight, clustered bootstrap advantage intervals, estimator agreement, and clipping/propensity-floor sensitivity.
- Bound the new split, uncertainty, overlap, estimator, and sensitivity fields into the compiled question and finding-adoption chain while retaining execution contract 0.1 compatibility.
- Added success, non-confirmation, contamination, uncertain forecast, low-overlap, doubly robust, and sensitivity-reversal regressions.
- Completed an unseen Open Bandit cross-host blind test: raw Codex scored 89, Codex + Data Lens 91, and WorkBuddy/CodeBuddy + Data Lens 36. The Codex OPE evaluability mechanism remains only a `testable_increment`; the overall and cross-host results are `no_increment`, so this version makes no superiority claim.

## 0.9.0-dev.6 — 2026-09-04

### Executed deep-analysis layers

- Added a separate deterministic executor for subgroup heterogeneity, direct mechanism discrimination, rolling-origin forecast-model competition, and constrained expected-net-utility policy evaluation.
- Froze layer-specific bindings in the question plan, including subgroup definitions, competing mechanism predictions, forecast candidates and common origins, and action utility/constraint/fallback rules.
- Added explicit `completed`, `inconclusive`, and `unverifiable` result coverage; mixed mechanism predictions, unsupported subgroup cells, and infeasible decisions remain evidence but cannot complete a required layer.
- Added `analysis_coverage_evidence_refs` so ordinary findings can cite completed layer results without being relabelled as prediction, causal effect, or decision rule.
- Re-run saved deep-analysis results from their embedded source specification during evidence adaptation and again during ledger validation; edited result bindings or outputs are rejected.
- Added end-to-end regressions proving that heterogeneity plus mechanism plus causal coverage can close an effect plan, prediction competition can support a bounded prediction, and subgroup plus policy results can support a bounded decision rule.
- Added descriptive uncertainty for subgroup contrasts, paired loss diagnostics for forecast competitors, and scenario/threshold margins for policy evaluation.

## 0.9.0-dev.5 — 2026-09-04

### Deep data analysis kernel

- Added a decision-first question compiler that separates description, diagnosis, explanation, prediction, intervention-effect estimation, and action selection before choosing methods.
- Added independent readiness and claim boundaries for measurement, descriptive, temporal, heterogeneity, mechanism, causal, predictive, and decision layers; no overall depth score can hide a blocked layer.
- Added deterministic difference-in-differences, subgroup-difference-spread, and rolling-origin naive forecast probes with explicit non-causal and no-future-leakage boundaries.
- Added method-specific causal readiness checks and separate causal-effect, prediction, and descriptive-rule decision bases, so a method label alone cannot unlock causal claims and forecast-driven decisions do not need a fake causal design.
- Connected the question plan to finding adoption: prediction, causal-effect, and decision-rule claims now require an allowed layer, exact compiled target, compatible validation type, and derived analysis-result evidence, while legacy ordinary ledgers remain valid.
- Bound advanced result artifacts to one executed component and to layer-specific forecast, identification, or utility fields; the same completed result can no longer be relabelled across prediction, causal-effect, and decision-rule claims.
- Recompile advanced plans from their source question and current evidence before adoption; hand-written or edited permissions are rejected.
- Bound causal design evidence to the exact analysis unit, outcome, intervention, comparator, group mapping, identification strategy, and estimand, preventing an unrelated experiment record from being reused.
- Bound advanced executions to a hashed input file, data evidence references, the measured outcome field, and treatment/control values; inline or swapped-field executions cannot enter the adoption chain.
- Restricted advanced result trust to implemented result adapters and generated canonical measured claims, so unknown self-signed results or reversed free-text conclusions cannot become anchors.
- Prevented a locally valid estimate from marking the core question answered while another required analytical layer remains conditional or blocked.
- Separated layer readiness from executed result coverage; declaring a segment or mechanism ready can no longer let one causal estimate stand in for unexecuted heterogeneity or mechanism analysis.
- Prevented an unplanned mechanism hypothesis from becoming an anchor; it may remain as a bounded hypothesis until a compiled direct test produces a bound result.
- Rejected explicit causal, future-prediction, and action-directive prose under lower claim labels and required relationship findings to state their non-causal status, closing claim-label downgrade attacks.
- Applied claim-level semantic checks to every public conclusion field, preventing unsupported predictions or directives from being hidden in decision relevance, baseline, or decision-delta text.
- Added compositional semantic checks for future-time plus determinate outcome, uniform-policy plus action, and agent-plus-outcome-change wording, so omitted modal verbs do not downgrade advanced claims into patterns.
- Separated planned experiment design from executed identification checks; a randomization plan can no longer stand in for observed assignment-integrity evidence.
- Froze the planned causal estimator and canonicalized forecast horizon, cutoff, and baseline labels from structured fields, closing estimator and display-field relabelling paths.
- Replaced global causal-readiness assertions with evidence-referenced identification checks and dedicated experiment-design or identification-design evidence lanes.
- Evidence-free question compilation can route future work but cannot allow evidence-dependent claims; DiD rejects invalid time ordering and rolling-origin probes reject mixed series at one timestamp.
- Added a research-grounded operating reference covering data-generating processes, target-trial framing, identification before estimation, heterogeneous effects, refutation, and decision thresholds.

## 0.9.0-dev.4 — 2026-09-03

### Adversarial-review closure

- Added a post-reveal `rebase-increments` command that attaches the real raw Codex final baseline to the already frozen Skill ledger without accepting regenerated candidates.
- Legacy hand-filled reviews can no longer produce a validated increment; measured results must match the candidate's frozen evidence, exact window, granularity, measurement, and E0/E1 numeric predicates.
- Holdout isolation now rejects different evidence IDs that reuse the same independence group, unit, or exact source locator.
- Deep synthesis and final rendering can consume the increment assessment, exclude tagged E1 findings under `e0_only`, and publish the required no-increment notice.
- Untrusted source/candidate instructions are explicitly separated from host instructions, within-period operating-table findings must be represented in workbook reconciliation, and group sample sizes now count usable measurements.

## 0.9.0-dev.3 — 2026-09-03

### External-baseline increment attribution

- Strict paired evaluations now use the real raw Codex final answer as `external_raw_baseline` after both isolated runs finish; the Skill run's internal first pass no longer counts as proof of superiority over the raw model.
- `review_incomplete` now forces an E0-only final report and the reader-facing notice “本轮没有分析增量”; incomplete candidates cannot be promoted into management conclusions.
- Continuous operating-table analysis must retain decision-relevant within-period stages, local turning points, and leading signals found by the raw model, with time and path scored independently.

## 0.9.0-dev.2 — 2026-09-03

### Hypothesis falsification

- Added a standard-library Python runner for atomized claim scoring and direct E0/E1 experiments.
- Separated direction, time, point, path, and invalidation outcomes and deliberately omitted an overall verdict.
- Locked each component to its declared evaluation window and minimum data granularity; coarser data now returns `unverifiable` and later observations cannot repair an earlier failed window.
- Added measured incremental-review contract 0.2. Its holdout direction is derived from experiment output instead of a model-supplied label, while 0.1 remains readable for compatibility.
- Added three synthetic regressions shaped after the observed market-evaluation failures plus a direct feedback-origin comparison.
- Changed reader behavior so a completed `no_increment` result is disclosed as “本轮没有分析增量” without exposing internal audit clutter.

## 0.9.0-dev.1 — 2026-09-03

### Incremental discovery

- Added an experimental two-pass incremental-discovery engine that freezes the host's pre-engine explanation before generating alternative mechanisms.
- Added structural-change, divergent-prediction, decision-delta, generation/holdout separation, and explicit no-increment outcomes.
- Added an independent mechanism-to-test alignment review so a tangential experiment cannot validate a different core mechanism.
- Added a pre-generation routing command: a complete high-quality first pass enters adversarial augmentation; an incomplete first pass returns to full discovery. Candidate compilation rejects a mutated E0.
- Bound each candidate's declared core mechanism to its experiment target before independent semantic alignment review.
- This development version has contract and fixture coverage only. It does not claim stable superiority over a raw host until new blind forward evaluations are complete.

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
