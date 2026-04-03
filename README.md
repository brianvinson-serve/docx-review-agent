# docx-review-agent

A CLI tool that accepts tracked changes and resolves reviewer comments in Word documents (.docx) using Claude — without touching the formatting.

## How it works

1. **Extract** — parses tracked changes and comments from the original document XML
2. **Feasibility** — checks for complexity risks and asks for go/no-go before making any API calls
3. **Revise** — sends the document and comments to Claude, receives targeted find/replace edits as JSON
4. **Rebuild** — applies edits surgically to the original XML; headers, footers, styles, tables, and images are untouched

## Setup

```bash
git clone https://github.com/brianvinson-serve/docx-review-agent.git
cd docx-review-agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Usage

```bash
# Basic
python agent.py path/to/document.docx

# See what Claude would receive, without calling the API
python agent.py path/to/document.docx --dry-run

# Override model or output path
python agent.py path/to/document.docx --model claude-opus-4-6 --output clean.docx
```

Output: `{original_name}_revised.docx` in the same directory as the input file.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (required) | — |
| `DOCX_AGENT_MODEL` | Model to use | `claude-sonnet-4-6` |

Set in `.env` (copy from `.env.example`) or as environment variables. `--model` flag overrides `DOCX_AGENT_MODEL`.

## What it preserves

Because the tool edits only `word/document.xml` and repacks the original ZIP:

- Page layout, margins, headers, footers
- All table styles and formatting
- Images and media
- All named paragraph and character styles
- Fonts, colors, spacing

## Running tests

```bash
# Generate test fixtures first (one-time)
python tests/fixtures/create_fixtures.py

# Run unit tests (no API calls)
pytest -m "not integration" -v

# Run integration tests (requires ANTHROPIC_API_KEY)
pytest -m integration -v
```

## Known limitations

- Comment edits that target text split across differently-formatted runs may not locate their target. These are reported as misses in the terminal output.
- Structural table edits (add/remove rows) are not supported — only text substitution within table cells.
