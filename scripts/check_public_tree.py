#!/usr/bin/env python3
"""A small public-tree tripwire, not a substitute for a real secret review."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "provider token": re.compile(r"\bsk-(?:or-v1-|proj-)?[A-Za-z0-9_-]{32,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "personal deployment path": re.compile(r"/Users/[A-Za-z0-9_.-]+/(?:Desktop|\.omp|\.pi|\.ssh)(?:/|\b)"),
}
PRIVATE_NETWORK = re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")


def main():
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            cwd=ROOT, capture_output=True, check=True)
    paths = sorted(set(p for p in result.stdout.decode().split("\0") if p))
    failures = []
    for relative in paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.is_symlink():
            failures.append((relative, "symlink in public tree"))
            continue
        name = path.name
        if (name.startswith(".env") or name in {"mcp.json", ".mcp.json", "id_rsa", "id_ed25519"}
                or path.suffix in {".pem", ".key"} or ".backup-" in name):
            failures.append((relative, "private/generated filename"))
        raw = path.read_bytes()
        if b"\x00" in raw:
            failures.append((relative, "unexpected binary file"))
            continue
        text = raw.decode("utf-8")
        for label, pattern in RULES.items():
            if pattern.search(text):
                failures.append((relative, label))
        # Private-IP examples are allowed in unit tests for network boundary checks,
        # not in application defaults, documentation or installation configuration.
        if not relative.startswith("tests/") and PRIVATE_NETWORK.search(text):
            failures.append((relative, "private network address outside a test fixture"))
    if failures:
        for path, reason in failures:
            print(f"FAIL: {path}: {reason}")  # Never echo the potential secret itself.
        return 1
    print(f"Public-tree checks passed ({len(paths)} files). Review the diff/history too; this is not a comprehensive secret scanner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
