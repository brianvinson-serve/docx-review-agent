"""
Stage 1: Extract tracked changes, comments, and clean paragraph text from a .docx file.
No side effects — does not modify the source file.
"""
import zipfile
from pathlib import Path
from lxml import etree

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WNS}}}"


def _tag(local: str) -> str:
    return f"{W}{local}"


def _get_para_style(para_el) -> str:
    ppr = para_el.find(_tag("pPr"))
    if ppr is None:
        return "Normal"
    pstyle = ppr.find(_tag("pStyle"))
    if pstyle is None:
        return "Normal"
    return pstyle.get(_tag("val"), "Normal")


def _extract_tracked_changes(doc_root) -> list:
    changes = []

    # Insertions: w:ins elements containing w:t text
    for ins in doc_root.findall(f".//{_tag('ins')}"):
        author = ins.get(_tag("author"), "Unknown")
        date = ins.get(_tag("date"), "")
        text = "".join(t.text or "" for t in ins.findall(f".//{_tag('t')}")).strip()
        if not text:
            continue
        # Get surrounding paragraph text for context
        parent = ins.getparent()
        while parent is not None and parent.tag != _tag("p"):
            parent = parent.getparent()
        context = ""
        if parent is not None:
            context = "".join(
                t.text or "" for t in parent.findall(f".//{_tag('t')}")
            ).strip()[:200]
        changes.append({
            "type": "insertion",
            "text": text,
            "author": author,
            "date": date,
            "context": context,
        })

    # Deletions: w:del elements containing w:delText
    for del_el in doc_root.findall(f".//{_tag('del')}"):
        author = del_el.get(_tag("author"), "Unknown")
        date = del_el.get(_tag("date"), "")
        text = "".join(
            t.text or "" for t in del_el.findall(f".//{_tag('delText')}")
        ).strip()
        if not text:
            continue
        parent = del_el.getparent()
        while parent is not None and parent.tag != _tag("p"):
            parent = parent.getparent()
        context = ""
        if parent is not None:
            context = "".join(
                t.text or "" for t in parent.findall(f".//{_tag('t')}")
            ).strip()[:200]
        changes.append({
            "type": "deletion",
            "original_text": text,
            "author": author,
            "date": date,
            "context": context,
        })

    return changes


def _extract_comments(doc_root, comments_xml: bytes | None) -> list:
    if comments_xml is None:
        return []

    try:
        comments_root = etree.fromstring(comments_xml)
    except etree.XMLSyntaxError:
        return []

    # Build id -> comment body + author map
    comments_map = {}
    for comment_el in comments_root.findall(f".//{_tag('comment')}"):
        cid = comment_el.get(_tag("id"))
        author = comment_el.get(_tag("author"), "Unknown")
        date = comment_el.get(_tag("date"), "")
        body = "".join(
            t.text or "" for t in comment_el.findall(f".//{_tag('t')}")
        ).strip()
        if cid is not None:
            comments_map[cid] = {"author": author, "date": date, "body": body}

    # Find anchor text for each comment using commentRangeStart/End markers
    results = []
    for cid, cdata in comments_map.items():
        collecting = False
        anchor_parts = []
        for el in doc_root.iter():
            if el.tag == _tag("commentRangeStart") and el.get(_tag("id")) == cid:
                collecting = True
                continue
            if el.tag == _tag("commentRangeEnd") and el.get(_tag("id")) == cid:
                collecting = False
                break
            if collecting and el.tag == _tag("t") and el.text:
                anchor_parts.append(el.text)
        results.append({
            "id": cid,
            "author": cdata["author"],
            "date": cdata["date"],
            "comment_body": cdata["body"],
            "anchor_text": "".join(anchor_parts).strip(),
        })

    results.sort(key=lambda c: int(c["id"]) if c["id"].isdigit() else 0)
    return results


def _extract_clean_paragraphs(doc_root) -> list:
    """
    Return paragraphs with tracked changes resolved:
    - Include w:t text (including text inside w:ins)
    - Exclude w:delText (text inside w:del)
    """
    paragraphs = []
    for para in doc_root.findall(f".//{_tag('p')}"):
        style = _get_para_style(para)
        text_parts = []
        for el in para.iter():
            if el.tag == _tag("t") and el.text:
                # Exclude if inside a w:del
                ancestor = el.getparent()
                in_del = False
                while ancestor is not None:
                    if ancestor.tag == _tag("del"):
                        in_del = True
                        break
                    ancestor = ancestor.getparent()
                if not in_del:
                    text_parts.append(el.text)
        text = "".join(text_parts).strip()
        if text:
            paragraphs.append({"style": style, "text": text})
    return paragraphs


def extract_document(docx_path: Path) -> dict:
    """
    Main entry point. Returns dict with:
      tracked_changes, comments, clean_paragraphs, source_path
    """
    docx_path = Path(docx_path)

    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read("word/document.xml")
        try:
            comments_xml = z.read("word/comments.xml")
        except KeyError:
            comments_xml = None

    doc_root = etree.fromstring(doc_xml)

    return {
        "tracked_changes": _extract_tracked_changes(doc_root),
        "comments": _extract_comments(doc_root, comments_xml),
        "clean_paragraphs": _extract_clean_paragraphs(doc_root),
        "source_path": str(docx_path),
    }
