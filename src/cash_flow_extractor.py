from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from cash_flow_profile import CashFlowSingleLineMapping, WORKBOOK_PROFILE

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

REQUIRED_PROPERTIES = [
    "resultAfterFinancialItems",
    "nonCashAdjustments",
    "incomeTaxPaid",
    "operatingCashFlowBeforeWorkingCapital",
    "changeInShortTermReceivables",
    "changeInShortTermLiabilities",
    "operatingCashFlowTotal",
    "intangibleComposedInvestingCashFlow",
    "investmentsTangibleAssets",
    "investmentsFinancialAssets",
    "investingCashFlowTotal",
    "financingCashFlowTotal",
    "netCashFlowForYear",
    "cashAtBeginning",
    "cashAtEnd",
]

TOLERANCE = Decimal("0.01")


class ExtractionError(Exception):
    pass


@dataclass
class CellData:
    value_text: str
    formula: Optional[str]
    has_cached_value: bool


@dataclass
class SheetData:
    row_cells: Dict[int, Dict[str, CellData]]


def _safe_source_path(path: Path) -> str:
    if path.is_absolute():
        return path.name
    return path.as_posix()


def _ns(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _normalize_label(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = normalized.replace("å", "a").replace("ä", "a").replace("ö", "o")
    return normalized


def _split_cell_ref(cell_ref: str) -> Tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_ref)
    if not match:
        raise ExtractionError(f"Unsupported cell reference: {cell_ref}")
    return match.group(1), int(match.group(2))


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: List[str] = []
    for si in root.findall(_ns("si")):
        text = "".join((t.text or "") for t in si.findall(f".//{_ns('t')}"))
        values.append(text.strip())
    return values


def _read_cell_text(cell: ET.Element, shared_strings: List[str]) -> str:
    cell_type = cell.attrib.get("t")
    v_node = cell.find(_ns("v"))

    if cell_type == "inlineStr":
        t_node = cell.find(f"{_ns('is')}/{_ns('t')}")
        return (t_node.text if t_node is not None and t_node.text is not None else "").strip()

    if v_node is None or v_node.text is None:
        return ""

    if cell_type == "s":
        index = int(v_node.text)
        if index < 0 or index >= len(shared_strings):
            raise ExtractionError(f"Shared string index out of range: {index}")
        return shared_strings[index].strip()

    return v_node.text.strip()


def _read_sheet_data(zf: zipfile.ZipFile, sheet_path: str, shared_strings: List[str]) -> SheetData:
    root = ET.fromstring(zf.read(sheet_path))
    row_cells: Dict[int, Dict[str, CellData]] = {}

    for row in root.findall(f".//{_ns('row')}"):
        row_index = int(row.attrib["r"])
        cells: Dict[str, CellData] = {}
        for cell in row.findall(_ns("c")):
            cell_ref = cell.attrib["r"]
            col, _ = _split_cell_ref(cell_ref)
            formula_node = cell.find(_ns("f"))
            formula = formula_node.text.strip() if formula_node is not None and formula_node.text else None
            cells[col] = CellData(
                value_text=_read_cell_text(cell, shared_strings),
                formula=formula,
                has_cached_value=cell.find(_ns("v")) is not None,
            )
        row_cells[row_index] = cells

    return SheetData(row_cells=row_cells)


def _resolve_sheet_paths(zf: zipfile.ZipFile) -> Dict[str, str]:
    workbook_xml = "xl/workbook.xml"
    workbook_rels = "xl/_rels/workbook.xml.rels"
    if workbook_xml not in zf.namelist() or workbook_rels not in zf.namelist():
        raise ExtractionError("Invalid .xlsx structure: workbook metadata missing")

    wb_root = ET.fromstring(zf.read(workbook_xml))
    rel_root = ET.fromstring(zf.read(workbook_rels))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall(f"{{{REL_NS}}}Relationship")
    }

    sheet_paths: Dict[str, str] = {}
    for sheet in wb_root.find(_ns("sheets")):
        sheet_name = sheet.attrib.get("name")
        rid = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
        if not sheet_name or not rid or rid not in rel_map:
            continue
        target = rel_map[rid]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheet_paths[sheet_name] = target

    return sheet_paths


def _find_rows_for_labels(sheet: SheetData, label_column: str, accepted_labels: List[str]) -> List[Tuple[int, str]]:
    accepted = {_normalize_label(label) for label in accepted_labels}
    matches: List[Tuple[int, str]] = []

    for row_index in sorted(sheet.row_cells.keys()):
        label_cell = sheet.row_cells.get(row_index, {}).get(label_column)
        if label_cell is None or not label_cell.value_text.strip():
            continue
        if _normalize_label(label_cell.value_text) in accepted:
            matches.append((row_index, label_cell.value_text))

    return matches


def _cell_ref(col: str, row_index: int) -> str:
    return f"{col}{row_index}"


