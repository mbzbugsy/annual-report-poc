from __future__ import annotations

import json
from typing import Any, Dict


class NotesProvenanceError(ValueError):
    pass


DIRECT_WORKBOOK_NOTES = {"13", "14"}
HYBRID_WORKBOOK_NOTES = {"4", "17", "18", "19", "22", "23", "26"}
FULL_NOTE_OVERRIDE_NOTES = {
    "1", "2", "3", "5", "6", "7", "8", "9", "10", "11", "12", "15", "16", "20", "21", "24", "25", "27", "28"
}
ALL_NOTE_KEYS = {str(i) for i in range(1, 29)}
ALLOWED_RENDER_AUTHORITIES = {
    "direct_workbook",
    "hybrid_workbook_preview_override",
    "full_note_preview_override",
}


def encode_canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def validate_provenance_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise NotesProvenanceError("Notes provenance payload must be an object")

    required_non_empty_string_fields = {
        "schemaVersion",
        "rendererVersion",
        "semanticContractPath",
        "semanticContractSha256",
        "rawContractPath",
        "rawContractSha256",
        "sourceWorkbookSha256",
        "metadataPath",
        "metadataSha256",
        "mappingPath",
        "mappingSha256",
        "managementContractPath",
        "managementContractSha256",
        "previewOverridePath",
        "previewOverrideSha256",
        "previewOverrideSourceType",
        "previewOverrideApprovalScope",
        "outputTexPath",
        "outputTexSha256",
    }

    for field in required_non_empty_string_fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise NotesProvenanceError(f"Notes provenance missing or invalid '{field}'")

    required_mapping_fields = {
        "notes": dict,
        "rangeDispositionAccounting": dict,
        "sourceRangesUsed": dict,
        "sourceCellsUsed": dict,
        "formulasUsed": dict,
        "pageMap": dict,
    }
    for field, expected_type in required_mapping_fields.items():
        value = payload.get(field)
        if not isinstance(value, expected_type):
            raise NotesProvenanceError(f"Notes provenance field '{field}' must be {expected_type.__name__}")

    notes = payload["notes"]
    note_keys = set(notes.keys())
    if note_keys != ALL_NOTE_KEYS:
        raise NotesProvenanceError("Notes provenance must contain exactly note keys '1' through '28'")

    direct_notes: set[str] = set()
    hybrid_notes: set[str] = set()
    full_override_notes: set[str] = set()

    for note_key in sorted(notes.keys(), key=int):
        note_payload = notes[note_key]
        if not isinstance(note_payload, dict):
            raise NotesProvenanceError(f"Notes provenance note '{note_key}' must be an object")

        render_authority = note_payload.get("renderAuthority")
        if render_authority not in ALLOWED_RENDER_AUTHORITIES:
            raise NotesProvenanceError(
                f"Notes provenance note '{note_key}' has invalid renderAuthority: {render_authority!r}"
            )

        for list_field in (
            "physicalPage",
            "workbookRenderedSourceRanges",
            "workbookRenderedSourceCells",
            "workbookSupportingEvidence",
            "fieldOverridesUsed",
            "rowOverridesUsed",
            "labelMappingsUsed",
            "prefaceOverridesUsed",
            "prefaceCoveredSourceRefs",
            "appendixOverridesUsed",
            "appendixCoveredSourceRefs",
            "coveredDiagnostics",
            "nonRenderedEvidenceReasons",
            "displayFieldAuthorities",
        ):
            value = note_payload.get(list_field)
            if not isinstance(value, list):
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' missing or invalid '{list_field}'"
                )

        if not all(isinstance(page, int) for page in note_payload["physicalPage"]):
            raise NotesProvenanceError(f"Notes provenance note '{note_key}' has non-integer physicalPage entries")

        full_note_override_used = note_payload.get("fullNoteOverrideUsed")
        if not isinstance(full_note_override_used, bool):
            raise NotesProvenanceError(
                f"Notes provenance note '{note_key}' missing or invalid 'fullNoteOverrideUsed'"
            )

        if render_authority == "direct_workbook":
            direct_notes.add(note_key)
            if full_note_override_used:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' direct_workbook cannot mark fullNoteOverrideUsed"
                )
            if note_payload["fieldOverridesUsed"] or note_payload["rowOverridesUsed"] or note_payload["labelMappingsUsed"]:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' direct_workbook cannot claim override usage"
                )
            if not note_payload["workbookRenderedSourceRanges"]:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' direct_workbook must include rendered source ranges"
                )
        elif render_authority == "hybrid_workbook_preview_override":
            hybrid_notes.add(note_key)
            if full_note_override_used:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' hybrid mode cannot mark fullNoteOverrideUsed"
                )
            if not note_payload["rowOverridesUsed"]:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' hybrid mode must include rowOverridesUsed"
                )
            if not note_payload["workbookRenderedSourceCells"]:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' hybrid mode must include workbookRenderedSourceCells"
                )
        else:
            full_override_notes.add(note_key)
            if not full_note_override_used:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' full override mode must mark fullNoteOverrideUsed"
                )
            if note_payload["workbookRenderedSourceCells"]:
                raise NotesProvenanceError(
                    f"Notes provenance note '{note_key}' full override mode cannot include workbookRenderedSourceCells"
                )

    if direct_notes != DIRECT_WORKBOOK_NOTES:
        raise NotesProvenanceError("Notes provenance direct authority matrix mismatch")
    if hybrid_notes != HYBRID_WORKBOOK_NOTES:
        raise NotesProvenanceError("Notes provenance hybrid authority matrix mismatch")
    if full_override_notes != FULL_NOTE_OVERRIDE_NOTES:
        raise NotesProvenanceError("Notes provenance full-override authority matrix mismatch")
