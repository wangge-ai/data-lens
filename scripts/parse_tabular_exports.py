from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import posixpath
import re
import subprocess
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from _common import file_sha256, read_text_fallback, write_json


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def json_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def trim_rows(rows: list[list[Any]], max_rows: int | None) -> list[list[Any]]:
    cleaned: list[list[Any]] = []
    for row in rows[:max_rows] if max_rows else rows:
        values = [json_cell(value) for value in row]
        while values and values[-1] in (None, ""):
            values.pop()
        cleaned.append(values)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def candidate_sheet_role(rows: list[list[Any]]) -> str:
    sample = " ".join(str(value) for row in rows[:30] for value in row[:20] if value not in (None, ""))
    if re.search(r"评论|留言|评价|用户反馈|comment|review|voc", sample, re.I):
        return "audience_voice_candidate"
    if re.search(r"股票|证券|涨幅|跌幅|买入|卖出|代码|开盘|收盘", sample, re.I):
        return "market_record_candidate"
    if re.search(r"商品|店铺|订单|访客|客单价|主图|详情页|电商", sample, re.I):
        return "ecommerce_table_candidate"
    if re.search(r"阅读|点赞|转发|收藏|曝光|点击|转化|read|view|click", sample, re.I):
        return "performance_table_candidate"
    return "unclassified_table"


def sheet_profile(rows: list[list[Any]]) -> dict[str, Any]:
    nonempty = [value for row in rows for value in row if value not in (None, "")]
    sample = " | ".join(str(value) for value in nonempty[:30])[:1000]
    return {
        "row_count": len(rows),
        "max_columns": max((len(row) for row in rows), default=0),
        "nonempty_cells": len(nonempty),
        "text_sample": sample,
        "candidate_role": candidate_sheet_role(rows),
        "screening_status": "unreviewed",
        "analysis_role": "unassigned",
    }


