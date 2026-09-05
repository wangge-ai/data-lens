from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT_FILES = {
    Path("LICENSE"),
    Path("NOTICE"),
    Path("SKILL.md"),
    Path("VERSION"),
    Path("pyproject.toml"),
}
PACKAGE_ROOT_DIRS = {
    "assets",
    "contracts",
    "fixtures",
    "methods",
    "references",
    "scripts",
}
PACKAGE_EXTRA_FILES = {
    Path("evals/README.md"),
    Path("evals/semantic-conformance/probes-public.json"),
}
PACKAGE_EXCLUDED_FILES = {
    Path("evals/semantic-conformance/expectations-private.json"),
    Path("evals/semantic-conformance/responses-pass.json"),
    Path("evals/semantic-conformance/responses-fail.json"),
}


def _split_skill(skill_text: str) -> tuple[list[str], str]:
    if not skill_text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    parts = skill_text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("SKILL.md frontmatter is not closed")
    return parts[1].strip().splitlines(), parts[2].lstrip("\n")


def build_workbuddy_skill_text(skill_text: str) -> str:
    """Return the canonical Skill unchanged after checking its frontmatter."""
    errors = validate_workbuddy_skill_text(skill_text)
    if errors:
        raise ValueError("; ".join(errors))
    return skill_text


def validate_workbuddy_skill_text(skill_text: str) -> list[str]:
    errors: list[str] = []
    frontmatter, _ = _split_skill(skill_text)
    joined = "\n".join(frontmatter)
    required = ("name", "description")
    for field in required:
        if not re.search(rf"(?m)^{field}:\s*\S.+$", joined):
            errors.append(f"WorkBuddy frontmatter is missing {field}")
    return errors


def _is_package_file(relative: Path) -> bool:
    if relative in PACKAGE_EXCLUDED_FILES:
        return False
    if relative in PACKAGE_ROOT_FILES or relative in PACKAGE_EXTRA_FILES:
        return True
    return bool(relative.parts and relative.parts[0] in PACKAGE_ROOT_DIRS)


def package_workbuddy_skill(root: Path, output: Path, *, force: bool = False) -> dict[str, object]:
    root = root.resolve()
    output = output.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    packaged_skill = build_workbuddy_skill_text(
        (root / "SKILL.md").read_text(encoding="utf-8")
    )
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    source_files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and _is_package_file(path.relative_to(root))
        and path.suffix.lower() != ".pyc"
    ]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_files):
            relative = path.relative_to(root)
            archive_name = PurePosixPath("skills", "data-lens", *relative.parts).as_posix()
            if relative == Path("SKILL.md"):
                archive.writestr(archive_name, packaged_skill.encode("utf-8"))
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
