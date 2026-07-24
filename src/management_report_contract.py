from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from report_metadata import load_report_metadata


class ContractError(Exception):
    pass


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


SECTION_HEADING_ALIASES: Dict[str, List[str]] = {
    "managementReportHeading": ["Förvaltningsberättelse"],
    "businessInformation": ["Allmänt om verksamheten"],
    "multiYearOverview": ["Utveckling av företagets verksamhet, resultat och ställning"],
    "significantEvents": ["Väsentliga händelser under räkenskapsåret"],
    "researchAndDevelopment": ["Forskning och utveckling"],
    "sustainabilityDisclosures": [
        "Hållbarhetsupplysningar",
        "Hållbarhetsupplysningar - ESG (Environmental, Social and Governance)",
    ],
    "futureDevelopmentAndRisks": ["Förväntad framtida utveckling samt väsentliga risker och osäkerhetsfaktorer"],
    "equityAndProfitDisposition": ["Eget kapital"],
}


SECTION_ORDER = [
    "managementReportHeading",
    "businessInformation",
    "multiYearOverview",
    "significantEvents",
    "researchAndDevelopment",
    "sustainabilityDisclosures",
    "futureDevelopmentAndRisks",
    "equityAndProfitDisposition",
]

SIGNED_REFERENCE_AUTHORITY_TYPE = "signed_reference_pdf"
SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE = {
    "scopeId": "management_alignment_entity_period_section_v1",
    "companyName": "Omegapoint Malmö AB",
    "organizationNumber": "556613-1339",
    "currentReportingPeriod": "2025-01-01\n-2025-12-31",
}

OFFICE_ALIGNMENT_CORRECTION_ID = "management.office_location_without_oslo.v1"
OFFICE_ALIGNMENT_DIAGNOSTIC = "SIGNED_REFERENCE_OFFICE_LOCATION_ALIGNMENT_REQUIRED"
OFFICE_ALIGNMENT_SIGNED_PAGE = "2"
OFFICE_ALIGNMENT_OLD_VALUE = "Uppsala, Oslo, Köpenhamn och Montréal."
OFFICE_ALIGNMENT_NEW_VALUE = "Uppsala, Köpenhamn och Montréal."

SUSTAINABILITY_HEADING_CORRECTION_ID = "management.sustainability_heading_normalization.v1"
SUSTAINABILITY_HEADING_DIAGNOSTIC = "SIGNED_REFERENCE_SUSTAINABILITY_HEADING_ALIGNMENT_REQUIRED"
SUSTAINABILITY_HEADING_SIGNED_PAGE = "3"
SUSTAINABILITY_HEADING_OLD_VALUE = "Hållbarhetsupplysningar - ESG (Environmental, Social and Governance)"
SUSTAINABILITY_HEADING_NEW_VALUE = "Hållbarhetsupplysningar"

CLOSING_SUPPRESSION_CORRECTION_ID = "management.closing_sentence_suppression.v1"
CLOSING_SUPPRESSION_DIAGNOSTIC = "SIGNED_REFERENCE_CLOSING_SENTENCE_SUPPRESSION_REQUIRED"
CLOSING_SUPPRESSION_SIGNED_PAGE = "4"
CLOSING_SUPPRESSION_OLD_VALUE_1 = "Vad beträffar resultat och ställning i övrigt hänvisas till efterföljande resultat- och balansräkning med"
CLOSING_SUPPRESSION_OLD_VALUE_2 = "tillhörande noter."
CLOSING_SUPPRESSION_DISPOSITION = "excluded_from_closing_transition"


def _block_id_set(blocks: List[Dict[str, object]]) -> Set[str]:
    ids: Set[str] = set()
    for block in blocks:
        bid = block.get("blockId")
        if isinstance(bid, str):
            ids.add(bid)
    return ids


def _paragraph_text(block: Dict[str, object]) -> str:
    paragraph = block.get("paragraph")
    if not isinstance(paragraph, dict):
        return ""
    text = paragraph.get("text")
    return text if isinstance(text, str) else ""


def _non_empty(text: str) -> bool:
    return bool(text.strip())


