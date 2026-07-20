from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from balance_sheet_profile import BalanceSheetLineMapping, BalanceSheetWorkbookProfile, WORKBOOK_PROFILE

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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


def _ns(tag: str) -> str:
    return f"{{{MAIN_NS}}}{tag}"


def _safe_source_path(path: Path) -> str:
    if path.is_absolute():
        return path.name
    return path.as_posix()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized.strip().lower())


def _parse_decimal(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    shared_path = "xl/sharedStrings.xml"
    if shared_path not in zf.namelist():
        return []

    root = ET.fromstring(zf.read(shared_path))
    values: List[str] = []
    for si in root.findall(_ns("si")):
        text = "".join((t.text or "") for t in si.findall(f".//{_ns('t')}"))
        values.append(text.strip())
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


def _split_cell_ref(cell_ref: str) -> Tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_ref)
    if not match:
        raise ExtractionError(f"Unsupported cell reference format: {cell_ref}")
    return match.group(1), int(match.group(2))


def _read_sheet_data(zf: zipfile.ZipFile, sheet_path: str, shared_strings: List[str]) -> SheetData:
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
            cells[col] = CellData(value_text=value_text, formula=formula, has_cached_value=has_cached_value)
        row_cells[row_index] = cells

    return SheetData(row_cells=row_cells)


def _get_cell_data(sheet: SheetData, row_index: int, col: str) -> Optional[CellData]:
    return sheet.row_cells.get(row_index, {}).get(col)


def _build_sheet_path_map(zf: zipfile.ZipFile) -> Dict[str, str]:
    workbook_xml = "xl/workbook.xml"
    workbook_rels = "xl/_rels/workbook.xml.rels"
    if workbook_xml not in zf.namelist() or workbook_rels not in zf.namelist():
        raise ExtractionError("Invalid .xlsx structure: missing workbook XML metadata")

    wb_root = ET.fromstring(zf.read(workbook_xml))
    rel_root = ET.fromstring(zf.read(workbook_rels))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall(f"{{{REL_NS}}}Relationship")
    }

    sheet_paths: Dict[str, str] = {}
    sheets_node = wb_root.find(_ns("sheets"))
    if sheets_node is None:
        raise ExtractionError("Workbook has no sheets")

    for sheet in sheets_node.findall(_ns("sheet")):
        name = sheet.attrib.get("name")
        rid = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
        if not name or not rid or rid not in rel_map:
            continue
        path = rel_map[rid]
        if not path.startswith("xl/"):
            path = f"xl/{path}"
        sheet_paths[name] = path

    return sheet_paths


def _parse_workbook(workbook_path: Path, profile: BalanceSheetWorkbookProfile) -> Dict[str, SheetData]:
    if not workbook_path.exists():
        raise ExtractionError(f"Workbook does not exist: {workbook_path}")

    try:
        with zipfile.ZipFile(workbook_path) as zf:
            sheet_paths = _build_sheet_path_map(zf)
            shared_strings = _parse_shared_strings(zf)

            required_sheets = [
                profile.workbook_sheet_br,
                profile.workbook_sheet_equity,
                profile.workbook_sheet_income,
            ]
            parsed: Dict[str, SheetData] = {}
            for sheet_name in required_sheets:
                sheet_path = sheet_paths.get(sheet_name)
                if not sheet_path:
                    raise ExtractionError(f"Expected sheet not found: {sheet_name}")
                if sheet_path not in zf.namelist():
                    raise ExtractionError(f"Sheet XML not found for {sheet_name}: {sheet_path}")
                parsed[sheet_name] = _read_sheet_data(zf, sheet_path, shared_strings)

            return parsed
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"Invalid or corrupt XLSX file: {workbook_path}") from exc


def _row_snapshot(sheet: SheetData, row: int, cols: List[str]) -> Dict[str, object]:
    out: Dict[str, object] = {"row": row}
    for col in cols:
        cell = _get_cell_data(sheet, row, col)
        if cell is None:
            continue
        if cell.value_text != "":
            out[col] = cell.value_text
        if cell.formula:
            out[f"{col}Formula"] = cell.formula
    return out


