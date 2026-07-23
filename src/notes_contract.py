from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from notes_workbook_extractor import raw_notes_workbook_contract_json_bytes
from report_metadata import ReportMetadata, load_report_metadata


class NotesContractError(Exception):
    pass


IDENTITY_MODE_METADATA_ONLY = "metadata_only"
IDENTITY_MODE_APPROVED_ANCHOR = "approved_anchor"

ALLOWED_RANGE_DISPOSITIONS = {
    "render_content",
    "supporting_evidence",
    "reconciliation_evidence",
    "excluded_internal_template_content",
}
ALLOWED_RENDER_AUTHORITY_MODES = {
    "direct_workbook",
    "hybrid_workbook_preview_override",
    "full_note_preview_override",
}


CANONICAL_NOTE_TITLES = [
    "Redovisnings- och värderingsprinciper",
    "Nettoomsättningens fördelning",
    "Arvode till revisorer",
    "Leasingavtal",
    "Anställda och personalkostnader",
    "Övriga rörelsekostnader",
    "Övriga ränteintäkter och liknande resultatposter",
    "Räntekostnader och liknande resultatposter",
    "Bokslutsdispositioner",
    "Aktuell och uppskjuten skatt",
    "Goodwill",
    "Inventarier, verktyg och installationer",
    "Andelar i koncernföretag",
    "Specifikation andelar i koncernföretag",
    "Andra långfristiga värdepappersinnehav",
    "Andra långfristiga fordringar",
    "Övriga fordringar",
    "Upparbetad men ej fakturerad intäkt",
    "Förutbetalda kostnader och upplupna intäkter",
    "Antal aktier och kvotvärde",
    "Disposition av vinst eller förlust",
    "Likvida medel",
    "Upplupna kostnader och förutbetalda intäkter",
    "Räntor och utdelningar",
    "Justering för poster som inte ingår i kassaflödet",
    "Ställda säkerheter",
    "Transaktioner med närstående",
    "Väsentliga händelser efter räkenskapsårets slut",
]


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def semantic_notes_contract_json_bytes(contract: Dict[str, Any]) -> bytes:
    return _canonical_json_bytes(contract)


def _safe_source_path(path: Path) -> str:
    return path.name if path.is_absolute() else path.as_posix()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_mapping_policy(mapping_path: Path) -> Dict[str, Any]:
    if not mapping_path.exists():
        raise NotesContractError(f"Mapping file does not exist: {mapping_path}")
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotesContractError(f"Invalid mapping JSON: {mapping_path}") from exc
    if not isinstance(payload, dict):
        raise NotesContractError("Mapping policy must be a JSON object")
    return payload