def _paragraph_blocks(raw_contract: Dict[str, object]) -> List[Dict[str, object]]:
    blocks = raw_contract.get("blocks")
    if not isinstance(blocks, list):
        raise ContractError("Raw contract is missing blocks array")
    out: List[Dict[str, object]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("blockType") == "paragraph":
            out.append(block)
    return out


def _table_blocks(raw_contract: Dict[str, object]) -> List[Dict[str, object]]:
    blocks = raw_contract.get("blocks")
    if not isinstance(blocks, list):
        raise ContractError("Raw contract is missing blocks array")
    out: List[Dict[str, object]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("blockType") == "table":
            out.append(block)
    return out


def _block_index(block: Dict[str, object]) -> int:
    idx = block.get("blockIndex")
    if not isinstance(idx, int):
        raise ContractError("Block is missing integer blockIndex")
    return idx


def _find_heading_blocks(paragraph_blocks: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    resolved: Dict[str, Dict[str, object]] = {}
    duplicates: Dict[str, List[str]] = {}

    for key, aliases in SECTION_HEADING_ALIASES.items():
        matches: List[Dict[str, object]] = []
        alias_set = set(aliases)
        for block in paragraph_blocks:
            text = _paragraph_text(block).strip()
            if text in alias_set:
                matches.append(block)

        if len(matches) == 0:
            raise ContractError(f"Missing required semantic heading: {key}")
        if len(matches) > 1:
            duplicates[key] = [str(m.get("blockId")) for m in matches]
        resolved[key] = matches[0]

    if duplicates:
        details = ", ".join(f"{k}={v}" for k, v in sorted(duplicates.items()))
        raise ContractError(f"Duplicate required semantic headings detected: {details}")

    ordered_indices = [_block_index(resolved[key]) for key in SECTION_ORDER]
    if ordered_indices != sorted(ordered_indices):
        raise ContractError("Required semantic headings appear in an impossible order")

    return resolved


def _internal_instruction_blocks(
    blocks: List[Dict[str, object]],
    management_heading_index: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    pre_blocks: List[Dict[str, object]] = [b for b in blocks if _block_index(b) < management_heading_index]
    instruction_blocks: List[Dict[str, object]] = []
    allowed_empty: List[Dict[str, object]] = []

    for block in pre_blocks:
        if block.get("blockType") != "paragraph":
            raise ContractError("Ambiguous pre-management content: non-paragraph block before heading")
        text = _paragraph_text(block)
        if not _non_empty(text):
            allowed_empty.append(block)
            continue

        markers = [
            "ska ej ingå i förvaltningsberättelsen eller noten",
            "uppdaterar texten för å",
            "gemensam text från koncernen",
            "beskrivning/hjälptext",
        ]
        normalized = text.strip().lower()
        if any(marker in normalized for marker in markers):
            instruction_blocks.append(block)
            continue

        raise ContractError("Ambiguous pre-management boundary: unexpected non-empty paragraph before heading")

    return instruction_blocks, allowed_empty


def _post_report_boundary(
    blocks: List[Dict[str, object]],
) -> Tuple[int, List[Dict[str, object]]]:
    explicit_break_blocks = [b for b in blocks if b.get("blockType") == "explicitPageBreak"]
    if not explicit_break_blocks:
        raise ContractError("Ambiguous management-report/post-report boundary: explicit page break not found")

    first_break = min(explicit_break_blocks, key=_block_index)
    break_index = _block_index(first_break)

    trailing = [b for b in blocks if _block_index(b) > break_index]
    non_empty_after_break: List[Dict[str, object]] = []
    for block in trailing:
        if block.get("blockType") != "paragraph":
            continue
        if _non_empty(_paragraph_text(block)):
            non_empty_after_break.append(block)

    if not non_empty_after_break:
        raise ContractError("Ambiguous management-report/post-report boundary: no post-break paragraph evidence")

    first_text = _paragraph_text(non_empty_after_break[0]).strip()
    if "NOTER FÖR TEXTUPPDATERING" not in first_text and not first_text.startswith("Not X"):
        raise ContractError("Ambiguous management-report/post-report boundary: note-update heading not detected")

    excluded = [b for b in blocks if _block_index(b) >= break_index]
    return break_index, excluded


def _find_period_evidence(intro_paragraphs: List[Dict[str, object]]) -> Tuple[str, str, str, List[str]]:
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})")
    for block in intro_paragraphs:
        text = _paragraph_text(block)
        match = pattern.search(text)
        if match:
            raw_text = match.group(0)
            return raw_text, match.group(1), match.group(2), [str(block.get("blockId"))]
    raise ContractError("Missing required reporting period evidence in introductory source text")


def _slice_by_index(blocks: List[Dict[str, object]], start: int, end: int) -> List[Dict[str, object]]:
    return [b for b in blocks if start < _block_index(b) < end]


def _table_shape(block: Dict[str, object]) -> Tuple[int, int]:
    table = block.get("table")
    if not isinstance(table, dict):
        raise ContractError("Table block is missing table payload")
    row_count = table.get("rowCount")
    grid_cols = table.get("gridColumnCount")
    if not isinstance(row_count, int) or not isinstance(grid_cols, int):
        raise ContractError("Table payload is missing deterministic dimensions")
    return row_count, grid_cols


def _require_single_table_in_range(blocks: List[Dict[str, object]], expected_rows: int, expected_cols: int, label: str) -> Dict[str, object]:
    tables = [b for b in blocks if b.get("blockType") == "table"]
    if len(tables) != 1:
        raise ContractError(f"Missing required table for {label}")
    row_count, col_count = _table_shape(tables[0])
    if row_count != expected_rows or col_count != expected_cols:
        raise ContractError(f"Malformed table dimensions for {label}: expected {expected_rows}x{expected_cols}, got {row_count}x{col_count}")
    return tables[0]


def _build_section_payload(
    key: str,
    heading_block: Optional[Dict[str, object]],
    paragraph_blocks: List[Dict[str, object]],
    *,
    forced_heading_text: Optional[str] = None,
) -> Dict[str, object]:
    heading_text = ""
    heading_block_id = ""
    if heading_block is not None:
        heading_text = _paragraph_text(heading_block)
        bid = heading_block.get("blockId")
        if isinstance(bid, str):
            heading_block_id = bid
    if forced_heading_text is not None:
        heading_text = forced_heading_text

    return {
        "sectionKey": key,
        "heading": {
            "text": heading_text,
            "sourceBlockId": heading_block_id,
        },
        "paragraphs": [
            {
                "sourceBlockId": block.get("blockId"),
                "text": _paragraph_text(block),
            }
            for block in paragraph_blocks
        ],
    }


def _collect_unsupported_paragraph_evidence(blocks: List[Dict[str, object]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = block.get("blockId")
        block_type = block.get("blockType")

        if block_type == "paragraph":
            paragraph = block.get("paragraph")
            if not isinstance(paragraph, dict):
                continue
            attached = paragraph.get("attachedUnsupportedConstructs")
            if not isinstance(attached, dict):
                continue
            out.append(
                {
                    "scope": "paragraph",
                    "source": {
                        "blockId": block_id,
                    },
                    "text": _paragraph_text(block),
                    "attached": attached,
                }
            )
            continue

        if block_type == "table":
            table = block.get("table")
            if not isinstance(table, dict):
                continue
            rows = table.get("rows")
            if not isinstance(rows, list):
                continue
            table_index = table.get("tableIndex")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_index = row.get("rowIndex")
                cells = row.get("cells")
                if not isinstance(cells, list):
                    continue
                for cell in cells:
                    if not isinstance(cell, dict):
                        continue
                    cell_index = cell.get("cellIndex")
                    paragraphs = cell.get("paragraphs")
                    if not isinstance(paragraphs, list):
                        continue
                    for para in paragraphs:
                        if not isinstance(para, dict):
                            continue
                        attached = para.get("attachedUnsupportedConstructs")
                        if not isinstance(attached, dict):
                            continue
                        out.append(
                            {
                                "scope": "tableCellParagraph",
                                "source": {
                                    "blockId": block_id,
                                    "tableIndex": table_index,
                                    "rowIndex": row_index,
                                    "cellIndex": cell_index,
                                    "cellParagraphIndex": para.get("paragraphIndex"),
                                },
                                "text": para.get("text", "") if isinstance(para.get("text"), str) else "",
                                "attached": attached,
                            }
                        )

    return out


def _semantic_unsupported_diagnostics_or_raise(
    raw_contract: Dict[str, object],
    blocks: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    diagnostics_out: List[Dict[str, object]] = []

    raw_diags = raw_contract.get("diagnostics")
    raw_diagnostics = raw_diags if isinstance(raw_diags, list) else []

    features_obj = raw_contract.get("documentFeatures")
    features = features_obj if isinstance(features_obj, dict) else {}

    unsupported_nodes = [
        d
        for d in raw_diagnostics
        if isinstance(d, dict) and d.get("code") == "UNSUPPORTED_TOP_LEVEL_BLOCK_DETECTED"
    ]
    if unsupported_nodes:
        raise ContractError("Unsupported top-level DOCX blocks detected; semantic extraction fails closed")

    if features.get("headersPresent") is True or features.get("footersPresent") is True:
        raise ContractError("Headers/footers present in DOCX; semantic extraction fails closed")

    comments_text_count = features.get("commentsTextCount")
    if isinstance(comments_text_count, int) and comments_text_count > 0:
        raise ContractError("comments.xml contains comment text; semantic extraction fails closed")

    if features.get("trackedChangesDetected") is True or features.get("trackRevisionsEnabled") is True:
        raise ContractError("Tracked changes markers/settings detected; semantic extraction fails closed")

    hidden_text_diags = [
        d for d in raw_diagnostics if isinstance(d, dict) and d.get("code") == "HIDDEN_TEXT_DETECTED"
    ]
    if hidden_text_diags:
        raise ContractError("Hidden text detected in source; semantic extraction fails closed")

    paragraph_evidence = _collect_unsupported_paragraph_evidence(blocks)

    field_refs = [
        e["source"]
        for e in paragraph_evidence
        if isinstance(e.get("attached"), dict) and e["attached"].get("containsFieldCode") is True
    ]
    if field_refs:
        raise ContractError("Field code content detected; semantic extraction fails closed")

    textbox_refs_with_text = [
        e["source"]
        for e in paragraph_evidence
        if isinstance(e.get("attached"), dict)
        and e["attached"].get("containsTextBox") is True
        and isinstance(e.get("text"), str)
        and e["text"].strip()
    ]
    if textbox_refs_with_text:
        raise ContractError("Text box with meaningful text detected; semantic extraction fails closed")

    drawing_refs = [
        {"source": e["source"], "text": e.get("text", "")}
        for e in paragraph_evidence
        if isinstance(e.get("attached"), dict) and e["attached"].get("containsDrawing") is True
    ]
    pict_refs = [
        {"source": e["source"], "text": e.get("text", "")}
        for e in paragraph_evidence
        if isinstance(e.get("attached"), dict) and e["attached"].get("containsPict") is True
    ]

    drawings_count = features.get("drawingsCount")
    if isinstance(drawings_count, int) and drawings_count > 0:
        if not drawing_refs:
            raise ContractError("Drawing nodes detected without block-level source trace; semantic extraction fails closed")
        if any(isinstance(ref.get("text"), str) and ref["text"].strip() for ref in drawing_refs):
            raise ContractError("Drawing with meaningful adjacent text detected; semantic extraction fails closed")
        diagnostics_out.append(
            {
                "code": "UNSUPPORTED_DECORATIVE_DRAWING_PRESENT",
                "severity": "review_required",
                "message": "Decorative drawing nodes detected; retained as reviewable unsupported evidence.",
                "count": drawings_count,
                "sourceRefs": [ref["source"] for ref in drawing_refs],
                "rawDiagnosticCodes": ["UNSUPPORTED_DRAWING_DETECTED"],
            }
        )

    pict_count = features.get("pictCount")
    if isinstance(pict_count, int) and pict_count > 0:
        if not pict_refs:
            raise ContractError("Pict nodes detected without block-level source trace; semantic extraction fails closed")
        if any(isinstance(ref.get("text"), str) and ref["text"].strip() for ref in pict_refs):
            raise ContractError("Pict with meaningful adjacent text detected; semantic extraction fails closed")
        diagnostics_out.append(
            {
                "code": "UNSUPPORTED_DECORATIVE_PICT_PRESENT",
                "severity": "review_required",
                "message": "Decorative pict nodes detected; retained as reviewable unsupported evidence.",
                "count": pict_count,
                "sourceRefs": [ref["source"] for ref in pict_refs],
                "rawDiagnosticCodes": ["UNSUPPORTED_PICT_DETECTED"],
            }
        )

    return diagnostics_out


def _validate_source_block_accounting(
    blocks: List[Dict[str, object]],
    sections: List[Dict[str, object]],
    tables: List[Dict[str, object]],
    excluded_content: List[Dict[str, object]],
    signed_reference_corrections: Optional[List[Dict[str, object]]] = None,
    *,
    enforce_completeness: bool = True,
) -> Set[str]:
    used_ids: List[str] = []

    for section in sections:
        heading = section.get("heading")
        if isinstance(heading, dict):
            hb = heading.get("sourceBlockId")
            if isinstance(hb, str) and hb:
                used_ids.append(hb)
        for p in section.get("paragraphs", []):
            if isinstance(p, dict):
                bid = p.get("sourceBlockId")
                if isinstance(bid, str):
                    used_ids.append(bid)

    for table_entry in tables:
        bid = table_entry.get("sourceBlockId")
        if isinstance(bid, str):
            used_ids.append(bid)

    for exclusion in excluded_content:
        for block in exclusion.get("blocks", []):
            if isinstance(block, dict):
                bid = block.get("sourceBlockId")
                if isinstance(bid, str):
                    used_ids.append(bid)

    if signed_reference_corrections is not None:
        for correction in signed_reference_corrections:
            excluded_ids = correction.get("excludedSourceBlockIds")
            if isinstance(excluded_ids, list):
                for bid in excluded_ids:
                    if isinstance(bid, str):
                        used_ids.append(bid)

    used_set = set(used_ids)
    if len(used_set) != len(used_ids):
        raise ContractError("Semantic source block referenced more than once unexpectedly")

    paragraph_and_table_ids: Set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("blockType")
        if block_type in {"paragraph", "table", "explicitPageBreak"}:
            bid = block.get("blockId")
            if isinstance(bid, str):
                paragraph_and_table_ids.add(bid)

    if enforce_completeness:
        missing_ids = sorted(paragraph_and_table_ids.difference(used_set))
        if missing_ids:
            raise ContractError(f"Source block silently lost from semantic contract: {missing_ids}")

    return used_set


def _scope_matches_signed_reference_alignment(metadata: object) -> bool:
    return (
        getattr(metadata, "company_name", None) == SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["companyName"]
        and getattr(metadata, "organization_number", None) == SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["organizationNumber"]
        and getattr(metadata, "current_reporting_period", None)
        == SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["currentReportingPeriod"]
    )


def _correction_approval_scope(section_key: str) -> Dict[str, str]:
    return {
        "scopeId": SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["scopeId"],
        "companyName": SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["companyName"],
        "organizationNumber": SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["organizationNumber"],
        "currentReportingPeriod": SIGNED_REFERENCE_ALIGNMENT_APPROVAL_SCOPE["currentReportingPeriod"],
        "sectionKey": section_key,
    }


def _validate_signed_reference_corrections(
    corrections: List[Dict[str, object]],
    diagnostics: List[Dict[str, object]],
    sections: List[Dict[str, object]],
) -> None:
    by_code: Dict[str, Dict[str, object]] = {}
    for d in diagnostics:
        code = d.get("code")
        if isinstance(code, str):
            by_code[code] = d

    section_payload: Dict[str, Dict[str, object]] = {}
    for s in sections:
        key = s.get("sectionKey")
        if isinstance(key, str):
            section_payload[key] = s

    expected = {
        OFFICE_ALIGNMENT_CORRECTION_ID: {
            "diagnosticCode": OFFICE_ALIGNMENT_DIAGNOSTIC,
            "signedReferencePage": OFFICE_ALIGNMENT_SIGNED_PAGE,
            "sectionKey": "businessInformation",
        },
        SUSTAINABILITY_HEADING_CORRECTION_ID: {
            "diagnosticCode": SUSTAINABILITY_HEADING_DIAGNOSTIC,
            "signedReferencePage": SUSTAINABILITY_HEADING_SIGNED_PAGE,
            "sectionKey": "sustainabilityDisclosures",
        },
        CLOSING_SUPPRESSION_CORRECTION_ID: {
            "diagnosticCode": CLOSING_SUPPRESSION_DIAGNOSTIC,
            "signedReferencePage": CLOSING_SUPPRESSION_SIGNED_PAGE,
            "sectionKey": "closingTransition",
        },
    }

    seen_ids: set[str] = set()
    for correction in corrections:
        cid = correction.get("correctionId")
        if not isinstance(cid, str) or not cid:
            raise ContractError("signedReferenceCorrections[].correctionId must be non-empty string")
        if cid in seen_ids:
            raise ContractError(f"Duplicate signed-reference correctionId: {cid}")
        seen_ids.add(cid)
        if cid not in expected:
            raise ContractError(f"Unknown signed-reference correctionId: {cid}")

        exp = expected[cid]
        if correction.get("diagnosticCode") != exp["diagnosticCode"]:
            raise ContractError(f"signedReferenceCorrections[{cid}] diagnosticCode mismatch")
        if correction.get("signedReferencePage") != exp["signedReferencePage"]:
            raise ContractError(f"signedReferenceCorrections[{cid}] signedReferencePage mismatch")
        if correction.get("sectionKey") != exp["sectionKey"]:
            raise ContractError(f"signedReferenceCorrections[{cid}] sectionKey mismatch")
        if correction.get("authorityType") != SIGNED_REFERENCE_AUTHORITY_TYPE:
            raise ContractError(f"signedReferenceCorrections[{cid}] authorityType mismatch")

        approval_scope = correction.get("approvalScope")
        if not isinstance(approval_scope, dict):
            raise ContractError(f"signedReferenceCorrections[{cid}] approvalScope must be object")
        for field, expected_value in _correction_approval_scope(exp["sectionKey"]).items():
            if approval_scope.get(field) != expected_value:
                raise ContractError(f"signedReferenceCorrections[{cid}] approvalScope.{field} mismatch")

        source_block_id = correction.get("sourceBlockId")
        if not isinstance(source_block_id, str) or not source_block_id:
            raise ContractError(f"signedReferenceCorrections[{cid}] sourceBlockId must be non-empty string")

        section_obj = section_payload.get(exp["sectionKey"])
        if not isinstance(section_obj, dict):
            raise ContractError(f"signedReferenceCorrections[{cid}] section payload missing")
        section_ids: set[str] = set()
        heading = section_obj.get("heading")
        if isinstance(heading, dict):
            hb = heading.get("sourceBlockId")
            if isinstance(hb, str) and hb:
                section_ids.add(hb)
        paragraphs = section_obj.get("paragraphs")
        if isinstance(paragraphs, list):
            for p in paragraphs:
                if isinstance(p, dict):
                    pid = p.get("sourceBlockId")
                    if isinstance(pid, str) and pid:
                        section_ids.add(pid)
        if source_block_id not in section_ids and cid != CLOSING_SUPPRESSION_CORRECTION_ID:
            raise ContractError(f"signedReferenceCorrections[{cid}] sourceBlockId not present in section")

        original_value = correction.get("originalValue")
        aligned_value = correction.get("alignedValue")
        disposition = correction.get("disposition")
        if not isinstance(original_value, str) or not original_value:
            raise ContractError(f"signedReferenceCorrections[{cid}] originalValue must be non-empty string")
        if not isinstance(aligned_value, str) or not aligned_value:
            raise ContractError(f"signedReferenceCorrections[{cid}] alignedValue must be non-empty string")
        if not isinstance(disposition, str) or not disposition:
            raise ContractError(f"signedReferenceCorrections[{cid}] disposition must be non-empty string")

        if cid == CLOSING_SUPPRESSION_CORRECTION_ID:
            excluded_ids = correction.get("excludedSourceBlockIds")
            if not isinstance(excluded_ids, list) or len(excluded_ids) != 2:
                raise ContractError("closing-suppression correction must include exactly two excludedSourceBlockIds")
            if any(not isinstance(v, str) or not v for v in excluded_ids):
                raise ContractError("closing-suppression excludedSourceBlockIds must be non-empty strings")
            if disposition != CLOSING_SUPPRESSION_DISPOSITION:
                raise ContractError("closing-suppression disposition mismatch")

        diag = by_code.get(exp["diagnosticCode"])
        if not isinstance(diag, dict):
            raise ContractError(f"signedReferenceCorrections[{cid}] missing diagnostic record")
        if diag.get("severity") != "info":
            raise ContractError(f"signedReferenceCorrections[{cid}] diagnostic must be severity=info")
        if diag.get("sectionKey") != exp["sectionKey"]:
            raise ContractError(f"signedReferenceCorrections[{cid}] diagnostic sectionKey mismatch")
        if diag.get("sourceBlockId") != source_block_id:
            raise ContractError(f"signedReferenceCorrections[{cid}] diagnostic sourceBlockId mismatch")


def build_semantic_management_report_contract(
    raw_contract: Dict[str, object],
    metadata_path: Path,
) -> Dict[str, object]:
    schema_version = raw_contract.get("schemaVersion")
    if schema_version != "1.0":
        raise ContractError("Unsupported raw contract schemaVersion")

    source = raw_contract.get("source")
    if not isinstance(source, dict):
        raise ContractError("Raw contract source payload is missing")
    source_file = source.get("file")
    source_sha = source.get("sha256")
    if not isinstance(source_file, str) or not isinstance(source_sha, str):
        raise ContractError("Raw contract source evidence is incomplete")

    blocks = raw_contract.get("blocks")
    if not isinstance(blocks, list):
        raise ContractError("Raw contract blocks payload is missing")

    unsupported_semantic_diagnostics = _semantic_unsupported_diagnostics_or_raise(raw_contract, blocks)

    all_block_ids = _block_id_set(blocks)
    paragraph_blocks = _paragraph_blocks(raw_contract)
    heading_blocks = _find_heading_blocks(paragraph_blocks)

    management_heading = heading_blocks["managementReportHeading"]
    management_heading_idx = _block_index(management_heading)

    instruction_blocks, pre_heading_empty = _internal_instruction_blocks(blocks, management_heading_idx)

    page_break_index, post_report_excluded_blocks = _post_report_boundary(blocks)

    managed_blocks = [b for b in blocks if management_heading_idx <= _block_index(b) < page_break_index]

    business_heading_idx = _block_index(heading_blocks["businessInformation"])
    multi_year_heading_idx = _block_index(heading_blocks["multiYearOverview"])
    significant_heading_idx = _block_index(heading_blocks["significantEvents"])
    research_heading_idx = _block_index(heading_blocks["researchAndDevelopment"])
    sustainability_heading_idx = _block_index(heading_blocks["sustainabilityDisclosures"])
    future_heading_idx = _block_index(heading_blocks["futureDevelopmentAndRisks"])
    equity_heading_idx = _block_index(heading_blocks["equityAndProfitDisposition"])

    intro_candidate = _slice_by_index(managed_blocks, management_heading_idx, business_heading_idx)
    intro_paragraphs = [b for b in intro_candidate if b.get("blockType") == "paragraph"]
    if not intro_paragraphs:
        raise ContractError("Missing introductory paragraph content")

    currency_start_idx: Optional[int] = None
    for b in intro_paragraphs:
        if "Årsredovisningen är upprättad i svenska kronor, SEK." in _paragraph_text(b):
            currency_start_idx = _block_index(b)
            break
    if currency_start_idx is None:
        raise ContractError("Missing required currency statement section")

    introductory_paragraphs = [b for b in intro_paragraphs if _block_index(b) < currency_start_idx]
    currency_paragraphs = [b for b in intro_paragraphs if _block_index(b) >= currency_start_idx]

    if not any(_non_empty(_paragraph_text(b)) for b in introductory_paragraphs):
        raise ContractError("Introductory statement is empty")
    if not any(_non_empty(_paragraph_text(b)) for b in currency_paragraphs):
        raise ContractError("Currency statement is empty")

    period_raw, period_start, period_end, period_block_ids = _find_period_evidence(intro_paragraphs)

    metadata = load_report_metadata(metadata_path)
    metadata_current_parts = [p.strip() for p in metadata.current_reporting_period.splitlines() if p.strip()]
    if len(metadata_current_parts) != 2:
        raise ContractError("Metadata currentReportingPeriod must have two date lines")
    metadata_start = metadata_current_parts[0]
    metadata_end = metadata_current_parts[1].lstrip("-")
    if period_start != metadata_start or period_end != metadata_end:
        raise ContractError("Contradictory reporting period between DOCX and report metadata")

    in_alignment_scope = _scope_matches_signed_reference_alignment(metadata)

    business_paragraphs = [b for b in _slice_by_index(managed_blocks, business_heading_idx, multi_year_heading_idx) if b.get("blockType") == "paragraph"]
    significant_paragraphs = [b for b in _slice_by_index(managed_blocks, significant_heading_idx, research_heading_idx) if b.get("blockType") == "paragraph"]
    research_paragraphs = [b for b in _slice_by_index(managed_blocks, research_heading_idx, sustainability_heading_idx) if b.get("blockType") == "paragraph"]
    sustainability_paragraphs = [b for b in _slice_by_index(managed_blocks, sustainability_heading_idx, future_heading_idx) if b.get("blockType") == "paragraph"]
    future_paragraphs = [b for b in _slice_by_index(managed_blocks, future_heading_idx, equity_heading_idx) if b.get("blockType") == "paragraph"]

    normalized_business_paragraphs: List[Dict[str, object]] = []
    signed_reference_corrections: List[Dict[str, object]] = []

    office_candidates: List[Dict[str, object]] = []
    office_phrase_seen_outside_business = False
    for block in managed_blocks:
        if block.get("blockType") != "paragraph":
            continue
        text = _paragraph_text(block)
        if OFFICE_ALIGNMENT_OLD_VALUE in text:
            if business_heading_idx < _block_index(block) < multi_year_heading_idx:
                office_candidates.append(block)
            else:
                office_phrase_seen_outside_business = True

    if office_phrase_seen_outside_business:
        raise ContractError("Signed-reference office-location phrase found outside approved businessInformation section")

    if office_candidates:
        if not in_alignment_scope:
            raise ContractError("Signed-reference office-location correction out of approved entity/period scope")
        if len(office_candidates) > 1:
            raise ContractError("Multiple office-location candidates found for signed-reference alignment")

    office_candidate_id: Optional[str] = None
    if len(office_candidates) == 1:
        oc = office_candidates[0].get("blockId")
        if isinstance(oc, str):
            office_candidate_id = oc

    for block in business_paragraphs:
        paragraph = block.get("paragraph")
        if not isinstance(paragraph, dict):
            normalized_business_paragraphs.append(block)
            continue
        text = paragraph.get("text")
        if not isinstance(text, str):
            normalized_business_paragraphs.append(block)
            continue
        if "Oslo" in text and OFFICE_ALIGNMENT_OLD_VALUE not in text:
            raise ContractError("Office-location source wording differs from approved signed-reference match text")

        block_id = block.get("blockId")
        is_target = isinstance(block_id, str) and block_id == office_candidate_id
        if is_target:
            replaced = text.replace(OFFICE_ALIGNMENT_OLD_VALUE, OFFICE_ALIGNMENT_NEW_VALUE, 1)
            if replaced == text:
                raise ContractError("Office-location alignment target block did not contain approved source phrase")
            block_copy = dict(block)
            paragraph_copy = dict(paragraph)
            paragraph_copy["text"] = replaced
            block_copy["paragraph"] = paragraph_copy
            normalized_business_paragraphs.append(block_copy)
            signed_reference_corrections.append(
                {
                    "correctionId": OFFICE_ALIGNMENT_CORRECTION_ID,
                    "diagnosticCode": OFFICE_ALIGNMENT_DIAGNOSTIC,
                    "signedReferencePage": OFFICE_ALIGNMENT_SIGNED_PAGE,
                    "approvalScope": _correction_approval_scope("businessInformation"),
                    "authorityType": SIGNED_REFERENCE_AUTHORITY_TYPE,
                    "sectionKey": "businessInformation",
                    "sourceBlockId": block_id,
                    "originalValue": OFFICE_ALIGNMENT_OLD_VALUE,
                    "alignedValue": OFFICE_ALIGNMENT_NEW_VALUE,
                    "disposition": "text_replaced",
                    "matchedSourceText": text,
                }
            )
            continue
        normalized_business_paragraphs.append(block)

    multi_year_range = _slice_by_index(managed_blocks, multi_year_heading_idx, significant_heading_idx)
    multi_year_table = _require_single_table_in_range(multi_year_range, expected_rows=8, expected_cols=6, label="multiYearOverview")

    equity_range = _slice_by_index(managed_blocks, equity_heading_idx, page_break_index)
    equity_table = _require_single_table_in_range(equity_range, expected_rows=11, expected_cols=6, label="equityAndProfitDisposition")

    # Closing transition is expected after the equity table and before the explicit page break.
    equity_table_idx = _block_index(equity_table)
    closing_paragraphs = [
        b
        for b in managed_blocks
        if b.get("blockType") == "paragraph" and _block_index(b) > equity_table_idx
    ]
    closing_start_matches = [
        b for b in closing_paragraphs if _paragraph_text(b).strip() == CLOSING_SUPPRESSION_OLD_VALUE_1
    ]
    closing_tail_matches = [
        b for b in closing_paragraphs if _paragraph_text(b).strip() == CLOSING_SUPPRESSION_OLD_VALUE_2
    ]

    if closing_start_matches or closing_tail_matches:
        if not in_alignment_scope:
            raise ContractError("Signed-reference closing-suppression correction out of approved entity/period scope")
        if len(closing_start_matches) != 1 or len(closing_tail_matches) != 1:
            raise ContractError("Closing-suppression correction requires exactly one matching source block per sentence")

        removed_ids = {
            closing_start_matches[0].get("blockId"),
            closing_tail_matches[0].get("blockId"),
        }
        closing_paragraphs = [
            b for b in closing_paragraphs if b.get("blockId") not in removed_ids
        ]

        start_id = closing_start_matches[0].get("blockId")
        tail_id = closing_tail_matches[0].get("blockId")
        if not isinstance(start_id, str) or not isinstance(tail_id, str):
            raise ContractError("Closing-suppression correction requires stable source block ids")

        signed_reference_corrections.append(
            {
                "correctionId": CLOSING_SUPPRESSION_CORRECTION_ID,
                "diagnosticCode": CLOSING_SUPPRESSION_DIAGNOSTIC,
                "signedReferencePage": CLOSING_SUPPRESSION_SIGNED_PAGE,
                "approvalScope": _correction_approval_scope("closingTransition"),
                "authorityType": SIGNED_REFERENCE_AUTHORITY_TYPE,
                "sectionKey": "closingTransition",
                "sourceBlockId": start_id,
                "originalValue": CLOSING_SUPPRESSION_OLD_VALUE_1,
                "alignedValue": CLOSING_SUPPRESSION_DISPOSITION,
                "disposition": CLOSING_SUPPRESSION_DISPOSITION,
                "excludedSourceBlockIds": [start_id, tail_id],
                "matchedValues": [CLOSING_SUPPRESSION_OLD_VALUE_1, CLOSING_SUPPRESSION_OLD_VALUE_2],
            }
        )

    if not closing_paragraphs:
        raise ContractError("Closing transition became structurally empty after signed-reference suppression")

    closing_has_non_empty = any(_non_empty(_paragraph_text(b)) for b in closing_paragraphs)
    if not closing_has_non_empty:
        structural_ids = [b.get("blockId") for b in closing_paragraphs if isinstance(b.get("blockId"), str)]
        if not structural_ids:
            raise ContractError("Closing transition is structurally invalid after signed-reference suppression")

    sustainability_heading_text = _paragraph_text(heading_blocks["sustainabilityDisclosures"])
    forced_sustainability_heading: Optional[str] = None
    if sustainability_heading_text == SUSTAINABILITY_HEADING_OLD_VALUE:
        if not in_alignment_scope:
            raise ContractError("Signed-reference sustainability-heading correction out of approved entity/period scope")
        forced_sustainability_heading = SUSTAINABILITY_HEADING_NEW_VALUE
        sustainability_block_id = heading_blocks["sustainabilityDisclosures"].get("blockId")
        if not isinstance(sustainability_block_id, str) or not sustainability_block_id:
            raise ContractError("Sustainability heading correction requires stable source block id")
        signed_reference_corrections.append(
            {
                "correctionId": SUSTAINABILITY_HEADING_CORRECTION_ID,
                "diagnosticCode": SUSTAINABILITY_HEADING_DIAGNOSTIC,
                "signedReferencePage": SUSTAINABILITY_HEADING_SIGNED_PAGE,
                "approvalScope": _correction_approval_scope("sustainabilityDisclosures"),
                "authorityType": SIGNED_REFERENCE_AUTHORITY_TYPE,
                "sectionKey": "sustainabilityDisclosures",
                "sourceBlockId": sustainability_block_id,
                "originalValue": SUSTAINABILITY_HEADING_OLD_VALUE,
                "alignedValue": SUSTAINABILITY_HEADING_NEW_VALUE,
                "disposition": "heading_normalized",
            }
        )
    elif sustainability_heading_text == SUSTAINABILITY_HEADING_NEW_VALUE:
        forced_sustainability_heading = None

    sections = [
        _build_section_payload("managementReportHeading", heading_blocks["managementReportHeading"], []),
        _build_section_payload("introductoryStatement", None, introductory_paragraphs),
        _build_section_payload("currencyStatement", None, currency_paragraphs),
        _build_section_payload("businessInformation", heading_blocks["businessInformation"], normalized_business_paragraphs),
        _build_section_payload("significantEvents", heading_blocks["significantEvents"], significant_paragraphs),
        _build_section_payload("futureDevelopmentAndRisks", heading_blocks["futureDevelopmentAndRisks"], future_paragraphs),
        _build_section_payload("researchAndDevelopment", heading_blocks["researchAndDevelopment"], research_paragraphs),
        _build_section_payload(
            "sustainabilityDisclosures",
            heading_blocks["sustainabilityDisclosures"],
            sustainability_paragraphs,
            forced_heading_text=forced_sustainability_heading,
        ),
        _build_section_payload("multiYearOverview", heading_blocks["multiYearOverview"], []),
        _build_section_payload("equityAndProfitDisposition", heading_blocks["equityAndProfitDisposition"], []),
        _build_section_payload("closingTransition", None, closing_paragraphs),
    ]

    tables = [
        {
            "tableKey": "multiYearOverview",
            "sourceBlockId": multi_year_table.get("blockId"),
            "table": multi_year_table.get("table"),
        },
        {
            "tableKey": "equityAndProfitDisposition",
            "sourceBlockId": equity_table.get("blockId"),
            "table": equity_table.get("table"),
        },
    ]

    excluded_content = [
        {
            "exclusionKey": "internalTemplateInstructions",
            "diagnosticCode": "INTERNAL_TEMPLATE_INSTRUCTION_EXCLUDED",
            "reason": "Internal template/helper instruction text was detected before management report heading.",
            "blocks": [
                {
                    "sourceBlockId": b.get("blockId"),
                    "text": _paragraph_text(b),
                }
                for b in (instruction_blocks + pre_heading_empty)
            ],
        },
        {
            "exclusionKey": "postReportNoteUpdateContent",
            "diagnosticCode": "POST_REPORT_NOTE_UPDATE_CONTENT_EXCLUDED",
            "reason": "Content after explicit page break was classified as post-report note-update material.",
            "blocks": [
                {
                    "sourceBlockId": b.get("blockId"),
                    "blockType": b.get("blockType"),
                    "text": _paragraph_text(b) if b.get("blockType") == "paragraph" else "",
                }
                for b in post_report_excluded_blocks
            ],
        },
    ]

    diagnostics = [
        {
            "code": "INTERNAL_TEMPLATE_INSTRUCTION_EXCLUDED",
            "severity": "info",
            "message": "Internal helper/instruction content excluded from management-report semantics.",
            "sourceBlockIds": [b.get("blockId") for b in (instruction_blocks + pre_heading_empty)],
        },
        {
            "code": "POST_REPORT_NOTE_UPDATE_CONTENT_EXCLUDED",
            "severity": "info",
            "message": "Post-report note-update content excluded based on explicit page-break boundary and heading evidence.",
            "sourceBlockIds": [b.get("blockId") for b in post_report_excluded_blocks],
        },
        {
            "code": "EQUITY_DISPOSITION_SOURCE_AUTHORITY_UNRESOLVED",
            "severity": "review_required",
            "message": "Equity/disposition source authority is unresolved; DOCX Table 2 is preserved exactly and requires manual approval before rendering authority is finalized.",
            "sourceBlockId": equity_table.get("blockId"),
        },
    ]

    for correction in signed_reference_corrections:
        diagnostics.append(
            {
                "code": correction["diagnosticCode"],
                "severity": "info",
                "message": "Signed-reference correction applied.",
                "sectionKey": correction["sectionKey"],
                "sourceBlockId": correction["sourceBlockId"],
                "correctionId": correction["correctionId"],
            }
        )
    diagnostics.extend(unsupported_semantic_diagnostics)

    _validate_signed_reference_corrections(signed_reference_corrections, diagnostics, sections)

    used_set = _validate_source_block_accounting(
        blocks,
        sections,
        tables,
        excluded_content,
        signed_reference_corrections,
        enforce_completeness=False,
    )

    structural_whitespace_blocks: List[Dict[str, object]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        bid = block.get("blockId")
        if not isinstance(bid, str) or bid in used_set:
            continue
        if block.get("blockType") != "paragraph":
            continue
        if _paragraph_text(block).strip() == "":
            structural_whitespace_blocks.append(block)

    if structural_whitespace_blocks:
        excluded_content.append(
            {
                "category": "structuralWhitespace",
                "message": "Structural empty paragraphs excluded while preserving source traceability.",
                "sourceBlockIds": [b.get("blockId") for b in structural_whitespace_blocks],
                "blocks": [
                    {
                        "sourceBlockId": b.get("blockId"),
                        "text": _paragraph_text(b),
                    }
                    for b in structural_whitespace_blocks
                ],
            }
        )
        used_set.update(
            b.get("blockId")
            for b in structural_whitespace_blocks
            if isinstance(b.get("blockId"), str)
        )

    _validate_source_block_accounting(
        blocks,
        sections,
        tables,
        excluded_content,
        signed_reference_corrections,
    )

    raw_hash = _sha256_bytes(_canonical_json_bytes(raw_contract))

    semantic_contract: Dict[str, object] = {
        "schemaVersion": "1.0",
        "status": "review_required",
        "sourceEvidence": {
            "file": source_file,
            "sha256": source_sha,
            "coreProperties": source.get("coreProperties", {}),
        },
        "periodEvidence": {
            "rawDetectedText": period_raw,
            "normalizedCurrentPeriod": f"{period_start}\n-{period_end}",
            "metadataCurrentPeriod": metadata.current_reporting_period,
            "validationResult": "match",
            "sourceBlockIds": period_block_ids,
        },
        "sections": sections,
        "tables": tables,
        "excludedContent": excluded_content,
        "signedReferenceCorrections": signed_reference_corrections,
        "unresolvedAmbiguities": [],
        "diagnostics": diagnostics,
        "rawContractSha256": raw_hash,
    }

    canonical = json.loads(_canonical_json_bytes(semantic_contract).decode("utf-8"))
    return canonical


def semantic_contract_json_bytes(contract: Dict[str, object]) -> bytes:
    return _canonical_json_bytes(contract)
