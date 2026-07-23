from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class ManagementReportProvenanceError(ValueError):
    pass


def encode_canonical_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def write_provenance_bytes(path: Path, payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ManagementReportProvenanceError("Management report provenance payload must be an object")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_canonical_json(payload))
