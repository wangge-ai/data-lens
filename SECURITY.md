# Security policy

## Data handling

Data Lens is local-first. Source files are read-only and must not be copied into the repository. Runtime manifests, reports, vector indexes, extracted evidence, databases, credentials, local paths, and private datasets belong in ignored runtime directories.

No script may upload source material, call a remote model, or connect to a remote vector service without an explicit authorization immediately before that operation. Optional dependencies are detected, never installed automatically.

## Reporting a vulnerability

Open a GitHub security advisory for vulnerabilities involving path traversal, credential exposure, unsafe command execution, unintended network access, or private-data leakage. Do not include real secrets or private source material in an issue.

## Supported versions

Security fixes target the latest released version until a stable support policy is published.
