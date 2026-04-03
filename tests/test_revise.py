import pytest
from revise import _build_prompt


def test_build_prompt_includes_document_text(clean_sow):
    from extract import extract_document
    extracted = extract_document(clean_sow)
    prompt = _build_prompt(extracted)
    assert "DOCUMENT TEXT" in prompt
    assert "statement of work" in prompt.lower()


def test_build_prompt_includes_tracked_changes(tracked_change_proposal):
    from extract import extract_document
    extracted = extract_document(tracked_change_proposal)
    prompt = _build_prompt(extracted)
    assert "TRACKED CHANGES" in prompt
    assert "Jane Reviewer" in prompt


def test_build_prompt_includes_comments(table_comment_doc):
    from extract import extract_document
    extracted = extract_document(table_comment_doc)
    prompt = _build_prompt(extracted)
    assert "REVIEWER COMMENTS" in prompt
    assert "Alice Reviewer" in prompt


def test_build_prompt_no_changes_note(clean_sow):
    from extract import extract_document
    extracted = extract_document(clean_sow)
    prompt = _build_prompt(extracted)
    # Clean SOW has no changes — prompt should note this
    assert "No tracked changes" in prompt or "edits" in prompt.lower()


@pytest.mark.integration
def test_revise_returns_valid_structure(table_comment_doc):
    """Calls the real Claude API. Run with: pytest -m integration"""
    from extract import extract_document
    from revise import revise_with_claude
    extracted = extract_document(table_comment_doc)
    result = revise_with_claude(extracted)
    assert "edits" in result
    assert "flagged_comments" in result
    assert isinstance(result["edits"], list)
    assert isinstance(result["flagged_comments"], list)
