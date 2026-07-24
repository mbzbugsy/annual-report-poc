from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from report_metadata import ReportMetadata, load_report_metadata


class ManagementReportRenderError(ValueError):
    pass


RENDERER_VERSION = "2.0"

EXPECTED_SECTION_ORDER = [
    "managementReportHeading",
    "introductoryStatement",
    "currencyStatement",
    "businessInformation",
    "significantEvents",
    "futureDevelopmentAndRisks",
    "researchAndDevelopment",
    "sustainabilityDisclosures",
    "multiYearOverview",
    "equityAndProfitDisposition",
    "closingTransition",
]

APPROVED_MULTI_YEAR_LABELS: List[Tuple[str, str]] = [
    ("Nettoomsättning", "Nettoomsättning"),
    ("Rörelseresultat", "Rörelseresultat"),
    ("Resultat efter skatt", "Resultat efter skatt"),
    ("Rörelsemarginal %", "Rörelsemarginal (%)"),
    ("Soliditet%\nDefinitioner: se not xx", "Soliditet (%)"),
]

APPROVED_SOLIDITET_SOURCE_LABELS = {
    "Soliditet%\nDefinitioner: se not xx",
    "Soliditet%Definitioner: se not xx",
}

APPROVED_MULTI_YEAR_REFERENCE_LINE = "För definitioner av nyckeltal, se Redovisnings- och värderingsprinciper."

REQUIRED_OVERRIDE_SOURCE_TYPE = "signed_reference_preview_override"
REQUIRED_OVERRIDE_APPROVAL_SCOPE = "poc_preview_only"
REQUIRED_SIGNED_REFERENCE_SHA256 = "e4396bbe09d63a6b4a3828fc6f63c9cd5b18a4b9500fe58acfe303428b0768f0"

REQUIRED_OVERRIDE_FIELDS = {
    "schemaVersion",
    "sourceType",
    "approvalScope",
    "companyName",
    "organizationNumber",
    "currentReportingPeriod",
    "signedReference",
    "coveredDiagnosticCodes",
    "coveredSourceBlockIds",
    "overriddenFields",
    "changesInEquity",
    "profitDisposition",
}

EXPECTED_OVERRIDE_FIELD_MANIFEST = [
    "changesInEquity.heading",
    "changesInEquity.columns",
    "changesInEquity.rows",
    "profitDisposition.heading",
    "profitDisposition.intro",
    "profitDisposition.lines",
    "profitDisposition.dispositionLead",
    "profitDisposition.disposalLines",
    "profitDisposition.closingStatement",
]

EXPECTED_CHANGES_IN_EQUITY_ROW_LABELS = [
    "Belopp vid årets ingång",
    "Balanseras i ny räkning",
    "Årets resultat",
    "Belopp vid årets utgång",
]

EXPECTED_PROFIT_LINES_LABELS = [
    "balanserad vinst",
    "årets vinst",
    "",
]

EXPECTED_DISPOSAL_LINES_LABELS = [
    "i ny räkning överföres",
    "",
]

ALLOWED_BLOCKING_SEVERITIES = {"blocking", "blocker", "error", "fatal"}
REVIEW_REQUIRED_SEVERITY = "review_required"
OVERRIDE_SCOPE_EQUITY_TABLE_TOKEN = "equityAndProfitDisposition.table"
IMPLICITLY_SCOPED_DECORATIVE_CODES = {
    "UNSUPPORTED_DECORATIVE_DRAWING_PRESENT",
    "UNSUPPORTED_DECORATIVE_PICT_PRESENT",
}

SIGNED_REFERENCE_AUTHORITY_TYPE = "signed_reference_pdf"
SIGNED_REFERENCE_ALIGNMENT_SCOPE_ID = "management_alignment_entity_period_section_v1"

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
CLOSING_SUPPRESSION_DISPOSITION = "excluded_from_closing_transition"

EXPECTED_SIGNED_REFERENCE_FINAL_CLOSING_PARAGRAPH = (
    "Företagets resultat och ställning i övrigt framgår av efterföljande resultat- och balansräkning samt kassaflödesanalys med noter."
)


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "_": "\\_",
        "#": "\\#",
        "$": "\\$",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagementReportRenderError(f"Expected object for '{field_name}'")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManagementReportRenderError(f"Missing or invalid non-empty string '{field_name}'")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ManagementReportRenderError(f"Missing or invalid string '{field_name}'")
    return value


