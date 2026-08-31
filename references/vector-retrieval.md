# Vector retrieval

Vector retrieval is a support module for candidate discovery in corpora too large for direct reading. It is not the analysis itself.

## Evidence boundary

- The index is derived, local by default, and safe to delete and rebuild.
- Every chunk retains a relative source path, source hash, and character range.
- Search scores describe index similarity, not truth, prevalence, importance, or independent evidence.
- Retrieval hits never define the corpus denominator or justify full-coverage language.
- Adopted findings must return to source evidence and pass the normal evidence validator.

## Backends

`scripts/local_vector_index.py` provides a deterministic SQLite-backed hashing-vector baseline with no third-party dependency. Optional embedding providers may be used only when installed and explicitly selected. Remote vector services require separate user authorization before any data is sent.

Use diverse queries and deterministic or stratified sampling together. A nearest-neighbor list must not replace negative-case search or coverage accounting.
