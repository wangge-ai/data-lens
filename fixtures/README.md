# Synthetic fixtures

All files in this directory are deliberately small synthetic fixtures created for Data Lens regression tests. They do not contain private user material, copied reports, production exports, credentials, or real performance data.

When adding a fixture, state its synthetic or redistributable provenance and keep only the minimum content needed to exercise the behavior.

`ocr/*.tsv` contains hand-authored synthetic Tesseract-shaped output for invented text, including a literal quote-token regression shape. It contains no captured screenshot or copied OCR result.

`pdf/*.txt` contains hand-authored synthetic Poppler-shaped metadata. No source PDF or rendered page from a user document is included.

`video/*.json` contains hand-authored synthetic ffprobe and Whisper-shaped output for invented media. It includes no user audio, video, frames, transcript, or model checkpoint.

`angle-discovery/*.json` contains invented candidate and evidence-card shapes for contract, evidence-gate, and bounded-synthesis regression tests.

`workbooks/*.xml` contains hand-authored OOXML fragments for an invented WPS cell-image shape. Tests assemble them into a temporary workbook; no user workbook or image is stored here.
