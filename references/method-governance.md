# Method governance

Each method is a versioned decision contract, not merely a prompt or function name.

## Required declaration

- stable method ID and semantic version;
- status: experimental, validated, published, deprecated, or retired;
- question types and accepted analysis units;
- input shapes and minimum eligibility checks;
- assumptions and required human gates;
- implementation runtime and entry point;
- deterministic outputs, diagnostics, and evidence needs;
- allowed claims, forbidden claims, and unsuitable scenarios;
- validation status and fixture coverage.

Method meaning cannot change in place. A change to units, eligibility, calculations, evidence requirements, or allowed claims requires a new version.

## Promotion path

```text
new problem
→ why existing methods fail
→ experimental manifest
→ synthetic success, boundary, and failure fixtures
→ deterministic and contract tests
→ de-identified real-shape trial
→ human review
→ validated release
```

A successful run produces a case note, not an automatic global method update.
