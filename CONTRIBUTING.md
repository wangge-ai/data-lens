# Contributing

Contributions are welcome when they improve a real analysis route, evidence boundary, deterministic helper, fixture, or compatibility layer.

## Method requirements

A method must declare its question types, analysis unit, input shape, eligibility checks, assumptions, human gates, outputs, diagnostics, allowed claims, forbidden claims, implementation version, and validation status. New versions must not silently change the meaning of an existing version.

## Tests and fixtures

- Use synthetic or explicitly redistributable fixtures.
- Include a success case, boundary case, and failure case for material changes.
- Test observable behavior and evidence invariants rather than exact prose.
- Do not add private paths, copied user documents, credentials, runtime databases, or generated indexes.

## Before opening a change

```bash
python scripts/test_data_lens.py
python scripts/check_public_tree.py
python scripts/check_agent_compatibility.py
```

Changes to `SKILL.md` should also pass the Agent Skill structural validator.
