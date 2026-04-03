"""
Stage 2: Pre-flight feasibility analysis.
Inspects the document for risk factors, prints a confidence report,
and asks the user for go/no-go before any Claude API call.
"""
import zipfile
from pathlib import Path
from lxml import etree

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WNS}}}"


def _tag(local: str) -> str:
    return f"{W}{local}"


def _has_nested_tracked_changes(doc_root) -> bool:
    for ins in doc_root.findall(f".//{_tag('ins')}"):
        if ins.find(f".//{_tag('ins')}") is not None:
            return True
        if ins.find(f".//{_tag('del')}") is not None:
            return True
    for del_el in doc_root.findall(f".//{_tag('del')}"):
        if del_el.find(f".//{_tag('ins')}") is not None:
            return True
        if del_el.find(f".//{_tag('del')}") is not None:
            return True
    return False


def _avg_runs_per_paragraph(doc_root) -> float:
    paras = doc_root.findall(f".//{_tag('p')}")
    counts = []
    for p in paras:
        text_len = sum(len(t.text or "") for t in p.findall(f".//{_tag('t')}"))
        if text_len < 20:
            continue
        runs = p.findall(f".//{_tag('r')}")
        counts.append(len(runs))
    return sum(counts) / len(counts) if counts else 0.0


def _comment_ids_in_tables(doc_root) -> list:
    ids = []
    for tbl in doc_root.findall(f".//{_tag('tbl')}"):
        for crs in tbl.findall(f".//{_tag('commentRangeStart')}"):
            cid = crs.get(_tag("id"))
            if cid:
                ids.append(cid)
    return ids


def analyze(extracted: dict, source_path: Path) -> bool:
    """
    Print pre-flight report and return True (proceed) or False (abort).
    """
    source_path = Path(source_path)
    n_changes = len(extracted["tracked_changes"])
    n_comments = len(extracted["comments"])

    # Re-parse XML for structural checks
    with zipfile.ZipFile(source_path) as z:
        doc_xml = z.read("word/document.xml")
    doc_root = etree.fromstring(doc_xml)

    risks = []

    if n_changes == 0 and n_comments == 0:
        risks.append(("WARN", "No tracked changes or comments found. Nothing to apply."))

    if _has_nested_tracked_changes(doc_root):
        risks.append(("MEDIUM", "Nested tracked changes detected. Outer changes processed first."))

    avg_runs = _avg_runs_per_paragraph(doc_root)
    if avg_runs > 8:
        risks.append((
            "MEDIUM",
            f"High run fragmentation (avg {avg_runs:.1f} runs/paragraph). "
            "Some comment edits may not locate their target text."
        ))

    table_comment_ids = _comment_ids_in_tables(doc_root)
    if table_comment_ids:
        risks.append((
            "MEDIUM",
            f"{len(table_comment_ids)} comment(s) anchored inside table cells. "
            "Text substitution works; structural table edits will not."
        ))

    estimated_tokens = sum(len(p["text"]) for p in extracted["clean_paragraphs"]) // 4
    if estimated_tokens > 100_000:
        risks.append((
            "LOW",
            f"Large document (~{estimated_tokens:,} tokens). Will be processed in chunks."
        ))

    # Determine confidence
    medium_count = sum(1 for level, _ in risks if level == "MEDIUM")
    has_warn = any(level == "WARN" for level, _ in risks)

    if medium_count >= 2:
        confidence = "LOW"
    elif medium_count == 1 or has_warn:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    # Print report
    n_ins = sum(1 for c in extracted["tracked_changes"] if c["type"] == "insertion")
    n_del = sum(1 for c in extracted["tracked_changes"] if c["type"] == "deletion")

    print(f"\ndocx-review-agent: Pre-flight Analysis")
    print("=" * 50)
    print(f"Document:  {source_path.name}")
    print(f"Changes:   {n_changes} tracked ({n_ins} insertions, {n_del} deletions)")
    print(f"Comments:  {n_comments}")
    print()
    print(f"Confidence: {confidence}")

    if not risks:
        print("  No risk factors detected.")
    for level, msg in risks:
        prefix = "  [!]" if level in ("MEDIUM", "WARN") else "  [i]"
        print(f"{prefix} {msg}")

    print()
    resp = input("Proceed with revision? [y/N] ")
    return resp.strip().lower() == "y"