def _parse_decimal_cell(
    line_key: str,
    period_name: str,
    cell_ref: str,
    cell: Optional[CellData],
    diagnostics: List[Dict[str, object]],
) -> Optional[Decimal]:
    if cell is not None and cell.formula and not cell.has_cached_value:
        diagnostics.append(
            {
                "code": "FORMULA_WITHOUT_CACHED_VALUE",
                "severity": "error",
                "line": line_key,
                "message": f"Formula cell without cached value for {line_key} ({period_name}) at {cell_ref}.",
                "trace": {"cell": cell_ref, "period": period_name, "formula": cell.formula},
                "reviewRequired": True,
            }
        )
        return None

    if cell is None or cell.value_text.strip() == "":
        diagnostics.append(
            {
                "code": "BLANK_AUTHORITATIVE_CELL",
                "severity": "error",
                "line": line_key,
                "message": f"Blank authoritative cell for {line_key} ({period_name}) at {cell_ref}.",
                "trace": {"cell": cell_ref, "period": period_name},
                "reviewRequired": True,
            }
        )
        return None

    try:
        return Decimal(cell.value_text)
    except InvalidOperation:
        diagnostics.append(
            {
                "code": "NON_NUMERIC_AUTHORITATIVE_VALUE",
                "severity": "error",
                "line": line_key,
                "message": f"Non-numeric value for {line_key} ({period_name}) at {cell_ref}.",
                "trace": {"cell": cell_ref, "period": period_name, "raw": cell.value_text},
                "reviewRequired": True,
            }
        )
        return None


def _unresolved_line_template(target_property: str) -> Dict[str, object]:
    return {
        "valueCurrent": None,
        "valuePrevious": None,
        "status": "unresolved",
        "source": {
            "semanticAnchor": target_property,
            "sheet": "KFA",
        },
        "renderedLabelSv": None,
        "sourceLabel": None,
        "trace": {},
    }


def _extract_single_line(
    mapping: CashFlowSingleLineMapping,
    kfa_sheet: SheetData,
    diagnostics: List[Dict[str, object]],
) -> Dict[str, object]:
    matches = _find_rows_for_labels(kfa_sheet, WORKBOOK_PROFILE.label_anchor_column, mapping.accepted_labels)
    if len(matches) == 0:
        diagnostics.append(
            {
                "code": "MISSING_LABEL",
                "severity": "error",
                "line": mapping.target_property,
                "message": f"Missing KFA anchor label for {mapping.target_property}.",
                "trace": {"acceptedLabels": mapping.accepted_labels},
                "reviewRequired": True,
            }
        )
        line = _unresolved_line_template(mapping.target_property)
        line["renderedLabelSv"] = mapping.rendered_label_sv
        line["source"]["semanticAnchor"] = mapping.source_semantic_label
        return line

    if len(matches) > 1:
        diagnostics.append(
            {
                "code": "DUPLICATE_SEMANTIC_ANCHOR",
                "severity": "error",
                "line": mapping.target_property,
                "message": f"Duplicate semantic anchor rows for {mapping.target_property}.",
                "trace": {
                    "acceptedLabels": mapping.accepted_labels,
                    "matchedRows": [row for row, _ in matches],
                },
                "reviewRequired": True,
            }
        )
        line = _unresolved_line_template(mapping.target_property)
        line["renderedLabelSv"] = mapping.rendered_label_sv
        line["source"]["semanticAnchor"] = mapping.source_semantic_label
        line["sourceLabel"] = matches[0][1]
        return line

    row_index, raw_label = matches[0]
    curr_col = WORKBOOK_PROFILE.value_current_column
    prev_col = WORKBOOK_PROFILE.value_previous_column
    current_ref = _cell_ref(curr_col, row_index)
    previous_ref = _cell_ref(prev_col, row_index)
    current_cell = kfa_sheet.row_cells.get(row_index, {}).get(curr_col)
    previous_cell = kfa_sheet.row_cells.get(row_index, {}).get(prev_col)

    current_decimal = _parse_decimal_cell(mapping.target_property, "current", current_ref, current_cell, diagnostics)
    previous_decimal = _parse_decimal_cell(mapping.target_property, "previous", previous_ref, previous_cell, diagnostics)

    status = "resolved" if current_decimal is not None and previous_decimal is not None else "unresolved"

    return {
        "valueCurrent": str(current_decimal) if current_decimal is not None else None,
        "valuePrevious": str(previous_decimal) if previous_decimal is not None else None,
        "status": status,
        "source": {
            "semanticAnchor": mapping.source_semantic_label,
            "sheet": WORKBOOK_PROFILE.kfa_sheet_name,
        },
        "renderedLabelSv": mapping.rendered_label_sv,
        "sourceLabel": raw_label,
        "trace": {
            "matchMethod": "normalized_label",
            "labelCell": _cell_ref(WORKBOOK_PROFILE.label_anchor_column, row_index),
            "valueCurrentCell": current_ref,
            "valuePreviousCell": previous_ref,
            "formulaCurrent": current_cell.formula if current_cell is not None else None,
            "formulaPrevious": previous_cell.formula if previous_cell is not None else None,
            "currentHasCachedValue": bool(current_cell.has_cached_value) if current_cell is not None else False,
            "previousHasCachedValue": bool(previous_cell.has_cached_value) if previous_cell is not None else False,
            "currentRawValue": current_cell.value_text if current_cell is not None else None,
            "previousRawValue": previous_cell.value_text if previous_cell is not None else None,
        },
    }


