from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Tuple

from notes_contract import CANONICAL_NOTE_TITLES
from report_metadata import ReportMetadata, load_report_metadata


class NotesRenderError(ValueError):
    pass


RENDERER_VERSION = "2.0"

DIRECT_WORKBOOK_NOTES = {13, 14}
HYBRID_WORKBOOK_NOTES = {4, 17, 18, 19, 22, 23, 26}
FULL_NOTE_OVERRIDE_NOTES = {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 20, 21, 24, 25, 27, 28}

PAGE_NOTE_MAP: Dict[int, List[int]] = {
    9: [1],
    10: [1],
    11: [2],
    12: [3, 4],
    13: [5, 6, 7],
    14: [8, 9, 10],
    15: [11, 12, 13, 14],
    16: [15, 16, 17, 18],
    17: [19, 20, 21, 22],
    18: [23, 24, 25, 26],
    19: [27, 28],
}

SIGNED_REFERENCE_SHA256 = "e4396bbe09d63a6b4a3828fc6f63c9cd5b18a4b9500fe58acfe303428b0768f0"
REQUIRED_OVERRIDE_SOURCE_TYPE = "signed_reference_preview_override"
REQUIRED_OVERRIDE_APPROVAL_SCOPE = "poc_preview_only"
ALLOWED_OVERRIDE_KINDS = {
    "blank-to-zero presentation",
    "display formatting",
    "label mapping",
    "row-role authority",
    "signed-preview value override",
    "signed-reference inter-note insertion",
    "signed-reference note appendix",
}