def _surrounding_evidence(sheet: SheetData, row: int, cols: List[str]) -> List[Dict[str, object]]:
    evidence: List[Dict[str, object]] = []
    for idx in [row - 1, row, row + 1]:
        if idx < 1:
            continue
        snap = _row_snapshot(sheet, idx, cols)
        if len(snap) > 1:
            evidence.append(snap)
    return evidence


def _find_br_row(sheet: SheetData, mapping: BalanceSheetLineMapping) -> Tuple[Optional[int], Optional[str]]:
    accepted_codes = {code.strip().upper() for code in mapping.accepted_account_codes if code.strip()}
    accepted_labels = {_normalize_text(label) for label in mapping.accepted_labels if label.strip()}

    code_matches: List[int] = []
    for row in sorted(sheet.row_cells):
        code_cell = _get_cell_data(sheet, row, "A")
        if code_cell and code_cell.value_text.strip().upper() in accepted_codes:
            code_matches.append(row)

    if len(code_matches) == 1:
        return code_matches[0], "code_exact"
    if len(code_matches) > 1:
        refined = []
        for row in code_matches:
            label_cell = _get_cell_data(sheet, row, "B")
            if label_cell and _normalize_text(label_cell.value_text) in accepted_labels:
                refined.append(row)
        if len(refined) == 1:
            return refined[0], "code_exact+label_refine"
        return None, "ambiguous_code_match"

    label_matches: List[int] = []
    for row in sorted(sheet.row_cells):
        label_cell = _get_cell_data(sheet, row, "B")
        if label_cell and _normalize_text(label_cell.value_text) in accepted_labels:
            label_matches.append(row)

    if len(label_matches) == 1:
        return label_matches[0], "label_normalized"
    if len(label_matches) > 1:
        return None, "ambiguous_label_match"

    return None, "not_found"


def _find_br_anchor_anywhere(sheet: SheetData, mapping: BalanceSheetLineMapping) -> Optional[int]:
    accepted_codes = {code.strip().upper() for code in mapping.accepted_account_codes if code.strip()}
    accepted_labels = {_normalize_text(label) for label in mapping.accepted_labels if label.strip()}

    for row in sorted(sheet.row_cells):
        for code_col, label_col in [("A", "B"), ("G", "H")]:
            code_cell = _get_cell_data(sheet, row, code_col)
            label_cell = _get_cell_data(sheet, row, label_col)
            code_value = code_cell.value_text.strip().upper() if code_cell else ""
            label_value = _normalize_text(label_cell.value_text) if label_cell else ""
            if code_value in accepted_codes or label_value in accepted_labels:
                return row
    return None


