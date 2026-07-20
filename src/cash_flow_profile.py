from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CashFlowSingleLineMapping:
    target_property: str
    source_semantic_label: str
    rendered_label_sv: str
    accepted_labels: List[str]


@dataclass(frozen=True)
class CashFlowWorkbookProfile:
    kfa_sheet_name: str
    ar_layout_sheet_name: str
    label_anchor_column: str
    value_current_column: str
    value_previous_column: str
    single_line_mappings: List[CashFlowSingleLineMapping]
    receivables_component_labels: List[str]
    intangible_component_labels: List[str]
    financing_detail_labels: List[str]


WORKBOOK_PROFILE = CashFlowWorkbookProfile(
    kfa_sheet_name="KFA",
    ar_layout_sheet_name="ÅR Layout",
    label_anchor_column="D",
    value_current_column="J",
    value_previous_column="L",
    single_line_mappings=[
        CashFlowSingleLineMapping(
            target_property="resultAfterFinancialItems",
            source_semantic_label="Resultat efter finansiella poster",
            rendered_label_sv="Rörelseresultat",
            accepted_labels=["Resultat efter finansiella poster"],
        ),
        CashFlowSingleLineMapping(
            target_property="nonCashAdjustments",
            source_semantic_label="Justeringar för poster som inte ingår i kassaflödet, m.m.",
            rendered_label_sv="Justeringar för poster som inte ingår i kassaflödet, m.m.",
            accepted_labels=["Justeringar för poster som inte ingår i kassaflödet, m.m."],
        ),
        CashFlowSingleLineMapping(
            target_property="incomeTaxPaid",
            source_semantic_label="Betald skatt",
            rendered_label_sv="Betald skatt",
            accepted_labels=["Betald skatt"],
        ),
        CashFlowSingleLineMapping(
            target_property="operatingCashFlowBeforeWorkingCapital",
            source_semantic_label="förändringar av rörelsekapital",
            rendered_label_sv="Kassaflöde från den löpande verksamheten före förändringar av rörelsekapital",
            accepted_labels=["förändringar av rörelsekapital"],
        ),
        CashFlowSingleLineMapping(
            target_property="changeInShortTermLiabilities",
            source_semantic_label="Ökning(+)/Minskning(-) av rörelseskulder",
            rendered_label_sv="Ökning(+)/Minskning(-) av rörelseskulder",
            accepted_labels=["Ökning(+)/Minskning(-) av rörelseskulder"],
        ),
        CashFlowSingleLineMapping(
            target_property="operatingCashFlowTotal",
            source_semantic_label="Kassaflöde från den löpande verksamheten",
            rendered_label_sv="Kassaflöde från den löpande verksamheten",
            accepted_labels=["Kassaflöde från den löpande verksamheten"],
        ),
        CashFlowSingleLineMapping(
            target_property="investmentsTangibleAssets",
            source_semantic_label="Förvärv av materiella anläggningstillgångar",
            rendered_label_sv="Förvärv av materiella anläggningstillgångar",
            accepted_labels=["Förvärv av materiella anläggningstillgångar"],
        ),
        CashFlowSingleLineMapping(
            target_property="investmentsFinancialAssets",
            source_semantic_label="Avyttring/minskning av finansiella tillgångar",
            rendered_label_sv="Avyttring/minskning av finansiella tillgångar",
            accepted_labels=["Avyttring/minskning av finansiella tillgångar"],
        ),
        CashFlowSingleLineMapping(
            target_property="investingCashFlowTotal",
            source_semantic_label="Kassaflöde från investeringsverksamheten",
            rendered_label_sv="Kassaflöde från investeringsverksamheten",
            accepted_labels=["Kassaflöde från investeringsverksamheten"],
        ),
        CashFlowSingleLineMapping(
            target_property="financingCashFlowTotal",
            source_semantic_label="Kassaflöde från finansieringsverksamheten",
            rendered_label_sv="Kassaflöde från finansieringsverksamheten",
            accepted_labels=["Kassaflöde från finansieringsverksamheten"],
        ),
        CashFlowSingleLineMapping(
            target_property="netCashFlowForYear",
            source_semantic_label="Årets kassaflöde",
            rendered_label_sv="Årets kassaflöde",
            accepted_labels=["Årets kassaflöde"],
        ),
        CashFlowSingleLineMapping(
            target_property="cashAtBeginning",
            source_semantic_label="Likvida medel vid årets början",
            rendered_label_sv="Likvida medel vid årets början",
            accepted_labels=["Likvida medel vid årets början"],
        ),
        CashFlowSingleLineMapping(
            target_property="cashAtEnd",
            source_semantic_label="Likvida medel vid årets slut",
            rendered_label_sv="Likvida medel vid årets slut",
            accepted_labels=["Likvida medel vid årets slut"],
        ),
    ],
    receivables_component_labels=[
        "Ökning(-)/Minskning(+) av varulager",
        "Ökning(-)/Minskning(+) av rörelsefordringar",
    ],
    intangible_component_labels=[
        "Försäljning av rörelsegren",
        "Förvärv av immateriella anläggningstillgångar",
    ],
    financing_detail_labels=[
        "Nyemission",
        "Erhållna aktieägartillskott",
        "Återköp av egna aktier",
        "Överlåtelse av egna aktier",
        "Upptagna lån",
        "Amortering av låneskulder",
        "Förändring av utnyttjad checkkredit",
        "Utbetald utdelning",
        "Erhållna koncernbidrag",
        "Lämnade koncernbidrag",
    ],
)
