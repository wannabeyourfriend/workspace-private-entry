#!/usr/bin/env python3
"""
Security scanner: Detect exposed API keys in the workspace.
Compares findings against known .env file values to identify untracked credentials.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple
import argparse


# API key patterns (comprehensive)
PATTERNS = {
    "openai_api_key": r"sk-[a-zA-Z0-9]{20,}",
    "openai_org_id": r"org-[a-zA-Z0-9]{20,}",
    "anthropic_api_key": r"claude-[a-zA-Z0-9]{32,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "aws_secret_key": r"aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}",
    "github_token": r"ghp_[a-zA-Z0-9]{36,255}",
    "github_pat": r"github_pat_[a-zA-Z0-9]{22,255}",
    "stripe_sk": r"sk_live_[a-zA-Z0-9]{20,}",
    "stripe_pk": r"pk_live_[a-zA-Z0-9]{20,}",
    "google_api_key": r"AIza[0-9A-Za-z\-_]{35}",
    "private_key": r"-----BEGIN (RSA|DSA|EC) PRIVATE KEY-----",
    "password_assignment": r"(?:password|passwd|pwd)\s*=\s*['\"]([^'\"]+)['\"]",
    "generic_api_key": r"api[_-]?key\s*[=:]\s*['\"]([A-Za-z0-9\-_]{20,})['\"]",
}

# Files/patterns to exclude
EXCLUDE_PATTERNS = {
    ".git",
    ".gitignore",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "*.pyc",
    "*.so",
    "*.o",
    ".venv",
    "venv",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.pdf",
}


def load_env_values(env_file: str = ".env") -> Set[str]:
    """Load all values from .env files to avoid false positives."""
    env_values = set()
    for env_path in [".env", ".env.local", ".env.llmapi", ".env.openai"]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            _, value = line.split("=", 1)
                            value = value.strip().strip("'\"")
                            if value and len(value) > 10:  # Only track meaningful values
                                env_values.add(value)
            except Exception as e:
                print(f"[!] Error reading {env_path}: {e}", file=sys.stderr)
    return env_values


def should_exclude(file_path: Path) -> bool:
    """Check if file should be excluded from scanning."""
    path_str = str(file_path)

    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*."):
            if file_path.name.endswith(pattern[1:]):
                return True
        elif pattern in path_str:
            return True

    # Skip binary files
    if file_path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz"}:
        return True

    return False


def scan_file(file_path: Path, patterns: Dict[str, str], env_values: Set[str]) -> List[Tuple[str, str, int]]:
    """
    Scan a single file for API key patterns.
    Returns list of (pattern_type, matched_value, line_number).
    """
    findings = []

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                for pattern_type, pattern in patterns.items():
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        key = match.group(0)
                        # Skip if this value is already in .env (likely legitimate)
                        if key not in env_values and len(key) > 10:
                            findings.append((pattern_type, key, line_num))
    except Exception as e:
        print(f"[!] Error scanning {file_path}: {e}", file=sys.stderr)

    return findings


def scan_directory(root_dir: str = ".", verbose: bool = False) -> Dict[str, List]:
    """
    Recursively scan directory for exposed API keys.
    Returns dict mapping file paths to findings.
    """
    root_path = Path(root_dir).resolve()
    env_values = load_env_values()
    results = {}
    files_scanned = 0

    print(f"[*] Scanning {root_path}")
    print(f"[*] Loaded {len(env_values)} values from .env files to exclude")
    print(f"[*] Using {len(PATTERNS)} pattern detectors\n")

    try:
        for file_path in root_path.rglob("*"):
            if not file_path.is_file():
                continue

            if should_exclude(file_path):
                if verbose:
                    print(f"[+] Skipping: {file_path.relative_to(root_path)}")
                continue

            files_scanned += 1
            findings = scan_file(file_path, PATTERNS, env_values)

            if findings:
                rel_path = str(file_path.relative_to(root_path))
                results[rel_path] = findings

                if verbose:
                    print(f"[!] FOUND in {rel_path}:")
                    for pattern_type, key, line_num in findings:
                        # Mask the key for security
                        masked = key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else "*" * len(key)
                        print(f"    Line {line_num}: [{pattern_type}] {masked}")

    except PermissionError as e:
        print(f"[!] Permission denied: {e}", file=sys.stderr)

    print(f"\n[*] Scanned {files_scanned} files")
    print(f"[!] Found {len(results)} files with potential exposed keys\n")

    return results


def print_report(results: Dict[str, List]) -> None:
    """Print a formatted security report."""
    if not results:
        print("[✓] No exposed API keys detected outside of .env files!")
        return

    print("=" * 70)
    print("SECURITY REPORT: EXPOSED API KEYS DETECTED")
    print("=" * 70)
    print()

    for file_path in sorted(results.keys()):
        findings = results[file_path]
        print(f"FILE: {file_path}")
        print("-" * 70)

        for pattern_type, key, line_num in findings:
            # Mask the key for security
            masked = key[:4] + "*" * max(0, len(key) - 8) + (key[-4:] if len(key) > 8 else "")
            print(f"  Line {line_num}: [{pattern_type}]")
            print(f"    Value: {masked} (length: {len(key)})")
        print()

    print("=" * 70)
    print("RECOMMENDATIONS:")
    print("  1. Move exposed keys to .env files")
    print("  2. Regenerate keys if committed to git")
    print("  3. Add patterns to .gitignore to prevent future leaks")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Scan for exposed API keys in workspace, excluding values already in .env"
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Directory to scan (default: current directory)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output during scanning"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    results = scan_directory(args.dir, args.verbose)

    if args.json:
        import json
        print(json.dumps(results, indent=2))
    else:
        print_report(results)

    # Exit with non-zero if keys found
    return 1 if results else 0


if __name__ == "__main__":
    sys.exit(main())
