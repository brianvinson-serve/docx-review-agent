import pytest
from extract import extract_document


def test_extract_returns_required_keys(clean_sow):
    result = extract_document(clean_sow)
    assert "tracked_changes" in result
    assert "comments" in result
    assert "clean_paragraphs" in result
    assert "source_path" in result


def test_extract_no_changes_in_clean_doc(clean_sow):
    result = extract_document(clean_sow)
    assert result["tracked_changes"] == []
    assert result["comments"] == []


def test_extract_clean_doc_has_paragraphs(clean_sow):
    result = extract_document(clean_sow)
    assert len(result["clean_paragraphs"]) >= 2
    texts = [p["text"] for p in result["clean_paragraphs"]]
    assert any("statement of work" in t.lower() for t in texts)


def test_extract_finds_insertion(tracked_change_proposal):
    result = extract_document(tracked_change_proposal)
    insertions = [c for c in result["tracked_changes"] if c["type"] == "insertion"]
    assert len(insertions) >= 1
    assert "newly inserted" in insertions[0]["text"]
    assert insertions[0]["author"] == "Jane Reviewer"


def test_extract_finds_deletion(tracked_change_proposal):
    result = extract_document(tracked_change_proposal)
    deletions = [c for c in result["tracked_changes"] if c["type"] == "deletion"]
    assert len(deletions) >= 1
    assert "old text" in deletions[0]["original_text"]


def test_extract_clean_paragraphs_include_insertions(tracked_change_proposal):
    result = extract_document(tracked_change_proposal)
    full_text = " ".join(p["text"] for p in result["clean_paragraphs"])
    assert "newly inserted" in full_text


def test_extract_clean_paragraphs_exclude_deletions(tracked_change_proposal):
    result = extract_document(tracked_change_proposal)
    full_text = " ".join(p["text"] for p in result["clean_paragraphs"])
    assert "old text" not in full_text


def test_extract_finds_comments(table_comment_doc):
    result = extract_document(table_comment_doc)
    assert len(result["comments"]) >= 1
    comment = result["comments"][0]
    assert comment["author"] == "Alice Reviewer"
    assert "reword" in comment["comment_body"].lower()


def test_extract_comment_has_anchor_text(table_comment_doc):
    result = extract_document(table_comment_doc)
    comment = result["comments"][0]
    assert comment["anchor_text"] != ""
    assert "Please reword" in comment["anchor_text"]


def test_extract_source_path_correct(clean_sow):
    result = extract_document(clean_sow)
    assert result["source_path"] == str(clean_sow)
