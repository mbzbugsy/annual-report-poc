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
    style: str = "normal"  # normal|subtotal|total|subsection|section-with-note


REQUIRED_KEYS = [
    "goodwill",
    "machineryTechnicalInstallations",
    "equipmentToolsInstallations",
    "sharesInGroupCompanies",
    "otherLongTermSecurities",
    "otherLongTermReceivables",
    "totalFinancialFixedAssets",
    "totalFixedAssets",
    "tradeReceivables",
    "receivablesFromGroupCompanies",
    "otherReceivables",
    "accruedUnbilledRevenue",
    "prepaidExpensesAccruedIncome",
    "totalShortTermReceivables",
    "cashAndBank",
    "totalCurrentAssets",
    "totalAssets",
    "shareCapital",
    "reserveFund",
    "totalRestrictedEquity",
    "retainedEarnings",
    "profitForYear",
    "totalUnrestrictedEquity",
    "totalEquity",
    "advancesFromCustomers",
    "tradePayables",
    "liabilitiesToGroupCompanies",
    "currentTaxLiabilities",
    "otherLiabilities",
    "accruedExpensesDeferredIncome",
    "totalShortTermLiabilities",
    "totalEquityAndLiabilities",
]


ASSET_ROWS: List[StatementRow] = [
    StatementRow("section", display_label="TILLGÅNGAR"),
    StatementRow("section", display_label="Anläggningstillgångar"),
    StatementRow("section", display_label="Immateriella anläggningstillgångar", style="subsection"),
    StatementRow("line", "goodwill", "Goodwill", "11", indent_mm=2),
    StatementRow("section", display_label="Materiella anläggningstillgångar", style="subsection"),
    StatementRow("line", "machineryTechnicalInstallations", "Maskiner och andra tekniska anläggningar", "", indent_mm=2),
    StatementRow("line", "equipmentToolsInstallations", "Inventarier, verktyg och installationer", "12", indent_mm=2),
    StatementRow("section", display_label="Finansiella anläggningstillgångar", style="subsection"),
    StatementRow("line", "sharesInGroupCompanies", "Andelar i koncernföretag", "13, 14", indent_mm=2),
    StatementRow("line", "otherLongTermSecurities", "Andra långfristiga värdepappersinnehav", "15", indent_mm=2),
    StatementRow("line", "otherLongTermReceivables", "Andra långfristiga fordringar", "16", indent_mm=2),
    StatementRow("line", "totalFinancialFixedAssets", "", "", style="subtotal"),
    StatementRow("line", "totalFixedAssets", "Summa anläggningstillgångar", "", style="total"),
    StatementRow("space"),
    StatementRow("section", display_label="Omsättningstillgångar"),
    StatementRow("section", display_label="Kortfristiga fordringar", style="subsection"),
    StatementRow("line", "tradeReceivables", "Kundfordringar", "", indent_mm=2),
    StatementRow("line", "receivablesFromGroupCompanies", "Fordringar hos koncernföretag", "", indent_mm=2),
    StatementRow("line", "otherReceivables", "Övriga fordringar", "17", indent_mm=2),
    StatementRow("line", "accruedUnbilledRevenue", "Upparbetad men ej fakturerad intäkt", "18", indent_mm=2),
    StatementRow("line", "prepaidExpensesAccruedIncome", "Förutbetalda kostnader och upplupna intäkter", "19", indent_mm=2),
    StatementRow("line", "totalShortTermReceivables", "", "", style="subtotal"),
    StatementRow("line", "cashAndBank", "Kassa och bank", "", indent_mm=2, style="subsection"),
    StatementRow("line", "totalCurrentAssets", "Summa omsättningstillgångar", "", style="total"),
    StatementRow("space"),
    StatementRow("line", "totalAssets", "SUMMA TILLGÅNGAR", "", style="total"),
]


