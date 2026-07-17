from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from balance_sheet_extractor import (  # noqa: E402
    ExtractionError,
    ensure_real_balance_sheet_renderable,
    extract_balance_sheet,
)
from balance_sheet_renderer import REQUIRED_KEYS  # noqa: E402


def _is_numeric_text(value: str) -> bool:
    try:
        Decimal(value)
        return True
    except Exception:
        return False


def _cell_xml(cell: dict[str, object]) -> str:
    value = cell.get("value")
    formula = cell.get("formula")
    force_string = bool(cell.get("force_string", False))
    without_cached_value = bool(cell.get("without_cached_value", False))

    formula_xml = f"<f>{formula}</f>" if formula else ""
    if force_string:
        text = "" if value is None else str(value)
        return f'<c r="{{ref}}" t="inlineStr">{formula_xml}<is><t>{text}</t></is></c>'

    if without_cached_value:
        return f'<c r="{{ref}}">{formula_xml}</c>'

    text = "" if value is None else str(value)
    if not _is_numeric_text(text):
        return f'<c r="{{ref}}" t="inlineStr">{formula_xml}<is><t>{text}</t></is></c>'
    return f'<c r="{{ref}}">{formula_xml}<v>{text}</v></c>'


def _sheet_xml(rows: dict[int, dict[str, dict[str, object]]]) -> str:
    row_xml_parts: list[str] = []
    for row_idx in sorted(rows):
        cells_xml: list[str] = []
        for col in sorted(rows[row_idx]):
            cell = rows[row_idx][col]
            template = _cell_xml(cell)
            cells_xml.append(template.replace("{ref}", f"{col}{row_idx}"))
        row_xml_parts.append(f'<row r="{row_idx}">' + "".join(cells_xml) + "</row>")

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        + "".join(row_xml_parts)
        + "</sheetData></worksheet>"
    )


def _base_rr_rows() -> dict[int, dict[str, dict[str, object]]]:
    return {
        44: {
            "A": {"value": "Årets resultat", "force_string": True},
            "D": {"value": "33.00"},
        }
    }


