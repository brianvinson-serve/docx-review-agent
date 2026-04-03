# DOCX Review & Revision Agent — Design Spec

**Date:** 2026-04-02  
**Status:** Approved  
**Location:** `/Users/bvinson/AnthMCP/07_Experiments/DOCX_Review_Revision_Agent/`

---

## Purpose

A CLI tool that reads a Word document (.docx), extracts tracked changes and reviewer comments, runs a feasibility pre-flight, sends a targeted revision request to Claude, and applies Claude's edits surgically to the original document XML — preserving all formatting, styles, headers, footers, tables, and images.

---

## Core Principle

**Never rebuild from scratch. Never go through markdown.**

The original document ZIP is the source of truth. Only `word/document.xml` is modified. All other files in the ZIP (headers, footers, styles, theme, media) are preserved exactly.

---

## Pipeline

```
extract.py  →  feasibility.py  →  [go/no-go]  →  revise.py  →  rebuild.py
(read XML)     (analyze + report)   (user gate)    (Claude JSON)   (surgical XML)
```

---

## Module Specifications

### `extract.py`

**Responsibility:** Unzip the .docx and parse XML into structured data. No side effects. No judgment calls.

**Inputs:** Path to `.docx` file.

**Outputs:** Dict containing:
- `tracked_changes`: List of `{type, text/original_text, author, date, context_paragraph}`
- `comments`: List of `{id, author, date, comment_body, anchor_text}`
- `paragraphs`: List of `{style, text, runs}` — clean text after conceptually accepting tracked changes, used for Claude's reading copy
- `source_path`: String

**Implementation notes:**
- Unzip to temp directory (do not modify in place)
- Parse `word/document.xml` with lxml
- Parse `word/comments.xml` if present
- For tracked changes: find `<w:ins>` (insertions) and `<w:del>` (deletions) with author/date attributes
- For comments: match `<w:commentRangeStart>` / `<w:commentRangeEnd>` pairs to comment IDs; read full comment body from `comments.xml`
- Produce "clean text" by walking paragraphs: include `<w:ins>` text, exclude `<w:del>` text — this is what Claude reads
- Do NOT modify source file

---

### `feasibility.py`

**Responsibility:** Analyze the extracted document and produce a human-readable confidence report. Gate the pipeline with a go/no-go prompt.

**Inputs:** Extracted dict from `extract.py`, source path.

**Outputs:** Printed report to terminal. Returns `True` (proceed) or `False` (abort).

**Checks performed:**

| Check | Logic | Risk level |
|---|---|---|
| No changes or comments | Zero tracked changes AND zero comments | Warn — nothing to do |
| Nested tracked changes | `<w:ins>` or `<w:del>` containing another `<w:ins>` or `<w:del>` | Medium |
| Run fragmentation | Any paragraph with avg >8 `<w:r>` elements per 10 words of text | Medium — may affect find/replace |
| Comments in table cells | Comment range anchors found inside `<w:tbl>` elements | Medium |
| Large document | Estimated token count >100k | Low — will chunk, note it |
| Ambiguous comment language | Comments with no clear directive and no clear question | Low — Claude will classify |

**Output format:**
```
docx-agent: Pre-flight Analysis
================================
Document:   my_document.docx
Changes:    4 tracked (3 insertions, 1 deletion)
Comments:   6 (estimated: 4 actionable, 1 question, 1 informational)

Confidence: HIGH
  No nested tracked changes detected.
  Run fragmentation: low (avg 2.1 runs/sentence).
  No comments anchored inside table cells.

Proceed with revision? [y/N]
```

**Confidence levels:**
- **HIGH** — no medium/high risk factors detected
- **MEDIUM** — one or more medium-risk factors; explains specific concern
- **LOW** — nested tracked changes, heavy table comment anchors, or severe fragmentation; strongly recommends manual review

---

### `revise.py`

**Responsibility:** Send the extracted content to Claude and receive structured JSON edits.

**Inputs:** Extracted dict, model name.