EQUITY_LIABILITIES_ROWS: List[StatementRow] = [
    StatementRow("section", display_label="EGET KAPITAL OCH SKULDER"),
    StatementRow("section", display_label="Eget kapital", note="20, 21", style="section-with-note"),
    StatementRow("section", display_label="Bundet eget kapital", style="subsection"),
    StatementRow("line", "shareCapital", "Aktiekapital", "", indent_mm=2),
    StatementRow("line", "reserveFund", "Reservfond", "", indent_mm=2),
    StatementRow("line", "totalRestrictedEquity", "", "", style="subtotal"),
    StatementRow("space"),
    StatementRow("section", display_label="Fritt eget kapital", style="subsection"),
    StatementRow("line", "retainedEarnings", "Balanserad vinst eller förlust", "", indent_mm=2),
    StatementRow("line", "profitForYear", "Årets resultat", "", indent_mm=2),
    StatementRow("line", "totalUnrestrictedEquity", "", "", style="subtotal"),
    StatementRow("line", "totalEquity", "Summa eget kapital", "", style="total"),
    StatementRow("space"),
    StatementRow("section", display_label="Kortfristiga skulder"),
    StatementRow("line", "advancesFromCustomers", "Förskott från kunder", "", indent_mm=2),
    StatementRow("line", "tradePayables", "Leverantörsskulder", "", indent_mm=2),
    StatementRow("line", "liabilitiesToGroupCompanies", "Skulder till koncernföretag", "22", indent_mm=2),
    StatementRow("line", "currentTaxLiabilities", "Aktuella skatteskulder", "", indent_mm=2),
    StatementRow("line", "otherLiabilities", "Övriga skulder", "", indent_mm=2),
    StatementRow("line", "accruedExpensesDeferredIncome", "Upplupna kostnader och förutbetalda intäkter", "23", indent_mm=2),
    StatementRow("line", "totalShortTermLiabilities", "Summa kortfristiga skulder", "", style="total"),
    StatementRow("space"),
    StatementRow("line", "totalEquityAndLiabilities", "SUMMA EGET KAPITAL OCH SKULDER", "", style="total"),
]

ASSETS_PAGE_INDICATOR = "6 (19)"
EQUITY_LIABILITIES_PAGE_INDICATOR = "7 (19)"


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


