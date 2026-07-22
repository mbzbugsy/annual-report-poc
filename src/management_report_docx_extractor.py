from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


class ExtractionError(Exception):
    pass


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
V_NS = "urn:schemas-microsoft-com:vml"
WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


NS = {
    "w": W_NS,
    "r": R_NS,
    "rels": PKG_REL_NS,
    "cp": CP_NS,
    "dc": DC_NS,
    "dcterms": DCTERMS_NS,
    "v": V_NS,
    "wps": WPS_NS,
}


HEADER_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
FOOTER_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_source_name(path: Path) -> str:
    return path.name if path.is_absolute() else path.as_posix()


def _bool_flag(val: Optional[str]) -> bool:
    if val is None:
        return True
    return val not in {"0", "false", "False"}


def _style_name_map(styles_root: ET.Element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for style in styles_root.findall("w:style", NS):
        style_id = style.attrib.get(f"{{{W_NS}}}styleId")
        if not style_id:
            continue
        name_node = style.find("w:name", NS)
        if name_node is None:
            continue
        name = name_node.attrib.get(f"{{{W_NS}}}val", "")
        out[style_id] = name
    return out


def _style_outline_map(styles_root: ET.Element) -> Dict[str, Optional[int]]:
    out: Dict[str, Optional[int]] = {}
    for style in styles_root.findall("w:style", NS):
        style_id = style.attrib.get(f"{{{W_NS}}}styleId")
        if not style_id:
            continue
        ppr = style.find("w:pPr", NS)
        if ppr is None:
            out[style_id] = None
            continue
        lvl = ppr.find("w:outlineLvl", NS)
        if lvl is None:
            out[style_id] = None
            continue
        raw = lvl.attrib.get(f"{{{W_NS}}}val")
        if raw is None:
            out[style_id] = None
            continue
        try:
            out[style_id] = int(raw) + 1
        except ValueError:
            out[style_id] = None
    return out


def _core_properties(zf: zipfile.ZipFile) -> Dict[str, str]:
    path = "docProps/core.xml"
    if path not in zf.namelist():
        return {
            "creator": "",
            "lastModifiedBy": "",
            "created": "",
            "modified": "",
            "title": "",
            "subject": "",
            "description": "",
        }
    try:
        root = ET.fromstring(zf.read(path))
    except ET.ParseError as exc:
        raise ExtractionError("Malformed core properties XML") from exc

    def _txt(q: str) -> str:
        node = root.find(q, NS)
        return (node.text or "") if node is not None else ""

    return {
        "creator": _txt("dc:creator"),
        "lastModifiedBy": _txt("cp:lastModifiedBy"),
        "created": _txt("dcterms:created"),
        "modified": _txt("dcterms:modified"),
        "title": _txt("dc:title"),
        "subject": _txt("dc:subject"),
        "description": _txt("dc:description"),
    }


def _document_relationships(zf: zipfile.ZipFile) -> Dict[str, Dict[str, str]]:
    rel_path = "word/_rels/document.xml.rels"
    if rel_path not in zf.namelist():
        return {}
    try:
        root = ET.fromstring(zf.read(rel_path))
    except ET.ParseError as exc:
        raise ExtractionError("Malformed document relationships XML") from exc
    out: Dict[str, Dict[str, str]] = {}
    for rel in root.findall("rels:Relationship", NS):
        rid = rel.attrib.get("Id")
        if not rid:
            continue
        out[rid] = {
            "type": rel.attrib.get("Type", ""),
            "target": rel.attrib.get("Target", ""),
        }
    return out


def _header_footer_presence(rels: Dict[str, Dict[str, str]]) -> Tuple[bool, bool]:
    has_header = any(v.get("type") == HEADER_REL for v in rels.values())
    has_footer = any(v.get("type") == FOOTER_REL for v in rels.values())
    return has_header, has_footer


def _read_text_nodes_in_order(parent: ET.Element) -> str:
    parts: List[str] = []
    for node in parent:
        tag = node.tag.split("}")[-1]
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in {"cr", "br"}:
            br_type = node.attrib.get(f"{{{W_NS}}}type", "textWrapping")
            if br_type == "page":
                continue
            parts.append("\n")
        elif tag == "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def _run_format_flags(run: ET.Element) -> Dict[str, bool]:
    rpr = run.find("w:rPr", NS)
    if rpr is None:
        return {
            "bold": False,
            "italic": False,
            "hidden": False,
            "underline": False,
        }

    b = rpr.find("w:b", NS)
    i = rpr.find("w:i", NS)
    v = rpr.find("w:vanish", NS)
    u = rpr.find("w:u", NS)
    return {
        "bold": _bool_flag(b.attrib.get(f"{{{W_NS}}}val") if b is not None else None) if b is not None else False,
        "italic": _bool_flag(i.attrib.get(f"{{{W_NS}}}val") if i is not None else None) if i is not None else False,
        "hidden": _bool_flag(v.attrib.get(f"{{{W_NS}}}val") if v is not None else None) if v is not None else False,
        "underline": (u is not None and u.attrib.get(f"{{{W_NS}}}val", "single") != "none"),
    }


def _paragraph_meta(
    paragraph: ET.Element,
    style_names: Dict[str, str],
    style_outlines: Dict[str, Optional[int]],
) -> Dict[str, object]:
    ppr = paragraph.find("w:pPr", NS)
    style_id = ""
    style_name = ""
    heading_level: Optional[int] = None
    numbering: Dict[str, object] = {
        "numId": None,
        "ilvl": None,
    }

    if ppr is not None:
        pstyle = ppr.find("w:pStyle", NS)
        if pstyle is not None:
            style_id = pstyle.attrib.get(f"{{{W_NS}}}val", "")
            style_name = style_names.get(style_id, "")
            heading_level = style_outlines.get(style_id)

        outline = ppr.find("w:outlineLvl", NS)
        if outline is not None:
            raw = outline.attrib.get(f"{{{W_NS}}}val")
            if raw is not None:
                try:
                    heading_level = int(raw) + 1
                except ValueError:
                    heading_level = heading_level

        numpr = ppr.find("w:numPr", NS)
        if numpr is not None:
            num_id = numpr.find("w:numId", NS)
            ilvl = numpr.find("w:ilvl", NS)
            numbering = {
                "numId": num_id.attrib.get(f"{{{W_NS}}}val") if num_id is not None else None,
                "ilvl": ilvl.attrib.get(f"{{{W_NS}}}val") if ilvl is not None else None,
            }

    return {
        "styleId": style_id,
        "styleName": style_name,
        "headingLevel": heading_level,
        "numbering": numbering,
    }


@dataclass
class ParsedParagraph:
    text: str
    runs: List[Dict[str, object]]
    explicit_page_breaks: List[Dict[str, int]]
    explicit_line_break_count: int
    last_rendered_page_break: bool
    contains_drawing: bool
    contains_pict: bool
    contains_textbox: bool
    contains_field_code: bool
    hidden_text_detected: bool


def _parse_paragraph_runs(paragraph: ET.Element) -> ParsedParagraph:
    runs: List[Dict[str, object]] = []
    text_parts: List[str] = []
    explicit_page_breaks: List[Dict[str, int]] = []
    line_break_count = 0
    has_last_rendered = paragraph.find(".//w:lastRenderedPageBreak", NS) is not None
    contains_drawing = paragraph.find(".//w:drawing", NS) is not None
    contains_pict = paragraph.find(".//w:pict", NS) is not None
    contains_textbox = (
        paragraph.find(".//w:txbxContent", NS) is not None
        or paragraph.find(".//wps:txbx", NS) is not None
        or paragraph.find(".//v:textbox", NS) is not None
    )
    contains_field_code = paragraph.find(".//w:instrText", NS) is not None
    hidden_text_detected = False

    run_nodes = paragraph.findall(".//w:r", NS)
    for run_index, run in enumerate(run_nodes, start=1):
        flags = _run_format_flags(run)
        hidden_text_detected = hidden_text_detected or bool(flags["hidden"])

        run_text = _read_text_nodes_in_order(run)

        break_nodes = run.findall("w:br", NS)
        breaks: List[Dict[str, object]] = []
        for break_index, br in enumerate(break_nodes, start=1):
            br_type = br.attrib.get(f"{{{W_NS}}}type", "textWrapping")
            breaks.append({
                "type": br_type,
                "breakIndex": break_index,
            })
            if br_type == "page":
                explicit_page_breaks.append({
                    "runIndex": run_index,
                    "breakIndex": break_index,
                })
            else:
                line_break_count += 1

        text_parts.append(run_text)
        runs.append(
            {
                "runIndex": run_index,
                "text": run_text,
                "bold": flags["bold"],
                "italic": flags["italic"],
                "hidden": flags["hidden"],
                "underline": flags["underline"],
                "breaks": breaks,
            }
        )

    return ParsedParagraph(
        text="".join(text_parts),
        runs=runs,
        explicit_page_breaks=explicit_page_breaks,
        explicit_line_break_count=line_break_count,
        last_rendered_page_break=has_last_rendered,
        contains_drawing=contains_drawing,
        contains_pict=contains_pict,
        contains_textbox=contains_textbox,
        contains_field_code=contains_field_code,
        hidden_text_detected=hidden_text_detected,
    )


def _table_cell_payload(
    cell: ET.Element,
    style_names: Dict[str, str],
    style_outlines: Dict[str, Optional[int]],
    diagnostics: List[Dict[str, object]],
    table_index: int,
    row_index: int,
    cell_index: int,
) -> Dict[str, object]:
    tcpr = cell.find("w:tcPr", NS)
    grid_span: Optional[int] = None
    v_merge: Optional[str] = None
    if tcpr is not None:
        gs = tcpr.find("w:gridSpan", NS)
        if gs is not None:
            raw = gs.attrib.get(f"{{{W_NS}}}val")
            if raw is not None:
                try:
                    grid_span = int(raw)
                except ValueError:
                    grid_span = None

        vm = tcpr.find("w:vMerge", NS)
        if vm is not None:
            v_merge = vm.attrib.get(f"{{{W_NS}}}val", "continue")

    paragraphs = cell.findall("w:p", NS)
    paragraph_payloads: List[Dict[str, object]] = []
    cell_text_parts: List[str] = []

    for para_index, para in enumerate(paragraphs, start=1):
        parsed = _parse_paragraph_runs(para)
        meta = _paragraph_meta(para, style_names, style_outlines)

        if parsed.hidden_text_detected:
            hidden_run_indices = [
                run.get("runIndex")
                for run in parsed.runs
                if isinstance(run, dict) and run.get("hidden") is True and isinstance(run.get("runIndex"), int)
            ]
            source_trace: Dict[str, object] = {
                "part": "word/document.xml",
                "tableIndex": table_index,
                "rowIndex": row_index,
                "cellIndex": cell_index,
                "cellParagraphIndex": para_index,
            }
            if hidden_run_indices:
                source_trace["runIndex"] = hidden_run_indices[0]
                source_trace["runIndices"] = hidden_run_indices
            diagnostics.append(
                {
                    "code": "HIDDEN_TEXT_DETECTED",
                    "severity": "warning",
                    "message": "Table cell paragraph contains hidden text runs.",
                    "sourceTrace": source_trace,
                }
            )

        paragraph_payloads.append(
            {
                "paragraphIndex": para_index,
                "text": parsed.text,
                "styleId": meta["styleId"],
                "styleName": meta["styleName"],
                "headingLevel": meta["headingLevel"],
                "numbering": meta["numbering"],
                "runs": parsed.runs,
                "explicitPageBreaks": parsed.explicit_page_breaks,
                "explicitLineBreakCount": parsed.explicit_line_break_count,
                "lastRenderedPageBreak": parsed.last_rendered_page_break,
                "attachedUnsupportedConstructs": {
                    "containsDrawing": parsed.contains_drawing,
                    "containsPict": parsed.contains_pict,
                    "containsTextBox": parsed.contains_textbox,
                    "containsFieldCode": parsed.contains_field_code,
                },
            }
        )
        cell_text_parts.append(parsed.text)

    return {
        "text": "\n".join(cell_text_parts),
        "gridSpan": grid_span,
        "vMerge": v_merge,
        "paragraphs": paragraph_payloads,
    }


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def extract_management_report_raw(docx_path: Path) -> Dict[str, object]:
    if not docx_path.exists():
        raise ExtractionError(f"Input DOCX does not exist: {docx_path}")

    try:
        docx_bytes = docx_path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"Unable to read DOCX: {docx_path}") from exc

    source_sha = _sha256_bytes(docx_bytes)

    try:
        zf = zipfile.ZipFile(docx_path)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"Invalid or corrupt DOCX ZIP container: {docx_path}") from exc

    with zf:
        if "word/document.xml" not in zf.namelist():
            raise ExtractionError("DOCX is missing required part: word/document.xml")

        try:
            doc_root = ET.fromstring(zf.read("word/document.xml"))
        except ET.ParseError as exc:
            raise ExtractionError("Malformed XML in word/document.xml") from exc

        styles_root: Optional[ET.Element] = None
        if "word/styles.xml" in zf.namelist():
            try:
                styles_root = ET.fromstring(zf.read("word/styles.xml"))
            except ET.ParseError as exc:
                raise ExtractionError("Malformed XML in word/styles.xml") from exc

        numbering_xml_present = "word/numbering.xml" in zf.namelist()

        settings_root: Optional[ET.Element] = None
        if "word/settings.xml" in zf.namelist():
            try:
                settings_root = ET.fromstring(zf.read("word/settings.xml"))
            except ET.ParseError as exc:
                raise ExtractionError("Malformed XML in word/settings.xml") from exc

        comments_present = "word/comments.xml" in zf.namelist()
        comments_text_count = 0
        if comments_present:
            try:
                comments_root = ET.fromstring(zf.read("word/comments.xml"))
            except ET.ParseError as exc:
                raise ExtractionError("Malformed XML in word/comments.xml") from exc
            for t_node in comments_root.findall(".//w:t", NS):
                text = t_node.text or ""
                if text.strip():
                    comments_text_count += 1

        core_properties = _core_properties(zf)
        rels = _document_relationships(zf)
        has_header, has_footer = _header_footer_presence(rels)

        style_names = _style_name_map(styles_root) if styles_root is not None else {}
        style_outlines = _style_outline_map(styles_root) if styles_root is not None else {}

        body = doc_root.find("w:body", NS)
        if body is None:
            raise ExtractionError("Malformed document XML: missing w:body")

        tracked_changes_detected = bool(
            body.findall(".//w:ins", NS)
            or body.findall(".//w:del", NS)
            or body.findall(".//w:moveFrom", NS)
            or body.findall(".//w:moveTo", NS)
        )
        track_revisions_enabled = False
        if settings_root is not None:
            track_revisions_enabled = settings_root.find("w:trackRevisions", NS) is not None

        drawings = body.findall(".//w:drawing", NS)
        pict_nodes = body.findall(".//w:pict", NS)
        textbox_nodes = (
            body.findall(".//w:txbxContent", NS)
            + body.findall(".//wps:txbx", NS)
            + body.findall(".//v:textbox", NS)
        )
        field_nodes = body.findall(".//w:instrText", NS)

        diagnostics: List[Dict[str, object]] = []

        if drawings:
            diagnostics.append(
                {
                    "code": "UNSUPPORTED_DRAWING_DETECTED",
                    "severity": "info",
                    "message": "Drawing nodes detected in DOCX body.",
                    "count": len(drawings),
                }
            )
        if pict_nodes:
            diagnostics.append(
                {
                    "code": "UNSUPPORTED_PICT_DETECTED",
                    "severity": "info",
                    "message": "Pict nodes detected in DOCX body.",
                    "count": len(pict_nodes),
                }
            )
        if textbox_nodes:
            diagnostics.append(
                {
                    "code": "UNSUPPORTED_TEXTBOX_DETECTED",
                    "severity": "warning",
                    "message": "Text box content detected and requires semantic review.",
                    "count": len(textbox_nodes),
                }
            )
        if field_nodes:
            diagnostics.append(
                {
                    "code": "UNSUPPORTED_FIELD_CODE_DETECTED",
                    "severity": "warning",
                    "message": "Field codes detected and require semantic review.",
                    "count": len(field_nodes),
                }
            )
        if comments_present:
            diagnostics.append(
                {
                    "code": "COMMENTS_PRESENT",
                    "severity": "info",
                    "message": "comments.xml exists in source document.",
                    "count": comments_text_count,
                }
            )
        if tracked_changes_detected or track_revisions_enabled:
            diagnostics.append(
                {
                    "code": "TRACKED_CHANGES_PRESENT",
                    "severity": "warning",
                    "message": "Tracked changes markers or revision tracking setting detected.",
                }
            )

        blocks: List[Dict[str, object]] = []
        block_index = 0
        paragraph_index = 0
        table_index = 0

        for node in list(body):
            node_tag = node.tag.split("}")[-1]

            if node_tag == "p":
                paragraph_index += 1
                parsed = _parse_paragraph_runs(node)
                meta = _paragraph_meta(node, style_names, style_outlines)

                block_index += 1
                block_id = f"b{block_index:04d}"
                paragraph_block = {
                    "blockId": block_id,
                    "blockIndex": block_index,
                    "blockType": "paragraph",
                    "sourceTrace": {
                        "part": "word/document.xml",
                        "paragraphIndex": paragraph_index,
                    },
                    "paragraph": {
                        "text": parsed.text,
                        "styleId": meta["styleId"],
                        "styleName": meta["styleName"],
                        "headingLevel": meta["headingLevel"],
                        "numbering": meta["numbering"],
                        "runs": parsed.runs,
                        "explicitPageBreaks": parsed.explicit_page_breaks,
                        "explicitLineBreakCount": parsed.explicit_line_break_count,
                        "lastRenderedPageBreak": parsed.last_rendered_page_break,
                        "attachedUnsupportedConstructs": {
                            "containsDrawing": parsed.contains_drawing,
                            "containsPict": parsed.contains_pict,
                            "containsTextBox": parsed.contains_textbox,
                            "containsFieldCode": parsed.contains_field_code,
                        },
                    },
                }
                blocks.append(paragraph_block)

                if parsed.hidden_text_detected:
                    diagnostics.append(
                        {
                            "code": "HIDDEN_TEXT_DETECTED",
                            "severity": "warning",
                            "message": "Paragraph contains hidden text runs.",
                            "sourceTrace": {
                                "part": "word/document.xml",
                                "paragraphIndex": paragraph_index,
                                "blockId": block_id,
                            },
                        }
                    )

                for page_break in parsed.explicit_page_breaks:
                    block_index += 1
                    blocks.append(
                        {
                            "blockId": f"b{block_index:04d}",
                            "blockIndex": block_index,
                            "blockType": "explicitPageBreak",
                            "sourceTrace": {
                                "part": "word/document.xml",
                                "paragraphIndex": paragraph_index,
                                "paragraphBlockId": block_id,
                                "runIndex": page_break["runIndex"],
                                "breakIndex": page_break["breakIndex"],
                            },
                        }
                    )

            elif node_tag == "tbl":
                table_index += 1
                rows = node.findall("w:tr", NS)
                tbl_grid = node.find("w:tblGrid", NS)
                grid_columns = len(tbl_grid.findall("w:gridCol", NS)) if tbl_grid is not None else 0

                row_payloads: List[Dict[str, object]] = []
                for row_index, row in enumerate(rows, start=1):
                    cell_payloads: List[Dict[str, object]] = []
                    cells = row.findall("w:tc", NS)
                    for cell_index, cell in enumerate(cells, start=1):
                        payload = _table_cell_payload(
                            cell,
                            style_names,
                            style_outlines,
                            diagnostics,
                            table_index,
                            row_index,
                            cell_index,
                        )
                        payload["cellIndex"] = cell_index
                        payload["sourceTrace"] = {
                            "part": "word/document.xml",
                            "tableIndex": table_index,
                            "rowIndex": row_index,
                            "cellIndex": cell_index,
                        }
                        cell_payloads.append(payload)
                    row_payloads.append(
                        {
                            "rowIndex": row_index,
                            "cellCount": len(cell_payloads),
                            "cells": cell_payloads,
                            "sourceTrace": {
                                "part": "word/document.xml",
                                "tableIndex": table_index,
                                "rowIndex": row_index,
                            },
                        }
                    )

                block_index += 1
                blocks.append(
                    {
                        "blockId": f"b{block_index:04d}",
                        "blockIndex": block_index,
                        "blockType": "table",
                        "sourceTrace": {
                            "part": "word/document.xml",
                            "tableIndex": table_index,
                        },
                        "table": {
                            "tableIndex": table_index,
                            "rowCount": len(row_payloads),
                            "gridColumnCount": grid_columns,
                            "rows": row_payloads,
                        },
                    }
                )

            elif node_tag == "sectPr":
                # Section properties are captured in documentFeatures and are not represented as semantic content blocks.
                continue
            else:
                diagnostics.append(
                    {
                        "code": "UNSUPPORTED_TOP_LEVEL_BLOCK_DETECTED",
                        "severity": "warning",
                        "message": f"Unsupported top-level body node detected: {node_tag}",
                        "sourceTrace": {
                            "part": "word/document.xml",
                            "nodeTag": node_tag,
                        },
                    }
                )

        contract: Dict[str, object] = {
            "schemaVersion": "1.0",
            "source": {
                "file": _safe_source_name(docx_path),
                "sha256": source_sha,
                "coreProperties": core_properties,
            },
            "documentFeatures": {
                "commentsPresent": comments_present,
                "commentsTextCount": comments_text_count,
                "trackedChangesDetected": tracked_changes_detected,
                "trackRevisionsEnabled": track_revisions_enabled,
                "headersPresent": has_header,
                "footersPresent": has_footer,
                "relationships": [
                    {
                        "id": rid,
                        "type": rels[rid].get("type", ""),
                        "target": rels[rid].get("target", ""),
                    }
                    for rid in sorted(rels.keys())
                ],
                "stylesPartPresent": styles_root is not None,
                "numberingPartPresent": numbering_xml_present,
                "settingsPartPresent": settings_root is not None,
                "drawingsCount": len(drawings),
                "pictCount": len(pict_nodes),
                "textBoxCount": len(textbox_nodes),
                "fieldCodeCount": len(field_nodes),
            },
            "diagnostics": diagnostics,
            "blocks": blocks,
        }

        # Canonicalize contract to enforce deterministic key ordering for in-memory consumers.
        canonical = json.loads(_canonical_json_bytes(contract).decode("utf-8"))
        return canonical


def raw_contract_json_bytes(contract: Dict[str, object]) -> bytes:
    return _canonical_json_bytes(contract)
