# Synthetic fixtures

All files in this directory are deliberately small synthetic fixtures created for Data Lens regression tests. They do not contain private user material, copied reports, production exports, credentials, or real performance data.

When adding a fixture, state its synthetic or redistributable provenance and keep only the minimum content needed to exercise the behavior.

`ocr/*.tsv` contains hand-authored synthetic Tesseract-shaped output for invented text, including a literal quote-token regression shape. `ocr/paddle-*.json` contains invented PaddleOCR v2/v3-shaped line, confidence, and polygon output. They contain no captured screenshot or copied OCR result.

`pdf/*.txt` contains hand-authored synthetic Poppler-shaped metadata. No source PDF or rendered page from a user document is included.

`video/*.json` contains hand-authored synthetic ffprobe and Whisper-shaped output for invented media. It includes no user audio, video, frames, transcript, or model checkpoint.

`angle-discovery/*.json` contains invented candidate and evidence-card shapes for contract, evidence-gate, and bounded-synthesis regression tests.

`incremental-discovery/*` contains invented Chinese course-analysis evidence, E0/E1 candidates with frozen executable tests, legacy and measured review records, and two tiny source files. It exercises baseline preservation, post-reveal external rebasing, structurally distinct predictions, source-level holdout separation, exact window/measurement/predicate binding, direct mechanism-test alignment, and explicit no-increment behavior; it contains no real course or business data.

`hypothesis-experiment/*` contains invented time-series and group-comparison values. Three cases reproduce only the shapes of previously observed evaluation failures: insufficient intraday granularity, a composite claim whose dimensions disagree, and post-window observations that must not repair a failed forecast. The values are synthetic and contain no private market corpus.

`deep-analysis-question/*` contains an invented store-month profit question and one synthetic evidence card. It exercises separate readiness for measurement, temporal, heterogeneity, mechanism, causal, predictive, and decision layers without storing user business data.

`deep-findings/synthetic-experiment-spec.json` and `deep-findings/synthetic-experiment-result.json` are an invented executable specification/result pair used only to verify that an advanced claim cannot cite raw article or table evidence as if it were an experiment output.

`workbooks/*.xml` contains hand-authored OOXML fragments for an invented WPS cell-image shape. Tests assemble them into a temporary workbook; no user workbook or image is stored here.
