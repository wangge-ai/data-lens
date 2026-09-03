from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_schema(value: Any, schema: dict[str, Any], location: str = "$") -> list[str]:
    """Validate the JSON Schema keywords used by the method contract."""
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _type_matches(value, expected_type):
        return [f"{location}: expected {expected_type}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{location}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value {value!r} is not in the allowed enum")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{location}: string is shorter than minLength")
        if pattern := schema.get("pattern"):
            if re.fullmatch(pattern, value) is None:
                errors.append(f"{location}: string does not match {pattern!r}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{location}: array is shorter than minItems")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{location}: array items must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, item_schema, f"{location}[{index}]"))
    if isinstance(value, dict):
        required = set(schema.get("required", []))
        for key in sorted(required - set(value)):
            errors.append(f"{location}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in sorted(set(value) - set(properties)):
                errors.append(f"{location}: unexpected property {key!r}")
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_schema(value[key], child_schema, f"{location}.{key}"))
    return errors


def validate_repository(root: Path = SKILL_ROOT) -> dict[str, Any]:
    schema = json.loads((root / "contracts" / "method-manifest.schema.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "methods" / "registry.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_manifests: set[str] = set()
    for item in registry.get("methods", []):
        method_id = item.get("method_id")
        manifest_name = item.get("manifest")
        if method_id in seen_ids:
            errors.append(f"methods/registry.json: duplicate method_id {method_id!r}")
        if manifest_name in seen_manifests:
            errors.append(f"methods/registry.json: duplicate manifest {manifest_name!r}")
        seen_ids.add(method_id)
        seen_manifests.add(manifest_name)
        manifest_path = root / "methods" / str(manifest_name)
        if not manifest_path.is_file():
            errors.append(f"methods/registry.json: missing manifest {manifest_name!r}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors.extend(f"methods/{manifest_name}: {error}" for error in validate_schema(manifest, schema))
        if manifest.get("method_id") != method_id:
            errors.append(f"methods/{manifest_name}: method_id does not match registry")
        if manifest.get("version") != item.get("version"):
            errors.append(f"methods/{manifest_name}: version does not match registry")
        entrypoint = str(manifest.get("implementation", {}).get("entrypoint", "")).strip()
        entrypoint_path = entrypoint.split(maxsplit=1)[0] if entrypoint else ""
        if entrypoint_path and not (root / entrypoint_path).is_file():
            errors.append(f"methods/{manifest_name}: implementation entrypoint does not exist: {entrypoint_path!r}")
        for fixture in manifest.get("validation", {}).get("fixtures", []):
            if not (root / str(fixture)).exists():
                errors.append(f"methods/{manifest_name}: validation fixture does not exist: {fixture!r}")
    return {
        "contract_version": "data-lens-method-governance-validation/1.0",
        "valid": not errors,
        "method_count": len(registry.get("methods", [])),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all registered method manifests against the canonical schema.")
    parser.add_argument("--root", type=Path, default=SKILL_ROOT)
    args = parser.parse_args()
    result = validate_repository(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
