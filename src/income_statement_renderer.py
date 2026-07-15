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
    indent_mm: int = 0
    style: str = "normal"  # normal|subtotal|total


REQUIRED_CURRENT_KEYS = [
    "revenue",
    "otherOperatingIncome",
    "totalIncome",
    "operatingResult",
    "resultAfterFinancialItems",
    "profitBeforeTax",
    "taxForYear",
    "netResult",
]

LAYOUT_ROWS: List[StatementRow] = [
    StatementRow("section", display_label="Rörelsens intäkter", style="total"),
    StatementRow("line", "revenue", "Nettoomsättning", "2, 27"),
    StatementRow("line", "otherOperatingIncome", "Övriga rörelseintäkter", ""),
    StatementRow("line", "totalIncome", "Summa intäkter", "", style="subtotal"),
    StatementRow("space"),
    StatementRow("section", display_label="Rörelsens kostnader", style="total"),
    StatementRow("line", "costOfGoodsAndServices", "Kostnad för sålda varor och tjänster", "27"),
    StatementRow("line", "otherExternalCosts", "Övriga externa kostnader", "3, 4"),
    StatementRow("line", "personnelCosts", "Personalkostnader", "5"),
    StatementRow(
        "line",
        "depreciationAndAmortization",
        "Avskrivningar och nedskrivningar av materiella och immateriella anläggningstillgångar",
        "",
    ),
    StatementRow("line", "otherOperatingCosts", "Övriga rörelsekostnader", "6"),
    StatementRow("line", "totalOperatingCosts", "", "", style="subtotal"),
    StatementRow("line", "operatingResult", "Rörelseresultat", "", style="total"),
    StatementRow("space"),
    StatementRow("section", display_label="Resultat från finansiella poster", style="total"),
    StatementRow("line", "interestIncome", "Övriga ränteintäkter och liknande resultatposter", "7"),
    StatementRow("line", "interestCosts", "Räntekostnader och liknande resultatposter", "8"),
    StatementRow("line", "netFinancialItems", "", "", style="subtotal"),
    StatementRow("line", "resultAfterFinancialItems", "Resultat efter finansiella poster", "", style="total"),
    StatementRow("space"),
    StatementRow("line", "appropriations", "Bokslutsdispositioner", "9"),
    StatementRow("line", "profitBeforeTax", "Resultat före skatt", "", style="total"),
    StatementRow("space"),
    StatementRow("line", "taxForYear", "Skatt på årets resultat", "10"),
    StatementRow("line", "netResult", "Årets resultat", "", style="total"),
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


def _parse_decimal_or_fail(key: str, value: object) -> Decimal:
    if not isinstance(value, str):
        raise RenderError(f"Invalid decimal value for '{key}': expected string, got {type(value).__name__}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RenderError(f"Invalid decimal value for '{key}': {value!r}") from exc


def format_amount(value: Decimal) -> str:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    abs_text = f"{abs(rounded):,}".replace(",", " ")
    return f"-{abs_text}" if rounded < 0 else abs_text


def _optional_decimal(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RenderError(f"Invalid decimal value type in previous-period fixture: {type(value).__name__}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RenderError(f"Invalid decimal value in previous-period fixture: {value!r}") from exc


def _load_lines(json_path: Path) -> Dict[str, Dict[str, object]]:
    if not json_path.exists():
        raise RenderError(f"Input JSON does not exist: {json_path}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid JSON file: {json_path}") from exc

    lines = data.get("lines")
    if not isinstance(lines, dict):
        raise RenderError("Missing 'lines' object in input JSON")

    for key in REQUIRED_CURRENT_KEYS:
        if key not in lines:
            raise RenderError(f"Missing required income-statement line: {key}")

    return lines


def _load_previous_period_fixture(previous_period_fixture_path: Optional[Path]) -> Dict[str, object]:
    if previous_period_fixture_path is None:
        return {"periodLabel": None, "values": {}}

    if not previous_period_fixture_path.exists():
        raise RenderError(f"Previous-period fixture does not exist: {previous_period_fixture_path}")

    try:
        raw = json.loads(previous_period_fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid previous-period fixture JSON: {previous_period_fixture_path}") from exc

    values = raw.get("values")
    if not isinstance(values, dict):
        raise RenderError("Previous-period fixture must contain an object field 'values'")

    period_label = raw.get("periodLabel")
    if not isinstance(period_label, str) or not period_label.strip():
        period_label = None

    return {
        "periodLabel": period_label,
        "values": values,
    }


def _format_optional_amount(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    return format_amount(value)


def _render_period_label(label: str) -> str:
    lines = [escape_latex(part.strip()) for part in label.splitlines() if part.strip()]
    if not lines:
        lines = [escape_latex("N/A")]
    return " \\\\ ".join(lines)


def _line_value(lines: Dict[str, Dict[str, object]], key: str) -> Optional[Decimal]:
    entry = lines.get(key)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise RenderError(f"Line '{key}' must be an object")
    return _parse_decimal_or_fail(key, entry.get("value"))


def render_income_statement_tex(
    json_path: Path,
    output_path: Path,
    previous_period_fixture_path: Optional[Path] = None,
    metadata_path: Optional[Path] = None,
) -> str:
    metadata = load_report_metadata(metadata_path)
    lines = _load_lines(json_path)
    previous_fixture = _load_previous_period_fixture(previous_period_fixture_path)
    previous_values = previous_fixture["values"]
    if not isinstance(previous_values, dict):
        raise RenderError("Previous-period fixture field 'values' must be an object")

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

        current_decimal = _line_value(lines, row.key)
        previous_decimal = _optional_decimal(previous_values.get(row.key))
        if current_decimal is None and previous_decimal is None:
            continue

        current_value = _format_optional_amount(current_decimal)
        previous_value = _format_optional_amount(previous_decimal)

        label = escape_latex(row.display_label)
        if row.indent_mm > 0:
            label = f"\\hspace*{{{row.indent_mm}mm}}{label}"
        note = escape_latex(row.note)

        if row.style == "total":
            if row.key == "netResult":
                rendered_rows.append("\\FinancialStatementPreFinalTotalSpace")
            rendered_rows.append(
                f"\\FinancialStatementTotalRow{{{label}}}{{{note}}}{{{current_value}}}{{{previous_value}}}"
            )
        elif row.style == "subtotal":
            rendered_rows.append(
                f"\\FinancialStatementSubtotalRow{{{label}}}{{{note}}}{{{current_value}}}{{{previous_value}}}"
            )
        else:
            rendered_rows.append(
                f"\\FinancialStatementNormalRow{{{label}}}{{{note}}}{{{current_value}}}{{{previous_value}}}"
            )

    previous_period_label = previous_fixture["periodLabel"]
    if not isinstance(previous_period_label, str) or not previous_period_label.strip():
        previous_period_label = metadata.previous_reporting_period

    tex = "\n".join(
        [
            "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
            (
                "\\FinancialStatementBegin"
                f"{{{escape_latex(metadata.company_name)}}}"
                f"{{{escape_latex(metadata.organization_number)}}}"
                "{Resultaträkning}"
                f"{{{_render_period_label(metadata.current_reporting_period)}}}"
                f"{{{_render_period_label(previous_period_label)}}}"
            ),
            *rendered_rows,
            "\\FinancialStatementEnd",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tex, encoding="utf-8")
    return tex
