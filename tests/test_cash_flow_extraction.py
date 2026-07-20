from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cash_flow_extractor import (  # noqa: E402
    ExtractionError,
    REQUIRED_PROPERTIES,
    ensure_real_cash_flow_renderable,
    extract_cash_flow,
)


def _cell_xml(cell: dict[str, object], ref: str) -> str:
    value = cell.get("value")
    formula = cell.get("formula")
    force_string = bool(cell.get("force_string", False))
    without_cached_value = bool(cell.get("without_cached_value", False))

    formula_xml = f"<f>{formula}</f>" if formula else ""
    if force_string:
        text = "" if value is None else str(value)
        return f'<c r="{ref}" t="inlineStr">{formula_xml}<is><t>{text}</t></is></c>'

    if without_cached_value:
        return f'<c r="{ref}">{formula_xml}</c>'

    text = "" if value is None else str(value)
    if text == "":
        return f'<c r="{ref}">{formula_xml}</c>'

    try:
        float(text)
    except Exception:
        return f'<c r="{ref}" t="inlineStr">{formula_xml}<is><t>{text}</t></is></c>'

    return f'<c r="{ref}">{formula_xml}<v>{text}</v></c>'


def _sheet_xml(rows: dict[int, dict[str, dict[str, object]]]) -> str:
    row_xml: list[str] = []
    for row_idx in sorted(rows):
        cells_xml: list[str] = []
        for col in sorted(rows[row_idx]):
            cells_xml.append(_cell_xml(rows[row_idx][col], f"{col}{row_idx}"))
        row_xml.append(f'<row r="{row_idx}">' + "".join(cells_xml) + "</row>")

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(row_xml)
        + "</sheetData></worksheet>"
    )


def _build_base_kfa_rows() -> dict[int, dict[str, dict[str, object]]]:
    rows: dict[int, dict[str, dict[str, object]]] = {
        7: {
            "J": {"value": "45658"},
            "L": {"value": "45292"},
        },
        8: {
            "J": {"value": "–2025-12-31", "force_string": True},
            "L": {"value": "–2024-12-31", "force_string": True},
        },
    }

    line_rows = {
        11: ("Resultat efter finansiella poster", "100.1", "90.1"),
        12: ("Justeringar för poster som inte ingår i kassaflödet, m.m.", "10.2", "9.2"),
        14: ("Betald skatt", "-5.3", "-4.3"),
        16: ("förändringar av rörelsekapital", "20.4", "19.4"),
        19: ("Ökning(-)/Minskning(+) av varulager", "-2.5", "-1.5"),
        20: ("Ökning(-)/Minskning(+) av rörelsefordringar", "3.6", "2.6"),
        21: ("Ökning(+)/Minskning(-) av rörelseskulder", "4.7", "3.7"),
        22: ("Kassaflöde från den löpande verksamheten", "26.2", "24.2"),
        29: ("Försäljning av rörelsegren", "7.8", "6.8"),
        30: ("Förvärv av immateriella anläggningstillgångar", "-1.9", "-2.9"),
        32: ("Förvärv av materiella anläggningstillgångar", "-2.1", "-3.1"),
        35: ("Avyttring/minskning av finansiella tillgångar", "5.2", "4.2"),
        36: ("Kassaflöde från investeringsverksamheten", "1.2", "0.2"),
        39: ("Nyemission", "0", "0"),
        40: ("Erhållna aktieägartillskott", "0", "0"),
        41: ("Återköp av egna aktier", "0", "0"),
        42: ("Överlåtelse av egna aktier", "0", "0"),
        43: ("Upptagna lån", "0", "0"),
        44: ("Amortering av låneskulder", "0", "0"),
        45: ("Förändring av utnyttjad checkkredit", "0", "0"),
        46: ("Utbetald utdelning", "0", "0"),
        47: ("Erhållna koncernbidrag", "0", "0"),
        48: ("Lämnade koncernbidrag", "0", "0"),
        49: ("Kassaflöde från finansieringsverksamheten", "0", "0"),
        51: ("Årets kassaflöde", "27.4", "24.4"),
        52: ("Likvida medel vid årets början", "10.0", "11.0"),
        54: ("Likvida medel vid årets slut", "37.4", "35.4"),
    }

    for row_idx, (label, curr, prev) in line_rows.items():
        rows[row_idx] = {
            "D": {"value": label, "force_string": True},
            "J": {"value": curr},
            "L": {"value": prev},
        }

    return rows


