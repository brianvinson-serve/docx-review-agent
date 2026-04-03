import pytest
from extract import extract_document
from feasibility import analyze


def test_analyze_returns_true_on_yes(clean_sow, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    result = analyze(extract_document(clean_sow), clean_sow)
    assert result is True


def test_analyze_returns_false_on_no(clean_sow, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = analyze(extract_document(clean_sow), clean_sow)
    assert result is False


def test_analyze_returns_false_on_empty_input(clean_sow, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    result = analyze(extract_document(clean_sow), clean_sow)
    assert result is False


def test_analyze_prints_document_summary(clean_sow, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    analyze(extract_document(clean_sow), clean_sow)
    captured = capsys.readouterr()
    assert "clean_sow.docx" in captured.out
    assert "Confidence" in captured.out


def test_analyze_reports_no_changes(clean_sow, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    analyze(extract_document(clean_sow), clean_sow)
    captured = capsys.readouterr()
    assert "0" in captured.out  # 0 tracked changes


def test_analyze_handles_tracked_changes(tracked_change_proposal, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    analyze(extract_document(tracked_change_proposal), tracked_change_proposal)
    captured = capsys.readouterr()
    assert "tracked" in captured.out.lower() or "change" in captured.out.lower()


def test_analyze_handles_comments(table_comment_doc, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    analyze(extract_document(table_comment_doc), table_comment_doc)
    captured = capsys.readouterr()
    assert "comment" in captured.out.lower()
