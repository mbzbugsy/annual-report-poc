from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from income_statement_profile import WORKBOOK_PROFILE

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class ExtractionError(Exception):
    pass


def _safe_source_path(path: Path) -> str:
    # Keep source metadata portable by avoiding absolute local paths.
    if path.is_absolute():
        return path.name
    return path.as_posix()

@dataclass
class CellData:
    value_text: str
    formula: Optional[str]
    has_cached_value: bool


@dataclass
class SheetData:
    row_cells: Dict[int, Dict[str, CellData]]
    merged_master: Dict[str, str]


def _ns(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


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


def _split_cell_ref(cell_ref: str) -> Tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_ref)
    if not match:
        raise ExtractionError(f"Unsupported cell reference format: {cell_ref}")
    return match.group(1), int(match.group(2))


def _expand_range(range_ref: str) -> List[str]:
    start, end = range_ref.split(":", 1)
    start_col, start_row = _split_cell_ref(start)
    end_col, end_row = _split_cell_ref(end)

    cells: List[str] = []
    for row in range(start_row, end_row + 1):
        for col_num in range(_column_to_number(start_col), _column_to_number(end_col) + 1):
            cells.append(f"{_number_to_column(col_num)}{row}")
    return cells


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    shared_path = "xl/sharedStrings.xml"
    if shared_path not in zf.namelist():
        return []

    root = ET.fromstring(zf.read(shared_path))
    values: List[str] = []
    for si in root.findall(_ns("si")):
        text = "".join((t.text or "") for t in si.findall(f".//{_ns('t')}")).strip()
        values.append(text)
    return values


