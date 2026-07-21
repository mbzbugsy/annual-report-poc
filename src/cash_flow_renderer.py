from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional

from report_metadata import load_report_metadata


class RenderError(Exception):
    pass


@dataclass(frozen=True)
class StatementRow:
    kind: str
    key: str = ""
    display_label: str = ""
    note: str = ""
    style: str = "normal"  # normal|total


REQUIRED_KEYS = [
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

CASH_FLOW_PAGE_INDICATOR = "8 (19)"

LAYOUT_ROWS: List[StatementRow] = [
    StatementRow("section", display_label="Den löpande verksamheten"),
    StatementRow("line", "resultAfterFinancialItems", "Rörelseresultat", "24"),
    StatementRow("line", "nonCashAdjustments", "Justeringar för poster som inte ingår i kassaflödet", "25"),
    StatementRow("line", "incomeTaxPaid", "Betald inkomstskatt"),
    StatementRow(
        "line",
        "operatingCashFlowBeforeWorkingCapital",
        "Kassaflöde från den löpande verksamheten före förändring av rörelsekapital",
        style="total",
    ),
    StatementRow("section", display_label="Kassaflöde från förändring av rörelsekapitalet"),
    StatementRow("line", "changeInShortTermReceivables", "Förändring av kortfristiga fordringar"),
    StatementRow("line", "changeInShortTermLiabilities", "Förändring av kortfristiga skulder"),
    StatementRow("line", "operatingCashFlowTotal", "Kassaflöde från den löpande verksamheten", style="total"),
    StatementRow("space"),
    StatementRow("section", display_label="Investeringsverksamheten"),
    StatementRow(
        "line",
        "intangibleComposedInvestingCashFlow",
        "Försäljning av immateriella anläggningstillgångar",
    ),
    StatementRow("line", "investmentsTangibleAssets", "Investeringar i materiella anläggningstillgångar"),
    StatementRow("line", "investmentsFinancialAssets", "Investeringar i finansiella anläggningstillgångar"),
    StatementRow("line", "investingCashFlowTotal", "Kassaflöde från investeringsverksamheten", style="total"),
    StatementRow("space"),
    StatementRow("line", "netCashFlowForYear", "Årets kassaflöde", style="total"),
    StatementRow("section", display_label="Likvida medel vid årets början"),
    StatementRow("line", "cashAtBeginning", "Likvida medel vid årets början"),
    StatementRow("line", "cashAtEnd", "Likvida medel vid årets slut", "22", style="total"),
]


def escape_latex(text: str) -> str:
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


def format_amount(value: Decimal) -> str:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    abs_text = f"{abs(rounded):,}".replace(",", " ")
    return f"-{abs_text}" if rounded < 0 else abs_text


def _normalize_period_label(value: str) -> str:
    return "\n".join(part.strip() for part in value.splitlines() if part.strip())


def _parse_decimal_or_fail(key: str, period_name: str, value: object) -> Decimal:
    if value is None:
        raise RenderError(f"Missing value for '{key}' ({period_name})")
    if not isinstance(value, str):
        raise RenderError(
            f"Invalid value type for '{key}' ({period_name}): expected string, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RenderError(f"Invalid decimal value for '{key}' ({period_name}): {value!r}") from exc


def _load_payload(json_path: Path) -> Dict[str, object]:
    if not json_path.exists():
        raise RenderError(f"Input JSON does not exist: {json_path}")

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid JSON file: {json_path}") from exc

    if not isinstance(payload, dict):
        raise RenderError("Top-level payload must be a JSON object")

    schema_version = payload.get("schemaVersion")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise RenderError("Missing or invalid 'schemaVersion'")

    if "fixtureType" not in payload and "source" not in payload:
        raise RenderError("Payload must contain either 'fixtureType' or 'source'")

    status = payload.get("status")
    if status != "ok":
        raise RenderError("Cash-flow payload status must be 'ok'")

    period = payload.get("period")
    if not isinstance(period, dict):
        raise RenderError("Missing or invalid 'period' object")

    current_label = period.get("currentPeriodLabel")
    if not isinstance(current_label, str) or not current_label.strip():
        raise RenderError("Missing or blank period.currentPeriodLabel")

    previous_label = period.get("previousPeriodLabel")
    if not isinstance(previous_label, str) or not previous_label.strip():
        raise RenderError("Missing or blank period.previousPeriodLabel")

    lines = payload.get("lines")
    if not isinstance(lines, dict):
        raise RenderError("Missing or invalid 'lines' object")

    for key in REQUIRED_KEYS:
        line = lines.get(key)
        if not isinstance(line, dict):
            raise RenderError(f"Missing required cash-flow line: {key}")

        line_status = line.get("status")
        if line_status is not None and line_status != "resolved":
            raise RenderError(f"Cash-flow line '{key}' has unresolved status: {line_status}")

        _parse_decimal_or_fail(key, "current", line.get("valueCurrent"))
        _parse_decimal_or_fail(key, "previous", line.get("valuePrevious"))

    return payload


def _render_period_label(label: str) -> str:
    lines = [escape_latex(part.strip()) for part in label.splitlines() if part.strip()]
    if not lines:
        lines = [escape_latex("N/A")]
    return " \\\\ ".join(lines)


def _financing_should_display(lines: Dict[str, Dict[str, object]]) -> bool:
    line = lines["financingCashFlowTotal"]
    current = _parse_decimal_or_fail("financingCashFlowTotal", "current", line.get("valueCurrent"))
    previous = _parse_decimal_or_fail("financingCashFlowTotal", "previous", line.get("valuePrevious"))
    return not (current == Decimal("0") and previous == Decimal("0"))


def render_cash_flow_tex(
    json_path: Path,
    output_path: Path,
    metadata_path: Optional[Path] = None,
) -> str:
    payload = _load_payload(json_path)
    metadata = load_report_metadata(metadata_path)

    period = payload["period"]
    if not isinstance(period, dict):
        raise RenderError("Missing or invalid 'period' object")

    current_period = period["currentPeriodLabel"]
    previous_period = period["previousPeriodLabel"]
    if not isinstance(current_period, str) or not isinstance(previous_period, str):
        raise RenderError("Period labels must be strings")

    current_norm = _normalize_period_label(current_period)
    previous_norm = _normalize_period_label(previous_period)
    metadata_current_norm = _normalize_period_label(metadata.current_reporting_period)
    metadata_previous_norm = _normalize_period_label(metadata.previous_reporting_period)

    if current_norm != metadata_current_norm:
        raise RenderError("Payload current period label contradicts report metadata")
    if previous_norm != metadata_previous_norm:
        raise RenderError("Payload previous period label contradicts report metadata")

    lines_obj = payload["lines"]
    if not isinstance(lines_obj, dict):
        raise RenderError("Missing or invalid 'lines' object")
    lines: Dict[str, Dict[str, object]] = lines_obj

    show_financing = _financing_should_display(lines)

    rendered_rows: List[str] = []
    for row in LAYOUT_ROWS:
        if row.kind == "space":
            rendered_rows.append("\\FinancialStatementSpaceRow")
            continue

        if row.kind == "section":
            rendered_rows.append(
                f"\\FinancialStatementSectionRow{{{escape_latex(row.display_label)}}}"
            )
            continue

        if row.key == "cashAtEnd":
            rendered_rows.append("\\FinancialStatementPreFinalTotalSpace")

        line = lines[row.key]
        current_decimal = _parse_decimal_or_fail(row.key, "current", line.get("valueCurrent"))
        previous_decimal = _parse_decimal_or_fail(row.key, "previous", line.get("valuePrevious"))

        current_value = format_amount(current_decimal)
        previous_value = format_amount(previous_decimal)

        label = escape_latex(row.display_label)
        note = escape_latex(row.note)

        if row.style == "total":
            rendered_rows.append(
                f"\\FinancialStatementTotalRow{{{label}}}{{{note}}}{{{current_value}}}{{{previous_value}}}"
            )
        else:
            rendered_rows.append(
                f"\\FinancialStatementNormalRow{{{label}}}{{{note}}}{{{current_value}}}{{{previous_value}}}"
            )

        # financingCashFlowTotal is rendered out-of-band here because the whole
        # financing section is conditional and should be omitted when both values are zero.
        if row.key == "investingCashFlowTotal" and show_financing:
            rendered_rows.append("\\FinancialStatementSpaceRow")
            rendered_rows.append("\\FinancialStatementSectionRow{Finansieringsverksamheten}")
            financing_line = lines["financingCashFlowTotal"]
            financing_current = _parse_decimal_or_fail(
                "financingCashFlowTotal", "current", financing_line.get("valueCurrent")
            )
            financing_previous = _parse_decimal_or_fail(
                "financingCashFlowTotal", "previous", financing_line.get("valuePrevious")
            )
            rendered_rows.append(
                "\\FinancialStatementTotalRow"
                "{Kassaflöde från finansieringsverksamheten}{}"
                f"{{{format_amount(financing_current)}}}{{{format_amount(financing_previous)}}}"
            )
            rendered_rows.append("\\FinancialStatementSpaceRow")

    tex = "\n".join(
        [
            "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
            "% Synthetic cash-flow slice for statement layout validation only.",
            (
                "\\FinancialStatementBegin"
                f"{{{escape_latex(metadata.company_name)}}}"
                f"{{{escape_latex(metadata.organization_number)}}}"
                "{Kassaflödesanalys}"
                f"{{{_render_period_label(current_period)}}}"
                f"{{{_render_period_label(previous_period)}}}"
                f"{{{escape_latex(CASH_FLOW_PAGE_INDICATOR)}}}"
            ),
            *rendered_rows,
            "\\FinancialStatementEnd",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tex, encoding="utf-8")
    return tex
