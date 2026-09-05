# Data Lens — Full guide

[Back to overview](../README.en.md) | [中文](guide.zh-CN.md)

Data Lens is a local deep-analysis Skill for agent hosts such as Codex and Claude Code.

It does not replace the model's judgment, and it is not another analytics website. It gives the host an executable analysis structure: establish the scope and unit first, then measure, connect evidence, investigate explanations, search for counterexamples, and deliver conclusions with clear limits and a first action.

It is designed for work that cannot be resolved by reading one file in isolation: repeated operating exports, article or interview collections, comments and chats, PDFs, images, audio, video, or project folders containing several kinds of evidence.

## Codex, Data Lens, and the combination

| Component | Primary responsibility |
|---|---|
| Codex | Understand the user's real question, interpret context, form natural explanations, handle open-ended semantic judgment, and communicate the result |
| Data Lens | Inventory material, define units and denominators, select an eligible route, run reproducible extraction and measurement, connect sources, and check counterexamples, alternatives, and claim limits |
| Codex + Data Lens | Preserve flexible reasoning for unfamiliar problems while making important numbers, evidence locations, reasoning limits, and deliverables reviewable |

The most accurate positioning is not “a different writing style for the model.” It is: **turn an agent's one-off analysis into a working result with evidence, boundaries, and a way to test what comes next.**

## Six distinctive capabilities

### 1. Start when the user does not yet know what to analyze

For a large folder, Data Lens does not promote the largest file or the most frequent words into a topic. It first separates evidence groups, versions, duplicates, and source roles, then selects a valuable question that the available material can actually support.

### 2. Define the unit before reporting numbers

A file is not necessarily a sample, and one workbook may contain many observation units. Data Lens distinguishes files, articles, orders, products, platform-days, image regions, and video segments. It records numerators, denominators, missing values, and exclusions before making a quantitative claim.

### 3. Treat depth as analytical progression, not report length

Measurement, description, time structure, subgroup differences, mechanisms, prediction, causality, and action selection remain separate. If the evidence only supports description, the result stays descriptive. Correlation is not promoted to causality without an eligible design.

### 4. Search for evidence that could overturn the current view

Data Lens preserves the strongest natural explanation first, then looks for observations it fails to explain. It only pursues an alternative when that alternative is structurally different and makes a distinguishable prediction. It can stop without inventing novelty.

### 5. Connect several sources without flattening them

A change in an operating table, a usage complaint, a PDF clause, an image detail, and a video timestamp can retain their own locations while contributing to one question. A retrieval hit helps locate evidence; it does not prove full coverage or create an independent fact.

### 6. Serve readers and reviewers separately

Readers get conclusions, evidence, alternatives, limits, and one priority action. Calculations, source locations, failures, and run records stay in separate review artifacts instead of crowding the main report.

## How deep can it analyze?

Data Lens does not collapse depth into one score. It reports which analytical layers are supported and why the next layer is available or blocked.

| Layer | Question answered | Evidence required |
|---|---|---|
| Measurement | What exactly does this field or number mean? | Defined unit, source, denominator, and missing-value rule |
| Description | What happened? | Reproducible facts, counts, and distributions |
| Time | When did it change, and were there regime shifts? | Comparable time points, windows, and consistently defined series |
| Heterogeneity | Which products, groups, channels, or content differ? | Eligible groups, sufficient observations, and overlap checks |
| Mechanism | Why might it happen, and what else could explain it? | A competing explanation, counterexamples, and distinguishable predictions |
| Prediction | Which method predicts future observations better? | No-future-leakage validation and common forecast origins |
| Causality | Did an intervention cause the change? | An eligible experiment or defensible identification design |
| Decision | What should be done under benefit, cost, and constraints? | Validated results, a utility rule, risks, and a rollback condition |

A task does not need to reach all eight layers. Real depth means knowing which layer is supported and which one still lacks evidence.

## Supported material

- CSV and XLSX files for sales, cost, refunds, advertising, inventory, and repeated operating exports;
- article collections, books, comments, interviews, case studies, research notes, and chat exports;
- PDFs, images, audio, video, and combinations of them;
- project directories containing multiple versions, sources, and nested projects.

The format determines how a source is read. The user's question determines how it should be analyzed.

## What a complete run produces

A reader-facing delivery normally includes:

1. the conclusions worth reading first;
2. the facts and sources behind them;
3. important counterexamples, alternatives, and limits;
4. one priority action;
5. signals that would support, narrow, or overturn the current view;
6. an offline HTML report, Markdown, a filterable workbook, or data attachments when useful.

When review is needed, the run can also preserve evidence locations, deterministic outputs, unreadable or failed items, and a run manifest. Those records support traceability and stay out of the reader narrative by default.

## How it works

```text
the user's question + specified material
                ↓
form a natural analysis without discarding useful native findings
                ↓
confirm scope, analytical unit, versions, denominators, and evidence capability
                ↓
run the necessary parsing, matching, deduplication, measurement, and quality checks
                ↓
find the largest explanatory gap, alternatives, counterexamples, and distinguishing evidence
                ↓
run only the additional analysis that could change the conclusion or decision
                ↓
deliver the reader report, review artifacts, and one first action
```

