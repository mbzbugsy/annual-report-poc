from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class IncomeStatementLineMapping:
    target_property: str
    accepted_labels: List[str]
    required: bool = True


@dataclass(frozen=True)
class IncomeStatementWorkbookProfile:
    sheet_name: str
    label_anchor_column: str
    value_column: str
    line_mappings: List[IncomeStatementLineMapping]


WORKBOOK_PROFILE = IncomeStatementWorkbookProfile(
    sheet_name="RR sammanställning",
    label_anchor_column="A",
    value_column="D",
    line_mappings=[
        IncomeStatementLineMapping("revenue", ["Nettoomsättning"]),
        IncomeStatementLineMapping("otherOperatingIncome", ["Övriga rörelseintäkter"]),
        IncomeStatementLineMapping("totalIncome", ["Summa intäkter", "Totala intäkter"]),
        IncomeStatementLineMapping(
            "costOfGoodsAndServices",
            ["Kostnad för sålda varor och tjänster", "Kostnad sålda varor och tjänster"],
            required=False,
        ),
        IncomeStatementLineMapping("otherExternalCosts", ["Övriga externa kostnader"], required=False),
        IncomeStatementLineMapping("personnelCosts", ["Personalkostnader"], required=False),
        IncomeStatementLineMapping(
            "depreciationAndAmortization",
            [
                "Avskrivningar och nedskrivningar av materiella och immateriella anläggningstillgångar",
                "Av-/Nedskrivningar",
            ],
            required=False,
        ),
        IncomeStatementLineMapping("otherOperatingCosts", ["Övriga rörelsekostnader"], required=False),
        IncomeStatementLineMapping("totalOperatingCosts", ["Rörelsens kostnader"], required=False),
        IncomeStatementLineMapping("operatingResult", ["Rörelseresultat"]),
        IncomeStatementLineMapping("interestIncome", ["Ränteintäkter"], required=False),
        IncomeStatementLineMapping("interestCosts", ["Räntekostnader"], required=False),
        IncomeStatementLineMapping(
            "resultAfterFinancialItems",
            ["Resultat efter finansiella poster", "Resultat efter finansiella poste"],
        ),
        IncomeStatementLineMapping("appropriations", ["Bokslutsdispositioner"], required=False),
        IncomeStatementLineMapping("profitBeforeTax", ["Resultat före skatt"]),
        IncomeStatementLineMapping("taxForYear", ["Skatt"]),
        IncomeStatementLineMapping("netResult", ["Årets resultat"]),
    ],
)
