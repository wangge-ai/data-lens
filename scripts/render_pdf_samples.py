from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import file_sha256, write_json


def page_indices(count: int, maximum: int) -> list[int]:
    if count <= maximum:
        return list(range(count))
    if maximum <= 1:
        return [0]
    return sorted({round(index * (count - 1) / (maximum - 1)) for index in range(maximum)})


def render(paths: list[Path], output_dir: Path, maximum: int) -> dict:
    try:
        import pypdfium2 as pdfium  # type: ignore
        from PIL import Image, ImageDraw, ImageOps  # type: ignore
    except ImportError as exc:
        raise RuntimeError("render_pdf_samples requires pypdfium2 and Pillow") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for source in paths:
        if not source.is_file() or source.suffix.lower() != ".pdf":
            raise ValueError(f"not a readable PDF: {source}")
        document = pdfium.PdfDocument(str(source))
        total = len(document)
        selected = page_indices(total, maximum)
        thumbs = []
        for page_index in selected:
            image = document[page_index].render(scale=1.35).to_pil().convert("RGB")
            image.thumbnail((520, 740), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (560, 800), "white")
            canvas.paste(image, ((560 - image.width) // 2, 40))
            ImageDraw.Draw(canvas).text((16, 12), f"Page {page_index + 1}/{total}", fill="#111827")
            thumbs.append(ImageOps.expand(canvas, border=1, fill="#d1d5db"))
        columns = 2
        rows = (len(thumbs) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * 562, rows * 802), "#f3f4f6")
        for index, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((index % columns) * 562, (index // columns) * 802))
        output = output_dir / f"{source.stem}_contact_sheet.jpg"
        sheet.save(output, quality=88, optimize=True)
        records.append({
            "origin_path": str(source.resolve()), "origin_sha256": file_sha256(source),
            "page_count": total, "rendered_pages": [value + 1 for value in selected],
            "contact_sheet_path": str(output.resolve()), "contact_sheet_sha256": file_sha256(output),
            "review_status": "pixel_readable_not_semantically_reviewed",
        })
    payload = {"pdf_sample_version": "1.0", "records": records}
    write_json(output_dir / "manifest.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Render evenly spaced, origin-hashed PDF page samples for semantic review.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=6)
    args = parser.parse_args()
    result = render(args.inputs, args.output_dir, args.max_pages)
    print(json.dumps({"output": str((args.output_dir / "manifest.json").resolve()), "pdfs": len(result["records"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
