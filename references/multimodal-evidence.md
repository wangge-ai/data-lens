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

File existence, image count, OCR text, transcript text, or pixel readability does not equal semantic review. Claims about layout, objects, speech, sequence, tone, or interaction require the corresponding reviewed evidence and locator.