def xlsx_media_by_sheet(path: Path) -> dict[str, list[str]]:
    """Map embedded image members to sheet names without claiming their semantic content."""
    result: dict[str, list[str]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
                return result
            workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
            rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rels = {node.attrib["Id"]: node.attrib["Target"] for node in rel_root.findall("r:Relationship", REL_NS)}
            relationship_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            for sheet_node in workbook_root.findall("m:sheets/m:sheet", NS):
                sheet_name = sheet_node.attrib.get("name", "Sheet")
                target = rels.get(sheet_node.attrib.get(relationship_key, ""), "").lstrip("/")
                sheet_part = target if target.startswith("xl/") else f"xl/{target}"
                sheet_rels = posixpath.join(posixpath.dirname(sheet_part), "_rels", posixpath.basename(sheet_part) + ".rels")
                media: list[str] = []
                if sheet_rels not in names:
                    result[sheet_name] = media
                    continue
                sheet_rel_root = ET.fromstring(archive.read(sheet_rels))
                for relation in sheet_rel_root.findall("r:Relationship", REL_NS):
                    if not relation.attrib.get("Type", "").endswith("/drawing"):
                        continue
                    drawing_part = posixpath.normpath(posixpath.join(posixpath.dirname(sheet_part), relation.attrib.get("Target", "")))
                    drawing_rels = posixpath.join(posixpath.dirname(drawing_part), "_rels", posixpath.basename(drawing_part) + ".rels")
                    if drawing_rels not in names:
                        continue
                    drawing_rel_root = ET.fromstring(archive.read(drawing_rels))
                    for image_relation in drawing_rel_root.findall("r:Relationship", REL_NS):
                        if image_relation.attrib.get("Type", "").endswith("/image"):
                            media_part = posixpath.normpath(posixpath.join(posixpath.dirname(drawing_part), image_relation.attrib.get("Target", "")))
                            media.append(media_part)
                result[sheet_name] = sorted(set(media))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return result
    return result


def enrich_sheets(path: Path, sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    media_map = xlsx_media_by_sheet(path) if path.suffix.lower() == ".xlsx" else {}
    enriched: list[dict[str, Any]] = []
    for sheet in sheets:
        item = dict(sheet)
        rows = item.get("rows", [])
        media = media_map.get(str(item.get("name")), [])
        item.update(sheet_profile(rows))
        item["embedded_media"] = media
        item["embedded_media_count"] = len(media)
        item["media_review_status"] = "not_extracted" if media else "none"
        enriched.append(item)
    return enriched


def read_delimited(path: Path, max_rows: int | None) -> list[dict[str, Any]]:
    text, encoding = read_text_fallback(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
    return [{"name": path.stem, "encoding": encoding, "rows": trim_rows(rows, max_rows)}]


def read_xlsx_openpyxl(path: Path, max_rows: int | None) -> list[dict[str, Any]]:
    import openpyxl  # type: ignore

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets: list[dict[str, Any]] = []
    try:
        for worksheet in workbook.worksheets:
            # Some WPS/Excel exports declare a stale A1-only dimension even
            # though sheetData contains hundreds of populated rows. Read-only
            # iteration trusts that declaration unless dimensions are reset.
            # Resetting is safe here because max_rows still bounds the scan.
            reset_dimensions = getattr(worksheet, "reset_dimensions", None)
            if callable(reset_dimensions):
                reset_dimensions()
            rows: list[list[Any]] = []
            for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
                if max_rows and row_number > max_rows:
                    break
                rows.append([json_cell(value) for value in row])
            sheets.append({"name": worksheet.title, "rows": trim_rows(rows, None)})
    finally:
        workbook.close()
    return sheets


def has_standard_xlsx_manifest(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "[Content_Types].xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def cell_col_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference.upper())
    if not letters:
        return 0
    value = 0
    for char in letters.group(1):
        value = value * 26 + ord(char) - 64
    return value - 1


def excel_serial_to_iso(value: float) -> str:
    origin = datetime(1899, 12, 30)
    result = origin + timedelta(days=value)
    return result.date().isoformat() if result.time() == datetime.min.time() else result.isoformat()


def read_xlsx_stdlib(path: Path, max_rows: int | None) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", NS):
                shared.append("".join(node.text or "" for node in item.iterfind(".//m:t", NS)))

        date_style_ids: set[int] = set()
        if "xl/styles.xml" in archive.namelist():
            style_root = ET.fromstring(archive.read("xl/styles.xml"))
            custom_formats: dict[int, str] = {}
            for node in style_root.findall("m:numFmts/m:numFmt", NS):
                custom_formats[int(node.attrib.get("numFmtId", "0"))] = node.attrib.get("formatCode", "")
            date_ids = set(range(14, 23)) | {45, 46, 47}
            cell_xfs = style_root.find("m:cellXfs", NS)
            if cell_xfs is not None:
                for index, xf in enumerate(cell_xfs):
                    num_fmt = int(xf.attrib.get("numFmtId", "0"))
                    code = custom_formats.get(num_fmt, "")
                    if num_fmt in date_ids or re.search(r"[ymdhis]", re.sub(r'\[[^\]]+\]|"[^"]*"', "", code), re.I):
                        date_style_ids.add(index)

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rels = {node.attrib["Id"]: node.attrib["Target"] for node in rel_root.findall("r:Relationship", REL_NS)}
        sheets: list[dict[str, Any]] = []
        relationship_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for sheet_node in workbook_root.findall("m:sheets/m:sheet", NS):
            relationship = rels[sheet_node.attrib[relationship_key]].lstrip("/")
            target = relationship if relationship.startswith("xl/") else f"xl/{relationship}"
            sheet_root = ET.fromstring(archive.read(target))
            rows: list[list[Any]] = []
            for row_number, row_node in enumerate(sheet_root.findall("m:sheetData/m:row", NS), start=1):
                if max_rows and row_number > max_rows:
                    break
                row: list[Any] = []
                for cell in row_node.findall("m:c", NS):
                    col = cell_col_index(cell.attrib.get("r", "A1"))
                    while len(row) <= col:
                        row.append(None)
                    cell_type = cell.attrib.get("t")
                    style_id = int(cell.attrib.get("s", "0"))
                    value_node = cell.find("m:v", NS)
                    inline = cell.find("m:is/m:t", NS)
                    value: Any = None
                    if inline is not None:
                        value = inline.text or ""
                    elif value_node is not None:
                        raw = value_node.text or ""
                        if cell_type == "s":
                            value = shared[int(raw)] if raw else ""
                        elif cell_type == "b":
                            value = raw == "1"
                        elif cell_type in ("str", "inlineStr"):
                            value = raw
                        else:
                            try:
                                number = float(raw)
                                value = excel_serial_to_iso(number) if style_id in date_style_ids else int(number) if number.is_integer() else number
                            except ValueError:
                                value = raw
                    row[col] = value
                rows.append(row)
            sheets.append({"name": sheet_node.attrib.get("name", "Sheet"), "rows": trim_rows(rows, None)})
        return sheets


def convert_xls_with_excel(source: Path, target: Path) -> None:
    if platform.system() != "Windows":
        raise RuntimeError("Legacy .xls conversion requires Microsoft Excel on Windows. Convert the file to .xlsx first.")
    ps_script = r"""
$ErrorActionPreference = 'Stop'
$sourcePath = $env:DATA_LENS_XLS_SOURCE
$targetPath = $env:DATA_LENS_XLS_TARGET
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
  $workbook = $excel.Workbooks.Open($sourcePath, 0, $true)
  try { $workbook.SaveAs($targetPath, 51) }
  finally { $workbook.Close($false) }
}
finally {
  $excel.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
"""
    process_env = os.environ.copy()
    process_env["DATA_LENS_XLS_SOURCE"] = str(source.resolve())
    process_env["DATA_LENS_XLS_TARGET"] = str(target.resolve())
    process = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=False,
        timeout=180,
        check=False,
        env=process_env,
    )
    if process.returncode != 0 or not target.exists():
        raw_detail = process.stderr or process.stdout or b""
        detail = raw_detail.decode("gb18030", errors="replace").strip()
        raise RuntimeError(f"Could not convert legacy .xls with Excel: {detail}")


def legacy_xls_cache_path(path: Path, cache_dir: Path) -> Path:
    """Address converted files by source bytes and converter contract, not by filename."""
    key = file_sha256(path)
    return cache_dir / f"{key[:24]}-excel51-v1.xlsx"


def read_workbook(path: Path, max_rows: int | None, conversion_cache: Path | None = None) -> tuple[str, list[dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        return suffix.lstrip("."), enrich_sheets(path, read_delimited(path, max_rows))
    if suffix == ".xls":
        if conversion_cache is not None:
            conversion_cache.mkdir(parents=True, exist_ok=True)
            converted = legacy_xls_cache_path(path, conversion_cache)
            if not converted.exists():
                convert_xls_with_excel(path, converted)
            try:
                return "xls-via-xlsx-cache", enrich_sheets(converted, read_xlsx_openpyxl(converted, max_rows))
            except ImportError:
                return "xls-via-xlsx-cache", enrich_sheets(converted, read_xlsx_stdlib(converted, max_rows))
        with tempfile.TemporaryDirectory(prefix="data-lens-xls-") as temp_dir:
            converted = Path(temp_dir) / f"{path.stem}.xlsx"
            convert_xls_with_excel(path, converted)
            try:
                return "xls-via-xlsx", enrich_sheets(converted, read_xlsx_openpyxl(converted, max_rows))
            except ImportError:
                return "xls-via-xlsx", enrich_sheets(converted, read_xlsx_stdlib(converted, max_rows))
    if suffix == ".xlsx":
        if has_standard_xlsx_manifest(path):
            try:
                return "xlsx", enrich_sheets(path, read_xlsx_openpyxl(path, max_rows))
            except ImportError:
                pass
        return "xlsx", enrich_sheets(path, read_xlsx_stdlib(path, max_rows))
    raise ValueError(f"Unsupported table format: {path.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse CSV, TSV, XLSX, and legacy XLS exports into UTF-8 JSON.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--conversion-cache", type=Path, help="Persistent cache directory for legacy .xls conversions.")
    args = parser.parse_args()
    files = []
    for source in args.inputs:
        if not source.exists():
            raise FileNotFoundError(str(source))
        cache_dir = args.conversion_cache or (args.output.parent / ".data-lens-cache" / "xls")
        detected_format, sheets = read_workbook(source, args.max_rows, cache_dir)
        files.append({"path": str(source.resolve()), "format": detected_format, "sheets": sheets})
    payload = {
        "table_parse_version": "1.3",
        "legacy_xls_cache": str((args.conversion_cache or (args.output.parent / ".data-lens-cache" / "xls")).resolve()),
        "coverage_boundary": "每个工作表都必须单独分配 analysis_role；candidate_role 只来自关键词，嵌入图片清单只证明存在媒体，不等于完成OCR或语义审核。",
        "files": files,
    }
    write_json(args.output, payload)
    print(json.dumps({"output": str(args.output), "files": len(files), "sheets": sum(len(item["sheets"]) for item in files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
