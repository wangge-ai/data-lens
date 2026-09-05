from __future__ import annotations

import argparse
import json
import re
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent.parent
WORKBUDDY_FIELDS = {
    "display_name": "Data Lens 深度分析",
    "display_name_en": "Data Lens",
    "description_zh": "从表格、文本、图片及混合资料中识别关键问题、跨来源关系、竞争解释和可验证行动。",
    "description_en": (
        "Evidence-grounded deep analysis across tables, text, images, and mixed corpora, "
        "with competing explanations and testable actions."
    ),
}
EXCLUDED_PARTS = {".git", ".github", "dist", "__pycache__", ".pytest_cache"}
EVALUATOR_ONLY_FILES = {
    Path("evals/semantic-conformance/expectations-private.json"),
    Path("evals/semantic-conformance/responses-pass.json"),
    Path("evals/semantic-conformance/responses-fail.json"),
    Path("tests/test_semantic_conformance.py"),
}


def _split_skill(skill_text: str) -> tuple[list[str], str]:
    if not skill_text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    parts = skill_text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("SKILL.md frontmatter is not closed")
    return parts[1].strip().splitlines(), parts[2].lstrip("\n")


def build_workbuddy_skill_text(skill_text: str, version: str, author: str) -> str:
    frontmatter, body = _split_skill(skill_text)
    generated_names = {*WORKBUDDY_FIELDS, "version", "author"}
    retained = [
        line
        for line in frontmatter
        if not any(re.match(rf"^{re.escape(name)}\s*:", line) for name in generated_names)
    ]
    for name, value in WORKBUDDY_FIELDS.items():
        retained.append(f"{name}: {json.dumps(value, ensure_ascii=False)}")
    retained.append(f"version: {json.dumps(version)}")
    retained.append(f"author: {json.dumps(author, ensure_ascii=False)}")
    return "---\n" + "\n".join(retained) + "\n---\n\n" + body


def validate_workbuddy_skill_text(skill_text: str, expected_version: str) -> list[str]:
    errors: list[str] = []
    frontmatter, _ = _split_skill(skill_text)
    joined = "\n".join(frontmatter)
    required = ("name", "description", "description_zh", "description_en", "version", "author")
    for field in required:
        if not re.search(rf"(?m)^{field}:\s*\S.+$", joined):
            errors.append(f"generated WorkBuddy frontmatter is missing {field}")
    version = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)[\"']?\s*$", joined)
    if version and version.group(1) != expected_version:
        errors.append("generated WorkBuddy version does not match VERSION")
    return errors


def _project_author(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    authors = project.get("authors", [])
    if not authors or not authors[0].get("name"):
        raise ValueError("pyproject.toml must declare a project author")
    return str(authors[0]["name"])


def package_workbuddy_skill(root: Path, output: Path, *, force: bool = False) -> dict[str, object]:
    root = root.resolve()
    output = output.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    generated_skill = build_workbuddy_skill_text(
        (root / "SKILL.md").read_text(encoding="utf-8"),
        version,
        _project_author(root),
    )
    validation_errors = validate_workbuddy_skill_text(generated_skill, version)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    source_files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
        and path.relative_to(root) not in EVALUATOR_ONLY_FILES
        and path.suffix.lower() != ".pyc"
    ]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_files):
            relative = path.relative_to(root)
            archive_name = PurePosixPath("skills", "data-lens", *relative.parts).as_posix()
            if relative == Path("SKILL.md"):
                archive.writestr(archive_name, generated_skill.encode("utf-8"))
            else:
                archive.write(path, archive_name)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        required_entry = "skills/data-lens/SKILL.md"
        if required_entry not in names:
            raise RuntimeError(f"package is missing {required_entry}")
    return {
        "output": str(output),
        "version": version,
        "file_count": len(source_files),
        "skill_entry": "skills/data-lens/SKILL.md",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a WorkBuddy-compatible Data Lens Skill ZIP")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output = args.output or ROOT / "dist" / f"data-lens-{version}-workbuddy.zip"
    print(json.dumps(package_workbuddy_skill(ROOT, output, force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