def _load_management_contract(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.exists():
        raise NotesContractError(f"Management contract does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotesContractError(f"Invalid management contract JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise NotesContractError("Management contract must be a JSON object")
    return payload


def _identity_policy(mapping_policy: Dict[str, Any]) -> Dict[str, Any]:
    raw = mapping_policy.get("reportingEntityIdentity")
    if not isinstance(raw, dict):
        return {
            "companyName": {
                "authority": "metadata",
                "workbookEvidenceMode": IDENTITY_MODE_METADATA_ONLY,
            },
            "organizationNumber": {
                "authority": "metadata",
                "workbookEvidenceMode": IDENTITY_MODE_METADATA_ONLY,
                "diagnosticCode": "WORKBOOK_REPORTING_ENTITY_ORG_NUMBER_NOT_PRESENT",
            },
        }
    return raw


def _mapped_range_content_policy(mapping_policy: Dict[str, Any]) -> Dict[str, bool]:
    raw = mapping_policy.get("mappedRangeContentPolicy")
    if not isinstance(raw, dict):
        return {
            "failOnMeaningfulComments": True,
            "failOnMeaningfulObjects": True,
        }
    return {
        "failOnMeaningfulComments": bool(raw.get("failOnMeaningfulComments", True)),
        "failOnMeaningfulObjects": bool(raw.get("failOnMeaningfulObjects", True)),
    }


def _unsupported_content_allowlist(mapping_policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    policy = mapping_policy.get("unsupportedContentPolicy")
    if not isinstance(policy, dict):
        return []
    entries = policy.get("allowlist")
    if not isinstance(entries, list):
        return []
    out: List[Dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise NotesContractError("unsupportedContentPolicy.allowlist entries must be objects")
        construct_type = entry.get("constructType")
        worksheet = entry.get("worksheet")
        if not isinstance(construct_type, str) or not isinstance(worksheet, str):
            raise NotesContractError("Allowlist entry requires constructType and worksheet")
        normalized = dict(entry)
        normalized.setdefault("id", f"allowlist_{idx}")
        normalized.setdefault("requiresPresence", True)
        normalized.setdefault("scope", "any")
        normalized.setdefault("diagnosticCode", "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED")
        out.append(normalized)
    return out


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _comment_allowlist_match(comment: Dict[str, Any], entry: Dict[str, Any]) -> Tuple[bool, str]:
    if entry.get("constructType") != "comment":
        return False, "constructType mismatch"
    if entry.get("worksheet") != comment.get("sheet"):
        return False, "worksheet mismatch"
    if entry.get("coordinate") != comment.get("coordinate"):
        return False, "coordinate mismatch"

    text = comment.get("text")
    if not isinstance(text, str):
        text = ""
    expected_text = entry.get("expectedText")
    expected_sha = entry.get("expectedSha256")

    if isinstance(expected_text, str) and text != expected_text:
        return False, "expectedText mismatch"
    if isinstance(expected_sha, str) and _sha256_text(text) != expected_sha:
        return False, "expectedSha256 mismatch"

    return True, "match"


def _object_allowlist_match(obj: Dict[str, Any], entry: Dict[str, Any]) -> Tuple[bool, str]:
    if entry.get("constructType") != "object_relationship":
        return False, "constructType mismatch"
    if entry.get("worksheet") != obj.get("sheet"):
        return False, "worksheet mismatch"

    rel = obj.get("relationship")
    if not isinstance(rel, dict):
        return False, "relationship missing"

    for key in ("relationshipId", "relationshipType", "target", "type"):
        expected = entry.get(key)
        if isinstance(expected, str) and rel.get(key) != expected:
            return False, f"{key} mismatch"
    return True, "match"


def _worksheet_map(raw_contract: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    worksheets = raw_contract.get("worksheets")
    if not isinstance(worksheets, list):
        raise NotesContractError("Raw contract missing worksheets list")

    out: Dict[str, Dict[str, Any]] = {}
    for worksheet in worksheets:
        if not isinstance(worksheet, dict):
            continue
        name = worksheet.get("name")
        if isinstance(name, str):
            out[name] = worksheet
    return out


def _cell_map(worksheet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    cells = worksheet.get("cells")
    if not isinstance(cells, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        coordinate = cell.get("coordinate")
        if isinstance(coordinate, str):
            out[coordinate] = cell
    return out


def _split_cell_ref(cell_ref: str) -> Tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", cell_ref)
    if not match:
        raise NotesContractError(f"Unsupported cell reference: {cell_ref}")
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
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("A") + rem))
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


def _validate_canonical_mapping(notes: List[Dict[str, Any]]) -> None:
    if len(notes) != 28:
        raise NotesContractError(f"Mapping must contain exactly 28 notes, got {len(notes)}")

    seen_numbers: Set[int] = set()
    for index, note in enumerate(notes, start=1):
        number = note.get("noteNumber")
        title = note.get("title")
        if not isinstance(number, int):
            raise NotesContractError("Mapping noteNumber must be integer")
        if number in seen_numbers:
            raise NotesContractError(f"Duplicate note number in mapping: {number}")
        seen_numbers.add(number)
        if number != index:
            raise NotesContractError("Unexpected note ordering in mapping policy")
        expected_title = CANONICAL_NOTE_TITLES[index - 1]
        if title != expected_title:
            raise NotesContractError(
                f"Canonical title mismatch for note {index}: expected '{expected_title}', got '{title}'"
            )
        authority_mode = note.get("authorityMode")
        if not isinstance(authority_mode, str) or authority_mode not in ALLOWED_RENDER_AUTHORITY_MODES:
            raise NotesContractError(
                f"Canonical note {index} must define one authorityMode in {sorted(ALLOWED_RENDER_AUTHORITY_MODES)}"
            )
        authority_modes = note.get("authorityModes")
        if authority_modes is not None:
            raise NotesContractError("authorityModes is not supported; use exactly one authorityMode per note")

    if seen_numbers != set(range(1, 29)):
        missing = sorted(set(range(1, 29)).difference(seen_numbers))
        raise NotesContractError(f"Missing canonical notes: {missing}")


def _collect_table_from_range(worksheet: Dict[str, Any], range_ref: str) -> Dict[str, Any]:
    cell_lookup = _cell_map(worksheet)
    coordinates = _expand_range(range_ref)
    rows_map: Dict[int, List[Dict[str, Any]]] = {}
    source_refs: List[Dict[str, str]] = []

    for coordinate in coordinates:
        col, row = _split_cell_ref(coordinate)
        cell = cell_lookup.get(coordinate)
        displayed = cell.get("displayedValue") if isinstance(cell, dict) else ""
        value_type = cell.get("valueType") if isinstance(cell, dict) else "empty"
        rows_map.setdefault(row, []).append(
            {
                "coordinate": coordinate,
                "text": displayed if isinstance(displayed, str) else "",
                "valueType": value_type if isinstance(value_type, str) else "empty",
                "rawValue": cell.get("rawValue") if isinstance(cell, dict) else None,
                "cachedValue": cell.get("cachedValue") if isinstance(cell, dict) else None,
                "formula": cell.get("formula") if isinstance(cell, dict) else None,
                "numberFormat": cell.get("numberFormat") if isinstance(cell, dict) else None,
            }
        )
        source_refs.append(
            {
                "sheet": worksheet.get("name", ""),
                "coordinate": coordinate,
            }
        )

    ordered_rows: List[Dict[str, Any]] = []
    for row in sorted(rows_map.keys()):
        row_cells = sorted(rows_map[row], key=lambda item: _column_to_number(_split_cell_ref(item["coordinate"])[0]))
        ordered_rows.append({"rowIndex": row, "cells": row_cells})

    return {
        "range": range_ref,
        "rows": ordered_rows,
        "sourceRefs": source_refs,
    }


def _management_post_report_blocks(management_contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if management_contract is None:
        return []

    excluded = management_contract.get("excludedContent")
    if not isinstance(excluded, list):
        return []

    for item in excluded:
        if not isinstance(item, dict):
            continue
        if item.get("exclusionKey") != "postReportNoteUpdateContent":
            continue
        blocks = item.get("blocks")
        if not isinstance(blocks, list):
            return []

        out: List[Dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            source_block_id = block.get("sourceBlockId")
            if isinstance(text, str) and isinstance(source_block_id, str):
                out.append({"sourceBlockId": source_block_id, "text": text})
        return out

    return []


def _docx_note_targets(text: str) -> Optional[int]:
    lowered = text.lower()
    if "väsentliga händelser" in lowered:
        return 28
    if "transaktioner med närstående" in lowered or "moderföretag" in lowered:
        return 27
    if "redovisningsprincip" in lowered or "koncernredovisning" in lowered:
        return 1
    return None


def _workbook_reporting_period(metadata: ReportMetadata) -> str:
    parts = [part.strip() for part in metadata.current_reporting_period.splitlines() if part.strip()]
    if len(parts) != 2:
        raise NotesContractError("Metadata currentReportingPeriod must contain two date lines")
    return f"{parts[0][:7]}--{parts[1].lstrip('-')[:7]}"


def _org_number_occurrences(raw_contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    worksheets = raw_contract.get("worksheets")
    if not isinstance(worksheets, list):
        return []

    org_pattern = re.compile(r"\b\d{6}-\d{4}\b")
    out: List[Dict[str, Any]] = []

    for worksheet in worksheets:
        if not isinstance(worksheet, dict):
            continue
        sheet = worksheet.get("name")
        if not isinstance(sheet, str):
            continue
        cells = worksheet.get("cells")
        if not isinstance(cells, list):
            continue

        for cell in cells:
            if not isinstance(cell, dict):
                continue
            displayed = cell.get("displayedValue")
            coordinate = cell.get("coordinate")
            if not isinstance(displayed, str) or not isinstance(coordinate, str):
                continue
            for token in org_pattern.findall(displayed):
                out.append(
                    {
                        "value": token,
                        "sheet": sheet,
                        "coordinate": coordinate,
                        "displayedText": displayed,
                        "sourceTrace": cell.get("sourceTrace") if isinstance(cell.get("sourceTrace"), dict) else {
                            "worksheetName": sheet,
                            "coordinate": coordinate,
                        },
                    }
                )

    return out


def _anchor_cells(
    *,
    worksheets_by_name: Dict[str, Dict[str, Any]],
    anchor: Dict[str, Any],
) -> List[Dict[str, Any]]:
    sheet = anchor.get("sheet")
    range_ref = anchor.get("range")
    if not isinstance(sheet, str) or not isinstance(range_ref, str):
        raise NotesContractError("Configured identity workbookAnchor must include sheet and range")

    worksheet = worksheets_by_name.get(sheet)
    if worksheet is None:
        raise NotesContractError(f"Configured identity workbookAnchor sheet missing: {sheet}")

    lookup = _cell_map(worksheet)
    out: List[Dict[str, Any]] = []
    for coordinate in _expand_range(range_ref):
        cell = lookup.get(coordinate)
        if cell is None:
            continue
        displayed = cell.get("displayedValue")
        if not isinstance(displayed, str):
            displayed = ""
        out.append(
            {
                "sheet": sheet,
                "coordinate": coordinate,
                "value": displayed,
                "sourceTrace": cell.get("sourceTrace") if isinstance(cell.get("sourceTrace"), dict) else {
                    "worksheetName": sheet,
                    "coordinate": coordinate,
                },
            }
        )

    if not out:
        raise NotesContractError(
            f"Configured identity workbookAnchor not present in workbook: {sheet}!{range_ref}"
        )
    return out


def _identity_validation(
    *,
    raw_contract: Dict[str, Any],
    metadata: ReportMetadata,
    identity_policy: Dict[str, Any],
    worksheets_by_name: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    top_level_diagnostics: List[Dict[str, Any]] = []

    company_policy = identity_policy.get("companyName")
    org_policy = identity_policy.get("organizationNumber")
    if not isinstance(company_policy, dict) or not isinstance(org_policy, dict):
        raise NotesContractError("reportingEntityIdentity policy must define companyName and organizationNumber")

    company_mode = company_policy.get("workbookEvidenceMode", IDENTITY_MODE_METADATA_ONLY)
    org_mode = org_policy.get("workbookEvidenceMode", IDENTITY_MODE_METADATA_ONLY)
    if company_mode not in {IDENTITY_MODE_METADATA_ONLY, IDENTITY_MODE_APPROVED_ANCHOR}:
        raise NotesContractError(f"Unsupported companyName workbookEvidenceMode: {company_mode}")
    if org_mode not in {IDENTITY_MODE_METADATA_ONLY, IDENTITY_MODE_APPROVED_ANCHOR}:
        raise NotesContractError(f"Unsupported organizationNumber workbookEvidenceMode: {org_mode}")

    company_evidence: Dict[str, Any] = {
        "metadataValue": metadata.company_name,
        "workbookEvidenceMode": company_mode,
    }
    org_evidence: Dict[str, Any] = {
        "metadataValue": metadata.organization_number,
        "workbookEvidenceMode": org_mode,
    }

    if company_mode == IDENTITY_MODE_METADATA_ONLY:
        company_evidence["workbookEvidenceStatus"] = "not_present"
        company_evidence["validationResult"] = "metadata_authoritative"
    else:
        anchor = company_policy.get("workbookAnchor")
        if not isinstance(anchor, dict):
            raise NotesContractError("companyName approved_anchor mode requires workbookAnchor")
        anchor_cells = _anchor_cells(worksheets_by_name=worksheets_by_name, anchor=anchor)
        anchor_values = [item["value"].strip() for item in anchor_cells if isinstance(item.get("value"), str)]
        if metadata.company_name not in anchor_values:
            raise NotesContractError("Workbook company name at approved anchor contradicts metadata")
        company_evidence["workbookEvidenceStatus"] = "match"
        company_evidence["validationResult"] = "match"
        company_evidence["anchor"] = anchor
        company_evidence["anchorEvidence"] = anchor_cells

    if org_mode == IDENTITY_MODE_METADATA_ONLY:
        diagnostic_code = org_policy.get("diagnosticCode", "WORKBOOK_REPORTING_ENTITY_ORG_NUMBER_NOT_PRESENT")
        if not isinstance(diagnostic_code, str):
            diagnostic_code = "WORKBOOK_REPORTING_ENTITY_ORG_NUMBER_NOT_PRESENT"
        org_evidence["workbookEvidenceStatus"] = "not_present"
        org_evidence["validationResult"] = "metadata_authoritative"
        org_evidence["diagnostic"] = diagnostic_code
        top_level_diagnostics.append(
            {
                "code": diagnostic_code,
                "severity": "review_required",
                "scope": "reportingEntityIdentity.organizationNumber",
            }
        )
    else:
        anchor = org_policy.get("workbookAnchor")
        if not isinstance(anchor, dict):
            raise NotesContractError("organizationNumber approved_anchor mode requires workbookAnchor")
        anchor_cells = _anchor_cells(worksheets_by_name=worksheets_by_name, anchor=anchor)
        found_values = []
        org_pattern = re.compile(r"\b\d{6}-\d{4}\b")
        for item in anchor_cells:
            value = item.get("value")
            if not isinstance(value, str):
                continue
            found_values.extend(org_pattern.findall(value))

        if not found_values:
            raise NotesContractError("Configured organizationNumber workbookAnchor has no organization number")
        if metadata.organization_number not in found_values:
            raise NotesContractError("Workbook organization number at approved anchor contradicts metadata")

        org_evidence["workbookEvidenceStatus"] = "match"
        org_evidence["validationResult"] = "match"
        org_evidence["anchor"] = anchor
        org_evidence["anchorEvidence"] = anchor_cells

    related_refs = _org_number_occurrences(raw_contract)
    # Preserve all org-like workbook content as traceable related-entity references.
    for item in related_refs:
        item["referenceType"] = "relatedEntityReference"

    return {
        "metadataCompanyName": metadata.company_name,
        "metadataOrganizationNumber": metadata.organization_number,
        "companyName": company_evidence,
        "organizationNumber": org_evidence,
        "relatedEntityReferences": related_refs,
    }, top_level_diagnostics


def _metadata_validations(
    *,
    raw_contract: Dict[str, Any],
    metadata: ReportMetadata,
) -> Dict[str, Any]:
    worksheets = raw_contract.get("worksheets")
    if not isinstance(worksheets, list):
        raise NotesContractError("Raw contract missing worksheets")

    period_tokens: List[Dict[str, str]] = []
    period_pattern = re.compile(r"\b\d{4}-\d{2}--\d{4}-\d{2}\b")
    expected_period_token = _workbook_reporting_period(metadata)

    for worksheet in worksheets:
        if not isinstance(worksheet, dict):
            continue
        name = worksheet.get("name")
        if not isinstance(name, str):
            continue
        cells = worksheet.get("cells")
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            value = cell.get("displayedValue")
            coordinate = cell.get("coordinate")
            if not isinstance(value, str) or not isinstance(coordinate, str):
                continue

            for match in period_pattern.findall(value):
                period_tokens.append({"sheet": name, "coordinate": coordinate, "value": match})

    if period_tokens and not any(token["value"] == expected_period_token for token in period_tokens):
        raise NotesContractError("Workbook reporting period contradicts metadata")

    reporting_period_evidence = {
        "expectedToken": expected_period_token,
        "matchedTokens": [token for token in period_tokens if token["value"] == expected_period_token],
        "status": "match" if any(token["value"] == expected_period_token for token in period_tokens) else "not_found",
    }
    return reporting_period_evidence


def _extract_source_references(source: Dict[str, Any]) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    source_type = source.get("sourceType")
    if source_type == "workbook_range":
        sheet = source.get("sheet")
        table_shapes = source.get("tableShapes")
        if isinstance(sheet, str) and isinstance(table_shapes, list):
            for shape in table_shapes:
                if isinstance(shape, dict) and isinstance(shape.get("range"), str):
                    refs.append({"sheet": sheet, "range": shape["range"]})
    elif source_type == "workbook_multi_range":
        worksheet_ranges = source.get("worksheetRanges")
        if isinstance(worksheet_ranges, list):
            for item in worksheet_ranges:
                if isinstance(item, dict) and isinstance(item.get("sheet"), str) and isinstance(item.get("range"), str):
                    refs.append({"sheet": item["sheet"], "range": item["range"]})
        support = source.get("supportingRanges")
        if isinstance(support, list):
            for item in support:
                if isinstance(item, dict) and isinstance(item.get("sheet"), str) and isinstance(item.get("range"), str):
                    refs.append({"sheet": item["sheet"], "range": item["range"]})
    elif source_type == "start_sheet_reference":
        entries = source.get("worksheetRanges")
        if isinstance(entries, list):
            for item in entries:
                if isinstance(item, dict) and isinstance(item.get("sheet"), str) and isinstance(item.get("range"), str):
                    refs.append({"sheet": item["sheet"], "range": item["range"]})
    return refs


def _range_key(sheet: str, range_ref: str) -> str:
    return f"{sheet}:{range_ref}"


def _range_dimensions(range_ref: str) -> Tuple[int, int]:
    coordinates = _expand_range(range_ref)
    if not coordinates:
        raise NotesContractError(f"Empty range is not allowed: {range_ref}")
    first_col, first_row = _split_cell_ref(coordinates[0])
    last_col, last_row = _split_cell_ref(coordinates[-1])
    row_count = last_row - first_row + 1
    col_count = _column_to_number(last_col) - _column_to_number(first_col) + 1
    return row_count, col_count


def _table_shape_map_for_source(source: Dict[str, Any], source_refs: List[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    shape_map: Dict[str, Dict[str, int]] = {}
    source_type = source.get("sourceType")
    table_shapes = source.get("tableShapes")
    if not isinstance(table_shapes, list):
        return shape_map

    if source_type == "workbook_range":
        sheet = source.get("sheet")
        if not isinstance(sheet, str):
            return shape_map
        for shape in table_shapes:
            if not isinstance(shape, dict):
                continue
            range_ref = shape.get("range")
            row_count = shape.get("rowCount")
            col_count = shape.get("colCount")
            if isinstance(range_ref, str) and isinstance(row_count, int) and isinstance(col_count, int):
                shape_map[_range_key(sheet, range_ref)] = {"rowCount": row_count, "colCount": col_count}
        return shape_map

    if source_type == "workbook_multi_range":
        for shape in table_shapes:
            if not isinstance(shape, dict):
                continue
            range_ref = shape.get("range")
            row_count = shape.get("rowCount")
            col_count = shape.get("colCount")
            if not (isinstance(range_ref, str) and isinstance(row_count, int) and isinstance(col_count, int)):
                continue

            candidates = [
                ref for ref in source_refs
                if ref.get("range") == range_ref
            ]
            if len(candidates) != 1:
                raise NotesContractError(
                    f"Ambiguous or missing table shape mapping for range {range_ref} in workbook_multi_range"
                )
            sheet = candidates[0].get("sheet")
            if isinstance(sheet, str):
                shape_map[_range_key(sheet, range_ref)] = {"rowCount": row_count, "colCount": col_count}
        return shape_map

    return shape_map


def _extract_range_dispositions(
    *,
    note_number: int,
    source: Dict[str, Any],
    source_refs: List[Dict[str, str]],
    shape_map: Dict[str, Dict[str, int]],
    require_explicit: bool,
) -> Dict[str, Dict[str, Any]]:
    entries = source.get("rangeDispositions")
    if not source_refs:
        if entries:
            raise NotesContractError(f"Note {note_number} defines rangeDispositions without mapped source ranges")
        return {}

    if not isinstance(entries, list) or not entries:
        if require_explicit:
            raise NotesContractError(f"Note {note_number} must define non-empty source.rangeDispositions")
        fallback: Dict[str, Dict[str, Any]] = {}
        for ref in source_refs:
            sheet = ref["sheet"]
            range_ref = ref["range"]
            key = _range_key(sheet, range_ref)
            shape = shape_map.get(key)
            inferred_rows, inferred_cols = _range_dimensions(range_ref)
            expected_rows = shape["rowCount"] if shape is not None else inferred_rows
            expected_cols = shape["colCount"] if shape is not None else inferred_cols
            fallback[key] = {
                "sheet": sheet,
                "range": range_ref,
                "disposition": "render_content",
                "expectedRowCount": expected_rows,
                "expectedColCount": expected_cols,
            }
        return fallback

    source_keys = {
        _range_key(ref["sheet"], ref["range"])
        for ref in source_refs
    }

    disposition_map: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NotesContractError(f"Note {note_number} rangeDispositions entries must be objects")

        sheet = entry.get("sheet")
        range_ref = entry.get("range")
        disposition = entry.get("disposition")
        expected_rows = entry.get("expectedRowCount")
        expected_cols = entry.get("expectedColCount")

        if not isinstance(sheet, str) or not isinstance(range_ref, str):
            raise NotesContractError(f"Note {note_number} rangeDispositions entries require sheet and range")
        if not isinstance(disposition, str) or disposition not in ALLOWED_RANGE_DISPOSITIONS:
            raise NotesContractError(f"Note {note_number} has invalid range disposition: {disposition}")
        if not isinstance(expected_rows, int) or not isinstance(expected_cols, int):
            raise NotesContractError(f"Note {note_number} rangeDispositions entries require expectedRowCount and expectedColCount")

        key = _range_key(sheet, range_ref)
        if key in disposition_map:
            raise NotesContractError(f"Note {note_number} source range has multiple dispositions: {key}")
        if key not in source_keys:
            raise NotesContractError(f"Note {note_number} rangeDispositions contains unknown range: {key}")

        inferred_rows, inferred_cols = _range_dimensions(range_ref)
        if (expected_rows, expected_cols) != (inferred_rows, inferred_cols):
            raise NotesContractError(
                f"Note {note_number} rangeDispositions shape mismatch for {key}: "
                f"expected {expected_rows}x{expected_cols}, inferred {inferred_rows}x{inferred_cols}"
            )

        shape = shape_map.get(key)
        if disposition == "render_content" and shape is not None:
            if shape["rowCount"] != expected_rows or shape["colCount"] != expected_cols:
                raise NotesContractError(
                    f"Note {note_number} approved render range changed shape for {key}: "
                    f"mapping tableShape {shape['rowCount']}x{shape['colCount']} vs disposition {expected_rows}x{expected_cols}"
                )

        disposition_map[key] = dict(entry)

    missing = sorted(source_keys.difference(disposition_map.keys()))
    if missing:
        raise NotesContractError(f"Note {note_number} mapped source ranges missing disposition: {missing}")

    render_ranges = [
        (entry["sheet"], entry["range"])
        for entry in disposition_map.values()
        if entry.get("disposition") == "render_content"
    ]
    for idx, (sheet_a, range_a) in enumerate(render_ranges):
        cells_a = set(_expand_range(range_a))
        for sheet_b, range_b in render_ranges[idx + 1:]:
            if sheet_a != sheet_b:
                continue
            if cells_a.intersection(_expand_range(range_b)):
                raise NotesContractError(
                    f"Note {note_number} has overlapping render_content ranges on {sheet_a}: {range_a} and {range_b}"
                )

    return disposition_map


def _note_status_from_authority(authority_status: str) -> str:
    if authority_status in {
        "workbook_direct",
        "direct_workbook",
        "hybrid_workbook_preview_override",
        "full_note_preview_override",
    }:
        return "renderable"
    if authority_status == "blocked":
        return "blocked"
    return "review_required"


def build_semantic_notes_contract(
    *,
    raw_contract: Dict[str, Any],
    mapping_path: Path,
    metadata_path: Path,
    management_contract_path: Optional[Path],
    expected_raw_contract_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    mapping_policy = _load_mapping_policy(mapping_path)
    metadata = load_report_metadata(metadata_path)
    management_contract = _load_management_contract(management_contract_path)

    notes_mapping = mapping_policy.get("canonicalNotes")
    if not isinstance(notes_mapping, list):
        raise NotesContractError("Mapping policy must include canonicalNotes list")
    _validate_canonical_mapping(notes_mapping)

    worksheets_by_name = _worksheet_map(raw_contract)
    identity_policy = _identity_policy(mapping_policy)
    mapped_range_content_policy = _mapped_range_content_policy(mapping_policy)
    unsupported_allowlist = _unsupported_content_allowlist(mapping_policy)
    reporting_period_evidence = _metadata_validations(
        raw_contract=raw_contract,
        metadata=metadata,
    )

    raw_hash = _sha256_bytes(raw_notes_workbook_contract_json_bytes(raw_contract))
    if expected_raw_contract_sha256 is not None and expected_raw_contract_sha256 != raw_hash:
        raise NotesContractError("Provided raw contract sha256 does not match raw contract bytes")
    mapping_hash = _sha256_bytes(mapping_path.read_bytes())
    require_explicit_range_dispositions = isinstance(mapping_policy.get("sourceRangeDispositionVersion"), str)

    company_identity_evidence, top_level_diagnostics = _identity_validation(
        raw_contract=raw_contract,
        metadata=metadata,
        identity_policy=identity_policy,
        worksheets_by_name=worksheets_by_name,
    )

    post_report_blocks = _management_post_report_blocks(management_contract)
    mapped_coordinates: Dict[str, int] = {}
    notes_out: List[Dict[str, Any]] = []

    meaningful_object_diagnostics: List[Dict[str, Any]] = []
    for diag in raw_contract.get("diagnostics", []):
        if not isinstance(diag, dict):
            continue
        if diag.get("code") != "WORKSHEET_DRAWING_RELATIONSHIP_PRESENT":
            continue
        relationship = diag.get("relationship")
        if isinstance(relationship, dict) and relationship.get("type") == "unsupportedMeaningfulObject":
            meaningful_object_diagnostics.append(diag)

    for note in notes_mapping:
        assert isinstance(note, dict)
        note_number = note["noteNumber"]
        title = note["title"]
        source = note.get("source")
        if not isinstance(source, dict):
            raise NotesContractError(f"Note {note_number} missing source object")

        note_diagnostics: List[Dict[str, Any]] = []
        authority_mode = note.get("authorityMode")
        if not isinstance(authority_mode, str) or authority_mode not in ALLOWED_RENDER_AUTHORITY_MODES:
            raise NotesContractError(f"Note {note_number} missing valid authorityMode")
        source_refs = _extract_source_references(source)
        shape_map = _table_shape_map_for_source(source, source_refs)
        range_dispositions = _extract_range_dispositions(
            note_number=note_number,
            source=source,
            source_refs=source_refs,
            shape_map=shape_map,
            require_explicit=require_explicit_range_dispositions,
        )
        tables: List[Dict[str, Any]] = []
        render_tables: List[Dict[str, Any]] = []
        supporting_evidence: List[Dict[str, Any]] = []
        reconciliation_evidence: List[Dict[str, Any]] = []
        excluded_internal_evidence: List[Dict[str, Any]] = []
        formulas_used: List[Dict[str, str]] = []
        paragraphs: List[Dict[str, Any]] = []

        for code in note.get("diagnosticCodes", []):
            if isinstance(code, str):
                note_diagnostics.append(
                    {
                        "code": code,
                        "severity": "review_required",
                    }
                )

        for ref in source_refs:
            sheet_name = ref["sheet"]
            range_ref = ref["range"]
            range_key = _range_key(sheet_name, range_ref)
            disposition_entry = range_dispositions[range_key]
            disposition = disposition_entry["disposition"]
            worksheet = worksheets_by_name.get(sheet_name)
            if worksheet is None:
                raise NotesContractError(f"Missing required worksheet for note {note_number}: {sheet_name}")

            table = _collect_table_from_range(worksheet, range_ref)
            tables.append(
                {
                    "sheet": sheet_name,
                    "range": range_ref,
                    "rows": table["rows"],
                }
            )

            expected_rows = disposition_entry["expectedRowCount"]
            expected_cols = disposition_entry["expectedColCount"]
            if len(table["rows"]) != expected_rows:
                raise NotesContractError(
                    f"Malformed table shape for note {note_number} range {range_ref}: expected {expected_rows} rows"
                )
            for row in table["rows"]:
                if len(row["cells"]) != expected_cols:
                    raise NotesContractError(
                        f"Malformed table shape for note {note_number} range {range_ref}: expected {expected_cols} columns"
                    )

            range_payload = {
                "sheet": sheet_name,
                "range": range_ref,
                "rows": table["rows"],
                "disposition": disposition,
                "reason": disposition_entry.get("reason"),
            }
            if disposition == "render_content":
                render_tables.append(range_payload)
            elif disposition == "supporting_evidence":
                supporting_evidence.append(range_payload)
            elif disposition == "reconciliation_evidence":
                reconciliation_evidence.append(range_payload)
            elif disposition == "excluded_internal_template_content":
                excluded_internal_evidence.append(range_payload)
            else:
                raise NotesContractError(f"Unsupported source disposition '{disposition}' in note {note_number}")

            for shape in source.get("tableShapes", []):
                if not isinstance(shape, dict):
                    continue
                if shape.get("range") != range_ref:
                    continue
                expected_rows = shape.get("rowCount")
                expected_cols = shape.get("colCount")
                if isinstance(expected_rows, int) and isinstance(expected_cols, int):
                    if len(table["rows"]) != expected_rows:
                        raise NotesContractError(
                            f"Malformed table shape for note {note_number} range {range_ref}: expected {expected_rows} rows"
                        )
                    for row in table["rows"]:
                        if len(row["cells"]) != expected_cols:
                            raise NotesContractError(
                                f"Malformed table shape for note {note_number} range {range_ref}: expected {expected_cols} columns"
                            )

            cell_lookup = _cell_map(worksheet)
            for coordinate in _expand_range(range_ref):
                unique_ref = f"{sheet_name}!{coordinate}"
                if unique_ref in mapped_coordinates and mapped_coordinates[unique_ref] != note_number:
                    raise NotesContractError(
                        f"Source cell mapped to more than one note: {unique_ref} -> {mapped_coordinates[unique_ref]} and {note_number}"
                    )
                mapped_coordinates[unique_ref] = note_number

                cell = cell_lookup.get(coordinate)
                if isinstance(cell, dict):
                    formula = cell.get("formula")
                    cached = cell.get("cachedValue")
                    if isinstance(formula, str):
                        formulas_used.append(
                            {
                                "sheet": sheet_name,
                                "coordinate": coordinate,
                                "formula": formula,
                                "cachedValue": cached if isinstance(cached, str) else "",
                            }
                        )

        for block in post_report_blocks:
            text = block["text"]
            candidate = _docx_note_targets(text)
            if candidate != note_number:
                continue
            entry = {
                "sourceBlockId": block["sourceBlockId"],
                "text": text,
                "candidateTargetNoteNumber": candidate,
                "containsNotePlaceholder": "Not X" in text,
            }
            paragraphs.append(entry)
            if "Not X" in text:
                note_diagnostics.append(
                    {
                        "code": "NOTE_NUMBER_PLACEHOLDER_UNRESOLVED",
                        "severity": "review_required",
                        "sourceBlockId": block["sourceBlockId"],
                    }
                )

        reconciliations = []
        for req in note.get("reconciliationRequirements", []):
            if not isinstance(req, dict):
                continue
            reconciliations.append(
                {
                    "diagnostic": "STATEMENT_RECONCILIATION_REQUIRED",
                    "expectedStatementSource": req.get("expectedStatementSource"),
                    "noteValueSource": source.get("sourceType"),
                    "reconciliationKey": req.get("reconciliationKey"),
                    "roundingPolicy": req.get("roundingPolicy"),
                    "status": "not_evaluated",
                    "unit": req.get("unit"),
                }
            )

        authority_status = note.get("authorityStatus", "review_required")
        if not isinstance(authority_status, str):
            authority_status = "review_required"
        if authority_mode == "direct_workbook" and note_diagnostics:
            raise NotesContractError(
                f"Note {note_number} direct_workbook mode cannot have unresolved diagnostics: "
                f"{[d.get('code') for d in note_diagnostics]}"
            )
        status = _note_status_from_authority(authority_status)
        if authority_mode in {"direct_workbook", "hybrid_workbook_preview_override", "full_note_preview_override"} and status != "blocked":
            status = "renderable"
        if any(d.get("code") == "NOTE_NUMBER_PLACEHOLDER_UNRESOLVED" for d in note_diagnostics):
            status = "review_required"

        renderability = "renderable" if status == "renderable" else "review_required"
        if status == "blocked":
            renderability = "blocked"

        notes_out.append(
            {
                "diagnostics": note_diagnostics,
                "formulasUsed": formulas_used,
                "noteNumber": note_number,
                "order": note_number,
                "paragraphs": paragraphs,
                "renderParagraphs": list(paragraphs),
                "reconciliationRequirements": reconciliations,
                "renderTables": render_tables,
                "supportingEvidence": supporting_evidence,
                "reconciliationEvidence": reconciliation_evidence,
                "excludedInternalEvidence": excluded_internal_evidence,
                "sourceRangeDispositions": [
                    range_dispositions[_range_key(ref["sheet"], ref["range"])]
                    for ref in source_refs
                ],
                "renderability": renderability,
                "renderAuthority": {
                    "mode": authority_mode,
                },
                "sourceReferences": source_refs,
                "sourceType": source.get("sourceType", "unknown"),
                "status": status,
                "tables": tables,
                "title": title,
            }
        )

    # Unsupported workbook constructs policy:
    # - unknown meaningful comment/object inside mapped ranges => fail closed by default
    # - outside mapped ranges => keep diagnostics/source trace
    allowlist_by_id: Dict[str, Dict[str, Any]] = {str(item["id"]): item for item in unsupported_allowlist}
    matched_allowlist_ids: Set[str] = set()

    worksheet_lookup = _worksheet_map(raw_contract)
    all_comments: List[Dict[str, Any]] = []
    for worksheet_name, worksheet in worksheet_lookup.items():
        for cell in worksheet.get("cells", []):
            if not isinstance(cell, dict):
                continue
            comment = cell.get("commentEvidence")
            if not isinstance(comment, dict):
                continue
            comment_text = comment.get("text")
            if not isinstance(comment_text, str) or not comment_text.strip():
                continue
            coordinate = cell.get("coordinate")
            if not isinstance(coordinate, str):
                continue
            unique_ref = f"{worksheet_name}!{coordinate}"
            all_comments.append(
                {
                    "sheet": worksheet_name,
                    "coordinate": coordinate,
                    "text": comment_text,
                    "sourcePart": comment.get("sourcePart"),
                    "sourceTrace": cell.get("sourceTrace") if isinstance(cell.get("sourceTrace"), dict) else {
                        "worksheetName": worksheet_name,
                        "coordinate": coordinate,
                    },
                    "insideMappedRange": unique_ref in mapped_coordinates,
                    "sha256": _sha256_text(comment_text),
                }
            )

    for comment in all_comments:
        entry_match: Optional[Dict[str, Any]] = None
        for entry in unsupported_allowlist:
            ok, reason = _comment_allowlist_match(comment, entry)
            if ok:
                entry_match = entry
                break
            # same location but changed content must fail closed
            if (
                entry.get("constructType") == "comment"
                and entry.get("worksheet") == comment["sheet"]
                and entry.get("coordinate") == comment["coordinate"]
                and reason in {"expectedText mismatch", "expectedSha256 mismatch"}
            ):
                raise NotesContractError(
                    f"Allowlisted comment content changed at {comment['sheet']}!{comment['coordinate']}"
                )

        if entry_match is not None:
            entry_id = str(entry_match["id"])
            matched_allowlist_ids.add(entry_id)
            top_level_diagnostics.append(
                {
                    "code": entry_match.get("diagnosticCode", "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED"),
                    "severity": "review_required",
                    "classification": entry_match.get("classification"),
                    "worksheet": comment["sheet"],
                    "coordinate": comment["coordinate"],
                    "sourceTrace": comment["sourceTrace"],
                }
            )
            continue

        if comment["insideMappedRange"] and mapped_range_content_policy["failOnMeaningfulComments"]:
            raise NotesContractError(
                f"Unknown meaningful comment content found in mapped authoritative range: {comment['sheet']}!{comment['coordinate']}"
            )

        top_level_diagnostics.append(
            {
                "code": "UNSUPPORTED_WORKBOOK_COMMENT_OUTSIDE_MAPPED_RANGE",
                "severity": "review_required",
                "worksheet": comment["sheet"],
                "coordinate": comment["coordinate"],
                "sourceTrace": comment["sourceTrace"],
            }
        )

    mapped_sheets: Set[str] = set(ref.split("!", 1)[0] for ref in mapped_coordinates.keys())
    for diag in meaningful_object_diagnostics:
        sheet = diag.get("sheet")
        if not isinstance(sheet, str):
            continue
        rel = diag.get("relationship")
        obj_item = {
            "sheet": sheet,
            "relationship": rel,
            "sourceTrace": {
                "worksheetName": sheet,
                "relationship": rel,
            },
            "insideMappedRange": sheet in mapped_sheets,
        }

        matched_object: Optional[Dict[str, Any]] = None
        for entry in unsupported_allowlist:
            ok, _ = _object_allowlist_match(obj_item, entry)
            if ok:
                matched_object = entry
                break

        if matched_object is not None:
            entry_id = str(matched_object["id"])
            matched_allowlist_ids.add(entry_id)
            top_level_diagnostics.append(
                {
                    "code": matched_object.get("diagnosticCode", "KNOWN_INTERNAL_WORKBOOK_COMMENT_EXCLUDED"),
                    "severity": "review_required",
                    "classification": matched_object.get("classification"),
                    "worksheet": sheet,
                    "relationship": rel,
                }
            )
            continue

        if obj_item["insideMappedRange"] and mapped_range_content_policy["failOnMeaningfulObjects"]:
            raise NotesContractError(
                f"Unknown meaningful object present on mapped authoritative worksheet: {sheet}"
            )

        top_level_diagnostics.append(
            {
                "code": "UNSUPPORTED_WORKBOOK_OBJECT_OUTSIDE_MAPPED_RANGE",
                "severity": "review_required",
                "worksheet": sheet,
                "relationship": rel,
            }
        )

    for entry_id, entry in allowlist_by_id.items():
        if entry_id in matched_allowlist_ids:
            continue
        if bool(entry.get("requiresPresence", True)):
            if entry.get("constructType") == "comment":
                raise NotesContractError(
                    f"Required allowlisted comment missing: {entry.get('worksheet')}!{entry.get('coordinate')}"
                )
            raise NotesContractError(
                f"Required allowlisted object missing on worksheet: {entry.get('worksheet')}"
            )

    note_numbers = [note["noteNumber"] for note in notes_out]
    if note_numbers != list(range(1, 29)):
        raise NotesContractError("Canonical notes 1-28 must be present in exact order")

    if management_contract is None:
        for note_number in (1, 27, 28):
            notes_out[note_number - 1]["diagnostics"].append(
                {
                    "code": "NOTE_TEXT_SOURCE_REQUIRED",
                    "severity": "review_required",
                }
            )
            notes_out[note_number - 1]["status"] = "review_required"
            notes_out[note_number - 1]["renderability"] = "review_required"

    if any(any(d.get("code") == "EXTERNAL_LINK_CACHED_VALUE_USED" for d in note.get("diagnostics", [])) for note in notes_out):
        pass
    else:
        # bubble raw external-link diagnostics into note 10 when present there
        raw_diags = raw_contract.get("diagnostics")
        if isinstance(raw_diags, list):
            for diag in raw_diags:
                if not isinstance(diag, dict):
                    continue
                if diag.get("code") != "EXTERNAL_LINK_CACHED_VALUE_USED":
                    continue
                if diag.get("sheet") == "Skatt":
                    notes_out[9]["diagnostics"].append(
                        {
                            "code": "EXTERNAL_LINK_CACHED_VALUE_USED",
                            "severity": "review_required",
                            "sourceTrace": diag.get("sourceTrace"),
                        }
                    )

    unresolved = [
        {
            "noteNumber": note["noteNumber"],
            "title": note["title"],
            "status": note["status"],
            "diagnostics": [d.get("code") for d in note.get("diagnostics", []) if isinstance(d, dict)],
        }
        for note in notes_out
        if note["status"] != "renderable"
    ]

    if any(note["status"] == "blocked" for note in notes_out):
        overall_status = "blocked"
    elif any(note["status"] == "review_required" for note in notes_out):
        overall_status = "review_required"
    else:
        overall_status = "renderable"

    contract = {
        "schemaVersion": "1.0",
        "status": overall_status,
        "sourceEvidence": {
            "file": raw_contract.get("source", {}).get("file"),
            "sha256": raw_contract.get("source", {}).get("sha256"),
            "worksheetCount": raw_contract.get("workbook", {}).get("worksheetCount"),
            "nonEmptyCellCount": raw_contract.get("workbook", {}).get("nonEmptyCellCount"),
            "formulaCellCount": raw_contract.get("workbook", {}).get("formulaCellCount"),
        },
        "mappingPolicyEvidence": {
            "file": _safe_source_path(mapping_path),
            "sha256": mapping_hash,
            "policyVersion": mapping_policy.get("policyVersion"),
            "notesSchemaVersion": mapping_policy.get("notesSchemaVersion"),
            "sourceRangeDispositionVersion": mapping_policy.get("sourceRangeDispositionVersion"),
            "reportingEntityIdentity": identity_policy,
            "mappedRangeContentPolicy": mapped_range_content_policy,
            "unsupportedContentPolicy": mapping_policy.get("unsupportedContentPolicy"),
        },
        "reportingPeriodEvidence": reporting_period_evidence,
        "companyIdentityEvidence": company_identity_evidence,
        "notes": notes_out,
        "diagnostics": top_level_diagnostics,
        "unresolvedAmbiguities": unresolved,
        "rawContractSha256": raw_hash,
    }

    return json.loads(_canonical_json_bytes(contract).decode("utf-8"))