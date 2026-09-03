from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from select_samples import _is_relative_to, discover_project_anchors, project_bucket


CODE_SUFFIXES = {".py", ".r", ".sh", ".ps1", ".rb", ".go", ".rs", ".java", ".ts"}
TABLE_SUFFIXES = {".csv", ".tsv", ".xls", ".xlsx", ".parquet"}
VISUAL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".exe", ".db", ".sqlite"}


def artifact_role(path: Path, project_root: Path) -> str:
    relative = path.relative_to(project_root)
    parts = [part.lower() for part in relative.parts]
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == "plugin.json" and path.parent.name.lower() in {".codebuddy-plugin", ".codex-plugin"}:
        return "project_manifest"
    if len(relative.parts) == 1 and name in {"skill.md", "pyproject.toml", "package.json", "cargo.toml", "go.mod"}:
        return "project_entrypoint"
    if name in {"skill.md", "blade.md"}:
        return "skill_entrypoint"
    if any(part in {"tests", "test", "evals", "evaluation"} for part in parts) or name.startswith("test_"):
        return "test_or_evaluation"
    if any(token in str(relative).lower() for token in ("fixture", "example", "sample", "样例", "示例")):
        return "sample_or_fixture"
    if any(token in str(relative).lower() for token in ("report", "output", "result", "报告", "结果", "产出")):
        return "report_or_output"
    if suffix in CODE_SUFFIXES:
        return "executable_code"
    if suffix in TABLE_SUFFIXES:
        return "tabular_asset"
    if suffix in VISUAL_SUFFIXES:
        return "visual_asset"
    if suffix in ARCHIVE_SUFFIXES or name.endswith(".min.js"):
        return "dependency_or_archive"
    if suffix in {".md", ".txt", ".docx", ".pdf", ".html"}:
        return "documentation"
    return "other"


def declared_skills(project_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    manifests = [
        project_root / ".codebuddy-plugin" / "plugin.json",
        project_root / ".codex-plugin" / "plugin.json",
    ]
    manifest_path = next((path for path in manifests if path.exists()), None)
    if manifest_path is None:
        return None, []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": str(manifest_path), "parse_status": "failed", "error": type(exc).__name__}, []
    profiles = []
    for value in manifest.get("skills", []) if isinstance(manifest.get("skills"), list) else []:
        declared = str(value)
        skill_root = (project_root / declared).resolve()
        files = [path for path in skill_root.rglob("*") if path.is_file()] if skill_root.exists() else []
        roles = Counter(artifact_role(path, skill_root) for path in files) if files else Counter()
        profiles.append(
            {
                "declared_path": declared,
                "resolved_path": str(skill_root),
                "directory_exists": skill_root.is_dir(),
                "entrypoint_exists": (skill_root / "SKILL.md").is_file(),
                "file_count": len(files),
                "role_counts": dict(sorted(roles.items())),
                "code_backed": roles.get("executable_code", 0) > 0,
                "sample_backed": roles.get("sample_or_fixture", 0) > 0,
                "test_backed": roles.get("test_or_evaluation", 0) > 0,
                "output_backed": roles.get("report_or_output", 0) > 0,
            }
        )
    manifest_profile = {
        "path": str(manifest_path),
        "parse_status": "parsed",
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "declared_skill_count": len(profiles),
    }
    return manifest_profile, profiles


def profile(inventory: dict[str, Any]) -> dict[str, Any]:
    anchors = discover_project_anchors(inventory)
    canonical_paths = [
        Path(str(item.get("path"))) for item in inventory.get("files", [])
        if item.get("canonical", True) and item.get("path")
    ]
    projects = []
    for anchor in anchors:
        files = []
        for path in canonical_paths:
            containing = [candidate for candidate in anchors if _is_relative_to(path, candidate)]
            if containing and max(containing, key=lambda value: len(value.parts)).resolve() == anchor.resolve():
                files.append(path)
        if not files:
            continue
        label, _ = project_bucket(files[0], inventory, anchors)
        role_counts = Counter(artifact_role(path, anchor) for path in files)
        component_counts = Counter()
        for path in files:
            _, component = project_bucket(path, inventory, anchors)
            if component:
                component_counts[component.split("::", 1)[-1]] += 1
        manifest, skills = declared_skills(anchor)
        projects.append(
            {
                "project": label or anchor.name,
                "root": str(anchor),
                "canonical_file_count": len(files),
                "role_counts": dict(sorted(role_counts.items())),
                "component_counts": dict(sorted(component_counts.items())),
                "manifest": manifest,
                "declared_skills": skills,
                "declared_skill_summary": {
                    "count": len(skills),
                    "entrypoints_present": sum(1 for item in skills if item["entrypoint_exists"]),
                    "code_backed": sum(1 for item in skills if item["code_backed"]),
                    "sample_backed": sum(1 for item in skills if item["sample_backed"]),
                    "test_backed": sum(1 for item in skills if item["test_backed"]),
                    "output_backed": sum(1 for item in skills if item["output_backed"]),
                },
                "maturity_boundary": "入口、代码、样例、测试和输出是不同实现层；任何一层存在都不能单独证明结果已被采用或产生业务效果。",
            }
        )
    return {
        "contract_version": "data-lens-nested-project-profile/1.0",
        "project_count": len(projects),
        "projects": projects,
        "coverage_boundary": "只识别带明确项目标记的嵌套目录。未带标记的资料家族仍由mixed_corpus语义审核决定；项目文件数和实现层计数不是质量或效果证据。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect nested projects and separate entrypoints, code, samples, tests, outputs, dependencies, and archives.")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.inventory])
    result = profile(load_json(args.inventory))
    write_json(args.output, result)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "projects": result["project_count"],
        "declared_skills": sum(item["declared_skill_summary"]["count"] for item in result["projects"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
