from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class IncomeStatementLineMapping:
    target_property: str
    accepted_labels: List[str]


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
        IncomeStatementLineMapping("operatingResult", ["Rörelseresultat"]),
        IncomeStatementLineMapping(
            "resultAfterFinancialItems",
            ["Resultat efter finansiella poster", "Resultat efter finansiella poste"],
        ),
        IncomeStatementLineMapping("profitBeforeTax", ["Resultat före skatt"]),
        IncomeStatementLineMapping("taxForYear", ["Skatt"]),
        IncomeStatementLineMapping("netResult", ["Årets resultat"]),
    ],
)