ALLOWED_INSERTION_PAGES = set(range(9, 20))


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


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path, *, field_name: str) -> Dict[str, Any]:
    if not path.exists():
        raise NotesRenderError(f"Missing {field_name}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NotesRenderError(f"Invalid JSON in {field_name}: {path}") from exc
    if not isinstance(payload, dict):
        raise NotesRenderError(f"{field_name} top-level JSON must be an object")
    return payload


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise NotesRenderError(f"Expected object for '{field_name}'")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise NotesRenderError(f"Missing or invalid string '{field_name}'")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    text = _require_string(value, field_name)
    if not text.strip():
        raise NotesRenderError(f"Missing or invalid non-empty string '{field_name}'")
    return text


def _render_note_heading(note_number: int, title: str, *, continued: bool = False) -> List[str]:
    if continued:
        return [f"\\textbf{{Not {note_number} {_escape_latex(title)} (forts.)}}", ""]
    return [f"\\textbf{{Not {note_number} {_escape_latex(title)}}}", ""]


def _render_paragraphs(paragraphs: List[str]) -> List[str]:
    def wrap_words(text: str, width: int = 92) -> List[str]:
        words = text.split()
        if not words:
            return [""]
        lines: List[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    lines: List[str] = []
    for paragraph in paragraphs:
        wrapped = wrap_words(paragraph)
        for part in wrapped:
            lines.append(_escape_latex(part))
        lines.append("")
    return lines


def _render_table_rows(rows: List[List[str]], *, small: bool = True) -> List[str]:
    col_count = max(len(row) for row in rows) if rows else 0
    if col_count < 1:
        raise NotesRenderError("Malformed table: missing columns")

    if col_count == 1:
        tabular_spec = "p{152mm}"
    elif col_count == 2:
        tabular_spec = "p{120mm}r"
    elif col_count == 3:
        tabular_spec = "p{104mm}rr"
    elif col_count == 4:
        tabular_spec = "p{70mm}>{\\raggedleft\\arraybackslash}p{22mm}>{\\raggedright\\arraybackslash}p{34mm}p{20mm}"
    else:
        tabular_spec = "p{86mm}" + ("r" * (col_count - 1))

    lines: List[str] = []
    lines.append("{")
    lines.append("\\setlength{\\tabcolsep}{2.0pt}")
    if small:
        lines.append("\\footnotesize")
    lines.append(f"\\begin{{tabular}}{{{tabular_spec}}}")
    lines.append("\\toprule")

    for idx, row in enumerate(rows):
        escaped = [_escape_latex(value) for value in row]
        first = escaped[0].strip() if escaped else ""
        is_total = first.startswith("Summa") or first.startswith("Totalt") or first.startswith("Utgående")
        if first == "":
            is_total = False
        if is_total:
            escaped = [f"\\textbf{{{value}}}" if value else value for value in escaped]
        lines.append(" & ".join(escaped) + " \\\\")
        if idx == 0:
            lines.append("\\midrule")

    lines.append("\\bottomrule")
    lines.append("\\end{tabular}")
    lines.append("}")
    return lines


def _render_signed_reference_text_block(block: Dict[str, Any], *, field_prefix: str) -> List[str]:
    lines: List[str] = []

    paragraphs = block.get("paragraphs", [])
    if not isinstance(paragraphs, list):
        raise NotesRenderError(f"{field_prefix}.paragraphs must be list")
    for paragraph in paragraphs:
        text = _require_string(paragraph, f"{field_prefix}.paragraph")
        if "Not X" in text:
            raise NotesRenderError(f"Unresolved Not X placeholder in {field_prefix}")
    lines.extend(_render_paragraphs(paragraphs))

    tables = block.get("tables", [])
    if not isinstance(tables, list):
        raise NotesRenderError(f"{field_prefix}.tables must be list")
    for table in tables:
        t = _require_dict(table, f"{field_prefix}.table")
        heading = t.get("heading")
        if isinstance(heading, str) and heading.strip():
            lines.append(_escape_latex(heading))
            lines.append("")
        rows_payload = t.get("rows")
        if not isinstance(rows_payload, list):
            raise NotesRenderError(f"{field_prefix}.table.rows must be list")
        rows: List[List[str]] = []
        for row in rows_payload:
            row_obj = _require_dict(row, f"{field_prefix}.table.row")
            cells = row_obj.get("cells")
            if not isinstance(cells, list) or not cells:
                raise NotesRenderError(f"{field_prefix}.table.row.cells must be non-empty list")
            rows.append([_require_string(cell, f"{field_prefix}.table.row.cell") for cell in cells])
        lines.extend(_render_table_rows(rows))
        lines.append("")

    return lines


def _collect_review_diagnostics(semantic_contract: Dict[str, Any]) -> Dict[Tuple[int | None, str], Dict[str, Any]]:
    out: Dict[Tuple[int | None, str], Dict[str, Any]] = {}
    top = semantic_contract.get("diagnostics")
    if isinstance(top, list):
        for d in top:
            if isinstance(d, dict) and d.get("severity") == "review_required" and isinstance(d.get("code"), str):
                out[(None, d["code"])] = d
    notes = semantic_contract.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if not isinstance(note, dict):
                continue
            num = note.get("noteNumber")
            if not isinstance(num, int):
                continue
            ds = note.get("diagnostics")
            if not isinstance(ds, list):
                continue
            for d in ds:
                if isinstance(d, dict) and d.get("severity") == "review_required" and isinstance(d.get("code"), str):
                    out[(num, d["code"])] = d
    return out


def _semantic_cell_lookup(semantic_note: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    tables = semantic_note.get("tables")
    if not isinstance(tables, list):
        return lookup
    for table in tables:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                coord = cell.get("coordinate")
                if isinstance(coord, str) and coord:
                    lookup[coord] = cell
    return lookup


def _semantic_cell_lookup_by_sheet(semantic_note: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}
    tables = semantic_note.get("tables")
    if not isinstance(tables, list):
        return lookup
    for table in tables:
        if not isinstance(table, dict):
            continue
        sheet = table.get("sheet")
        if not isinstance(sheet, str) or not sheet.strip():
            continue
        rows = table.get("rows")
        if not isinstance(rows, list):
            continue
        sheet_map = lookup.setdefault(sheet, {})
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                coord = cell.get("coordinate")
                if isinstance(coord, str) and coord:
                    sheet_map[coord] = cell
    return lookup


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _format_number_swedish(value: Decimal, places: int) -> str:
    quant = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    abs_val = abs(rounded)
    whole = int(abs_val)
    grouped = f"{whole:,}".replace(",", " ")
    if places == 0:
        return sign + grouped
    frac = f"{abs_val:.{places}f}".split(".")[1]
    return sign + grouped + "," + frac


_EXCEL_DATE_EPOCH = datetime(1899, 12, 30)
_EXCEL_1904_DATE_EPOCH = datetime(1904, 1, 1)
_DATE_NUMBER_FORMAT_CODES = {"builtin:14", "builtin:15", "builtin:16", "builtin:17", "builtin:22"}
_GENERAL_NUMBER_FORMAT_CODES = {"builtin:0", "General"}


def _strip_excel_format_literals(format_code: str) -> str:
    # Remove quoted/escaped/section metadata so token checks only inspect format directives.
    text = re.sub(r'"[^"]*"', "", format_code)
    text = re.sub(r"\\(.)", r"\1", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"_.", "", text)
    text = re.sub(r"\*.", "", text)
    first_section = text.split(";", 1)[0]
    return first_section.strip()


def _is_date_number_format(number_format: str) -> bool:
    if number_format in _DATE_NUMBER_FORMAT_CODES:
        return True
    normalized = _strip_excel_format_literals(number_format).lower().replace("\\-", "-")
    # Narrow allowlist for custom dates used by this workbook contract.
    return normalized in {"yyyy-mm-dd", "yyyy/mm/dd", "yyyy.mm.dd"}


def _is_unsupported_date_like_format(number_format: str) -> bool:
    if _is_date_number_format(number_format):
        return False
    normalized = _strip_excel_format_literals(number_format).lower()
    if not normalized:
        return False
    if "y" not in normalized:
        return False
    if normalized.replace("\\-", "-") in {"yyyy-mm-dd", "yyyy/mm/dd", "yyyy.mm.dd"}:
        return False
    return True


def _excel_serial_to_iso_date(raw_dec: Decimal, workbook_date_system: str) -> str:
    try:
        days = int(raw_dec)
    except (ValueError, OverflowError) as exc:
        raise NotesRenderError(f"Unsupported Excel date serial value: {raw_dec!r}") from exc
    if workbook_date_system == "excel_1900":
        if 1 <= days <= 60:
            raise NotesRenderError(
                "Unsupported Excel 1900 date serial in range 1-60; this range intersects "
                "Excel's fictitious 1900 leap-day behavior and is intentionally not rendered"
            )
        base = _EXCEL_DATE_EPOCH
    elif workbook_date_system == "excel_1904":
        base = _EXCEL_1904_DATE_EPOCH
    else:
        raise NotesRenderError(f"Unsupported workbook date-system mode: {workbook_date_system!r}")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _display_from_cell(cell: Dict[str, Any] | None, *, workbook_date_system: str | None) -> str:
    if not isinstance(cell, dict):
        return ""
    number_format = str(cell.get("numberFormat") or "")
    raw_dec = _as_decimal(cell.get("rawValue"))
    if raw_dec is not None:
        if _is_date_number_format(number_format):
            if workbook_date_system is None:
                raise NotesRenderError("Missing workbook date-system evidence for numeric date cell")
            return _excel_serial_to_iso_date(raw_dec, workbook_date_system)
        if _is_unsupported_date_like_format(number_format):
            raise NotesRenderError(
                "Unsupported numeric date format for cell "
                f"{cell.get('coordinate')!r}: {number_format!r}"
            )
        if number_format == "builtin:3":
            return _format_number_swedish(raw_dec, 0)
        if number_format in {"builtin:2", "builtin:4"}:
            return _format_number_swedish(raw_dec, 2)
        if number_format == "#,##0.0":
            return _format_number_swedish(raw_dec, 1)
        if number_format == "builtin:10":
            return _format_number_swedish(raw_dec * Decimal("100"), 2) + " %"
        if number_format == "0.0%":
            return _format_number_swedish(raw_dec * Decimal("100"), 1) + " %"
        if number_format in _GENERAL_NUMBER_FORMAT_CODES:
            raw_text = cell.get("rawValue")
            if isinstance(raw_text, str) and re.fullmatch(r"-?\d+", raw_text):
                return raw_text
            raise NotesRenderError(
                "Unsupported numeric General-format value for cell "
                f"{cell.get('coordinate')!r}: {raw_text!r}"
            )
        if number_format not in _GENERAL_NUMBER_FORMAT_CODES:
            raise NotesRenderError(
                "Unsupported workbook number format for numeric cell "
                f"{cell.get('coordinate')!r}: {number_format!r}"
            )
    displayed = cell.get("text")
    if isinstance(displayed, str):
        return displayed
    displayed = cell.get("displayedValue")
    if isinstance(displayed, str):
        return displayed
    return ""


def _workbook_date_system_mode(raw_contract: Dict[str, Any]) -> str | None:
    workbook = raw_contract.get("workbook")
    if not isinstance(workbook, dict):
        return None
    date_system = workbook.get("dateSystem")
    if not isinstance(date_system, dict):
        return None
    mode = date_system.get("mode")
    if mode in {"excel_1900", "excel_1904"}:
        return mode
    return None


def _validate_semantic_contract(
    semantic_contract: Dict[str, Any],
    *,
    raw_contract: Dict[str, Any],
    metadata: ReportMetadata,
    mapping_bytes: bytes,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, List[str]], Dict[str, List[str]], Dict[str, List[Dict[str, str]]], Dict[Tuple[int | None, str], Dict[str, Any]]]:
    raw_expected_sha = _require_non_empty_string(semantic_contract.get("rawContractSha256"), "semantic.rawContractSha256")
    raw_actual_sha = _sha256_bytes(_canonical_json_bytes(raw_contract))
    if raw_expected_sha != raw_actual_sha:
        raise NotesRenderError("Semantic rawContractSha256 does not match raw contract")

    source_evidence = _require_dict(semantic_contract.get("sourceEvidence"), "semantic.sourceEvidence")
    if _require_non_empty_string(source_evidence.get("sha256"), "semantic.sourceEvidence.sha256") != _require_non_empty_string(
        _require_dict(raw_contract.get("source"), "raw.source").get("sha256"), "raw.source.sha256"
    ):
        raise NotesRenderError("Semantic source workbook SHA-256 mismatch")

    company_identity = _require_dict(semantic_contract.get("companyIdentityEvidence"), "semantic.companyIdentityEvidence")
    if _require_non_empty_string(company_identity.get("metadataCompanyName"), "metadataCompanyName") != metadata.company_name:
        raise NotesRenderError("Semantic metadata company mismatch")
    if _require_non_empty_string(company_identity.get("metadataOrganizationNumber"), "metadataOrganizationNumber") != metadata.organization_number:
        raise NotesRenderError("Semantic metadata org mismatch")

    mapping_evidence = _require_dict(semantic_contract.get("mappingPolicyEvidence"), "semantic.mappingPolicyEvidence")
    expected_mapping_sha = _require_non_empty_string(mapping_evidence.get("sha256"), "semantic.mappingPolicyEvidence.sha256")
    actual_mapping_sha = _sha256_bytes(mapping_bytes)
    if expected_mapping_sha != actual_mapping_sha:
        raise NotesRenderError("Semantic mapping-policy SHA mismatch")

    notes = semantic_contract.get("notes")
    if not isinstance(notes, list) or len(notes) != 28:
        raise NotesRenderError("Semantic notes contract must contain exactly 28 notes")

    notes_by_number: Dict[int, Dict[str, Any]] = {}
    source_ranges_used: Dict[str, List[str]] = {}
    source_cells_used: Dict[str, List[str]] = {}
    formulas_used: Dict[str, List[Dict[str, str]]] = {}

    for index, note in enumerate(notes, start=1):
        note_obj = _require_dict(note, f"semantic.notes[{index}]")
        note_number = note_obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number != index:
            raise NotesRenderError("Semantic notes are reordered or malformed")
        title = _require_non_empty_string(note_obj.get("title"), f"note {note_number} title")
        if title != CANONICAL_NOTE_TITLES[note_number - 1]:
            raise NotesRenderError(f"Canonical note title mismatch for note {note_number}")

        authority = _require_dict(note_obj.get("renderAuthority"), f"note {note_number} renderAuthority")
        mode = _require_non_empty_string(authority.get("mode"), f"note {note_number} renderAuthority.mode")
        if mode not in {"direct_workbook", "hybrid_workbook_preview_override", "full_note_preview_override"}:
            raise NotesRenderError(f"Note {note_number} has unsupported render authority mode: {mode}")

        diagnostics = note_obj.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise NotesRenderError(f"note {note_number} diagnostics must be list")
        if mode == "direct_workbook" and diagnostics:
            raise NotesRenderError(f"direct mode with unresolved diagnostics is not allowed (note {note_number})")

        source_references = note_obj.get("sourceReferences")
        if not isinstance(source_references, list):
            raise NotesRenderError(f"note {note_number} sourceReferences must be list")
        note_ranges: List[str] = []
        for ref in source_references:
            ref_obj = _require_dict(ref, f"note {note_number} source reference")
            sheet = _require_non_empty_string(ref_obj.get("sheet"), "source sheet")
            rng = _require_non_empty_string(ref_obj.get("range"), "source range")
            note_ranges.append(f"{sheet}:{rng}")
        source_ranges_used[str(note_number)] = note_ranges

        cell_refs: List[str] = []
        tables = note_obj.get("tables")
        if not isinstance(tables, list):
            raise NotesRenderError(f"note {note_number} tables must be list")
        for table_idx, table in enumerate(tables, start=1):
            t = _require_dict(table, f"note {note_number} table")
            rows = t.get("rows")
            if not isinstance(rows, list):
                raise NotesRenderError(f"note {note_number} table rows must be list")
            for row in rows:
                r = _require_dict(row, f"note {note_number} row")
                cells = r.get("cells")
                if not isinstance(cells, list):
                    raise NotesRenderError(f"note {note_number} row cells must be list")
                for cell in cells:
                    c = _require_dict(cell, f"note {note_number} cell")
                    coord = c.get("coordinate")
                    if isinstance(coord, str):
                        cell_refs.append(f"table{table_idx}:{coord}")
        source_cells_used[str(note_number)] = cell_refs

        formulas = note_obj.get("formulasUsed")
        if not isinstance(formulas, list):
            raise NotesRenderError(f"note {note_number} formulasUsed must be list")
        formula_entries: List[Dict[str, str]] = []
        for formula in formulas:
            f = _require_dict(formula, f"note {note_number} formula")
            formula_entries.append(
                {
                    "sheet": _require_non_empty_string(f.get("sheet"), "formula sheet"),
                    "coordinate": _require_non_empty_string(f.get("coordinate"), "formula coordinate"),
                    "formula": _require_non_empty_string(f.get("formula"), "formula"),
                    "cachedValue": _require_string(f.get("cachedValue"), "cachedValue"),
                }
            )
        formulas_used[str(note_number)] = formula_entries

        notes_by_number[note_number] = note_obj

    mode_sets = {
        "direct_workbook": {n for n, note in notes_by_number.items() if note["renderAuthority"]["mode"] == "direct_workbook"},
        "hybrid_workbook_preview_override": {
            n for n, note in notes_by_number.items() if note["renderAuthority"]["mode"] == "hybrid_workbook_preview_override"
        },
        "full_note_preview_override": {
            n for n, note in notes_by_number.items() if note["renderAuthority"]["mode"] == "full_note_preview_override"
        },
    }
    if mode_sets["direct_workbook"] != DIRECT_WORKBOOK_NOTES:
        raise NotesRenderError("Direct workbook authority note set mismatch")
    if mode_sets["hybrid_workbook_preview_override"] != HYBRID_WORKBOOK_NOTES:
        raise NotesRenderError("Hybrid authority note set mismatch")
    if mode_sets["full_note_preview_override"] != FULL_NOTE_OVERRIDE_NOTES:
        raise NotesRenderError("Full-note override authority note set mismatch")

    return notes_by_number, source_ranges_used, source_cells_used, formulas_used, _collect_review_diagnostics(semantic_contract)


def _validate_override_manifest(
    override: Dict[str, Any],
    *,
    metadata: ReportMetadata,
    review_diags: Dict[Tuple[int | None, str], Dict[str, Any]],
) -> Dict[str, Any]:
    def require_allowed_override_kind(value: Any, field_name: str) -> str:
        override_kind = _require_non_empty_string(value, field_name)
        if override_kind not in ALLOWED_OVERRIDE_KINDS:
            raise NotesRenderError(
                f"Unsupported overrideKind for {field_name}: {override_kind!r}; "
                f"allowed={sorted(ALLOWED_OVERRIDE_KINDS)}"
            )
        return override_kind

    def require_note_diagnostic_covered(note_number: int, code: str, field_name: str) -> None:
        # Strict note-local scope: field/row/label overrides cannot claim global-only diagnostics.
        if (note_number, code) not in review_diags:
            if (None, code) in review_diags:
                raise NotesRenderError(
                    f"{field_name} claims global diagnostic as note-local: note={note_number} code={code}"
                )
            raise NotesRenderError(
                f"{field_name} claims absent diagnostic: note={note_number} code={code}"
            )

    required = {
        "schemaVersion",
        "sourceType",
        "approvalScope",
        "companyName",
        "organizationNumber",
        "currentReportingPeriod",
        "signedReference",
        "fullNoteOverrides",
        "interNoteInsertions",
        "hybridNotePrefaceParagraphs",
        "hybridNoteAppendixParagraphs",
        "fieldOverrides",
        "rowOverrides",
        "labelMappings",
        "acknowledgedPolicyDiagnostics",
    }
    missing = sorted(required.difference(override.keys()))
    if missing:
        raise NotesRenderError(f"Missing required override manifest fields: {missing}")

    if _require_non_empty_string(override.get("sourceType"), "override.sourceType") != REQUIRED_OVERRIDE_SOURCE_TYPE:
        raise NotesRenderError("Override sourceType mismatch")
    if _require_non_empty_string(override.get("approvalScope"), "override.approvalScope") != REQUIRED_OVERRIDE_APPROVAL_SCOPE:
        raise NotesRenderError("Override approvalScope mismatch")
    if _require_non_empty_string(override.get("companyName"), "override.companyName") != metadata.company_name:
        raise NotesRenderError("Override companyName mismatch")
    if _require_non_empty_string(override.get("organizationNumber"), "override.organizationNumber") != metadata.organization_number:
        raise NotesRenderError("Override organizationNumber mismatch")
    if _require_non_empty_string(override.get("currentReportingPeriod"), "override.currentReportingPeriod") != metadata.current_reporting_period:
        raise NotesRenderError("Override currentReportingPeriod mismatch")

    signed_ref = _require_dict(override.get("signedReference"), "override.signedReference")
    if _require_non_empty_string(signed_ref.get("sha256"), "override.signedReference.sha256") != SIGNED_REFERENCE_SHA256:
        raise NotesRenderError("Override signed reference SHA-256 mismatch")

    full_raw = override.get("fullNoteOverrides")
    if not isinstance(full_raw, list):
        raise NotesRenderError("fullNoteOverrides must be a list")
    full_map: Dict[int, Dict[str, Any]] = {}
    for item in full_raw:
        obj = _require_dict(item, "fullNoteOverrides[]")
        num = obj.get("noteNumber")
        if not isinstance(num, int):
            raise NotesRenderError("fullNoteOverrides[].noteNumber must be int")
        if num in full_map:
            raise NotesRenderError(f"Duplicate full-note override: note {num}")
        if num not in FULL_NOTE_OVERRIDE_NOTES:
            raise NotesRenderError(f"Unexpected full-note override for note {num}")
        if _require_non_empty_string(obj.get("title"), f"fullNoteOverrides[{num}].title") != CANONICAL_NOTE_TITLES[num - 1]:
            raise NotesRenderError(f"Full-note override title mismatch for note {num}")

        paragraphs = obj.get("paragraphs", [])
        tables = obj.get("tables", [])
        page_segments = obj.get("pageSegments")
        if not isinstance(paragraphs, list):
            raise NotesRenderError(f"fullNoteOverrides[{num}].paragraphs must be list")
        if not isinstance(tables, list):
            raise NotesRenderError(f"fullNoteOverrides[{num}].tables must be list")
        if page_segments is not None and not isinstance(page_segments, dict):
            raise NotesRenderError(f"fullNoteOverrides[{num}].pageSegments must be object when present")
        if not paragraphs and not tables and not page_segments:
            raise NotesRenderError(f"full override missing visible signed-reference block for note {num}")

        _require_non_empty_string(obj.get("sourceJustification"), f"fullNoteOverrides[{num}].sourceJustification")
        covered_source_refs = obj.get("coveredSourceRefs")
        if not isinstance(covered_source_refs, list) or not covered_source_refs:
            raise NotesRenderError(f"fullNoteOverrides[{num}].coveredSourceRefs must be non-empty list")
        has_signed_page_ref = False
        for idx, ref in enumerate(covered_source_refs, start=1):
            ref_obj = _require_dict(ref, f"fullNoteOverrides[{num}].coveredSourceRefs[{idx}]")
            kind = _require_non_empty_string(ref_obj.get("kind"), f"fullNoteOverrides[{num}].coveredSourceRefs[{idx}].kind")
            value = _require_non_empty_string(ref_obj.get("value"), f"fullNoteOverrides[{num}].coveredSourceRefs[{idx}].value")
            if kind == "signed_reference_page":
                has_signed_page_ref = True
                if not re.fullmatch(r"\d+", value):
                    raise NotesRenderError(
                        f"fullNoteOverrides[{num}] signed_reference_page value must be numeric page reference, got {value!r}"
                    )
                page = int(value)
                if page < 9 or page > 19:
                    raise NotesRenderError(
                        f"fullNoteOverrides[{num}] signed_reference_page value out of approved range 9-19: {page}"
                    )
        if not has_signed_page_ref:
            raise NotesRenderError(f"fullNoteOverrides[{num}] must include at least one signed_reference_page reference")
        covered = obj.get("coveredDiagnostics", obj.get("coveredDiagnosticCodes", []))
        if not isinstance(covered, list):
            raise NotesRenderError(f"fullNoteOverrides[{num}].coveredDiagnostics must be list")
        for code in covered:
            _require_non_empty_string(code, f"fullNoteOverrides[{num}].coveredDiagnostics[]")

        full_map[num] = obj

    if set(full_map.keys()) != FULL_NOTE_OVERRIDE_NOTES:
        raise NotesRenderError("fullNoteOverrides must cover exactly approved full-note authority set")

    inter_insertions = override.get("interNoteInsertions")
    if not isinstance(inter_insertions, list):
        raise NotesRenderError("interNoteInsertions must be list")
    inter_map: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for idx, item in enumerate(inter_insertions, start=1):
        obj = _require_dict(item, "interNoteInsertions[]")
        insertion_id = _require_non_empty_string(obj.get("id"), f"interNoteInsertions[{idx}].id")
        page_number = obj.get("pageNumber")
        if not isinstance(page_number, int) or page_number not in ALLOWED_INSERTION_PAGES:
            raise NotesRenderError(f"interNoteInsertions[{insertion_id}].pageNumber must be integer in 9..19")
        insert_before = obj.get("insertBeforeNoteNumber")
        if not isinstance(insert_before, int) or insert_before < 1 or insert_before > 28:
            raise NotesRenderError(f"interNoteInsertions[{insertion_id}].insertBeforeNoteNumber must be 1..28")
        if insert_before not in PAGE_NOTE_MAP.get(page_number, []):
            raise NotesRenderError(
                f"interNoteInsertions[{insertion_id}] targets note {insert_before} which is not rendered on page {page_number}"
            )
        _require_non_empty_string(obj.get("sourceJustification"), f"interNoteInsertions[{insertion_id}].sourceJustification")
        require_allowed_override_kind(obj.get("overrideKind"), f"interNoteInsertions[{insertion_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(
            obj.get("diagnosticCovered"), f"interNoteInsertions[{insertion_id}].diagnosticCovered"
        )
        require_note_diagnostic_covered(insert_before, diagnostic_covered, f"interNoteInsertions[{insertion_id}].diagnosticCovered")
        refs = obj.get("coveredSourceRefs")
        if not isinstance(refs, list) or not refs:
            raise NotesRenderError(f"interNoteInsertions[{insertion_id}].coveredSourceRefs must be non-empty list")
        has_signed_page_ref = False
        for ref_idx, ref in enumerate(refs, start=1):
            ref_obj = _require_dict(ref, f"interNoteInsertions[{insertion_id}].coveredSourceRefs[{ref_idx}]")
            kind = _require_non_empty_string(
                ref_obj.get("kind"), f"interNoteInsertions[{insertion_id}].coveredSourceRefs[{ref_idx}].kind"
            )
            value = _require_non_empty_string(
                ref_obj.get("value"), f"interNoteInsertions[{insertion_id}].coveredSourceRefs[{ref_idx}].value"
            )
            if kind == "signed_reference_page":
                has_signed_page_ref = True
                if not re.fullmatch(r"\d+", value):
                    raise NotesRenderError(
                        f"interNoteInsertions[{insertion_id}] signed_reference_page value must be numeric page reference, got {value!r}"
                    )
                page = int(value)
                if page < 9 or page > 19:
                    raise NotesRenderError(
                        f"interNoteInsertions[{insertion_id}] signed_reference_page value out of approved range 9-19: {page}"
                    )
        if not has_signed_page_ref:
            raise NotesRenderError(f"interNoteInsertions[{insertion_id}] must include signed_reference_page reference")

        _render_signed_reference_text_block(obj, field_prefix=f"interNoteInsertions[{insertion_id}]")
        key = (page_number, insert_before)
        inter_map.setdefault(key, []).append(obj)

    preface_raw = override.get("hybridNotePrefaceParagraphs")
    if not isinstance(preface_raw, list):
        raise NotesRenderError("hybridNotePrefaceParagraphs must be list")
    preface_map: Dict[int, List[Dict[str, Any]]] = {n: [] for n in HYBRID_WORKBOOK_NOTES}
    for idx, item in enumerate(preface_raw, start=1):
        obj = _require_dict(item, "hybridNotePrefaceParagraphs[]")
        preface_id = _require_non_empty_string(obj.get("id"), f"hybridNotePrefaceParagraphs[{idx}].id")
        note_number = obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number not in HYBRID_WORKBOOK_NOTES:
            raise NotesRenderError(f"hybridNotePrefaceParagraphs[{preface_id}].noteNumber must target hybrid note")
        position = _require_non_empty_string(obj.get("position"), f"hybridNotePrefaceParagraphs[{preface_id}].position")
        if position != "before_table":
            raise NotesRenderError(f"hybridNotePrefaceParagraphs[{preface_id}] unsupported position: {position}")
        _require_non_empty_string(obj.get("sourceJustification"), f"hybridNotePrefaceParagraphs[{preface_id}].sourceJustification")
        require_allowed_override_kind(obj.get("overrideKind"), f"hybridNotePrefaceParagraphs[{preface_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(
            obj.get("diagnosticCovered"), f"hybridNotePrefaceParagraphs[{preface_id}].diagnosticCovered"
        )
        require_note_diagnostic_covered(note_number, diagnostic_covered, f"hybridNotePrefaceParagraphs[{preface_id}].diagnosticCovered")

        refs = obj.get("coveredSourceRefs")
        if not isinstance(refs, list) or not refs:
            raise NotesRenderError(f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs must be non-empty list")
        has_signed_page_ref = False
        for ref_idx, ref in enumerate(refs, start=1):
            ref_obj = _require_dict(ref, f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[{ref_idx}]")
            kind = _require_non_empty_string(
                ref_obj.get("kind"), f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[{ref_idx}].kind"
            )
            value = _require_non_empty_string(
                ref_obj.get("value"), f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[{ref_idx}].value"
            )
            if kind == "signed_reference_page":
                has_signed_page_ref = True
                if not re.fullmatch(r"\d+", value):
                    raise NotesRenderError(
                        f"hybridNotePrefaceParagraphs[{preface_id}] signed_reference_page value must be numeric page reference, got {value!r}"
                    )
                page = int(value)
                if page < 9 or page > 19:
                    raise NotesRenderError(
                        f"hybridNotePrefaceParagraphs[{preface_id}] signed_reference_page value out of approved range 9-19: {page}"
                    )
        if not has_signed_page_ref:
            raise NotesRenderError(f"hybridNotePrefaceParagraphs[{preface_id}] must include signed_reference_page reference")
        if note_number == 4 and not any(isinstance(ref, dict) and ref.get("kind") == "signed_reference_page" and ref.get("value") == "12" for ref in refs):
            raise NotesRenderError(f"hybridNotePrefaceParagraphs[{preface_id}] note 4 requires signed_reference_page=12")

        _render_signed_reference_text_block(obj, field_prefix=f"hybridNotePrefaceParagraphs[{preface_id}]")
        preface_map[note_number].append(obj)

    appendix_raw = override.get("hybridNoteAppendixParagraphs")
    if not isinstance(appendix_raw, list):
        raise NotesRenderError("hybridNoteAppendixParagraphs must be list")
    appendix_map: Dict[int, List[Dict[str, Any]]] = {n: [] for n in HYBRID_WORKBOOK_NOTES}
    for idx, item in enumerate(appendix_raw, start=1):
        obj = _require_dict(item, "hybridNoteAppendixParagraphs[]")
        appendix_id = _require_non_empty_string(obj.get("id"), f"hybridNoteAppendixParagraphs[{idx}].id")
        note_number = obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number not in HYBRID_WORKBOOK_NOTES:
            raise NotesRenderError(f"hybridNoteAppendixParagraphs[{appendix_id}].noteNumber must target hybrid note")
        position = _require_non_empty_string(obj.get("position"), f"hybridNoteAppendixParagraphs[{appendix_id}].position")
        if position != "after_table":
            raise NotesRenderError(f"hybridNoteAppendixParagraphs[{appendix_id}] unsupported position: {position}")
        _require_non_empty_string(obj.get("sourceJustification"), f"hybridNoteAppendixParagraphs[{appendix_id}].sourceJustification")
        require_allowed_override_kind(obj.get("overrideKind"), f"hybridNoteAppendixParagraphs[{appendix_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(
            obj.get("diagnosticCovered"), f"hybridNoteAppendixParagraphs[{appendix_id}].diagnosticCovered"
        )
        require_note_diagnostic_covered(note_number, diagnostic_covered, f"hybridNoteAppendixParagraphs[{appendix_id}].diagnosticCovered")

        refs = obj.get("coveredSourceRefs")
        if not isinstance(refs, list) or not refs:
            raise NotesRenderError(f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs must be non-empty list")
        has_signed_page_ref = False
        for ref_idx, ref in enumerate(refs, start=1):
            ref_obj = _require_dict(ref, f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[{ref_idx}]")
            kind = _require_non_empty_string(
                ref_obj.get("kind"), f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[{ref_idx}].kind"
            )
            value = _require_non_empty_string(
                ref_obj.get("value"), f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[{ref_idx}].value"
            )
            if kind == "signed_reference_page":
                has_signed_page_ref = True
                if not re.fullmatch(r"\d+", value):
                    raise NotesRenderError(
                        f"hybridNoteAppendixParagraphs[{appendix_id}] signed_reference_page value must be numeric page reference, got {value!r}"
                    )
                page = int(value)
                if page < 9 or page > 19:
                    raise NotesRenderError(
                        f"hybridNoteAppendixParagraphs[{appendix_id}] signed_reference_page value out of approved range 9-19: {page}"
                    )
        if not has_signed_page_ref:
            raise NotesRenderError(f"hybridNoteAppendixParagraphs[{appendix_id}] must include signed_reference_page reference")
        if note_number == 4 and not any(isinstance(ref, dict) and ref.get("kind") == "signed_reference_page" and ref.get("value") == "12" for ref in refs):
            raise NotesRenderError(f"hybridNoteAppendixParagraphs[{appendix_id}] note 4 requires signed_reference_page=12")

        _render_signed_reference_text_block(obj, field_prefix=f"hybridNoteAppendixParagraphs[{appendix_id}]")
        appendix_map[note_number].append(obj)

    row_overrides = override.get("rowOverrides")
    if not isinstance(row_overrides, list):
        raise NotesRenderError("rowOverrides must be list")
    row_map: Dict[int, List[Dict[str, Any]]] = {n: [] for n in HYBRID_WORKBOOK_NOTES}
    row_ids: set[str] = set()
    for item in row_overrides:
        obj = _require_dict(item, "rowOverrides[]")
        row_id = _require_non_empty_string(obj.get("id"), "rowOverrides[].id")
        if row_id in row_ids:
            raise NotesRenderError(f"Duplicate row override id: {row_id}")
        row_ids.add(row_id)
        note_number = obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number not in HYBRID_WORKBOOK_NOTES:
            raise NotesRenderError("rowOverrides may only target hybrid notes")
        row_type = _require_non_empty_string(obj.get("type"), f"rowOverrides[{row_id}].type")
        if row_type not in {"workbook_row_authority", "signed_preview_row_override"}:
            raise NotesRenderError(f"Unsupported row override type: {row_type}")
        require_allowed_override_kind(obj.get("overrideKind"), f"rowOverrides[{row_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(obj.get("diagnosticCovered"), f"rowOverrides[{row_id}].diagnosticCovered")
        require_note_diagnostic_covered(note_number, diagnostic_covered, f"rowOverrides[{row_id}].diagnosticCovered")
        if row_type == "signed_preview_row_override" and str(obj.get("semanticPath", "")).strip() in {f"notes[{note_number}]", f"notes[{note_number}].*"}:
            raise NotesRenderError("Hybrid override cannot cover an entire note")
        if row_type == "workbook_row_authority":
            _require_non_empty_string(obj.get("worksheet"), f"rowOverrides[{row_id}].worksheet")
            _require_non_empty_string(obj.get("labelCell"), f"rowOverrides[{row_id}].labelCell")
            _require_non_empty_string(obj.get("currentCell"), f"rowOverrides[{row_id}].currentCell")
            prev = obj.get("previousCell")
            if prev is not None and not isinstance(prev, str):
                raise NotesRenderError(f"rowOverrides[{row_id}].previousCell must be string")
        if note_number == 4 and row_type == "signed_preview_row_override":
            refs = obj.get("coveredSourceRefs")
            if not isinstance(refs, list) or not refs:
                raise NotesRenderError(f"rowOverrides[{row_id}] note 4 signed rows require coveredSourceRefs")
            if not any(isinstance(ref, dict) and ref.get("kind") == "signed_reference_page" and ref.get("value") == "12" for ref in refs):
                raise NotesRenderError(f"rowOverrides[{row_id}] note 4 signed rows require signed_reference_page=12")
        row_map[note_number].append(obj)

    for note_number in HYBRID_WORKBOOK_NOTES:
        if not any(obj.get("type") == "workbook_row_authority" for obj in row_map[note_number]):
            raise NotesRenderError(f"Hybrid mode without exact workbook row/cell authority is invalid for note {note_number}")

    field_overrides = override.get("fieldOverrides")
    if not isinstance(field_overrides, list):
        raise NotesRenderError("fieldOverrides must be list")
    field_map: Dict[int, List[Dict[str, Any]]] = {n: [] for n in HYBRID_WORKBOOK_NOTES}
    field_ids: set[str] = set()
    for item in field_overrides:
        obj = _require_dict(item, "fieldOverrides[]")
        field_id = _require_non_empty_string(obj.get("id"), "fieldOverrides[].id")
        if field_id in field_ids:
            raise NotesRenderError(f"Duplicate field override id: {field_id}")
        field_ids.add(field_id)
        note_number = obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number not in HYBRID_WORKBOOK_NOTES:
            raise NotesRenderError("fieldOverrides may only target hybrid notes")
        path = _require_non_empty_string(obj.get("semanticPath"), f"fieldOverrides[{field_id}].semanticPath")
        if path in {f"notes[{note_number}]", f"notes[{note_number}].*"}:
            raise NotesRenderError("Hybrid override cannot cover an entire note")
        _require_non_empty_string(obj.get("signedDisplayValue"), f"fieldOverrides[{field_id}].signedDisplayValue")
        source = _require_dict(obj.get("workbookSource"), f"fieldOverrides[{field_id}].workbookSource")
        _require_non_empty_string(source.get("worksheet"), f"fieldOverrides[{field_id}].workbookSource.worksheet")
        _require_non_empty_string(source.get("cell"), f"fieldOverrides[{field_id}].workbookSource.cell")
        require_allowed_override_kind(obj.get("overrideKind"), f"fieldOverrides[{field_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(obj.get("diagnosticCovered"), f"fieldOverrides[{field_id}].diagnosticCovered")
        require_note_diagnostic_covered(note_number, diagnostic_covered, f"fieldOverrides[{field_id}].diagnosticCovered")
        if note_number == 4:
            refs = obj.get("coveredSourceRefs")
            if not isinstance(refs, list) or not refs:
                raise NotesRenderError(f"fieldOverrides[{field_id}] note 4 requires coveredSourceRefs")
            if not any(isinstance(ref, dict) and ref.get("kind") == "signed_reference_page" and ref.get("value") == "12" for ref in refs):
                raise NotesRenderError(f"fieldOverrides[{field_id}] note 4 requires signed_reference_page=12")
        field_map[note_number].append(obj)

    label_mappings = override.get("labelMappings")
    if not isinstance(label_mappings, list):
        raise NotesRenderError("labelMappings must be list")
    label_map: Dict[int, List[Dict[str, Any]]] = {n: [] for n in HYBRID_WORKBOOK_NOTES}
    label_ids: set[str] = set()
    for item in label_mappings:
        obj = _require_dict(item, "labelMappings[]")
        mapping_id = _require_non_empty_string(obj.get("id"), "labelMappings[].id")
        if mapping_id in label_ids:
            raise NotesRenderError(f"Duplicate label mapping id: {mapping_id}")
        label_ids.add(mapping_id)
        note_number = obj.get("noteNumber")
        if not isinstance(note_number, int) or note_number not in HYBRID_WORKBOOK_NOTES:
            raise NotesRenderError("labelMappings may only target hybrid notes")
        _require_non_empty_string(obj.get("semanticPath"), f"labelMappings[{mapping_id}].semanticPath")
        _require_non_empty_string(obj.get("signedLabel"), f"labelMappings[{mapping_id}].signedLabel")
        _require_non_empty_string(obj.get("workbookSourceCell"), f"labelMappings[{mapping_id}].workbookSourceCell")
        require_allowed_override_kind(obj.get("overrideKind"), f"labelMappings[{mapping_id}].overrideKind")
        diagnostic_covered = _require_non_empty_string(obj.get("diagnosticCovered"), f"labelMappings[{mapping_id}].diagnosticCovered")
        require_note_diagnostic_covered(note_number, diagnostic_covered, f"labelMappings[{mapping_id}].diagnosticCovered")
        if note_number == 4:
            refs = obj.get("coveredSourceRefs")
            if not isinstance(refs, list) or not refs:
                raise NotesRenderError(f"labelMappings[{mapping_id}] note 4 requires coveredSourceRefs")
            if not any(isinstance(ref, dict) and ref.get("kind") == "signed_reference_page" and ref.get("value") == "12" for ref in refs):
                raise NotesRenderError(f"labelMappings[{mapping_id}] note 4 requires signed_reference_page=12")
        label_map[note_number].append(obj)

    ack = override.get("acknowledgedPolicyDiagnostics")
    if not isinstance(ack, list):
        raise NotesRenderError("acknowledgedPolicyDiagnostics must be list")

    for entry in ack:
        obj = _require_dict(entry, "acknowledgedPolicyDiagnostics[]")
        code = _require_non_empty_string(obj.get("code"), "acknowledgedPolicyDiagnostics[].code")
        note_number = obj.get("noteNumber")
        if note_number is not None and not isinstance(note_number, int):
            raise NotesRenderError("acknowledgedPolicyDiagnostics[].noteNumber must be int or null")
        if code == "NOTE_NUMBER_PLACEHOLDER_UNRESOLVED" and isinstance(note_number, int) and note_number in FULL_NOTE_OVERRIDE_NOTES:
            continue
        if (note_number, code) not in review_diags and (None, code) not in review_diags:
            raise NotesRenderError(f"Override claims absent diagnostics: note={note_number} code={code}")

    return {
        "fullNoteOverrides": full_map,
        "interNoteInsertions": inter_map,
        "hybridNotePrefaceParagraphs": preface_map,
        "hybridNoteAppendixParagraphs": appendix_map,
        "rowOverrides": row_map,
        "fieldOverrides": field_map,
        "labelMappings": label_map,
        "acknowledgedPolicyDiagnostics": ack,
    }


def _resolve_signed_block_with_workbook_bindings(
    *,
    note_number: int,
    block: Dict[str, Any],
    cell_lookup: Dict[str, Dict[str, Any]],
    cell_lookup_by_sheet: Dict[str, Dict[str, Dict[str, Any]]],
    workbook_date_system: str | None,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    bindings = block.get("workbookBindings")
    if bindings is None:
        return block, []
    if not isinstance(bindings, list):
        raise NotesRenderError(f"hybrid note {note_number} workbookBindings must be a list")

    resolved = dict(block)
    paragraphs = resolved.get("paragraphs", [])
    if not isinstance(paragraphs, list):
        raise NotesRenderError(f"hybrid note {note_number} paragraphs must be a list when workbookBindings are used")

    refs: List[Dict[str, str]] = []
    replacements: Dict[str, str] = {}
    for idx, entry in enumerate(bindings, start=1):
        obj = _require_dict(entry, f"workbookBindings[{idx}]")
        placeholder = _require_non_empty_string(obj.get("placeholder"), f"workbookBindings[{idx}].placeholder")
        worksheet = _require_non_empty_string(obj.get("worksheet"), f"workbookBindings[{idx}].worksheet")
        cell = _require_non_empty_string(obj.get("cell"), f"workbookBindings[{idx}].cell")
        role = _require_non_empty_string(obj.get("semanticRole"), f"workbookBindings[{idx}].semanticRole")

        cell_obj = cell_lookup_by_sheet.get(worksheet, {}).get(cell)
        if not isinstance(cell_obj, dict):
            cell_obj = cell_lookup.get(cell)
        if not isinstance(cell_obj, dict):
            raise NotesRenderError(f"hybrid note {note_number} workbook binding cell missing: {worksheet}!{cell}")
        source_trace = cell_obj.get("sourceTrace")
        source_ws = ""
        if isinstance(source_trace, dict):
            ws_value = source_trace.get("worksheetName")
            if isinstance(ws_value, str):
                source_ws = ws_value
        if source_ws and source_ws != worksheet:
            raise NotesRenderError(
                f"hybrid note {note_number} workbook binding worksheet mismatch for {cell}: expected {worksheet}, got {source_ws}"
            )

        rendered_value = _display_from_cell(cell_obj, workbook_date_system=workbook_date_system)
        expected = obj.get("expectedRenderedValue")
        if isinstance(expected, str) and rendered_value != expected:
            raise NotesRenderError(
                f"hybrid note {note_number} workbook binding value drift for {worksheet}!{cell}: "
                f"expected {expected!r}, got {rendered_value!r}"
            )
        replacements[placeholder] = rendered_value
        refs.append(
            {
                "authority": "workbook",
                "semanticRole": role,
                "worksheet": worksheet,
                "cell": cell,
                "formula": _require_string(cell_obj.get("formula"), "formula") if isinstance(cell_obj.get("formula"), str) else "",
                "rawValue": _require_string(cell_obj.get("rawValue"), "rawValue") if isinstance(cell_obj.get("rawValue"), str) else "",
                "cachedValue": _require_string(cell_obj.get("cachedValue"), "cachedValue") if isinstance(cell_obj.get("cachedValue"), str) else "",
                "displayedValue": rendered_value,
            }
        )

    resolved_paragraphs: List[str] = []
    for idx, paragraph in enumerate(paragraphs, start=1):
        text = _require_string(paragraph, f"paragraphs[{idx}]")
        for placeholder, replacement in replacements.items():
            text = text.replace(placeholder, replacement)
        if "{{" in text or "}}" in text:
            raise NotesRenderError(f"hybrid note {note_number} unresolved workbook binding placeholder in paragraph")
        resolved_paragraphs.append(text)
    resolved["paragraphs"] = resolved_paragraphs
    return resolved, refs


def _validate_note4_hybrid_model(
    *,
    semantic_note: Dict[str, Any],
    row_overrides: List[Dict[str, Any]],
    field_overrides: List[Dict[str, Any]],
    label_mappings: List[Dict[str, Any]],
    preface_blocks: List[Dict[str, Any]],
    appendix_blocks: List[Dict[str, Any]],
    workbook_date_system: str | None,
) -> None:
    dispositions = _extract_range_meta(semantic_note, 4)
    expected_dispositions = {
        "Operationell leasing del 2:A1:D23": "render_content",
        "Operationell leasing del 1:A1:X172": "supporting_evidence",
    }
    if set(dispositions.keys()) != set(expected_dispositions.keys()):
        raise NotesRenderError("Note 4 fail-closed: source ranges changed")
    for key, expected in expected_dispositions.items():
        if dispositions[key].get("disposition") != expected:
            raise NotesRenderError(f"Note 4 fail-closed: disposition changed for {key}")

    lookup = _semantic_cell_lookup(semantic_note)
    lookup_by_sheet = _semantic_cell_lookup_by_sheet(semantic_note)
    sheet_lookup = lookup_by_sheet.get("Operationell leasing del 2", {})
    for coord in ("B12", "B13", "B14", "B15", "B21", "A13"):
        if coord not in sheet_lookup:
            raise NotesRenderError(f"Note 4 fail-closed: required source cell missing ({coord})")

    if _display_from_cell(sheet_lookup["A13"], workbook_date_system=workbook_date_system).strip() != "Mellan ett och fem år":
        raise NotesRenderError("Note 4 fail-closed: workbook row label drift at A13")

    expected_formulas = {
        "B12": "SUM('Operationell leasing del 1'!V20:V170)",
        "B13": "SUM('Operationell leasing del 1'!W20:W170)",
        "B14": "SUM('Operationell leasing del 1'!X20:X170)",
        "B15": "SUM(B12:B14)",
    }
    for cell, formula in expected_formulas.items():
        got = sheet_lookup[cell].get("formula")
        if got != formula:
            raise NotesRenderError(f"Note 4 fail-closed: formula drift at {cell}")

    if sheet_lookup["B21"].get("formula") not in {None, ""}:
        raise NotesRenderError("Note 4 fail-closed: B21 must remain workbook value cell without formula override")

    expected_displays = {
        "B12": "5 646 453",
        "B13": "14 285 066",
        "B14": "0",
        "B15": "19 931 519",
        "B21": "5 924 000",
    }
    for cell, expected in expected_displays.items():
        got = _display_from_cell(sheet_lookup[cell], workbook_date_system=workbook_date_system)
        if got != expected:
            raise NotesRenderError(f"Note 4 fail-closed: workbook value drift at {cell}")

    workbook_rows = [r for r in row_overrides if r.get("type") == "workbook_row_authority"]
    signed_rows = [r for r in row_overrides if r.get("type") == "signed_preview_row_override"]
    expected_workbook_row_coords = {
        "notes[4].rows[2]": ("A12", "B12"),
        "notes[4].rows[3]": ("A13", "B13"),
        "notes[4].rows[4]": ("A14", "B14"),
        "notes[4].rows[5]": ("A15", "B15"),
    }
    if len(workbook_rows) != len(expected_workbook_row_coords):
        raise NotesRenderError("Note 4 fail-closed: workbook authority row count changed")
    seen_paths: Set[str] = set()
    for row in workbook_rows:
        path = _require_non_empty_string(row.get("semanticPath"), "note4 workbook row semanticPath")
        if path in seen_paths:
            raise NotesRenderError("Note 4 fail-closed: duplicate workbook row authority semanticPath")
        seen_paths.add(path)
        expected = expected_workbook_row_coords.get(path)
        if expected is None:
            raise NotesRenderError("Note 4 fail-closed: unexpected workbook row authority semanticPath")
        if row.get("labelCell") != expected[0] or row.get("currentCell") != expected[1]:
            raise NotesRenderError("Note 4 fail-closed: workbook row authority source cell changed")

    if len(signed_rows) != 1:
        raise NotesRenderError("Note 4 fail-closed: signed comparison header row count changed")

    current_paths = {
        "notes[4].rows[2].current",
        "notes[4].rows[3].current",
        "notes[4].rows[4].current",
        "notes[4].rows[5].current",
        "notes[4].finalParagraph.current",
    }
    for entry in field_overrides:
        path = _require_non_empty_string(entry.get("semanticPath"), "note4 field override semanticPath")
        if path in current_paths:
            raise NotesRenderError("Note 4 fail-closed: signed override cannot replace workbook-authoritative current-year value")

    if len(preface_blocks) != 1:
        raise NotesRenderError("Note 4 fail-closed: missing signed introductory paragraph block")
    if len(appendix_blocks) != 1:
        raise NotesRenderError("Note 4 fail-closed: missing signed final paragraph block")


def _extract_range_meta(semantic_note: Dict[str, Any], note_number: int) -> Dict[str, Dict[str, Any]]:
    entries = semantic_note.get("sourceRangeDispositions")
    if not isinstance(entries, list):
        raise NotesRenderError(f"Note {note_number} missing sourceRangeDispositions")
    out: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        entry_obj = _require_dict(entry, f"note {note_number} sourceRangeDispositions entry")
        sheet = _require_non_empty_string(entry_obj.get("sheet"), f"note {note_number} disposition sheet")
        range_ref = _require_non_empty_string(entry_obj.get("range"), f"note {note_number} disposition range")
        disposition = _require_non_empty_string(entry_obj.get("disposition"), f"note {note_number} disposition")
        key = f"{sheet}:{range_ref}"
        if key in out:
            raise NotesRenderError(f"Note {note_number} duplicate sourceRangeDispositions entry for {key}")
        out[key] = {
            "sheet": sheet,
            "range": range_ref,
            "disposition": disposition,
            "reason": entry_obj.get("reason"),
        }
    return out


def _table_range_key(table_obj: Dict[str, Any], note_number: int) -> str:
    sheet = _require_non_empty_string(table_obj.get("sheet"), f"note {note_number} table sheet")
    range_ref = _require_non_empty_string(table_obj.get("range"), f"note {note_number} table range")
    return f"{sheet}:{range_ref}"


def _range_accounting_for_note(note_number: int, semantic_note: Dict[str, Any]) -> Dict[str, Any]:
    dispositions = _extract_range_meta(semantic_note, note_number)
    render_tables = semantic_note.get("renderTables")
    supporting = semantic_note.get("supportingEvidence")
    reconciliation = semantic_note.get("reconciliationEvidence")
    excluded_internal = semantic_note.get("excludedInternalEvidence")

    if not isinstance(render_tables, list):
        raise NotesRenderError(f"Note {note_number} renderTables must be a list")
    if not isinstance(supporting, list):
        raise NotesRenderError(f"Note {note_number} supportingEvidence must be a list")
    if not isinstance(reconciliation, list):
        raise NotesRenderError(f"Note {note_number} reconciliationEvidence must be a list")
    if not isinstance(excluded_internal, list):
        raise NotesRenderError(f"Note {note_number} excludedInternalEvidence must be a list")

    seen: Dict[str, str] = {}
    rendered_ranges: List[str] = []
    supporting_ranges: List[str] = []
    reconciliation_ranges: List[str] = []
    excluded_ranges: List[str] = []
    non_render_reasons: List[Dict[str, str]] = []

    def consume(items: List[Dict[str, Any]], expected_disposition: str, collector: List[str], include_reason: bool) -> None:
        for item in items:
            item_obj = _require_dict(item, f"note {note_number} evidence item")
            key = _table_range_key(item_obj, note_number)
            if key in seen:
                raise NotesRenderError(f"Note {note_number} source range accounted multiple times: {key}")
            disp_meta = dispositions.get(key)
            if disp_meta is None:
                raise NotesRenderError(f"Note {note_number} evidence references unmapped range: {key}")
            if disp_meta.get("disposition") != expected_disposition:
                raise NotesRenderError(
                    f"Note {note_number} range {key} disposition mismatch: expected {expected_disposition}, got {disp_meta.get('disposition')}"
                )
            seen[key] = expected_disposition
            collector.append(key)
            if include_reason:
                reason = disp_meta.get("reason")
                non_render_reasons.append(
                    {
                        "range": key,
                        "disposition": expected_disposition,
                        "reason": reason if isinstance(reason, str) and reason.strip() else "classified_non_rendered_evidence",
                    }
                )

    consume(render_tables, "render_content", rendered_ranges, include_reason=False)
    consume(supporting, "supporting_evidence", supporting_ranges, include_reason=True)
    consume(reconciliation, "reconciliation_evidence", reconciliation_ranges, include_reason=True)
    consume(excluded_internal, "excluded_internal_template_content", excluded_ranges, include_reason=True)

    missing = sorted(set(dispositions.keys()).difference(set(seen.keys())))
    if missing:
        raise NotesRenderError(f"Note {note_number} has unaccounted source ranges: {missing}")

    return {
        "renderedSourceRanges": rendered_ranges,
        "supportingEvidenceRanges": supporting_ranges,
        "reconciliationEvidenceRanges": reconciliation_ranges,
        "excludedInternalRanges": excluded_ranges,
        "nonRenderedEvidenceReasons": non_render_reasons,
    }


def _render_full_override_note(note_number: int, page_number: int, note_title: str, override_note: Dict[str, Any], continued: bool) -> Tuple[List[str], Dict[str, Any]]:
    lines = _render_note_heading(note_number, note_title, continued=continued)

    payload = override_note
    page_segments = override_note.get("pageSegments")
    if isinstance(page_segments, dict) and str(page_number) in page_segments:
        payload = _require_dict(page_segments[str(page_number)], f"override note {note_number} pageSegments[{page_number}]")

    lines.extend(_render_signed_reference_text_block(payload, field_prefix=f"fullNoteOverrides[{note_number}]"))

    return lines, {
        "fullNoteOverrideUsed": True,
        "fieldOverridesUsed": [],
        "rowOverridesUsed": [],
        "labelMappingsUsed": [],
        "prefaceOverridesUsed": [],
        "prefaceCoveredSourceRefs": [],
        "workbookRenderedSourceCells": [],
        "coveredDiagnostics": list(override_note.get("coveredDiagnostics", override_note.get("coveredDiagnosticCodes", []))),
    }


def _render_direct_note(
    note_number: int,
    note_title: str,
    semantic_note: Dict[str, Any],
    continued: bool,
    *,
    workbook_date_system: str | None,
) -> Tuple[List[str], Dict[str, Any]]:
    lines = _render_note_heading(note_number, note_title, continued=continued)

    paragraphs_payload = semantic_note.get("renderParagraphs")
    if not isinstance(paragraphs_payload, list):
        paragraphs_payload = semantic_note.get("paragraphs")
    if not isinstance(paragraphs_payload, list):
        raise NotesRenderError(f"note {note_number} paragraphs missing")

    paragraphs: List[str] = []
    for paragraph in paragraphs_payload:
        p = _require_dict(paragraph, f"note {note_number} paragraph")
        text = _require_string(p.get("text"), f"note {note_number} paragraph.text")
        if "Not X" in text:
            raise NotesRenderError(f"Unresolved Not X in note {note_number}")
        if text.strip():
            paragraphs.append(text)
    lines.extend(_render_paragraphs(paragraphs))

    tables_payload = semantic_note.get("renderTables")
    if not isinstance(tables_payload, list):
        raise NotesRenderError(f"note {note_number} renderTables missing")

    rendered_cells: List[str] = []
    for table_payload in tables_payload:
        table_obj = _require_dict(table_payload, f"note {note_number} table")
        if table_obj.get("disposition") not in {None, "render_content"}:
            raise NotesRenderError(f"Note {note_number} non-render disposition reached render path")
        rows_payload = table_obj.get("rows")
        if not isinstance(rows_payload, list):
            raise NotesRenderError(f"note {note_number} table rows malformed")
        rows: List[List[str]] = []
        for row in rows_payload:
            row_obj = _require_dict(row, f"note {note_number} row")
            cells_payload = row_obj.get("cells")
            if not isinstance(cells_payload, list):
                raise NotesRenderError(f"note {note_number} row cells malformed")
            row_text: List[str] = []
            for cell in cells_payload:
                c = _require_dict(cell, f"note {note_number} cell")
                coord = c.get("coordinate")
                if isinstance(coord, str):
                    rendered_cells.append(coord)
                row_text.append(_display_from_cell(c, workbook_date_system=workbook_date_system))
            rows.append(row_text)
        lines.extend(_render_table_rows(rows))
        lines.append("")

    if len(rendered_cells) != len(set(rendered_cells)):
        raise NotesRenderError(f"Hybrid workbook cells appear more than once for note {note_number}")

    return lines, {
        "fullNoteOverrideUsed": False,
        "fieldOverridesUsed": [],
        "rowOverridesUsed": [],
        "labelMappingsUsed": [],
        "prefaceOverridesUsed": [],
        "prefaceCoveredSourceRefs": [],
        "workbookRenderedSourceCells": rendered_cells,
        "coveredDiagnostics": [],
    }


def _render_hybrid_note(
    note_number: int,
    note_title: str,
    semantic_note: Dict[str, Any],
    row_overrides: List[Dict[str, Any]],
    field_overrides: List[Dict[str, Any]],
    label_mappings: List[Dict[str, Any]],
    preface_blocks: List[Dict[str, Any]],
    appendix_blocks: List[Dict[str, Any]],
    continued: bool,
    *,
    workbook_date_system: str | None,
) -> Tuple[List[str], Dict[str, Any]]:
    lines = _render_note_heading(note_number, note_title, continued=continued)

    if note_number == 4:
        _validate_note4_hybrid_model(
            semantic_note=semantic_note,
            row_overrides=row_overrides,
            field_overrides=field_overrides,
            label_mappings=label_mappings,
            preface_blocks=preface_blocks,
            appendix_blocks=appendix_blocks,
            workbook_date_system=workbook_date_system,
        )

    paragraphs_payload = semantic_note.get("renderParagraphs")
    if not isinstance(paragraphs_payload, list):
        paragraphs_payload = semantic_note.get("paragraphs")
    if not isinstance(paragraphs_payload, list):
        raise NotesRenderError(f"note {note_number} paragraphs missing")

    paragraphs: List[str] = []
    for paragraph in paragraphs_payload:
        p = _require_dict(paragraph, f"note {note_number} paragraph")
        text = _require_string(p.get("text"), f"note {note_number} paragraph.text")
        if text.strip():
            paragraphs.append(text)
    lines.extend(_render_paragraphs(paragraphs))

    cell_lookup = _semantic_cell_lookup(semantic_note)
    cell_lookup_by_sheet = _semantic_cell_lookup_by_sheet(semantic_note)
    workbook_rows = [r for r in row_overrides if r.get("type") == "workbook_row_authority"]
    signed_preview_rows = [r for r in row_overrides if r.get("type") == "signed_preview_row_override"]
    workbook_rows.sort(key=lambda item: int(item.get("order", 0)))
    signed_preview_rows.sort(key=lambda item: int(item.get("order", 0)))

    table_rows: List[Tuple[int, List[str]]] = []
    used_cells: List[str] = []
    used_row_ids: List[str] = []

    label_by_path = {m["semanticPath"]: m for m in label_mappings}
    field_by_path = {m["semanticPath"]: m for m in field_overrides}

    used_label_ids: List[str] = []
    used_field_ids: List[str] = []
    display_field_authorities: List[Dict[str, str]] = []
    authority_roles: Set[str] = set()

    used_preface_ids: List[str] = []
    preface_source_refs: List[Dict[str, str]] = []
    for preface in preface_blocks:
        preface_id = _require_non_empty_string(preface.get("id"), "hybrid preface id")
        used_preface_ids.append(preface_id)
        refs = preface.get("coveredSourceRefs", [])
        if isinstance(refs, list):
            for ref in refs:
                ref_obj = _require_dict(ref, f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[]")
                preface_source_refs.append(
                    {
                        "kind": _require_non_empty_string(
                            ref_obj.get("kind"),
                            f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[].kind",
                        ),
                        "value": _require_non_empty_string(
                            ref_obj.get("value"),
                            f"hybridNotePrefaceParagraphs[{preface_id}].coveredSourceRefs[].value",
                        ),
                    }
                )
        lines.extend(_render_signed_reference_text_block(preface, field_prefix=f"hybridNotePrefaceParagraphs[{preface_id}]"))
        if note_number == 4:
            role = "note4.intro_paragraph"
            if role in authority_roles:
                raise NotesRenderError("Note 4 fail-closed: intro paragraph authority duplicated")
            authority_roles.add(role)
            display_field_authorities.append(
                {
                    "semanticRole": role,
                    "authority": "signed_reference",
                    "signedReferencePage": "12",
                    "diagnosticCovered": _require_non_empty_string(preface.get("diagnosticCovered"), "note4 intro diagnosticCovered"),
                    "displayedValue": "Framtida leasingavgifter, för icke uppsägningsbara leasingavtal, förfaller till betalning enligt följande:",
                }
            )

    for row in workbook_rows:
        row_id = _require_non_empty_string(row.get("id"), "row override id")
        used_row_ids.append(row_id)
        semantic_path = _require_non_empty_string(row.get("semanticPath"), f"row override {row_id} semanticPath")
        label_path = semantic_path + ".label"
        current_path = semantic_path + ".current"
        previous_path = semantic_path + ".previous"

        label_cell = _require_non_empty_string(row.get("labelCell"), f"row override {row_id} labelCell")
        current_cell = _require_non_empty_string(row.get("currentCell"), f"row override {row_id} currentCell")
        worksheet = _require_non_empty_string(row.get("worksheet"), f"row override {row_id} worksheet")
        previous_cell = row.get("previousCell")
        if previous_cell is None:
            previous_cell = ""
        if not isinstance(previous_cell, str):
            raise NotesRenderError(f"row override {row_id} previousCell must be string")

        label_obj = cell_lookup_by_sheet.get(worksheet, {}).get(label_cell)
        current_obj = cell_lookup_by_sheet.get(worksheet, {}).get(current_cell)
        previous_obj = cell_lookup_by_sheet.get(worksheet, {}).get(previous_cell) if previous_cell else None

        if not isinstance(label_obj, dict):
            label_obj = cell_lookup.get(label_cell)
        if not isinstance(current_obj, dict):
            current_obj = cell_lookup.get(current_cell)
        if previous_cell and not isinstance(previous_obj, dict):
            previous_obj = cell_lookup.get(previous_cell)

        if not isinstance(label_obj, dict) or not isinstance(current_obj, dict) or (previous_cell and not isinstance(previous_obj, dict)):
            raise NotesRenderError(f"missing hybrid source cell fails: note {note_number} row {row_id}")

        base_label = _display_from_cell(label_obj, workbook_date_system=workbook_date_system).strip()
        base_current = _display_from_cell(current_obj, workbook_date_system=workbook_date_system).strip()
        base_previous = _display_from_cell(previous_obj, workbook_date_system=workbook_date_system).strip() if previous_cell else ""

        used_cells.extend([label_cell, current_cell])
        if previous_cell:
            used_cells.append(previous_cell)

        if label_path in label_by_path:
            mapping = label_by_path[label_path]
            base_label = _require_string(mapping.get("signedLabel"), f"label mapping {mapping.get('id')} signedLabel")
            used_label_ids.append(_require_non_empty_string(mapping.get("id"), "label mapping id"))
            if note_number == 4:
                role = f"{semantic_path}.label"
                if role in authority_roles:
                    raise NotesRenderError("Note 4 fail-closed: duplicate authority for label")
                authority_roles.add(role)
                display_field_authorities.append(
                    {
                        "semanticRole": role,
                        "authority": "signed_reference",
                        "signedReferencePage": "12",
                        "diagnosticCovered": _require_non_empty_string(mapping.get("diagnosticCovered"), "note4 label diagnosticCovered"),
                        "displayedValue": base_label,
                    }
                )
        elif note_number == 4:
            role = f"{semantic_path}.label"
            if role in authority_roles:
                raise NotesRenderError("Note 4 fail-closed: duplicate authority for label")
            authority_roles.add(role)
            display_field_authorities.append(
                {
                    "semanticRole": role,
                    "authority": "workbook",
                    "worksheet": worksheet,
                    "cell": label_cell,
                    "formula": _require_string(label_obj.get("formula"), "label formula") if isinstance(label_obj.get("formula"), str) else "",
                    "rawValue": _require_string(label_obj.get("rawValue"), "label rawValue") if isinstance(label_obj.get("rawValue"), str) else "",
                    "cachedValue": _require_string(label_obj.get("cachedValue"), "label cachedValue") if isinstance(label_obj.get("cachedValue"), str) else "",
                    "displayedValue": base_label,
                }
            )

        if current_path in field_by_path:
            ov = field_by_path[current_path]
            base_current = _require_string(ov.get("signedDisplayValue"), f"field override {ov.get('id')} signedDisplayValue")
            used_field_ids.append(_require_non_empty_string(ov.get("id"), "field override id"))
            if note_number == 4:
                raise NotesRenderError("Note 4 fail-closed: current-year value cannot be signed override")
        elif note_number == 4:
            role = f"{semantic_path}.current"
            if role in authority_roles:
                raise NotesRenderError("Note 4 fail-closed: duplicate authority for current value")
            authority_roles.add(role)
            display_field_authorities.append(
                {
                    "semanticRole": role,
                    "authority": "workbook",
                    "worksheet": worksheet,
                    "cell": current_cell,
                    "formula": _require_string(current_obj.get("formula"), "current formula") if isinstance(current_obj.get("formula"), str) else "",
                    "rawValue": _require_string(current_obj.get("rawValue"), "current rawValue") if isinstance(current_obj.get("rawValue"), str) else "",
                    "cachedValue": _require_string(current_obj.get("cachedValue"), "current cachedValue") if isinstance(current_obj.get("cachedValue"), str) else "",
                    "displayedValue": base_current,
                }
            )

        if previous_path in field_by_path:
            ov = field_by_path[previous_path]
            base_previous = _require_string(ov.get("signedDisplayValue"), f"field override {ov.get('id')} signedDisplayValue")
            used_field_ids.append(_require_non_empty_string(ov.get("id"), "field override id"))
            if note_number == 4:
                role = f"{semantic_path}.previous"
                if role in authority_roles:
                    raise NotesRenderError("Note 4 fail-closed: duplicate authority for previous value")
                authority_roles.add(role)
                display_field_authorities.append(
                    {
                        "semanticRole": role,
                        "authority": "signed_reference",
                        "signedReferencePage": "12",
                        "diagnosticCovered": _require_non_empty_string(ov.get("diagnosticCovered"), "note4 previous diagnosticCovered"),
                        "displayedValue": base_previous,
                    }
                )
        elif note_number == 4:
            raise NotesRenderError("Note 4 fail-closed: missing signed previous-year override")

        row_order = int(row.get("order", 0))
        table_rows.append((row_order, [base_label, base_current, base_previous]))

    for row in signed_preview_rows:
        row_id = _require_non_empty_string(row.get("id"), "signed preview row id")
        used_row_ids.append(row_id)
        signed_display = _require_dict(row.get("signedDisplay"), f"signed preview row {row_id} signedDisplay")
        row_order = int(row.get("order", 0))
        table_rows.append(
            (
                row_order,
                [
                    _require_string(signed_display.get("label", ""), f"signed preview row {row_id} label"),
                    _require_string(signed_display.get("current", ""), f"signed preview row {row_id} current"),
                    _require_string(signed_display.get("previous", ""), f"signed preview row {row_id} previous"),
                ],
            )
        )
        if note_number == 4:
            role_current = "notes[4].rows[1].current"
            role_previous = "notes[4].rows[1].previous"
            if role_current in authority_roles or role_previous in authority_roles:
                raise NotesRenderError("Note 4 fail-closed: duplicate authority for header row")
            authority_roles.add(role_current)
            authority_roles.add(role_previous)
            display_field_authorities.append(
                {
                    "semanticRole": role_current,
                    "authority": "signed_reference",
                    "signedReferencePage": "12",
                    "diagnosticCovered": _require_non_empty_string(row.get("diagnosticCovered"), "note4 header diagnosticCovered"),
                    "displayedValue": _require_string(signed_display.get("current", ""), f"signed preview row {row_id} current"),
                }
            )
            display_field_authorities.append(
                {
                    "semanticRole": role_previous,
                    "authority": "signed_reference",
                    "signedReferencePage": "12",
                    "diagnosticCovered": _require_non_empty_string(row.get("diagnosticCovered"), "note4 header diagnosticCovered"),
                    "displayedValue": _require_string(signed_display.get("previous", ""), f"signed preview row {row_id} previous"),
                }
            )

    if len(used_cells) != len(set(used_cells)):
        raise NotesRenderError(f"Hybrid workbook cells appear exactly once violation for note {note_number}")

    ordered_table_rows = [cells for _, cells in sorted(table_rows, key=lambda item: item[0])]
    lines.extend(_render_table_rows(ordered_table_rows))
    lines.append("")

    used_appendix_ids: List[str] = []
    appendix_source_refs: List[Dict[str, str]] = []
    for appendix in appendix_blocks:
        appendix_id = _require_non_empty_string(appendix.get("id"), "hybrid appendix id")
        used_appendix_ids.append(appendix_id)
        refs = appendix.get("coveredSourceRefs", [])
        if isinstance(refs, list):
            for ref in refs:
                ref_obj = _require_dict(ref, f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[]")
                appendix_source_refs.append(
                    {
                        "kind": _require_non_empty_string(
                            ref_obj.get("kind"),
                            f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[].kind",
                        ),
                        "value": _require_non_empty_string(
                            ref_obj.get("value"),
                            f"hybridNoteAppendixParagraphs[{appendix_id}].coveredSourceRefs[].value",
                        ),
                    }
                )
        resolved_appendix, binding_refs = _resolve_signed_block_with_workbook_bindings(
            note_number=note_number,
            block=appendix,
            cell_lookup=cell_lookup,
            cell_lookup_by_sheet=cell_lookup_by_sheet,
            workbook_date_system=workbook_date_system,
        )
        lines.extend(_render_signed_reference_text_block(resolved_appendix, field_prefix=f"hybridNoteAppendixParagraphs[{appendix_id}]"))
        if note_number == 4:
            role = "note4.final_paragraph"
            if role in authority_roles:
                raise NotesRenderError("Note 4 fail-closed: duplicate authority for final paragraph")
            authority_roles.add(role)
            display_field_authorities.append(
                {
                    "semanticRole": role,
                    "authority": "signed_reference",
                    "signedReferencePage": "12",
                    "diagnosticCovered": _require_non_empty_string(appendix.get("diagnosticCovered"), "note4 final diagnosticCovered"),
                    "displayedValue": "Årets leasingkostnader avseende leasingavtal, uppgår till 5 924 000 kronor (6 310 759).",
                }
            )
            for ref in binding_refs:
                role_name = ref.get("semanticRole", "")
                if role_name:
                    if role_name in authority_roles:
                        raise NotesRenderError("Note 4 fail-closed: duplicate authority role in workbook binding")
                    authority_roles.add(role_name)
                display_field_authorities.append(ref)

    covered_codes: List[str] = []
    for entry in row_overrides + field_overrides + label_mappings + appendix_blocks:
        code = entry.get("diagnosticCovered")
        if isinstance(code, str) and code not in covered_codes:
            covered_codes.append(code)

    return lines, {
        "fullNoteOverrideUsed": False,
        "fieldOverridesUsed": used_field_ids,
        "rowOverridesUsed": used_row_ids,
        "labelMappingsUsed": used_label_ids,
        "prefaceOverridesUsed": used_preface_ids,
        "prefaceCoveredSourceRefs": preface_source_refs,
        "appendixOverridesUsed": used_appendix_ids,
        "appendixCoveredSourceRefs": appendix_source_refs,
        "workbookRenderedSourceCells": used_cells,
        "coveredDiagnostics": covered_codes,
        "displayFieldAuthorities": display_field_authorities,
    }


def render_notes(
    *,
    semantic_input_path: Path,
    raw_input_path: Path,
    metadata_path: Path,
    mapping_path: Path,
    management_contract_path: Path,
    preview_override_path: Path,
) -> Dict[str, Any]:
    metadata = load_report_metadata(metadata_path)

    semantic_contract = _load_json(semantic_input_path, field_name="notes semantic contract")
    raw_contract = _load_json(raw_input_path, field_name="notes raw contract")
    _load_json(management_contract_path, field_name="management semantic contract")
    preview_override = _load_json(preview_override_path, field_name="notes preview override")

    semantic_sha = _sha256_path(semantic_input_path)
    raw_sha = _sha256_path(raw_input_path)
    metadata_sha = _sha256_path(metadata_path)
    mapping_sha = _sha256_path(mapping_path)
    management_sha = _sha256_path(management_contract_path)
    override_sha = _sha256_path(preview_override_path)
    workbook_date_system = _workbook_date_system_mode(raw_contract)

    notes_by_number, source_ranges_used, source_cells_used, formulas_used, review_diags = _validate_semantic_contract(
        semantic_contract,
        raw_contract=raw_contract,
        metadata=metadata,
        mapping_bytes=mapping_path.read_bytes(),
    )

    override_scope = _validate_override_manifest(preview_override, metadata=metadata, review_diags=review_diags)

    tex_lines: List[str] = [
        "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
        "\\fancypagestyle{notesstyle}{%",
        "  \\fancyhf{}",
        "  \\fancyhead[L]{\\fontfamily{phv}\\selectfont\\small \\shortstack[l]{\\FinancialStatementCompanyHeader}}",
        "  \\fancyhead[R]{\\fontfamily{phv}\\selectfont\\small \\notespageindicator}",
        "  \\renewcommand{\\headrulewidth}{0pt}",
        "  \\renewcommand{\\footrulewidth}{0pt}",
        "}",
        f"\\gdef\\FinancialStatementCompanyHeader{{{_escape_latex(metadata.company_name)}\\\\Org.nr {_escape_latex(metadata.organization_number)}}}",
        "\\newcommand{\\notespageindicator}{}",
        "",
        "\\footnotesize",
        "\\setlength{\\parskip}{0.18em}",
        "\\renewcommand{\\arraystretch}{0.92}",
        "\\setlength{\\emergencystretch}{2.2em}",
        "\\sloppy",
    ]

    per_note_range_accounting: Dict[str, Dict[str, Any]] = {}
    per_note_provenance: Dict[str, Dict[str, Any]] = {}

    for note_number in range(1, 29):
        per_note_range_accounting[str(note_number)] = _range_accounting_for_note(note_number, notes_by_number[note_number])

    note_pages: Dict[int, List[int]] = {n: [] for n in range(1, 29)}

    for page in range(9, 20):
        tex_lines.append("\\clearpage")
        tex_lines.append(f"\\renewcommand{{\\notespageindicator}}{{{page} (19)}}")
        tex_lines.append("\\pagestyle{notesstyle}")
        tex_lines.append("\\thispagestyle{notesstyle}")
        tex_lines.append("")

        for note_number in PAGE_NOTE_MAP[page]:
            inter_blocks = override_scope["interNoteInsertions"].get((page, note_number), [])
            for block in inter_blocks:
                block_id = _require_non_empty_string(block.get("id"), "inter-note insertion id")
                tex_lines.extend(_render_signed_reference_text_block(block, field_prefix=f"interNoteInsertions[{block_id}]"))

            note_pages[note_number].append(page)
            semantic_note = notes_by_number[note_number]
            title = _require_non_empty_string(semantic_note.get("title"), f"note {note_number} title")
            mode = _require_non_empty_string(_require_dict(semantic_note.get("renderAuthority"), "renderAuthority").get("mode"), "renderAuthority.mode")
            continued = page == 10 and note_number == 1

            if mode == "direct_workbook":
                content_lines, mode_info = _render_direct_note(
                    note_number,
                    title,
                    semantic_note,
                    continued,
                    workbook_date_system=workbook_date_system,
                )
            elif mode == "hybrid_workbook_preview_override":
                content_lines, mode_info = _render_hybrid_note(
                    note_number,
                    title,
                    semantic_note,
                    override_scope["rowOverrides"].get(note_number, []),
                    override_scope["fieldOverrides"].get(note_number, []),
                    override_scope["labelMappings"].get(note_number, []),
                    override_scope["hybridNotePrefaceParagraphs"].get(note_number, []),
                    override_scope["hybridNoteAppendixParagraphs"].get(note_number, []),
                    continued,
                    workbook_date_system=workbook_date_system,
                )
            elif mode == "full_note_preview_override":
                full = override_scope["fullNoteOverrides"].get(note_number)
                if full is None:
                    raise NotesRenderError(f"Missing full-note override entry for note {note_number}")
                content_lines, mode_info = _render_full_override_note(note_number, page, title, full, continued)
            else:
                raise NotesRenderError(f"Unsupported authority mode: {mode}")

            tex_lines.extend(content_lines)

            accounting = per_note_range_accounting[str(note_number)]
            workbook_supporting = (
                accounting["supportingEvidenceRanges"]
                + accounting["reconciliationEvidenceRanges"]
                + accounting["excludedInternalRanges"]
            )

            per_note_provenance[str(note_number)] = {
                "renderAuthority": mode,
                "workbookRenderedSourceRanges": accounting["renderedSourceRanges"],
                "workbookRenderedSourceCells": mode_info["workbookRenderedSourceCells"],
                "workbookSupportingEvidence": workbook_supporting,
                "fullNoteOverrideUsed": mode_info["fullNoteOverrideUsed"],
                "fieldOverridesUsed": mode_info["fieldOverridesUsed"],
                "rowOverridesUsed": mode_info["rowOverridesUsed"],
                "labelMappingsUsed": mode_info["labelMappingsUsed"],
                "prefaceOverridesUsed": mode_info.get("prefaceOverridesUsed", []),
                "prefaceCoveredSourceRefs": mode_info.get("prefaceCoveredSourceRefs", []),
                "appendixOverridesUsed": mode_info.get("appendixOverridesUsed", []),
                "appendixCoveredSourceRefs": mode_info.get("appendixCoveredSourceRefs", []),
                "coveredDiagnostics": mode_info["coveredDiagnostics"],
                "nonRenderedEvidenceReasons": accounting["nonRenderedEvidenceReasons"],
                "physicalPage": note_pages[note_number],
                "displayFieldAuthorities": mode_info.get("displayFieldAuthorities", []),
            }

    tex_lines.append("\\fussy")
    tex_lines.append("\\normalsize")
    tex_lines.append("\\renewcommand{\\arraystretch}{1.0}")
    tex_lines.append("\\setlength{\\parskip}{0.7em}")
    tex_lines.append("")

    tex = "\n".join(tex_lines).rstrip() + "\n"

    source_workbook_sha = _require_non_empty_string(_require_dict(semantic_contract.get("sourceEvidence"), "sourceEvidence").get("sha256"), "sourceEvidence.sha256")

    provenance = {
        "schemaVersion": "2.0",
        "rendererVersion": RENDERER_VERSION,
        "semanticContractPath": str(semantic_input_path).replace("\\", "/"),
        "semanticContractSha256": semantic_sha,
        "rawContractPath": str(raw_input_path).replace("\\", "/"),
        "rawContractSha256": raw_sha,
        "sourceWorkbookSha256": source_workbook_sha,
        "metadataPath": str(metadata_path).replace("\\", "/"),
        "metadataSha256": metadata_sha,
        "mappingPath": str(mapping_path).replace("\\", "/"),
        "mappingSha256": mapping_sha,
        "managementContractPath": str(management_contract_path).replace("\\", "/"),
        "managementContractSha256": management_sha,
        "previewOverridePath": str(preview_override_path).replace("\\", "/"),
        "previewOverrideSha256": override_sha,
        "previewOverrideSourceType": _require_non_empty_string(preview_override.get("sourceType"), "override.sourceType"),
        "previewOverrideApprovalScope": _require_non_empty_string(preview_override.get("approvalScope"), "override.approvalScope"),
        "sourceRangesUsed": source_ranges_used,
        "sourceCellsUsed": source_cells_used,
        "formulasUsed": formulas_used,
        "rangeDispositionAccounting": per_note_range_accounting,
        "notes": per_note_provenance,
        "pageMap": {str(page): PAGE_NOTE_MAP[page] for page in range(9, 20)},
    }

    return {"tex": tex, "provenance": provenance}
