from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

from package_workbuddy_skill import build_workbuddy_skill_text, validate_workbuddy_skill_text


def validate() -> list[str]:
    errors: list[str] = []
    text = SKILL.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append("SKILL.md must start with YAML frontmatter")
        return errors
    parts = text.split("---", 2)
    if len(parts) < 3:
        errors.append("SKILL.md frontmatter is not closed")
        return errors
    frontmatter = parts[1]
    if not re.search(r"(?m)^name:\s*data-lens\s*$", frontmatter):
        errors.append("frontmatter name must be data-lens")
    description = re.search(r"(?m)^description:\s*(.+)$", frontmatter)
    if not description or len(description.group(1).strip(" \"'")) < 40:
        errors.append("frontmatter description is missing or too weak for discovery")
    packaged_workbuddy_skill = build_workbuddy_skill_text(text)
    errors.extend(validate_workbuddy_skill_text(packaged_workbuddy_skill))
    for forbidden in ("allowed-tools:", "context:", "agent:", "model:"):
        if forbidden in frontmatter:
            errors.append(f"platform-specific canonical frontmatter field is not allowed: {forbidden}")
    for target in LINK_RE.findall(text):
        if "://" in target or target.startswith("#"):
            continue
        if re.match(r"^[A-Za-z]:[/\\]", target) or target.startswith("/"):
            errors.append(f"resource link must be relative: {target}")
            continue
        if not (ROOT / target).is_file():
            errors.append(f"linked resource is missing: {target}")
    metadata = ROOT / "agents" / "openai.yaml"
    if not metadata.is_file():
        errors.append("Codex metadata is missing")
    else:
        yaml = metadata.read_text(encoding="utf-8")
        if "$data-lens" not in yaml:
            errors.append("agents/openai.yaml default_prompt must mention $data-lens")
    for required in (
        "references/agent-compatibility.md",
        "references/optional-r.md",
        "references/vector-retrieval.md",
        "references/multimodal-evidence.md",
    ):
        if not (ROOT / required).is_file():
            errors.append(f"compatibility resource is missing: {required}")
    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print("Codex, Claude Code, and WorkBuddy/CodeBuddy canonical Skill compatibility checks passed")


if __name__ == "__main__":
    main()