Small, direct tasks use a lightweight path. Large, mixed-source tasks or formal predictive and causal claims use the fuller evidence and review path only when needed. Asking for a final report or HTML does not require every analytical step; important facts, sources, and claim limits must still be checked.

## Installation

### Requirements

- A host that supports local Skills, such as Codex, Claude Code, or WorkBuddy/CodeBuddy;
- Python 3.10 or later for deterministic inventory, measurement, and validation;
- Git when installing with `git clone`, or a downloaded GitHub ZIP placed manually in the Skill directory.

### Install for Codex

Windows PowerShell:

```powershell
git clone https://github.com/wangge-ai/data-lens.git "$env:USERPROFILE\.codex\skills\data-lens"
```

macOS or Linux:

```bash
git clone https://github.com/wangge-ai/data-lens.git ~/.codex/skills/data-lens
```

Open a new Codex task after installation. To update an existing installation, run this inside the Skill directory:

```bash
git pull --ff-only
```

Optional verification:

```bash
python scripts/data_lens.py capabilities
python scripts/data_lens.py test
```

### Other hosts

```text
Claude Code:         ~/.claude/skills/data-lens
WorkBuddy/CodeBuddy: ~/.codebuddy/skills/data-lens
Project installation: <project>/.codebuddy/skills/data-lens
```

The official WorkBuddy/CodeBuddy format requires a `SKILL.md` with `name`, `description`, and instructions, and allows scripts, references, and assets beside it. Data Lens therefore keeps one canonical set of analytical instructions instead of maintaining a host-specific fork.

Before importing through the WorkBuddy UI, run:

```bash
python scripts/package_workbuddy_skill.py
```

Import the complete ZIP from `dist/`. Its archive root contains `SKILL.md`, as required by WorkBuddy's uploader, and the distribution contains only runtime capabilities and public smoke material. Copying only `SKILL.md` omits execution scripts, method references, and the report template. A structural package check proves only that the package can load and its scripts can start; real analytical behavior still requires a fresh task inside WorkBuddy.

Official reference: [WorkBuddy/CodeBuddy Skills](https://cloud.tencent.com/document/product/1831/134516).

## How to use it

After installation, you do not need a long reusable prompt. Provide the material and the question that matters.

### No preset angle

```text
Use $data-lens to analyze <folder>.
I do not have a fixed angle yet. First identify which material belongs to the same problem,
then select the most valuable direction. Return the key findings, evidence limits, and one first action.
```

### Stress-test an existing belief

```text
Use $data-lens to examine the claim that the sales decline was mainly caused by price.
Find supporting evidence, counterevidence, and alternative explanations.
If the material is insufficient, state what it cannot prove.
```

### Analyze an article collection or book

```text
Use $data-lens to analyze these articles.
Do not stop at a theme summary. Trace recurring mechanisms across documents,
look for documents that could overturn the main view, and locate the final claims in the source text.
```

### Support a business action

```text
Use $data-lens to analyze these operating tables, refund records, and customer-support notes.
I need to choose whether to change acquisition, promotions, or product mix next month.
Keep description, explanation, and causality separate, and return one priority action for now.
```

For complex work, add the audience, time range, required coverage, and preferred deliverable. The Skill selects methods from the question and available evidence.

## Dependency logic

The default core uses only the Python standard library. Optional capabilities are used only when the task needs them and the device already provides them:

| Task | Possible optional capability |
|---|---|
| Deeper XLSX reading and delivery | openpyxl |
| Image text and layout | Pillow, Tesseract, or an explicitly configured PaddleOCR model |
| PDF page rendering | Poppler |
| Audio/video metadata and frames | ffprobe and ffmpeg |
| Local transcription | an existing local Whisper checkpoint |
| Specialized statistical, temporal, or spatial methods | R and the relevant packages |
| Large tables or vector retrieval | DuckDB, embedding models, or a vector store |

Data Lens does not automatically install these components, silently switch methods when one is missing, or send source material to a remote model or vector service on its own. It degrades to what the current evidence supports or reports the missing capability. Data handling by the model service remains governed by the selected host.

## Boundaries

- A simple formula, deterministic lookup, or pure format conversion usually does not need Data Lens.
- Without sufficient evidence, it can produce a method and evidence plan, but it cannot claim a completed deep analysis.
- Correlation, clustering, predictive accuracy, and model explanations do not automatically establish causality.
- Successful OCR, readable files, and retrieval hits do not mean the material has been semantically reviewed.
- Data Lens is not a web application, background service, project database, or automatic remote-model orchestrator.

## Development and review

```bash
python scripts/data_lens.py capabilities
python scripts/data_lens.py test
python scripts/data_lens.py validate-methods
python scripts/check_public_tree.py
python scripts/check_agent_compatibility.py
```

More details: [`DESIGN.md`](../DESIGN.md) | [`CONTRIBUTING.md`](../CONTRIBUTING.md) | [`CHANGELOG.md`](../CHANGELOG.md)

## License

Apache License 2.0. See [`LICENSE`](../LICENSE).
