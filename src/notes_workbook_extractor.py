from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class NotesWorkbookExtractionError(Exception):
    pass


def _ns(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _safe_source_path(path: Path) -> str:
    return path.name if path.is_absolute() else path.as_posix()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def raw_notes_workbook_contract_json_bytes(contract: Dict[str, Any]) -> bytes:
    return _canonical_json_bytes(contract)


@dataclass(frozen=True)
class CellData:
    coordinate: str
    row: int
    col_letter: str
    col_index: int
    cell_type: str
    style_id: int
    value_text: str
    formula: Optional[str]
    has_cached_value: bool


def _split_cell_ref(cell_ref: str) -> Tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_ref)
    if not match:
        raise NotesWorkbookExtractionError(f"Unsupported cell reference: {cell_ref}")
    return match.group(1), int(match.group(2))


def _column_to_number(column: str) -> int:
    value = 0
    for ch in column:
        value = value * 26 + (ord(ch.upper()) - ord("A") + 1)
    return value


def _number_to_column(number: int) -> str:
    chars: List[str] = []
    n = number
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def _expand_range(range_ref: str) -> List[str]:
    if ":" not in range_ref:
        return [range_ref]

    start, end = range_ref.split(":", 1)
    sc, sr = _split_cell_ref(start)
    ec, er = _split_cell_ref(end)

    out: List[str] = []
    for row in range(sr, er + 1):
        for col in range(_column_to_number(sc), _column_to_number(ec) + 1):
            out.append(f"{_number_to_column(col)}{row}")
    return out


def _load_mapping_policy(mapping_path: Path) -> Dict[str, Any]:
    if not mapping_path.exists():
        raise NotesWorkbookExtractionError(f"Mapping file does not exist: {mapping_path}")
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotesWorkbookExtractionError(f"Invalid mapping JSON: {mapping_path}") from exc
    if not isinstance(payload, dict):
        raise NotesWorkbookExtractionError("Mapping JSON must be an object")
    return payload


def _authoritative_ranges_by_sheet(mapping_policy: Dict[str, Any]) -> Dict[str, Set[str]]:
    notes = mapping_policy.get("canonicalNotes")
    if not isinstance(notes, list):
        return {}

    out: Dict[str, Set[str]] = {}
    for item in notes:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if not isinstance(source, dict):
            continue
        source_type = source.get("sourceType")
        if source_type not in {"workbook_range", "workbook_multi_range"}:
            continue

        if source_type == "workbook_range":
            sheet = source.get("sheet")
            table_shapes = source.get("tableShapes")
            if not isinstance(sheet, str) or not isinstance(table_shapes, list):
                continue
            for shape in table_shapes:
                if not isinstance(shape, dict):
                    continue
                range_ref = shape.get("range")
                if isinstance(range_ref, str):
                    out.setdefault(sheet, set()).update(_expand_range(range_ref))
        else:
            ranges = source.get("worksheetRanges")
            if not isinstance(ranges, list):
                continue
            for entry in ranges:
                if not isinstance(entry, dict):
                    continue
                sheet = entry.get("sheet")
                range_ref = entry.get("range")
                if isinstance(sheet, str) and isinstance(range_ref, str):
                    out.setdefault(sheet, set()).update(_expand_range(range_ref))

    return out


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    shared_path = "xl/sharedStrings.xml"
    if shared_path not in zf.namelist():
        return []

    root = ET.fromstring(zf.read(shared_path))
    values: List[str] = []
    for si in root.findall(_ns("si")):
        text = "".join((t.text or "") for t in si.findall(f".//{_ns('t')}"))
        values.append(text)
    return values


