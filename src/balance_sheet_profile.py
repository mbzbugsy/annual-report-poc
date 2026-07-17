from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass(frozen=True)
class BalanceSheetLineMapping:
    target_property: str
    accepted_account_codes: List[str]
    accepted_labels: List[str]
    required: bool = True


@dataclass(frozen=True)
class BalanceSheetWorkbookProfile:
    workbook_sheet_br: str
    workbook_sheet_equity: str
    workbook_sheet_income: str
    label_anchor_column: str
    account_code_column: str
    value_columns: Dict[str, str]
    line_mappings: List[BalanceSheetLineMapping]
    canonical_equity_account_mappings: Dict[str, str]
    canonical_equity_description_aliases: Dict[str, List[str]]
    additional_canonical_equity_mappings: Dict[str, str] = field(default_factory=dict)
    restricted_equity_component_accounts: List[str] = field(default_factory=lambda: ["2081", "2086"])
    unrestricted_equity_component_accounts: List[str] = field(default_factory=lambda: ["2091", "2099"])
    restricted_equity_br_codes: List[str] = field(default_factory=lambda: ["20RE"])
    restricted_equity_br_labels: List[str] = field(default_factory=lambda: ["Bundet eget kapital"])
    unrestricted_equity_br_codes: List[str] = field(default_factory=lambda: ["20UE"])
    unrestricted_equity_br_labels: List[str] = field(
        default_factory=lambda: ["Annat eget kapital inkl periodens resultat (fritt)"]
    )
    known_optional_canonical_equity_accounts: List[str] = field(default_factory=lambda: ["2082", "2083", "2085", "2097"])
    decimal_tolerance: Decimal = Decimal("0.01")


WORKBOOK_PROFILE = BalanceSheetWorkbookProfile(
    workbook_sheet_br="BR Sammanställning",
    workbook_sheet_equity="Eget kapital",
    workbook_sheet_income="RR sammanställning",
    label_anchor_column="B",
    account_code_column="A",
    value_columns={
        "base": "C",
        "reallocation": "D",
        "output": "E",
    },
    line_mappings=[
        BalanceSheetLineMapping("goodwill", ["1070"], ["Goodwill"]),
        BalanceSheetLineMapping("machineryTechnicalInstallations", ["1220"], ["Maskiner och andra tekniska anläggningar"]),
        BalanceSheetLineMapping("equipmentToolsInstallations", ["1299"], ["Materiella anläggningstillgångar"]),
        BalanceSheetLineMapping("sharesInGroupCompanies", ["1310"], ["Participations in group companies", "Andelar i koncernföretag"]),
        BalanceSheetLineMapping("otherLongTermSecurities", ["1350"], ["Participations and securities in other companies", "Andra långfristiga värdepappersinnehav"]),
        BalanceSheetLineMapping("otherLongTermReceivables", ["1380"], ["Other long-term receivables", "Andra långfristiga fordringar"]),
        BalanceSheetLineMapping("totalFinancialFixedAssets", ["1399"], ["Finansiella anläggningstillgångar"]),
        BalanceSheetLineMapping("totalFixedAssets", ["1FA"], ["Summa anläggningstillgångar"]),
        BalanceSheetLineMapping("tradeReceivables", ["I1599EX"], ["Kundfordringar"]),
        BalanceSheetLineMapping("receivablesFromGroupCompanies", ["I15991699"], ["Fordringar hos koncernbolag"]),
        BalanceSheetLineMapping("otherReceivables", ["I16EXT"], ["Övriga fordringar"]),
        BalanceSheetLineMapping("accruedUnbilledRevenue", ["1499"], ["Upparbetad men ej fakturerad intäkt"]),
        BalanceSheetLineMapping("prepaidExpensesAccruedIncome", ["1799"], ["Förutbetalda kostnader och upplupna intäkter"]),
        BalanceSheetLineMapping("totalShortTermReceivables", ["I1CA"], ["Summa kortfristiga fordringar"]),
        BalanceSheetLineMapping("cashAndBank", ["1999"], ["Kassa och Bank"]),
        BalanceSheetLineMapping("totalCurrentAssets", ["1CA"], ["Summa omsättningstillgångar"]),
        BalanceSheetLineMapping("totalAssets", ["1TA"], ["Summa tillgångar"]),
        BalanceSheetLineMapping("totalEquity", ["20SETOT"], ["Summa eget kapital"]),
        BalanceSheetLineMapping("advancesFromCustomers", ["2420"], ["Förskott från kunder"]),
        BalanceSheetLineMapping("tradePayables", ["2440"], ["Leverantörsskulder"]),
        BalanceSheetLineMapping("liabilitiesToGroupCompanies", ["I2499INT"], ["Skulder till koncernbolag"]),
        BalanceSheetLineMapping("currentTaxLiabilities", ["2599"], ["Skatteskulder", "Aktuella skatteskulder"]),
        BalanceSheetLineMapping("otherLiabilities", ["I2OTHCL"], ["Övriga kortfristiga skulder", "Övriga skulder"]),
        BalanceSheetLineMapping("accruedExpensesDeferredIncome", ["2999"], ["Upplupna kostnader och förutbetalda intäkter"]),
        BalanceSheetLineMapping("totalShortTermLiabilities", ["2CL"], ["Summa kortfristiga skulder"]),
        BalanceSheetLineMapping("totalEquityAndLiabilities", ["2TLE"], ["Summa eget kapital och skulder"]),
    ],
    canonical_equity_account_mappings={
        "2081": "shareCapital",
        "2086": "reserveFund",
        "2091": "retainedEarnings",
        "2099": "profitForYear",
        "20SE": "equitySheetTotal",
    },
    canonical_equity_description_aliases={
        "shareCapital": ["share capital", "aktiekapital"],
        "reserveFund": ["statutory reserve", "reservfond"],
        "retainedEarnings": ["retained profit", "balanserad vinst eller förlust"],
        "profitForYear": ["net income", "årets resultat"],
        "equitySheetTotal": ["total equity", "summa eget kapital"],
    },
)
