import sys
from pathlib import Path

# Allow `import extract`, `import rebuild`, etc. from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def clean_sow():
    return FIXTURES_DIR / "clean_sow.docx"


@pytest.fixture
def tracked_change_proposal():
    return FIXTURES_DIR / "tracked_change_proposal.docx"


@pytest.fixture
def table_comment_doc():
    return FIXTURES_DIR / "table_comment_doc.docx"