def _base_br_rows() -> dict[int, dict[str, dict[str, object]]]:
    return {
        12: {
            "G": {"value": "1220", "force_string": True},
            "H": {"value": "Inventarier och verktyg", "force_string": True},
            "I": {"value": "1200"},
        },
        15: {
            "A": {"value": "1070", "force_string": True},
            "B": {"value": "Goodwill", "force_string": True},
            "C": {"value": "999"},
            "D": {"value": "1"},
            "E": {"value": "10", "formula": "SUM(C15:D15)"},
        },
        18: {
            "A": {"value": "1299", "force_string": True},
            "B": {"value": "Materiella anläggningstillgångar", "force_string": True},
            "E": {"value": "20"},
        },
        19: {
            "A": {"value": "1310", "force_string": True},
            "B": {"value": "Participations in group companies", "force_string": True},
            "E": {"value": "", "force_string": True},
        },
        20: {
            "A": {"value": "1350", "force_string": True},
            "B": {"value": "Participations and securities in other companies", "force_string": True},
            "E": {"value": "30"},
        },
        22: {
            "A": {"value": "1380", "force_string": True},
            "B": {"value": "Other long-term receivables", "force_string": True},
            "E": {"value": "40"},
        },
        23: {
            "A": {"value": "1399", "force_string": True},
            "B": {"value": "Finansiella anläggningstillgångar", "force_string": True},
            "E": {"value": "", "force_string": True},
        },
        24: {
            "A": {"value": "1FA", "force_string": True},
            "B": {"value": "Summa anläggningstillgångar", "force_string": True},
            "E": {"value": "100"},
        },
        26: {
            "A": {"value": "1499", "force_string": True},
            "B": {"value": "Upparbetad men ej fakturerad intäkt", "force_string": True},
            "E": {"value": "50"},
        },
        27: {
            "A": {"value": "I1599EX", "force_string": True},
            "B": {"value": "Kundfordringar", "force_string": True},
            "E": {"value": "60"},
        },
        28: {
            "A": {"value": "I15991699", "force_string": True},
            "B": {"value": "Fordringar hos koncernbolag", "force_string": True},
            "E": {"value": "70", "formula": "SUM(C28:D28)"},
        },
        30: {
            "A": {"value": "I16EXT", "force_string": True},
            "B": {"value": "Övriga fordringar", "force_string": True},
            "E": {"value": "80"},
        },
        31: {
            "A": {"value": "1799", "force_string": True},
            "B": {"value": "Förutbetalda kostnader och upplupna intäkter", "force_string": True},
            "E": {"value": "90"},
        },
        32: {
            "A": {"value": "I1CA", "force_string": True},
            "B": {"value": " ", "force_string": True},
            "E": {"value": "300", "formula": "SUM(E26:E31)"},
        },
        34: {
            "A": {"value": "1999", "force_string": True},
            "B": {"value": "Kassa och Bank", "force_string": True},
            "C": {"value": "0"},
            "E": {"value": "", "force_string": True},
        },
        35: {
            "A": {"value": "1CA", "force_string": True},
            "B": {"value": "Summa omsättningstillgångar", "force_string": True},
            "E": {"value": "350", "formula": "+E32+E34"},
        },
        36: {
            "A": {"value": "1TA", "force_string": True},
            "B": {"value": "Summa tillgångar", "force_string": True},
            "E": {"value": "450", "formula": "+E35+E24"},
        },
        37: {
            "G": {"value": "2099", "force_string": True},
            "H": {"value": "Årets resultat", "force_string": True},
            "I": {"value": "33.00"},
        },
        43: {
            "A": {"value": "20SETOT", "force_string": True},
            "B": {"value": "Summa eget kapital", "force_string": True},
            "E": {"value": "200"},
        },
        44: {
            "A": {"value": "20UE", "force_string": True},
            "B": {"value": "Annat eget kapital inkl periodens resultat (fritt)", "force_string": True},
            "E": {"value": "210"},
        },
        50: {
            "A": {"value": "2420", "force_string": True},
            "B": {"value": "Förskott från kunder", "force_string": True},
            "E": {"value": "11"},
        },
        51: {
            "A": {"value": "2440", "force_string": True},
            "B": {"value": "Leverantörsskulder", "force_string": True},
            "E": {"value": "12"},
        },
        52: {
            "A": {"value": "I2499INT", "force_string": True},
            "B": {"value": "Skulder till koncernbolag", "force_string": True},
            "E": {"value": "13", "formula": "SUM(C52:D52)"},
        },
        53: {
            "A": {"value": "2599", "force_string": True},
            "B": {"value": "Skatteskulder", "force_string": True},
            "E": {"value": "14"},
        },
        54: {
            "A": {"value": "I2OTHCL", "force_string": True},
            "B": {"value": "Övriga kortfristiga skulder", "force_string": True},
            "E": {"value": "15"},
        },
        55: {
            "A": {"value": "2999", "force_string": True},
            "B": {"value": "Upplupna kostnader och förutbetalda intäkter", "force_string": True},
            "E": {"value": "16"},
        },
        56: {
            "A": {"value": "2CL", "force_string": True},
            "B": {"value": " ", "force_string": True},
            "E": {"value": "250", "formula": "SUM(E50:E55)"},
        },
        57: {
            "A": {"value": "2TLE", "force_string": True},
            "B": {"value": "Summa eget kapital och skulder", "force_string": True},
            "E": {"value": "450", "formula": "+E56+E43"},
        },
    }


def _base_eq_rows() -> dict[int, dict[str, dict[str, object]]]:
    return {
        10: {
            "A": {"value": "208101", "force_string": True},
            "B": {"value": "OB Share capital", "force_string": True},
            "D": {"value": "100"},
        },
        17: {
            "A": {"value": "2081", "force_string": True},
            "B": {"value": "Share capital", "force_string": True},
            "D": {"value": "100"},
        },
        19: {
            "A": {"value": "2081_IMPD", "force_string": True},
            "B": {"value": "Difference:Share capital", "force_string": True},
            "D": {"value": "100"},
        },
        51: {
            "A": {"value": "208601", "force_string": True},
            "B": {"value": "OB Statutory reserve", "force_string": True},
            "D": {"value": "50"},
        },
        57: {
            "A": {"value": "2086", "force_string": True},
            "B": {"value": "Statutory reserve", "force_string": True},
            "D": {"value": "50"},
        },
        59: {
            "A": {"value": "2086_IMPD", "force_string": True},
            "B": {"value": "Difference:Statutory reserve", "force_string": True},
            "D": {"value": "50"},
        },
        71: {
            "A": {"value": "209101", "force_string": True},
            "B": {"value": "OB Retained profit", "force_string": True},
            "D": {"value": "180"},
        },
        72: {
            "A": {"value": "209102", "force_string": True},
            "B": {"value": "Profit or loss carried forward", "force_string": True},
            "D": {"value": "20"},
        },
        88: {
            "A": {"value": "2091", "force_string": True},
            "B": {"value": "Retained profit", "force_string": True},
            "D": {"value": "200"},
        },
        90: {
            "A": {"value": "2091_IMPD", "force_string": True},
            "B": {"value": "Difference:Retained profit", "force_string": True},
            "D": {"value": "200"},
        },
        92: {
            "A": {"value": "2099", "force_string": True},
            "B": {"value": "Net income", "force_string": True},
        },
        94: {
            "A": {"value": "20SE", "force_string": True},
            "B": {"value": "TOTAL EQUITY", "force_string": True},
            "D": {"value": "199"},
        },
    }