**Outputs:** Dict:
```json
{
  "edits": [
    {
      "find": "exact phrase to locate in document",
      "replace": "replacement text",
      "context": "surrounding sentence fragment for disambiguation"
    }
  ],
  "flagged_comments": [
    {
      "author": "Reviewer name",
      "comment": "Original comment text",
      "anchor": "Text the comment was attached to",
      "reason": "Why this needs a human decision"
    }
  ]
}
```

**What Claude receives:**
1. System prompt defining the three comment buckets and output schema
2. User message containing:
   - Clean document text (post-tracked-change acceptance), formatted with headings
   - Tracked changes list: each insertion and deletion with context
   - Comments list: each with anchor text and full comment body

**What Claude does:**
- Accepts all tracked insertions (already reflected in clean text — no action needed)
- Confirms all tracked deletions removed (already reflected — no action needed)
- For each actionable comment: produces an `edit` entry with find/replace targeting the anchor text
- For each question/decision comment: produces a `flagged_comment` entry, no edit
- For each informational comment: produces nothing (comment will be stripped in rebuild)

**System prompt (abridged):**
> You are a document editor. You will receive the clean text of a Word document (with tracked changes already applied) and a list of reviewer comments. Your job is to produce a JSON response with two keys: "edits" (list of find/replace operations for actionable comments) and "flagged_comments" (list of comments requiring human decision). Do not return the full document. Only return edits for comments with clear editorial direction. Preserve all other text exactly.

**Chunking:** If estimated token count exceeds 150k, split by top-level heading sections. Each chunk receives all comments (Claude applies only those relevant to its section). Merge results: combine all `edits` and `flagged_comments` arrays.

**Retry:** 3 attempts with exponential backoff on rate limit or API errors.

---

### `rebuild.py`

**Responsibility:** Apply all changes to the original document XML surgically, producing a clean output file.

**Inputs:** Original `.docx` path, JSON edits dict from `revise.py`, output path.

**Process (in order):**

1. **Unzip** original to temp directory
2. **Parse** `word/document.xml` with lxml
3. **Accept tracked changes:**
   - Find all `<w:ins>` elements: unwrap (move children to parent, remove `<w:ins>` wrapper)
   - Find all `<w:del>` elements: remove entirely (including all children)
   - Process outer-first on nested tracked changes
4. **Strip comment markers:**
   - Remove all `<w:commentRangeStart>`, `<w:commentRangeEnd>`, `<w:commentReference>` elements
5. **Merge runs** within each paragraph:
   - Walk each `<w:p>` element
   - For consecutive `<w:r>` elements with identical `<w:rPr>` (or both lacking `<w:rPr>`), merge their `<w:t>` text content into the first run and remove the subsequent run
   - This normalizes fragmented text for reliable string search
6. **Apply edits:**
   - For each edit in `edits` list: search all `<w:t>` text nodes for the `find` string; when found, replace with `replace` string
   - If not found: log a warning to terminal (`[miss] Could not locate: "find phrase"`) — do not abort
   - If found in multiple locations: use `context` field to disambiguate; if still ambiguous, apply to first match and log a note
7. **Clear comments.xml:** Replace with empty-but-valid XML
8. **Clear extended comment files** if present (`commentsExtended.xml`, `commentsExtensible.xml`, `commentsIds.xml`)
9. **Repack** temp directory as ZIP with `.docx` extension
10. **Write** to output path

**Safety:** Assert output path != input path. Never overwrite source file.

---

### `agent.py`

**Responsibility:** CLI entry point. Orchestrates all stages. Handles errors and prints final summary.

**CLI interface:**
```bash
python agent.py path/to/document.docx [--model MODEL] [--output OUTPUT] [--dry-run]
```

**Flags:**
- `--model` — override Claude model (default: `claude-sonnet-4-6`)
- `--output` — override output filename (default: `{stem}_revised.docx` in same directory)
- `--dry-run` — run extract + feasibility only; print what Claude would receive; do not call Claude or write output

**Flow:**
1. Validate input file exists and is `.docx`
2. Run extract
3. Run feasibility → if user says N, exit 0
4. If `--dry-run`, print Claude payload and exit 0
5. Run revise (Claude call)
6. Run rebuild
7. Print summary:
   - Output file path and size
   - Number of tracked changes accepted
   - Number of comment edits applied
   - Number of edit misses (if any)
   - Flagged comments (formatted as a readable list)
