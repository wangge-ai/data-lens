# Data Lens

[中文](README.md) | English

Data Lens is a general-purpose deep-analysis Skill. Give it spreadsheets, articles, interviews, PDFs, images, or an entire project folder. It helps the host agent find the question that matters, connect evidence across sources, and turn the result into a report people can read and act on.

It is useful when:

- you have too many files and do not know where to start;
- tables and written material need to be understood together;
- one explanation looks convincing, but you want to check alternatives and exceptions;
- you need a next action, not just a summary.

## Start in 30 seconds

Clone the repository into the Codex skills directory:

```powershell
git clone https://github.com/wangge-ai/data-lens.git "$env:USERPROFILE\.codex\skills\data-lens"
```

On macOS or Linux:

```bash
git clone https://github.com/wangge-ai/data-lens.git ~/.codex/skills/data-lens
```

Open a new task and say:

```text
Use $data-lens to analyze <folder>.
I do not have a fixed angle yet. Find the most important question first,
then give me the key findings and the first action to take.
```

There is no separate long prompt to copy. `SKILL.md` contains the working method. You only need to say where the material is and what decision or question you care about.

## What it does

| When you are facing | Data Lens will |
|---|---|
| No clear analysis angle | Compare possible questions and start with the one that matters most and can be answered from the available material |
| Many files with unclear relationships | Separate sources, versions, duplicates, and evidence roles before combining anything |
| One explanation that sounds right | Keep facts separate from interpretation, look for counterexamples and alternatives, and leave uncertainty visible |
| Too many recommendations | Reduce them to one priority action, with a metric, a stopping condition, and a signal that would change the decision |

Data Lens does not make a report longer just to make it look deeper. If the material only supports description, it stays descriptive. If fields conflict, data is missing, or a file cannot be read, the report says so directly.

## Supported material

- CSV and XLSX files for sales, cost, refunds, operations, or repeated exports;
- articles, comments, interviews, case studies, research notes, and chat exports;
- PDFs, images, audio, video, and mixed evidence;
- project folders containing multiple versions, sources, and file types.

File format determines how something is read. Your question determines how it should be analyzed.

## Example requests

### A large folder with no preset angle

```text
Use $data-lens to review this folder. First identify what is here and which files
are actually about the same problem. Then choose the most valuable question to analyze.
```

### A business decision

```text
Use $data-lens to analyze these operating tables, refund records, and support notes.
I need to decide whether to change acquisition, promotions, or product mix next month.
Show me the evidence and the first action to take.
```

### Stress-test an existing belief

```text
Use $data-lens to check the claim that the sales decline was mainly caused by price.
Find supporting evidence, counterexamples, and other explanations, and tell me what data is still missing.
```

For a complex task, you can also name the audience, time range, required coverage, and preferred deliverable. The Skill can infer the rest from the material.

## What you get

A standard report usually contains:

1. the conclusions worth reading first;
2. the facts and sources behind them;
3. alternatives, important exceptions, and limits;
4. the first action to take;
5. signals that would support or overturn the current view.

The main report is written for readers. File locations, calculations, and run records are kept separate and shown only when review is needed.

## Install on other hosts

The repository root is the complete Skill folder:

```text
Codex:               ~/.codex/skills/data-lens
Claude Code:         ~/.claude/skills/data-lens
WorkBuddy/CodeBuddy: ~/.codebuddy/skills/data-lens
```

Update an existing installation with:

```bash
git pull --ff-only
```

Before importing through the WorkBuddy UI, build the complete ZIP:

```bash
python scripts/package_workbuddy_skill.py
```

Import the generated file from `dist/`. Copying only `SKILL.md` leaves out the scripts, method references, and report template.

Data Lens is a local Skill executed by the host agent, not a standalone web application. Support for OCR, local models, and individual file formats depends on the tools available on the device and in the host.

## Preview

The three screenshots below use fully synthetic data. They show the report format and contain no real business information.

### Conclusions first, evidence next

![Data Lens synthetic business report overview](docs/images/data-lens-report-desktop.png)

### Every finding keeps alternatives, limits, and a next step

![Data Lens synthetic report finding card](docs/images/data-lens-report-detail.png)

### Readable on mobile too

<img src="docs/images/data-lens-report-mobile.png" width="390" alt="Data Lens synthetic report mobile view">

## For developers

Regular users do not need the command line. For development and review:

```bash
python scripts/data_lens.py capabilities
python scripts/data_lens.py test
python scripts/data_lens.py validate-methods
python scripts/check_public_tree.py
python scripts/check_agent_compatibility.py
```

The default path uses only the Python standard library. R, Poppler, Tesseract, PaddleOCR, ffprobe, Pillow, Whisper, DuckDB, and vector search components are optional. They are not installed or called silently.

More details: [`DESIGN.md`](DESIGN.md) | [`CONTRIBUTING.md`](CONTRIBUTING.md) | [`CHANGELOG.md`](CHANGELOG.md)

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