def _create_test_workbook(
    path: Path,
    *,
    rr_rows: dict[int, dict[str, dict[str, object]]] | None = None,
    br_rows: dict[int, dict[str, dict[str, object]]] | None = None,
    eq_rows: dict[int, dict[str, dict[str, object]]] | None = None,
    include_rr_sheet: bool = True,
    include_br_sheet: bool = True,
    include_eq_sheet: bool = True,
) -> None:
    rr = copy.deepcopy(_base_rr_rows()) if rr_rows is None else rr_rows
    br = copy.deepcopy(_base_br_rows()) if br_rows is None else br_rows
    eq = copy.deepcopy(_base_eq_rows()) if eq_rows is None else eq_rows

    sheets: list[tuple[str, str, str]] = []
    sheet_xmls: list[str] = []

    if include_rr_sheet:
        sheets.append(("RR sammanställning", "1", "rId1"))
        sheet_xmls.append(_sheet_xml(rr))
    if include_br_sheet:
        sheets.append(("BR Sammanställning", str(len(sheets) + 1), f"rId{len(sheets) + 1}"))
        sheet_xmls.append(_sheet_xml(br))
    if include_eq_sheet:
        sheets.append(("Eget kapital", str(len(sheets) + 1), f"rId{len(sheets) + 1}"))
        sheet_xmls.append(_sheet_xml(eq))

    workbook_sheets = "".join(
        f'<sheet name="{name}" sheetId="{sheet_id}" r:id="{rid}"/>' for name, sheet_id, rid in sheets
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets></workbook>"
    )

    rels_entries = []
    content_entries = []
    for idx, (_, _, rid) in enumerate(sheets, start=1):
        rels_entries.append(
            f'<Relationship Id="{rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
        )
        content_entries.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels_entries)
        + "</Relationships>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(content_entries)
        + "</Types>"
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdWorkbook" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        for idx, sheet_xml in enumerate(sheet_xmls, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml)