8. Size ratio warning if output < 30% of input size

---

## Directory Structure

```
07_Experiments/DOCX_Review_Revision_Agent/
├── agent.py
├── extract.py
├── feasibility.py
├── revise.py
├── rebuild.py
├── requirements.txt
├── .env.example          # ANTHROPIC_API_KEY=, DOCX_AGENT_MODEL=
├── .gitignore            # ignores .env, __pycache__, *.pyc, output *.docx
├── README.md
├── tests/
│   ├── test_pipeline.py
│   └── fixtures/
│       ├── clean_sow.docx
│       ├── tracked_change_proposal.docx
│       └── table_comment_doc.docx
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-02-docx-review-revision-agent-design.md
```

---

## Configuration

All runtime configuration is read from environment variables. No secrets or model preferences in code.

| Env var | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (required) | None — exits with clear error if missing |
| `DOCX_AGENT_MODEL` | Claude model to use | `claude-sonnet-4-6` |

**`.env` support:** If a `.env` file exists in the project directory, it is loaded automatically at startup (via `python-dotenv`). A `.env.example` is committed to the repo; the actual `.env` is gitignored.

**CLI `--model` flag** overrides `DOCX_AGENT_MODEL` when provided.

**For sharing:** Clone the repo, copy `.env.example` to `.env`, add your `ANTHROPIC_API_KEY`. No code changes needed.

---

## Dependencies

```
anthropic>=0.25.0
python-docx>=1.1.0
lxml>=5.0.0
python-dotenv>=1.0.0
```

System: `pandoc` (optional — used only for informational pre-flight token estimation if available)

---

## What This Preserves

Because only `word/document.xml` is modified and all other ZIP contents are untouched:

- Page layout, margins, columns
- Headers and footers (logo, branded footer, page numbers)
- All table styles (including custom styles like Resultant's light-blue header tables)
- All named paragraph and character styles
- Images and media
- Signature blocks
- Fonts, colors, spacing

---

## Known Limitations

1. **Cross-format run boundaries:** If an edit targets text that spans runs with different character formatting (e.g., part bold, part not), the merged run will apply the first run's formatting to the full replacement text. Uncommon in standard consulting document prose.

2. **Edit misses:** If the `find` string doesn't match exactly (punctuation, spacing, or tracked change fragmentation), the edit is skipped and logged. The document is still written; the user reviews the miss log.

3. **Table cell comment edits:** Comments anchored inside table cells work correctly for text substitution. However, if a comment requests structural table changes (add row, change column), the tool cannot execute those — they will appear as misses.

---

## Testing Strategy

Test fixtures live in `tests/fixtures/`. Three documents cover the main risk surface:

| Fixture | What it exercises |
|---|---|
| `clean_sow.docx` | A standard SOW with no tracked changes and no comments. Verifies the no-op path: tool detects nothing to do, warns the user, exits cleanly without writing a corrupted or empty file. |
| `tracked_change_proposal.docx` | A proposal with a mix of insertions and deletions — including at least one nested tracked change. Verifies tracked change acceptance, run merging, and that the output preserves the original template formatting (headers, footers, styles). |
| `table_comment_doc.docx` | A document with reviewer comments anchored inside table cells, plus at least one question-type comment and one informational comment. Verifies comment classification, flagged_comments output, and that table formatting survives untouched. |

**Running tests:**
```bash
python -m pytest tests/
```

Each test runs the full pipeline (extract → feasibility auto-approved → revise → rebuild) against its fixture and asserts:
- Output file exists and is a valid ZIP
- Output file size is within 70–130% of input size
- `word/document.xml` in output does not contain `<w:ins>`, `<w:del>`, or comment markers
- Flagged comments match expected count and content

Tests that call the Claude API are marked `@pytest.mark.integration` and skipped by default (`pytest -m "not integration"` for offline runs).

---

## Success Criteria

- Tracked insertions appear in output as accepted text
- Tracked deletions are absent from output
- Actionable comments result in the targeted text edit
- Question-type comments appear in the flagged summary, text unchanged
- Output file opens cleanly in Word with no validation errors
- Output file preserves all formatting from the original template
- Tool is reusable on any `.docx` without modification
