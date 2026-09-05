# Data Lens

[中文](README.md) | English | [Full guide](docs/guide.en.md)

![Data Lens connects spreadsheets, books and other sources into traceable findings](docs/images/data-lens-hero.png)

**Turn a pile of material into a judgment you can check.**

Data Lens is a local analysis Skill for Codex, Claude Code and WorkBuddy/CodeBuddy. Bring operating tables, articles, a book or mixed sources. Explore what happened, what might explain it, and what to test next.

The model handles understanding and reasoning. The Skill helps it check numbers, connect sources and look for counterexamples—without losing useful initial findings. It is not another model or a hosted analytics app.

## Go beyond the summary

![Six capabilities: Scope, Measure, Explain, Challenge, Connect and Act](docs/images/data-lens-capabilities.png)

Start without a preset angle, or stress-test a belief you already have. **Depth means pursuing the important question—not making the report longer—and knowing where the evidence stops.**

## What to bring

| Material | A useful question |
|---|---|
| Operating tables, refunds and support notes | Orders grew. Why didn't profit follow? |
| An article collection or a book | Which idea recurs, and which passages contradict it? |
| Reviews, interviews and chats | Where do people struggle? Do groups differ? |
| PDFs, images and file versions | Which sources concern the same issue, and where do they conflict? |

Audio and video are also supported when the host and local tools can read them. Format determines how to read; the question determines how to analyze.

## What you get

![Delivery concept: findings linked to sources, with alternatives and a next step](docs/images/data-lens-delivery.png)

A readable report with **key findings, source evidence, alternatives, limits and one priority action**. Markdown, offline HTML or data attachments when useful; calculations and failure records stay separate for review.

*These are AI-generated concept illustrations made with the built-in image tool, not execution screenshots or a fixed report template.*

## Install and start

Requires a host that supports local Skills and **Python 3.10+**. Install the whole repository, not just `SKILL.md`.

<details>
<summary>Codex · Windows PowerShell</summary>

```powershell
git clone https://github.com/wangge-ai/data-lens.git "$env:USERPROFILE\.codex\skills\data-lens"
```

</details>

<details>
<summary>Codex · macOS / Linux</summary>

```bash
git clone https://github.com/wangge-ai/data-lens.git ~/.codex/skills/data-lens
```

</details>

<details>
<summary>Claude Code / WorkBuddy / CodeBuddy</summary>

Place the complete repository in the host's Skill directory:

- Claude Code: `~/.claude/skills/data-lens`
- WorkBuddy/CodeBuddy: `~/.codebuddy/skills/data-lens`

For a WorkBuddy UI import, run from the repository root:

```bash
python scripts/package_workbuddy_skill.py
```

Import the complete ZIP in `dist/`. [Detailed installation](docs/guide.en.md#installation)

</details>

Open a new task after installation and ask:

```text
Use $data-lens to analyze this material.
Go beyond a summary: identify the important question, verify key numbers and passages,
and actively seek counterevidence. Tell me what is supported, what is missing,
and the one action worth taking first.
```

[More prompt examples](docs/guide.en.md#how-to-use-it) | [Updates and dependencies](docs/guide.en.md#dependency-logic)

## Know the limits

Simple lookups and formulas usually do not need this Skill. Weak evidence stays uncertain; correlation and predictive accuracy do not establish causality. Asking for a final report or HTML does not require the full analytical pipeline.

The core uses Python's standard library. OCR, audio/video and specialized statistics may need optional tools, which are not installed automatically. The Skill does not upload material to a remote analysis service on its own; the host's data-handling rules still apply.

## Explore further

[Full capability and usage guide](docs/guide.en.md) · [Design](DESIGN.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

<details>
<summary>Development and self-tests</summary>

```bash
python scripts/data_lens.py capabilities
python scripts/data_lens.py test
python scripts/data_lens.py validate-methods
python scripts/check_public_tree.py
python scripts/check_agent_compatibility.py
```

</details>

Apache License 2.0 · [LICENSE](LICENSE)
