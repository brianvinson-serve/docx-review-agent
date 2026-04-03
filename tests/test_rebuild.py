import zipfile
import pytest
from pathlib import Path
from lxml import etree
from rebuild import rebuild_document

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WNS}}}"


def _read_doc_xml(docx_path: Path) -> etree._Element:
    with zipfile.ZipFile(docx_path) as z:
        return etree.fromstring(z.read("word/document.xml"))


def _full_text(docx_path: Path) -> str:
    from docx import Document
    doc = Document(str(docx_path))
    return " ".join(p.text for p in doc.paragraphs)


def test_rebuild_produces_valid_docx(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    stats = rebuild_document(
        tracked_change_proposal, {"edits": [], "flagged_comments": []}, output
    )
    assert output.exists()
    # Must be a valid ZIP (docx is a ZIP)
    with zipfile.ZipFile(output) as z:
        assert "word/document.xml" in z.namelist()


def test_rebuild_accepts_insertions(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    rebuild_document(
        tracked_change_proposal, {"edits": [], "flagged_comments": []}, output
    )
    root = _read_doc_xml(output)
    assert root.findall(f".//{W}ins") == []
    # Inserted text should be present
    full = _full_text(output)
    assert "newly inserted" in full


def test_rebuild_removes_deletions(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    rebuild_document(
        tracked_change_proposal, {"edits": [], "flagged_comments": []}, output
    )
    root = _read_doc_xml(output)
    assert root.findall(f".//{W}del") == []
    full = _full_text(output)
    assert "old text" not in full


def test_rebuild_strips_comment_markers(table_comment_doc, tmp_path):
    output = tmp_path / "out.docx"
    rebuild_document(
        table_comment_doc, {"edits": [], "flagged_comments": []}, output
    )
    root = _read_doc_xml(output)
    assert root.findall(f".//{W}commentRangeStart") == []
    assert root.findall(f".//{W}commentRangeEnd") == []
    assert root.findall(f".//{W}commentReference") == []


def test_rebuild_applies_edit(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    edits_dict = {
        "edits": [
            {
                "find": "newly inserted",
                "replace": "brand new",
                "context": "This is",
            }
        ],
        "flagged_comments": [],
    }
    stats = rebuild_document(tracked_change_proposal, edits_dict, output)
    full = _full_text(output)
    assert "brand new" in full
    assert "newly inserted" not in full
    assert stats["applied"] == 1
    assert stats["misses"] == 0


def test_rebuild_reports_miss_for_unfindable_text(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    edits_dict = {
        "edits": [
            {
                "find": "this text does not exist in the document at all xyz",
                "replace": "replacement",
                "context": "",
            }
        ],
        "flagged_comments": [],
    }
    stats = rebuild_document(tracked_change_proposal, edits_dict, output)
    assert stats["misses"] == 1
    assert stats["applied"] == 0
    # Output file still written despite miss
    assert output.exists()


def test_rebuild_never_overwrites_source(tracked_change_proposal):
    with pytest.raises(AssertionError):
        rebuild_document(
            tracked_change_proposal,
            {"edits": [], "flagged_comments": []},
            tracked_change_proposal,
        )


def test_rebuild_preserves_non_body_zip_contents(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    rebuild_document(
        tracked_change_proposal, {"edits": [], "flagged_comments": []}, output
    )
    with zipfile.ZipFile(tracked_change_proposal) as orig_z:
        orig_files = set(orig_z.namelist())
    with zipfile.ZipFile(output) as out_z:
        out_files = set(out_z.namelist())
    # All non-document files should be preserved
    preserved = orig_files - {"word/document.xml", "word/comments.xml"}
    for f in preserved:
        assert f in out_files, f"Missing from output: {f}"


def test_rebuild_clears_comments_xml(table_comment_doc, tmp_path):
    output = tmp_path / "out.docx"
    rebuild_document(
        table_comment_doc, {"edits": [], "flagged_comments": []}, output
    )
    with zipfile.ZipFile(output) as z:
        if "word/comments.xml" in z.namelist():
            comments_root = etree.fromstring(z.read("word/comments.xml"))
            assert comments_root.findall(f".//{W}comment") == []


def test_rebuild_returns_stats_dict(tracked_change_proposal, tmp_path):
    output = tmp_path / "out.docx"
    stats = rebuild_document(
        tracked_change_proposal, {"edits": [], "flagged_comments": []}, output
    )
    assert "applied" in stats
    assert "misses" in stats
    assert isinstance(stats["applied"], int)
    assert isinstance(stats["misses"], int)