class BalanceSheetExtractionTests(unittest.TestCase):
    def _run_extraction(
        self,
        *,
        rr_rows: dict[int, dict[str, dict[str, object]]] | None = None,
        br_rows: dict[int, dict[str, dict[str, object]]] | None = None,
        eq_rows: dict[int, dict[str, dict[str, object]]] | None = None,
        include_rr_sheet: bool = True,
        include_br_sheet: bool = True,
        include_eq_sheet: bool = True,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wb_path = tmp_path / "test.xlsx"
            out_path = tmp_path / "out.json"
            _create_test_workbook(
                wb_path,
                rr_rows=rr_rows,
                br_rows=br_rows,
                eq_rows=eq_rows,
                include_rr_sheet=include_rr_sheet,
                include_br_sheet=include_br_sheet,
                include_eq_sheet=include_eq_sheet,
            )
            payload = extract_balance_sheet(wb_path, out_path)
            self.assertTrue(out_path.exists())
            from_file = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], from_file["status"])
            return payload

    def test_missing_workbook_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            with self.assertRaises(ExtractionError):
                extract_balance_sheet(Path(tmp) / "missing.xlsx", out_path)

    def test_corrupt_xlsx_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wb_path = Path(tmp) / "bad.xlsx"
            wb_path.write_text("not-a-zip", encoding="utf-8")
            out_path = Path(tmp) / "out.json"
            with self.assertRaises(ExtractionError):
                extract_balance_sheet(wb_path, out_path)

    def test_missing_br_sheet_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wb_path = Path(tmp) / "test.xlsx"
            out_path = Path(tmp) / "out.json"
            _create_test_workbook(wb_path, include_br_sheet=False)
            with self.assertRaises(ExtractionError):
                extract_balance_sheet(wb_path, out_path)

    def test_missing_equity_sheet_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wb_path = Path(tmp) / "test.xlsx"
            out_path = Path(tmp) / "out.json"
            _create_test_workbook(wb_path, include_eq_sheet=False)
            with self.assertRaises(ExtractionError):
                extract_balance_sheet(wb_path, out_path)

    def test_duplicate_br_anchor_marks_line_unresolved(self) -> None:
        br_rows = copy.deepcopy(_base_br_rows())
        br_rows[60] = {
            "A": {"value": "1TA", "force_string": True},
            "B": {"value": "Summa tillgångar", "force_string": True},
            "E": {"value": "450"},
        }
        payload = self._run_extraction(br_rows=br_rows)
        self.assertEqual(payload["lines"]["totalAssets"]["status"], "unresolved")

    def test_duplicate_canonical_equity_account_marks_unresolved(self) -> None:
        eq_rows = copy.deepcopy(_base_eq_rows())
        eq_rows[58] = {
            "A": {"value": "2086", "force_string": True},
            "B": {"value": "Statutory reserve", "force_string": True},
            "D": {"value": "50"},
        }
        payload = self._run_extraction(eq_rows=eq_rows)
        self.assertEqual(payload["lines"]["reserveFund"]["status"], "unresolved")
        diag_codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("EQUITY_CANONICAL_DUPLICATE", diag_codes)

    def test_formula_without_cached_value_is_unresolved(self) -> None:
        br_rows = copy.deepcopy(_base_br_rows())
        br_rows[27]["E"] = {"formula": "SUM(C27:D27)", "without_cached_value": True}
        payload = self._run_extraction(br_rows=br_rows)
        self.assertEqual(payload["lines"]["tradeReceivables"]["status"], "unresolved")
        self.assertIsNone(payload["lines"]["tradeReceivables"]["value"])

    def test_canonical_equity_row_moved_to_different_row(self) -> None:
        eq_rows = copy.deepcopy(_base_eq_rows())
        eq_rows[188] = eq_rows.pop(88)
        payload = self._run_extraction(eq_rows=eq_rows)
        self.assertEqual(payload["lines"]["retainedEarnings"]["value"], "200")
        self.assertEqual(payload["lines"]["retainedEarnings"]["trace"]["valueCell"], "D188")

    def test_canonical_br_row_moved_to_different_row(self) -> None:
        br_rows = copy.deepcopy(_base_br_rows())
        br_rows[143] = br_rows.pop(43)
        payload = self._run_extraction(br_rows=br_rows)
        self.assertEqual(payload["lines"]["totalEquity"]["value"], "200")
        self.assertEqual(payload["lines"]["totalEquity"]["trace"]["valueCell"], "E143")

    def test_reads_br_values_from_column_e_only(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["lines"]["goodwill"]["value"], "10")
        self.assertEqual(payload["lines"]["goodwill"]["trace"]["valueCell"], "E15")

    def test_does_not_fallback_to_c_or_d_for_blank_e(self) -> None:
        payload = self._run_extraction()
        self.assertIsNone(payload["lines"]["cashAndBank"]["value"])
        self.assertEqual(payload["lines"]["cashAndBank"]["status"], "unresolved")

    def test_blank_required_e_value_is_unresolved_not_zero(self) -> None:
        payload = self._run_extraction()
        self.assertIsNone(payload["lines"]["sharesInGroupCompanies"]["value"])
        self.assertEqual(payload["lines"]["sharesInGroupCompanies"]["status"], "unresolved")

    def test_maps_canonical_equity_account_codes(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["lines"]["shareCapital"]["value"], "100")
        self.assertEqual(payload["lines"]["reserveFund"]["value"], "50")
        self.assertEqual(payload["lines"]["retainedEarnings"]["value"], "200")

    def test_excludes_ob_movement_import_difference_from_aggregation(self) -> None:
        payload = self._run_extraction()
        info_codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("EQUITY_DOUBLE_COUNT_PROTECTION", info_codes)
        self.assertEqual(payload["lines"]["shareCapital"]["value"], "100")

    def test_blank_2099_produces_unresolved_and_review_required(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["status"], "review_required")
        self.assertEqual(payload["lines"]["profitForYear"]["status"], "unresolved")
        self.assertIsNone(payload["lines"]["profitForYear"]["value"])

    def test_non_zero_unknown_canonical_equity_account_produces_unmapped(self) -> None:
        eq_rows = copy.deepcopy(_base_eq_rows())
        eq_rows[27] = {
            "A": {"value": "2082", "force_string": True},
            "B": {"value": "Other contributed equity", "force_string": True},
            "D": {"value": "5"},
        }
        payload = self._run_extraction(eq_rows=eq_rows)
        unmapped = payload["equity"]["unmappedAccounts"]
        self.assertEqual(len(unmapped), 1)
        self.assertEqual(unmapped[0]["accountCode"], "2082")
        self.assertEqual(unmapped[0]["value"], "5")

    def test_br_e43_is_authoritative_total_equity(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["lines"]["totalEquity"]["value"], "200")
        self.assertEqual(payload["lines"]["totalEquity"]["trace"]["valueCell"], "E43")

    def test_equity_sheet_total_stored_only_as_reconciliation_trace(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["reconciliation"]["equitySheetTotal"], "199")
        self.assertEqual(payload["reconciliation"]["difference"], "1")

    def test_equity_total_mismatch_produces_review_required(self) -> None:
        payload = self._run_extraction()
        diag_codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("TOTAL_EQUITY_RECONCILIATION_MISMATCH", diag_codes)
        self.assertEqual(payload["status"], "review_required")

    def test_unresolved_extraction_cannot_be_rendered_as_real_pdf(self) -> None:
        payload = self._run_extraction()
        with self.assertRaises(ExtractionError):
            ensure_real_balance_sheet_renderable(payload)

    def test_total_restricted_equity_always_exists(self) -> None:
        payload = self._run_extraction()
        self.assertIn("totalRestrictedEquity", payload["lines"])

    def test_total_unrestricted_equity_always_exists(self) -> None:
        payload = self._run_extraction()
        self.assertIn("totalUnrestrictedEquity", payload["lines"])

    def test_total_restricted_equity_uses_configured_canonical_accounts(self) -> None:
        payload = self._run_extraction()
        line = payload["lines"]["totalRestrictedEquity"]
        self.assertEqual(line["status"], "resolved")
        self.assertEqual(line["value"], "150")
        component_codes = [c["accountCode"] for c in line["trace"]["components"]]
        self.assertEqual(component_codes, ["2081", "2086"])

    def test_blank_2099_is_never_treated_as_zero_in_component_derivation(self) -> None:
        br_rows = copy.deepcopy(_base_br_rows())
        br_rows.pop(44)
        payload = self._run_extraction(br_rows=br_rows)
        self.assertEqual(payload["lines"]["profitForYear"]["status"], "unresolved")
        self.assertEqual(payload["lines"]["totalUnrestrictedEquity"]["status"], "unresolved")
        self.assertIsNone(payload["lines"]["totalUnrestrictedEquity"]["value"])

    def test_br_20ue_can_resolve_unrestricted_while_profit_for_year_unresolved(self) -> None:
        payload = self._run_extraction()
        self.assertEqual(payload["lines"]["profitForYear"]["status"], "unresolved")
        self.assertEqual(payload["lines"]["totalUnrestrictedEquity"]["status"], "resolved")
        self.assertEqual(payload["lines"]["totalUnrestrictedEquity"]["value"], "210")
        self.assertEqual(payload["lines"]["totalUnrestrictedEquity"]["trace"]["source"], "authoritative BR Output")

    def test_all_renderer_required_keys_exist(self) -> None:
        payload = self._run_extraction()
        missing = [key for key in REQUIRED_KEYS if key not in payload["lines"]]
        self.assertEqual(missing, [])

    def test_decimal_values_serialize_as_strings(self) -> None:
        payload = self._run_extraction()
        self.assertIsInstance(payload["lines"]["goodwill"]["value"], str)
        self.assertIsInstance(payload["reconciliation"]["brTotalEquity"], str)


if __name__ == "__main__":
    unittest.main()