def _load_json(path: Path, *, field_name: str) -> Dict[str, Any]:
    if not path.exists():
        raise ManagementReportRenderError(f"Missing {field_name}: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManagementReportRenderError(f"Invalid JSON in {field_name}: {path}") from exc
    if not isinstance(raw, dict):
        raise ManagementReportRenderError(f"Top-level JSON must be object in {field_name}: {path}")
    return raw


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_string_list(value: Any, field_name: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise ManagementReportRenderError(f"Missing or invalid non-empty string list '{field_name}'")
    out: List[str] = []
    for item in value:
        out.append(_require_non_empty_string(item, field_name))
    return out


def _require_heading_text(value: Any, field_name: str) -> str:
    text = _require_non_empty_string(value, field_name)
    return text.strip()


def _paragraph_texts(section: Dict[str, Any]) -> List[str]:
    paragraphs = section.get("paragraphs")
    if not isinstance(paragraphs, list):
        raise ManagementReportRenderError("Section paragraphs must be a list")

    texts: List[str] = []
    for paragraph in paragraphs:
        payload = _require_dict(paragraph, "section paragraph")
        text = payload.get("text")
        if not isinstance(text, str):
            raise ManagementReportRenderError("Section paragraph text must be a string")
        if text.strip():
            texts.append(text)
    return texts


def _require_unique_source_block_ids(items: Sequence[str], field_name: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        raise ManagementReportRenderError(f"Duplicate sourceBlockIds in '{field_name}': {sorted(duplicates)}")


def _resolve_sections(semantic_contract: Dict[str, Any]) -> Dict[str, Any]:
    sections = semantic_contract.get("sections")
    if not isinstance(sections, list):
        raise ManagementReportRenderError("Management report semantic contract must include list 'sections'")

    seen_keys: set[str] = set()
    mapped: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []
    source_usage: Dict[str, str] = {}

    def _register_source(source_block_id: str, destination: str) -> None:
        prior = source_usage.get(source_block_id)
        if prior is not None and prior != destination:
            raise ManagementReportRenderError(
                f"sourceBlockId '{source_block_id}' is used in more than one destination: '{prior}' and '{destination}'"
            )
        source_usage[source_block_id] = destination

    for section in sections:
        section_obj = _require_dict(section, "section")
        key = _require_non_empty_string(section_obj.get("sectionKey"), "sectionKey")
        if key in seen_keys:
            raise ManagementReportRenderError(f"Duplicate sectionKey detected: '{key}'")
        if key not in EXPECTED_SECTION_ORDER:
            raise ManagementReportRenderError(f"Unknown sectionKey detected: '{key}'")
        seen_keys.add(key)
        ordered_keys.append(key)

        heading = _require_dict(section_obj.get("heading"), f"{key}.heading")
        heading_source = heading.get("sourceBlockId")
        if isinstance(heading_source, str) and heading_source.strip():
            _register_source(heading_source, f"section:{key}:heading")

        paragraphs = section_obj.get("paragraphs")
        if not isinstance(paragraphs, list):
            raise ManagementReportRenderError(f"Section '{key}' paragraphs must be a list")
        paragraph_sources: List[str] = []
        for index, paragraph in enumerate(paragraphs):
            paragraph_obj = _require_dict(paragraph, f"{key}.paragraph[{index}]")
            source_id = _require_non_empty_string(
                paragraph_obj.get("sourceBlockId"),
                f"{key}.paragraph[{index}].sourceBlockId",
            )
            paragraph_sources.append(source_id)
            _register_source(source_id, f"section:{key}:paragraph[{index}]")
        _require_unique_source_block_ids(paragraph_sources, f"{key}.paragraphs")

        mapped[key] = section_obj

    missing = sorted(set(EXPECTED_SECTION_ORDER).difference(mapped.keys()))
    if missing:
        raise ManagementReportRenderError(f"Management report semantic contract missing required sections: {missing}")
    if ordered_keys != EXPECTED_SECTION_ORDER:
        raise ManagementReportRenderError(
            f"Management report semantic sections must use exact required order: {EXPECTED_SECTION_ORDER}"
        )

    return {
        "sections": mapped,
        "source_usage": source_usage,
    }


def _resolve_multi_year_table(semantic_contract: Dict[str, Any], source_usage: Dict[str, str]) -> Dict[str, Any]:
    tables = semantic_contract.get("tables")
    if not isinstance(tables, list) or len(tables) < 2:
        raise ManagementReportRenderError("Management report semantic contract must include both required tables")

    table_payload = _require_dict(tables[0], "tables[0]")
    multi_year_source_id = _require_non_empty_string(table_payload.get("sourceBlockId"), "tables[0].sourceBlockId")
    prior = source_usage.get(multi_year_source_id)
    if prior is not None and prior != "table:multiYearOverview":
        raise ManagementReportRenderError(
            f"sourceBlockId '{multi_year_source_id}' is used in more than one destination: '{prior}' and 'table:multiYearOverview'"
        )
    source_usage[multi_year_source_id] = "table:multiYearOverview"

    table = _require_dict(table_payload.get("table"), "tables[0].table")
    rows = table.get("rows")
    if not isinstance(rows, list) or len(rows) < 8:
        raise ManagementReportRenderError("Management report multi-year table shape is invalid")

    def _row_cells(row: Dict[str, Any]) -> List[str]:
        cells = row.get("cells")
        if not isinstance(cells, list):
            raise ManagementReportRenderError("Table row must include list 'cells'")

        values: List[str] = []
        for cell in cells:
            cell_obj = _require_dict(cell, "table cell")
            text = cell_obj.get("text", "")
            if not isinstance(text, str):
                raise ManagementReportRenderError("Table cell text must be string")
            values.append(text)
        return values

    years_start = _row_cells(_require_dict(rows[1], "multiYear rows[1]"))[1:]
    years_end = _row_cells(_require_dict(rows[2], "multiYear rows[2]"))[1:]
    if len(years_start) != 5 or len(years_end) != 5:
        raise ManagementReportRenderError("Management report multi-year year headers must have five periods")

    value_rows: List[Dict[str, Any]] = []
    display_mappings: List[Dict[str, str]] = []
    for index, row in enumerate(rows[3:8]):
        values = _row_cells(_require_dict(row, "multiYear value row"))
        if len(values) < 6:
            raise ManagementReportRenderError("Management report multi-year row has too few columns")
        expected_source, display_label = APPROVED_MULTI_YEAR_LABELS[index]
        source_label = _require_string(values[0], "multiYear source label")
        if index == 4:
            label_ok = source_label in APPROVED_SOLIDITET_SOURCE_LABELS
        else:
            label_ok = source_label == expected_source
        if not label_ok:
            raise ManagementReportRenderError(
                f"Unexpected multi-year source label at row {index + 4}: expected '{expected_source}', got '{source_label}'"
            )
        display_mappings.append({"sourceLabel": source_label, "displayLabel": display_label})

        value_rows.append(
            {
                "sourceLabel": source_label,
                "label": display_label,
                "values": values[1:6],
            }
        )

    return {
        "sourceBlockId": multi_year_source_id,
        "years": [f"{start}-{end}" for start, end in zip(years_start, years_end)],
        "rows": value_rows,
        "displayMappings": display_mappings,
    }


def _extract_diagnostic_source_block_ids(diagnostic: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    direct = diagnostic.get("sourceBlockId")
    if isinstance(direct, str) and direct.strip():
        out.add(direct)

    source_block_ids = diagnostic.get("sourceBlockIds")
    if isinstance(source_block_ids, list):
        for item in source_block_ids:
            if isinstance(item, str) and item.strip():
                out.add(item)

    source_refs = diagnostic.get("sourceRefs")
    if isinstance(source_refs, list):
        for ref in source_refs:
            if isinstance(ref, dict):
                block_id = ref.get("blockId")
                if isinstance(block_id, str) and block_id.strip():
                    out.add(block_id)
    return out


def _validate_equity_override(
    preview_override: Dict[str, Any],
    *,
    metadata: ReportMetadata,
    semantic_contract: Dict[str, Any],
    equity_table_source_block_id: str,
) -> Dict[str, Any]:
    missing_fields = sorted(REQUIRED_OVERRIDE_FIELDS.difference(preview_override.keys()))
    if missing_fields:
        raise ManagementReportRenderError(f"Missing required override fields: {missing_fields}")

    source_type = _require_non_empty_string(preview_override.get("sourceType"), "sourceType")
    if source_type != REQUIRED_OVERRIDE_SOURCE_TYPE:
        raise ManagementReportRenderError("Equity override sourceType must be 'signed_reference_preview_override'")

    approval_scope = _require_non_empty_string(preview_override.get("approvalScope"), "approvalScope")
    if approval_scope != REQUIRED_OVERRIDE_APPROVAL_SCOPE:
        raise ManagementReportRenderError("Equity override approvalScope must be 'poc_preview_only'")

    signed_reference = _require_dict(preview_override.get("signedReference"), "signedReference")
    reference_sha = _require_non_empty_string(signed_reference.get("sha256"), "signedReference.sha256")
    if reference_sha != REQUIRED_SIGNED_REFERENCE_SHA256:
        raise ManagementReportRenderError("Equity override signed reference SHA-256 mismatch")

    company_name = _require_non_empty_string(preview_override.get("companyName"), "companyName")
    if company_name != metadata.company_name:
        raise ManagementReportRenderError("Override companyName does not match metadata")

    organization_number = _require_non_empty_string(preview_override.get("organizationNumber"), "organizationNumber")
    if organization_number != metadata.organization_number:
        raise ManagementReportRenderError("Override organizationNumber does not match metadata")

    reporting_period = _require_non_empty_string(preview_override.get("currentReportingPeriod"), "currentReportingPeriod")
    if reporting_period != metadata.current_reporting_period:
        raise ManagementReportRenderError("Override currentReportingPeriod does not match metadata")

    period_evidence = _require_dict(semantic_contract.get("periodEvidence"), "periodEvidence")
    semantic_reporting_period = _require_non_empty_string(
        period_evidence.get("normalizedCurrentPeriod"),
        "periodEvidence.normalizedCurrentPeriod",
    )
    if semantic_reporting_period != metadata.current_reporting_period:
        raise ManagementReportRenderError("Semantic reporting period does not match metadata")

    covered_diagnostic_codes = _require_string_list(preview_override.get("coveredDiagnosticCodes"), "coveredDiagnosticCodes")
    covered_source_block_ids = _require_string_list(preview_override.get("coveredSourceBlockIds"), "coveredSourceBlockIds")
    overridden_fields = _require_string_list(preview_override.get("overriddenFields"), "overriddenFields")

    if len(set(covered_diagnostic_codes)) != len(covered_diagnostic_codes):
        raise ManagementReportRenderError("coveredDiagnosticCodes contains duplicate values")
    if len(set(covered_source_block_ids)) != len(covered_source_block_ids):
        raise ManagementReportRenderError("coveredSourceBlockIds contains duplicate values")
    if len(set(overridden_fields)) != len(overridden_fields):
        raise ManagementReportRenderError("overriddenFields contains duplicate values")

    resolved_covered_source_ids: List[str] = []
    for covered_source in covered_source_block_ids:
        if covered_source == OVERRIDE_SCOPE_EQUITY_TABLE_TOKEN:
            resolved_covered_source_ids.append(equity_table_source_block_id)
            continue
        resolved_covered_source_ids.append(covered_source)

    covered_source_set = set(resolved_covered_source_ids)
    if not covered_source_set:
        raise ManagementReportRenderError("coveredSourceBlockIds must not be empty")
    if not covered_source_set.issubset({equity_table_source_block_id}):
        raise ManagementReportRenderError(
            "coveredSourceBlockIds includes a source block not used by the overridden equity/disposition table"
        )

    expected_fields = set(EXPECTED_OVERRIDE_FIELD_MANIFEST)
    manifest_fields = set(overridden_fields)
    if manifest_fields != expected_fields:
        missing_manifest = sorted(expected_fields.difference(manifest_fields))
        unexpected_manifest = sorted(manifest_fields.difference(expected_fields))
        raise ManagementReportRenderError(
            f"Invalid overriddenFields manifest. Missing={missing_manifest}, unexpected={unexpected_manifest}"
        )

    diagnostics_raw = semantic_contract.get("diagnostics")
    if not isinstance(diagnostics_raw, list):
        raise ManagementReportRenderError("Semantic contract must include diagnostics list")

    diagnostics: List[Dict[str, Any]] = []
    for diagnostic in diagnostics_raw:
        diagnostics.append(_require_dict(diagnostic, "diagnostics[]"))

    semantic_codes = {_require_non_empty_string(d.get("code"), "diagnostics[].code") for d in diagnostics}
    override_code_set = set(covered_diagnostic_codes)
    missing_codes_in_semantic = sorted(override_code_set.difference(semantic_codes))
    if missing_codes_in_semantic:
        raise ManagementReportRenderError(
            f"coveredDiagnosticCodes includes codes not present in semantic diagnostics: {missing_codes_in_semantic}"
        )

    allowed_review_codes = set(covered_diagnostic_codes)
    for diagnostic in diagnostics:
        code = _require_non_empty_string(diagnostic.get("code"), "diagnostics[].code")
        severity = _require_non_empty_string(diagnostic.get("severity"), f"diagnostics[{code}].severity")

        if severity in ALLOWED_BLOCKING_SEVERITIES:
            raise ManagementReportRenderError(f"Blocking diagnostic is not allowed for rendering: {code}")

        if severity != REVIEW_REQUIRED_SEVERITY:
            continue

        source_ids = _extract_diagnostic_source_block_ids(diagnostic)
        if not source_ids:
            raise ManagementReportRenderError(f"review_required diagnostic lacks source block references: {code}")
        if not source_ids.issubset(covered_source_set):
            raise ManagementReportRenderError(
                f"review_required diagnostic '{code}' has uncovered source blocks: {sorted(source_ids.difference(covered_source_set))}"
            )

        if code not in allowed_review_codes and code not in IMPLICITLY_SCOPED_DECORATIVE_CODES:
            raise ManagementReportRenderError(f"review_required diagnostic is not explicitly covered by override: {code}")

    if "EQUITY_DISPOSITION_SOURCE_AUTHORITY_UNRESOLVED" not in allowed_review_codes:
        raise ManagementReportRenderError("coveredDiagnosticCodes must include EQUITY_DISPOSITION_SOURCE_AUTHORITY_UNRESOLVED")

    return {
        "sourceType": source_type,
        "approvalScope": approval_scope,
        "coveredDiagnosticCodes": covered_diagnostic_codes,
        "coveredSourceBlockIds": sorted(covered_source_set),
        "overriddenFields": overridden_fields,
    }


def _validate_override_financial_shapes(preview_override: Dict[str, Any]) -> None:
    _require_non_empty_string(preview_override.get("schemaVersion"), "schemaVersion")
    changes = _require_dict(preview_override.get("changesInEquity"), "changesInEquity")
    columns = changes.get("columns")
    rows = changes.get("rows")

    if not isinstance(columns, list) or len(columns) != 5:
        raise ManagementReportRenderError("changesInEquity.columns must contain exactly 5 entries")
    for col in columns:
        _require_non_empty_string(col, "changesInEquity.columns[]")

    if not isinstance(rows, list) or len(rows) != len(EXPECTED_CHANGES_IN_EQUITY_ROW_LABELS):
        raise ManagementReportRenderError("changesInEquity.rows must contain exactly 4 rows")

    seen_labels: set[str] = set()
    for index, row_payload in enumerate(rows):
        row_obj = _require_dict(row_payload, "changesInEquity.rows[]")
        label = _require_non_empty_string(row_obj.get("label"), "changesInEquity.rows[].label")
        expected_label = EXPECTED_CHANGES_IN_EQUITY_ROW_LABELS[index]
        if label != expected_label:
            raise ManagementReportRenderError(
                f"Unexpected changesInEquity row label at index {index}: expected '{expected_label}', got '{label}'"
            )
        if label in seen_labels:
            raise ManagementReportRenderError(f"Duplicate changesInEquity row label: '{label}'")
        seen_labels.add(label)

        values = row_obj.get("values")
        if not isinstance(values, list) or len(values) != 5:
            raise ManagementReportRenderError("Each changesInEquity row must have exactly 5 values")
        for value in values:
            _require_string(value, "changesInEquity row value")

    disposition = _require_dict(preview_override.get("profitDisposition"), "profitDisposition")
    _require_non_empty_string(disposition.get("heading"), "profitDisposition.heading")
    _require_non_empty_string(disposition.get("intro"), "profitDisposition.intro")
    _require_non_empty_string(disposition.get("dispositionLead"), "profitDisposition.dispositionLead")
    closing_statement = _require_non_empty_string(disposition.get("closingStatement"), "profitDisposition.closingStatement")
    if closing_statement != EXPECTED_SIGNED_REFERENCE_FINAL_CLOSING_PARAGRAPH:
        raise ManagementReportRenderError("profitDisposition.closingStatement must match approved signed-reference final paragraph")

    lines_payload = disposition.get("lines")
    if not isinstance(lines_payload, list) or len(lines_payload) != len(EXPECTED_PROFIT_LINES_LABELS):
        raise ManagementReportRenderError("profitDisposition.lines must contain exactly 3 rows")

    for index, entry in enumerate(lines_payload):
        row = _require_dict(entry, "profitDisposition.lines[]")
        label = _require_string(row.get("label"), "profitDisposition.lines[].label")
        if label != EXPECTED_PROFIT_LINES_LABELS[index]:
            raise ManagementReportRenderError(
                f"Unexpected profitDisposition.lines label at index {index}: expected '{EXPECTED_PROFIT_LINES_LABELS[index]}', got '{label}'"
            )
        _require_non_empty_string(row.get("amount"), "profitDisposition.lines[].amount")

    disposal_lines_payload = disposition.get("disposalLines")
    if not isinstance(disposal_lines_payload, list) or len(disposal_lines_payload) != len(EXPECTED_DISPOSAL_LINES_LABELS):
        raise ManagementReportRenderError("profitDisposition.disposalLines must contain exactly 2 rows")

    for index, entry in enumerate(disposal_lines_payload):
        row = _require_dict(entry, "profitDisposition.disposalLines[]")
        label = _require_string(row.get("label"), "profitDisposition.disposalLines[].label")
        if label != EXPECTED_DISPOSAL_LINES_LABELS[index]:
            raise ManagementReportRenderError(
                f"Unexpected profitDisposition.disposalLines label at index {index}: expected '{EXPECTED_DISPOSAL_LINES_LABELS[index]}', got '{label}'"
            )
        _require_non_empty_string(row.get("amount"), "profitDisposition.disposalLines[].amount")


def _validate_signed_reference_corrections(
    semantic_contract: Dict[str, Any],
    *,
    metadata: ReportMetadata,
    diagnostics_raw: List[Dict[str, Any]],
    sections: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    corrections_raw = semantic_contract.get("signedReferenceCorrections")
    if not isinstance(corrections_raw, list):
        raise ManagementReportRenderError("Semantic contract must include signedReferenceCorrections list")

    diagnostics_by_code: Dict[str, Dict[str, Any]] = {}
    for d in diagnostics_raw:
        if isinstance(d, dict):
            code = d.get("code")
            if isinstance(code, str):
                diagnostics_by_code[code] = d

    expected = {
        OFFICE_ALIGNMENT_CORRECTION_ID: {
            "diagnosticCode": OFFICE_ALIGNMENT_DIAGNOSTIC,
            "signedReferencePage": OFFICE_ALIGNMENT_SIGNED_PAGE,
            "sectionKey": "businessInformation",
            "originalValue": OFFICE_ALIGNMENT_OLD_VALUE,
            "alignedValue": OFFICE_ALIGNMENT_NEW_VALUE,
            "disposition": "text_replaced",
        },
        SUSTAINABILITY_HEADING_CORRECTION_ID: {
            "diagnosticCode": SUSTAINABILITY_HEADING_DIAGNOSTIC,
            "signedReferencePage": SUSTAINABILITY_HEADING_SIGNED_PAGE,
            "sectionKey": "sustainabilityDisclosures",
            "originalValue": SUSTAINABILITY_HEADING_OLD_VALUE,
            "alignedValue": SUSTAINABILITY_HEADING_NEW_VALUE,
            "disposition": "heading_normalized",
        },
        CLOSING_SUPPRESSION_CORRECTION_ID: {
            "diagnosticCode": CLOSING_SUPPRESSION_DIAGNOSTIC,
            "signedReferencePage": CLOSING_SUPPRESSION_SIGNED_PAGE,
            "sectionKey": "closingTransition",
            "disposition": CLOSING_SUPPRESSION_DISPOSITION,
        },
    }

    seen_ids: set[str] = set()
    validated: List[Dict[str, Any]] = []
    for correction in corrections_raw:
        c = _require_dict(correction, "signedReferenceCorrections[]")
        cid = _require_non_empty_string(c.get("correctionId"), "signedReferenceCorrections[].correctionId")
        if cid in seen_ids:
            raise ManagementReportRenderError(f"Duplicate signedReferenceCorrections.correctionId: {cid}")
        seen_ids.add(cid)
        if cid not in expected:
            raise ManagementReportRenderError(f"Unknown signedReferenceCorrections correctionId: {cid}")
        exp = expected[cid]

        diagnostic_code = _require_non_empty_string(c.get("diagnosticCode"), f"signedReferenceCorrections[{cid}].diagnosticCode")
        if diagnostic_code != exp["diagnosticCode"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] diagnosticCode mismatch")

        signed_page = _require_non_empty_string(c.get("signedReferencePage"), f"signedReferenceCorrections[{cid}].signedReferencePage")
        if signed_page != exp["signedReferencePage"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] signedReferencePage mismatch")

        section_key = _require_non_empty_string(c.get("sectionKey"), f"signedReferenceCorrections[{cid}].sectionKey")
        if section_key != exp["sectionKey"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] sectionKey mismatch")
        if section_key not in sections:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] references missing section")

        authority_type = _require_non_empty_string(c.get("authorityType"), f"signedReferenceCorrections[{cid}].authorityType")
        if authority_type != SIGNED_REFERENCE_AUTHORITY_TYPE:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] authorityType mismatch")

        approval_scope = _require_dict(c.get("approvalScope"), f"signedReferenceCorrections[{cid}].approvalScope")
        if _require_non_empty_string(approval_scope.get("scopeId"), f"signedReferenceCorrections[{cid}].approvalScope.scopeId") != SIGNED_REFERENCE_ALIGNMENT_SCOPE_ID:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] approvalScope.scopeId mismatch")
        if _require_non_empty_string(approval_scope.get("companyName"), f"signedReferenceCorrections[{cid}].approvalScope.companyName") != metadata.company_name:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] approvalScope.companyName mismatch")
        if _require_non_empty_string(approval_scope.get("organizationNumber"), f"signedReferenceCorrections[{cid}].approvalScope.organizationNumber") != metadata.organization_number:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] approvalScope.organizationNumber mismatch")
        if _require_non_empty_string(approval_scope.get("currentReportingPeriod"), f"signedReferenceCorrections[{cid}].approvalScope.currentReportingPeriod") != metadata.current_reporting_period:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] approvalScope.currentReportingPeriod mismatch")
        if _require_non_empty_string(approval_scope.get("sectionKey"), f"signedReferenceCorrections[{cid}].approvalScope.sectionKey") != section_key:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] approvalScope.sectionKey mismatch")

        source_block_id = _require_non_empty_string(c.get("sourceBlockId"), f"signedReferenceCorrections[{cid}].sourceBlockId")
        section_ids: set[str] = set()
        heading = _require_dict(sections[section_key].get("heading"), f"{section_key}.heading")
        heading_id = heading.get("sourceBlockId")
        if isinstance(heading_id, str) and heading_id.strip():
            section_ids.add(heading_id)
        paragraphs = sections[section_key].get("paragraphs")
        if isinstance(paragraphs, list):
            for paragraph in paragraphs:
                if isinstance(paragraph, dict):
                    pid = paragraph.get("sourceBlockId")
                    if isinstance(pid, str) and pid.strip():
                        section_ids.add(pid)
        if cid != CLOSING_SUPPRESSION_CORRECTION_ID and source_block_id not in section_ids:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] sourceBlockId not present in section")

        original_value = _require_non_empty_string(c.get("originalValue"), f"signedReferenceCorrections[{cid}].originalValue")
        aligned_value = _require_non_empty_string(c.get("alignedValue"), f"signedReferenceCorrections[{cid}].alignedValue")
        disposition = _require_non_empty_string(c.get("disposition"), f"signedReferenceCorrections[{cid}].disposition")
        if disposition != exp["disposition"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] disposition mismatch")
        if "originalValue" in exp and original_value != exp["originalValue"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] originalValue mismatch")
        if "alignedValue" in exp and aligned_value != exp["alignedValue"]:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] alignedValue mismatch")

        if cid == CLOSING_SUPPRESSION_CORRECTION_ID:
            excluded_ids = c.get("excludedSourceBlockIds")
            if not isinstance(excluded_ids, list) or len(excluded_ids) != 2:
                raise ManagementReportRenderError("Closing-suppression correction must include exactly two excludedSourceBlockIds")
            for idx, excluded_id in enumerate(excluded_ids):
                _require_non_empty_string(excluded_id, f"signedReferenceCorrections[{cid}].excludedSourceBlockIds[{idx}]")

        diag = diagnostics_by_code.get(diagnostic_code)
        if not isinstance(diag, dict):
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] missing diagnostic")
        if _require_non_empty_string(diag.get("severity"), f"diagnostics[{diagnostic_code}].severity") != "info":
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] diagnostic severity must be info")
        if _require_non_empty_string(diag.get("sectionKey"), f"diagnostics[{diagnostic_code}].sectionKey") != section_key:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] diagnostic sectionKey mismatch")
        if _require_non_empty_string(diag.get("sourceBlockId"), f"diagnostics[{diagnostic_code}].sourceBlockId") != source_block_id:
            raise ManagementReportRenderError(f"signedReferenceCorrections[{cid}] diagnostic sourceBlockId mismatch")

        validated.append(c)

    return validated