def _read_cell_text(cell: ET.Element, shared_strings: List[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        text = "".join((t.text or "") for t in cell.findall(f".//{_ns('t')}"))
        return text

    value_node = cell.find(_ns("v"))
    if value_node is None or value_node.text is None:
        return ""

    if cell_type == "s":
        try:
            index = int(value_node.text)
        except ValueError as exc:
            raise NotesWorkbookExtractionError(f"Invalid shared string index: {value_node.text!r}") from exc
        if index < 0 or index >= len(shared_strings):
            raise NotesWorkbookExtractionError(f"Shared string index out of range: {index}")
        return shared_strings[index]

    if cell_type == "b":
        return "TRUE" if value_node.text == "1" else "FALSE"

    return value_node.text


def _infer_value_type(cell: ET.Element) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        return "sharedString"
    if cell_type == "inlineStr":
        return "inlineString"
    if cell_type == "b":
        return "boolean"
    if cell_type == "e":
        return "error"
    if cell_type == "str":
        return "formulaString"
    if cell.find(_ns("f")) is not None:
        return "formulaNumericOrString"
    return "numberOrDate"


def _load_styles(zf: zipfile.ZipFile) -> Dict[str, Any]:
    styles_path = "xl/styles.xml"
    if styles_path not in zf.namelist():
        return {"num_formats": {}, "cell_xfs": []}

    root = ET.fromstring(zf.read(styles_path))
    num_formats: Dict[int, str] = {}
    cell_xfs: List[Dict[str, int]] = []

    num_formats_node = root.find(_ns("numFmts"))
    if num_formats_node is not None:
        for node in num_formats_node.findall(_ns("numFmt")):
            raw_id = node.attrib.get("numFmtId")
            if raw_id is None:
                continue
            try:
                num_formats[int(raw_id)] = node.attrib.get("formatCode", "")
            except ValueError:
                continue

    cell_xfs_node = root.find(_ns("cellXfs"))
    if cell_xfs_node is not None:
        for xf in cell_xfs_node.findall(_ns("xf")):
            try:
                num_fmt_id = int(xf.attrib.get("numFmtId", "0"))
            except ValueError:
                num_fmt_id = 0
            cell_xfs.append({"numFmtId": num_fmt_id})

    return {"num_formats": num_formats, "cell_xfs": cell_xfs}


def _resolve_number_format(style_id: int, styles: Dict[str, Any]) -> str:
    cell_xfs = styles.get("cell_xfs", [])
    num_formats = styles.get("num_formats", {})
    if not isinstance(cell_xfs, list) or style_id < 0 or style_id >= len(cell_xfs):
        return "builtin:0"
    xf = cell_xfs[style_id]
    if not isinstance(xf, dict):
        return "builtin:0"
    num_fmt_id = xf.get("numFmtId", 0)
    if not isinstance(num_fmt_id, int):
        return "builtin:0"
    return num_formats.get(num_fmt_id, f"builtin:{num_fmt_id}")


def _resolve_workbook_sheet_entries(zf: zipfile.ZipFile) -> List[Dict[str, Any]]:
    workbook_xml = "xl/workbook.xml"
    workbook_rels = "xl/_rels/workbook.xml.rels"
    if workbook_xml not in zf.namelist() or workbook_rels not in zf.namelist():
        raise NotesWorkbookExtractionError("Invalid .xlsx structure: missing workbook metadata")

    try:
        workbook_root = ET.fromstring(zf.read(workbook_xml))
        rels_root = ET.fromstring(zf.read(workbook_rels))
    except ET.ParseError as exc:
        raise NotesWorkbookExtractionError("Malformed workbook XML") from exc

    rel_map = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels_root.findall(f"{{{REL_NS}}}Relationship")
        if rel.attrib.get("Id")
    }

    sheets_node = workbook_root.find(_ns("sheets"))
    if sheets_node is None:
        raise NotesWorkbookExtractionError("Workbook has no sheets")

    entries: List[Dict[str, Any]] = []
    for index, sheet in enumerate(sheets_node.findall(_ns("sheet")), start=1):
        name = sheet.attrib.get("name")
        if not name:
            continue
        rid = sheet.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        target = rel_map.get(rid, "")
        if target and not target.startswith("xl/"):
            target = f"xl/{target}"
        entries.append(
            {
                "index": index,
                "name": name,
                "sheetId": sheet.attrib.get("sheetId", ""),
                "visibility": sheet.attrib.get("state", "visible"),
                "rid": rid,
                "target": target,
            }
        )
    return entries


def _extract_defined_names(workbook_root: ET.Element, sheet_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    defined_names_node = workbook_root.find(_ns("definedNames"))
    if defined_names_node is None:
        return []

    out: List[Dict[str, Any]] = []
    sheet_names = [entry["name"] for entry in sheet_entries]

    for node in defined_names_node.findall(_ns("definedName")):
        local_sheet_id = node.attrib.get("localSheetId")
        local_sheet_name = None
        if local_sheet_id is not None:
            try:
                idx = int(local_sheet_id)
                if 0 <= idx < len(sheet_names):
                    local_sheet_name = sheet_names[idx]
            except ValueError:
                local_sheet_name = None

        out.append(
            {
                "name": node.attrib.get("name", ""),
                "localSheetId": local_sheet_id,
                "localSheetName": local_sheet_name,
                "hidden": node.attrib.get("hidden") == "1",
                "formula": node.text or "",
            }
        )
    return out


def _extract_calculation_properties(workbook_root: ET.Element) -> Dict[str, str]:
    calc_pr = workbook_root.find(_ns("calcPr"))
    if calc_pr is None:
        return {}
    return {key: value for key, value in sorted(calc_pr.attrib.items())}


def _extract_workbook_date_system(workbook_root: ET.Element) -> Dict[str, str]:
    workbook_pr = workbook_root.find(_ns("workbookPr"))
    if workbook_pr is None:
        return {
            "mode": "excel_1900",
            "source": "workbookPr default (date1904 absent)",
        }

    raw_flag = workbook_pr.attrib.get("date1904")
    if raw_flag is None:
        return {
            "mode": "excel_1900",
            "source": "workbookPr default (date1904 absent)",
        }

    normalized = raw_flag.strip().lower()
    if normalized in {"1", "true"}:
        return {
            "mode": "excel_1904",
            "source": "workbookPr.date1904",
            "raw": raw_flag,
        }
    if normalized in {"0", "false"}:
        return {
            "mode": "excel_1900",
            "source": "workbookPr.date1904",
            "raw": raw_flag,
        }

    return {
        "mode": "unknown",
        "source": "workbookPr.date1904",
        "raw": raw_flag,
    }


def _extract_external_links(zf: zipfile.ZipFile) -> Dict[str, Any]:
    parts = sorted(path for path in zf.namelist() if path.startswith("xl/externalLinks/") and path.endswith(".xml"))
    relationships: List[Dict[str, str]] = []

    for part in parts:
        rel_path = f"{part.rsplit('/', 1)[0]}/_rels/{part.rsplit('/', 1)[1]}.rels"
        if rel_path not in zf.namelist():
            continue
        try:
            rel_root = ET.fromstring(zf.read(rel_path))
        except ET.ParseError:
            continue

        for rel in rel_root.findall(f"{{{REL_NS}}}Relationship"):
            relationships.append(
                {
                    "externalLinkPart": part,
                    "id": rel.attrib.get("Id", ""),
                    "type": rel.attrib.get("Type", ""),
                    "target": rel.attrib.get("Target", ""),
                    "targetMode": rel.attrib.get("TargetMode", ""),
                }
            )

    return {
        "parts": parts,
        "count": len(parts),
        "relationships": sorted(relationships, key=lambda item: (item["externalLinkPart"], item["id"])),
    }


def _extract_comments_for_sheet(
    zf: zipfile.ZipFile,
    sheet_xml_path: str,
    worksheet_root: ET.Element,
) -> Dict[str, Dict[str, str]]:
    rel_path = f"{sheet_xml_path.rsplit('/', 1)[0]}/_rels/{sheet_xml_path.rsplit('/', 1)[1]}.rels"
    if rel_path not in zf.namelist():
        return {}

    try:
        rel_root = ET.fromstring(zf.read(rel_path))
    except ET.ParseError:
        return {}

    comments_targets: List[str] = []
    for rel in rel_root.findall(f"{{{REL_NS}}}Relationship"):
        rel_type = rel.attrib.get("Type", "")
        if rel_type.endswith("/comments"):
            target = rel.attrib.get("Target", "")
            if target.startswith("../"):
                resolved = f"xl/{target.replace('../', '', 1)}"
            elif target.startswith("xl/"):
                resolved = target
            else:
                resolved = f"{sheet_xml_path.rsplit('/', 1)[0]}/{target}"
            comments_targets.append(resolved)

    comments: Dict[str, Dict[str, str]] = {}
    for comments_path in sorted(set(comments_targets)):
        if comments_path not in zf.namelist():
            continue
        try:
            comments_root = ET.fromstring(zf.read(comments_path))
        except ET.ParseError:
            continue

        for comment in comments_root.findall(f".//{_ns('comment')}"):
            ref = comment.attrib.get("ref", "")
            if not ref:
                continue
            text = "".join((node.text or "") for node in comment.findall(f".//{_ns('t')}"))
            comments[ref] = {
                "commentRef": ref,
                "text": text,
                "sourcePart": comments_path,
            }

    return comments


def _extract_hyperlinks_for_sheet(
    zf: zipfile.ZipFile,
    sheet_xml_path: str,
    worksheet_root: ET.Element,
) -> Dict[str, Dict[str, str]]:
    rel_path = f"{sheet_xml_path.rsplit('/', 1)[0]}/_rels/{sheet_xml_path.rsplit('/', 1)[1]}.rels"
    rel_map: Dict[str, Dict[str, str]] = {}
    if rel_path in zf.namelist():
        try:
            rel_root = ET.fromstring(zf.read(rel_path))
            for rel in rel_root.findall(f"{{{REL_NS}}}Relationship"):
                rel_id = rel.attrib.get("Id")
                if rel_id:
                    rel_map[rel_id] = {
                        "type": rel.attrib.get("Type", ""),
                        "target": rel.attrib.get("Target", ""),
                        "targetMode": rel.attrib.get("TargetMode", ""),
                    }
        except ET.ParseError:
            rel_map = {}

    out: Dict[str, Dict[str, str]] = {}
    hyperlinks_node = worksheet_root.find(_ns("hyperlinks"))
    if hyperlinks_node is None:
        return out

    for link in hyperlinks_node.findall(_ns("hyperlink")):
        ref = link.attrib.get("ref", "")
        if not ref:
            continue
        rel_id = link.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        relation = rel_map.get(rel_id, {})
        out[ref] = {
            "ref": ref,
            "relationshipId": rel_id,
            "location": link.attrib.get("location", ""),
            "display": link.attrib.get("display", ""),
            "target": relation.get("target", ""),
            "targetMode": relation.get("targetMode", ""),
            "relationshipType": relation.get("type", ""),
        }

    return out


def _sheet_drawing_relationships(zf: zipfile.ZipFile, sheet_xml_path: str, worksheet_root: ET.Element) -> List[Dict[str, str]]:
    rel_path = f"{sheet_xml_path.rsplit('/', 1)[0]}/_rels/{sheet_xml_path.rsplit('/', 1)[1]}.rels"
    rels: Dict[str, Dict[str, str]] = {}
    if rel_path in zf.namelist():
        try:
            rel_root = ET.fromstring(zf.read(rel_path))
            for rel in rel_root.findall(f"{{{REL_NS}}}Relationship"):
                rel_id = rel.attrib.get("Id")
                if rel_id:
                    rels[rel_id] = {
                        "type": rel.attrib.get("Type", ""),
                        "target": rel.attrib.get("Target", ""),
                        "targetMode": rel.attrib.get("TargetMode", ""),
                    }
        except ET.ParseError:
            rels = {}

    out: List[Dict[str, str]] = []
    drawing_node = worksheet_root.find(_ns("drawing"))
    if drawing_node is not None:
        drawing_rid = drawing_node.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        rel = rels.get(drawing_rid, {})
        target = rel.get("target", "")
        if target.startswith("../"):
            resolved_target = f"xl/{target.replace('../', '', 1)}"
        elif target.startswith("xl/"):
            resolved_target = target
        elif target:
            resolved_target = f"{sheet_xml_path.rsplit('/', 1)[0]}/{target}"
        else:
            resolved_target = ""
        out.append(
            {
                "type": "drawing",
                "relationshipId": drawing_rid,
                "relationshipType": rel.get("type", ""),
                "target": resolved_target,
                "targetMode": rel.get("targetMode", ""),
            }
        )

    for rel_id, rel in sorted(rels.items()):
        rel_type = rel.get("type", "")
        if "chart" in rel_type or "oleObject" in rel_type:
            out.append(
                {
                    "type": "unsupportedMeaningfulObject",
                    "relationshipId": rel_id,
                    "relationshipType": rel_type,
                    "target": rel.get("target", ""),
                    "targetMode": rel.get("targetMode", ""),
                }
            )

    return out


def _parse_sheet_cells(
    worksheet_root: ET.Element,
    shared_strings: List[str],
) -> Dict[str, CellData]:
    out: Dict[str, CellData] = {}
    for row in worksheet_root.findall(f".//{_ns('row')}"):
        for cell in row.findall(_ns("c")):
            ref = cell.attrib.get("r")
            if not ref:
                continue
            col_letter, row_number = _split_cell_ref(ref)
            formula_node = cell.find(_ns("f"))
            formula = formula_node.text if formula_node is not None and formula_node.text is not None else None
            value_text = _read_cell_text(cell, shared_strings)
            has_cached = cell.find(_ns("v")) is not None
            try:
                style_id = int(cell.attrib.get("s", "0"))
            except ValueError:
                style_id = 0

            out[ref] = CellData(
                coordinate=ref,
                row=row_number,
                col_letter=col_letter,
                col_index=_column_to_number(col_letter),
                cell_type=_infer_value_type(cell),
                style_id=style_id,
                value_text=value_text,
                formula=formula,
                has_cached_value=has_cached,
            )
    return out


def _manual_page_breaks(worksheet_root: ET.Element) -> Dict[str, List[Dict[str, str]]]:
    row_breaks: List[Dict[str, str]] = []
    col_breaks: List[Dict[str, str]] = []

    row_node = worksheet_root.find(_ns("rowBreaks"))
    if row_node is not None:
        for brk in row_node.findall(_ns("brk")):
            row_breaks.append({key: value for key, value in sorted(brk.attrib.items())})

    col_node = worksheet_root.find(_ns("colBreaks"))
    if col_node is not None:
        for brk in col_node.findall(_ns("brk")):
            col_breaks.append({key: value for key, value in sorted(brk.attrib.items())})

    return {"row": row_breaks, "column": col_breaks}


def _data_validations(worksheet_root: ET.Element) -> List[Dict[str, str]]:
    node = worksheet_root.find(_ns("dataValidations"))
    if node is None:
        return []

    out: List[Dict[str, str]] = []
    for dv in node.findall(_ns("dataValidation")):
        item: Dict[str, str] = {key: value for key, value in sorted(dv.attrib.items())}
        formula1 = dv.find(_ns("formula1"))
        formula2 = dv.find(_ns("formula2"))
        if formula1 is not None and formula1.text is not None:
            item["formula1"] = formula1.text
        if formula2 is not None and formula2.text is not None:
            item["formula2"] = formula2.text
        out.append(item)
    return out


def _sheet_visibility_rows_columns(worksheet_root: ET.Element) -> Tuple[List[int], List[str], Dict[str, float], Dict[str, Dict[str, Any]]]:
    hidden_rows: List[int] = []
    row_heights: Dict[str, float] = {}

    for row in worksheet_root.findall(f".//{_ns('row')}"):
        raw_idx = row.attrib.get("r")
        if raw_idx is None:
            continue
        try:
            row_idx = int(raw_idx)
        except ValueError:
            continue
        if row.attrib.get("hidden") == "1":
            hidden_rows.append(row_idx)
        if "ht" in row.attrib:
            try:
                row_heights[str(row_idx)] = float(row.attrib["ht"])
            except ValueError:
                continue

    hidden_columns: List[str] = []
    column_widths: Dict[str, Dict[str, Any]] = {}
    cols_node = worksheet_root.find(_ns("cols"))
    if cols_node is not None:
        for col in cols_node.findall(_ns("col")):
            min_raw = col.attrib.get("min")
            max_raw = col.attrib.get("max")
            if min_raw is None or max_raw is None:
                continue
            try:
                mn = int(min_raw)
                mx = int(max_raw)
            except ValueError:
                continue
            width = col.attrib.get("width")
            hidden = col.attrib.get("hidden") == "1"
            custom_width = col.attrib.get("customWidth") == "1"

            for col_num in range(mn, mx + 1):
                col_letter = _number_to_column(col_num)
                if hidden:
                    hidden_columns.append(col_letter)
                entry: Dict[str, Any] = {
                    "hidden": hidden,
                    "customWidth": custom_width,
                }
                if width is not None:
                    try:
                        entry["width"] = float(width)
                    except ValueError:
                        entry["width"] = width
                column_widths[col_letter] = entry

    return sorted(hidden_rows), sorted(set(hidden_columns)), row_heights, column_widths


def _freeze_pane(worksheet_root: ET.Element) -> Optional[Dict[str, str]]:
    sheet_views = worksheet_root.find(_ns("sheetViews"))
    if sheet_views is None:
        return None
    sheet_view = sheet_views.find(_ns("sheetView"))
    if sheet_view is None:
        return None
    pane = sheet_view.find(_ns("pane"))
    if pane is None:
        return None
    return {key: value for key, value in sorted(pane.attrib.items())}


def _print_area_for_sheet(defined_names: List[Dict[str, Any]], sheet_name: str) -> Optional[str]:
    for item in defined_names:
        if item.get("name") == "_xlnm.Print_Area" and item.get("localSheetName") == sheet_name:
            formula = item.get("formula")
            if isinstance(formula, str):
                return formula
    return None


def _merged_ranges(worksheet_root: ET.Element) -> Tuple[List[str], Dict[str, str]]:
    ranges: List[str] = []
    membership: Dict[str, str] = {}

    merged = worksheet_root.find(_ns("mergeCells"))
    if merged is None:
        return ranges, membership
    for item in merged.findall(_ns("mergeCell")):
        ref = item.attrib.get("ref")
        if not ref:
            continue
        ranges.append(ref)
        for coordinate in _expand_range(ref):
            membership[coordinate] = ref
    return sorted(ranges), membership


def _cell_id(sheet_index: int, row: int, col_index: int) -> str:
    return f"ws{sheet_index:02d}_r{row:05d}_c{col_index:04d}"


def extract_notes_workbook_raw(
    workbook_path: Path,
    mapping_path: Path,
) -> Dict[str, Any]:
    if not workbook_path.exists():
        raise NotesWorkbookExtractionError(f"Workbook does not exist: {workbook_path}")

    mapping_policy = _load_mapping_policy(mapping_path)
    authoritative_ranges = _authoritative_ranges_by_sheet(mapping_policy)

    try:
        workbook_bytes = workbook_path.read_bytes()
    except OSError as exc:
        raise NotesWorkbookExtractionError(f"Unable to read workbook: {workbook_path}") from exc

    source_sha = _sha256_bytes(workbook_bytes)

    try:
        zf = zipfile.ZipFile(workbook_path)
    except zipfile.BadZipFile as exc:
        raise NotesWorkbookExtractionError(f"Invalid or corrupt XLSX ZIP container: {workbook_path}") from exc

    with zf:
        sheet_entries = _resolve_workbook_sheet_entries(zf)

        workbook_root = ET.fromstring(zf.read("xl/workbook.xml"))
        defined_names = _extract_defined_names(workbook_root, sheet_entries)
        calc_props = _extract_calculation_properties(workbook_root)
        date_system = _extract_workbook_date_system(workbook_root)
        external_links = _extract_external_links(zf)
        shared_strings = _parse_shared_strings(zf)
        styles = _load_styles(zf)

        diagnostics: List[Dict[str, Any]] = []
        worksheets: List[Dict[str, Any]] = []
        global_non_empty = 0
        global_formula = 0
        global_missing_authoritative_cached = 0

        for sheet in sheet_entries:
            sheet_name = sheet["name"]
            target = sheet.get("target", "")
            if not target:
                raise NotesWorkbookExtractionError(f"Missing worksheet target for sheet: {sheet_name}")
            if target not in zf.namelist():
                raise NotesWorkbookExtractionError(f"Sheet XML missing for sheet '{sheet_name}': {target}")

            try:
                worksheet_root = ET.fromstring(zf.read(target))
            except ET.ParseError as exc:
                raise NotesWorkbookExtractionError(f"Malformed worksheet XML for sheet '{sheet_name}'") from exc

            comments_by_ref = _extract_comments_for_sheet(zf, target, worksheet_root)
            hyperlinks_by_ref = _extract_hyperlinks_for_sheet(zf, target, worksheet_root)
            drawing_relationships = _sheet_drawing_relationships(zf, target, worksheet_root)

            merged_ranges, merged_membership = _merged_ranges(worksheet_root)
            hidden_rows, hidden_columns, row_heights, column_widths = _sheet_visibility_rows_columns(worksheet_root)
            freeze_pane = _freeze_pane(worksheet_root)
            page_breaks = _manual_page_breaks(worksheet_root)
            data_validations = _data_validations(worksheet_root)

            dimension = worksheet_root.find(_ns("dimension"))
            used_range = dimension.attrib.get("ref", "A1") if dimension is not None else "A1"

            parsed_cells = _parse_sheet_cells(worksheet_root, shared_strings)

            must_preserve_coordinates: Set[str] = set()
            must_preserve_coordinates.update(authoritative_ranges.get(sheet_name, set()))
            for merged_ref in merged_ranges:
                must_preserve_coordinates.update(_expand_range(merged_ref))

            all_coordinates = set(parsed_cells.keys())
            all_coordinates.update(must_preserve_coordinates)
            all_coordinates.update(comments_by_ref.keys())
            all_coordinates.update(hyperlinks_by_ref.keys())

            sorted_coordinates = sorted(
                all_coordinates,
                key=lambda ref: (_split_cell_ref(ref)[1], _column_to_number(_split_cell_ref(ref)[0])),
            )

            cells_out: List[Dict[str, Any]] = []
            non_empty_count = 0
            formula_count = 0
            missing_authoritative_cached = 0

            for coordinate in sorted_coordinates:
                col_letter, row_idx = _split_cell_ref(coordinate)
                col_index = _column_to_number(col_letter)
                cell = parsed_cells.get(coordinate)

                value_text = cell.value_text if cell is not None else ""
                formula = cell.formula if cell is not None else None
                has_cached = bool(cell.has_cached_value) if cell is not None else False
                style_id = cell.style_id if cell is not None else 0
                value_type = cell.cell_type if cell is not None else "empty"

                if formula is not None:
                    formula_count += 1
                    if not has_cached and coordinate in authoritative_ranges.get(sheet_name, set()):
                        missing_authoritative_cached += 1
                        diagnostics.append(
                            {
                                "code": "FORMULA_MISSING_CACHED_VALUE",
                                "severity": "error",
                                "sheet": sheet_name,
                                "coordinate": coordinate,
                                "sourceTrace": {
                                    "worksheetPart": target,
                                    "coordinate": coordinate,
                                },
                            }
                        )

                if formula is not None and "[" in formula and "]" in formula:
                    if has_cached:
                        diagnostics.append(
                            {
                                "code": "EXTERNAL_LINK_CACHED_VALUE_USED",
                                "severity": "review_required",
                                "sheet": sheet_name,
                                "coordinate": coordinate,
                                "sourceTrace": {
                                    "worksheetPart": target,
                                    "coordinate": coordinate,
                                    "formula": formula,
                                },
                            }
                        )
                    else:
                        diagnostics.append(
                            {
                                "code": "EXTERNAL_LINK_UNRESOLVED_REFERENCE",
                                "severity": "error",
                                "sheet": sheet_name,
                                "coordinate": coordinate,
                                "sourceTrace": {
                                    "worksheetPart": target,
                                    "coordinate": coordinate,
                                    "formula": formula,
                                },
                            }
                        )

                comment_payload = comments_by_ref.get(coordinate)
                hyperlink_payload = hyperlinks_by_ref.get(coordinate)

                semantically_significant = (
                    bool(value_text)
                    or formula is not None
                    or coordinate in must_preserve_coordinates
                    or comment_payload is not None
                    or hyperlink_payload is not None
                )
                if not semantically_significant:
                    continue

                if bool(value_text) or formula is not None:
                    non_empty_count += 1

                cells_out.append(
                    {
                        "cachedValue": value_text if formula is not None and has_cached else None,
                        "cellId": _cell_id(sheet["index"], row_idx, col_index),
                        "commentEvidence": comment_payload,
                        "coordinate": coordinate,
                        "column": col_letter,
                        "columnIndex": col_index,
                        "displayedValue": value_text,
                        "formula": formula,
                        "hasCachedValue": has_cached,
                        "hyperlinkEvidence": hyperlink_payload,
                        "mergedRange": merged_membership.get(coordinate),
                        "numberFormat": _resolve_number_format(style_id, styles),
                        "rawValue": value_text,
                        "row": row_idx,
                        "sourceTrace": {
                            "coordinate": coordinate,
                            "worksheetName": sheet_name,
                            "worksheetPart": target,
                        },
                        "styleId": style_id,
                        "valueType": value_type,
                    }
                )

            global_non_empty += non_empty_count
            global_formula += formula_count
            global_missing_authoritative_cached += missing_authoritative_cached

            for rel in drawing_relationships:
                severity = "review_required" if rel.get("type") == "unsupportedMeaningfulObject" else "info"
                diagnostics.append(
                    {
                        "code": "WORKSHEET_DRAWING_RELATIONSHIP_PRESENT",
                        "severity": severity,
                        "sheet": sheet_name,
                        "relationship": rel,
                    }
                )

            worksheet_payload = {
                "cells": cells_out,
                "columnWidths": column_widths,
                "comments": sorted(comments_by_ref.values(), key=lambda item: item["commentRef"]),
                "dataValidations": data_validations,
                "drawingRelationships": drawing_relationships,
                "freezePane": freeze_pane,
                "hiddenColumns": hidden_columns,
                "hiddenRows": hidden_rows,
                "index": sheet["index"],
                "manualPageBreaks": page_breaks,
                "mergedRanges": merged_ranges,
                "name": sheet_name,
                "nonEmptyCellCount": non_empty_count,
                "formulaCellCount": formula_count,
                "missingAuthoritativeCachedFormulaCount": missing_authoritative_cached,
                "printArea": _print_area_for_sheet(defined_names, sheet_name),
                "rowHeights": row_heights,
                "sheetId": sheet["sheetId"],
                "usedRange": used_range,
                "visibility": sheet["visibility"],
            }
            worksheets.append(worksheet_payload)

        required_sheets: Set[str] = set(authoritative_ranges.keys())
        existing_sheets: Set[str] = {sheet["name"] for sheet in sheet_entries}
        missing_required = sorted(required_sheets.difference(existing_sheets))
        if missing_required:
            raise NotesWorkbookExtractionError(f"Missing required worksheet(s): {missing_required}")

        if global_missing_authoritative_cached > 0:
            raise NotesWorkbookExtractionError(
                "Authoritative mapped range contains formula without cached value"
            )

        contract: Dict[str, Any] = {
            "diagnostics": diagnostics,
            "schemaVersion": "1.0",
            "source": {
                "file": _safe_source_path(workbook_path),
                "sha256": source_sha,
            },
            "workbook": {
                "calculationProperties": calc_props,
                "dateSystem": date_system,
                "definedNames": defined_names,
                "externalLinks": external_links,
                "sheetOrder": [sheet["name"] for sheet in sheet_entries],
                "worksheetCount": len(sheet_entries),
                "nonEmptyCellCount": global_non_empty,
                "formulaCellCount": global_formula,
                "authoritativeFormulaMissingCachedCount": global_missing_authoritative_cached,
            },
            "worksheets": worksheets,
        }

        return json.loads(_canonical_json_bytes(contract).decode("utf-8"))