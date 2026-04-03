"""
Stage 3: Send extracted document content to Claude.
Returns structured JSON: targeted edits and flagged comments.
"""
import os
import json
import re
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.environ.get("DOCX_AGENT_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
CHUNK_TOKEN_THRESHOLD = 150_000

SYSTEM_PROMPT = """You are a professional document editor. You will receive:
1. The clean text of a Word document (tracked changes already applied)
2. A list of tracked changes that were applied (for context)
3. A list of reviewer comments with their anchor text

Return a JSON object with exactly two keys:

"edits": list of find/replace operations for actionable comments. Each item:
  { "find": "<exact phrase from document>", "replace": "<revised text>", "context": "<surrounding fragment>" }

"flagged_comments": list of comments needing human decision. Each item:
  { "author": "<name>", "comment": "<comment text>", "anchor": "<anchor text>", "reason": "<why human needed>" }

Rules:
- Actionable comments (change/remove/reword/add directives): produce an edit.
- Question/decision comments (confirm/check/is this accurate?/should this): produce a flagged_comment, no edit.
- Informational/FYI comments: produce nothing — they will be stripped automatically.
- "find" must be an exact substring of the clean document text provided.
- Return ONLY valid JSON. No prose, no markdown code fences, no explanation."""


def _build_prompt(extracted: dict) -> str:
    parts = []

    # Clean document text
    parts.append("## DOCUMENT TEXT (tracked changes already applied)\n")
    for para in extracted.get("clean_paragraphs", []):
        text = para.get("text", "").strip()
        style = para.get("style", "Normal")
        if not text:
            continue
        if "Heading1" in style or "Heading 1" in style:
            parts.append(f"# {text}")
        elif "Heading2" in style or "Heading 2" in style:
            parts.append(f"## {text}")
        elif "Heading3" in style or "Heading 3" in style:
            parts.append(f"### {text}")
        else:
            parts.append(text)

    # Tracked changes summary
    tracked = extracted.get("tracked_changes", [])
    if tracked:
        parts.append("\n## TRACKED CHANGES APPLIED\n")
        for tc in tracked:
            if tc["type"] == "insertion":
                parts.append(f'- INSERTED: "{tc["text"]}" (by {tc["author"]})')
            else:
                parts.append(f'- DELETED: "{tc["original_text"]}" (by {tc["author"]})')

    # Reviewer comments
    comments = extracted.get("comments", [])
    if comments:
        parts.append("\n## REVIEWER COMMENTS\n")
        for c in comments:
            parts.append(f"Comment #{c['id']} by {c['author']}:")
            if c.get("anchor_text"):
                parts.append(f'  Anchor: "{c["anchor_text"]}"')
            parts.append(f"  Comment: {c['comment_body']}")
            parts.append("")

    if not tracked and not comments:
        parts.append(
            '\n[No tracked changes or comments found. '
            'Return {"edits": [], "flagged_comments": []}]'
        )

    return "\n".join(parts)


def _call_claude(prompt: str, model: str) -> dict:
    client = anthropic.Anthropic()
    last_error = None

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip markdown code fences (handles ```json, ```JSON, ``` etc.)
            text = re.sub(r'^```[a-zA-Z]*\n', '', text)
            text = re.sub(r'\n```\s*$', '', text)
            text = text.strip()
            return json.loads(text)

        except (anthropic.RateLimitError, anthropic.APIError) as e:
            wait = 2 ** (attempt + 1)
            print(f"  [API error] {e}. Retrying in {wait}s...")
            time.sleep(wait)
            last_error = e
        except json.JSONDecodeError as e:
            wait = 2 ** (attempt + 1)
            print(f"  [parse error] Could not parse Claude response as JSON: {e}. Retrying in {wait}s...")
            time.sleep(wait)
            last_error = e

    raise RuntimeError(f"Claude API failed after 3 attempts: {last_error}")


def revise_with_claude(extracted: dict, model: str = DEFAULT_MODEL) -> dict:
    """
    Main entry point. Returns {"edits": [...], "flagged_comments": [...]}.
    """
    prompt = _build_prompt(extracted)
    estimated_tokens = len(prompt) // 4
    print(f"  Estimated input tokens: ~{estimated_tokens:,}")

    if estimated_tokens > CHUNK_TOKEN_THRESHOLD:
        print("  Document is large — processing in single call (may approach context limits).")

    return _call_claude(prompt, model)
