from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from _common import atomic_output_path, guard_cli_output
from validate_operational_outputs import validate_ooxml_structure


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def hide_validation_sheet(source: Path, output: Path, sheet_name: str = "_corpus_lens_validation") -> None:
    """Publish a copy with the canonical validation sheet hidden.

    The artifact author remains the source of workbook content. This narrow
    OOXML post-process changes only the workbook sheet-state attribute because
    the current authoring API does not expose worksheet visibility.
    """
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise ValueError(f"source workbook does not exist: {source}")
    if source == output:
        raise ValueError("output must differ from source workbook")

    with zipfile.ZipFile(source, "r") as archive:
        archive.testzip()
        workbook_xml = archive.read("xl/workbook.xml")
        root = ET.fromstring(workbook_xml)
        sheets = root.find(f"{{{MAIN_NS}}}sheets")
        if sheets is None:
            raise ValueError("xl/workbook.xml has no sheets collection")
        matches = [sheet for sheet in sheets if sheet.attrib.get("name") == sheet_name]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one validation sheet named {sheet_name!r}")
        visible_others = [
            sheet for sheet in sheets
            if sheet is not matches[0] and sheet.attrib.get("state", "visible") == "visible"
        ]
        if not visible_others:
            raise ValueError("refusing to hide the only visible worksheet")
        matches[0].set("state", "hidden")

        ET.register_namespace("", MAIN_NS)
        ET.register_namespace("r", REL_NS)
        patched_workbook_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        with atomic_output_path(output) as temporary:
            with zipfile.ZipFile(temporary, "w") as target:
                for item in archive.infolist():
                    payload = patched_workbook_xml if item.filename == "xl/workbook.xml" else archive.read(item.filename)
                    target.writestr(item, payload)

            structural_errors = validate_ooxml_structure(temporary)
            if structural_errors:
                raise ValueError("finalized workbook failed OOXML validation: " + ";".join(structural_errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Hide the canonical validation sheet in an authored workbook copy.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sheet-name", default="_corpus_lens_validation")
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.source])
    hide_validation_sheet(args.source, args.output, args.sheet_name)


if __name__ == "__main__":
    main()