def _decimal_to_str(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(value, "f")


def _cell_trace(sheet_name: str, row: int, code_cell: CellData, label_cell: Optional[CellData], value_cell: Optional[CellData], method: str) -> Dict[str, object]:
    value_decimal = _parse_decimal(value_cell.value_text) if value_cell else None
    return {
        "sheet": sheet_name,
        "accountCode": code_cell.value_text if code_cell else None,
        "sourceLabel": label_cell.value_text if label_cell else None,
        "labelCell": f"B{row}" if label_cell else None,
        "valueCell": f"E{row}",
        "formula": value_cell.formula if value_cell else None,
        "cachedNumericValue": _decimal_to_str(value_decimal),
        "matchMethod": method,
    }


def _classify_equity_row(code: str, description: str) -> str:
    code_u = (code or "").strip().upper()
    desc_n = _normalize_text(description)

    if code_u == "20SE" or "total equity" in desc_n:
        return "grand total"
    if code_u.endswith("_IMPS") or desc_n.startswith("import:"):
        return "technical import row"
    if code_u.endswith("_IMPD") or desc_n.startswith("difference:"):
        return "technical difference row"
    if desc_n.startswith("ob"):
        return "opening-balance row"
    if "organisational change" in desc_n:
        return "movement/detail row"
    if any(token in desc_n for token in [
        "write-ups",
        "write-downs",
        "dividends",
        "merger result",
        "group contribution",
        "def. tax",
        "appropriation",
        "changes in restricted and non-restr",
    ]):
        return "movement/detail row"
    if re.fullmatch(r"20\d{2}", code_u):
        return "canonical output/account-total row"
    if re.fullmatch(r"20\d{4,}", code_u):
        return "movement/detail row"
    return "unknown"


def _is_non_zero_numeric(value_text: str) -> bool:
    parsed = _parse_decimal(value_text)
    return parsed is not None and parsed != 0


def _extract_income_statement_hint(rr_sheet: SheetData) -> Optional[str]:
    for row in sorted(rr_sheet.row_cells):
        label = _get_cell_data(rr_sheet, row, "A")
        if not label:
            continue
        if _normalize_text(label.value_text) == _normalize_text("Årets resultat"):
            value_cell = _get_cell_data(rr_sheet, row, "D")
            if value_cell and value_cell.value_text.strip() != "":
                return value_cell.value_text.strip()
    return None


def _extract_br_2099_hint(br_sheet: SheetData) -> Optional[str]:
    for row in sorted(br_sheet.row_cells):
        code_cell = _get_cell_data(br_sheet, row, "G")
        if not code_cell:
            continue
        if code_cell.value_text.strip() == "2099":
            hint_cell = _get_cell_data(br_sheet, row, "I")
            if hint_cell and hint_cell.value_text.strip() != "":
                return hint_cell.value_text.strip()
    return None


def _line_unresolved(trace: Dict[str, object]) -> Dict[str, object]:
    return {
        "value": None,
        "status": "unresolved",
        "trace": trace,
    }


def _line_resolved(value: Decimal, trace: Dict[str, object]) -> Dict[str, object]:
    return {
        "value": _decimal_to_str(value),
        "status": "resolved",
        "trace": trace,
    }


def _canonical_property_by_account(profile: BalanceSheetWorkbookProfile) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for code, prop in profile.canonical_equity_account_mappings.items():
        if prop == "equitySheetTotal":
            continue
        out[code.upper()] = prop
    for code, prop in profile.additional_canonical_equity_mappings.items():
        if prop == "equitySheetTotal":
            continue
        out[code.upper()] = prop
    return out


def _resolve_br_subtotal_line(
    br_sheet: SheetData,
    profile: BalanceSheetWorkbookProfile,
    target_property: str,
    accepted_codes: List[str],
    accepted_labels: List[str],
) -> Optional[Dict[str, object]]:
    mapping = BalanceSheetLineMapping(target_property=target_property, accepted_account_codes=accepted_codes, accepted_labels=accepted_labels)
    matched_row, match_method = _find_br_row(br_sheet, mapping)
    if matched_row is None:
        if match_method and match_method != "not_found":
            return _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_br,
                    "accountCode": None,
                    "sourceLabel": None,
                    "labelCell": None,
                    "valueCell": None,
                    "formula": None,
                    "cachedNumericValue": None,
                    "matchMethod": match_method,
                    "source": "authoritative BR Output",
                }
            )
        return None

    code_cell = _get_cell_data(br_sheet, matched_row, profile.account_code_column)
    label_cell = _get_cell_data(br_sheet, matched_row, profile.label_anchor_column)
    value_cell = _get_cell_data(br_sheet, matched_row, profile.value_columns["output"])
    trace = _cell_trace(profile.workbook_sheet_br, matched_row, code_cell, label_cell, value_cell, match_method)
    trace["source"] = "authoritative BR Output"

    if value_cell is None or value_cell.value_text.strip() == "":
        trace["surroundingEvidence"] = _surrounding_evidence(br_sheet, matched_row, ["A", "B", "C", "D", "E", "G", "H", "I", "J"])
        return _line_unresolved(trace)

    parsed = _parse_decimal(value_cell.value_text)
    if parsed is None:
        trace["surroundingEvidence"] = _surrounding_evidence(br_sheet, matched_row, ["A", "B", "C", "D", "E"])
        return _line_unresolved(trace)
    return _line_resolved(parsed, trace)


