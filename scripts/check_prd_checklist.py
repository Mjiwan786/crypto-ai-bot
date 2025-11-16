#!/usr/bin/env python3
"""
PRD-001 Checklist Enforcement Script

Validates that all items in docs/PRD-001-CHECKLIST.md are checked off.
Used in CI/CD to prevent merging incomplete work.

Exit codes:
  0 - All items checked, safe to merge
  1 - Unchecked items found, block merge
  2 - File not found or parse error

Usage:
  python scripts/check_prd_checklist.py
"""

import re
import sys
from pathlib import Path


def find_checklist_file() -> Path:
    """Find the PRD checklist file."""
    # Try from repo root
    repo_root = Path(__file__).parent.parent
    checklist_path = repo_root / "docs" / "PRD-001-CHECKLIST.md"

    if not checklist_path.exists():
        print(f"[X] ERROR: Checklist not found at {checklist_path}")
        sys.exit(2)

    return checklist_path


def parse_checklist(file_path: Path) -> dict:
    """
    Parse checklist and count checked/unchecked items.

    Returns:
        dict with keys: total, checked, unchecked, unchecked_items
    """
    content = file_path.read_text(encoding="utf-8")

    # Patterns for checklist items
    checked_pattern = re.compile(r"^- \[x\]", re.MULTILINE | re.IGNORECASE)
    unchecked_pattern = re.compile(r"^- \[ \]", re.MULTILINE)

    # Find all matches
    checked_items = checked_pattern.findall(content)
    unchecked_matches = list(unchecked_pattern.finditer(content))

    # Extract unchecked item details
    unchecked_items = []
    lines = content.split("\n")

    for match in unchecked_matches:
        # Find line number
        line_num = content[:match.start()].count("\n") + 1

        # Get the full line
        if line_num <= len(lines):
            full_line = lines[line_num - 1].strip()
            unchecked_items.append({
                "line": line_num,
                "text": full_line
            })

    total_checked = len(checked_items)
    total_unchecked = len(unchecked_matches)
    total_items = total_checked + total_unchecked

    return {
        "total": total_items,
        "checked": total_checked,
        "unchecked": total_unchecked,
        "unchecked_items": unchecked_items
    }


def main():
    """Main execution."""
    print("[*] PRD-001 Checklist Validation")
    print("=" * 60)

    # Find checklist
    checklist_path = find_checklist_file()
    print(f"[>] Checklist: {checklist_path}")
    print()

    # Parse checklist
    try:
        results = parse_checklist(checklist_path)
    except Exception as e:
        print(f"[X] ERROR: Failed to parse checklist: {e}")
        sys.exit(2)

    # Report results
    total = results["total"]
    checked = results["checked"]
    unchecked = results["unchecked"]

    print(f"Total items:     {total}")
    print(f"Checked [x]:     {checked}")
    print(f"Unchecked [ ]:   {unchecked}")
    print()

    if total == 0:
        print("[!] WARNING: No checklist items found!")
        print("    This might indicate a parsing error.")
        sys.exit(2)

    # Calculate completion
    completion_pct = (checked / total * 100) if total > 0 else 0
    print(f"Completion: {completion_pct:.1f}%")
    print()

    # Check if all items are checked
    if unchecked == 0:
        print("[+] SUCCESS: All checklist items complete!")
        print("    Safe to merge/deploy.")
        sys.exit(0)
    else:
        print(f"[-] FAILURE: {unchecked} unchecked item(s) found!")
        print("    Cannot merge until all items are checked off.")
        print()

        # Show first 10 unchecked items
        print("Unchecked items (first 10):")
        print("-" * 60)

        for i, item in enumerate(results["unchecked_items"][:10], 1):
            line_num = item["line"]
            text = item["text"]

            # Truncate long lines
            if len(text) > 70:
                text = text[:67] + "..."

            print(f"  {i}. Line {line_num}: {text}")

        if unchecked > 10:
            print(f"  ... and {unchecked - 10} more")

        print()
        print("[i] TIP: Check off items as you complete them:")
        print("    - [ ] Incomplete item")
        print("    - [x] Completed item")

        sys.exit(1)


if __name__ == "__main__":
    main()
