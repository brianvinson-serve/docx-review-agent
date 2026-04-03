"""
Stage 4: Apply edits surgically to the original document XML.

Strategy:
1. Accept tracked changes directly in the original XML (unwrap w:ins, remove w:del)
2. Strip all comment markers
3. Merge adjacent same-format runs within each paragraph (enables text search)
4. Apply Claude's find/replace edits as targeted text-node substitutions
5. Clear comments.xml
6. Repack as .docx

Never rebuilds from scratch. All formatting, styles, headers, footers preserved.
"""
import zipfile
import tempfile
from pathlib import Path
from lxml import etree

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WNS}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

EMPTY_COMMENTS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:comments xmlns:w="{WNS}"/>'
).encode("utf-8")

EMPTY_EXTENDED_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<root xmlns:w="{WNS}"/>'
).encode("utf-8")


def _tag(local: str) -> str:
    return f"{W}{local}"


def _accept_tracked_changes(root) -> None:
    """
    Accept all tracked changes in-place.
    Pass 1: Remove all w:del elements (and everything inside them).
    Pass 2: Unwrap all w:ins elements (keep their children).
    """
    # Pass 1: remove deletions (collect first, then remove to avoid mutation issues)
    for del_el in list(root.findall(f".//{_tag('del')}"))[::-1]:
        parent = del_el.getparent()
        if parent is not None:
            parent.remove(del_el)

    # Pass 2: unwrap insertions (process in document order — safe with pre-collected list)
    for ins in list(root.findall(f".//{_tag('ins')}")):
        parent = ins.getparent()
        if parent is None:
            continue
        idx = list(parent).index(ins)
        for child in list(ins):
            parent.insert(idx, child)
            idx += 1
        parent.remove(ins)


def _strip_comment_markers(root) -> None:
    """Remove commentRangeStart, commentRangeEnd, and commentReference elements."""
    tags_to_strip = [
        _tag("commentRangeStart"),
        _tag("commentRangeEnd"),
        _tag("commentReference"),
        _tag("rPrChange"),
        _tag("pPrChange"),
        _tag("sectPrChange"),
    ]
    for tag in tags_to_strip:
        for el in list(root.findall(f".//{tag}")):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)


def _rpr_key(rpr_el) -> str:
    """Canonical string key for run properties (for comparison)."""
    if rpr_el is None:
        return ""
    return etree.tostring(rpr_el, encoding="unicode")


def _merge_runs(root) -> None:
    """
    Merge adjacent w:r elements with identical w:rPr within each paragraph.
    Only merges direct children of w:p — does not touch runs inside hyperlinks, etc.
    """
    for para in root.findall(f".//{_tag('p')}"):
        children = list(para)
        i = 0
        while i < len(children) - 1:
            curr = children[i]
            nxt = children[i + 1]

            if curr.tag != _tag("r") or nxt.tag != _tag("r"):
                i += 1
                continue

            if _rpr_key(curr.find(_tag("rPr"))) != _rpr_key(nxt.find(_tag("rPr"))):
                i += 1
                continue

            curr_t = curr.find(_tag("t"))
            nxt_t = nxt.find(_tag("t"))

            if curr_t is None:
                curr_t = etree.SubElement(curr, _tag("t"))
                curr_t.text = ""

            curr_t.text = (curr_t.text or "") + (nxt_t.text if nxt_t is not None else "")

            # Preserve whitespace attribute if merged text contains spaces
            if " " in (curr_t.text or ""):
                curr_t.set(XML_SPACE, "preserve")

            para.remove(nxt)
            children = list(para)
            # Don't increment i — try to merge with the new next element


def _apply_edits(root, edits: list) -> tuple:
    """
    Apply find/replace edits to w:t text nodes.
    Returns (applied_count, miss_count).
    """
    applied = 0
    misses = 0

    for edit in edits:
        find_str = edit.get("find", "")
        replace_str = edit.get("replace", "")
        if not find_str:
            continue

        found = False
        for t_el in root.findall(f".//{_tag('t')}"):
            text = t_el.text or ""
            if find_str in text:
                t_el.text = text.replace(find_str, replace_str, 1)
                if " " in (t_el.text or ""):
                    t_el.set(XML_SPACE, "preserve")
                found = True
                applied += 1
                break

        if not found:
            preview = find_str[:60]
            print(f"  [miss] Could not locate: \"{preview}\"")
            misses += 1

    return applied, misses


def rebuild_document(original_path: Path, edits_dict: dict, output_path: Path) -> dict:
    """
    Main entry point. Applies all changes to original document XML surgically.
    Returns {"applied": int, "misses": int}.
    """
    original_path = Path(original_path)
    output_path = Path(output_path)

    assert output_path.resolve() != original_path.resolve(), (
        "Output path must differ from input path"
    )

    edits = edits_dict.get("edits", [])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Unzip original
        with zipfile.ZipFile(original_path) as z:
            z.extractall(tmp)

        # Parse document.xml
        doc_xml_path = tmp / "word" / "document.xml"
        doc_xml = doc_xml_path.read_bytes()
        root = etree.fromstring(doc_xml)

        # Stage A: Accept tracked changes
        _accept_tracked_changes(root)

        # Stage B: Strip comment markers
        _strip_comment_markers(root)

        # Stage C: Merge runs (normalize for text search)
        _merge_runs(root)

        # Stage D: Apply edits
        applied, misses = _apply_edits(root, edits)

        # Write modified document.xml back
        doc_xml_path.write_bytes(
            etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        )

        # Clear comments.xml
        comments_path = tmp / "word" / "comments.xml"
        if comments_path.exists():
            comments_path.write_bytes(EMPTY_COMMENTS_XML)

        # Clear extended comment files if present
        for extra in [
            "word/commentsExtended.xml",
            "word/commentsExtensible.xml",
            "word/commentsIds.xml",
        ]:
            p = tmp / extra
            if p.exists():
                p.write_bytes(EMPTY_EXTENDED_XML)

        # Repack as docx
        output_path.unlink(missing_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for f in sorted(tmp.rglob("*")):
                if f.is_file():
                    zout.write(f, f.relative_to(tmp))

    return {"applied": applied, "misses": misses}