def _component_entry(
    line_key: str,
    label: str,
    kfa_sheet: SheetData,
    diagnostics: List[Dict[str, object]],
) -> Dict[str, object]:
    matches = _find_rows_for_labels(kfa_sheet, WORKBOOK_PROFILE.label_anchor_column, [label])
    if len(matches) == 0:
        diagnostics.append(
            {
                "code": "MISSING_LABEL",
                "severity": "error",
                "line": line_key,
                "message": f"Missing KFA component label '{label}'.",
                "trace": {"label": label},
                "reviewRequired": True,
            }
        )
        return {
            "label": label,
            "row": None,
            "status": "unresolved",
            "valueCurrent": None,
            "valuePrevious": None,
            "valueCurrentCell": None,
            "valuePreviousCell": None,
            "formulaCurrent": None,
            "formulaPrevious": None,
            "currentHasCachedValue": False,
            "previousHasCachedValue": False,
        }

    if len(matches) > 1:
        diagnostics.append(
            {
                "code": "DUPLICATE_SEMANTIC_ANCHOR",
                "severity": "error",
                "line": line_key,
                "message": f"Duplicate rows for component label '{label}'.",
                "trace": {"label": label, "matchedRows": [row for row, _ in matches]},
                "reviewRequired": True,
            }
        )
        return {
            "label": label,
            "row": None,
            "status": "unresolved",
            "valueCurrent": None,
            "valuePrevious": None,
            "valueCurrentCell": None,
            "valuePreviousCell": None,
            "formulaCurrent": None,
            "formulaPrevious": None,
            "currentHasCachedValue": False,
            "previousHasCachedValue": False,
        }

    row_index, source_label = matches[0]
    curr_col = WORKBOOK_PROFILE.value_current_column
    prev_col = WORKBOOK_PROFILE.value_previous_column
    current_ref = _cell_ref(curr_col, row_index)
    previous_ref = _cell_ref(prev_col, row_index)

    current_cell = kfa_sheet.row_cells.get(row_index, {}).get(curr_col)
    previous_cell = kfa_sheet.row_cells.get(row_index, {}).get(prev_col)
    current_decimal = _parse_decimal_cell(line_key, "current", current_ref, current_cell, diagnostics)
    previous_decimal = _parse_decimal_cell(line_key, "previous", previous_ref, previous_cell, diagnostics)

    return {
        "label": source_label,
        "row": row_index,
        "status": "resolved" if current_decimal is not None and previous_decimal is not None else "unresolved",
        "valueCurrent": str(current_decimal) if current_decimal is not None else None,
        "valuePrevious": str(previous_decimal) if previous_decimal is not None else None,
        "valueCurrentCell": current_ref,
        "valuePreviousCell": previous_ref,
        "formulaCurrent": current_cell.formula if current_cell is not None else None,
        "formulaPrevious": previous_cell.formula if previous_cell is not None else None,
        "currentHasCachedValue": bool(current_cell.has_cached_value) if current_cell is not None else False,
        "previousHasCachedValue": bool(previous_cell.has_cached_value) if previous_cell is not None else False,
    }


def _sum_optional(values: List[Optional[Decimal]]) -> Optional[Decimal]:
    if any(v is None for v in values):
        return None
    return sum(values, Decimal("0"))


def _extract_receivables_line(kfa_sheet: SheetData, diagnostics: List[Dict[str, object]]) -> Dict[str, object]:
    line_key = "changeInShortTermReceivables"
    component_entries = [
        _component_entry(line_key, label, kfa_sheet, diagnostics)
        for label in WORKBOOK_PROFILE.receivables_component_labels
    ]

    current_values = [Decimal(c["valueCurrent"]) if c["valueCurrent"] is not None else None for c in component_entries]
    previous_values = [Decimal(c["valuePrevious"]) if c["valuePrevious"] is not None else None for c in component_entries]

    current_sum = _sum_optional(current_values)
    previous_sum = _sum_optional(previous_values)

    status = "resolved" if current_sum is not None and previous_sum is not None else "unresolved"

    return {
        "valueCurrent": str(current_sum) if current_sum is not None else None,
        "valuePrevious": str(previous_sum) if previous_sum is not None else None,
        "status": status,
        "source": {
            "semanticAnchor": "Ökning(-)/Minskning(+) av varulager + Ökning(-)/Minskning(+) av rörelsefordringar",
            "sheet": WORKBOOK_PROFILE.kfa_sheet_name,
        },
        "renderedLabelSv": "Förändring av kortfristiga fordringar",
        "sourceLabel": " + ".join(c["label"] for c in component_entries if c["label"]),
        "trace": {
            "aggregationOperation": "sum",
            "components": component_entries,
            "componentRanges": {
                "current": "KFA!J19:J20",
                "previous": "KFA!L19:L20",
            },
        },
    }