def _build_base_ar_rows(acquisition_row: int = 30, sale_row: int = 29) -> dict[int, dict[str, dict[str, object]]]:
    return {
        15: {
            "D": {
                "value": "-1.9",
                "formula": f"KFA!J{acquisition_row}",
            },
            "F": {
                "value": "3.9",
                "formula": f"SUM(KFA!L{sale_row}:L{acquisition_row})",
            },
        }
    }


def _create_workbook(
    path: Path,
    *,
    kfa_rows: dict[int, dict[str, dict[str, object]]] | None = None,
    ar_rows: dict[int, dict[str, dict[str, object]]] | None = None,
    include_kfa: bool = True,
    include_ar: bool = True,
) -> None:
    kfa = copy.deepcopy(_build_base_kfa_rows()) if kfa_rows is None else kfa_rows
    ar = copy.deepcopy(_build_base_ar_rows()) if ar_rows is None else ar_rows

    sheets: list[tuple[str, str, str]] = []
    xmls: list[str] = []
    if include_ar:
        sheets.append(("ÅR Layout", "1", "rId1"))
        xmls.append(_sheet_xml(ar))
    if include_kfa:
        sheets.append(("KFA", str(len(sheets) + 1), f"rId{len(sheets) + 1}"))
        xmls.append(_sheet_xml(kfa))

    workbook_sheets = "".join(
        f'<sheet name="{name}" sheetId="{sheet_id}" r:id="{rid}"/>'
        for name, sheet_id, rid in sheets
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets></workbook>"
    )

    rels = "".join(
        f'<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{idx}.xml"/>'
        for idx, (_, _, rid) in enumerate(sheets, start=1)
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + rels
        + "</Relationships>"
    )

    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx, _ in enumerate(sheets, start=1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + content_overrides
        + "</Types>"
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdWorkbook" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        for idx, xml in enumerate(xmls, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", xml)