def _derive_equity_subtotal_from_components(
    *,
    profile: BalanceSheetWorkbookProfile,
    target_property: str,
    component_accounts: List[str],
    lines: Dict[str, Dict[str, object]],
    property_by_account: Dict[str, str],
) -> Dict[str, object]:
    component_trace: List[Dict[str, object]] = []
    subtotal = Decimal("0")

    for account_code in component_accounts:
        code = account_code.upper()
        property_name = property_by_account.get(code)
        if not property_name:
            return _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_equity,
                    "matchMethod": "configured_components",
                    "source": "component derivation",
                    "reason": "configured account has no canonical property mapping",
                    "componentAccounts": component_accounts,
                    "missingAccountCode": account_code,
                    "components": component_trace,
                }
            )

        line = lines.get(property_name)
        value_text = line.get("value") if isinstance(line, dict) else None
        parsed = _parse_decimal(value_text) if value_text is not None else None
        component_trace.append(
            {
                "accountCode": account_code,
                "property": property_name,
                "status": line.get("status") if isinstance(line, dict) else None,
                "value": _decimal_to_str(parsed),
                "sourceValueCell": (line.get("trace") or {}).get("valueCell") if isinstance(line, dict) else None,
            }
        )

        if not isinstance(line, dict) or line.get("status") != "resolved" or parsed is None:
            return _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_equity,
                    "matchMethod": "configured_components",
                    "source": "component derivation",
                    "reason": "required component unresolved",
                    "componentAccounts": component_accounts,
                    "components": component_trace,
                }
            )

        subtotal += parsed

    return _line_resolved(
        subtotal,
        {
            "sheet": profile.workbook_sheet_equity,
            "matchMethod": "configured_components",
            "source": "component derivation",
            "componentAccounts": component_accounts,
            "components": component_trace,
        },
    )