def _find_layout_composed_cells(
    ar_sheet: SheetData,
    acquisition_row: Optional[int],
    sale_row: Optional[int],
) -> Dict[str, object]:
    current_matches: List[Tuple[int, CellData]] = []
    previous_matches: List[Tuple[int, CellData]] = []

    if acquisition_row is not None:
        needle = f"KFA!J{acquisition_row}"
        for row_index in sorted(ar_sheet.row_cells.keys()):
            cell = ar_sheet.row_cells[row_index].get("D")
            if cell is None or not cell.formula:
                continue
            normalized_formula = cell.formula.replace("$", "")
            if needle in normalized_formula:
                current_matches.append((row_index, cell))

    if acquisition_row is not None and sale_row is not None:
        needle_a = f"KFA!L{sale_row}"
        needle_b_prefixed = f"KFA!L{acquisition_row}"
        needle_b_range_tail = f":L{acquisition_row}"
        for row_index in sorted(ar_sheet.row_cells.keys()):
            cell = ar_sheet.row_cells[row_index].get("F")
            if cell is None or not cell.formula:
                continue
            normalized_formula = cell.formula.replace("$", "")
            if (
                needle_a in normalized_formula
                and (
                    needle_b_prefixed in normalized_formula
                    or needle_b_range_tail in normalized_formula
                )
            ):
                previous_matches.append((row_index, cell))

    return {
        "currentMatches": current_matches,
        "previousMatches": previous_matches,
    }


def _extract_intangible_composed_line(
    kfa_sheet: SheetData,
    ar_sheet: SheetData,
    diagnostics: List[Dict[str, object]],
) -> Dict[str, object]:
    line_key = "intangibleComposedInvestingCashFlow"
    sale_label, acquisition_label = WORKBOOK_PROFILE.intangible_component_labels
    sale_component = _component_entry(line_key, sale_label, kfa_sheet, diagnostics)
    acquisition_component = _component_entry(line_key, acquisition_label, kfa_sheet, diagnostics)

    current_decimal = Decimal(acquisition_component["valueCurrent"]) if acquisition_component["valueCurrent"] is not None else None

    previous_decimal = None
    if sale_component["valuePrevious"] is not None and acquisition_component["valuePrevious"] is not None:
        previous_decimal = Decimal(sale_component["valuePrevious"]) + Decimal(acquisition_component["valuePrevious"])

    layout_match = _find_layout_composed_cells(
        ar_sheet,
        acquisition_component["row"],
        sale_component["row"],
    )

    current_matches = layout_match["currentMatches"]
    previous_matches = layout_match["previousMatches"]

    current_layout = current_matches[0] if len(current_matches) == 1 else None
    previous_layout = previous_matches[0] if len(previous_matches) == 1 else None

    ambiguous_layout = len(current_matches) > 1 or len(previous_matches) > 1
    if ambiguous_layout:
        diagnostics.append(
            {
                "code": "AMBIGUOUS_AR_LAYOUT_COMPOSITION",
                "severity": "error",
                "line": line_key,
                "message": "ÅR Layout composition mapping is ambiguous for intangible cash flow line.",
                "trace": {
                    "currentMatches": [
                        {"sheet": WORKBOOK_PROFILE.ar_layout_sheet_name, "cell": _cell_ref("D", row_idx), "formula": cell.formula}
                        for row_idx, cell in current_matches
                    ],
                    "previousMatches": [
                        {"sheet": WORKBOOK_PROFILE.ar_layout_sheet_name, "cell": _cell_ref("F", row_idx), "formula": cell.formula}
                        for row_idx, cell in previous_matches
                    ],
                },
                "reviewRequired": True,
            }
        )
        current_decimal = None
        previous_decimal = None

    if current_layout is None or previous_layout is None:
        diagnostics.append(
            {
                "code": "MISSING_AR_LAYOUT_COMPOSITION",
                "severity": "error",
                "line": line_key,
                "message": "Could not locate ÅR Layout composed presentation cells for intangible cash flow line.",
                "trace": {
                    "expectedCurrentReference": acquisition_component["valueCurrentCell"],
                    "expectedPreviousComponents": [sale_component["valuePreviousCell"], acquisition_component["valuePreviousCell"]],
                },
                "reviewRequired": True,
            }
        )

    diagnostics.append(
        {
            "code": "COMPOSED_INVESTING_LABEL_REVIEW_REQUIRED",
            "severity": "warning",
            "line": line_key,
            "message": "Rendered label indicates pure sale while source semantics are composed for previous period.",
            "trace": {
                "renderedLabelSv": "Försäljning av immateriella anläggningstillgångar",
                "sourceSemantics": [sale_label, acquisition_label],
            },
            "reviewRequired": True,
        }
    )

    status = "resolved" if current_decimal is not None and previous_decimal is not None else "unresolved"

    trace: Dict[str, object] = {
        "aggregationOperation": {
            "current": "identity(acquisition_component)",
            "previous": "sum(sale_component, acquisition_component)",
        },
        "components": [sale_component, acquisition_component],
        "presentationSource": {
            "current": None,
            "previous": None,
        },
    }

    if current_layout is not None:
        row_idx, cell = current_layout
        trace["presentationSource"]["current"] = {
            "sheet": WORKBOOK_PROFILE.ar_layout_sheet_name,
            "cell": _cell_ref("D", row_idx),
            "formula": cell.formula,
            "cachedValue": cell.value_text if cell.has_cached_value else None,
            "hasCachedValue": cell.has_cached_value,
        }

    if previous_layout is not None:
        row_idx, cell = previous_layout
        trace["presentationSource"]["previous"] = {
            "sheet": WORKBOOK_PROFILE.ar_layout_sheet_name,
            "cell": _cell_ref("F", row_idx),
            "formula": cell.formula,
            "cachedValue": cell.value_text if cell.has_cached_value else None,
            "hasCachedValue": cell.has_cached_value,
        }

    return {
        "valueCurrent": str(current_decimal) if current_decimal is not None else None,
        "valuePrevious": str(previous_decimal) if previous_decimal is not None else None,
        "status": status,
        "source": {
            "semanticAnchor": "Försäljning av rörelsegren + Förvärv av immateriella anläggningstillgångar",
            "sheet": WORKBOOK_PROFILE.kfa_sheet_name,
        },
        "renderedLabelSv": "Försäljning av immateriella anläggningstillgångar",
        "sourceLabel": "Försäljning av rörelsegren / Förvärv av immateriella anläggningstillgångar",
        "trace": trace,
    }


