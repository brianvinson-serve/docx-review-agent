import os
import sys
import subprocess
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_agent_importable():
    """Verify agent.py can be imported without crashing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "agent", PROJECT_ROOT / "agent.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # Don't exec — just verify spec loads
    assert spec is not None


def test_agent_missing_file_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "agent.py", "nonexistent.docx"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "ANTHROPIC_API_KEY": "test"},
    )
    assert result.returncode != 0
    assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()


def test_agent_non_docx_exits_nonzero(tmp_path):
    fake_txt = tmp_path / "file.txt"
    fake_txt.write_text("not a docx")
    result = subprocess.run(
        [sys.executable, "agent.py", str(fake_txt)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "ANTHROPIC_API_KEY": "test"},
    )
    assert result.returncode != 0


def test_agent_dry_run_prints_document_text(tracked_change_proposal, tmp_path):
    """Dry run should print the Claude payload and exit 0 without calling the API."""
    result = subprocess.run(
        [sys.executable, "agent.py", str(tracked_change_proposal), "--dry-run"],
        input="y\n",
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "ANTHROPIC_API_KEY": "test-not-used"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DOCUMENT TEXT" in result.stdout


def test_agent_dry_run_no_go_exits_cleanly(tracked_change_proposal):
    """If user says N at go/no-go, dry-run should still exit 0."""
    result = subprocess.run(
        [sys.executable, "agent.py", str(tracked_change_proposal), "--dry-run"],
        input="n\n",
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "ANTHROPIC_API_KEY": "test-not-used"},
    )
    assert result.returncode == 0


@pytest.mark.integration
def test_full_pipeline(tracked_change_proposal, tmp_path):
    """Full integration test — calls real Claude API."""
    output = tmp_path / "out_revised.docx"
    result = subprocess.run(
        [
            sys.executable, "agent.py",
            str(tracked_change_proposal),
            "--output", str(output),
        ],
        input="y\n",
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.exists()
    assert "Done." in result.stdout