def extract_balance_sheet(
    workbook_path: Path,
    output_path: Path,
    profile: BalanceSheetWorkbookProfile = WORKBOOK_PROFILE,
) -> Dict[str, object]:
    sheets = _parse_workbook(workbook_path, profile)
    br_sheet = sheets[profile.workbook_sheet_br]
    equity_sheet = sheets[profile.workbook_sheet_equity]
    rr_sheet = sheets[profile.workbook_sheet_income]

    diagnostics: List[Dict[str, object]] = []
    lines: Dict[str, Dict[str, object]] = {}
    unresolved_found = False

    for mapping in profile.line_mappings:
        matched_row, match_method = _find_br_row(br_sheet, mapping)

        if matched_row is None:
            unresolved_found = True
            anchor_row = _find_br_anchor_anywhere(br_sheet, mapping)
            trace = {
                "sheet": profile.workbook_sheet_br,
                "accountCode": None,
                "sourceLabel": None,
                "labelCell": None,
                "valueCell": None,
                "formula": None,
                "cachedNumericValue": None,
                "matchMethod": match_method,
                "anchorRow": anchor_row,
                "surroundingEvidence": _surrounding_evidence(br_sheet, anchor_row, ["A", "B", "C", "D", "E", "G", "H", "I", "J"]) if anchor_row else [],
            }
            lines[mapping.target_property] = _line_unresolved(trace)
            diagnostics.append(
                {
                    "code": "BR_LINE_UNRESOLVED",
                    "severity": "review_required",
                    "message": f"Unresolved BR line for {mapping.target_property}: {match_method}.",
                    "context": {"targetProperty": mapping.target_property},
                }
            )
            continue

        code_cell = _get_cell_data(br_sheet, matched_row, profile.account_code_column)
        label_cell = _get_cell_data(br_sheet, matched_row, profile.label_anchor_column)
        value_cell = _get_cell_data(br_sheet, matched_row, profile.value_columns["output"])

        trace = _cell_trace(profile.workbook_sheet_br, matched_row, code_cell, label_cell, value_cell, match_method)

        if value_cell is None or value_cell.value_text.strip() == "":
            unresolved_found = True
            trace["surroundingEvidence"] = _surrounding_evidence(br_sheet, matched_row, ["A", "B", "C", "D", "E", "G", "H", "I", "J"])
            lines[mapping.target_property] = _line_unresolved(trace)
            diagnostics.append(
                {
                    "code": "BR_OUTPUT_BLANK",
                    "severity": "review_required",
                    "message": f"BR Output column E is blank for required property {mapping.target_property}.",
                    "context": {
                        "targetProperty": mapping.target_property,
                        "valueCell": f"E{matched_row}",
                        "accountCode": code_cell.value_text if code_cell else None,
                    },
                }
            )
            continue

        value = _parse_decimal(value_cell.value_text)
        if value is None:
            unresolved_found = True
            trace["surroundingEvidence"] = _surrounding_evidence(br_sheet, matched_row, ["A", "B", "C", "D", "E"])
            lines[mapping.target_property] = _line_unresolved(trace)
            diagnostics.append(
                {
                    "code": "BR_OUTPUT_NON_NUMERIC",
                    "severity": "review_required",
                    "message": f"Non-numeric BR Output value for {mapping.target_property}.",
                    "context": {"targetProperty": mapping.target_property, "valueCell": f"E{matched_row}"},
                }
            )
            continue

        lines[mapping.target_property] = _line_resolved(value, trace)

    equity_rows: List[Dict[str, object]] = []
    excluded_rows: List[Dict[str, object]] = []
    canonical_rows_by_code: Dict[str, Dict[str, object]] = {}
    canonical_duplicate_rows_by_code: Dict[str, List[Dict[str, object]]] = {}

    for row in sorted(equity_sheet.row_cells):
        code_cell = _get_cell_data(equity_sheet, row, "A")
        desc_cell = _get_cell_data(equity_sheet, row, "B")
        prev_cell = _get_cell_data(equity_sheet, row, "C")
        curr_cell = _get_cell_data(equity_sheet, row, "D")

        code = code_cell.value_text.strip() if code_cell else ""
        description = desc_cell.value_text.strip() if desc_cell else ""
        prev = prev_cell.value_text.strip() if prev_cell else ""
        curr = curr_cell.value_text.strip() if curr_cell else ""

        if not (code or description or prev or curr):
            continue

        classification = _classify_equity_row(code, description)
        row_payload = {
            "sheet": profile.workbook_sheet_equity,
            "row": row,
            "code": code,
            "description": description,
            "codeCell": f"A{row}" if code else None,
            "descriptionCell": f"B{row}" if description else None,
            "previousCell": f"C{row}" if prev_cell else None,
            "previousValue": prev if prev != "" else None,
            "currentCell": f"D{row}" if curr_cell else None,
            "currentValue": curr if curr != "" else None,
            "currentFormula": curr_cell.formula if curr_cell else None,
            "classification": classification,
        }
        equity_rows.append(row_payload)

        if classification == "canonical output/account-total row":
            canonical_code = code.upper()
            if canonical_code in canonical_rows_by_code:
                canonical_duplicate_rows_by_code.setdefault(canonical_code, [canonical_rows_by_code[canonical_code]]).append(row_payload)
            else:
                canonical_rows_by_code[canonical_code] = row_payload
        elif classification in {
            "opening-balance row",
            "movement/detail row",
            "technical import row",
            "technical difference row",
        }:
            excluded_rows.append(row_payload)

    mapped_accounts: List[Dict[str, object]] = []
    unmapped_accounts: List[Dict[str, object]] = []

    canonical_property_by_account = _canonical_property_by_account(profile)

    for account_code, property_name in canonical_property_by_account.items():

        duplicate_rows = canonical_duplicate_rows_by_code.get(account_code)
        if duplicate_rows:
            unresolved_found = True
            lines[property_name] = _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_equity,
                    "accountCode": account_code,
                    "matchMethod": "duplicate_code",
                    "duplicateRows": duplicate_rows,
                }
            )
            diagnostics.append(
                {
                    "code": "EQUITY_CANONICAL_DUPLICATE",
                    "severity": "review_required",
                    "message": f"Duplicate canonical equity rows found for {property_name} ({account_code}).",
                    "context": {
                        "property": property_name,
                        "accountCode": account_code,
                        "duplicateRows": duplicate_rows,
                    },
                }
            )
            continue

        canonical = canonical_rows_by_code.get(account_code)
        method = "code_exact"
        if canonical is None:
            aliases = {_normalize_text(alias) for alias in profile.canonical_equity_description_aliases.get(property_name, [])}
            for row_payload in equity_rows:
                if row_payload["classification"] != "canonical output/account-total row":
                    continue
                if _normalize_text(row_payload.get("description") or "") in aliases:
                    canonical = row_payload
                    method = "description_alias"
                    break

        if canonical is None:
            unresolved_found = True
            lines[property_name] = _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_equity,
                    "accountCode": account_code,
                    "sourceLabel": None,
                    "labelCell": None,
                    "valueCell": None,
                    "formula": None,
                    "cachedNumericValue": None,
                    "matchMethod": "not_found",
                }
            )
            diagnostics.append(
                {
                    "code": "EQUITY_CANONICAL_NOT_FOUND",
                    "severity": "review_required",
                    "message": f"Canonical equity row not found for {property_name} ({account_code}).",
                    "context": {"property": property_name, "accountCode": account_code},
                }
            )
            continue

        current_value = canonical.get("currentValue")
        parsed_current = _parse_decimal(current_value or "")
        mapped_accounts.append(
            {
                "property": property_name,
                "accountCode": canonical.get("code"),
                "description": canonical.get("description"),
                "currentCell": canonical.get("currentCell"),
                "currentValue": _decimal_to_str(parsed_current),
                "matchMethod": method,
                "classification": canonical.get("classification"),
            }
        )

        if parsed_current is None:
            unresolved_found = True
            lines[property_name] = _line_unresolved(
                {
                    "sheet": profile.workbook_sheet_equity,
                    "accountCode": canonical.get("code"),
                    "sourceLabel": canonical.get("description"),
                    "labelCell": canonical.get("descriptionCell"),
                    "valueCell": canonical.get("currentCell"),
                    "formula": canonical.get("currentFormula"),
                    "cachedNumericValue": None,
                    "matchMethod": method,
                }
            )
            diagnostics.append(
                {
                    "code": "EQUITY_CANONICAL_BLANK",
                    "severity": "review_required",
                    "message": f"Canonical equity row has blank current value for {property_name}.",
                    "context": {"property": property_name, "accountCode": canonical.get("code")},
                }
            )
        else:
            lines[property_name] = _line_resolved(
                parsed_current,
                {
                    "sheet": profile.workbook_sheet_equity,
                    "accountCode": canonical.get("code"),
                    "sourceLabel": canonical.get("description"),
                    "labelCell": canonical.get("descriptionCell"),
                    "valueCell": canonical.get("currentCell"),
                    "formula": canonical.get("currentFormula"),
                    "cachedNumericValue": _decimal_to_str(parsed_current),
                    "matchMethod": method,
                },
            )

    # Prevent double counting by explicitly recording non-canonical rows in families where canonical rows exist.
    for family_code in ["2081", "2086", "2091"]:
        canonical = canonical_rows_by_code.get(family_code)
        if not canonical:
            continue
        family_rows = [
            row_payload
            for row_payload in equity_rows
            if (row_payload.get("code") or "").startswith(family_code)
            and row_payload.get("code") != family_code
            and _is_non_zero_numeric(row_payload.get("currentValue") or "")
        ]
        if family_rows:
            diagnostics.append(
                {
                    "code": "EQUITY_DOUBLE_COUNT_PROTECTION",
                    "severity": "info",
                    "message": f"Excluded non-canonical rows from {family_code} aggregation to prevent double counting.",
                    "context": {
                        "canonicalRow": canonical,
                        "excludedNonCanonicalRows": family_rows,
                    },
                }
            )

    covered_codes = set(canonical_property_by_account.keys())

    for row_payload in equity_rows:
        if row_payload["classification"] != "canonical output/account-total row":
            continue
        code = (row_payload.get("code") or "").upper()
        if code in covered_codes:
            continue
        if code == "20SE":
            continue

        current_value = row_payload.get("currentValue") or ""
        parsed_current = _parse_decimal(current_value)
        unmapped = {
            "accountCode": row_payload.get("code"),
            "description": row_payload.get("description"),
            "cell": row_payload.get("currentCell"),
            "value": _decimal_to_str(parsed_current),
            "classification": row_payload.get("classification"),
        }
        if parsed_current is not None and parsed_current != 0:
            unresolved_found = True
            unmapped_accounts.append(unmapped)
            diagnostics.append(
                {
                    "code": "UNMAPPED_EQUITY_ACCOUNT_NON_ZERO",
                    "severity": "review_required",
                    "message": "Non-zero canonical equity account is not covered by mappings.",
                    "context": unmapped,
                }
            )

    property_by_account = canonical_property_by_account

    restricted_line = _resolve_br_subtotal_line(
        br_sheet,
        profile,
        "totalRestrictedEquity",
        profile.restricted_equity_br_codes,
        profile.restricted_equity_br_labels,
    )
    if restricted_line is None:
        restricted_line = _derive_equity_subtotal_from_components(
            profile=profile,
            target_property="totalRestrictedEquity",
            component_accounts=profile.restricted_equity_component_accounts,
            lines=lines,
            property_by_account=property_by_account,
        )
    lines["totalRestrictedEquity"] = restricted_line
    if restricted_line.get("status") != "resolved":
        unresolved_found = True
        diagnostics.append(
            {
                "code": "RESTRICTED_EQUITY_SUBTOTAL_UNRESOLVED",
                "severity": "review_required",
                "message": "Could not resolve totalRestrictedEquity from authoritative BR or configured components.",
                "context": {"trace": restricted_line.get("trace")},
            }
        )

    unrestricted_line = _resolve_br_subtotal_line(
        br_sheet,
        profile,
        "totalUnrestrictedEquity",
        profile.unrestricted_equity_br_codes,
        profile.unrestricted_equity_br_labels,
    )
    if unrestricted_line is None:
        unrestricted_line = _derive_equity_subtotal_from_components(
            profile=profile,
            target_property="totalUnrestrictedEquity",
            component_accounts=profile.unrestricted_equity_component_accounts,
            lines=lines,
            property_by_account=property_by_account,
        )
    lines["totalUnrestrictedEquity"] = unrestricted_line
    if unrestricted_line.get("status") != "resolved":
        unresolved_found = True
        diagnostics.append(
            {
                "code": "UNRESTRICTED_EQUITY_SUBTOTAL_UNRESOLVED",
                "severity": "review_required",
                "message": "Could not resolve totalUnrestrictedEquity from authoritative BR or configured components.",
                "context": {"trace": unrestricted_line.get("trace")},
            }
        )

    br_total_equity_line = lines.get("totalEquity")
    br_total_equity = _parse_decimal(br_total_equity_line["value"]) if br_total_equity_line and br_total_equity_line["value"] is not None else None

    equity_sheet_total_row = next(
        (row_payload for row_payload in equity_rows if (row_payload.get("code") or "").upper() == "20SE"),
        None,
    )
    equity_sheet_total = _parse_decimal((equity_sheet_total_row or {}).get("currentValue") or "")
    difference: Optional[Decimal] = None
    if br_total_equity is not None and equity_sheet_total is not None:
        difference = br_total_equity - equity_sheet_total
        if abs(difference) > profile.decimal_tolerance:
            unresolved_found = True
            diagnostics.append(
                {
                    "code": "TOTAL_EQUITY_RECONCILIATION_MISMATCH",
                    "severity": "review_required",
                    "message": "BR total equity and equity-sheet total differ beyond tolerance.",
                    "context": {
                        "brTotalEquity": _decimal_to_str(br_total_equity),
                        "equitySheetTotal": _decimal_to_str(equity_sheet_total),
                        "difference": _decimal_to_str(difference),
                        "tolerance": _decimal_to_str(profile.decimal_tolerance),
                    },
                }
            )

    income_statement_profit_hint = _extract_income_statement_hint(rr_sheet)
    br_2099_diagnostic_hint = _extract_br_2099_hint(br_sheet)

    # Enforce explicit 2099 blank behavior hints.
    if lines.get("profitForYear", {}).get("status") == "unresolved":
        diagnostics.append(
            {
                "code": "PROFIT_FOR_YEAR_HINTS",
                "severity": "review_required",
                "message": "profitForYear unresolved: providing reconciliation hints only.",
                "context": {
                    "incomeStatementProfitHint": income_statement_profit_hint,
                    "br2099DiagnosticHint": br_2099_diagnostic_hint,
                },
            }
        )

    unresolved_found = True
    diagnostics.append(
        {
            "code": "BALANCE_DATE_LABEL_UNRESOLVED",
            "severity": "review_required",
            "message": "balanceDateLabel extraction is not implemented for workbook-driven extraction.",
            "context": {
                "field": "balanceDateLabel",
                "policy": "keep explicit null and block status=ok until validated metadata adapter is implemented",
            },
        }
    )

    status = "review_required" if unresolved_found or any(d["severity"] == "review_required" for d in diagnostics) else "ok"

    payload: Dict[str, object] = {
        "schemaVersion": "1.0",
        "status": status,
        "source": {
            "file": _safe_source_path(workbook_path),
            "sheets": {
                "balanceSheet": profile.workbook_sheet_br,
                "equity": profile.workbook_sheet_equity,
                "incomeStatement": profile.workbook_sheet_income,
            },
        },
        "balanceDateLabel": None,
        "lines": lines,
        "equity": {
            "mappedAccounts": mapped_accounts,
            "unmappedAccounts": unmapped_accounts,
            "excludedRows": excluded_rows,
            "allRows": equity_rows,
        },
        "reconciliation": {
            "brTotalEquity": _decimal_to_str(br_total_equity),
            "equitySheetTotal": _decimal_to_str(equity_sheet_total),
            "difference": _decimal_to_str(difference),
            "tolerance": _decimal_to_str(profile.decimal_tolerance),
            "incomeStatementProfitHint": income_statement_profit_hint,
            "br2099DiagnosticHint": br_2099_diagnostic_hint,
        },
        "diagnostics": diagnostics,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def ensure_real_balance_sheet_renderable(extraction_payload: Dict[str, object]) -> None:
    status = extraction_payload.get("status")
    if status != "ok":
        raise ExtractionError(
            "Real balance-sheet rendering is blocked because extraction status is not ok. "
            f"Current status: {status!r}."
        )

    lines = extraction_payload.get("lines")
    if not isinstance(lines, dict):
        raise ExtractionError("Extraction payload is missing 'lines' object.")

    unresolved = [key for key, value in lines.items() if isinstance(value, dict) and value.get("status") != "resolved"]
    if unresolved:
        raise ExtractionError(
            "Real balance-sheet rendering is blocked because some lines are unresolved: "
            + ", ".join(sorted(unresolved))
        )