def _parse_decimal_or_fail(key: str, value: object, fixture_name: str) -> Decimal:
    if not isinstance(value, str):
        raise RenderError(
            f"Invalid decimal value for '{key}' in {fixture_name}: expected string, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise RenderError(f"Invalid decimal value for '{key}' in {fixture_name}: {value!r}") from exc


def format_amount(value: Decimal) -> str:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    abs_text = f"{abs(rounded):,}".replace(",", " ")
    return f"-{abs_text}" if rounded < 0 else abs_text


def _render_period_label(label: str) -> str:
    lines = [escape_latex(part.strip()) for part in label.splitlines() if part.strip()]
    if not lines:
        lines = [escape_latex("N/A")]
    return " \\\\ ".join(lines)


def _single_balance_date_label(raw_label: str, source_name: str) -> str:
    lines = [part.strip() for part in raw_label.splitlines() if part.strip()]
    if not lines:
        raise RenderError(f"Missing balance-date label in {source_name}")

    # If a range is provided, use the end date for point-in-time balance-sheet headings.
    candidate = lines[-1].lstrip("-").strip()
    if not candidate:
        raise RenderError(f"Invalid balance-date label in {source_name}: {raw_label!r}")
    return candidate


def _load_current_fixture(json_path: Path) -> Dict[str, object]:
    if not json_path.exists():
        raise RenderError(f"Input JSON does not exist: {json_path}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid JSON file: {json_path}") from exc

    lines = data.get("lines")
    if not isinstance(lines, dict):
        raise RenderError("Missing 'lines' object in current-period balance-sheet fixture")

    balance_date_label = data.get("balanceDateLabel")
    if balance_date_label is not None:
        if not isinstance(balance_date_label, str) or not balance_date_label.strip():
            raise RenderError("Current-period fixture field 'balanceDateLabel' must be a non-empty string when provided")
        balance_date_label = balance_date_label.strip()

    for key in REQUIRED_KEYS:
        if key not in lines:
            raise RenderError(f"Missing required balance-sheet line in current-period fixture: {key}")

    return {
        "lines": lines,
        "balanceDateLabel": balance_date_label,
    }


def _load_previous_fixture(previous_period_fixture_path: Path) -> Dict[str, object]:
    if not previous_period_fixture_path.exists():
        raise RenderError(f"Previous-period fixture does not exist: {previous_period_fixture_path}")

    try:
        raw = json.loads(previous_period_fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Invalid previous-period fixture JSON: {previous_period_fixture_path}") from exc

    values = raw.get("values")
    if not isinstance(values, dict):
        raise RenderError("Previous-period fixture must contain an object field 'values'")

    for key in REQUIRED_KEYS:
        if key not in values:
            raise RenderError(f"Missing required balance-sheet line in previous-period fixture: {key}")

    period_label = raw.get("periodLabel")
    if not isinstance(period_label, str) or not period_label.strip():
        period_label = None

    balance_date_label = raw.get("balanceDateLabel")
    if balance_date_label is not None:
        if not isinstance(balance_date_label, str) or not balance_date_label.strip():
            raise RenderError("Previous-period fixture field 'balanceDateLabel' must be a non-empty string when provided")
        balance_date_label = balance_date_label.strip()

    return {
        "balanceDateLabel": balance_date_label,
        "periodLabel": period_label,
        "values": values,
    }


def _line_value(lines: Dict[str, Dict[str, object]], key: str) -> Decimal:
    entry = lines.get(key)
    if not isinstance(entry, dict):
        raise RenderError(f"Line '{key}' must be an object in current-period fixture")
    return _parse_decimal_or_fail(key, entry.get("value"), "current-period fixture")


def _previous_value(values: Dict[str, object], key: str) -> Decimal:
    return _parse_decimal_or_fail(key, values.get(key), "previous-period fixture")


def _validate_balanced(current: Dict[str, Decimal], previous: Dict[str, Decimal]) -> None:
    if current["totalAssets"] != current["totalEquityAndLiabilities"]:
        raise RenderError(
            "Current-period fixture is not balanced: totalAssets differs from totalEquityAndLiabilities"
        )

    if previous["totalAssets"] != previous["totalEquityAndLiabilities"]:
        raise RenderError(
            "Previous-period fixture is not balanced: totalAssets differs from totalEquityAndLiabilities"
        )


def _render_rows(
    rows: List[StatementRow],
    current_values: Dict[str, Decimal],
    previous_values: Dict[str, Decimal],
) -> List[str]:
    rendered_rows: List[str] = []
    for row in rows:
        if row.kind == "space":
            rendered_rows.append("\\FinancialStatementSpaceRow")
            continue

        if row.kind == "section":
            if row.style == "subsection":
                rendered_rows.append(
                    f"\\FinancialStatementSubsectionRow{{{escape_latex(row.display_label)}}}"
                )
            elif row.style == "section-with-note":
                rendered_rows.append(
                    f"\\FinancialStatementSectionRowWithNote{{{escape_latex(row.display_label)}}}{{{escape_latex(row.note)}}}"
                )
            else:
                rendered_rows.append(
                    f"\\FinancialStatementSectionRow{{{escape_latex(row.display_label)}}}"
                )
            continue

        current_amount = format_amount(current_values[row.key])
        previous_amount = format_amount(previous_values[row.key])
        label = escape_latex(row.display_label)
        if row.indent_mm > 0:
            label = f"\\hspace*{{{row.indent_mm}mm}}{label}"
        if row.style == "subsection":
            label = f"\\textit{{{label}}}"
        note = escape_latex(row.note)

        if row.style == "total":
            if row.key in {"totalAssets", "totalEquityAndLiabilities"}:
                rendered_rows.append("\\FinancialStatementPreFinalTotalSpace")
            rendered_rows.append(
                f"\\FinancialStatementTotalRow{{{label}}}{{{note}}}{{{current_amount}}}{{{previous_amount}}}"
            )
        elif row.style == "subtotal":
            rendered_rows.append(
                f"\\FinancialStatementSubtotalRow{{{label}}}{{{note}}}{{{current_amount}}}{{{previous_amount}}}"
            )
        else:
            rendered_rows.append(
                f"\\FinancialStatementNormalRow{{{label}}}{{{note}}}{{{current_amount}}}{{{previous_amount}}}"
            )

    return rendered_rows


def render_balance_sheet_tex(
    json_path: Path,
    output_path: Path,
    previous_period_fixture_path: Path,
    metadata_path: Optional[Path] = None,
) -> str:
    metadata = load_report_metadata(metadata_path)
    current_fixture = _load_current_fixture(json_path)
    lines_raw = current_fixture["lines"]
    if not isinstance(lines_raw, dict):
        raise RenderError("Current-period fixture field 'lines' must be an object")
    lines: Dict[str, Dict[str, object]] = lines_raw

    previous_fixture = _load_previous_fixture(previous_period_fixture_path)
    previous_values_raw = previous_fixture["values"]
    if not isinstance(previous_values_raw, dict):
        raise RenderError("Previous-period fixture field 'values' must be an object")

    current_values: Dict[str, Decimal] = {key: _line_value(lines, key) for key in REQUIRED_KEYS}
    previous_values: Dict[str, Decimal] = {key: _previous_value(previous_values_raw, key) for key in REQUIRED_KEYS}

    _validate_balanced(current_values, previous_values)

    current_balance_date_label_raw = current_fixture.get("balanceDateLabel")
    if not isinstance(current_balance_date_label_raw, str) or not current_balance_date_label_raw.strip():
        current_balance_date_label_raw = metadata.current_reporting_period
    current_balance_date_label = _single_balance_date_label(current_balance_date_label_raw, "current-period balance-sheet label")

    previous_balance_date_label_raw = previous_fixture.get("balanceDateLabel")
    if not isinstance(previous_balance_date_label_raw, str) or not previous_balance_date_label_raw.strip():
        previous_period_label = previous_fixture.get("periodLabel")
        if isinstance(previous_period_label, str) and previous_period_label.strip():
            previous_balance_date_label_raw = previous_period_label
        else:
            previous_balance_date_label_raw = metadata.previous_reporting_period
    previous_balance_date_label = _single_balance_date_label(previous_balance_date_label_raw, "previous-period balance-sheet label")

    assets_rows = _render_rows(ASSET_ROWS, current_values, previous_values)
    equity_rows = _render_rows(EQUITY_LIABILITIES_ROWS, current_values, previous_values)

    tex = "\n".join(
        [
            "% AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.",
            "% Synthetic balance-sheet vertical slice for layout validation only.",
            (
                "\\FinancialStatementBegin"
                f"{{{escape_latex(metadata.company_name)}}}"
                f"{{{escape_latex(metadata.organization_number)}}}"
                "{Balansräkning}"
                f"{{{_render_period_label(current_balance_date_label)}}}"
                f"{{{_render_period_label(previous_balance_date_label)}}}"
                f"{{{escape_latex(ASSETS_PAGE_INDICATOR)}}}"
            ),
            *assets_rows,
            "\\FinancialStatementEnd",
            "% Explicit statement boundary between assets and equity/liabilities pages.",
            (
                "\\FinancialStatementBeginContinuation"
                f"{{{escape_latex(metadata.company_name)}}}"
                f"{{{escape_latex(metadata.organization_number)}}}"
                f"{{{_render_period_label(current_balance_date_label)}}}"
                f"{{{_render_period_label(previous_balance_date_label)}}}"
                f"{{{escape_latex(EQUITY_LIABILITIES_PAGE_INDICATOR)}}}"
            ),
            *equity_rows,
            "\\FinancialStatementEnd",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tex, encoding="utf-8")
    return tex
