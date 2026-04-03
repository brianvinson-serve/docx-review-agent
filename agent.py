"""
docx-review-agent: Accept tracked changes and resolve reviewer comments in .docx files.
Uses Claude to make targeted text edits while preserving all document formatting.

Usage:
    python agent.py path/to/document.docx
    python agent.py path/to/document.docx --dry-run
    python agent.py path/to/document.docx --model claude-opus-4-6 --output revised.docx

Configuration (via .env or environment):
    ANTHROPIC_API_KEY  — required (unless --dry-run)
    DOCX_AGENT_MODEL   — optional, default: claude-sonnet-4-6
"""
import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from extract import extract_document
from feasibility import analyze
from revise import revise_with_claude, _build_prompt
from rebuild import rebuild_document


def _check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("Copy .env.example to .env and add your API key, or set the environment variable.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Accept tracked changes and resolve reviewer comments using Claude."
    )
    parser.add_argument("docx_path", help="Path to input .docx file")
    parser.add_argument(
        "--model",
        help="Claude model override (default: DOCX_AGENT_MODEL env var or claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: {stem}_revised.docx in same directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extract + feasibility only; print Claude payload; no API call, no output file",
    )
    args = parser.parse_args()

    input_path = Path(args.docx_path)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)
    if input_path.suffix.lower() != ".docx":
        print(f"Error: Not a .docx file: {input_path}")
        sys.exit(1)

    if not args.dry_run:
        _check_api_key()

    output_path = (
        Path(args.output)
        if args.output
        else input_path.parent / f"{input_path.stem}_revised.docx"
    )
    model = args.model or os.environ.get("DOCX_AGENT_MODEL", "claude-sonnet-4-6")

    print(f"\ndocx-review-agent")
    print(f"Input:  {input_path}")
    if not args.dry_run:
        print(f"Output: {output_path}")
    print(f"Model:  {model}")
    print("-" * 60)

    # Stage 1: Extract
    print("\nStage 1: Extracting content...")
    extracted = extract_document(input_path)
    n_changes = len(extracted["tracked_changes"])
    n_comments = len(extracted["comments"])
    print(f"  {n_changes} tracked changes, {n_comments} comments")

    # Stage 2: Feasibility + go/no-go
    print("\nStage 2: Pre-flight analysis...")
    proceed = analyze(extracted, input_path)
    if not proceed:
        print("Aborted.")
        sys.exit(0)

    # Dry run: print payload and stop
    if args.dry_run:
        print("\n[dry-run] Claude would receive:\n")
        print(_build_prompt(extracted))
        sys.exit(0)

    # Stage 3: Revise with Claude
    print("\nStage 3: Sending to Claude for revision...")
    edits_dict = revise_with_claude(extracted, model=model)
    n_edits = len(edits_dict.get("edits", []))
    n_flagged = len(edits_dict.get("flagged_comments", []))
    print(f"  {n_edits} edits, {n_flagged} flagged comments")

    # Stage 4: Rebuild
    print("\nStage 4: Rebuilding document...")
    stats = rebuild_document(input_path, edits_dict, output_path)

    if not output_path.exists():
        print("Error: Output file was not created.")
        sys.exit(1)

    in_size = input_path.stat().st_size
    out_size = output_path.stat().st_size
    ratio = out_size / in_size if in_size > 0 else 0

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Done. Output: {output_path}")
    print(f"Size: {in_size:,} → {out_size:,} bytes ({ratio:.0%})")
    print(f"Tracked changes accepted: {n_changes}")
    print(f"Comment edits applied:    {stats['applied']}")
    if stats["misses"] > 0:
        print(f"Edit misses (review manually): {stats['misses']}")

    if edits_dict.get("flagged_comments"):
        print(f"\nFlagged for human review ({n_flagged}):")
        for fc in edits_dict["flagged_comments"]:
            print(f"\n  [{fc.get('author', 'Unknown')}] on: \"{fc.get('anchor', '')}\"")
            print(f"    Comment: {fc.get('comment', '')}")
            print(f"    Reason:  {fc.get('reason', '')}")

    if ratio < 0.3:
        print("\n[warning] Output is significantly smaller than input. Review carefully.")

    print()


if __name__ == "__main__":
    main()