def _read_cell_text(cell: ET.Element, shared_strings: List[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        t_node = cell.find(f"{_ns('is')}/{_ns('t')}")
        return (t_node.text if t_node is not None and t_node.text is not None else "").strip()

    v_node = cell.find(_ns("v"))
    if v_node is None or v_node.text is None:
        return ""

    if cell_type == "s":
        index = int(v_node.text)
        if index < 0 or index >= len(shared_strings):
            raise ExtractionError(f"Shared string index out of range: {index}")
        return shared_strings[index].strip()

    return v_node.text.strip()


def _read_sheet_data(
    zf: zipfile.ZipFile, sheet_path: str, shared_strings: List[str]
) -> SheetData:
    root = ET.fromstring(zf.read(sheet_path))

    row_cells: Dict[int, Dict[str, CellData]] = {}
    for row in root.findall(f".//{_ns('row')}"):
        row_index = int(row.attrib["r"])
        cells: Dict[str, CellData] = {}
        for cell in row.findall(_ns("c")):
            cell_ref = cell.attrib["r"]
            col, _ = _split_cell_ref(cell_ref)
            value_text = _read_cell_text(cell, shared_strings)
            formula_node = cell.find(_ns("f"))
            formula = formula_node.text.strip() if formula_node is not None and formula_node.text else None
            has_cached_value = cell.find(_ns("v")) is not None
            cells[col] = CellData(
                value_text=value_text,
                formula=formula,
                has_cached_value=has_cached_value,
            )
        row_cells[row_index] = cells

    merged_master: Dict[str, str] = {}
    merge_cells = root.find(_ns("mergeCells"))
    if merge_cells is not None:
        for merge in merge_cells.findall(_ns("mergeCell")):
            ref = merge.attrib.get("ref")
            if not ref or ":" not in ref:
                continue
            top_left = ref.split(":", 1)[0]
            for cell_ref in _expand_range(ref):
                if cell_ref != top_left:
                    merged_master[cell_ref] = top_left

    return SheetData(row_cells=row_cells, merged_master=merged_master)


def _get_cell_data(sheet: SheetData, row_index: int, col: str) -> Optional[CellData]:
    row = sheet.row_cells.get(row_index, {})
    direct = row.get(col)
    if direct is not None:
        return direct

    merged_key = f"{col}{row_index}"
    master_ref = sheet.merged_master.get(merged_key)
    if not master_ref:
        return None

    master_col, master_row = _split_cell_ref(master_ref)
    return sheet.row_cells.get(master_row, {}).get(master_col)


def _find_row_for_label(
    sheet: SheetData,
    accepted_labels: List[str],
    label_anchor_column: str,
    value_column: str,
) -> Tuple[int, str]:
    normalized_accept = {_normalize_label(label): label for label in accepted_labels}
    matches: List[Tuple[int, str]] = []

    for row_index in sorted(sheet.row_cells.keys()):
        cell = _get_cell_data(sheet, row_index, label_anchor_column)
        if cell is None or not cell.value_text:
            continue

        normalized_value = _normalize_label(cell.value_text)
        if normalized_value in normalized_accept:
            matches.append((row_index, cell.value_text))

    if not matches:
        raise ExtractionError(
            f"Required label not found. Accepted labels: {accepted_labels}"
        )

    unique_rows = sorted({row for row, _ in matches})
    if len(unique_rows) > 1:
        rows_with_value = []
        for row_index, raw_label in matches:
            value_cell = _get_cell_data(sheet, row_index, value_column)
            if value_cell is not None and value_cell.value_text.strip() != "":
                rows_with_value.append((row_index, raw_label))

        if len(rows_with_value) == 1:
            return rows_with_value[0]

        raise ExtractionError(
            "Ambiguous label match. "
            f"Accepted labels: {accepted_labels}. Matched rows: {unique_rows}"
        )

    return matches[0]


def _parse_numeric_or_fail(
    label: str, row_index: int, cell_ref: str, cell: Optional[CellData]
) -> Tuple[Decimal, bool]:
    if cell is not None and cell.formula and not cell.has_cached_value:
        raise ExtractionError(
            f"Formula cell has no cached value for label '{label}' at {cell_ref} (row {row_index})."
        )

    if cell is None or cell.value_text == "":
        raise ExtractionError(
            f"Missing numeric value for label '{label}' at expected cell {cell_ref} (row {row_index})."
        )

    try:
        number = Decimal(cell.value_text)
    except InvalidOperation as exc:
        raise ExtractionError(
            f"Non-numeric value for label '{label}' at {cell_ref} (row {row_index}): {cell.value_text!r}"
        ) from exc

    return number, bool(cell.formula)


def extract_income_statement(
    workbook_path: Path,
    output_path: Path,
    sheet_name: Optional[str] = None,
) -> Dict[str, object]:
    profile = WORKBOOK_PROFILE
    active_sheet_name = sheet_name or profile.sheet_name

    if not workbook_path.exists():
        raise ExtractionError(f"Workbook does not exist: {workbook_path}")

    try:
        with zipfile.ZipFile(workbook_path) as zf:
            workbook_xml = "xl/workbook.xml"
            workbook_rels = "xl/_rels/workbook.xml.rels"
            if workbook_xml not in zf.namelist() or workbook_rels not in zf.namelist():
                raise ExtractionError(f"Invalid .xlsx structure: {workbook_path}")

            wb_root = ET.fromstring(zf.read(workbook_xml))
            rel_root = ET.fromstring(zf.read(workbook_rels))
            rel_map = {
                rel.attrib["Id"]: rel.attrib["Target"]
                for rel in rel_root.findall(f"{{{REL_NS}}}Relationship")
            }

            target_sheet_path: Optional[str] = None
            for sheet in wb_root.find(_ns("sheets")):
                if sheet.attrib.get("name") != active_sheet_name:
                    continue
                rid = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
                if rid and rid in rel_map:
                    target_sheet_path = rel_map[rid]
                    break

            if target_sheet_path is None:
                raise ExtractionError(f"Expected sheet not found: {active_sheet_name}")

            if not target_sheet_path.startswith("xl/"):
                target_sheet_path = f"xl/{target_sheet_path}"

            if target_sheet_path not in zf.namelist():
                raise ExtractionError(f"Sheet XML not found for {active_sheet_name}: {target_sheet_path}")

            shared_strings = _parse_shared_strings(zf)
            sheet_data = _read_sheet_data(zf, target_sheet_path, shared_strings)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"Invalid or corrupt XLSX file: {workbook_path}") from exc

    lines: Dict[str, object] = {}
    for entry in profile.line_mappings:
        try:
            row_index, matched_label = _find_row_for_label(
                sheet_data,
                entry.accepted_labels,
                profile.label_anchor_column,
                profile.value_column,
            )
        except ExtractionError:
            if entry.required:
                raise
            continue

        value_cell_ref = f"{profile.value_column}{row_index}"

        value_cell = _get_cell_data(sheet_data, row_index, profile.value_column)

        value, value_is_formula = _parse_numeric_or_fail(
            matched_label, row_index, value_cell_ref, value_cell
        )

        lines[entry.target_property] = {
            "label": matched_label,
            "value": str(value),
            "sourceTrace": {
                "valueCell": value_cell_ref,
                "valueIsFormula": value_is_formula,
            },
        }

    if {"interestIncome", "interestCosts"}.issubset(lines):
        net_financial_items = Decimal(lines["interestIncome"]["value"]) + Decimal(lines["interestCosts"]["value"])
        lines["netFinancialItems"] = {
            "label": "Resultat från finansiella poster",
            "value": str(net_financial_items),
            "sourceTrace": {
                "derivedFrom": ["interestIncome", "interestCosts"],
                "derivationNote": "Derived because section row has no authoritative numeric value in column D.",
            },
        }

    payload = {
        "schemaVersion": "1.0",
        "source": {
            "file": _safe_source_path(workbook_path),
            "sheet": active_sheet_name,
        },
        "extractionBasis": {
            "labelAnchorColumn": profile.label_anchor_column,
            "finalValueColumn": profile.value_column,
            "note": "Configured authoritative value column is used for extraction."
        },
        "period": {
            "reportingPeriod": None,
            "source": None,
            "note": "Not reliably derivable from RR sammanställning in this slice."
        },
        "lines": lines,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return payload