def _extract_financing_detail_rows(kfa_sheet: SheetData, diagnostics: List[Dict[str, object]]) -> List[Dict[str, object]]:
    details: List[Dict[str, object]] = []
    for label in WORKBOOK_PROFILE.financing_detail_labels:
        details.append(_component_entry("financingCashFlowTotal", label, kfa_sheet, diagnostics))
    return details


def _decimal_from_line(line: Dict[str, object], key: str) -> Optional[Decimal]:
    value = line.get(key)
    if not isinstance(value, str):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _reconciliation_entry(
    name: str,
    period: str,
    expected: Optional[Decimal],
    authoritative: Optional[Decimal],
    diagnostics: List[Dict[str, object]],
) -> Dict[str, object]:
    if expected is None or authoritative is None:
        return {
            "name": name,
            "status": "not_computable",
            "expected": str(expected) if expected is not None else None,
            "authoritative": str(authoritative) if authoritative is not None else None,
            "difference": None,
            "withinTolerance": False,
            "tolerance": str(TOLERANCE),
        }

    diff = authoritative - expected
    within_tolerance = abs(diff) <= TOLERANCE
    if not within_tolerance:
        diagnostics.append(
            {
                "code": "RECONCILIATION_DIFFERENCE",
                "severity": "warning",
                "line": name,
                "message": f"Reconciliation difference exceeds tolerance for {name} ({period}).",
                "trace": {
                    "period": period,
                    "expected": str(expected),
                    "authoritative": str(authoritative),
                    "difference": str(diff),
                    "tolerance": str(TOLERANCE),
                },
                "reviewRequired": True,
            }
        )

    return {
        "name": name,
        "period": period,
        "status": "ok" if within_tolerance else "difference",
        "expected": str(expected),
        "authoritative": str(authoritative),
        "difference": str(diff),
        "withinTolerance": within_tolerance,
        "tolerance": str(TOLERANCE),
    }


