# Data Lens repository rules

## Product

Data Lens is an agent-native data-analysis Skill, not a browser workbench or hosted service. Keep the canonical package directly installable as a folder containing `SKILL.md`, `scripts/`, `references/`, `methods/`, `contracts/`, `assets/`, and `fixtures/`.

## Invariants

- Preserve the user's original decision question.
- Separate deterministic computation from semantic interpretation.
- A successful model request is not an adopted finding.
- Adopted findings must pass contract and evidence validation.
- Retrieval results are candidates, never the corpus denominator or source of truth.
- R, vector, and multimodal capabilities are optional and capability-gated; never auto-install them.
- Do not add a web UI, API server, database-backed workbench, provider configuration surface, RAG service, or automatic external-model retry.
- Source files are read-only. Never modify, move, rename, or delete user data.
- Never commit private inputs, runtime outputs, local paths, credentials, vector indexes, or generated databases.

## Changes

- Use UTF-8 text files.
- Add or update fixtures and tests for behavioral changes.
- Keep `SKILL.md` concise and route conditional detail to `references/`.
- Version method changes; do not silently replace the meaning of an existing method version.
- Run the Skill validator, unit tests, public-tree guard, and platform compatibility checks before release.

## Release

GitHub publication is the final step. Confirm the public tree contains only redistributable synthetic fixtures and no local runtime artifacts before pushing.
