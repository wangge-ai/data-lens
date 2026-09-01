# Multimodal evidence

Multimodal analysis starts by creating locatable evidence, not by asking a model for an impression of a folder.

| Medium | Minimum locator | Processing states |
|---|---|---|
| Image | file hash plus pixel region or full-frame declaration | metadata, pixel-readable, OCR, semantically reviewed |
| PDF | file hash and page number; region when needed | metadata, rendered, OCR/text extracted, semantically reviewed |
| Audio | file hash and start/end time | metadata, transcribed, speaker-reviewed, semantically reviewed |
| Video | file hash and start/end time or frame timestamp | metadata, frames extracted, transcribed, semantically reviewed |

`scripts/multimodal_inventory.py` records the initial metadata and review requirements. Existing PDF rendering and visual review helpers can then prepare bounded evidence.

For local image OCR, run `python scripts/data_lens.py ocr <image> --output <result.json>`. The experimental adapter runs one to three explicitly bounded Tesseract PSM candidates (default 6 and 11), retains raw candidate text, word and line confidence, pixel boxes, source hash, and engine parameters, and labels any deterministic preference as `algorithmic_candidate_only`. Missing requested language data is a hard eligibility failure. OCR never sets semantic review or finding adoption to complete.

For PDF evidence, run `python scripts/data_lens.py pdf <file.pdf> --output-dir <empty-directory>`. The adapter uses Poppler to render at most six evenly distributed pages by default; use `--pages 1,3-5` when the question requires explicit pages. Each record binds the source PDF hash and 1-based page number to the rendered PNG hash and, when requested, the OCR JSON hash. The output directory must be empty so prior evidence is not overwritten. Render and OCR failures remain in `failure_ledger` with `retry_status: not_retried`; successful pages do not erase failed pages or imply complete document coverage.

For video frames, run `python scripts/data_lens.py video <file> --output-dir <empty-directory>`. The default is at most six timestamps distributed across the full duration, not the first six seconds or first six shots. `--timestamps 0.5,10,42.25` selects explicit seconds. Each frame binds the source hash and millisecond timestamp to a frame hash. Failed timestamps remain in the same non-retried ledger.

For optional local transcription, run `python scripts/data_lens.py transcribe <file> --output-dir <empty-directory> --model-checkpoint <local.pt>`. The checkpoint must already exist as a local file and its hash is recorded; passing a model name is not supported, so the adapter does not trigger Whisper's model downloader. The default clip budget is 20 minutes. Media beyond that budget requires explicit `--start-ms` and `--end-ms`, and the selected clip must remain within the budget. The raw Whisper JSON and normalized segment/word timestamps are retained. Transcript completion is still `speaker_review_status: not_reviewed`, `semantic_review_status: not_reviewed`, and `adoption_status: not_adopted`.

File existence, image count, OCR text, transcript text, or pixel readability does not equal semantic review. Claims about layout, objects, speech, sequence, tone, or interaction require the corresponding reviewed evidence and locator.