class CashFlowExtractionTests(unittest.TestCase):
    def _extract(
        self,
        *,
        kfa_rows: dict[int, dict[str, dict[str, object]]] | None = None,
        ar_rows: dict[int, dict[str, dict[str, object]]] | None = None,
        include_kfa: bool = True,
        include_ar: bool = True,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workbook = tmp_path / "cf.xlsx"
            output = tmp_path / "out.json"
            _create_workbook(
                workbook,
                kfa_rows=kfa_rows,
                ar_rows=ar_rows,
                include_kfa=include_kfa,
                include_ar=include_ar,
            )
            payload = extract_cash_flow(workbook, output)
            self.assertTrue(output.exists())
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], persisted["status"])
            return payload

    def _resolved_line(self) -> dict[str, object]:
        return {
            "valueCurrent": "1",
            "valuePrevious": "1",
            "status": "resolved",
            "source": {"semanticAnchor": "x", "sheet": "KFA"},
            "renderedLabelSv": "x",
            "sourceLabel": "x",
            "trace": {},
        }

    def _base_renderable_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "1.0",
            "status": "ok",
            "period": {
                "currentPeriodLabel": "2025-01-01-2025-12-31",
                "previousPeriodLabel": "2024-01-01-2024-12-31",
            },
            "lines": {key: self._resolved_line() for key in REQUIRED_PROPERTIES},
            "diagnostics": [],
        }

    def test_reads_current_values_from_kfa_j_and_previous_from_l(self) -> None:
        payload = self._extract()
        self.assertEqual(payload["lines"]["resultAfterFinancialItems"]["valueCurrent"], "100.1")
        self.assertEqual(payload["lines"]["resultAfterFinancialItems"]["valuePrevious"], "90.1")
        self.assertEqual(payload["lines"]["cashAtEnd"]["trace"]["valueCurrentCell"], "J54")
        self.assertEqual(payload["lines"]["cashAtEnd"]["trace"]["valuePreviousCell"], "L54")

    def test_no_fixed_row_dependency_with_moved_rows(self) -> None:
        base = _build_base_kfa_rows()
        moved: dict[int, dict[str, dict[str, object]]] = {7: base[7], 8: base[8]}
        mapping = {
            11: 111,
            12: 112,
            14: 114,
            16: 116,
            19: 119,
            20: 120,
            21: 121,
            22: 122,
            29: 129,
            30: 130,
            32: 132,
            35: 135,
            36: 136,
            39: 139,
            40: 140,
            41: 141,
            42: 142,
            43: 143,
            44: 144,
            45: 145,
            46: 146,
            47: 147,
            48: 148,
            49: 149,
            51: 151,
            52: 152,
            54: 154,
        }
        for old_row, new_row in mapping.items():
            moved[new_row] = base[old_row]

        ar_rows = _build_base_ar_rows(acquisition_row=130, sale_row=129)
        payload = self._extract(kfa_rows=moved, ar_rows=ar_rows)
        self.assertEqual(payload["lines"]["investmentsTangibleAssets"]["valueCurrent"], "-2.1")
        self.assertEqual(payload["lines"]["intangibleComposedInvestingCashFlow"]["valuePrevious"], "3.9")

    def test_missing_workbook_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError):
                extract_cash_flow(Path(tmp) / "missing.xlsx", Path(tmp) / "out.json")

    def test_corrupt_xlsx_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "bad.xlsx"
            workbook.write_text("not zip", encoding="utf-8")
            with self.assertRaises(ExtractionError) as ctx:
                extract_cash_flow(workbook, Path(tmp) / "out.json")
            self.assertIn("Invalid or corrupt XLSX", str(ctx.exception))

    def test_missing_kfa_sheet_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "missing-kfa.xlsx"
            _create_workbook(workbook, include_kfa=False, include_ar=True)
            with self.assertRaises(ExtractionError) as ctx:
                extract_cash_flow(workbook, Path(tmp) / "out.json")
            self.assertIn("Missing required sheets", str(ctx.exception))

    def test_missing_ar_layout_sheet_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook = Path(tmp) / "missing-ar.xlsx"
            _create_workbook(workbook, include_kfa=True, include_ar=False)
            with self.assertRaises(ExtractionError) as ctx:
                extract_cash_flow(workbook, Path(tmp) / "out.json")
            self.assertIn("Missing required sheets", str(ctx.exception))

    def test_duplicate_anchor_produces_review_required(self) -> None:
        rows = _build_base_kfa_rows()
        rows[200] = {
            "D": {"value": "Resultat efter finansiella poster", "force_string": True},
            "J": {"value": "1"},
            "L": {"value": "1"},
        }
        payload = self._extract(kfa_rows=rows)
        self.assertEqual(payload["status"], "review_required")
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("DUPLICATE_SEMANTIC_ANCHOR", codes)

    def test_blank_authoritative_cell_sets_unresolved(self) -> None:
        rows = _build_base_kfa_rows()
        rows[12]["J"] = {"value": ""}
        payload = self._extract(kfa_rows=rows)
        self.assertEqual(payload["lines"]["nonCashAdjustments"]["status"], "unresolved")
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("BLANK_AUTHORITATIVE_CELL", codes)

    def test_formula_without_cached_value_sets_unresolved(self) -> None:
        rows = _build_base_kfa_rows()
        rows[11]["J"] = {"formula": "1+1", "without_cached_value": True}
        payload = self._extract(kfa_rows=rows)
        self.assertEqual(payload["lines"]["resultAfterFinancialItems"]["status"], "unresolved")
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("FORMULA_WITHOUT_CACHED_VALUE", codes)

    def test_non_numeric_authoritative_value_sets_unresolved(self) -> None:
        rows = _build_base_kfa_rows()
        rows[11]["J"] = {"value": "N/A", "force_string": True}
        payload = self._extract(kfa_rows=rows)
        line = payload["lines"]["resultAfterFinancialItems"]
        self.assertIsNone(line["valueCurrent"])
        self.assertEqual(line["status"], "unresolved")
        self.assertNotEqual(line["valueCurrent"], "0")
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("NON_NUMERIC_AUTHORITATIVE_VALUE", codes)
        self.assertEqual(payload["status"], "review_required")

    def test_decimal_values_are_serialized_as_strings(self) -> None:
        payload = self._extract()
        self.assertIsInstance(payload["lines"]["cashAtEnd"]["valueCurrent"], str)
        self.assertIsInstance(payload["lines"]["cashAtEnd"]["valuePrevious"], str)

    def test_receivables_aggregation_contains_both_components(self) -> None:
        payload = self._extract()
        components = payload["lines"]["changeInShortTermReceivables"]["trace"]["components"]
        labels = {component["label"] for component in components}
        self.assertIn("Ökning(-)/Minskning(+) av varulager", labels)
        self.assertIn("Ökning(-)/Minskning(+) av rörelsefordringar", labels)

    def test_intangible_composed_line_preserves_all_components(self) -> None:
        payload = self._extract()
        components = payload["lines"]["intangibleComposedInvestingCashFlow"]["trace"]["components"]
        self.assertEqual(len(components), 2)
        labels = {component["label"] for component in components}
        self.assertIn("Försäljning av rörelsegren", labels)
        self.assertIn("Förvärv av immateriella anläggningstillgångar", labels)

    def test_semantic_label_mismatch_produces_review_required(self) -> None:
        payload = self._extract()
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("SEMANTIC_LABEL_REVIEW_REQUIRED", codes)
        self.assertIn("COMPOSED_INVESTING_LABEL_REVIEW_REQUIRED", codes)
        self.assertEqual(payload["status"], "review_required")

    def test_financing_total_always_exists_even_when_zero(self) -> None:
        payload = self._extract()
        line = payload["lines"]["financingCashFlowTotal"]
        self.assertIn("financingCashFlowTotal", payload["lines"])
        self.assertEqual(line["valueCurrent"], "0")
        self.assertEqual(line["valuePrevious"], "0")

    def test_non_zero_financing_policy_requires_visible_presentation(self) -> None:
        rows = _build_base_kfa_rows()
        rows[49]["J"] = {"value": "12"}
        rows[43]["J"] = {"value": "12"}
        payload = self._extract(kfa_rows=rows)
        policy = payload["lines"]["financingCashFlowTotal"]["trace"]["presentationPolicy"]
        self.assertTrue(policy["showSectionWhenAnyDisplayedPeriodNonZero"])
        self.assertTrue(policy["computedShouldDisplay"])

    def test_authoritative_totals_not_replaced_by_derived_totals(self) -> None:
        rows = _build_base_kfa_rows()
        rows[36]["J"] = {"value": "99.9"}
        payload = self._extract(kfa_rows=rows)
        self.assertEqual(payload["lines"]["investingCashFlowTotal"]["valueCurrent"], "99.9")

    def test_reconciliation_difference_produces_review_required(self) -> None:
        rows = _build_base_kfa_rows()
        rows[22]["J"] = {"value": "999.9"}
        payload = self._extract(kfa_rows=rows)
        self.assertEqual(payload["status"], "review_required")
        codes = {d["code"] for d in payload["diagnostics"]}
        self.assertIn("RECONCILIATION_DIFFERENCE", codes)

    def test_reconciliation_previous_period_difference_produces_review_required(self) -> None:
        rows = _build_base_kfa_rows()
        rows[22]["L"] = {"value": "999.9"}
        payload = self._extract(kfa_rows=rows)

        operating = payload["reconciliation"]["operatingSubtotal"]
        self.assertEqual(operating["current"]["status"], "ok")
        self.assertTrue(operating["current"]["withinTolerance"])
        self.assertEqual(operating["previous"]["status"], "difference")
        self.assertFalse(operating["previous"]["withinTolerance"])

        previous_diffs = [
            d
            for d in payload["diagnostics"]
            if d.get("code") == "RECONCILIATION_DIFFERENCE"
            and isinstance(d.get("trace"), dict)
            and d["trace"].get("period") == "previous"
        ]
        self.assertTrue(previous_diffs)
        self.assertEqual(payload["status"], "review_required")

    def test_duplicate_ar_layout_anchor_produces_review_required(self) -> None:
        ar_rows = _build_base_ar_rows()
        ar_rows[16] = {
            "D": {
                "value": "-1.9",
                "formula": "KFA!J30",
            },
            "F": {
                "value": "3.9",
                "formula": "SUM(KFA!L29:L30)",
            },
        }

        payload = self._extract(ar_rows=ar_rows)
        line = payload["lines"]["intangibleComposedInvestingCashFlow"]
        codes = {d["code"] for d in payload["diagnostics"]}

        self.assertIn("AMBIGUOUS_AR_LAYOUT_COMPOSITION", codes)
        self.assertEqual(line["status"], "unresolved")
        self.assertIsNone(line["valueCurrent"])
        self.assertIsNone(line["valuePrevious"])
        self.assertIsNone(line["trace"]["presentationSource"]["current"])
        self.assertIsNone(line["trace"]["presentationSource"]["previous"])
        self.assertEqual(payload["status"], "review_required")

    def test_render_guard_rejects_current_real_extraction(self) -> None:
        workbook = ROOT / "source-data" / "Kassaflödesanalys 2025 - Omegapoint Malmö.xlsx"
        if not workbook.exists():
            self.skipTest("Real workbook fixture missing")

        with tempfile.TemporaryDirectory() as tmp:
            payload = extract_cash_flow(workbook, Path(tmp) / "real.json")

        with self.assertRaises(ExtractionError):
            ensure_real_cash_flow_renderable(payload)

    def test_render_guard_rejects_unresolved_required_value(self) -> None:
        payload = self._base_renderable_payload()
        payload["lines"]["cashAtEnd"]["status"] = "unresolved"

        with self.assertRaises(ExtractionError) as ctx:
            ensure_real_cash_flow_renderable(payload)
        self.assertIn("unresolved required values", str(ctx.exception))

    def test_render_guard_rejects_missing_period_label(self) -> None:
        payload = self._base_renderable_payload()
        payload["period"]["currentPeriodLabel"] = None

        with self.assertRaises(ExtractionError) as ctx:
            ensure_real_cash_flow_renderable(payload)
        self.assertIn("currentPeriodLabel is unresolved", str(ctx.exception))

    def test_render_guard_rejects_semantic_review_diagnostics(self) -> None:
        payload = self._base_renderable_payload()
        payload["diagnostics"] = [
            {
                "code": "SEMANTIC_LABEL_REVIEW_REQUIRED",
                "reviewRequired": True,
            }
        ]

        with self.assertRaises(ExtractionError) as ctx:
            ensure_real_cash_flow_renderable(payload)
        self.assertIn("unresolved semantic review diagnostics", str(ctx.exception))

    def test_every_required_contract_property_exists(self) -> None:
        payload = self._extract()
        for key in REQUIRED_PROPERTIES:
            self.assertIn(key, payload["lines"])


if __name__ == "__main__":
    unittest.main()
