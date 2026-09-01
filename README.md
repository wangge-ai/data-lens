# Data Lens

Data Lens is an evidence-grounded data-analysis Skill for AI agents. It helps Codex, Claude Code, and WorkBuddy/CodeBuddy inspect mixed inputs, choose eligible methods, separate deterministic computation from interpretation, and deliver findings that remain traceable to source evidence.

Data Lens is a Skill, not a web application. It does not ship a browser workbench, API server, project database, provider console, or automatic external-model calls.

Maintained by **Wangge**. The intended public home is `wangge-ai/data-lens`.

## What it analyzes

- structured tables and repeated operational exports;
- articles, comments, interviews, cases, and document corpora;
- images, PDF pages, audio, video, and mixed evidence;
- time changes, comparisons, anomalies, and method corpora;
- large corpora through optional local vector retrieval;
- registered statistical methods through an optional R adapter.

## Install

Clone this repository into the user-level Skill directory used by your agent:

```text
Codex:               ~/.codex/skills/data-lens
Claude Code:         ~/.claude/skills/data-lens
WorkBuddy/CodeBuddy: ~/.codebuddy/skills/data-lens
```

The repository root is the installable Skill folder. WorkBuddy can also import the local folder through its Skill interface.

## Use

Ask the agent to use `data-lens` and provide the source location plus the decision question. The agent inventories inputs, selects a route and sampling strategy, runs deterministic helpers, validates evidence, and produces a report with a run manifest.

Useful local commands:

```bash
python scripts/data_lens.py capabilities
python scripts/data_lens.py ocr <image> --output ocr-result.json
python scripts/data_lens.py test
python scripts/data_lens.py inventory <source> --output inventory.json
python scripts/data_lens.py plan --goal "your original question" --inventory inventory.json --output plan.json
```

## Optional capabilities

The default path uses the Python standard library. Data Lens detects but never auto-installs optional runtimes such as R, Tesseract, ffprobe, Pillow, sentence-transformers, Chroma, or Qdrant clients. Capability reports distinguish installed dependencies from wired, fixture-validated, and production-ready workflows. Optional capabilities must degrade visibly when unavailable.

## Evidence rule

A model request may succeed while producing no usable analysis. A finding is adopted only after strict contract and evidence validation. If the core question has no adopted finding, the run cannot be marked complete.

## Development

```bash
python scripts/test_data_lens.py
python scripts/check_public_tree.py
python scripts/check_agent_compatibility.py
```

See `CONTRIBUTING.md` for method and fixture requirements.

## License

Apache License 2.0. See `LICENSE`.