def _extract_period_metadata(kfa_sheet: SheetData, diagnostics: List[Dict[str, object]]) -> Dict[str, object]:
    # Period labels come from workbook header structure cells (J7/J8 and L7/L8)
    # rather than line-item label anchors, by design.
    current_7 = kfa_sheet.row_cells.get(7, {}).get("J")
    current_8 = kfa_sheet.row_cells.get(8, {}).get("J")
    previous_7 = kfa_sheet.row_cells.get(7, {}).get("L")
    previous_8 = kfa_sheet.row_cells.get(8, {}).get("L")

    current_source = " ".join(
        part for part in [
            current_7.value_text.strip() if current_7 is not None else "",
            current_8.value_text.strip() if current_8 is not None else "",
        ]
        if part
    ) or None

    previous_source = " ".join(
        part for part in [
            previous_7.value_text.strip() if previous_7 is not None else "",
            previous_8.value_text.strip() if previous_8 is not None else "",
        ]
        if part
    ) or None

    diagnostics.append(
        {
            "code": "PERIOD_LABEL_REVIEW_REQUIRED",
            "severity": "warning",
            "line": "period",
            "message": "Rendered full period labels are unresolved from workbook source.",
            "trace": {
                "currentCells": ["J7", "J8"],
                "previousCells": ["L7", "L8"],
            },
            "reviewRequired": True,
        }
    )

    return {
        "currentPeriodSourceLabel": current_source,
        "previousPeriodSourceLabel": previous_source,
        "currentPeriodLabel": None,
        "previousPeriodLabel": None,
        "trace": {
            "currentPeriodSourceCells": {
                "J7": {
                    "value": current_7.value_text if current_7 is not None else None,
                    "formula": current_7.formula if current_7 is not None else None,
                    "hasCachedValue": current_7.has_cached_value if current_7 is not None else False,
                },
                "J8": {
                    "value": current_8.value_text if current_8 is not None else None,
                    "formula": current_8.formula if current_8 is not None else None,
                    "hasCachedValue": current_8.has_cached_value if current_8 is not None else False,
                },
            },
            "previousPeriodSourceCells": {
                "L7": {
                    "value": previous_7.value_text if previous_7 is not None else None,
                    "formula": previous_7.formula if previous_7 is not None else None,
                    "hasCachedValue": previous_7.has_cached_value if previous_7 is not None else False,
                },
                "L8": {
                    "value": previous_8.value_text if previous_8 is not None else None,
                    "formula": previous_8.formula if previous_8 is not None else None,
                    "hasCachedValue": previous_8.has_cached_value if previous_8 is not None else False,
                },
            },
        },
    }