def _render_paragraphs(texts: Sequence[str]) -> List[str]:
    rendered: List[str] = []
    for text in texts:
        rendered.append(_escape_latex(text))
        rendered.append("")
    return rendered


def _render_heading(text: str) -> List[str]:
    return [f"\\textbf{{{_escape_latex(text)}}}", ""]


def _format_multi_year_header(year_label: str) -> str:
    if len(year_label) >= 21 and year_label[10] == "-":
        first = _escape_latex(year_label[:11])
        second = _escape_latex(year_label[11:])
        return f"\\shortstack[r]{{{first}\\\\{second}}}"
    return _escape_latex(year_label)


def _render_multi_year_block(section_heading: str, multi_year_table: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.extend(_render_heading(section_heading))
    lines.append("Flerårsöversikt (Tkr)")
    lines.append("")
    lines.append("{")
    lines.append("\\setlength{\\tabcolsep}{2.5pt}")
    lines.append("\\footnotesize")
    lines.append("\\begin{tabular}{lrrrrr}")
    lines.append("\\toprule")
    header_years = " & ".join(_format_multi_year_header(year) for year in multi_year_table["years"])
    lines.append(f" & {header_years} \\\\")
    lines.append("\\midrule")
    for row in multi_year_table["rows"]:
        label = _escape_latex(row["label"])
        values = " & ".join(_escape_latex(value) for value in row["values"])
        lines.append(f"{label} & {values} \\\\")
    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("}")
    lines.append("")
    lines.append(APPROVED_MULTI_YEAR_REFERENCE_LINE)
    lines.append("")
    return lines


def _render_changes_in_equity_block(override: Dict[str, Any]) -> List[str]:
    changes = _require_dict(override.get("changesInEquity"), "changesInEquity")
    heading = _require_non_empty_string(changes.get("heading"), "changesInEquity.heading")
    columns = changes.get("columns")
    rows = changes.get("rows")

    if not isinstance(columns, list) or len(columns) != 5:
        raise ManagementReportRenderError("changesInEquity.columns must contain exactly 5 entries")
    if not isinstance(rows, list) or not rows:
        raise ManagementReportRenderError("changesInEquity.rows must contain at least one row")

    lines: List[str] = []
    lines.extend(_render_heading(heading))
    lines.append("{")
    lines.append("\\setlength{\\tabcolsep}{2pt}")
    lines.append("\\footnotesize")
    lines.append("\\begin{tabular}{lrrrrr}")
    lines.append("\\toprule")
    header_columns = " & ".join(
        _escape_latex(_require_non_empty_string(col, "changesInEquity.columns item"))
        for col in columns
    )
    lines.append(f" & {header_columns} \\\\")
    lines.append("\\midrule")

    for row_payload in rows:
        row_obj = _require_dict(row_payload, "changesInEquity.rows item")
        label = _require_non_empty_string(row_obj.get("label"), "changesInEquity.rows[].label")
        values = row_obj.get("values")
        if not isinstance(values, list) or len(values) != 5:
            raise ManagementReportRenderError("Each changesInEquity row must have exactly 5 values")
        row_values = " & ".join(
            _escape_latex(_require_string(value, "changesInEquity row value")) for value in values
        )
        lines.append(f"{_escape_latex(label)} & {row_values} \\\\")

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("}")
    lines.append("")
    return lines


def _render_profit_disposition_block(override: Dict[str, Any]) -> List[str]:
    disposition = _require_dict(override.get("profitDisposition"), "profitDisposition")
    heading = _require_non_empty_string(disposition.get("heading"), "profitDisposition.heading")
    intro = _require_non_empty_string(disposition.get("intro"), "profitDisposition.intro")
    lines_payload = disposition.get("lines")
    disposition_lead = _require_non_empty_string(disposition.get("dispositionLead"), "profitDisposition.dispositionLead")
    disposal_lines_payload = disposition.get("disposalLines")
    closing = _require_non_empty_string(disposition.get("closingStatement"), "profitDisposition.closingStatement")

    if not isinstance(lines_payload, list) or not lines_payload:
        raise ManagementReportRenderError("profitDisposition.lines must be a non-empty list")
    if not isinstance(disposal_lines_payload, list) or not disposal_lines_payload:
        raise ManagementReportRenderError("profitDisposition.disposalLines must be a non-empty list")

    lines: List[str] = []
    lines.extend(_render_heading(heading))
    lines.append(_escape_latex(intro))
    lines.append("")

    lines.append("\\begin{tabular}{lr}")
    for entry in lines_payload:
        row = _require_dict(entry, "profitDisposition.lines item")
        label = _require_string(row.get("label"), "profitDisposition.lines[].label")
        amount = _require_non_empty_string(row.get("amount"), "profitDisposition.lines[].amount")
        lines.append(f"{_escape_latex(label)} & {_escape_latex(amount)} \\\\")
    lines.append("\\end{tabular}")
    lines.append("")

    lines.append(_escape_latex(disposition_lead))
    lines.append("")

    lines.append("\\begin{tabular}{lr}")
    for entry in disposal_lines_payload:
        row = _require_dict(entry, "profitDisposition.disposalLines item")
        label = _require_string(row.get("label"), "profitDisposition.disposalLines[].label")
        amount = _require_non_empty_string(row.get("amount"), "profitDisposition.disposalLines[].amount")
        lines.append(f"{_escape_latex(label)} & {_escape_latex(amount)} \\\\")
    lines.append("\\end{tabular}")
    lines.append("")

    lines.append(_escape_latex(closing))
    lines.append("")
    return lines


def render_management_report(
    *,
    semantic_input_path: Path,
    raw_input_path: Path,
    metadata_path: Path,
    preview_override_path: Path,
) -> Dict[str, Any]:
    metadata = load_report_metadata(metadata_path)
    semantic_contract = _load_json(semantic_input_path, field_name="management-report semantic contract")
    raw_contract = _load_json(raw_input_path, field_name="management-report raw contract")
    preview_override = _load_json(preview_override_path, field_name="management-report page-4 preview override")

    semantic_sha = _sha256_path(semantic_input_path)
    raw_sha = _sha256_path(raw_input_path)
    metadata_sha = _sha256_path(metadata_path)
    override_sha = _sha256_path(preview_override_path)

    expected_raw_sha = _require_non_empty_string(semantic_contract.get("rawContractSha256"), "rawContractSha256")
    actual_raw_canonical_sha = _sha256_bytes(_canonical_json_bytes(raw_contract))
    if expected_raw_sha != actual_raw_canonical_sha:
        raise ManagementReportRenderError(
            "Semantic rawContractSha256 does not match canonical SHA-256 of provided raw contract"
        )

    source_evidence = _require_dict(semantic_contract.get("sourceEvidence"), "sourceEvidence")
    semantic_source_sha = _require_non_empty_string(source_evidence.get("sha256"), "sourceEvidence.sha256")

    raw_source = _require_dict(raw_contract.get("source"), "raw.source")
    raw_source_sha = _require_non_empty_string(raw_source.get("sha256"), "raw.source.sha256")
    if semantic_source_sha != raw_source_sha:
        raise ManagementReportRenderError("Semantic source DOCX SHA-256 does not match raw contract source SHA-256")

    raw_source_file = _require_non_empty_string(raw_source.get("file"), "raw.source.file")
    semantic_source_file = _require_non_empty_string(source_evidence.get("file"), "sourceEvidence.file")
    if raw_source_file != semantic_source_file:
        raise ManagementReportRenderError("Semantic source file path does not match raw contract source file path")

    period_evidence = _require_dict(semantic_contract.get("periodEvidence"), "periodEvidence")
    semantic_reporting_period = _require_non_empty_string(
        period_evidence.get("normalizedCurrentPeriod"),
        "periodEvidence.normalizedCurrentPeriod",
    )
    if semantic_reporting_period != metadata.current_reporting_period:
        raise ManagementReportRenderError("Semantic reporting period contradicts report metadata")

    status = _require_non_empty_string(semantic_contract.get("status"), "status")
    if status not in {"review_required", "validated"}:
        raise ManagementReportRenderError(
            "Management report semantic status must be 'review_required' or 'validated' before rendering"
        )

    diagnostics_raw = semantic_contract.get("diagnostics")
    if not isinstance(diagnostics_raw, list):
        raise ManagementReportRenderError("Semantic contract must include diagnostics list")
    review_diagnostics = [
        _require_dict(d, "diagnostics[]") for d in diagnostics_raw
        if isinstance(d, dict) and d.get("severity") == REVIEW_REQUIRED_SEVERITY
    ]

    if status == "validated" and review_diagnostics:
        raise ManagementReportRenderError("Semantic status 'validated' is invalid when review_required diagnostics are present")
    if status == "review_required" and not review_diagnostics:
        raise ManagementReportRenderError("Semantic status 'review_required' is invalid when no review_required diagnostics exist")

    resolved_sections = _resolve_sections(semantic_contract)
    sections = resolved_sections["sections"]
    source_usage = resolved_sections["source_usage"]
    signed_reference_corrections = _validate_signed_reference_corrections(
        semantic_contract,
        metadata=metadata,
        diagnostics_raw=diagnostics_raw,
        sections=sections,
    )
    multi_year_table = _resolve_multi_year_table(semantic_contract, source_usage)

    tables = semantic_contract.get("tables")
    assert isinstance(tables, list)
    equity_table_payload = _require_dict(tables[1], "tables[1]")
    equity_table_source = _require_non_empty_string(equity_table_payload.get("sourceBlockId"), "tables[1].sourceBlockId")
    prior = source_usage.get(equity_table_source)
    if prior is not None and prior != "table:equityAndProfitDisposition":
        raise ManagementReportRenderError(
            f"sourceBlockId '{equity_table_source}' is used in more than one destination: '{prior}' and 'table:equityAndProfitDisposition'"
        )
    source_usage[equity_table_source] = "table:equityAndProfitDisposition"

    override_scope = _validate_equity_override(
        preview_override,
        metadata=metadata,
        semantic_contract=semantic_contract,
        equity_table_source_block_id=equity_table_source,
    )
    _validate_override_financial_shapes(preview_override)

    if status == "review_required" and not override_scope["coveredDiagnosticCodes"]:
        raise ManagementReportRenderError("review_required rendering needs non-empty override diagnostic coverage")

    management_heading = _require_non_empty_string(
        _require_dict(sections["managementReportHeading"].get("heading"), "managementReportHeading.heading").get("text"),
        "managementReportHeading.heading.text",
    )
    management_heading = _require_heading_text(management_heading, "managementReportHeading.heading.text")

    business_heading = _require_non_empty_string(
        _require_dict(sections["businessInformation"].get("heading"), "businessInformation.heading").get("text"),
        "businessInformation.heading.text",
    )
    business_heading = _require_heading_text(business_heading, "businessInformation.heading.text")
    significant_heading = _require_non_empty_string(
        _require_dict(sections["significantEvents"].get("heading"), "significantEvents.heading").get("text"),
        "significantEvents.heading.text",
    )
    significant_heading = _require_heading_text(significant_heading, "significantEvents.heading.text")
    future_heading = _require_non_empty_string(
        _require_dict(sections["futureDevelopmentAndRisks"].get("heading"), "futureDevelopmentAndRisks.heading").get("text"),
        "futureDevelopmentAndRisks.heading.text",
    )
    future_heading = _require_heading_text(future_heading, "futureDevelopmentAndRisks.heading.text")
    research_heading = _require_non_empty_string(
        _require_dict(sections["researchAndDevelopment"].get("heading"), "researchAndDevelopment.heading").get("text"),
        "researchAndDevelopment.heading.text",
    )
    research_heading = _require_heading_text(research_heading, "researchAndDevelopment.heading.text")
    sustainability_heading = _require_non_empty_string(
        _require_dict(sections["sustainabilityDisclosures"].get("heading"), "sustainabilityDisclosures.heading").get("text"),
        "sustainabilityDisclosures.heading.text",
    )
    sustainability_heading = _require_heading_text(sustainability_heading, "sustainabilityDisclosures.heading.text")
    multi_year_heading = _require_non_empty_string(
        _require_dict(sections["multiYearOverview"].get("heading"), "multiYearOverview.heading").get("text"),
        "multiYearOverview.heading.text",
    )
    multi_year_heading = _require_heading_text(multi_year_heading, "multiYearOverview.heading.text")

    intro_texts = _paragraph_texts(sections["introductoryStatement"])
    currency_texts = _paragraph_texts(sections["currencyStatement"])
    business_texts = _paragraph_texts(sections["businessInformation"])
    significant_texts = _paragraph_texts(sections["significantEvents"])
    future_texts = _paragraph_texts(sections["futureDevelopmentAndRisks"])
    research_texts = _paragraph_texts(sections["researchAndDevelopment"])
    sustainability_texts = _paragraph_texts(sections["sustainabilityDisclosures"])
    closing_texts = _paragraph_texts(sections["closingTransition"])

    page2_significant_count = 3 if len(significant_texts) >= 3 else len(significant_texts)
    page2_significant = significant_texts[:page2_significant_count]
    page3_significant = significant_texts[page2_significant_count:]

    page3_sustainability_count = 2 if len(sustainability_texts) >= 2 else len(sustainability_texts)
    page3_sustainability = sustainability_texts[:page3_sustainability_count]
    page4_sustainability = sustainability_texts[page3_sustainability_count:]

    tex_lines: List[str] = [
        "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
        "\\fancypagestyle{managementreportstyle}{%",
        "  \\fancyhf{}",
        "  \\fancyhead[L]{\\fontfamily{phv}\\selectfont\\small \\shortstack[l]{\\FinancialStatementCompanyHeader}}",
        "  \\fancyhead[R]{\\fontfamily{phv}\\selectfont\\small \\managementreportpageindicator}",
        "  \\renewcommand{\\headrulewidth}{0pt}",
        "  \\renewcommand{\\footrulewidth}{0pt}",
        "}",
        f"\\gdef\\FinancialStatementCompanyHeader{{{_escape_latex(metadata.company_name)}\\\\Org.nr {_escape_latex(metadata.organization_number)}}}",
        "\\newcommand{\\managementreportpageindicator}{}",
        "",
        "\\clearpage",
        "\\renewcommand{\\managementreportpageindicator}{2 (19)}",
        "\\pagestyle{managementreportstyle}",
        "\\thispagestyle{managementreportstyle}",
        "\\small",
        "\\setlength{\\parskip}{0.35em}",
        "\\setlength{\\emergencystretch}{1.5em}",
    ]

    tex_lines.extend(_render_heading(management_heading))

    tex_lines.extend(_render_paragraphs(intro_texts))
    tex_lines.extend(_render_paragraphs(currency_texts))
    tex_lines.extend(_render_heading(business_heading))
    tex_lines.extend(_render_paragraphs(business_texts))
    tex_lines.extend(_render_heading(significant_heading))
    tex_lines.extend(_render_paragraphs(page2_significant))

    tex_lines.extend([
        "\\clearpage",
        "\\renewcommand{\\managementreportpageindicator}{3 (19)}",
        "\\thispagestyle{managementreportstyle}",
        "",
    ])

    tex_lines.extend(_render_paragraphs(page3_significant))
    tex_lines.extend(_render_heading(future_heading))
    tex_lines.extend(_render_paragraphs(future_texts))
    tex_lines.extend(_render_heading(research_heading))
    tex_lines.extend(_render_paragraphs(research_texts))
    tex_lines.extend(_render_heading(sustainability_heading))
    tex_lines.extend(_render_paragraphs(page3_sustainability))

    tex_lines.extend([
        "\\clearpage",
        "\\renewcommand{\\managementreportpageindicator}{4 (19)}",
        "\\thispagestyle{managementreportstyle}",
        "",
    ])

    tex_lines.extend(_render_paragraphs(page4_sustainability))
    tex_lines.extend(_render_multi_year_block(multi_year_heading, multi_year_table))
    tex_lines.extend(_render_changes_in_equity_block(preview_override))
    tex_lines.extend(_render_profit_disposition_block(preview_override))
    tex_lines.extend(_render_paragraphs(closing_texts))

    tex_lines.extend([
        "\\normalsize",
        "\\setlength{\\parskip}{0.7em}",
        "\\clearpage",
        "\\pagestyle{fancy}",
        "\\fancyhf{}",
        "\\fancyhead[L]{\\reporttitle}",
        "\\fancyhead[R]{\\fiscalyear}",
        "\\fancyfoot[C]{\\thepage}",
        "",
    ])

    tex = "\n".join(tex_lines)
    source_block_ids_used: Dict[str, Any] = {
        "sections": {},
        "tables": {
            "multiYearOverview": [multi_year_table["sourceBlockId"]],
            "equityAndProfitDisposition": [equity_table_source],
        },
    }

    section_id_map: Dict[str, List[str]] = {}
    for section_key in EXPECTED_SECTION_ORDER:
        section_payload = sections[section_key]
        ids: List[str] = []
        heading = _require_dict(section_payload.get("heading"), f"{section_key}.heading")
        heading_source = heading.get("sourceBlockId")
        if isinstance(heading_source, str) and heading_source.strip():
            ids.append(heading_source)
        paragraphs = section_payload.get("paragraphs")
        if isinstance(paragraphs, list):
            for paragraph in paragraphs:
                if isinstance(paragraph, dict):
                    sid = paragraph.get("sourceBlockId")
                    if isinstance(sid, str) and sid.strip():
                        ids.append(sid)
        section_id_map[section_key] = ids
    source_block_ids_used["sections"] = section_id_map

    review_codes = [
        _require_non_empty_string(d.get("code"), "diagnostics[].code")
        for d in diagnostics_raw
        if isinstance(d, dict) and d.get("severity") == REVIEW_REQUIRED_SEVERITY
    ]

    provenance_payload = {
        "schemaVersion": "2.0",
        "rendererVersion": RENDERER_VERSION,
        "semanticContractPath": str(semantic_input_path).replace("\\", "/"),
        "semanticContractSha256": semantic_sha,
        "rawContractPath": str(raw_input_path).replace("\\", "/"),
        "rawContractSha256": raw_sha,
        "sourceDocxSha256": raw_source_sha,
        "metadataPath": str(metadata_path).replace("\\", "/"),
        "metadataSha256": metadata_sha,
        "previewOverridePath": str(preview_override_path).replace("\\", "/"),
        "previewOverrideSha256": override_sha,
        "previewOverrideSourceType": override_scope["sourceType"],
        "previewOverrideApprovalScope": override_scope["approvalScope"],
        "coveredDiagnosticCodes": override_scope["coveredDiagnosticCodes"],
        "coveredSourceBlockIds": override_scope["coveredSourceBlockIds"],
        "overriddenFields": override_scope["overriddenFields"],
        "displayMappings": multi_year_table["displayMappings"],
        "reviewDiagnosticsPresent": review_codes,
        "signedReferenceCorrections": signed_reference_corrections,
        "sourceBlockIdsUsed": source_block_ids_used,
        "outputTexPath": "",
        "outputTexSha256": "",
    }

    return {
        "tex": tex,
        "provenance": provenance_payload,
        "semantic_contract": semantic_contract,
        "raw_contract": raw_contract,
        "preview_override": preview_override,
    }