def extract_cash_flow(
    workbook_path: Path,
    output_path: Path,
) -> Dict[str, object]:
    if not workbook_path.exists():
        raise ExtractionError(f"Workbook does not exist: {workbook_path}")

    diagnostics: List[Dict[str, object]] = []

    try:
        with zipfile.ZipFile(workbook_path) as zf:
            sheet_paths = _resolve_sheet_paths(zf)
            missing_sheets = [
                name
                for name in [WORKBOOK_PROFILE.kfa_sheet_name, WORKBOOK_PROFILE.ar_layout_sheet_name]
                if name not in sheet_paths
            ]
            if missing_sheets:
                raise ExtractionError(f"Missing required sheets: {', '.join(missing_sheets)}")

            shared_strings = _parse_shared_strings(zf)
            kfa_sheet = _read_sheet_data(zf, sheet_paths[WORKBOOK_PROFILE.kfa_sheet_name], shared_strings)
            ar_sheet = _read_sheet_data(zf, sheet_paths[WORKBOOK_PROFILE.ar_layout_sheet_name], shared_strings)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"Invalid or corrupt XLSX file: {workbook_path}") from exc

    lines: Dict[str, Dict[str, object]] = {}
    for mapping in WORKBOOK_PROFILE.single_line_mappings:
        lines[mapping.target_property] = _extract_single_line(mapping, kfa_sheet, diagnostics)

    lines["changeInShortTermReceivables"] = _extract_receivables_line(kfa_sheet, diagnostics)
    lines["intangibleComposedInvestingCashFlow"] = _extract_intangible_composed_line(kfa_sheet, ar_sheet, diagnostics)

    # Keep financing detail rows for traceability even when totals are zero.
    financing_details = _extract_financing_detail_rows(kfa_sheet, diagnostics)
    financing_line = lines["financingCashFlowTotal"]
    financing_current = _decimal_from_line(financing_line, "valueCurrent")
    financing_previous = _decimal_from_line(financing_line, "valuePrevious")
    financing_line_trace = financing_line.get("trace", {})
    financing_line_trace["detailRows"] = financing_details
    financing_line_trace["presentationPolicy"] = {
        "hideSectionWhenBothDisplayedPeriodsZero": True,
        "showSectionWhenAnyDisplayedPeriodNonZero": True,
        "neverHideSilently": True,
        "computedShouldDisplay": not (
            financing_current is not None
            and financing_previous is not None
            and financing_current == Decimal("0")
            and financing_previous == Decimal("0")
        ),
    }
    financing_line["trace"] = financing_line_trace

    diagnostics.append(
        {
            "code": "SEMANTIC_LABEL_REVIEW_REQUIRED",
            "severity": "warning",
            "line": "resultAfterFinancialItems",
            "message": "Source semantic concept differs from rendered signed-report label.",
            "trace": {
                "sourceSemanticLabel": "Resultat efter finansiella poster",
                "renderedLabelSv": "Rörelseresultat",
            },
            "reviewRequired": True,
        }
    )

    period = _extract_period_metadata(kfa_sheet, diagnostics)

    for required_key in REQUIRED_PROPERTIES:
        if required_key not in lines:
            lines[required_key] = _unresolved_line_template(required_key)
            diagnostics.append(
                {
                    "code": "MISSING_REQUIRED_PROPERTY",
                    "severity": "error",
                    "line": required_key,
                    "message": f"Required property missing from extraction result: {required_key}",
                    "trace": {},
                    "reviewRequired": True,
                }
            )

    unresolved_properties = [
        key
        for key in REQUIRED_PROPERTIES
        if lines.get(key, {}).get("status") != "resolved"
        or lines.get(key, {}).get("valueCurrent") is None
        or lines.get(key, {}).get("valuePrevious") is None
    ]

    operating_expected = _sum_optional(
        [
            _decimal_from_line(lines["operatingCashFlowBeforeWorkingCapital"], "valueCurrent"),
            _decimal_from_line(lines["changeInShortTermReceivables"], "valueCurrent"),
            _decimal_from_line(lines["changeInShortTermLiabilities"], "valueCurrent"),
        ]
    )
    operating_authoritative = _decimal_from_line(lines["operatingCashFlowTotal"], "valueCurrent")
    operating_expected_previous = _sum_optional(
        [
            _decimal_from_line(lines["operatingCashFlowBeforeWorkingCapital"], "valuePrevious"),
            _decimal_from_line(lines["changeInShortTermReceivables"], "valuePrevious"),
            _decimal_from_line(lines["changeInShortTermLiabilities"], "valuePrevious"),
        ]
    )
    operating_authoritative_previous = _decimal_from_line(lines["operatingCashFlowTotal"], "valuePrevious")

    # This subtotal intentionally reconciles only the fixed rendered contract lines.
    # Non-zero investing rows outside the contract should surface as a reconciliation difference.
    investing_expected = _sum_optional(
        [
            _decimal_from_line(lines["intangibleComposedInvestingCashFlow"], "valueCurrent"),
            _decimal_from_line(lines["investmentsTangibleAssets"], "valueCurrent"),
            _decimal_from_line(lines["investmentsFinancialAssets"], "valueCurrent"),
        ]
    )
    investing_authoritative = _decimal_from_line(lines["investingCashFlowTotal"], "valueCurrent")
    investing_expected_previous = _sum_optional(
        [
            _decimal_from_line(lines["intangibleComposedInvestingCashFlow"], "valuePrevious"),
            _decimal_from_line(lines["investmentsTangibleAssets"], "valuePrevious"),
            _decimal_from_line(lines["investmentsFinancialAssets"], "valuePrevious"),
        ]
    )
    investing_authoritative_previous = _decimal_from_line(lines["investingCashFlowTotal"], "valuePrevious")

    financing_detail_sum = _sum_optional(
        [Decimal(item["valueCurrent"]) if item.get("valueCurrent") is not None else None for item in financing_details]
    )
    financing_authoritative = _decimal_from_line(lines["financingCashFlowTotal"], "valueCurrent")
    financing_detail_sum_previous = _sum_optional(
        [Decimal(item["valuePrevious"]) if item.get("valuePrevious") is not None else None for item in financing_details]
    )
    financing_authoritative_previous = _decimal_from_line(lines["financingCashFlowTotal"], "valuePrevious")

    net_expected = _sum_optional(
        [
            _decimal_from_line(lines["operatingCashFlowTotal"], "valueCurrent"),
            _decimal_from_line(lines["investingCashFlowTotal"], "valueCurrent"),
            _decimal_from_line(lines["financingCashFlowTotal"], "valueCurrent"),
        ]
    )
    net_authoritative = _decimal_from_line(lines["netCashFlowForYear"], "valueCurrent")
    net_expected_previous = _sum_optional(
        [
            _decimal_from_line(lines["operatingCashFlowTotal"], "valuePrevious"),
            _decimal_from_line(lines["investingCashFlowTotal"], "valuePrevious"),
            _decimal_from_line(lines["financingCashFlowTotal"], "valuePrevious"),
        ]
    )
    net_authoritative_previous = _decimal_from_line(lines["netCashFlowForYear"], "valuePrevious")

    cash_bridge_expected = _sum_optional(
        [
            _decimal_from_line(lines["cashAtBeginning"], "valueCurrent"),
            _decimal_from_line(lines["netCashFlowForYear"], "valueCurrent"),
        ]
    )
    cash_bridge_authoritative = _decimal_from_line(lines["cashAtEnd"], "valueCurrent")
    cash_bridge_expected_previous = _sum_optional(
        [
            _decimal_from_line(lines["cashAtBeginning"], "valuePrevious"),
            _decimal_from_line(lines["netCashFlowForYear"], "valuePrevious"),
        ]
    )
    cash_bridge_authoritative_previous = _decimal_from_line(lines["cashAtEnd"], "valuePrevious")

    reconciliation = {
        "operatingSubtotal": {
            "current": _reconciliation_entry(
                "operatingSubtotal", "current", operating_expected, operating_authoritative, diagnostics
            ),
            "previous": _reconciliation_entry(
                "operatingSubtotal", "previous", operating_expected_previous, operating_authoritative_previous, diagnostics
            ),
        },
        "investingSubtotal": {
            "current": _reconciliation_entry(
                "investingSubtotal", "current", investing_expected, investing_authoritative, diagnostics
            ),
            "previous": _reconciliation_entry(
                "investingSubtotal", "previous", investing_expected_previous, investing_authoritative_previous, diagnostics
            ),
        },
        "financingSubtotal": {
            "current": _reconciliation_entry(
                "financingSubtotal", "current", financing_detail_sum, financing_authoritative, diagnostics
            ),
            "previous": _reconciliation_entry(
                "financingSubtotal", "previous", financing_detail_sum_previous, financing_authoritative_previous, diagnostics
            ),
        },
        "netCashFlow": {
            "current": _reconciliation_entry(
                "netCashFlow", "current", net_expected, net_authoritative, diagnostics
            ),
            "previous": _reconciliation_entry(
                "netCashFlow", "previous", net_expected_previous, net_authoritative_previous, diagnostics
            ),
        },
        "cashBridge": {
            "current": _reconciliation_entry(
                "cashBridge", "current", cash_bridge_expected, cash_bridge_authoritative, diagnostics
            ),
            "previous": _reconciliation_entry(
                "cashBridge", "previous", cash_bridge_expected_previous, cash_bridge_authoritative_previous, diagnostics
            ),
        },
    }

    for line_key in REQUIRED_PROPERTIES:
        line = lines[line_key]
        if line.get("valueCurrent") is None or line.get("valuePrevious") is None:
            diagnostics.append(
                {
                    "code": "MISSING_PERIOD_VALUE",
                    "severity": "error",
                    "line": line_key,
                    "message": "Current and previous period values must both be present.",
                    "trace": {
                        "valueCurrent": line.get("valueCurrent"),
                        "valuePrevious": line.get("valuePrevious"),
                    },
                    "reviewRequired": True,
                }
            )

    status = "ok"
    if unresolved_properties or any(d.get("reviewRequired") for d in diagnostics):
        status = "review_required"

    payload = {
        "schemaVersion": "1.0",
        "status": status,
        "source": {
            "file": _safe_source_path(workbook_path),
            "sheets": {
                "kfa": WORKBOOK_PROFILE.kfa_sheet_name,
                "arLayout": WORKBOOK_PROFILE.ar_layout_sheet_name,
            },
        },
        "extractionPolicy": {
            "currentPeriodColumn": WORKBOOK_PROFILE.value_current_column,
            "previousPeriodColumn": WORKBOOK_PROFILE.value_previous_column,
            "labelAnchorColumn": WORKBOOK_PROFILE.label_anchor_column,
            "normalization": "lowercase + whitespace fold + swedish character fold",
        },
        "period": period,
        "lines": lines,
        "reconciliation": reconciliation,
        "diagnostics": diagnostics,
        "unresolvedProperties": unresolved_properties,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def ensure_real_cash_flow_renderable(payload: Dict[str, object]) -> None:
    if payload.get("status") != "ok":
        raise ExtractionError("Cash-flow extraction is not renderable: overall status must be 'ok'.")

    lines = payload.get("lines")
    if not isinstance(lines, dict):
        raise ExtractionError("Cash-flow extraction is not renderable: missing lines object.")

    unresolved: List[str] = []
    for key in REQUIRED_PROPERTIES:
        line = lines.get(key)
        if not isinstance(line, dict):
            unresolved.append(key)
            continue
        if line.get("status") != "resolved":
            unresolved.append(key)
            continue
        if line.get("valueCurrent") is None or line.get("valuePrevious") is None:
            unresolved.append(key)

    if unresolved:
        raise ExtractionError(
            "Cash-flow extraction is not renderable: unresolved required values: "
            + ", ".join(unresolved)
        )

    period = payload.get("period")
    if not isinstance(period, dict):
        raise ExtractionError("Cash-flow extraction is not renderable: period metadata missing.")

    if not isinstance(period.get("currentPeriodLabel"), str) or not period.get("currentPeriodLabel"):
        raise ExtractionError("Cash-flow extraction is not renderable: currentPeriodLabel is unresolved.")
    if not isinstance(period.get("previousPeriodLabel"), str) or not period.get("previousPeriodLabel"):
        raise ExtractionError("Cash-flow extraction is not renderable: previousPeriodLabel is unresolved.")

    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        unresolved_semantic_codes = {
            "SEMANTIC_LABEL_REVIEW_REQUIRED",
            "COMPOSED_INVESTING_LABEL_REVIEW_REQUIRED",
        }
        for item in diagnostics:
            if isinstance(item, dict) and item.get("code") in unresolved_semantic_codes:
                raise ExtractionError(
                    "Cash-flow extraction is not renderable: unresolved semantic review diagnostics remain."
                )
